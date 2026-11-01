"""RM-1196 - the RM-314 timeout rationale cites code by symbol, not by line.

The RM-314 timeout rationale is written out in four places: the module
docstring and comments of tests/test_vision_request_timeout_rm314.py, plus
the comment blocks above `_REQUEST_TIMEOUT_S` in modes/shared_vision.py,
tft/tft_vision_reader.py and vision_server/_inference.py. It backed each
number with a `<file>.py:<line>` cite, about thirty distinct cites in all.
At HEAD (lane/repo, 2026-10-31) almost every one of them pointed at
unrelated code. Examples:
`coaches/aram_coach.py:1105` (the 20 s coach timeout) now sits inside a
`_ds_enemy_stats(` call. `coaches/arena_coach.py:426` (the 20.0 s vision
cadence) is a `return ""`. `tft/tft_live_analysis.py:220` (the reader
construction) is a list of trait words. `tft/tft_pbe_engine.py:353` names a
file that RM-292 (b) deleted. Some never matched: `modes/shared_vision.py:110`
and `tft/tft_vision_reader.py:174` were an `else:` and a `y = 0` even at the
RM-314 commit.

Each cite now names its symbol. This guard pins two things:

(a) none of the four files carries a `<file>.py:<line>` cite or a bare
    `:<line>` continuation cite again;
(b) every symbol the rationale now names still exists in its module AND
    still holds the value the rationale quotes for it. For example
    `Coach._run_coach` in coaches/aram_coach.py still passes `timeout = 20`,
    and `TftLiveAnalysis._loop` still keeps its 20.0 s scan floor.
    A rename or a value change names the stale sentence.

Port references such as `:8889/vision` and slices such as `raw[:200]` are not
cites, and the pattern excludes them (see test_pattern_catches_the_old_forms).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

RM314_TEST = "tests/test_vision_request_timeout_rm314.py"
SHARED_VISION = "modes/shared_vision.py"
TFT_READER = "tft/tft_vision_reader.py"
INFERENCE = "vision_server/_inference.py"

CITERS = (RM314_TEST, SHARED_VISION, TFT_READER, INFERENCE)

_PY_LINE_CITE = re.compile(r"[\w/]+\.py:\d+")
# A bare `:NNN` or `:NNN-MMM` continuation cite. Not preceded by a word
# character, a dot, a colon, a slash or `[` (so `127.0.0.1:8889`, `v2:0` and
# `raw[:200]` stay out), and not followed by `/` (so `:8889/vision` stays out).
_BARE_LINE_CITE = re.compile(r"(?<![\w.:/\[])`?:\d{2,4}(?:-\d+)?\b(?![/\d])")

# (citer, module, qualified symbol, regex that must match the symbol's source)
CLAIMS = (
    # The 20 s coach-turn convention.
    (RM314_TEST, "coaches/aram_coach.py", "Coach._run_coach",
     r"timeout\s*=\s*20\b"),
    (RM314_TEST, "coaches/arena_coach.py", "Coach._run_coach",
     r"timeout\s*=\s*20\b"),
    (RM314_TEST, "coaches/brawl_coach.py", "Coach._run_coach",
     r"timeout\s*=\s*20\b"),
    (RM314_TEST, "coaches/replay_coach.py", "analyze_match",
     r"timeout\s*=\s*20\b"),
    (RM314_TEST, "tft/tft_coach_engine.py", "TftCoachEngine.__init__",
     r"_timeout\s*=\s*20\b"),
    # The 10 s shortest call.
    (RM314_TEST, "coaches/arena_coach.py", "Coach._handle_anvil",
     r"timeout\s*=\s*10\b"),
    # Loop cadences.
    (RM314_TEST, "coaches/aram_coach.py", "Coach._VISION_INTERVAL",
     r"=\s*25\.0\b"),
    (RM314_TEST, "coaches/aram_coach.py", "Coach._FAST_VISION_INTERVAL",
     r"=\s*6\.0\b"),
    (RM314_TEST, "coaches/arena_coach.py", "Coach._VISION_INTERVAL",
     r"=\s*20\.0\b"),
    (RM314_TEST, "coaches/brawl_coach.py", "Coach._VISION_INTERVAL",
     r"=\s*18\.0\b"),
    (RM314_TEST, "tft/tft_live_analysis.py", "TftLiveAnalysis._loop",
     r">=\s*20\.0\b"),
    # The TFT reader's construction and its Haiku default.
    (RM314_TEST, "tft/tft_live_analysis.py", "TftLiveAnalysis.__init__",
     r"TftVisionReader\(api_key,\s*model\)"),
    (RM314_TEST, "tft/tft_live_analysis.py", "TftLiveAnalysis.__init__",
     r'model:\s*str\s*=\s*"claude-haiku-4-5'),
    # The two RM-302 sites the RM-314 sweep set aside, since bounded.
    (RM314_TEST, "tft/tft_live_analysis.py", "TftLiveAnalysis._run_analysis",
     r"messages\.create\(.*timeout=_MODEL_TIMEOUT_S"),
    (RM314_TEST, "tft/tft_live_analysis.py",
     "TftLiveAnalysis._run_augment_select",
     r"messages\.create\(.*timeout=_MODEL_TIMEOUT_S"),
    # moon_proxy: the 8 s budget and the two relay routes.
    (RM314_TEST, "core/moon_proxy.py", "TIMEOUT_S", r"=\s*8\b"),
    (RM314_TEST, "core/moon_proxy.py", "MoonProxy.extract_vision",
     r"/vision\""),
    (RM314_TEST, "core/moon_proxy.py", "MoonProxy.get_coaching",
     r"/coach\""),
    # Site 1 runs SONNET_MODEL, set in GameVisionReader.__init__.
    (RM314_TEST, SHARED_VISION, "SONNET_MODEL", r'"claude-sonnet-'),
    (RM314_TEST, SHARED_VISION, "GameVisionReader.__init__",
     r"self\._model\s*=\s*SONNET_MODEL"),
    (RM314_TEST, SHARED_VISION, "GameVisionReader.USE_RELAY", r"=\s*True"),
    (RM314_TEST, TFT_READER, "TftVisionReader._extract",
     r"moon_proxy\.extract_vision\("),
    # modes/shared_vision.py header block.
    (SHARED_VISION, "core/moon_proxy.py", "TIMEOUT_S", r"=\s*8\b"),
    (SHARED_VISION, "coaches/arena_coach.py", "Coach._VISION_INTERVAL",
     r"=\s*20\.0\b"),
    (SHARED_VISION, "coaches/brawl_coach.py", "Coach._VISION_INTERVAL",
     r"=\s*18\.0\b"),
    (SHARED_VISION, "coaches/aram_coach.py", "Coach._run_coach",
     r"timeout\s*=\s*20\b"),
    (SHARED_VISION, "coaches/replay_coach.py", "analyze_match",
     r"timeout\s*=\s*20\b"),
    (SHARED_VISION, "tft/tft_coach_engine.py", "TftCoachEngine.__init__",
     r"_timeout\s*=\s*20\b"),
    (SHARED_VISION, "coaches/aram_coach.py", "Coach._run_vision",
     r"get\(\"augment_select\"\)"),
    # tft/tft_vision_reader.py header and cost-tracker comment.
    (TFT_READER, "tft/tft_live_analysis.py", "TftLiveAnalysis._loop",
     r">=\s*20\.0\b"),
    (TFT_READER, "tft/tft_live_analysis.py", "TftLiveAnalysis.__init__",
     r'model:\s*str\s*=\s*"claude-haiku-4-5'),
    # vision_server/_inference.py model-shape and RM-314 blocks.
    (INFERENCE, SHARED_VISION, "SONNET_MODEL", r'"claude-sonnet-'),
    (INFERENCE, SHARED_VISION, "HAIKU_MODEL", r'"claude-haiku-'),
    (INFERENCE, "vision_server/_config.py", "VISION_MODEL", r'"claude-'),
    (INFERENCE, "vision_server/_config.py", "COACH_MODEL", r'"claude-'),
    (INFERENCE, "tft/tft_coach_engine.py", "TftCoachEngine.__init__",
     r'_model\s*=\s*"claude-'),
    (INFERENCE, "vision_server/_config.py", "_get_client",
     r"Anthropic\(api_key=_API_KEY,\s*base_url="),
    (INFERENCE, "core/moon_proxy.py", "MoonProxy.extract_vision",
     r"/vision\""),
    (INFERENCE, "core/moon_proxy.py", "MoonProxy.get_coaching",
     r"/coach\""),
    (INFERENCE, "core/moon_proxy.py", "TIMEOUT_S", r"=\s*8\b"),
    (INFERENCE, "coaches/arena_coach.py", "Coach._handle_anvil",
     r"timeout\s*=\s*10\b"),
    (INFERENCE, SHARED_VISION, "GameVisionReader._extract",
     r"isinstance\(result,\s*dict\)"),
    (INFERENCE, "dashboard/_screen_read.py", "run_screen_read",
     r"isinstance\(raw,\s*dict\)"),
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _symbol_source(module: str, qualname: str) -> str | None:
    """Source of `qualname` in `module`: a def / class, or an assignment
    target in a module or class body. None when the symbol is gone."""
    text = _read(module)
    body = ast.parse(text).body
    parts = qualname.split(".")
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        found = None
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.name == part:
                found = node
                break
            if last and isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                if any(isinstance(t, ast.Name) and t.id == part
                       for t in targets):
                    found = node
                    break
        if found is None:
            return None
        if last:
            return ast.get_source_segment(text, found)
        body = getattr(found, "body", [])
    return None


def test_citers_present():
    for rel in CITERS:
        assert (ROOT / rel).is_file(), f"{rel} missing"
    assert CLAIMS, "CLAIMS must not be empty"
    assert {c[0] for c in CLAIMS} == set(CITERS), (
        "every citer must carry at least one claim"
    )


@pytest.mark.parametrize("rel", CITERS)
def test_no_py_line_cite(rel):
    hits = _PY_LINE_CITE.findall(_read(rel))
    assert not hits, (
        f"{rel} cites code by line again: {hits}. Name the symbol "
        "instead (RM-1196)."
    )


@pytest.mark.parametrize("rel", CITERS)
def test_no_bare_line_cite(rel):
    hits = [m.group(0) for m in _BARE_LINE_CITE.finditer(_read(rel))]
    assert not hits, (
        f"{rel} carries a bare :<line> cite again: {hits}. Name the "
        "symbol instead (RM-1196)."
    )


@pytest.mark.parametrize(
    "citer,module,qualname,pattern", CLAIMS,
    ids=[f"{c[0].rsplit('/', 1)[-1]}->{c[1].rsplit('/', 1)[-1]}:{c[2]}"
         for c in CLAIMS],
)
def test_named_symbol_holds_the_quoted_value(citer, module, qualname,
                                             pattern):
    assert qualname in _read(citer), (
        f"{citer} no longer names {qualname} (RM-1196)"
    )
    src = _symbol_source(module, qualname)
    assert src is not None, (
        f"{module} has no {qualname}; {citer} names it (RM-1196)"
    )
    assert re.search(pattern, src), (
        f"{module} {qualname} no longer matches {pattern!r}; the sentence "
        f"in {citer} that names it is stale (RM-1196)"
    )


def test_pattern_catches_the_old_forms():
    for old in ("`coaches/aram_coach.py:1105`", "core/moon_proxy.py:28",
                "`_config.py:35-36`"):
        assert _PY_LINE_CITE.search(old), old
    for old in ("fast mode 6.0 s at `:583`", "(`:426`)", "(:139)",
                "(`:108` /vision"):
        assert _BARE_LINE_CITE.search(old), old
    for fine in ("`:8889/vision`", "127.0.0.1:8889", "raw[:200]",
                 "`anthropic.claude-...-v2:0`", "{\"a\":1}"):
        assert not _BARE_LINE_CITE.search(fine), fine


def test_symbol_lookup_reports_a_missing_symbol():
    assert _symbol_source("core/moon_proxy.py", "TIMEOUT_S") is not None
    assert _symbol_source("core/moon_proxy.py", "NO_SUCH_SYMBOL") is None
    assert _symbol_source("coaches/arena_coach.py",
                          "Coach.no_such_method") is None
