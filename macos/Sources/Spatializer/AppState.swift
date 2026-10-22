import AppKit
import Foundation
import Observation
import ServiceManagement

@MainActor
@Observable
final class AppState {
    @ObservationIgnored private let engine = AudioEngine()
    @ObservationIgnored private let defaults = UserDefaults.standard
    @ObservationIgnored private var meterTimer: Timer?
    @ObservationIgnored private var deviceTimer: Timer?
    @ObservationIgnored private var meterLogTick = 0
    @ObservationIgnored private var startGeneration = 0
    @ObservationIgnored private var pendingAutoStart = false
    @ObservationIgnored private var activityToken: NSObjectProtocol?
    @ObservationIgnored private var wakeObserver: NSObjectProtocol?

    private enum Key {
        static let outputUID = "outputUID"
        static let datasetPath = "datasetPath"
        static let datasetRoot = "datasetRoot"
        static let blockSize = "blockSize"
        static let volume = "volume"
        static let bypass = "bypass"
        static let autoStart = "autoStart"
    }

    var devices: [AudioOutputDevice] = []
    var datasets: [URL] = []
    var datasetRoot: URL = HRTFLoader.defaultDatasetRoot()
    var datasetURL: URL? = nil
    var selectedOutputUID: String? = nil
    var blockSize: Int = 128
    var volume: Double = 1.0
    var bypass: Bool = false
    var autoStart: Bool = false
    var launchAtLogin: Bool = false

    var isRunning = false
    var isStarting = false
    var isScanningDatasets = false
    var statusText = "Stopped"
    var lastError: String?
    var meterLeft: Float = 0
    var meterRight: Float = 0
    var latencyMilliseconds: Double = 0
    var sampleRate: Double = 0
    var bufferFrames: UInt32 = 0
    var partitions: Int = 0

    var selectedOutput: AudioOutputDevice? {
        guard let selectedOutputUID else { return nil }
        return devices.first { $0.uid == selectedOutputUID }
    }

    var menuIcon: String {
        if lastError != nil { return "exclamationmark.triangle" }
        if bypass { return "headphones.slash" }
        return isRunning ? "headphones.circle.fill" : "headphones"
    }

    var statusLine: String {
        if let lastError {
            return lastError
        }
        if isStarting {
            return "Starting…"
        }
        return statusText
    }

