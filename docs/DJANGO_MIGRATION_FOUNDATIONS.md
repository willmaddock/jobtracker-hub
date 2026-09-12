# Django Migration Foundations

## 1. Purpose and authority

Status: Topics 1–9 accepted with the user's final refinements; consolidated
2026-09-12. This is an authoritative design specification, not a claim of
implementation or operational readiness. Application code may not yet satisfy it.

Source-of-truth responsibilities, in order:

1. Code and migrations establish what is actually implemented.
2. [Decisions](DJANGO_MIGRATION_DECISIONS.md) owns accepted product and architecture boundaries.
3. This document owns accepted detailed foundational implementation contracts within those boundaries.
4. [Status](DJANGO_MIGRATION_STATUS.md) owns the maintained implementation, verification, and readiness checkpoint.
5. [Migration plan](DJANGO_MIGRATION_PLAN.md), historical handoffs, and troubleshooting notes supply supporting context only, subordinate where stale or conflicting.

If Foundations appears to contradict Decisions, surface the conflict for review;
do not silently rewrite either side. Decisions 1–10 remain authoritative.
Implementation details may vary where the contracts explicitly leave flexibility.

The documentation checkpoint entering this consolidation is `a96cdf9`.
The supplied tested implementation baseline is `ecd1727`. No implementation,
real-data backfill, or operational validation is authorized by documenting this
design. Implementation requires separate explicit authorization.

## 2. Topic 1 — Lifecycle ownership, Trash, restore, purge

### Ownership and direct state

Workspace is the lifecycle root. Application owns its Documents and exclusive
metadata, including overrides and status history. Document owns its override and
exclusive derived artifacts. Shared extraction caches remain workspace-owned and
are retained while any surviving/restorable Document requires them.

Archive controls visibility/organization; Trash is reversible deletion; business
status, manual overrides, and review dismissal are separate concepts. Store direct
Trash state and derive effective Trash through true containment only. Preserve
prior child state without recursively rewriting descendants. A parent restore
must not restore children independently trashed earlier.

Category membership is organizational, not Application containment. Category
Trash hides its organizational presentation, not member Applications. Category
purge removes membership rows, not Applications or Documents. Category restore
preserves member Trash/archive/status. A live Application may explicitly leave or
be reassigned away from a trashed Category without restoring it; adding members
into an effectively trashed Category and Category-context bulk mutation are
blocked. Normal metadata mutation of that trashed Category remains blocked.

Workspace owns RetainedMessages. Application relationships do not transfer source
ownership. Application purge removes its owned evidence Documents and relationship
rows, not shared retained sources. Surviving references, including those from
restorable trashed objects, block direct source purge. Removing the last reference
does not automatically delete the source. Workspace purge can remove all its data.

### Lifecycle services

Dedicated services own Trash, restore, and purge. Ordinary Trash does not require
Archive and never physically deletes stored content. Permanent deletion requires
Trash plus a separate explicit confirmation; Workspace purge needs stronger
confirmation. There is no automatic user Trash expiration.

Restore requires accessible containment ancestors first. Trash permits authorized
inspection, not ordinary mutation. Restore is unavailable once purge begins.
Direct state, lifecycle revision, and purge-operation association must distinguish
reversible Trash from irreversible cleanup. No-op state setters do not churn
revisions. Parent purge includes all truly owned descendants, including those
independently trashed, but never expands ownership through generic references.

Purge uses a durable PurgeOperation and frozen cleanup manifest. Preview and
confirmation bind target, revision, and scope. Revalidate before irreversible
work; a changed scope needs renewed confirmation. Once begun, never silently add
targets. Track storage cleanup durably, retry idempotently, and keep incomplete or
uncertain cleanup visible. Do not report success until required files and records
are removed. Do not rely on signals or Celery delivery as the sole cleanup authority.

FK direction must resist incidental hard deletion: protect User→Workspace and
primary lifecycle boundaries; use cascades for exclusively owned metadata and
SET_NULL for meaningful provenance references where appropriate. Exact FK changes
must follow typed ownership. Disable default admin hard-delete bypasses; privileged
writes still use lifecycle services. No generic Trash UI is implied for every
model: Posting/Discovery dismiss/restore remains review state, and independent
source deletion actions require their own approved workflow.

Workspace Trash suspends ordinary background/provider work while preserving data
and credentials. Restore does not automatically restart email access; explicit
resume is required. Explicit disconnect removes credentials. Maintenance barriers,
Trash, and purge are distinct (Topics 6 and 9).

### Files

Each Document owns its governed storage object. Rename changes the visible
filename, not necessarily the storage key; previews/downloads/exports use the
current visible name. Preserve PDF, text, and web-rendered DOCX viewing and browser
download/open behavior. No desktop launch assumption. Physical cleanup belongs to
permanent deletion; orphan objects are not a recovery mechanism.

## 3. Topic 2 — Application identity and reconciliation

Application PK remains normal Django/API identity; preserve existing PK/FKs.
Add immutable `portable_id`, generated once and unique within Workspace, for
export/reconciliation. Legitimate same-record restore preserves it. A conflict is
explicit reconciliation, never silent UUID regeneration or overwrite.

Company, role, section, category, dates, paths, and source labels are descriptive,
not uniqueness or identity. Remove the existing descriptive/path uniqueness in
coordination with new creation behavior. Repeated identical attempts are valid;
no mandatory application date, requisition ID, or artificial attempt number.
Existing non-pipeline Application rows and relationships remain intact.

