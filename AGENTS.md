# Repository instructions for coding agents

## Read first and establish evidence

- [Accepted architecture/product decisions](docs/DJANGO_MIGRATION_DECISIONS.md)
- [Current migration checkpoint](docs/DJANGO_MIGRATION_STATUS.md)
- [Broader migration context](docs/DJANGO_MIGRATION_PLAN.md)
- Consult relevant handoffs/specifications for historical or behavioral evidence
  where appropriate, not as automatically current instructions.

Code determines what is implemented. The Decision Record determines the accepted
target; the status document records the maintained checkpoint. Never infer
completion from an old test count or handoff statement. Distinguish acceptance,
implementation, automated verification, and operational/end-to-end validation.

## Architecture

- Preserve `_app/` as the behavioral reference during migration. Django under
  `backend/` is the target authoritative backend.
- Legacy `domain/` and `infrastructure/` live under `_app/`; they are not a
  shared Django library. Do not introduce shared abstractions merely to remove
  duplication unless explicitly planned.
- Do not reintroduce filesystem identity into Django models.
- Respect explicit workspace scoping and authenticated ownership. Validate
  referenced objects against the specified workspace/user; no global active
  workspace pointer. Browser tabs must safely use different workspaces.

## Data and lifecycle invariants

- Stable Django IDs are authoritative. Legacy paths/keys are provenance and
  reconciliation data, not normal identity or permanent uniqueness.
- Never silently merge repeated applications based only on company/role.
  Use explicit duplicate warnings and idempotency as specified in the decisions.
- Automatic application state, manual overrides, Archive, and Trash are distinct.
  Manual values take precedence where specified in the Decision Record.
- Derivation is deterministic and only updates derived fields. Preserve evidence
  timestamps; import time or metadata edits must not manufacture activity.
- Trash preserves records, relationships, files, and prior child state.
  Trashing must not physically delete stored files. Permanent deletion is
  explicit/destructive and follows defined ownership/cleanup rules.
- Import/reconciliation preserves source data and is idempotent. Do not fabricate
  missing evidence or export authentication secrets.
- Retained email is sensitive workspace data; disconnecting removes credentials,
  not already retained evidence. Shared sources require explicit lifecycle rules.

## Frontend and API

- Preserve the existing UI during migration; no visual redesign or broad
  restructuring unless explicitly approved. Narrow integration refactors only.
- Django contracts are authoritative for migrated workflows. One authoritative
  write path; no silent fallback to FastAPI writes.
- Use explicit workspace context and stable IDs.
- Follow the centralized API-client direction: sessions/auth, CSRF, workspace,
  normalized errors, retries, idempotency, and asynchronous task state.
- Temporary compatibility must have a removal point before legacy retirement.

## Testing and evidence

Legacy, from repository root:

```sh
.venv/bin/python -m pytest
```

Django, from `backend/`:

```sh
venv/bin/python manage.py test
```

Targeted Django tests may run first, for example:

```sh
venv/bin/python manage.py test core
```

Run relevant full suites before declaring implementation checkpoints complete.
Do not claim tests passed unless actually run in the current working state;
label supplied/historical results as such. Documentation-only work should use
documentation checks and must not imply a fresh application test run.

Test complete workflows, workspace isolation, lifecycle behavior, idempotency,
and frontend-visible errors where affected. Automated tests do not establish
real PostgreSQL, storage, Redis/Celery, OAuth, backup/restore, or cutover validation.
Never modify real tracker databases as part of tests; use isolated fixtures/data.

## Environments and dependencies

| Purpose | Environment | Dependencies |
|---|---|---|
| Legacy | `.venv/` | `_app/requirements.txt`, `requirements-dev.txt` |
| Desktop additions | Legacy/build workflow as appropriate | `desktop/requirements.txt` |
| Django | `backend/venv/` | `backend/requirements.txt` |

Do not install/update dependencies without explicit need and approval. Do not
revive stale `.venv-django` instructions.

## Git, user data, and scope

- Inspect git status and diff before and after changes.
- Work on the checked-out branch unless explicitly instructed otherwise.
- Do not switch branches, merge, rebase, reset, commit, push, force-push, or
  delete branches without explicit approval.
- Do not delete or rewrite user data. Real-data changes require explicit
  authorization; migration design is not permission to alter a user's tracker.
- Keep changes scoped to the requested task. Do not use migration work as an
  invitation to investigate or fix unrelated product bugs.
- Preserve local source data and rollback artifacts; do not silently repoint
  desktop installations or imply local/hosted synchronization.

## Documentation maintenance

- Update `docs/DJANGO_MIGRATION_STATUS.md` when a checkpoint materially changes,
  recording what changed and the actual verification evidence/limitations.
- Change `docs/DJANGO_MIGRATION_DECISIONS.md` only when the accepted decision
  itself has explicitly changed, not to rationalize accidental implementation drift.
- Keep status concise, not a session transcript. Preserve useful historical
  evidence while distinguishing it from current instructions.
- Do not follow obsolete ZIP-transfer or sandbox instructions as current workflow.

## Deferred unless explicitly requested

All-workspaces overview; structured React modernization; broader event-based
lifecycle redesign; nested/multi-category membership; automatic Trash expiration;
whole-mailbox archiving; broad automatic email attachment ingestion; permanent
legacy API compatibility; public signup/invitations; new desktop wrapper;
offline/local synchronization.
