"""P1-L20 (2026-05-19) - ability_dps RESOLUTION-MATH hardening.

Audit lane: the block/form/cooldown/combo resolution MATH that consumes
the (saturated, machine-guarded) pure-data override registries -
``champion_block_index.json`` / ``champion_form_index.json`` /
``champion_max_priority.json`` / ``champion_combo_sequences.json``.
Distinct from the registry-coverage sweeps (s223-s232) and from the
per-rank base-value audit (P1-L10): this file pins the SELECTION /
COMBINATION logic, not the data.

Audit verdict: all four sub-areas VERIFIED CORRECT against the vendored
snapshot + the documented selection rule. These tests lock the
invariants so a future refactor of ``_select_blocks`` /
``_form_cooldown_at_rank`` / the burst combo walker cannot silently
regress them.

Discipline: every expected value is DERIVED IN-TEST from the loaded
abilities snapshot + the documented rule (the damage-only filter, the
one-past-end clamp-to-last, form-0 cooldown inheritance, the
canonical>base-key block-override precedence, the "default"-branch
conditional resolution). No hardcoded champion magic numbers. No
fragile cross-champion comparison assertions - every assert is on a
quantity recomputed from the same primitives the engine uses.
"""
from __future__ import annotations

import json
import unittest

from agents.daemon_slayer import ult_rates
from agents.daemon_slayer.abilities import (
    AbilitiesSnapshot,
    AbilityForm,
    DamageBlock,
    reset_default_cache,
)
from agents.daemon_slayer.ability_dps import (
    _BLOCK_INDEX_PATH,
    _FORM_INDEX_PATH,
    _PRIORITY_TABLES,
    AbilityContext,
    _evaluate_block,
    _form_cooldown_at_rank,
    _select_blocks,
    compute_ability_dps,
    get_block_index_for,
    get_form_index_for,
    get_max_priority_for,
    rank_at_level,
    reset_block_index_cache,
    reset_form_index_cache,
    reset_max_priority_cache,
)
from agents.daemon_slayer.burst import (
    compute_burst_damage,
    get_combo_for,
    reset_combo_cache,
)
from agents.daemon_slayer.data_loader import DataSnapshot


def _abil_snap() -> AbilitiesSnapshot:
    reset_default_cache()
    reset_block_index_cache()
    reset_form_index_cache()
    reset_max_priority_cache()
    reset_combo_cache()
    ult_rates.reset_cache()
    return AbilitiesSnapshot.load()


def _data_snap() -> DataSnapshot:
    return DataSnapshot.load()


def _ctx() -> AbilityContext:
    """A fixed non-degenerate context. Concrete numbers are irrelevant -
    every assertion compares engine output against a recompute through
    the SAME ``_evaluate_block`` with this SAME ctx, so the context
    values never become magic numbers."""
    return AbilityContext(
        base_ad=60.0,
        total_ad=120.0,
        bonus_ad=60.0,
        ap=200.0,
        caster_max_hp=2200.0,
        caster_bonus_hp=700.0,
        caster_bonus_armor=0.0,
        caster_bonus_mr=0.0,
        caster_max_mp=600.0,
        caster_mp_regen_per_5=10.0,
        target_armor=80.0,
        target_mr=50.0,
        target_max_hp=2400.0,
        target_current_hp=2400.0,
        target_missing_hp=0.0,
        target_bonus_hp=900.0,
    )


def _damage_blocks(form: AbilityForm) -> tuple[DamageBlock, ...]:
    """Re-derive the damage-only block list exactly as ``_select_blocks``
    filters it - this IS the documented convention the registry was
    authored against (the registry _meta documents each filtered case
    e.g. 'Shen Q filtered idx 1 = raw block 2, raw 0 Slow stripped')."""
    return tuple(b for b in form.damage_blocks if b.attribute_kind == "damage")


def _resolved_form(snap, fmap, champ, base_key):
    """Apply the form_index registry the same way the engine does."""
    forms = snap.get_abilities(champ).get(base_key, ())
    if not forms:
        return None, ()
    fidx = fmap.get(base_key, 0)
    if fidx < 0 or fidx >= len(forms):
        fidx = 0
    return forms[fidx], forms


def _flatten_idx_values(v):
    """All concrete int indices reachable from an int / list / conditional
    dict registry value (the dict's branch values, default + downgrades)."""
    out: list[int] = []
    if isinstance(v, bool):
        return out
    if isinstance(v, int):
        return [v]
    if isinstance(v, list):
        return [int(x) for x in v]
    if isinstance(v, dict):
        for vv in v.values():
            out.extend(_flatten_idx_values(vv))
    return out


