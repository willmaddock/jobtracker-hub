# Django migration: current status

Maintained checkpoint: 2026-10-05. Authoritative branch: `django-migration`;
checkpoint `56214508cd646650863b23628e58c10b80fea010`
(`Implement retained extraction evidence API`), parent
`e96a33c13a3a554a4faa6bdffa6118a30a89316f`. Before this documentation edit,
local HEAD, tracking ref and live remote were verified synchronized at that checkpoint,
ahead/behind 0/0, with a clean working tree and empty index.

Retained Email Source Identity and Content
Foundation is committed at `2f0cd1f`; Gmail Mailbox Identity and Durable Lineage
Foundation is committed at `9f6627770c43fd3b3af492d2201e647af77cc53f` on
`django-migration`. Gmail Provider Adoption into Retained-Source Authority is committed
at `fcbfcf353201552d4a579408299323e0bf731b21`. **Backend ApplicationMessage Relationship
Foundation** is committed at `b5c1faf1ad100acfd3d24aead679c3a1831f3a48`.
**Retained Application Review Identity & Candidate Snapshot Foundation** is committed
at `eedf57abbdf98f05d430ac116941fc447336f87b`. **Retained Review Attach to Existing
Application** is committed at `4d545820f62d92c76cf4da189706f17b3832949f`.
**Retained Review Disposition — Dismiss / Restore Foundation** is committed at
`5e25093a62a6c908d2da8123d1d6a7323eca2cd5`. **Retained Review Create Application
Orchestration** is committed at `ab1cb0e5e37faff606b1be7c84cf83fb99f77e30`
(`Implement retained review create application orchestration`).
**JobPosting Portable Identity Foundation** is committed at
`6863f277b04e1f084d6f7b2169c4a8209c65592c` (`Implement JobPosting portable identity`).
**Retained Posting Extraction Provenance Foundation** is committed at
`c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6` (`Implement retained posting extraction provenance`).
**Durable Posting Source-Item Identity + Immutable Initial Output Association** is
committed at `2090a61b1a43252a8eb93d82c87c7d90e4c40074`
(`Implement retained posting item identity`). **Append-Only Posting-Item Association
Corrections + Revision-Based Effective State** is committed at
`8812bf8f61de1db5b622af6f61b71a5a1b68fdb3` (`Implement retained posting item corrections`).
**Attach Existing JobPosting Only + Immutable Initial PostingSource Mapping** is
committed at `482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3`
(`Implement initial PostingSource mapping`). **PostingSource Correction / Effective-Mapping
Authority** is committed at `ac6d13db7f52889bff12b128a153e397769fee67`
(`Implement PostingSource correction authority`). **Retained Posting Interpretation
Selection Authority** is committed/pushed at `d46ef1508259f0418d1d0c842678456c883f5732`
(`Implement retained posting interpretation authority`). **Posting-Level Interpretation
Arbitration Authority** is committed/pushed at
`5f832dcc261d13365d851806623fca1a373e1644`
(`Implement posting-level interpretation arbitration authority`). Descriptor Projection
Authority is committed/pushed at `8ba7bc869787f80b217c0c066f9c713a337a5669`
(`Implement descriptor projection authority`). Canonical JobPosting Allocation is
committed/pushed at `cce6cf08717d6dca18fd1ce8945f68df9589f39e`
(`Implement canonical JobPosting allocation authority`). Retained Posting Review
Orchestration was reviewed and committed/pushed at
`ecb2ecf98c7d12552b5b0b9327f1f74fd28388ff`
(`Implement retained posting review orchestration`). Retained Posting Candidate
Discovery was reviewed and committed/pushed at
`3aab4762224efbf1d8e5b11f57040b88eb9a4094`
(`Implement retained posting candidate discovery`). Retained-Text Job-Alert
Extraction Producer was reviewed and committed/pushed at
`56c45dcb6768e6af9ab73f7c739ee27c665020f1`
(`Implement retained text extraction producer`). It provides explicit retained-message
extraction production from retained-selector-derived arguments using the existing
`job_alert_rules` / `"1"` parser, immutable ordered extraction evidence, historical
replay before parsing and shared persisted-batch validation; it is not canonical ingestion.
Explicit Retained Extraction Request Batch Command was reviewed and committed/pushed
at `97751b857ba0ce784cd7b80d7c9fa42930204285`
(`Add retained extraction batch command`). It is an operator-controlled execution adapter
around that producer: explicit retained-message IDs, caller-owned UUIDv4 operations and
exact input specifications undergo complete bounded preflight before sequential producer
invocation. Independent per-entry transactions preserve earlier successes on first failure;
unchanged retry uses producer idempotency. Content-free reporting ends at immutable
extraction evidence, without provider automation or downstream orchestration.
Source-Scoped Retained Extraction Evidence Inspection was reviewed and committed/pushed
at `b3a8d451272bd1ee5e4626e4b30ebd5f5f6cbc63`
(`Implement source-scoped retained extraction inspection`). The owner-authorized,
read-only domain contract exposes bounded source history before item association,
including no recorded history, completed zero-output operations and unassociated outputs.
It reuses complete extraction-batch validation and returns detached immutable evidence
with advisory current source eligibility; it adds no execution or downstream authority.
Workspace-Scoped Read-Only Retained Extraction Evidence HTTP API was reviewed and
committed/pushed at `56214508cd646650863b23628e58c10b80fea010`
(`Implement retained extraction evidence API`). This authenticated, owner-scoped,
bounded endpoint consumes the existing source-scoped evidence reader and adds HTTP
transport/navigation only, without extraction execution or downstream mutation authority.
Frontend integration, historical reconciliation, email derivation and operational
cutover remain pending.

## 1. Scope and source of truth

- Code and migrations establish implementation. [Decisions](DJANGO_MIGRATION_DECISIONS.md)
  owns accepted product/architecture boundaries; [Foundations](DJANGO_MIGRATION_FOUNDATIONS.md)
  owns accepted detailed contracts; this document owns current implementation,
  verification, and readiness. Apparent conflicts must be surfaced for review,
  never silently resolved by rewriting an authoritative document.
- The [plan](DJANGO_MIGRATION_PLAN.md) supplies broader context. Handoffs/specs
  are supporting historical/behavioral evidence, subordinate where stale or conflicting.
- Keep four states separate: **accepted/designed**, **implemented**,
  **automated-test verified**, and **operationally/end-to-end validated**.
  Acceptance is not implementation; passing component tests is not cutover proof.
- Correct this checkpoint when code/evidence materially changes. Do not change
  accepted decisions implicitly or append a chronological session transcript.

## 2. Current verification evidence


### Workspace-Scoped Read-Only Retained Extraction Evidence HTTP API — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `56214508cd646650863b23628e58c10b80fea010`,
parent `e96a33c13a3a554a4faa6bdffa6118a30a89316f`. The endpoint
`GET /api/workspaces/{workspace_id}/retained-messages/{retained_message_id}/posting-extractions/`
(route name `retained-posting-extraction-list`) requires authenticated session ownership,
reuses existing Workspace scoping and explicit source routing, and calls the existing
source-scoped evidence reader. Historical operations preserve no-history versus completed
zero-output semantics and valid conflicted-source inspection with `source_eligible=false`.

Strict bounded navigation uses default limit 2 and maximum 5, with a stateless unsigned
canonical base64url cursor. The cursor carries navigation state, not authorization;
Workspace/source context is independently revalidated. Valid numeric `last_extraction_id`
changes intentionally alter navigation. Pagination remains advisory, not a snapshot.
Explicit response-field whitelists exclude raw retained content, provider payload/locator,
credentials and association/canonical identity fields. `input_spec_json` remains a canonical
extraction-metadata string; historical order, nulls, blanks, duplicates and timestamps are
preserved.

JSON-only GET/HEAD/OPTIONS handling has no mutation handlers and sets
`Cache-Control: no-store`. Existing 400/401/404/409 conventions are preserved; DatabaseError
inside APIView dispatch receives a fixed sanitized 500 without raw exception text, SQL or
source content. Earlier middleware failures remain governed by existing infrastructure.
Ordinary endpoint/domain behavior is read-only; exceptional Django session maintenance may
legitimately update/delete session infrastructure without becoming domain mutation.

This adds HTTP transport/navigation authority only: no extraction execution, provider/sync
adoption, automatic source admission, generated operation identity, selector inference,
item association, interpretation, PostingSource mapping, allocation, arbitration,
projection, Application mutation, frontend workflow, PostgreSQL validation or scheduling/
retry state. No model, migration or durable cursor state is added.

Retained implementation/final-review evidence: API **18 passed**, source inspection
**22 passed**, recorder **34 passed**, producer **22 passed**, batch command **29 passed**,
retained interpretation **58 passed**, retained posting review **53 passed**, Candidate
Discovery **26 passed**, combined focused **262 passed**, postings **615 passed**, affected
apps **1,332 passed** and full Django **1,332 passed**, with no failures/errors/skips.
Django system check passed; postings migration drift: none. Global dry run reported only
the known `EmailAccount.provider` alteration, not generated. Static/scope checks passed.
Application tests were not rerun during commit/push and are not being rerun merely for
this documentation maintenance; these are retained results, not fresh documentation-stage
application tests.

Accepted limitations: advisory pagination, unsigned valid boundary edits, APIView-local
DatabaseError sanitization and exceptional session maintenance remain as described above.
PostgreSQL operation and production deployment/operation remain unverified; provider
extraction automation remains unresolved/unvalidated. A stable read-only HTTP contract now
exists, but browser/frontend workflow remains unimplemented and separately scoped.
Provider/storage/jobs/backup-restore/cutover gates remain open.

### Source-Scoped Retained Extraction Evidence Inspection — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `b3a8d451272bd1ee5e4626e4b30ebd5f5f6cbc63`,
parent `09e07d821615b1571668dcc7c3e5734bafeed906`. Explicit actor/Workspace/source
context reuses existing owner authorization and retained-source integrity validation.
The domain reader exposes historical operations before item association, distinguishing
no recorded extraction history from a completed zero-output operation without drawing
job/relevance conclusions. Unassociated outputs remain inspectable.

Bounded ascending-PK keyset navigation returns detached immutable source/operation/output
DTOs and canonical immutable input-specification JSON. Every returned operation uses the
existing extraction-owned complete batch validator; corrupt returned evidence fails the
whole call rather than returning a partially validated page. SELECT-only reads acquire
no write locks. Source eligibility is advisory current state; pages are not snapshots,
and later higher-PK operations may appear on subsequent reads.

This adds read/navigation authority only: no extraction or replay execution, provider/sync
adoption, automatic admission, generated operation identity, inferred selectors, item
association, interpretation/mapping/allocation/arbitration/projection or Application writes.
No HTTP routes, serializers, frontend consumer, cursor transport encoding, durable work
state or scheduling were introduced by that slice. At that checkpoint, a later read-only
HTTP API remained separately scoped and unselected; the completed adapter is recorded above.

Retained implementation/final-review evidence: targeted correction **2 passed**, source
inspection **22 passed**, combined focused **244 passed**, postings **597 passed**,
affected apps **1,314 passed** and full Django **1,314 passed**, with no failures/errors/
skips. Django system check passed; postings migration drift: none. Global dry run reported
only the known `EmailAccount.provider` alteration, not generated. Static/scope checks passed.
Application tests were not rerun during commit/push and are not being rerun for this
documentation maintenance; these are retained results, not fresh application tests.

Accepted limitations: reads are advisory, not snapshots; PostgreSQL operational behavior
remains unverified. Reusing the complete validator costs queries per returned operation
and transient memory. Privileged evidence rewrites remain unsupported; arbitrarily
oversized corrupt database JSON may allocate before validation rejects it. Cursor transport
serialization was future API work at that checkpoint and is now supplied by the adapter
above. Provider/storage/jobs/backup-restore/cutover gates
remain open.

### Explicit Retained Extraction Request Batch Command — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `97751b857ba0ce784cd7b80d7c9fa42930204285`,
parent `1f79d0050b154112d7cd033fbf35376559b052ea`. The management command accepts
one bounded strict JSON request file, validates the entire structure and authorizes an
explicit persisted actor/Workspace before any execution. Caller-owned operation UUIDv4s
and exact retained input specifications define requests; specifications are detached before
execution, with regression coverage proving nested mutation independence.