ImportSource represents source lineage. ApplicationSourceMapping identifies
`(import_source, source_record_key)`. Distinct source records map to distinct
Applications by default. Several historical keys may map to one Application only
through explicitly established same-record rename/move/alias lineage. Labels,
paths, fingerprints, and content equality alone are insufficient. Services may
enforce alias semantics where relational constraints cannot express them.
Verified embedded lineage permits automatic source registration; request manual
registration selection only when lineage genuinely cannot be established.

Prefer retaining mappings in terminal removed state after Application purge,
with only source identity, needed portable identity, and minimal operation metadata.
No notes, documents, bodies, or descriptive snapshots remain for replay protection.
Routine import cannot resurrect a terminal target; explicit new intent is required.
Workspace purge removes its mappings.

PostingApplicationConversion distinguishes operation identity, posting-to-attempt
relationship, operational conversion time, and live/removed target. Many conversions
per posting require explicit new-attempt intent. Ordinary retry resolves the old
conversion, including a purged target's terminal state. A conditional surviving
posting/application uniqueness constraint may protect duplicate links; never make
posting alone unique. Transitional `applied_application` is backfill-only and must
be removed after verified conversion-backed reads/writes take over. Null historical
links do not prove prior conversion; preserve unknown time as unknown.

Duplicate warnings are advisory, initially normalized company/role comparisons.
Include authorized archived/directly or effectively trashed candidates with state;
never expose another Workspace or purged descriptive data. Opening existing or
explicitly creating another attempt is supported. Warnings do not reserve identity.
Fuzzy/alias matching may improve warnings later, never identity. Established import
mappings bypass human duplicate-warning flows. Continuations are intent-bound
409-class challenges (Topic 8), not reusable `force=true`.

One creation service creates actual new attempts. Manual creation, posting new
attempt, and accepted discovery creation call it with explicit intent. Import
reconciles first and creates only when required. Initial related database records
are transactional; arbitrary IntegrityError must not become a company/role warning.
`source_relpath` remains transitional read-only provenance until consumer inventory
and Topic 7 backfill replacement are verified; normal flows do not depend on it.

## 4. Topic 3 — Timestamp provenance and Application derivation

### Separate meanings and precision

Keep five classes separate: factual/source timestamps; operational/storage times;
manual dates; derived Application dates/activity; recorded status-history times.
Source facts may be uncertain claims. Preserve actual instant, calendar-date-only,
or unknown precision with a constrained representation exposed in APIs. Never
manufacture midnight instants. Keep source offset/semantics where known; historical
naive time without reliable zone remains uncertain rather than assumed UTC/local.

Workspace has explicit calendar timezone, UTC only until configured. Do not infer
geography from server or browser. Store real instants as aware UTC values; leave
dates as dates. Compare mixed precision at workspace-calendar-day granularity where
sufficient; do not invent within-day order when one value is date-only.

Document-owned provenance preserves source candidates and selects activity by:

1. Retained/provider timestamp for generated email evidence when it actually represents the evidence event.
2. Specifically identified evidence-event date/time.
3. Verified preserved legacy filesystem mtime.
4. Original upload time only for genuinely new user uploads without better evidence.
5. Unknown.

Import, restore, extraction, retention, regeneration, and conversion execution
times never manufacture activity. A random parseable document date is not evidence
of activity. Preserve source facts separately from selected derived values.
Shared extraction caches describe bytes, not individual Document arrival/source
identity, retained-message provenance, or fallback time. Extraction method/version,
evidence tier, supporting source, precision, and conflict/unavailability must be
representable without copying per-Document assumptions into the cache.

### Derived state and manual values

Persist reproducible first/last activity with precision/provenance. Clear derived
values when evidence becomes ineligible; no eligible evidence means unknown, not
Application creation/import/derivation time. Keep derivation version, input revision
or fingerprint, operational `derived_at`, and completeness states such as current,
pending, incomplete, needs reconciliation. These metadata never affect business state.

Automatic status uses effective Document classification, including user correction:
`rejected > interviewing > applied > drafted > unknown`; non-pipeline rows retain
`n/a`. This is classification priority, not chronological event interpretation.
Manual status always wins. Ghosted is explicit/manual only, with choices, validation,
frontend, metrics, filtering, and history parity; never infer it from age. Preserve
legacy attention semantics separately from Ghosted and explicit due actions.

Maintain an automatic confirmation-date candidate separately from stored dates.
Effective application date is deterministic:

| Mode | Effective value |
|---|---|
| automatic | Eligible strong-confirmation candidate |
| manual/accepted | Explicitly entered or accepted stored date |
| legacy-preserved | Protected ambiguous historical stored date |
| suppressed | Null until explicitly reset to automatic |

Do not label ambiguous legacy dates as manual or fabricate user intent. Preserve
available historical source labels without pretending they prove intent. Such
values survive evidence changes until explicitly replaced, suppressed, or reset.
Recalculation never overwrites stored manual/legacy values. Posting evidence is a
suggestion; explicit acceptance is a manual decision with provenance. Strong
candidates agreeing on a calendar date may support autofill; materially conflicting
strong dates require review with no arbitrary winner. Never use filename, insertion
order, or earliest-wins as an unapproved tie-breaker. Automatic dates retract/change
with evidence; manual/accepted/legacy values persist even when source becomes unavailable.

Needs Attention precedence is explicit activity reset → effective application date
→ derived last Document activity. Unknown remains unknown. Day thresholds, due
and snooze calculations use Workspace calendar semantics. Archive, Trash, snooze,
next-action dates, and business status retain separate rules.

### Service and history

