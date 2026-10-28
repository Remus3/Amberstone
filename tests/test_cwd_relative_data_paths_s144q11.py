# arch: RM-1022 (2) - RC data paths are anchored to the repo root, never the CWD
"""RM-1022 part (2) - RC modules named their ``data/`` files relative to
the process working directory.

``Path("data") / ...`` resolves against the CWD at the moment of each read,
so a process whose CWD is not the repo root silently missed the data (a
missing rewind DB, a missing WPA model, an empty DDragon index) or, worse,
read a same-named file planted in whatever directory it stood in. Live, RC
runs with ``cwd=<repo>``, so the relative path happened to name the right
file; nothing in the code made it so. The precedent fix is already in the
tree: ``coaches/replay_coach.py`` and ``coaches/champ_pool_recommender.py``
anchor ``_REWIND_DB`` to ``Path(__file__)``, and the WPA route modules were
anchored the same way (tests/test_p2w1_dash_e.py item 6).

Sites (module-level constants and call-time defaults):
- core/draft_elo_db.py ``_REWIND_DB`` (the RC_REWIND_DB override is kept)
- dashboard/routes_personal_vs.py and dashboard/routes_pickban.py ``_REWIND_DB``
- core/item_wpa.py ``_DS_DIR`` and the ``compute_item_wpa_from_db`` default
- core/post_game_rubric.py ``_OVERRIDES_PATH``
- core/post_game_score.py ``_DEFAULT_MODEL_PATH`` and the ``train_from_db``
  default
- core/rune_wpa.py and core/summoner_spell_wpa.py ``_DDRAGON_DIR`` and their
  ``*_from_db`` defaults (same-root siblings found by the sweep)
- core/skill_wpa.py ``compute_skill_wpa_from_db`` default (sibling)

Every test runs with the CWD moved to an empty temp dir. The read-path
tests use tracked data files, so they HIT after the fix and MISS on the
base; the gitignored files (the rewind DB, the rubric overrides) are
checked by resolved path and by planting a decoy in the foreign CWD that
the fixed code must ignore. agents/daemon_slayer/cc_conditional.py carries
the same shape but is DS-package code (ds lane; the RM-337 DS guard did not
catch it) and is excluded from the guard below.
"""
from __future__ import annotations

import ast
import os
import sqlite3
from pathlib import Path
from unittest import mock

import pytest

import core.draft_elo_db as draft_elo_db
import core.item_wpa as item_wpa
import core.post_game_rubric as post_game_rubric
import core.post_game_score as post_game_score
import core.rune_wpa as rune_wpa
import core.skill_wpa as skill_wpa
import core.summoner_spell_wpa as summoner_spell_wpa
import dashboard.routes_personal_vs as routes_personal_vs
import dashboard.routes_pickban as routes_pickban

ROOT = Path(__file__).resolve().parent.parent

_CONSTANTS = [
    (draft_elo_db, "_REWIND_DB", "data/rewind_history.db"),
    (routes_personal_vs, "_REWIND_DB", "data/rewind_history.db"),
    (routes_pickban, "_REWIND_DB", "data/rewind_history.db"),
    (item_wpa, "_DS_DIR", "data/daemon_slayer"),
    (item_wpa, "_ITEMS_JSON", "data/daemon_slayer/16.11.1/items.json"),
    (post_game_rubric, "_OVERRIDES_PATH", "data/post_game_rubric_weights.json"),
    (post_game_score, "_DEFAULT_MODEL_PATH", "data/post_game_wpa_model.json"),
    (rune_wpa, "_DDRAGON_DIR", "data/meta_build/ddragon"),
    (rune_wpa, "_RUNES_JSON", "data/meta_build/ddragon/16.11.1/runesReforged.json"),
    (summoner_spell_wpa, "_DDRAGON_DIR", "data/meta_build/ddragon"),
    (summoner_spell_wpa, "_SUMMONER_JSON", "data/meta_build/ddragon/16.11.1/summoner.json"),
]


