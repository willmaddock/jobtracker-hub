# Notes from writing this suite

## Found while building test isolation, not from a bug report

`workspace._owned_siblings_dir()` decides where `create_workspace()`
(and the two "import into a new tracker" endpoints) put a brand-new
tracker folder. In packaged mode it's hard-coded:

```python
if IS_PACKAGED:
    docs_dir = Path.home() / "Documents" / "JobTracker Hub"
```

Every other piece of packaged-mode state (`workspaces.json`, each
workspace's DB pair) goes under `JOBTRACKER_STATE_DIR`, which is fully
overridable by an env var — that's what makes the rest of this test
suite possible without touching a real machine's real files. This one
path has no such override.

Practical effect: running `test_create_workspace` without the
`monkeypatch.setattr(ws_module, "_owned_siblings_dir", ...)` workaround
in that test would create a real `~/Documents/JobTracker Hub/…` folder
on whatever machine runs the suite — including a CI runner or a
teammate's laptop, not just yours.

This isn't a correctness bug for the shipped app (a user's own
`~/Documents` is exactly where you'd want an app-created tracker to
live), but it is a testability gap worth knowing about: any future
test, script, or CI job that exercises `create_workspace()` directly
(instead of going through the API with a monkeypatch, as this suite
does) will write to the real filesystem unless it remembers the same
workaround.

If this is ever worth fixing at the source: give
`_owned_siblings_dir()` the same `JOBTRACKER_*_DIR`-style env-var
override `STATE_DIR` already has, falling back to
`~/Documents/JobTracker Hub` only when unset. That would let this
suite (and any future one) drop the monkeypatch entirely.