Use one deterministic per-Application calculation/service, callable by ordinary
mutations, extraction completion, import/reconciliation, and repair. Update only
automatic fields; input revision prevents stale writes. Normal GETs do not derive,
extract, write caches, or autofill dates. Replace dossier GET mutation through this
explicit workflow. Report pending/incomplete/conflicted derivation honestly.

Document create/extraction/type correction recalculates relevant evidence; rename
creates no activity but may alter filename classification/status. Document Trash
excludes its evidence for a live Application; restore reuses original evidence;
purge removes contribution. Parent Application/Workspace Trash preserves its last
valid internal snapshot and blocks ordinary processing. Reconcile as needed on
restore. Category membership/lifecycle alone never invokes derivation.

History appends only genuine effective user-visible status changes; suppress future
consecutive duplicates. Automatic changes hidden by manual override are not effective
transitions. Removing override may expose a real transition. Recorded transition
time is when JobTracker recorded it, not the evidence date; supporting evidence can
be referenced separately. Imported history preserves original known times and
existing duplicates. Import/backfill/repair must not fabricate historical transitions
at execution time. Operational reconciliation audit is distinct from user history.

## 5. Topic 4 — Category schema and membership

Category has Workspace ownership, stable PK, immutable workspace-scoped portable
ID, mutable display name, broad section, independent Archive and lifecycle state.
Rename/section change preserves identity. Empty Categories are valid; no placeholder
Document. Multiple Categories share a section. No name, normalized-name, section,
path, member-set, or creation-order identity/uniqueness.

CategoryMembership explicitly connects zero/one Category per Application to many
Applications per Category. Enforce Application.workspace == Category.workspace in
services, API, import, admin, workers, and database where practical. Membership has
no independent Archive/Trash. Category purge removes memberships only; Application
purge removes its membership. Absence means uncategorized, not a synthetic row.
Live records remain discoverable through system/pipeline and uncategorized views
after category removal or unresolved mapping. Category-context hiding never hides
live Applications from authoritative system views.

Category.section is organizational navigation; Application.section is existing
system classification. Neither is silently rewritten when the other changes.
Display mismatches consistently, not automatic repair. Applications is a protected
pipeline concept, never a Category row. Preserve existing non-pipeline records;
no entity-type split is authorized.

Names may duplicate with authorized section/lifecycle context in warnings. Normalize
for comparisons/sorting only, not merging. Preserve display spelling, reject empty
names/control characters, and do not apply filesystem identity semantics. Reserve
normalized case-insensitive `Applications` in normal create/rename. Imported original
text remains provenance without ambiguous pipeline navigation. Rename collision
warns; restore cannot fail solely on a duplicate name. Established source identities
bypass interactive duplicate warnings during import.

Recognized source sections map to supported system sections. Unknown/custom legacy
slugs map explicitly to `misc`, preserving original slug/path and distinct Category
name/identity/navigation. Report the mapping; never claim misc was original or merge
all custom categories. No custom section-definition system is introduced.

Category Archive affects organizational visibility only. Trash preserves memberships;
restore preserves archive/member state. Apply the asymmetric membership rule in
Topic 1: live Applications can leave trashed Categories, but cannot enter them;
effectively trashed Applications require restoration before ordinary reorganization.
Archive alone permits explicit movement. Membership changes cause no derivation/history.
Order by section/navigation order, normalized name, stable ID. Manual ordering deferred.

Category source mappings follow Topic 2, including verified aliases and terminal
removed state. Inventory FolderOverride into verified physical provenance, synthetic
section groups, standalone metadata, and ambiguous/stale records. Never convert all
rows blindly. Create only supported synthetic representation when that is all that
is known; do not fabricate historical folders or copy one ambiguous archive flag onto
several Categories as observed fact. Preserve old structures until validated backfill
and rollback requirements permit removal. New Category-ID services are sole writes;
retire destructive section-based category deletion. Frontend changes remain narrow.

## 6. Topic 5 — Retained-message identity, ownership, and relationships

Separate authorization episode, durable mailbox lineage, provider-side locator,
workspace RetainedMessage, workflow relationship, and generated Document. Existing
EmailAccount may safely evolve into either account role without gratuitous renaming.
Credentials remain separate. Disconnect removes usable credentials/access but keeps
lineage/content; reconnect obtains fresh authorization and reuses lineage only when
verified, never from email-address equality alone. Provider principal identifiers
are preserved when available, not invented.

RetainedMessage has runtime PK and immutable workspace-scoped portable ID. It belongs
to Workspace, never the first Application/Discovery/Posting/connection. No cross-
Workspace retained-content sharing, even for identical bytes. Subject, sender, hash,
RFC Message-ID, and thread ID are not retained identity.

MessageSourceIdentity represents a strong complete namespace: provider, mailbox,
folder namespace where applicable, locator kind/value, stability/version metadata
such as UIDVALIDITY. Strong identity uniqueness excludes weak identifiers. Preserve
RFC Message-ID, References, In-Reply-To, and provider conversation identifiers as
metadata; threads never prove one Application owns all messages. Missing RFC ID
must not discard relevant mail. With no strong locator or established import lineage,
create an unresolved case only after relevance qualifies for retention. Fingerprints
support exact observation retry recognition, not proof of same-message identity.
Preview/review remains possible; uncertain identity blocks automatic downstream
Application/Posting/evidence effects.

Same strong locator plus materially conflicting normalized/versioned content means
reconciliation: preserve observations safely, never overwrite or create another
supposedly identical source, and pause automatic effects. Harmless normalization
changes are not material conflicts. Content hashes are comparison evidence only.

