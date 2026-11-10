"""S144-D-382 - the RM-41 burst off-axis gate matches the live text it cites.

WHY. ``_burst_off_axis`` (RM-41, ENGINE 1.240.0) names Shaco as its standing
no-decisive-split example and quoted his split as "0.521 magical / 0.347
physical". That was the lolmath ``damage_distribution`` in every vendored
dir 16.10.1..16.18.1; from 16.19.1 it moved, and at 16.22.1 it reads 0.503 /
0.342. Shaco resolves to ``None`` at both, and for the same two reasons both
times: magical leads, but under the 0.55 dominance floor and inside the 0.20
margin. The doc now dates the old split and quotes the live one (the comment
in ``test_burst_off_axis_rm41.py`` likewise). The Akali 85.5 percent figure
is a dated 1.239.0 measurement; live reads 86.7.

The item-side examples (Hextech Gunblade 80 AP + 40 AD, Statikk Shiv 45 /
45, Berserker's Greaves carrying attack speed only) and the shared
threshold pair with ``core.archetype_picks`` are pinned here as live facts.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
and comment fixes only; no code path changes.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _burst_off_axis as boa
from core import archetype_picks

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_RM41_TEST = Path(__file__).resolve().parent / "test_burst_off_axis_rm41.py"


def _patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _champions(patch: str) -> dict[str, Any]:
    raw = json.loads(
        (_DATA / patch / "champions.json").read_text(encoding="utf-8")
    )
    return raw["data"]


@cache
def _items() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "items.json").read_text(encoding="utf-8")
    )
    return raw["data"]


def _vendored() -> list[str]:
    return sorted(
        d.name for d in _DATA.iterdir() if (d / "champions.json").is_file()
    )


def _dist(patch: str, champion: str) -> dict[str, float]:
    return _champions(patch)[champion]["lolmath"]["damage_distribution"]


def _flat(text: str) -> str:
    return " ".join(text.split())


_DOC = _flat(boa.__doc__ or "")


def test_doc_is_nonempty():
    assert len(_DOC) > 500


def test_thresholds_mirror_archetype_picks():
    assert boa._AXIS_DOMINANT_MIN == archetype_picks._AXIS_DOMINANT_MIN
    assert boa._AXIS_MARGIN_MIN == archetype_picks._AXIS_MARGIN_MIN
    assert "(0.55 / 0.20)" in _DOC


def test_shaco_live_split_is_quoted_and_indecisive():
    dist = _dist(_patch(), "Shaco")
    magical = round(float(dist["magical"]), 3)
    physical = round(float(dist["physical"]), 3)
    assert boa.champion_burst_axis(_champions(_patch())["Shaco"]) is None
    assert magical < boa._AXIS_DOMINANT_MIN
    assert magical - physical < boa._AXIS_MARGIN_MIN
    assert f"{magical:.3f} / {physical:.3f} at {_patch()}" in _DOC
    assert "under the 0.55 dominance floor and inside the 0.20 margin" in _DOC
    assert "at every vendored patch" in _DOC


@pytest.mark.parametrize("patch", ["16.10.1", "16.14.1", "16.18.1"])
def test_shaco_historic_split_is_dated(patch):
    assert (_DATA / patch / "champions.json").is_file(), f"{patch} champions.json not vendored"
    dist = _dist(patch, "Shaco")
    magical = float(dist["magical"])
    physical = float(dist["physical"])
    assert round(magical, 3) == 0.521
    assert round(physical, 3) == 0.347
    assert physical < magical < boa._AXIS_DOMINANT_MIN
    assert magical - physical < boa._AXIS_MARGIN_MIN
    assert boa.champion_burst_axis(_champions(patch)["Shaco"]) is None
    assert "0.521 magical / 0.347 physical at 16.10.1..16.18.1" in _DOC


@pytest.mark.parametrize("patch", _vendored())
def test_shaco_fails_both_gates_in_every_vendored_dir(patch):
    dist = _dist(patch, "Shaco")
    magical = float(dist["magical"])
    physical = float(dist["physical"])
    assert physical < magical < boa._AXIS_DOMINANT_MIN
    assert magical - physical < boa._AXIS_MARGIN_MIN


def test_rm41_test_comment_quotes_both_shaco_splits():
    raw = _RM41_TEST.read_text(encoding="utf-8")
    text = _flat(re.sub(r"\n[ \t]*#[ \t]?", "\n", raw))
    assert "0.521 magical / 0.347 physical - dominant" not in text
    assert "0.503 / 0.342 at 16.22.1" in text
    assert "under the 0.55 floor and inside the 0.20 margin both times" in text


def test_akali_figure_is_dated_and_live_figure_given():
    magical = float(_dist(_patch(), "Akali")["magical"])
    assert boa.champion_burst_axis(_champions(_patch())["Akali"]) == "ap"
    assert f"{magical * 100:.1f} percent at {_patch()}" in _DOC
    assert "85.5 percent magical damage at that time" in _DOC


@pytest.mark.parametrize(
    ("item_id", "ap", "ad"),
    [("3146", 80, 40), ("3087", 45, 45)],
)
def test_hybrid_examples_are_live_and_survive_both_axes(item_id, ap, ad):
    rec = _items()[item_id]
    stats = rec["stats"]
    assert stats["FlatMagicDamageMod"] == ap
    assert stats["FlatPhysicalDamageMod"] == ad
    assert boa.is_off_axis_candidate(rec, "ap") is False
    assert boa.is_off_axis_candidate(rec, "ad") is False


def test_doc_quotes_the_live_hybrid_lines():
    assert "Hextech Gunblade 80 AP + 40 AD" in _DOC
    assert "Statikk Shiv at 45/45" in _DOC


def test_attack_speed_only_boot_is_never_stripped():
    rec = _items()["3006"]
    assert rec["name"] == "Berserker's Greaves"
    assert "PercentAttackSpeedMod" in rec["stats"]
    assert not any(
        key in rec["stats"]
        for key in boa._PHYSICAL_OFFENSE_KEYS + boa._MAGIC_OFFENSE_KEYS
    )
    assert boa.is_off_axis_candidate(rec, "ap") is False
    assert boa.is_off_axis_candidate(rec, "ad") is False
