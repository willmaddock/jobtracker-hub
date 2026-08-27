#!/usr/bin/env bash
# Builds dist/JobTracker Hub.app from scratch. Must run on macOS.
#
# NOTE: this could not be run or verified in the sandbox that wrote it
# (no network access to install fastapi/pywebview/pyinstaller there).
# Run it for real on your Mac; expect to fix a few things on first try
# (see the .spec file's own note about hiddenimports being a
# best-effort guess).
#
# Usage: ./scripts/build-macos.sh   (run from the repo root)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "error: this script must run on macOS (produces a .app bundle)." >&2
  exit 1
fi

if [[ ! -f "assets/icon.icns" ]]; then
  echo "assets/icon.icns not found -- building it first..."
  ./scripts/build-icon.sh
fi

VENV_DIR=".build-venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "creating build venv at $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "installing backend + desktop dependencies..."
pip install --upgrade pip -q
pip install -r _app/requirements.txt -q
pip install -r desktop/requirements.txt -q

echo "running PyInstaller..."
rm -rf build dist
pyinstaller --noconfirm scripts/jobtracker-hub.spec

echo
echo "Build complete: dist/${APP_NAME:-JobTracker Hub}.app"
echo "Run it directly to test, or continue with ./scripts/package-dmg.sh to make a .dmg."
