"""RM-292 (b): the TFT PBE coach subsystem is retired (DELETE verdict).

Adjudicated 2026-10-25 (session 134 slice S3, read-only adjudicator):
`coaches/tft_pbe_coach.py` and `tft/tft_pbe_engine.py` were reachable only
through `coaches/__init__.py` `load_coach`, which had ZERO callers since the
initial commit. Production builds TFT in `app/_game_lifecycle.py`
`on_game_start` from `core/coach_registry.py` `MODE_COACH_MAP["_tft_mode"]`,
the literal `coaches.tft_coach`, and reads no `tft_pbe` flag. The live config
carried `tft_pbe: true` yet the PBE data files the constructor creates never
existed, no dashboard / web file read them, and the live TFT path already
covers Double Up and the Set 17 Realm of the Gods round schedule.

What this pins:
  1. both modules are gone from the git index and are not importable;
  2. `coaches/__init__.py` carries no dynamic loader (the dead
     `load_coach` / `unload_all` / `_MODE_MAP` / `_PREFIX_MAP` / `_is_tft_pbe`);
  3. no tracked source imports either module, statically or by string
     (anchored: the scan must see the live TFT route's own files, and its
     pattern must match a known positive);
  4. the live TFT route is untouched (positive control);
  5. `tft/tft_pbe_data.py` STAYS - `tft/tft_state_reader.py` round_schedule
     and `tft/tft_roll_odds.py` read it;
  6. a legacy `tft_pbe` key in `config/coach_settings.json` is still
     TOLERATED by the validator (the operator's live config carries it, and
     an unknown or legacy key must not break startup).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests import _repo_walk  # noqa: E402

_RETIRED_FILES = ("coaches/tft_pbe_coach.py", "tft/tft_pbe_engine.py")
_RETIRED_MODULES = ("coaches.tft_pbe_coach", "tft.tft_pbe_engine")
_DEAD_LOADER_NAMES = ("load_coach", "unload_all", "_MODE_MAP", "_PREFIX_MAP",
                      "_is_tft_pbe", "_loaded")

# An import of a retired module: `import x`, `from x import`, `from pkg
# import mod` (one line, or a parenthesised list spanning lines - `[^)]`
# crosses newlines), or the module path as a quoted string (importlib /
# __import__ / PyInstaller hiddenimports / sys.modules lookups).
_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+(?:coaches\.tft_pbe_coach|tft\.tft_pbe_engine)\b"
    r"|^\s*from\s+(?:coaches\s+import\s+.*\btft_pbe_coach\b"
    r"|tft\s+import\s+.*\btft_pbe_engine\b)"
    r"|^\s*from\s+(?:coaches\s+import\s*\([^)]*\btft_pbe_coach\b"
    r"|tft\s+import\s*\([^)]*\btft_pbe_engine\b)"
    r"|[\"'](?:coaches\.tft_pbe_coach|tft\.tft_pbe_engine)[\"']",
    re.MULTILINE,
)

# This guard's OWN scope exemptions, each with its reason.
_SCAN_EXEMPT = {
    # This file names the retired modules as data.
    "tests/test_rm292b_pbe_coach_retired.py",
    # FROZEN (CLAUDE.md frozen list). `RESTART_ONLY_MODULES` holds the name
    # in a frozenset nothing reads (only SAFE_RELOAD_MODULES is consulted),
    # so the stale string is inert; editing it needs operator approval.
    "ops/rc_dev_runtime.py",
}


def _tracked() -> frozenset[str]:
    tracked = _repo_walk.tracked_relpaths(str(_ROOT))
    # Fail closed, never skip: an unreadable index must not turn this guard
    # into an always-passing one (tests/test_skip_condition_hygiene.py).
    assert tracked is not None, "git index unreadable - cannot measure the tracked set"
    return tracked


def test_retired_files_are_out_of_the_index_and_off_disk() -> None:
    tracked = _tracked()
    for rel in _RETIRED_FILES:
        assert rel not in tracked, f"{rel} is still tracked"
        assert not (_ROOT / rel).exists(), f"{rel} is still on disk"


@pytest.mark.parametrize("module", _RETIRED_MODULES)
def test_retired_modules_are_not_importable(module: str) -> None:
    sys.modules.pop(module, None)
    assert importlib.util.find_spec(module) is None


def test_coaches_package_carries_no_dynamic_loader() -> None:
    import coaches

    coaches = importlib.reload(coaches)
    leftover = [n for n in _DEAD_LOADER_NAMES if hasattr(coaches, n)]
    assert leftover == [], f"coaches/__init__.py still defines {leftover}"
    src = (_ROOT / "coaches" / "__init__.py").read_text(encoding="utf-8")
    assert "coach_settings" not in src
    assert "tft_pbe" not in src


def test_import_pattern_matches_known_positives() -> None:
    """Anchor: an empty-matching pattern would make the scan pass vacuously."""
    positives = (
        "from tft.tft_pbe_engine import TftPbeCoachEngine\n",
        "import coaches.tft_pbe_coach as m\n",
        "    from coaches import tft_pbe_coach\n",
        "from tft import tft_pbe_engine as eng\n",
        "from coaches import (\n    tft_coach,\n    tft_pbe_coach,\n)\n",
        "from tft import (tft_data,\n                 tft_pbe_engine)\n",
        '    "coaches.tft_pbe_coach",\n',
        "importlib.import_module('tft.tft_pbe_engine')\n",
    )
    for text in positives:
        assert _IMPORT_RE.search(text), text
    negatives = (
        "from tft import tft_pbe_data as d\n",
        "from tft.tft_pbe_data import BOON_ROUND\n",
        '    "coaches.tft_coach",\n',
        "from tft import (\n    tft_pbe_data,\n)\nx = 'tft_pbe_engine'\n",
    )
    for text in negatives:
        assert not _IMPORT_RE.search(text), text


def test_no_tracked_source_imports_a_retired_module() -> None:
    files = _repo_walk.repo_files(_ROOT, patterns=("*.py", "*.js", "*.mjs",
                                                   "*.spec", "*.ps1"))
    rels = {_repo_walk.relative_posix(p, _ROOT) for p in files}
    # Anchor: the walk must reach the live TFT route, or a clean result is
    # a claim about an empty enumeration.
    for anchor in ("core/coach_registry.py", "coaches/tft_coach.py",
                   "app/_game_lifecycle.py", "tools/amberstone.spec"):
        assert anchor in rels, f"scan did not reach {anchor}"
    hits = []
    for path in files:
        rel = _repo_walk.relative_posix(path, _ROOT)
        if rel in _SCAN_EXEMPT:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in _IMPORT_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{rel}:{line}: {m.group(0).strip()}")
    assert hits == [], "retired PBE module still imported:\n" + "\n".join(hits)


def test_live_tft_route_is_untouched() -> None:
    from core.coach_registry import MODE_COACH_MAP

    module, cls, data = MODE_COACH_MAP["_tft_mode"]
    assert (module, cls, data) == ("coaches.tft_coach", "Coach",
                                   "tft_coaching_data.json")
    assert importlib.util.find_spec(module) is not None


def test_pbe_data_tables_stay_for_their_live_callers() -> None:
    assert importlib.util.find_spec("tft.tft_pbe_data") is not None
    reader = (_ROOT / "tft" / "tft_state_reader.py").read_text(encoding="utf-8")
    assert "tft_pbe_data" in reader


def test_legacy_tft_pbe_key_is_still_tolerated(tmp_path: Path,
                                               monkeypatch) -> None:
    from core import config_validator as cv

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "coach_settings.json").write_text(json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "debounce_seconds": 15,
        "timeout": 20,
        "max_tokens": 700,
        "tft_pbe": True,
    }), encoding="utf-8")
    monkeypatch.setattr(cv, "APP_DIR", tmp_path)
    result = cv._validate_coach_settings()
    assert result.status == "OK", result