Requests run sequentially in supplied order through the existing producer as the sole
extraction execution authority. No command-wide transaction encloses the independent
producer transactions. First failure stops execution while preserving earlier committed
entries; unchanged retry replays completed operations. Transaction-context rejection
before invocation leaves the current request unattempted; once invocation begins, that
request counts as attempted even if it fails. Execution terminates at immutable extraction
evidence with deterministic content-free JSON reporting.

This is an operator execution boundary only. It does not complete provider/sync adoption
or decide provider operation-ID, admission/classification or failure/retry policies.
Automatic retained-item association, interpretation/PostingSource/allocation automation,
arbitration/projection automation, retained-to-canonical JobPosting ingestion and
retained-workflow API/frontend integration remain incomplete. No model, migration or
downstream authority change is included.

Retained implementation/final-review evidence: command **29 passed**, combined focused
**174 passed**, postings **575 passed**, affected apps **1,292 passed** and full Django
**1,292 passed**, with no failures/errors/skips. Django system check passed; postings
migration drift: none. Global dry run reported only the known `EmailAccount.provider`
alteration, not generated. Diff, AST, final-newline, whitespace and empty-initializer
checks passed. Application tests were not rerun during commit/push and are not being
rerun for this documentation maintenance; these are retained results, not fresh tests.

Accepted limitations: validation uses isolated SQLite databases; PostgreSQL operational
behavior remains unverified. Invocation is operator-controlled, with no durable batch
lifecycle; retry requires preserved operation UUIDs/specifications. Stdout delivery can
fail after successful persistence, and unexpected connection/commit failures can leave
the failing request's state uncertain. Standard operator debugging such as `--traceback`
may expose stack details outside the normal sanitized output contract. Broader
provider/storage/jobs/backup-restore/cutover gates remain open.

### Retained-Text Job-Alert Extraction Producer — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `56c45dcb6768e6af9ab73f7c739ee27c665020f1`,
parent `a9e2be91dd4a6bac0a67e8d21788066e8fcebd3c`. The explicit synchronous producer
resolves declared retained selectors and executes the existing `job_alert_rules` / `"1"`
parser only for new operations. It records through the existing extraction recorder,
using shared extraction-owned persisted-batch validation. Historical replay occurs
before parsing and preserves ordered outputs, IDs and timestamps; changed operation
intent is rejected. Zero-output completion is valid, parser failure records no completed
evidence, and valid historical replay remains available after sticky source conflict
with `source_eligible=False`. Workspace/source locks cover parsing, nested recording
and detached frozen receipt construction; recording and receipt failure roll back new evidence.

This completes extraction production only. Existing explicit downstream authorities
remain implemented separately; automatic retained-item association, interpretation,
PostingSource mapping, canonical allocation and arbitration/projection adoption remain
incomplete, as do provider/sync adoption and retained-workflow API/frontend integration.
No model, migration, parser-semantic, provider, API or frontend change is included.
The earlier recorder-only provenance scope and exclusions remain historical evidence.

Retained implementation/final-review evidence: focused producer/recorder/interpretation/
parser suites **145 passed**; full Django **1,263 passed**, with no failures/errors/skips.
Django system check passed; postings migration drift: none. Global dry run reported only
the known `EmailAccount.provider` alteration, not generated. Diff, AST, final-newline
and whitespace checks passed. Application tests were not rerun during commit/push
or this documentation maintenance; these retained results are not fresh documentation-stage tests.

Accepted limitations: parsing holds Workspace/source locks; historical replay performs
repeated bounded validation; PostgreSQL contention remains operationally unvalidated.
Privileged bulk/raw maintenance can bypass cooperative protections, rolled-back parsing
may execute again on explicit retry, and caller-owned outer transactions determine
eventual commit. Provider/storage/jobs/backup-restore/cutover gates remain open.

### Retained Posting Candidate Discovery — committed checkpoint, 2026-10-05

Reviewed, committed and pushed at `3aab4762224efbf1d8e5b11f57040b88eb9a4094`.
The four-file backend slice adds advisory SQL-read-only interpretation observation,
exact company/title candidate discovery, location as factual evidence only, Workspace
and posting-account Workspace safety, ascending-PK keyset pagination and detached
advisory results. It confers no identity or mapping authority and performs no allocation,
interpretation selection, arbitration, projection or Application/disposition writes.
No model, migration, API or frontend change is included.

Retained final-review evidence: focused interpretation/candidate tests **83 passed**;
full Django **1,239 passed**, with no failures/errors/skips. Django system check,
SQL-read-only, detachment and diff checks passed. Postings migration drift: none;
global dry run reported only the known EmailAccount.provider alteration, not generated.
This documentation-only update adds no new application-test or operational evidence;
application tests were not rerun during documentation maintenance.

Accepted limitations: advisory observations are non-serialized; interpretation validation
cost grows with history; candidate pagination bounds canonical rows materialized, not
total database scan cost. PostgreSQL operational behavior remains unvalidated.
Browser/provider/storage/jobs/backup/restore/cutover gates remain open.

### Retained Posting Review Orchestration — historical implementation-stage evidence, 2026-10-04

Subsequently reviewed, committed and pushed at
`ecb2ecf98c7d12552b5b0b9327f1f74fd28388ff`. Counts and Git-stage statements
below describe the original implementation-stage verification, not current repository state.

Prior authoritative checkpoint: `cce6cf08717d6dca18fd1ce8945f68df9589f39e`.
Stateless coordinator and advisory reader implemented within six authorized files;
no model/migration or canonical primitive changes. Independent phase commits preserve
explicit mapping/allocation, selection and projection authority. Strict transaction
context guard, immutable DTOs, detached receipts and structured partial failures are
implemented. Application/disposition/API/frontend behavior remains outside scope.

Fresh tests: orchestration 53; PostingSource 70; allocation 40; combined retained
interpretation/arbitration/projection 151; Application review 83; postings 488;
affected apps 1,187; full Django 1,205. All final runs passed without failures/errors/
skips. Django check passed; postings drift none; global dry-run only the known
EmailAccount.provider alteration, not generated. Python AST, final newlines,
whitespace, Markdown links/anchors and diff checks passed. All three added files
inspected; exact three modified/three untracked scope, empty index, checkpoint and
remote synchronized 0/0, database/provider migration paths absent.

At that implementation stage, the slice was complete and ready for separate read-only
pre-commit review, not yet committed or operationally validated. Independent commits can leave partial
success, ambiguous outcomes require replay, and composed reads remain advisory.
SQLite concurrency is not PostgreSQL operational validation. See
[orchestration review](DJANGO_RETAINED_POSTING_REVIEW_ORCHESTRATION.md).



### Canonical JobPosting Allocation — historical implementation verification, 2026-10-04

Subsequently committed/pushed at `cce6cf08717d6dca18fd1ce8945f68df9589f39e`.
The counts and Git-stage statements below describe the original allocation verification.

Implemented and automated-test verified; sixteen files remain unstaged, uncommitted
and unpushed on django-migration. Prior authoritative checkpoint:
`8ba7bc869787f80b217c0c066f9c713a337a5669`. Separate read-only pre-commit review is next.

- Explicit owner allocation atomically creates a default-only JobPosting, initial
  PostingSource and immutable JobPostingAllocation. Selected interpretation/evidence,
  locator and mailbox binding are validated; reserved identity and ingestion guards,
  historical replay/readers and read-only admin are implemented.
- Fresh implementation-pass results: allocation + migration 40; Gmail migration 1;
  PostingSource 70; retained interpretation 49; arbitration 46; projection 57;
  services/ingestion 19; postings 435; affected apps 1,134; full Django 1,152.
  All final runs: zero failures/errors/skips. Existing passing suites were retained;
  Gmail migration, affected apps and full Django ran after the test-only correction.
- Django check passed; postings drift none; global drift only the known provider
  AlterField (dry-run only). Graph through 0012; inspected SQL creates only the new
  allocation table and constraints/indexes. Populated migration fixture preserves
  existing tables without backfill and checks alias-aware validation.
- Two bounded interruptions required explicit authorization: accidental provider
  migration generation was stopped and repaired only by deleting that file and
  correcting 0012 to email_sync 0007; the Gmail historical fixture's impossible
  email_sync 0006/latest-postings combination was corrected in the authorized
  sixteenth file by pinning postings 0011, preserving current forward leaves and
  all assertions. The latter changes no production behavior.
- Scope: eleven modified, five untracked, nothing staged. Local/origin/live remote
  remain synchronized at the checkpoint (0/0); real DB and both provider migration
  paths absent. Python parsing, newlines, whitespace, Markdown links/anchors and
  diff checks passed; all five added files inspected.
- SQLite concurrency tests use caller retries for contention, not production retries
  or PostgreSQL verification. PROTECT can block account deletion; disconnect remains
  allowed. Raw maintenance bypass, semantic duplicates, orphan lifecycle, unbound
  allocation, API/frontend, historical reconciliation and operational cutover remain
  outside this implementation evidence.

See [allocation review](DJANGO_JOB_POSTING_ALLOCATION_REVIEW.md) for the full contract,
scope, validation and limitations.


### Descriptor projection authority — historical pre-commit verification, 2026-10-03

Subsequently committed/pushed at `8ba7bc869787f80b217c0c066f9c713a337a5669`.
The Git-stage statements and counts below are historical projection evidence.

Prior authoritative checkpoint: `5f832dcc261d13365d851806623fca1a373e1644`.
The current thirteen-file slice is implemented and validated, unstaged/uncommitted/
unpushed, awaiting separately authorized read-only pre-commit review.

- Immutable JobPostingDescriptorProjection records an exact arbitration FK, six-field
  snapshot and matched descriptor-digest precondition. One transaction appends and
  materializes exactly source/title/company/location/salary/employment_type, then
  rereads/verifies. URL, dedupe, identity, metadata and lifecycle remain outside it.
- Destination capacities reject atomically; no widening or normalization. Ownership
  persists after first projection. Ingestion preserves owned descriptors, ordinary
  saves enforce alias-aware guards, and admin rejects stale protected submissions.
- Replay never rematerializes. Explicit drift repair is supported; arbitration/lower
  staleness, descriptor drift and sticky-conflict eligibility remain distinct. Frozen
  coherent readers and captured-prefix history reuse existing arbitration validation.
- Additive migration 0011 creates one table with five named constraints and three
  protected FKs. Populated 0010 and non-default-alias tests pass; no backfill/allocation.
- Fresh corrective-pass suites, 2026-10-04: focused **57 passed** (8.024s),
  postings **393 passed** (32.790s), affected apps **1092 passed** (130.831s),
  full Django **1110 passed** (136.678s), with zero failures/errors/skips.
  Three added regressions cover primary-key-only deferred saves (including forced
  saves), explicit empty saves, and continued projection ownership. Automatic empty
  inference now leaves update_fields unset. Earlier services **17 passed** and
  neighboring authority **256 passed** are prior implementation evidence, not reruns.
- Fresh Django check passed. Prior schema validation: postings drift none; global dry
  run only the known provider
  choice-label alteration, deliberately ungenerated. Graph through 0011; SQL inspected.
  AST/newline/whitespace/local Markdown links and git diff --check passed.
- Exactly eight modified/five untracked authorized files, nothing staged. Checkpoint
  remains unchanged and synchronized. Real DB/provider migration absent. SQLite test
  contention uses explicit caller retry, not production retries or PostgreSQL proof.
- Digest detects current equality, not ABA history. Bulk/raw bypasses, growing history
  cost, PROTECT/purge handling and stale values in existing consumers remain limitations.
  No API/frontend, field widening, allocation, provider or cutover expansion.

See [projection review](DJANGO_JOB_POSTING_PROJECTION_REVIEW.md) for implementation,
commands/log locations, validation details, scope and limitations.

### Posting-level interpretation arbitration — historical pre-commit verification, 2026-10-03

Subsequently committed/pushed at `5f832dcc261d13365d851806623fca1a373e1644`.
The Git-stage statements and counts below are historical arbitration evidence.

Prior authoritative checkpoint `d46ef1508259f0418d1d0c842678456c883f5732`,
subject `Implement retained posting interpretation authority`, parent
`ac6d13db7f52889bff12b128a153e397769fee67`. Branch/local/tracking/live remote,
0/0 ahead/behind, clean pre-edit tree/index, and DB/provider migration absence verified.
See [arbitration review](DJANGO_JOB_POSTING_INTERPRETATION_REVIEW.md).

- Explicit append-only posting selection binds an exact item interpretation and initial
  mapping/revision. No implied winner, fallback, transfer, reactivation or projection.
