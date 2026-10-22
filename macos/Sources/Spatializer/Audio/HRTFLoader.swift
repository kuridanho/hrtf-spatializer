import AVFoundation
import Foundation

struct HRIRPosition: Sendable {
    let stem: String
    let label: String
    let leftGain: Float
    let rightGain: Float
}

struct HRTFDataset: Sendable {
    let directory: URL
    let sampleRate: Double
    let hrirLength: Int
    let directions: Int
    let hrirs: [Float]      // (directions, hrirLength, 2) interleaved
    let panCoefs: [Float]   // (directions, 2)

    var name: String { directory.lastPathComponent }
}

enum HRTFLoader {
    static let positions: [HRIRPosition] = [
        HRIRPosition(stem: "100_0", label: "L100", leftGain: 1.00, rightGain: 0.00),
        HRIRPosition(stem: "0_100", label: "R100", leftGain: 0.00, rightGain: 1.00),
        HRIRPosition(stem: "10_0", label: "L10", leftGain: 0.55, rightGain: 0.45),
        HRIRPosition(stem: "0_10", label: "R10", leftGain: 0.45, rightGain: 0.55),
        HRIRPosition(stem: "20_0", label: "L20", leftGain: 0.60, rightGain: 0.40),
        HRIRPosition(stem: "0_20", label: "R20", leftGain: 0.40, rightGain: 0.60),
        HRIRPosition(stem: "30_0", label: "L30", leftGain: 0.65, rightGain: 0.35),
        HRIRPosition(stem: "0_30", label: "R30", leftGain: 0.35, rightGain: 0.65),
        HRIRPosition(stem: "40_0", label: "L40", leftGain: 0.70, rightGain: 0.30),
        HRIRPosition(stem: "0_40", label: "R40", leftGain: 0.30, rightGain: 0.70),
        HRIRPosition(stem: "50_0", label: "L50", leftGain: 0.75, rightGain: 0.25),
        HRIRPosition(stem: "0_50", label: "R50", leftGain: 0.25, rightGain: 0.75),
        HRIRPosition(stem: "60_0", label: "L60", leftGain: 0.80, rightGain: 0.20),
        HRIRPosition(stem: "0_60", label: "R60", leftGain: 0.20, rightGain: 0.80),
        HRIRPosition(stem: "70_0", label: "L70", leftGain: 0.85, rightGain: 0.15),
        HRIRPosition(stem: "0_70", label: "R70", leftGain: 0.15, rightGain: 0.85),
        HRIRPosition(stem: "80_0", label: "L80", leftGain: 0.90, rightGain: 0.10),
        HRIRPosition(stem: "0_80", label: "R80", leftGain: 0.10, rightGain: 0.90),
        HRIRPosition(stem: "90_0", label: "L90", leftGain: 0.95, rightGain: 0.05),
        HRIRPosition(stem: "0_90", label: "R90", leftGain: 0.05, rightGain: 0.95),
        HRIRPosition(stem: "0_0", label: "Center", leftGain: 0.50, rightGain: 0.50),
    ]

    static let allowedBlockSizes = [64, 128, 256, 512]

    static func defaultDatasetRoot() -> URL {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        let root = base.appendingPathComponent("Spatializer/HRTF", isDirectory: true)
        try? FileManager.default.createDirectory(
            at: root,
            withIntermediateDirectories: true
        )
        return root
    }

    static func isDataset(_ directory: URL) -> Bool {
        positions.allSatisfy { position in
            FileManager.default.fileExists(
                atPath: directory.appendingPathComponent("\(position.stem).wav").path
            )
        }
    }

