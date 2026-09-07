"""
Explicit MIME types for formats browsers/servers sometimes guess wrong (or
don't know at all, like .tex) — used by /api/file so inline previews (PDF
iframe, .md/.tex text view) always get a sane Content-Type instead of
falling back to application/octet-stream.

Extracted verbatim from api.py's former module-level EXTRA_MEDIA_TYPES
constant, into its own module so infrastructure/paths.py can import it
without importing api.py itself (that would be a circular import, since
api.py imports from infrastructure/).
"""

from __future__ import annotations

EXTRA_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".tex": "text/x-tex",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
}