- Historical mapping/interpretation/membership and extraction witnesses validate;
  independent current witness changes yield all applicable ordered stale reasons.
- Atomic Workspace gate then all relevant sources in ascending order. Replacement checks
  new-source eligibility; conflicted old valid sources allow replacement but current-source
  conflict blocks withdrawal. Validated replay/reads remain allowed; corruption fails closed.
- Additive 0010: one empty table, six constraints, protected references, alias-aware
  insertion guard and read-only admin. Populated-0009 preservation and repeat target tested.
- Focused **47 passed** (4.591s), neighboring **216 passed** (10.204s), postings
  **331 passed** (24.316s), affected apps **1030 passed** (119.098s), full Django
  **1048 passed** (138.057s); all zero failures/errors/skips. Completed affected log
  reused on continuation; full suite ran on 2026-10-03. No production/test edits followed.
- Django check and scoped postings drift pass. Global dry run reports only the known
  EmailAccount.provider choice-label alteration; no file generated. Graph reaches 0010;
  SQL confirms one additive table, six constraints and four automatic FK indexes.
- Exactly eleven authorized files, six modified/five untracked, unstaged/uncommitted/unpushed.
  All added files inspected; syntax, whitespace, local Markdown links and diff checks pass.
  HEAD/local/tracking/live remote remain the prior checkpoint, ahead/behind 0/0;
  DB/provider migration absent. Separate read-only pre-commit review is next.
  PostgreSQL, production scale, providers and cutover remain unvalidated.

### Retained posting interpretation selection — historical pre-commit verification, 2026-09-29

Base `ac6d13db7f52889bff12b128a153e397769fee67` on `django-migration`; branch,
local/tracking/live remote, subject/parent, clean pre-edit tree/index, and DB/provider
migration absence verified. See [interpretation review](DJANGO_RETAINED_POSTING_INTERPRETATION_REVIEW.md).

- Item-level append-only select/withdraw decisions; revision 0 unresolved. Whole-output
  selection records a validated logical membership witness. Later membership revisions
  make selection stale, including away-and-back; explicit reaffirmation appends.
- UUID replay returns original immutable event plus current state; historical membership
  prefixes and complete persisted extraction envelopes/digests validate without parsing.
  Coherent readers share Workspace/source serialization; captured-prefix history pagination.
- Additive 0009 creates one empty table with six constraints and protected references.
  Read-only admin and alias-aware ordinary insertion guards. No mapping, descriptor,
  allocation, ingestion, API/frontend or lifecycle side effects.
- Historical final suites from that implementation pass: interpretation/migration **50 passed** (3.265s), neighboring
  retained-posting **166 passed** (8.586s), postings **284 passed** (18.516s), affected
  apps **983 passed** (118.894s), full Django **1001 passed** (124.966s); zero
  failures/errors/skips. Affected/full completion logs were reused on continuation;
  no implementation/test edits followed these results. Isolated SQLite only.
- Django check and scoped postings drift pass. Global drift is only the known provider
  choice-label alteration; no provider migration generated. Graph/SQL confirm additive
  0009; populated-0008 preservation, repeated target and non-default alias validation pass.
- At that implementation checkpoint: eleven files, six modified/five added,
  unstaged/uncommitted/unpushed; HEAD was the base. DB/provider migration absent;
  added-file inspection, syntax, whitespace, local Markdown links and diff checks passed.
  Separate review and commit/push subsequently completed at
  `d46ef1508259f0418d1d0c842678456c883f5732`. PostgreSQL, production scale,
  providers and cutover remained unvalidated.

### PostingSource correction/effective mapping — historical pre-commit verification, 2026-09-28

Base `482bcc5f9528fb9a6e9b3e7dce1c43a7443c40b3` on `django-migration`; local,
tracking/live remote, parent/subject, clean tree/index and DB/provider-migration absence
verified before edits. See [correction review](DJANGO_POSTING_SOURCE_CORRECTION_REVIEW.md).

- Append-only associate/withdraw events anchored to the initial assertion; revision 0
  initial, contiguous later revisions, UUID replay returning original event plus current
  state, no-op rejection, scoped historical-target validation and captured-prefix readers.
- Additive 0008 creates one empty table with six constraints. PROTECT/read-only admin;
  no allocation, descriptors, interpretation, membership coupling, ingestion or API changes.
- Focused **105 passed** (5.338s); postings **234 passed** (15.194s); affected
  **933 passed** (111.575s); full Django **951 passed** (120.240s). All final runs have
  zero failures/errors/skips, isolated SQLite only. Focused/postings ran before the
  separately authorized one-line core admin read-only allowlist update; affected/full
  ran afterward. The prior affected run's single allowlist expectation failure is resolved.
- Django check and postings drift check pass. Global dry run reports only known
  EmailAccount.provider drift; no file generated. Migration graph/SQL confirm additive
  0008; disposable populated-0007 preservation and non-default alias validation pass.
- At that implementation checkpoint: eleven authorized files, unstaged/uncommitted;
  HEAD was `482bcc5f`. Separate review and commit/push subsequently completed at
  `ac6d13db7f52889bff12b128a153e397769fee67`. The counts above are historical
  implementation evidence. Real DB/provider migration were absent; added-file inspection,
  syntax/whitespace/local Markdown links and diff checks passed. PostgreSQL, production
  scale, providers, cutover and purge remained unvalidated/deferred.

### Initial PostingSource mapping — historical pre-commit verification, 2026-09-28

Base `8812bf8f61de1db5b622af6f61b71a5a1b68fdb3` on `django-migration`; repo/branch,
local/tracking/live remote, subject/parent, clean tree/index and DB/provider-migration
absence verified before edits. See [PostingSource review](DJANGO_POSTING_SOURCE_REVIEW.md).

- Immutable explicit-owner item→existing JobPosting assertion; item-keyed replay,
  many items per posting, no allocation/descriptive interpretation or downstream writes.
  Zero-output items are allowed; later membership correction leaves mapping unchanged.
- Current-owner Workspace gate, persisted endpoint/account scope, source integrity,
  sticky-conflict read/replay semantics, bounded initial-only readers and read-only admin.
  PROTECT intentionally blocks mapped endpoint/account cascades; deletion API handling
  and account decoupling remain deferred. Disconnect retains mapping and account.
- Focused **30 passed** (29 service/model/reader/concurrency/admin + 1 migration; 1.551s),
  postings **192 passed** (13.949s), affected **891 passed** (112.008s), full Django
  **909 passed** (117.394s). External in-memory SQLite/disposable fixtures only.
- System checks, posting migration drift, AST/whitespace/local references/diff checks
  pass. Global dry-run drift is only known EmailAccount.provider; no migration generated.
- Additive 0007 creates one empty table with item OneToOne and two policy checks.
  Historical 0006 fixture preserves all prior rows/columns, including correction history,
  and repeated migration target is stable. No historical mapping inference/backfill.
- At that review: exactly eleven approved files, unstaged/uncommitted; subsequently
  committed at `482bcc5f`. backend/db.sqlite3 absent/untracked;
  provider migration absent. Initial/correction/extraction services, ingestion, parser,
  provider, API/frontend and deletion surfaces unchanged.
- Initial mappings are historical assertions for inspection only. Mapping corrections/
  effective authority must precede canonical consumers. SQLite explicit-retry tests do
  not validate PostgreSQL contention, production scale, live providers or cutover.

### Append-only posting-item corrections — historical pre-commit verification, 2026-09-28

Base `2090a61b1a43252a8eb93d82c87c7d90e4c40074` on `django-migration`; repository,
local/tracking/live remote, subject/parent, clean tree/index and DB/provider-migration
absence verified before edits. See [correction review](DJANGO_RETAINED_POSTING_ITEM_CORRECTION_REVIEW.md).

- Immutable owner-attributed associate/withdraw revisions, operation UUID replay and
  expected-revision concurrency; historical operation and current state are separate.
  No-op rejection does not reserve UUIDs. Initial assertions and old items remain intact.
- Shared chain validation checks all captured revisions; owner-scoped effective reads,
  captured-bound history and read-only admin. Source integrity precedes replay; sticky
  conflict blocks new work including withdrawal, while permitting read/exact replay.
- Focused **33 passed** (32 service/model/reader/concurrency/admin + 1 migration; 1.678s),
  postings **162 passed** (12.477s), affected **861 passed** (110.282s), full Django
  **879 passed** (115.308s). External in-memory SQLite settings/disposable fixtures only.
- System checks, postings drift, AST, whitespace, documentation references and diff
  checks pass. Global dry-run drift remains only known EmailAccount.provider; no file generated.
- Additive 0006 creates one empty table and six constraints; populated historical
  migration test preserves all old tables/rows/columns and repeats the target stably.
- At that review: exactly eleven authorized files, unstaged/uncommitted; subsequently
  committed at `8812bf8f`. Initial service, migration 0005,
  extraction contracts, provider/frontend/API and unrelated production code unchanged.
  backend/db.sqlite3 and unrelated provider migration remain absent.
- SQLite contention tests use explicit retry; PostgreSQL locks/deadlocks, production
  scale, live providers, export/restore and cutover remain unvalidated. No interpretation
  selection, split/merge, PostingSource, ingestion or historical backfill is implemented.

### Durable posting items + immutable initial associations — historical pre-commit verification, 2026-09-28

Base `c5f8e20f9db15e2cf4dc9f0e80a0929bd222fff6` on `django-migration`; local/tracking/live
remote, subject/parent, clean tree/index and DB/provider-migration absence were verified
before edits. See the [item foundation review](DJANGO_RETAINED_POSTING_ITEM_REVIEW.md).

- Source-scoped immutable item identity and initial output associations; explicit-owner
  allocation/attachment only. Output-keyed replay preserves original actor even for a
  different current owner. Same-source validation, atomic allocation, bounded readers
  and read-only admin; no automatic continuity, correction, current selection or mapping.
- Retained-item tests **26 passed** (0.399s), populated migration **1 passed** (0.870s),
  postings **129 passed** (10.312s), affected apps **828 passed** (106.954s), full Django
  **846 passed** (112.804s). Isolated SQLite only; no real database opened or migrated.
- System checks, posting drift, AST, whitespace, local references and diff checks pass.
  Global dry-run drift remains only known EmailAccount.provider; no migration generated.
- Additive 0005 creates two empty tables with protected references and finite constraints;
  existing extraction provenance and all other populated fixture tables are preserved.
- At that review: exactly eleven authorized files; unstaged/uncommitted; backend/db.sqlite3
  and provider migration absent. Subsequently committed at `2090a61b`. Committed extraction 0004/contracts/helpers remain unchanged.
- PostgreSQL locking/deadlocks, production scale, live providers, scheduling, export/restore
  and cutover remain unvalidated. Actor assertion is accountable, not proof of human review.
  At that checkpoint correction/effective decisions were deferred. Interpretation
  selection, split/merge, PostingSource, historical reconciliation and ingestion remain deferred.

### Retained Posting Extraction Provenance — historical pre-commit verification, 2026-09-28

Base `6863f277b04e1f084d6f7b2169c4a8209c65592c` on `django-migration`; repository,
HEAD/tracking/live remote, subject/parent, clean tree/index and absent local DB/provider
migration were verified before edits. See the [extraction provenance review](DJANGO_RETAINED_POSTING_EXTRACTION_REVIEW.md).

- Immutable completed operations and ordered output observations, strict versioned
  input/output contracts, source integrity/scope validation, atomic replay/conflict
  recording, scoped reader and read-only admin. No parser execution or JobPosting writes.
- Initial implementation verification (before correction): provenance **29**, migration
  **1**, combined **30**, postings **98**, retained-source/review **69**, affected **797**,
  full Django **815** passed. The review then found receipt-provenance semantic validation
  missing despite matching digests. This history is preserved in the slice review.
- The bounded correction enforces canonical provider/receipt-source compatibility and
  adjacent receipt precision/value rules, without retention or digest-schema changes.
  New receipt regressions **4 passed**; all provenance **33 passed**, migration **1 passed**
  (combined **34**, 1.440s), retained-source/review **69 passed**, postings **102 passed**,
  affected apps **801 passed** (103.609s), full Django **819 passed** (108.779s).
- System check, posting drift, AST, whitespace, local Markdown references and diff
  checks pass. Global dry-run drift remains only known `EmailAccount.provider`.