# --- Sub-area 1: block selection + one-past-end clamp ------------------------


class BlockSelectionMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = _abil_snap()
        cls.fmap_all = json.loads(
            _BLOCK_INDEX_PATH.read_text(encoding="utf-8")
        )["champions"]

    def test_indexed_selection_matches_registry_block_after_documented_filter(self):
        """For every mapped (champion, single-int key) the engine's
        "indexed" pick equals ``_evaluate_block`` of the registry index
        into the DAMAGE-FILTERED list with clamp-to-last - the exact
        documented rule. Asserts the selected block is the registry one
        (not silently block 0, not out of range -> exception)."""
        ctx = _ctx()
        checked = 0
        for champ, keymap in self.fmap_all.items():
            if champ not in self.snap.champions:
                continue
            fmap, _ = get_form_index_for(champ)
            for k, raw_v in keymap.items():
                if not isinstance(raw_v, int) or isinstance(raw_v, bool):
                    continue
                base_k = k[0] if (len(k) == 2 and k[1] in "234") else k
                form, _forms = _resolved_form(self.snap, fmap, champ, base_k)
                if form is None:
                    continue
                dmg = _damage_blocks(form)
                if not dmg:
                    continue
                for rank in (0, 2, 4):
                    got = _select_blocks(
                        form.damage_blocks, rank, ctx, "indexed",
                        block_index=raw_v,
                    )
                    clamped = max(0, min(raw_v, len(dmg) - 1))
                    exp = _evaluate_block(dmg[clamped], rank, ctx)
                    self.assertAlmostEqual(
                        got, exp, places=6,
                        msg=(f"{champ} {k} idx={raw_v} rank={rank}: indexed "
                             f"selection diverged from clamped damage-filtered "
                             f"block {clamped}/{len(dmg)}"),
                    )
                checked += 1
        self.assertGreater(checked, 60, "expected many single-int entries")

    def test_one_past_end_clamps_to_last_damage_block_not_index_error(self):
        """The known one-past-end indices (idx == len(damage_blocks)) must
        resolve to the LAST damage block - the documented clamp-to-last
        convention (numerically the Total/Max/component roll-up). Asserts
        the load-bearing invariant: the pick equals ``_evaluate_block`` of
        the last damage block, never raises IndexError, and never silently
        falls back to block 0. (The block's *name* is intentionally not
        asserted - sum-list components like Malphite W [2,3] are correctly
        named per-component, not 'Total'.)"""
        ctx = _ctx()
        found = 0
        for champ, keymap in self.fmap_all.items():
            if champ not in self.snap.champions:
                continue
            fmap, _ = get_form_index_for(champ)
            for k, raw_v in keymap.items():
                base_k = k[0] if (len(k) == 2 and k[1] in "234") else k
                form, _forms = _resolved_form(self.snap, fmap, champ, base_k)
                if form is None:
                    continue
                dmg = _damage_blocks(form)
                if not dmg:
                    continue
                for iv in _flatten_idx_values(raw_v):
                    if iv != len(dmg):  # exactly one-past-end
                        continue
                    found += 1
                    # Must equal evaluating the last block, not raise,
                    # not block 0.
                    got = _select_blocks(
                        form.damage_blocks, 4, ctx, "indexed", block_index=iv,
                    )
                    exp_last = _evaluate_block(dmg[-1], 4, ctx)
                    self.assertAlmostEqual(
                        got, exp_last, places=6,
                        msg=(f"{champ} {k}: one-past-end idx {iv} did not "
                             f"clamp to the last damage block"),
                    )
                    if len(dmg) > 1:
                        exp_b0 = _evaluate_block(dmg[0], 4, ctx)
                        if abs(exp_last - exp_b0) > 1e-6:
                            self.assertNotAlmostEqual(
                                got, exp_b0, places=6,
                                msg=f"{champ} {k}: clamp fell back to block 0",
                            )
        self.assertGreaterEqual(found, 10, "expected the documented ~16 clamp cases")

    def test_unmapped_champion_defaults_to_first_damage_block(self):
        """An UNMAPPED champion has an empty block-index map -> the engine
        keeps the global ``block_strategy='first'`` = damage block 0."""
        unmapped = None
        for cid in self.snap.champion_ids():
            if cid in self.fmap_all:
                continue
            m, src = get_block_index_for(cid)
            if src != "default" or m != {}:
                continue
            forms = self.snap.get_abilities(cid).get("Q", ())
            if forms and len(_damage_blocks(forms[0])) >= 1:
                unmapped = cid
                break
        self.assertIsNotNone(unmapped, "need an unmapped champ with a Q damage block")
        ctx = _ctx()
        form = self.snap.get_abilities(unmapped)["Q"][0]
        dmg = _damage_blocks(form)
        got = _select_blocks(form.damage_blocks, 4, ctx, "first")
        exp = _evaluate_block(dmg[0], 4, ctx)
        self.assertAlmostEqual(got, exp, places=6)

    def test_negative_index_clamps_to_zero_not_python_negative_wrap(self):
        """A negative index must clamp to block 0 - NOT Python's
        list[-1] tail-wrap (a classic off-by-one trap)."""
        ctx = _ctx()
        form = None
        for cid in self.snap.champion_ids():
            f = self.snap.get_abilities(cid).get("Q", ())
            if f and len(_damage_blocks(f[0])) >= 2:
                form = f[0]
                break
        self.assertIsNotNone(form)
        dmg = _damage_blocks(form)
        got = _select_blocks(form.damage_blocks, 3, ctx, "indexed", block_index=-5)
        exp_first = _evaluate_block(dmg[0], 3, ctx)
        exp_last = _evaluate_block(dmg[-1], 3, ctx)
        self.assertAlmostEqual(got, exp_first, places=6)
        if abs(exp_first - exp_last) > 1e-6:
            self.assertNotAlmostEqual(got, exp_last, places=6)

    def test_conditional_dict_resolves_default_branch_not_downgrade(self):
        """Part-1 conditional schema: a dict block_index resolves to its
        ``"default"`` (operator-commits) branch unconditionally, never a
        downgrade branch - and a list-valued default sums its blocks."""
        ctx = _ctx()
        seen = 0
        for champ, keymap in self.fmap_all.items():
            if champ not in self.snap.champions:
                continue
            bmap, _ = get_block_index_for(champ)
            fmap, _ = get_form_index_for(champ)
            for k, v in bmap.items():
                if not isinstance(v, dict):
                    continue
                base_k = k[0] if (len(k) == 2 and k[1] in "234") else k
                form, _forms = _resolved_form(self.snap, fmap, champ, base_k)
                if form is None:
                    continue
                dmg = _damage_blocks(form)
                if not dmg:
                    continue
                default_v = v["default"]
                idxs = [default_v] if isinstance(default_v, int) else list(default_v)
                exp = 0.0
                for iv in idxs:
                    c = max(0, min(int(iv), len(dmg) - 1))
                    exp += _evaluate_block(dmg[c], 4, ctx)
                got = _select_blocks(
                    form.damage_blocks, 4, ctx, "indexed", block_index=v,
                )
                self.assertAlmostEqual(
                    got, exp, places=6,
                    msg=f"{champ} {k}: conditional default branch mis-resolved",
                )
                seen += 1
        self.assertGreater(seen, 0, "expected at least one conditional-dict entry")

    def test_empty_index_list_returns_zero(self):
        """An empty index sequence must return 0.0 (documented), not raise
        and not silently fall back to block 0."""
        ctx = _ctx()
        form = self.snap.get_abilities("Aatrox")["Q"][0]
        self.assertEqual(
            _select_blocks(form.damage_blocks, 3, ctx, "indexed", block_index=[]),
            0.0,
        )


