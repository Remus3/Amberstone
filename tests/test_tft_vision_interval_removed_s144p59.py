"""RM-1303 - TftLiveAnalysis has no `_vision_interval`, and the TFT vision
timeout rationale no longer leans on it.

`TftLiveAnalysis.__init__` stored `_vision_interval = 15.0` from the initial
commit, and nothing read it: every reference on every tracked surface was that
one store, two test stubs setting it, prose, the RM-1196 regex pins on that
prose, and one RM-1302 assertion that watchdog advice never names it. `_loop`
paces on one planning scan a round (`_scanned_planning`) and a literal 20.0 s
floor on augment and god rounds.

The RM-314 rationale for `_REQUEST_TIMEOUT_S` in tft/tft_vision_reader.py was
built on it: "15s equals the TFT scan cadence ... so a hung extract cannot
outlive the round it was scanning". Both halves were false. No cadence is 15 s,
and the bound is per attempt: the reader's client keeps the SDK default of 2
retries, the case the _MODEL_TIMEOUT_S note in tft/tft_live_analysis.py spells
out for the analysis calls.

This pin fails if the attribute returns, if the old wording returns, if the 20.0
floor, the planning window or the 15 s value changes, or if the reader's
Anthropic() call gains max_retries or the reader uses with_options. It reads
source only, so it does not drive a hung call. It does not catch every way the
retry count could change (assigning max_retries on the client stays green), or
every way `_loop` could change while keeping those literals.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = "tft/tft_live_analysis.py"
READER = "tft/tft_vision_reader.py"
RM314_TEST = "tests/test_vision_request_timeout_rm314.py"


def _src(rel: str) -> str:
    return (ROOT / rel).read_bytes().decode("utf-8")


def _flat(rel: str) -> str:
    return " ".join(_src(rel).replace("#", " ").split())


def _method(rel: str, cls: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(_src(rel)).body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return item
    raise AssertionError(f"{rel} has no {cls}.{name}")


def test_the_attribute_is_gone_from_the_live_analysis_module():
    assert "_vision_interval" not in _src(LIVE), (
        "TftLiveAnalysis stores _vision_interval again. Nothing reads it, and "
        "_loop paces on the planning scan and the 20.0 s floor (RM-1303). "
        "Give it a real reader in _loop or leave it out."
    )


def test_no_cited_rationale_names_the_attribute_as_a_cadence():
    for rel in (READER, RM314_TEST):
        assert "_vision_interval" not in _src(rel), rel
        assert "equals the TFT scan cadence" not in _flat(rel), rel
        assert "cannot outlive the" not in _flat(rel), rel


def test_a_hold_past_the_planning_window_is_named_as_a_skip():
    """`_loop` scans a planning round only inside `1.5<=ra<3.5`, so a long hold
    drops that scan, while a forced scan or one on the floor path runs late. The
    rationale must say so."""
    loop = ast.get_source_segment(_src(LIVE), _method(LIVE, "TftLiveAnalysis", "_loop"))
    assert "1.5<=ra<3.5" in loop
    flat = _flat(READER)
    assert "is skipped, not run late" in flat
    assert "a forced scan bypasses both" in flat


def test_the_loop_floor_the_rationale_quotes_is_still_20s():
    """The rationale names a 20.0 s floor; it must be the one `_loop` compares
    against, not a literal elsewhere in the method."""
    loop = _method(LIVE, "TftLiveAnalysis", "_loop")
    floors = [
        c.value
        for n in ast.walk(loop)
        if isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.GtE)
        for c in n.comparators
        if isinstance(c, ast.Constant)
    ]
    assert floors == [20.0], floors
    assert "20.0s floor" in _flat(READER)
    assert "TftLiveAnalysis._loop" in _flat(READER)


def test_the_bound_is_per_attempt_because_the_reader_keeps_sdk_retries():
    """If the reader's client ever sets max_retries, the '2 retries' and '45s'
    sentences in its rationale are stale: reword them with the new ceiling."""
    init = _method(READER, "TftVisionReader", "__init__")
    calls = [
        n for n in ast.walk(init)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and n.func.attr == "Anthropic"
    ]
    assert len(calls) == 1
    assert "max_retries" not in {k.arg for k in calls[0].keywords}
    assert "with_options" not in _src(READER)
    flat = _flat(READER)
    assert "per attempt" in flat and "2 retries" in flat and "45s" in flat
    # 45s is three attempts at this value.
    values = [
        n.value.value for n in ast.parse(_src(READER)).body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_REQUEST_TIMEOUT_S" for t in n.targets)
        and isinstance(n.value, ast.Constant)
    ]
    assert values == [15], values
