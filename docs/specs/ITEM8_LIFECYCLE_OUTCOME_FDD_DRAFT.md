# Item 8 — Lifecycle & Outcome Tracking: FDD Draft (design only, not implemented)

## Status

**Scoping only.** No code has been written for this item. This document
exists to capture the design discussion before implementation begins,
the same way `ITEM7_TIMELINE_FDD_DRAFT.md` did for Item 7. Deferred
since Item 6's Checkpoint 1 as "the archive/lifecycle engine."

## Why this exists

Today, `overrides.db`'s `archived` field is a single boolean — an
application is either visible in the active Pipeline or hidden in
Manage's Archived list. `rejected` is currently overloaded as both a
*status* and, in practice, the only signal for *why* something left
the active pipeline. That collapses several genuinely different
outcomes into one bucket and throws away information a real job
search naturally produces (a rejection is not the same event as
silence, and neither is the same as a company freezing the role).

## Two orthogonal concepts, not one

- **Visibility** (`archived`, unchanged) — is this item cluttering the
  active Pipeline view. Purely organizational, no semantic content.
- **Outcome** (new) — *why* an application stopped being active. This
  is the new piece. An item can be closed with a specific outcome and
  still be unarchived (visible in a dedicated Closed view) — archiving
  stays a separate, later, purely-declutter action, not something an
  outcome forces.

## Outcome taxonomy

| Stored value (`outcome`) | Display label | Trigger |
|---|---|---|
| `no_response` | **Ghosted** | Total silence from the employer — no formal rejection ever arrives, including after a seemingly strong interview. |
| `rejected` | **Rejected (TBNT)** | A "thanks but no thanks" email or a direct decline arrives. |
| `role_frozen` | **Role Frozen / Canceled** | The listing is pulled, a hiring freeze hits, or headcount budget disappears before anyone is hired. |
| `withdrawn` | **Withdrew** | The user pulls out — a red flag in the process, a bait-and-switch job description, an unreasonable take-home. |
| `offer_declined` | **Offer Declined** | An offer arrives and the user turns it down. |
| `offer_accepted` | **Offer Accepted** | The win condition. |

The stored value is deliberately neutral (`no_response`, not
`ghosted`) even though the UI shows the vernacular label — see the
design note below.

## Design note: neutral storage, vernacular display

"Ghosting" as a term is well past trend status — recruiting-industry
research now tracks it as a standing, worsening metric rather than a
one-season buzzword: independent reports through 2025–2026 put
employer-side silence at roughly half to three-quarters of all
applications, and SHRM ranks it among the industry's top recruiting
challenges. The vernacular has genuine staying power and is worth
using in the interface — it is how people actually describe this to
each other. But the term originates in dating culture and carries an
emotional charge the underlying data doesn't need. What the app can
actually observe is simple and factual: no response arrived. Storing
`no_response` keeps the data model boring and accurate; showing
"Ghosted" in the UI keeps the language the one people would reach for
themselves. The same split is available to any other label here if a
future review finds a term that's drifted or reads wrong.

## Suggestion engine, not auto-move

Consistent with how Item 6/7 treated auto-fill (fires once, only into
an empty field, never a silent overwrite): **the engine suggests, it
never moves an item on its own.** Two different trigger strengths:

- **Staleness-based suggestion** (`no_response` / Ghosted): once
  `days_since_activity` crosses a threshold for an `applied` or
  `interviewing` item, surface a one-click "Mark as Ghosted?" prompt —
  same shape as Checkpoint 5/6's date-applied suggestion. Given how
  close to universal no-response has become, this is less "we
  detected something surprising" and more "confirm the obvious now
  that enough time has passed."
- **Status-based suggestion** (`rejected` / TBNT): a `rejected`
  status is already a real signal, not a guess from silence, so this
  can suggest immediately (or even default) to `outcome: rejected`
  rather than waiting on a staleness clock.
