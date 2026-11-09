"""S144-P-318 - no tracked ``.py`` has a mutable or call-built argument default, held at zero.

ruff.toml ignores B006 (mutable default argument) and B008 (function call in a default) for the WHOLE tree with the
comment "known pattern in project" / "used intentionally". Measured 2026-11-07 with ``ruff check --isolated
--select B006,B008`` over every tracked ``.py``: zero findings, so the waiver covers nothing today and a NEW
``def f(x=[])`` (one list shared by every call) or ``def f(t=time.time())`` (evaluated once at import) would enter
unseen. This pins zero without un-ignoring the rules in ruff.toml (which would also pull the config's other waivers
into scope): the ratchet runs ruff with NO config, so the waiver cannot hide a hit, over the tracked files only.

Fix a hit with the ``None`` sentinel (``def f(x=None): x = [] if x is None else x``) or a tuple / ``frozenset`` /
``types.MappingProxyType`` default. Nothing is grandfathered.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "B006,B008"


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_tracked_py_has_a_mutable_or_call_built_default():
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = _ruff([".", "--exclude", "data,logs,ops/runtime"])
    hits = []
    for d in found:
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            hits.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not hits, f"mutable / call-built argument default (use a None sentinel): {sorted(hits)}"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("def f(x=[]):\n    return x\n", "B006"),
        ("def f(x={}):\n    return x\n", "B006"),
        ("import time\n\n\ndef f(t=time.time()):\n    return t\n", "B008"),
    ],
)
def test_the_probe_is_live(code, expected):
    """The isolated run flags each shape (the repo config would hide it), so an empty tree result is a clean tree,
    not a dead probe."""
    found = _ruff(["--stdin-filename", "x.py", "-"], stdin=code)
    assert [d["code"] for d in found] == [expected]


def test_the_safe_spellings_are_not_flagged():
    code = (
        "def f(x=None, y=(), z=frozenset()):\n"
        "    return [] if x is None else x, y, z\n"
    )
    assert _ruff(["--stdin-filename", "x.py", "-"], stdin=code) == []


def test_ruff_toml_still_waives_both_rules():
    """This ratchet exists because ruff.toml waives B006 and B008; if the waiver is lifted the ordinary lint covers
    it and this file should be retired, not left as a second copy."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    ignore_block = text.split("ignore = [", 1)[1].split("]", 1)[0]
    assert '"B006"' in ignore_block
    assert '"B008"' in ignore_block
