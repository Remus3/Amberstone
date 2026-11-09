"""Shared ``--check`` comparison for the four DS WIN-credit table builders.

S144-D-236. Each builder stamps ``_meta.ds_patch`` from
``data/daemon_slayer/current.txt`` when it builds, so a plain text compare
reported DRIFT from the first patch after a table was built, although nothing
in the table had changed (measured 2026-11-09: all three survivability tables,
built at 16.12.1, ``champions`` byte-equal to a fresh 16.22.1 build). The stamp
is provenance (the snapshot the table was built against); no loader reads it.
So ``--check`` keeps the COMMITTED stamp when the committed one is a string and
compares everything else byte for byte: content and format drift still fail.
Write mode is unchanged and stamps the patch it built at.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def render(table: dict) -> str:
    """The exact text a builder writes for ``table``."""
    return json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def committed_matches(out: Path, built: dict) -> bool:
    """True when ``out`` equals a fresh build, the provenance stamp aside."""
    try:
        cur = out.read_text(encoding="utf-8")
    except OSError:
        return False
    try:
        stamp = (json.loads(cur).get("_meta") or {}).get("ds_patch")
    except (ValueError, AttributeError):
        return False
    expected = copy.deepcopy(built)
    if isinstance(stamp, str) and isinstance(expected.get("_meta"), dict):
        expected["_meta"]["ds_patch"] = stamp
    return cur == render(expected)
