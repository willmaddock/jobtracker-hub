# Feature: Email Sync board v2 — enrichment, archive, stats, filters

Builds on `discoveries-kanban-spec.md` (Parts 1-4, shipped). This
covers what's missing now that the 3-column board is live and being
used against a real inbox (66+ discoveries).

## Why Job Postings cards feel thin right now

`discovered_matches` only ever stores what `search_unmatched_messages()`
captures: `message_id, subject, sender, received_at, guessed_company`.
Nothing from the email **body** is captured at discovery time — so a
Job Postings card has no posting URL, no location, no salary, nothing
except a truncated subject line and a raw timestamp. "View email"
works (it fetches the body live via `/preview`), but the card itself
can't show a link until something extracts one.

## Part 5 — Job Posting card enrichment

**Backend:**
- On `/preview` fetch (already fetches the body), run the existing
  `extract.extract_urls()` against the body text and return the first
  URL whose domain looks like a job board/ATS (linkedin.com/jobs,
  indeed.com, greenhouse.io, lever.co, myworkdayjobs.com, etc. —
  reuse/extend whatever domain list `guess_company_from_email` already
  treats as ATS domains) as `posting_url`.
- Cache it: add `posting_url TEXT` to `discovered_matches` (migration,
  same pattern as `kind`), fill it in lazily the first time a card is
  previewed or on `discover`, so repeat visits don't re-fetch.
- `received_at` is already stored — the fix here is display, not data.

**Frontend:**
- Job Postings card: relative "posted 3d ago" (compute from
  `received_at`) instead of/alongside the raw timestamp, plus an
  "Open posting ↗" link when `posting_url` is present, opening via the
  existing `open_url` allowed-scheme helper.
- When no URL is found in the body, show nothing rather than a dead
  button — don't fake a link.

## Part 6 — Archive (distinct from Dismiss)

Today "Dismiss" removes a discovery from the queue permanently with no
way to review it again. That's fine for spam/irrelevant senders, but
too destructive for "I saw this posting, I'm not applying, but I don't
want to lose the record."

- Add `status = 'archived'` alongside existing
  `pending / accepted / dismissed` in `discovered_matches`.
- New `POST /api/discoveries/{id}/archive`, mirrors `/dismiss` but sets
  `archived` instead. Board gets a 4th, collapsed-by-default column
  ("Archived") or a toggle ("Show archived") rather than a permanent
  column eating space.
- Bulk "Archive selected" alongside the existing "Dismiss selected".

## Part 7 — Stats bar (mirror Pipeline's Insights)

A thin bar above the board, same visual language as Pipeline's
insights cards:
- Total pending, Job Postings count, Needs Triage count, Applications
  resolved this session/today.
- Oldest unresolved discovery (age) — surfaces the "I have 66 of these
  piling up" problem directly instead of the user having to scroll.
- Per-account breakdown (which of the 6 mailboxes is generating the
  most noise) — useful since some accounts probably produce almost
  all the postings-column volume.

## Part 8 — Filtering

Reuse the existing filter-pill pattern from Pipeline:
- By account/mailbox (a company using 6 addresses wants to isolate one).
- By company (type-ahead, since Job Postings often cluster by company —
  KPMG/Comcast repeatedly).
- Date range on `received_at`.
- "Has posting link" vs "no link found" (helps triage which postings
  are actually actionable vs just noise).

## Suggested build order
1. Part 5 (link/date enrichment) — highest visible impact, unblocks
   "why can't I just click through to the job."
2. Part 6 (archive) — small, mechanical, same shape as existing
   dismiss/mark-posting endpoints.
3. Part 7 (stats bar) — presentation-only, no schema changes beyond
   what 5/6 already add.
4. Part 8 (filtering) — biggest frontend surface area, do last once
   the data it filters on (links, archive state) actually exists.