### Content and relationships

Messages remain transient until needed for retained evidence, Discovery/review,
or Posting sources. Do not persist irrelevant observations or a whole mailbox.
Already-retained relevance processing should be replayable without routine refetch.
Initially store approved textual representation in PostgreSQL: subject; structured
From/Sender/Reply-To/To/Cc/available Bcc; ordered/repeated Date, Message-ID,
In-Reply-To, References and selected MIME/charset headers; provider timestamp
metadata; readable decoded text and original HTML within configured limits.
Do not retain raw MIME or attachment bodies by default. Explicit later attachment
ingestion creates its own governed Document/source relationship.

Preserve HTML as source but render only sanitized derivatives: disable scripts,
forms, event handlers, unsafe URLs, remote images/tracking. Sanitizer upgrades do
not rewrite original content. Complete, partial/truncated, unavailable, conflict
states must be honest, including truncation reason/location when known. Extraction
and evidence generation must know when content is incomplete.

Preserve header-sent, genuine provider-received/internal, observation, and retention
times separately under Topic 3. Never backfill Outlook/IMAP header Date as verified
receipt. Legacy PDF-only evidence stays a Document; do not reverse-engineer a body
and claim original source recovery. Missing source is explicitly unavailable.

ApplicationMessage is many-to-many, unique per Application/source (plus purpose
if multiple purposes are required). Application owns link, not source. Discovery
references source; candidates are suggestions, dismissal is review state. PostingSource
supports many-to-many postings/sources without content-based posting identity.
Thread hints preserve supporting provenance where known. All endpoints must be
same-Workspace across every execution surface.

EvidenceGeneration identifies Application + retained source + purpose, not filename,
Document ID, renderer version, or time. Track current Document, terminal state, and
operational version/time. Each Application owns its own generated file. Retries
reuse generation and cannot restore/recreate intentionally trashed/purged artifacts.
Explicit regeneration needs the unresolved artifact policy in section 14.
Dismissal/disconnect never implies evidence deletion. Source purge checks all
surviving/restorable references; no automatic orphan deletion or generic Trash UI.

Backfill across accounts, matches, discoveries, thread hints, postings, and evidence
only when source identity is established. Metadata-only sources may preserve known
links. Preserve conflicting observations and existing relationships during staging;
no fabricated provider IDs, mailbox continuity, or external fetches in migrations.
Exports include approved content/provenance/relationships/terminal state, never
credentials or live authorization. Each launch provider separately validates locator,
reconnect, folder movement, timestamps, missing IDs, pagination/retry and thread semantics.

## 7. Topic 6 — Workspace scoping contract

Normal resources/actions use `/api/workspaces/{workspace_id}/...`, including object,
file, search, count, settings, review, import/export and operation URLs. Repeat Workspace
in object URLs even with global PKs. No backend mutable current/active Workspace.
No normal header/session/body alternate scope; reject conflicting redundant scope.
Normal payloads cannot assign owner/Workspace or move entities across Workspaces.

Lookup order: authenticate → authorized Workspace → lifecycle eligibility → scoped
object lookup → nested endpoint validation → service with resolved context. Do not
fetch unscoped objects then check. Same-owner Workspaces remain isolated for reads,
writes, references, counts, suggestions, files, caches and jobs. Nested Document
URLs validate both Workspace and Application parent. Ordinary synchronous bulk
mutations prevalidate every ID/state before any effect; reject mismatches rather
than silently skipping. Use bounded atomic database effects.

| Condition | Public contract |
|---|---|
| Missing/expired authentication | 401 authentication_required |
| CSRF rejection | 403 csrf_failed |
| Unknown/unowned/mismatched scoped resource | 404 not_found |
| Invalid payload/reference | 400 validation_error or generic unavailable-reference outcome without foreign details |
| Authorized lifecycle/duplicate/reconciliation conflict | 409 with specific code |

Verify framework configuration actually implements these distinctions. Same-origin
Django session auth and CSRF protect state changes, including login. Basic auth is
not normal production product access. Narrow unscoped endpoints: auth/session/CSRF,
Workspace selector/create, Workspace-addressed lifecycle, tenant-free health,
validated OAuth callbacks, internal admin/system scheduling. Selector is not an
all-workspace dashboard.

Creation derives scope from route; new Workspace owner derives from actor. Import
archive ownership is provenance only. Import-as-new establishes destination first.
Frontend per-tab route/hash-route is selection authority. User/tab sessionStorage
may assist navigation, never override route. No shared localStorage active selection
or sensitive payload cache. Clear prior-user context on session identity change.
Capture immutable Workspace/intent per request/retry; navigation never retargets a
write. Abort obsolete reads or ignore late responses by Workspace/navigation generation.

Cache keys include applicable actor, Workspace, query/resource, lifecycle visibility,
and content/derivation version. Hash is not authorization. Sensitive file/preview/export
access initially is authenticated and scoped; raw storage keys are not product IDs.
Later signed URLs require scoped issuance and honest bounded bearer lifetime, not
claims of immediate revocation.

OAuth attempts independently bind unguessable state, user/session, Workspace,
provider, PKCE where needed, safe return location, expiry and consumption/cancellation.
Callbacks resolve exactly one attempt, reject replay, revalidate actor/scope/lifecycle,
and return to bound Workspace. Concurrent tabs cannot overwrite one provider session
slot. Jobs persist immutable Workspace/actor/targets/intent and revalidate before
sensitive access and significant commits. Scope loss gives explicit result, not
retargeting. System scheduling can enumerate eligible workspaces but dispatches
scoped units; UI Sync all means selected Workspace only.

