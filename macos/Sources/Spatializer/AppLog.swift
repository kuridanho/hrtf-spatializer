import Foundation

/// Minimal file logger for a menu bar app (stdout is not visible when launched
/// from Finder).  Logs live in ~/Library/Logs/Spatializer.
enum AppLog {
    private static let lock = NSLock()

    static let directory: URL = {
        let base = FileManager.default.urls(
            for: .libraryDirectory,
            in: .userDomainMask
        )[0]
        let directory = base.appendingPathComponent("Logs/Spatializer", isDirectory: true)
        try? FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }()

    static let fileURL = directory.appendingPathComponent("spatializer.log")

    static func write(_ message: String) {
        lock.lock()
        defer { lock.unlock() }

        let timestamp = ISO8601DateFormatter().string(from: Date())
        guard let data = "[\(timestamp)] \(message)\n".data(using: .utf8) else {
            return
        }

        if !FileManager.default.fileExists(atPath: fileURL.path) {
            try? data.write(to: fileURL)
            return
        }

        guard let handle = try? FileHandle(forWritingTo: fileURL) else {
            return
        }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    }
}
