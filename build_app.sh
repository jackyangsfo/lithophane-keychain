#!/bin/bash
# Build macOS .app for Lithophane Keychain Generator (Rev 1.0)
# Copyright © 2026 NovaForge Innovations LLC. All rights reserved.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

APP_NAME="Lithophane Keychain Generator"
APP_DIR="$ROOT/${APP_NAME}.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
BUNDLE_ID="com.novaforgeinnovations.lithophane-keychain"
VERSION="2.0"
COPYRIGHT="Copyright © 2026 NovaForge Innovations LLC. All rights reserved."

if [[ ! -x "$ROOT/venv/bin/python" ]]; then
  echo "Error: venv not found. Create it first:"
  echo "  python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "Generating app icon…"
"$ROOT/venv/bin/python" "$ROOT/make_icon.py"

echo "Creating ${APP_NAME}.app…"
rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES"

# Launcher — always uses project venv next to the .app
cat > "$MACOS/LithophaneKeychain" <<'EOF'
#!/bin/bash
# Lithophane Keychain Generator launcher
# Copyright © 2026 NovaForge Innovations LLC

set -euo pipefail

# Resolve .app/Contents/MacOS → project root (sibling of the .app)
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_BUNDLE="$(cd "$HERE/../.." && pwd)"
PROJECT_ROOT="$(cd "$APP_BUNDLE/.." && pwd)"

PYTHON="$PROJECT_ROOT/venv/bin/python"
GUI="$PROJECT_ROOT/gui.py"

if [[ ! -x "$PYTHON" ]]; then
  osascript -e 'display dialog "Virtual environment not found.\n\nExpected:\n'"$PYTHON"'\n\nOpen Terminal in the project folder and run:\n  python3 -m venv venv\n  ./venv/bin/pip install -r requirements.txt" buttons {"OK"} default button 1 with title "Lithophane Keychain Generator"'
  exit 1
fi

if [[ ! -f "$GUI" ]]; then
  osascript -e 'display dialog "gui.py not found in:\n'"$PROJECT_ROOT"'" buttons {"OK"} default button 1 with title "Lithophane Keychain Generator"'
  exit 1
fi

cd "$PROJECT_ROOT"
exec "$PYTHON" "$GUI"
EOF
chmod +x "$MACOS/LithophaneKeychain"

# Info.plist
cat > "$CONTENTS/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleDevelopmentRegion</key>
	<string>en</string>
	<key>CFBundleDisplayName</key>
	<string>${APP_NAME}</string>
	<key>CFBundleExecutable</key>
	<string>LithophaneKeychain</string>
	<key>CFBundleIconFile</key>
	<string>AppIcon</string>
	<key>CFBundleIdentifier</key>
	<string>${BUNDLE_ID}</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>${APP_NAME}</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>${VERSION}</string>
	<key>CFBundleVersion</key>
	<string>${VERSION}</string>
	<key>LSMinimumSystemVersion</key>
	<string>11.0</string>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSHumanReadableCopyright</key>
	<string>${COPYRIGHT}</string>
	<key>NSPrincipalClass</key>
	<string>NSApplication</string>
</dict>
</plist>
EOF

# PkgInfo
echo -n "APPL????" > "$CONTENTS/PkgInfo"

# Icon
if [[ -f "$ROOT/assets/AppIcon.icns" ]]; then
  cp "$ROOT/assets/AppIcon.icns" "$RESOURCES/AppIcon.icns"
fi

# Touch to refresh Finder icon cache hints
touch "$APP_DIR"

echo ""
echo "Built: $APP_DIR"
echo "  Version : Rev ${VERSION}"
echo "  Owner   : NovaForge Innovations LLC"
echo ""
echo "Double-click the app to launch, or:"
echo "  open \"$APP_DIR\""