Staff/superuser never broadens normal product querysets. Admin is explicit privileged
access with scoped relationship validation, hidden credentials, lifecycle services,
and actor/Workspace mutation logs. User deletion cannot incidentally cascade Workspace
purge. Replace owner-wide paths workflow-by-workflow; migrate frontend, verify, disable
old write path. No singleton-workspace inference or fallback. Temporary read adapters
must be removed before legacy retirement.

## 8. Topic 7 — Import/export representation and reconciliation

### Modes and identity

Actor/workflow explicitly selects mode before mutation:

| Mode | Contract |
|---|---|
| Same-logical-Workspace restore | Empty/new recovery destination; preserve lineage and portable graph identities, relationships and direct/terminal states; local PKs may change |
| Legacy import | New target lineage where native lineage absent; preserve legacy identity through ImportSource, never claim legacy had a native UUID |
| Existing-Workspace reconciliation | Established mappings and reviewed field-aware plan, no silent overwrite |
| Independent copy | New Workspace and graph portable identities; remap relationships; preserve origin as provenance only |

Workspace portable identity is independent of PK, owner, name, path, and artifact.
No initial destructive restore over populated live Workspace. If active same-lineage
destination exists, require recovery/reconciliation rather than two active authorities.
Copy is a fork, never synchronization. Do not assign independent UUIDs mechanically
to joins: typed endpoint keys suffice for membership, overrides, source links where
no independent durable history is needed.

### Format and validation

Use explicit versioned manifest/data ZIP, not Django fixture/database dump. Manifest
records format major/minor, required features, snapshot ID, source lineage, operational
export time, completeness, entity/file counts, member sizes/SHA-256, exporter version,
and known source unavailability. Data groups encode entities and typed portable
references; files may use Document portable ID plus safe current filename. Exact
visible filename stays metadata; equal bytes never merge Documents or physical
ownership. Each imported Document gets its own governed storage object.

Use explicit supported-version adapters. Reject unsupported major/required semantics
before domain mutation; tolerate unknown optional fields only by format contract.
Checksums prove integrity, not source identity/authenticity/authorization. ZIP checksum
is never ImportSource identity. Validate paths, traversal, duplicate members, links/
special entries, compressed/uncompressed limits, entry counts/decompression exhaustion,
required files/checksums, portable uniqueness, relationship cardinality, same-Workspace
and terminal/lifecycle invariants. Imported text/HTML/filenames are untrusted.

Complete export must verify every required file; unreadable/missing content fails.
Diagnostic incomplete artifacts are labelled non-restorable and rejected by normal
restore. Explicitly unavailable original email content can be a complete known-state
representation when evidence/relationships are intact. Empty Categories are structured
records, not folders/placeholders.

Include Applications, Documents/files/overrides, Categories/membership, all manual/
legacy/suppression state, history with original known times/duplicates, retained bodies/
headers/availability/source identities, Discovery/thread/evidence relationships,
postings/sources/conversions, generation terminal state, settings/timezone, aliases,
sender rules and provenance mappings. Preserve settings card/link semantics without
assuming old group keys are Category IDs. Export derived state as comparison checkpoint;
rederive and report differences without fake history. Caches are rebuildable, not
canonical restoration data; retain unreconstructable known provenance as uncertain.

### Reconciliation and publication

ImportSource is persistent lineage; ImportRun is execution against mode/artifact.
New artifact normally means new run, not source. A trustworthy BASE is last applied
source state; compare semantically with LOCAL and INCOMING. Incoming unchanged keeps
local changes; local unchanged permits incoming proposal subject to protected rules;
both changed differently means conflict; missing trustworthy base forbids guessed
overwrite. Manual status/date/corrections, legacy-ambiguous dates, suppression, archive,
direct Trash, review decisions and terminal state are protected. Source absence is
not deletion of entities or relationships. Verified aliases only; terminal mappings
block routine resurrection and retain no purged payload.

Complete same-lineage exports include live, archived, direct/restorable Trash and
independently trashed descendants plus minimal terminal state. Do not flatten effective
Trash. Independent copies may preserve snapshot states under new identities.
Exclude tokens/passwords/keys, session/CSRF/OAuth attempt state, signed URLs, infrastructure
credentials and live authorization through an explicit allowlist. Restored mailbox
provenance is disconnected; reconnect is fresh authorization. Portable export is not
operational PostgreSQL/object-storage/configuration disaster-recovery backup.

Stages: validate → immutable/versioned plan → resolve/review conflicts → stage files
→ maintenance barrier → revalidate destination revision → bounded DB publication →
derive/verify. Plan binds mode, destination, lineage, artifact, expected revision,
mappings, creates/updates, protected choices, files, unresolved references and validation.
Approval applies to that plan; stale plans require recompute/review, not mutation of
approved intent. No normal half-import visibility. Keep database transactions out of
upload/decompression/hashing/storage/user-review waits. Track staged objects durably.

Export barrier captures consistent database/file state and prevents relevant mutations/
purge until verification; release safely on failure. Import barrier covers shortest
practical final window. Reads may show consistent pre-operation state. Block/wait
exports during active purge rather than snapshot mixed deletion state.

Before publication: validation does not mutate domain data; bounded DB failure rolls
back that unit; staging cleanup handles abandoned artifacts; cancellation exposes no
partial import. After publication, never blindly delete imported records as rollback;
use coordinated checkpoint recovery or reviewed compensation. Same-run retry resumes;
new run reconciles. Sensitive temporary archives use authenticated scoped access and
controlled retention. Original legacy folder/ZIP/database/evidence remains unmodified;
use snapshots/read-only adapters, not legacy helpers with migration side effects.
ZIP materialization/import time never substitutes for uncertain source timestamps.