- Additive postings 0004 creates two empty tables and three unique constraints; no
  historical backfill. Disposable migration fixture preserves every pre-existing row.
  The separately approved thirteenth-file correction pins the old retained-email
  migration test's pre-retention postings baseline to 0003; assertions remain intact.
- Isolated in-memory/disposable SQLite only; no real database opened or migrated.
  At verification, `backend/db.sqlite3` and provider migration were absent and nothing
  was staged/committed. The slice subsequently committed at `c5f8e20`.
- PostgreSQL concurrency, production payload performance, providers, task/retry
  orchestration, export/restore and cutover remain unvalidated. Recorder trusts the
  producer envelope. At that checkpoint, source items, PostingSource, evidence and
  ingestion remained deferred.

### JobPosting portable identity — historical verification, 2026-09-27

Base `ab1cb0e5e37faff606b1be7c84cf83fb99f77e30` on `django-migration`; local HEAD,
tracking and live remote matched with a clean tree before edits. The approved 11-file
slice was uncommitted during verification and subsequently committed at `6863f277`.
See the [posting identity review](DJANGO_POSTING_IDENTITY_REVIEW.md).

- Identity **5 passed**, populated migration **1 passed**, posting service/view **31 passed**,
  Application identity/creation regressions **25 passed**. Posting-focused **68 passed**
  (7.384s); affected **767 passed** (105.766s); full Django **785 passed** (108.560s).
  All final runs exited 0 against the final code/test state.
- System checks, Python AST, whitespace, Markdown references and diff checks pass.
  Posting model/migration drift is absent. Global dry-run drift is only known
  `EmailAccount.provider`; no unrelated migration file was generated.
- `postings.0003_jobposting_portable_identity` allocates UUIDs without merging rows,
  changing old columns/relationships or inferring source lineage. Direct helper replay
  and migration-target replay preserve assigned identities. A migration test executor-cache
  issue was corrected in the new test harness; production migration was unchanged.
- Verification used isolated SQLite and disposable migration fixtures; no real database
  was migrated. `backend/db.sqlite3` remains absent/untracked; nothing is staged.
- PostgreSQL migration locking/concurrent writes, deployed table size/performance,
  live providers and cutover remain unvalidated. Reverse schema removes UUID identity
  and is not identity-preserving rollback after external consumption.

### Retained review Create Application — historical verification at `ab1cb0e`, 2026-09-27

Base `5e25093a62a6c908d2da8123d1d6a7323eca2cd5` on `django-migration`; HEAD,
tracking and live remote matched before editing, with a clean tree and absent
`backend/db.sqlite3`. Implementation was left uncommitted for review, then committed
and pushed at `ab1cb0e`. See the
[creation review report](DJANGO_RETAINED_REVIEW_CREATE_REVIEW.md) for exact scope,
transaction boundaries, commands and limitations.

- Focused creation/review/identity/Category/derivation/lifecycle/migration/admin:
  **193 passed**, exit 0, 11.751s.
- Affected `applications documents email_sync core postings`: **758 passed**, exit 0,
  102.083s. Full Django: **776 passed**, exit 0, 107.240s, final code/test state.
- Bounded pre-commit correction rejects fresh-key continuations before intent insertion
  under the shared Workspace gate; existing pending state, digest mismatch precedence and
  completed replay are preserved across manual/posting/review creation. Two new persistence
  regression tests pass (0.249s); final suite counts above supersede 191/756/774.
- Django system checks, Python AST, whitespace and local documentation references pass.
  Application model/migration drift is absent; global drift remains only the known
  `EmailAccount.provider` choice change. No unrelated migration file was generated.
- Additive `applications.0010_retained_review_creation_result` is schema-only, with
  no historical backfill. Populated migration preservation and forward replay pass.
  The historical disposition test is pinned to its intended `0009` target without
  weakening preservation assertions; the new creation test is pinned to `0010`.
- Verification uses isolated SQLite settings/fixtures; `backend/db.sqlite3` remains
  absent. The slice was uncommitted during verification and subsequently committed at
  `ab1cb0e` after final review.
- PostgreSQL locking/deadlocks/isolation, live Gmail, browser/frontend, Redis/Celery,
  storage, deployment, backup/restore and cutover remain operationally unvalidated.

### Retained review disposition — historical verification at `5e25093`, 2026-09-26

Base `4d545820f62d92c76cf4da189706f17b3832949f` on `django-migration`; local HEAD,
tracking and live remote verified before edits and again when recovering the eight-file
interrupted implementation. No commit/push occurred during that implementation stage;
the slice was subsequently committed/pushed at `5e25093`. No unrelated changes. See the
[disposition review report](DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md) for exact
commands, file inventory, transaction reasoning and test-harness correction.

- Focused review/disposition/attachment/relationship/historical migration/lifecycle/admin:
  **93 passed**, exit 0, 6.000s.
- Affected `applications documents email_sync core postings`: **726 passed**, exit 0,
  96.230s. Full Django: **744 passed**, exit 0, 102.982s, final code/test state.
  **19 new tests** cover disposition, serialization, preservation and migration.
- System checks, whitespace and local documentation links pass. Application model drift
  check has no changes; new `0009` fully represents the sidecar. Global dry run reports
  only known `email_sync.0008_alter_emailaccount_provider` drift; no file generated.
- Populated forward upgrade from Application `0008` preserves every old table/column,
  fabricates zero dispositions, enforces one-to-one identity and supports forward replay.
  Existing historical migration tests pass unchanged. No data migration/backfill.
- Tests and management checks use external in-memory SQLite settings; historical
  migration fixtures use disposable files. `backend/db.sqlite3` remains absent.
  No real data or dependency changes. PostgreSQL locking/deadlocks, live Gmail, browser,
  Redis/Celery, storage, deployment, backup/restore and cutover remain unvalidated.
  No fresh legacy FastAPI/frontend suite is claimed.

### Retained review attachment — historical verification at `4d54582`, 2026-09-26

Verified clean checkpoint `eedf57a`, including exact live remote SHA after authorized
network escalation. The [attachment review report](DJANGO_RETAINED_REVIEW_ATTACH_REVIEW.md)
records exact commands, API and transaction boundaries, files and limitations.

- Focused attachment/review/relationship/historical migration/admin run: **59 passed**.
- Affected `applications email_sync core postings`: **652 passed**.
- Full Django suite: **725 passed**, exit 0, 98.664s, final code/test state; 12 new tests.
- System check, local documentation links and whitespace checks pass. Application model
  drift check reports no changes; global dry run reports only the known
  `email_sync.0008_alter_emailaccount_provider` choice drift, left unchanged.
- No schema/data migration. Existing historical migration preservation passes unchanged.
  Every database command uses external in-memory SQLite settings; migration fixtures
  use disposable databases. `backend/db.sqlite3` remains absent; no real data changed.
- No dependency, frontend, provider or legacy implementation changes. No PostgreSQL,
  live Gmail, browser, Redis/Celery, storage, backup/restore or cutover validation.
  Dismiss/restore was deferred at this checkpoint; the approved disposition slice is
  recorded separately below. These results predate that implementation.

### Retained Application review foundation — historical verification at `eedf57a`, 2026-09-26

Started from clean `b5c1faf`; root, branch, HEAD, tracking reference and live remote
matched. See the [review record](DJANGO_RETAINED_APPLICATION_REVIEW.md) for exact
commands, schema/API contracts, file inventory and limitations.

- Final focused review/relationship/historical migration/admin run: **47 passed**.
  Affected `applications email_sync core postings`: **638 passed** before two further
  tests. Final full Django, including those tests and a strengthened fresh-observation
  replay assertion: **713 passed**, exit 0. **25 new tests** including migration safety.
- System check, documentation links and whitespace checks pass. Scoped Application
  migration check has no changes; global dry run reports only known
  `email_sync.0008_alter_emailaccount_provider` choice drift. No new unexpected drift.
- Sole new migration: `applications.0008_retained_application_review`, additive schema
  only. Populated pre-review tables/rows remain unchanged and zero historical reviews/
  candidates are created. Plans were inspected using disposable settings.
- Missing `backend/venv` was created and declared requirements installed with explicit
  user approval; dependency declarations are unchanged. `backend/db.sqlite3` was absent
  at inspection and remains absent. All database verification used in-memory/disposable
  SQLite; the previous run's unresolved local provenance is not resolved by this run.
- No PostgreSQL, live Gmail, browser, worker/storage or cutover validation. No fresh
  legacy/frontend suite is claimed. Review actions, historical reconciliation, evidence
  generation and frontend integration remain separately scoped.

### ApplicationMessage relationship foundation — historical verification at `b5c1faf`, 2026-09-20

Started from clean `fcbfcf3`; root, branch, HEAD, tracking and live remote matched.
Continuation preserved the intentional diff at the same HEAD. See the
[ApplicationMessage review](DJANGO_APPLICATION_MESSAGE_REVIEW.md) for exact contracts,
changed files, historical migration-test rationale, verification and limitations.

- Final focused relationships, populated/historical migrations and admin: **22 passed**,
  exit 0. Affected `applications email_sync core postings`: **615 passed**, exit 0.
  Full Django: **688 passed**, exit 0. System, whitespace and local documentation-link
  checks pass.
- System check passes. Scoped Application migration check reports no changes;
  global dry run reports only the pre-existing EmailAccount.provider choice drift.
  Sole new migration: `applications.0007_application_message`; additive CreateModel,
  no historical backfill. Fresh and populated disposable database upgrades pass.
- Two historical migration tests pin their original Application `0006` schema while
  retaining the original email `0005`/`0006` baselines; explicit absence assertions
  prevent later schema from silently entering those baselines.
- Unexpected local `backend/db.sqlite3` already records `0007` as applied at
  `2026-09-20 20:12:32 UTC`; the user did not apply it. Read-only investigation found
  the table and record but cannot attribute the writer. This run did not migrate or
  alter that database; subsequent verification checks its hash/size/mtime unchanged.
  This is unresolved local provenance, not operational migration validation.
- No fresh legacy or frontend suite is claimed. SQLite logical concurrency, synthetic
  Gmail and API checks do not validate PostgreSQL, live Gmail or browser workflows.
  Review mutations, generated evidence, historical reconciliation and cutover remain
  separately scoped; replacement versus supersession remains unresolved.

### Gmail provider adoption — historical verification at `fcbfcf3`, 2026-09-20

Started from the exact clean `9f66277` checkpoint; local/tracking/live remote matched.
The implementation was subsequently committed at `fcbfcf3`. See the
[Gmail adoption review](DJANGO_GMAIL_ADOPTION_REVIEW.md) for inspection, contracts,
changed files, exact commands and limitations.

- Final focused `email_sync core.tests_workspace_scope core.tests
  applications.tests.test_derivation`: **394 passed**, exit 0, including 30 new
  producer/adoption tests. Full Django: **671 passed**, exit 0.
- Django system check, whitespace and local documentation links pass.
- Migration dry run exits 1 only for the pre-existing EmailAccount.provider choice
  drift (`0008_alter_emailaccount_provider`), independently reproduced before edits;
  no schema migration or new drift. No real tracker database was migrated.
- No fresh legacy `_app` or frontend run is claimed; those trees are unchanged.
  Historical legacy failures below remain separately scoped. Django compatibility
  matching/discovery/posting, identity/lifecycle and retained inspection tests pass.
- SQLite verifies logical convergence/rollback/replay, not PostgreSQL operations.
  Synthetic Gmail fixtures are not live-provider certification. Review relationships,
  frontend, historical reconciliation and production cutover remain pending.

### Gmail mailbox identity — historical verification at `9f66277`, 2026-09-20

The clean committed baseline and later intentional partial tree were inspected on
`django-migration` at `2f0cd1f`; all changes are confined to this bounded slice.
See [Gmail identity review](DJANGO_GMAIL_IDENTITY_REVIEW.md) for the Google sources,
assertion/binding contracts, migration details, resume inventory and exact commands.

- Final focused identity/OAuth/provider/retention/core and populated/historical
  migration checks: **125 passed**, exit 0.
- Affected `email_sync accounts core applications documents postings`: **641 passed**,
  exit 0. Separate full Django run: **641 passed**, exit 0.
- System check and `git diff --check`: clean. Global migration dry run exits 1 solely for the known
  EmailAccount.provider choice AlterField; no unrelated migration was generated.
- Frontend Node: **8 passed**. Legacy: **367 passed, 3 known failures**, 2 warnings;
  unchanged real-path import PermissionErrors and deletion 500-versus-200 failure.
