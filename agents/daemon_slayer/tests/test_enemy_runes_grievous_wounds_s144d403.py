"""S144-D-403 (split as S144-D-404 a): the ``GRIEVOUS_WOUNDS_PCT`` comment.

Measured at patch 16.22.1 (ENGINE 1.291.0) against the vendored ``item.json``
and ``summoner.json`` snapshots under ``data/meta_build/ddragon/``.

The comment above ``GRIEVOUS_WOUNDS_PCT`` in ``enemy_runes.py`` claimed a
"heavy" 50% tier on melee Mortal Reminder / Chempunk. Every Summoner's Rift
(map 11) item whose description mentions Wounds states its Wounds percent as
40% in every vendored snapshot, those two included, so no such tier exists on
that map. Items on other maps do state other Wounds percents (50%, 60%, 80%),
which is why the comment and this test are scoped to SR. The
rewritten comment is pinned whole (whitespace aside). From the feeds come its
percent (the one percent the SR items state, which must also equal
``GRIEVOUS_WOUNDS_PCT``) and its patch range (the first and last vendored
``item.json`` snapshot). Ignite's ``0.40`` (twice) comes from
``summoners.SUMMONER_SPELLS[14].antiheal_pct``. Typed as literal text: the two
item names (each checked against the feed by id 3033 / 6609), the "50%" the
comment rules out on SR (every SR "N% (Grievous )Wounds" percent is checked
to be the one percent, so no SR item states a 50% Wounds), and the rest of the
prose. Ignite's live tooltip is checked
to be templated (``{{ grievousamount*100 }}``), which is why its value stays
wiki-cited.

No value changed, only the comment, so every scorer output is byte-identical.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import enemy_runes, summoners
from agents.daemon_slayer.enemy_runes import GRIEVOUS_WOUNDS_PCT
from agents.daemon_slayer.tests.test_rune_hsp_resist_shield_live_text_s144d386 import (
    _CURRENT_TXT,
    _DDRAGON_ROOT,
    _spaced,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _text(desc: str) -> str:
    return _spaced(_TAG_RE.sub(" ", desc))


@pytest.fixture(scope="module")
def order() -> list[str]:
    if not _DDRAGON_ROOT.is_dir():
        pytest.skip("no vendored DDragon snapshots")
    patches = [c.name for c in _DDRAGON_ROOT.iterdir() if c.is_dir() and (c / "item.json").is_file()]
    patches.sort(key=lambda p: tuple(int(x) for x in p.split(".")))
    assert patches, "no vendored item.json"
    assert _CURRENT_TXT.read_text(encoding="utf-8").strip() == patches[-1]
    return patches


def _sr_wounds_items(patch: str) -> dict[str, tuple[str, list[str]]]:
    """SR item id -> (name, every "N% (Grievous )Wounds" percent it states)."""
    data = json.loads((_DDRAGON_ROOT / patch / "item.json").read_text(encoding="utf-8"))["data"]
    out = {}
    for item_id, item in data.items():
        if not item.get("maps", {}).get("11"):
            continue
        text = _text(item.get("description", ""))
        if "Wounds" in text:
            out[item_id] = (item["name"], re.findall(r"(\d+)% (?:Grievous )?Wounds", text))
    return out


def _gw_comment() -> list[str]:
    lines = Path(enemy_runes.__file__).read_text(encoding="utf-8").splitlines()
    end = lines.index(f"GRIEVOUS_WOUNDS_PCT = {GRIEVOUS_WOUNDS_PCT:.2f}")
    start = end
    while lines[start - 1].startswith("#"):
        start -= 1
    return lines[start:end]


def _ignite_tooltip() -> str:
    patch = _CURRENT_TXT.read_text(encoding="utf-8").strip()
    data = json.loads((_DDRAGON_ROOT / patch / "summoner.json").read_text(encoding="utf-8"))["data"]
    rows = [spell["tooltip"] for spell in data.values() if spell["key"] == "14"]
    assert len(rows) == 1
    return rows[0]


def test_every_sr_grievous_wounds_item_reads_the_modeled_percent(order) -> None:
    pct = f"{GRIEVOUS_WOUNDS_PCT * 100:g}"
    for patch in order:
        items = _sr_wounds_items(patch)
        assert len(items) >= 5, patch
        for item_id, (name, found) in items.items():
            assert found, (patch, item_id, name)
            assert set(found) == {pct}, (patch, item_id, name, found)
        assert items["3033"][0] == "Mortal Reminder", patch
        assert items["6609"][0] == "Chempunk Chainsword", patch


def test_grievous_wounds_comment_is_pinned_whole(order) -> None:
    stated = {p for patch in order for _name, found in _sr_wounds_items(patch).values() for p in found}
    assert len(stated) == 1, stated
    pct = stated.pop()
    assert float(pct) == GRIEVOUS_WOUNDS_PCT * 100
    ignite = f"{summoners.SUMMONER_SPELLS[14].antiheal_pct:.2f}"
    expected = (
        f"Grievous Wounds healing-reduction fraction, {pct}%. Every Summoner's Rift item whose DDragon "
        f"item.json description applies it reads {pct}% in every vendored snapshot {order[0]}..{order[-1]}, "
        "Mortal Reminder and Chempunk Chainsword included; no SR 50% tier exists to model (S144-D-403). "
        f"Ignite's tooltip is templated, so its {ignite} stays the LoL wiki value (summoners.py Ignite "
        f"antiheal_pct={ignite})."
    )
    got = _spaced(" ".join(line.removeprefix("#") for line in _gw_comment()))
    assert got == expected


def test_grievous_wounds_comment_facts() -> None:
    ignite = summoners.SUMMONER_SPELLS[14]
    assert ignite.antiheal_pct == GRIEVOUS_WOUNDS_PCT
    assert "{{ grievousamount*100 }}" in _ignite_tooltip()
    assert "LoL wiki" in _spaced(ignite.formula)
    assert enemy_runes.enemy_antiheal_pct(True) == GRIEVOUS_WOUNDS_PCT
