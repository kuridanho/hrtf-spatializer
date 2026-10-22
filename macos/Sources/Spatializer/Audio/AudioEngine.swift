import AudioToolbox
import CoreAudio
import Foundation

/// Owns the process tap, the Rust DSP core, and the Core Audio IOProc.
final class AudioEngine: @unchecked Sendable {
    private(set) var isRunning = false
    private(set) var sampleRate: Double = 0
    private(set) var blockSize: Int = 0
    private(set) var bufferFrames: UInt32 = 0
    private(set) var partitions: Int = 0
    private(set) var latencyMilliseconds: Double = 0

    private var tap: ProcessTap?
    private var core: OpaquePointer?
    private var inputBuffer: UnsafeMutablePointer<Float>?
    private var outputBuffer: UnsafeMutablePointer<Float>?
    private var inputIsNonInterleaved = false
    private var outputIsNonInterleaved = false

    func start(datasetURL: URL, outputUID: String, blockSize: Int) throws {
        stop()
        guard blockSize >= 64 else {
            throw SpatializerAudioError("Block size must be at least 64 samples")
        }

        let tap = ProcessTap()
        try tap.prepare(outputUID: outputUID, blockSize: UInt32(blockSize))

        do {
            guard let tapFormat = tap.tapFormat else {
                throw SpatializerAudioError("The system audio tap has no format")
            }

            AppLog.write("AudioEngine: loading HRTF")
            let dataset = try HRTFLoader.load(
                directory: datasetURL,
                targetSampleRate: tapFormat.mSampleRate
            )
            AppLog.write("AudioEngine: HRTF loaded, creating core")

            let createdCore: OpaquePointer? = dataset.hrirs.withUnsafeBufferPointer { hrirs in
                dataset.panCoefs.withUnsafeBufferPointer { pan in
                    spatializer_core_create(
                        hrirs.baseAddress,
                        pan.baseAddress,
                        Int32(dataset.directions),
                        Int32(dataset.hrirLength),
                        Int32(tapFormat.mSampleRate.rounded()),
                        Int32(blockSize)
                    )
                }
            }
            guard let createdCore else {
                throw SpatializerAudioError("Could not create the HRTF processor")
            }

            let input = UnsafeMutablePointer<Float>.allocate(
                capacity: blockSize * 2
            )
            let output = UnsafeMutablePointer<Float>.allocate(
                capacity: blockSize * 2
            )
            input.initialize(repeating: 0, count: blockSize * 2)
            output.initialize(repeating: 0, count: blockSize * 2)

            self.tap = tap
            self.core = createdCore
            self.inputBuffer = input
            self.outputBuffer = output
            self.blockSize = blockSize
            self.sampleRate = tapFormat.mSampleRate
            self.bufferFrames = tap.bufferFrameSize
            self.partitions = Int(spatializer_core_partitions(createdCore))
            self.inputIsNonInterleaved =
                (tapFormat.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0

            let outputFormat = tap.aggregateOutputFormat ?? tapFormat
            self.outputIsNonInterleaved =
                (outputFormat.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0

            AppLog.write("AudioEngine: starting tap")
            try tap.start { [weak self] _, inputData, _, outputData, _ in
                self?.render(
                    inputData: inputData,
                    outputData: outputData
                )
            }

            self.isRunning = true
            self.latencyMilliseconds = estimateLatency()
            AppLog.write(
                "AudioEngine started rate=\(sampleRate) buffer=\(bufferFrames) "
                    + "block=\(blockSize) partitions=\(partitions) "
                    + "latency=\(String(format: "%.2f", latencyMilliseconds))ms"
            )
        } catch {
            tap.stop()
            if let createdCore = self.core {
                spatializer_core_destroy(createdCore)
            }
            self.core = nil
            if let input = self.inputBuffer {
                input.deinitialize(count: blockSize * 2)
                input.deallocate()
            }
            if let output = self.outputBuffer {
                output.deinitialize(count: blockSize * 2)
                output.deallocate()
            }
            self.inputBuffer = nil
            self.outputBuffer = nil
            self.tap = nil
            throw error
        }
    }

    func stop() {
        tap?.stop()
        tap = nil

        if let core {
            spatializer_core_destroy(core)
            self.core = nil
        }

        if let input = inputBuffer {
            input.deinitialize(count: blockSize * 2)
            input.deallocate()
            inputBuffer = nil
        }
        if let output = outputBuffer {
            output.deinitialize(count: blockSize * 2)
            output.deallocate()
            outputBuffer = nil
        }

        isRunning = false
        blockSize = 0
        sampleRate = 0
        bufferFrames = 0
        partitions = 0
        latencyMilliseconds = 0
    }

    func setGain(_ gain: Float) {
        guard let core else { return }
        spatializer_core_set_gain(core, gain)
    }

    func setBypass(_ bypass: Bool) {
        guard let core else { return }
        spatializer_core_set_bypass(core, bypass)
    }

    func meters() -> (Float, Float) {
        guard let core else { return (0, 0) }
        var left: Float = 0
        var right: Float = 0
        spatializer_core_get_meters(core, &left, &right)
        return (left, right)
    }

    private func render(
        inputData: UnsafePointer<AudioBufferList>,
        outputData: UnsafeMutablePointer<AudioBufferList>
    ) {
        guard let core, let inputBuffer, let outputBuffer else { return }

        let inputList = UnsafeMutableAudioBufferListPointer(
            UnsafeMutablePointer(mutating: inputData)
        )
        let outputList = UnsafeMutableAudioBufferListPointer(outputData)
        guard inputList.count > 0, outputList.count > 0 else { return }

        let bytesPerFrame = inputIsNonInterleaved ? 4 : 8
        var frames = Int(inputList[0].mDataByteSize) / bytesPerFrame
        if frames <= 0 {
            frames = blockSize
        }
        frames = min(frames, blockSize)
        guard frames > 0 else { return }

        if inputIsNonInterleaved {
            guard inputList.count >= 2,
                  let leftData = inputList[0].mData,
                  let rightData = inputList[1].mData
            else { return }
            let left = leftData.assumingMemoryBound(to: Float.self)
            let right = rightData.assumingMemoryBound(to: Float.self)
            for index in 0..<frames {
                inputBuffer[index * 2] = left[index]
                inputBuffer[index * 2 + 1] = right[index]
            }
        } else {
            guard let data = inputList[0].mData else { return }
            inputBuffer.update(
                from: data.assumingMemoryBound(to: Float.self),
                count: frames * 2
            )
        }

        spatializer_core_process(core, inputBuffer, outputBuffer, Int32(frames))

        if outputIsNonInterleaved {
            guard outputList.count >= 2,
                  let leftData = outputList[0].mData,
                  let rightData = outputList[1].mData
            else { return }
            let left = leftData.assumingMemoryBound(to: Float.self)
            let right = rightData.assumingMemoryBound(to: Float.self)
            for index in 0..<frames {
                left[index] = outputBuffer[index * 2]
                right[index] = outputBuffer[index * 2 + 1]
            }
        } else {
            guard let data = outputList[0].mData else { return }
            data.assumingMemoryBound(to: Float.self).update(
                from: outputBuffer,
                count: frames * 2
            )
        }
    }

    private func estimateLatency() -> Double {
        guard let tap, sampleRate > 0 else { return 0 }
        let frames = Double(tap.bufferFrameSize)
        let safety = (try? tap.aggregateID.readSafetyOffset()).map(Double.init) ?? 0
        let deviceLatency = (try? tap.aggregateID.readLatency()).map(Double.init) ?? 0
        let algorithm = Double(blockSize)
        return (frames + safety + deviceLatency + algorithm) / sampleRate * 1000.0
    }

    deinit {
        stop()
    }
}
