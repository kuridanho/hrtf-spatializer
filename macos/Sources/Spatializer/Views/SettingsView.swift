import SwiftUI

struct SettingsView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        Form {
            Section("Status") {
                LabeledContent("State", value: state.statusLine)
                if state.isRunning {
                    LabeledContent(
                        "Sample rate",
                        value: state.sampleRate > 0
                            ? "\(Int(state.sampleRate)) Hz"
                            : "—"
                    )
                    LabeledContent(
                        "Buffer",
                        value: state.bufferFrames > 0
                            ? "\(state.bufferFrames) frames"
                            : "—"
                    )
                    LabeledContent(
                        "Estimated latency",
                        value: String(format: "%.1f ms", state.latencyMilliseconds)
                    )
                    LabeledContent("HRIR partitions", value: "\(state.partitions)")
                }

                if let error = state.lastError {
                    Text(error)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }

                HStack {
                    Button(state.isRunning ? "Stop" : "Start") {
                        if state.isRunning {
                            state.stop()
                        } else {
                            state.start()
                        }
                    }
                    .disabled(state.isStarting)

                    Button("Apply & Restart") {
                        state.restart()
                    }
                    .disabled(!state.isRunning || state.isStarting)

                    Spacer()

                    Button("Privacy Settings…") {
                        state.openPrivacySettings()
                    }
                }
            }

            Section("Output") {
                Picker(
                    "Device",
                    selection: Binding(
                        get: { state.selectedOutputUID ?? "" },
                        set: { state.selectOutput($0) }
                    )
                ) {
                    ForEach(state.devices) { device in
                        Text(device.displayName).tag(device.uid)
                    }
                }

                if state.selectedOutput?.isBluetooth == true {
                    Text(
                        "Bluetooth output is supported, but its own transport latency "
                            + "is not part of the low-latency target."
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }

                HStack {
                    Text("\(state.devices.count) output device(s)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Button("Refresh") {
                        state.refreshDevices()
                    }
                }
            }

            Section("HRTF Dataset") {
                Text(state.datasetURL?.path ?? "No dataset selected")
                    .font(.caption)
                    .textSelection(.enabled)
                    .lineLimit(2)

                HStack {
                    Button("Choose Folder…") {
                        state.chooseDataset()
                    }
                    Button("Rescan") {
                        state.refreshDatasets()
                    }
                    Spacer()
                    if state.isScanningDatasets {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text("\(state.datasets.count) detected")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Latency") {
                Picker(
                    "Block size",
                    selection: Binding(
                        get: { state.blockSize },
                        set: { state.setBlockSize($0) }
                    )
                ) {
                    ForEach(HRTFLoader.allowedBlockSizes, id: \.self) { size in
                        let rate = state.sampleRate > 0 ? state.sampleRate : 48_000
                        Text(
                            "\(size) samples  (\(String(format: "%.1f", Double(size) / rate * 1000)) ms)"
                        )
                        .tag(size)
                    }
                }

                Text(
                    "Smaller blocks reduce latency but require more CPU. "
                        + "64 or 128 samples are recommended for wired output."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Section("Level") {
                Toggle(
                    "Bypass HRTF",
                    isOn: Binding(
                        get: { state.bypass },
                        set: { state.setBypass($0) }
                    )
                )

                HStack {
                    Text("Volume")
                    Slider(
                        value: Binding(
                            get: { state.volume },
                            set: { state.setVolume($0) }
                        ),
                        in: 0.0...1.5
                    )
                    Text("\(Int(state.volume * 100))%")
                        .monospacedDigit()
                        .frame(width: 44, alignment: .trailing)
                }

                HStack(spacing: 12) {
                    Text("L")
                        .font(.caption)
                    ProgressView(value: Double(state.meterLeft), total: 1.0)
                    Text("R")
                        .font(.caption)
                    ProgressView(value: Double(state.meterRight), total: 1.0)
                }
            }

            Section("Startup") {
                Toggle(
                    "Launch at Login",
                    isOn: Binding(
                        get: { state.launchAtLogin },
                        set: { state.setLaunchAtLogin($0) }
                    )
                )
                Toggle(
                    "Start audio when Spatializer launches",
                    isOn: Binding(
                        get: { state.autoStart },
                        set: { state.setAutoStart($0) }
                    )
                )
            }
        }
        .formStyle(.grouped)
        .padding(20)
        .frame(width: 560)
        .onAppear {
            state.refreshDevices()
            state.refreshDatasets()
        }
    }
}
