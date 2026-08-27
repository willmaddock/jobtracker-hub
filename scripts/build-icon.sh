#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_SVG="$REPO_ROOT/assets/icon.svg"
ICONSET="$REPO_ROOT/assets/icon.iconset"
ICNS_OUT="$REPO_ROOT/assets/icon.icns"

if [[ ! -f "$SRC_SVG" ]]; then
  echo "error: $SRC_SVG not found" >&2
  exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

render() {
  local size="$1" out="$2"
  if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w "$size" -h "$size" "$SRC_SVG" -o "$out"
  elif command -v qlmanage >/dev/null 2>&1; then
    local tmp_dir
    tmp_dir="$(mktemp -d)"
    qlmanage -t -s "$size" -o "$tmp_dir" "$SRC_SVG" >/dev/null 2>&1
    local produced="$tmp_dir/$(basename "$SRC_SVG").png"
    if [[ ! -f "$produced" ]]; then
      echo "error: qlmanage failed to render $SRC_SVG at ${size}px" >&2
      rm -rf "$tmp_dir"
      exit 1
    fi
    mv "$produced" "$out"
    rm -rf "$tmp_dir"
  else
    echo "error: neither rsvg-convert nor qlmanage is available" >&2
    exit 1
  fi
}

SIZES="
icon_16x16.png:16
icon_16x16@2x.png:32
icon_32x32.png:32
icon_32x32@2x.png:64
icon_128x128.png:128
icon_128x128@2x.png:256
icon_256x256.png:256
icon_256x256@2x.png:512
icon_512x512.png:512
icon_512x512@2x.png:1024
"

for pair in $SIZES; do
  name="${pair%%:*}"
  size="${pair##*:}"
  echo "rendering $name (${size}px)..."
  render "$size" "$ICONSET/$name"
done

if command -v iconutil >/dev/null 2>&1; then
  iconutil -c icns "$ICONSET" -o "$ICNS_OUT"
  echo "Wrote $ICNS_OUT via iconutil"
else
  echo "error: iconutil not found -- this script must run on macOS" >&2
  exit 1
fi

echo "Iconset PNGs left in $ICONSET for inspection; $ICNS_OUT is the file build-macos.sh consumes."
