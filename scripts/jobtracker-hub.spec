# -*- mode: python ; coding: utf-8 -*-
#
# Build with:  pyinstaller --noconfirm scripts/jobtracker-hub.spec
# (run from the repo root; produces dist/JobTracker Hub.app on macOS)
#
# NOTE: written and syntax/dry-run-checked in a sandbox with no network
# access, so PyInstaller itself couldn't be installed there to run a
# real build. The overall shape (Analysis -> PYZ -> EXE -> BUNDLE, data
# dirs, icon) follows PyInstaller's standard one-file-app pattern, but
# has not been proven against this actual codebase. Expect to iterate
# once you run it for real -- especially the hiddenimports list, which
# is a best-effort guess at what fastapi/uvicorn/pydantic need beyond
# static analysis.

import sys
from pathlib import Path

block_cipher = None

REPO_ROOT = Path(SPECPATH).parent  # scripts/ -> repo root
APP_NAME = "JobTracker Hub"

a = Analysis(
    [str(REPO_ROOT / "desktop" / "entry.py")],
    pathex=[str(REPO_ROOT / "desktop"), str(REPO_ROOT / "_app")],
    binaries=[],
    datas=[
        (str(REPO_ROOT / "_app"), "_app"),
        (str(REPO_ROOT / "sample-tracker"), "sample-tracker"),
        (str(REPO_ROOT / "desktop" / "first_run.html"), "."),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "pydantic.deprecated.decorator",
        "multipart",  # python-multipart, imported as `multipart` by starlette
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(REPO_ROOT / "assets" / "icon.icns") if sys.platform == "darwin" else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(REPO_ROOT / "assets" / "icon.icns") if sys.platform == "darwin" else None,
    bundle_identifier="com.jobtrackerhub.app",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": "1.1.0",
        "NSHighResolutionCapable": True,
        # This app never talks to the network except localhost -- the
        # backend binds 127.0.0.1 only (see _app/api.py's __main__
        # block). No network-usage description is needed because no
        # network entitlement is requested.
    },
)
