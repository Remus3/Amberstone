"""RM-1302, RM-1301, RM-1300 - the cost watchdog's vision advice and tiers.

RM-1302: `--remediate` lowered `vision_calls_per_min` and logged
`remediated: true`, and every vision proposal told the reader to do the same.
Nothing acted on that key: its only reader was CostTracker.acquire_vision_token,
whose last production caller was removed on purpose by b3f7939d5 (operator
directive 2026-06-03, "stop throttling vision capture"). The advice could not
change spend, so a logged remediation was a false claim. The flag is gone, and
each vision purpose now names a lever that really paces it. RM-1305 then
removed the bucket itself (tests/test_cost_tracker_vision_bucket_removed_s144p61.py).

RM-1301: vision_relay said SONNET, but the relay bills whichever model its
caller sends, and since RM-868 / RM-869 every coach reader goes direct. The TFT
reader and its Haiku default are the only live sender, so a hot relay was being
called "hot SONNET". It is HAIKU, pinned here by the routing itself.

RM-1300: nothing tied a PURPOSE_MAP row to the docs/COST_TRACE.md matrix it
says it copies, and the file check accepted a comment mention of a purpose.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

from tests import _repo_walk

_ROOT = Path(__file__).resolve().parent.parent
_TOOL = _ROOT / "tools" / "cost_health_watchdog.py"
_SPEC = importlib.util.spec_from_file_location("chw_s144p58", str(_TOOL))
chw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chw)

_DOC = _ROOT / "docs" / "COST_TRACE.md"
_SITE_CELL = re.compile(r"[^\s|~`]+\.py:[0-9]+")
_SOURCE_GLOBS = ("*.py", "*.js", "*.mjs", "*.html", "*.ps1", "*.bat", "*.yml")


def _src(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def _production_files(globs=("*.py",)):
    """(rel, text) for tracked non-test, non-doc files matching the globs."""
    for path in _repo_walk.iter_repo_files(_ROOT, globs):
        rel = _repo_walk.relative_posix(path, _ROOT)
        if rel.startswith(("tests/", "docs/")) or "/tests/" in rel:
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


def _doc_body_rows() -> list[list[str]]:
    """The cells of every body row of the call-site matrix."""
    text = _DOC.read_text(encoding="utf-8")
    section = text.split("## Call-site matrix", 1)[1].split("\n## ", 1)[0]
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in section.splitlines() if line.startswith("|")]
    assert rows[0][0] == "Site" and set(rows[1][0]) == {"-"}, rows[:2]
    return rows[2:]


def _doc_live_rows() -> dict[str, tuple[str, str]]:
    """{purpose: (tier, file)} for each unstruck row of the call-site matrix."""
    live: dict[str, tuple[str, str]] = {}
    for cells in _doc_body_rows():
        if cells[0].startswith("~~"):
            continue
        assert len(cells) == 5 and _SITE_CELL.fullmatch(cells[0]), cells
        assert cells[4] not in live, f"duplicate matrix row: {cells[4]}"
        live[cells[4]] = (cells[1], cells[0].split(":", 1)[0])
    return live


def _purpose_call_arguments(rel: str) -> set[str]:
    """Every string literal passed as a real `purpose=` call argument."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(_src(rel))):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "purpose" and isinstance(kw.value, ast.Constant):
                found.add(str(kw.value.value))
    return found


def _uses_attribute(text: str, attr: str) -> bool:
    """A call or a bound reference: `x.attr(...)` and `f = x.attr` both count."""
    return attr in text and any(
        isinstance(node, ast.Attribute) and node.attr == attr
        for node in ast.walk(ast.parse(text)))


def _references_name(text: str, name: str) -> bool:
    """An import, a bare name or `module.name`; a comment or docstring is not."""
    if name not in text:
        return False
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and any(
                alias.name == name for alias in node.names):
            return True
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


# ------------------------------------------------------- RM-1302 inert knob

def test_the_remediate_flag_is_gone(tmp_path):
    with pytest.raises(SystemExit) as exc:
        chw.main(["--remediate", "--spend-dir", str(tmp_path),
                  "--state", str(tmp_path / "state.json")])
    assert exc.value.code == 2


def test_the_tool_no_longer_writes_or_names_the_inert_knob():
    text = _TOOL.read_text(encoding="utf-8")
    for gone in ("vision_calls_per_min", "coach_settings", "VISION_RATE_FLOOR",
                 "remediated", "self-healing"):
        assert gone not in text, gone


def test_the_knob_really_has_no_production_reader():
    """The reason for the removal. Any mention goes red, the bucket's old module
    included: rewiring the bucket reverses b3f7939d5, and the watchdog's advice
    has to be re-decided with it. A name match, so getattr and a bound method
    cannot escape it, and every source surface, not only .py."""
    names = ("acquire_vision_token", "vision_calls_per_min",
             "CFG_VISION_RATE_PER_MIN")
    hits: list[tuple[str, str]] = []
    scanned = 0
    for rel, text in _production_files(_SOURCE_GLOBS):
        scanned += 1
        hits.extend((rel, n) for n in names if n in text)
    assert scanned > 100, scanned
    assert hits == []


@pytest.mark.parametrize("name", sorted(chw.PURPOSE_MAP))
def test_no_proposal_names_an_inert_knob(name):
    proposal = chw.classify({name: {"usd": 9.0}})["proposal"]
    assert "vision_calls_per_min" not in proposal, proposal
    # Stored by TftLiveAnalysis.__init__ and read by nothing (RM-1303).
    assert "_vision_interval" not in proposal, proposal


