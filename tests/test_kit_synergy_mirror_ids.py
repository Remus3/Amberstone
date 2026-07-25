"""Mode-mirror id coverage for core/build_planner/kit_synergy.py curated id sets.

The four curated effect-flag tables in kit_synergy are frozensets of CANONICAL
4-digit Summoner's Rift item ids. The live 706-item catalog ships the SAME item
a second time under a 6-digit mode-mirror id (Arena / map 30 uses a ``22``
prefix), and ``item_effect_flags`` originally tested membership against the raw
id - so every mirror form silently lost its curated flags:

    item_effect_flags("3508")   -> AH, bonusAD, on-hit, spellblade
    item_effect_flags("223508") -> AH, on-hit                (spellblade LOST)

The consequence measured in the committed live table
data/daemon_slayer/16.14.1/build_orders_arena.json: Essence Reaver's Arena
mirror 223508 sat at slot 1 for Caitlyn / Jinx / Twitch across all three comp
classes, because coherence.py:109-110 calls stat_fit / anti_synergy_penalty with
the raw Arena row id and neither dock ever fired.

These tests are catalog-DRIVEN, not hand-listed: the structural assumptions that
make suffix normalization safe (ids are only 4- or 6-digit numerics; a mirror is
a 2-digit prefix plus the canonical id) are asserted against the live items.json
so a Riot id-space change fails here loudly instead of silently re-opening the
gap. Cross-item float comparisons are only made after the test itself proves the
two entries carry an IDENTICAL stat line (R161 doctrine B: a mirror credits its
own DDragon stats, so equal fit is NOT guaranteed in general).

ASCII only - use " - " for a clause break (repo hard rule).
"""
from __future__ import annotations

import json

import pytest

from core.build_planner import kit_synergy as ks
from core.build_planner.kit_synergy import (
    _BONUS_AD_SCALING_IDS,
    _MAXHP_DAMAGE_IDS,
    _SPELLBLADE_IDS,
    _SPELLBLADE_NONUSER_PENALTY,
    _TRUE_DAMAGE_IDS,
    anti_synergy_penalty,
    canonical_item_id,
    champ_kit_traits,
    item_effect_flags,
    item_vector,
    stat_fit,
)

# Every curated id table in the module, by attribute name. A new table added to
# kit_synergy without mirror coverage should be added here.
CURATED_SETS: dict[str, frozenset] = {
    "_MAXHP_DAMAGE_IDS": _MAXHP_DAMAGE_IDS,
    "_TRUE_DAMAGE_IDS": _TRUE_DAMAGE_IDS,
    "_BONUS_AD_SCALING_IDS": _BONUS_AD_SCALING_IDS,
    "_SPELLBLADE_IDS": _SPELLBLADE_IDS,
}

ALL_CURATED_IDS: frozenset[str] = frozenset().union(*CURATED_SETS.values())

# A pure crit / auto marksman - champ_kit_traits(...)["spellblade_user"] is False,
# so the spellblade dock applies. Asserted in the dock tests rather than assumed.
CRIT_ADCS = ("Jinx", "Caitlyn", "Twitch")

# The ONE catalog id pair where a 2-digit prefix strip crosses between two
# genuinely DIFFERENT items (3172 Gunmetal Greaves, maps 11/21/35, vs 223172
# Zephyr, map 30). Neither is curated, so the hazard is inert - the guard test
# below fails if a future slice ever adds 3172 to a curated table.
KNOWN_CROSS_ITEM_SUFFIX_PAIR = ("3172", "223172")


@pytest.fixture(scope="module")
def catalog() -> dict[str, dict]:
    """The live active-patch items.json 'data' map, keyed by str(id)."""
    patch = ks._resolve_ds_patch()
    assert patch, "no active DS patch in data/daemon_slayer/current.txt"
    path = ks._DS_DIR / patch / "items.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    out = {str(k): v for k, v in data.items() if isinstance(v, dict)}
    assert len(out) > 500, f"catalog looks truncated: {len(out)} entries"
    return out


