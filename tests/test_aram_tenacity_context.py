"""Pin the ARAM tenacity coach-prompt consumer (closes the ENGINE 1.25.0
BACKLOG carry "Future EHP enemy-CC model for aram_tenacity_mult"; first
live consumer of ``effective_cc_duration`` from ``ehp.py``).

Coverage:

* ``LoadTenacityMapTests`` - the snapshot-backed loader returns exactly
  the 17 ARAM-modified champions at patch 16.10.1; champions with the
  default 1.0 multiplier are intentionally omitted.
* ``GetTenacityMultTests`` - mode-agnostic value lookup with None /
  unknown fallbacks.
* ``AramTenacityLineTests`` - the prompt-friendly renderer's mode gating,
  empty-output paths, and worked-example math.
* ``FailSoftTests`` - missing patch / missing champions.json / malformed
  JSON return ``{}`` not a crash.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from unittest import mock


class LoadTenacityMapTests(unittest.TestCase):
    """The module-level _TENACITY_MAP captures the live 16.10.1 set."""

    def test_map_size_is_seventeen(self) -> None:
        from core.aram_tenacity_context import _TENACITY_MAP
        self.assertEqual(len(_TENACITY_MAP), 17)

    def test_all_known_assassins_present(self) -> None:
        from core.aram_tenacity_context import _TENACITY_MAP
        expected = {
            "Akali", "Belveth", "Ekko", "Elise", "Evelynn", "Fizz",
            "Katarina", "Kayn", "Khazix", "Lucian", "Nunu", "Pyke",
            "Qiyana", "Quinn", "Rengar", "Talon", "Zed",
        }
        self.assertEqual(set(_TENACITY_MAP.keys()), expected)

    def test_default_tenacity_champ_absent(self) -> None:
        # Aatrox is the canonical "no ARAM tenacity modifier" champion.
        from core.aram_tenacity_context import _TENACITY_MAP
        self.assertNotIn("Aatrox", _TENACITY_MAP)
        self.assertNotIn("Garen", _TENACITY_MAP)

    def test_one_two_zero_mults(self) -> None:
        from core.aram_tenacity_context import _TENACITY_MAP
        # 15 champs at 1.20.
        expected_120 = {
            "Akali", "Belveth", "Ekko", "Evelynn", "Katarina", "Kayn",
            "Khazix", "Lucian", "Nunu", "Pyke", "Qiyana", "Quinn",
            "Rengar", "Talon", "Zed",
        }
        for c in expected_120:
            self.assertAlmostEqual(_TENACITY_MAP[c], 1.20, places=4, msg=c)

    def test_one_one_zero_mults(self) -> None:
        from core.aram_tenacity_context import _TENACITY_MAP
        for c in ("Elise", "Fizz"):
            self.assertAlmostEqual(_TENACITY_MAP[c], 1.10, places=4, msg=c)


class GetTenacityMultTests(unittest.TestCase):
    def test_known_champion_returns_value(self) -> None:
        from core.aram_tenacity_context import get_tenacity_mult
        self.assertAlmostEqual(get_tenacity_mult("Zed"), 1.20, places=4)
        self.assertAlmostEqual(get_tenacity_mult("Fizz"), 1.10, places=4)

    def test_unknown_champion_returns_one(self) -> None:
        from core.aram_tenacity_context import get_tenacity_mult
        self.assertEqual(get_tenacity_mult("Aatrox"), 1.0)
        self.assertEqual(get_tenacity_mult("NOPE"), 1.0)

    def test_none_returns_one(self) -> None:
        from core.aram_tenacity_context import get_tenacity_mult
        self.assertEqual(get_tenacity_mult(None), 1.0)

    def test_empty_string_returns_one(self) -> None:
        from core.aram_tenacity_context import get_tenacity_mult
        self.assertEqual(get_tenacity_mult(""), 1.0)


class AramTenacityLineTests(unittest.TestCase):
    def test_aram_modified_renders_line(self) -> None:
        from core.aram_tenacity_context import aram_tenacity_line
        line = aram_tenacity_line("Akali", "ARAM")
        self.assertIn("ARAM tenacity: 1.20x", line)
        self.assertIn("on you", line)
        self.assertIn("1.20s", line)

    def test_worked_example_uses_helper(self) -> None:
        # Fizz at 1.10 -> 1.10s worked.
        from core.aram_tenacity_context import aram_tenacity_line
        line = aram_tenacity_line("Fizz", "ARAM")
        self.assertIn("1.10x", line)
        self.assertIn("1.10s", line)

    def test_kiwi_mode_renders_line(self) -> None:
        # ARAM Mayhem uses queueId 2400 game_mode "KIWI" - same modifier.
        from core.aram_tenacity_context import aram_tenacity_line
        line = aram_tenacity_line("Zed", "KIWI")
        self.assertIn("1.20x", line)

    def test_sr_mode_renders_empty(self) -> None:
        from core.aram_tenacity_context import aram_tenacity_line
        self.assertEqual(aram_tenacity_line("Akali", "SR"), "")
        self.assertEqual(aram_tenacity_line("Zed", "CLASSIC"), "")

    def test_aram_default_champion_renders_empty(self) -> None:
        # Aatrox is in ARAM but has no tenacity modifier.
        from core.aram_tenacity_context import aram_tenacity_line
        self.assertEqual(aram_tenacity_line("Aatrox", "ARAM"), "")

    def test_unknown_champion_renders_empty(self) -> None:
        from core.aram_tenacity_context import aram_tenacity_line
        self.assertEqual(aram_tenacity_line("NOPE", "ARAM"), "")

    def test_none_inputs_render_empty(self) -> None:
        from core.aram_tenacity_context import aram_tenacity_line
        self.assertEqual(aram_tenacity_line(None, None), "")
        self.assertEqual(aram_tenacity_line(None, "ARAM"), "")
        self.assertEqual(aram_tenacity_line("Akali", None), "")

    def test_empty_strings_render_empty(self) -> None:
        from core.aram_tenacity_context import aram_tenacity_line
        self.assertEqual(aram_tenacity_line("", "ARAM"), "")
        self.assertEqual(aram_tenacity_line("Akali", ""), "")

    def test_line_is_single_line(self) -> None:
        # Coach user template injects this as one row; embedded newlines
        # would shift the format. Pin no-newline contract.
        from core.aram_tenacity_context import aram_tenacity_line
        line = aram_tenacity_line("Akali", "ARAM")
        self.assertNotIn("\n", line)

    def test_line_is_ascii(self) -> None:
        # Per CLAUDE.md no-em-dash hard rule.
        from core.aram_tenacity_context import aram_tenacity_line
        line = aram_tenacity_line("Akali", "ARAM")
        line.encode("ascii")  # raises if any non-ascii slipped in


class FailSoftTests(unittest.TestCase):
    """The loader must never raise; the consumer falls back to empty."""

    def test_missing_patch_file_returns_empty_map(self) -> None:
        from core import aram_tenacity_context as mod
        with mock.patch.object(
            mod, "_DATA_DIR", pathlib.Path("/nonexistent/path/no/such")
        ):
            self.assertEqual(mod._load_tenacity_map(), {})

    def test_missing_champions_json_returns_empty_map(self, tmp_path=None) -> None:
        from core import aram_tenacity_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            # NO 16.99.9/champions.json -> json read fails fail-soft.
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_tenacity_map(), {})

    def test_malformed_json_returns_empty_map(self) -> None:
        from core import aram_tenacity_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            (tmpdir / "16.99.9" / "champions.json").write_text(
                "{not json}", encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_tenacity_map(), {})

    def test_blank_patch_returns_empty_map(self) -> None:
        from core import aram_tenacity_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("", encoding="utf-8")
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_tenacity_map(), {})

    def test_unexpected_data_shape_returns_empty_map(self) -> None:
        from core import aram_tenacity_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            # data is a list not a dict.
            (tmpdir / "16.99.9" / "champions.json").write_text(
                json.dumps({"version": "16.99.9", "data": []}),
                encoding="utf-8",
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_tenacity_map(), {})

    def test_non_numeric_tenacity_skipped(self) -> None:
        from core import aram_tenacity_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            payload = {
                "version": "16.99.9",
                "data": {
                    "Bogus": {
                        "lolmath": {
                            "aram_modifiers": {"aramTenacity": "abc"}
                        }
                    },
                    "Real": {
                        "lolmath": {
                            "aram_modifiers": {"aramTenacity": 1.20}
                        }
                    },
                },
            }
            (tmpdir / "16.99.9" / "champions.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                m = mod._load_tenacity_map()
                self.assertEqual(m, {"Real": 1.20})


class EnemyAramTenacityLineTests(unittest.TestCase):
    def test_one_modified_enemy_renders_line(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Zed", "Garen", "Lux"], "ARAM")
        self.assertIn("Enemy ARAM tenacity", line)
        self.assertIn("Zed 1.20x", line)
        self.assertNotIn("Garen", line)
        self.assertNotIn("Lux", line)

    def test_multiple_modified_enemies_listed(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(
            ["Zed", "Talon", "Aatrox", "Garen", "Lux"], "ARAM"
        )
        self.assertIn("Zed 1.20x", line)
        self.assertIn("Talon 1.20x", line)
        self.assertNotIn("Aatrox", line)

    def test_descending_mult_then_alpha_sort(self) -> None:
        # Fizz (1.10) + Zed (1.20) -> Zed first, Fizz second.
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Fizz", "Zed"], "ARAM")
        # Confirm order by index of substrings in the rendered line.
        i_zed = line.index("Zed")
        i_fizz = line.index("Fizz")
        self.assertLess(i_zed, i_fizz)

    def test_equal_mult_alphabetical_tiebreaker(self) -> None:
        # Two 1.20x champs should sort alphabetical.
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Zed", "Akali"], "ARAM")
        self.assertLess(line.index("Akali"), line.index("Zed"))

    def test_kiwi_mode_renders_line(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Zed"], "KIWI")
        self.assertIn("Zed 1.20x", line)

    def test_sr_mode_renders_empty(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        self.assertEqual(
            enemy_aram_tenacity_line(["Zed", "Akali"], "SR"), ""
        )

    def test_no_modified_enemies_renders_empty(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        self.assertEqual(
            enemy_aram_tenacity_line(["Aatrox", "Garen", "Lux"], "ARAM"),
            "",
        )

    def test_empty_enemies_renders_empty(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        self.assertEqual(enemy_aram_tenacity_line([], "ARAM"), "")

    def test_none_enemies_renders_empty(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        self.assertEqual(enemy_aram_tenacity_line(None, "ARAM"), "")

    def test_none_mode_renders_empty(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        self.assertEqual(enemy_aram_tenacity_line(["Zed"], None), "")

    def test_skips_blank_and_none_entries(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(
            [None, "", "Zed", None, "Aatrox"], "ARAM"
        )
        self.assertIn("Zed 1.20x", line)
        # Does not include extra commas or trailing whitespace artifacts.
        self.assertNotIn(", ,", line)
        self.assertFalse(line.endswith(", "))

    def test_skips_unknown_champion_names(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["NOPE", "Zed"], "ARAM")
        self.assertIn("Zed 1.20x", line)
        self.assertNotIn("NOPE", line)

    def test_tuple_input_accepted(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(("Zed", "Talon"), "ARAM")
        self.assertIn("Zed 1.20x", line)
        self.assertIn("Talon 1.20x", line)

    def test_line_is_single_line(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Zed", "Talon", "Akali"], "ARAM")
        self.assertNotIn("\n", line)

    def test_line_is_ascii(self) -> None:
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        line = enemy_aram_tenacity_line(["Zed", "Akali"], "ARAM")
        line.encode("ascii")


class AramCoachWireTests(unittest.TestCase):
    """The ARAM coach imports the helpers and threads them into _USER_TMPL."""

    def test_user_template_has_aram_tenacity_field(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{aram_tenacity}", _USER_TMPL)

    def test_user_template_has_enemy_aram_tenacity_field(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{enemy_aram_tenacity}", _USER_TMPL)

    def test_coach_imports_helper(self) -> None:
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "aram_tenacity_line"))

    def test_coach_imports_enemy_helper(self) -> None:
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "enemy_aram_tenacity_line"))

    def test_user_template_format_supports_field(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="",
            enemy_aram_tenacity="",
            enemy_cc_threats="",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("ARAM", out)

    def test_user_template_renders_tenacity_when_provided(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        from core.aram_tenacity_context import aram_tenacity_line
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity=aram_tenacity_line("Zed", "ARAM"),
            enemy_aram_tenacity="",
            enemy_cc_threats="",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("ARAM tenacity: 1.20x", out)

    def test_user_template_renders_enemy_tenacity_when_provided(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        from core.aram_tenacity_context import enemy_aram_tenacity_line
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="",
            enemy_aram_tenacity=enemy_aram_tenacity_line(
                ["Zed", "Talon"], "ARAM"
            ),
            enemy_cc_threats="",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("Enemy ARAM tenacity", out)
        self.assertIn("Zed 1.20x", out)
        self.assertIn("Talon 1.20x", out)


if __name__ == "__main__":
    unittest.main()
