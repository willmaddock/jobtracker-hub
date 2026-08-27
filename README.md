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

## 📦 Download for macOS

The easiest way to run JobTracker Hub — no Python, no Terminal, no setup.

**[⬇ Download JobTracker Hub.dmg](https://github.com/willmaddock/jobtracker-hub/releases/latest)**

Open the `.dmg`, drag **JobTracker Hub** into **Applications**, then launch
it like any other Mac app. First launch will ask you to pick (or create)
the folder you want it to track — everything after that happens in the
window shown above.

> Prefer to run from source, or want to poke at the code? Skip to
> [Quickstart](#quickstart-try-it-with-sample-data-first) below.

**Full user guide:** [`docs/JobTracker_User_Guide.pdf`](docs/JobTracker_User_Guide.pdf)
— a longer walkthrough of every screen and workflow, if you want more than
this README. LaTeX source lives in `docs/guide-src/` if you want to edit
or rebuild it.

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
it). If you'd rather keep it around as a reference tracker instead, use
**Import tracker → Choose a folder instead** and point it at
`sample-tracker/` to add it to the switcher explicitly.

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

- **A second tracker inside the same running app**: use the tracker
  switcher in the UI to create a sibling tracker with its own root and
  database pair — no copying, no second server.
- **A genuinely separate installation**: copy `_app/` into any other
  folder you want to track (a different computer, a different repo,
  someone else's setup entirely) — leave `jobtracker.db`, `overrides.db`,
  `workspaces.json`, `workspaces/`, and `__pycache__/` behind, since those
  are this tracker's own local state, not code. It auto-detects its root
  as whatever folder `_app/` is sitting inside, exactly like the original.

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
  dates, merges) — `overrides.db`.
- `build_index.py` — the filesystem parser; also runnable standalone:
  `python build_index.py` (defaults to `DEFAULT_ROOT`) or
  `python build_index.py /explicit/path`. Produces `jobtracker.db`.
- `classify.py` / `classify_config.json` — classification heuristics
  (section mapping, doc type, status inference, ignore rules) — see
  "Customizing classification" above.
- `workspace.py` — multiple-tracker/workspace bookkeeping.
- `labels.py` — the section/doc-type display labels the frontend renders.
- `api.py` — FastAPI server exposing the backend as JSON, and serving
  the frontend itself.

Frontend:
- `frontend/index.html` — the dark master-detail + Kanban UI described
  above. Single file, React from a CDN, no build tooling required.

Documentation:
- `docs/JobTracker_User_Guide.pdf` — the full user guide.
- `docs/guide-src/` — its LaTeX source and screenshots, if you want to
  edit or rebuild the PDF.

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

**Note on Gatekeeper:** this is an unsigned, ad-hoc build (no Apple
Developer ID), so macOS will flag it as being from an "unidentified
developer" on first launch. Right-click the app (or the `.dmg`'s app
icon) and choose **Open**, or go to **System Settings → Privacy &
Security → Open Anyway**, instead of double-clicking.

## License

MIT — see `LICENSE`. Use it, fork it, sell your own hosted version of it,
whatever you want.

## Author

JobTracker Hub is a full-stack application (Python/FastAPI backend,
React frontend) built by William Maddock —
[portfolio](https://willmaddock.github.io/dev/)