# --------------------------------------------------------------------------- #
# Structural assumptions that make suffix normalization provably safe.
# --------------------------------------------------------------------------- #
def test_catalog_ids_are_only_four_or_six_digit_numerics(catalog):
    """Suffix normalization assumes exactly two id widths - assert it."""
    bad = [i for i in catalog if not (i.isdigit() and len(i) in (4, 6))]
    assert bad == [], f"unexpected id shapes in the live catalog: {bad[:20]}"


def test_no_same_length_suffix_pairs_in_catalog(catalog):
    """No id is a suffix of another of the SAME width - so width alone decides.

    Guarantees the "6 digits -> take the last 4" rule is unambiguous: a shorter
    id can only ever be a suffix of a wider one.
    """
    ids = sorted(catalog)
    same = [(a, b) for a in ids for b in ids
            if a != b and len(a) == len(b) and b.endswith(a)]
    assert same == [], f"same-width suffix pairs break the width rule: {same[:10]}"


def test_every_six_digit_suffix_pair_is_a_two_digit_prefix(catalog):
    """Every suffix relation in the catalog is <2-digit prefix> + <4-digit id>."""
    ids = sorted(catalog)
    offenders = [
        (a, b) for a in ids for b in ids
        if a != b and b.endswith(a) and not (len(a) == 4 and len(b) == 6)
    ]
    assert offenders == [], f"non-2-digit-prefix suffix relations: {offenders[:10]}"


# --------------------------------------------------------------------------- #
# canonical_item_id - the normalizer itself.
# --------------------------------------------------------------------------- #
def test_canonical_item_id_strips_the_arena_mirror_prefix():
    assert canonical_item_id("223508") == "3508"
    assert canonical_item_id("226692") == "6692"


def test_canonical_item_id_is_identity_on_canonical_ids():
    for iid in ("3508", "6692", "3031", "3057"):
        assert canonical_item_id(iid) == iid


def test_canonical_item_id_accepts_int_and_none():
    assert canonical_item_id(223508) == "3508"
    assert canonical_item_id(3508) == "3508"
    assert canonical_item_id(None) is None


def test_canonical_item_id_leaves_non_numeric_untouched():
    assert canonical_item_id("abc123") == "abc123"
    assert canonical_item_id("22350") == "22350"  # 5 digits - not a mirror width


def test_canonical_item_id_is_identity_on_every_canonical_catalog_id(catalog):
    """Collision-negative half 1 - normalization can never MERGE two 4-digit ids.

    Driven from the live catalog rather than a hand-written list: every 4-digit
    catalog id must normalize to itself, so the map is injective on the whole
    canonical keyspace and no unrelated pair of real items can be conflated.
    """
    for iid in catalog:
        if len(iid) == 4:
            assert canonical_item_id(iid) == iid, iid


def test_canonical_item_id_is_idempotent_over_the_live_catalog(catalog):
    for iid in catalog:
        once = canonical_item_id(iid)
        assert canonical_item_id(once) == once, iid


def test_no_unrelated_catalog_id_normalizes_into_a_curated_set(catalog):
    """Collision-negative half 2 - the live-catalog anti-collision guard.

    For EVERY id in the live catalog whose canonical form lands in a curated
    table, the mirror and the canonical entry must be the same underlying item.
    ``tags`` is the structural identity signal (never ``name`` - the repo rule is
    to sweep by id suffix, and 5 of the 175 mirror pairs carry a renamed or blank
    name: 223095 / 223172 / 226653 / 226660 / 226675).

    This is what stops a blind endswith() from being a bug factory: if Riot ever
    reuses a curated id's number space the way 3172 / 223172 already is reused,
    this test fails instead of the scorer silently mis-flagging an item.
    """
    offenders = []
    for iid, entry in catalog.items():
        cid = canonical_item_id(iid)
        if cid == iid or cid not in ALL_CURATED_IDS:
            continue
        base = catalog.get(cid)
        if base is None:
            offenders.append((iid, cid, "canonical id absent from catalog"))
            continue
        if sorted(entry.get("tags") or []) != sorted(base.get("tags") or []):
            offenders.append((iid, cid, "tag mismatch - different items"))
    assert offenders == [], f"normalization would conflate unrelated items: {offenders}"


