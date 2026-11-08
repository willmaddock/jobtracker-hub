# Gateway mode: Django sign-in in front of the original JobTracker app

`JTH_GATEWAY=true` (set in `backend/.env.example`) changes what happens after sign-in.

```
browser ──► Django (sign-in, email code, MFA, sessions)
              │  every /api/* request that is not /api/auth/*, /api/account/*, /api/health
              ▼
        gateway proxy ──► the signed-in user's own uvicorn process (127.0.0.1, random port, secret token)
                              runs _app/api.py unchanged, via _app/gateway_asgi.py
```

* `/` shows Django's sign-in and MFA screens until the session is fully verified, then serves the
  original UI. A "Sign out" button is added bottom-right; an expired session returns you to sign-in.
* Each user gets `jth-data/users/<id>/` (override with `JTH_DATA_DIR`) holding their own
  `state/` (tracker registry, indexes), `home/` (their tracker folders and uploaded documents)
  and `logs/app.log`. Processes start on first request, are shared by all web workers (file lock),
  and stop after `JTH_IDLE_MINUTES` idle: run `python manage.py jth_stop_backends` from cron, or
  `--all` to stop everything.
* The private process only answers requests carrying a per-process secret token, and starts with a
  minimal environment (no Django secrets or cloud credentials).

## Endpoints blocked on a server

`_app/gateway_policy.py` refuses, in both the proxy and the private process: `/api/open`,
`/api/open-url`, `/api/diagnostics*`, `/api/workspaces/import-folder-local`, everything under
`/api/accounts/` except listing (Mail.app sync needs macOS), and `/api/workspaces/link` + `/inspect`
(they read arbitrary server folders). The last two can be switched on for **superusers only** with
`JTH_ALLOW_LOCAL_LINK=true`, intended for running on your own computer so you can link an existing
JobTracker folder in place instead of uploading it.

## Getting your existing applications in

* On your own Mac: sign in as a superuser (`python manage.py createsuperuser`, then sign in with
  that account) with `JTH_ALLOW_LOCAL_LINK=true`, and use **Link existing folder**.
* On a server, or for any other user: use **Import** (zip of the tracker folder, or folder upload).

## Known limits

* Unix only (uses `fcntl`, process groups). Not for Windows hosting.
* Email sync via Mail.app is unavailable. Documents live on the server's disk, not the user's machine.
* Django's own workspace/applications API and `/app/` pages are not used in this mode.
* The Django data model and the original app's folders are separate stores; nothing syncs between them.
* Behind a TLS proxy set `JTH_MAX_UPLOAD_MB` and the proxy's body-size and timeout limits to match.