## 9. Topic 8 — Idempotency strategy

Four independent identities: HTTP request, durable business operation, source mapping,
and worker attempt. New HTTP key does not authorize another posting attempt; source
existence does not prove downstream processing completed; task delivery is not new intent.

Clients generate one cryptographically random opaque Idempotency-Key before consequential
record/artifact allocation or destructive initiation. Retry preserves key, Workspace,
route/kind/targets/material payload/plan. New explicit intent gets a new key. Scope
normal uniqueness to durable actor + Workspace + key, not session cookie; replay always
reauthorizes. System operations use explicit system principal. Bind versioned canonical
digest to semantic fields, including omission/null/false, collection ordering, modes,
plan/challenge revisions, file-entry IDs/digests. Exclude cookies/CSRF/tracing/time.
Same key with changed intent returns 409 idempotency_key_reused.

RequestIntent holds minimal digest/context/state and linked result/operation, not full
sensitive bodies. Typed domain operations remain authoritative. Replay resolves original
effect with current authorized state: live/trashed result, minimal removed outcome,
or completed export with expired artifact. Never recreate because response is unavailable.
Detailed replay metadata defaults to 30 days after completion, configurable; compact
consequential key mappings remain through required lifecycle, normally Workspace purge.
Expiry never makes old keys reusable. Operational request records are not user history
or source/activity timestamps.

Duplicate/new-attempt challenge defaults to 15 minutes, configurable; binds actor,
Workspace, intent, candidates/revision. Atomically validate/consume and continue the
same intent. Expiry/material changes need renewed review, not automatic execution.
No reusable force flag. Explicit another-attempt intent creates new Application and
conversion; different HTTP key alone is insufficient. Discovery acceptance similarly
has durable acceptance result and requires explicit intent for another attempt.

Prefer desired-state setters with expected revision, not toggles. Current revision
applies/no-ops; changed revision gives 409 stale_revision. No-op causes no revision or
history churn. Keys optional for simple setters needing transparent lost-response
recovery; otherwise refetch uncertain outcome. Membership obeys Topic 4. Trash/restore
obey lifecycle revision and prior child state. Permanent purge requires frozen confirmed
scope and durable manifest; unexpected references cause conflict, not scope expansion.
OAuth single-use attempt supplies protocol identity without generic client key.

Sync separately tracks reconciliation and unfinished matching/review/posting/evidence
stages. Posting ingestion uses durable source-item mapping, not connection/company/title
or parser order; uncertain parser changes need reconciliation. Evidence generation
uses Application/source/purpose and terminal artifact state; renderer upgrades never
create automatic duplicates. Upload batch key plus stable entry IDs reconciles staged
successes; digests bind bytes, not global Document identity. Stage storage before bounded
DB publication and reconcile uncertain writes. Same ImportRun retries; new run reconciles;
export retry preserves original snapshot even after artifact expires.

PostgreSQL unique constraints enforce request/source/relationship/operation invariants;
row locks and bounded transactions protect mutable decisions. Define consistent lock
ordering; deadlock/serialization retries keep identity. No frontend button, process
mutex, cache, or Celery task ID is final authority. Domain operation and outbox commit
together; dispatcher may publish twice. Workers use attempts, leases and fencing.
Expired lease does not establish non-effect: reconcile uncertain storage/provider
outcomes before retry. Domain/source terminal deletion protection outlives replay-cache
expiration. Workspace purge removes its state; late scoped requests cannot recreate it.

## 10. Topic 9 — Async task/API contract

### Durable execution and public state

Keep business operation, outbox event, Celery delivery, worker attempt, and public
projection separate. PostgreSQL is authority; Redis result expiry or Celery success
is not business outcome. Shared envelope complements typed ImportRun, ExportOperation,
PurgeOperation, EvidenceGeneration, conversion, upload and sync records. Scope, kind,
target, intent, approved plan and idempotency binding are immutable; changed intent
requires new operation. Envelope supplies actor/system principal, state/typed phase,
revision, cancellation flag, factual progress, attempt/retry scheduling and safe result.

Public states: queued, running, retry_wait, awaiting_action, reconciling, succeeded,
partially_succeeded, failed, cancelled. Succeeded/partially_succeeded/cancelled are
normally terminal. Failed resumes only by permitted explicit recorded transition on
same intent. Never silently reopen completed/cancelled work. Retry_wait, awaiting_action,
reconciling are non-terminal. Cancellation requested is a flag, not completion.
Phase is workflow-specific (e.g. import validating/planning/staging/publishing/deriving/
verifying); no mandatory global phase enum. Outbox publication is internal diagnostics,
not competing public broker states.

Async acceptance: 202 plus Location and scoped operation representation containing ID,
kind/state/phase/revision, factual progress, allowed actions, result/error. Poll/list/
cancel/retry routes are `/api/workspaces/{workspace_id}/operations/...`. Poll GET returns
200 for successful retrieval even if business failed. All links remain scoped; no raw
storage or Celery access IDs. Authorization/replay always follows Topics 6–8.

### Workflow contracts

Bounded setters, membership, Archive/Trash/restore, creation/conversion/acceptance
are generally synchronous. Email sync, posting extraction, missing previews/extraction,
evidence generation, import/export, purge/storage cleanup, bulk repair, long upload
publication are async. Derivation uses the same bounded local service synchronously
or asynchronously. Normal GET never starts extraction, cache writes, evidence or sync;
return availability and already-started operation links. Creation success does not
claim pending evidence succeeded.

