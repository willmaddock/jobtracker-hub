"""
core media_types.

Phase 5 port of _app/media_types.py and infrastructure/paths.py's
guess_media_type, unchanged. Neither had any filesystem dependency to
begin with -- both operate on a filename/suffix only -- so unlike the
rest of infrastructure/paths.py (see core/exceptions.py's docstring
for what got dropped there), this one ports as-is. Still needed once
Phase 8 builds the download endpoint for Document.file: browsers and
Python's mimetypes module guess some of these wrong (or don't know
.tex at all), so /api/file-equivalent responses need this to set a
sane Content-Type for inline previews (PDF iframe, .md/.tex text
view).
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

EXTRA_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".tex": "text/x-tex",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
}


def guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in EXTRA_MEDIA_TYPES:
        return EXTRA_MEDIA_TYPES[ext]
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"
