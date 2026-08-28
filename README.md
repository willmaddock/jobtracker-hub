# JobTracker Hub

[![Download for macOS](https://img.shields.io/badge/Download-macOS%20.dmg-0d1117?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/willmaddock/jobtracker-hub/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-3fb950?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS-lightgrey?style=for-the-badge&logo=apple&logoColor=white)](#-download-for-macos)

**v1.0.0**

A local, private dashboard over a folder of job-application documents you
already keep on disk — a real pipeline view (list + drag-and-drop Kanban),
follow-up tracking, notes, search, and light document management (upload,
rename, delete) — with everything staying on your machine.

![JobTracker Hub demo — installing from the DMG and touring the Pipeline, Kanban, Needs Attention, and Search Hub views](docs/media/jobtracker-hub-demo.gif)

No account, no cloud, no server other than the one you run yourself on
`localhost`. It reads whatever folder structure you already use for job
hunting and turns it into a dashboard; it never uploads anything anywhere.

## Contents

- [📦 Download for macOS](#-download-for-macos)
  - [🔓 macOS blocked the app? (first launch)](#-macos-blocked-the-app-first-launch)
- [Quickstart (try it with sample data first)](#quickstart-try-it-with-sample-data-first)
- [Zero-config layout: drop `_app/` inside your own tracker folder](#zero-config-layout-drop-_app-inside-your-own-tracker-folder)
- [Customizing classification for your own folders](#customizing-classification-for-your-own-folders)
- [Running it](#running-it)
- [Running the tests](#running-the-tests)
- [Two local databases, two very different lifetimes](#two-local-databases-two-very-different-lifetimes)
- [What it does](#what-it-does)
- [Power-user features](#power-user-features)
- [Multiple trackers / a second, independent installation](#multiple-trackers--a-second-independent-installation)
- [Why "Date applied" matters more than file dates](#why-date-applied-matters-more-than-file-dates)
- [Files](#files)
- [Building the macOS app (.dmg) from source](#building-the-macos-app-dmg-from-source)
- [License](#license)
- [Author](#author)

## 📦 Download for macOS

The easiest way to run JobTracker Hub — no Python, no Terminal, no setup.

**[⬇ Download JobTracker Hub.dmg](https://github.com/willmaddock/jobtracker-hub/releases/latest)**

1. Open the downloaded `.dmg` and drag **JobTracker Hub** into
   **Applications**.
2. Open **JobTracker Hub** from your **Applications** folder. macOS will
   block it the first time — this is expected for an unsigned,
   non-notarized build, not a sign anything's wrong. See
   **[macOS blocked the app? Click here ▸](#-macos-blocked-the-app-first-launch)**
   for the exact steps.
3. First launch will ask you to pick (or create) the folder you want it
   to track — everything after that happens in the window shown above.

> Prefer to run from source, or want to poke at the code? Skip to
> [Quickstart](#quickstart-try-it-with-sample-data-first) below.

**Full user guide:** [`docs/JobTracker_User_Guide.pdf`](docs/JobTracker_User_Guide.pdf)
— a longer walkthrough of every screen and workflow, if you want more than
this README. LaTeX source lives in `docs/guide-src/` if you want to edit
or rebuild it.

### 🔓 macOS blocked the app? (first launch)

This happens on **every** first launch of this app — downloaded `.dmg`
or self-built — because it's an unsigned, ad-hoc build (no Apple
Developer ID). It doesn't mean anything is wrong with it.

The first dialog you'll see is titled **"JobTracker Hub.app" Not
Opened**, with only two buttons: **Move to Trash** and **Done** — there's
no **Open Anyway** button here yet.

1. Click **Done** — not "Move to Trash."
2. In **Applications**, right-click (or Control-click) **JobTracker
   Hub** and choose **Open**. A second dialog appears, this one with an
   actual **Open** button — click it.
3. If right-click doesn't offer **Open**, go to **System Settings →
   Privacy & Security**, scroll to **Security**, and click **Open
   Anyway** next to the message about JobTracker Hub being blocked.

You only need to do this once — macOS remembers your choice after that.

## Quickstart (try it with sample data first)

This repo ships a small `sample-tracker/` folder with a couple of fake
companies so you can see the app working before pointing it at your real
documents.

```bash
cp -r sample-tracker my-tracker
cp -r _app my-tracker/_app
cd my-tracker/_app
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

Then open **`http://127.0.0.1:8000`** in your browser and click **Build
index**. You should see "Acme Robotics" and "Riverbend Public Library" as
sample applications. Once you're happy with how it looks, swap in your
own `Applications/`, `Certifications/`, etc. folders and rebuild.

**What just happened, and what's left over:** the moment `_app` runs from
*inside* `my-tracker/`, that folder is automatically registered as your
first tracker — named "Job Search" by default — and shows up in the
tracker switcher (click the **J** top-left) immediately. No import step
needed; this only happens for the one folder `_app` physically lives in.

The original `sample-tracker/` folder, on the other hand, is left
completely untouched by all of this — it's not a tracker, the app has no
record of it, it's just the leftover template you copied *from*. Once
you're comfortable with the app, it's safe to delete (plain
`rm -rf sample-tracker` / move to Trash — nothing in the app references
it). If you'd rather keep it around as a reference tracker instead, click the
tracker switcher (the **J** top-left) → **Use an Existing Folder**, point
it at `sample-tracker/`, and confirm — you'll see a quick preview (doc
count, whether it already looks like a tracker) before anything's added
to the switcher.

## Zero-config layout: drop `_app/` inside your own tracker folder

All app code (backend + frontend + both local databases) lives in one
self-contained folder, **`_app/`**, meant to be nested one level *inside*
the folder of job-search documents you want it to index:

```
MyTracker/                 <- your real files, completely untouched
├── Applications/
│   └── SomeCompany/
│       ├── resume.pdf
│       └── coverletter.pdf
├── Certifications/
├── ... whatever other folders you already have ...
└── _app/                  <- this project
    ├── api.py, db.py, build_index.py, classify.py, classify_config.json
    ├── overrides_store.py, workspace.py, labels.py
    ├── frontend/index.html
    ├── requirements.txt
    └── (jobtracker.db, overrides.db — created on first run, gitignored)
```

Because `_app/` always knows it's nested one level inside the folder it
should index, **there is no path to type in, paste, or configure.**
`build_index.py`/`db.py` resolve the scan target as `..` — the parent of
`_app/` — automatically, and the indexer explicitly skips `_app/` itself,
every hidden dir/file, and any `.zip` archive anywhere in the tree, so the
app never tries to index its own code, its own databases, or backups of
itself. Just click **Build index** the first time you run it.

## Customizing classification for your own folders

Classification (which folder maps to which section, and document type
guessing) is filename-based and lives in two places:

- **`classify_config.json`** — the file you're expected to edit. It holds
  the section-mapping rules (which top-level folder name maps to which
  part of the dashboard) and an optional, disabled-by-default
  `nested_application_markers` pattern for folders that bundle real job
  applications inside a dated compliance/case-management structure (common
  with state unemployment/workforce-center reporting requirements — see
  the example inside the file). Edit this, then rebuild the index —
  `overrides.db` is untouched by a rebuild.
- **`classify.py`** — the document-type regexes (resume / cover letter /
  interview prep / rejection notice / etc.) are generic keyword matches
  that work for most people out of the box. You generally shouldn't need
  to touch this file; if a filename convention of yours isn't being
  picked up, it's a one-line regex edit here, same as before.

If a folder name doesn't match any rule in `classify_config.json`, it
still gets its own tab automatically (its name is slugified into a
section id) — you only need to add a rule if you want it to merge into an
*existing* section like Credentials or Network.

## Running it

The frontend is a single static HTML file (`frontend/index.html`, React
loaded from a CDN, no build step) served directly by a small local API
server (`api.py`, FastAPI) — one process, one address, no separate dev
server or build tooling.

```bash
cd _app
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --reload --port 8000
```

Then open **`http://127.0.0.1:8000`** in your browser and click **Build
index** on first load. (The frontend's own requests are relative — e.g.
`fetch("/api/...")` — so it needs to be loaded from that address rather
than opened as a bare `frontend/index.html` file; opening it directly
won't be able to reach the API.)

**Privacy:** `api.py` binds to `127.0.0.1`/`localhost` only — nothing
here is reachable from your LAN or the internet. File endpoints resolve
every path against the tracker root and refuse anything that would
escape it.

## Running the tests

The backend has a pytest suite (`tests/`) covering workspace
linking/switching/deletion, `/api/file`'s path-traversal and symlink
protections, export-zip integrity, folder-copy import (and its preview
step), pre-link folder inspection, notes/status/hub-settings
portability across relink and export/import, and Search Hub settings
persistence. Run it from the **repository root** (not from inside
`_app/`) — that's where `pytest.ini` and `requirements-dev.txt` live,
and where the paths in the commands below resolve from:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r _app/requirements.txt -r requirements-dev.txt
pytest
```

**Prerequisites:** the same Python 3 you'd use for `_app/` itself (3.10+
recommended) — everything else needed comes from those two requirements
files (`_app/requirements.txt` for the app's own runtime deps, plus
`requirements-dev.txt` for `pytest`/`httpx`, the test-only additions).
No separate services, no real tracker folder, and nothing macOS-only —
the suite runs the same way on Linux/Windows CI.

This test venv is intentionally separate from `_app/.venv` created in
[Running it](#running-it) above, so `pytest`/`httpx` never end up bundled
into the shipped app's own dependencies. The suite also runs in a
throwaway, session-scoped state directory (`JOBTRACKER_STATE_DIR`,
env var set in `tests/conftest.py`) instead of your real
`~/Library/Application Support/JobTracker Hub` — safe to run against a
real checkout without touching (or losing) any tracker you already have
set up.

A clean run reports `48 passed`:

```bash
$ pytest
========================= test session starts ==========================
collected 48 items
tests/test_export.py ...
tests/test_file_serving.py ......
tests/test_hub_settings.py .......
tests/test_import_local_folder.py ........
tests/test_overrides_portability.py ....
tests/test_workspace_inspect.py ...........
tests/test_workspaces.py .........
==================== 48 passed, 1 warning in 0.90s =====================
```

## Two local databases, two very different lifetimes

- **`jobtracker.db`** — the disposable, auto-built index. Every click of
  **Rebuild index** drops and fully rewrites it from whatever's currently
  on disk. Safe to delete any time.
- **`overrides.db`** — *your* data: manual status corrections, notes,
  applied dates, next actions, snoozes, archived items, company merges.
  **Rebuild index never touches this file.** It's keyed by a stable
  `item_key` (section + company + role folder + path), so your notes stay
  attached to the right application even after a full rebuild, as long as
  you don't rename a company/role folder.

Both files are gitignored — they hold your personal data and are never
meant to be committed.

## What it does

- **Pipeline** — every application, as cards (list view) or a
  drag-and-drop Kanban board grouped by status. Each card shows how many
  days it's been sitting, and flags itself if it's gone quiet.
- **Needs Attention** — the triage view: applications with no update in
  21+ days (applied/interviewing) or 14+ days (drafted/unknown), plus
  anything with a next-action date that's arrived. Mark followed-up,
  snooze 7 days, archive, or bulk-select and apply an action — nothing is
  ever deleted.
- **Search & Retrieval** — full-text search across every indexed
  filename/company/role, with matches highlighted inline.
- **Browse by Section** — everything outside `Applications/`: whatever
  categories you've configured (Credentials, Network, Resume Library,
  Leads, Compliance, or any custom folder), plus a Personal section
  hidden by default.
- **Insights** — response rate, interview rate, average time-to-response,
  plus velocity and status-distribution charts.
- **Manage** — merge companies that got split across multiple folders,
  undo a merge, and see/restore archived applications.
- **Search Hub** — a curated directory of external job-search sites
  (higher-ed, K-12, AI job-search assistants, government, mainstream
  boards), grouped by category. Set your target role/location once and
  it builds a ready-to-paste AI prompt plus per-site search links; add
  your own custom cards or override any built-in link's title/URL.
  Everything here is saved server-side (`overrides.db`, same as your
  notes) via `/api/hub/settings`, so it travels with the tracker through
  export/import instead of being pinned to one browser.

## Power-user features

- **Document management** — drag-and-drop upload onto any application;
  rename in place; delete moves the real file to your OS Trash (never a
  permanent unlink), with an Undo toast before the move happens.
- **Source files hidden by default** — `.tex` and similar source files
  stay searchable but are hidden from document lists by default (toggle
  "Show source files"). Content-hash duplicate detection flags
  byte-identical files without touching anything automatically.
- **Command palette** — `⌘K`/`Ctrl+K` for fuzzy search across every
  application, quick view jumps, and a Rebuild index action.
- **Keyboard navigation** — `j`/`k`/arrow keys move focus in list views;
  `Enter` opens the first PDF inline; `Esc` closes whatever's open.
- **Drag-and-drop Kanban** — native HTML5 drag & drop; dropping a card in
  a new column updates its status immediately.
- **Batch operations** — multi-select in Needs Attention with bulk move
  to Applied / mark Rejected / Archive.
- **Inline document viewer** — click the eye icon to open a PDF in a side
  drawer instead of shelling out to your OS's default app.
- **Search highlighting** — matching terms highlighted directly in
  results as you type.
- **URL-driven state + local caching** — current view/selection mirrored
  to the URL for bookmarking/sharing; last-loaded index cached in
  `localStorage` for instant repaint on reopen.
- **Insights charts** — Chart.js velocity and status-distribution charts.

## Multiple trackers / a second, independent installation

The tracker switcher (click the **J** top-left, or the first-run screen
if you have no tracker yet) offers three ways to add one:

- **Create New Tracker** — a blank tracker with an empty `Applications/`
  folder, owned by the app.
- **Import a Copy** — copies an existing folder's contents (or a `.zip`
  export) into a new, independent tracker; the original folder is never
  modified.
- **Use an Existing Folder** *(packaged `.dmg` build only — browsers
  can't hand JavaScript a raw filesystem path)* — points a tracker
  directly at a folder in place, nothing is copied or moved.

In the packaged desktop app, both **Import a Copy**'s "Choose a folder
instead" option and **Use an Existing Folder** show a preview — file
count, whether the folder already looks JobTracker-shaped and would
bring its notes/statuses/dates along, whether it's empty — before
anything happens, so you can back out and pick a different folder
instead of committing blind. The one difference: a folder that's
*already linked as another tracker* is a hard block for **Use an
Existing Folder** (two trackers can't safely share one live folder) but
only a soft warning for **Import a Copy** (copying a tracked folder is
harmless). In the browser, folder import still works via your OS's
folder picker, just without that preview step first.

**A genuinely separate installation**, outside this app's UI entirely:
copy `_app/` into any other folder you want to track (a different
computer, a different repo, someone else's setup entirely) — leave
`jobtracker.db`, `overrides.db`, `workspaces.json`, `workspaces/`, and
`__pycache__/` behind, since those are this tracker's own local state,
not code. It auto-detects its root as whatever folder `_app/` is sitting
inside, exactly like the original.

**Fixing a tracker named "JobTracker — JobTracker — \<name\>":** versions
before this fix could double-prefix an owned tracker's name/folder if you
imported from an existing app-owned tracker folder without typing an
explicit name (see `workspace._strip_owned_prefix`'s docstring for why).
If you already have one of these, quit the app and run
`scripts/fix_doubled_tracker_names.py` (dry run by default; add `--apply`
to actually rename things) — it collapses the name and folder back to a
single prefix and leaves everything else untouched. It only ever touches
app-owned trackers, never a linked folder.

## Why "Date applied" matters more than file dates

"Last activity" purely from file modification time breaks the moment you
copy, sync, or reorganize your tracker folder — every file's mtime resets,
so everything looks "recently active" even if you applied months ago. This
app still falls back to file mtime when nothing else is available, but
every application card lets you set a real **Date applied**, and the
Insights velocity chart is built from it too. Setting this on your active
applications is the highest-leverage thing to do after your first
rebuild.

## Files

Backend:
- `db.py` — combines the auto-built index with your overrides into the
  "effective" status/company/staleness the app renders; computes Insights
  metrics; exposes `DEFAULT_ROOT` (`_app/`'s parent folder).
- `overrides_store.py` — your durable local data (notes, manual status,
  dates, merges, and Search Hub settings) — `overrides.db`. Lives inside
  each tracker's own `.jobtracker/` folder so it travels with the folder
  through relink and export/import.
- `build_index.py` — the filesystem parser; also runnable standalone:
  `python build_index.py` (defaults to `DEFAULT_ROOT`) or
  `python build_index.py /explicit/path`. Produces `jobtracker.db`.
- `classify.py` / `classify_config.json` — classification heuristics
  (section mapping, doc type, status inference, ignore rules) — see
  "Customizing classification" above.
- `workspace.py` — multiple-tracker/workspace bookkeeping: create, link,
  import (zip/upload/local-folder copy), switch, rename, delete, export,
  and `inspect_folder()` — the pick-a-folder preview used by both the
  link and import flows (doc count, tracker-shaped detection, already-
  linked-elsewhere detection).
- `labels.py` — the section/doc-type display labels the frontend renders.
- `api.py` — FastAPI server exposing the backend as JSON, and serving
  the frontend itself. Includes `/api/workspaces/inspect`,
  `/api/workspaces/import-folder-local` (packaged-desktop folder copy),
  and `/api/hub/settings` (Search Hub persistence).

Frontend:
- `frontend/index.html` — the dark master-detail + Kanban UI described
  above. Single file, React from a CDN, no build tooling required.

Desktop packaging:
- `desktop/launcher.py` — the pywebview bridge (`Api` class) the packaged
  `.dmg` build talks to for native folder pickers: `pick_folder`,
  `inspect_folder`, `confirm_link_folder`, `confirm_import_folder`, and
  `confirm_first_run_link` back the same pick → preview → confirm flow
  described in "Multiple trackers" above.
- `desktop/first_run.html` — the first-run window shown before any
  tracker exists in a fresh packaged install.

Documentation:
- `docs/JobTracker_User_Guide.pdf` — the full user guide.
- `docs/guide-src/` — its LaTeX source and screenshots, if you want to
  edit or rebuild the PDF.

Tests:
- `tests/` — the pytest suite; see [Running the tests](#running-the-tests).
- `requirements-dev.txt` — test-only dependencies (`pytest`, `httpx`),
  installed alongside `_app/requirements.txt`.
- `pytest.ini` — points pytest at `tests/`.

Maintenance scripts:
- `scripts/fix_doubled_tracker_names.py` — one-off cleanup for a tracker
  name/folder doubled by a since-fixed bug — see "Multiple trackers"
  above.

## Building the macOS app (.dmg) from source

The desktop-app packaging tooling lives in `scripts/`, `desktop/`, and
`assets/`, alongside `_app/`. To build your own `.dmg`:

```bash
chmod +x scripts/*.sh
./scripts/build-macos.sh      # creates dist/JobTracker Hub.app
./scripts/package-dmg.sh      # wraps it into dist/JobTracker Hub.dmg
```

`build-macos.sh` creates its own build-only virtualenv (`.build-venv/`,
gitignored) and runs PyInstaller against `desktop/entry.py` — it doesn't
touch your normal `_app/.venv`. Both `dist/` and `build/` are gitignored,
so nothing from a build gets committed; every maintainer builds locally
from the same source.

**Note on Gatekeeper:** your own build hits the same unsigned/non-notarized
warning as the downloaded `.dmg` — see
**[macOS blocked the app? ▸](#-macos-blocked-the-app-first-launch)**
near the top of this README for the exact click-through steps.

## License

MIT — see `LICENSE`. Use it, fork it, sell your own hosted version of it,
whatever you want.

## Author

JobTracker Hub is a full-stack application (Python/FastAPI backend,
React frontend) built by William Maddock —
[portfolio](https://willmaddock.github.io/dev/)
