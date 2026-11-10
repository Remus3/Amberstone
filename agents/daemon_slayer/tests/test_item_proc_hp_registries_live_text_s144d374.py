"""S144-D-374..377 - three DS caster-HP item registries match the live text they cite.

WHY. The Anguish self-heal (RM-103), Heartsteel permanent-HP (R137) and item
caster-HP proc (RM-91 T2) registries document their ids, maps, source text and
cadence from the patch they were written at (16.14.1). Their credit and mirror
guards pin the VALUES; nothing pinned the prose to the live snapshot, and each
had drifted.

* S144-D-374 ``_item_proc_heal``: it put 2502 on maps "11 / 12 / 21 / 35" (live:
  11, 12 and 453) in a "706-item index" (live: 699). It never said that the 3%
  bonus-health ratio is Meraki-only: live DDragon prints the 250% heal but no
  ratio, and Meraki is frozen at content patch 25.15 (RM-808 source order).
* S144-D-375 ``_item_health_stack``: it said the 3084 damage half "carries
  every_n_seconds=3.5"; RM-99b / A-04 moved 3084 to 30.0, and only the mirror
  223084 still carries 3.5. It called its mechanic "verbatim, wiki + DDragon
  agreeing"; the live DDragon sentence is different wording. It said the Meraki
  body is identical across "all five" vendored dirs; it is identical across
  every vendored dir through 16.22.1. It called 223084 the Arena mirror only;
  it is live on maps 12 and 30 (the resolver hands it out under arena only).
* S144-D-376 ``_item_caster_hp_proc``: it said "2502 becomes 222502 on ARAM";
  222502 is the Arena copy (map 30 only) and ARAM buys 2502. It called Sunfire /
  Titanic at 0.10 the largest converted fraction; Reverberation 447114 (0.20),
  Arena Heartsteel 223084 and Void Immolation 223069 are larger.
* S144-D-377 (filed, Tier-2, not changed here): live Hellfire Hatchet 4017 Char
  grows with "how much more max Health they have than you", up to a 3000 health
  difference. ``ITEM_EFFECTS["4017"]`` reads ``caster_max_hp - target_max_hp``
  capped at 2000, the other direction. The deny in ``_DENIED_ITEM_IDS`` holds
  under either reading; the docstring now names the gap.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Docstring
and comment fixes only; no registry value or code path changes, so scorer
output is byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from agents.daemon_slayer import _effects_data as effects_data_mod
from agents.daemon_slayer import _item_caster_hp_proc as hp_proc_mod
from agents.daemon_slayer import _item_health_stack as stack_mod
from agents.daemon_slayer import _item_proc_heal as heal_mod
from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import CallContext

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"


def _patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


@cache
def _items() -> dict[str, Any]:
    raw = json.loads(
        (_DATA / _patch() / "items.json").read_text(encoding="utf-8")
    )
    return raw["data"]


@cache
def _meraki_body(patch: str) -> dict[str, Any]:
    raw = json.loads(
        (_DATA / patch / "items_meraki.json").read_text(encoding="utf-8")
    )
    return raw["items"]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _desc(iid: str) -> str:
    return _plain(_items()[iid].get("description", ""))


def _maps(iid: str) -> list[str]:
    return sorted(
        (m for m, on in _items()[iid].get("maps", {}).items() if on), key=int
    )


def _names(name: str) -> set[str]:
    return {k for k, v in _items().items() if v.get("name") == name}


def _flat(text: str) -> str:
    return " ".join(text.split())


def _meraki_text(iid: str, name: str) -> str:
    row = _meraki_body(_patch())[iid]
    for block in list(row.get("passives") or []) + list(row.get("active") or []):
        if block.get("name") == name:
            return block.get("effects") or ""
    raise AssertionError(f"Meraki {iid} carries no {name!r} passive or active")


def _source(mod: Any) -> str:
    return _flat(inspect.getsource(mod))


_HEAL_DOC = _flat(heal_mod.__doc__ or "")
_STACK_DOC = _flat(stack_mod.__doc__ or "")
_PROC_DOC = _flat(hp_proc_mod.__doc__ or "")


@pytest.mark.parametrize("doc", [_HEAL_DOC, _STACK_DOC, _PROC_DOC])
def test_docstring_cites_no_snapshot_line_numbers(doc: str) -> None:
    assert not re.search(r"items(?:_meraki)?\.json:\d", doc)


# --------------------------------------------------------------------------
# S144-D-374 - _item_proc_heal
# --------------------------------------------------------------------------


def test_proc_heal_registry_is_every_live_unending_despair() -> None:
    assert _names("Unending Despair") == {"2502", "222502"}
    assert set(heal_mod._ITEM_PROC_HEAL_BONUS_HP_SCALING) == {"2502", "222502"}
    assert "322502" not in _items()


def test_proc_heal_index_size_matches_live() -> None:
    assert f"{len(_items())}-item index" in _HEAL_DOC
    assert "706-item" not in _HEAL_DOC


def test_proc_heal_maps_match_live() -> None:
    assert _maps("2502") == ["11", "12", "453"]
    assert _maps("222502") == ["30"]
    assert "``maps`` 11 / 12 / 453" in _HEAL_DOC
    assert "21 / 35" not in _HEAL_DOC
    assert "``maps`` 30 only" in _HEAL_DOC


def test_proc_heal_both_ids_print_the_250_percent_heal() -> None:
    for iid in ("2502", "222502"):
        assert "heal for 250% of the damage dealt" in _desc(iid), iid
        assert "Anguish Every 4 seconds" in _desc(iid), iid


def test_proc_heal_ratio_is_meraki_only_and_says_so() -> None:
    anguish = _meraki_text("2502", "Anguish")
    assert "3% of your '''bonus''' health" in anguish
    assert "250% of the" in anguish
    assert "within 650 units" in anguish
    # Live DDragon prints the multiplier but no bonus-health ratio.
    assert "3%" not in _desc("2502")
    assert "3%" not in _desc("222502")
    assert "Meraki-only" in _HEAL_DOC
    assert "RM-808" in _HEAL_DOC


def test_proc_heal_mirror_stat_block_matches_live() -> None:
    assert _desc("2502").startswith("400 Health 50 Armor 15 Ability Haste")
    assert _desc("222502").startswith("350 Health 50 Armor 10 Ability Haste")
    assert "350 HP / 10 AH vs the base 400 / 15" in _HEAL_DOC


def test_proc_heal_cites_the_slice_c_test_by_its_path() -> None:
    path = Path(__file__).resolve().parent / "test_r144_mirror_slice_c.py"
    cite = path.relative_to(_REPO_ROOT).as_posix()
    assert cite in _HEAL_DOC
    assert path.is_file()


# --------------------------------------------------------------------------
# S144-D-375 - _item_health_stack
# --------------------------------------------------------------------------


def test_health_stack_meraki_body_is_identical_through_the_cited_dir() -> None:
    m = re.search(r"16\.10\.1 \.\. (16\.\d+\.\d+)", _STACK_DOC)
    assert m, "the docstring no longer names its vendored-dir range"
    end = m.group(1)
    dirs = sorted(
        (
            p.name
            for p in _DATA.iterdir()
            if p.is_dir()
            and re.fullmatch(r"16\.\d+\.\d+", p.name)
            and (p / "items_meraki.json").is_file()
        ),
        key=lambda s: tuple(int(x) for x in s.split(".")),
    )
    assert dirs[0] == "16.10.1"
    assert end in dirs
    span = dirs[: dirs.index(end) + 1]
    first = _meraki_body(span[0])
    assert all(_meraki_body(d) == first for d in span), span
    assert "all five vendored" not in _STACK_DOC
    assert "all five vendored" not in _source(effects_data_mod)


def test_health_stack_coefficient_meraki_8_ddragon_10() -> None:
    assert "8% of that amount" in _meraki_text("3084", "Colossal Consumption")
    assert "grants 10% of the damage as max Health" in _desc("3084")
    assert stack_mod._ITEM_HEALTH_STACK_PCT["3084"] == 0.10
    assert "grants 10% of the damage as max Health" in _source(stack_mod)


def test_health_stack_quotes_the_live_ddragon_sentence() -> None:
    m = re.search(r"If an enemy champion is nearby.*?as max Health\.", _desc("3084"))
    assert m
    assert m.group(0) in _STACK_DOC
    assert "verbatim, wiki + DDragon" not in _STACK_DOC
    # Kept for test_heartsteel_cadence_a04, which reads this phrase.
    assert "30 second cooldown PER TARGET" in _STACK_DOC


def test_health_stack_cadence_prose_matches_the_damage_half() -> None:
    assert ITEM_EFFECTS["3084"].periodics[0].every_n_seconds == 30.0
    assert ITEM_EFFECTS["223084"].periodics[0].every_n_seconds == 3.5
    assert effects_data_mod.HEARTSTEEL_CADENCE_FIX_IDS == ("223084",)
    assert "``every_n_seconds=30.0``" in _STACK_DOC
    assert "HEARTSTEEL_CADENCE_FIX_IDS" in _STACK_DOC
    assert "RM-99b" in _STACK_DOC
    assert (
        "The damage half in ``_effects_data`` carries ``every_n_seconds=3.5``"
        not in _STACK_DOC
    )


def test_health_stack_mirror_maps_and_stats_match_live() -> None:
    from core.daemon_slayer_resolver import name_to_id

    assert _names("Heartsteel") == {"3084", "223084"}
    assert _maps("223084") == ["12", "30"]
    assert _maps("3084") == ["11", "12", "453"]
    assert name_to_id("Heartsteel", mode="aram") == "3084"
    assert name_to_id("Heartsteel", mode="arena") == "223084"
    assert _items()["223084"]["gold"]["total"] == 2500
    assert _items()["3084"]["gold"]["total"] == 3000
    assert _desc("223084").startswith("700 Health")
    assert _desc("3084").startswith("900 Health")
    assert "%" not in _desc("223084")
    assert "maps 12 and 30" in _source(stack_mod)


# --------------------------------------------------------------------------
# S144-D-376 - _item_caster_hp_proc
# --------------------------------------------------------------------------


def test_caster_hp_proc_mirror_prefix_example_matches_live() -> None:
    assert _maps("222502") == ["30"]
    assert _items()["2501"]["name"] == "Overlord's Bloodmail"
    assert _items()["447111"]["name"] == "Overlord's Bloodmail"
    assert _maps("447111") == ["30"]
    assert "222502 on ARAM" not in _PROC_DOC
    assert "Overlord's Bloodmail 2501" in _PROC_DOC


def test_caster_hp_proc_fraction_ceiling_names_the_live_maximum() -> None:
    census = hp_proc_mod.caster_hp_proc_census()
    ceilings = {
        iid: e.fires_per_fight * (e.max_hp_pct + e.bonus_hp_pct) / 100.0
        for iid, e in census.items()
    }
    top = max(ceilings, key=ceilings.__getitem__)
    assert top == "447114"
    assert ceilings[top] == pytest.approx(0.20)
    assert ceilings[top] < hp_proc_mod._MAX_CONVERTED_FRACTION
    assert ceilings["223084"] > 0.10
    assert ceilings["223069"] > 0.10
    src = _source(hp_proc_mod)
    assert "the largest shipped value is Sunfire / Titanic at 0.10" not in src
    assert "Reverberation 447114" in src


def test_caster_hp_proc_one_pool_per_item_at_the_cited_patch() -> None:
    for iid, e in hp_proc_mod.caster_hp_proc_census().items():
        assert (e.max_hp_pct > 0.0) != (e.bonus_hp_pct > 0.0), iid
    assert "for every shipped item at 16.14.1" not in _source(hp_proc_mod)
    assert f"for every shipped item at {_patch()}" in _source(hp_proc_mod)


# --------------------------------------------------------------------------
# S144-D-377 - Hellfire Hatchet Char direction (filed, Tier-2)
# --------------------------------------------------------------------------


def _char(caster_max_hp: float, target_max_hp: float) -> float:
    proc = ITEM_EFFECTS["4017"].periodics[0]
    return proc.resolve_damage(
        CallContext(
            base_ad=100.0,
            bonus_ad=50.0,
            level=13,
            caster_max_hp=caster_max_hp,
            target_max_hp=target_max_hp,
        )
    )


def test_hellfire_live_text_scales_on_target_minus_caster() -> None:
    assert _names("Hellfire Hatchet") == {"4017"}
    assert _maps("4017") == ["30"]
    text = _desc("4017")
    assert "how much more max Health they have than you" in text
    assert "maximum is reached at 3000 health difference" in text


def test_hellfire_engine_still_reads_caster_minus_target() -> None:
    # The filed S144-D-377 state: the engine rewards the wielder out-tanking the
    # target, the opposite of the live text. A Tier-2 fix makes this fail on
    # purpose; update it and the docstring together.
    # Same target, so the outer target-max-HP magnitude is fixed: only the
    # health-difference term moves.
    assert _char(3000.0, 2400.0) > _char(2400.0, 2400.0)
    # A target with MORE max health than the wielder earns no difference bonus,
    # however large the gap; live text says that gap is the bonus.
    assert _char(1000.0, 3000.0) == pytest.approx(_char(3000.0, 3000.0))


def test_hellfire_docstring_names_the_filed_gap_and_keeps_the_deny() -> None:
    assert "4017" in hp_proc_mod._DENIED_ITEM_IDS
    assert "S144-D-377" in _PROC_DOC
    assert "how much more max Health they have than you" in _PROC_DOC
    src = _source(hp_proc_mod)
    assert "No mirror of it exists at 16.14.1" not in src
    assert "Arena-only" in src
