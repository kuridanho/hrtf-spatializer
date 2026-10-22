import AppKit
import SwiftUI

struct MenuContent: View {
    @Environment(AppState.self) private var state
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(state.statusLine)
            .disabled(true)

        if state.isRunning || state.latencyMilliseconds > 0 {
            Text(latencyText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .disabled(true)
        }

        Divider()

        Button(state.isRunning ? "Stop" : "Start") {
            if state.isRunning {
                state.stop()
            } else {
                state.start()
            }
        }
        .disabled(state.isStarting)

        Toggle(
            "Bypass",
            isOn: Binding(
                get: { state.bypass },
                set: { state.setBypass($0) }
            )
        )

        Menu("Volume") {
            ForEach([0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5], id: \.self) { value in
                Button {
                    state.setVolume(value)
                } label: {
                    if abs(state.volume - value) < 0.001 {
                        Label("\(Int(value * 100))%", systemImage: "checkmark")
                    } else {
                        Text("\(Int(value * 100))%")
                    }
                }
            }
        }

        Menu("Output Device") {
            ForEach(state.devices) { device in
                Button {
                    state.selectOutput(device.uid)
                } label: {
                    if state.selectedOutputUID == device.uid {
                        Label(device.displayName, systemImage: "checkmark")
                    } else {
                        Text(device.displayName)
                    }
                }
            }
        }

        Menu("HRTF Dataset") {
            ForEach(state.datasets, id: \.self) { url in
                Button {
                    state.selectDataset(url)
                } label: {
                    if state.datasetURL == url {
                        Label(url.lastPathComponent, systemImage: "checkmark")
                    } else {
                        Text(url.lastPathComponent)
                    }
                }
            }
            if state.datasets.isEmpty {
                Text("No datasets found")
                    .disabled(true)
            }
            Divider()
            Button("Choose Folder…") {
                state.chooseDataset()
            }
            Button("Rescan") {
                state.refreshDatasets()
            }
        }

        Menu("Latency") {
            ForEach(HRTFLoader.allowedBlockSizes, id: \.self) { size in
                Button {
                    state.setBlockSize(size)
                } label: {
                    let rate = state.sampleRate > 0 ? state.sampleRate : 48_000
                    let label = "\(size) samples (\(String(format: "%.1f", Double(size) / rate * 1000)) ms)"
                    if state.blockSize == size {
                        Label(label, systemImage: "checkmark")
                    } else {
                        Text(label)
                    }
                }
            }
        }

        Divider()

        Button("Settings…") {
            openWindow(id: "settings")
            NSApp.activate(ignoringOtherApps: true)
        }

        Button("Open Privacy Settings…") {
            state.openPrivacySettings()
        }

        Divider()

        Button("Quit Spatializer") {
            NSApplication.shared.terminate(nil)
        }
    }

    private var latencyText: String {
        if state.latencyMilliseconds > 0 {
            return String(format: "Estimated latency: %.1f ms", state.latencyMilliseconds)
        }
        return "Latency: —"
    }
}
