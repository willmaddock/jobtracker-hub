# Deployment and migration options (gateway branch)

| | |
|---|---|
| Written | 2026-11-08, against `feature/gateway` at `17dcef6` |
| Purpose | Record where the branch stands, the paths forward, and what is and is not verified, so a later audit can see why a path was chosen |
| Method | Static reading of the repository, plus AWS and Django documentation fetched on the date above |
| Not done | The Docker image was not built, nothing was deployed, and no AWS service was contacted. Every statement tagged **[read]** comes from reading files; **[src]** from a cited document; **[inferred]** is reasoning that has not been tested |

## 1. Where the branch stands

Two different designs currently live in one repository. They do not fit together yet.

**Design A: gateway mode** (`JTH_GATEWAY=true`, `docs/GATEWAY.md`)
- Django handles sign-in, emailed codes, MFA and passkeys, then proxies `/api/*` to a private copy of the original FastAPI app for each user. [read]
- Each user's trackers, databases and uploaded documents live on the server's local disk under `JTH_DATA_DIR/users/<id>/`. [read]
- Each user gets their own `uvicorn` process bound to `127.0.0.1` on a random port. Several web workers coordinate through a file lock and `backend.json`. Unix only (`fcntl`). Idle processes stop only when `jth_stop_backends` runs (for example from cron). [read: `backend/gateway/backends.py`, `docs/GATEWAY.md`]
- Works end to end locally: sign-in, MFA, passkey registration and sign-in, import, and the new-account 409 fix were exercised in a browser on 2026-11-08. 12 gateway tests passed earlier the same day.

**Design B: the Django migration** (`docs/DJANGO_MIGRATION_*.md`, `docs/DEPLOYMENT.md`)
- Application data moves into Django models on PostgreSQL, with documents in S3. Accounts are created by an administrator; the doc records "start fresh on the hosted instance". [read]
- `prod.py` has fail-closed settings, S3 storage with 5-minute signed links, forced MFA, and a proxy-aware HTTPS setup. [read]
- `docs/DEPLOYMENT.md` states plainly: image not built; nothing run against RDS, S3, Redis or an ALB; no staging deploy; production gates in Status §10 still open. [read]

### Gaps found between A and B
1. **Gateway mode is not wired into the deployment scaffolding.** No `JTH_*` variable appears in `prod.py`, `deploy/env.example`, `docker-compose.local.yml` or the `Dockerfile`. [read]
2. **Likely write failure in the container.** `JTH_DATA_DIR` defaults to `<repo>/jth-data`, i.e. `/app/jth-data`, while the image runs as the non-root `app` user and `/app` is created by root. [inferred; not tested]
3. **S3 does not cover gateway data.** The S3 settings apply to Django's own file storage. Gateway users' documents are written by the private process to local disk. [read]
4. **More than one container cannot share users.** Each private process listens on that container's own `127.0.0.1`, and the port is recorded in a shared file. A second container reading that file would connect to its own loopback. [inferred]
5. **Stale docs.** `README.md` and `docs/DEPLOYMENT.md` name `docker-compose.yml`; the file in the repo is `docker-compose.local.yml`. [read]
6. **Sign-up policy differs.** `DEPLOYMENT.md` assumes administrator-created accounts and no signup; the local compose file turns on `EMAIL_SIGNUP_OPEN` so an unknown address creates an account. [read]
7. **Other branches ride along.** `feature/gateway` sits on top of `feature/django-templates-app` and `feature/email-signin-theme`; merging it brings their commits to `main`. The long-running `django-migration` branch described in the status docs has not been compared with this branch. [read: `git log main..feature/gateway`]

## 2. External facts used (fetched 2026-11-08)

