# arch: RM-80 / A-15 on-hit route adjudication tests | section=tests | frozen=no
"""RM-80 / A-15 - "Master Yi is mis-ROUTED to the bruiser scorer".

VERDICT: REFUTED. Master Yi stays on ``ds.hybrid`` (the bruiser route), and so
does every on-hit-flavoured sibling swept alongside him. These tests PIN that
adjudication so the next roster sweep does not re-litigate it.

MEASURED at ENGINE 1.245.0 / patch 16.14.1 against live ``:8893``, comparing
``/rank-bruiser`` against ``/rank-onhit`` for each champion's OWN real build
(``data/meta_build/sr_champion_builds.json``, aggregator-A-sourced 2026-05-02):

* Master Yi's real build is Kraken Slayer > Berserker's > Guinsoo's Rageblade >
  Experimental Hexplate > Death's Dance > Guardian Angel. Two of its six slots
  are DEFENSIVE, which the blended ``alpha*dps + beta*ehp`` bruiser scorer
  credits and the pure-DPS on-hit scorer does not. Seeded at his real 3-item
  core, ``/rank-bruiser`` places Experimental Hexplate (a CORE item) at #24 of
  138 and Death's Dance at #37; ``/rank-onhit`` demotes them to #43 and #39.
  The bruiser route is strictly closer to reality on the items where the two
  routes disagree.
* The Slice-C evidence bar (an override lands only when the CURRENT route's
  top-3 have a ~0% real pick rate AND the target route's pool is the right item
  family) is NOT met: the bruiser top-3 for Yi is Blade of The Ruined King (his
  documented alt core, 57.98% WR) > Trinity Force > Lord Dominik's Regards (his
  documented vs-tank 4th, 62.37% WR). Two of three are genuinely-built items.
* FAMILY failure on the target route: because ``ds.onhit`` sums ability DPS and
  auto DPS, it over-credits AP burn items for AD champions. Liandry's Torment
  lands in the ``/rank-onhit`` top-3 for Nilah, Yasuo, Yone, Bel'Veth, Shyvana,
  Warwick and Jax - a fresh never-build violation that the bruiser route does
  not commit. So even where the on-hit route scores a marginally better mean
  rank, its pool is the WRONG family and the Slice-C bar still fails.

Per Engine/Build Conventions these are PER-CHAMPION assertions - a single
generic shape is not an acceptable validation for a route decision. ASCII only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.archetype_picks import default_for_champion
from core.ds_onhit_ap_roster import load_onhit_ap_roster
from core.ds_support_route_overrides import load_support_route_overrides

_ROSTER = (
    Path(__file__).resolve().parent.parent / "core" / "ds_support_route_overrides.json"
)

# The RM-80 subject plus every bruiser-primary champion whose real meta build
# contains an on-hit item (Guinsoo's / Wit's End / Terminus / Kraken / BotRK /
# Nashor's). Each was probed on BOTH routes and each KEEPS its current route.
_SWEPT_KEEP_BRUISER = [
    ("Master Yi", "bruiser", "assassin"),
    ("Nilah", "bruiser", "assassin"),
    ("Bel'Veth", "bruiser", "tank"),
    ("Irelia", "bruiser", "assassin"),
    ("Shyvana", "bruiser", "tank"),
    ("Viego", "bruiser", "assassin"),
    ("Yasuo", "bruiser", "assassin"),
    ("Yone", "bruiser", "assassin"),
    ("Tryndamere", "bruiser", "assassin"),
    ("Warwick", "bruiser", "tank"),
    ("Jax", "bruiser", "tank"),
    # Spot-checked alongside the on-hit cohort and confirmed genuine bruisers.
    ("Xin Zhao", "bruiser", "tank"),
    ("Yorick", "bruiser", "tank"),
    ("Nasus", "bruiser", "tank"),
    ("Udyr", "bruiser", "tank"),
    ("Volibear", "bruiser", "tank"),
]

# ``ds.onhit`` is the on-hit-AP scorer (core/ds_onhit_ap_roster.json). No AD
# on-hit carry belongs in it - that is the root cause behind the RM-80 refute.
_ONHIT_AP_ROSTER = {"Gwen", "Kayle", "KogMaw"}


@pytest.mark.parametrize(
    "champ,primary,secondary",
    [pytest.param(c, p, s, id=c.replace(" ", "_")) for c, p, s in _SWEPT_KEEP_BRUISER],
)
def test_swept_champion_keeps_its_bruiser_route(
    champ: str, primary: str, secondary: str
) -> None:
    assert default_for_champion(champ) == (primary, secondary)


def test_master_yi_is_not_routed_to_the_onhit_scorer() -> None:
    # The headline RM-80 claim, pinned as REFUTED.
    assert default_for_champion("Master Yi")[0] != "onhit"
    assert default_for_champion("MasterYi")[0] != "onhit"


@pytest.mark.parametrize(
    "champ", [pytest.param(c, id=c.replace(" ", "_")) for c, _p, _s in _SWEPT_KEEP_BRUISER]
)
def test_swept_champion_is_absent_from_both_rosters(champ: str) -> None:
    # Neither lookup may quietly take ownership of a swept champion later.
    assert champ not in load_support_route_overrides()
    assert champ not in load_onhit_ap_roster()
    assert champ.replace(" ", "").replace("'", "") not in load_onhit_ap_roster()


def test_onhit_ap_roster_stays_ap_only() -> None:
    assert set(load_onhit_ap_roster()) == _ONHIT_AP_ROSTER


def test_alias_spellings_agree_for_the_swept_cohort() -> None:
    # A partial override would make a route depend on which spelling a caller
    # used - the same trap the Renata alias test guards for Slice C.
    for a, b in (("Master Yi", "MasterYi"), ("Bel'Veth", "Belveth"),
                 ("Xin Zhao", "XinZhao")):
        assert default_for_champion(a) == default_for_champion(b), (a, b)


# --- adjudication provenance ---------------------------------------------


def _doc() -> dict:
    raw = _ROSTER.read_bytes()
    assert raw.decode("ascii")  # repo hard rule: 7-bit ASCII authored content
    return json.loads(raw.decode("ascii"))


def test_rm80_adjudication_is_recorded_in_the_override_file() -> None:
    held = _doc()["_held"]
    assert "Master Yi" in held, "RM-80 adjudication must be discoverable in _held"
    assert "RM-80" in held["Master Yi"]


def test_rm80_sibling_sweep_is_recorded() -> None:
    sweep = _doc()["_rm80_onhit_sweep"]
    # Probed champions get a per-champion verdict; the spot-checked-only ones
    # are named in the summary line. Every swept champion must appear in one.
    spot = sweep["_also_spot_checked"].split(" - ")[0]
    named = set(sweep["champions"]) | {s.strip() for s in spot.split(",")}
    for champ, _p, _s in _SWEPT_KEEP_BRUISER:
        if champ == "Master Yi":
            continue  # recorded in _held as the named RM-80 subject
        assert champ in named, f"{champ} was swept but is not recorded"


def test_override_file_scope_comment_is_no_longer_support_only() -> None:
    # The file now carries a non-Support-tag adjudication (Master Yi is
    # Fighter/Assassin), so its stated scope must say so.
    comment = _doc()["_comment"]
    assert "archetype ROUTE corrections" in comment
    assert "not support-only" in comment.lower()


def test_rm80_records_do_not_change_the_active_roster() -> None:
    # _held / _rm80_onhit_sweep are documentation blocks; only "champions" is
    # loaded, so the runtime routing table is untouched by this slice.
    assert set(load_support_route_overrides()) == {
        "Morgana",
        "Thresh",
        "Rakan",
        "Taric",
        "Bard",
    }