- Populated forward migration preserves every old column/row, including retained
  evidence; principal/binding tables remain empty with no guessed identity backfill.
- SQLite tests cover logical convergence and stale refresh interleavings, not
  PostgreSQL race behavior. Google consent/reconnect/Workspace-domain behavior,
  production storage/workers and cutover are not operationally validated.

### Retained-email foundation — historical verification at `2f0cd1f`, 2026-09-20

Continuation verified the canonical root, `django-migration`, HEAD/local tracking
and live remote at `120d493`, preserving the intentional four-modified/seven-new-file
implementation tree. Review required no code/test correction; this continuation
completed documentation and verification only. See the
[retained-email review](DJANGO_RETAINED_EMAIL_REVIEW.md) for exact commands,
contracts, complete inventory and limitations.

- Focused retention/service/API/concurrency, populated migration and core tests:
  **36 passed**, exit 0. Affected `email_sync accounts core applications documents
  postings`: **606 passed**, exit 0. Full Django: **606 passed**, exit 0.
- System check: no issues, exit 0. Scoped/global migration checks: exit 1 solely
  for the pre-existing EmailAccount.provider choice AlterField; verbose dry run
  confirms no retained-model or unrelated drift. Proposed filename is now
  `0007_alter_emailaccount_provider`; no file was generated.
- Migration plan: exit 0; additive `email_sync.0006_retained_email_foundation`
  follows `email_sync.0005_imapcredential` and `accounts.0001_initial`, and is
  unapplied locally. Populated disposable SQLite preservation passed; no real
  tracker database was migrated.
- Frontend Node: **8 passed**, exit 0. Full legacy: **367 passed, exactly the same
  3 known failures**, 2 warnings, exit 1: two portability real-path PermissionErrors
  and deletion 500-versus-200. Names/signatures match the supplied baseline below.
- Final whitespace check passes. Six modified tracked files and seven new files
  remain uncommitted for review; no dependency/environment changes. Every required
  final run completed; the known exceptions prevent a fully green repository claim.
- Provider adoption, live-provider behavior, PostgreSQL concurrency, frontend/domain
  integration, retained-email derivation, storage/Redis/Celery, backup/restore and
  operational cutover remain unvalidated or unimplemented as specified in §7.

### Historical derivation verification (`120d493`)

The interrupted implementation started from `74f1e91`. This continuation verified
the canonical root, branch and local/tracking HEAD and preserved the intentional
dirty tree; no fresh live-remote check was performed. See [derivation review](DJANGO_DERIVATION_REVIEW.md)
for contracts, exact commands, changed files, results and limitations.

- Focused derivation, populated forward migration, and lifecycle/race tests:
  **43 passed**. Affected `applications documents core postings accounts` regression:
  **331 passed** on the final implementation tree.
- Full Django verification: **573 passed**, exit 0, on the final implementation
  tree. All required continuation runs completed; known exceptions remain below.
- Frontend Node regression: **8 passed**. Full legacy: **367 passed, 3 known
  baseline failures**, with the same two real-path PermissionErrors and deletion
  500-versus-200 signature recorded below. Legacy code and frontend are unchanged.
- System check and scoped drift checks pass. Global drift still reports only
  `email_sync.0006_alter_emailaccount_provider`; no such migration was generated.
- Three additive migrations preserve existing data and mark unreconciled rows
  pending; existing non-null stored dates become `legacy_preserved`. No historical
  status/activity backfill, source timestamp invention, or synthetic history.
- Existing environments reused without dependency changes. Tests use isolated
  SQLite/storage fixtures; no real tracker migration or production validation.

### Historical Trash/Restore verification (`74f1e91`)

Trash/Restore started from clean `3f564ba`; branch, local tracking reference, and
live remote were verified. See [review and verification report](DJANGO_TRASH_RESTORE_REVIEW.md)
for exact commands, API contracts, changed-file inventory and limitations.

- New lifecycle/migration tests: **14 passed** on isolated SQLite fixtures.
- Named Categories regression suites: **20 passed**; identity/creation/posting/
  workspace/cross-cutting suites: **92 passed**; affected Document/dossier suites:
  **30 passed**.
- Final combined Django suites: **284 passed**; full Django suite: **544 passed**.
  System check and scoped migration drift check are clean.
- Frontend: **8 passed**, using the bundled Node executable (no `node` on PATH).
- Legacy preservation suites: **40 passed**; portability suites: **13 passed,
  2 failed**; full legacy suite: **367 passed, 3 failed**, 2 warnings.
  The same two import PermissionErrors and deletion 500-versus-200 failure were
  reproduced from an untouched `git archive 3f564ba` with the same Python environment.
- Scoped migration drift check: clean; global check reports only the existing
  `email_sync` provider-choice drift, reproduced on that untouched baseline.
  No unrelated migration generated or fixed.
- Both missing virtual environments were created and declared dependencies
  installed with explicit user approval. No real tracker database was migrated.
  SQLite tests do **not** validate PostgreSQL concurrency, production storage,
  browser lifecycle workflows, backup/restore, or operational readiness.

### Historical Application Identity verification

The following results describe the earlier identity slice, not fresh lifecycle verification.

Base: `django-migration` at `188351c` — Implement frontend auth and workspace foundation.
At that historical verification point, identity changes and four new migrations
were uncommitted; they subsequently landed at `3a62b58`. No real tracker database
was migrated. The legacy implementation and frontend were unchanged.

| Command (Django from `backend/`, others from root) | Current identity-slice result |
|---|---|
| `venv/bin/python manage.py test applications.tests.test_identity applications.tests.test_creation applications.tests.test_identity_migrations postings.tests.test_views postings.tests.test_services core.tests_workspace_scope` | 76 passed |
| `venv/bin/python manage.py test applications postings core` | 221 passed |
| `venv/bin/python manage.py test` | 523 passed; system check clean |
| `venv/bin/python manage.py check` | No issues |
| `venv/bin/python manage.py makemigrations --check --dry-run applications core postings` | No changes detected, exit 0 |
| `venv/bin/python manage.py makemigrations --check --dry-run` | Exit 1: only known `email_sync` provider-choice drift; no migration generated |
| `venv/bin/python manage.py showmigrations applications core postings --plan` | Exit 0; four new migrations pending on the local database, as intended |
| `node --test tests/frontend/*.test.cjs` | 8 passed |
| `.venv/bin/python -m pytest tests/test_build_index.py tests/test_overrides_store.py tests/test_status_history.py tests/test_job_postings_store.py tests/test_dossier.py` | 56 passed, one known deletion/status-history failure, 2 warnings |
| `.venv/bin/python -m pytest tests/test_export.py tests/test_import_local_folder.py tests/test_overrides_portability.py` | 13 passed, two known import PermissionError failures, 2 warnings |
| `.venv/bin/python -m pytest` | 367 passed, the same 3 baseline failures, 2 warnings |
| `git diff --check` | Passed |

Identity tests exercise both HTTP creation paths, changed-intent rejection, explicit
repeat/replay, challenge expiry/renewal and stale candidates, account/workspace
reauthorization, terminal removal, rollback of initial writes, independent child
rows/document lists, dossier input scoping, and ambiguous email attribution for
identical attempts. Dossier assembly is mocked in the identity isolation test;
the existing dossier/extraction suites remain separate coverage.

Two threaded tests exercise simultaneous same-key requests and competing manual/
posting requests on SQLite. At most one initial effect is permitted. SQLite may
reject one **or both** requests with `503 creation_busy`; explicit reconciliation
using the original keys must yield one effect and (for a competing intent) a
409 review challenge. The first full run exposed an overstrict test assumption
that one concurrent SQLite request must succeed; the test was corrected without
adding automatic retries. These tests do not prove PostgreSQL row-lock, deadlock,
or production concurrency behavior. That validation remains a production/cutover
gate; neither `psycopg` nor `psycopg2` is installed in `backend/venv` (verified
with `importlib.util.find_spec`). No PostgreSQL infrastructure or dependencies were added.

The populated migration test uses a separate temporary SQLite database. It builds
the old checkpoint schema before adding fixture data, then upgrades only forward:
Application PKs, Override/StatusHistory/Document FKs, non-pipeline rows and source
paths survive; UUIDs are distinct and unchanged on repeated backfill; one known
posting link becomes one conversion, while a null link invents none. Historical
conversion timestamp/request identity remain null. It never replays the destructive
historical Document migration over populated data. No real-data upgrade or rollback
has been validated. The conversion migration is deliberately irreversible because
one old pointer cannot represent repeated conversions; operational rollback requires
a separately rehearsed backup/restore plan.

### Historical frontend checkpoint verification (`188351c`)

Base: `django-migration` at `e1785f9` — Implement workspace-scoped Django API.
Frontend foundation was committed and pushed as `188351c`; it created no migrations.

| Command | Historical frontend-checkpoint result |
|---|---|
| `node --test tests/frontend/*.test.cjs` (root) | 8 passed, 0 failed |
| `venv/bin/python manage.py test accounts core` (`backend/`) | 104 passed |
| `venv/bin/python manage.py test` (`backend/`) | 501 passed; system check clean |
| `.venv/bin/python -m pytest` (root) | 367 passed, 3 failed, 2 deprecation warnings |
| `venv/bin/python manage.py check` (`backend/`) | No issues |
| `venv/bin/python manage.py makemigrations --check --dry-run` (`backend/`) | Exit 1: known `email_sync` provider-choice drift, proposes `0006_alter_emailaccount_provider.py`; not generated or fixed |
| `git diff --check` | Passed |

Legacy failures (all reproduced on clean `e1785f9` under the same sandbox):
- `tests/test_overrides_portability.py::test_export_then_import_round_trips_notes_and_status`
- `tests/test_overrides_portability.py::test_export_then_import_round_trips_hub_settings`
- `tests/test_status_history.py::test_deleting_an_application_clears_its_status_history`

The two import tests attempted folder creation under the real
`~/Documents/JobTracker Hub/` location and raised sandbox `PermissionError`.
The deletion test returned HTTP 500 where 200 was expected on both trees; its
underlying cause was not investigated. No broadened access or unrelated fix was
attempted. The full legacy suite is **not green** in this environment, but none of
these three failures is a regression introduced by this slice.

Clean-baseline comparison used `git archive e1785f9` exported into a new temporary
directory (equivalent isolated committed-source checkout), with `.venv` pointing
to the current repository's same Python environment. Original checkout/branch/index
were untouched. The exact three node IDs listed above were passed together to
`.venv/bin/python -m pytest` from the exported root: **3 failed, 2 warnings**, exit 1.
Both import failures reproduced the same real-Documents-path `PermissionError`;
the deletion failure reproduced the same 500-versus-200 assertion. Each is
classified **reproduced on clean e1785f9 / pre-existing or environment-dependent**,
not a slice regression. Temporary paths differed; interpreter, dependencies, user,
fixture behavior and sandbox permissions were shared. No test was rerun with
broadened filesystem permissions.

Isolated browser validation used
`backend/venv/bin/python tests/frontend/serve_foundation.py` (root): a new
TemporaryDirectory for SQLite and media, fixture users Alice/Bob, dedicated cookie
names, and test-only multipart/slow-response endpoints absent from product URLs.
Binding localhost required sandbox escalation; no real tracker database was used.

- `tests/frontend/foundation-browser.html`: 7 passed / 0 failed in actual Safari
  26.6.2, and 7 passed / 0 failed in the in-app Chromium browser (UA Chrome 152).
  Covers anonymous-login CSRF rejection, session login and rotated token, real XHR
  File/text/session/CSRF multipart, XHR CSRF errors, scoped ownership, delayed-read
  invalidation, logout 204, and expired-session 401.
- Product UI: explicit A/B selection in two shared-session tabs; reload and back
  navigation preserve independent selection; create explicitly selects the new
  workspace; logout clears the other tab; Alice→Bob account change clears prior
  context and does not select Bob's sole workspace automatically.
- Separate Safari/Alice and Chromium/Bob sessions concurrently read A and C;
  logging out Safari leaves Bob authenticated after reload.
- Isolated server request-log inspection found zero unexpected/legacy API requests.
  Product traffic was limited to auth, workspace list/create, and scoped insights.
- After final cleanup, a fresh anonymous browser visit shows ordinary login with
  no session-ended alert. Deliberate logout also shows normal login; a previously
  authenticated tab reports session ended after another shared-session tab logs out.
