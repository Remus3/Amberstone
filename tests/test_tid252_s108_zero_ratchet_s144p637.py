"""S144-P-637 - TID252 and S108 held at zero over the tracked ``.py``.

``ruff.toml`` selects only E, F, I, UP, B and BLE. Two more codes measured 18 findings on 2026-11-09
(``ruff check --isolated --target-version py39``, every tracked ``.py``) and all 18 were fixed in the same slice:

- TID252 (11 hits, two Daemon Slayer test modules): a relative import from a parent package (``from .. import x``).
  The other 480-odd Daemon Slayer tests import ``agents.daemon_slayer`` absolutely; a relative parent import ties a
  test to the directory it sits in and breaks when the module is run as a script or moved.
- S108 (7 hits, four root test modules): a hardcoded ``/tmp/...`` path literal. Each was a pure path-arithmetic or
  rejection fixture (``out_dir_for`` joins, a containment check) that never touches the filesystem, so the literal
  became a non-temp absolute string (``/override/whatever``, ``/srv/rc_escape.txt``). A literal that names a real
  scratch location belongs under ``tmp_path``, never ``/tmp``.

The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding, and each rule carries a positive
control so a rule a future ruff stops firing (or removes) fails loudly instead of passing for nothing. Nothing is
grandfathered: fix a hit, never widen the list.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

# code -> source linted from stdin.
_PROBES: dict[str, str] = {
    "TID252": "from .. import server\n",
    "S108": "path = '/tmp/scratch.txt'\n",
}
_RULES = ",".join(_PROBES)


def _ruff(rules: str, args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", rules, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure (for instance a removed rule code).
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_no_tracked_py_trips_tid252_or_s108():
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 500, "the tracked-file walk returned almost nothing"
    found = _ruff(_RULES, [".", "--exclude", "data,logs,ops/runtime"])
    hits = []
    for d in found:
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            hits.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not hits, f"ruff rule hit (fix the site, do not widen the list): {sorted(hits)}"


@pytest.mark.parametrize("code", sorted(_PROBES))
def test_each_rule_fires_on_its_pattern(code):
    """A positive control per rule: a rule that silently stopped firing would pass the ratchet for nothing."""
    found = _ruff(code, ["--stdin-filename", "probe.py", "-"], stdin=_PROBES[code])
    assert code in {d["code"] for d in found}, (code, found)


def test_the_rules_are_not_in_ruff_toml_select():
    """If ruff.toml ever selects one of these, this ratchet is redundant for it - say so instead of drifting."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    select = text.split("select = [", 1)[1].split("]", 1)[0]
    chosen = {line.split('"')[1] for line in select.splitlines() if '"' in line}

    # A selector covers a code only inside the SAME linter: ruff's "S" (bandit) is not "SIM".
    def _linter(name: str) -> str:
        return re.match(r"[A-Z]+", name).group()

    overlap = sorted(c for c in _PROBES
                     if any(c.startswith(s) and _linter(c) == _linter(s) for s in chosen))
    assert not overlap, f"ruff.toml already selects these rules: {overlap}"
