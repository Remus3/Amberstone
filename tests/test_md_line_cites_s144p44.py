"""RM-1195 - five test files cite Markdown docs by section, not by line.

Measured at the lane/repo base before this slice (2026-10-31):

- tests/test_lcu_push_watcher.py cited "docs/LIVE_GAME_GATED_SYNC.md line
  90" for gated item A1. Line 90 had become a blank line in a later session
  entry (just above its "NEW BUGS FOUND THIS SITTING" list), and
  A1 is a closed row the doc records as dropped from the checklist body
  (history LEDGER 859 + 867).
- tests/test_precomputed_laning_coach.py cited
  "HZ_HAIKU_CALL_INVENTORY.md:49-108" and ":97-99" for the hold/farm
  calibration finding. At authoring (75e35a795) 49-108 spanned the
  2026-06-19-01 and -02 UPDATE sections, and 97-99 spanned the end of the
  BUILD-lane bullet and the first line of the "LANING `even` understatement
  QUANTIFIED" bullet (the one about `even` ticks facing Haiku `hold`, which
  is what the citer means); both ranges have since moved (97-99 now
  lands in a note on where an unrelated threshold number came from). The
  citer now names both sections and both bullets.
- tests/test_vision_request_timeout_rm314.py cited "BACKLOG.md:63" for the
  RM-314 row (now far below line 63) and listed the four untimed call sites
  by line numbers that no longer land on them.
- tests/test_cost_trace_matrix_is_live.py cited "BACKLOG.md:30" (now an
  unrelated row) and "docs/COST_TRACE.md:11" (still accurate, but positional).
- tests/test_vision_fusion.py cited "docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163"
  (still accurate, but positional).

Each citer now names a section heading or a quoted sentence. This guard pins
(a) no ``<doc>.md`` line cite returns to those files, (b) every named anchor
still exists in its target doc, (c) each citer still names its anchor, and
(d) the four RM-314 call-site symbols still exist in their modules.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

CITERS = (
    "tests/test_lcu_push_watcher.py",
    "tests/test_precomputed_laning_coach.py",
    "tests/test_vision_request_timeout_rm314.py",
    "tests/test_cost_trace_matrix_is_live.py",
    "tests/test_vision_fusion.py",
)

# A Markdown doc cited by position: "x.md:12", "x.md:12-15", "x.md line 90",
# "x.md lines 3-5", "x.md L12".
_MD_LINE_CITE = re.compile(
    r"[\w./-]+\.md`?\s*(?::\d+|,?\s+lines?\s+\d+|\s+L\d+)", re.IGNORECASE
)

# (citer, target doc, anchor text that must be in BOTH the doc and the citer)
ANCHORS = (
    ("tests/test_lcu_push_watcher.py", "docs/LIVE_GAME_GATED_SYNC.md",
     "A1 / A2 / A7 / A13 - closed rows finally dropped"),
    ("tests/test_precomputed_laning_coach.py",
     "ops/audit/HZ_HAIKU_CALL_INVENTORY.md",
     "(run 2026-06-19-01)"),
    ("tests/test_precomputed_laning_coach.py",
     "ops/audit/HZ_HAIKU_CALL_INVENTORY.md",
     "(run 2026-06-19-02)"),
    ("tests/test_precomputed_laning_coach.py",
     "ops/audit/HZ_HAIKU_CALL_INVENTORY.md",
     "Haiku says `hold` on 114"),
    ("tests/test_precomputed_laning_coach.py",
     "ops/audit/HZ_HAIKU_CALL_INVENTORY.md",
     "LANING `even` understatement QUANTIFIED"),
    ("tests/test_vision_request_timeout_rm314.py", "BACKLOG.md",
     "**RM-314 SHIPPED"),
    ("tests/test_cost_trace_matrix_is_live.py", "BACKLOG.md",
     "deterministic champ-select brief FLIP"),
    ("tests/test_cost_trace_matrix_is_live.py", "docs/COST_TRACE.md",
     "`core/moon_proxy.py` does NOT call Anthropic"),
    ("tests/test_vision_fusion.py", "docs/NO_LLM_PRECOMPUTE_PLAN.md",
     "CONFIDENCE-WEIGHTED FUSION"),
)

# The four RM-314 call sites, named by symbol in the citer.
RM314_SITES = (
    ("modes/shared_vision.py", "def _extract("),
    ("tft/tft_vision_reader.py", "def _extract_local("),
    ("vision_server/_inference.py", "def handle_vision("),
    ("vision_server/_inference.py", "def handle_coach("),
)

# The RM-314 module docstring's numbered site list and the inference class
# docstring must not carry a line number for the four sites. (The file's
# other rationale cites into .py files are out of this slice's scope.)
_RM314_SITE_LINE = re.compile(
    r"^\s+\d\.\s+`(?:modes/shared_vision|tft/tft_vision_reader"
    r"|vision_server/_inference)\.py:\d+"
    r"|handle_(?:vision|coach) \(:\d+\)",
    re.MULTILINE,
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_citer_list_is_nonempty_and_present():
    assert len(CITERS) == 5
    for rel in CITERS:
        assert (ROOT / rel).is_file(), rel


@pytest.mark.parametrize("rel", CITERS)
def test_citer_has_no_markdown_line_cite(rel):
    hits = [m.group(0) for m in _MD_LINE_CITE.finditer(_read(rel))]
    assert not hits, (
        f"{rel} cites a Markdown doc by line: {hits}. Name the section "
        f"heading or quote the sentence instead (RM-1195)."
    )


@pytest.mark.parametrize(("citer", "doc", "anchor"), ANCHORS)
def test_anchor_exists_in_doc_and_citer(citer, doc, anchor):
    assert anchor in _read(doc), (
        f"{doc} no longer carries {anchor!r}; re-point {citer}."
    )
    assert anchor in _read(citer), (
        f"{citer} no longer names {anchor!r} for its {doc} cite."
    )


@pytest.mark.parametrize(("module", "symbol"), RM314_SITES)
def test_rm314_site_symbol_exists(module, symbol):
    assert symbol in _read(module), f"{module} lost {symbol!r}"


def test_rm314_site_list_cites_by_symbol():
    text = _read("tests/test_vision_request_timeout_rm314.py")
    hits = [m.group(0) for m in _RM314_SITE_LINE.finditer(text)]
    assert not hits, (
        f"RM-314 site list cites by line again: {hits} (RM-1195)."
    )


def test_pattern_catches_the_old_forms():
    for probe in (
        "docs/LIVE_GAME_GATED_SYNC.md line 90",
        "HZ_HAIKU_CALL_INVENTORY.md:97-99",
        "`BACKLOG.md:63`",
        "docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163",
        "x.md lines 3-5",
        "x.md L12",
    ):
        assert _MD_LINE_CITE.search(probe), probe
    for probe in (
        "  1. `modes/shared_vision.py:389`      GameVisionReader._extract",
        "handle_vision (:246)",
    ):
        assert _RM314_SITE_LINE.search(probe), probe
