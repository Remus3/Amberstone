"""RM-1353: core/tft_stage_gate.py cites its neighbours by symbol.

The module prose carried five `file.py:<line>` anchors into
tft/tft_state_reader.py, core/tft_worker.py and lcu/snapshot_shape.py. A line
number is a measurement at one commit and they had drifted (the reader's
`going_backward` is not at `:181`, the OCR loop is not at `:84`). The prose now
names the symbol; these guards keep it that way and pin that each cited symbol
still exists where the prose says it does.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "core" / "tft_stage_gate.py"

# `name.py:123`, `name.py:12-34`, `sr.json:4`, `lines 12`. A bare `(:2999` is
# the Live Client port in this module's prose, not a cite, so it is not matched.
_LINE_CITE = re.compile(
    r"[A-Za-z_/.]+\.(?:py|js|json):\d+"
    r"|\bat :\d+|, :\d+\)|\bto :\d+"
    r"|\blines? \d{2,}"
)


def test_module_cites_no_file_line_numbers():
    text = MODULE.read_text(encoding="utf-8")
    assert _LINE_CITE.findall(text) == [], "cite a symbol, not a line number"


def test_line_cite_pattern_catches_the_old_forms():
    for old in (
        "(`going_backward`, tft/tft_state_reader.py:181)",
        "(core/tft_worker.py:44) and",
        "(tft/tft_state_reader.py:84), so",
        "sanity bounds (tft/tft_state_reader.py:172-174): stage",
        "(names: lcu/snapshot_shape.py:74-78) ->",
        "to 0 (tft/tft_state_reader.py:145), so",
    ):
        assert _LINE_CITE.search(old), old


@pytest.mark.parametrize(
    "rel, needle",
    [
        ("tft/tft_state_reader.py", "going_backward ="),
        ("tft/tft_state_reader.py", "def _ocr_loop("),
        ("tft/tft_state_reader.py", "def _parse("),
        ("tft/tft_state_reader.py", "# Sanity bounds"),
        ("tft/tft_state_reader.py", 'gd.get("gameTime",0)'),
        ("core/tft_worker.py", "POLL_INTERVAL_S"),
        ("lcu/snapshot_shape.py", "_LOBBY_QUEUE_NAMES = {"),
    ],
)
def test_every_symbol_the_module_cites_still_exists(rel, needle):
    assert needle in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} lost {needle}"


@pytest.mark.parametrize(
    "name",
    [
        "going_backward",
        "POLL_INTERVAL_S",
        "_ocr_loop",
        "_LOBBY_QUEUE_NAMES",
        "Sanity bounds",
    ],
)
def test_prose_still_names_the_symbol(name):
    assert name in MODULE.read_text(encoding="utf-8")
