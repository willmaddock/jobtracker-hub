# Item 8D — DMG: Mounted Volume Gets the Real App Icon: IMPLEMENTED

## Why this item exists

`assets/icon.icns` was only ever applied to the `.app` bundle itself.
Both the unmounted `JobTracker Hub.dmg` file and the mounted volume
Finder shows after double-clicking it (the "JobTracker Hub" item in the
install window) fell back to macOS's generic disk-image icon, since
nothing in `scripts/package-dmg.sh` ever told Finder otherwise.

## What this item contains

**`scripts/package-dmg.sh`**
- After mounting the temporary read-write dmg, copies `assets/icon.icns`
  in as the volume's `.VolumeIcon.icns`, marks it invisible, and sets the
  "has custom icon" Finder flag on the mount point via `SetFile` (part of
  the Xcode Command Line Tools) -- the standard mechanism Finder uses for
  a folder/volume's custom icon. Guarded behind `command -v SetFile` and
  an `assets/icon.icns` existence check, each with a warning instead of
  aborting the build, since this is cosmetic and shouldn't be able to
  break packaging.
- The *outer*, unmounted `.dmg` file's own icon is a different mechanism
  (a single file's custom icon, not a folder/volume's) and needs
  `Rez`/`DeRez` rather than `SetFile` -- not scripted here. Set it by hand
  instead: open `assets/icon.icns` in Preview, Select All + Copy, then
  Get Info on the built `.dmg`, click its icon well, and Paste.
- Only affects *newly built* dmgs -- rerun `./scripts/build-macos.sh`
  then `./scripts/package-dmg.sh` to get the new icon; it does not
  retroactively change a `.dmg` already sitting on someone's Desktop.



## Why this item exists

In the packaged desktop app, clicking a link rendered *inside* a PDF in
the in-app viewer (e.g. "review the full job description here" inside a
`Job Bulletin.pdf`) navigated the app's own native window to that
external site, in place, with no back/forward chrome anywhere in this
frameless app to escape it. The app's own React UI already routes
external links through `openExternalUrl()` -> `POST /api/open-url` (see
`_app/frontend/index.html` and `_app/api.py`), but a PDF opened in the
native WebKit/WebView2 PDF viewer is opaque to that JS entirely, so links
inside it bypassed the guard completely. Confirmed only on macOS
(WKWebView); the underlying pywebview behavior is not platform-specific.

## What this item contains

**`desktop/launcher.py`**
- New `_guard_external_navigation(window, port)`: subscribes to
  `window.events.loaded`, which pywebview fires after *every* successful
  navigation (not just the first). When a load lands outside the app's
  own local origin, it hands that URL to the existing `/api/open-url`
  endpoint (same OS-opener path the rest of the app already uses) and
  immediately snaps the window back to the app's own root — no
  per-page special-casing needed, since it catches any external link
  from anywhere inside the shell, not just the one from this report.
- Wired into both places a main app window gets created: the normal
  launch path in `main()`, and the window swap in
  `Api.confirm_first_run_link()` after first-run setup.
- Also sets `webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True`
  as defense in depth for `target="_blank"` links, which pywebview can
  redirect to the OS browser itself before a popup window ever opens —
  a different code path from the same-window navigation the new guard
  handles.



## Why this item exists

The switcher's three creation/import actions (Create, Import, Link)
had grown disconnected from how people actually think about starting
a tracker. This item regroups them by intent, and closes the one path
where switching browsers mid-import could silently drop notes,
statuses, and dates.

## What this item contains

**`_app/frontend/index.html`**
- The switcher popover and the first-run onboarding screen now group
  their three actions under three intent-based labels instead of
  their old technical names: **Start Fresh** (was "Create New
  Tracker"), **Bring In a Copy** (zip or folder, folder as a
  sub-choice), and **Use This Folder As-Is** (was "Use an Existing
  Folder"; desktop/packaged only, link-based, unchanged visibility
  rule).
- The browser-only portability warning — telling people a plain
  folder copy in a non-Chrome browser can lose notes/statuses/dates —
  now renders as static text next to "Choose a folder instead"
  *before* the folder picker opens, rather than after the person has
  already made the lossy choice.