def test_known_cross_item_suffix_pair_stays_out_of_every_curated_set(catalog):
    """The one real cross-item suffix pair in the catalog must stay uncurated."""
    sr, mirror = KNOWN_CROSS_ITEM_SUFFIX_PAIR
    assert sr in catalog and mirror in catalog
    # Confirm they really are different items (so this guard keeps its meaning).
    assert (sorted(catalog[sr].get("tags") or [])
            != sorted(catalog[mirror].get("tags") or []))
    assert sr not in ALL_CURATED_IDS, (
        f"{sr} is now curated - {mirror} is a DIFFERENT item and would be "
        "mis-flagged; add an explicit exclusion before curating it"
    )


# --------------------------------------------------------------------------- #
# item_effect_flags - the reported bug.
# --------------------------------------------------------------------------- #
def test_arena_mirror_essence_reaver_matches_sr_flags():
    """The reported bug: 223508 lost the spellblade + bonusAD flags."""
    assert item_effect_flags("223508") == item_effect_flags("3508")
    assert "spellblade" in item_effect_flags("223508")
    assert "bonusAD" in item_effect_flags("223508")


def test_arena_mirror_eclipse_matches_sr_flags():
    """The sibling exposure: 226692 lost the bonusAD flag."""
    assert item_effect_flags("226692") == item_effect_flags("6692")
    assert "bonusAD" in item_effect_flags("226692")


@pytest.mark.parametrize("set_name", sorted(CURATED_SETS))
def test_every_curated_set_is_mirror_closed_over_the_live_catalog(set_name, catalog):
    """Every mirror form of every curated id must carry the same curated flags."""
    checked = 0
    for sr_id in sorted(CURATED_SETS[set_name]):
        sr_flags = item_effect_flags(sr_id)
        for iid in catalog:
            if len(iid) == 6 and canonical_item_id(iid) == sr_id:
                mirror_flags = item_effect_flags(iid)
                # Curated flags are id-driven; tag-driven flags come from the
                # mirror's OWN entry, so compare the curated subset only.
                curated = {"%maxHP", "true", "bonusAD", "spellblade"}
                assert (mirror_flags & curated) == (sr_flags & curated), (
                    f"{iid} (mirror of {sr_id}) curated flags "
                    f"{sorted(mirror_flags & curated)} != {sorted(sr_flags & curated)}"
                )
                checked += 1
    if CURATED_SETS[set_name]:
        assert checked > 0, f"{set_name}: no mirror ids found - coverage is vacuous"


def test_non_mirror_six_digit_ids_gain_no_curated_flag(catalog):
    """A 6-digit id whose canonical form is uncurated must gain no curated flag."""
    curated = {"%maxHP", "true", "bonusAD", "spellblade"}
    for iid in catalog:
        if len(iid) != 6:
            continue
        if canonical_item_id(iid) in ALL_CURATED_IDS:
            continue
        assert not (item_effect_flags(iid) & curated), (
            f"{iid} normalizes to {canonical_item_id(iid)} (uncurated) yet gained "
            f"{sorted(item_effect_flags(iid) & curated)}"
        )


# --------------------------------------------------------------------------- #
# SR byte-identical pin - the fix must move NO Summoner's Rift behavior.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("sr_id", "expected"), [
    ("3508", {"AH", "bonusAD", "on-hit", "spellblade"}),   # Essence Reaver
    ("6692", {"AH", "bonusAD"}),                           # Eclipse
    ("3057", {"AH", "on-hit", "spellblade"}),              # Sheen
    ("3078", {"AH", "on-hit", "spellblade"}),              # Trinity Force
    ("6632", {"%maxHP", "AH", "on-hit", "spellblade"}),    # Divine Sunderer
    ("3142", {"bonusAD"}),                                 # Youmuu's Ghostblade
    ("3071", {"AH", "bonusAD", "on-hit"}),                 # Black Cleaver
    ("3153", {"%maxHP", "on-hit"}),                        # BoRK
    ("6653", {"%maxHP"}),                                  # Liandry's
    ("4637", {"%maxHP"}),                                  # Demonic Embrace
    ("3031", set()),                                       # Infinity Edge
])
def test_sr_effect_flags_are_pinned(sr_id, expected):
    """Captured from the pre-fix module - SR flag sets must not move at all."""
    assert item_effect_flags(sr_id) == frozenset(expected)