    static func scanDatasets(root: URL) -> [URL] {
        let manager = FileManager.default
        var results: [URL] = []

        if isDataset(root) {
            results.append(root)
        } else if let children = try? manager.contentsOfDirectory(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) {
            for child in children {
                var isDirectory: ObjCBool = false
                guard manager.fileExists(atPath: child.path, isDirectory: &isDirectory),
                      isDirectory.boolValue,
                      isDataset(child)
                else {
                    continue
                }
                results.append(child)
            }
        }

        return results.sorted {
            $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent)
                == .orderedAscending
        }
    }

    static func load(directory: URL, targetSampleRate: Double) throws -> HRTFDataset {
        guard targetSampleRate > 0 else {
            throw SpatializerAudioError("Invalid target sample rate")
        }
        guard isDataset(directory) else {
            throw SpatializerAudioError(
                "\(directory.lastPathComponent) is not a complete 21-direction HRTF dataset"
            )
        }

        var loaded: [(left: [Float], right: [Float])] = []
        var maxLength = 0

        for position in positions {
            let primary = directory.appendingPathComponent("\(position.stem).wav")
            var take = try readTake(url: primary)
            let alternate = directory.appendingPathComponent("\(position.stem)(2).wav")

            if FileManager.default.fileExists(atPath: alternate.path) {
                let second = try readTake(url: alternate)
                guard abs(second.sampleRate - take.sampleRate) < 0.5,
                      second.left.count == take.left.count
                else {
                    throw SpatializerAudioError(
                        "Mismatched alternate take for \(position.stem).wav"
                    )
                }
                for index in take.left.indices {
                    take.left[index] = (take.left[index] + second.left[index]) * 0.5
                    take.right[index] = (take.right[index] + second.right[index]) * 0.5
                }
            }

            let resampled = try resample(
                take: take,
                targetSampleRate: targetSampleRate
            )
            guard !resampled.left.isEmpty else {
                throw SpatializerAudioError("Empty HRIR: \(primary.lastPathComponent)")
            }
            maxLength = max(maxLength, resampled.left.count)
            loaded.append(resampled)
        }

        var hrirs = [Float](repeating: 0.0, count: positions.count * maxLength * 2)
        for (direction, take) in loaded.enumerated() {
            for index in 0..<take.left.count {
                hrirs[(direction * maxLength + index) * 2] = take.left[index]
                hrirs[(direction * maxLength + index) * 2 + 1] = take.right[index]
            }
        }

        guard hrirs.allSatisfy({ $0.isFinite }) else {
            throw SpatializerAudioError("HRIR contains NaN or infinity")
        }

        var panCoefs = [Float]()
        panCoefs.reserveCapacity(positions.count * 2)
        for position in positions {
            panCoefs.append(position.leftGain)
            panCoefs.append(position.rightGain)
        }

        return HRTFDataset(
            directory: directory,
            sampleRate: targetSampleRate,
            hrirLength: maxLength,
            directions: positions.count,
            hrirs: hrirs,
            panCoefs: panCoefs
        )
    }

    private struct Take {
        var left: [Float]
        var right: [Float]
        let sampleRate: Double
    }

    private static func readTake(url: URL) throws -> Take {
        let file: AVAudioFile
        do {
            file = try AVAudioFile(forReading: url)
        } catch {
            throw SpatializerAudioError(
                "Could not read \(url.lastPathComponent): \(error.localizedDescription)"
            )
        }

        guard file.processingFormat.channelCount == 2 else {
            throw SpatializerAudioError(
                "\(url.lastPathComponent) must be a 2-channel WAV"
            )
        }
        guard file.length > 0 else {
            throw SpatializerAudioError("\(url.lastPathComponent) is empty")
        }

        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: file.processingFormat,
            frameCapacity: AVAudioFrameCount(file.length)
        ) else {
            throw SpatializerAudioError("Could not allocate buffer for \(url.lastPathComponent)")
        }

        do {
            try file.read(into: buffer)
        } catch {
            throw SpatializerAudioError(
                "Could not decode \(url.lastPathComponent): \(error.localizedDescription)"
            )
        }

        guard let channels = buffer.floatChannelData else {
            throw SpatializerAudioError(
                "\(url.lastPathComponent) is not float32-decodable"
            )
        }

        let frames = Int(buffer.frameLength)
        guard frames > 0 else {
            throw SpatializerAudioError("\(url.lastPathComponent) has no samples")
        }

        let left = Array(UnsafeBufferPointer(start: channels[0], count: frames))
        let right = Array(UnsafeBufferPointer(start: channels[1], count: frames))
        return Take(
            left: left,
            right: right,
            sampleRate: file.processingFormat.sampleRate
        )
    }

    private static func resample(take: Take, targetSampleRate: Double) throws -> (left: [Float], right: [Float]) {
        if abs(take.sampleRate - targetSampleRate) < 0.5 {
            return (take.left, take.right)
        }

        guard let sourceFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: take.sampleRate,
            channels: 2,
            interleaved: false
        ), let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: targetSampleRate,
            channels: 2,
            interleaved: false
        ), let converter = AVAudioConverter(from: sourceFormat, to: targetFormat)
        else {
            throw SpatializerAudioError("Could not create HRIR sample-rate converter")
        }

        converter.sampleRateConverterQuality = AVAudioQuality.max.rawValue

        guard let sourceBuffer = AVAudioPCMBuffer(
            pcmFormat: sourceFormat,
            frameCapacity: AVAudioFrameCount(take.left.count)
        ) else {
            throw SpatializerAudioError("Could not allocate source resample buffer")
        }
        sourceBuffer.frameLength = AVAudioFrameCount(take.left.count)
        sourceBuffer.floatChannelData![0].update(from: take.left, count: take.left.count)
        sourceBuffer.floatChannelData![1].update(from: take.right, count: take.right.count)

        let ratio = targetSampleRate / take.sampleRate
        let targetCapacity = AVAudioFrameCount(
            ceil(Double(take.left.count) * ratio) + 64
        )
        guard let targetBuffer = AVAudioPCMBuffer(
            pcmFormat: targetFormat,
            frameCapacity: targetCapacity
        ) else {
            throw SpatializerAudioError("Could not allocate target resample buffer")
        }

        var suppliedInput = false
        var conversionError: NSError?
        let status = converter.convert(
            to: targetBuffer,
            error: &conversionError
        ) { _, inputStatus in
            if suppliedInput {
                inputStatus.pointee = .endOfStream
                return nil
            }
            suppliedInput = true
            inputStatus.pointee = .haveData
            return sourceBuffer
        }

        if status == .error || conversionError != nil {
            throw SpatializerAudioError(
                "HRIR resampling failed: \(conversionError?.localizedDescription ?? "unknown error")"
            )
        }

        guard let channels = targetBuffer.floatChannelData else {
            throw SpatializerAudioError("Resampled HRIR has no float data")
        }
        let frames = Int(targetBuffer.frameLength)
        guard frames > 0 else {
            throw SpatializerAudioError("Resampled HRIR is empty")
        }

        return (
            Array(UnsafeBufferPointer(start: channels[0], count: frames)),
            Array(UnsafeBufferPointer(start: channels[1], count: frames))
        )
    }
}
