# arch: A-29 CDragon surplus-AD credit seam (allowlist-gated) | section=ds-tests | frozen=no
"""A-29 / BACKLOG R129 - the CDragon surplus-block class.

``_apply_cdragon_ratio_preference`` is an OVERWRITE-only re-source: its docstring
promises "the damage-block COUNT is never changed", and its cardinality guard
(``m_counts != Counter(csig)``) falls the WHOLE form back to Meraki whenever the
two block sets do not form a clean bijection. Viego R is that case - the Meraki
snapshot carries ONE damage block (the 12/16/20 percent missing-HP strike) while
the CDragon sidecar resolves TWO mechanical blocks, the second of which is the
120 percent total-AD primary hit ("TotalDamage"). The surplus block is dropped, so
``compute_ability_dps("Viego")`` credits 0.0 for R at full target HP - both of the
snapshot block's coefficients scale on MISSING HP, which is zero there.

MEASURED 2026-07-24 at ENGINE 1.244.0 / patch 16.14.1, level 16, no items,
target_max_hp=2400, full HP: Viego R per-spell dps == 0.0 (total 51.514 from Q+W).

The seam is ``AbilitiesSnapshot.load(apply_cdragon_surplus_ad=...)``, default
False / OFF so every form is byte-identical to today. When ON it consults a
narrow hand-audited allowlist of (champion, spell_key) pairs and MERGES the named
surplus sidecar block's machine-parsed ratio fields into the designated Meraki
damage block through the existing ``_apply_cdragon_block`` field-router.

Why MERGE and not APPEND (measured, and it is the whole reason the naive design
does not work): ``compute_ability_dps`` defaults to ``block_strategy="first"``,
which evaluates ``damage_blocks[0]`` and nothing else
(``ability_dps._select_blocks``), and Viego carries NO ``champion_block_index.json``
override to widen that. A block appended at index 1 would therefore never be
read and the credit would stay 0.0. Merging the 120 percent ``total_ad_pct`` into
block 0 - which carries no AD-family field at all, so the router cannot
double-count - credits the term under every strategy, leaves the block COUNT
invariant (``test_cdragon_ratio_matcher.test_block_count_invariant_flag_on``
keeps holding), and disturbs no block index.

Why an ALLOWLIST and not a general append seam: a general "append every surplus
CDragon block" pass was measured over the live sidecar and would add 329 blocks
across 220 (champion, spell) pairs, of which 65 pairs already carry at least as
many Meraki damage blocks as the sidecar resolves. Eight spot-checks all showed
outright duplication - Teemo E ``ImpactCalculatedDamage`` base [9,23,37,51,65]
ap 30 is character-for-character the snapshot's "Magic Damage On-Hit"; Pantheon Q
``HoldDamageCalc`` / ``ExecuteDamageCalcModified`` duplicate "Hurl Physical
Damage" / "Increased Hurl Damage"; Jax E ``TotalDamage`` duplicates "Minimum
Magic Damage"; Yone W ``WDamage`` duplicates "Total Mixed Damage" and brings a
second anonymous 100 percent-AD block; Shyvana W offers a ``Calc_Shield`` (a
shield, not damage) and Ornn W a ``TotalMonsterDamageCap`` (a cap, not an
instance). The general seam is REFUTED as unsafe; only the allowlist ships.

The five filed siblings are all EXCLUDED in v1 on evidence from their own
effects text, and each gets a byte-identical exclusion test below:

  Pyke   R - the 80 percent bonus AD is an EXECUTE THRESHOLD ("executing enemy
             champions ... below 250:550 (+ 80% bonus AD) health"), not damage.
  Rengar R - "Rengar's NEXT BASIC ATTACK ... deals 100% AD bonus physical
             damage": an auto-attack empower ``compute_dps`` already counts.
  Quinn  R - the 35 percent block belongs to Skystrike, which is form_index 1;
             the sidecar is form-indexless and the merge only ever sees form 0
             (the damage-less channel), so there is no correct target block.
  Yorick R - ``YorickBigGhoulDamage`` is the Maiden PET's damage, a separate
             cadence from the caster's spell rotation.
  Jinx   Q - "Basic attacks with Fishbones ... deal 110% AD modified physical
             damage": an auto-attack modifier, double-counted against autos.

Each also has snapshot damage-block count 0 for the slot, so there is no Meraki
block to merge into even if the semantics passed - the merge seam cannot reach
them at all, which the exclusion tests pin from the outside.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.abilities import (
    _CDRAGON_RATIO_SIDECAR,
    _CDRAGON_SURPLUS_AD_MERGES,
    _DEFAULT_DATA_ROOT,
    AbilitiesSnapshot,
)
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

_KEYS = ("P", "Q", "W", "E", "R")
_AD_FIELDS = ("total_ad_pct", "bonus_ad_pct")

# The five filed siblings, all v1-EXCLUDED (see the module docstring).
_EXCLUDED_SIBLINGS = [
    ("Pyke", "R"),
    ("Rengar", "R"),
    ("Quinn", "R"),
    ("Yorick", "R"),
    ("Jinx", "Q"),
]

# REFUTED-nearby: snapshot is already as rich as (or richer than) the sidecar.
_REFUTED_NEARBY = [("Yone", "W"), ("Teemo", "E"), ("Shyvana", "W")]

# Pairs whose sidecar block DUPLICATES a Meraki block the snapshot already
# carries - the mandatory negative set. Measured duplications, see docstring.
_ALREADY_MATCHED = [("Teemo", "E"), ("Pantheon", "Q"), ("Jax", "E"), ("Yone", "W")]

_BF_SWORD = "1038"  # +40 flat AD, verified present in items.json


def _current_patch() -> str | None:
    pointer = _DEFAULT_DATA_ROOT / "current.txt"
    if not pointer.exists():
        return None
    return pointer.read_text(encoding="utf-8").strip() or None


def _require_live_sidecar() -> None:
    """Fail (never skip) when the current-patch sidecar is absent.

    Both halves are TRACKED and committed, so absence means a committed
    artifact was deleted or the patch pointer moved ahead of its extract.
    See the matching helper in test_cdragon_ratio_matcher.py.
    """
    patch = _current_patch()
    assert patch, f"tracked patch pointer {_DEFAULT_DATA_ROOT / 'current.txt'} is missing or empty"
    sidecar = _DEFAULT_DATA_ROOT / patch / _CDRAGON_RATIO_SIDECAR
    assert sidecar.exists(), (
        f"current.txt points at patch {patch!r} but the tracked CDragon sidecar "
        f"{sidecar} is not committed"
    )


def _pair() -> tuple[AbilitiesSnapshot, AbilitiesSnapshot]:
    """The live snapshot with the A-29 seam OFF (the default) and ON."""
    off = AbilitiesSnapshot.load()
    on = AbilitiesSnapshot.load(apply_cdragon_surplus_ad=True)
    return off, on


def _r_dps(
    data: DataSnapshot,
    abilities: AbilitiesSnapshot,
    champion: str,
    key: str,
    items: list[str] | None = None,
) -> float:
    """Per-spell ability DPS for one slot at level 16 against a full-HP target."""
    res = compute_ability_dps(
        data,
        champion,
        16,
        item_ids=items,
        target_max_hp=2400.0,
        target_current_hp_pct=1.0,
        abilities_snapshot=abilities,
    )
    for spell in res.per_spell:
        if spell.key == key:
            return spell.dps
    return 0.0


@pytest.fixture(scope="module")
def data() -> DataSnapshot:
    return DataSnapshot.load()


# --- registry shape ----------------------------------------------------------


def test_registry_seeds_viego_r_only():
    """v1 allowlist is the tightest matching set: Viego R and nothing else."""
    assert ("Viego", "R") in _CDRAGON_SURPLUS_AD_MERGES
    assert len(_CDRAGON_SURPLUS_AD_MERGES) == 1, (
        "v1 seed must stay the tightest matching set - widen only on per-champion "
        f"evidence, got {sorted(_CDRAGON_SURPLUS_AD_MERGES)}"
    )


def test_registry_entry_names_the_surplus_block():
    """The entry names the sidecar block + its Meraki target index explicitly."""
    block_name, target_index = _CDRAGON_SURPLUS_AD_MERGES[("Viego", "R")]
    assert block_name == "TotalDamage"
    assert target_index == 0


@pytest.mark.parametrize("cid,key", _EXCLUDED_SIBLINGS)
def test_filed_siblings_are_not_seeded(cid, key):
    """Every filed sibling stays out of v1 (execute / auto-empower / pet / form)."""
    assert (cid, key) not in _CDRAGON_SURPLUS_AD_MERGES


@pytest.mark.parametrize("cid,key", _REFUTED_NEARBY)
def test_refuted_nearby_are_not_seeded(cid, key):
    assert (cid, key) not in _CDRAGON_SURPLUS_AD_MERGES


# --- Viego R: the credit ------------------------------------------------------


def test_viego_r_credits_zero_at_full_hp_flag_off(data):
    """Default guard: the filed bug reproduces exactly at the shipped default."""
    _require_live_sidecar()
    off, _on = _pair()
    assert _r_dps(data, off, "Viego", "R") == 0.0


def test_viego_r_credited_flag_on(data):
    """RED before the fix: the 120 percent total-AD term is scored flag-ON."""
    _require_live_sidecar()
    _off, on = _pair()
    assert _r_dps(data, on, "Viego", "R") > 0.0


def test_viego_r_scales_with_bonus_ad_flag_on(data):
    """RED: the credited term is an AD RATIO, not a constant - it rises with AD."""
    _require_live_sidecar()
    _off, on = _pair()
    bare = _r_dps(data, on, "Viego", "R")
    with_ad = _r_dps(data, on, "Viego", "R", items=[_BF_SWORD])
    assert with_ad > bare


def test_viego_r_block_gains_total_ad_pct_flag_on():
    """RED: the merged block carries the sidecar's 120 percent total_ad_pct."""
    _require_live_sidecar()
    off, on = _pair()
    off_block = off.get_abilities("Viego")["R"][0].damage_blocks[0]
    on_block = on.get_abilities("Viego")["R"][0].damage_blocks[0]
    assert off_block.total_ad_pct is None
    assert on_block.total_ad_pct is not None
    assert on_block.total_ad_pct[0] == pytest.approx(120.0)
    # The pre-existing missing-HP coefficients are untouched.
    assert on_block.target_missing_hp_pct == off_block.target_missing_hp_pct