- **AWS App Runner is closed to new customers.** Existing customers can keep using it; AWS plans no new features. AWS recommends Amazon ECS Express Mode, which provisions a Fargate service, an ALB, autoscaling and networking from a container image, with no extra charge beyond the resources. [src: AWS App Runner availability change, https://docs.aws.amazon.com/ja_jp/apprunner/latest/dg/apprunner-availability-change.html] → App Runner is not an option for a new project.
- **ECS storage.** On Fargate the usable options are EBS, EFS, S3 Files, bind mounts and FSx for NetApp ONTAP (via S3 Access Points). EFS is persistent and shared; bind mounts are ephemeral; EBS is persistent only for standalone tasks and ephemeral for tasks maintained by a service. [src: https://docs.aws.amazon.com/AmazonECS/latest/userguide/using_data_volumes.html]
- **Lightsail Linux bundles with IPv4** (monthly): 1 GB / 2 vCPU / 40 GB, $7; 2 GB / 2 vCPU / 60 GB, $12; 4 GB / 2 vCPU / 80 GB, $24; 8 GB / 2 vCPU / 160 GB, $44. Each includes a data-transfer allowance; prices vary only with the bundle. [src: https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.md]
- **Django deployment checklist:** run `manage.py check --deploy`; never use `runserver`; keep `SECRET_KEY` out of source control; `DEBUG` off; `ALLOWED_HOSTS` set; enforce HTTPS and secure cookies; treat uploads as untrusted; back up the database; configure logging and error reporting. [src: https://django.readthedocs.io/en/6.0.x/howto/deployment/checklist.html]
- **Not researched:** EC2 pricing, RDS pricing, EFS performance with file locks, per-user memory use of the private process, and security-audit requirements for hosting other people's documents.

## 3. Options

### Option 1: one server, gateway mode as built (Lightsail or EC2)
- **Shape:** one Linux instance with a persistent disk; Django behind a reverse proxy with TLS; `jth_stop_backends` on a cron timer; disk snapshots as the backup.
- **Fits because:** it matches how gateway mode already works (local disk, loopback processes, one host).
- **Cost (Lightsail, from the table above):** about $12–$24 a month for 2–4 GB. Whether that holds N concurrent users depends on the memory of one private process, which has not been measured.
- **Work needed:** make the container or host data path writable; set the `JTH_*` variables; pick Postgres or SQLite for the Django side; TLS and domain; backups; the Django checklist.
- **Limits:** a single point of failure, no horizontal scaling, Unix only, and user documents on one disk.
- **Good for:** you plus a small number of known users.

### Option 2: ECS Express Mode or Fargate, gateway mode with EFS
- **Shape:** one task with an EFS volume for `JTH_DATA_DIR`; RDS for Django.
- **Fits partly:** state survives restarts. But see gap 4: it must stay at one task. [inferred] Whether the gateway's file lock behaves correctly on EFS is unknown and needs a test.
- **Verdict:** more moving parts than Option 1 for no gain in capacity. Not recommended unless there is a reason to be on ECS.

### Option 3: finish the Django migration (Design B)
- **Shape:** the stateless container in `docs/DEPLOYMENT.md`: web, Celery worker, Celery beat, RDS, Redis, S3 behind an ALB. Express Mode is AWS's current simple path to run the container.
- **Work needed:** the application features still have to be ported from the FastAPI app into Django (the migration docs track this slice by slice); build and test the image; staging; the open Status §10 gates (backup/restore, cutover, rollback, scale).
- **Good for:** a real multi-user hosted product. It is the largest option and not near done.

### Option 4: stay local or desktop
- Gateway mode already works on one computer, with `JTH_ALLOW_LOCAL_LINK=true` to link an existing folder in place. No hosting work.

## 4. Recommendation (not a decision)
Option 1 if something needs to be online soon; treat Option 3 as the longer-term replacement. Skip Option 2 and App Runner. Decision owner: **William Maddock**. Record the decision in §6.

## 5. Checklist before any real user
- [ ] `manage.py check --deploy` against the production settings, output saved
- [ ] Docker image builds; container starts as the non-root user; data directory writable
- [ ] Gateway tests pass (`pytest`), and the full suite is run once on the target Python version
- [ ] Per-user private process memory measured; instance size chosen from that
- [ ] HTTPS end to end, then HSTS enabled (`docs/DEPLOYMENT.md` records HSTS as deliberately deferred until HTTPS works end to end)
- [ ] Real email sending configured (the product currently prints sign-in codes to the console in dev); sign-up policy decided (open or invite only)
- [ ] Backups and a restore test of the data disk or database
- [ ] `jth_stop_backends` scheduled
- [ ] Diagnostics row and other blocked endpoints confirmed hidden in a browser (the hide-diagnostics change is not browser-tested)
- [ ] `README.md` and `docs/DEPLOYMENT.md` compose filename corrected; README clone line fixed at merge
- [ ] `feature/gateway` reconciled with `main` and with `django-migration` before merge

## 6. Decision log (to complete)
| Date | Decision | Decided by | Notes |
|---|---|---|---|
| | Hosting option chosen | | |
| | Sign-up policy | | |
| | Where user documents live | | |

## 7. Open questions
- Who will use the hosted copy, and how many at once?
- Should user documents ever be on S3 in gateway mode? That needs code changes to the private app, not just settings.
- Does the `django-migration` branch supersede gateway mode?
- What are the data-protection duties for hosting other people's job-search documents?