- Node tests cover immutable request snapshots/body serialization, stale success
  and stale authentication errors, read cancellation, XHR error parity, invalid
  routes, empty responses, and no automatic transport retry. Browser race checks
  exercise the transport/context harness, not exhaustive React timing interleavings.

Historical `e1785f9` workspace checkpoint evidence: 370 legacy, 491 full Django,
52 scope/cross-cutting subset, 44 application/documents/dossier subset, and 31
other document/category/posting subset tests passed. Those are historical results,
not substitutes for the current failures. The provider-choice drift was previously
reproduced at clean `8108a9f` and remains unchanged.

Browser checks establish only the bounded foundation on local SQLite. Production
sessions/CSRF, PostgreSQL, storage security, OAuth, workers, import/export, full
product workflows and cutover remain unvalidated.

## 3. Accepted target summary

All ten decisions are approved; full boundaries and consequences live in the
[Decision Record](DJANGO_MIGRATION_DECISIONS.md).

1. One explicitly selected workspace; safe independent tabs.
2. Adapt existing frontend in place; no redesign/build-system replacement.
3. Deterministic document-derived automatic state; manual precedence and real timestamps.
4. Stable application-attempt IDs; repeats allowed, duplicate warnings/idempotency.
5. Named workspace categories separate from sections.
6. Soft-delete Trash, explicit permanent cleanup, previews, portable export.
7. Relevant retained messages, durable evidence, review, provider-independent identity.
8. Authoritative Django contracts and centralized frontend client; one write path.
9. Private administrative onboarding; production PostgreSQL/S3/Redis/Celery.
10. Browser-first cutover; legacy desktop retained only for transition/rollback.

## 4. Current architecture/runtime boundaries

- `_app/`: live legacy FastAPI/Uvicorn, React HTML frontend, filesystem indexing,
  disposable `jobtracker.db`, durable `overrides.db`, and Mail.app integration.
- `_app/domain/` and `_app/infrastructure/`: extracted legacy helpers, not
  repository-root shared layers. Django does not import them.
- `backend/`: independent Django/DRF apps (`accounts`, `core`, `applications`,
  `documents`, `postings`, `email_sync`). Ported helpers are duplicated/adapted;
  fixes do not propagate between architectures automatically.
- `desktop/`: pywebview launcher still starts legacy FastAPI.
- Django has owned workspaces, stable IDs/FKs, admin, file storage abstraction,
  provider integrations, Celery tasks, and Redis configuration. Included synchronous
  core/application/document/posting APIs now require a selected workspace in the
  URL. New retained-email inspection is also workspace-scoped; transitional
  provider APIs remain separate, and old destructive deletion routes are retired.
  Production settings still inherit SQLite.
- Environments: `.venv/` for legacy tests; `backend/venv/` for Django. Manifests:
  `_app/requirements.txt`, `requirements-dev.txt`, `desktop/requirements.txt`,
  and `backend/requirements.txt`.

## 5. Functional migration matrix

All target behavior below is **accepted**. Implementation is assessed against
the audit at `ecd1727`, updated below for Workspace Scoping Core. “Baseline coverage”
means existing component tests, not complete target parity; current counts are in §2.
No newly accepted capability is marked verified merely because it is designed.

| Area | Implemented now | Automated verification | Operational/end-to-end evidence |
|---|---|---|---|
| Auth/workspaces | Session-only product auth, anonymous-login CSRF bootstrap/protection, structured DRF exception codes; owned workspace list/create and explicit route selection in Django entry | 104 accounts/core subset; bounded browser session/tab checks described in §2 | Local foundation validated; broader onboarding/production/cutover pending |
| Frontend/desktop | Existing HTML has explicit Django entry with separate minimal root/client/context; legacy App never mounts in Django mode; desktop remains FastAPI | 8 Node tests; browser harness 7/7 in Safari and Chromium; three legacy suite failures recorded in §2 | Only login → explicit workspace select/create → insights read → logout validated; domain UI pending |
| Applications/overrides | Stable numeric PKs plus workspace portable UUID; shared protected creation, explicit repeat challenges and durable replay | Identity/ownership and duplicate-safe future transition coverage in §2 | Backend-only; duplicate-warning/domain UI pending |
| Derivation/dossier | Canonical per-Application status/activity, manual precedence, source precision, confirmation candidate/modes, duplicate-safe transitions; read-only dossier GET | Current derivation/forward-migration/SQLite coverage in §2 | Historical reconciliation, import provenance, frontend and operations pending |
| Categories | Native stable identity, single revision-protected membership, independent Archive; committed at `3f564ba`; reversible Trash committed at `74f1e91` | Current Category and lifecycle coverage in §2 | Frontend category workflow pending |
| Documents/files | Upload/list/type correction/metadata rename; storage URL; retained Trash and effective parent eligibility | Current Document/lifecycle coverage in §2 | Production storage/previews and frontend integration pending |
| Trash/recovery | Application/Document/Category Trash and Restore, revisions, mutation/admin guards; old deletes retired | Current lifecycle/migration/SQLite race coverage in §2 | Workspace lifecycle, purge, frontend and operational validation deferred |
| Search/dashboards/settings | Included reads, counts, search, section adapters, merges, and settings scoped to URL workspace; search parity and Ghosted still pending | Scoped isolation coverage; broader target parity pending | Frontend integration pending |
| Provider connections | Gmail/Outlook/IMAP connect/sync/disconnect; encrypted credentials | Baseline provider/view coverage, mocked external seams | Historical Gmail OAuth/live-sync checkpoint; complete target flows unvalidated; Outlook/IMAP live validation unestablished |
| Sync/jobs | Gmail per-message retention plus transitional match/discovery/thread projection; inline single sync, queued bulk/Beat | Gmail adoption/replay and existing sync/task coverage; not real-broker proof | Real Redis/worker/Beat operation unestablished |
| Retained messages/review | Protected source/observation models, verified Gmail lineage and native-ID producer adoption; scoped review inspection, explicit attachment, independent disposition and atomic create-Application orchestration with durable results | Retention, Gmail adoption, attachment/disposition/creation APIs, migration preservation and SQLite logical concurrency coverage in §2 | Other-provider adoption, broader review actions, frontend and operational validation pending |
| Postings | Integer PK plus immutable Workspace-scoped portable UUID; existing extractor/ingestion and list/save/dismiss/restore/apply APIs; explicit retained-text extraction production with validated historical replay, operator batch extraction execution and source-scoped read-only extraction evidence inspection, plus a workspace-scoped read-only retained extraction evidence HTTP API; retained extraction/items and corrections, PostingSource mapping/corrections, item interpretation, posting-level arbitration, descriptor projection, canonical allocation, stateless review orchestration and bounded advisory candidate discovery | Identity/migration/replay and authority-boundary coverage in §2; latest API 18, retained inspection 22, combined focused 262, postings 615 and full Django 1,332 passed | Sync does not produce canonical postings; automatic retained-to-canonical workflows, broader canonical consumers, provider/sync adoption, frontend/browser integration, broader retained-workflow APIs, PostgreSQL and production/operational validation remain pending |
| Import/export | No Django legacy importer or portable export/restore | Unimplemented/unverified | Reconciliation/cutover pending |
| Production | Partial settings/storage/task scaffolding; SQLite inherited, development fallbacks remain | Suite success is not deployment verification | PostgreSQL/storage/jobs/backup/restore/rollback pending |

## 6. Known parity gaps and blockers

- Retained-text extraction production, explicit operator batch execution, source-level
  evidence inspection and its workspace-scoped read-only HTTP adapter are complete. A stable
  evidence HTTP contract exists; browser/frontend integration and broader retained-workflow
  APIs remain separately scoped gaps. The batch command, reader and HTTP adapter are not
  the provider/sync adoption mechanism. That adoption requires
  separate decisions on recurring extraction-operation identity, source admission,
  selector ownership where applicable and failure/retry handling, plus PostgreSQL validation
  before broader provider/write automation. The reader and HTTP API do not resolve these
  requirements; the completed read endpoint does not establish PostgreSQL validation.
  Provider/sync adoption and automatic retained-to-canonical workflows remain unimplemented
  and require separate
  planning and authorization. Sync does not currently produce canonical JobPosting rows;
  explicit retained extraction is distinct from legacy direct canonical ingestion, and
  `ingest_extracted_postings` is not designated as the adoption path.
- Review Gmail producer adoption; separately authorize other-provider adoption,
  account listing, discovery preview/attach/accept/dismiss/restore/sender
  classification, and evidence/backfill.
- Per-Application derivation is committed at `120d493`. Historical rows are
  intentionally not bulk-reconciled; missing source facts remain unknown. Future
  importer/cutover work must supply verified provenance and preserve history.
- Add Ghosted choices/metrics/UI parity. This main-branch change exists only
  in the legacy implementation.
- Named Categories and Application/Document/Category Trash are now implemented
  in the backend. Their frontend integration, Workspace lifecycle and confirmed
  permanent cleanup remain pending.
- Complete remaining workspace integration for email/jobs and the frontend;
  included synchronous core APIs are scoped. Adapt remaining payloads/errors and
  search semantics deliberately. Preserve PDF/text/DOCX browser previews.
- Build importer/exporter and validate restoration. Existing documents migration
  `0002` deletes/recreates DocumentOverride assuming no real data; fresh-database
  tests do not establish safe upgrades of populated intermediate databases.
- Legacy Finding 9 lock mitigations are present, but its field root cause is
  unresolved; do not turn that unrelated investigation into migration scope.

## 7. Current implementation phase

Decisions 1–10 and foundational Topics 1–9, including final refinements, are
accepted. **Workspace Scoping Core — Backend Only is implemented.** A reusable
request mixin resolves authenticated workspace ownership, rejects conflicting
workspace/owner input, and scopes included object lookups and nested references.
Included application/document/posting APIs and core reads/settings use URL context;
bulk overrides validate all targets before writing. Converted owner-wide routes
are removed, with no redirects or fallback writes. DRF format-suffix variants are
preserved for converted router routes and the existing deletion-only routes;
explicit category/core adapters gain no new suffix behavior.

At the Workspace Scoping checkpoint, deletion remained legacy behavior (superseded
by the current Trash slice below). No Trash, schema,
email/account/auth infrastructure, frontend, or task changes were part of that backend-only slice.
This is not completion of the broader workspace contract or historical phases.
Evidence regeneration replacement versus supersession still requires an explicit
decision before that behavior is implemented; other remaining implementation and
operational details are listed in Foundations.

### Frontend API Foundation — committed and pushed at `188351c`

The explicit Django same-origin entry serves the existing HTML and allowlisted
public assets. Its minimal root provides login, workspace list/create, hash-route
selection, one scoped insights read, and logout. It never mounts the legacy App,
loads its sensitive localStorage cache, or invokes legacy/domain screens. Existing
FastAPI entry behavior and Safari upload helper remain in place.

The client uses session cookies and CSRF, handles empty 204 and structured errors,
captures actor/workspace/navigation generation, cancels obsolete reads or rejects
late results, and never retries/replays mutations. XHR multipart has equivalent
CSRF/context/error handling without forcing Content-Type. Selection has no shared
persistent storage; focus/session-change messages revalidate identity and clear old
context. No singleton selection, destructive workspace UI, generic legacy URL
adapter, domain/schema migration, upload workflow, jobs, or cutover is included.

Auth changes implement `401 authentication_required`, `403 csrf_failed`, genuine
`403 permission_denied`, scoped `404 not_found`, and `400 validation_error` for
DRF exception paths. Invalid credentials have their own code. Existing successful
representations remain unchanged. This does not normalize every historical explicit
error Response or implement future duplicate/operation contracts.

Plan differences: insights replaced settings GET because settings lazily writes a
row; an additional isolated browser-server helper makes the harness reproducible.
Final cleanup distinguishes a fresh anonymous visit from a lost authenticated
session and removes the stray import from config/urls.py's introductory docstring.
All commands in §2 were rerun after these two changes. Browser evidence and
clean-baseline regression comparison are recorded above. Known environment/baseline
failures prevent a fully green suite claim; they do not indicate a slice regression.
This frontend checkpoint was committed and pushed as `188351c`.

### Application Identity & Repeated Attempts — committed at `3a62b58`

