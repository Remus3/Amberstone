"""Guards for the TFT engine package tft/engine (slice TFT-13, ADR-018).

1. NAME IN ONE PLACE. The engine's display name lives in ONE constant,
   tft.engine.ENGINE_NAME (ADR-018 Decision): a rename is a one-line change,
   so the name (read from the constant, never spelled in this file) may
   appear in exactly one source file - tft/engine/__init__.py - exactly once.
   The match is a strict case-insensitive substring (camelCase identifiers
   count); only a whole word in ALLOWED_CONTAINING_WORDS (empty) is exempt.
   Prose (docs/*.md, the ADR, its README row) and data files (*.json: game
   data may legitimately carry a similar word) are out of scope by design,
   as are untracked files outside tft/engine (named blind spots).
   Enumeration: the git index via tests/_repo_walk (ADR-015) plus the
   engine package on disk, so a brand-new, unstaged engine file is still
   swept; the walker self-check keeps an empty enumeration from reading as
   clean.
2. NOT DAEMON SLAYER. No module of tft/engine imports agents.daemon_slayer or
   names the DS port (AST sweep), and importing the whole package in a fresh
   interpreter loads no agents.daemon_slayer module (transitive proof).
3. LLM-FREE, NETWORK-FREE, DETERMINISTIC. No network, LLM, clock or random
   import; no URL literal.
4. NO THIRD-PARTY DATA (RM-846). The engine never reaches the meta files
   (comps / tier lists), the overlay comp state or the legacy hand-written
   tier tables in tft/tft_data.py, and does no file I/O of its own: with
   those entry points and builtins.open made to explode, the whole pipeline
   still runs on game data handed in through tft/tft_set.py.
Each sweep is proven to fire on a planted offender, so a green run is not a
checker that sees nothing.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _repo_walk
from tests.test_tft_engine_synthetic import SYNTH_DOC, synth_history, timeline_record, u
from tft import engine as tft_engine

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = REPO_ROOT / "tft" / "engine"
ENGINE_FILES = ("__init__.py", "comps.py", "milestones.py", "recommend.py", "compare.py")
CODE_PATTERNS = ("*.py", "*.pyw", "*.js", "*.mjs", "*.cjs", "*.ts", "*.html", "*.css",
                 "*.ps1", "*.psm1", "*.bat", "*.cmd", "*.sh")

BANNED_IMPORT_ROOTS = frozenset({
    # Daemon Slayer (ADR-018)
    "agents",
    # network / LLM
    "socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "websocket",
    "websockets", "anthropic", "openai",
    # non-determinism
    "random", "time", "datetime", "uuid", "secrets",
})
BANNED_NAMES = frozenset({
    # tft/tft_set.py entry points to RC-authored / third-party-shaped data
    "load_meta", "meta_path", "comp_state", "pbe_flag",
    # hand-written tables in tft/tft_data.py that are not game data
    "ITEM_TIERS", "TEMPO_MILESTONES", "AUGMENT_TIERS", "ROUND_EVENTS", "PVE_ROUNDS", "EMBLEM_TRAITS",
    # direct file I/O
    "open", "read_text", "read_bytes", "write_text", "write_bytes",
})
BANNED_LITERALS = (re.compile(r"https?://"), re.compile(r":8860\b"), re.compile(r"daemon_slayer"),
                   re.compile(r"tier_list"))


def _engine_sources():
    return {name: (ENGINE_DIR / name).read_text(encoding="utf-8") for name in ENGINE_FILES}


def test_engine_package_has_its_file_set():
    for name in ENGINE_FILES:
        assert (ENGINE_DIR / name).is_file(), name


def test_engine_constants():
    assert isinstance(tft_engine.ENGINE_NAME, str) and tft_engine.ENGINE_NAME.strip()
    assert tft_engine.ENGINE_NAME.isascii()
    assert isinstance(tft_engine.ENGINE_SCHEMA, int) and tft_engine.ENGINE_SCHEMA >= 1
    assert tft_engine.engine_meta() == {"engine": tft_engine.ENGINE_NAME, "schema": tft_engine.ENGINE_SCHEMA}


# ------------------------------------------------------------ 1. one name

# Lower-case words that merely CONTAIN the engine name (an English word, not a
# hard-coded label). Empty today: nothing in the swept tree needs it. Adding a
# word here is a deliberate, reviewed act; never add an identifier.
ALLOWED_CONTAINING_WORDS: frozenset = frozenset()


def _name_hits(text, name, allowed=ALLOWED_CONTAINING_WORDS):
    # Strict: case-insensitive substring, so camelCase / snake_case / CSS uses
    # ("get<Name>Picks", "tft<Name>", "MY_<NAME>") all count. Only an allowed
    # whole word that contains the name is subtracted.
    hits = len(re.findall(re.escape(name), text, flags=re.IGNORECASE))
    for word in allowed:
        hits -= len(re.findall(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, flags=re.IGNORECASE)) \
            * len(re.findall(re.escape(name), word, flags=re.IGNORECASE))
    return hits


def _swept_files():
    _repo_walk.self_check(REPO_ROOT)
    files = set(_repo_walk.repo_files(REPO_ROOT, CODE_PATTERNS))
    files |= {p.resolve() for p in ENGINE_DIR.glob("*.py")}
    return sorted(files)


def test_engine_name_lives_in_exactly_one_source_file():
    name = tft_engine.ENGINE_NAME
    files = _swept_files()
    assert len(files) > 500, f"enumeration collapsed: {len(files)} files"
    offenders = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = _name_hits(text, name)
        if hits:
            offenders[_repo_walk.relative_posix(path, REPO_ROOT)] = hits
    assert offenders == {"tft/engine/__init__.py": 1}, offenders
    init = (ENGINE_DIR / "__init__.py").read_text(encoding="utf-8")
    assert re.search(r'^ENGINE_NAME = "' + re.escape(name) + r'"$', init, flags=re.MULTILINE)


def test_name_sweep_fires_on_a_planted_copy():
    name = tft_engine.ENGINE_NAME
    assert _name_hits(f'label = "{name} picks"', name) == 1
    assert _name_hits(f"<h1>{name.upper()}</h1>", name) == 1
    assert _name_hits(f"const {name.lower()}Panel = 1; MY_{name.upper()} = 2", name) == 2
    # camelCase with a letter on either side still counts (the rename trap).
    assert _name_hits(f"get{name}Picks(); tft{name} = 1; render{name.upper()}", name) == 3
    assert _name_hits("label = ENGINE_NAME", name) == 0
    # Only an explicitly allowed whole English word is subtracted, nothing else.
    word = "in" + name.lower() + "ate"
    assert _name_hits(f"we {word} it", name) == 1
    assert _name_hits(f"we {word} it; tft{name} = 1", name, allowed=frozenset({word})) == 1
    assert ALLOWED_CONTAINING_WORDS == frozenset()


# --------------------------------------------- 2-4. AST / literal sweeps

def _violations(source):
    out = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_IMPORT_ROOTS:
                    out.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod.split(".")[0] in BANNED_IMPORT_ROOTS:
                out.append(f"from {mod} import")
            for alias in node.names:
                if alias.name in BANNED_NAMES:
                    out.append(f"from {mod} import {alias.name}")
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            out.append(f"name {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            out.append(f"attribute .{node.attr}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "__import__":
            out.append("__import__")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for pat in BANNED_LITERALS:
                if pat.search(node.value):
                    out.append(f"literal {pat.pattern}")
    if "importlib" in source:
        out.append("importlib")
    return out


def test_engine_sources_pass_the_import_name_and_literal_sweep():
    bad = {name: v for name, src in _engine_sources().items() if (v := _violations(src))}
    assert bad == {}, bad


@pytest.mark.parametrize("planted", [
    "import agents.daemon_slayer\n",
    "from agents.daemon_slayer import dps\n",
    "import requests\n",
    "from anthropic import Anthropic\n",
    "import random\n",
    "from tft.tft_set import load_meta\n",
    "from tft import tft_data\nx = tft_data.ITEM_TIERS\n",
    "x = open('f')\n",
    "URL = 'https://example.com/tier'\n",
    "PORT = 'http://127.0.0.1:8860/rank'\n",
    "import importlib\nm = importlib.import_module('x')\n",
])
def test_sweep_fires_on_planted_offenders(planted):
    assert _violations(planted), planted


def test_engine_sources_are_ascii_and_lf():
    for name in ENGINE_FILES:
        raw = (ENGINE_DIR / name).read_bytes()
        assert raw.isascii(), name
        assert b"\r" not in raw, name


def test_importing_the_engine_loads_no_daemon_slayer_module():
    code = ("import sys\n"
            "import tft.engine, tft.engine.comps, tft.engine.milestones, tft.engine.recommend, "
            "tft.engine.compare\n"
            "bad = sorted(m for m in sys.modules if m.startswith('agents') or m in ('anthropic', 'requests'))\n"
            "print('BAD=' + ','.join(bad))\n")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True,
                          text=True, timeout=120, creationflags=flags)
    assert proc.returncode == 0, proc.stderr
    assert "BAD=\n" in proc.stdout or proc.stdout.strip() == "BAD=", proc.stdout


# --------------------------------------- 4. runtime: game data only, no I/O

def test_pipeline_runs_with_meta_files_network_and_open_blocked(monkeypatch):
    from tft import tft_roll_odds, tft_set
    from tft.engine import comps, compare, milestones, recommend

    sd = comps.SetData.from_cdragon(SYNTH_DOC)
    consts = tft_roll_odds.SetConstants(
        source="test", set_number=sd.set_id, verified_in_client=True,
        tier_odds={6: {1: 0.3, 2: 0.4, 3: 0.25, 4: 0.05, 5: 0.0}},
        pool_sizes={1: 30, 2: 25, 3: 18, 4: 10, 5: 9}, units_per_cost={1: 2, 2: 3, 3: 3, 4: 2, 5: 2})
    recs = synth_history() + [timeline_record("t1", 1, {"2-1": 4, "3-1": 6})]

    def boom(*_a, **_k):
        raise AssertionError("the engine reached a forbidden source")

    for attr in ("load_meta", "meta_path", "comp_state", "pbe_flag"):
        monkeypatch.setattr(tft_set, attr, boom)
    import socket
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr("builtins.open", boom)
    monkeypatch.setattr("io.open", boom)

    cat = comps.build_catalogue(recs, sd)
    ms = milestones.milestones_by_comp(recs, cat, sd)
    state = {"label": "3-2", "level": 6, "board": [u("U_Gale"), u("U_Cora")], "bench": [],
             "items": ["C_Rod", "C_Bow"], "offers": [{"slot": 0, "champion_api": "U_Jinx", "cost": 5}]}
    out = recommend.recommend(state, cat, ms, sd, consts=consts)
    picker = recommend.planner_choices(cat, ms, sd, lobby_boards=[[u("U_Jinx")]])
    cmp = compare.compare_boards(state["board"], [u("U_Hex")], sd)
    assert cat["comps"] and out["target"] and picker["choices"] and cmp["own"]["units"] == 2
