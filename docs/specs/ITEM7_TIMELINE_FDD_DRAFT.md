# Item 7 — Application Timeline: FDD Draft (v1 scope)

## Why this document exists

Checkpoint 5/6 of Item 6 left a "Timeline view" as the recommended next
feature (see `docs/ITEM6_DEV_LOG.tex`'s Next Steps box): built from
per-document detected dates and the item's status, showing the shape
of an application's life — applied → interviewing → resolved — without
requiring the user to type anything new. This document is the working
scope definition for that feature, referenced from `dossier.py`,
`overrides_store.py`, `tests/test_timeline.py`, and
`tests/test_status_history.py` rather than duplicated inline in each.

## v1 scope, as actually shipped

The originally discussed design considered a six-stage abstract event
model (drafted → applied → phone screen → interview → offer/rejected →
closed). Real-corpus review during implementation showed that model
doesn't match what the documents in a real tracker actually contain —
most folders have at most a confirmation email and, sometimes, one or
more interview-request emails; rejection is very rarely a standalone
document at all. v1 narrows to what the evidence actually supports:

- **Document-derived events** — one entry per document classified as
  `application_confirmation` or `interview_notice` that has a detected
  date (`extract.py`'s existing per-document `detected_date_applied`,
  already computed for every document regardless of type — no new
  extraction logic). A folder with two interview-request documents
  (e.g. a phone screen, then a later on-site) produces two separate
  events, never merged into one — collapsing them would hide real
  information the documents contain.
- **The "Current status" event** — item-level, not document-derived.
  Backed by a new `status_history` log (`overrides_store.py`) that
  records every real status transition going forward. Because
  rejection so rarely shows up as its own document, this is how a
  rejection (or any other status) actually surfaces on the Timeline:
  as the current status plus, when known, the date it became current.

## Explicitly out of scope for v1

- Recovering a transition date for a status that was already set
  before `status_history` shipped. There is no reliable signal for
  when an existing `manual_status` value was actually set — the table
  only answers "when did this become X" for changes made after it
  exists. `current_status_date_known` is `False` in that case, and the
  UI must say the date is unknown rather than guess or backfill one.
- Any status other than the item's current effective status appearing
  as its own Timeline entry (no "was interviewing, now rejected" two-
  line history in v1 — only the latest transition to the current
  status is surfaced).
- The archive/lifecycle engine, deferred since Checkpoint 1.

## Ordering and tie-breaking

Document-derived events sort chronologically by detected date. When
two events land on the same date, `application_confirmation` sorts
before `interview_notice` (reads naturally as "applied" before
"interview scheduled" for a same-day pair), with relpath as the final
deterministic tiebreak. The "Current status" entry is always rendered
as the last/latest line, separately from the document-derived list,
since it represents the item's present state rather than a dated
historical document.

## `status_history` table contract

- Append-only. A row is inserted only when the effective status
  (`manual_status` if set, else auto-detected) actually changes from
  its previous value — saving the same status again is a no-op and
  does not insert a duplicate row (`append_status_history`'s
  no-op-on-repeat-save behavior; see
  `test_repeated_save_of_same_status_does_not_duplicate_history`).
- The most recent row matching a given status is that status's
  transition date (`get_latest_status_change`), which correctly
  returns the *second* occurrence of a status after a re-open (e.g.
  rejected → interviewing again).
- A "reset to auto" action is itself logged as a real transition (to
  whatever the auto-detected status resolves to), not treated as a
  null/no-op — so the Timeline never has a silent gap where the
  status pill visibly changes but no event explains why.
- Deleting an item's overrides (`delete_status_history`) also clears
  its status_history rows, so a removed application doesn't leave
  orphaned history behind.

## Known limitation carried into Item 7 v1

The identical-status-saved-twice no-op case is exercised at the unit
level (`test_repeated_save_of_same_status_does_not_duplicate_history`)
but has not been independently isolated in a manual packaged-app UI
test — a real click-through covered two *distinct* transitions
(Applied → Interviewing → Applied) rather than the narrower "save the
same status twice in a row" case specifically. See
`docs/ITEM7_TIMELINE_DEV_LOG.tex` for the full verification record.
