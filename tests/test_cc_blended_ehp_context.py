"""Pin core.cc_blended_ehp_context.cc_blended_ehp_impact_line behavior.

First coach-prompt consumer of the ``cc_blended_ehp`` math model shipped
item 137 Slice A ``99164e8`` (ENGINE 1.33.0 - 2nd engine math consumer
of ``compute_cc_pressure``). Mirror of
``tests/test_enemy_cc_threat_context.py`` pattern - monkey-patches
``compute_cc_pressure`` via ``unittest.mock.patch`` so the consumer is
exercised directly regardless of whether the engine module is loaded
fresh.

Math contract pinned exactly to ``agents/daemon_slayer/ehp.compute_ehp``:
  total_cc_seconds = sum(compute_cc_pressure(e, mode).total_cc_seconds
                         for e in enemies if e)
  cc_pressure_fraction = min(total_cc_seconds / fight_window_s, 1.0)
  effective_ehp_loss_pct = cc_pressure_fraction * cc_effectiveness_factor * 100

Output line format:
  "Enemy CC pressure: 1.5s over 6s fight = 25% saturation, "
  "blended-EHP impact -13%"

Test classes:
  * LineRendersTests              - happy path + sum + saturation clamp
  * ModeGateTests                 - blank / None mode, empty enemies
  * FightWindowTests              - per-call fight_window_s override
  * CcEffectivenessFactorTests    - per-call factor override
  * MonkeyPatchTests              - patch target works as documented
  * TupleInputTests               - tuple input accepted
  * SkipsBlankTests               - blank / None entries silently skipped
  * CoachWireTests                - 4 mode coaches import + invoke helper
  * AsciiHygieneTest              - new module + test are pure ASCII
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


# Slice-A-shaped fakes mirror the engine's CcPressureResult; we only
# need ``total_cc_seconds`` (the renderer reads nothing else).


@dataclass(frozen=True)
class FakeResult:
    champion: str
    mode: str
    total_cc_seconds: float


def _empty(champion: str, mode: str) -> FakeResult:
    return FakeResult(
        champion=champion, mode=mode, total_cc_seconds=0.0,
    )


def _morgana(_champion="Morgana", mode="SR") -> FakeResult:
    """Morgana Q root - 3.0s at max rank."""
    return FakeResult(
        champion="Morgana", mode=mode, total_cc_seconds=3.0,
    )


def _annie(_champion="Annie", mode="SR") -> FakeResult:
    """Annie R stun - 1.5s at max rank."""
    return FakeResult(
        champion="Annie", mode=mode, total_cc_seconds=1.5,
    )


def _malzahar(_champion="Malzahar", mode="SR") -> FakeResult:
    """Malzahar R suppress - 2.5s at max rank."""
    return FakeResult(
        champion="Malzahar", mode=mode, total_cc_seconds=2.5,
    )


def _galio(_champion="Galio", mode="SR") -> FakeResult:
    """Galio W+E+R - 3.5s total."""
    return FakeResult(
        champion="Galio", mode=mode, total_cc_seconds=3.5,
    )


def _heavy(_champion="Heavy", mode="SR") -> FakeResult:
    """Synthesized heavy CC user - 3.0s total (used for saturation)."""
    return FakeResult(
        champion="Heavy", mode=mode, total_cc_seconds=3.0,
    )


def _make_dispatcher(table: dict[str, FakeResult]):
    """Build a stub function for compute_cc_pressure that dispatches
    by champion name; missing names return empty."""

    def _stub(champion: str, mode: str = "SR") -> FakeResult:
        if not champion:
            return _empty(champion or "", mode)
        return table.get(champion, _empty(champion, mode))

    return _stub


_PATCH_TARGET = "core.cc_blended_ehp_context.compute_cc_pressure"


class LineRendersTests(unittest.TestCase):
    def test_single_morgana_renders(self):
        # 3.0s / 6s = 50% saturation; 0.50 * 0.5 = 0.25 -> -25%.
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "SR")
        self.assertEqual(
            line,
            "Enemy CC pressure: 3.0s over 6s fight = 50% saturation, "
            "blended-EHP impact -25%",
        )

    def test_three_enemies_sum(self):
        # Morgana 3.0 + Malzahar 2.5 + Annie 1.5 = 7.0s -> clamps to 6
        # = 100% saturation, -50% blended-EHP.
        table = {
            "Annie": _annie(),
            "Morgana": _morgana(),
            "Malzahar": _malzahar(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Annie", "Morgana", "Malzahar"], "SR"
            )
        # Total 7.0s but reported BEFORE clamp - the clamp is for the
        # saturation fraction, NOT for the displayed total.
        self.assertIn("Enemy CC pressure: 7.0s", line)
        self.assertIn("100% saturation", line)
        self.assertIn("blended-EHP impact -50%", line)

    def test_one_enemy_at_25pct_saturation(self):
        # Synthesize a 1.5s total -> 1.5/6 = 25%; 0.25*0.5=0.125 ->
        # Python banker's rounding 0.0f gives "12" not "13".
        table = {"Annie": _annie()}
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Annie"], "SR")
        self.assertIn("Enemy CC pressure: 1.5s", line)
        self.assertIn("25% saturation", line)
        # f"{12.5:.0f}" -> "12" in Python (banker's rounding).
        self.assertIn("blended-EHP impact -12%", line)

    def test_saturation_clamp_at_100pct(self):
        # 5 enemies at 3.0s each = 15s -> clamp at 1.0 fraction -> 50%
        # impact floor.
        table = {
            "H1": _heavy(), "H2": _heavy(), "H3": _heavy(),
            "H4": _heavy(), "H5": _heavy(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["H1", "H2", "H3", "H4", "H5"], "SR"
            )
        self.assertIn("Enemy CC pressure: 15.0s", line)
        self.assertIn("100% saturation", line)
        self.assertIn("blended-EHP impact -50%", line)

    def test_aram_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Morgana": _morgana(mode="ARAM")}),
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "ARAM")
        self.assertIn("Enemy CC pressure", line)

    def test_kiwi_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Morgana": _morgana(mode="KIWI")}),
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "KIWI")
        self.assertIn("Enemy CC pressure", line)

    def test_arena_cherry_mode_supported(self):
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Annie": _annie(mode="CHERRY")}),
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Annie"], "CHERRY")
        self.assertIn("Enemy CC pressure", line)


class ModeGateTests(unittest.TestCase):
    def test_blank_mode_returns_empty(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line(["Morgana"], ""), ""
            )

    def test_none_mode_returns_empty(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line(["Morgana"], None), ""
            )

    def test_valid_mode_empty_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line([], "SR"), ""
            )

    def test_valid_mode_none_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line(None, "SR"), ""
            )

    def test_valid_mode_all_unknown_enemies_returns_empty(self):
        # All unknown -> compute_cc_pressure returns empty (0.0) ->
        # total stays 0 -> empty.
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line(
                    ["Aatrox", "Garen", "Vayne"], "SR"
                ),
                "",
            )

    def test_single_registered_enemy_renders(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Annie": _annie()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Annie", "Aatrox", "Garen"], "SR"
            )
        # Only Annie contributes -> 1.5s total.
        self.assertIn("1.5s", line)

    def test_lowercase_aram_accepted(self):
        # Mirror enemy_cc_threat_line contract: mode is mode-agnostic
        # at this consumer level; compute_cc_pressure does the
        # uppercase comparison internally.
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Morgana": _morgana(mode="aram")}),
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "aram")
        self.assertIn("Enemy CC pressure", line)


class FightWindowTests(unittest.TestCase):
    def _table(self):
        return {"Morgana": _morgana()}  # 3.0s

    def test_default_fight_window_is_6(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "SR")
        # default 6s window -> 3/6 = 50%, "over 6s fight"
        self.assertIn("over 6s fight", line)
        self.assertIn("50% saturation", line)

    def test_custom_fight_window_10(self):
        # 3.0 / 10 = 30%; 0.30 * 0.5 = 0.15 -> -15%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Morgana"], "SR", fight_window_s=10.0,
            )
        self.assertIn("over 10s fight", line)
        self.assertIn("30% saturation", line)
        self.assertIn("blended-EHP impact -15%", line)

    def test_custom_fight_window_3(self):
        # 3.0 / 3 = 100% (clamped); 1.0 * 0.5 = 0.5 -> -50%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Morgana"], "SR", fight_window_s=3.0,
            )
        self.assertIn("over 3s fight", line)
        self.assertIn("100% saturation", line)
        self.assertIn("-50%", line)

    def test_zero_fight_window_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Morgana"], "SR", fight_window_s=0.0,
            )
        self.assertEqual(line, "")

    def test_negative_fight_window_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Morgana"], "SR", fight_window_s=-3.0,
            )
        self.assertEqual(line, "")


class CcEffectivenessFactorTests(unittest.TestCase):
    def _table(self):
        return {"Galio": _galio()}  # 3.5s, 58% saturation @ 6s

    def test_default_factor_is_half(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Galio"], "SR")
        # 3.5 / 6 = 58.33% -> rounded 58%; 0.5833 * 0.5 = 0.2917 -> 29%.
        self.assertIn("58% saturation", line)
        self.assertIn("blended-EHP impact -29%", line)

    def test_factor_0_3_dampens_impact(self):
        # 0.5833 * 0.3 = 0.175 -> rounded 18%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Galio"], "SR", cc_effectiveness_factor=0.3,
            )
        self.assertIn("58% saturation", line)
        self.assertIn("blended-EHP impact -18%", line)

    def test_factor_1_0_maximizes_impact(self):
        # 0.5833 * 1.0 = 0.5833 -> rounded 58%.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Galio"], "SR", cc_effectiveness_factor=1.0,
            )
        self.assertIn("blended-EHP impact -58%", line)

    def test_factor_0_renders_zero_impact_but_keeps_line(self):
        # The line still renders because saturation is non-zero - the
        # operator can see CC is incoming even if the calibration says
        # it doesn't translate to EHP loss.
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["Galio"], "SR", cc_effectiveness_factor=0.0,
            )
        self.assertIn("58% saturation", line)
        self.assertIn("blended-EHP impact -0%", line)


class MonkeyPatchTests(unittest.TestCase):
    """Verify the patch target itself - the import path the
    fallback-stub mechanism uses."""

    def test_patch_target_is_importable_attr(self):
        # The module exposes compute_cc_pressure as a module-level
        # name (either real or fallback stub); the patch target name
        # MUST match what mock.patch expects.
        import core.cc_blended_ehp_context as mod
        self.assertTrue(hasattr(mod, "compute_cc_pressure"))

    def test_patch_substitutes_dispatcher(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"X": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["X"], "SR")
        self.assertIn("Enemy CC pressure", line)


class TupleInputTests(unittest.TestCase):
    def test_tuple_input_accepted(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(("Morgana",), "SR")
        self.assertIn("Morgana", "Morgana")  # name not in output text
        self.assertIn("Enemy CC pressure", line)

    def test_tuple_with_multiple_entries(self):
        table = {"Morgana": _morgana(), "Annie": _annie()}
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ("Morgana", "Annie"), "SR"
            )
        # 3.0 + 1.5 = 4.5s
        self.assertIn("4.5s", line)


class SkipsBlankTests(unittest.TestCase):
    def test_skips_blank_string_entries(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Annie": _annie()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                ["", "Annie", ""], "SR"
            )
        # Only Annie contributes.
        self.assertIn("1.5s", line)

    def test_skips_none_entries(self):
        with patch(
            _PATCH_TARGET, _make_dispatcher({"Annie": _annie()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(
                [None, "Annie", None], "SR"
            )
        self.assertIn("1.5s", line)

    def test_all_blank_entries_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            self.assertEqual(
                cc_blended_ehp_impact_line(
                    ["", None, ""], "SR"
                ),
                "",
            )


class CoachWireTests(unittest.TestCase):
    """4 active mode coaches all import + invoke
    cc_blended_ehp_impact_line."""

    def test_aram_coach_imports_helper(self):
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "cc_blended_ehp_impact_line"))

    def test_aram_user_template_has_placeholder(self):
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{cc_blended_ehp_impact}", _USER_TMPL)

    def test_aram_user_template_format_with_field(self):
        from coaches.aram_coach import _USER_TMPL
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="", enemy_aram_tenacity="",
            enemy_cc_threats="",
            cc_blended_ehp_impact=(
                "Enemy CC pressure: 3.0s over 6s fight = "
                "50% saturation, blended-EHP impact -25%"
            ),
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("blended-EHP impact -25%", out)

    def test_arena_coach_imports_helper(self):
        import coaches.arena_coach as mod
        self.assertTrue(hasattr(mod, "cc_blended_ehp_impact_line"))

    def test_arena_user_template_has_placeholder(self):
        from coaches.arena_coach import _USER_TEMPLATE
        self.assertIn("{cc_blended_ehp_impact}", _USER_TEMPLATE)

    def test_arena_user_template_format_with_field(self):
        from coaches.arena_coach import _USER_TEMPLATE
        out = _USER_TEMPLATE.format(
            round="1", champion="Caitlyn", partner="Lux", hp_pct=100,
            gold=0, level=1, kda="0/0/0", items="none", rank="1",
            alive="4", next_opp="?", team_rankings="-", augments="none",
            my_abilities="none",
            enemy_cc_threats="",
            cc_blended_ehp_impact=(
                "Enemy CC pressure: 1.5s over 6s fight = "
                "25% saturation, blended-EHP impact -12%"
            ),
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", vision_context="",
        )
        self.assertIn("blended-EHP impact", out)

    def test_brawl_coach_imports_helper(self):
        import coaches.brawl_coach as mod
        self.assertTrue(hasattr(mod, "cc_blended_ehp_impact_line"))

    def test_brawl_coach_source_invokes_helper(self):
        # Brawl builds the user string by concat - the call site lives
        # in the source string. Verify by literal grep.
        src = (
            Path(__file__).resolve().parent.parent
            / "coaches" / "brawl_coach.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cc_blended_ehp_impact_line(", src)

    def test_sr_prompt_imports_helper(self):
        import coach_integration._sr_prompt as mod
        self.assertTrue(hasattr(mod, "cc_blended_ehp_impact_line"))

    def test_sr_prompt_source_invokes_helper(self):
        src = (
            Path(__file__).resolve().parent.parent
            / "coach_integration" / "_sr_prompt.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cc_blended_ehp_impact_line(", src)


class AsciiHygieneTest(unittest.TestCase):
    def test_module_is_pure_ascii(self):
        p = (
            Path(__file__).resolve().parent.parent
            / "core" / "cc_blended_ehp_context.py"
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
        # Belt+braces - no byte above 127.
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
            _PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})
        ):
            from core.cc_blended_ehp_context import (
                cc_blended_ehp_impact_line,
            )
            line = cc_blended_ehp_impact_line(["Morgana"], "SR")
        # Regex pin: "Enemy CC pressure: <X.X>s over <Y>s fight = "
        #            "<Z>% saturation, blended-EHP impact -<W>%"
        pattern = (
            r"^Enemy CC pressure: \d+\.\d+s over \d+s fight = "
            r"\d+% saturation, blended-EHP impact -\d+%$"
        )
        self.assertIsNotNone(
            _re.match(pattern, line),
            f"format mismatch: {line!r}",
        )


if __name__ == "__main__":
    unittest.main()
