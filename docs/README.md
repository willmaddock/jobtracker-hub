# JobTracker documentation

## Start here

- [`CLAUDE_HANDOFF.md`](troubleshooting/CLAUDE_HANDOFF.md) — the living handoff for the `_app/` single-user FastAPI app's Email Sync / Job Postings redesign. Keep this file current.
- [`DJANGO_BACKEND_HANDOFF.md`](DJANGO_BACKEND_HANDOFF.md) — the living handoff for the `backend/` Django rewrite track (Phase 9 onward). A different codebase from `_app/` — check which directory a change touches before assuming either file applies.
- [`DJANGO_MIGRATION_PLAN.md`](DJANGO_MIGRATION_PLAN.md) — the stable Phase 0-10 plan for the Django rewrite. Doesn't change session to session; `DJANGO_BACKEND_HANDOFF.md` is where progress against it is recorded.
- [`CHANGES.md`](troubleshooting/CHANGES.md) — project change history.

## Troubleshooting

- [`troubleshooting/email-sync/`](troubleshooting/email-sync/) — start
  here for any Email Sync (Mail.app discovery / Job Postings) bug report.
  Symptom-to-cause table, numbered audit findings, and pointers to the
  relevant source files and regression tests.

## Specifications

- [`specs/ITEM7_TIMELINE_FDD_DRAFT.md`](specs/ITEM7_TIMELINE_FDD_DRAFT.md) — historical Item 7 functional design document.
- [`specs/ITEM8_LIFECYCLE_OUTCOME_FDD_DRAFT.md`](specs/ITEM8_LIFECYCLE_OUTCOME_FDD_DRAFT.md) — historical Item 8 design document.
- [`specs/discoveries-board-v2-spec.md`](specs/discoveries-board-v2-spec.md) — historical Email Sync board v2 specification; useful background for the current Job Postings redesign.

## Archived handoffs

- [`archive/handoffs/HANDOFF_SESSION16_LEGACY.md`](archive/handoffs/HANDOFF_SESSION16_LEGACY.md) — preserved prior session-by-session engineering handoff. It is historical reference, not the active handoff.
- [`archive/handoffs/HANDOFF.md`](archive/handoffs/HANDOFF.md) — superseded root-level pointer stub, kept for history only.

Other files in this directory are development logs, source material, and the User Guide.
