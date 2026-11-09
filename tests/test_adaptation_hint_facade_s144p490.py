"""S144-P-490 - coaches/adaptation_hint.py is a facade; pin that every name it re-exports is the real one.

``coaches/adaptation_hint.py`` is the former 1602-line monolith, split by concern (AUTONOMOUS_AUDIT spec 4.C).
Its 33 re-exports (34 imported names with ``main``) are all "unused" to ruff F401, and ``tests/test_unused_import_ratchet_s144p108.py`` carries them as a
deliberate-facade baseline row, so lint cannot tell a live re-export from a stale one. Nothing else pinned the contract
the module docstring states:

* every public and semi-public name of a split module is reachable as ``coaches.adaptation_hint.<name>`` and IS the
  split module's object (not a copy, not a stale rebinding);
* a name the facade imports still exists in its source module (a rename in a split module would otherwise break the
  facade import at module load and every coach that imports it);
* ``DB_DIR`` monkeypatched on the FACADE redirects ``_adaptation_common._db`` (the test-suite patch contract the
  docstring names), because ``_db`` resolves the directory off the facade at call time.

The checker reads the facade by AST (no import side effects for the census) and the identity checks import it once.
A control proves the census flags a facade that dropped a name.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT

_FACADE_REL = "coaches/adaptation_hint.py"

# split module -> the names the facade must re-export from it (public + the semi-public underscore names the facade
# docstring promises). Pinned EXACTLY: a name added to or removed from the facade imports must be added here.
_EXPECTED: dict[str, tuple[str, ...]] = {
    "coaches._adaptation_common": (
        "DB_DIR",
        "SUPPORTED_MODES",
        "_DEFAULT_TOP_COUNTERS",
        "_MIN_ABSOLUTE_DELTA",
        "_MIN_SAMPLE",
        "_PROJECT_ROOT",
        "_db",
        "_start_of_today_iso",
        "logger",
    ),
    "coaches.adaptation_hint_aggregates": ("kda_trends", "top_champions"),
    "coaches.adaptation_hint_champion": ("for_champion", "format_hint_line", "insight_card", "matchup_delta"),
    "coaches.adaptation_hint_cli": (
        "_SEVERITY_BAND",
        "_format_day_of_week_text",
        "_format_digest_text",
        "_format_duration_text",
        "_format_games_text",
        "_format_session_text",
        "_format_time_of_day_text",
        "_format_trends_text",
        "_parse_since",
        "_severity_tag",
        "main",
    ),
    "coaches.adaptation_hint_digest": ("coaching_digest",),
    "coaches.adaptation_hint_session": ("session_games", "session_summary"),
    "coaches.adaptation_hint_temporal": (
        "_DURATION_TIERS",
        "_WEEKDAY_NAMES",
        "day_of_week_analysis",
        "duration_analysis",
        "time_of_day_analysis",
    ),
}

# Public top-level functions of a split module that the facade deliberately does NOT re-export (none today).
_PUBLIC_NOT_EXPORTED: dict[str, frozenset[str]] = {}


def _facade_imports(source: str) -> dict[str, set[str]]:
    """module -> set of imported names, over the top-level ``from X import ...`` statements of the facade."""
    out: dict[str, set[str]] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("coaches."):
            out.setdefault(node.module, set()).update(a.name for a in node.names)
    return out


def _census_problems(source: str) -> list[str]:
    got = _facade_imports(source)
    want = {mod: set(names) for mod, names in _EXPECTED.items()}
    problems: list[str] = []
    for mod in sorted(set(got) | set(want)):
        missing = want.get(mod, set()) - got.get(mod, set())
        extra = got.get(mod, set()) - want.get(mod, set())
        if missing:
            problems.append(f"{mod}: facade dropped {sorted(missing)}")
        if extra:
            problems.append(f"{mod}: facade imports unpinned {sorted(extra)}")
    return problems


def _facade_source() -> str:
    return (REPO_ROOT / _FACADE_REL).read_text(encoding="utf-8")


def test_facade_imports_are_the_pinned_set() -> None:
    assert _census_problems(_facade_source()) == []


def test_census_flags_a_dropped_and_an_unpinned_name() -> None:
    """Positive control: the census is not vacuous."""
    src = _facade_source()
    dropped = src.replace(
        "from coaches.adaptation_hint_session import session_games, session_summary\n",
        "from coaches.adaptation_hint_session import session_summary\n",
    )
    assert dropped != src
    assert any("dropped ['session_games']" in p for p in _census_problems(dropped))
    extra = src + "\nfrom coaches.adaptation_hint_digest import _call\n"
    assert any("unpinned ['_call']" in p for p in _census_problems(extra))


@pytest.mark.parametrize("module", sorted(_EXPECTED))
def test_every_reexport_is_the_split_modules_own_object(module: str) -> None:
    facade = importlib.import_module("coaches.adaptation_hint")
    source = importlib.import_module(module)
    for name in _EXPECTED[module]:
        assert hasattr(source, name), f"{module} no longer defines {name}"
        assert getattr(facade, name) is getattr(source, name), f"facade.{name} is not {module}.{name}"


@pytest.mark.parametrize("module", [m for m in sorted(_EXPECTED) if m != "coaches._adaptation_common"])
def test_every_public_function_of_a_split_module_is_reachable_from_the_facade(module: str) -> None:
    facade = importlib.import_module("coaches.adaptation_hint")
    source = importlib.import_module(module)
    skip = _PUBLIC_NOT_EXPORTED.get(module, frozenset())
    public = [
        n for n, v in vars(source).items()
        if callable(v) and not n.startswith("_") and getattr(v, "__module__", None) == module and n not in skip
    ]
    assert public, f"{module} has no public function: the check would pass on nothing"
    missing = [n for n in public if getattr(facade, n, None) is not getattr(source, n)]
    assert missing == [], f"{module} public names not on the facade: {missing}"


def test_db_dir_patched_on_the_facade_redirects_every_split_module(tmp_path: Path, monkeypatch) -> None:
    facade = importlib.import_module("coaches.adaptation_hint")
    common = importlib.import_module("coaches._adaptation_common")
    mode = min(common.SUPPORTED_MODES)
    (tmp_path / f"{mode}.db").write_bytes(b"")
    monkeypatch.setattr(facade, "DB_DIR", tmp_path)
    assert common._db(mode) == tmp_path / f"{mode}.db"
    assert common._db("not-a-mode") is None
    monkeypatch.setattr(facade, "DB_DIR", tmp_path / "absent")
    assert common._db(mode) is None
