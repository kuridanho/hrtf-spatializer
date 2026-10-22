import CoreAudio
import Foundation

struct AudioOutputDevice: Identifiable, Hashable, Sendable {
    let uid: String
    let name: String
    let sampleRate: Double
    let channels: Int
    let isBluetooth: Bool

    var id: String { uid }

    var displayName: String {
        isBluetooth ? "\(name) (Bluetooth)" : name
    }
}

enum AudioDeviceManager {
    static func outputDevices() -> [AudioOutputDevice] {
        guard let deviceIDs = try? AudioObjectID.deviceList() else { return [] }

        var devices: [AudioOutputDevice] = []
        for deviceID in deviceIDs {
            guard let channels = try? deviceID.outputChannelCount(), channels > 0 else {
                continue
            }
            guard
                let uid = try? deviceID.readDeviceUID(),
                let name = try? deviceID.readDeviceName()
            else {
                continue
            }

            // Never route through the legacy virtual driver or our private aggregate.
            if name.localizedCaseInsensitiveContains("BlackHole")
                || name.localizedCaseInsensitiveContains("Spatializer")
            {
                continue
            }

            let sampleRate = (try? deviceID.readNominalSampleRate()) ?? 0
            let transport = (try? deviceID.readTransportType()) ?? 0
            let isBluetooth = transport == kAudioDeviceTransportTypeBluetooth
                || transport == kAudioDeviceTransportTypeBluetoothLE

            devices.append(
                AudioOutputDevice(
                    uid: uid,
                    name: name,
                    sampleRate: sampleRate,
                    channels: channels,
                    isBluetooth: isBluetooth
                )
            )
        }

        return devices.sorted {
            $0.name.localizedStandardCompare($1.name) == .orderedAscending
        }
    }

    static func defaultOutputUID() -> String? {
        guard let deviceID = try? AudioObjectID.defaultOutputDevice(),
              deviceID.isValid
        else {
            return nil
        }
        return try? deviceID.readDeviceUID()
    }
}