`applications.0002_application_portable_identity` adds a nullable UUID, backfills
one UUID per historical row, then enforces a generated, non-null UUID unique within
Workspace. `source_relpath` retains its values as blank-allowed provenance. Numeric
PKs remain normal API lookups. Normal create/override APIs reject identity assignment;
Application admin add is disabled and identity fields are read-only. Model save also
rejects identity/workspace changes; privileged bulk SQL/ORM writes are not a supported
identity-editing workflow.

`core.0003_applicationrequestintent` stores only compact actor/workspace/key,
versioned semantic digest, pending challenge and linked/terminal result identity.
No raw request bodies or candidate descriptions are retained. Completed key mappings
remain until workspace deletion; there is no detailed replay cache or background
retention job in this slice. Both manual create and posting apply call
`applications/creation.py`, under one workspace transaction authority. Initial
Application, Override, StatusHistory, intent completion and conversion commit together.
Arbitrary IntegrityError is not translated into a duplicate-company warning.

Both existing creation URLs now require `Idempotency-Key` (16–128 opaque ASCII
letters/digits/underscore/hyphen; clients must generate a random key). Semantic digest
v1 includes route kind/target and validated supplied fields, preserving omission.
Same key/intent resolves the current effect with 200; changed intent returns
`409 idempotency_key_reused`. First allocation returns 201. Removed results return
only `state: removed` and portable identity; retries never recreate them.

Normalized company/role matches warn across the authorized workspace, including
archived attempts. `409 new_attempt_confirmation_required` supplies scoped numeric
candidate IDs/state, a token and expiry. Explicit continuation resubmits the same
URL/key/fields plus `challenge`; the token binds actor/workspace/intent and the visible
candidate/posting/conversion revision. Expiry defaults to 900 seconds, configurable
with `APPLICATION_CHALLENGE_TTL_SECONDS`. Invalid, expired and stale tokens get distinct
409 codes. Re-submit without a token to renew review; no `force` flag or automatic
mutation retry exists. Consuming the token creates a separate attempt once; replay
then resolves that result.

`postings.0002_posting_application_conversions` creates durable conversion rows,
backfills only non-null known links (cross-workspace links fail migration explicitly),
and removes the old pointer. New conversions link one request intent, record actual
conversion time and retain portable result identity when their Application is deleted.
A new request key alone does not authorize another conversion. The list serializer
adds conversion states and retains `applied_application` only as a read projection
of the latest surviving conversion; remove that projection when the posting UI
adopts conversion representations, before legacy retirement. No pointer dual-write
or ordinary admin allocation bypass remains.

Final review found and closed an admin reparenting bypass: existing postings now
keep both `workspace` and `account` read-only in admin, and model saves reject changes
to either persisted FK (including an existing PK supplied on a fresh instance).
New-posting ownership setup and unrelated metadata edits remain available. No
conversion history or historical workspace IDs are rewritten. Three regression
tests cover terminal conversion followed by attempted model/admin reparenting,
forged admin ownership input with allowed metadata edits, new creation and fixed
account identity. The original workspace still requires a new-attempt challenge;
the destination workspace returns 404. Privileged bulk ORM/SQL writes bypass model
save hooks and are not a supported reparenting workflow; the historical-corruption
scope test uses such a write explicitly. This safeguard adds no migration.
The review's non-ASCII challenge validation fix is retained and tested: malformed
non-ASCII tokens return 400 instead of raising TypeError.

Finally, `applications.0003_allow_repeated_attempts`, dependent on conversion setup,
drops descriptive uniqueness. Deploy the protected code with these migrations;
do not run old allocators after removing the constraint. No Categories, Trash,
timestamp/derivation/history parity, retained-message schema, importer/exporter,
discovery acceptance, frontend CRUD, upload/storage or worker framework was added.
The permanent-deletion routes from that checkpoint are now retired by the Trash slice below.

Plan concretizations: continuation uses the existing creation URLs, not an extra
endpoint; compact synchronous intent state lives in one model; unsafe admin creation
is disabled; SQLite contention has a bounded 503 response. These stay within the
approved backend-only boundary. PostgreSQL and full domain/browser workflows remain
unvalidated.

### Named Categories — committed and pushed at `3f564ba`

Native Category IDs/portable IDs, empty containers, independent archive state,
single revision-protected membership, creation replay and conservative synthetic
backfill are implemented. Sections remain classifications. Category membership
never owns Applications. The supplied historical 245/245 result is distinct from
the fresh regression verification in §2.

### Backend Trash & Restore — committed and pushed at `74f1e91`

Application, Document and Category gain nullable `trashed_at` and nonnegative
`lifecycle_revision`, defaulting to live/revision 0 without invented history.
`applications.0005_retained_lifecycle` precedes `documents.0005_retained_lifecycle`;
the latter also follows the committed Category backfill. Ownership FKs use PROTECT
for these resources, preventing incidental ancestor deletion. Identity, membership,
Archive, overrides/history, extraction provenance and file references survive.

`core.lifecycle.set_trash` owns desired-state transitions, with workspace ownership,
expected revision, current-state no-ops and parent-first Document restoration.
The existing workspace transaction gate serializes transitions, membership and
ordinary included mutations; resource locking follows Category → Application →
Document where applicable. Real transitions increment only lifecycle revision;
stale requests return 409. No-ops do not churn timestamps or revisions.

Ordinary reads use centralized `.live()` eligibility. Application Trash makes its
Documents effectively unavailable without changing their direct state. Restoring
it leaves directly trashed children excluded. Document restore under a trashed
Application returns `409 parent_trashed`. Category Trash preserves memberships and
never trashes, archives or changes member Applications. Live members can leave a
trashed Category; new assignments into one are blocked.

Workspace-scoped POST `applications|documents|categories/{id}/trash|restore/`
accepts `expected_revision`. Detail inspection and explicit `show_trashed=true`
Application/Category/child-Document listing retain authorized recovery access.
Ordinary metadata mutation is blocked while directly/effectively trashed. Old
unscoped Application single/bulk and Document delete routes return 410; remove
these retirement responses before legacy retirement. Admin cannot hard-delete the
three resources, mutate trashed Application/Document records, or overwrite newer
lifecycle/membership revisions from stale forms. Document creation and standalone
DocumentOverride writes use product APIs instead of admin bypasses.

Creation/duplicate/replay identity still includes retained attempts. Completed
Application, posting-conversion and Category creation requests resolve the original
current record without cloning, restoring or recreating cleared membership.

**Historical limitation at `74f1e91`:** the lifecycle slice intentionally deferred
status/activity recalculation and retained the old dossier GET autofill behavior.
The derivation slice below now handles future evidence mutations and makes GETs
read-only. Untouched historical Applications remain unreconciled; this is still
not whole-database or final product parity.

No permanent purge, physical file deletion, Workspace Trash, frontend changes,
automatic expiration, provider/background work or unrelated migration fixes are
implemented. PostgreSQL concurrency and operational recovery remain unvalidated.

### Backend Deterministic Application Derivation — committed at `120d493`

`applications.derivation` applies effective Document type priority
`rejected > interviewing > applied > drafted > unknown`; non-pipeline is `n/a`.
Manual status remains authoritative, including existing Ghosted values. Explicit
upload, type/rename, direct Trash/Restore, and manual reset paths use the same
workspace-gated transaction and Application-before-Document locks. Creation replay
remains identity-preserving. Category operations never trigger derivation.

Parent Trash preserves its business snapshot. A direct child change while the
parent is trashed marks reconciliation needed; Restore reconciles that actual
change once. A parent-only cycle produces no business transition. Same inputs do
not churn derived metadata, history, activity, or lifecycle/membership revisions.

Additive `accounts.0002_deterministic_derivation`,
`applications.0006_deterministic_derivation`, and
`documents.0006_deterministic_derivation` retain source-event/date precision,
verified legacy mtime, genuine new-upload fallback, automatic confirmation candidate,
manual/legacy/suppressed date mode, and fingerprint/completeness metadata.
Calendar timezone defaults explicitly to UTC; configuration UI is deferred.
Dates never become invented midnight instants. Extraction claims are content-only;
Document arrival/source facts are separate. Conflicting confirmation dates have no
arbitrary winner. Attention uses calendar days and the existing reset → effective
application date → last evidence precedence and due-first ordering.

Dossier GET does not extract, write caches, or autofill overrides. POST
`/api/workspaces/{workspace_id}/applications/{id}/derive/` explicitly reconciles one
live Application without fabricating historical transitions. Ordinary evidence
mutations record real effective changes once, using recorded-now history timestamps
rather than source dates. Existing duplicate history is preserved. Missing, failed,
and conflicting evidence is reported; no cross-workspace evidence is admitted.

### Backend Retained Email Source Identity and Content Foundation — committed at `2f0cd1f`

`MailboxLineage`, `RetainedMessage`, `RetentionKey` and `RetainedObservation` separate
established mailbox lineage, strong source identity and exact observation retry.
Workspace-owned portable identities and complete source namespaces are unique;
weak IDs/content hashes cannot merge messages. Changed-key and source-content
conflicts preserve canonical content and candidate observations, with sticky
ineligibility. Incomplete identity remains inspectable and unresolved.

The explicit internal service validates ownership/references and bounded content,
then commits under the existing Workspace gate. It performs no provider/network
work. Default UTF-8 text/HTML limits are 128/256 KiB, with explicit truncation;
observations over 2 MiB are rejected. Source time precision/offset/provenance remains
separate from observation and retention times. JSON-only read APIs omit original
HTML and expose authorized state/content without writes. Admin is read-only.

All new FKs use PROTECT, with no EmailAccount/credential or workflow ownership link;
account disconnect/deletion preserves retained data. Additive
`email_sync.0006_retained_email_foundation` follows `email_sync.0005_imapcredential`
and `accounts.0001_initial`, creates only four tables/five constraints, and performs
no historical backfill or existing-field alteration. See the
[retained-email review](DJANGO_RETAINED_EMAIL_REVIEW.md) for contracts and evidence.

Gmail producer adoption is described below; other providers remain unadopted. No
review actions, posting ingestion, generated Documents, derivation hooks, frontend
integration, purge, import/export,
workers or historical reconstruction are included. PostgreSQL and operational
validation remain open; SQLite race tests are not production concurrency proof.

### Gmail Mailbox Identity and Durable Lineage Foundation — committed at `9f66277`

New Gmail authorization requests only the approved `openid email gmail.readonly`
scopes (the last uses its full Google scope URI). The callback verifies the exchange
ID token through the installed Google verifier, checks issuer/audience/signature,
subject/times, optional authorized presenter and access-token hash binding, then
uses Google OIDC `sub` as opaque account identity. Email remains metadata.

Additive `email_sync.0007_gmail_mailbox_identity` creates MailboxPrincipal and
AccountMailboxBinding only. The existing retention authority resolves unique
workspace/provider/namespace/principal identity to MailboxLineage. Same-principal
reconnect or account recreation resolves the same lineage; changed email can update
ordinary account metadata without changing lineage. Conflicting principals, ambiguous
legacy accounts and address collisions return a deterministic conflict without merging
or overwriting credentials/history. New bindings require fresh offline authorization.

Legacy accounts/lineages are preserved unverified until prospective authorization;
no historical identity or message backfill runs. Empty stored refresh scopes retain
the old read-only fallback, and refresh never establishes identity. Stale refresh
results cannot overwrite a replacement grant or recreate disconnected credentials.
Workspace-gated identity/account/credential writes are atomic; lineage/principal and
retained evidence survive disconnect and account deletion. New identity admin is
read-only, and bound account workspace/provider cannot be changed by ordinary saves.

That identity slice left provider adoption for the next bounded slice below. Its
retained read APIs and downstream review/posting/evidence workflows are unchanged;
Outlook/IMAP identity is not adopted. See the
[identity review](DJANGO_GMAIL_IDENTITY_REVIEW.md) for historical limits/evidence.

### Gmail Provider Adoption into Retained-Source Authority — committed at `fcbfcf3`

Newly fetched, relevance-qualified Gmail messages now call `retain_observation`
using native Gmail message ID under verified workspace-owned durable MailboxLineage.
The provider DTO keeps native ID, RFC Message-ID, provider thread metadata and
source/observation timestamps separate. Missing RFC ID no longer discards canonical
evidence. `threadId` is conversation metadata only; equal RFC/thread values never
merge different native sources.

Binding/principal/provider/workspace are checked before fetch and revalidated during
persistence; a changed binding requires another fetch. Missing verified lineage or
native identity produces an unresolved observation, with no email/header identity
guess. Same-principal reconnect and account recreation reuse the durable namespace.

