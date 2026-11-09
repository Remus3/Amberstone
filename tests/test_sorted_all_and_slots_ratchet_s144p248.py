"""RM-1747 - ruff RUF022 (unsorted ``__all__``) and RUF023 (unsorted ``__slots__``) held at zero in the held scope.

Not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated`` (target py39) over the tracked tree: 85
findings in total, 13 of them in 12 modules outside every fenced area. This slice sorted those 12 modules (ruff's own
fix; the order of an ``__all__`` or ``__slots__`` carries no meaning for an import or an attribute lookup):

- ``tools/``: ``gated_g312_aram_debounce_lag`` (``__all__``), ``laning_verdict_information_probe`` (``_Pair.__slots__``),
  ``live_write_tracer`` (``_CountingHandle.__slots__``), ``md_guard_selector`` (``_Scope.__slots__``).
- ``lib/http/``: ``__init__`` (``__all__``) and ``client`` (``Response`` and ``_HostState`` slots).
- ``tft/tft_roll_odds``, ``game_reader/__init__``, ``vision_server/__init__``, ``agents/supervisor`` and the two agent
  ``__init__`` modules (``__all__``).

HELD here: ``tools/``, ``lib/``, ``tft/``, ``game_reader/``, ``vision_server/`` and ``agents/`` outside
``agents/daemon_slayer/``. NOT held (still carry findings, each for a named reason): ``agents/daemon_slayer/`` (the DS
lane's files, 41 rows), ``core/`` (27 rows in 24 modules, including frozen ``core/game_snapshot.py``; the next slice),
``ops/fleet_kit/`` (vendored byte-for-byte), ``ops/audit/``, ``oss/`` (a separate package) and one ``tests/`` module.
The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. The held scope has no baseline.
"""
from __future__ import annotations

import collections
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

_RULES = ("RUF022", "RUF023")
_HELD = ("tools/", "lib/", "tft/", "game_reader/", "vision_server/", "agents/")
_NOT_HELD = ("agents/daemon_slayer/",)
_FIXED = (
    "agents/agent2_backend/pipeline/__init__.py",
    "agents/agent4_coach_mentor/__init__.py",
    "agents/supervisor.py",
    "game_reader/__init__.py",
    "lib/http/__init__.py",
    "lib/http/client.py",
    "tft/tft_roll_odds.py",
    "tools/gated_g312_aram_debounce_lag.py",
    "tools/laning_verdict_information_probe.py",
    "tools/live_write_tracer.py",
    "tools/md_guard_selector.py",
    "vision_server/__init__.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len([t for t in tracked if t.startswith("tools/")]) > 50, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["tools", "lib", "tft", "game_reader", "vision_server", "agents"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_HELD) and not rel.startswith(_NOT_HELD):
            counts[rel] += 1
    return dict(counts)


def test_held_scope_has_no_unsorted_all_or_slots(held_counts):
    assert not held_counts, f"ruff {_RULES} findings in the held scope, file: count: {held_counts}"


def test_the_fixed_modules_are_tracked_and_in_the_held_scope():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert rel.startswith(_HELD) and not rel.startswith(_NOT_HELD), rel


@pytest.mark.parametrize(
    ("rule", "probe"),
    [
        ("RUF022", "__all__ = ['b', 'a']\n"),
        ("RUF023", "class C:\n    __slots__ = ('b', 'a')\n"),
    ],
)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"] == rule for d in found), (rule, [d["code"] for d in found])