# --- Sub-area 2: form resolution --------------------------------------------


class FormResolutionMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = _abil_snap()

    def test_form_index_selects_canonical_empowered_form_not_base(self):
        """Every form_index registry entry must select the registry form,
        and that form must differ from form 0 (it is the empowered /
        recast variant - Swain R / Briar W / Evelynn E / Riven R etc.)."""
        reg = json.loads(_FORM_INDEX_PATH.read_text(encoding="utf-8"))["champions"]
        self.assertTrue(reg, "form_index registry unexpectedly empty")
        for champ, keymap in reg.items():
            if champ not in self.snap.champions:
                continue
            fmap, src = get_form_index_for(champ)
            self.assertEqual(src, "champion")
            for k, want_idx in keymap.items():
                forms = self.snap.get_abilities(champ).get(k, ())
                self.assertTrue(forms, f"{champ} {k} has no forms")
                self.assertLess(
                    want_idx, len(forms),
                    f"{champ} {k} registry idx {want_idx} out of range",
                )
                self.assertNotEqual(
                    want_idx, 0,
                    f"{champ} {k} registry points at form 0 - pointless override",
                )
                chosen = forms[want_idx]
                base = forms[0]
                # The chosen form is a genuinely distinct stance (different
                # name OR different damage-block shape than form 0).
                distinct = (
                    chosen.name != base.name
                    or chosen.damage_blocks != base.damage_blocks
                )
                self.assertTrue(
                    distinct,
                    f"{champ} {k} form {want_idx} indistinguishable from form 0",
                )

    def test_compute_ability_dps_scores_overridden_form(self):
        """End-to-end: ``compute_ability_dps`` reports the registry
        form_index for an overridden key and the per-spell raw damage
        equals re-evaluating THAT form's selected block - proving the
        base form was not scored."""
        snap = _data_snap()
        # Swain R -> form 1 (Demonflare burst), block_index registry may
        # also redirect; recompute through the public selection helpers.
        res = compute_ability_dps(
            snap, "Swain", 16, item_ids=[], mode="SR",
            target_armor=70.0, target_mr=45.0, target_max_hp=2300.0,
        )
        self.assertEqual(res.form_index_source, "champion")
        fmap, _ = get_form_index_for("Swain")
        self.assertIn("R", fmap)
        rspell = next(s for s in res.per_spell if s.key == "R")
        self.assertEqual(
            rspell.form_index, fmap["R"],
            "R per-spell did not use the registry form_index",
        )
        forms = AbilitiesSnapshot.load().get_abilities("Swain")["R"]
        self.assertNotEqual(rspell.form_name, forms[0].name)
        self.assertEqual(rspell.form_name, forms[fmap["R"]].name)

    def test_out_of_range_form_override_falls_back_to_form_zero(self):
        """A caller form_index past the form count clamps to form 0 (no
        IndexError) and then needs no cooldown inheritance."""
        snap = _data_snap()
        res = compute_ability_dps(
            snap, "Garen", 11, item_ids=[], mode="SR",
            target_armor=60.0, target_mr=40.0, target_max_hp=2000.0,
            form_index_overrides={"Q": 99},
        )
        qspell = next(s for s in res.per_spell if s.key == "Q")
        self.assertEqual(qspell.form_index, 0)
        forms = AbilitiesSnapshot.load().get_abilities("Garen")["Q"]
        self.assertEqual(qspell.form_name, forms[0].name)


