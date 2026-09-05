# JobTracker — Living Claude Handoff
## Email Sync → Job Postings Audit, Redesign, and Implementation

> **Purpose:** This is the single living handoff document for the JobTracker email-sync / job-postings redesign.
>
> **Rule:** Keep this file in the repository and update it continuously as work progresses. A new Claude session should read this file first, inspect the actual repository, and continue without relying on chat history.

---

## 0. Starting Repository Snapshot (2026-09-02)

This repository snapshot was supplied from the user's Mac while on branch `main`. The user reported that `main` was up to date with `origin/main` and had the following uncommitted work:

### Modified files

- `HANDOFF.md` (historical handoff; moved into `docs/archive/handoffs/` in this prepared package)
- `_app/api.py`
- `_app/frontend/index.html`
- `_app/overrides_store.py`
- `_app/requirements.txt`
- `tests/test_overrides_store.py`

### Newly created/untracked files

- `_app/email_pdf.py`
- `_app/mail_app_store.py`
- `discoveries-board-v2-spec.md` (moved into `docs/specs/` in this prepared package)
- `scripts/cleanup_bogus_account_matches.py`
- `tests/test_accounts_api.py`
- `tests/test_discoveries.py`
- `tests/test_email_pdf.py`
- `tests/test_mail_app_store.py`

The preparation of this handoff also reorganizes documentation only; it does **not** intentionally alter application behavior. The next Claude must run `git status`, inspect the diff, and verify all of this against the actual checkout before coding.

The repository also contained generated Python caches and local runtime/workspace database state in the supplied tree. Those are not part of the clean Claude-ready archive generated from this package; the source code and tests are preserved.

### Documentation organization after this preparation

- `CLAUDE_HANDOFF.md` — **single living Claude/project handoff; keep updating this file**
- `CHANGES.md` — project change history
- `docs/specs/` — durable/historical feature specifications
- `docs/archive/handoffs/` — historical session handoffs preserved for reference
- `docs/` — development logs, user guide, and project documentation


## 0A. Critical Workspace / ZIP Boundary

**The user owns and controls the real Git repository. Claude does NOT work directly in the user's Git repository.**

The development workflow is:

```text
USER'S REAL MAC GIT REPOSITORY
        │
        │ user creates/sends ZIP
        ▼
CLAUDE TEMPORARY WORKSPACE
        │
        │ Claude edits source
        │ Claude tests what it can
        │ Claude updates CLAUDE_HANDOFF.md
        ▼
UPDATED ZIP
        │
        │ Claude MUST return/attach the ZIP
        ▼
USER DOWNLOADS ZIP
        │
        │ user inspects/validates
        ▼
USER'S REAL MAC GIT REPOSITORY
```

### Absolute rules

1. Treat an uploaded ZIP as a **source snapshot**, not as the user's live Git repository.
2. Do not initialize a new Git repository in the ZIP workspace.
3. Do not commit or push.
4. Do not claim that `git status`, `git diff`, branch names, or HEAD describe the user's real checkout unless the user explicitly provides access to that checkout.
5. The user applies, merges, reviews, commits, and pushes changes in the real Mac repository.
6. `CLAUDE_HANDOFF.md` is the continuity mechanism between Claude sessions.
7. The updated repository ZIP is the **physical handoff artifact**.
8. A filename printed by a shell command is **not** a successful handoff. The ZIP must actually be attached/returned so the user can access it.
9. Never claim a handoff is complete merely because a ZIP exists in Claude's private workspace.
10. Before the practical context limit, stop feature work early enough to create, verify, and return the ZIP reliably.
11. If there is not enough remaining context to safely finish the handoff, stop feature work immediately and prioritize the handoff.
12. The next Claude session starts from the **latest ZIP actually received by the user**.

### Required handoff sequence

```text
STOP FEATURE WORK
↓
SAVE CURRENT WORK
↓
UPDATE CLAUDE_HANDOFF.md
↓
CREATE UPDATED ZIP
↓
VERIFY ZIP CONTENTS
↓
ATTACH / RETURN ZIP TO USER
↓
STOP
```

Do not begin another feature after entering the handoff sequence.

---

## 1. Mission

Redesign **Email Sync** so job-alert emails from sources such as LinkedIn, Handshake, Indeed, ZipRecruiter, and other job boards/recruiting platforms produce **actual individual job postings** under **Job Postings**.

Desired behavior:

> If one email contains six real jobs, JobTracker should represent six jobs, not one email.

Each job should have a usable direct posting/application link whenever the email provides one.

The existing **Possible New Applications** flow remains a separate concept: it is for emails that may relate to applications, interviews, recruiting activity, etc.

---

## 2. Core Product Model

The architecture should be:

```text
EMAIL SYNC
│
├── Job-alert / job-listing emails
│       ↓
│   Job Posting Extractor
│       ↓
│   N individual Job Postings
│
└── Application / recruiting emails
        ↓
    Possible New Applications / Needs Triage
```

Do **not** solve this by making `discovered_matches.kind = "posting"` the permanent job model.

The data model must support:

```text
one email → many job postings
```

---

## 3. Rule for Every New Claude Session

Before changing anything:

1. Read this file completely.
2. Inspect `git status`.
3. Inspect the current branch and HEAD.
4. Inspect the actual repository code.
5. Inspect relevant tests.
6. Determine what is already implemented versus what this document says.
7. Do not assume this document is correct if source code contradicts it.
8. Report important discrepancies before substantial changes.
9. Preserve unrelated existing work.
10. Do not reset, revert, stash, or discard changes unless explicitly instructed.
11. Do not commit or push unless the user explicitly approves it.

This file is a coordination aid, **not a substitute for inspecting the code**.

---

## 4. User's Desired UI

**Job Postings** should contain actual jobs.

A job card should ideally show:

- Job title
- Company
- Location
- Salary, when present
- Employment type, when present
- Source
- Date/age
- Direct posting/application URL
- Clear **Open job ↗** action

The count must represent **jobs**, not emails.

Example:

```text
Job Postings · 6
```

means six individual jobs, even if all six came from one LinkedIn digest.

---

## 5. Original Architecture Problem

The old system used `discovered_matches` as an email-level review queue.

Conceptually:

```text
one email = one discovery
```

That queue can be useful for application triage, but it cannot correctly represent a digest containing many jobs.

The old Job Postings count therefore counted discovery emails classified as postings, not actual jobs.

The redesign should introduce/use a first-class job-posting representation.

---

## 6. Real Email Acceptance Fixtures

Two real email examples are important regression cases.

### LinkedIn

A real LinkedIn email has a subject similar to:

```text
Software Engineer at Haystack
```

It contains six visible jobs:

1. Software Engineer — Haystack
2. Back-End Developer - WFH — Torentify
3. Backend Engineer — Piper Companies
4. Backend Software Engineer, PDP Experience — Ladders
5. Software Engineer - Work From Home — Torentify
6. Software Engineer, AI Enablement — Ladders

**Acceptance:** LinkedIn fixture → **6 postings**.

Important lesson: a legitimate job digest does not necessarily have "job alert" in its subject.

### Handshake

A real Handshake weekly jobs round-up contains at least these visible listings:

1. IT Support Desk Engineer II — Heartland Business Systems (HBS)
2. Desktop Support Technician I, II or III
3. SDR — Sales Development Representative
4. Entry Level Recruiter/Sales Trainee
5. Unified Communications Sales Consultant

There is also a **View more jobs** continuation action.

**Acceptance:** Handshake fixture → **at least 5 visible individual postings**.

"View more jobs" is **not** itself a job posting.

If the actual PDF/email fixtures are available in the current repository/session, use them instead of inventing simplified test text.

This prepared repository includes the two real source PDFs under:

```text
tests/fixtures/email-source/linkedin_job_alert_haystack.pdf
tests/fixtures/email-source/handshake_weekly_jobs_roundup.pdf
```

Treat these as regression/source fixtures. Do not modify or replace them with invented examples unless explicitly instructed.

---

## 7. Known Problems in the Original System

### 7.1 The "8" counted emails, not jobs

The old Job Postings column filtered `discovered_matches` by `kind === "posting"`.

Therefore the number was the number of qualifying discovery emails.

### 7.2 Posting subject detection was too narrow

Old patterns included things like:

- `just posted a \d+% match`
- `new .* jobs open`
- `just in:.*has new`

That misses legitimate digests such as:

```text
Software Engineer at Haystack
```

### 7.3 Sender coverage was incomplete

Some legitimate job-alert sources were not reaching the scanner.

Handshake was an important example.

### 7.4 Digest exclusions conflicted with the desired product

The old application-discovery logic deliberately excluded phrases such as:

- job alert
- jobs match your preferences
- new jobs in
- new jobs for you
- recommended jobs
- jobs for you
- jobs you may be interested in
- jobs matching
- your job recommendations
- your weekly job

