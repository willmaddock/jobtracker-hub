# Django templates branch: plan

**Status:** approved by the owner on 2026-11-07 (plan, screen order and shell mockups). Commits and pushes still need the owner's go-ahead.
**Branch:** `feature/django-templates-app`, created from `feature/email-signin-theme`.
**Written from:** the uploaded zip of `feature/email-signin-theme` (no `.git` in the zip, so the commit was not checked).

## 1. Goal

Build JobTracker Hub as a normal Django app: models, views, templates, forms, admin and
tests. One hosted address, one login. Small amounts of JavaScript (htmx or plain JS) only
where a page needs it, such as Kanban drag-and-drop or live search.

## 2. Why a new branch

- The current plan ports the 8,700-line React file (`_app/frontend/index.html`) one slice
  at a time, with a design review, a browser-check suite and a Status update per slice.
  That is careful but slow.
- Django already has the hard parts: accounts, MFA, passkeys, emailed-code sign-in,
  workspaces, Applications, Categories, documents, postings, Trash and a large test suite.
- The old branches stay untouched as the fallback.

## 3. Reuse

- Models and migrations under `backend/` (accounts, applications, documents, postings,
  core, email_sync).
- Auth: sessions, MFA, passkeys and the email sign-in flow in `backend/accounts/`.
- Workspace ownership checks and the business logic already behind the API.
- Django admin as the operator tool.
- Existing Django tests. Run them before and after each change.
- `JobTracker_Hub_sign-in_mockups.html` as the visual starting point for sign-in pages.

## 4. Stop using on this branch

- The React `DjangoFoundation` UI and its browser-check suite.
- The per-slice Status document updates (replaced by the changelog in section 9).
- The legacy FastAPI app (`_app/api.py`) is not extended. It stays in the repo for
  reference.

## 5. Decisions that differ from `AGENTS.md` / Decisions on this branch

| Existing rule | On this branch |
|---|---|
| Preserve the existing UI, no redesign | UI is rebuilt as templates; look follows the mockups |
| Centralized API-client frontend | Server-rendered pages; DRF endpoints stay where they already work |
| Update `DJANGO_MIGRATION_STATUS.md` per checkpoint | One short changelog (section 9) |
| Gate every slice on explicit authorization | Owner approves the screen order once; each screen is a normal commit |

Owner should confirm each row. If the branch merges later, update Decisions on purpose
rather than let the docs and code drift apart.

## 6. Rules that still apply

- Explicit workspace scoping. A user must never see another user's workspace (return 404).
- Stable Django IDs, never filesystem paths, as identity.
- Trash preserves records and files; permanent deletion is explicit.
- Never touch real tracker data in tests; use fixtures.
- No secrets in the repo.
- No commit, push, merge or branch deletion without the owner's approval.
- Start fresh on the hosted instance. No importer for the macOS app's data for now
  (matches `docs/DEPLOYMENT.md`).

## 7. Screen inventory (what already backs each screen)

Endpoint and model names below come from `backend/*/urls.py` and `models.py` in the zip.
"Confirm" means not checked in detail.

| Screen | Existing backing | Notes |
|---|---|---|
| Sign in, email code, MFA | `auth/*` endpoints; `SignInCode`, `EmailCode`, `MfaDevice`, `PasskeyCredential` | Mockups exist; rebuild as templates |
| Workspaces (list, create, switch) | `WorkspaceViewSet`; `Workspace` | |
| Applications list and create | `application-list` (GET, POST) | Duplicate warnings per Decisions |
| Application detail | `application-detail`, `dossier`, `messages` | |
| Status override and notes | `application-override`, `bulk-override`; `Override`, `StatusHistory` | Manual status concurrency is a known gap |
| Documents on an Application | `application-documents`, `document-detail/rename/override` | Previews need work (PDF, text, DOCX) |
| Pipeline and Kanban | confirm: `BrowseView`, `ManageView` | Needs JavaScript for drag-and-drop |
| Search, attention, insights | `SearchView`, `AttentionView`, `InsightsView` | Search parity is a known gap |
| Categories | `category-list/detail/applications`, `application-category`; `CategoryMembership` | |
| Merge companies | `MergeView`, `UnmergeView`; `CompanyAlias` | |
| Trash and restore | confirm: `backend/core/lifecycle_views.py` | |
| Settings | `HubSettingsView`; `HubSettings` | |
| Postings | `job-posting-list` plus actions; `JobPosting` | Later |
| Retained email review | `application-review-*`; review models | Later |
| Email connect and sync | `backend/email_sync/` | Later, hardest and most operational |

## 8. Build order (placeholder, owner to confirm)

1. Base layout, theme tokens, top bar, avatar menu and sign-in pages.
2. Workspace list and switcher.
3. Applications list and create.
4. Application detail with status and notes.
5. Pipeline and Kanban.
6. Documents.
7. Search and attention.
8. Categories.
9. Trash and restore.

Later: postings, retained review, email connect.

Mock up only the new shell (step 1) and any screen the owner wants changed. The legacy app
is the reference for the rest.

## 9. Definition of done for each screen

- View, template and form, with validation errors shown on the page.
- Requires login and checks workspace ownership.
- Django test-client tests: happy path, validation failure, and a workspace-isolation
  test (another user gets 404).
- Does not import anything from the React file.
- Full Django test suite passes (`python manage.py test` from `backend/`).
- One entry added to the changelog below.

### Changelog

- 2026-11-07, step 1 (partial): new `backend/web/` app with base layout, theme tokens,
  sidebar, tracker menu, sign out and a read-only Pipeline page at `/app/`. The MFA
  middleware now also guards `/app/`. Anonymous visitors go to `/` until the template
  sign-in pages exist. Tests: `web.tests` (8 pass). Not yet done: template sign-in pages,
  workspace create, Pipeline filters, detail panel and Kanban.

## 10. Out of scope for now

Importing macOS-app data, offline or local sync, public signup beyond what email sign-in
already provides, a desktop wrapper, provider email sync.

## 11. Open questions

- Which screens does the owner use most? That sets the real build order.
- Keep the DRF endpoints long term, or retire them as pages replace them?
- Is `EMAIL_SIGNIN_SATISFIES_MFA` acceptable for production? (Open in `docs/MFA_DESIGN.md`.)

## 12. Not verified

Written from reading the zip, not from running it. Test counts, route names and model names
were taken from the files and are not a fresh test run.
