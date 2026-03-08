#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "Building HealthTick..."

# Try universal binary, fallback to native arch
if swift build -c release --arch arm64 --arch x86_64 2>/dev/null; then
    BINARY=".build/apple/Products/Release/HealthTick"
    echo "Built universal binary (arm64 + x86_64)"
else
    swift build -c release
    BINARY=".build/release/HealthTick"
    echo "Built native binary"
fi

APP_DIR="$HOME/Applications/HealthTick.app/Contents/MacOS"
mkdir -p "$APP_DIR"
cp "$BINARY" "$APP_DIR/"
cp Sources/Info.plist "$HOME/Applications/HealthTick.app/Contents/"

# Copy resources
RES_DIR="$HOME/Applications/HealthTick.app/Contents/Resources"
mkdir -p "$RES_DIR"
if [ -d "Sources/Resources" ]; then
    cp -R Sources/Resources/* "$RES_DIR/"
fi

# Ad-hoc code signing
codesign --force --deep --sign - "$HOME/Applications/HealthTick.app"
echo "Done! App installed to ~/Applications/HealthTick.app (signed)"
echo "Run: open ~/Applications/HealthTick.app"
