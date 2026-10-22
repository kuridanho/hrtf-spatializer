# Spatializer — native macOS menu bar app

The native app is a SwiftUI menu bar application that captures system audio
with **Core Audio Process Tap** (macOS 14.2+), applies the 21-direction HRTF
with a Rust real-time DSP core, and plays the result through the selected
output device.

**BlackHole is not required.** The app creates a private aggregate device
containing a global tap and the chosen output device, muting the original
system output while the tap is being read. The app's own process is excluded
from the tap to prevent feedback.

## Requirements

- macOS 14.2 or newer (tested on macOS 26.6)
- Xcode command line tools / Swift 6 toolchain
- Rust (for the DSP core)
- A 21-file HRTF dataset (see [../docs/dataset.md](../docs/dataset.md))

## Build and run

```bash
./macos/build.sh
open build/Spatializer.app
```

or build and launch in one step:

```bash
./macos/build.sh --run
```

The app is ad-hoc signed for personal use. To install it, drag
`build/Spatializer.app` into `/Applications` (you may need administrator
rights). No notarization or Developer ID is used.

## First run

1. The app has no Dock icon; look for the **headphones** icon in the menu bar.
2. Open **Settings…** from the menu.
3. Grant **System Audio Recording** permission when macOS prompts. If it was
   denied, open **System Settings → Privacy & Security → Screen & System Audio
   Recording** (or **Audio Recording**) and enable Spatializer.
4. Choose an HRTF dataset folder containing the 21 WAV files.
5. Choose an output device and press **Start**.

The first start may take a moment while the tap and aggregate device are
created. Subsequent starts are fast.

## Menu bar

- Status and estimated latency
- Start / Stop
- Bypass
- Volume presets
- Output device
- HRTF dataset
- Latency profile
- Settings…
- Open Privacy Settings…
- Quit

The icon reflects the state: outline (stopped), filled (running), slash
(bypass), warning triangle (error).

## Settings window

The settings window contains:

- Live status, sample rate, buffer frames, estimated latency, HRIR partitions
- Output device picker and Bluetooth warning
- HRTF dataset picker / rescan
- Latency profile (64 / 128 / 256 / 512 samples)
- Volume and bypass with L/R meters
- Launch at Login and "start audio when Spatializer launches"
- Privacy Settings shortcut

Settings are stored in `UserDefaults` for the bundle identifier
`com.kuridanho.spatializer`.

## Latency

Measured with a 16,384-tap HRTF and a 48 kHz stream:

| Block | Algorithmic budget | Rust core mean | Rust core p95 |
|---:|---:|---:|---:|
| 64 | 1.33 ms | 0.49 ms | 0.70 ms |
| 128 | 2.67 ms | 0.50 ms | 0.63 ms |
| 256 | 5.33 ms | 0.56 ms | 0.68 ms |
| 512 | 10.67 ms | 0.63 ms | 0.73 ms |

The app's estimated latency is roughly `(buffer frames + safety offset +
device latency + one block) / sample rate`. On this machine, 64 frames showed
about **2.7 ms** and 128 frames about **5.3 ms** (estimated). The true
end-to-end latency depends on the output device and needs a loopback/acoustic
measurement.

**AirPods:** supported, but Bluetooth transport latency is outside the
low-latency target and is not compensated by this app. Use wired headphones,
a USB-C DAC, or the built-in output for the lowest latency.

## Architecture

```text
System audio
    │
    ▼
CATapDescription (global, excludes Spatializer)
    │  muteBehavior = .mutedWhenTapped
    ▼
Private aggregate device (tap + selected output)
    │
    ▼
Core Audio IOProc (64/128/256/512 frames)
    │
    ▼
Rust spatializer-core (21 directions, partitioned FFT)
    │
    ▼
Selected output device
```

- `Audio/ProcessTap.swift` — tap, aggregate device, IOProc
- `Audio/AudioEngine.swift` — buffer handling and Rust FFI
- `Audio/HRTFLoader.swift` — 21 WAVs, optional `(2).wav` averaging, resampling
- `Audio/AudioDeviceManager.swift` — Core Audio output devices
- `AppState.swift` — settings, lifecycle, meters
- `rust/spatializer-core` — real-time DSP (no Python/GIL)

The app sets `kAudioDevicePropertyBufferFrameSize` on the aggregate device to
the selected profile. The process tap and aggregate are private to the app and
are destroyed on Stop/Quit, which restores normal system audio.

## Login item

**Launch at Login** uses `SMAppService.mainApp.register()`. It has been tested
from the build directory; if the app is moved, toggle the setting off/on so
macOS registers the new path. macOS may require approval under
**System Settings → General → Login Items**.

## Logs

`~/Library/Logs/Spatializer/spatializer.log` (rotated at ~1 MB).

Useful entries include the tap/aggregate IDs, sample rate, buffer size,
partitions, estimated latency, and DSP start errors.

## Development

```bash
# Rust DSP correctness tests
cargo test --release --manifest-path rust/spatializer-core/Cargo.toml

# Performance benchmark
cargo run --release --example bench --manifest-path rust/spatializer-core/Cargo.toml

# Build the app
./macos/build.sh
```

The build requires a local Cargo home; `macos/build.sh` sets
`CARGO_HOME=.cargo-home` so it works in restricted environments.

## Limitations

- macOS only; the native app targets macOS 14.2+ and was developed on macOS 26.
- AirPods/Bluetooth output has its own transport latency and is not a
  low-latency target.
- Process Tap requires the system audio recording permission.
- Ad-hoc signing is used for personal use; distribution would require
  Developer ID signing and notarization.
- The Python implementation remains available for headless/offline use.