@pytest.fixture
def foreign_cwd(tmp_path, monkeypatch):
    """Move the CWD to an empty temp dir for the duration of one test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("module", "attr", "rel"), _CONSTANTS,
    ids=[f"{m.__name__}.{a}" for m, a, _ in _CONSTANTS],
)
def test_constant_resolves_under_the_repo_root(foreign_cwd, module, attr, rel):
    value = Path(getattr(module, attr))
    assert value.is_absolute(), f"{module.__name__}.{attr} = {value!s} is CWD-relative"
    assert value.resolve() == (ROOT / rel).resolve()


def test_draft_elo_default_ignores_cwd_and_keeps_env_override(foreign_cwd, monkeypatch):
    monkeypatch.delenv("RC_REWIND_DB", raising=False)
    got = draft_elo_db._resolve_db_path()
    assert got.resolve() == (ROOT / "data" / "rewind_history.db").resolve()
    override = foreign_cwd / "override.db"
    monkeypatch.setenv("RC_REWIND_DB", str(override))
    assert draft_elo_db._resolve_db_path() == override


# -- read paths over TRACKED data files: miss on the base, hit after ----------

def test_wpa_model_loads_from_a_foreign_cwd(foreign_cwd):
    assert (ROOT / "data" / "post_game_wpa_model.json").is_file()
    assert post_game_score.load_model() is not None


@pytest.mark.parametrize("module", [rune_wpa, summoner_spell_wpa],
                         ids=["rune_wpa", "summoner_spell_wpa"])
def test_ddragon_index_reads_from_a_foreign_cwd(foreign_cwd, module):
    assert (ROOT / "data" / "meta_build" / "ddragon" / "_index.json").is_file()
    assert module._latest_pulled_version() != ""


def test_items_catalog_resolves_from_a_foreign_cwd(foreign_cwd):
    assert (ROOT / "data" / "daemon_slayer" / "current.txt").is_file()
    got = item_wpa._default_items_json()
    assert got.is_file(), str(got)
    assert got.resolve().is_relative_to(ROOT.resolve())


# -- gitignored files: a decoy planted in the foreign CWD is never read ------

def _plant(cwd: Path, rel: str, data: bytes) -> Path:
    p = cwd / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_pickban_db_mtime_ignores_a_cwd_decoy(foreign_cwd):
    decoy = _plant(foreign_cwd, "data/rewind_history.db", b"")
    os.utime(decoy, (12345.0, 12345.0))
    assert routes_pickban._db_mtime() != 12345.0


def test_rubric_overrides_ignore_a_cwd_decoy(foreign_cwd, caplog):
    _plant(foreign_cwd, "data/post_game_rubric_weights.json", b"\xff\xfe\xfa bad")
    with caplog.at_level("WARNING", logger=post_game_rubric._LOG.name):
        post_game_rubric._load_weights_overrides()
    assert not [r for r in caplog.records if "not valid UTF-8" in r.getMessage()]


class _Opened(Exception):
    pass


_FROM_DB = [
    (item_wpa.compute_item_wpa_from_db, True),
    (rune_wpa.compute_rune_wpa_from_db, True),
    (summoner_spell_wpa.compute_summoner_spell_wpa_from_db, True),
    (skill_wpa.compute_skill_wpa_from_db, True),
    (post_game_score.train_from_db, False),
]


@pytest.mark.parametrize(
    ("fn", "checks_exists"), _FROM_DB,
    ids=[f.__module__ + "." + f.__name__ for f, _ in _FROM_DB],
)
def test_from_db_default_never_opens_a_cwd_decoy(foreign_cwd, fn, checks_exists):
    _plant(foreign_cwd, "data/rewind_history.db", b"")
    opened: list[str] = []

    def _fake_connect(database, *args, **kwargs):
        opened.append(database)
        raise _Opened(database)

    real = ROOT / "data" / "rewind_history.db"
    with mock.patch.object(sqlite3, "connect", _fake_connect):
        try:
            fn()
        except _Opened:
            pass
    if checks_exists and not real.exists():
        assert opened == [], opened
        return
    assert len(opened) == 1, opened
    path = opened[0].removeprefix("file:").split("?", 1)[0]
    assert Path(path).is_absolute(), path
    assert Path(path).resolve() == real.resolve()


# -- guard: no RC production module names data/ relative to the CWD ----------

_GUARD_DIRS = ("app", "agents", "coaches", "core", "dashboard", "game_reader",
               "lcu", "lib", "modes", "tft", "vision_server")
_GUARD_SKIP_PARTS = {"daemon_slayer", "tests", "__pycache__"}


def _is_rooted(s: str) -> bool:
    return s.startswith(("/", "\\")) or (len(s) > 1 and s[1] == ":")


def _cwd_data_paths(source: str) -> list[int]:
    """Line numbers of ``Path("data"...)`` calls not bound to a ``*_REL`` name.

    A ``*_REL`` constant is joined to a root at call time by design
    (tft/assets/icon_cache.py ``CACHE_REL``), so it is not a CWD read.
    """
    tree = ast.parse(source)
    rel_bound: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id.endswith("_REL") for t in targets):
                rel_bound.update(id(n) for n in ast.walk(node))
    hits: list[int] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Path" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and id(node) not in rel_bound):
            s = node.args[0].value
            first = s.replace("\\", "/").lstrip("./").split("/", 1)[0]
            if not _is_rooted(s) and first == "data":
                hits.append(node.lineno)
    return sorted(hits)


def test_guard_predicate_shape():
    src = (
        'from pathlib import Path\n'
        'A = Path("data") / "x.db"\n'
        'B = Path("data/x.json")\n'
        'C_REL = Path("data") / "y"\n'
        'D = Path(__file__).resolve().parent / "data"\n'
        'E = Path("web") / "x"\n'
    )
    assert _cwd_data_paths(src) == [2, 3]


def test_no_rc_module_reads_data_relative_to_the_cwd():
    offenders: list[str] = []
    scanned = 0
    for top in _GUARD_DIRS:
        base = ROOT / top
        if not base.is_dir():
            continue
        for py in sorted(base.rglob("*.py")):
            if _GUARD_SKIP_PARTS & set(py.relative_to(ROOT).parts):
                continue
            scanned += 1
            for line in _cwd_data_paths(py.read_text(encoding="utf-8")):
                offenders.append(f"{py.relative_to(ROOT).as_posix()}:{line}")
    # An empty enumeration must not pass: core/ and dashboard/ alone hold hundreds.
    assert scanned > 300, scanned
    assert offenders == [], offenders