Those exclusions may make sense for application triage, but they are wrong for a first-class job-posting pipeline.

### 7.5 URLs were extracted too late

The old system could extract posting URLs from a body, but extraction happened lazily during preview.

Desired:

```text
sync
→ identify job-alert email
→ fetch body
→ extract jobs
→ persist jobs
→ show jobs
```

### 7.6 One email can contain many jobs

A digest must be able to produce:

```text
email A
├── job 1
├── job 2
├── job 3
├── job 4
├── job 5
└── job 6
```

---

## 8. Desired Job Posting Data Model

Exact fields should follow the actual codebase, but conceptually a job-posting record should support:

```text
job_postings
------------------------------
id
account_id
message_id
source
title
company
location
salary
employment_type
posting_url
received_at
email_subject
sender
status
created_at
dedupe_key
```

Potential later fields, only if justified:

```text
description
remote
job_id
posted_date
application_url
```

Prioritize:

1. One row per job.
2. Traceability to the source email.
3. Direct URL when available.
4. Deterministic deduplication.
5. Safe repeated sync.

---

## 9. Deduplication

Repeated sync must not create duplicate jobs.

Preferred identity when possible:

```text
account_id + normalized posting URL
```

Fallback when there is no reliable URL:

```text
account_id + message_id + normalized title + normalized company
```

or an equivalent deterministic hash.

Test at minimum:

- same email scanned twice → no duplicates
- same URL in multiple emails → normally one posting for the account
- one linkless email containing two different jobs → both survive
- similar title/company but genuinely different jobs → do not over-collapse

Document the actual normalization rules selected.

---

## 10. Extraction Strategy

Use deterministic layered extraction.

### Layer 1 — Source recognition

Recognize known job-alert sources by sender/domain.

Examples:

- LinkedIn
- Handshake
- Indeed
- ZipRecruiter
- other known job boards

Keep source recognition testable/configurable.

### Layer 2 — Subject signals

Use subject wording as evidence, not the sole requirement.

Do not require the literal phrase "job alert".

### Layer 3 — Body structure

Recognize repeated job-shaped blocks containing combinations of:

- title
- company
- location
- salary
- employment type
- posting/application link

### Layer 4 — URL evidence

Recognize job URLs and associate them with the correct listing.

Existing correct URL extraction code should be reused rather than duplicated.

Potential domains/patterns already encountered include:

- linkedin.com/jobs
- indeed.com
- greenhouse.io
- lever.co
- myworkdayjobs.com
- icims.com
- smartrecruiters.com
- taleo.net
- jobvite.com
- ashbyhq.com
- bamboohr.com
- ziprecruiter.com
- workable.com
- breezy.hr
- recruiting.com

This is an evolving provider list, not a reason to hard-code the whole product around today's providers.

---

## 11. Extraction Quality Rules

The extractor should:

- preserve listing order where useful
- de-duplicate URLs
- ignore unsubscribe/preferences/privacy links
- ignore generic navigation links
- not treat "View more jobs" as a job
- handle wrapped titles
- handle wrapped company/location lines
- tolerate missing salary
- tolerate missing employment type
- tolerate missing URL
- tolerate reasonable email-format variation
- return zero for ordinary application emails

The core parser should be predictable and testable.

Do not make an LLM the primary deterministic parser unless the user explicitly approves that architecture.

---

## 12. Existing Code Worth Inspecting/Reusing

When these areas exist, inspect them before replacing anything:

```text
_app/mail_app_store.py
_app/api.py
_app/overrides_store.py
_app/frontend/index.html
tests/test_discoveries.py
tests/test_overrides_store.py
```

Potentially reusable pieces include:

- Mail.app integration
- message IDs
- sender/domain classification
- posting URL extraction
- multi-URL extraction
- discovery persistence
- existing application matching
- sender overrides
- test fixtures

Reuse good implementation; do not preserve an abstraction merely because it already exists.

---

## 13. Separation of Responsibilities

### Job Postings

Means:

> Here are jobs I could apply to.

These are individual job records.

### Possible New Applications

Means:

> Here is an email that may relate to an application I submitted or should add to my tracker.

These are email/discovery records.

Do not force one into the other.

---

## 14. API Direction

The frontend should consume a first-class job-posting endpoint/model.

A likely endpoint is:

```text
GET /api/job-postings
```

Potential operations include:

```text
POST /api/job-postings/{id}/dismiss
```

Use the actual project's conventions.

Do not break the existing discovery API contract without a deliberate reason.

---

## 15. Frontend Direction

The Email Sync page should be backed by actual `job_postings` records.

Do not use:

```javascript
discoveries.filter(d => d.kind === "posting")
```

as the canonical Job Postings count.

Each digest listing should become its own UI item.

Example:

```text
Software Engineer
Haystack
Colorado, United States · Remote
LinkedIn
Posted 3d ago

[ Open job ↗ ]
```

The user should not have to open an email preview just to reveal the posting link.

---

## 16. Historical Scanning

Do not imply that a small inbox scan means "all jobs".

If historical scanning is implemented, make its scope explicit:

- recent
- 7 days
- 30 days
- 90 days
- all available

Avoid arbitrary message limits being mistaken for complete discovery.

Truthful guarantee:

> all recognizable jobs contained in the emails that were actually scanned

Not:

> all jobs currently available on LinkedIn/Handshake/Indeed.

---

## 17. Testing Requirements

Minimum acceptance suite:

### LinkedIn

Real fixture:

```text
expected = 6
```

Verify titles/companies and direct URLs when the fixture contains them.

### Handshake

Real fixture:

```text
expected >= 5
```

Verify titles/companies and ensure "View more jobs" is not a job.

### Ordinary application

For an email such as:

```text
Thank you for applying...
We received your application...
```

Expected:

```text
[]
```

### Deduplication

Test:

- same email twice
- same URL twice
- multiple jobs without URLs
- multiple jobs in one email

### API

Test:

- creation
- listing
- safe repeated sync
- compatibility with existing discovery endpoints

### Regression

Run the full test suite on the real Mac whenever possible.

---

## 18. Verification Order

Use this sequence:

```text
1. Static inspection
2. Unit tests
3. API tests
4. Full pytest suite
5. Start application locally
6. Real Mail.app sync
7. Safari validation
8. User review
9. Only then commit
10. Only then push if explicitly approved
```

Never call the feature complete based only on unit tests.

---

## 19. macOS / Safari Requirement

This project uses macOS and Mail.app.

Sandbox/Linux validation is useful but does not replace real validation.

Before final completion:

- launch the application on the user's Mac
- use real Mail.app
- perform a real Email Sync
- inspect Job Postings in Safari
- verify direct links
- verify the count represents actual jobs
- verify application discovery still works
- check for UI regressions

---

## 20. Git Safety

The user's workflow:

- **No commit until explicitly approved.**
- **No push until explicitly approved.**
- Use explicit paths with `git add`.
- Never use:

```bash
git add -A
```

Before a proposed commit, report:

```bash
git status
git diff --stat
git diff --check
```

and state exactly what will be committed.

---

## 21. Living Handoff Protocol

This file is a **living document** and the primary continuity record between Claude sessions.

However, this file alone is **not** the physical transfer mechanism.

**The updated repository ZIP is the physical transfer mechanism.**

### Checkpoint triggers

Create a handoff checkpoint when **either** condition is met:

1. **A meaningful task or phase is completed.**
2. **Context usage approaches 80%.**

Treat 80% as the safety threshold, not as a target to push past. Do not wait until 90–99% context usage.

A completed task is a natural checkpoint; 80% is the mandatory safety checkpoint.

### Meaningful-task checkpoint

When a meaningful task or phase is complete:

1. Stop before starting another substantial feature.
2. Update this file with the exact completed work.
3. Record tests and validation evidence.
4. Record known issues and the exact next action.
5. Create an updated repository ZIP.
6. Verify the ZIP contents.
7. **Actually attach/return the ZIP to the user.**
8. Only continue feature work if there is ample context remaining and doing so is clearly safer than handing off.

### 80% context checkpoint

When context usage approaches **80%**:

1. Stop feature work immediately.
2. Do not start another task.
3. Update this file.
4. Save all current changes.
5. Run only the checks needed to record the current state safely.
6. Create an updated repository ZIP.
7. Verify the ZIP contents.
8. **Actually attach/return the ZIP to the user.**
9. End the session.

The goal is to leave enough context to complete the handoff reliably.

### What counts as a successful handoff

This is **not** sufficient:

```text
ZIPNAME=some-file.zip
```

That only proves a file was named or created inside the temporary workspace.

A successful handoff requires that the user can actually access/download the resulting ZIP from Claude's response.

If the ZIP cannot be attached or returned, say so explicitly. Do not claim the handoff is complete.

### Required status in this document

At each checkpoint record:

- exact date/time
- checkpoint trigger: `TASK COMPLETE` or `~80% CONTEXT`
- phase/task completed
- changed files
- tests and exact results
- manual validation status
- known issues
- exact next action
- ZIP filename
- whether that ZIP was actually returned to the user

## 22. Checkpoint Template

Use this at each major checkpoint:

```markdown
## Checkpoint — YYYY-MM-DD HH:MM

### Repository
- Branch:
- HEAD:
- Working tree:

### Completed
- ...

### Changed Files
- ...

### Tests
- Command:
- Result:

### Manual Validation
- Mail.app:
- Safari:
- Result:

### Remaining
- ...

### Known Issues
- ...

### Next Action
- ...
```

---

## 23. New-Session Procedure

For a brand-new Claude session:

### Step 1

Read this file.

### Step 2

Run:

```bash
git status --short
git branch --show-current
git log -1 --oneline
```

### Step 3

Inspect the repository tree and relevant source.

### Step 4

Find the Email Sync implementation.

### Step 5

Find:

- discovery schema
- discovery APIs
- Mail.app search
- sender classification
- URL extraction
- Job Postings frontend
- existing tests

### Step 6

Determine whether a previous job-postings implementation exists.

### Step 7

If it exists:

- verify it against the actual code
- run tests
- inspect diffs
- continue from the real state

### Step 8

If it does not exist:

- perform the audit
- make a concise implementation plan
- build incrementally

Do not restart work that is already complete.

---

## 24. Things Claude Must Not Do

Do not:

- merely expand the old posting regex
- merely add sender domains
- use `discovered_matches.kind = posting` as the permanent job model
- count emails as jobs
- require preview before extracting links
- require "job alert" in every subject
- treat "View more jobs" as a job
- discard unrelated user changes
- commit without approval
- claim Safari validation without doing it
- claim the inbox contains every job available on the web
- fabricate tests or validation results

Do:

- represent individual jobs
- preserve source-email provenance
- extract during sync
- deduplicate deterministically
- test against real email fixtures
- keep application discovery separate
- validate on the real Mac/Safari environment

---

## 25. Definition of Done

The redesign is complete only when:

- [ ] Intended job-alert sources are detected.
- [ ] One digest can produce multiple individual job records.
- [ ] LinkedIn real fixture produces 6 jobs.
- [ ] Handshake real fixture produces at least 5 visible jobs.
- [ ] Ordinary application mail produces zero job postings.
- [ ] Individual jobs have direct links whenever the email provides them.
- [ ] Navigation/continuation links are not falsely represented as jobs.
- [ ] Repeated sync does not duplicate jobs.
- [ ] Job Postings count represents actual job records.
- [ ] Job Postings UI displays individual jobs.
- [ ] Existing Possible New Applications behavior still works.
- [ ] Full test suite passes on the real Mac.
- [ ] Real Mail.app sync has been tested.
- [ ] Safari UI has been tested.
- [ ] User has reviewed the result.
- [ ] Only after approval: explicit git add, commit, and optional push.

---

## 26. Final Operating Principle

Keep returning to this model:

```text
EMAIL
  ↓
CLASSIFY
  ├── application/recruiting mail
  │       ↓
  │   application discovery
  │
  └── job-alert/listing mail
          ↓
      EXTRACT
          ↓
      N JOBS
          ↓
      DEDUPE
          ↓
      JOB POSTINGS
          ↓
      USER CAN APPLY
```

The goal is not "better email classification."

The goal is:

> **Turn job opportunities arriving by email into a useful, deduplicated list of actual jobs with links the user can apply through.**

This document should remain the shared source of truth between Claude sessions, the user, and future development work.


## 27. Current Session Transfer State

This section describes the **latest physical handoff artifact**, not merely a ZIP created internally.

### Latest Returned ZIP
- Filename: `jobtracker-hub-handoff-checkpoint-20260902-2.zip`
- Returned/attached to user: **YES only after the user can actually access it**
- Checkpoint trigger: **TASK COMPLETE** (first real implementation increment)
- Checkpoint represented: deterministic job-posting extractor + storage + API, backend-only (see Checkpoint below)
- Phase: Job Postings redesign — backend extraction/storage/API implemented; frontend and real-Mac validation still pending

### ZIP Rule
Never record a ZIP here merely because Claude created it internally.

Only record `Returned/attached to user: YES` after the user can actually access the file.

If an updated ZIP has not successfully reached the user, the previous ZIP actually received by the user remains the authoritative external handoff artifact.

### Next Session Rule
The next Claude session must begin by reading `CLAUDE_HANDOFF.md` from the latest ZIP actually received by the user, then inspect the repository snapshot before making changes.

---

## Checkpoint — 2026-09-02 (this session)

