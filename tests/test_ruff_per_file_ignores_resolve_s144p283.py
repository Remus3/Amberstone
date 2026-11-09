"""S144-P-283 - every ruff.toml per-file-ignores key names a tracked file or matches at least one.

A per-file-ignore for a path that no longer exists lints nothing, but it reads as a live
baseline: a reader sees `tools/bridge_pull_tasks.py` carry a "frozen bridge tools" ignore and
goes looking for a frozen tool that ADR-012 removed (the bridge was decommissioned, commit
558552a2f). Worse, the key silently re-activates if a file of that name ever reappears.
Measured 2026-11-06: 6 of 27 keys matched zero tracked files (dashboard/routes_bridge_pending.py
and five tools/bridge_*.py); all six were dropped with this guard.

The rule: a key without a glob character is a tracked path; a key with one matches at least one
tracked path. `test_resolver_is_live` proves the resolver reports a dead literal and a dead glob
and accepts a live one, since an empty tracked set would otherwise pass for any reason.
"""
from __future__ import annotations

import fnmatch
import tomllib

from tests._repo_walk import REPO_ROOT, tracked_relpaths

_GLOB_CHARS = "*?["


def dead_keys(keys, tracked) -> list[str]:
    """Keys that name no tracked file: a literal not in the index, a glob matching nothing."""
    dead = []
    for key in keys:
        if any(ch in key for ch in _GLOB_CHARS):
            if not any(fnmatch.fnmatchcase(path, key) for path in tracked):
                dead.append(key)
        elif key not in tracked:
            dead.append(key)
    return dead


def _keys() -> list[str]:
    with (REPO_ROOT / "ruff.toml").open("rb") as fh:
        cfg = tomllib.load(fh)
    return list(cfg["lint"]["per-file-ignores"])


def test_every_per_file_ignore_key_resolves():
    tracked = tracked_relpaths()
    assert tracked, "git index unavailable - an empty set would call every key dead or none"
    keys = _keys()
    assert len(keys) > 10, f"ruff.toml per-file-ignores read as {len(keys)} keys; the parse lost them"
    assert "main.py" in keys and "main.py" in tracked
    dead = dead_keys(keys, tracked)
    assert not dead, (
        "ruff.toml per-file-ignores keys that match no tracked file (drop them, or say in the "
        f"commit why a file is expected back): {dead}"
    )


def test_resolver_is_live():
    tracked = frozenset({"core/a.py", "tools/ds_x.py"})
    assert dead_keys(["core/a.py"], tracked) == []
    assert dead_keys(["core/gone.py"], tracked) == ["core/gone.py"]
    assert dead_keys(["tools/ds_*.py"], tracked) == []
    assert dead_keys(["tools/zz_*.py"], tracked) == ["tools/zz_*.py"]
    assert dead_keys(["core/**"], tracked) == []
    assert dead_keys([], tracked) == []
