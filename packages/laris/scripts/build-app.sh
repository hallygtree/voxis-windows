#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Laris.app"
APP_DIR="${REPO_ROOT}/${APP_NAME}"
SRC_SCRIPT="${REPO_ROOT}/scripts/applet.scpt.applescript"

rm -rf "$APP_DIR"

osacompile -o "$APP_DIR" "$SRC_SCRIPT"

cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>applet</string>
    <key>CFBundleIconFile</key>
    <string>applet</string>
    <key>CFBundleIdentifier</key>
    <string>dev.sammyjdev.laris</string>
    <key>CFBundleName</key>
    <string>LARIS</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSBackgroundOnly</key>
    <false/>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>LARIS needs microphone access to transcribe your voice into text.</string>
</dict>
</plist>
PLIST

chmod +x "$APP_DIR/Contents/MacOS/applet"

echo "Built $APP_DIR"
echo "To launch: open $APP_DIR"
