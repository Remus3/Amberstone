"""Pin the ARAM damage-balance coach-prompt consumer (BACKLOG F6).

Mirrors the SHIPPED ``core/aram_tenacity_context.py`` pattern: a snapshot-
backed loader builds a self-only {champion: (dealt, taken)} multiplier map
from the patch ``champions.json`` ``aram_modifiers`` block, and a render-
side ``aram_balance_line`` returns one prompt-friendly row that the ARAM
coach interpolates into its user template (empty in the non-ARAM /
neutral / unknown-champion case so the prompt size is unchanged).

Coverage:

* ``LoadBalanceMapTests`` - the loader captures the live 16.12.1 non-
  neutral set (>=120 champs); neutral (1.0, 1.0) champs are omitted.
* ``GetBalanceMultsTests`` - mode-agnostic value lookup with None /
  unknown / empty fallbacks to (1.0, 1.0).
* ``AramBalanceLineTests`` - the renderer's mode gating, empty-output
  paths, and exact one-line strings.
* ``FailSoftTests`` - missing patch / missing champions.json / malformed
  JSON / blank patch / list-shaped data return ``{}`` not a crash, plus
  the PER-FIELD fallback (a bad value on ONE field must not drop the
  whole champ).
* ``AramCoachWireTests`` - the coach imports the helper and threads the
  ``{aram_balance}`` field through ``_USER_TMPL``.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from unittest import mock


class LoadBalanceMapTests(unittest.TestCase):
    """The module-level _BALANCE_MAP captures the live 16.12.1 set."""

    def test_neutral_champ_absent(self) -> None:
        from core.aram_balance_context import _BALANCE_MAP
        self.assertNotIn("Ahri", _BALANCE_MAP)

    def test_aatrox_dealt_only(self) -> None:
        from core.aram_balance_context import _BALANCE_MAP
        dealt, taken = _BALANCE_MAP["Aatrox"]
        self.assertAlmostEqual(dealt, 1.05, places=4)
        self.assertAlmostEqual(taken, 1.0, places=4)

    def test_corki_taken_only(self) -> None:
        from core.aram_balance_context import _BALANCE_MAP
        dealt, taken = _BALANCE_MAP["Corki"]
        self.assertAlmostEqual(dealt, 1.0, places=4)
        self.assertAlmostEqual(taken, 0.9, places=4)

    def test_akshan_both(self) -> None:
        from core.aram_balance_context import _BALANCE_MAP
        dealt, taken = _BALANCE_MAP["Akshan"]
        self.assertAlmostEqual(dealt, 1.05, places=4)
        self.assertAlmostEqual(taken, 0.95, places=4)

    def test_bard_both(self) -> None:
        from core.aram_balance_context import _BALANCE_MAP
        dealt, taken = _BALANCE_MAP["Bard"]
        self.assertAlmostEqual(dealt, 1.15, places=4)
        self.assertAlmostEqual(taken, 0.85, places=4)

    def test_map_size_lower_bound(self) -> None:
        # 126 non-neutral champs at 16.12.1; pin a stable lower bound.
        from core.aram_balance_context import _BALANCE_MAP
        self.assertGreaterEqual(len(_BALANCE_MAP), 120)


class GetBalanceMultsTests(unittest.TestCase):
    def test_known_champion_returns_pair(self) -> None:
        from core.aram_balance_context import get_balance_mults
        dealt, taken = get_balance_mults("Akshan")
        self.assertAlmostEqual(dealt, 1.05, places=4)
        self.assertAlmostEqual(taken, 0.95, places=4)

    def test_unknown_champion_returns_neutral(self) -> None:
        from core.aram_balance_context import get_balance_mults
        self.assertEqual(get_balance_mults("NOPE"), (1.0, 1.0))

    def test_none_returns_neutral(self) -> None:
        from core.aram_balance_context import get_balance_mults
        self.assertEqual(get_balance_mults(None), (1.0, 1.0))

    def test_empty_string_returns_neutral(self) -> None:
        from core.aram_balance_context import get_balance_mults
        self.assertEqual(get_balance_mults(""), (1.0, 1.0))


class AramBalanceLineTests(unittest.TestCase):
    def test_dealt_only_exact(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Aatrox", "ARAM")
        self.assertEqual(line, "ARAM balance: you deal +5% damage")
        self.assertNotIn("take", line)

    def test_taken_only_exact(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Corki", "ARAM")
        self.assertEqual(line, "ARAM balance: you take -10% damage")
        self.assertNotIn("deal", line)

    def test_both_exact(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Akshan", "ARAM")
        self.assertEqual(line, "ARAM balance: you deal +5%, take -5% damage")

    def test_bard_contains_both_clauses(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Bard", "ARAM")
        self.assertIn("deal +15%", line)
        self.assertIn("take -15%", line)

    def test_kiwi_mode_renders_line(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Akshan", "KIWI")
        self.assertIn("ARAM balance:", line)

    def test_sr_mode_renders_empty(self) -> None:
        from core.aram_balance_context import aram_balance_line
        self.assertEqual(aram_balance_line("Akshan", "SR"), "")
        self.assertEqual(aram_balance_line("Bard", "CLASSIC"), "")

    def test_neutral_champion_renders_empty(self) -> None:
        from core.aram_balance_context import aram_balance_line
        self.assertEqual(aram_balance_line("Ahri", "ARAM"), "")

    def test_unknown_champion_renders_empty(self) -> None:
        from core.aram_balance_context import aram_balance_line
        self.assertEqual(aram_balance_line("NOPE", "ARAM"), "")

    def test_none_inputs_render_empty(self) -> None:
        from core.aram_balance_context import aram_balance_line
        self.assertEqual(aram_balance_line(None, None), "")
        self.assertEqual(aram_balance_line(None, "ARAM"), "")
        self.assertEqual(aram_balance_line("Akshan", None), "")

    def test_empty_strings_render_empty(self) -> None:
        from core.aram_balance_context import aram_balance_line
        self.assertEqual(aram_balance_line("", "ARAM"), "")
        self.assertEqual(aram_balance_line("Akshan", ""), "")

    def test_line_contains_literal_plus(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Bard", "ARAM")
        self.assertIn("+", line)

    def test_line_is_single_line(self) -> None:
        from core.aram_balance_context import aram_balance_line
        line = aram_balance_line("Bard", "ARAM")
        self.assertNotIn("\n", line)

    def test_line_is_ascii(self) -> None:
        from core.aram_balance_context import aram_balance_line
        aram_balance_line("Bard", "ARAM").encode("ascii")


class FailSoftTests(unittest.TestCase):
    """The loader must never raise; the consumer falls back to empty."""

    def test_missing_patch_file_returns_empty_map(self) -> None:
        from core import aram_balance_context as mod
        with mock.patch.object(
            mod, "_DATA_DIR", pathlib.Path("/nonexistent/path/no/such")
        ):
            self.assertEqual(mod._load_balance_map(), {})

    def test_missing_champions_json_returns_empty_map(self) -> None:
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            # NO 16.99.9/champions.json -> json read fails fail-soft.
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_balance_map(), {})

    def test_malformed_json_returns_empty_map(self) -> None:
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            (tmpdir / "16.99.9" / "champions.json").write_text(
                "{not json}", encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_balance_map(), {})

    def test_blank_patch_returns_empty_map(self) -> None:
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("", encoding="utf-8")
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertEqual(mod._load_balance_map(), {})

    def test_unexpected_data_shape_returns_empty_map(self) -> None:
        from core import aram_balance_context as mod
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
                self.assertEqual(mod._load_balance_map(), {})

    def test_per_field_fallback_keeps_champ(self) -> None:
        # aramDamageDealt is junk but aramDamageTaken=0.9 is good: the
        # champ must survive with dealt falling back to 1.0 for THAT
        # field only (diverges from tenacity's whole-champ continue).
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            payload = {
                "version": "16.99.9",
                "data": {
                    "OneBad": {
                        "lolmath": {
                            "aram_modifiers": {
                                "aramDamageDealt": "abc",
                                "aramDamageTaken": 0.9,
                            }
                        }
                    },
                },
            }
            (tmpdir / "16.99.9" / "champions.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                m = mod._load_balance_map()
                self.assertIn("OneBad", m)
                dealt, taken = m["OneBad"]
                self.assertAlmostEqual(dealt, 1.0, places=4)
                self.assertAlmostEqual(taken, 0.9, places=4)

    def test_both_fields_bad_omitted(self) -> None:
        # When BOTH fields fall back to 1.0 the champ is neutral and
        # therefore OMITTED from the map.
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            payload = {
                "version": "16.99.9",
                "data": {
                    "BothBad": {
                        "lolmath": {
                            "aram_modifiers": {
                                "aramDamageDealt": "abc",
                                "aramDamageTaken": None,
                            }
                        }
                    },
                },
            }
            (tmpdir / "16.99.9" / "champions.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                self.assertNotIn("BothBad", mod._load_balance_map())

    def test_missing_aram_modifiers_key_omitted(self) -> None:
        from core import aram_balance_context as mod
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "current.txt").write_text("16.99.9", encoding="utf-8")
            (tmpdir / "16.99.9").mkdir()
            payload = {
                "version": "16.99.9",
                "data": {
                    "NoMods": {"lolmath": {}},
                    "Real": {
                        "lolmath": {
                            "aram_modifiers": {"aramDamageTaken": 0.9}
                        }
                    },
                },
            }
            (tmpdir / "16.99.9" / "champions.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            with mock.patch.object(mod, "_DATA_DIR", tmpdir):
                m = mod._load_balance_map()
                self.assertNotIn("NoMods", m)
                self.assertIn("Real", m)


class AramCoachWireTests(unittest.TestCase):
    """The ARAM coach imports the helper and threads it into _USER_TMPL."""

    def test_user_template_has_aram_balance_field(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        self.assertIn("{aram_balance}", _USER_TMPL)

    def test_coach_imports_helper(self) -> None:
        import coaches.aram_coach as mod
        self.assertTrue(hasattr(mod, "aram_balance_line"))

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
            aram_balance="",
            enemy_cc_threats="",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("ARAM", out)

    def test_user_template_renders_balance_when_provided(self) -> None:
        from coaches.aram_coach import _USER_TMPL
        from core.aram_balance_context import aram_balance_line
        out = _USER_TMPL.format(
            game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0,
            lv=1, kda="0/0/0", items="none", allies="-", enemies="-",
            enemy_items="-", matchup_ctx="-", dead="-", alive="-",
            dead_resp="-", my_t=100, en_t=100, augs="-", packs="-",
            wave_pct=50, my_abilities="-", my_runes="-", enemy_runes="-",
            aram_tenacity="",
            enemy_aram_tenacity="",
            aram_balance=aram_balance_line("Bard", "ARAM"),
            enemy_cc_threats="",
            cc_blended_ehp_impact="",
            cc_conditional_impact="",
            ds_picks="-", ds_label="-", event_line="-",
        )
        self.assertIn("ARAM balance:", out)
        self.assertIn("deal +15%", out)


if __name__ == "__main__":
    unittest.main()
