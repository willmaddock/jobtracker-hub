"""
Renders a source email (subject/sender/date/body) into a simple one-page
PDF, so an email that JobTracker Hub discovers or matches can be saved as
a real, viewable document in the application's folder -- same as a
resume or cover letter -- instead of only ever existing as a live fetch
in a preview modal (see mail_app_store.get_message_preview()'s docstring
for why the body itself is never persisted anywhere else).

Two call sites use this:
  - api.accept_discovery(): saves the just-previewed email as a PDF into
    the brand-new application folder, going forward.
  - api.backfill_email_pdfs(): sweeps existing account_matches (from a
    normal sync, or an accept from before this module existed) and saves
    a PDF for any that's missing one.

Uses fpdf2 (see requirements.txt) rather than pypdf -- pypdf only reads/
edits existing PDF bytes, it has no text-layout/rendering engine to
build one from scratch.
"""

from __future__ import annotations

import re

from fpdf import FPDF
from fpdf.enums import XPos, YPos

# --- filename -----------------------------------------------------------
# Keeps the same "Email - <subject>.pdf" shape callers can rely on to
# check "does this folder already have one of these" (see
# backfill_email_pdfs' skip-if-present check in api.py) without needing
# a separate marker file or DB column.
_UNSAFE_CHARS_RE = re.compile(r'[\\/:*?"<>|]')
EMAIL_PDF_PREFIX = "Email - "


def safe_email_filename(subject: str | None) -> str:
    """Turns an email subject into a filesystem-safe base filename (no
    extension), prefixed so it's recognizable at a glance in the
    Attached Documents list. Falls back to a generic name if the
    subject is empty/whitespace-only -- a message can have no subject
    at all, and this still needs to produce a usable, non-colliding
    file (unique_dest_path in api.py handles true collisions)."""
    subject = (subject or "").strip()
    if not subject:
        subject = "Untitled message"
    # Strip characters that are unsafe across macOS/Windows/Linux
    # filesystems; collapse whitespace runs left behind.
    cleaned = _UNSAFE_CHARS_RE.sub("", subject)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = "Untitled message"
    return f"{EMAIL_PDF_PREFIX}{cleaned}"[:150]  # keep filenames sane-length


# --- PDF rendering --------------------------------------------------------

def render_email_pdf(subject: str | None, sender: str | None, received_at: str | None, body: str | None) -> bytes:
    """Renders a one-page PDF: a header block (subject/from/date) then
    the plain-text body. `body` may be None (e.g. mail_app_store
    couldn't fetch it, or the message has since moved/been deleted --
    see preview_discovery's docstring) -- in that case the PDF still
    gets produced, just with a placeholder line, so callers never have
    to special-case "no body" themselves."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Every multi_cell() call below pins new_x/new_y explicitly -- fpdf2
    # doesn't reliably reset the cursor to the left margin on its own
    # when a line happens to run right up against the page width (seen
    # in practice with long, space-free strings like email addresses),
    # and a stale cursor position makes the *next* multi_cell() raise
    # "not enough horizontal space" instead of just wrapping normally.
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(0, 8, _latin1_safe(subject or "(no subject)"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 90, 90)
    if sender:
        pdf.multi_cell(0, 6, _latin1_safe(f"From: {sender}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if received_at:
        pdf.multi_cell(0, 6, _latin1_safe(f"Date: {received_at}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    pdf.set_draw_color(200, 200, 200)
    y = pdf.get_y()
    pdf.line(10, y, 200, y)
    pdf.ln(6)

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)
    text = body if body else "(This email's body could not be retrieved.)"
    pdf.multi_cell(0, 6, _latin1_safe(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output())


def _latin1_safe(text: str) -> str:
    """fpdf2's built-in Helvetica font is latin-1 only -- anything
    outside that range (smart quotes, emoji, non-Latin scripts, which
    show up plenty in real recruiter email) would otherwise raise
    inside fpdf2 rather than degrade gracefully. Since this PDF is a
    saved-evidence copy, not the canonical record (the discovery row /
    account_match still has the original text), a lossy substitution
    here is an acceptable trade for never failing the accept/backfill
    that triggered it."""
    return text.encode("latin-1", errors="replace").decode("latin-1")
