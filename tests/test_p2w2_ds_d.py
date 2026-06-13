"""P2-W2 cycle 12 DS-engine audit (slice D, effects-data) - regression tests.

Covers the FIX-NOW hardening landed in this slice on the effect-application
boundary (``agents/daemon_slayer/_effects_types.py``). The dominant cycle
7-11 finding class is a non-finite (NaN/inf) numeric serializing to a bare
``NaN`` / ``Infinity`` JSON token that breaks downstream browser
``JSON.parse``. The three magnitude-resolution methods on the effect
dataclasses were the un-guarded sink:

* ``PeriodicProc.resolve_damage`` returned ``float(callable(ctx))`` with NO
  finite guard - a proc lambda fed a non-finite ``CallContext`` field
  (e.g. ``target_max_hp=inf`` from a caller / sweep axis through the
  ``0.09 * c.target_max_hp`` BotRK proc) returned ``inf``/``nan`` straight
  into ``dps._periodic_proc_dps`` -> ``DpsResult.weighted_dps`` ->
  ``json.dumps`` (default ``allow_nan=True``) -> bare ``Infinity``/``NaN``.
* ``ItemShield.resolve_magnitude`` / ``ItemHeal.resolve_magnitude`` ended
  with ``max(0.0, float(total))``. ``max(0.0, nan)`` floors to 0.0 by
  CPython evaluation order, but ``max(0.0, inf)`` returns ``inf`` -> the
  same bare-token hazard one level up in ``ehp.compute_ehp``
  (physical_ehp / magical_ehp / true_ehp -> ``to_dict`` -> ``json.dumps``).

The fix returns 0.0 on a non-finite resolved magnitude - the same
"contributes nothing on degenerate input" convention the whole effects
module already uses (e.g. ``total_bonus_ap_from_hp`` returns 0.0 when
``caster_bonus_hp <= 0``). Finite inputs are byte-identical: NO scorer
numeric output changes for real data, only degenerate non-finite input is
guarded.

Each test asserts the OLD path leaked a non-finite value (RED) and the
NEW path returns a JSON-finite number (GREEN). tmp_path is not needed -
these are pure in-memory dataclass tests with no file writes.

Symbols grep-confirmed against the live tree before use:
  _effects_types.PeriodicProc                 (_effects_types.py:143)
  _effects_types.PeriodicProc.resolve_damage  (_effects_types.py:204)
  _effects_types.PeriodicProc.bonus_damage    (_effects_types.py:170)
  _effects_types.ItemShield                   (_effects_types.py:217)
  _effects_types.ItemShield.resolve_magnitude (_effects_types.py:279)
  _effects_types.ItemHeal                     (_effects_types.py:311)
  _effects_types.ItemHeal.resolve_magnitude   (_effects_types.py:396)
  _effects_types.CallContext                  (_effects_types.py:30)
  _effects_types.CallContext.target_max_hp    (_effects_types.py:80)
  _effects_types.CallContext.base_ad          (_effects_types.py:74)
  _effects_types.MAGICAL / PHYSICAL / ANY     (_effects_types.py:16,17,26)
  effects.collect_effects                     (effects.py:55)
  effects.total_crit_chance_bonus             (effects.py:110)
  _effects_data.ITEM_EFFECTS                  (_effects_data.py:26)
  _effects_data ITEM_EFFECTS["3153"] (BotRK, 0.09*target_max_hp lambda)
                                              (_effects_data.py:532)
"""

from __future__ import annotations

import json
import math

import pytest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._effects_types import (
    ANY,
    CallContext,
    ItemHeal,
    ItemShield,
    MAGICAL,
    PHYSICAL,
    PeriodicProc,
)
from agents.daemon_slayer.effects import (
    collect_effects,
    total_crit_chance_bonus,
)


def _ctx(**kw: float) -> CallContext:
    base = dict(base_ad=60.0, bonus_ad=50.0, level=11)
    base.update(kw)
    return CallContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PeriodicProc.resolve_damage - non-finite proc magnitude (primary sink)
# ---------------------------------------------------------------------------


