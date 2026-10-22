#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="${ROOT}/build/Spatializer.app"
export CARGO_HOME="${ROOT}/.cargo-home"
export TMPDIR="${ROOT}/.build-cache/tmp"
export CLANG_MODULE_CACHE_PATH="${ROOT}/.build-cache/clang"
export SWIFT_MODULE_CACHE_PATH="${ROOT}/.build-cache/swift"
mkdir -p "${TMPDIR}" "${CLANG_MODULE_CACHE_PATH}" "${SWIFT_MODULE_CACHE_PATH}"

echo "==> Building Rust DSP core"
cargo build --release --manifest-path "${ROOT}/rust/spatializer-core/Cargo.toml"

echo "==> Building Swift app"
rm -rf "${APP}"
mkdir -p "${APP}/Contents/MacOS" "${APP}/Contents/Resources"

SOURCES=()
while IFS= read -r -d '' file; do
    SOURCES+=("${file}")
done < <(find "${ROOT}/macos/Sources/Spatializer" -name '*.swift' -print0 | sort -z)

ARCH="$(uname -m)"
swiftc \
    -O -whole-module-optimization \
    -parse-as-library \
    -disable-sandbox \
    -swift-version 5 \
    -target "${ARCH}-apple-macos14.2" \
    -sdk "$(xcrun --sdk macosx --show-sdk-path)" \
    -import-objc-header "${ROOT}/macos/Sources/Spatializer/BridgingHeader.h" \
    -Xcc "-I${ROOT}/rust/spatializer-core/include" \
    -L "${ROOT}/rust/spatializer-core/target/release" \
    -lspatializer_core \
    -framework SwiftUI \
    -framework AppKit \
    -framework CoreAudio \
    -framework AudioToolbox \
    -framework AVFoundation \
    -framework ServiceManagement \
    "${SOURCES[@]}" \
    -o "${APP}/Contents/MacOS/Spatializer"

cp "${ROOT}/macos/Resources/Info.plist" "${APP}/Contents/Info.plist"
printf 'APPL????' > "${APP}/Contents/PkgInfo"

xattr -cr "${APP}" 2>/dev/null || true
codesign --force --deep --sign - "${APP}"

echo "Built ${APP}"
if [[ "${1:-}" == "--run" ]]; then
    open "${APP}"
fi