SyncAll parent records scoped child operations and their outcomes. Sync supports
explicit per-source/stage partial success: committed work survives later failure;
fetched count is not completed downstream count. Cursor advancement cannot abandon
unfinished retained-source processing. Scheduler creates durable scheduled identity
and prevents equivalent overlap; initial 15-minute cadence is configurable. Manual
and scheduled runs can differ but serialize safely per connection.

Upload entries stage independently/retry without duplication, but initial Document
publication is batch-level: no normal half-created batch. Import remains non-visible
until approved publication; after publish cancellation is not rollback. Complete export
requires consistent verified content/artifact; missing required files is failed, not
partial backup. Expired artifact leaves succeeded operation with unavailable artifact;
new export requires new intent. Evidence generation success requires verified governed
artifact, not renderer invocation. Purge success requires complete confirmed cleanup.

### Cancellation, retries and operations

Cancel cooperatively before external access where practical, between bounded units,
before publication and irreversible cleanup. Completion may win cancellation race;
report actual result. After irreversible purge begins, cancel is unavailable: finish,
retry or reconcile frozen scope. No process kill implies business rollback.

Retry only explicitly transient network/provider/rate-limit/storage/database conditions,
with bounded backoff/jitter/provider guidance. Invalid input, revoked/disconnected access,
stale plans, lost authorization, source conflict and uncertain effects are failed,
awaiting_action or reconciling, not blind retry. Reconciling is first-class for possibly
completed external effects; inspect known identities/checksums/state before repeating.

OperationAttempt tracks operation, lease owner/expiry, fence, heartbeat, start/finish
and outcome. Commit only under current fence; operation/attempt staging prevents stale
workers overwriting published external artifacts. Lease expiry permits takeover but
never proves no prior effect. Outbox event and operation commit atomically; dispatch
ack loss/duplicate delivery safe through durable identity, not solely on_commit.

Polling initially starts around 2 seconds, backs off toward 10 with jitter/server guidance,
pauses/slows for hidden tabs/action states, stops on terminal state, refreshes on focus/
network recovery. These are configurable defaults, not protocol invariants. Reload
recovers scoped recent/unfinished operations; no sensitive localStorage result cache.
Progress reports unit/completed/failed/skipped/pending/total-if-known/bytes/last meaningful
time and determinate state. No invented percentages. Partial success only where contract
permits permanent mixed outcomes, not unfinished staging/purge/export/import.

Public error: stable code, safe message, retryability, next action and correlation ID.
No raw exceptions, credentials, email bodies, provider payloads, signed URLs/storage keys
or foreign identifiers. Protected logs correlate Workspace/operation/attempt/outbox/category
without duplicating sensitive content. Detail/progress retention defaults ~30 days after
completion; export artifacts ~7 days, configurable. Compact consequential results persist
for accepted lifecycle. Never silently expire unfinished work. Temporary cleanup is not
user Trash expiration.

Workspace Trash stops ordinary work at safe boundaries and requires explicit email
resume after restoration. Maintenance may wait/revalidate; purge permits only confirmed
cleanup, not broad processing. Late ordinary jobs cannot write into purged Workspace.
A minimal short-lived purge receipt outside deleted graph is actor/admin-principal-bound,
opaque Workspace/operation identity plus minimal status/timestamps only. No names/content,
restoration authority, source mapping, or ghost Workspace. After deletion, use a narrow
receipt reference, never surviving general Workspace operation API. Account/privacy
policy may remove receipt sooner; exact short retention configurable.

Production roles: web, workers, Beat/scheduler, outbox dispatcher, recovery loop.
Packaging may combine safe lightweight loops, responsibilities stay distinct. PostgreSQL
is authoritative; Redis transport/results optional operational convenience. Bounded
capacity-separated queues prevent long imports/storage/purge starving ordinary work.
Graceful restart preserves outbox/queued/retry work, recovers expired leases and fences
old workers. Do not depend on Redis result history. Replace old synchronous sync,
direct delay and Beat write paths; disable/drain or safely reject old deliveries before
new authority. Provider fetch/normalize happens outside long transactions; bounded
source commits/checkpoints follow. Real production-component validation is mandatory.

## 11. Cross-topic ownership/reference table

PK means normal runtime identity; portable identities are Workspace-scoped except
Workspace lineage. Logical keys avoid unnecessary join UUIDs. FK spelling does not
supersede the lifecycle service rules.

