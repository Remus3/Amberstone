"""P1-L4 audit: the CALLER path that derives enemy/target state for DS.

Lane: NOT the engine's damage-vs-target math (verified correct by a prior
audit). This file pins the integration layer - how RC computes
``target_armor`` / ``target_mr`` / ``target_max_hp`` / ``target_bonus_hp``
from the real enemy team (live champions + their items) and feeds them to
the Daemon Slayer engine, across 1..6 enemy items and rising level.

Ground truth is derived, never hardcoded magic:
  - champion base resist/HP by level: Riot quadratic growth
    ``base + perlevel * (n-1) * (0.7025 + 0.0175 * (n-1))`` (the exact
    formula the DS engine uses - ``agents.daemon_slayer.stats.scaled``),
    read from ``data/meta/ddragon_champions.json``.
  - per-item flat armor/MR/HP: ``data/meta/ddragon_items.json`` (the
    catalog ``core.enemy_aware_stats`` actually reads), cross-checked
    against Meraki where the key exists.

Two classes of test:
  * CHARACTERIZATION - pins the current (deferred-design) reality so the
    contract is explicit and a future change is a conscious one. The
    headline reality: the per-tick coach loop feeds DS a FIXED level-only
    heuristic curve, NOT the real enemy build.
  * BUG - ``compute_target_stats_from_items`` (the live-items path, used
    by the ON-DEMAND ``/api/ds-preview`` route + the on-demand
    build-planner brain, NEVER the coach tick) omits the champion base
    resist-by-level
    entirely; its docstring's "engine adds base separately / additive
    delta" rationale is contradicted by the engine, which treats
    ``target_armor`` as the absolute target armor. Fixed test-first in
    the non-frozen ``core/enemy_aware_stats.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests import _repo_walk

_ROOT = Path(__file__).resolve().parent.parent
_CHAMP_PATH = _ROOT / "data" / "meta" / "ddragon_champions.json"
_ITEM_PATH = _ROOT / "data" / "meta" / "ddragon_items.json"


# ---------------------------------------------------------------------------
# Riot ground-truth helpers (no magic numbers - all derived from data files)
# ---------------------------------------------------------------------------
def _riot_growth_multiplier(level: int) -> float:
    """The canonical Riot per-level growth coefficient.

    Identical to ``agents.daemon_slayer.stats.growth_multiplier`` - we
    re-derive it here from first principles rather than importing so the
    caller-side expectation is independent of the engine module.
    """
    return (level - 1) * (0.7025 + 0.0175 * (level - 1))


def _champ_stats() -> dict:
    raw = json.loads(_CHAMP_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _item_stats() -> dict:
    raw = json.loads(_ITEM_PATH.read_text(encoding="utf-8"))
    return raw.get("data", raw)


def _champ_base_by_level(champ: str, level: int) -> tuple[float, float, float]:
    """(armor, mr, hp) for ``champ`` at ``level`` via Riot quadratic growth."""
    s = _champ_stats()[champ]["stats"]
    g = _riot_growth_multiplier(level)
    armor = s["armor"] + s["armorperlevel"] * g
    mr = s["spellblock"] + s["spellblockperlevel"] * g
    hp = s["hp"] + s["hpperlevel"] * g
    return armor, mr, hp


def _item_flat(item_id: str) -> tuple[float, float, float]:
    e = _item_stats().get(str(item_id)) or {}
    st = e.get("stats") or {}
    return (
        float(st.get("FlatArmorMod") or 0.0),
        float(st.get("FlatSpellBlockMod") or 0.0),
        float(st.get("FlatHPPoolMod") or 0.0),
    )


# A spread of real defensive items so 1..6-item builds exercise armor,
# MR and HP simultaneously. Ids verified present in ddragon_items.json.
_ARMOR_ITEM_POOL = [
    "3075",  # Thornmail        -> +75 armor, +150 hp
    "3143",  # Randuin's Omen   -> +75 armor, +350 hp
    "1057",  # Negatron Cloak   -> +45 mr
    "3211",  # Spectre's Cowl   -> +35 mr,   +200 hp
    "1011",  # Giant's Belt     -> +350 hp
    "1029",  # Cloth Armor      -> +15 armor
]


# ===========================================================================
# CHARACTERIZATION - the per-tick coach loop feeds DS a fixed level-only
# heuristic curve, NOT the real enemy build. This is a deferred design
# choice (the s170 module docstring calls it "Tier 1: heuristic only").
# Pinned so any future change to make it build-aware is conscious.
# ===========================================================================
class TestCoachFeedsFixedCurveNotEnemyBuild:
    def test_compute_enemy_stats_is_level_only_ignores_items(self):
        """compute_enemy_stats has NO enemy-item parameter at all - it
        cannot react to what the enemy team bought. Two calls at the
        same mode+level are byte-identical regardless of enemy build."""
        from coach_integration.enemy_stats import compute_enemy_stats

        a = compute_enemy_stats(mode="sr", level=11)
        b = compute_enemy_stats(mode="sr", level=11)
        assert a == b
        # The only knobs are mode / level / game_seconds / overrides.
        import inspect

        params = set(inspect.signature(compute_enemy_stats).parameters)
        assert "enemy_items" not in params and "enemy_builds" not in params
        # bonus_hp_override is the ONLY item-derived hook, and only for HP.
        assert "bonus_hp_override" in params

    def test_compute_enemy_stats_linear_in_level_below_caps(self):
        """The curve is strictly linear ``base + per_level*level`` below
        caps - internally inconsistent with the engine's Riot-quadratic
        per-level base-stat scaling, but it is an anchor table so we pin
        the documented behaviour rather than 'fix' a heuristic."""
        from coach_integration.enemy_stats import compute_enemy_stats, _MODE_ANCHORS

        ab, apl, mb, mpl, hb, hpl = _MODE_ANCHORS["sr"]
        for lv in (1, 6, 11):
            es = compute_enemy_stats(mode="sr", level=lv)
            assert es.armor == pytest.approx(round(ab + apl * lv, 1))
            assert es.mr == pytest.approx(round(mb + mpl * lv, 1))
            assert es.max_hp == pytest.approx(round(hb + hpl * lv, 1))
        # Linear delta between consecutive levels is exactly per_level.
        assert (
            compute_enemy_stats(mode="sr", level=11).armor
            - compute_enemy_stats(mode="sr", level=10).armor
        ) == pytest.approx(apl)

    def test_sr_coach_passes_curve_not_live_items(self):
        """SR coach (coach_integration/_coach.py) wires the heuristic
        curve into DS and never reads enemy items - not even for
        bonus_hp (unlike ARAM/Arena/Brawl). Pinned via source so a
        regression that silently drops the curve is caught."""
        src = (_ROOT / "coach_integration" / "_coach.py").read_text(encoding="utf-8")
        assert "compute_enemy_stats" in src
        assert "_ds_enemy_stats(" in src
        # SR does NOT pass an item-aware bonus_hp override kwarg into the
        # curve - it appears ONLY in the comment explaining its absence,
        # never as a `bonus_hp_override=` call argument (contrast
        # ARAM/Arena/Brawl which DO pass it).
        assert "bonus_hp_override=" not in src
        # The live-items path is NOT used by the coach loop. (string
        # split so this assertion does not self-match this test file.)
        assert ("compute_target_stats" + "_from_items") not in src
        assert ("enemy_items" + "_from_liveclient") not in src

    @pytest.mark.parametrize(
        "rel",
        [
            "coaches/aram_coach.py",
            "coaches/arena_coach.py",
            "coaches/brawl_coach.py",
        ],
    )
    def test_mode_coaches_only_item_aware_for_bonus_hp(self, rel):
        """ARAM/Arena/Brawl are item-aware ONLY for target_bonus_hp
        (via _estimate_target_bonus_hp -> bonus_hp_override). armor / mr
        / max_hp still come from the level-only curve - they do NOT sum
        the enemy team's armor/MR items. Pinned as the current contract."""
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert "compute_enemy_stats" in src
        assert "bonus_hp_override" in src
        assert "_estimate_target_bonus_hp" in src
        # No armor/MR item summation on the coach tick path.
        assert "compute_target_stats_from_items" not in src

    def test_live_items_path_only_wired_to_ds_preview(self):
        """The s170 live-items remedy (core.enemy_aware_stats) is wired
        ONLY into the ON-DEMAND routes / planner, NEVER the per-tick coach
        loop. This is THE key deliverable: in-game, the coach's DS armor
        / MR target does not move when the enemy team buys defensive
        items - only champion level moves it.

        Two production callers, both ON-DEMAND (request-scoped, not the
        coach tick): the /api/ds-preview route (dashboard/routes_state.py)
        and the WP-C3 counter-build planner brain
        (core/build_planner/situational.build_enemy_profile), which is
        reached only via the on-demand /api/build-plan route - same
        category as the ds-preview route, NOT coach_integration/_coach.py,
        coaches/*_coach.py, or the _state_builder tick (verified WP-C5)."""
        needle = "compute_target_stats" + "_from_items("  # avoid self-match
        skip_names = {"enemy_aware_stats.py", Path(__file__).name}
        callers = []
        # Enumeration is tests/_repo_walk's job, not a raw rglob: it filters to
        # the git-tracked set (so the gitignored ops/runtime/responder_export/
        # <sha>/ full-repo COPIES cannot be scanned as if they were callers),
        # with EXCLUDED_DIRS segment skips as the backstop. It also owns the
        # relative-vs-absolute trap the inline .claude / _archive check used to
        # record: matching ABSOLUTE parts returns nothing at all when the
        # checkout itself lives under a .claude/worktrees/<id> path, which reads
        # exactly like a clean tree. See tests/_repo_walk.py.
        for p in _repo_walk.repo_files(_ROOT, patterns=("*.py",)):
            if p.name in skip_names:
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if needle in txt:
                callers.append(p.relative_to(_ROOT).as_posix())
        # Exactly the two ON-DEMAND production callers (sorted): the
        # ds-preview route + the on-demand build-planner brain. NEVER the
        # coach tick.
        assert sorted(callers) == [
            "core/build_planner/situational.py",
            "dashboard/routes_state.py",
        ], callers


