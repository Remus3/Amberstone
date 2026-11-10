"""Hardening pins for core.cc_conditional_impact_context (s144 true-audit).

The ARAM, Arena, Brawl and SR coach prompts pass the Live Client roster,
whose ``championName`` is a DISPLAY name ("Twisted Fate", "Nunu &
Willump"), while the cc_conditional registry keys on canonical DDragon ids
("TwistedFate", "Nunu"). Before this pass eight registered champions
rendered nothing from a live roster. The renderer also raised out of the
prompt build on a non-number kwarg, rendered "nan%" / "--10%" on a
non-finite or negative one, accepted a whitespace mode, and summed an
infinite engine value into an "infs" line.

Every test here names the defect it pins; the engine is stubbed except in
the display-name parity test, which reads the real registry.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from unittest.mock import patch

import pytest

import core.cc_conditional_impact_context as mod
from core.cc_conditional_impact_context import cc_conditional_impact_line

_PATCH_TARGET = "core.cc_conditional_impact_context.compute_cc_pressure"


@dataclass(frozen=True)
class _Res:
    conditional_cc_seconds: object = 0.0


def _spy_table(table: dict, seen: list):
    def _stub(champion, mode="SR", *, include_conditional=False):
        seen.append((champion, mode, include_conditional))
        return _Res(table.get(champion, 0.0))

    return _stub


# ---------------------------------------------------------------- F1 names

# (canonical id, Live Client display name) for every cc_conditional
# champion whose display name differs from its id, measured against the
# 16.22.1 DDragon roster this cycle.
_DISPLAY_PAIRS = (
    ("JarvanIV", "Jarvan IV"),
    ("KSante", "K'Sante"),
    ("Leblanc", "LeBlanc"),
    ("Nunu", "Nunu & Willump"),
    ("Renata", "Renata Glasc"),
    ("TahmKench", "Tahm Kench"),
    ("TwistedFate", "Twisted Fate"),
    ("XinZhao", "Xin Zhao"),
)


@pytest.mark.parametrize("cid,display", _DISPLAY_PAIRS)
def test_display_name_renders_same_line_as_canonical_id(cid, display):
    by_id = cc_conditional_impact_line([cid], "ARAM")
    assert by_id, f"{cid} carries no conditional CC any more - re-measure"
    assert cc_conditional_impact_line([display], "ARAM") == by_id


def test_display_name_reaches_engine_as_canonical_id():
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"TwistedFate": 0.6}, seen)):
        line = cc_conditional_impact_line(["  Twisted Fate "], "SR")
    assert [s[0] for s in seen] == ["TwistedFate"]
    assert line.startswith("Enemy conditional CC pressure: 0.6s")


def test_resolver_failure_falls_back_to_the_name(caplog):
    seen: list = []

    def _boom(_name):
        raise RuntimeError("resolver down")

    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, seen)), patch(
        "core.archetype_picks.canonical_champion_id", _boom
    ), caplog.at_level(logging.DEBUG, logger=mod.__name__):
        line = cc_conditional_impact_line(["Brand"], "SR")
    assert [s[0] for s in seen] == ["Brand"]
    assert "1.4s" in line


def test_one_for_all_duplicates_still_sum():
    # ONEFORALL routes to the Brawl coach: five enemies of ONE champion
    # each carry the conditional CC, so a roster is never de-duplicated.
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"TwistedFate": 0.6}, seen)):
        line = cc_conditional_impact_line(["Twisted Fate"] * 3, "SR")
    assert len(seen) == 3
    assert line.startswith("Enemy conditional CC pressure: 1.8s")


# --------------------------------------------------------- F2 roster shape


@pytest.mark.parametrize(
    "roster",
    ["Brand", b"Brand", {"Brand": 1}, {"Brand"}, (n for n in ["Brand"]), 5],
)
def test_only_a_list_or_tuple_roster_is_read(roster):
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4, "B": 9.0}, seen)):
        assert cc_conditional_impact_line(roster, "SR") == ""
    assert seen == []


def test_non_string_entries_never_reach_engine():
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, seen)):
        line = cc_conditional_impact_line(
            [5, None, b"Brand", ["Brand"], True, "", "   ", "Brand"], "SR"
        )
    assert [s[0] for s in seen] == ["Brand"]
    assert "1.4s" in line


def test_oversized_name_never_reaches_engine():
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({}, seen)):
        assert cc_conditional_impact_line(["X" * 200], "SR") == ""
    assert seen == []


def test_roster_read_is_bounded():
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"Brand": 0.1}, seen)):
        cc_conditional_impact_line(["Brand"] * 500, "SR")
    assert len(seen) == mod._MAX_ENEMIES
    assert mod._MAX_ENEMIES >= 14  # Arena: 7 enemy duos


# ----------------------------------------------------------------- F3 mode


@pytest.mark.parametrize("mode", ["   ", "\t", 5, ["ARAM"], b"ARAM", True])
def test_blank_or_non_string_mode_is_empty_without_engine(mode):
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, seen)):
        assert cc_conditional_impact_line(["Brand"], mode) == ""
    assert seen == []


def test_padded_mode_reaches_engine_stripped():
    seen: list = []
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, seen)):
        cc_conditional_impact_line(["Brand"], "  ARAM ")
    assert seen == [("Brand", "ARAM", True)]


# ---------------------------------------------------------- F4 tuning kwargs


@pytest.mark.parametrize(
    "window", [math.nan, math.inf, -math.inf, "6", None, True, False, -0.0]
)
def test_unusable_fight_window_is_empty_never_raises(window):
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, [])):
        assert cc_conditional_impact_line(
            ["Brand"], "SR", fight_window_s=window
        ) == ""


@pytest.mark.parametrize(
    "factor", [math.nan, math.inf, None, "0.5", True, -0.1, 1.5]
)
def test_unusable_effectiveness_factor_is_empty_never_raises(factor):
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, [])):
        assert cc_conditional_impact_line(
            ["Brand"], "SR", cc_effectiveness_factor=factor
        ) == ""


def test_integer_kwargs_still_render():
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, [])):
        line = cc_conditional_impact_line(
            ["Brand"], "SR", fight_window_s=7, cc_effectiveness_factor=1
        )
    assert line.endswith("= 20% saturation, blended-EHP impact -20%")


# ------------------------------------------------------- F5 engine values


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "1.5"])
def test_unusable_engine_value_is_skipped(bad):
    with patch(_PATCH_TARGET, _spy_table({"Bad": bad, "Brand": 1.4}, [])):
        assert cc_conditional_impact_line(["Bad"], "SR") == ""
        line = cc_conditional_impact_line(["Bad", "Brand"], "SR")
    assert line.startswith("Enemy conditional CC pressure: 1.4s")
    assert "nan" not in line and "inf" not in line


def test_overflowing_sum_is_empty_not_inf():
    with patch(_PATCH_TARGET, _spy_table({"Big": 1e308}, [])):
        assert cc_conditional_impact_line(["Big", "Big"], "SR") == ""


def test_engine_failure_is_logged_and_skipped(caplog):
    def _stub(champion, mode="SR", *, include_conditional=False):
        if champion == "Boom":
            raise KeyError("registry row")
        return _Res(1.4)

    with patch(_PATCH_TARGET, _stub), caplog.at_level(
        logging.DEBUG, logger=mod.__name__
    ):
        line = cc_conditional_impact_line(["Boom", "Brand"], "SR")
    assert "1.4s" in line
    assert any("Boom" in r.getMessage() for r in caplog.records)


def test_line_has_no_double_minus_or_non_finite_text():
    with patch(_PATCH_TARGET, _spy_table({"Brand": 1.4}, [])):
        line = cc_conditional_impact_line(
            ["Brand"], "SR", cc_effectiveness_factor=0.0
        )
    assert "--" not in line
    assert line.endswith("blended-EHP impact -0%")
