#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
RELEASE="$BUILD/release"
DIST="$BUILD/dist-macos"
WORK="$BUILD/work-macos"
APP="$DIST/VK Search.app"
APP_BIN="$APP/Contents/MacOS/VK Search"
BROWSERS="$BUILD/playwright-browsers"
DMG="$RELEASE/VK_Search_0.4.10_macOS_arm64.dmg"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.ci-venv/bin/python}"

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "This release must be built on native Apple Silicon." >&2
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo "Production frontend bundle is missing." >&2
  exit 1
fi

rm -rf "$DIST" "$WORK" "$RELEASE" "$BUILD/app-icon.iconset" "$BUILD/app-icon.icns"
mkdir -p "$RELEASE" "$BUILD/app-icon.iconset"

make_icon() {
  local pixels="$1"
  local name="$2"
  sips -s format png -z "$pixels" "$pixels" "$BUILD/app-icon.png" --out "$BUILD/app-icon.iconset/$name" >/dev/null
}
make_icon 16 icon_16x16.png
make_icon 32 icon_16x16@2x.png
make_icon 32 icon_32x32.png
make_icon 64 icon_32x32@2x.png
make_icon 128 icon_128x128.png
make_icon 256 icon_128x128@2x.png
make_icon 256 icon_256x256.png
make_icon 512 icon_256x256@2x.png
make_icon 512 icon_512x512.png
make_icon 1024 icon_512x512@2x.png
iconutil -c icns "$BUILD/app-icon.iconset" -o "$BUILD/app-icon.icns"

export PLAYWRIGHT_BROWSERS_PATH="$BROWSERS"
"$PYTHON_BIN" -m playwright install chromium
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST" \
  --workpath "$WORK" \
  "$BUILD/VKOutreachManagerMac.spec"

APP_BROWSER_RESOURCES="$APP/Contents/Resources/playwright-browsers"
rm -rf "$APP_BROWSER_RESOURCES"
mkdir -p "$(dirname "$APP_BROWSER_RESOURCES")"
cp -R "$BROWSERS" "$APP_BROWSER_RESOURCES"
test -d "$APP_BROWSER_RESOURCES"

test -x "$APP_BIN"
file "$APP_BIN" | grep -q 'arm64'

codesign --force --deep --sign - --timestamp=none "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

run_self_test() {
  local flag="$1"
  local label="$2"
  local number="$3"
  local log="$RUNNER_TEMP/${label}-${number}.log"
  rm -f "$log"
  VK_OUTREACH_SELF_TEST_LOG="$log" "$APP_BIN" "$flag"
  if [[ -s "$log" ]]; then
    cat "$log" >&2
    exit 1
  fi
}

for number in 1 2; do run_self_test --self-test application "$number"; done
for number in 1 2; do run_self_test --browser-self-test browser "$number"; done
for number in 1 2; do run_self_test --frontend-self-test frontend "$number"; done

STAGING="$RUNNER_TEMP/vk-search-dmg"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create \
  -volname "VK Search" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG"
hdiutil verify "$DMG"
shasum -a 256 "$DMG" > "$DMG.sha256"

echo "Built $DMG"
