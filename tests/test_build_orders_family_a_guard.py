"""LEAP-04 - the FIRST staleness + dock-parity guard for build-order "Family A".

Family A is ``data/daemon_slayer/<patch>/build_orders_{sr,aram,arena}.json``,
produced by ``tools/daemon_slayer_build_orders_generate.py`` (enemy-comp-class
keyspace: ``{champ display name: {ad_heavy|balanced|ap_heavy: [item_id, ...]}}``).
Before this module it had NO guard at all - no ``engine_version`` stamp and no
content-freshness test, unlike Family B
(``tests/test_build_order_content_freshness.py``, whose fixture + skip-gating
style this module mirrors). A regen that skips one family therefore left stale
rows serving live with nothing going red.

Three layers, all here:

1. LAYER 1 - fast, per-commit, SERVER-FREE. Static read of the committed tables
   at the patch named in ``data/daemon_slayer/current.txt``: stamp integrity
   (``version`` / ``mode`` / ISO ``generated_at``), roster floor + cross-mode key
   parity, per-cell structure, and ARTIFACT-ABSENCE - Essence Reaver (3508) and
   Eclipse (6692) must not appear in the first three slots of any comp-class cell
   for the seven Step-1b flipped crit-ADCs. This is the red-first signal that a
   future table regressed to pre-dock content.
2. LAYER 2 - slow, env-gated behind ``RC_BUILD_ORDER_LIVE_PARITY=1``, needs the
   DS engine on :8860. Re-derives the generator's exact cell in-process with the
   coherence dock ON and asserts the live result still equals the committed
   first three ids. Skips cleanly (never fails) when the env var is unset or the
   engine is down.
3. LAYER 3 - fast, server-free ``effective_score`` parse pin (see
   ``test_ranked_item_from_dict_parses_effective_score``).

RED demonstration (LEAP-04 acceptance criterion 1): rather than temporarily
injecting a synthetic pre-dock cell and deleting it again, the teeth of the
artifact-absence check are proven permanently by
``test_artifact_scan_has_teeth_on_synthetic_pre_dock_cell``, which feeds the same
helper a synthetic pre-dock Miss Fortune cell (``[6692, 3508, 3031, ...]``) and
asserts BOTH artifacts are reported. If that test ever passes trivially the
Layer-1 scan has lost its teeth.

ID-SUFFIX rule (memory ``feedback_deny_sweep_by_id_suffix_not_name``): DDragon
ships one item under several ids - Essence Reaver is 3508 on SR/ARAM and 223508
as the Arena map-30 mirror. The artifact scan therefore resolves an ALIAS SET by
id suffix out of the live patch catalog instead of matching a single literal id
or a display name. Champion keys are likewise resolved out of the actual JSON by
normalized display name: Family A is DISPLAY-name keyed, so joining on the
DDragon key ("MissFortune" / "Kaisa") would silently match nothing and skip the
assertion.

LAYER-2 SHAPE - follows the CODE, not the loose prose. The generator does not
take "the first three rows of one rank call": ``core/build_order.py:597-724``
runs a GREEDY loop - slot 1 is the top legal row of a rank call at
``item_ids=[]``, slot 2 is the injected boots id (``:704-724``, synthetic, never
engine-ranked), slot 3 is the top legal row of a SECOND rank call that now sees
slots 1 + 2 in ``item_ids``. Asserting one call's first three rows against the
committed first three would compare unrelated quantities. So Layer 2 does both
halves properly: a direct ``rank_for_primary_archetype`` call (dock ON) pinned to
the committed slot 1, and a full ``build_order_for_class`` re-derivation - the
generator's own cell function - pinned to the committed first three.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

import tools.daemon_slayer_build_orders_generate as gen
from core import daemon_slayer_client as dsc
from core.build_order import _pick_top_safe
from core.daemon_slayer_client import RankedItem

_MODE_KEYS = gen.MODES  # ("sr", "aram", "arena")

# Cross-mode key-set equality is the primary roster guard; the floor is a coarse
# backstop that catches a --champion / seed collapse. Deliberately not the exact
# roster size so a real roster change does not require a test edit.
_ROSTER_FLOOR = 170

# The seven crit-ADCs the Step-1b coherence tightening flipped. Spelled as
# display names for readability only - every lookup goes through
# _resolve_champ_key(), which resolves against the keys actually present in the
# JSON (normalized), so a spacing / apostrophe difference cannot silently skip.
_FLIPPED_CRIT_ADCS = (
    "Miss Fortune",
    "Jhin",
    "Kai'Sa",
    "Varus",
    "Twitch",
    "Jinx",
    "Caitlyn",
)

# Base ids of the two coherence-dock artifacts (core/build_planner/coherence.py
# docstring + core/build_planner/kit_synergy.py _SPELLBLADE_IDS).
_ARTIFACT_BASE_IDS = ("3508", "6692")
_ARTIFACT_NAMES = {"3508": "Essence Reaver", "6692": "Eclipse"}

# How many leading slots the artifact scan covers.
_FIRST_N = 3

# Layer 2 runs SR + ARAM only: the Arena tables are a 22xxxx mirror keyspace and
# the mirror-id parity question is a separate item.
_PARITY_MODE_KEYS = ("sr", "aram")

_LIVE_PARITY = os.environ.get("RC_BUILD_ORDER_LIVE_PARITY")


# --------------------------------------------------------------------------- #
# fixtures / helpers (server-free)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def patch() -> str:
    """The active patch, resolved exactly the way the generator resolves it."""
    return gen.resolve_patch()


def _table_path(patch_str: str, mode_key: str):
    return gen.out_dir_for(patch_str, None) / f"build_orders_{mode_key}.json"


@pytest.fixture(scope="module")
def tables(patch: str) -> dict:
    """``{mode_key: payload}`` for the three committed Family A tables."""
    out: dict = {}
    for mode_key in _MODE_KEYS:
        path = _table_path(patch, mode_key)
        assert path.exists(), (
            f"Family A table missing: {path} - regen with "
            f"'python tools/daemon_slayer_build_orders_generate.py --mode all'"
        )
        out[mode_key] = json.loads(path.read_text(encoding="utf-8"))
    return out


def _norm(name: str) -> str:
    """Fold a champion display name to a join-safe key (lower alphanumerics)."""
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def _resolve_champ_key(build_orders: dict, display_name: str) -> str:
    """Return the key in ``build_orders`` that denotes ``display_name``.

    Family A is keyed by DDragon DISPLAY name (``Miss Fortune``, ``Kai'Sa``), not
    the DDragon id, so the join is done on a normalized form of the key set that
    is actually in the file. Raises AssertionError rather than skipping when the
    champion is absent - a vanished key is a finding, not a reason to pass.
    """
    wanted = _norm(display_name)
    for key in build_orders:
        if _norm(key) == wanted:
            return key
    raise AssertionError(
        f"champion {display_name!r} (normalized {wanted!r}) has no key in the "
        f"committed table - the artifact guard cannot be evaluated for it"
    )


@pytest.fixture(scope="module")
def artifact_alias_ids(patch: str) -> dict:
    """``{base_id: frozenset(alias_ids)}`` for the two dock artifacts.

    Resolved by id SUFFIX out of the live patch item catalog so mode-mirror ids
    (Arena map-30 ships Essence Reaver as 223508, Eclipse as 226692) are covered.
    Matching a single literal id would let a mirror-id regression pass.
    """
    catalog_path = gen._DS_DIR / patch / "items.json"
    catalog_ids: list[str] = []
    if catalog_path.exists():
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog_ids = [str(k) for k in (raw.get("data") or raw or {})]
    out: dict = {}
    for base in _ARTIFACT_BASE_IDS:
        aliases = {base}
        aliases.update(i for i in catalog_ids if i.endswith(base))
        out[base] = frozenset(aliases)
    return out


def _artifact_hits(ids, alias_ids: dict, first_n: int = _FIRST_N) -> list:
    """Return ``[(slot_index, item_id, base_id), ...]`` for every dock artifact
    (or mode-mirror alias of one) inside the first ``first_n`` entries of ``ids``.

    Pure function - no I/O - so the RED demonstration can feed it a synthetic
    pre-dock cell and prove the scan has teeth.
    """
    hits: list = []
    for idx, item_id in enumerate(list(ids)[:first_n]):
        for base, aliases in alias_ids.items():
            if str(item_id) in aliases:
                hits.append((idx, str(item_id), base))
    return hits


# --------------------------------------------------------------------------- #
# LAYER 1 - fast, server-free static guards
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode_key", _MODE_KEYS)
def test_stamp_integrity(tables: dict, patch: str, mode_key: str) -> None:
    """version tracks current.txt, mode matches the filename, generated_at is ISO.

    Family A carries no engine_version stamp (generator payload keys, see
    tools/daemon_slayer_build_orders_generate.py generate_mode), so the patch
    stamp plus the Layer-2 parity run are the freshness signal.
    """
    payload = tables[mode_key]
    assert payload.get("version") == patch, (
        f"{mode_key}: version stamp {payload.get('version')!r} != patch "
        f"{patch!r} from current.txt - the table was generated for another patch"
    )
    assert payload.get("mode") == mode_key, (
        f"{mode_key}: mode stamp {payload.get('mode')!r} does not match the "
        f"filename mode {mode_key!r} - a cross-mode write clobbered the file"
    )
    stamp = payload.get("generated_at")
    assert isinstance(stamp, str) and stamp, f"{mode_key}: generated_at missing"
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None, (
        f"{mode_key}: generated_at {stamp!r} parsed without a timezone - the "
        f"generator writes UTC with a trailing Z"
    )
    assert parsed.astimezone(timezone.utc).year >= 2025, (
        f"{mode_key}: generated_at {stamp!r} is implausibly old"
    )


def test_roster_floor_and_cross_mode_parity(tables: dict) -> None:
    """Each mode carries the same champion key-set, above a >=170 floor."""
    rosters = {}
    for mode_key in _MODE_KEYS:
        content = tables[mode_key].get("build_orders")
        assert isinstance(content, dict) and content, (
            f"{mode_key}: build_orders missing or empty"
        )
        rosters[mode_key] = frozenset(content)

    for mode_key, keys in rosters.items():
        assert len(keys) >= _ROSTER_FLOOR, (
            f"{mode_key}: roster has {len(keys)} champions, below floor "
            f"{_ROSTER_FLOOR} - a --champion narrowed regen collapsed the table"
        )

    ref_mode = _MODE_KEYS[0]
    ref = rosters[ref_mode]
    for mode_key, keys in rosters.items():
        assert keys == ref, (
            f"{mode_key} roster differs from {ref_mode}: "
            f"missing={sorted(ref - keys)[:5]} extra={sorted(keys - ref)[:5]} - "
            f"one mode was skipped by the last regen"
        )


@pytest.mark.parametrize("mode_key", _MODE_KEYS)
def test_cell_structural_integrity(tables: dict, mode_key: str) -> None:
    """Every champ carries the 3 comp classes, each a full slot list of ids.

    Cell length is asserted against the generator's own ``_SLOTS`` constant
    rather than a literal, and ids are validated as numeric strings only - the
    ARAM / Arena tables legitimately use 22xxxx / 44xxxx mirror ids that a base
    catalog membership check would false-fail on.
    """
    content = tables[mode_key]["build_orders"]
    for champ, cells in content.items():
        assert isinstance(cells, dict), f"{mode_key}/{champ}: cell block not a dict"
        assert set(cells) == set(gen.ENEMY_COMP_CLASSES), (
            f"{mode_key}/{champ}: comp classes {sorted(cells)} != "
            f"{sorted(gen.ENEMY_COMP_CLASSES)}"
        )
        for comp_class, ids in cells.items():
            assert isinstance(ids, list) and len(ids) == gen._SLOTS, (
                f"{mode_key}/{champ}/{comp_class}: "
                f"{len(ids) if isinstance(ids, list) else ids!r} ids, expected "
                f"the generator's {gen._SLOTS}-slot build - an empty / truncated "
                f"cell means the engine failed mid-regen"
            )
            for item_id in ids:
                assert isinstance(item_id, str) and item_id.isdigit(), (
                    f"{mode_key}/{champ}/{comp_class}: non-numeric-string item "
                    f"id {item_id!r}"
                )


def test_artifact_alias_set_covers_mode_mirrors(artifact_alias_ids: dict) -> None:
    """The suffix-resolved alias set picks up the Arena map-30 mirror ids.

    Pins the ID-SUFFIX rule: 3508 also ships as 223508 and 6692 as 226692, so a
    literal-id-only scan would miss a mirror-id regression outright.
    """
    for base in _ARTIFACT_BASE_IDS:
        aliases = artifact_alias_ids[base]
        assert base in aliases, f"alias set for {base} lost the base id"
        mirrors = sorted(a for a in aliases if a != base)
        assert mirrors, (
            f"alias set for {base} ({_ARTIFACT_NAMES[base]}) resolved no mirror "
            f"id - expected at least the Arena 22{base} mirror from the patch "
            f"item catalog; the suffix resolution is not working"
        )


def test_artifact_scan_has_teeth_on_synthetic_pre_dock_cell(
    artifact_alias_ids: dict,
) -> None:
    """RED demonstration: a synthetic PRE-dock cell must be reported.

    LEAP-04 acceptance criterion 1 asked for a temporary injected fixture; this
    makes the demonstration permanent instead. The cell below is the pre-dock
    Miss Fortune shape recorded in docs/ORCHESTRATION_PLAN.md (Eclipse and
    Essence Reaver in the leading slots).
    """
    pre_dock = ["6692", "3508", "3031", "3006", "3072", "3094"]
    hits = _artifact_hits(pre_dock, artifact_alias_ids)
    found = {base for _, _, base in hits}
    assert found == {"6692", "3508"}, (
        f"the artifact scan missed a synthetic pre-dock cell {pre_dock} - it "
        f"reported {sorted(found)} instead of both artifacts, so the Layer-1 "
        f"guard has lost its teeth"
    )
    mirror_cell = ["223508", "223006", "226692"]
    mirror_hits = _artifact_hits(mirror_cell, artifact_alias_ids)
    assert {base for _, _, base in mirror_hits} == {"3508", "6692"}, (
        f"the artifact scan missed the Arena mirror ids in {mirror_cell} - "
        f"suffix-aware matching is required (id-suffix rule)"
    )


@pytest.mark.parametrize("champion", _FLIPPED_CRIT_ADCS)
@pytest.mark.parametrize("mode_key", _MODE_KEYS)
def test_no_dock_artifact_in_first_three(
    tables: dict, artifact_alias_ids: dict, mode_key: str, champion: str,
) -> None:
    """No dock artifact (3508 / 6692, or a mode mirror) in the leading 3 slots.

    The coherence dock demotes the Spellblade-proc artifact for exactly these
    seven flipped crit-ADCs, so a committed table that surfaces one of them
    early is either a pre-dock table or a dock that failed to reach that cell.
    """
    content = tables[mode_key]["build_orders"]
    champ_key = _resolve_champ_key(content, champion)
    failures: list[str] = []
    for comp_class in gen.ENEMY_COMP_CLASSES:
        ids = content[champ_key].get(comp_class) or []
        for idx, item_id, base in _artifact_hits(ids, artifact_alias_ids):
            failures.append(
                f"{mode_key}/{champ_key}/{comp_class}: slot {idx + 1} is "
                f"{item_id} ({_ARTIFACT_NAMES[base]}, base {base}); "
                f"first {_FIRST_N} = {list(ids)[:_FIRST_N]}"
            )
    assert not failures, (
        "dock artifact present in the leading slots of a flipped crit-ADC cell "
        "- the committed table is pre-dock / stale, or the dock does not cover "
        "this id form:\n  " + "\n  ".join(failures)
    )


# --------------------------------------------------------------------------- #
# LAYER 3 - effective_score parse pin (fast, server-free)
# --------------------------------------------------------------------------- #
def test_ranked_item_from_dict_parses_effective_score() -> None:
    """RankedItem.from_dict must keep round-tripping ``effective_score``.

    If that parse is dropped (core/daemon_slayer_client.py:71), the coherence
    dock's fight_length-engaged branch reads a missing / zero attribute and
    silently reverts to a target-BLIND kit-fit sort for exactly the crit-ADCs the
    dock targets. That regression does NOT crash and does NOT show a stamp diff,
    so this pin is the only loud signal.
    """
    row = {
        "item_id": "3031",
        "item_name": "Infinity Edge",
        "delta_dps": 12.5,
        "gold": 3450,
        "effective_score": 7.5,
    }
    parsed = RankedItem.from_dict(row)
    assert parsed.effective_score == 7.5, (
        "RankedItem.from_dict dropped effective_score "
        f"(got {parsed.effective_score!r}) - the coherence dock's "
        "fight_length-engaged branch now falls back to a target-blind kit-fit "
        "sort for the mapped crit-ADCs: a silent, non-crashing, stamp-invisible "
        "revert. Restore the effective_score parse in "
        "core/daemon_slayer_client.py RankedItem.from_dict."
    )
    assert RankedItem.from_dict({"item_id": "1"}).effective_score == 0.0, (
        "a row without effective_score must default to 0.0, not raise"
    )


# --------------------------------------------------------------------------- #
# LAYER 2 - live dock parity (slow, env-gated, needs :8860)
# --------------------------------------------------------------------------- #
def _require_live_engine() -> None:
    """Skip when the DS engine is not answering on :8860 - unless it was DECLARED up.

    RM-119 B2 (2026-08-06). The old docstring read "skip - never fail", and
    that was wrong in one specific case: every caller of this helper is
    already behind `RC_BUILD_ORDER_LIVE_PARITY`, whose own skip reason says
    the layer "needs the DS engine on :8860". Setting that flag IS a
    declaration that the engine is up, so a down engine there is a failure,
    not an absent capability - otherwise arming the live-parity layer on a
    wedged engine reports green and proves nothing. `RC_REQUIRE_DS_ENGINE`
    arms it the same way for callers who set that instead.

    With NEITHER flag set the behaviour is unchanged: a skip.
    """
    from tests.test_ds_live_route_gate import require_live_engine
    require_live_engine("the live build-order dock-parity layer",
                        up=dsc.is_engine_up(timeout=2.0),
                        also_required=bool(_LIVE_PARITY))


def _generator_cell_kwargs(comp_class: str, mode_key: str) -> dict:
    """The generator's EXACT first rank call for one cell.

    Mirrors core/build_order.py:597-619 (the engine-call kwargs at
    ``item_ids=[]``) fed with the generator's constants
    (tools/daemon_slayer_build_orders_generate.py:107-128, :188-207).
    """
    ad_share, ap_share = gen._COMP_SHARES[comp_class]
    return dict(
        level=gen._LEVEL,
        item_ids=[],
        mode=gen.DS_MODE_BY_KEY[mode_key],
        target_armor=gen._TARGET_ARMOR,
        target_mr=gen._TARGET_MR,
        target_max_hp=gen._TARGET_MAX_HP,
        target_bonus_hp=gen._TARGET_BONUS_HP,
        sort_by="delta",
        filter_shared_uniques=True,
        enemy_ad_share=ad_share,
        enemy_ap_share=ap_share,
        timeout=gen._TIMEOUT,
    )


@pytest.mark.skipif(
    not _LIVE_PARITY,
    reason="RC_BUILD_ORDER_LIVE_PARITY not set - the live dock-parity layer "
           "needs the DS engine on :8860 and is too slow for per-commit CI",
)
@pytest.mark.parametrize("comp_class", gen.ENEMY_COMP_CLASSES)
@pytest.mark.parametrize("champion", _FLIPPED_CRIT_ADCS)
@pytest.mark.parametrize("mode_key", _PARITY_MODE_KEYS)
def test_live_dock_parity_slot_one(
    tables: dict, mode_key: str, champion: str, comp_class: str,
) -> None:
    """A direct dock-ON rank call still yields the committed slot-1 item.

    ``rank_for_primary_archetype`` hosts the client-side coherence dock, so its
    top legal row IS what the generator commits to slot 1
    (core/build_order.py:622-696). Slot 2 is the synthetic injected boots id and
    slot 3 comes from a second rank call, so only slot 1 is comparable against a
    single call - see the module docstring.
    """
    _require_live_engine()
    content = tables[mode_key]["build_orders"]
    champ_key = _resolve_champ_key(content, champion)
    committed = content[champ_key][comp_class]

    archetype = gen.archetype_for(champ_key)
    out = dsc.rank_for_primary_archetype(
        champ_key, archetype, **_generator_cell_kwargs(comp_class, mode_key)
    )
    assert out is not None, (
        f"{mode_key}/{champ_key}/{comp_class}: rank_for_primary_archetype "
        f"returned None with the engine reported up"
    )
    rows = [r for r in (out.get("ranked") or []) if r.get("item_id")]
    assert rows, f"{mode_key}/{champ_key}/{comp_class}: engine returned no rows"
    chosen, _excl_family, _excl_example = _pick_top_safe(rows, incumbent_id=None)
    assert chosen is not None, (
        f"{mode_key}/{champ_key}/{comp_class}: every candidate collided with a "
        f"locked unique passive"
    )
    live_slot_one = str(chosen.get("item_id"))
    assert live_slot_one == committed[0], (
        f"{mode_key}/{champ_key}/{comp_class}: live dock slot 1 is "
        f"{live_slot_one}, committed slot 1 is {committed[0]} "
        f"(committed first {_FIRST_N} = {committed[:_FIRST_N]}, live top rows = "
        f"{[str(r.get('item_id')) for r in rows[:_FIRST_N]]}) - the committed "
        f"table is STALE vs the live dock, or the dock changed. Regen: "
        f"python tools/daemon_slayer_build_orders_generate.py --mode all"
    )


@pytest.mark.skipif(
    not _LIVE_PARITY,
    reason="RC_BUILD_ORDER_LIVE_PARITY not set - the live dock-parity layer "
           "needs the DS engine on :8860 and is too slow for per-commit CI",
)
@pytest.mark.parametrize("comp_class", gen.ENEMY_COMP_CLASSES)
@pytest.mark.parametrize("champion", _FLIPPED_CRIT_ADCS)
@pytest.mark.parametrize("mode_key", _PARITY_MODE_KEYS)
def test_live_dock_parity_first_three(
    tables: dict, mode_key: str, champion: str, comp_class: str,
) -> None:
    """Re-deriving the generator's own cell reproduces the committed first 3.

    Calls ``build_order_for_class`` - the generator's cell function - so the
    greedy loop, the boots injection and the dock all run exactly as they did at
    regen time (``rank_fn`` defaults to the dock-hosting
    ``rank_for_primary_archetype``). This is the real regen-parity proof.
    """
    _require_live_engine()
    content = tables[mode_key]["build_orders"]
    champ_key = _resolve_champ_key(content, champion)
    committed = content[champ_key][comp_class]

    archetype = gen.archetype_for(champ_key)
    live = gen.build_order_for_class(champ_key, archetype, mode_key, comp_class)
    assert live, (
        f"{mode_key}/{champ_key}/{comp_class}: live re-derivation produced an "
        f"empty order with the engine reported up"
    )
    assert live[:_FIRST_N] == committed[:_FIRST_N], (
        f"{mode_key}/{champ_key}/{comp_class}: live first {_FIRST_N} "
        f"{live[:_FIRST_N]} != committed first {_FIRST_N} "
        f"{committed[:_FIRST_N]} (live full = {live}, committed full = "
        f"{list(committed)}) - the committed table is STALE. Regen: python "
        f"tools/daemon_slayer_build_orders_generate.py --mode all"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