- `role_frozen`, `withdrawn`, `offer_declined`, `offer_accepted` stay
  manual-only in v1 — none of these have a reliable automatic signal
  the app could detect (a company pulling a listing, or the user
  deciding to withdraw, aren't things a document or a timer can infer).

## Threshold: not yet calibrated against real data

The `days_since_activity` cutoff for the Ghosted suggestion should be
set from real numbers, the way Checkpoint 5's date patterns were set
from a real 461-PDF spot-check rather than guessed. `working-db.zip`
was checked for this and **cannot supply that number** — every item's
`last_activity` in that snapshot collapsed to the same 4-day gap
(re-zipping the folder reset every file's mtime, the exact failure
mode the README already warns about), and `date_applied` was empty on
all 77 overridden items in that copy. A real threshold needs a
`days_since_activity` pull against the live Mac tracker, not a
re-zipped snapshot, before this becomes a hard-coded default.

## Timeline / status_history integration

An outcome change is logged through the same `status_history` table
Item 7 built — an outcome becomes just another append-only transition,
so *when* something closed and *why* both stay on the Timeline
instead of disappearing the moment an item is marked closed or
archived. No new table needed; `status_history.status` already
accepts any effective-status string.

## A "Closed" view, separate from Archived

Pipeline stays limited to genuinely active statuses (`drafted` /
`applied` / `interviewing`). A new **Closed** view — filterable by
outcome — becomes the second home for everything that resolved, so
looking back at rejected/ghosted/withdrawn applications for patterns
doesn't require digging through Manage's Archived list, which today
reads more like a one-way, half-hidden trash can than a place worth
revisiting. Archiving remains available as a separate, later
declutter step on top of a Closed item, not a replacement for it.

## How outcomes fit Insights

- **Signal rate vs. Ghost rate.** Split what "response rate" currently
  conflates: **Signal rate** = (Rejected + Interviewing + Offer) ÷
  Applied — did a human ever engage — as a distinct metric from
  **Ghost rate**. This is the real resume/ATS-penetration signal the
  current single response-rate number can't isolate.
  `role_frozen` outcomes are excluded from both — a pulled req isn't a
  reflection of resume or interview quality, closer to a right-censored
  data point than a real result.
- **Outcome distribution chart**, for the Closed set specifically —
  Ghosted / TBNT / Frozen / Withdrew / Declined / Accepted as shares,
  instead of (or alongside) the current flat status-distribution
  chart.
- **Time-to-outcome, split by type**, not one blended velocity number.
  Median days-to-TBNT vs. median days-to-Ghosted-confirmation tells
  the user something concrete: if TBNT typically lands around 10 days,
  a live application quiet well past that is a much stronger Ghosted
  candidate than one at day 12.
- **Funnel view**: Applied → Interviewing → Offer → Accepted, as an
  actual conversion funnel rather than the current flat bar chart —
  Offer Declined shows up as leakage at the very last stage, which
  reads very differently from leakage at Applied → Interviewing.
- **Withdrawal-reason correlation** (loose, v2-ish): even a simple tag
  on why the user withdrew (red flags, bait-and-switch, bad
  take-home), cross-tabbed against company, could surface patterns
  like "I keep withdrawing from staffing agencies" — not required for
  v1, noted here so it isn't lost.

## Explicitly out of scope for v1

- Auto-moving anything without a click — see "Suggestion engine,
  not auto-move" above.
- Detecting `role_frozen`, `withdrawn`, `offer_declined`, or
  `offer_accepted` automatically from documents or timing — all four
  stay manual-entry only until (if ever) a real signal is found.
- A hard-coded staleness threshold — see "Threshold: not yet
  calibrated" above; needs real `days_since_activity` numbers first.
- Free-text withdrawal-reason tagging and its Insights correlation —
  noted as a later idea, not v1 scope.

## Open questions before implementation begins

1. Real `days_since_activity` distribution from the live tracker, to
   set the Ghosted-suggestion threshold instead of guessing.
2. Whether `rejected`'s existing manual-status value should be
   reused directly as the `outcome`, or kept as a separate field that
   merely defaults from it (affects whether existing `rejected`
   applications in the real 119-application dataset need a migration
   step or pick up the new field automatically).
3. Whether Closed is a new top-level view or a filtered mode of the
   existing Pipeline/Manage screens — a UI decision, not a data-model
   one, but worth settling before frontend work starts.