def test_every_vision_purpose_and_every_sonnet_row_has_advice():
    sonnet = {n for n, (tier, _f) in chw.PURPOSE_MAP.items()
              if tier == "SONNET"}
    assert sonnet == {"vision_direct"}
    assert set(chw._VISION_ADVICE) == {"vision_relay", "vision_direct"}


def test_the_relay_lever_really_paces_the_tft_scan():
    proposal = chw.classify({"vision_relay": {"usd": 9.0}})["proposal"]
    assert "TftLiveAnalysis._loop" in proposal
    assert "tft/tft_live_analysis.py" in proposal
    tree = ast.parse(_src("tft/tft_live_analysis.py"))
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "TftLiveAnalysis")
    loop = next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "_loop")
    body = ast.get_source_segment(_src("tft/tft_live_analysis.py"), loop)
    assert "self._run_cycle()" in body
    assert ">=20.0" in body
    assert "self._scanned_planning=True" in body


def test_the_direct_levers_are_really_read():
    proposal = chw.classify({"vision_direct": {"usd": 9.0}})["proposal"]
    assert "_VISION_INTERVAL" in proposal
    assert re.search(r">=\s*self\._VISION_INTERVAL",
                     _src("coaches/_base_coach.py"))
    # The base value paces none of these callers: each coach overrides it.
    for rel in ("coaches/aram_coach.py", "coaches/arena_coach.py",
                "coaches/brawl_coach.py"):
        assert rel in proposal
        assert re.search(r"^\s+_VISION_INTERVAL\b[^=\n]*=\s*[0-9]", _src(rel),
                         re.M), rel
    # Moving fields to OCR is not offered: a partial OCR read still sends the
    # full prompt, so it saves no call (RM-1304).
    assert "read_tiered" not in proposal
    assert "core/vision_routing" not in proposal


# ---------------------------------------------------------- RM-1301 relay tier

def test_the_only_relay_senders_are_the_gated_reader_and_tft():
    senders = {rel for rel, text in _production_files()
               if _uses_attribute(text, "extract_vision")}
    assert senders == {"modes/shared_vision.py", "tft/tft_vision_reader.py"}
    shared = _src("modes/shared_vision.py")
    assert (shared.index("if self.USE_RELAY:")
            < shared.index("_mp.extract_vision(img_b64, self._model)"))


def test_every_coach_reader_opts_out_of_the_relay():
    """A new GameVisionReader user that keeps the default sends Sonnet through
    the relay and voids the HAIKU row, so it has to be decided here."""
    users = {rel for rel, text in _production_files()
             if rel != "modes/shared_vision.py"
             and _references_name(text, "GameVisionReader")}
    assert users == {"coaches/aram_coach.py", "coaches/arena_coach.py",
                     "coaches/brawl_coach.py", "dashboard/_screen_read.py"}
    for rel in users:
        assert re.search(r"^\s*(r\.)?USE_RELAY = False$", _src(rel), re.M), rel


def test_the_tft_sender_uses_its_haiku_default():
    live = _src("tft/tft_live_analysis.py")
    assert re.search(r'model: str = "claude-haiku', live)
    assert "TftVisionReader(api_key,model)" in live
    calls = [n for n in ast.walk(ast.parse(_src("core/tft_worker.py")))
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "TftLiveAnalysis"]
    assert len(calls) == 1
    assert len(calls[0].args) < 3
    assert all(kw.arg != "model" for kw in calls[0].keywords)
    assert re.search(r'VISION_MODEL = "claude-haiku',
                     _src("vision_server/_config.py"))


def test_a_hot_relay_is_not_called_sonnet():
    r = chw.classify({"vision_relay": {"usd": 0.382}})
    assert r["tier"] == "HAIKU"
    assert "SONNET" not in r["proposal"]
    assert "hot HAIKU vision purpose" in r["proposal"]


def test_the_direct_vision_path_is_still_sonnet():
    """vision_direct goes direct with the reader's own SONNET_MODEL."""
    shared = _src("modes/shared_vision.py")
    assert re.search(r'^SONNET_MODEL = "claude-sonnet', shared, re.M)
    assert "self._model  = SONNET_MODEL" in shared
    r = chw.classify({"vision_direct": {"usd": 9.0}})
    assert r["tier"] == "SONNET"
    assert "hot SONNET vision purpose" in r["proposal"]


# ------------------------------------------------- RM-1300 doc and call site

def test_the_matrix_parse_is_not_empty():
    assert len(_doc_live_rows()) >= 15


def test_every_map_row_has_a_matrix_row_and_the_reverse():
    assert set(chw.PURPOSE_MAP) == set(_doc_live_rows())


@pytest.mark.parametrize("name", sorted(chw.PURPOSE_MAP))
def test_each_map_row_agrees_with_its_matrix_row(name):
    assert chw.PURPOSE_MAP[name] == _doc_live_rows()[name]


@pytest.mark.parametrize("name", sorted(chw.PURPOSE_MAP))
def test_each_mapped_file_passes_the_purpose_as_a_real_call_argument(name):
    """A comment mention, or `purpose="x"` in a docstring, is not a caller."""
    _tier, fil = chw.PURPOSE_MAP[name]
    assert name in _purpose_call_arguments(fil), (name, fil)