Existing relevance order and search semantics are preserved. Retention happens
before legacy RFC duplicate suppression. Selected repeated headers, structured
addresses and available inline plain/HTML MIME bodies pass through existing limits
and truncation. Raw MIME, file parts and nested attachment bodies are not retained.
InternalDate has explicit Gmail provenance; missing/invalid values remain unknown,
with no RFC Date fallback. Header-sent precision, observation and retention stay
separate; Application activity/derivation is untouched.

Gmail fetch/decode/classification is outside persistence transactions. One relevant
message's retention and compatibility projection commit together under the existing
Workspace gate. Fresh fetches produce new observations against one native source;
reusing an attempt replays the original observation. Conflicts preserve variants and
canonical content and suppress new projections. Unresolved cases preserve existing
legacy compatibility behavior without establishing canonical downstream authority.
Earlier committed units survive a later failure, but the sync cursor does not advance;
retry is safe. Other providers keep their existing transaction behavior.

Matches/discoveries/posting discoveries remain one transitional RFC-based projection
path, preserving dismissed state and replay behavior. Missing RFC ID can have no
legacy projection, and two native sources with one RFC ID can have only one legacy
projection. Replace these consumers with retained-backed relationships before legacy
retirement. That adoption slice included no schema migration, historical backfill/
reconciliation, review mutations, ApplicationMessage/PostingSource, JobPosting ingestion,
generated evidence, Outlook/IMAP adoption or frontend work. Retained inspection/admin
remain read-only. See the
[adoption review](DJANGO_GMAIL_ADOPTION_REVIEW.md).

### Backend ApplicationMessage Relationship Foundation — committed `b5c1faf`

`RetainedMessage → ApplicationMessage → specific Application` is now the canonical
explicit relationship path. Immutable runtime/portable link identities, original
creation time and bounded manual origin preserve provenance. Database uniqueness per
Application/source supports many-to-many links and distinct repeated attempts.

One atomic service uses the Workspace gate, then Application and retained-message
locks, validates same-workspace ownership and source eligibility, rejects direct
Application Trash or source conflict, and resolves/creates the pair. POST
`applications/{id}/messages/` under the explicit workspace route takes only
`retained_message_id`: 201 first creation, 200 eligible replay without provenance or
revision churn. GET provides paginated live-Application inspection with existing
retained summaries. No provider calls, alternate writer or request-intent model.

Trash preserves links/sources and Restore exposes the same relationships. Ordinary
model edits/deletion are blocked, ancestor FKs PROTECT, and admin is read-only.
No independent relationship Trash, detach, review decisions or permanent purge.
Attachment does not modify Application status/activity/history, Documents, retained
source/observation identity, legacy AccountMatch/Discovery (including posting kind),
thread hints or postings. Gmail compatibility projection cannot allocate links.

No inference/backfill, generated evidence, PostingSource, JobPosting ingestion,
provider changes or frontend work is included. Legacy consumers remain temporary
compatibility and must be replaced before retirement. See the
[ApplicationMessage review](DJANGO_APPLICATION_MESSAGE_REVIEW.md).

### Retained Application Review Identity & Candidate Snapshot Foundation — committed at `eedf57a`

`RetainedMessage → RetainedApplicationReview → RetainedApplicationReviewCandidate`
separates review identity from source identity and canonical ApplicationMessage links.
One workspace-owned portable review identity per source retains the first zero/one/many
candidate snapshot and originating observation. Candidates preserve specific attempt
portable IDs, with nullable current Application references; replay never replaces the
set when matching facts change. Trash/Restore preserves provenance and only changes
current target availability. Source conflicts remain inspectable and ineligible.

One internal atomic ensure service validates Workspace/source/observation/candidates,
using Workspace → source → review locks, without Application locks. Gmail invokes it
after retention and before legacy projection/RFC suppression for match, ambiguous and
unmatched Application classifications. Posting and unresolved observations do not enter
this domain. Legacy matching/classification/projections and frontend consumers remain.

The foundation added workspace-scoped `application-reviews/` list/detail JSON inspection;
source content stays in existing retained inspection. Detail shows candidates' current
availability and existing relationships. Admin is read-only. Additive Application
migration `0008_retained_application_review` creates no historical reviews/candidates.
The foundation added no review decisions, attachment, detach, evidence, posting-source
ingestion, provider expansion, permanent purge or frontend integration. Explicit
attachment is now added below. See the
[retained Application review](DJANGO_RETAINED_APPLICATION_REVIEW.md) for full contracts,
verification, changed files and limitations. The queue does not cover all legacy history.

### Retained Review Attach to Existing Application — committed at `4d54582`

`POST /api/workspaces/{workspace_id}/application-reviews/{id}/attach/` accepts only
`{"application_id": positive_integer}`. Scoped immutable review provenance supplies
the canonical source ID; `attach_message()` remains the sole relationship writer and
creation/lock authority. At the attachment checkpoint there was no outer
transaction. Disposition admission now holds the Workspace gate around delegation,
as described below, without extra review/source locks.
Creation returns 201; eligible existing-pair replay returns 200. Trash, source conflict,
ownership, strict payload and contention behavior follow the canonical service.

Zero/one/many suggestions require one explicit target per request; eligible targets
outside the initial snapshot and multiple distinct attempts are supported. Initial
classification, candidate membership/portable identities and timestamps never change.
List/detail remain inclusive and derive `attachment_status` and `relationship_count`
from valid scoped ApplicationMessage links, including trashed targets. Distinct counts
avoid candidate/link join multiplication; detail links expose `live`/`trashed`
availability. Existing direct relationship writes are immediately reflected.

No schema/data migration, historical scan, legacy write, provider change, evidence,
derivation or frontend change. No terminal acceptance or stored attachment state.
Dismiss/restore was outside that attachment slice and is now implemented below. See the
[attachment review report](DJANGO_RETAINED_REVIEW_ATTACH_REVIEW.md) for verification,
transaction reasoning and operational limits.

### Retained Review Disposition — committed at `5e25093`

`RetainedApplicationReviewDisposition` is a mutable one-to-one sidecar using review
identity, nullable `dismissed_at` and a nonnegative revision. No disposition row means
active/revision 0. The first actual dismissal allocates revision 1; restore clears the
timestamp while keeping the row. Current-revision no-ops do not write; stale revision
rejects before no-op detection. Ordinary deletion/reparenting and admin mutation are
blocked. One additive schema-only Application `0009` has no historical backfill.

`POST .../application-reviews/{id}/dismiss/` and `/restore/` accept exactly
`{"expected_revision": nonnegative_integer}` and return identity plus nested disposition.
The scoped desired-state service owns both transitions; conflict does not prevent
review dismissal/restoration. List/detail expose state/revision/timestamp and remain
inclusive. No disposition filter, handled state, candidate decision or generalized Trash.

Review attachment holds the Workspace gate before disposition admission through
unchanged canonical `attach_message()` delegation. Dismissed new pairs return
`409 review_dismissed`; existing pairs still recheck canonical Trash/conflict eligibility.
The direct ApplicationMessage API remains independent. No relationship or provenance
changes occur during disposition transitions, and attachment never changes disposition.
Application Trash/Restore remains independent. Historical Discovery is never inferred
or rewritten. See the [disposition review report](DJANGO_RETAINED_REVIEW_DISPOSITION_REVIEW.md)
for transaction reasoning, actual verification and operational limitations.

### Retained Review Create Application — committed at `ab1cb0e`

`POST .../application-reviews/{id}/create-application/` uses an Idempotency-Key and
explicit company/optional role, status, Category and candidate provenance. It creates
an Application through the existing allocator, attaches via `attach_message()`, inserts
an immutable `RetainedReviewCreationResult`, then completes RequestIntent in one atomic
Workspace-gated transaction. Manual/posting request digests and challenge semantics
remain unchanged. New result schema is additive Application `0010`, without backfill.

New requests require confirmation for prior results, existing source relationships or
ordinary duplicates. A fresh key alone cannot bypass repeat protection; confirmed work
always creates a new Application. Completed replay reads its durable result without
allocation/attachment, including after dismissal, conflict or Application Trash. New
work rejects dismissed reviews and conflicted sources. Missing completed result fails
closed. Review detail adds 50-result cursor pages; list/filter behavior is unchanged.

Versioned snapshots preserve explicit semantic inputs only. No candidate label copying,
automatic disposition, email activity/status/date inference, evidence generation,
PostingSource, provider, frontend or historical reconciliation work. Protected references
leave future purge/terminal compaction to a separately approved lifecycle slice.

### JobPosting Portable Identity — committed at 6863f277

JobPosting retains integer PK/routes and gains immutable Workspace-scoped portable UUID.
Serializer/admin expose it read-only; conversion UUID fields still identify Applications.
The existing ingestion dedupe/URL/positional rules and descriptor updates remain transitional,
not canonical posting identity. Workspace/account FK deletion behavior is unchanged:
account cascade remains transitional and requires separate ownership work. No source-item,
PostingSource, retained-source ingestion, evidence, frontend or reconciliation work is included.
See the [posting identity review](DJANGO_POSTING_IDENTITY_REVIEW.md) for exact migration,
preservation, reverse limitations and verification evidence.

## 8. Next recommended implementation actions

1. Retained-text extraction production, explicit operator batch execution, source-scoped read-only evidence inspection and its workspace-scoped read-only HTTP API are complete through `56214508cd646650863b23628e58c10b80fea010`, alongside the existing explicit retained-posting authorities. The next substantive migration slice has not been selected and has not been authorized. Provider/sync adoption, automatic canonical workflows, broader canonical consumers, broader retained-workflow APIs, browser/frontend integration, PostgreSQL and remaining operational work require separate planning and authorization. Prior local database provenance remains unresolved.
2. Resolve the legacy verification blockers under separately approved scope before declaring a fully green checkpoint.
3. Separately scope further review actions and future filtering/queue UX, along with broader email/job and frontend work.
4. Plan provenance-aware historical reconciliation with importer/cutover work; do not silently backfill current records.
5. Connect core browser workflows, then retained email/review/postings/evidence.
6. Develop import/export alongside models; rehearse representative workspaces.
7. Validate production operations and cutover gates before retiring legacy.

Use the [Decision Record sequence](DJANGO_MIGRATION_DECISIONS.md#recommended-implementation-sequence)
for detail. Future work remains scoped to the user's authorized task.

## 9. Import/export and cutover readiness

**Not ready.** No Django importer/exporter or accepted-model reconciliation
implementation exists. Preserve source data, distinct attempts/categories,
legacy timestamps, manual state, evidence PDFs, and provenance. Missing source
email must remain explicitly unavailable. Exports exclude all credentials.

Before cutover, demonstrate repeatable import/reconciliation and export/restore,
preserve rollback artifacts, and explicitly transition workspace write authority.
No local/hosted synchronization or silent installation repointing is implied.

## 10. Production validation and retirement gates

All remain open unless supported by new, recorded evidence:
- Same-origin product sessions/CSRF, administrative onboarding/recovery, isolation.
- PostgreSQL, private storage, Redis, separate web/worker/Beat, safe required secrets.
- Full enabled-provider flows, including retained evidence, retries, and disconnect.
- Browser acceptance for core workflows, imports/exports, previews, and Trash.
- Coordinated database/content backup and tested restoration.
- Documented/logged deployment, migrations, jobs, storage, and rollback operations.
- Successful reconciliation, end-to-end acceptance, and rollback readiness before
  desktop retirement; no deletion/alteration of local source data without approval.

## 11. Historical checkpoint context

At `ecd1727`, main is integrated and inspected legacy fixes are preserved. Three
repeated legacy commits are patch-equivalent; no inspected evidence of merge
loss. Ghosted and override-lock mitigations landed in legacy, not Django;
backend files were unchanged by those merges.

2026-09-11: user approved audit and Decisions 1–10; created this maintained
checkpoint, the durable Decision Record, and root AGENTS.md only. Historical
handoffs remain unchanged and may still contain stale counts, ZIP workflows,
commit references, and incorrect completion claims. No application changes or
new operational validation are represented by this checkpoint.

2026-09-12: consolidated accepted Topics 1–9 in Foundations and narrowly updated
Decisions, Status, and AGENTS authority/navigation at `8108a9f`. That consolidation
was documentation only and added no fresh test or operational evidence.

Workspace Scoping Core now implements the backend-only subset described in §7,
with fresh automated verification in §2. All operational cutover/retirement gates
remain open.