# ===========================================================================
# BUG - compute_target_stats_from_items (live path, ds-preview) omits the
# champion base resist-by-level. Engine treats target_armor as ABSOLUTE
# (dps.py:574 effective_target_armor(target_armor,...) - no base added),
# and the live-items branch in _resolve_ds_target_stats RETURNS instead of
# summing with the curve, so the base is never added anywhere. Fixed
# test-first via an opt-in champion-base layer in the non-frozen module.
# ===========================================================================
class TestLiveItemsPathOmitsChampionBase:
    def test_legacy_no_champion_arg_is_unchanged_items_only(self):
        """Backward-compat guard: called the old way (no enemy champions),
        behaviour is item-sum only - existing ds-preview callers and
        tests see no change."""
        from core.enemy_aware_stats import compute_target_stats_from_items

        a3075, _, h3075 = _item_flat("3075")
        out = compute_target_stats_from_items([["3075"]], aggregator="avg")
        assert out["target_armor"] == pytest.approx(round(a3075, 1))
        assert out["target_max_hp"] == pytest.approx(round(h3075, 1))
        assert out["source"] == "live-items"

    @pytest.mark.parametrize("level", [1, 6, 11, 16, 18])
    @pytest.mark.parametrize("n_items", [1, 2, 3, 4, 5, 6])
    def test_base_by_level_added_when_champions_supplied(self, level, n_items):
        """When the caller supplies the enemy champions + level (which
        /api/ds-preview already resolves), the returned target_armor /
        target_mr / target_max_hp MUST equal Riot-quadratic champion base
        by level PLUS the item flats, averaged across enemies - matching
        what the engine expects for an absolute target.

        Single enemy with an n-item build, levels {1,6,11,16,18}.
        """
        from core.enemy_aware_stats import compute_target_stats_from_items

        champ = "Malphite"  # representative bruiser/tank target
        items = _ARMOR_ITEM_POOL[:n_items]
        ia = im = ih = 0.0
        for it in items:
            a, m, h = _item_flat(it)
            ia += a
            im += m
            ih += h
        ba, bm, bh = _champ_base_by_level(champ, level)

        out = compute_target_stats_from_items(
            [items], aggregator="avg",
            enemy_champions=[champ], level=level,
        )
        assert out["source"] == "live-items+base"
        assert out["target_armor"] == pytest.approx(round(ba + ia, 1), abs=0.2)
        assert out["target_mr"] == pytest.approx(round(bm + im, 1), abs=0.2)
        assert out["target_max_hp"] == pytest.approx(round(bh + ih, 1), abs=0.2)
        # bonus_hp excludes champion BASE hp (item + per-level growth only)
        # because bonus-HP-scaling items (Giant Slayer / BotRK) key off
        # bonus HP, not max HP.
        s = _champ_stats()[champ]["stats"]
        grown_hp = s["hpperlevel"] * _riot_growth_multiplier(level)
        assert out["target_bonus_hp"] == pytest.approx(round(grown_hp + ih, 1), abs=0.2)

    def test_multi_enemy_average_includes_each_base(self):
        """Aggregator 'avg' must average base+items per enemy, not just
        items - a 5-item-armor enemy and a naked enemy still both carry
        their champion base armor by level."""
        from core.enemy_aware_stats import compute_target_stats_from_items

        champs = ["Malphite", "Lux"]
        builds = [["3075", "3143"], []]  # tank itemized, mage naked
        level = 11
        per_enemy_armor = []
        for champ, items in zip(champs, builds):
            ia = sum(_item_flat(i)[0] for i in items)
            ba, _, _ = _champ_base_by_level(champ, level)
            per_enemy_armor.append(ba + ia)
        expected = round(sum(per_enemy_armor) / len(per_enemy_armor), 1)

        out = compute_target_stats_from_items(
            builds, aggregator="avg",
            enemy_champions=champs, level=level,
        )
        assert out["target_armor"] == pytest.approx(expected, abs=0.3)

    def test_understatement_is_material_single_thornmail_l11(self):
        """Concrete regression: a level-11 enemy with one Thornmail.
        Old behaviour fed DS ~75 armor (item only); correct absolute
        target armor is base-by-level + 75, which is roughly DOUBLE.
        Pin that the corrected value is materially larger so a revert
        that drops the base is caught loudly."""
        from core.enemy_aware_stats import compute_target_stats_from_items

        champ, level = "Malphite", 11
        items_only = compute_target_stats_from_items([["3075"]], aggregator="avg")
        with_base = compute_target_stats_from_items(
            [["3075"]], aggregator="avg",
            enemy_champions=[champ], level=level,
        )
        ba, _, _ = _champ_base_by_level(champ, level)
        assert with_base["target_armor"] == pytest.approx(
            round(ba + _item_flat("3075")[0], 1), abs=0.2
        )
        # base armor at L11 for a tank is ~75 - i.e. the omission roughly
        # halved the target armor. Assert the gap is the full base.
        assert with_base["target_armor"] - items_only["target_armor"] == pytest.approx(
            round(ba, 1), abs=0.2
        )
        assert with_base["target_armor"] > items_only["target_armor"] * 1.5


