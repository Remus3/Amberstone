"""Pin core.enemy_cc_threat_context.enemy_cc_threat_line behavior.

First coach-prompt consumer of
``agents.daemon_slayer.cc_pressure.compute_cc_pressure`` (Slice A of
item 136 parallel drain). Mirror of
``tests/test_aram_tenacity_context.py`` pattern.

Slice A ships ``compute_cc_pressure`` + the ``CcPressureResult`` /
``CcSpellEntry`` dataclasses. This slice tests the renderer-side
consumer. Because the two slices are parallel and the engine module
may not be importable when this test file is exercised alone, all
behavior tests monkey-patch ``compute_cc_pressure`` at the consumer
call site via ``unittest.mock.patch`` - that's the canonical
defensive pattern for orchestrator-merged parallel slices and it
matches the spec verbatim.

Test classes:
  * LineRendersTests       - happy path + sort + limit-default
  * ModeGateTests          - blank / None mode, empty enemies, etc.
  * LimitTests             - limit=0/1/3/5 behavior
  * KindHintsTests         - registered hints + "CC" fallback
  * TopSpellTests          - highest-duration spell selected
  * AramTenacityIntegrationTests - duration_post_tenacity is what we read
  * CoachWireTests         - import + placeholder + format call in 4 coaches
  * AsciiHygieneTest       - new module is pure ASCII
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch


# Slice-A-shaped fakes so we don't depend on the real engine module
# (Slice A ships agents/daemon_slayer/cc_pressure.py separately).


@dataclass(frozen=True)
class FakeSpell:
    spell_key: str
    base_durations_s: tuple = ()
    max_rank_duration_s: float = 0.0
    duration_post_tenacity_s: float = 0.0


@dataclass(frozen=True)
class FakeResult:
    champion: str
    mode: str
    total_cc_seconds: float
    spells: tuple
    tenacity_mult: float = 1.0


def _empty(champion: str, mode: str) -> FakeResult:
    return FakeResult(
        champion=champion, mode=mode, total_cc_seconds=0.0,
        spells=(), tenacity_mult=1.0,
    )


def _morgana(_champion="Morgana", mode="SR") -> FakeResult:
    """Morgana Q root - 3.0s at max rank."""
    return FakeResult(
        champion="Morgana", mode=mode,
        total_cc_seconds=3.0,
        spells=(
            FakeSpell(
                spell_key="Q",
                base_durations_s=(2.0, 2.25, 2.5, 2.75, 3.0),
                max_rank_duration_s=3.0,
                duration_post_tenacity_s=3.0,
            ),
        ),
        tenacity_mult=1.0,
    )


def _annie(_champion="Annie", mode="SR") -> FakeResult:
    """Annie R stun - 1.5s at max rank."""
    return FakeResult(
        champion="Annie", mode=mode,
        total_cc_seconds=1.5,
        spells=(
            FakeSpell(
                spell_key="R", max_rank_duration_s=1.5,
                duration_post_tenacity_s=1.5,
            ),
        ),
        tenacity_mult=1.0,
    )


def _malzahar(_champion="Malzahar", mode="SR") -> FakeResult:
    """Malzahar R suppress - 2.5s at max rank."""
    return FakeResult(
        champion="Malzahar", mode=mode,
        total_cc_seconds=2.5,
        spells=(
            FakeSpell(
                spell_key="R", max_rank_duration_s=2.5,
                duration_post_tenacity_s=2.5,
            ),
        ),
        tenacity_mult=1.0,
    )


def _galio(_champion="Galio", mode="SR") -> FakeResult:
    """Galio W taunt (2.0s) + E knockup (0.75s) + R knockup (0.75s).
    Highest-duration spell pick should be W."""
    return FakeResult(
        champion="Galio", mode=mode,
        total_cc_seconds=3.5,
        spells=(
            FakeSpell(
                spell_key="W", max_rank_duration_s=2.0,
                duration_post_tenacity_s=2.0,
            ),
            FakeSpell(
                spell_key="E", max_rank_duration_s=0.75,
                duration_post_tenacity_s=0.75,
            ),
            FakeSpell(
                spell_key="R", max_rank_duration_s=0.75,
                duration_post_tenacity_s=0.75,
            ),
        ),
        tenacity_mult=1.0,
    )


def _vi_r_chosen(_champion="Vi", mode="SR") -> FakeResult:
    """Vi Q knockup 0.75 + R knockup 1.0 - R wins."""
    return FakeResult(
        champion="Vi", mode=mode,
        total_cc_seconds=1.75,
        spells=(
            FakeSpell(
                spell_key="Q", max_rank_duration_s=0.75,
                duration_post_tenacity_s=0.75,
            ),
            FakeSpell(
                spell_key="R", max_rank_duration_s=1.0,
                duration_post_tenacity_s=1.0,
            ),
        ),
        tenacity_mult=1.0,
    )


def _zed_aram(_champion="Zed", mode="ARAM") -> FakeResult:
    """Zed has no registered CC in the 16.10.1 seed; FakeResult here
    is only used in an ARAM tenacity-flow test to assert the consumer
    reads duration_post_tenacity_s (not max_rank_duration_s)."""
    return FakeResult(
        champion="Zed", mode=mode,
        total_cc_seconds=1.2,
        spells=(
            FakeSpell(
                spell_key="W", max_rank_duration_s=1.0,
                duration_post_tenacity_s=1.2,  # 1.20x tenacity lift
            ),
        ),
        tenacity_mult=1.20,
    )


def _make_dispatcher(table: dict[str, FakeResult]):
    """Build a stub function for compute_cc_pressure that dispatches
    by champion name; missing names return empty."""

    def _stub(champion: str, mode: str = "SR") -> FakeResult:
        if not champion:
            return _empty(champion or "", mode)
        return table.get(champion, _empty(champion, mode))

    return _stub


_PATCH_TARGET = "core.enemy_cc_threat_context.compute_cc_pressure"


class LineRendersTests(unittest.TestCase):
    def test_single_morgana_renders_root(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "SR")
        self.assertEqual(line, "Enemy CC threats: Morgana 3.0s root (Q)")

    def test_three_enemies_sorted_desc_by_total(self):
        table = {
            "Annie": _annie(),
            "Morgana": _morgana(),
            "Malzahar": _malzahar(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana", "Malzahar"], "SR"
            )
        # Morgana 3.0 > Malzahar 2.5 > Annie 1.5
        self.assertEqual(
            line,
            "Enemy CC threats: Morgana 3.0s root (Q), "
            "Malzahar 2.5s suppress (R), Annie 1.5s stun (R)",
        )

    def test_default_limit_is_three(self):
        table = {
            "Annie": _annie(),
            "Morgana": _morgana(),
            "Malzahar": _malzahar(),
            "Galio": _galio(),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana", "Malzahar", "Galio"], "SR"
            )
        # 3 chunks (separated by 2 commas)
        self.assertEqual(line.count(", "), 2)

    def test_aram_mode_supported(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana(mode="ARAM")})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "ARAM")
        self.assertIn("Morgana", line)

    def test_alpha_tiebreaker_on_equal_total(self):
        # Two champs with equal total - alpha order on champion name.
        table = {
            "Morgana": _morgana(),
            "Annie": FakeResult(
                champion="Annie", mode="SR", total_cc_seconds=3.0,
                spells=(FakeSpell(
                    spell_key="R", max_rank_duration_s=1.5,
                    duration_post_tenacity_s=1.5,
                ),),
                tenacity_mult=1.0,
            ),
        }
        with patch(_PATCH_TARGET, _make_dispatcher(table)):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana", "Annie"], "SR")
        # Alpha: Annie first on tied total.
        self.assertTrue(line.index("Annie") < line.index("Morgana"))


class ModeGateTests(unittest.TestCase):
    def test_blank_mode_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(enemy_cc_threat_line(["Morgana"], ""), "")

    def test_none_mode_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(enemy_cc_threat_line(["Morgana"], None), "")

    def test_valid_mode_empty_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(enemy_cc_threat_line([], "SR"), "")

    def test_valid_mode_none_enemies_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(enemy_cc_threat_line(None, "SR"), "")

    def test_valid_mode_all_unknown_enemies_returns_empty(self):
        # All-unknown -> compute_cc_pressure returns empty -> skipped.
        with patch(_PATCH_TARGET, _make_dispatcher({})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(
                enemy_cc_threat_line(["Aatrox", "Garen", "Vayne"], "SR"),
                "",
            )

    def test_single_registered_enemy_renders(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Annie": _annie()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Annie", "Aatrox", "Garen"], "SR")
        # Only Annie has CC -> 1 chunk.
        self.assertEqual(line, "Enemy CC threats: Annie 1.5s stun (R)")

    def test_tuple_input_accepted(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(("Morgana",), "SR")
        self.assertIn("Morgana", line)

    def test_skips_blank_and_none_entries(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Annie": _annie()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["", None, "Annie", None], "SR")
        self.assertEqual(line, "Enemy CC threats: Annie 1.5s stun (R)")

    def test_aram_kiwi_mode_accepted(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana(mode="KIWI")})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "KIWI")
        self.assertIn("Morgana", line)


class LimitTests(unittest.TestCase):
    def _table(self):
        return {
            "Annie": _annie(),
            "Morgana": _morgana(),
            "Malzahar": _malzahar(),
            "Galio": _galio(),
            "Vi": _vi_r_chosen(),
        }

    def test_limit_1_single_chunk(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana", "Malzahar", "Galio", "Vi"],
                "SR", limit=1,
            )
        # No comma separators.
        self.assertEqual(line.count(", "), 0)
        # Galio has highest total (3.5) in this fixture set; wins.
        self.assertIn("Galio", line)

    def test_limit_5_returns_up_to_5(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana", "Malzahar", "Galio", "Vi"],
                "SR", limit=5,
            )
        # 5 chunks - 4 commas.
        self.assertEqual(line.count(", "), 4)

    def test_limit_0_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana"], "SR", limit=0,
            )
        self.assertEqual(line, "")

    def test_limit_negative_returns_empty(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana"], "SR", limit=-2,
            )
        self.assertEqual(line, "")

    def test_limit_default_is_3(self):
        with patch(_PATCH_TARGET, _make_dispatcher(self._table())):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(
                ["Annie", "Morgana", "Malzahar", "Galio", "Vi"], "SR"
            )
        # 3 chunks, 2 commas.
        self.assertEqual(line.count(", "), 2)


class KindHintsTests(unittest.TestCase):
    def test_morgana_q_is_root(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Morgana", "Q"), "root")

    def test_annie_r_is_stun(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Annie", "R"), "stun")

    def test_lulu_w_is_polymorph(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Lulu", "W"), "polymorph")

    def test_malzahar_r_is_suppress(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Malzahar", "R"), "suppress")

    def test_fiddlesticks_q_is_fear(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Fiddlesticks", "Q"), "fear")

    def test_zoe_e_is_sleep(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Zoe", "E"), "sleep")

    def test_galio_w_is_taunt(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Galio", "W"), "taunt")

    def test_unknown_spell_falls_back_to_cc(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Aatrox", "Q"), "CC")
        self.assertEqual(_kind("MysteryChamp", "R"), "CC")
        self.assertEqual(_kind("", ""), "CC")

    def test_registry_size_is_53(self):
        # Mirror the 53-entry _PER_SPELL_CC_DURATIONS seed exactly.
        from core.enemy_cc_threat_context import _CC_KIND_HINTS
        self.assertEqual(len(_CC_KIND_HINTS), 53)

    def test_wave2_alistar_q_knockup(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Alistar", "Q"), "knockup")

    def test_wave2_gnar_r_knockback(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Gnar", "R"), "knockback")

    def test_wave2_skarner_r_suppress(self):
        from core.enemy_cc_threat_context import _kind
        self.assertEqual(_kind("Skarner", "R"), "suppress")


class TopSpellTests(unittest.TestCase):
    def test_galio_picks_w_over_e_and_r(self):
        # Galio: W=2.0 > E=0.75 == R=0.75 -> W wins.
        with patch(_PATCH_TARGET, _make_dispatcher({"Galio": _galio()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Galio"], "SR")
        self.assertIn("(W)", line)
        self.assertNotIn("(E)", line)
        self.assertNotIn("(R)", line)
        self.assertIn("taunt", line)

    def test_vi_picks_r_over_q(self):
        # Vi: Q=0.75 < R=1.0 -> R wins.
        with patch(_PATCH_TARGET, _make_dispatcher({"Vi": _vi_r_chosen()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Vi"], "SR")
        self.assertIn("(R)", line)
        self.assertNotIn("(Q)", line)
        # Vi R is knockup per the registry.
        self.assertIn("knockup", line)

    def test_single_spell_picked_when_only_one(self):
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana()})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "SR")
        self.assertIn("(Q)", line)

    def test_zero_duration_spells_skipped(self):
        # Champ with non-empty spells but all zero durations -> skip.
        zero = FakeResult(
            champion="Z", mode="SR", total_cc_seconds=0.0,
            spells=(
                FakeSpell(spell_key="Q", duration_post_tenacity_s=0.0),
            ),
            tenacity_mult=1.0,
        )
        with patch(_PATCH_TARGET, _make_dispatcher({"Z": zero})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            self.assertEqual(enemy_cc_threat_line(["Z"], "SR"), "")


class AramTenacityIntegrationTests(unittest.TestCase):
    """Consumer reads duration_post_tenacity_s - the engine seam
    composes ARAM tenacity per-spell. SR mode hands back identity
    (post == max); ARAM mode hands back the lifted value."""

    def test_sr_mode_reads_post_tenacity_identity(self):
        # SR Morgana: post == max == 3.0.
        with patch(_PATCH_TARGET, _make_dispatcher({"Morgana": _morgana(mode="SR")})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "SR")
        self.assertIn("3.0s", line)

    def test_aram_mode_reads_lifted_post_tenacity(self):
        # ARAM Zed: post=1.2 (1.20x lift from 1.0 base).
        with patch(_PATCH_TARGET, _make_dispatcher({"Zed": _zed_aram(mode="ARAM")})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Zed"], "ARAM")
        self.assertIn("1.2s", line)

    def test_consumer_uses_post_tenacity_field_not_max_rank(self):
        # Build a result where post != max; consumer MUST read post.
        diverged = FakeResult(
            champion="X", mode="ARAM", total_cc_seconds=2.5,
            spells=(
                FakeSpell(
                    spell_key="R", max_rank_duration_s=1.0,
                    duration_post_tenacity_s=2.5,
                ),
            ),
            tenacity_mult=2.5,
        )
        with patch(_PATCH_TARGET, _make_dispatcher({"X": diverged})):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["X"], "ARAM")
        # MUST read the lifted 2.5s (NOT 1.0s).
        self.assertIn("2.5s", line)
        self.assertNotIn("1.0s", line)


class CoachWireTests(unittest.TestCase):
    """4 active mode coaches all import + invoke enemy_cc_threat_line."""

    def test_aram_coach_imports_helper(self):
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "enemy_cc_threat_line"))

    def test_aram_user_template_has_placeholder(self):
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{enemy_cc_threats}", _USER_TMPL)

    def test_aram_user_template_format_with_field(self):
        from coaches.aram_coach import _USER_TMPL
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="", enemy_aram_tenacity="",
            enemy_cc_threats="Enemy CC threats: Morgana 3.0s root (Q)",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("Morgana", out)

    def test_arena_coach_imports_helper(self):
        import coaches.arena_coach as mod
        self.assertTrue(hasattr(mod, "enemy_cc_threat_line"))

    def test_arena_user_template_has_placeholder(self):
        from coaches.arena_coach import _USER_TEMPLATE
        self.assertIn("{enemy_cc_threats}", _USER_TEMPLATE)

    def test_arena_user_template_format_with_field(self):
        from coaches.arena_coach import _USER_TEMPLATE
        out = _USER_TEMPLATE.format(
            round="1", champion="Caitlyn", partner="Lux", hp_pct=100,
            gold=0, level=1, kda="0/0/0", items="none", rank="1",
            alive="4", next_opp="?", team_rankings="-", augments="none",
            my_abilities="none",
            enemy_cc_threats="Enemy CC threats: Annie 1.5s stun (R)",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", vision_context="",
        )
        self.assertIn("Annie", out)

    def test_brawl_coach_imports_helper(self):
        import coaches.brawl_coach as mod
        self.assertTrue(hasattr(mod, "enemy_cc_threat_line"))

    def test_brawl_coach_source_invokes_helper(self):
        # Brawl builds the user string by concat; verify the call site.
        src = (Path(__file__).resolve().parent.parent
               / "coaches" / "brawl_coach.py").read_text(encoding="utf-8")
        self.assertIn("enemy_cc_threat_line(", src)

    def test_sr_prompt_imports_helper(self):
        import coach_integration._sr_prompt as mod
        self.assertTrue(hasattr(mod, "enemy_cc_threat_line"))

    def test_sr_prompt_source_invokes_helper(self):
        src = (Path(__file__).resolve().parent.parent
               / "coach_integration" / "_sr_prompt.py").read_text(encoding="utf-8")
        self.assertIn("enemy_cc_threat_line(", src)


class AsciiHygieneTest(unittest.TestCase):
    def test_module_is_pure_ascii(self):
        p = (Path(__file__).resolve().parent.parent
             / "core" / "enemy_cc_threat_context.py")
        text = p.read_text(encoding="utf-8")
        # Build BAD glyph set via chr() so the test file is also clean.
        bad = {
            chr(0x2014): "em-dash",
            chr(0x2013): "en-dash",
            chr(0x201C): "smart-lq",
            chr(0x201D): "smart-rq",
            chr(0x2018): "smart-l",
            chr(0x2019): "smart-r",
        }
        for ch, label in bad.items():
            self.assertNotIn(ch, text, f"non-ASCII glyph {label!r} in module")
        # Belt+braces - no byte above 127.
        non_ascii = [b for b in text if ord(b) > 127]
        self.assertEqual(non_ascii, [], f"non-ASCII bytes: {non_ascii!r}")

    def test_format_string_pattern_matches_spec(self):
        # The spec pin: "Champion X.Xs kindword (KEY)" - regex pin.
        import re as _re
        with patch(
            _PATCH_TARGET,
            _make_dispatcher({"Morgana": _morgana()}),
        ):
            from core.enemy_cc_threat_context import enemy_cc_threat_line
            line = enemy_cc_threat_line(["Morgana"], "SR")
        m = _re.search(r"Morgana \d+\.\d+s [a-z]+ \([QWER]\)", line)
        self.assertIsNotNone(m, f"format mismatch: {line!r}")


if __name__ == "__main__":
    unittest.main()