| Record | Lifecycle owner/root | Portable/source identity | Containment versus reference and deletion effects |
|---|---|---|---|
| Workspace | Protected User ownership; lifecycle root | Workspace lineage UUID; PK runtime | Purge all owned graph; no incidental User cascade |
| Application | Workspace | PK + portable UUID; source mappings | Owns Documents/overrides/history; not Category or source |
| Category | Workspace | PK + portable UUID; category mappings | Owns organizational metadata/memberships, never Applications |
| CategoryMembership | Endpoint-owned relationship in Workspace | Application/Category portable endpoints | One per Application; endpoint purge removes link only |
| Document | Application, same Workspace | PK + portable UUID | Owns file/override/exclusive artifacts; shared source is reference |
| RetainedMessage | Workspace | PK + portable UUID; strong source identities | Survives individual link purge; required references block source purge |
| ApplicationMessage | Application | Application/source/purpose | Link removal never automatically removes retained source |
| Discovery/review | Workspace | PK; durable review identity/source reference | Candidates not ownership; dismissal preserves source |
| JobPosting | Workspace | PK + portable UUID; source-item mappings | Dismissal not deletion; conversion does not own Application |
| PostingSource | Posting relationship in Workspace | Posting/source endpoints | Link removal never automatically purges source |
| PostingApplicationConversion | Posting/Workspace | Durable conversion/operation identity | Application FK can null; terminal outcome survives target purge |
| EvidenceGeneration | Application/Workspace | Application/source/purpose | Owns logical generation state; Document purge leaves replay protection |
| ImportSource | Destination Workspace | Source lineage registration | Owns mappings, not mapped domain entities; terminal mapping may survive target |
| ImportRun | Destination Workspace | Durable run/plan identity | Staging cleanup separate from published domain ownership |
| RequestIntent | Workspace, actor/system scope | Scoped key + versioned intent digest | Operational link, not owner of created content |
| Durable/public Operation | Workspace; public projection not separate owner | Operation ID and typed intent | Typed rules govern effect; no deletion of targets by generic operation cleanup |
| OperationAttempt | Durable operation | Attempt ID/fence | Execution metadata, never a new business intent |
| PurgeOperation | Workspace until purge; narrow external receipt afterward | Frozen confirmed operation/manifest | Deletes true owned scope only; never broadens references into ownership |

## 12. Migration safety

Distinguish normal schema additions from data backfills, populated intermediate
upgrades, and legacy import. Preserve existing PK/FKs unless a specific accepted
migration requires otherwise. Add nullable/transitional fields and backfill verified
portable IDs/mappings before required constraints/authority cutover. Inventory consumers
before dropping source_relpath, FolderOverride, old account/message metadata or posting
links. Remove old authorities only after replacement reads/writes and rollback needs
are verified; never run permanent parallel writes.

Populated databases require inventories and rehearsals independent of fresh-schema
tests. `documents 0002` deletes/recreates DocumentOverride under a historical no-data
assumption; older populated states need explicit preservation before that path.
Do not fabricate request IDs, provider IDs, dates, lineage, conversions, manual intent,
source bodies, or status transitions. Known unknowns remain explicit. No external
mailbox fetch inside schema/data migration; no source-mutating legacy helper calls.

Before material real-data repair/backfill, comparison plans show stored/proposed values,
source, precision, confidence, manual/automatic/legacy/unknown mode, conflicts, mappings,
relationships and file availability. Source-level and target-level uncertainty are
reported, not guessed. Writing a migration or accepting design does not authorize
real-data changes. Preserve original local sources and rollback artifacts through
cutover acceptance. Implementation remains separately authorized.

## 13. Verification requirements

| Layer | Required evidence |
|---|---|
| Unit/service | Deterministic derivation, ownership, state setters, semantic comparisons, conflict/replay logic, redaction |
| Model/schema migration | Constraints, unchanged populated PK/FKs, honest backfill, terminal state, lock/fence invariants |
| API/contract | Session/CSRF/errors, explicit scope, nested references, bulk atomicity, challenges, polling/actions |
| Integration/workflow | Full browser/import/email/evidence/lifecycle flows, repeat effects, partial stages, restoration and failure boundaries |
| Operational/production | Actual services/providers, concurrency, crashes, restart recovery, capacity, coordinated backups/restoration |

Mandatory scope fixture: actor owns A and B; second actor owns C. Verify positive
and negative access in lists, objects, nested relationships, counts/search/files,
OAuth attempts, workers, replay and late frontend responses.

Crash tests include lost response after commit; simultaneous same-key create; changed
payload; new key without new-attempt authority; challenge races/stale revision; partial
upload; storage success before DB publication; DB/outbox commit before publish; duplicate
publish; expired lease with old worker alive; existing source with unfinished stages;
Trash/purge before replay; Workspace purge before late jobs. Test Category purge leaves
Applications/files discoverable, and parent restore preserves independent child Trash.

Exercise all four import modes for counts, identities, relationships, checksums, manual/
ambiguous dates, history, repeated attempts, Categories, retained/unavailable content,
conversions, terminal state, secret exclusions, derivation and repeat/failure/cancellation.
Support historical format fixtures and representative large Workspace rehearsals.

Automated unit/integration success does not establish operational validation of
PostgreSQL concurrency, Redis redelivery, Celery workers, Beat, outbox/recovery loops,
object storage, production session/CSRF, actual provider locator/reconnect behavior,
deployment drains/restarts, or coordinated backup/restore. Validate each enabled provider
with appropriate test accounts and real components. Record operational evidence separately
from suite counts. No tests were run for this documentation consolidation.

## 14. Explicit unresolved/deferred items

### Requires explicit decision before implementation

- Evidence regeneration artifact behavior: replacement versus governed supersession.
  Retry identity is settled; artifact behavior must not be chosen silently.

### Implementation/operational details still to determine or validate

- Provider-specific locator guarantees, reconnect and timestamp behavior.
- Posting source-item reconciliation examples/rules within accepted identity boundaries.
- Exact field names/model decomposition where multiple schemas satisfy the contracts.
- PostgreSQL lock ordering and worker queue/concurrency sizing.
- Retention configuration values within the accepted configurable policies.
- Exact API spelling and archive serialization subdivision.
- Hosting vendor/infrastructure specifics and validated launch-provider subset.

These are not reopened product decisions. No additional design topic or implementation
is authorized here. Existing product deferrals remain in Decisions: frontend modernization,
public onboarding, offline synchronization, new desktop wrapper, whole-mailbox retention,
automatic Trash expiration and broader event lifecycle are not added to this scope.