@pytest.mark.parametrize("champ", CRIT_ADCS)
@pytest.mark.parametrize(("sr_id", "fit", "pen"), [
    ("3508", None, 2.5),
    ("3031", None, 0.0),
])
def test_sr_dock_magnitudes_are_pinned(champ, sr_id, fit, pen):
    """The SR penalty magnitudes the fix must leave byte-identical."""
    assert anti_synergy_penalty(sr_id, champ) == pytest.approx(pen)


def test_mirror_stat_axes_still_come_from_the_mirrors_own_entry(catalog):
    """R161 doctrine B pin - normalization must NOT redirect the stat lookup.

    Trinity Force's Arena mirror ships a different DDragon stat line (375 HP /
    40 AD / 25 percent AS vs 333 / 36 / 30), so its stat axes must differ from
    the SR entry even though its curated flags now match.
    """
    assert catalog["3078"]["stats"] != catalog["223078"]["stats"], (
        "fixture assumption broken - 3078 and 223078 now share a stat line"
    )
    sr_vec, mirror_vec = item_vector("3078"), item_vector("223078")
    assert sr_vec["AD"] != mirror_vec["AD"]
    assert sr_vec["HP-scaling"] != mirror_vec["HP-scaling"]


# --------------------------------------------------------------------------- #
# Dock behavior - anti_synergy_penalty / stat_fit on the Arena mirror.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_crit_adc_is_not_a_spellblade_user(champ):
    """Precondition for the dock tests - asserted, never assumed."""
    assert champ_kit_traits(champ)["spellblade_user"] is False


@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_anti_synergy_docks_arena_essence_reaver_for_a_crit_adc(champ, catalog):
    """The live bug: the spellblade dock never fired on the Arena mirror.

    Asserted as a computed quantity - the mirror's penalty must exceed its
    flag-less crit-core baseline (Infinity Edge's Arena mirror) by at least the
    spellblade non-user dock.
    """
    baseline = anti_synergy_penalty("223031", champ)   # Arena Infinity Edge
    docked = anti_synergy_penalty("223508", champ)     # Arena Essence Reaver
    assert docked - baseline >= _SPELLBLADE_NONUSER_PENALTY


@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_arena_essence_reaver_docks_identically_to_the_sr_twin(champ, catalog):
    """Equal stat line -> equal dock. The equality precondition is asserted."""
    assert catalog["3508"]["stats"] == catalog["223508"]["stats"], (
        "fixture assumption broken - 3508 and 223508 no longer share a stat line"
    )
    assert (anti_synergy_penalty("223508", champ)
            == pytest.approx(anti_synergy_penalty("3508", champ)))


@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_stat_fit_drops_the_spellblade_axes_on_the_arena_mirror(champ, catalog):
    """stat_fit must strip the artifact on-hit / bonusAD credit for the mirror."""
    assert catalog["3508"]["stats"] == catalog["223508"]["stats"]
    assert stat_fit("223508", champ) == pytest.approx(stat_fit("3508", champ))


@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_arena_crit_core_out_fits_the_arena_spellblade_mirror(champ):
    """The whole point of the dock: Arena Infinity Edge must now out-fit 223508.

    Both are 2500-gold Arena mirrors with a 25 percent crit line, so the
    comparison is between two same-tier rows rather than across gold tiers.
    """
    ie_fit = stat_fit("223031", champ)
    er_fit = stat_fit("223508", champ)
    assert ie_fit > er_fit, f"{champ}: IE {ie_fit:.4f} <= ER {er_fit:.4f}"


@pytest.mark.parametrize("champ", CRIT_ADCS)
def test_arena_eclipse_regains_its_bonus_ad_credit(champ, catalog):
    """226692 lost the bonusAD axis entirely - it must now match its SR twin."""
    assert catalog["6692"]["stats"] == catalog["226692"]["stats"]
    assert item_vector("226692")["bonusAD"] == pytest.approx(1.0)
    assert stat_fit("226692", champ) == pytest.approx(stat_fit("6692", champ))