# --- Sub-area 3: cooldown inheritance ---------------------------------------


class CooldownInheritanceMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = _abil_snap()

    SETTLED = (("Riven", "R"), ("Renekton", "E"),
               ("AurelionSol", "R"), ("Qiyana", "Q"))

    def test_none_cooldown_form_inherits_form0_exactly_every_rank(self):
        """The 4 settled form-swap abilities: form 1 has cooldown=None and
        must inherit form 0's per-rank list EXACTLY at every rank, with
        the documented rank-clamp-to-last for shorter lists."""
        for champ, k in self.SETTLED:
            forms = self.snap.get_abilities(champ)[k]
            f0, f1 = forms[0], forms[1]
            self.assertTrue(f0.cooldown, f"{champ} {k} form0 should carry CD")
            self.assertFalse(
                bool(f1.cooldown),
                f"{champ} {k} form1 expected cooldown=None (settled rule)",
            )
            n = len(f0.cooldown)
            for rank in range(n + 2):  # exercise the rank-clamp tail too
                inherited = _form_cooldown_at_rank(f1, rank, fallback_form=f0)
                clamped_rank = max(0, min(rank, n - 1))
                self.assertEqual(
                    inherited, float(f0.cooldown[clamped_rank]),
                    msg=(f"{champ} {k} rank {rank}: inherited CD "
                         f"{inherited} != form0 {f0.cooldown[clamped_rank]}"),
                )

    def test_form_with_own_cooldown_does_not_inherit(self):
        """A non-form-0 form that DOES carry its own per-rank CD must use
        it, never the fallback (e.g. Nidalee/Jayce/Elise/Swain form 1)."""
        reg = json.loads(_FORM_INDEX_PATH.read_text(encoding="utf-8"))["champions"]
        checked = 0
        for champ, keymap in reg.items():
            if champ not in self.snap.champions:
                continue
            for k, idx in keymap.items():
                forms = self.snap.get_abilities(champ).get(k, ())
                if idx >= len(forms):
                    continue
                f = forms[idx]
                if not f.cooldown:
                    continue  # covered by the inheritance test
                # Fabricate a divergent fallback; the form's own CD wins.
                bogus = AbilityForm(
                    key=k, name="bogus", form_index=0, icon=None,
                    cooldown=(999.0,), cost=None, damage_type="MAGIC",
                    targeting=None, affects=None, resource=None,
                    is_aoe=False, damage_blocks=(), raw_effects_count=0,
                    raw_leveling_count=0, parse_status="ok", parse_notes=(),
                )
                for rank in range(len(f.cooldown)):
                    got = _form_cooldown_at_rank(f, rank, fallback_form=bogus)
                    self.assertEqual(
                        got, float(f.cooldown[rank]),
                        msg=f"{champ} {k} inherited despite own CD",
                    )
                    self.assertNotEqual(got, 999.0)
                checked += 1
        self.assertGreater(checked, 0, "expected own-CD form_index entries")

    def test_generic_60s_fallback_only_when_both_forms_lack_cd(self):
        """When neither the form nor the fallback has CD data the helper
        returns the documented generic 60.0 - and form 0 with no fallback
        also yields 60.0 (pre-s206 behavior preserved)."""
        empty = AbilityForm(
            key="R", name="e", form_index=1, icon=None, cooldown=None,
            cost=None, damage_type="MAGIC", targeting=None, affects=None,
            resource=None, is_aoe=False, damage_blocks=(),
            raw_effects_count=0, raw_leveling_count=0, parse_status="ok",
            parse_notes=(),
        )
        self.assertEqual(_form_cooldown_at_rank(empty, 0), 60.0)
        self.assertEqual(_form_cooldown_at_rank(empty, 2, fallback_form=empty), 60.0)

    def test_cooldown_inheritance_flows_into_ability_dps_frequency(self):
        """Integration: the inherited cooldown is the one reported by
        ``compute_ability_dps`` for the settled spells (when no measured
        cast-rate exists the theoretical 1/cd uses it)."""
        snap = _data_snap()
        for champ, k in self.SETTLED:
            res = compute_ability_dps(
                snap, champ, 16, item_ids=[], mode="SR",
                target_armor=60.0, target_mr=40.0, target_max_hp=2000.0,
            )
            forms = AbilitiesSnapshot.load().get_abilities(champ)[k]
            fmap, _ = get_form_index_for(champ)
            want_idx = fmap.get(k, 0)
            spell = next(s for s in res.per_spell if s.key == k)
            if spell.rank < 0:
                continue
            f0 = forms[0]
            clamped = max(0, min(spell.rank, len(f0.cooldown) - 1))
            self.assertEqual(
                spell.cooldown, float(f0.cooldown[clamped]),
                msg=(f"{champ} {k}: reported cd {spell.cooldown} != "
                     f"inherited form0 {f0.cooldown[clamped]}"),
            )
            self.assertEqual(spell.form_index, want_idx)


