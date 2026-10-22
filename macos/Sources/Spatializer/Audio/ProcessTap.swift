import AudioToolbox
import CoreAudio
import Foundation

/// A private system-audio tap plus an aggregate device that renders the
/// processed signal to the selected output device.
///
/// The tap is configured with `.mutedWhenTapped`, so while Spatializer is
/// reading the tap the original system output is muted and only the processed
/// signal reaches the headphones.  The app's own audio process is excluded
/// from the tap to avoid feedback.
final class ProcessTap {
    private(set) var tapID: AudioObjectID = .unknown
    private(set) var aggregateID: AudioObjectID = .unknown
    private(set) var tapFormat: AudioStreamBasicDescription?
    private(set) var aggregateOutputFormat: AudioStreamBasicDescription?
    private(set) var bufferFrameSize: UInt32 = 0

    private var ioProcID: AudioDeviceIOProcID?
    private let ioQueue = DispatchQueue(
        label: "com.kuridanho.spatializer.io",
        qos: .userInteractive
    )

    func prepare(outputUID: String, blockSize: UInt32) throws {
        stop()

        AppLog.write("ProcessTap: resolving own process")
        let ownPID = ProcessInfo.processInfo.processIdentifier
        let ownProcess = try AudioObjectID.translatePIDToProcessObject(pid: ownPID)
        AppLog.write("ProcessTap: own process=\(ownProcess)")

        let description = CATapDescription(
            stereoGlobalTapButExcludeProcesses: [ownProcess]
        )
        description.uuid = UUID()
        description.muteBehavior = CATapMuteBehavior(rawValue: 2) ?? .unmuted
        description.isPrivate = true

        var newTapID = AudioObjectID.unknown
        AppLog.write("ProcessTap: creating system tap")
        var status = AudioHardwareCreateProcessTap(description, &newTapID)
        AppLog.write("ProcessTap: tap status=\(status) id=\(newTapID)")
        guard status == noErr, newTapID.isValid else {
            throw SpatializerAudioError(
                "System audio tap could not be created (\(status)). "
                    + "Grant Spatializer permission in System Settings → Privacy & Security."
            )
        }
        tapID = newTapID

        do {
            let format = try newTapID.readAudioTapFormat()
            guard format.mFormatID == kAudioFormatLinearPCM,
                  format.mChannelsPerFrame == 2,
                  format.mBitsPerChannel == 32,
                  format.mFormatFlags & kAudioFormatFlagIsFloat != 0
            else {
                throw SpatializerAudioError(
                    "Unsupported system audio format: \(format.mFormatID), "
                        + "\(format.mChannelsPerFrame) channels"
                )
            }
            tapFormat = format
            AppLog.write(
                "ProcessTap: format rate=\(format.mSampleRate) "
                    + "channels=\(format.mChannelsPerFrame) flags=\(format.mFormatFlags)"
            )

            let aggregateUID = UUID().uuidString
            let aggregateDescription: [String: Any] = [
                kAudioAggregateDeviceNameKey: "Spatializer Tap",
                kAudioAggregateDeviceUIDKey: aggregateUID,
                kAudioAggregateDeviceMainSubDeviceKey: outputUID,
                kAudioAggregateDeviceIsPrivateKey: true,
                kAudioAggregateDeviceIsStackedKey: false,
                kAudioAggregateDeviceSubDeviceListKey: [
                    [kAudioSubDeviceUIDKey: outputUID]
                ],
                kAudioAggregateDeviceTapListKey: [
                    [
                        kAudioSubTapDriftCompensationKey: true,
                        kAudioSubTapUIDKey: description.uuid.uuidString,
                    ]
                ],
            ]

            var newAggregateID = AudioObjectID.unknown
            AppLog.write("ProcessTap: creating aggregate")
            status = AudioHardwareCreateAggregateDevice(
                aggregateDescription as CFDictionary,
                &newAggregateID
            )
            guard status == noErr, newAggregateID.isValid else {
                throw SpatializerAudioError(
                    "Could not create the Spatializer output device (\(status))"
                )
            }
            aggregateID = newAggregateID
            AppLog.write("ProcessTap: aggregate=\(newAggregateID)")

            // The requested block size is also the IOProc buffer size.  This
            // is where the low-latency target is set.
            try aggregateID.setBufferFrameSize(blockSize)
            bufferFrameSize = (try? aggregateID.readBufferFrameSize()) ?? blockSize
            AppLog.write("ProcessTap: buffer=\(bufferFrameSize)")

            aggregateOutputFormat = try? aggregateID.firstStreamFormat(
                scope: kAudioObjectPropertyScopeOutput
            )
        } catch {
            stop()
            throw error
        }
    }

    func start(ioBlock: @escaping AudioDeviceIOBlock) throws {
        guard aggregateID.isValid else {
            throw SpatializerAudioError("Audio tap is not prepared")
        }

        var status = AudioDeviceCreateIOProcIDWithBlock(
            &ioProcID,
            aggregateID,
            ioQueue,
            ioBlock
        )
        guard status == noErr, ioProcID != nil else {
            throw SpatializerAudioError("Could not create audio I/O proc (\(status))")
        }

        AppLog.write("ProcessTap: starting device")
        status = AudioDeviceStart(aggregateID, ioProcID)
        AppLog.write("ProcessTap: AudioDeviceStart status=\(status)")
        guard status == noErr else {
            if let ioProcID {
                AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
                self.ioProcID = nil
            }
            throw SpatializerAudioError("Could not start audio device (\(status))")
        }
    }

    func stop() {
        if aggregateID.isValid {
            if let ioProcID {
                _ = AudioDeviceStop(aggregateID, ioProcID)
                _ = AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
                self.ioProcID = nil
            }
            _ = AudioHardwareDestroyAggregateDevice(aggregateID)
            aggregateID = .unknown
        }

        if tapID.isValid {
            _ = AudioHardwareDestroyProcessTap(tapID)
            tapID = .unknown
        }

        tapFormat = nil
        aggregateOutputFormat = nil
        bufferFrameSize = 0
    }

    deinit {
        stop()
    }
}
