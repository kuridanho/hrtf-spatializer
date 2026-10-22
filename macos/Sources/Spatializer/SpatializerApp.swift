import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        AppLog.write("applicationDidFinishLaunching args=\(CommandLine.arguments)")

        if let bundleID = Bundle.main.bundleIdentifier {
            let others = NSRunningApplication.runningApplications(
                withBundleIdentifier: bundleID
            ).filter {
                $0.processIdentifier != ProcessInfo.processInfo.processIdentifier
            }
            if let existing = others.first {
                AppLog.write("Another instance is running; activating it")
                existing.activate()
                NSApp.terminate(nil)
                return
            }
        }

    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}

@main
struct SpatializerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var state = AppState()

    var body: some Scene {
        MenuBarExtra {
            MenuContent()
                .environment(state)
        } label: {
            MenuBarLabel()
                .environment(state)
        }
        .menuBarExtraStyle(.menu)

        Window("Spatializer Settings", id: "settings") {
            SettingsView()
                .environment(state)
        }
        .defaultSize(width: 560, height: 500)
        .windowResizability(.contentSize)
    }
}


private struct MenuBarLabel: View {
    @Environment(AppState.self) private var state
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Image(systemName: state.menuIcon)
            .onAppear {
                AppLog.write("MenuBarLabel onAppear")
                guard CommandLine.arguments.contains("--settings") else { return }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    AppLog.write("Opening settings window")
                    NSApp.activate(ignoringOtherApps: true)
                    openWindow(id: "settings")
                    AppLog.write("openWindow(settings) called")
                }
            }
    }
}