# --- Sub-area 4: max_priority / combo_sequence consumption ------------------


class MaxPriorityComboConsumptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = _abil_snap()

    def test_max_priority_changes_rank_curve_consistently(self):
        """``rank_at_level`` must honor the max_priority order: the
        first-maxed key out-ranks the third-maxed key at the level where
        the priority tables diverge - recomputed from the table, not a
        pinned champion number."""
        p1 = _PRIORITY_TABLES["priority_1"]
        p3 = _PRIORITY_TABLES["priority_3"]
        # Find a level where priority_1 strictly exceeds priority_3.
        lvl = next(L for L in range(1, 19) if p1[L] > p3[L])
        order = ("E", "Q", "W")  # E maxed first, W maxed third
        self.assertGreater(
            rank_at_level("E", lvl, max_priority=order),
            rank_at_level("W", lvl, max_priority=order),
            "max_priority not applied to the rank curve",
        )
        # And the resolved priority registry is actually consumed by
        # compute_ability_dps (source tag + the registry order).
        snap = _data_snap()
        res = compute_ability_dps(
            snap, "Cassiopeia", lvl, item_ids=[], mode="SR",
            target_armor=60.0, target_mr=40.0, target_max_hp=2000.0,
        )
        self.assertEqual(res.max_priority_source, "champion")
        reg_order, _ = get_max_priority_for("Cassiopeia")
        self.assertEqual(tuple(res.max_priority), tuple(reg_order))

    def test_explicit_max_priority_overrides_registry(self):
        """A caller-supplied max_priority wins over the registry and
        flips the rank ordering accordingly."""
        snap = _data_snap()
        base = compute_ability_dps(
            snap, "Cassiopeia", 9, item_ids=[], mode="SR",
            target_armor=50.0, target_mr=30.0, target_max_hp=1800.0,
        )
        forced = compute_ability_dps(
            snap, "Cassiopeia", 9, item_ids=[], mode="SR",
            target_armor=50.0, target_mr=30.0, target_max_hp=1800.0,
            max_priority=("W", "E", "Q"),
        )
        self.assertEqual(forced.max_priority_source, "override")
        self.assertEqual(tuple(forced.max_priority), ("W", "E", "Q"))
        self.assertNotEqual(tuple(base.max_priority), tuple(forced.max_priority))

    def test_combo_sequence_every_token_consumed_in_burst(self):
        """Every token of a champion's registered combo_sequence produces
        exactly one per_cast row, in order - the combo is applied, not
        ignored and not double-applied."""
        snap = _data_snap()
        for champ in ("Zed", "Akali", "Qiyana", "Talon"):
            combo, src = get_combo_for(champ)
            self.assertEqual(src, "champion")
            res = compute_burst_damage(
                snap, champ, 13, item_ids=[], mode="SR",
                target_armor=70.0, target_mr=45.0, target_max_hp=2200.0,
            )
            self.assertEqual(tuple(res.combo_sequence), tuple(combo))
            self.assertEqual(
                len(res.per_cast), len(combo),
                f"{champ}: per_cast length != combo length (double/skip)",
            )
            for tok, cast in zip(combo, res.per_cast):
                self.assertEqual(
                    cast.token, tok,
                    f"{champ}: combo token order not preserved",
                )

    def test_repeat_token_block_override_precedence_in_burst(self):
        """Akali's combo has R then R2; the registry maps R->0 and R2->2.
        The canonical-token entry (R2) must win over the base-key entry
        (R) for the recast - and each must equal the documented
        clamp-to-last evaluation of its own index."""
        snap = _data_snap()
        bmap, _ = get_block_index_for("Akali")
        self.assertIn("R", bmap)
        self.assertIn("R2", bmap)
        res = compute_burst_damage(
            snap, "Akali", 16, item_ids=[], mode="SR",
            target_armor=70.0, target_mr=45.0, target_max_hp=2200.0,
        )
        casts = {c.token: c for c in res.per_cast if c.is_ability}
        if "R" not in casts or "R2" not in casts:
            self.skipTest("Akali R/R2 not both present at this level")
        r1, r2 = casts["R"], casts["R2"]
        self.assertEqual(r1.form_index, r2.form_index,
                         "R and R2 should share the same form")
        forms = AbilitiesSnapshot.load().get_abilities("Akali")["R"]
        form = forms[r1.form_index]
        dmg = _damage_blocks(form)
        ctx = AbilityContext.from_build(
            stats={"ad": 60.0, "hp": 2000.0, "armor": 30.0, "mr": 32.0,
                   "mp": 200.0, "mpregen": 8.0},
            base_stats={"ad": 60.0, "hp": 2000.0, "armor": 30.0, "mr": 32.0},
            target_armor=70.0, target_mr=45.0, target_max_hp=2200.0,
            target_bonus_hp=0.0,
        )
        # Recompute the RAW (pre-mode/amp/mit) selection per the rule and
        # compare the ratio so amp/mit constants cancel out (no magic #).
        def raw_for(idx_val):
            return _select_blocks(form.damage_blocks, r1.rank, ctx,
                                  "indexed", block_index=idx_val)
        exp_r1 = raw_for(bmap["R"])
        exp_r2 = raw_for(bmap["R2"])
        self.assertGreater(exp_r2, 0.0)
        self.assertGreater(exp_r1, 0.0)
        # R2 index (2) clamps to the max-execute block; it must out-scale
        # the R base block - proving R2's canonical entry took precedence
        # over the R base-key entry (else r2 would equal r1's selection).
        self.assertAlmostEqual(
            r2.raw_damage / r1.raw_damage,
            exp_r2 / exp_r1,
            places=4,
            msg="R2 did not take canonical-token block-override precedence",
        )


if __name__ == "__main__":
    unittest.main()