class TestResolveDamageNonFinite:
    def test_inf_context_field_does_not_leak_inf(self) -> None:
        # A %-target-max-HP proc fed target_max_hp=inf pre-fix returned inf,
        # which json.dumps emits as a bare ``Infinity`` token. Post-fix the
        # non-finite resolved magnitude is dropped to 0.0.
        proc = PeriodicProc(
            name="Mist's Edge",
            bonus_damage=lambda c: 0.09 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        out = proc.resolve_damage(_ctx(target_max_hp=float("inf")))
        assert math.isfinite(out), f"expected finite, got {out!r}"
        assert out == 0.0

    def test_nan_context_field_does_not_leak_nan(self) -> None:
        proc = PeriodicProc(
            name="Mist's Edge",
            bonus_damage=lambda c: 0.09 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        out = proc.resolve_damage(_ctx(target_max_hp=float("nan")))
        assert not math.isnan(out)
        assert out == 0.0

    def test_resolved_value_is_json_finite(self) -> None:
        # End-to-end: the resolved magnitude must serialize without a bare
        # NaN/Infinity token (json default allow_nan=True would emit one).
        proc = PeriodicProc(
            name="Mist's Edge",
            bonus_damage=lambda c: 0.09 * c.target_max_hp,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        payload = json.dumps(
            {"dps": proc.resolve_damage(_ctx(target_max_hp=float("inf")))}
        )
        assert "Infinity" not in payload
        assert "NaN" not in payload

    def test_real_botrk_lambda_guarded(self) -> None:
        # Exercise the ACTUAL registry lambda (3153 BotRK Mist's Edge),
        # not a hand-rolled stand-in, so the guard protects the live data.
        proc = ITEM_EFFECTS["3153"].periodics[0]
        out = proc.resolve_damage(_ctx(target_max_hp=float("inf")))
        assert out == 0.0

    def test_finite_constant_unchanged(self) -> None:
        # Byte-identical pass-through for a finite constant proc.
        proc = PeriodicProc(
            name="Bolt",
            bonus_damage=100.0,
            damage_type=MAGICAL,
            every_n_seconds=4.0,
        )
        assert proc.resolve_damage(_ctx()) == 100.0

    def test_finite_callable_unchanged(self) -> None:
        # Byte-identical pass-through for a finite callable (Runaan's-shape).
        proc = PeriodicProc(
            name="Wind's Fury",
            bonus_damage=lambda c: 2.0 * 0.55 * (c.base_ad + c.bonus_ad),
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        # 2 * 0.55 * (60 + 50) = 121.0
        assert proc.resolve_damage(_ctx()) == pytest.approx(121.0)

    def test_negative_finite_passes_through(self) -> None:
        # resolve_damage has no 0.0 floor by design (callers compose the
        # value); a finite negative must still pass through unchanged - the
        # guard only drops NON-finite, it does not clamp sign.
        proc = PeriodicProc(
            name="Neg",
            bonus_damage=lambda c: -5.0,
            damage_type=PHYSICAL,
            every_n_attacks=1,
        )
        assert proc.resolve_damage(_ctx()) == -5.0


# ---------------------------------------------------------------------------
# ItemShield.resolve_magnitude - non-finite shield magnitude (EHP sink)
# ---------------------------------------------------------------------------


class TestItemShieldNonFinite:
    def test_inf_bonus_hp_does_not_leak_inf(self) -> None:
        # Sterak's-shape: 60% bonus HP. inf bonus_hp pre-fix returned inf
        # (max(0.0, inf) == inf), a bare-token hazard in ehp.compute_ehp.
        s = ItemShield(damage_type=ANY, bonus_hp_scaling=0.60)
        out = s.resolve_magnitude(level=11, bonus_hp=float("inf"))
        assert math.isfinite(out)
        assert out == 0.0

    def test_nan_flat_does_not_leak_nan(self) -> None:
        s = ItemShield(damage_type=ANY, flat=float("nan"))
        out = s.resolve_magnitude(level=5)
        assert not math.isnan(out)
        assert out == 0.0

    def test_finite_shield_unchanged(self) -> None:
        # Immortal-Shieldbow-shape flat at low level: byte-identical.
        s = ItemShield(damage_type=ANY, flat=400.0)
        assert s.resolve_magnitude(level=1) == 400.0

    def test_finite_scaling_unchanged(self) -> None:
        s = ItemShield(damage_type=ANY, bonus_hp_scaling=0.60)
        assert s.resolve_magnitude(level=11, bonus_hp=1000.0) == 600.0

    def test_json_finite(self) -> None:
        s = ItemShield(damage_type=ANY, bonus_hp_scaling=0.60)
        payload = json.dumps(
            {"ehp": s.resolve_magnitude(level=11, bonus_hp=float("inf"))}
        )
        assert "Infinity" not in payload and "NaN" not in payload


# ---------------------------------------------------------------------------
# ItemHeal.resolve_magnitude - non-finite heal magnitude (EHP sink)
# ---------------------------------------------------------------------------


class TestItemHealNonFinite:
    def test_inf_bonus_ad_does_not_leak_inf(self) -> None:
        # Death's-Dance-shape: 75% bonus AD. inf bonus_ad pre-fix returned
        # inf (max(0.0, inf) == inf).
        h = ItemHeal(bonus_ad_scaling=0.75)
        out = h.resolve_magnitude(bonus_ad=float("inf"))
        assert math.isfinite(out)
        assert out == 0.0

    def test_inf_missing_hp_does_not_leak_inf(self) -> None:
        # Sundered-Sky-shape: 6% missing HP additive.
        h = ItemHeal(missing_hp_pct=0.06)
        out = h.resolve_magnitude(missing_hp=float("inf"))
        assert math.isfinite(out)
        assert out == 0.0

    def test_finite_heal_unchanged(self) -> None:
        # base_ad_scaling=1.0 melee Sundered-Sky-shape: byte-identical.
        h = ItemHeal(base_ad_scaling=1.0)
        assert h.resolve_magnitude(base_ad=80.0) == 80.0

    def test_finite_missing_hp_unchanged(self) -> None:
        h = ItemHeal(base_ad_scaling=1.0, missing_hp_pct=0.06)
        # 80 base AD + 0.06 * 1000 missing = 80 + 60 = 140
        assert h.resolve_magnitude(base_ad=80.0, missing_hp=1000.0) == 140.0

    def test_json_finite(self) -> None:
        h = ItemHeal(bonus_ad_scaling=0.75)
        payload = json.dumps({"heal": h.resolve_magnitude(bonus_ad=float("inf"))})
        assert "Infinity" not in payload and "NaN" not in payload


# ---------------------------------------------------------------------------
# Companion guards already present in effects.py (regression pins, GREEN now)
# ---------------------------------------------------------------------------


class TestEffectsCompanionGuards:
    def test_collect_effects_dedup_first_seen_wins(self) -> None:
        # Two spellblade items: only the first survives (unique_passive_key).
        # Pins the dedup contract the data table relies on.
        out = collect_effects(["3078", "3100"])  # Trinity Force, Lich Bane
        assert len(out) == 1
        assert out[0].item_id == "3078"

    def test_total_crit_chance_zero_bonus_hp_no_ramp(self) -> None:
        # Atma's HP-ramp contributes 0 at 0 bonus HP (no divide hazard).
        atma = ITEM_EFFECTS["3039"]
        assert total_crit_chance_bonus([atma], caster_bonus_hp=0.0) == 0.0
