"""Pin core.cc_conditional_impact_context.cc_conditional_impact_line behavior.

FIRST coach-prompt consumer of the ``cc_conditional`` registry (item
141 Slice B forward-marker module at ENGINE 1.37.0; item 142 Slice A
first engine math consumer at ENGINE 1.38.0; items 143 Slice A + B
second + third engine math consumers at ENGINE 1.40.0). This file is
the 4TH OVERALL CONSUMER and FIRST coach-prompt consumer of the
cc_conditional ecosystem.

Mirror of ``tests/test_cc_blended_ehp_context.py`` pattern - monkey-
patches ``compute_cc_pressure`` via ``unittest.mock.patch`` so the
consumer is exercised directly regardless of whether the engine module
is loaded fresh.

Math contract pinned exactly to ``agents/daemon_slayer/ehp.compute_ehp``
with the conditional contribution sourced from
``CcPressureResult.conditional_cc_seconds`` (already post-tenacity
probability-weighted by the engine seam at ENGINE 1.38.0):
  conditional_total = sum(
      compute_cc_pressure(e, mode, include_conditional=True)
          .conditional_cc_seconds
      for e in enemies if e
  )
  cc_pressure_fraction = min(conditional_total / fight_window_s, 1.0)
  effective_ehp_loss_pct = cc_pressure_fraction * cc_effectiveness_factor * 100

Output line format:
  "Enemy conditional CC pressure: 4.2s probability-weighted "
  "(additive on top of unconditional CC) = 70% saturation, "
  "blended-EHP impact -35%"

Test classes:
  * LineRendersTests              - happy path + sum + saturation clamp
  * ModeGateTests                 - blank / None mode, empty enemies
  * FightWindowTests              - per-call fight_window_s override
  * CcEffectivenessFactorTests    - per-call factor override
  * MathTests                     - default constants match ehp.py
  * MonkeyPatchTests              - patch target works as documented
  * TupleInputTests               - tuple input accepted
  * SkipsBlankTests               - blank / None entries silently skipped
  * CoachWireTests                - 4 mode coaches import + invoke helper
  * AsciiHygieneTests             - new module + test are pure ASCII
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


# Slice-shaped fakes mirror the engine's CcPressureResult; we only need
# ``conditional_cc_seconds`` (the renderer reads exactly that field on
# the include_conditional=True path).


@dataclass(frozen=True)
class FakeResult:
    champion: str
    mode: str
    total_cc_seconds: float = 0.0
    conditional_cc_seconds: float = 0.0


def _empty(champion: str, mode: str) -> FakeResult:
    return FakeResult(
        champion=champion,
        mode=mode,
        total_cc_seconds=0.0,
        conditional_cc_seconds=0.0,
    )


def _brand(_champion="Brand", mode="SR") -> FakeResult:
    """Brand R 2.0s * nth_hit 0.7 = 1.4s probability-weighted."""
    return FakeResult(
        champion="Brand",
        mode=mode,
        total_cc_seconds=1.4,
        conditional_cc_seconds=1.4,
    )


def _mordekaiser(_champion="Mordekaiser", mode="SR") -> FakeResult:
    """Mordekaiser R banishment 7.0s * mode_gated 1.0 = 7.0s; with
    0.25s unconditional E pull total_cc=7.25 but conditional_cc=7.0."""
    return FakeResult(
        champion="Mordekaiser",
        mode=mode,
        total_cc_seconds=7.25,
        conditional_cc_seconds=7.0,
    )


def _twisted_fate(_champion="TwistedFate", mode="SR") -> FakeResult:
    """TwistedFate W Gold Card 1.5s * gold_card 0.4 = 0.6s
    probability-weighted (TF has no unconditional CC at 16.10.1)."""
    return FakeResult(
        champion="TwistedFate",
        mode=mode,
        total_cc_seconds=0.6,
        conditional_cc_seconds=0.6,
    )


def _annie(_champion="Annie", mode="SR") -> FakeResult:
    """Annie unconditional R only - conditional_cc_seconds=0.0 so
    Annie contributes nothing to the conditional aggregate."""
    return FakeResult(
        champion="Annie",
        mode=mode,
        total_cc_seconds=1.5,
        conditional_cc_seconds=0.0,
    )


def _heavy_cond(_champion="HeavyCond", mode="SR") -> FakeResult:
    """Synthesized heavy conditional CC user - 3.0s probability-
    weighted (used for saturation clamp tests)."""
    return FakeResult(
        champion="HeavyCond",
        mode=mode,
        total_cc_seconds=3.0,
        conditional_cc_seconds=3.0,
    )


def _make_dispatcher(table: dict[str, FakeResult]):
    """Build a stub function for compute_cc_pressure that dispatches
    by champion name; missing names return empty.

    The stub MUST accept ``include_conditional`` as a kwarg because the
    renderer passes it explicitly to opt into the conditional axis.
    """

    def _stub(
        champion: str,
        mode: str = "SR",
        *,
        include_conditional: bool = False,
    ) -> FakeResult:
        if not champion:
            return _empty(champion or "", mode)
        return table.get(champion, _empty(champion, mode))

    return _stub


_PATCH_TARGET = (
    "core.cc_conditional_impact_context.compute_cc_pressure"
)


class LineRendersTests(unittest.TestCase):
    def test_single_brand_renders(self):
        # 1.4s / 6s = 23.33% saturation; 0.2333 * 0.5 = 0.1167 -> -12%.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        self.assertEqual(
            line,
            "Enemy conditional CC pressure: 1.4s probability-weighted "
            "(additive on top of unconditional CC) = 23% saturation, "
            "blended-EHP impact -12%",
        )

    def test_two_enemies_sum(self):
        # Brand 1.4 + Mordekaiser 7.0 = 8.4s -> clamps to 6 at the
        # fraction layer = 100% saturation, -50% blended-EHP.
        table = {
            "Brand": _brand(),
            "Mordekaiser": _mordekaiser(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand", "Mordekaiser"], "SR"
            )
        # Total 8.4s reported BEFORE clamp - clamp is on saturation.
        self.assertIn("8.4s probability-weighted", line)
        self.assertIn("100% saturation", line)
        self.assertIn("blended-EHP impact -50%", line)

    def test_three_enemies_sum_below_saturation(self):
        # Brand 1.4 + TwistedFate 0.6 = 2.0s; Mordekaiser excluded so
        # 2.0 / 6 = 33.33% -> "33%"; 0.3333 * 0.5 = 0.1667 -> "17%".
        table = {
            "Brand": _brand(),
            "TwistedFate": _twisted_fate(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand", "TwistedFate"], "SR"
            )
        self.assertIn("2.0s probability-weighted", line)
        self.assertIn("33% saturation", line)
        self.assertIn("blended-EHP impact -17%", line)

    def test_saturation_clamp_at_100pct(self):
        # 5 enemies at 3.0s each = 15s -> clamp at 1.0 fraction -> 50%
        # impact floor.
        table = {
            "H1": _heavy_cond(), "H2": _heavy_cond(),
            "H3": _heavy_cond(), "H4": _heavy_cond(),
            "H5": _heavy_cond(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["H1", "H2", "H3", "H4", "H5"], "SR"
            )
        self.assertIn("15.0s probability-weighted", line)
        self.assertIn("100% saturation", line)
        self.assertIn("blended-EHP impact -50%", line)

    def test_aram_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Brand": _brand(mode="ARAM")}),
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "ARAM")
        self.assertIn("Enemy conditional CC pressure", line)

    def test_kiwi_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Brand": _brand(mode="KIWI")}),
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "KIWI")
        self.assertIn("Enemy conditional CC pressure", line)

    def test_arena_cherry_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Brand": _brand(mode="CHERRY")}),
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "CHERRY")
        self.assertIn("Enemy conditional CC pressure", line)

    def test_unconditional_only_enemy_returns_empty(self):
        # Annie has unconditional R only (total_cc=1.5) but
        # conditional_cc=0.0 - this consumer reads conditional only.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Annie": _annie()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Annie"], "SR")
        self.assertEqual(line, "")

    def test_phrase_contains_probability_weighted_marker(self):
        # The pinned phrase "probability-weighted" disambiguates this
        # line from the unconditional sibling at the operator-glance
        # level.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        self.assertIn("probability-weighted", line)
        self.assertIn(
            "additive on top of unconditional CC", line
        )

    def test_label_says_conditional_not_unconditional(self):
        # The header says "Enemy conditional CC pressure" not "Enemy
        # CC pressure" - distinct from cc_blended_ehp_impact_line.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        self.assertTrue(line.startswith("Enemy conditional CC pressure: "))


class ModeGateTests(unittest.TestCase):
    def test_blank_mode_returns_empty(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line(["Brand"], ""), ""
            )

    def test_none_mode_returns_empty(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line(["Brand"], None), ""
            )

    def test_valid_mode_empty_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line([], "SR"), ""
            )

    def test_valid_mode_none_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line(None, "SR"), ""
            )

    def test_valid_mode_all_unknown_enemies_returns_empty(self):
        # All unknown -> compute_cc_pressure returns empty (0.0
        # conditional) -> total stays 0 -> empty.
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line(
                    ["Aatrox", "Garen", "Vayne"], "SR"
                ),
                "",
            )

    def test_mix_of_registered_and_unknown_enemies(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand", "Aatrox", "Garen"], "SR"
            )
        # Only Brand contributes -> 1.4s total.
        self.assertIn("1.4s", line)

    def test_lowercase_aram_accepted(self):
        # Mirror enemy_cc_threat_line contract: mode is mode-agnostic
        # at this consumer level; compute_cc_pressure handles the
        # uppercase comparison internally for ARAM-family modes.
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Brand": _brand(mode="aram")}),
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "aram")
        self.assertIn("Enemy conditional CC pressure", line)


class FightWindowTests(unittest.TestCase):
    def _table(self):
        return {"Brand": _brand()}  # 1.4s conditional

    def test_default_fight_window_is_6(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        # default 6s window -> 1.4/6 = 23.33%; line itself does not
        # echo "over 6s fight" (phrasing differs from sibling).
        self.assertIn("23% saturation", line)

    def test_custom_fight_window_10(self):
        # 1.4 / 10 = 14%; 0.14 * 0.5 = 0.07 -> -7%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", fight_window_s=10.0,
            )
        self.assertIn("14% saturation", line)
        self.assertIn("blended-EHP impact -7%", line)

    def test_custom_fight_window_2(self):
        # 1.4 / 2 = 70%; 0.70 * 0.5 = 0.35 -> -35%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", fight_window_s=2.0,
            )
        self.assertIn("70% saturation", line)
        self.assertIn("-35%", line)

    def test_custom_fight_window_1_clamps(self):
        # 1.4 / 1 = 140% but clamps at 100%; 1.0 * 0.5 = 0.5 -> -50%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", fight_window_s=1.0,
            )
        self.assertIn("100% saturation", line)
        self.assertIn("-50%", line)

    def test_zero_fight_window_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", fight_window_s=0.0,
            )
        self.assertEqual(line, "")

    def test_negative_fight_window_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", fight_window_s=-3.0,
            )
        self.assertEqual(line, "")


class CcEffectivenessFactorTests(unittest.TestCase):
    def _table(self):
        # Mordekaiser conditional = 7.0s -> saturates at 100% always
        # given the default 6s window. Use a heavy stub to exercise
        # factor variations against a known fraction.
        return {"Brand": _brand()}  # 1.4s = 23% saturation at 6s

    def test_default_factor_is_half(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        # 1.4 / 6 = 23.33%; 0.2333 * 0.5 = 0.1167 -> "12%".
        self.assertIn("23% saturation", line)
        self.assertIn("blended-EHP impact -12%", line)

    def test_factor_0_3_dampens_impact(self):
        # 0.2333 * 0.3 = 0.07 -> "7%".
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", cc_effectiveness_factor=0.3,
            )
        self.assertIn("23% saturation", line)
        self.assertIn("blended-EHP impact -7%", line)

    def test_factor_1_0_maximizes_impact(self):
        # 0.2333 * 1.0 = 0.2333 -> "23%".
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", cc_effectiveness_factor=1.0,
            )
        self.assertIn("blended-EHP impact -23%", line)

    def test_factor_0_renders_zero_impact_but_keeps_line(self):
        # Line still renders because saturation is non-zero.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["Brand"], "SR", cc_effectiveness_factor=0.0,
            )
        self.assertIn("23% saturation", line)
        self.assertIn("blended-EHP impact -0%", line)


class MathTests(unittest.TestCase):
    def test_default_constants_match_ehp_module(self):
        # Constants MUST match agents/daemon_slayer/ehp.py exactly
        # (operator-tunable midpoints per items 137 + 138 don't-redo).
        import core.cc_conditional_impact_context as ctx
        import agents.daemon_slayer.ehp as ehp
        self.assertEqual(ctx._FIGHT_WINDOW_S, ehp._FIGHT_WINDOW_S)
        self.assertEqual(
            ctx._CC_EFFECTIVENESS_FACTOR,
            ehp._CC_EFFECTIVENESS_FACTOR,
        )

    def test_default_kwargs_use_module_constants(self):
        # The function signature defaults should point to the module-
        # level constants (not literal values - if the constants ever
        # move, the signature follows automatically).
        import core.cc_conditional_impact_context as ctx
        import inspect
        sig = inspect.signature(ctx.cc_conditional_impact_line)
        self.assertEqual(
            sig.parameters["fight_window_s"].default,
            ctx._FIGHT_WINDOW_S,
        )
        self.assertEqual(
            sig.parameters["cc_effectiveness_factor"].default,
            ctx._CC_EFFECTIVENESS_FACTOR,
        )


class MonkeyPatchTests(unittest.TestCase):
    """Verify the patch target itself - the import path the
    fallback-stub mechanism uses."""

    def test_patch_target_is_importable_attr(self):
        # The module exposes compute_cc_pressure as a module-level
        # name (either real or fallback stub).
        import core.cc_conditional_impact_context as mod
        self.assertTrue(hasattr(mod, "compute_cc_pressure"))

    def test_patch_substitutes_dispatcher(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"X": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["X"], "SR")
        self.assertIn("Enemy conditional CC pressure", line)

    def test_renderer_passes_include_conditional_true(self):
        # Verify the renderer ACTUALLY passes include_conditional=True
        # to compute_cc_pressure - this is load-bearing because the
        # conditional axis is gated behind the kwarg at the engine.
        seen_kwargs = []

        def _spy(
            champion,
            mode="SR",
            *,
            include_conditional: bool = False,
        ):
            seen_kwargs.append({
                "champion": champion,
                "mode": mode,
                "include_conditional": include_conditional,
            })
            return _brand() if champion == "Brand" else _empty(
                champion or "", mode
            )

        with patch(_PATCH_TARGET, _spy):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            cc_conditional_impact_line(["Brand"], "SR")
        self.assertEqual(len(seen_kwargs), 1)
        self.assertTrue(seen_kwargs[0]["include_conditional"])

    def test_renderer_reads_conditional_cc_seconds_field(self):
        # Build a fake with total_cc_seconds high but
        # conditional_cc_seconds low - prove the renderer reads the
        # CONDITIONAL field, not the total. Annie has unconditional
        # 1.5s + conditional 0.0s -> the consumer ignores Annie.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Annie": _annie()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Annie"], "SR")
        self.assertEqual(line, "")


class TupleInputTests(unittest.TestCase):
    def test_tuple_input_accepted(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(("Brand",), "SR")
        self.assertIn("Enemy conditional CC pressure", line)

    def test_tuple_with_multiple_entries(self):
        table = {"Brand": _brand(), "TwistedFate": _twisted_fate()}
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ("Brand", "TwistedFate"), "SR"
            )
        # 1.4 + 0.6 = 2.0s
        self.assertIn("2.0s", line)


class SkipsBlankTests(unittest.TestCase):
    def test_skips_blank_string_entries(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                ["", "Brand", ""], "SR"
            )
        # Only Brand contributes.
        self.assertIn("1.4s", line)

    def test_skips_none_entries(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(
                [None, "Brand", None], "SR"
            )
        self.assertIn("1.4s", line)

    def test_all_blank_entries_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            self.assertEqual(
                cc_conditional_impact_line(
                    ["", None, ""], "SR"
                ),
                "",
            )


class CoachWireTests(unittest.TestCase):
    """4 active mode coaches all import + invoke
    cc_conditional_impact_line. Mirrors item 138 CoachWireTests
    pattern."""

    def test_aram_coach_imports_helper(self):
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "cc_conditional_impact_line"))

    def test_aram_user_template_has_placeholder(self):
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{cc_conditional_impact}", _USER_TMPL)

    def test_aram_user_template_format_with_field(self):
        from coaches.aram_coach import _USER_TMPL
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="", enemy_aram_tenacity="", aram_balance="",
            enemy_cc_threats="", cc_blended_ehp_impact="",
            cc_conditional_impact=(
                "Enemy conditional CC pressure: 1.4s "
                "probability-weighted (additive on top of "
                "unconditional CC) = 23% saturation, "
                "blended-EHP impact -12%"
            ),
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("probability-weighted", out)
        self.assertIn("23% saturation", out)

    def test_arena_coach_imports_helper(self):
        import coaches.arena_coach as mod
        self.assertTrue(hasattr(mod, "cc_conditional_impact_line"))

    def test_arena_user_template_has_placeholder(self):
        from coaches.arena_coach import _USER_TEMPLATE
        self.assertIn("{cc_conditional_impact}", _USER_TEMPLATE)

    def test_arena_user_template_format_with_field(self):
        from coaches.arena_coach import _USER_TEMPLATE
        out = _USER_TEMPLATE.format(
            round="1", champion="Caitlyn", partner="Lux", hp_pct=100,
            gold=0, level=1, kda="0/0/0", items="none", rank="1",
            alive="4", next_opp="?", team_rankings="-", augments="none",
            my_abilities="none",
            enemy_cc_threats="", cc_blended_ehp_impact="",
            cc_conditional_impact=(
                "Enemy conditional CC pressure: 0.6s "
                "probability-weighted (additive on top of "
                "unconditional CC) = 10% saturation, "
                "blended-EHP impact -5%"
            ),
            ds_picks="-", ds_label="-", vision_context="",
        )
        self.assertIn("probability-weighted", out)

    def test_brawl_coach_imports_helper(self):
        import coaches.brawl_coach as mod
        self.assertTrue(hasattr(mod, "cc_conditional_impact_line"))

    def test_brawl_coach_source_invokes_helper(self):
        # Brawl builds the user string by concat - the call site lives
        # in the source string. Verify by literal grep.
        src = (
            Path(__file__).resolve().parent.parent
            / "coaches" / "brawl_coach.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cc_conditional_impact_line(", src)
        self.assertIn("_cc_conditional_line", src)
        self.assertIn("_cc_conditional_segment", src)

    def test_brawl_coach_segment_appears_in_user_string(self):
        # The segment is concatenated into the user f-string after
        # _cc_blended_segment - verify it's referenced in the f-string.
        src = (
            Path(__file__).resolve().parent.parent
            / "coaches" / "brawl_coach.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "{_cc_blended_segment}{_cc_conditional_segment}",
            src,
        )

    def test_sr_prompt_imports_helper(self):
        import coach_integration._sr_prompt as mod
        self.assertTrue(hasattr(mod, "cc_conditional_impact_line"))

    def test_sr_prompt_source_invokes_helper(self):
        src = (
            Path(__file__).resolve().parent.parent
            / "coach_integration" / "_sr_prompt.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cc_conditional_impact_line(", src)


class AsciiHygieneTests(unittest.TestCase):
    """ASCII drift probe per CLAUDE.md no-em-dashes hard rule. Only
    scans this slice's added surfaces - NOT a wider sweep."""

    def test_module_is_pure_ascii(self):
        p = (
            Path(__file__).resolve().parent.parent
            / "core" / "cc_conditional_impact_context.py"
        )
        text = p.read_text(encoding="utf-8")
        # Build BAD glyph set via chr() so the test file itself stays
        # clean against its own scan.
        bad = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "smart-lq",
            chr(0x201D): "smart-rq",
            chr(0x2018): "smart-l",
            chr(0x2019): "smart-r",
        }
        for ch, label in bad.items():
            self.assertNotIn(
                ch, text, f"non-ASCII glyph {label!r} in module"
            )
        non_ascii = [b for b in text if ord(b) > 127]
        self.assertEqual(
            non_ascii, [], f"non-ASCII bytes in module: {non_ascii!r}"
        )

    def test_test_file_is_pure_ascii(self):
        # Self-scan: this test file MUST also be ASCII clean.
        p = Path(__file__).resolve()
        text = p.read_text(encoding="utf-8")
        bad = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "smart-lq",
            chr(0x201D): "smart-rq",
            chr(0x2018): "smart-l",
            chr(0x2019): "smart-r",
        }
        for ch, label in bad.items():
            self.assertNotIn(
                ch, text, f"non-ASCII glyph {label!r} in test file"
            )
        non_ascii = [b for b in text if ord(b) > 127]
        self.assertEqual(
            non_ascii, [],
            f"non-ASCII bytes in test file: {non_ascii!r}",
        )

    def test_format_string_is_ascii(self):
        # Pin the canonical output format - direct contract check via
        # a known monkey-patched value to lock the punctuation.
        import re as _re
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Brand": _brand()})
        ):
            from core.cc_conditional_impact_context import (
                cc_conditional_impact_line,
            )
            line = cc_conditional_impact_line(["Brand"], "SR")
        # Regex pin: "Enemy conditional CC pressure: <X.X>s
        # probability-weighted (additive on top of unconditional CC)
        # = <Y>% saturation, blended-EHP impact -<Z>%"
        pattern = (
            r"^Enemy conditional CC pressure: \d+\.\d+s "
            r"probability-weighted "
            r"\(additive on top of unconditional CC\) = "
            r"\d+% saturation, "
            r"blended-EHP impact -\d+%$"
        )
        self.assertIsNotNone(
            _re.match(pattern, line),
            f"format mismatch: {line!r}",
        )

    def test_coach_added_lines_are_ascii(self):
        # Targeted scan: the lines this slice ADDED to the 4 coach
        # modules MUST be ASCII (the rest of the coach files have
        # pre-existing non-ASCII that's out of scope here per the
        # CLAUDE.md retroactive-sweep operator gate).
        added_substrings = [
            "{cc_conditional_impact}",
            "cc_conditional_impact = cc_conditional_impact_line(",
            "cc_conditional_impact_line(",
            "_cc_conditional_line",
            "_cc_conditional_segment",
            "from core.cc_conditional_impact_context import (",
        ]
        coach_files = [
            Path(__file__).resolve().parent.parent / "coaches" / "aram_coach.py",
            Path(__file__).resolve().parent.parent / "coaches" / "arena_coach.py",
            Path(__file__).resolve().parent.parent / "coaches" / "brawl_coach.py",
            Path(__file__).resolve().parent.parent / "coach_integration" / "_sr_prompt.py",
        ]
        bad = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "smart-lq",
            chr(0x201D): "smart-rq",
            chr(0x2018): "smart-l",
            chr(0x2019): "smart-r",
        }
        for cf in coach_files:
            text = cf.read_text(encoding="utf-8")
            for needle in added_substrings:
                start = 0
                while True:
                    idx = text.find(needle, start)
                    if idx < 0:
                        break
                    # Scan the line containing the match.
                    line_start = text.rfind("\n", 0, idx) + 1
                    line_end = text.find("\n", idx)
                    if line_end < 0:
                        line_end = len(text)
                    line = text[line_start:line_end]
                    for ch, label in bad.items():
                        self.assertNotIn(
                            ch, line,
                            f"non-ASCII {label!r} in {cf.name} "
                            f"line containing {needle!r}: {line!r}",
                        )
                    start = idx + len(needle)


if __name__ == "__main__":
    unittest.main()