def test_viego_r_block_count_unchanged_flag_on():
    """The merge preserves cardinality - it is not an append."""
    _require_live_sidecar()
    off, on = _pair()
    assert len(on.get_abilities("Viego")["R"][0].damage_blocks) == len(
        off.get_abilities("Viego")["R"][0].damage_blocks
    )


def test_viego_other_slots_unchanged_flag_on():
    """Only the seeded slot moves - Viego Q/W/E/P are byte-identical."""
    _require_live_sidecar()
    off, on = _pair()
    for key in ("P", "Q", "W", "E"):
        assert off.get_abilities("Viego").get(key, ()) == on.get_abilities(
            "Viego"
        ).get(key, ()), f"Viego {key} moved"


# --- the mandatory negative: no duplicate on an already-matched pair ---------


@pytest.mark.parametrize("cid,key", _ALREADY_MATCHED)
def test_already_matched_pair_gains_no_duplicate_block(cid, key):
    """MANDATORY negative: a pair whose sidecar block duplicates an existing
    Meraki block must not gain a block, a ratio, or any DPS flag-ON.

    These are the exact pairs a general APPEND seam was measured to
    double-count (Teemo E / Pantheon Q / Jax E / Yone W)."""
    _require_live_sidecar()
    off, on = _pair()
    off_forms = off.get_abilities(cid).get(key, ())
    on_forms = on.get_abilities(cid).get(key, ())
    assert off_forms == on_forms, f"{cid} {key} moved under the A-29 seam"