# ===========================================================================
# TIMEFRAME CONSISTENCY - as the game progresses (more items, higher level)
# the corrected live-items target must track it monotonically. A stale or
# first-tick-only snapshot would be a bug.
# ===========================================================================
class TestTimeframeConsistency:
    def test_target_tracks_rising_items_and_level(self):
        from core.enemy_aware_stats import compute_target_stats_from_items

        champ = "Malphite"
        prev_armor = -1.0
        prev_hp = -1.0
        # Walk a plausible game arc: level rises, items accumulate.
        for level, n_items in [(1, 0), (6, 1), (11, 3), (16, 5), (18, 6)]:
            items = _ARMOR_ITEM_POOL[:n_items]
            out = compute_target_stats_from_items(
                [items], aggregator="avg",
                enemy_champions=[champ], level=level,
            )
            assert out["target_armor"] >= prev_armor
            assert out["target_max_hp"] >= prev_hp
            prev_armor = out["target_armor"]
            prev_hp = out["target_max_hp"]
        # At the L1/0-item tick the target is still the champion base, not
        # zero - a "no items yet" snapshot must NOT collapse to 0 armor.
        z = compute_target_stats_from_items(
            [[]], aggregator="avg", enemy_champions=[champ], level=1,
        )
        ba, bm, _ = _champ_base_by_level(champ, 1)
        assert z["target_armor"] == pytest.approx(round(ba, 1), abs=0.2)
        assert z["target_mr"] == pytest.approx(round(bm, 1), abs=0.2)
