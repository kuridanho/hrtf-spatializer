import AudioToolbox
import CoreAudio
import Foundation

struct SpatializerAudioError: LocalizedError {
    let message: String
    var errorDescription: String? { message }

    init(_ message: String) {
        self.message = message
    }
}

extension AudioObjectID {
    static let system = AudioObjectID(kAudioObjectSystemObject)
    static let unknown = AudioObjectID(kAudioObjectUnknown)

    var isValid: Bool { self != .unknown }

    func read<T>(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
        element: AudioObjectPropertyElement = kAudioObjectPropertyElementMain,
        defaultValue: T
    ) throws -> T {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: scope,
            mElement: element
        )
        var size = UInt32(MemoryLayout<T>.size)
        var value = defaultValue
        let status = withUnsafeMutablePointer(to: &value) { pointer in
            AudioObjectGetPropertyData(self, &address, 0, nil, &size, pointer)
        }
        guard status == noErr else {
            throw SpatializerAudioError(
                "Core Audio property 0x\(String(selector, radix: 16)) failed: \(status)"
            )
        }
        return value
    }

    func readArray<T>(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
        element: AudioObjectPropertyElement = kAudioObjectPropertyElementMain,
        defaultValue: T
    ) throws -> [T] {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: scope,
            mElement: element
        )
        var size: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(self, &address, 0, nil, &size)
        guard status == noErr else {
            throw SpatializerAudioError(
                "Core Audio size for 0x\(String(selector, radix: 16)) failed: \(status)"
            )
        }

        let count = Int(size) / MemoryLayout<T>.stride
        var values = [T](repeating: defaultValue, count: count)
        status = values.withUnsafeMutableBufferPointer { buffer in
            AudioObjectGetPropertyData(self, &address, 0, nil, &size, buffer.baseAddress!)
        }
        guard status == noErr else {
            throw SpatializerAudioError(
                "Core Audio array 0x\(String(selector, radix: 16)) failed: \(status)"
            )
        }
        return values
    }

    func readString(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
        element: AudioObjectPropertyElement = kAudioObjectPropertyElementMain
    ) throws -> String {
        let value: CFString = try read(
            selector,
            scope: scope,
            element: element,
            defaultValue: "" as CFString
        )
        return value as String
    }

    func readDouble(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal
    ) throws -> Double {
        try read(selector, scope: scope, defaultValue: 0.0)
    }

    func readUInt32(
        _ selector: AudioObjectPropertySelector,
        scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal
    ) throws -> UInt32 {
        try read(selector, scope: scope, defaultValue: 0)
    }

    func readAudioTapFormat() throws -> AudioStreamBasicDescription {
        try read(kAudioTapPropertyFormat, defaultValue: AudioStreamBasicDescription())
    }

    func readDeviceUID() throws -> String {
        try readString(kAudioDevicePropertyDeviceUID)
    }

    func readDeviceName() throws -> String {
        try readString(kAudioDevicePropertyDeviceNameCFString)
    }

    func readNominalSampleRate() throws -> Double {
        try readDouble(kAudioDevicePropertyNominalSampleRate)
    }

    func readTransportType() throws -> UInt32 {
        try readUInt32(kAudioDevicePropertyTransportType)
    }

    func readBufferFrameSize() throws -> UInt32 {
        try readUInt32(kAudioDevicePropertyBufferFrameSize)
    }

    func readLatency() throws -> UInt32 {
        try readUInt32(kAudioDevicePropertyLatency)
    }

    func readSafetyOffset() throws -> UInt32 {
        try readUInt32(kAudioDevicePropertySafetyOffset)
    }

    func setBufferFrameSize(_ frames: UInt32) throws {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyBufferFrameSize,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value = frames
        let status = AudioObjectSetPropertyData(
            self,
            &address,
            0,
            nil,
            UInt32(MemoryLayout<UInt32>.size),
            &value
        )
        guard status == noErr else {
            throw SpatializerAudioError(
                "Could not set buffer frame size to \(frames): \(status)"
            )
        }
    }

    func outputChannelCount() throws -> Int {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: kAudioObjectPropertyScopeOutput,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(self, &address, 0, nil, &size)
        guard status == noErr else { return 0 }

        let raw = UnsafeMutableRawPointer.allocate(
            byteCount: Int(size),
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { raw.deallocate() }
        let list = raw.bindMemory(to: AudioBufferList.self, capacity: 1)
        status = AudioObjectGetPropertyData(self, &address, 0, nil, &size, list)
        guard status == noErr else { return 0 }

        return UnsafeMutableAudioBufferListPointer(list).reduce(0) {
            $0 + Int($1.mNumberChannels)
        }
    }

    func firstStreamFormat(scope: AudioObjectPropertyScope) throws -> AudioStreamBasicDescription {
        let streams: [AudioStreamID] = try readArray(
            kAudioDevicePropertyStreams,
            scope: scope,
            defaultValue: AudioStreamID(kAudioObjectUnknown)
        )
        guard let stream = streams.first, stream.isValid else {
            throw SpatializerAudioError("No audio stream for scope \(scope)")
        }
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioStreamPropertyVirtualFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        var format = AudioStreamBasicDescription()
        let status = AudioObjectGetPropertyData(
            stream,
            &address,
            0,
            nil,
            &size,
            &format
        )
        guard status == noErr else {
            throw SpatializerAudioError("Could not read stream format: \(status)")
        }
        return format
    }

    static func defaultOutputDevice() throws -> AudioDeviceID {
        try AudioObjectID.system.read(
            kAudioHardwarePropertyDefaultOutputDevice,
            defaultValue: AudioDeviceID(kAudioObjectUnknown)
        )
    }

    static func deviceList() throws -> [AudioObjectID] {
        try AudioObjectID.system.readArray(
            kAudioHardwarePropertyDevices,
            defaultValue: AudioObjectID.unknown
        )
    }

    static func translatePIDToProcessObject(pid: pid_t) throws -> AudioObjectID {
        let processObject: AudioObjectID = try AudioObjectID.system.read(
            kAudioHardwarePropertyTranslatePIDToProcessObject,
            defaultValue: AudioObjectID.unknown,
            qualifier: pid
        )
        guard processObject.isValid else {
            throw SpatializerAudioError("Could not resolve process object for PID \(pid)")
        }
        return processObject
    }

    private func read<T, Q>(
        _ selector: AudioObjectPropertySelector,
        defaultValue: T,
        qualifier: Q
    ) throws -> T {
        var address = AudioObjectPropertyAddress(
            mSelector: selector,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var qualifier = qualifier
        var size = UInt32(MemoryLayout<T>.size)
        var value = defaultValue
        let status = withUnsafeMutablePointer(to: &qualifier) { qualifierPointer in
            withUnsafeMutablePointer(to: &value) { valuePointer in
                AudioObjectGetPropertyData(
                    self,
                    &address,
                    UInt32(MemoryLayout<Q>.size),
                    qualifierPointer,
                    &size,
                    valuePointer
                )
            }
        }
        guard status == noErr else {
            throw SpatializerAudioError(
                "Core Audio qualified property 0x\(String(selector, radix: 16)) failed: \(status)"
            )
        }
        return value
    }
}