@pytest.mark.parametrize("cid,key", _ALREADY_MATCHED)
def test_already_matched_pair_dps_unchanged(cid, key, data):
    """Same negative, asserted on the computed quantity rather than the struct."""
    _require_live_sidecar()
    off, on = _pair()
    assert _r_dps(data, on, cid, key) == _r_dps(data, off, cid, key)


@pytest.mark.parametrize("cid,key", _EXCLUDED_SIBLINGS)
def test_excluded_siblings_byte_identical(cid, key):
    """Each filed-but-unseeded sibling is byte-identical flag-ON."""
    _require_live_sidecar()
    off, on = _pair()
    assert off.get_abilities(cid).get(key, ()) == on.get_abilities(cid).get(key, ())


@pytest.mark.parametrize("cid,key", _EXCLUDED_SIBLINGS)
def test_excluded_siblings_still_credit_zero_flag_on(cid, key, data):
    """The allowlist gates the credit: unseeded siblings stay at 0.0 flag-ON."""
    _require_live_sidecar()
    _off, on = _pair()
    assert _r_dps(data, on, cid, key) == 0.0


@pytest.mark.parametrize("cid,key", _REFUTED_NEARBY)
def test_refuted_nearby_byte_identical(cid, key):
    _require_live_sidecar()
    off, on = _pair()
    assert off.get_abilities(cid).get(key, ()) == on.get_abilities(cid).get(key, ())