    init() {
        let savedRoot = defaults.string(forKey: Key.datasetRoot)
        datasetRoot = savedRoot.map { URL(fileURLWithPath: $0) }
            ?? HRTFLoader.defaultDatasetRoot()
        datasets = []

        let savedDataset = defaults.string(forKey: Key.datasetPath)
        datasetURL = savedDataset.map { URL(fileURLWithPath: $0) }

        devices = AudioDeviceManager.outputDevices()
        let savedOutput = defaults.string(forKey: Key.outputUID)
        if let savedOutput, devices.contains(where: { $0.uid == savedOutput }) {
            selectedOutputUID = savedOutput
        } else if let defaultUID = AudioDeviceManager.defaultOutputUID(),
                  devices.contains(where: { $0.uid == defaultUID })
        {
            selectedOutputUID = defaultUID
        } else {
            selectedOutputUID = devices.first?.uid
        }

        let savedBlock = defaults.integer(forKey: Key.blockSize)
        blockSize = HRTFLoader.allowedBlockSizes.contains(savedBlock) ? savedBlock : 128

        let savedVolume = defaults.object(forKey: Key.volume) as? Double
        volume = min(max(savedVolume ?? 1.0, 0.0), 1.5)
        bypass = defaults.bool(forKey: Key.bypass)
        autoStart = defaults.bool(forKey: Key.autoStart)
        pendingAutoStart = autoStart
        launchAtLogin = SMAppService.mainApp.status == .enabled

        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) {
            [weak self] _ in
            Task { @MainActor in self?.updateMeters() }
        }
        deviceTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) {
            [weak self] _ in
            Task { @MainActor in self?.refreshDevices() }
        }
        if let meterTimer { RunLoop.main.add(meterTimer, forMode: .common) }
        if let deviceTimer { RunLoop.main.add(deviceTimer, forMode: .common) }

        wakeObserver = NotificationCenter.default.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isRunning else { return }
                AppLog.write("System wake: restarting audio")
                self.restart()
            }
        }

        AppLog.write(
            "AppState init devices=\(devices.count) "
                + "dataset=\(datasetURL?.lastPathComponent ?? "none") "
                + "output=\(selectedOutput?.name ?? "none")"
        )

        // Directory enumeration can be slow on network/FileProvider volumes,
        // so never block app launch on it.
        scheduleDatasetScan(preferred: datasetURL)
    }

    private func scheduleDatasetScan(preferred: URL?) {
        isScanningDatasets = true
        let root = datasetRoot

        DispatchQueue.global(qos: .userInitiated).async {
            let found = HRTFLoader.scanDatasets(root: root)
            DispatchQueue.main.async {
                self.applyDatasets(found, root: root, preferred: preferred)
            }
        }
    }

    private func applyDatasets(_ found: [URL], root: URL, preferred: URL?) {
        datasetRoot = root
        datasets = found
        isScanningDatasets = false

        if let preferred, found.contains(preferred) {
            datasetURL = preferred
        } else if let current = datasetURL, found.contains(current) {
            // keep current
        } else {
            datasetURL = found.first
        }

        if let datasetURL {
            defaults.set(datasetURL.path, forKey: Key.datasetPath)
            defaults.set(datasetRoot.path, forKey: Key.datasetRoot)
        }

        if found.isEmpty,
           root.path != HRTFLoader.defaultDatasetRoot().path
        {
            lastError = "No complete 21-direction HRTF dataset was found in that folder."
        }

        AppLog.write(
            "Datasets scanned root=\(root.path) count=\(found.count) "
                + "selected=\(datasetURL?.lastPathComponent ?? "none")"
        )

        if pendingAutoStart, !isRunning, !isStarting {
            pendingAutoStart = false
            if datasetURL != nil {
                start()
            }
        }
    }

    // ------------------------------------------------------------------
    // Stream
    // ------------------------------------------------------------------

    func start() {
        guard !isRunning, !isStarting else { return }
        guard let datasetURL else {
            lastError = "Select an HRTF dataset first."
            statusText = "No dataset"
            return
        }
        guard let selectedOutputUID else {
            lastError = "Select an output device first."
            statusText = "No output"
            return
        }

        isStarting = true
        lastError = nil
        statusText = "Starting…"
        startGeneration += 1
        let generation = startGeneration
        let engine = self.engine
        let requestedBlockSize = blockSize
        AppLog.write(
            "Starting audio dataset=\(datasetURL.lastPathComponent) "
                + "output=\(selectedOutputUID) block=\(requestedBlockSize)"
        )

        // Core Audio tap creation may wait for a permission prompt.  Keep the
        // menu bar responsive by doing the setup off the main thread.
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try engine.start(
                    datasetURL: datasetURL,
                    outputUID: selectedOutputUID,
                    blockSize: requestedBlockSize
                )
                DispatchQueue.main.async {
                    guard self.startGeneration == generation else { return }
                    engine.setGain(Float(self.volume))
                    engine.setBypass(self.bypass)
                    self.isRunning = true
                    self.isStarting = false
                    self.statusText = "Running"
                    self.beginAudioActivity()
                    self.updateDiagnostics()
                }
            } catch {
                DispatchQueue.main.async {
                    guard self.startGeneration == generation else { return }
                    self.lastError = error.localizedDescription
                    self.statusText = "Error"
                    self.isStarting = false
                    self.isRunning = false
                    self.endAudioActivity()
                    AppLog.write("Audio start failed: \(error.localizedDescription)")
                    engine.stop()
                }
            }
        }
    }

    func stop() {
        guard !isStarting else { return }
        startGeneration += 1
        engine.stop()
        isRunning = false
        statusText = "Stopped"
        endAudioActivity()
        meterLeft = 0
        meterRight = 0
        updateDiagnostics()
    }

    func restart() {
        guard !isStarting else { return }
        guard isRunning else {
            start()
            return
        }
        stop()
        start()
    }

    func setVolume(_ value: Double) {
        volume = min(max(value, 0.0), 1.5)
        engine.setGain(Float(volume))
        defaults.set(volume, forKey: Key.volume)
    }

    func setBypass(_ value: Bool) {
        bypass = value
        engine.setBypass(value)
        defaults.set(value, forKey: Key.bypass)
    }

    func setBlockSize(_ value: Int) {
        guard HRTFLoader.allowedBlockSizes.contains(value) else { return }
        blockSize = value
        defaults.set(value, forKey: Key.blockSize)
        if isRunning {
            restart()
        }
    }

    func selectOutput(_ uid: String) {
        guard devices.contains(where: { $0.uid == uid }) else { return }
        selectedOutputUID = uid
        defaults.set(uid, forKey: Key.outputUID)
        if isRunning {
            restart()
        }
    }

    func selectDataset(_ url: URL) {
        datasetURL = url
        defaults.set(url.path, forKey: Key.datasetPath)
        if isRunning {
            restart()
        }
    }

    func setAutoStart(_ value: Bool) {
        autoStart = value
        defaults.set(value, forKey: Key.autoStart)
    }

    // ------------------------------------------------------------------
    // Devices / datasets
    // ------------------------------------------------------------------

    func refreshDevices() {
        let updated = AudioDeviceManager.outputDevices()
        guard updated != devices else { return }
        devices = updated

        if let selectedOutputUID,
           devices.contains(where: { $0.uid == selectedOutputUID })
        {
            return
        }

        if let defaultUID = AudioDeviceManager.defaultOutputUID(),
           devices.contains(where: { $0.uid == defaultUID })
        {
            selectedOutputUID = defaultUID
        } else {
            selectedOutputUID = devices.first?.uid
        }

        if isRunning {
            stop()
            lastError = "The selected output device disconnected."
            statusText = "Output disconnected"
        }
    }

    func refreshDatasets() {
        scheduleDatasetScan(preferred: datasetURL)
    }

    func chooseDataset() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Choose HRTF Folder"
        panel.message = "Select a folder containing the 21 HRTF WAV files."

        guard panel.runModal() == .OK, let url = panel.url else { return }

        if HRTFLoader.isDataset(url) {
            datasetRoot = url.deletingLastPathComponent()
            selectDataset(url)
            defaults.set(datasetRoot.path, forKey: Key.datasetRoot)
            scheduleDatasetScan(preferred: url)
            return
        }

        datasetRoot = url
        scheduleDatasetScan(preferred: nil)
    }

    // ------------------------------------------------------------------
    // Login item / permissions
    // ------------------------------------------------------------------

    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            if enabled {
                try SMAppService.mainApp.register()
            } else {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            lastError = "Launch at Login: \(error.localizedDescription)"
        }
        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    func openPrivacySettings() {
        let urls = [
            "x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        ]
        for string in urls {
            if let url = URL(string: string), NSWorkspace.shared.open(url) {
                return
            }
        }
    }

    // ------------------------------------------------------------------
    // Live values
    // ------------------------------------------------------------------

    private func beginAudioActivity() {
        guard activityToken == nil else { return }
        activityToken = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .latencyCritical],
            reason: "Real-time HRTF audio processing"
        )
    }

    private func endAudioActivity() {
        if let activityToken {
            ProcessInfo.processInfo.endActivity(activityToken)
            self.activityToken = nil
        }
    }

    private func updateMeters() {
        if isRunning {
            let (left, right) = engine.meters()
            meterLeft = left
            meterRight = right
            updateDiagnostics()

            if defaults.bool(forKey: "DebugMeters") {
                meterLogTick += 1
                if meterLogTick % 10 == 0 {
                    AppLog.write(
                        "meters L=\(String(format: "%.5f", left)) "
                            + "R=\(String(format: "%.5f", right))"
                    )
                }
            }
        } else {
            meterLeft *= 0.8
            meterRight *= 0.8
        }
    }

    private func updateDiagnostics() {
        latencyMilliseconds = engine.latencyMilliseconds
        sampleRate = engine.sampleRate
        bufferFrames = engine.bufferFrames
        partitions = engine.partitions
    }

    deinit {
        meterTimer?.invalidate()
        deviceTimer?.invalidate()
        if let wakeObserver {
            NotificationCenter.default.removeObserver(wakeObserver)
        }
    }
}
