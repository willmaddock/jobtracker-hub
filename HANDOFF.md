# HANDOFF.md — JobTracker Hub

Living engineering handoff. Read this first in any new conversation continuing
this project. Update it before ending a session, especially near ~80–85%
context usage. Do not reconstruct prior conversations from scratch — this file
is the source of truth for state, findings, and next actions.

Last updated: 2026-08-30 (session 9), by Claude.

**Session 9** picked up §21's open items (the stale-sibling-folders
notice) and closed all of them: the user ran the real pytest suite
twice (150/150), tested both browser paths live, and Claude traced and
fixed the one confirmed gap — `desktop/launcher.py`'s
`confirm_import_folder()` was silently discarding the backend's
`stale_siblings_found` field for the native/packaged folder-import
path. Fixed in both `desktop/launcher.py` and
`_app/frontend/index.html`'s `confirmImportFolderNative()`, matching
the pattern already used by `doCreate()`/`doImport()`. User confirmed
the toast is correct. See §22 for the full record. Claude has not
staged, committed, or pushed anything, per §6.

**Session 7** made the first actual application-code change in this
project's handoff history: the user approved §3j's proposal and, per
§3j.7 #2's own suggestion, chose to implement the §3j.5 `.jobtracker`
link-target guard, decoupled from the rest of Item 8A. See §3k for the
full record. **The user ran the real suite themselves: 149/150 on the
first pass (§3k.5, one test-bug found and fixed), then 150/150 twice
more (§3k.6), plus manual real-app validation with no issues.** The
guard is complete and fully validated, ready for the user's own review
and commit via GitHub Desktop; Claude has not staged, committed, or
pushed anything, per §6.

**Session 8** (this update) implemented the rest of §3j — grouping/
relabeling (§3j.2), the toast-parity fix (§3j.3), and component
unification (§3j.4) — per the user's explicit approval to proceed to
that work over Checkpoint 4. See §3l for the full record.
**Frontend-only change, `_app/frontend/index.html` alone** — no
backend/API files, tests, or data touched. **Unlike the guard, this
repo has no frontend test suite, so there is no "150/150"-equivalent
result here.** Claude verified the changed file's JSX/JS is
syntactically valid (Babel transform + a structural parse check) and
grepped for dangling references to removed code, but **the app has not
been opened in a real browser or packaged build by anyone since this
change, and that is the user's necessary next step** — see §3l.3/§3l.4
for exactly what was and wasn't checked. Claude has not staged,
committed, or pushed anything, per §6.



---

## 1. Repository identity

- Repo: `jobtracker-hub` (local clone supplied as `jobtracker-hub.zip`)
- **VERIFIED** — `git status`: on branch `main`, up to date with
  `origin/main`, **working tree clean** (no uncommitted changes, nothing
  staged).
- **VERIFIED** — `git log` (most recent commits, newest first):
  1. `db16c5c` Complete Item 6 & Item 7: Application Dossier, auto-fill date
     applied, visual timeline, and status history log
  2. `387b62e` Release v1.1.0 with import feedback and updated user guide
  3. `19dd5e3` docs: user guide v1.7 — updated PDF/tex and remaining
     screenshots
  4. `281dc23` docs: user guide v1.7 — first-run preview, Search Hub, current
     tracker-creation flow
  5. `2007f9e` Update README for Items 1–5
  6. `34da885` Add preview flow for folder-copy import; persist Search Hub
     settings server-side
  7. `b798f28` Fix PDF preview download hint, ALLOW_DOWNLOADS packaging,
     gitignore workspace leakage
  8. `f3674b8` Added Contents to Readme
  9. `bbb7b83` Added build dmg instructions to README
  10. `76a859c` Add desktop packaging tooling (scripts, desktop, assets) to
      repo

> **DISCREPANCY (important) — RESOLVED session 5:** The kickoff instructions
> for session 1 stated there are "substantial uncommitted changes in the
> working tree." **This is confirmed false.** The user ran `git status`
> directly on their live local checkout (not just this ZIP) on
> 2026-08-29/30: branch `main`, up to date with `origin/main`, the only
> untracked file is `HANDOFF.md`, nothing staged, nothing modified. There
> are no uncommitted changes anywhere in the real working copy, and
> therefore no in-progress `ITEM8_LIFECYCLE_OUTCOME_FDD_DRAFT.md` exists
> locally either — it simply does not exist yet, anywhere. The original
> kickoff claim was stale or incorrect and can be disregarded going
> forward.

---

## 2. Items / Checkpoints completed (verified from repo)

- **VERIFIED** — Items 1–5: referenced in commit history and README as
  covering initial import/link/preview flow, Search Hub persistence, etc.
  Not independently re-audited line-by-line this session.
- **VERIFIED** — Item 6 (Application Dossier, auto-fill date applied) and
  Item 7 (visual timeline, status history log) are complete, per `CHANGES.md`
  ("Item 7 — Application Timeline: IMPLEMENTED + TESTED + REAL PACKAGED-APP
  VERIFIED + SEALED") and the latest commit message.
- **VERIFIED** — `ITEM7_TIMELINE_FDD_DRAFT.md` exists at repo root.
- **VERIFIED** — Full test suite: `python3 -m pytest -q` → **144 passed**,
  1 unrelated deprecation warning (starlette/httpx testclient). Matches the
  "144/144" figure `CHANGES.md` cites for Item 7's validation.

## 2a. Item 8 — status

> **DISCREPANCY (important):** The kickoff instructions describe
> `ITEM8_LIFECYCLE_OUTCOME_FDD_DRAFT.md` as an existing "design-only proposal
> for Lifecycle & Outcome Tracking" in the repository. **This file does not
> exist anywhere in the supplied `jobtracker-hub.zip`** (confirmed via
> recursive filename search and a content grep for "item 8" / "lifecycle"
> across all `.md` files).
>
> What *does* exist, verified:
> - `CHANGES.md` (end of the Item 7 section, "Continuation context"): *"No
>   Item 8 work has started. The archive/lifecycle engine (deferred since
>   Checkpoint 1) remains the next candidate scope, but has not been designed
>   or begun."*
> - `ITEM7_TIMELINE_FDD_DRAFT.md` also references "The archive/lifecycle
>   engine, deferred since Checkpoint 1" as a follow-on.
>
> So Item 8 is real as a *named future scope*, but the FDD draft document
> itself either (a) was never committed, (b) exists only in the user's local
> uncommitted work (consistent with the "substantial uncommitted changes"
> claim in section 1 — this may be exactly what those changes are), or (c)
> exists in a different location than this ZIP. **Treat "Item 8 FDD draft
> exists" as HYPOTHESIS, not fact, until confirmed against the user's actual
> working copy.**
>
> **DECISION (carried over from kickoff instructions, still binding
> regardless of the above):** Item 8 is PAUSED. Do not implement it. If/when
> its FDD draft is located or written, its open questions must be settled
> first — in particular, sourcing real `days_since_activity` data for a
> "Ghosted" threshold.
>
> **VERIFIED, and directly relevant to that open question:** `_app/db.py`
> **already computes `days_since_activity`** per application item today
> (used for the existing "stale" / Needs Attention logic, not for any
> Item-8-style lifecycle/outcome state machine). See `_app/db.py`,
> `load_applications()`:
> - Reference-date precedence: `activity_override` (explicit "reset activity
>   clock") → else `date_applied` → else `last_activity` (file mtime,
>   described in-code as "unreliable" and a last resort).
> - `_days_since()` computes whole days between that reference date and now.
> - `is_stale` is derived from `days_since_activity` against
>   `STALE_APPLIED_DAYS` / `STALE_DRAFTED_DAYS` thresholds, gated on
>   `effective_status` and not being archived.
>
> This is an existing building block, not a solved Item 8 — it doesn't
> address the "Ghosted" concept, its own thresholds, or the other two Item 8
> open questions (which were not enumerated anywhere in the supplied
> artifacts and remain **OPEN QUESTION**: their content is not established by
> this repo snapshot).

---

## 3. New priority: Tracker / J UX + Import/Export Overhaul — now **Item 8A**

**DECISION (user, session 2):** this workstream is formally named
**Item 8A — Tracker UX & Import/Export Overhaul**, distinct from and not to
be confused with **Item 8 — Lifecycle & Outcome Tracking**, which remains
frozen/paused (§2a) until Item 8A is resolved. The name "J organization" is
retired in favor of Item 8A because the investigation spans both the
frontend information architecture and the backend import/export/portability
behavior together — deliberately not being split apart prematurely.

**DECISION (user, session 2):** the handoff from session 1 is approved as a
good checkpoint document, with one correction: Checkpoint 1 was **not**
actually complete at the end of session 1 despite being labeled that way.
Session 2 (this update) closes that gap — see the new §3f **Checkpoint 1
Discovery Report** below, which formally supersedes the partial §3a–§3e
findings from session 1 (kept below for continuity/history, but §3f is now
the authoritative CP1 record).



Status: **discovery/design only, not approved for implementation.** This
session performed a first pass of Checkpoint 1-style tracing to make this
handoff accurate; it is not a complete Checkpoint 1 and should not be treated
as one.

### 3a. Verified: the five workspace entry points (backend)

All in `_app/api.py`, backed by `_app/workspace.py`:

| Endpoint | Function | Trigger (frontend) | Copies or links? |
|---|---|---|---|
| `POST /api/workspaces` | `create_workspace` | "Create New Tracker" | new, empty |
| `POST /api/workspaces/link` | `link_workspace` | native folder picker, first-run flow, desktop only | **links in place**, nothing copied |
| `POST /api/workspaces/import` | `import_workspace_from_zip` | "Import a Copy (.zip)" — file input, `accept=".zip"` | copies (from zip) |
| `POST /api/workspaces/import-folder` | `import_workspace_from_files` | "Import a Copy of a Folder" — browser `webkitdirectory` picker | copies (via HTTP upload of every file) |
| `POST /api/workspaces/import-folder-local` | `import_workspace_from_local_folder` | desktop native `FOLDER_DIALOG` → `Api.confirm_import_folder` | copies (direct filesystem read, no upload) |
| `GET /api/workspaces/{id}/export` | `export_workspace_to_zip` | "Export as zip" (per-tracker) | reads only, streams a zip |

So there are **4 distinct creation/import actions** exposed in the UI today
(New, Import zip, Import folder, Link folder), matching the kickoff
instructions' observation that the current experience "combine[s] too many
concepts." This is **VERIFIED**, not assumed.

### 3b. Verified: the `.jobtracker` claim — traced, and it does NOT match the
kickoff description

The kickoff instructions describe a user observation: *"the UI can allow a
`.jobtracker` file to be selected through a file-oriented workflow, while the
backend does not appear to actually import the `.jobtracker` in the same way
that ZIP import works,"* and explicitly warned not to assume this is
correct. It was traced. Findings:

- **VERIFIED** — `.jobtracker` is **not a file type or file extension**
  anywhere in this codebase. It is the name of a **hidden folder**
  (`OVERRIDES_DIRNAME = ".jobtracker"` in `_app/workspace.py`) that lives
  inside a tracker's root, containing `overrides.db` (and, per the supplied
  database ZIP, also `jobtracker.db` — see §4). It is directly analogous to
  a `.git/` folder.
- **VERIFIED** — Every file-picker in the frontend that accepts a single
  file is hard-restricted to `.zip`: both `<input type="file" accept=".zip">`
  occurrences in `_app/frontend/index.html` (workspace switcher's import
  flow, and the first-run/no-workspace-yet flow) only accept `.zip`. Neither
  accepts `.jobtracker` or any other extension. Drag-and-drop onto the import
  zone is likewise hard-checked against `f.name.toLowerCase().endsWith(".zip")`
  and rejects anything else with an explicit error message.
- **VERIFIED** — There is no native (`pywebview`) open/import file dialog in
  `desktop/launcher.py` at all — only a native **folder** dialog
  (`FOLDER_DIALOG`, used for link/import-folder) and a native **save**
  dialog (`SAVE_DIALOG`, used for zip export). Zip *import* on desktop still
  goes through the same in-page `<input type="file" accept=".zip">` as the
  browser build; there is no separate native zip-open dialog that could have
  a looser filter.
- **CONCLUSION:** the specific concern as originally phrased — a `.jobtracker`
  *file* being selectable through a file-oriented workflow — does not appear
  to be correct as a literal description of the current code. No UI surface
  found lets a user pick a `.jobtracker`-named item as an importable file.
  It is possible the user's observation refers to something adjacent (e.g.
  seeing a `.jobtracker` folder while using "Import a Copy of a Folder" or
  the native folder picker, since both of those *do* traverse into it — see
  §3c), or to a different build than this snapshot, or to work-in-progress
  local changes not present in this ZIP (see §1's discrepancy). **This
  should be confirmed directly with the user before further design work
  assumes either explanation.** Flagging as **OPEN QUESTION**, not resolved.

### 3c. Verified: `.jobtracker` portability is inconsistent across the four
entry points — this is likely closer to the real underlying issue

Traced `_resolve_import_dest()` and `export_workspace_to_zip()` in
`_app/workspace.py`. `.jobtracker/` (specifically `overrides.db`, i.e. notes,
manual statuses, dates, aliases, status history) is normally excluded by the
app's ignore rules (`should_ignore()` — dotfiles and `.db` files are both
normally filtered), but is **deliberately exempted** so it round-trips. That
exemption is applied consistently in the code that has it — but not every
entry point exercises that code path the same way, and one path has a
**browser-imposed limitation the app cannot work around**:

| Path | Carries `.jobtracker/overrides.db`? | Why |
|---|---|---|
| Export → zip | **Yes** | `export_workspace_to_zip` explicitly special-cases `OVERRIDES_DIRNAME` past `should_ignore()`. |
| Import zip | **Yes** | `_resolve_import_dest` exempts `.jobtracker/...` paths the same way. |
| Import folder (desktop native `FOLDER_DIALOG` → `import_workspace_from_local_folder`) | **Yes** | Uses `Path.rglob("*")` on the real filesystem, which sees hidden dotfiles fine, then the same `_resolve_import_dest` exemption applies. |
| Import folder (browser `webkitdirectory` picker → `import_workspace_from_files`) | **No** | Browsers do not include dotfiles/hidden folders in a `webkitdirectory` folder selection at all — the file list handed to the app from the browser never contains `.jobtracker/...` in the first place. This is a **browser API limitation**, not an app bug: the app's own code has nothing to exempt because it never receives those files. The frontend already surfaces a warning for this case ("Files were imported, but any existing notes, statuses, or dates didn't come across — browsers can't include hidden files in a folder upload. Export a .zip from the original tracker for a complete copy."). |

**This asymmetry — not a `.jobtracker`-as-file confusion — is the
concretely verified gap.** Three of four creation paths preserve notes/
status/dates; one (browser folder import) silently cannot, for reasons
outside the app's control, and the only mitigation today is a warning
message after the fact rather than the UI steering the user toward zip
import up front when portability matters. This seems like a strong
candidate for the real UX problem underlying the user's observation, but
should be confirmed with the user rather than assumed as the final
diagnosis. **HYPOTHESIS.**

### 3d. Verified: current workspace-switcher status surface

`_app/frontend/index.html`'s workspace popover (`workspace-status-card`)
already shows, per active tracker: a `LINKED FOLDER` vs
`JOBTRACKER-OWNED COPY` badge, a document count, a
"✓ Notes stored with tracker" / "Notes not saved yet" indicator (driven by
`has_portable_overrides`), and the full root path. This exists today and is
not itself broken — it's a plausible seed for the "My Trackers" /
"Actions" grouping sketched in the kickoff instructions, rather than
something that needs to be built from scratch. **VERIFIED**, useful context
for Checkpoint 3.

### 3e. Not yet done *(as of session 1 — closed out in §3f, session 2)*

- Backend endpoint tests were read (function names only) for confidence they
  exist and roughly what they cover; they were **not** re-executed
  individually beyond the full-suite run in §2, and their assertions were
  **not** individually re-verified line by line this session.
- `_app/overrides_store.py`'s full schema/API surface was only skimmed via
  its role in `db.py` (`ov.get_all_overrides`, `ov.get_aliases`), not fully
  read end to end.
- The desktop `first_run.html` flow (separate from the in-app switcher) was
  not traced this session beyond confirming `launcher.py`'s `Api` methods it
  calls.
- No frontend information-architecture options have been designed. That is
  explicitly out of scope until Checkpoint 3.

---

## 3f. Checkpoint 1 Discovery Report — Item 8A (session 2, formal, complete)

This section is the authoritative Checkpoint 1 record for Item 8A. It
completes every item listed in §3e and §8 from session 1. Still
discovery-only: no application code, tests, or data were modified; nothing
was staged, committed, or pushed.

### 3f.1 VERIFIED — Backend architecture (workspace lifecycle)

Six user-facing entry points feed into **five** backend code paths:

| Trigger (frontend/desktop) | Endpoint | `workspace.py` function | Copy or link? | `.jobtracker/overrides.db` carried? |
|---|---|---|---|---|
| "Create New Tracker" | `POST /api/workspaces` | `create_workspace` | new, empty | n/a (nothing to carry) |
| Desktop first-run (`first_run.html`) **and** in-app "Use an Existing Folder" (`WorkspacePopover.confirmLinkFolderNative`) | `POST /api/workspaces/link` | `link_workspace` | **links in place** | n/a — reads/writes the original folder's own `.jobtracker/` directly, nothing to "carry" |
| "Import a Copy (.zip)" | `POST /api/workspaces/import` | `import_workspace_from_zip` | copy | **Yes** |
| "Import a Copy of a Folder" — browser `webkitdirectory` picker | `POST /api/workspaces/import-folder` | `import_workspace_from_files` | copy | **No** — browser API limitation, not app code (§3f.3) |
| "Import a Copy of a Folder" / "Choose a folder instead" — desktop native `FOLDER_DIALOG` | `POST /api/workspaces/import-folder-local` | `import_workspace_from_local_folder` | copy | **Yes** |
| Per-tracker "Export as zip" | `GET /api/workspaces/{id}/export` | `export_workspace_to_zip` | read-only, streams a zip | **Yes** |

Confirmed **two separate frontend implementations** of the same
pick-folder→inspect→confirm sequence for both "link" and "import folder
(native)": `WorkspacePopover` (in-app, once a tracker already exists) and
`NoTrackerOnboarding` (shown only when there is no active tracker yet, i.e.
first browser-mode use or a from-scratch registry). Both call the exact same
desktop bridge methods (`pick_folder`, `inspect_folder`,
`confirm_link_folder`, `confirm_import_folder`) and both use the same shared
pure function `describeFolderInspection()` for the preview text, so the
*logic* isn't duplicated, but the *component code* (state, JSX, preview
rendering) is duplicated almost line-for-line between the two React
components. Not a bug, but a real maintenance-cost/consistency finding
relevant to Checkpoint 3 (a redesign should probably unify these two
surfaces rather than have Checkpoint-4 changes applied twice).

`desktop/launcher.py`'s `Api` class is a thin bridge: `pick_folder`
(native `FOLDER_DIALOG`), `inspect_folder` (proxies to
`POST /api/workspaces/inspect`), `confirm_first_run_link` /
`confirm_link_folder` (both call `POST /api/workspaces/link`),
`confirm_import_folder` (calls `POST /api/workspaces/import-folder-local`),
and `export_workspace` (native `SAVE_DIALOG` + a direct HTTP fetch of the
export endpoint, bypassing the browser's blob-download trick because
WKWebView silently no-ops on synthetic `<a download>` clicks — documented
in-code as a real, previously-hit bug, not a hypothetical). There is **no**
native *open*/import dialog for zip files — zip import always goes through
the in-page `<input type="file" accept=".zip">`, on both browser and
desktop builds.

### 3f.2 VERIFIED — `overrides_store.py`, read end to end

Single SQLite file (`overrides.db`, living inside the tracker's own
`.jobtracker/` folder — see `workspace._portable_ov_db_path`), separate from
the disposable, rebuildable `jobtracker.db` search index. Seven tables:

- `item_overrides` — one row per application `item_key`: `manual_status`,
  `notes`, `date_applied` (+ `date_applied_source` provenance),
  `next_action`/`next_action_date`, `archived`, `snoozed_until`,
  `activity_override` (the "reset activity clock" date that feeds
  `db.py`'s `days_since_activity` — see §2a). Upserted via `upsert_override`
  (merge-in-place semantics: only fields actually sent overwrite existing
  ones... actually fully replaces every column with the merged dict on
  every call, keyed by `item_key`).
- `company_aliases` — raw folder/company name → canonical display name
  (the "merge companies" feature).
- `document_overrides` — per-file `doc_type_override` correction
  (resume-vs-cover-letter disambiguation when a filename alone can't tell);
  never touches the file on disk.
- `hub_settings` — single-row (`id=1`) table for role/location/custom
  links/custom cards for the Search Hub. Explicitly migrated out of
  `localStorage` specifically so it would travel with the tracker like
  everything else in this file (i.e. this table's whole reason for existing
  is portability — directly relevant to Item 8A).
- `folder_overrides` — per-top-level-folder archive/delete flag, keyed by
  folder name (or a two-part `Applications/<subfolder>` path for the
  compliance-nested case), independent of section grouping.
- `document_extractions` — a content-hash-keyed cache of `extract.py`'s
  parsed output (emails/phones/urls/etc.), versioned by
  `extractor_version` so logic changes invalidate stale entries
  automatically. Not user data in the "your notes" sense, but still lives
  here (and thus travels with export/import) rather than in the
  disposable index.
- `status_history` — append-only log added in Item 7; one row per real
  status transition, no-op on a repeat save of the same status (tested,
  see §3f.4). This is the table whose presence in the supplied database
  proved post-Item-7 usage (§4).

`get_conn()` lazily creates `.jobtracker/` and the schema on first touch —
confirmed by `test_workspace_list_includes_kind_and_overrides_flag`: simply
calling `GET /api/applications` on a freshly linked, notes-free folder is
enough to flip `has_portable_overrides` to `true`, because reading
applications touches `overrides_store.get_conn()` even if nothing is
written. **This means `has_portable_overrides: true` (and, by extension, the
supplied database's `.jobtracker/overrides.db` existing at all) does not by
itself prove the user entered any notes** — only that the app was opened
against that folder at least once after linking. The populated
`status_history` table found in the supplied database (§4) is the stronger
signal of actual real usage, since that table is never written except by an
explicit status change.

`_migrate()` handles two additive schema migrations
(`activity_override`, `date_applied_source` columns) for pre-existing
`overrides.db` files — relevant if Item 8A ends up touching this schema
further: there's already a working, tested pattern for additive migrations
to follow, but no pattern yet for anything more invasive (column removal,
table restructuring).

### 3f.3 VERIFIED — `desktop/first_run.html`, traced

Static HTML/JS page (no React, no build step), shown only when
`GET /api/workspaces` reports `active: None` (`_needs_first_run` in
`launcher.py`) — i.e. only ever the very first tracker on a fresh install,
never shown again once any tracker exists. Its only path is
pick→inspect→confirm-**link** (`pick_folder` → `inspect_folder` →
`confirm_first_run_link`, which is a thin wrapper around the same
`POST /api/workspaces/link` call `confirm_link_folder` makes). It has
**no** import option at all (no zip, no copy-folder) — the in-page copy
explicitly says so ("You can add more trackers for other folders later, or
import a tracker .zip, from the sidebar once you're in"). So the very first
run only ever offers "point at a folder in place"; "start empty" and
"import a copy" are only reachable after that first tracker exists (via
`NoTrackerOnboarding`, which is the browser/no-active-tracker path, or the
in-app `WorkspacePopover`). This first-run window is deliberately small,
fixed-size initially, then destroyed and replaced by a full 1200×800 window
for the real app on success (`confirm_first_run_link`'s comment explains
pywebview can't resize a window after creation, so swapping windows was the
chosen workaround for a real prior bug — a blind-linked wrong/empty folder
with zero warning, per the file's own comments).

### 3f.4 VERIFIED — actual test assertions (not just names) for all five requested files

- **`test_export.py`** (3 tests): confirms the exported zip is genuinely
  valid (`zf.testzip() is None`, real CRCs), contains real file bytes
  (`resume.pdf` starts with `%PDF`), a bad workspace id is a clean 400 not
  a 500, and export never mutates the source folder (before/after file
  listing diff).
- **`test_import_local_folder.py`** (8 tests): confirms native local-folder
  import genuinely copies (new root ≠ source root, files exist at both
  locations), never modifies the source, rejects a missing or empty source
  folder with 400, correctly imports from a folder that's *also* currently
  linked elsewhere as a different tracker (import and link are
  independent — a folder can be both linked *and* separately imported-as-copy
  at the same time), strips the app's own `"JobTracker — "` naming prefix
  so re-importing an owned tracker's folder doesn't double it, and lands
  under the (test-redirected) owned-siblings directory.
- **`test_overrides_portability.py`** (4 tests) — the most directly
  relevant file to Item 8A:
  - `test_unlinking_and_relinking_the_same_folder_keeps_notes`: write a
    note, delete (unlink) the workspace entry, confirm
    `.jobtracker/overrides.db` **still exists on disk untouched**, re-link
    the same folder as a brand-new workspace id, confirm the note is still
    readable. This is the clearest proof that "unlink" is a registry-only
    operation, never a data-destroying one.
  - `test_legacy_overrides_db_is_migrated_into_the_tracker_folder`: proves
    there's automatic, silent migration logic for workspace entries whose
    `overrides.db` still lives at the *old* pre-portability location
    (this app's own private storage, keyed by workspace id) — the very
    next read moves the file into the portable `.jobtracker/` location and
    updates the registry, with no user-visible prompt. Confirms this
    codebase has already solved one prior "notes got orphaned from the
    folder" class of bug, which is useful precedent for Item 8A.
  - `test_export_then_import_round_trips_notes_and_status`: **directly
    confirms** `.jobtracker/overrides.db` is present by name in the
    exported zip's `namelist()`, and that re-importing that zip
    reconstructs the exact same notes/status. This is the strongest
    existing automated evidence that zip import/export is lossless for
    portable state.
  - `test_export_then_import_round_trips_hub_settings`: same round-trip
    guarantee, specifically for the Search Hub role/location settings
    table.
- **`test_workspace_inspect.py`** (11 tests): confirms `/api/workspaces/inspect`
  never 500s on a missing/non-folder path (reports `exists: false` instead);
  correctly detects an empty folder, a "tracker-shaped" folder (has
  `Applications/` etc.), a folder with real files that doesn't match any
  known section, and a hidden `.jobtracker/overrides.db`'s presence
  (`has_portable_overrides`) **without that hidden folder counting toward
  the visible file count**; correctly flags a folder that's already linked
  as a different tracker (and correctly does *not* flag an unrelated
  folder); caps the file count on a huge folder rather than scanning
  forever; and confirms `kind` (`"linked"` vs presumably `"owned"`) and
  `has_portable_overrides` both surface through `/api/workspaces` (list)
  and `/api/status` (active one).
- **`test_workspaces.py`** (9 tests): core lifecycle — link builds the
  index and becomes active immediately; rejects a nonexistent folder or a
  duplicate tracker name (400s, not crashes); switching between two linked
  workspaces actually changes which one `/api/status` reports; switching to
  an unknown id is rejected; rename updates both the registry and the
  active status; deleting a **linked** workspace removes only the registry
  entry — the real folder and its files are explicitly asserted to survive
  untouched; creating a brand-new tracker lands under the (redirected, in
  tests) owned-siblings directory with an empty `Applications/` folder and
  `doc_count: 0`.

No gaps or contradictions were found between what the tests assert and what
the traced `workspace.py`/`api.py` code actually does — the test suite's
claims in §3f.1's table (which entry points copy vs. link, and which carry
`.jobtracker/` across) are independently corroborated here, not just
inferred from code comments.

### 3f.5 VERIFIED — frontend J/workspace state & actions, fully mapped

**Two components own all tracker creation/import/link UI**, both driven by
the same `describeFolderInspection(inspection, mode)` pure function for
preview text (`mode: "link"` = hard-blocks an already-linked folder;
`mode: "import"` = soft-warns on one, since importing-as-copy from an
already-linked folder is harmless and produces two independent trackers —
confirmed by `test_import_local_folder_from_an_already_linked_folder_still_succeeds`):

- **`WorkspacePopover`** — the in-app switcher (opened from the rail/"J"
  logo). Renders: a live status card for the *active* tracker (`LINKED
  FOLDER` vs `JOBTRACKER-OWNED COPY` badge, doc count,
  "✓ Notes stored with tracker" / "Notes not saved yet", full root path);
  a scrollable list of every tracker with switch/rename/export/delete
  actions per row (export and delete both show a `spinning` CSS class on
  their icon while busy — this is the "spinning/active indicator" the
  kickoff instructions flagged as not-necessarily-a-problem; it's scoped
  per-row-per-action, not a global ambiguous spinner); then three
  bottom-anchored inline-expanding action rows: "Create New Tracker",
  "Import a Copy" (which itself branches into a `.zip` dropzone/file-input
  **or** a "Choose a folder instead" native-preview sub-flow, both writing
  into the same `doImport()`/`confirmImportFolderNative()` submit paths),
  and (desktop-only) "Use an Existing Folder" (native link, own
  pick→inspect→confirm preview state). All three of these expand *in
  place* inside the same small popover — this is the concrete UI
  manifestation of "too many concepts in one place" the kickoff
  instructions described, now precisely located rather than just
  characterized.
- **`NoTrackerOnboarding`** — shown instead of the main app whenever there
  is no active tracker (fresh install in browser mode, or a wiped
  registry). Same four actions (Create / Import zip / Import folder
  native / Link folder native), same preview components, but laid out as a
  single vertical button stack on a dedicated centered card rather than
  inside a popover — structurally a near-duplicate of `WorkspacePopover`'s
  bottom section (§3f.1 already flagged the code-duplication angle).
- **Desktop `first_run.html`** (§3f.3) — a third, non-React surface with
  only the "link" action, shown exactly once (very first tracker only, and
  desktop-only).

**Post-action feedback:** `IMPORT_NOTICE_KEY` (sessionStorage, read once on
next load then cleared) drives a dismissable toast after a reload triggered
by import: `"zip-success"` → *"Zip successfully imported with all notes,
statuses, and dates preserved."*; `"folder-warning"` → *"Files were
imported, but any existing notes, statuses, or dates didn't come across —
browsers can't include hidden files in a folder upload. Export a .zip from
the original tracker for a complete copy."* This toast is **only wired up
for the two `WorkspacePopover.doImport()` / `NoTrackerOnboarding.doImportZip()`
paths** (zip upload and browser-`webkitdirectory` folder upload). The two
**native** desktop import/link confirm functions
(`confirmImportFolderNative`, `confirmLinkFolderNative`, in both
components) reload on success but **never set `IMPORT_NOTICE_KEY`** — so a
successful native folder import (which, per §3f.1, *does* carry
`.jobtracker/overrides.db` across losslessly) gets no success toast at all,
while the browser folder import that *can't* carry it across does get an
explicit warning toast. **OPEN QUESTION / minor finding:** whether this
asymmetry (silence on the path that works fully vs. an explicit warning on
the path that partially works) was deliberate or just an oversight — worth
raising in Checkpoint 3, since consistent, honest feedback across
equivalent-looking buttons is exactly the kind of thing Item 8A is meant to
fix.

**Existing status surface** (already noted in session 1's §3d, confirmed
again here): the `workspace-status-card` in `WorkspacePopover` already
shows kind/doc-count/notes-portability/path for the active tracker. This
is a real, working building block — Checkpoint 3 should treat it as
something to extend/reorganize, not something to design from a blank page.

### 3f.6 What's actually wrong vs. merely confusing (synthesis)

**Actually wrong / a real functional gap:**
- Browser (non-desktop) folder import cannot carry `.jobtracker/overrides.db`
  across, for reasons outside this app's control (browser dotfile
  exclusion in `webkitdirectory`) — but the UI treats this the same as any
  other import button up front, and only reveals the limitation via a
  toast *after* the import has already happened and the page has reloaded.
  A user who wanted their notes preserved has no way to know that *before*
  choosing this button over "Import a Copy (.zip)".
- The success/warning toast asymmetry in §3f.5 between native and browser
  folder-import paths.

**Confusing, but not incorrect:**
- Four/five creation-or-import actions (Create, Import zip, Import folder
  [browser or native — same button, different underlying mechanism
  depending on `packaged`], Link folder [desktop-only]) are all exposed as
  peers in the same small space, with no grouping by what they actually do
  (start empty vs. bring in existing content vs. point at content in
  place) or by portability consequence (which ones keep your notes).
- The `.jobtracker` folder itself is invisible/undocumented to the end
  user anywhere in the UI — its existence is only ever implied indirectly
  via the "Notes stored with tracker" indicator, never named. This is
  probably fine (it's meant to be an implementation detail, like `.git`),
  but is worth an explicit design decision in Checkpoint 3 rather than
  leaving it as an accident of what wasn't built.
- Two structurally-duplicated React components (`WorkspacePopover`,
  `NoTrackerOnboarding`) implementing the same four actions differently
  laid out, which increases the risk that a Checkpoint 4/6 change gets
  applied to one and forgotten in the other.

**Not found to be a real problem:**
- The `.jobtracker`-as-a-selectable-file claim from the original kickoff
  (§3b, session 1) — reconfirmed absent in this deeper pass; no new
  evidence for it turned up while reading `overrides_store.py`,
  `first_run.html`, or the full test bodies.
- The spinning/loading indicators themselves — each is scoped to a single
  row/action (export busy, delete busy, "Looking…" during a folder
  preview lookup), not a global or ambiguous state indicator.

### 3f.7 Constraints to preserve into Checkpoint 2+

- Every existing round-trip guarantee in §3f.4 (unlink/relink,
  legacy-path migration, zip export→import, hub-settings round-trip) is
  covered by a passing automated test today. Any redesign must keep these
  passing (or deliberately, visibly update the corresponding test with the
  same intent) — not just "not break the UI."
- `.jobtracker/overrides.db`'s exemption from `should_ignore()` in both
  import and export is the single mechanism every portability guarantee
  depends on. Any Checkpoint 4 change to import/export behavior needs to
  either keep this exemption intact or replace it with something that
  preserves the same three currently-lossless paths (zip, native folder
  import, link-in-place) without regressing them.
- The "linked" vs "owned/copy" distinction (`kind` field) is structural,
  not cosmetic: linked workspaces' folders are never touched by delete;
  owned ones are sent to Trash. Any IA redesign that blurs this distinction
  in the UI must not blur it in the underlying delete behavior.
- The legacy-`overrides.db`-location migration path (§3f.4) is silent and
  automatic today. If Item 8A changes where `.jobtracker/` lives or how
  it's discovered, this migration pattern (and its test) is the template
  to extend, not something to route around.

### 3f.8 OPEN QUESTIONS carried into Checkpoint 2

1. What exactly was observed that read as "a `.jobtracker` file being
   selectable through a file-oriented workflow" (unresolved from session 1,
   still unresolved after this deeper pass — see §3f.6). **RESOLVED,
   session 5 — see §3h.** Confirmed via user screenshots: the native
   folder-picker used by "Link"/"Import folder" is an unfiltered OS
   file-system browser that exposes `.jobtracker` as a selectable folder
   when hidden files are visible in Finder.
2. ~~Whether the local working copy currently has uncommitted changes, and
   if so, whether an Item 8 FDD draft is among them~~ — **RESOLVED, session
   5: confirmed clean by the user's own `git status` on their live
   checkout. No uncommitted changes, no local Item 8 FDD draft exists
   anywhere.** See §1.
3. Whether the native-vs-browser import success/warning toast asymmetry
   (§3f.5) was intentional.
4. Whether `.jobtracker/` should remain a purely invisible implementation
   detail in the redesigned UI, or become a named, user-facing concept
   (e.g. "tracker data file") — a real design choice for Checkpoint 3, not
   a discovery-phase fact.

### 3f.9 Recommendation

**Proceed to Checkpoint 2** (Real Tracker/Database Artifact Investigation).
Session 1's §4 already did a first pass against the supplied
`working-db.zip`; Checkpoint 2 should formalize that the same way this
section formalized Checkpoint 1 — confirming there's nothing about the real
artifact that contradicts anything found here (initial cross-check in §4
found none), and explicitly answering §3f.8's open questions with the user
where they can't be settled from the artifacts alone. Do **not** proceed to
Checkpoint 3 (UX/IA design) until the two open questions that materially
affect scope (§3f.8 #1 and #2) are settled — a redesign built on a
misunderstanding of what the user actually saw, or that ignores in-flight
uncommitted work, risks having to be redone.

---

## 4. Real tracker/database artifact (`working-db.zip`) — investigation

- **VERIFIED** — The supplied ZIP extracts to a folder that is a real,
  **linked** (not app-owned) tracker root: alongside the three
  tracker-relevant top-level folders the app recognizes by convention
  (`Applications/`, `Certifications/`, `References/`), it also contains
  several top-level folders that are clearly the user's own life
  organization and not application-related: `Degree and Transcrips`,
  `For Coding Projects`, `Medicare SNAP`, `Case Management`,
  `Solicited Resume`, `MaddocksSolarPanels`, `PHI Theta`, `Personal`,
  `NSLS`. This is consistent with `link_workspace` (point the app at an
  existing folder in place) rather than an app-owned/imported copy, which
  would typically only contain the app's own convention folders. This was
  not re-confirmed against the app's own `kind` field (no `workspaces.json`
  registry was included in this ZIP — only the data folder itself), so
  "linked" here is an inference from folder contents, not a direct read of
  app state. **HYPOTHESIS**, high-confidence but not proven from this
  artifact alone.
- **VERIFIED** — Contains a `.jobtracker/` folder with exactly two files:
  `jobtracker.db` (434,176 bytes, valid SQLite 3, tables: `items`,
  `documents`, plus `documents_fts` and its shadow tables — this is the
  rebuildable search/index cache `build_index.py` produces) and
  `overrides.db` (184,320 bytes, valid SQLite 3, tables: `item_overrides`,
  `company_aliases`, `document_overrides`, `folder_overrides`,
  `hub_settings`, `document_extractions`, `status_history` — this is the
  portable, hand-entered/derived state).
- **VERIFIED** — The presence of a populated `status_history` table
  confirms this database has been used with the app **after** Item 7 shipped
  (that table is an Item 7 addition per `CHANGES.md`), consistent with the
  repo's current `HEAD` (Item 6+7 complete).
- **VERIFIED relationship to import/export code:** this artifact's shape —
  a folder with `Applications/` etc. at the top level *plus* a `.jobtracker/`
  subfolder containing both DB files — is exactly what
  `export_workspace_to_zip` produces (it walks the whole root, including
  `.jobtracker/`, applying the same exemption described in §3c) and exactly
  what `import_workspace_from_zip` / `import_workspace_from_local_folder`
  know how to consume losslessly (both exempt `.jobtracker/...` from
  filtering). It is **not** the shape a browser `webkitdirectory` import
  would be able to reproduce on its own (it would arrive missing
  `.jobtracker/` entirely, per §3c). This ZIP was not run through any actual
  import/export code this session — the relationship is established by
  static comparison of the artifact's structure against the traced code
  paths, not by executing an import against it. Application code and the
  supplied database were **not modified**.

## 3g. Checkpoint 2 Formal Report — Real Tracker/Database Artifact (session 4)

This section is the authoritative Checkpoint 2 record, formalized the same
way §3f formalized Checkpoint 1, per §3f.9/§9's recommendation. It
cross-checks session 1's §4 (informal first pass) directly against the two
SQLite files' actual contents (read with Python's `sqlite3`, not just file
sizes/table names as in the original §4 pass). Discovery-only: nothing in
`working-db.zip` or `files.zip` was modified.

### 3g.1 VERIFIED — table/row inventory (supersedes §4's table-name-only check)

- `jobtracker.db` (434,176 bytes): `items` — **119 rows**; `documents` —
  **714 rows**; plus `documents_fts` and its four shadow tables (`_data`,
  `_idx`, `_docsize`, `_config`), consistent with an FTS5 virtual table
  used by `build_index.py`'s search index. Table set exactly matches §4's
  claim.
- `overrides.db` (184,320 bytes): `item_overrides` — **80 rows**;
  `company_aliases` — **0 rows**; `document_overrides` — **6 rows**;
  `folder_overrides` — **0 rows**; `hub_settings` — **1 row**;
  `document_extractions` — **64 rows**; `status_history` — **10 rows**.
  Table set exactly matches §4's claim and §3f.2's schema description of
  `overrides_store.py`.

### 3g.2 VERIFIED — `status_history` content confirms real, recent, repeated manual use

Read all 10 rows directly. All have `source = 'manual'`. Timestamps are
same-day, `2026-08-29`, spanning `23:15:16` through `23:57:55` (UTC),
across at least three distinct `item_key`s (`Apple Retail`, `Adams
County|IT`, `Comcast|Hiring Documents`). Several items show rapid
back-and-forth transitions (e.g. Apple Retail: interviewing → rejected →
applied → interviewing → applied, five rows within ~11 minutes). This is
**directly-read confirmation**, not inference from row count alone, that
this database reflects a real user manually exercising the status-change
UI repeatedly and recently — strengthening §4's "used after Item 7 shipped"
conclusion from "the table has rows" to "the table's actual content is
consistent with genuine interactive use, not e.g. a single bulk-migration
insert."

### 3g.3 VERIFIED — `hub_settings` content confirms the "portability matters"
rationale from §3f.2, and is intrinsically tied to the surrounding folder's
non-tracker content

The single `hub_settings` row has `role: null`, `location: null`,
`custom_links: {}`, and a populated `custom_cards.govt` array with three
user-added links (Connecting Colorado, EBT Card, Peak Health), last
`updated_at` `2026-08-28`. This is a concrete, real instance of exactly the
kind of user-entered state §3f.2 said this table exists to make portable
(migrated out of `localStorage` specifically so it travels with the
tracker folder). It also corroborates §4's observation that this tracker
root's non-convention folders (`Medicare SNAP`, `Case Management`) reflect
the user's own life organization: the custom government/benefits links
stored in the app's own portable settings are thematically the same
category of thing as those two folders. Not itself a code-behavior finding
— included because it materially strengthens confidence that this artifact
is a real, lived-in tracker rather than a synthetic/test fixture, which is
relevant to how much weight Checkpoint 3 should give it as a UX reference
point.

### 3g.4 VERIFIED — `document_overrides` content is consistent with §3f.2's
description and includes two non-`Applications/` paths

Read all 6 rows. Four are under `Applications/...` (AffiniPay, Amazon
August 2026, American Systemes, Comcast) with plausible `doc_type_override`
values (`job_posting`, `application_confirmation`, `interview_prep`). Two
are under `For Coding Projects/...` — `JobTracker bash Codes.md` and
`CheckPoint01.zip`, both overridden to `application_confirmation`. This
last pair is a genuine anomaly worth flagging: `For Coding Projects/` is
one of the folders §4 identified as the user's own non-application life
organization, not a job-application folder, and `application_confirmation`
as a doc-type for a `.md` code-notes file and a zip named after this very
project's own checkpoint terminology looks like either (a) a plausible
misclassification the app's auto-detection made that the user then
corrected to something *else* wrong, or (b) a deliberate/test override the
user made while exploring the feature, unrelated to real application
tracking. **OPEN QUESTION (new, session 4):** whether this is a real
misclassification worth investigating as a document-type-detection bug, or
noise/test data from the user's own exploration — cannot be determined
from the artifact alone.

### 3g.5 VERIFIED — no contradiction found between session 1's §4 and this
deeper read

Every claim in §4 (file sizes, table names, the `.jobtracker/` exemption
theory, the "linked not owned" folder-content inference) is corroborated,
not contradicted, by directly reading row contents. §4's caveat that
"linked" is inferred from folder contents rather than read from a
`workspaces.json` registry (none was supplied) still stands — this session
did not find a way to close that specific gap, since no registry file
exists anywhere in either supplied ZIP.

### 3g.6 Recommendation

Checkpoint 2 is now formally complete. Open question §3f.8 #2
(uncommitted local changes) was resolved separately, by the user, via a
direct `git status` on their live checkout (see §1). §3h (below) resolves
the remaining open question, §3f.8 #1 (the `.jobtracker` observation),
via user-supplied screenshots. With both blocking questions now settled,
Checkpoint 3 (UX/IA design) may begin.

### 3h. `.jobtracker` observation — RESOLVED via user screenshots (session 5)

**RESOLVED.** The user supplied five screenshots. The relevant one shows a
Finder window titled `JobTracker — working-db`, browsing the top level of
the real `working-db` tracker folder: `.jobtracker` appears as a plain,
normally-rendered folder icon (distinguishable only by being greyed out, a
common Finder convention for dotfiles) sitting alongside `Applications`,
`Case Management`, `Certifications`, `Degree and Transcrips`, etc. — with
hidden files visible in that Finder session.

Two other screenshots show the in-app "TRACKERS" panel's **"Use an
Existing Folder"** (in-app) and **"Choose a folder instead"** (inline
preview flow) actions — both of which, per §3f.1, invoke the native
macOS folder-picker (pywebview `FOLDER_DIALOG`) rather than any
app-curated list.

**CONCLUSION:** the original observation is confirmed correct, just not
literally about a `.zip`-style "file type." The native folder-picker these
two actions open is a generic, unfiltered OS file-system browser — it has
no awareness that `.jobtracker` is the app's own internal data folder, and
nothing in that dialog (or in the app's own code, which never inspects
what the OS dialog shows) prevents a user who has hidden files visible in
Finder from navigating into a tracker's `.jobtracker` folder and selecting
*it* — instead of the tracker's actual root — as the folder to link or
import. This is the concrete, literal version of "a `.jobtracker`
[folder] being selectable through a file-oriented workflow": the workflow
in question is the raw OS folder picker, which is inherently
file-system/file-oriented (shows everything on disk) as opposed to a
curated, app-aware selection surface. This **supersedes** §3f.6's earlier
"not found to be a real problem" conclusion on this specific point — that
conclusion was based only on the in-page `<input type="file">` and
drag-and-drop surfaces (which *are* hard-filtered to `.zip`, and remain
correctly described that way), not on the native folder-picker, which was
not screenshotted or tested against a hidden-files-visible Finder
configuration in sessions 1–4.

**New, closely-related open question (minor, non-blocking):** what
actually happens if a user *does* select `.jobtracker` itself as the
target folder for "Link" or "Import folder (native)" — does
`inspect_folder`/`link_workspace`/`import_workspace_from_local_folder`
degrade gracefully (e.g. treat it as an empty/unrecognized folder), or
does something worse happen (e.g. it gets treated as a valid tracker root,
nesting a tracker's database inside itself, or corrupting the parent
tracker's own `.jobtracker/overrides.db` via a path collision)? This was
not traced in any session and is worth a quick, low-cost code check before
Checkpoint 3 design work, since it changes how seriously this needs to be
addressed in the UX (a graceful no-op is a minor polish item; data
corruption is a real bug that may deserve fixing ahead of the broader
Item 8A redesign).

### 3i. `.jobtracker`-as-link/import-target — traced, code-level (session 6)

**RESOLVED, asymmetric result — real minor bug found on one of two paths.**

- **`import_workspace_from_local_folder` (native folder *import*, copy
  path) — VERIFIED graceful.** `rglob("*")` on a selected `.jobtracker`
  folder yields only `jobtracker.db` and `overrides.db`. Both are filtered
  by the `.db`-suffix rule in `should_ignore()` via `_resolve_import_dest`
  — the one exemption that lets `.jobtracker/...` survive filtering only
  fires when the relative path's *first* segment is literally
  `.jobtracker` (i.e. the exemption is for something like
  `my-tracker/.jobtracker/overrides.db` inside a normal import), which
  doesn't apply when `.jobtracker` itself is the selected root. Nothing is
  copied, `extracted_any` stays `False`, `_finish_import` raises
  `WorkspaceError("Nothing importable was found in that folder...")` and
  removes the partially-created destination folder. Clean failure, clear
  message, no side effects.
- **`link_workspace` (in-place link) — VERIFIED a real bug.** This
  function has no emptiness/sanity check at all: it unconditionally does
  `(root / "Applications").mkdir(parents=True, exist_ok=True)` and
  registers the workspace, regardless of what `root` actually contains.
  Selecting a tracker's own `.jobtracker` folder as the link target
  **succeeds**: it silently writes a new, spurious `Applications/` folder
  *inside* the original tracker's real `.jobtracker/` directory (alongside
  its actual `jobtracker.db`/`overrides.db`), and registers a new,
  permanently-empty "tracker" workspace pointed at that internal folder.
  The new entry's own `ov_db_path` resolves to a doubly-nested
  `.jobtracker/.jobtracker/overrides.db`, which is never created unless
  someone actually uses the bogus tracker — so the **original tracker's
  real data is not corrupted or overwritten**, but the original tracker's
  internal storage directory does get polluted with an unexpected
  `Applications/` folder, and the workspace switcher gains a confusing,
  functionally-empty duplicate entry, from a single accidental click that
  the UI does nothing to prevent or warn about.

**Severity assessment:** minor, not urgent — no data loss or corruption,
easy to notice (the new "tracker" is visibly empty), and reachable only if
a user has hidden files shown *and* deliberately/accidentally navigates
into `.jobtracker` in the picker rather than stopping at the tracker root
one level up. Still, it's a real, now-traced bug (not a hypothesis), and
the fix is cheap: `link_workspace` should reject (or at minimum warn on)
a target folder whose name is `.jobtracker`, or more generally one that is
itself inside another registered workspace's root. Recorded as a
Checkpoint 4 (Import/Export Design) candidate fix, not something to
implement now — no application code changes without explicit approval,
per §6.

---

## 3j. Checkpoint 3 — UX / Information Architecture Design (session 6, first draft)

**Status: design proposal only, not approved for implementation.**
Grounded entirely in verified findings already in this document — §3f.1
(entry points/components), §3f.5 (current IA and duplication), §3f.6
(real vs. merely-confusing problems), §3f.7 (constraints to preserve),
§3h (the `.jobtracker`-in-picker finding), §3i (the link-target bug).
This is a proposal for the user to react to, not a decision.

### 3j.1 What this design must fix (from §3f.6, restated as goals)

1. A user choosing "Import a Copy of a Folder" has no way to know, before
   clicking, that the browser (non-desktop) path can't preserve their
   notes/statuses/dates — today that's only revealed in a toast *after*
   the import and a reload.
2. The native-folder-import success case gets no confirmation toast at
   all, while the browser-folder-import (partial) case gets an explicit
   warning — backwards from what a user would expect (the path that fully
   works is silent; the path with a real limitation is the only one that
   speaks up).
3. Four/five actions (Create, Import zip, Import folder, Link folder) are
   exposed as undifferentiated peers, with no grouping by what a user is
   actually trying to do or what it costs them in portability.
4. Two React components (`WorkspacePopover`, `NoTrackerOnboarding`)
   duplicate the same four actions almost line-for-line — a redesign
   applied to one and forgotten in the other is a real ongoing risk.
5. (New, §3i) `link_workspace` has no target-folder sanity check, so
   selecting an already-internal folder (most concretely `.jobtracker`
   itself) silently "succeeds" into a confusing, empty duplicate tracker.

### 3j.2 Proposed grouping: by intent, not by mechanism

Today's four actions are grouped by *how* they work (copy vs. link, zip
vs. folder). The proposal groups them by *what the user is trying to do*,
surfacing the portability consequence as part of the choice rather than
as an after-the-fact toast:

| User's intent | Action(s) it maps to today | Proposed label | Portability shown up front |
|---|---|---|---|
| "I'm starting a new job search" | Create New Tracker | **Start Fresh** | n/a |
| "I want JobTracker to manage this folder for me, as its own copy" | Import zip, Import folder (browser or native) | **Bring In a Copy** — sub-choice of zip vs. folder, but folder sub-choice shows a portability note *before* the picker opens, not after | Explicit, before commit |
| "This folder already lives where I want it — just point the app at it" | Link folder (desktop only) | **Use This Folder As-Is** | n/a (always full, in-place) |

Within "Bring In a Copy," the folder sub-option's copy would read
something like: *"On the web, folder copies can't include existing notes
or statuses (browsers can't see hidden files). For a complete copy
including your notes, use a `.zip` export instead."* — shown as static
text next to the button, not conditional on `packaged`, so desktop users
simply don't see a warning that doesn't apply to them (native folder
import *is* lossless, per §3f.1's table) while browser users see it before
they click, not after.

### 3j.3 Toast-parity fix (§3f.6's asymmetry)

Both native folder import and browser folder import should surface a
post-action toast, worded to match what actually happened:
- Native folder import (lossless): *"Folder imported — notes, statuses,
  and dates carried over."*
- Browser folder import (lossy): keep today's existing warning text
  verbatim (it's already accurate and appropriately specific).

This removes the current asymmetry (§3f.5/§3f.6) where the fully-working
path is silent and only the partially-working path speaks up, without
changing any actual import/export behavior — purely a feedback-parity fix.

### 3j.4 Component unification (§3f.1, §3f.5)

Both `WorkspacePopover`'s bottom section and `NoTrackerOnboarding` should
be redesigned as a single shared component (e.g. a
`TrackerCreationActions` component taking a `layout: "popover" |
"onboarding"` prop for the two different container/spacing needs), so a
future change to these three actions is made once. This is a structural
recommendation, not a code change made in this session.

### 3j.5 `.jobtracker` link-target guard (§3i)

Add a target-folder check to `link_workspace` (and ideally to
`inspect_folder`'s preview, so the picker's preview panel can warn
*before* commit, not just reject after): if the resolved folder's name is
`.jobtracker`, or the folder is itself nested inside another registered
workspace's root, refuse with a clear message ("That looks like
JobTracker's own internal data folder, not a tracker folder — pick the
folder one level up instead.") rather than silently creating an empty
duplicate tracker. Low cost, self-contained, doesn't depend on any other
part of this redesign — could reasonably be implemented and tested ahead
of the rest of Item 8A if the user wants it decoupled.

### 3j.6 What this proposal deliberately does NOT change

Per §3f.7's constraints: the `kind` field's linked-vs-owned distinction
and its effect on delete-vs-trash behavior; every existing round-trip
guarantee (zip export/import, native folder import, unlink/relink); the
`.jobtracker/overrides.db` exemption mechanism itself. This proposal is
presentation/grouping/feedback/guard-rail only — it does not propose
changing which paths copy vs. link, or restructuring the overrides schema.

### 3j.7 Open items for the user before this becomes an implementation plan

1. Does the three-way grouping in §3j.2 match how you actually think about
   these actions, or would you group them differently?
2. Should the §3j.5 link-target guard be implemented now, decoupled from
   the rest of Item 8A (it's small and self-contained), or held until the
   full redesign is approved together?
3. Any preference on the exact wording of the "Bring In a Copy" portability
   note in §3j.2, or is the draft wording above fine as a starting point?

---

## 3k. Session 7 — §3j.5 guard implemented (decoupled), real suite run by user

**DECISION (user, session 7):** approved §3j's design proposal as a
whole (grouping, toast-parity fix, component-unification recommendation)
and chose, per §3j.7 #2, to implement the `.jobtracker` link-target guard
(§3j.5) now, decoupled from the rest of Item 8A — rather than holding it
until the full redesign is approved together. §3j.2's exact grouping
labels/copy and §3j.4's component unification are **not** implemented —
those remain design-approved-but-not-built, same status as before, and
are Checkpoint 4/5 scope. Only §3j.5 (the guard) was built this session.

### 3k.1 What changed

- **`_app/workspace.py`:** added `_internal_tracker_conflict(root, data)`
  — a small pure function (stdlib-only: `pathlib`, no I/O beyond what's
  already loaded) that returns a human-readable reason a folder is not a
  valid link/import target, or `None` if it's fine. Two cases, both from
  §3j.5's spec: (1) `root`'s own name is `.jobtracker` (the internal
  storage dirname itself); (2) `root` is nested anywhere inside another
  registered workspace's *resolved* root (not just the `.jobtracker`
  case — any folder inside an existing tracker). Deliberately does
  **not** flag a workspace's own root matched against itself — that's
  the existing `already_linked` case, a different (recoverable) situation,
  not this guard's target.
  - `link_workspace` now calls this right after the existing
    `root.is_dir()` check and raises `WorkspaceError(conflict)` — turned
    into a 400 by the existing `except ws.WorkspaceError` handler in
    `_app/api.py`'s `/api/workspaces/link` endpoint. No changes needed
    in `api.py` itself.
  - `inspect_folder` now sets a new `internal_conflict` key (string
    reason, or `None`) in its result dict, computed the same way,
    reusing the registry data it already loads for the `already_linked`
    check. This lets the picker's preview panel warn *before* the user
    clicks "Use this folder" — per §3j.5's "ideally... so the picker's
    preview panel can warn before commit, not just reject after."
- **`_app/frontend/index.html`:** the shared `describeFolderInspection()`
  helper (used by the in-app `WorkspacePopover`'s "Use an Existing
  Folder" / "Import a Copy of a Folder" flows) now checks
  `inspection.internal_conflict` first, before the existing
  `already_linked` check, and returns `{tone:"block", canContinue:false,
  ...}` with the backend's message as `sub` — same shape/pattern as the
  existing `already_linked` block case, for both `"link"` and
  `"import"` modes (import would also fail — §3i found native folder
  import already rejects a `.jobtracker` target cleanly at the code
  level — so surfacing it in the preview is strictly earlier feedback,
  not new backend behavior for that path).
- **`desktop/first_run.html`:** the standalone first-run picker (native
  desktop only, doesn't share `index.html`'s JS) got the equivalent
  branch added to its own `renderPreview()`, checked before
  `already_linked`, same message/blocking pattern.
- **Docstrings:** `link_workspace`'s docstring in `workspace.py` now
  documents the guard and references this section for the bug it closes.

### 3k.2 What this deliberately did NOT touch

- §3j.2's three-way "Start Fresh / Bring In a Copy / Use This Folder
  As-Is" grouping and relabeling — not implemented.
- §3j.3's toast-parity fix (native folder import getting a success
  toast) — not implemented.
- §3j.4's `TrackerCreationActions` component unification — not
  implemented; `WorkspacePopover` and `NoTrackerOnboarding` still
  duplicate the four actions as before.
- `_app/api.py` — no changes; the existing `WorkspaceError` → 400
  handling in the `/api/workspaces/link` endpoint already covers the
  new raise.
- No database, schema, or import/export code changes — this is a
  reject-early guard, not a change to what copies vs. links.

### 3k.3 Verification performed in-session (this sandbox), and its limits

- **VERIFIED** — full-file syntax check (`ast.parse`) on the edited
  `_app/workspace.py`: no syntax errors.
- **VERIFIED, directly** — `_internal_tracker_conflict()` itself, in
  isolation: imported `workspace.py` with a stubbed `send2trash` module
  (the only third-party import that function's containing file needs at
  *import* time; `send2trash` itself is unrelated to this change — it's
  needed just to make the module importable at all in this
  no-network sandbox) and ran it directly against five constructed
  cases: the `.jobtracker` folder itself, a folder nested inside a
  registered tracker, the tracker root itself (must NOT conflict —
  that's `already_linked`'s territory), an unrelated folder (must NOT
  conflict), and a folder literally named `.jobtracker` that isn't
  nested inside any registered workspace at all (must still conflict,
  per the name-based rule alone). All five matched the intended
  behavior.
- Real full-suite `pytest` run was **not possible in this sandbox**
  (no network access, so `pytest`/`fastapi`/`httpx` couldn't be
  installed) — that's why this session's original text called it out as
  the key gap. **Superseded by §3k.5: the user ran it themselves.**

### 3k.4 New test cases added

- `tests/test_workspaces.py`:
  `test_link_rejects_the_jobtracker_folder_itself` — links a real
  tracker, touches `overrides.db` (via `GET /api/applications`) so
  `.jobtracker/` actually exists (see §3k.5 — it isn't created by
  linking alone), then attempts to link that tracker's own `.jobtracker`
  folder as a second workspace; asserts 400, the specific error
  substring, that no `Applications/` folder was created inside the real
  `.jobtracker/`, and that no bogus workspace was registered. This is
  the direct regression test for §3i's original bug.
  `test_link_rejects_a_folder_nested_inside_an_existing_tracker` — same
  pattern for a non-`.jobtracker` nested folder (`Applications/` itself).
- `tests/test_workspace_inspect.py`: four cases covering
  `internal_conflict` being set for the `.jobtracker` folder itself and
  for a nested folder, and being `None` for the tracker's own root
  (distinct from `already_linked`) and for an unrelated folder.

### 3k.5 Real suite run by the user (session 7, same session) — 149/150, one test bug found and fixed

**VERIFIED — the user ran the actual suite** (`pytest`, full 150-item
collection: 144 pre-existing + 6 new from §3k.4) **in their real
environment.** Result: **149 passed, 1 failed.**

- **The guard logic itself is confirmed working**, not just
  isolation-tested: `test_link_rejects_a_folder_nested_inside_an_existing_tracker`
  passed, as did all four new `inspect_folder` cases (`internal_conflict`
  set correctly for both conflict shapes, `None` for both non-conflict
  shapes) and every one of the 144 pre-existing tests (no regression
  anywhere else in the app).
- **The one failure, `test_link_rejects_the_jobtracker_folder_itself`,
  was a bug in the *test*, not the guard.** The test asserted
  `(sample_root / ".jobtracker").is_dir()` immediately after linking
  `sample_root`, assuming `link_workspace` creates that folder. It
  doesn't: `link_workspace` only creates `Applications/`.
  `.jobtracker/overrides.db` is created lazily, on first real touch of
  overrides.db (via `get_conn()` in `overrides_store.py`) — a fact this
  very document already knew and had recorded, almost verbatim, in the
  pre-existing `test_workspace_list_includes_kind_and_overrides_flag`
  test's own comment ("Touching overrides.db at all -- even a plain
  read -- creates it lazily inside the linked folder"). The new test
  just didn't apply that existing knowledge to itself.
- **Fix applied (this update):** the test now does
  `client.get("/api/applications")` right after linking — the same
  lazy-creation trigger the pre-existing test already uses — before
  asserting `.jobtracker/` exists and proceeding with the rest of the
  scenario. Syntax-checked (`ast.parse`) in this sandbox; **not yet
  re-run for real** by either party.
- **Net assessment:** the guard (§3k.1's actual code change) has real,
  independent confirmation from 149 passing tests including its own
  direct positive case. The one gap remaining is purely
  "does the corrected test file also pass," which is a much smaller,
  much lower-risk question than "does the guard work" — that one's
  answered.

### 3k.6 Confirmation: 150/150, plus real-app manual validation — guard is done

**VERIFIED — the user re-ran the suite after the §3k.5 fix, twice: 150
passed, 0 failed, both times.** `test_link_rejects_the_jobtracker_folder_itself`
now passes along with everything else. The guard (§3k.1) is fully
validated: every existing test, both new `link_workspace` rejection
cases, and all four new `inspect_folder` cases pass. This closes out
the "immediate next action" from §8/§9's prior text.

**Additional real-app validation (screenshots, same session), not part
of the automated suite but independently reassuring:** the user ran the
actual packaged dev server (`uvicorn api:app --reload`) and imported
the real `working-db.zip` (376 MB, the same real tracker data examined
in §3g) via "Import a Copy," which succeeded — *"Zip successfully
imported with all notes, statuses, and dates preserved,"* landing at
41 applied / 13 interviewing / 56 rejected, and the Application Dossier
view rendered correctly for a real item (Adams County — IT — timeline,
role summary, contacts, attached documents) with no errors. This
exercises a large swath of the app (import, indexing, dossier
extraction, status/history) end-to-end against real data post-change,
with none of it touching `link_workspace` specifically — i.e. it did
not directly exercise the new guard (that would require using the
native folder picker and selecting a `.jobtracker` folder, which is
desktop-native-only and wasn't part of these screenshots) — but it does
confirm nothing else broke from this session's change. Some
unrelated terminal noise appeared alongside the second full pytest run
(a `zsh` history/paste artifact producing `command not found` /
`permission denied` lines and a stray `48 passed` fragment) — that is
shell scrollback, not a second, smaller test run; the two genuine full
`pytest` invocations both clearly report `150 passed`.

**Status: the §3j.5 guard is complete and validated.** Ready for the
user's own review of the diff and, if satisfied, their own commit via
GitHub Desktop per §6 — Claude still does not stage/commit/push.

---

## 3l. Session 8 — §3j.2/§3j.3/§3j.4 implemented (frontend-only, unvalidated by user yet)

**DECISION (user, session 8):** asked to proceed to "the rest of §3j"
(grouping/relabeling §3j.2, toast-parity §3j.3, component unification
§3j.4) rather than Checkpoint 4 (Import/Export Design), and approved
this session's plan. §3j.5 (the link-target guard) was already done in
session 7 (§3k) and is untouched this session.

### 3l.1 What changed

All changes are in `_app/frontend/index.html` only. **No backend/API
files, tests, or data were touched** — §3j.2/3j.3/3j.4 are presentation-
only per §3j.6, so this is consistent with scope. `desktop/first_run.html`
was deliberately left alone: it's a link-only screen (no create/import
choice at all) and was never one of the two duplicated components §3j.1
goal 4 identified — only `WorkspacePopover` and `NoTrackerOnboarding`
were.

1. **§3j.4 — Component unification.** Added a new component,
   `TrackerCreationActions({layout, packaged, onError})`, defined once,
   containing all the Create / Import (zip or folder) / Link logic and
   markup that used to be duplicated almost line-for-line between
   `WorkspacePopover` and `NoTrackerOnboarding`. Both call sites were
   cut down to a single `<TrackerCreationActions layout="popover" .../>`
   or `layout="onboarding"` invocation. `layout` only changes
   container/spacing CSS (new `.tca-onboarding` rules); the actions,
   copy, and API calls are identical either way. Errors are reported up
   via an `onError` callback rather than kept in local state, so each
   caller can keep showing them wherever its own error banner already
   lived (`WorkspacePopover`'s top `err` banner; `NoTrackerOnboarding`'s
   `warning-banner`) — this is a real, if minor, behavior improvement to
   `NoTrackerOnboarding` too: it previously had no browser-folder-import
   path at all (only zip + native-only folder/link buttons); it now
   gains the exact same zip-or-folder dropzone `WorkspacePopover` already
   had, simply by virtue of sharing the same component. This was judged
   in-scope: eliminating exactly this kind of drift between the two
   components was §3j.1 goal 4's explicit purpose, not scope creep beyond
   the approved proposal.
2. **§3j.2 — Intent-based grouping/relabeling.** The three actions are
   now rendered under three labeled groups matching §3j.2's table:
   **"Start Fresh"** (Create), **"Bring In a Copy"** (zip or folder, with
   the folder path as a sub-choice via "Choose a folder instead"), and
   **"Use This Folder As-Is"** (link, desktop/packaged only — unchanged
   visibility rule). The Create button's own label changed from "Create
   New Tracker" to "Start Fresh" to match its group; the Link button's
   label changed from "Use an Existing Folder" to "Use This Folder
   As-Is" to match §3j.2's exact proposed name. The browser-only
   portability note (§3j.2's exact draft wording, used verbatim per
   §3j.7 #3 going unanswered — no alternative wording was ever
   specified, so the draft stands) now renders as static text next to
   the "Choose a folder instead" link **before** the picker opens,
   whenever `!packaged` — not gated behind any additional new
   conditional beyond the platform branch that already existed. Packaged
   users still see the pre-existing "picking a folder shows a preview"
   hint in that slot instead, since native folder import is lossless and
   the note doesn't apply to them.
3. **§3j.3 — Toast-parity fix.** Native folder import
   (`confirmImportFolderNative`, used by both the popover's and
   onboarding's "Bring In a Copy → Choose a folder instead" path) now
   sets a new `IMPORT_NOTICE_KEY` value, `"folder-native-success"`, on
   success, consumed by `App`'s existing post-reload notice `useEffect`
   to show *"Folder imported — notes, statuses, and dates carried
   over."* as a success toast — closing the exact asymmetry §3f.6/§3j.1
   goal 2 identified (the fully-working path was silent; the
   partially-working browser path was the only one that spoke up). Zip
   import's `"zip-success"` toast and browser folder import's
   `"folder-warning"` toast are both unchanged, including the
   `folder-warning` text, which §3j.3 said to keep verbatim. The Link
   flow (`confirmLinkFolderNative`) still gets no toast, unchanged —
   §3j.3 only discussed the two *copy* paths (zip vs. folder import);
   linking isn't a copy and was never described as needing one.

### 3l.2 What this deliberately did NOT change

Same constraints as §3j.6, reaffirmed: no backend/API changes, no
change to which paths copy vs. link, no change to the `kind` field or
delete/trash behavior, no change to the `.jobtracker/overrides.db`
exemption mechanism, no change to `first_run.html`. Also unchanged:
every workspace-list action in `WorkspacePopover` (switch/rename/
export/delete) — only the block below the divider (Create/Import/Link)
was touched. `describeFolderInspection()` (§3j.5's shared preview logic)
is unchanged and is now called from inside `TrackerCreationActions`
instead of directly inside each of the two former call sites — same
function, same behavior, one fewer place it's invoked from.

### 3l.3 Verification performed in-session (this sandbox), and its limits

**This is frontend-only work, and this repo has no JS/frontend test
suite — only Python/pytest for the backend (confirmed: no `.py` test
references `index.html`, `TrackerCreationActions`, or any React
component; the frontend has never had automated test coverage in this
project's history).** So, unlike §3k's guard, there is no equivalent to
a "150/150 passed" result available for this change, from Claude or
from the user. What *was* checked, in this sandbox, without network
access to install real frontend tooling:

- The full `<script type="text/babel">` body was extracted and run
  through `@babel/preset-react` (`transformSync`, both automatic and
  classic runtime) — **no syntax errors.**
- The transpiled output was loaded via `new Function(...)` (with the
  browser/React globals it references stubbed as parameters) to catch
  duplicate top-level declarations or other structural issues a syntax
  check alone might miss — **parsed and constructed successfully.**
- Brace/paren counts across the whole file remained balanced after
  every edit.
- Grepped for every removed function/state name
  (`startLinkFolderNative`, `confirmImportFolderNative`,
  `cancelImportPreview`, `doImportZip`, the old per-component `mode`
  state, etc.) to confirm none were left dangling in either
  `WorkspacePopover` or `NoTrackerOnboarding` after the refactor —
  confirmed all now live only inside `TrackerCreationActions`.
- Confirmed `TrackerCreationActions` is defined exactly once and called
  from exactly the two intended places.

**None of this is a substitute for actually running the app.** A syntax
check cannot catch a wrong prop name that both defines and consumes the
same (now-nonexistent) typo consistently, a CSS class that doesn't look
right against the onboarding card's actual background, or an
interaction that behaves differently than intended once a real browser
or the packaged pywebview bridge (`window.pywebview.api.pick_folder`,
`.inspect_folder`, `.confirm_import_folder`, `.confirm_link_folder`) is
involved. **This has NOT been opened in a real browser or the packaged
app by anyone, Claude or the user, as of this handoff update.**

### 3l.4 What the user should check before treating this as done

Per §6/§7, Claude does not stage/commit/push, and per this section,
Claude also cannot claim automated validation exists here the way it
did for §3k. The next step is the user opening the app (dev server
and/or packaged build) and exercising, at minimum:

1. The J-switcher popover: Start Fresh, Bring In a Copy (both the zip
   dropzone and "Choose a folder instead"), and — if on packaged/desktop
   — Use This Folder As-Is, including its preview/cancel states.
2. The first-run screen (`NoTrackerOnboarding`, only reachable with zero
   trackers registered) for the same three flows — this is the screen
   whose behavior changed the most (it gained the folder-dropzone UI it
   didn't have before).
3. That native folder import (packaged only) now shows the new
   "Folder imported — notes, statuses, and dates carried over." toast
   after a successful native folder import, where previously it showed
   nothing.
4. That the pre-existing zip-success and browser-folder-warning toasts
   are unchanged.
5. Visually, that the new group labels ("Start Fresh" / "Bring In a
   Copy" / "Use This Folder As-Is") and the new portability note (in the
   browser-only, non-packaged case) read and lay out reasonably in both
   the popover (dark, compact) and the onboarding card (lighter,
   roomier) contexts.

If anything looks or behaves wrong, that's expected to surface here,
not in an automated suite — there isn't one for this part of the app.

---

## 5. Checkpoint roadmap (unchanged from kickoff; not started)

0. *(session 1)* Handoff setup — no implementation. **Complete.**
1. Repository & Architecture Discovery — **Complete** as of session 2. See

   §3f (Checkpoint 1 Discovery Report) for the full, formal record. §3a–§3e
   are the superseded session-1 partial pass, kept for history.
2. Real Tracker/Database Artifact Investigation — **Complete** as of
   session 4. See §3g (Checkpoint 2 Formal Report). §4 (session 1) is the
   superseded informal first pass, kept for history.
3. UX / Information Architecture — design proposal (§3j) **approved by
   the user in session 7; all of it is now implemented as of session 8**
   (§3l): §3j.5 (guard, session 7, fully validated at 150/150) plus
   §3j.2/§3j.3/§3j.4 (grouping, toast-parity, component unification,
   session 8, frontend-only, **not yet run or reviewed by the user** —
   see §3l.3/§3l.4).
4. Import/Export Design — not started.
5. Implementation Plan — not formally written as a separate document for
   either §3j.5 or §3j.2/3/4; both went straight to implementation with
   the user's explicit approval (§3j.7 #2 for the guard; direct approval
   for the rest in session 8), consistent with this project's practice
   of small, decoupled, approved changes rather than a separate planning
   artifact.
6. Implementation — **all of §3j is now implemented**: the guard (§3k,
   session 7) and grouping/toast-parity/unification (§3l, session 8).
   Any further implementation (Checkpoint 4, or anything else) still
   requires explicit approval first, per §6.
7. Validation — **done for the guard** (§3k.6): full suite run twice by
   the user, 150/150 both times, plus manual real-app validation. **NOT
   done for session 8's §3j.2/3/4 work** — this repo has no frontend
   test suite, so unlike the guard there is no automated result to
   report; the user has not yet opened the app with these changes in
   place. See §3l.3/§3l.4 for exactly what was and wasn't checked, and
   what to look at.
8. Review / Explicit Approval — the guard's design, implementation, and
   validation are all complete and were the user's to review before
   committing (§3k). §3j.2/3/4's design and implementation are done;
   the user's own review — both of the diff and of the running app,
   since there's no test suite standing in for that here — is the
   immediate next step (§3l.4), ahead of any commit.
9. GitHub Desktop (user-controlled staging/commit/push) — not started
   for either the guard or the session 8 work; both exist only in
   session output/handoff attachments, not the user's real repo, until
   applied and committed by the user themselves.

---

## 6. Git / approval constraints (binding, unchanged)

- Do not `git add -A`, stage, commit, push, reset, or clean anything.
- Do not discard any existing work, committed or uncommitted.
- The user controls all Git operations via GitHub Desktop.
- No commit or push is authorized at any point without the user's explicit
  approval after validation.
- This session performed **read-only** inspection only: `git status`,
  `git log`, `git branch -a`, file reads, and `python3 -m pytest -q`
  (running the existing test suite is read-only with respect to the repo —
  it does not modify tracked files). `HANDOFF.md` is the only file created
  or modified this session, and it was not staged or committed.

---

## 7. Context handoff protocol (binding, unchanged)

- Keep this file current. Update it before ending a session, and proactively
  once context usage looks like it's approaching ~80–85%, not just at the
  hard limit.
- On every update, keep facts clearly labeled **VERIFIED**, **HYPOTHESIS**,
  **OPEN QUESTION**, or **DECISION**, as done throughout this document.
- Do not create a `.tex` or PDF version of this handoff. Markdown only.
- The next Claude conversation should be able to read this file top to
  bottom and continue without the user having to re-explain the project.

---

## 8. Recommended next step

*(Updated session 8 — §3j.2/3/4 are now implemented (§3l), but unlike
the guard, this work has no automated test suite to validate it. The
recommended next step has shifted from "run the suite" to "open the
app.")*

**The user opening the real app (dev server and/or packaged build) and
exercising the J-switcher popover and first-run onboarding screen —
see §3l.4 for the specific checklist.** There is no pytest run that can
stand in for this: §3j.2/3/4 are frontend-only changes to a file with
no JS test coverage in this project. Once the user has done that and is
either satisfied or has changes to request, the next question is
whether to proceed to Checkpoint 4 (Import/Export Design) per §5 — that
hasn't been started or touched by either session 7 or session 8. Ask
rather than assume. §3g.4's `document_overrides` anomaly remains
optional/non-blocking, unasked.

As with the guard, nothing here has been staged, committed, or pushed —
that remains the user's own action via GitHub Desktop, per §6, once
they're satisfied with both this session's diff and how it behaves in
the real app.

---

## 9. Session 7 status and exact resume point

**Session 7 made the first application-code change of this project's
handoff history** (§3k) — the `.jobtracker` link-target guard from
§3j.5, approved by the user and implemented as a decoupled fix per
§3j.7 #2. **The user ran the real suite three times total this
session: 149/150 on the first pass (§3k.5, one test-bug found and
fixed), then 150/150 twice more after the fix (§3k.6).** The user also
manually validated the running app against real data (import + dossier
view) with no issues. **The guard is complete and fully validated.**
Nothing has been staged, committed, or pushed anywhere; per §6, only
the user does that, via GitHub Desktop, on their own timeline.

**Exact resume point for the next chat:**
1. Read this file in full first, especially §3k.6 (the final validated
   state) — don't re-litigate whether the guard works; that's settled.
2. Ask the user what they'd like to do next: review/commit the guard
   diff themselves (their call, not Claude's), or move on to the next
   piece of work. If they want to continue building, ask whether that's
   the remaining §3j items (grouping §3j.2, toast-parity §3j.3,
   component unification §3j.4) or Checkpoint 4 (Import/Export Design)
   per §5 — don't assume which.
3. Continue to make no application-code changes and no Git operations
   without explicit approval, per §6.

## 9a. Session 6 status and exact resume point (superseded by §9 above)

**No application code, tests, or data files have been changed in any
session.** Session 3's `git status`/`git diff --stat` check (exactly one
untracked file, `HANDOFF.md`; no changes to any tracked file; nothing
staged, committed, or pushed) was independently reconfirmed in session 5
by the user running `git status` themselves on their live local checkout:
same result — clean branch, up to date with `origin/main`, only
`HANDOFF.md` untracked. This closes out §3f.8's uncommitted-changes
question for good (see §1). All Git operations remain the user's own, via
GitHub Desktop, per §6.

A fresh ZIP of the current repository working tree (as supplied, with only
this `HANDOFF.md` swapped for the updated version) was produced in session
4 for handoff/backup purposes, per the user's explicit request, and this
session's further HANDOFF.md updates are reflected in the copy attached to
this session's reply — it is a snapshot for the user, not a Git operation,
and creating it did not modify the repository itself in any way. `.git/`,
caches, and virtual environments were excluded (none were present in the
supplied ZIP to begin with).

**Exact resume point for the next chat:** Checkpoints 1 and 2 (Item 8A)
are both complete — see §3f and §3g. Both blocking open questions from
§3f.8 were resolved in session 5 (§1, §3h). **Checkpoint 3 (UX/IA design)
now has a first draft — §3j** — pending the user's reaction to §3j.7's
three open items. The next chat should:

1. Read this file in full first.
2. Check whether the user answered §3j.7's open items (grouping,
   guard-timing, wording) in the conversation that produced this update;
   if not, ask before treating §3j as final.
3. Once §3j is confirmed, proceed to Checkpoint 4 (Import/Export Design)
   per §5 — still design-only, no application code changes without
   explicit approval. The §3j.5 link-target guard could be implemented
   ahead of the rest of Item 8A if the user chooses to decouple it
   (§3j.7 #2) — that would be the first actual code change in this
   project's handoff history, and still requires explicit approval per §6
   even though it's small.
4. Continue to make no application-code changes and no Git operations
   without explicit approval, per §6.

## 10. Session 6 summary

Session 5 closed out both remaining §3f.8 blockers: the user ran `git
status` on their live local checkout, confirming a genuinely clean
working tree (§1); and supplied five screenshots showing the native
folder-picker (invoked by "Link"/"Import folder") exposing `.jobtracker`
as a plain, selectable folder when hidden files are visible in Finder —
resolving the `.jobtracker` observation (§3h).

Session 6 (this session), per the user's approval, did two things: (1)
traced §3h's follow-on question in code — confirmed native folder
*import* rejects a `.jobtracker`-as-target selection cleanly, but
`link_workspace` has no such guard and silently creates a spurious empty
tracker plus an unwanted `Applications/` folder inside the original
tracker's real `.jobtracker/` directory (§3i, a real but minor,
non-corrupting bug); and (2) produced a first-draft Checkpoint 3 UX/IA
design proposal (§3j) grounded in §3f/§3g/§3h/§3i's verified findings —
an intent-based three-way action grouping, a toast-parity fix, a
component-unification recommendation, and the §3i guard as a proposed
fix — explicitly marked as a proposal pending the user's review (§3j.7),
not an approved implementation plan. No application code, tests, or data
were modified in any session to date. No Git operations were performed by
Claude at any point.

## 11. Session 7 summary

The user approved §3j's design proposal and, per §3j.7 #2's own framing
of it as a reasonable option, chose to implement the §3j.5
`.jobtracker` link-target guard now, decoupled from the rest of Item
8A. This session (1) added `_internal_tracker_conflict()` to
`_app/workspace.py` and wired it into `link_workspace` (raises,
becomes a 400) and `inspect_folder` (new `internal_conflict` field);
(2) updated both frontend preview surfaces
(`_app/frontend/index.html`'s shared `describeFolderInspection()`, and
`desktop/first_run.html`'s standalone `renderPreview()`) to block on
that new field the same way they already block on `already_linked`;
(3) added 6 new test cases across `tests/test_workspaces.py` and
`tests/test_workspace_inspect.py`; and (4) verified the new pure logic
function directly, in isolation, against 5 constructed cases, since
this sandbox has no network access and could not install `pytest`/
`fastapi` to run the real suite itself.

**The user then ran the real suite in their own environment, three
times total this session: 149/150 on the first pass, then 150/150
twice more after a one-line test fix.** The single original failure was
a bad assumption in a new test (it expected `link_workspace` to create
`.jobtracker/` immediately, when that folder is actually created
lazily on first touch of `overrides.db` — documented behavior an
existing test already relied on), not a defect in the guard — every
other new test passed on the first run, including the guard's own
direct positive case and all four new `inspect_folder` cases, plus all
144 pre-existing tests with no regressions. The test was corrected
in-session (§3k.5), and the user's two follow-up full runs (§3k.6) both
came back clean at 150/150. The user also manually ran the packaged app
against real data (importing the real `working-db.zip`, viewing an
application's dossier) with no issues — further, if indirect,
confirmation nothing else broke. **The §3j.5 guard is complete and
fully validated as of this session.** No Git operations were performed
by Claude at any point; nothing is staged, committed, or pushed
anywhere, and this change exists only in this session's working
copy/output until the user reviews the diff and commits it themselves,
on their own timeline, via GitHub Desktop.

## 12. Session 8 status and exact resume point

Session 8 implemented §3j.2 (grouping/relabeling), §3j.3 (toast-parity
fix), and §3j.4 (component unification) in `_app/frontend/index.html`
only — see §3l for the full record. This was the user's explicit choice
(over Checkpoint 4) when asked which direction to take after session
7's guard was validated.

**This is frontend-only work in a repo with no frontend test suite.**
Everything that could be checked without a browser or the packaged app
was checked (§3l.3: Babel syntax transform, a structural parse of the
transpiled output, brace/paren balance, and a grep sweep for dangling
references to removed functions/state) and came back clean. **None of
that substitutes for actually running the app**, and nobody has done
that yet with this change in place.

**Exact resume point for the next chat:**
1. Read this file in full first, especially §3l (what changed and why)
   and §3l.3/§3l.4 (what was and wasn't verified, and the checklist for
   the user to run through in the real app).
2. Ask the user whether they've had a chance to open the app and run
   through §3l.4's checklist yet. If they report problems, treat that as
   the priority — fix before anything else. If they report it looks
   good, the natural next question is the same one as after the guard:
   commit (their call, via GitHub Desktop, per §6), and/or move on to
   Checkpoint 4 (Import/Export Design, per §5) — don't assume which,
   ask.
3. Continue to make no further application-code changes and no Git
   operations without explicit approval, per §6.

## 13. Session 8 summary

The user, asked to choose between finishing the rest of §3j
(grouping/toast-parity/component-unification) or starting Checkpoint 4
(Import/Export Design), chose to finish §3j and approved proceeding.
This session (1) added a new `TrackerCreationActions({layout, packaged,
onError})` component to `_app/frontend/index.html`, consolidating the
Create/Import/Link logic and markup that had been duplicated almost
line-for-line between `WorkspacePopover` and `NoTrackerOnboarding`
(§3j.4); (2) grouped and relabeled the three actions by user intent —
"Start Fresh," "Bring In a Copy," "Use This Folder As-Is" — matching
§3j.2's table exactly, and moved the browser-only portability warning
to before the folder picker opens instead of only after import; and
(3) added a new post-import success toast for native folder import
("Folder imported — notes, statuses, and dates carried over."),
closing the silent-success asymmetry §3j.3/§3f.6 identified, while
leaving the existing zip-success and browser-folder-warning toasts
unchanged. `desktop/first_run.html` was left untouched — it's a
link-only screen never in scope for §3j.2/3/4. No backend/API code,
tests, or data files were touched.

**Unlike session 7's guard, this change has no automated test suite to
validate it against** — this repo has pytest coverage for the backend
only, never the frontend. Claude verified the changed file's JSX/JS
compiles cleanly under Babel and parses structurally with no dangling
references to removed code, but this is a syntax/structure check, not a
behavioral one, and **the app has not been opened in a real browser or
the packaged build by anyone since this change was made.** That is the
explicit, flagged next step for the user (§3l.4), before any commit via
GitHub Desktop (§6). No Git operations were performed by Claude at any
point.

## 14. Session 8 — user validation of §3j.2/§3j.3/§3j.4 via screenshots

Per §3l.4's checklist, the user ran the dev build in Safari and supplied
screenshots plus a real folder-import-then-zip-import comparison using
`working-db.zip`. Confirmed from that evidence:

1. **§3j.2 grouping** — the three actions render under separate labeled
   sections ("Start Fresh" / "Bring In a Copy") matching the intent-based
   grouping.
2. **§3j.2 upfront portability note** — the new copy about browser folder
   copies not carrying notes/statuses appears *before* the folder picker
   opens, not only after import — the core fix for that item.
3. **§3j.3 toast unchanged for the lossy path** — the existing
   browser-folder-import warning toast (red/maroon, "Files were
   imported, but any existing notes, statuses, or dates didn't come
   across...") still fires, verbatim, untouched, distinct from the
   zip-import success toast (green, "Zip successfully imported with
   all notes, statuses, and dates preserved.") which fired correctly
   on the zip path.
4. **End-to-end correctness** — a folder import (browser, lossy) left
   statuses at default/blank, while a subsequent zip import correctly
   restored real statuses and history (e.g. an entry with a dated
   "Rejected" status change), confirming `.jobtracker/overrides.db`
   round-trips as intended.
5. **Backend untouched** — the user's pytest runs stayed at 150/150
   across multiple runs, consistent with this being a frontend-only
   change.

**Not yet exercised as of this point (expected, not a gap):** all of
the above was the dev server in Safari. The packaged/native-only
paths — the "Use This Folder As-Is" link, and native folder import's
new success toast ("Folder imported — notes, statuses, and dates
carried over.") — require the packaged/pywebview build; see §15 for
how far that testing got.

## 15. Session 8 — packaged app (native) testing of the two untested items

The user built the packaged app locally (`./scripts/build-macos.sh`
then `./scripts/package-dmg.sh`, both completed cleanly, no PyInstaller
errors) and ran it to exercise the two items flagged above as
untestable in the browser:

1. **"Use This Folder As-Is" — now validated.** Pointed the native
   app's link flow at a real, populated tracker folder
   (`/Users/cucii/Documents/applications`, distinct from the
   `working-db` test snapshot). The preview correctly identified it as
   an existing JobTracker-shaped folder ("This already looks like a
   JobTracker tracker... 669 files found") and linked it **without
   copying** — the resulting tracker showed the folder's real,
   un-curated data (e.g. Adams County at auto-detected `applied`
   status, no manual override), confirming the link-in-place path
   works end to end in the packaged build.
2. **Native zip import via "Bring In a Copy" — also exercised, and
   correct.** Using the native file picker to select a `.zip` fired
   the same green *"Zip successfully imported..."* success toast as
   the browser path, with all 110 applications and their real statuses
   (41 applied / 13 interviewing / 56 rejected) carried over correctly.
3. **Still not exercised: the native folder-import success toast**
   ("Folder imported — notes, statuses, and dates carried over.").
   This session's "Bring In a Copy" test used a `.zip`; that toast only
   fires via Bring In a Copy → "Choose a folder instead" with a real
   folder. This is now the only remaining item from the original
   packaged-app checklist.

**Net effect:** of the two originally-untested native-only paths, one
("Use This Folder As-Is") is now fully validated; the other (native
folder-import success toast) is not, and is the one remaining gap
before §3j.2/3/4 can be called fully verified end to end.

## 16. Session 8 — final item closed: native folder-import success toast

The user completed the last remaining checklist item: Bring In a Copy
→ "Choose a folder instead" → picked the real `applications` folder
(717 files, correctly identified as an existing JobTracker-shaped
folder) → "Import this folder." The new toast fired exactly as
designed: *"Folder imported — notes, statuses, and dates carried
over."* — and the resulting tracker showed all 110 applications with
real statuses intact (41 applied / 13 interviewing / 56 rejected),
confirming the native folder-copy path preserves everything the
browser path loses.

**§3j.2/§3j.3/§3j.4 are now fully verified end to end** — every item
on §3l.4's checklist (grouping/relabeling, the upfront portability
note, toast parity on both the lossy browser path and the two native
paths, and the "Use This Folder As-Is" link) has been exercised and
confirmed working, in both the Safari dev build and the packaged
native app. Nothing else is outstanding from this work. Still true as
of this point: nothing has been committed or pushed (§6) — that
remains the user's call, on their own timeline, via GitHub Desktop.

## 17. Session 9 — the browser-folder-import warning toast was firing unconditionally, even on browsers/versions where it shouldn't

**Starting point:** §16 closed out §3j as fully verified — but that
verification was all done on the versions of Safari/Chrome available
at the time. This session re-opened the question of whether the
"browsers strip dotfiles from folder uploads" premise still held.

**Research, then empirical confirmation.** A standalone throwaway test
page (`dotfile-test.html`, not part of the app) called
`showDirectoryPicker()` directly and enumerated the result. In the
user's current Chrome, it returned `.jobtracker` and its contents
without filtering — dotfiles were exposed. In Safari,
`showDirectoryPicker` doesn't exist on `window` at all (confirmed:
`showDirectoryPicker() is not supported in this browser.`), consistent
with Safari shipping OPFS only, no local-disk picker.

That result was against `showDirectoryPicker()`, which the shipped app
doesn't use — the real "Bring In a Copy → Choose a folder instead"
flow only ever used `<input webkitdirectory>` (`importFolderFiles` in
`TrackerCreationActions`). So the open question became: does the
*actual* app's plain `webkitdirectory` picker also expose dotfiles now
in current Chrome, contrary to the assumption baked into §3j?

Tested directly against the real app, same `applications` tracker
folder, via "Bring In a Copy → Choose a folder instead" in both
browsers:

- **Safari:** import succeeded, but Adams County showed the generic
  default — *"Current status: Applied — date unknown (set before
  Timeline tracking began)."* No real `status_history` row came
  through — `.jobtracker/overrides.db` was excluded, as expected for
  Safari.
- **Chrome:** the same tracker showed *"Current status: Rejected —
  since 2026-08-29"* — a real, specific date pulled from an actual
  imported `status_history` row. `.jobtracker/overrides.db` **did**
  come across.

Both imports triggered the exact same hardcoded warning toast
regardless — *"...browsers can't include hidden files in a folder
upload..."* — even on the Chrome import where it demonstrably wasn't
true. Confirmed this wasn't new data written by one browser leaking
into the other's view: both tabs point at the same local server and
the same on-disk tracker, so once Chrome's import wrote the real
`overrides.db` to disk, any browser (and a restarted server) would
correctly show it. The toast bug was real; the "Safari picked it up
too after a refresh" observation was not evidence of a Safari
capability change, just shared server state.

**The fix (`_app/frontend/index.html`, `doImport()`):** the
post-import notice is no longer hardcoded to "folder-warning" for
every folder import. Right before the reload, the code now scans the
picked `FileList`'s `webkitRelativePath` entries for a `.jobtracker`
path segment. If found → `"folder-success"` (new notice kind — same
green toast copy as the native path: *"Folder imported — notes,
statuses, and dates carried over."*). If not found → `"folder-warning"`
as before. This makes the toast accurate per-upload, regardless of
which browser or browser version is doing the uploading — no
assumption baked in about what any given browser does.

**Toast copy also made browser-aware, advisory only.** When the
warning does fire, a `suspectedNoDotfileFolderUpload()` helper (plain
`navigator.userAgent` sniff for Chrome/Chromium/Edge) decides which
sentence to show: if the person isn't already on Chrome, the warning
now says Chrome carried these across successfully in testing, as an
alternative to the zip suggestion; if they're already on Chrome (and
it still failed), it skips that suggestion and falls back to the
zip-only wording. This UA check is explicitly cosmetic — it only picks
which sentence displays, never whether the warning fires at all. That
decision is still made solely by the real `.jobtracker` scan above.

**Considered and declined: a persistent per-tracker indicator.**
Discussed replacing/supplementing the one-shot toast with a durable
badge on the tracker itself (in the Trackers panel), backed by a new
stored flag on the workspace recording whether its last folder-import
included `.jobtracker`. Real upside (checkable any time, not just in
the seconds after a reload) but real scope (backend flag +
`api.py`/`workspace.py` changes + new UI). Decision: skip it — keep
the existing toast pattern, now accurate, since it matches how the
rest of the app already surfaces this class of feedback (undo-delete,
error toasts) and the user wants to keep this simple.

**Not covered by this fix:** the native desktop folder-import path
(`import_workspace_from_local_folder`) and zip imports were already
unconditionally correct (§16) and are untouched. No backend files
changed this session — this was frontend-only, same as §14.

## 18. Session 9 (cont'd) — pre-import Chrome handoff, offered as clear numbered steps rather than a one-click "magic" action

Building on §17's accurate toast, the user asked whether the *warning*
could become a proactive offer at the moment of import — before the
lossy copy happens — to hand off to Chrome instead, and asked
specifically that the app "make sure they open the Chrome app," with
easy, understandable steps.

**What's actually possible here, stated plainly (and to the user
before building it):** no web page can detect which browsers are
installed on the machine — that's blocked deliberately, for privacy,
in every browser. The best available mechanism is Chrome's registered
`googlechrome://` link scheme, which silently does nothing if Chrome
isn't installed or hasn't registered it — there is no error to catch,
no way to confirm success, and no way to bring the person back to
Safari automatically afterward. "Make sure" therefore can't mean
"guarantee" at the code level; it was implemented as "make failure
impossible to get stuck on" instead, via an explicit fallback at every
step.

**New: `ChromeHandoffModal`** (`_app/frontend/index.html`) — shown when
"Import a Copy" is clicked with a picked *folder* (not zip) that's
missing `.jobtracker`, in a browser not already detected as Chrome.
Presented as four numbered steps rather than a single button:
1. Click **Open in Chrome** (an `<a href="googlechrome://...">` built
   from the current host/path, landing on `?view=pipeline`) — with an
   inline note that this app has no way to confirm in advance whether
   it'll work.
2. If nothing happened: a read-only input pre-filled with the plain
   `https://` version of the same URL, plus a one-click **Copy**
   button (`navigator.clipboard`), so the person can open Chrome
   themselves and paste it in rather than being stuck.
3. Use "Bring In a Copy" again, now in Chrome.
4. Come back to this tab whenever — nothing here changes meanwhile.

Below the steps: **Continue Importing Here Instead** (proceeds with
today's lossy import, closing the modal first) and **Cancel** (just
closes it, no import). Styled with the app's existing
`.modal-backdrop`/`.modal`/`.modal-foot` classes already used by
`FixTypeModal`/`RenameModal`/etc., so it matches the rest of the app
rather than introducing a new visual pattern.

**Shared detection logic, not duplicated.** The "does this picked
FileList actually contain `.jobtracker`" check from §17's toast fix
was pulled out into one function, `folderFilesIncludeDotfile()`, used
by both the pre-import modal gate and the post-import toast decision
in `doImport()` — one source of truth for "did this upload actually
include the dotfile," rather than the pre-check and the toast
potentially disagreeing.

**Scope respected:** the modal only appears for the *browser folder
upload* path (`packaged` is false and a folder, not a zip, was
picked). Zip imports and the packaged desktop's native folder
import/link paths are already lossless (§16) and are completely
unaffected — this only intercepts the one path that's ever actually
lossy.

**Not yet exercised by the user as of this point:** clicking "Open in
Chrome" for real, to confirm the `googlechrome://` handoff actually
launches Chrome on this machine (expected to work, since Chrome is
confirmed installed per §17's testing, but not yet clicked through in
this session), and the copy-to-clipboard fallback button. No backend
files changed this session — frontend-only, same as §14 and §17.

## 19. Session 9 (cont'd) — googlechrome:// scheme confirmed dead; modal simplified to copy-paste only, close button clarified

User tested the §18 modal for real. Two findings from that test:

**"Open in Chrome" failed loudly, not silently.** Clicking it threw a
visible Safari system dialog — *"Safari cannot open the page because
the address is invalid"* — rather than the silent no-op §18 was
designed around. Undocumented custom URL schemes like
`googlechrome://` are apparently no longer registered / accepted the
same way on current macOS + Safari, and Safari now validates and
rejects unknown schemes with an alert instead of quietly ignoring
them. That's worse than what was planned for (a confusing failure
mode is worse than an invisible one), so the scheme link has been
**removed entirely** rather than patched — no way to distinguish
"not installed" from "scheme rejected" from a web page in either
case, so there was nothing left to salvage. The copy-the-address step
is now the only path: slower, but it always works and never throws
something scary.

**Step 4 didn't say which button meant "done."** The modal told
people to "come back to this tab" but never named the action that
actually closes it out — `Cancel` was the correct button but didn't
read that way. Renamed to **"I'm Done — Close This"**, in the primary
button slot (`onCancel` under the hood — same behavior, closes the
modal without importing here — just clearer copy).

**Result confirmed working end-to-end anyway**, via the manual
copy/paste fallback: user copied the URL, pasted into Chrome, redid
"Bring In a Copy" there, and the import succeeded — Pipeline showed
110 real applications with notes/statuses/dates intact.

**Noted, not fixed this session — likely stray empty folder on
disk.** The first (Safari) attempt got far enough to create a
`JobTracker — applications` sibling folder via `_new_sibling_root()`
(`_app/workspace.py`) before the upload itself failed. The Chrome
import that followed used the same tracker name, so
`_new_sibling_root()`'s collision handling incremented it to
`JobTracker — applications (2)` — which is the real, complete
tracker (confirmed: 719 files, intact `.jobtracker/jobtracker.db` +
`overrides.db`). The `(2)` suffix visible in Settings' index root is
therefore expected/correct collision-avoidance behavior, not data
loss or duplication of the live tracker — but the original empty/
partial `JobTracker — applications` folder from the failed first
attempt is likely still sitting on disk unused. Not cleaned up
automatically (this app never deletes sibling folders it didn't just
create), and not yet confirmed present/absent — worth a manual check
next session.

**Files changed:** `_app/frontend/index.html` only — `ChromeHandoffModal`
component. No backend changes.

## 20. Session 9 (cont'd) — "I'm Done" now reloads the tab, not just closes the modal

Testing §19's fix surfaced one more gap: the modal told people to click
**I'm Done — Close This** once they'd finished importing in Chrome, but
that button only closed the modal — it never refreshed this tab's own
state. Since the actual import happened in a *separate browser
entirely*, this tab has no in-process way of knowing a tracker now
exists; every other successful-import path in this app
(`doImport()`, native/link imports, switching trackers) already calls
`window.location.reload()` immediately afterward for exactly this
reason (see the handful of `window.location.reload()` calls already in
`_app/frontend/index.html`). This modal's exit button was the one
path that skipped it, so clicking "I'm Done" left the person staring
at the same stale, empty "Nothing here" pipeline they started with.

**Fix:** the primary button now calls a small `finishedInChrome()`
wrapper — `onCancel()` then `window.location.reload()` — instead of
`onCancel` directly. The `\u2715` close button and backdrop-click still
call plain `onCancel` with no reload, since clicking those doesn't
imply the person actually went and finished anything in Chrome (they
might be backing out of the modal having never left this tab). Step 4's
copy was also updated to say the tab will refresh automatically,
rather than needing a separate manual instruction to reload.

**Files changed:** `_app/frontend/index.html` only — `ChromeHandoffModal`.
No backend changes.

## 21. Session 9 (cont'd) — orphaned "JobTracker — <name>" folders now surfaced instead of accumulating silently

The five stale folders found under `~/Documents/JobTracker Hub/` (§18-20's
testing debris: `JobTracker — Hub Reimported`, `(2)`, `JobTracker —
Reimported`, `(2)`) turned out to have a fixable root cause, not just a
one-off cleanup. Traced it down:

**Root cause.** Every create/import path (`create_workspace()`,
`import_workspace_from_zip/files/local_folder()`) calls
`_new_sibling_root()` to pick a folder name, which avoids colliding with
whatever's already on disk by silently incrementing to `(2)`, `(3)`,
etc. — and always has. Separately, `delete_workspace()` *does* properly
send an owned tracker's folder to the OS Trash when removed through the
app. The gap: `_new_sibling_root()` has no way to tell "a folder
actively being used by a tracker" from "a folder some earlier session
left behind" (registry reset during dev, app reinstalled, manual
`workspaces.json` edits, etc.) — this app's registry is the *only*
record of which folders are real trackers, and a folder can silently
outlive its registry entry. So every time that happens, the name
quietly climbs a suffix higher, forever, with nothing ever telling the
person it happened.

**Fix — surface it instead of hiding it.** `_new_sibling_root()`
(`_app/workspace.py`) now returns `(root, skipped)` instead of just
`root`, where `skipped` is how many pre-existing collisions it stepped
past. Threaded through all four call sites and `_finish_import()`'s
returned entry dict as `stale_siblings_found`, then through the four
relevant `/api/workspaces*` POST endpoints in `_app/api.py` (create,
zip-import, folder-import, local-folder-import — `link_workspace` is
correctly excluded, since linking never creates a sibling folder in the
first place).

**Frontend.** `doCreate()` and `doImport()` (`_app/frontend/index.html`)
now read `stale_siblings_found` off the response and, when it's above
0, stash the count in a new one-shot sessionStorage key
(`STALE_SIBLINGS_KEY`) alongside the existing `IMPORT_NOTICE_KEY`
pattern, consumed after the post-import reload. Folded into whatever
toast is already showing (or shown on its own for the plain "Start
Fresh" path, which has no other notice) — advisory, not an error, since
the new tracker itself is completely fine either way: *"Note: N older
folders with this same name already existed on disk and were left
alone — this created a new, separate one instead. Worth a look in
Finder if you don't recognize them."*

**Verified logic in isolation** (sandbox has no network access, so the
real pytest suite couldn't run — `pip install` fails outright): a
standalone reimplementation of the exact collision-counting loop now in
`_new_sibling_root()` reproduces the precise naming sequence seen in the
screenshots (`Reimported` → `Reimported (2)` → `Reimported (3)`,
skipped counts 0 → 1 → 2). `ast.parse()` confirms both modified backend
files are still syntactically valid. **Not yet run against the real
test suite or exercised by the user** — worth doing both before calling
this closed.

**Not covered by this fix:** the packaged desktop's native folder-import
path (`confirmImportFolderNative()` → `window.pywebview.api.
confirm_import_folder` → `desktop/launcher.py`) also ultimately calls
`import_workspace_from_local_folder()` and would carry the same
`stale_siblings_found` field back from the Python bridge — but that
bridge method itself wasn't touched this session, so it's unconfirmed
whether its result dict passes the field through or discards it. Only
the two browser-facing paths (`doCreate`, `doImport`) are confirmed
wired end-to-end.

**Not addressed at all:** the five specific stale folders already on
disk from before this fix existed are untouched by it — this only
prevents new ones from accumulating silently going forward. Deleting
the existing five is still a manual step for the user, whenever they're
ready.

**Files changed:** `_app/workspace.py`, `_app/api.py`,
`_app/frontend/index.html`.

---

## 22. Session 9 (cont'd) — §21's stale-siblings fix validated end-to-end (real pytest + real browsers), and its one open gap (native folder-import path) closed

§21 above shipped `stale_siblings_found` for the two browser-facing
paths (`doCreate`, `doImport`) but left the packaged desktop's native
folder-import path (`confirmImportFolderNative()` →
`window.pywebview.api.confirm_import_folder` → `desktop/launcher.py`)
explicitly unconfirmed. This session ran the full validation plan for
§21 and closed that gap.

**Step 1–2 — real pytest suite.** The user ran the actual suite (not
the sandboxed reimplementation from §21) twice: **150/150 both times.**
Confirms the `_new_sibling_root()` tuple-return change threaded through
`_app/workspace.py` and `_app/api.py` broke nothing, including
`test_import_local_folder.py`. (A pasted block of shell errors after
the second run — `zsh: command not found: collected`, `permission
denied: tests/test_export.py`, etc. — was the terminal re-executing
copied pytest output as commands, not a test failure; pytest had
already finished cleanly.)

**Step 3–4 — browser paths.** User confirmed both Safari and Chrome
work correctly.

**Step 5 — native/packaged path, the gap §21 flagged.** Traced it
precisely instead of guessing:
- `/api/workspaces/import-folder-local` (`_app/api.py`) already returns
  `{"ok": True, "workspace": {..., "stale_siblings_found": N}}`
  correctly — the backend side of §21 was fine.
- The break was entirely in `desktop/launcher.py`'s
  `confirm_import_folder()`: it called `_http_json(...)`, threw the
  parsed response away, and unconditionally returned `{"error": None}`.
  Confirmed `_http_json` does return the parsed JSON body (a plain
  dict via `json.loads`), so the fix is just wiring the discarded
  result through: now returns `{"error": None, "workspace":
  result.get("workspace")}`.
- The frontend's `confirmImportFolderNative()` (`_app/frontend/
  index.html`) was reading only `result.error` and never looked at
  `result.workspace` at all. Added the same
  `staleCount`/`STALE_SIBLINGS_KEY` block that `doCreate()`/`doImport()`
  already use, so all three import paths now handle
  `stale_siblings_found` identically.
- User confirmed live: no stale siblings were found in their actual
  test run (expected — a clean folder-import shouldn't trigger the
  notice), so this closes the code-path gap; it doesn't add a new
  positive real-world observation of the toast firing via this
  specific path. The manufactured-collision scenario from §21 was
  never re-run against the native path specifically.

**Verification done this session (not by running the app):**
`python3 -m py_compile` on `desktop/launcher.py` (clean), and a real
Babel (`@babel/preset-react`) `transformSync` on the full
`<script type="text/babel">` block of `_app/frontend/index.html`
(clean) — stronger than §21's structural-parse-only check, since it
actually runs the JSX/ES6+ transform rather than just balancing
brackets.

**Step 6 — toast/UX.** User confirmed the resulting toast is correct.

**Step 7 — this update.** Per the user, writing it up was left to
Claude's judgement; this section is that write-up. **All of §21's
"not yet run/not covered" caveats from that section are now resolved:**
real suite run twice (150/150), both browser paths tested live, and
the native path's gap identified, fixed, and confirmed not to error.
§21's separate, still-open item — the five pre-existing stale folders
already on disk — is unrelated cleanup and remains a manual step for
the user whenever they're ready.

**Files changed this session:** `desktop/launcher.py`,
`_app/frontend/index.html`. Claude has not staged, committed, or
pushed anything, per §6.