# --- global invariants -------------------------------------------------------


def test_only_viego_r_moves_across_the_whole_roster():
    """Blast-radius pin: exactly ONE (champion, slot) differs flag-ON vs OFF."""
    _require_live_sidecar()
    off, on = _pair()
    moved = []
    for cid in off.champion_ids():
        for key in _KEYS:
            if off.get_abilities(cid).get(key, ()) != on.get_abilities(cid).get(
                key, ()
            ):
                moved.append((cid, key))
    assert moved == [("Viego", "R")], f"unexpected movement: {moved}"


def test_no_ad_family_double_count_flag_on():
    """No damage block may carry two AD-family fields (a silent double-count)."""
    _require_live_sidecar()
    _off, on = _pair()
    doubled = []
    for cid in on.champion_ids():
        for key in _KEYS:
            for form in on.get_abilities(cid).get(key, ()):
                for block in form.damage_blocks:
                    if sum(getattr(block, f) is not None for f in _AD_FIELDS) > 1:
                        doubled.append((cid, key, block.attribute))
    assert not doubled, f"AD double-count blocks flag-ON: {doubled[:10]}"


def test_default_is_off_and_byte_identical():
    """A bare load() equals an explicitly-OFF load - the seam ships DEFAULT-OFF."""
    _require_live_sidecar()
    bare = AbilitiesSnapshot.load()
    explicit_off = AbilitiesSnapshot.load(apply_cdragon_surplus_ad=False)
    assert bare.champions == explicit_off.champions


def test_unrelated_ad_carry_ability_dps_unchanged(data):
    """An unrelated AD carry's ability DPS does not move at the default OR flag-ON."""
    _require_live_sidecar()
    off, on = _pair()
    for champion in ("Jhin", "Caitlyn", "Riven"):
        before = compute_ability_dps(
            data, champion, 16, target_max_hp=2400.0, abilities_snapshot=off
        ).total_ability_dps
        after = compute_ability_dps(
            data, champion, 16, target_max_hp=2400.0, abilities_snapshot=on
        ).total_ability_dps
        assert before == after, f"{champion} ability DPS moved"


def test_engine_version_pin():
    assert ENGINE_VERSION == "1.280.0"


def test_file_is_seven_bit_ascii():
    raw = Path(__file__).read_bytes()
    assert all(b < 128 for b in raw), "authored file must be 7-bit ASCII"