### Repository
- Branch: unknown (sandbox ZIP workspace only — see section 0A; not the user's real Mac checkout)
- HEAD: unknown
- Working tree: not a git repo in this workspace; see Changed Files below

### Completed
- New deterministic extractor `_app/posting_extract.py`: turns a job-alert
  digest email body into a list of individual job dicts
  (title/company/location/salary/employment_type/source). Layer 1 source
  recognition (`detect_provider`) covers linkedin/handshake/indeed/
  ziprecruiter by sender domain; only **linkedin** and **handshake** have
  real Layer-3 body-structure parsers so far (the two sources with real
  fixture emails — section 6). Indeed/ZipRecruiter/others are recognized
  but `extract_postings()` correctly returns `[]` for them until a parser
  is added — this is intentional, not a bug, per section 10's "evolving
  provider list" note.
- New `job_postings` table + CRUD in `_app/overrides_store.py`
  (`add_job_posting`, `list_job_postings`, `get_job_posting`,
  `set_job_posting_status`, `count_job_postings`), matching the section 8
  data model, deduped via `dedupe_key` (section 9: URL-based identity when
  a posting URL is known, else account+message+title+company).
- Wired into `_app/api.py`: new helper `_extract_and_store_job_postings()`
  fetches the message body (`mailapp.get_message_preview`) and persists
  each extracted job the moment a message is classified `kind="posting"`
  in **both** `sync_account()` and `discover_new_applications()` — i.e.
  extraction now happens during sync (section 7.5), not lazily on
  preview. New endpoints: `GET /api/job-postings` (canonical job list —
  this, not any `discoveries.filter(kind==='posting')` query, is what the
  count should come from — section 15) and
  `POST /api/job-postings/{id}/dismiss`.
- New tests: `tests/test_posting_extract.py` (runs the extractor against
  the REAL `linkedin_job_alert_haystack.pdf` and
  `handshake_weekly_jobs_roundup.pdf` fixtures — not invented text) and
  `tests/test_job_postings_store.py` (storage/dedupe unit tests).

### Changed Files
- New: `_app/posting_extract.py`
- New: `tests/test_posting_extract.py`
- New: `tests/test_job_postings_store.py`
- Modified: `_app/overrides_store.py` (job_postings table + CRUD)
- Modified: `_app/api.py` (import, `_extract_and_store_job_postings`,
  two call sites in `sync_account`/`discover_new_applications`, two new
  `/api/job-postings` routes)
- Not modified this session: `_app/frontend/index.html`,
  `_app/mail_app_store.py`, `_app/email_pdf.py`, `_app/classify.py`,
  `tests/test_overrides_store.py`, `_app/requirements.txt` — all
  pre-existing uncommitted work from section 0 is untouched/preserved.

### Tests
- Command: could **not** run the real pytest suite in this sandbox —
  no network access to install `pytest`/`fastapi` (both absent from the
  sandbox image; see section 0A, this is a temporary Claude workspace,
  not the user's real Mac environment).
- What WAS actually run: `python3 -m py_compile` on all three changed/new
  `_app/*.py` files (passed — no syntax errors). The extractor itself was
  exercised directly (no pytest needed, stdlib + `pypdf` only) against
  the real fixture PDFs by running the exact logic in
  `tests/test_posting_extract.py` as a plain script:
  - LinkedIn fixture → **6** postings, titles/companies match section 6
    exactly, salary captured on the 2 listings that have one, none
    fabricated on the 4 that don't.
  - Handshake fixture → **5** postings, all 5 expected titles present,
    "View more jobs" correctly excluded.
  - Ordinary T-Mobile application-confirmation text → **0** postings.
  - Unknown sender → **0** postings.
  - Dedupe-key tests (same URL / different account / linkless
    title+company fallback / two linkless jobs in one email both
    surviving) — all logic paths manually verified correct.
  The `overrides_store.job_postings` CRUD was similarly exercised
  directly against a real temp SQLite file (insert, dedupe no-op on
  repeat, 6-jobs-one-message, dismiss, count, get-by-id) — all passed.
- **This is real evidence the extraction/storage logic is correct, but
  it is NOT the same as running the actual `pytest` files.** The next
  session (or the user, on a machine with `pip install pytest fastapi`
  available) should run
  `pytest tests/test_posting_extract.py tests/test_job_postings_store.py`
  for real and confirm they pass as committed, then the full suite.

### Manual Validation
- Mail.app: **not done** — impossible in this sandbox (no macOS, no
  Mail.app, no network). `_extract_and_store_job_postings()` and its two
  call sites are unexercised against a real Mail.app sync.
- Safari: **not done** — the frontend was not changed this session, so
  there is nothing new to validate there yet regardless.
- Result: backend logic verified directly; end-to-end sync path NOT
  verified. This was always going to require the user's real Mac per
  section 19 — that requirement has not changed, only gotten closer.

### Remaining
- **Frontend**: `_app/frontend/index.html`'s Job Postings view still
  needs to be pointed at `GET /api/job-postings` instead of any
  `discoveries.filter(d => d.kind === 'posting')` logic, and each job
  needs its own card (title/company/location/salary/type/source/age +
  "Open job ↗") per section 4/15. Not started this session.
- Indeed/ZipRecruiter/Greenhouse/etc. body parsers — not implemented
  (see Completed above); only linkedin/handshake have real parsers.
- Full pytest suite has not actually been run (see Tests above).
- Real Mail.app sync + Safari validation (section 19) — not done, needs
  the user's Mac.
- No git status/diff has been inspected against the user's real
  checkout this session (section 0A: this sandbox is a ZIP workspace,
  not the user's git repo) — the next session (or the user) still needs
  to reconcile this against `git status`/`git diff` on the real machine
  before anything is committed.

### Known Issues
- Handshake's non-URL company-field heuristic is imperfect for one edge
  case in the real fixture: the line "Eagle County - Colorado" (a
  Handshake "recommended because of" tag, not a company name) gets
  misread as the company for "Desktop Support Technician I, II or III"
  since the parser only has "2 lines before the meta line = company +
  title" to go on. The **title** extraction for that job is correct;
  only its `company` field is wrong. Acceptable per section 11's
  "tolerate reasonable email-format variation," but worth a smarter
  heuristic (e.g. detecting location-shaped strings) if it turns out to
  recur across other real Handshake emails.
- `get_message_preview()` truncates at 4000 chars by default — a very
  long digest (more than the two fixtures) could lose trailing jobs.
  Not hit by either real fixture (both well under 4000 chars extracted),
  but worth raising `max_chars` for this call site specifically if a
  longer real digest surfaces later.
- URL-to-job association in `_extract_and_store_job_postings()` is
  positional-only (job *i* gets URL *i*, if one exists) — correct for
  both real fixtures' URL-free bodies (neither fixture's plain-text
  extraction contains real hyperlink URLs at all, so `posting_url` is
  `None` for every job from either fixture right now) but unverified
  against a real digest that DOES contain clickable links, since no such
  fixture exists yet.

### Next Action
1. Get `pytest`/`fastapi` available (network access, or the user's own
   Mac) and actually run
   `pytest tests/test_posting_extract.py tests/test_job_postings_store.py`,
   then the full suite, to convert the manual verification above into
   real recorded pytest results.
2. Update `_app/frontend/index.html`'s Job Postings view per Remaining
   above.
3. Real Mail.app sync + Safari validation (section 19) on the user's Mac.
4. Only after 1–3: report back to the user for review before any commit
   (section 20 — no commit/push without explicit approval).

### ZIP
- Filename: `jobtracker-hub-handoff-checkpoint-20260902-2.zip`
- Returned to user this turn: see the message this ZIP was attached to.

---

## Checkpoint — 2026-09-02 (continuation session)

### Repository
- Branch: unknown (sandbox ZIP workspace only, same as previous checkpoint
  -- this is still not the user's real Mac checkout)
- HEAD: unknown
- Working tree: not a git repo in this workspace

### Completed
- **Fixed a real bug from the previous session's diff**, found by
  actually running pytest for the first time (see Tests below): the
  `@app.post("/api/accounts/{account_id}/sync")` decorator had ended up
  attached to `_extract_and_store_job_postings` (the new helper) instead
  of to `sync_account()` immediately below it -- an insertion-order
  mistake, not a logic bug. FastAPI was therefore routing
  `POST /api/accounts/{id}/sync` to a plain helper function whose
  untyped params (`ov_conn`, `account_name`, `message_id`, ...) aren't
  `Depends(...)`, so it demanded them as required *query* parameters and
  returned `422 Unprocessable Entity` on every call. This is exactly the
  15 failures + 3 errors visible in the user's own terminal paste at the
  top of this file, from *before* any job-postings work existed this
  session or last -- i.e. this bug, once introduced, was real and would
  have broken `/sync` for every caller, not just the new feature. Fixed
  by moving the decorator to `sync_account`.
- **Closed a gap in `mark_discovery_as_posting()`** (`POST
  /api/discoveries/{id}/mark-posting`): the automatic paths
  (`sync_account`/`discover_new_applications`) already ran
  `_extract_and_store_job_postings()` when a message was classified
  `kind="posting"`, but the *manual* "mark as posting" button (for a
  digest the classifier missed) only relabeled the discovery row and
  never extracted its individual jobs. Fixed by calling the same helper
  from this endpoint too, with the same "extraction failure never blocks
  the relabel" swallow-and-continue behavior as the other two call
  sites. Two new tests cover this: one using the real LinkedIn fixture
  body (asserts all 6 jobs land in `/api/job-postings`), one confirming
  a `MailAppError` during the body fetch still returns 200 with the
  relabel applied and zero jobs extracted.
- **Frontend (`_app/frontend/index.html`) Job Postings view**, the
  "Remaining" item from the previous checkpoint:
  - New `JobPostingCard` component: one card per individually-extracted
    job (title, company + location, employment type, salary, source,
    relative age, "Open job ↗" linking to `posting_url` when known,
    Dismiss). Replaces the previous approach of rendering one
    `DiscoveryCard` per raw digest *email* in the Job Postings column.
  - `DiscoveriesBoard`'s Job Postings column now reads from a new
    `jobPostings` prop (fetched via `GET /api/job-postings`) instead of
    `discoveries.filter(d => d.kind === "posting")` -- this is the
    section 15 requirement the previous checkpoint flagged as not yet
    done. The column header count (`Job Postings · N`) is now the
    canonical count from that same list, not a discoveries-derived one.
  - `DiscoveryCard` (Needs-Triage-only now) had its dead `isPosting`
    branches removed since the Job Postings column no longer renders it
    at all -- confirmed via `grep -n "isPosting"` returning nothing and
    there being exactly one remaining `<DiscoveryCard>` call site (the
    Needs Triage column).
  - New state/handlers in the discoveries page component:
    `jobPostings`, `loadJobPostings()`, `dismissingJobId`,
    `dismissJobPosting()` (calls `POST /api/job-postings/{id}/dismiss`).
    Wired into the mount `useEffect` alongside the existing
    `loadDiscoveries()`/`loadAccounts()`, and into `scan()` (so "Check
    inbox now" refreshes both lists) and `markPosting()` (so manually
    marking a discovery as a posting also picks up its newly-extracted
    jobs without a page reload).
  - **Fixed a second pre-existing frontend bug while touching this
    code**: `markPosting()` was doing `setDiscoveries(result.discoveries)`,
    but `POST /api/discoveries/{id}/mark-posting` returns the single
    updated discovery object, not a `{discoveries: [...]}` envelope
    (confirmed against both the endpoint's actual `return updated`
    and `tests/test_discoveries.py::test_mark_posting_relabels_a_pending_discovery`,
    which asserts `resp.json()["kind"]`, not `resp.json()["discoveries"]`).
    This would have set the discoveries list state to `undefined` on
    every "Mark as posting" click, which -- given `DiscoveriesBoard`
    calls `discoveries.forEach(...)` unconditionally -- would have
    thrown and broken the board. Fixed to relabel the one row locally
    for the instant visual jump, then reload both lists for real.
  - The render gate above the board (`discoveries && discoveries.length
    > 0 && boardView === "board"`) was widened to also show the board
    when `jobPostings` is non-empty even if `discoveries` is currently
    empty, since dismissing/attaching every pending discovery no longer
    empties the Job Postings column (job_postings rows are a separate
    table and outlive their originating discovery either way).
  - Filter placeholder text updated from "Filter by subject or
    company…" to "Filter by title or company…" to match what it now
    actually filters on (job title/company, not email subject).

### Changed Files (this session, on top of the previous checkpoint's diff)
- Modified: `_app/api.py` (decorator fix; `mark_discovery_as_posting`
  now extracts jobs too)
- Modified: `_app/frontend/index.html` (Job Postings board rework
  described above)
- Modified: `tests/test_discoveries.py` (two new tests, plus a
  module-level `_linkedin_fixture_body()` helper + `Path`/`FIXTURE_DIR`
  imports to reuse the real fixture PDF from `test_posting_extract.py`)

### Tests
- **Actually ran pytest for real this time** -- `pip install -r
  _app/requirements.txt -r requirements-dev.txt` succeeded (network
  access to PyPI was available in this sandbox session, unlike last
  time), so the "next action #1" from the previous checkpoint is done:
  - Before the decorator fix: reproduced the user's exact failure list
    (15 failed, 3 errors, 284 passed) -- confirms the bug was real and
    not a sandbox artifact.
  - After the decorator fix: **`pytest -q` → 304 passed, 0 failed, 0
    errors.** Full suite, including all 22 posting-extraction/storage
    tests from the previous session and the 2 new mark-posting-extracts
    tests from this one.
  - `tests/test_discoveries.py` alone: 23 passed.
- Frontend: no JS test runner in this repo, so verified the edited
  `<script type="text/babel">` block parses by extracting it and
  running it through `@babel/core`'s `transformSync` with
  `@babel/preset-react` (installed via `npm install --no-save`, then
  removed afterward along with `node_modules`/`package.json` so nothing
  npm-related leaks into the zip) -- came back clean (no syntax errors).
  This confirms the JSX is well-formed; it is **not** the same as
  actually loading the page in a browser and clicking through the
  board, which still hasn't happened (see Manual Validation).

### Manual Validation
- Still not done, same as every previous checkpoint: no macOS/Mail.app/
  Safari available in this sandbox. The Job Postings board rework above
  has only been syntax-checked and reasoned through against the API
  contracts (endpoint shapes, existing test assertions) -- it has never
  actually been rendered in a browser. In particular, worth specifically
  checking on the user's Mac:
  - That dismissing a job posting card actually removes just that card
    (optimistic local filter in `dismissJobPosting`) and doesn't
    desync from a subsequent `loadDiscoveries()`/`loadJobPostings()`.
  - That dragging a Needs-Triage card onto the Job Postings column still
    feels right now that the column it lands in is showing unrelated
    job cards rather than a card for the thing just dragged (the
    dropped discovery's own card disappears from Needs Triage and its
    *extracted jobs*, not itself, appear in Job Postings after the
    reload -- this is a real UX shift from before, worth the user's own
    eyes on it, not just my reasoning about it).
  - The "Open job ↗" link, since `posting_url` is positional-only per
    the previous checkpoint's Known Issues (i.e. still unverified
    against a real digest containing actual clickable hyperlink URLs).

### Remaining
- Real Mail.app sync + Safari validation (section 19) -- still needs
  the user's Mac, unchanged from every previous checkpoint.
- Indeed/ZipRecruiter/Greenhouse/etc. body parsers -- still not
  implemented (only linkedin/handshake have real parsers).
- The Handshake company-field heuristic edge case from the previous
  checkpoint's Known Issues is unchanged/unaddressed.
- No git status/diff has been inspected against the user's real
  checkout -- still needs reconciling on the real machine before commit.
- Frontend has now been touched but only syntax-checked, never actually
  run in a browser -- see Manual Validation above.

### Next Action
1. Real Mail.app sync + Safari validation on the user's Mac -- now the
   single biggest remaining gap, since both backend and frontend are
   code-complete and test-passing/syntax-clean respectively.
2. On the user's Mac: `git status`/`git diff` against the real
   checkout to reconcile this sandbox's changes before anything is
   committed.
3. Only after 1–2, and with explicit user approval: commit/push
   (section 20 still applies unchanged).
4. Optional/lower-priority: Indeed/ZipRecruiter parsers, the Handshake
   company-field heuristic.

### ZIP
- Filename: see this turn's message.
- Contains: everything from the previous checkpoint's zip, plus the
  `_app/api.py` and `_app/frontend/index.html` edits and the
  `tests/test_discoveries.py` additions described above.

---

## Checkpoint — 2026-09-02 (real-machine validation + one fix)

### Repository
- This entry covers events on the user's **actual Mac**, not this
  sandbox -- the first time in this doc's history that's been true for
  the Tests/Manual Validation sections below, rather than the usual
  "still needs the user's Mac" caveat.

### Completed
- **The user ran the previous checkpoint's zip for real**, on their own
  machine, against real data:
  - `pytest -q` from repo root: **304 passed**, matching this sandbox's
    result exactly. Re-ran it a second time back-to-back, same result.
    Also ran the *old* `_app/requirements.txt`-only venv path (`cd _app
    && pip install -r requirements.txt && uvicorn api:app --reload`)
    and it started and served real traffic without error.
  - Started the real server and drove it through Safari against a real
    linked workspace (`Testing_Email_Sync_DB`, 742 documents / 122
    items / 77 companies) with 5 real connected Mail.app accounts.
  - Clicked **"Check inbox now"**: `POST /api/accounts/{id}/discover`
    fired for all 5 accounts, `GET /api/job-postings` and `GET
    /api/discoveries` both returned 200, and the Job Postings column
    went from **0 → 12 real job cards** (Needs Triage dropped from 56
    -> 53 accordingly) -- this is the first real-world confirmation
    that `_extract_and_store_job_postings()` actually fires end-to-end
    against real Mail.app data, not just the two fixture PDFs. Card
    contents (title, company, location, source, "posted 5mo ago"
    relative age, Dismiss button) all rendered correctly and matched
    what `JobPostingCard` was written to produce.
  - This is real confirmation of the decorator-bug fix from the
    previous checkpoint too, outside the sandbox: `/sync`,
    `/discover`, `/backfill-email-pdfs`, and `/attach` all returned 200
    against real accounts and real mail, with none of the `422
    ov_conn` errors that bug caused.
- **Found (from the user's screenshot) and fixed one real cosmetic
  bug** in the new `JobPostingCard`: the source tag rendered
  "**Linkedin**" instead of "**LinkedIn**". Cause: `posting_extract.py`
  correctly stores the lowercase provider id (`"linkedin"`,
  `"handshake"`, etc. -- see `_SOURCE_DOMAINS`/`_SUPPORTED_PROVIDERS`),
  since that's what dedupe/matching logic keys off of, but the card was
  displaying it via CSS `text-transform: capitalize`, which only
  capitalizes the first letter and can't know LinkedIn's or
  ZipRecruiter's actual internal capitalization. Fixed with a small
  `JOB_SOURCE_DISPLAY_NAMES` lookup (`linkedin` -> "LinkedIn",
  `handshake` -> "Handshake", `indeed` -> "Indeed", `ziprecruiter` ->
  "ZipRecruiter") used only for display; the stored/compared value is
  untouched. Re-verified the edited script block still parses cleanly
  via the same Babel `transformSync` check as before.
- Re-ran `pytest -q` in this sandbox after the fix: still **304
  passed** (this was a pure frontend display change, so no backend
  test was expected to move).

### Changed Files (this session)
- Modified: `_app/frontend/index.html` (`JOB_SOURCE_DISPLAY_NAMES` +
  `jobSourceDisplayName()` helper; `JobPostingCard`'s source `<span>`
  now calls it instead of relying on CSS `text-transform`)

### Tests
- Sandbox: `pytest -q` -> 304 passed (unchanged from before this
  session's one fix, as expected for a display-only change).
- **User's real Mac, this session (see Completed above): 304 passed,
  twice, plus a live end-to-end run against real Mail.app data that
  produced 12 real job-posting cards from real inboxes.** This is the
  strongest validation this feature has had yet -- the first time
  actual extraction-from-real-mail has been confirmed working, as
  opposed to the two fixture PDFs or reasoning about the code.

### Manual Validation
- **Safari, real Mac, done this session**: Email Sync page loads, the
  3-column board renders, all 5 connected accounts show with sync
  status, "Check inbox now" works, Job Postings column populated with
  real cards after a real sync (see Completed). This resolves the
  single biggest open item from the previous checkpoint's Manual
  Validation section.
- **Still not exercised / not yet seen in a screenshot**:
  - Clicking **Dismiss** on a job posting card (does it disappear
    cleanly via the optimistic local-state filter in
    `dismissJobPosting`, and does it stay gone after a reload).
  - Clicking **"Mark as posting"** on a Needs-Triage card and watching
    it produce new Job Postings cards via the newly-added extraction
    call in `mark_discovery_as_posting()` (the 12 cards seen so far
    came from the automatic sync/discover path, not this manual path).
  - The **"Open job ↗"** link -- none of the 12 cards in the
    screenshot showed one, consistent with the previous checkpoint's
    note that `posting_url` is currently `None` for both real fixture
    bodies; still unconfirmed whether any real digest in this user's
    actual mailboxes contains a body with real clickable hyperlink
    URLs that `mailapp.extract_posting_urls()` would find.
  - Dragging a Needs-Triage card onto the Job Postings column (vs.
    using the "Mark as posting" button) -- not shown in either
    screenshot so far.

### Remaining
- Everything from the previous checkpoint's Remaining section still
  applies (Indeed/ZipRecruiter/Greenhouse parsers, Handshake
  company-field heuristic, git status/diff reconciliation, commit
  approval) -- none of that changed this session.
- The four bullet points under Manual Validation above are the
  concrete next things to click through, now that the big end-to-end
  path is confirmed working.

### Next Action
1. Click through the four not-yet-exercised interactions above
   (Dismiss, manual Mark-as-posting extraction, Open job link, drag-
   to-column) and report back what happens -- particularly Dismiss,
   since that's the one with the most custom state logic
   (`dismissingJobId` + optimistic local filter) that's never been
   clicked once yet.
2. `git status`/`git diff` on the real checkout to see what's
   uncommitted, whenever convenient.
3. Only after 1-2, with explicit approval: commit/push.


---

## Checkpoint — 2026-09-03 (icon audit round two, implemented — shared with `main` branch)

### Repository
This entry documents work also recorded in full in the `main` branch's
`HANDOFF.md` §25 — that's the authoritative write-up of the mapping,
methodology, and verification. This entry covers only what's specific
to this branch.

### Completed
- Same `ICON_PATHS` additions (26 new SVG entries) and the same ~60
  shared emoji→`<Icon/>` call-site conversions as `main`, applied to
  this branch's `_app/frontend/index.html` (same script, same mapping
  — the files share the large majority of this code verbatim).
- **7 additional emailSync-only conversions**, matching
  `icon-audit-mockup-v2.html`'s dedicated "emailSync branch only"
  section:
  - `AccountMatchIcon`'s envelope badge (account-match indicator)
  - "Open Email Sync" button (settings/diagnostics area)
  - `JobPostingCard`'s "Open job ↗" link
  - "Sync all" button (multi-account sync)
  - "Check inbox now" button
  - Discoveries board's "Nothing pending review" `EmptyState`
  - The per-discovery envelope glyph in the doc-card list row
  All use the `mail` / `mailbox` / `refresh` / `open_ext` keys from
  the shared `ICON_PATHS` additions — no new icon paths were needed
  specifically for this branch.

### Changed Files
- Modified: `_app/frontend/index.html` only. No backend files
  (`_app/api.py`, `_app/mailapp.py`, `_app/posting_extract.py`, etc.)
  touched.

### Tests
- `pytest -q` → **308 passed, 0 failed** — this branch's normal full
  count (per the checkpoint above this one), unchanged by this
  frontend-only edit.
- Real Babel (`@babel/preset-react`) `transformSync` on the full
  `<script type="text/babel">` block: compiles cleanly, no syntax
  errors. Brace/paren balance: braces net-zero; parens show the same
  net +1 imbalance already present before this session's change (a
  pre-existing, previously-noted characteristic of this file, not
  something introduced here — confirmed by running the same balance
  check before and after this session's edits).
- Grep sweep for leftover emoji escape sequences: only the
  deliberately-unconverted ones remain (labels-object default
  section labels, the paperclip document-dropzone icon, the
  search-box placeholder, and plain typography) — same exceptions as
  `main`, see its §25.3 for the reasoning on each.

### Manual Validation
- **Not done.** Same as `main`: this has not been opened in a real
  browser or the packaged app by anyone since this change. See
  `main`'s HANDOFF.md §25.5 for the checklist — it applies here too,
  plus the 7 emailSync-only spots listed above (Account badges, Open
  Email Sync, Open job link, Sync all, Check inbox now, Discoveries
  empty state, discovery-row envelope) as additional things worth a
  look once the app is actually running.

### Remaining
- Same open item as `main`: the search-box placeholder still carries
  its old emoji character (an HTML `placeholder` attribute can't hold
  an SVG/JSX icon) — giving it a proper leading-icon treatment needs a
  small `ClearableInput` structural change, not a one-line swap.
- Everything else previously listed as Remaining in this file's prior
  checkpoints (Indeed/ZipRecruiter/Greenhouse parsers, the Handshake
  company-field heuristic, git status/diff reconciliation on the real
  machine, commit approval) is unchanged by this session.

### Next Action
1. Open the app (Safari and/or the packaged build) and spot-check the
   icon groups listed in `main`'s HANDOFF.md §25.5, plus this branch's
   7 emailSync-only spots, in both Dark and Light theme.
2. `git status`/`git diff` on the real checkout to reconcile before
   anything is committed.
3. Only after 1–2, with explicit approval: commit/push (unchanged
   from every prior checkpoint in this file).

## Follow-up checkpoint (same session, after approval) — search-box placeholder icon fixed

Mirrors `main`'s HANDOFF.md §25.7: `ClearableInput` now takes an optional
`leadingIcon` prop (renders an absolutely-positioned `<Icon/>` at the left edge
plus a `.has-leading-icon` class that pads the input so text clears it). The
top search bar's `ClearableInput` now passes `leadingIcon="leads"` and its
placeholder no longer starts with the 🔍 emoji character. Applied identically
to this branch's `_app/frontend/index.html` — confirmed the function, its CSS,
and the call-site edit are byte-identical between `main` and `emailsync` after
the change (same as every other shared-code edit this round).

The other three `ClearableInput` sites (command palette, Search Hub's
role/location fields) were left as-is — no emoji there, not part of what was
flagged.

### Verification
- Brace balance on the edited function: 21/21, matched.
- No real Babel `transformSync` this pass — no network access this session to
  install `@babel/standalone` — so this is structural-check-plus-review only,
  not a confirmed parse. Worth a real Babel pass next session.
- Not touched: no backend files, no other frontend regions.

### Remaining
- The search-box-placeholder item from the prior checkpoint's Remaining list
  is done now, not just flagged — remove it from anyone's follow-up list.
- Manual validation (opening the app) is still outstanding, same as every
  prior checkpoint — nothing here changes that.

## Checkpoint — 2026-09-03 (Email Sync audit: Findings 4 & 5, fixed + backfilled)

### Repository
This entry was written up in full as `AUDIT_FINDINGS.md` at the repo root
(new this session) — that's the authoritative write-up of root causes,
fixes, evidence, and known limitations. This checkpoint is the short
continuity summary.

### Completed
- **Finding 4** — Job Postings cards never got an "Open job" link. Root
  cause: `mail_app_store.extract_posting_urls()` rejected any URL containing
  `utm_`, but that's exactly how LinkedIn/most ATSs tag their real per-job
  links — confirmed 6/6 promoted `job_postings` and all 17 posting-kind
  discoveries in the real `overrides.db` had `posting_url = NULL`. Fixed by
  removing `utm_` from the exclusion list and adding a separate, narrower
  `_GENERIC_COLLECTION_URL_HINTS` filter for genuine "view all jobs" digest
  links so the existing count-matching safety net (Finding 3) still works.
- **Finding 5** — "Couldn't load the original email" for some senders but
  not others (e.g. Forbes Business Council never loaded, KPMG did). Root
  cause: `get_message_preview()` only ever searched `INBOX`; discoveries
  can sit unreviewed for months, so by review time a message may have been
  archived/moved elsewhere. Fixed by falling back to scanning every other
  mailbox on the account before giving up.
- **Backfill script** (`scripts/backfill_job_posting_urls.py`, new): the
  Finding 4 fix only helps *new* extractions — the 6 already-promoted
  `job_postings` rows in the real tracker still had `posting_url = NULL`
  stored from before the fix. This script groups affected rows by
  `(account_id, message_id)`, re-fetches each source email (benefiting from
  the Finding 5 fallback), and re-runs the same extraction + count-matched
  pairing logic to backfill just the `posting_url` column. Dry-run by
  default, `--apply` to write, with a timestamped `overrides.db` backup
  first. Run end-to-end against the real tracker this session: all 6 rows
  matched and updated correctly by title; a second `--apply` run correctly
  found nothing left to do (idempotent).
- Both fixes are in `_app/mail_app_store.py` only. No frontend files
  touched this session.

### Tests
- `tests/test_audit_findings.py` (new, 9 tests) covering both findings —
  URL extraction keeps tracked links, still filters generic collection
  links, end-to-end single-job extraction gets a real `posting_url`, the
  mailbox-fallback preview behavior, and the "truly gone from every
  mailbox" negative case.
- Full suite reported passing at 313/313 (304 pre-existing + 9 new) when
  last run inside the working session. **Not independently re-run in this
  handoff pass** — this sandbox has no network/pip access, so `pytest`
  couldn't be installed here to re-verify; take the 313/313 figure as
  session-reported, not re-confirmed by this checkpoint.

### Manual Validation
- Not done from a running app this session — this was a data/code audit
  driven by the real `overrides.db`, not a UI click-through. The backfill
  script's dry-run/apply/re-apply cycle was exercised directly against a
  copy of the real database and confirmed idempotent (see above).
- Still applies from prior checkpoints: opening the packaged/Safari app and
  clicking through Job Postings cards to confirm "Open job ↗" now renders
  for newly-synced postings (and, after running the backfill script with
  `--apply` on the user's real tracker, for the 6 backfilled ones too).

### Remaining
- Everything previously listed as Remaining in this file's prior
  checkpoints (Indeed/ZipRecruiter/Greenhouse parsers, Handshake
  company-field heuristic, git status/diff reconciliation on the real
  machine, commit approval) is unchanged by this session.
- The backfill script has only been run against the user's real tracker
  from within the working session — it has not been re-run from a fresh
  checkout by the user themselves yet.

### Next Action
1. On the real machine: run
   `python3 scripts/backfill_job_posting_urls.py <tracker_root>` (dry run)
   to confirm it reports the same 6 rows, then `--apply` if it wasn't
   already applied for real outside the sandbox.
2. Open the app and confirm "Open job ↗" now renders on Job Postings
   cards, and that a previously-unloadable email preview (e.g. Forbes
   Business Council) now loads.
3. `git status`/`git diff` on the real checkout to reconcile before
   anything is committed — this session's two files
   (`_app/mail_app_store.py`, `tests/test_audit_findings.py`) plus the new
   `AUDIT_FINDINGS.md` and `scripts/backfill_job_posting_urls.py` are all
   new/changed and unreviewed on the real machine.
4. Only after 1–3, with explicit approval: commit/push.

## Follow-up checkpoint — 2026-09-03/04 (real-machine run surfaces a second URL bug)

### What happened
`pytest` re-run for real on the user's Mac: **313/313 passing**, confirming
the prior session's reported figure independently. `scripts/backfill_job_posting_urls.py`
was then run (dry run, no `--apply`) against the real
`.jobtracker/overrides.db` at `/Users/cucii/Documents/GitHub/JobTracker —
Testing EmailSync db`. Result: **0 of 6 rows updated** — all 6 are one
message-id group (a LinkedIn digest), which re-extracted correctly as 6
jobs but **0 links**, tripping the "counts don't match, no link guessed"
safety rule.

### Likely second bug found (not yet confirmed against the real email body)
`_JOB_POSTING_URL_DOMAINS` in `_app/mail_app_store.py` requires the literal
substring `"linkedin.com/jobs"`. Real LinkedIn job-alert email links
commonly route through a tracking path that inserts a segment between the
domain and `/jobs` — e.g. `www.linkedin.com/comm/jobs/view/...` — which
does **not** contain `"linkedin.com/jobs"` as a substring. If that's what
this digest's links look like, every one of them would be silently dropped
by the domain allowlist itself, downstream of (and independent from) the
already-fixed Finding 4 `utm_` bug. The test fixtures never exercised this
because they use simplified synthetic URLs, not real LinkedIn tracking
links.

**Not yet confirmed** — nobody has actually seen the real message body's
raw URLs yet.

### Added this session
`scripts/debug_extract_urls.py` (new, read-only, doesn't touch
`overrides.db`): re-fetches a stuck message's body the same way the
backfill script does, prints every raw URL `extract.extract_urls()` finds
in it, and shows which of `_NON_POSTING_URL_HINTS` /
`_GENERIC_COLLECTION_URL_HINTS` / `_JOB_POSTING_URL_DOMAINS` — or "none at
all" — is why `extract_posting_urls()` did or didn't keep each one. With no
`--message-id`, it walks every message-id group the backfill script would
report as stuck.

Not yet run against the real message — this was written and syntax-checked
in the sandbox only (`ast.parse`, since this sandbox has no Mail.app to
actually execute it against).

### Next Action
1. On the real machine: `python3 scripts/debug_extract_urls.py "/Users/cucii/Documents/GitHub/JobTracker — Testing EmailSync db"`
   and share the output — this shows the real raw URLs and confirms or
   rules out the `linkedin.com/jobs` allowlist theory above.
2. If confirmed: widen `_JOB_POSTING_URL_DOMAINS`'s LinkedIn entry (e.g. to
   just `"linkedin.com"` plus a `_NON_POSTING_URL_HINTS`-style exclusion
   for LinkedIn's own non-job link shapes, so it doesn't over-match feed
   posts/profile links instead) — needs a real link sample to design
   correctly, not just the assumption above.
3. Re-run the backfill dry run, confirm it now proposes updating the 6
   rows, then `--apply`.
4. Everything else from the prior checkpoint's Next Action is unchanged
   and still pending (steps 2–4 there: reopen the app and confirm links
   render, `git status`/`git diff` reconciliation, commit/push approval).

## Follow-up checkpoint — 2026-09-04 (linkedin.com/jobs theory ruled out; real root cause found)

### What happened
`scripts/debug_extract_urls.py` was run for real against the stuck LinkedIn
digest message. Result: **0 raw URLs found at all** (body length 1559
chars). This rules out the `linkedin.com/jobs` vs `linkedin.com/comm/jobs/...`
domain-allowlist theory from the prior checkpoint — there was nothing for
that filter to even see.

### Actual root cause (high confidence, not yet fixed)
`get_message_preview()` in `_app/mail_app_store.py` fetches AppleScript's
`content of msg` — Mail.app's own **plain-text rendering** of the message,
per its own docstring ("Mail.app's own plain-text extraction of the
message -- not raw HTML"). For an HTML email like a LinkedIn job digest,
plain-text rendering keeps visible button labels (e.g. "View job") but
**drops the underlying `<a href="...">` URL entirely** — the URL only
exists in HTML markup that plain-text rendering discards. This is why
`posting_extract.extract_postings()` still correctly found all 6 job
titles/companies (visible text survives) while `extract_posting_urls()`
found nothing (no URLs ever reached it) — two different functions reading
the same lossy body, one needing text that survived, one needing markup
that didn't.

This means **Finding 4's `utm_`-filter fix, while correct as written, was
never actually the full story for real HTML digest emails** — it fixed a
filter that only ever mattered for the synthetic plain-text test fixtures,
which contain literal `http://` strings unlike a real HTML message's
`content of msg` rendering.

### Fix direction (not yet implemented — needs one more confirmation pass)
Need to fetch AppleScript's `source of msg` (raw RFC822 MIME source)
instead of/in addition to `content of msg`, then extract `href="..."`
values from the HTML MIME part after decoding whatever
Content-Transfer-Encoding it uses (quoted-printable and base64 are both
common for HTML email bodies — plain hrefs in `content` were never a safe
assumption to begin with).

### Added this session
`scripts/debug_raw_source.py` (new, read-only): fetches `source of msg`
for one message, does a best-effort MIME-boundary split + quoted-printable/
base64 decode per part, and prints every `href="..."` value found —
without printing the raw source itself (which includes headers/routing
info). Requires `--message-id` or walks every stuck group same as
`debug_extract_urls.py`. **Written and syntax-checked in the sandbox only
— not yet run against the real message**, since that requires macOS/Mail.app.

### Next Action
1. On the real machine:
   `python3 scripts/debug_raw_source.py "/Users/cucii/Documents/GitHub/JobTracker — Testing EmailSync db" --message-id "1406320464.14172961.1773883473504@lor1-app152049.prod.linkedin.com"`
   and share the output (href list + CTE headers seen). This confirms
   whether the hrefs are recoverable this way and what encoding they're
   under, before any production code changes.
2. Once confirmed: add a `get_message_source_links()` (or similar) to
   `_app/mail_app_store.py` that does this properly (real MIME parsing,
   not the debug script's rough boundary-split), wire it into
   `extract_posting_urls()`'s call sites (`api.py`'s
   `_extract_and_store_job_postings`, `discoveries.py`'s preview-persist
   path, and `scripts/backfill_job_posting_urls.py`) as the actual source
   of URLs instead of (or as a fallback alongside) the plain-text `content`
   body extract_posting_urls() currently receives.
3. New regression tests needed for whatever real MIME shape step 1
   reveals — the existing fixtures are plain-text and won't exercise this
   path at all.
4. Only after 1–3: re-run the backfill script, confirm it updates the 6
   rows, `--apply`, reopen the app, confirm "Open job ↗" renders.
5. `git status`/`git diff` reconciliation and commit/push approval — still
   pending from every prior checkpoint, unchanged.

## Follow-up checkpoint — 2026-09-04 (Reset Email Sync built, from a fresh sandbox with no prior session state)

### Context
Picked up in a brand-new chat/sandbox from a pasted transcript of the prior
session plus 5 uploaded zips. The prior session's Reset Email Sync work
(16 commands run, 8 files mid-edit) was **never committed** and is not
present in any uploaded zip — it only ever existed in that session's now-
gone sandbox. The MIME/LinkedIn-URL investigation documented in the two
checkpoints above this one is a **separate, still-unresolved thread** —
this session did not touch it, and did not attempt to verify whether it's
already fixed on the real machine (the live-session transcript pasted into
this chat suggested Findings 4/6 were working, which doesn't obviously
square with "not yet implemented" above — unreconciled, real `git status`/
`git diff` on the actual checkout needed before trusting either account).

### What was built (from scratch, per the original ask: "full reset to
eliminate any db problems so you can just reconnect the email accounts for
fresh start")
- `overrides_store.reset_email_sync(conn) -> dict`: deletes every row from
  `accounts`, `account_matches`, `discovered_matches`, `job_postings`.
  Returns per-table counts deleted. Deliberately does NOT touch
  `job_posting_senders` (user-taught, keyed on sender string not
  account_id) or `thread_identifiers` (keyed on Mail.app's own message
  ids, not this app's account_id scheme — stays meaningful after
  reconnect). Never touches application data (item_overrides,
  status_history, company_aliases, documents, etc).
- `POST /api/accounts/reset-email-sync` in `api.py`: calls the above,
  returns `{ok, deleted: {...counts}}`.
- Frontend (`_app/frontend/index.html`, `EmailHubPage`): a
  "Reset Email Sync" button (`btn danger-outline`, matches existing
  destructive-action styling) next to "+ Connect an account", gated by a
  detailed `window.confirm()` message — same pattern the app already uses
  for tracker deletion (`doDelete` in the workspace popover), not a new
  custom modal. On confirm: POSTs the reset, then re-runs
  `loadAccounts`/`loadDiscoveries`/`loadJobPostings` in parallel and fires
  a toast.

### Tests
New file `tests/test_reset_email_sync.py` (6 tests): full wipe across all
four tables with count assertions, preserved-tables check
(job_posting_senders + thread_identifiers survive), application-data
untouched check, empty-db no-op, and the API route both with seeded data
and on empty state. **Full suite run for real in this sandbox: 333/333
passing** (327 pre-existing + 6 new).

### Manual validation
Not done — this sandbox has no Mail.app/macOS, so nothing here has been
click-tested from a running app. The confirm-dialog copy and button
placement should be eyeballed on the real machine before relying on it.

### Remaining / Next Action
1. On the real machine: `git status`/`git diff` to see how far the real
   checkout has diverged from this zip's `70c8ea7` base — the real
   machine may already have separately fixed or partially built some of
   this, or the MIME/LinkedIn-URL work above.
2. Pull this branch's new commit in, open the app, click "Reset Email
   Sync" for real against a test tracker (not the real `.jobtracker` data)
   and confirm: accounts disappear, discoveries board empties, job
   postings board empties, applications/statuses are untouched, and a
   fresh "+ Connect an account" → sync afterward works cleanly.
3. Decide whether the confirm-dialog wording is enough friction for how
   destructive this is, or whether it's worth a type-to-confirm modal
   instead (the app doesn't use that pattern anywhere else today, which is
   why this session matched the existing `window.confirm` convention
   rather than introducing one).
4. Everything from the two checkpoints above (LinkedIn digest MIME
   extraction root cause, `debug_raw_source.py` not yet run for real) is
   unchanged and still pending — unrelated to this session's work.

## Checkpoint — 2026-09-05 (consolidated): EMAIL_SYNC_REDESIGN_HANDOFF.md complete, all sections click-tested

### Context
This entry replaces the four partial-session entries that previously
sat here ("Follow-up checkpoint — 2026-09-04/05", "§3 frontend
finished, §5 verified", the drop-columns work done in a separate chat
whose transcript was carried into a later session, and "Postings gaps
#1/#2 built") — reconciled into one now that every piece has been
confirmed working on the real machine, per this doc's own note that
the chain shouldn't grow unbounded. The individual per-session
implementation narration (which file/line each change touched, why
each design choice was made) has been trimmed; what follows is the
final state and what's been verified. If a future session needs the
blow-by-blow reasoning, it's in this conversation's history.

`EMAIL_SYNC_REDESIGN_HANDOFF.md` (the doc mapping an interactive
prototype's features onto this app's Needs-Triage/Job-Postings kanban
board) is now **fully implemented**, including two gaps found during a
mockup-vs-real-app comparison that weren't in the original doc.

### What's built (all confirmed via real click-testing on the actual machine)

**§1 — Board drag-and-drop, multi-select, bulk actions:**
Needs-Triage cards support checkboxes + a bulk bar (Mark as postings /
Dismiss selected) in Board view, matching what List view already had.
Group drag: dragging a card that's part of the current multi-select
applies the drop action to the whole selection (`bulkMarkPosting`,
sequential calls like the existing `bulkDismiss`).

Beyond the original doc's scope: the "Applications" drop zone was
split into three literal columns — **Interviews** / **Rejections** /
**Updates** (`STATUS_DROP_COLUMNS`) — each carrying an `intent`
(`interviewing` / `rejected` / `null` for Updates, which is attach-only
since assessment invites don't map to a real pipeline status).
`quickAttach(discoveryId, itemKey, intent)` attaches the email and, if
an intent is set, also fires the existing application-status-override
endpoint — same one the Pipeline board's own drag-and-drop uses.
`resolvingIntent`/`reviewingIntent` thread the intent through both the
quick-pick resolver and the "create new application" path, with the
resolver/review modals showing a "Will also mark the application
Interviewing/Rejected" line when relevant.

**§2 — "Sort all from this sender":** already existed end to end
before this work began (backend + frontend) — confirmed, no changes
needed.

**§3 — Job Postings polish:** star/save toggle (persisted to backend
via `job_postings.saved`, better than the mockup's in-memory-only
version); sort by newest/oldest/company/pay (pay parses the free-text
`salary` field, degrades gracefully on blanks/unparseable values);
grid/list view toggle (persisted to `localStorage` under
`jth_postings_view`). Saved items are a pre-sort partition, not part of
the sort comparator, per the doc's instruction.

**§4 — Undo-on-dismiss toast:** symmetric `POST .../{id}/restore`
endpoints (chosen over client-side-only undo, consistent with this
app's existing `status_history` pattern) back a 5-second toast with an
Undo button; dismissed items grey out immediately and are only really
removed once the undo window expires.

**§5 — Accessibility pass:** real `<button>` elements throughout this
redesign's scope (not the unrelated `MasterList`/pipeline-list
`<div onClick>` patterns elsewhere in the app, which were deliberately
left alone as out of scope); `:focus-visible` outline rules;
`aria-live="polite"` + `role="status"` on the undo toast;
`prefers-reduced-motion` override for kanban/toast transitions.

**Postings gap #1 (found via mockup comparison, not in the original
doc):** `JobPostingCard` now always has a click-through even when
`posting_url` extraction failed — "Search for it ↗" (a Google search
on title+company) instead of a dead end.

**Postings gap #2 (also found via mockup comparison):** an "Apply"
button opens a confirm modal (company/role/status, pre-filled) backed
by a new `POST /api/job-postings/{job_id}/apply` endpoint — reuses the
same `create_application_folder()`/`build()` pipeline as
`accept_discovery()`, saves the original digest email as PDF evidence,
links the account_match, and records `job_postings.applied_item_key`
so the card flips to a green "✓ In pipeline" pill (re-checked live
against the current applications list, so it correctly reverts to
"Apply" if that application is later deleted). Guards against
double-apply with a 409.

### Tests
**343/343 passing on the real machine** (confirmed by the user running
the actual suite, not just this sandbox's syntax/manual checks) — 333
original + 10 added across this arc (`test_discoveries.py`:
restore/save endpoints; `test_job_postings_store.py`: `saved` and
`applied_item_key` column/behavior tests).

### Manually verified on the real machine (not just sandboxed)
- Dragging a Needs-Triage card onto Interviews/Rejections/Updates:
  resolver shows the right "will also mark..." line, picking an
  application both attaches the email and flips its status (or just
  attaches, for Updates) — confirmed via Pipeline afterward.
- A posting with no `posting_url` shows "Search for it ↗" and opens a
  working search.
- "Apply" on a posting creates the application with evidence PDF,
  flips the card to "✓ In pipeline", and the pill correctly jumps to
  that Pipeline item.
- Screenshot-confirmed: Job Postings board renders correctly (star
  icons, sort dropdown, grid/list toggle, Search-for-it/Apply/Dismiss
  buttons all present and laid out as intended).

### Remaining / not part of this arc
- `MasterList`/pipeline-list accessibility pass — explicitly out of
  `EMAIL_SYNC_REDESIGN_HANDOFF.md`'s scope, noted here only in case
  it's wanted as separate future work.
- Everything from checkpoints above this one (LinkedIn digest MIME
  extraction root cause, `debug_raw_source.py` investigation) is
  unchanged and still pending — unrelated to this arc.

### Latest Returned ZIP
- Filename: `jobtracker-hub-checkpoint-20260905d.zip`
- Returned/attached to user: confirmed — user ran the real test suite
  and clicked through all three postings verification steps against
  this build.
