#!/usr/bin/env python3
"""One-off cleanup for trackers created before the double-prefix fix.

Before that fix, picking an existing app-owned tracker folder (already
named "JobTracker — <name>") as an import source -- e.g. via the
packaged app's native "Choose a folder instead" -- could feed that
whole prefixed name back in as the *new* tracker's name. The backend
would then prepend "JobTracker — " again, producing a folder (and
registry entry) named "JobTracker — JobTracker — <name>", compounding
further on every subsequent export/reimport.

This script finds any *owned* workspace whose name or root folder
carries that repeated prefix, collapses it back down to a single
prefix, and renames the folder on disk to match. It is always safe to
touch these folders because "owned" means the app created them --
they're copies, never the user's original documents in place (see
workspace.delete_workspace's docstring for the same reasoning). It
never touches "linked" workspaces, which point at a folder in place --
their root is never renamed regardless of what its name looks like.

Usage:
    Quit JobTracker Hub first (so nothing else has the registry file
    open while this runs), then:

        python3 scripts/fix_doubled_tracker_names.py            # dry run, shows what it would do
        python3 scripts/fix_doubled_tracker_names.py --apply    # actually renames things

    By default it looks at the same packaged-mode state directory the
    app itself uses (~/Library/Application Support/JobTracker Hub on
    macOS). Pass --state-dir to point it elsewhere (e.g. a dev-mode
    _app/ folder), or set JOBTRACKER_STATE_DIR the same way the app
    does.

A timestamped backup of workspaces.json is written next to the
original before anything is changed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PREFIX = "JobTracker — "


def default_state_dir() -> Path:
    env = os.environ.get("JOBTRACKER_STATE_DIR")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "JobTracker Hub"
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "JobTracker Hub"
    return Path.home() / ".local" / "share" / "JobTracker Hub"


def collapse_prefix(name: str) -> str:
    """Strips *every* leading repetition of "JobTracker — ", not just
    one -- a name could in principle have compounded more than once
    across several export/reimport cycles before this was caught."""
    while name.startswith(PREFIX):
        rest = name[len(PREFIX):].strip()
        if not rest:
            break
        name = rest
    return name


def unique_dest(parent: Path, base_name: str) -> Path:
    """Same collision handling as workspace._new_sibling_root: append
    " (2)", " (3)", ... until a not-yet-existing path is found."""
    dest = parent / f"{PREFIX}{base_name}"
    suffix = 2
    while dest.exists():
        dest = parent / f"{PREFIX}{base_name} ({suffix})"
        suffix += 1
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", type=Path, default=None,
                         help="Override the JobTracker Hub state directory (default: auto-detect, same as the app).")
    parser.add_argument("--apply", action="store_true",
                         help="Actually make changes. Without this flag, only prints what would happen.")
    args = parser.parse_args()

    state_dir = args.state_dir or default_state_dir()
    registry_path = state_dir / "workspaces.json"

    if not registry_path.exists():
        print(f"No registry found at {registry_path} -- nothing to do.")
        return 0

    data = json.loads(registry_path.read_text())
    workspaces = data.get("workspaces", {})

    changed = False
    actions: list[str] = []

    for ws_id, entry in workspaces.items():
        if entry.get("kind") != "owned":
            continue  # never touch a linked (user-owned) folder's root

        old_name = entry.get("name", "")
        new_name = collapse_prefix(old_name)

        old_root = Path(entry["root"])
        old_root_basename = old_root.name
        new_root_basename = collapse_prefix(old_root_basename)
        # A bare app-owned root's basename is always "JobTracker — <name>"
        # -- re-add exactly one prefix's worth once collapsed.
        if not new_root_basename.startswith(PREFIX):
            new_root_basename = f"{PREFIX}{new_root_basename}"

        name_changed = new_name != old_name
        root_changed = new_root_basename != old_root_basename

        if not name_changed and not root_changed:
            continue

        changed = True
        new_root = old_root
        if root_changed:
            if old_root.exists():
                new_root = unique_dest(old_root.parent, new_root_basename[len(PREFIX):])
                actions.append(f"[{ws_id}] rename folder:\n    {old_root}\n -> {new_root}")
                if args.apply:
                    old_root.rename(new_root)
            else:
                actions.append(f"[{ws_id}] root folder missing on disk ({old_root}) -- registry entry will still be corrected, but nothing to rename.")

        if name_changed:
            actions.append(f"[{ws_id}] rename entry: {old_name!r} -> {new_name!r}")

        entry["name"] = new_name
        entry["root"] = str(new_root)

    if not changed:
        print("No doubled-prefix trackers found -- nothing to do.")
        return 0

    print("Planned changes:\n")
    for a in actions:
        print(a)
        print()

    if not args.apply:
        print("Dry run only -- nothing was changed. Re-run with --apply to make these changes.")
        return 0

    backup_path = registry_path.with_name(
        f"workspaces.json.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(registry_path, backup_path)
    registry_path.write_text(json.dumps(data, indent=2))

    print(f"Done. Registry backup saved to {backup_path}.")
    print("Restart JobTracker Hub, then click \"Rebuild index\" on the affected tracker(s) once it's open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
