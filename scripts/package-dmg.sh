#!/usr/bin/env bash
# Packages dist/JobTracker Hub.app into dist/JobTracker Hub.dmg, with the
# standard "drag app onto Applications shortcut" layout: a background
# image with an arrow, four icons pre-positioned, and the Finder window
# opening automatically to the right size. Must run on macOS, after
# ./scripts/build-macos.sh.
#
# NOTE: confirmed working end-to-end on a real Mac on 2026-08-26 (build,
# install, and both the Learn More and User Guide shortcuts all worked).
# The icon Y-coordinates below were corrected against that real run --
# see the comment above WINDOW_W for what changed and why.
#
# Usage: ./scripts/package-dmg.sh   (run from the repo root)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APP_NAME="JobTracker Hub"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}.dmg"
BACKGROUND_PNG="scripts/dmg-assets/background.png"
GUIDE_PDF="docs/JobTracker_User_Guide.pdf"
PORTFOLIO_URL="https://willmaddock.github.io/dev/projects/jobtracker-hub/"

# Window/icon layout -- must match the plates/arrow/captions baked into
# background.png (regenerate via scripts/gen_bg.py if you change any of
# this). Row 1 is the primary drag-to-install flow; row 2 is optional --
# a "Learn More" web shortcut and a copy of the bundled User Guide PDF,
# so both are one double-click away right from the install window.
#
# Confirmed against a real build (screenshot pixel measurements,
# 2026-08-26): Finder's "set position of item to {x,y}" places the
# icon's CENTER at (x,y), 1:1 with background.png's own pixel grid --
# these *_ICON_Y values are exactly the *_center_y values gen_bg.py
# draws around. If you move an icon here, move its matching plate/
# caption in gen_bg.py by the same amount and regenerate the PNG.
WINDOW_W=660
WINDOW_H=600
ICON_SIZE=128
APP_ICON_X=180
APP_ICON_Y=170
APPS_ICON_X=480
APPS_ICON_Y=170
LEARN_ICON_X=240
LEARN_ICON_Y=420
GUIDE_ICON_X=420
GUIDE_ICON_Y=420

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this script must run on macOS (uses hdiutil/Finder)." >&2
  exit 1
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "error: $APP_PATH not found -- run ./scripts/build-macos.sh first." >&2
  exit 1
fi

if [[ ! -f "$BACKGROUND_PNG" ]]; then
  echo "error: $BACKGROUND_PNG not found." >&2
  exit 1
fi

if [[ ! -f "$GUIDE_PDF" ]]; then
  echo "error: $GUIDE_PDF not found." >&2
  exit 1
fi

STAGING_DIR="$(mktemp -d)"
RW_DMG="$(mktemp -u).dmg"
MOUNT_POINT=""

cleanup() {
  if [[ -n "$MOUNT_POINT" && -d "$MOUNT_POINT" ]]; then
    hdiutil detach "$MOUNT_POINT" -quiet -force 2>/dev/null || true
  fi
  rm -rf "$STAGING_DIR"
  rm -f "$RW_DMG"
}
trap cleanup EXIT

# --- stage contents -------------------------------------------------
cp -R "$APP_PATH" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"
mkdir -p "$STAGING_DIR/.background"
cp "$BACKGROUND_PNG" "$STAGING_DIR/.background/background.png"

# "Learn More" -- an Internet-shortcut file. A DMG background is just a
# flat image (nothing on it is clickable), so this plus the URL printed
# on the background itself are the two ways someone can reach the
# portfolio page from the install window.
cat > "$STAGING_DIR/Learn More.webloc" <<WEBLOC
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>URL</key>
	<string>${PORTFOLIO_URL}</string>
</dict>
</plist>
WEBLOC

# "User Guide" -- a plain copy of the bundled PDF, sitting right in the
# install window so it opens in Preview with a double-click, no digging
# through the installed app folder required.
cp "$GUIDE_PDF" "$STAGING_DIR/User Guide.pdf"

# --- build a temporary read-write dmg so Finder can style it --------
rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING_DIR" -ov \
  -fs HFS+ -format UDRW -size 300m "$RW_DMG" >/dev/null

MOUNT_POINT="/Volumes/${APP_NAME}"
hdiutil attach "$RW_DMG" -mountpoint "$MOUNT_POINT" -quiet -nobrowse

# --- style the window via Finder/AppleScript -------------------------
osascript <<APPLESCRIPT
tell application "Finder"
  tell disk "${APP_NAME}"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 200 + ${WINDOW_W}, 120 + ${WINDOW_H}}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to ${ICON_SIZE}
    set background picture of theViewOptions to file ".background:background.png"
    set position of item "${APP_NAME}.app" of container window to {${APP_ICON_X}, ${APP_ICON_Y}}
    set position of item "Applications" of container window to {${APPS_ICON_X}, ${APPS_ICON_Y}}
    set position of item "Learn More.webloc" of container window to {${LEARN_ICON_X}, ${LEARN_ICON_Y}}
    set position of item "User Guide.pdf" of container window to {${GUIDE_ICON_X}, ${GUIDE_ICON_Y}}
    close
    open
    -- Re-apply bounds/view options after the close+reopen above.
    -- Finder does not reliably keep everything set on the FIRST open --
    -- in particular the window bounds can silently revert to whatever
    -- Finder last remembered for a volume with this name (e.g. from an
    -- earlier build during development, or from resizing the window by
    -- hand while testing), leaving the background image anchored at its
    -- native 660x600 in a window Finder actually drew larger -- which
    -- shows up as a wide plain-white margin. Setting bounds/view options
    -- again here, on the window Finder is *actually* about to display,
    -- makes that stick instead.
    set the bounds of container window to {200, 120, 200 + ${WINDOW_W}, 120 + ${WINDOW_H}}
    set theViewOptions to the icon view options of container window
    set arrangement of theViewOptions to not arranged
    set icon size of theViewOptions to ${ICON_SIZE}
    set background picture of theViewOptions to file ".background:background.png"
    update without registering applications
    delay 1
  end tell
end tell
APPLESCRIPT

sync
hdiutil detach "$MOUNT_POINT" -quiet
MOUNT_POINT=""

# --- convert to the final compressed, read-only dmg ------------------
hdiutil convert "$RW_DMG" -format UDZO -ov -o "$DMG_PATH" >/dev/null

echo "Wrote $DMG_PATH"