- New **`ChromeHandoffModal`**: offered when a folder (not zip) is
  picked for "Bring In a Copy" in a non-Chrome browser without an
  existing `.jobtracker` marker. An early version tried a
  `googlechrome://` deep link to jump straight to Chrome; that scheme
  turned out to be dead on current Safari/macOS (it throws a visible
  "address is invalid" system alert instead of silently no-op'ing), so
  the modal was simplified to a single reliable path: copy the
  destination URL, open Chrome yourself, paste it in, and redo the
  import there. The modal's closing button reloads the tab
  automatically once you're done, so the person isn't left staring at
  a stale, empty pipeline after finishing the import in a different
  browser window entirely.

**`_app/workspace.py`, `_app/api.py`, `desktop/launcher.py`**
- `_new_sibling_root()` used to silently increment a tracker's folder
  name (`… (2)`, `… (3)`, …) whenever it collided with an orphaned
  folder left behind by an earlier session, with no record that it
  had happened. It now returns how many collisions it stepped past,
  threaded through every create/import endpoint and surfaced to the
  person as an advisory toast — *not* an error, since the new tracker
  itself is unaffected — pointing them at Finder if the count looks
  unfamiliar. The packaged desktop's native folder-import path was
  initially missed (its bridge method discarded the result before
  this fix), then closed the same session once traced down.

## Test results

**Automated suite: 150/150 passing**, run twice by the user against
the real environment (this project's frontend has no automated test
suite of its own — the 150/150 covers the backend changes above).

**Real validation, Safari → Chrome round trip:** the first import
attempt in Safari failed partway through (the address the person was
meant to paste turned out invalid on that attempt) but still created
an empty sibling folder on disk before failing. Redoing "Bring In a
Copy" in Chrome against the same tracker name succeeded completely —
719 files carried over, with the app's own collision handling
correctly suffixing the new, complete folder as `(2)` rather than
overwriting or duplicating anything. Pipeline showed all 110 real
applications afterward with notes, statuses, and dates intact.

## Known limitations

- The five pre-existing stale sibling folders that predate this fix
  (testing debris from this same session) are not cleaned up
  automatically — deleting them is a manual step for the user
  whenever convenient.
- The manufactured-collision scenario that proves the advisory toast
  fires was only exercised on the two browser-facing import paths, not
  re-run specifically against the packaged desktop's native path after
  its bridge fix — that path is confirmed not to error, but hasn't
  independently produced the toast itself yet.
- Carries forward all prior items' limitations unchanged.

## Continuation context

- **Item 8B is sealed.** Item 7 (Timeline) below remains sealed and
  unaffected.
- **Item 8 (Lifecycle & Outcome Tracking) remains paused**, design-only
  — see `HANDOFF.md` §23 and `ITEM8_LIFECYCLE_OUTCOME_FDD_DRAFT.md`.
- **Git has not been committed or pushed.** Committing this
  documentation update alongside the already-implemented code changes
  is still the user's own next step.

## Full development log

`HANDOFF.md` §18–22 is the cumulative, session-by-session version of
this same work; §24 seals it.

---

# Item 7 — Application Timeline: IMPLEMENTED + TESTED + REAL PACKAGED-APP VERIFIED + SEALED

## Why this item exists

Checkpoint 6 of Item 6 (Auto-Fill Date Applied) left "Timeline view" as
the recommended next feature: showing the shape of an application's
life — applied, interviewed, resolved — from evidence the app already
has, rather than anything the user has to type. Full scope definition:
[`ITEM7_TIMELINE_FDD_DRAFT.md`](ITEM7_TIMELINE_FDD_DRAFT.md).

## What this item contains

**`_app/dossier.py`**
- `assemble_dossier()` now also returns `timeline_events`: one entry
  per `application_confirmation`/`interview_notice` document with a
  detected date (`TIMELINE_EVENT_DOC_TYPES`), each event carrying its
  `date`, `doc_type`, and source `relpath`. Every matching document
  gets its own event — never merged — so a folder with a phone-screen
  request *and* a later interview request shows both. Reuses the
  per-document `detected_date_applied` `extract.py` already computes
  for every document; no new extraction logic. Events sort
  chronologically, with `application_confirmation` breaking same-date
  ties before `interview_notice`, relpath as the final tiebreak.
- Rejection is deliberately **not** a doc-derived event (the real
  corpus has effectively no standalone rejection documents) — it
  surfaces instead through the item-level "Current status" entry
  described below.

**`_app/overrides_store.py`**
- New append-only `status_history` table: one row per real status
  transition (`item_key`, resulting effective `status`, `changed_at`,
  `source`). Saving the same status again is a no-op — no duplicate
  row — verified by
  `test_repeated_save_of_same_status_does_not_duplicate_history`.
  `append_status_history`, `get_status_history`, and
  `get_latest_status_change` (returns the *most recent* row matching a
  given status, correctly distinguishing a re-opened application from
  its first pass through that status) are the new public functions.
  `delete_status_history` clears an item's rows when its overrides are
  deleted, so removed applications don't leave orphaned history.
- Only covers changes made after this table shipped — it has no way to
  retroactively recover a transition date for a status that was
  already set earlier. This is by design; see the FDD draft.

**`_app/api.py`**
- `save_override()` and `bulk_override()` both log a `status_history`
  row whenever the effective status actually changes (including a
  "reset to auto" action, which is itself a real logged transition,
  not a silent gap).
- `/api/applications/{item_id}/dossier` now also returns
  `current_status`, `current_status_date` (the `YYYY-MM-DD` from the
  latest matching `status_history` row, via `get_latest_status_change`),
  and `current_status_date_known` (`False`, with `current_status_date`
  `None`, when no history row exists for the current status — e.g. a
  status set before this table existed). The UI must say the date is
  unknown in that case rather than guess or backfill one.
- Deleting an item's overrides also deletes its `status_history` rows
  (`delete_status_history`), keeping the two tables consistent.

**New tests**
- `tests/test_timeline.py` (7 tests) — confirmation-only events,
  interview-only events, multiple interview documents each producing
  their own event, chronological sort across doc types, same-date
  tiebreak ordering, an empty timeline when no dated evidence exists,
  and `timeline_events` appearing alongside Checkpoint 6's
  `date_applied` auto-fill in the same dossier response without
  disturbing it.
- `tests/test_status_history.py` (14 tests) — direct unit tests of the
  new `overrides_store.py` functions (table creation, append/get,
  no-duplicate-on-repeat-save, transition sequencing, latest-match
  lookup including the re-opened-status case, no-history-recorded
  case) plus end-to-end tests through the real API covering
  `save_override`/`bulk_override` logging, the "reset to auto"
  transition, and `current_status_date_known` honestly reporting
  `False` for a pre-existing status with no recorded history.

## Test results

**Automated suite: 144/144 passing**, including the 21 new Item 7
tests above (135 pre-existing plus the incremental checkpoints
building to 144 — see `docs/ITEM7_TIMELINE_DEV_LOG.tex` for the full
per-checkpoint count history). Run for real against the FastAPI
`TestClient`, not simulated — this closeout session itself has no
network access to install `pytest`/`fastapi`/`httpx` to reproduce that
run directly, so the 144/144 figure is carried forward from the real
run performed against the actual working environment, consistent with
how Checkpoints 3 and 6 handled the same sandbox constraint.

**Real packaged-app validation was completed against the real
Working_DB tracker**, distinct from and in addition to the automated
suite:

- Confirmation-only timeline test: passed.
- Confirmation + interview timeline test: passed.
- Multiple-interview handling (a folder with more than one
  interview-related document): validated, each producing its own
  timeline entry.
- A pre-existing rejection (set before `status_history` shipped)
  correctly showed an unknown status date rather than a fabricated
  one.
- Status changes persisted across a complete application quit and
  relaunch of the packaged app — the status-history row survived,
  read back from `overrides.db` on disk rather than anything held in
  memory. Confirmed twice, both times on the packaged app rather than
  the dev server.
- A real Applied → Interviewing → Applied round trip was performed and
  persisted in the packaged app, with pipeline counts moving correctly
  on both transitions and a "Saved." confirmation on each save.
- `date_applied` remained independent from interview timeline dates
  throughout — accepting or auto-filling a date-applied suggestion
  never altered or duplicated a timeline event, and vice versa.
- Checkpoint 6 behavior (date-applied auto-fill/conflict/provenance)
  remained intact and unaffected by the Item 7 additions.

**Important validation note.** During manual validation, two separate
application windows were open at once: a Safari window against the
local dev server (`127.0.0.1`), and the packaged JobTracker Hub app.
These were tracking two different, out-of-sync copies of the data —
the dev-server window's stale display behavior (e.g. a Timeline line
that didn't refresh immediately after a save) reflects that separate,
older workspace, **not** a Item 7 defect in the packaged app. Only the
**packaged application's** results are recorded above as the official
Item 7 real-app validation; the dev-server window's behavior is
excluded from these results.

## Known limitations

- **Identical-status-saved-twice, isolated as its own manual UI step,
  was not independently exercised** in the packaged-app click-through.
  The real click-through covered two genuine transitions (Applied →
  Interviewing → Applied), not a same-status-twice repeat save. The
  no-duplicate-row behavior for an exact repeat save is fully covered
  at the unit level by
  `test_repeated_save_of_same_status_does_not_duplicate_history`
  (part of the passing 144/144 run), so this is corroborating
  real-app evidence layered on an already-verified case, not the only
  evidence for it — see `ITEM7_TIMELINE_FDD_DRAFT.md`.
- Cannot recover a transition date for any status set before
  `status_history` existed — by design, not a bug; see the FDD draft
  and `current_status_date_known`.
- Rejection (and any other status) only ever appears as the single
  "Current status" line, not as a full multi-transition history on
  the Timeline itself, in v1.
- Carries forward all Item 6 / Checkpoint 1–6 limitations unchanged
  (US-format phone regex, empty-password-only PDF decryption, no
  `.docx` support, trailing-boilerplate bleed into the last-matched
  role section, arbitrary-but-deterministic alphabetical job-posting
  tiebreak, no per-document source attribution on merged contacts, no
  non-US date formats, no signal for which confirmation document's
  date wins when a folder has more than one).

## Continuation context

- **Item 7 is sealed.** Checkpoint 6 (Item 6) remains sealed and
  unaffected.
- **No Item 8 work has started.** The archive/lifecycle engine
  (deferred since Checkpoint 1) remains the next candidate scope, but
  has not been designed or begun.
- **Git has not been committed or pushed.** This closeout produced a
  documentation-only update and a clean handoff zip; committing (CP6 +
  Item 7), pushing, and building the DMG are still the user's own next
  steps against their controlled local repository.

## Full development log

`docs/ITEM7_TIMELINE_DEV_LOG.tex` (compiled: `docs/ITEM7_TIMELINE_DEV_LOG.pdf`)
is the cumulative, human-readable version of this same information,
mirroring `docs/ITEM6_DEV_LOG.tex`'s structure and conventions. Its
Next Steps box is the first thing to read at the start of any future
chat continuing this project.
