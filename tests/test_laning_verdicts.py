"""Tests for core.laning_verdicts - the deterministic laning verdict -> A/B
coach-choice adapter (Lane C, matchup-driven, no LLM).

The matchup() client call is monkeypatched so no live :8893 engine is required.
We patch ``core.laning_verdicts.matchup`` (the name the module binds at import)
so the adapter logic is exercised in isolation.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import core.laning_verdicts as lv
from core.coach_choices import CoachChoice


def _matchup_dict(verdict: str, net_swing: float = 0.0) -> dict:
    """A minimal MatchupResult-shaped dict (mirrors matchup.to_dict keys)."""
    return {
        "champ_a": "Caitlyn",
        "champ_b": "Ezreal",
        "level_a": 6,
        "level_b": 6,
        "verdict": verdict,
        "net_swing": net_swing,
        "pct_a_removed": 0.2,
        "pct_b_removed": 0.5,
    }


class VerdictToChoicesTests(unittest.TestCase):
    """verdict_to_choices maps each verdict to the correct A/B pair."""

    def test_all_in_labels_confidence_keys(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("all_in", 0.4))
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "All in now")
        self.assertEqual(out[0].confidence, "high")
        self.assertEqual(out[1].label, "Back off")
        self.assertEqual(out[1].confidence, "low")
        self.assertTrue(all(c.source_tag == "ds-matchup" for c in out))

    def test_trade_labels_confidence_keys(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("trade", 0.15))
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "Trade now")
        self.assertEqual(out[0].confidence, "mid")
        self.assertEqual(out[1].label, "Farm safe")
        self.assertEqual(out[1].confidence, "mid")
        self.assertTrue(all(c.source_tag == "ds-matchup" for c in out))

    def test_back_off_labels_confidence_keys(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("back_off", -0.3))
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "Back off")
        self.assertEqual(out[0].confidence, "high")
        self.assertEqual(out[1].label, "Trade anyway")
        self.assertEqual(out[1].confidence, "low")
        self.assertTrue(all(c.source_tag == "ds-matchup" for c in out))

    def test_even_labels_confidence_keys(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("even", 0.0))
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "Trade even")
        self.assertEqual(out[0].confidence, "mid")
        self.assertEqual(out[1].label, "Farm")
        self.assertEqual(out[1].confidence, "mid")
        self.assertTrue(all(c.source_tag == "ds-matchup" for c in out))

    def test_all_returned_are_coachchoice_instances(self) -> None:
        for v in ("all_in", "trade", "back_off", "even"):
            out = lv.verdict_to_choices(_matchup_dict(v))
            self.assertTrue(out)
            self.assertTrue(all(isinstance(c, CoachChoice) for c in out))

    def test_net_swing_surfaced_in_expected_outcome(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("all_in", 0.34))
        self.assertIn("+34% net HP", out[0].expected_outcome)

    def test_negative_net_swing_signed(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("back_off", -0.42))
        self.assertIn("-42% net HP", out[0].expected_outcome)

    def test_missing_net_swing_no_clause(self) -> None:
        d = _matchup_dict("trade")
        d.pop("net_swing", None)
        out = lv.verdict_to_choices(d)
        # No "% net HP" fragment when net_swing is absent / unparseable.
        self.assertNotIn("% net HP", out[0].expected_outcome)

    def test_non_dict_input_returns_empty(self) -> None:
        self.assertEqual(lv.verdict_to_choices(None), [])  # type: ignore[arg-type]
        self.assertEqual(lv.verdict_to_choices([]), [])  # type: ignore[arg-type]

    def test_verdict_less_dict_returns_empty(self) -> None:
        self.assertEqual(lv.verdict_to_choices({"net_swing": 0.5}), [])

    def test_build_next_item_appends_third_choice(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("trade", 0.2), build_next_item="Kraken Slayer")
        self.assertEqual(len(out), 3)
        self.assertEqual(out[2].key, "C")
        self.assertEqual(out[2].label, "Buy Kraken Slayer")
        self.assertEqual(out[2].confidence, "mid")
        self.assertEqual(out[2].source_tag, "ds-build")
        self.assertIsInstance(out[2], CoachChoice)

    def test_no_build_next_item_only_two_choices(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("trade", 0.2))
        self.assertEqual(len(out), 2)
        out2 = lv.verdict_to_choices(_matchup_dict("trade", 0.2), build_next_item="")
        self.assertEqual(len(out2), 2)


class LaningChoicesTests(unittest.TestCase):
    """laning_choices resolves state + calls the (mocked) matchup engine."""

    def setUp(self) -> None:
        # Default: matchup returns a trade verdict; tests override per-case.
        self._orig_matchup = lv.matchup
        # Isolate from the committed build_orders table so the optional 3rd
        # "Buy X" choice never bleeds in - these tests assert the 2-choice core.
        self._orig_dir = lv._DS_DATA_DIR
        self._tmp = tempfile.mkdtemp()
        lv._DS_DATA_DIR = Path(self._tmp)  # type: ignore[assignment]

    def tearDown(self) -> None:
        lv.matchup = self._orig_matchup  # type: ignore[assignment]
        lv._DS_DATA_DIR = self._orig_dir  # type: ignore[assignment]
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_mocked_matchup_returns_mapped_choices(self) -> None:
        captured: dict = {}

        def fake(champ_a, champ_b, **kw):  # noqa: ANN001, ANN003
            captured["a"] = champ_a
            captured["b"] = champ_b
            captured.update(kw)
            return _matchup_dict("all_in", 0.5)

        lv.matchup = fake  # type: ignore[assignment]
        out = lv.laning_choices(
            {"champion": "Caitlyn", "level": 6, "items": [], "enemy_comp": ["Ezreal", "Lux"]},
            mode="SR",
        )
        self.assertEqual([c.key for c in out], ["A", "B"])
        self.assertEqual(out[0].label, "All in now")
        self.assertTrue(all(isinstance(c, CoachChoice) for c in out))
        # my champ + enemy laner passed through to the engine
        self.assertEqual(captured["a"], "Caitlyn")
        self.assertEqual(captured["b"], "Ezreal")

    def test_matchup_none_returns_empty(self) -> None:
        lv.matchup = lambda *a, **k: None  # type: ignore[assignment]
        out = lv.laning_choices(
            {"champion": "Caitlyn", "level": 6, "items": [], "enemy_comp": ["Ezreal"]},
            mode="SR",
        )
        self.assertEqual(out, [])

    def test_empty_game_state_returns_empty(self) -> None:
        # Should not raise + not call matchup (no champ resolvable).
        lv.matchup = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call"))  # type: ignore[assignment]
        self.assertEqual(lv.laning_choices({}), [])

    def test_non_dict_game_state_returns_empty(self) -> None:
        self.assertEqual(lv.laning_choices(None), [])  # type: ignore[arg-type]

    def test_missing_my_champ_returns_empty(self) -> None:
        lv.matchup = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call"))  # type: ignore[assignment]
        out = lv.laning_choices({"level": 6, "enemy_comp": ["Ezreal"]})
        self.assertEqual(out, [])

    def test_missing_enemy_comp_returns_empty(self) -> None:
        lv.matchup = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not call"))  # type: ignore[assignment]
        out = lv.laning_choices({"champion": "Caitlyn", "level": 6})
        self.assertEqual(out, [])

    def test_my_champion_key_preferred_over_champion(self) -> None:
        captured: dict = {}

        def fake(champ_a, champ_b, **kw):  # noqa: ANN001, ANN003
            captured["a"] = champ_a
            return _matchup_dict("even")

        lv.matchup = fake  # type: ignore[assignment]
        lv.laning_choices(
            {"my_champion": "Jinx", "champion": "Caitlyn", "level": 4, "enemy_comp": ["Draven"]},
        )
        self.assertEqual(captured["a"], "Jinx")

    def test_level_defaults_to_one_when_absent(self) -> None:
        captured: dict = {}

        def fake(champ_a, champ_b, **kw):  # noqa: ANN001, ANN003
            captured.update(kw)
            return _matchup_dict("trade")

        lv.matchup = fake  # type: ignore[assignment]
        lv.laning_choices({"champion": "Caitlyn", "enemy_comp": ["Ezreal"]})
        self.assertEqual(captured["level_a"], 1)
        # v1: enemy level mirrors mine when unknown
        self.assertEqual(captured["level_b"], 1)


class LaningChoicesCvTests(unittest.TestCase):
    """RC2 P5.2: laning_choices(apply_cv=...) folds the CV laning override onto
    the served chips. apply_cv defaults False -> byte-identical."""

    def setUp(self) -> None:
        self._orig_matchup = lv.matchup
        self._orig_dir = lv._DS_DATA_DIR
        self._tmp = tempfile.mkdtemp()
        lv._DS_DATA_DIR = Path(self._tmp)  # type: ignore[assignment]

    def tearDown(self) -> None:
        lv.matchup = self._orig_matchup  # type: ignore[assignment]
        lv._DS_DATA_DIR = self._orig_dir  # type: ignore[assignment]
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_cv_false_is_byte_identical(self) -> None:
        lv.matchup = lambda *a, **k: _matchup_dict("all_in", 0.5)  # type: ignore[assignment]
        gs = {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]}
        base = lv.laning_choices(gs, mode="SR")
        cv_off = lv.laning_choices(gs, mode="SR", apply_cv=False)
        self.assertEqual([c.to_dict() for c in base],
                         [c.to_dict() for c in cv_off])

    def test_apply_cv_true_no_fog_unchanged(self) -> None:
        # apply_cv True but the fog yields no override -> identical to base.
        lv.matchup = lambda *a, **k: _matchup_dict("trade", 0.2)  # type: ignore[assignment]
        gs = {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]}
        base = lv.laning_choices(gs, mode="SR")
        out = lv.laning_choices(gs, mode="SR", apply_cv=True, hp_fraction=0.9,
                                vision_state={"enemies": {}})
        self.assertEqual([c.to_dict() for c in base],
                         [c.to_dict() for c in out])

    def test_apply_cv_enemy_dead_overrides_served(self) -> None:
        lv.matchup = lambda *a, **k: _matchup_dict("back_off", -0.3)  # type: ignore[assignment]
        gs = {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]}
        vs = {"enemies": {"Ezreal": {"champion": "Ezreal", "is_dead": True,
                                     "respawn_in_s": 14.0, "visible": False}}}
        out = lv.laning_choices(gs, mode="SR", apply_cv=True, hp_fraction=0.9,
                                vision_state=vs)
        self.assertEqual(out[0].label, "Shove + take plates/prio")
        self.assertEqual(out[0].source_tag, "cv-laning")

    def test_apply_cv_low_hp_overrides_aggressive_served(self) -> None:
        lv.matchup = lambda *a, **k: _matchup_dict("all_in", 0.5)  # type: ignore[assignment]
        gs = {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]}
        vs = {"enemies": {"Ezreal": {"champion": "Ezreal", "visible": True}}}
        out = lv.laning_choices(gs, mode="SR", apply_cv=True, hp_fraction=0.2,
                                vision_state=vs)
        self.assertEqual(out[0].label, "Disengage")
        self.assertEqual(out[0].source_tag, "cv-laning")


class VerdictTriggerTests(unittest.TestCase):
    """RC2 5.3 - the served matchup chips name the live CONDITION (trigger).

    verdict_to_choices stamps the passed trigger on every choice; laning_choices
    builds the lean "enemy, lvl N" trigger off the resolved laner + level."""

    def test_verdict_to_choices_default_trigger_empty(self) -> None:
        out = lv.verdict_to_choices(_matchup_dict("trade", 0.15))
        self.assertTrue(all(c.trigger == "" for c in out))

    def test_verdict_to_choices_stamps_trigger_on_all(self) -> None:
        out = lv.verdict_to_choices(
            _matchup_dict("all_in", 0.4), build_next_item="Kraken Slayer",
            trigger="Ezreal, lvl 6",
        )
        self.assertEqual([c.key for c in out], ["A", "B", "C"])
        # A/B/C all carry the same condition line.
        self.assertTrue(all(c.trigger == "Ezreal, lvl 6" for c in out))

    def test_laning_choices_builds_enemy_level_trigger(self) -> None:
        self._orig = lv.matchup
        self._orig_dir = lv._DS_DATA_DIR
        tmp = tempfile.mkdtemp()
        lv._DS_DATA_DIR = Path(tmp)  # type: ignore[assignment]
        try:
            lv.matchup = lambda *a, **k: _matchup_dict("trade", 0.2)  # type: ignore[assignment]
            gs = {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]}
            out = lv.laning_choices(gs, mode="SR")
            self.assertTrue(out)
            self.assertEqual(out[0].trigger, "Ezreal, lvl 6")
            self.assertEqual(out[1].trigger, "Ezreal, lvl 6")
        finally:
            lv.matchup = self._orig  # type: ignore[assignment]
            lv._DS_DATA_DIR = self._orig_dir  # type: ignore[assignment]
            shutil.rmtree(tmp, ignore_errors=True)


class EnemyLanerResolutionTests(unittest.TestCase):
    """_resolve_enemy_laner picks the right opponent per mode."""

    def test_sr_same_role_pick(self) -> None:
        gs = {
            "champion": "Caitlyn",
            "role": "BOTTOM",
            "enemy_comp": ["Malphite", "Ezreal", "Lux"],
            "enemy_roles": {"Malphite": "TOP", "Ezreal": "BOTTOM", "Lux": "UTILITY"},
        }
        self.assertEqual(lv._resolve_enemy_laner(gs, mode="SR"), "Ezreal")

    def test_sr_fallback_to_first_when_role_absent(self) -> None:
        gs = {"champion": "Caitlyn", "enemy_comp": ["Malphite", "Ezreal"]}
        self.assertEqual(lv._resolve_enemy_laner(gs, mode="SR"), "Malphite")

    def test_sr_fallback_when_no_enemy_roles_map(self) -> None:
        gs = {"champion": "Caitlyn", "role": "BOTTOM", "enemy_comp": ["Malphite", "Ezreal"]}
        self.assertEqual(lv._resolve_enemy_laner(gs, mode="SR"), "Malphite")

    def test_aram_takes_first_enemy(self) -> None:
        gs = {"champion": "Jinx", "enemy_comp": ["Brand", "Leona"]}
        self.assertEqual(lv._resolve_enemy_laner(gs, mode="ARAM"), "Brand")

    def test_empty_enemy_comp_returns_none(self) -> None:
        self.assertIsNone(lv._resolve_enemy_laner({"champion": "Jinx", "enemy_comp": []}, mode="SR"))
        self.assertIsNone(lv._resolve_enemy_laner({"champion": "Jinx"}, mode="SR"))


class BuildNextItemTests(unittest.TestCase):
    """_next_build_item against a tmp build_orders fixture (absent -> None)."""

    def _write_fixture(self, tmp: Path, mode: str = "sr") -> None:
        patch = "16.11.1"
        (tmp / "current.txt").write_text(patch, encoding="utf-8")
        pdir = tmp / patch
        pdir.mkdir(parents=True, exist_ok=True)
        doc = {
            "build_orders": {
                "Caitlyn": {
                    "ad_heavy": ["3031", "3094"],
                    "balanced": ["3031", "3094"],
                },
            },
            "mode": mode.upper(),
        }
        (pdir / f"build_orders_{mode}.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_present_file_yields_first_unowned(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_fixture(tmp)
            orig = lv._DS_DATA_DIR
            try:
                lv._DS_DATA_DIR = tmp  # type: ignore[assignment]
                # 3031 = Infinity Edge per items_index byId
                name = lv._next_build_item("Caitlyn", [], mode="SR")
                self.assertEqual(name, "Infinity Edge")
            finally:
                lv._DS_DATA_DIR = orig  # type: ignore[assignment]

    def test_present_file_skips_owned(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_fixture(tmp)
            orig = lv._DS_DATA_DIR
            try:
                lv._DS_DATA_DIR = tmp  # type: ignore[assignment]
                # Own Infinity Edge -> next is 3094 (Rapid Firecannon)
                name = lv._next_build_item("Caitlyn", ["Infinity Edge"], mode="SR")
                self.assertEqual(name, "Rapid Firecannon")
            finally:
                lv._DS_DATA_DIR = orig  # type: ignore[assignment]

    def test_absent_file_returns_none_no_error(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "current.txt").write_text("16.11.1", encoding="utf-8")
            (tmp / "16.11.1").mkdir(parents=True, exist_ok=True)
            orig = lv._DS_DATA_DIR
            try:
                lv._DS_DATA_DIR = tmp  # type: ignore[assignment]
                # No build_orders_sr.json present -> None, no raise.
                self.assertIsNone(lv._next_build_item("Caitlyn", [], mode="SR"))
            finally:
                lv._DS_DATA_DIR = orig  # type: ignore[assignment]

    def test_laning_choices_only_two_when_build_file_absent(self) -> None:
        import tempfile

        orig_matchup = lv.matchup
        lv.matchup = lambda *a, **k: _matchup_dict("trade", 0.2)  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "current.txt").write_text("16.11.1", encoding="utf-8")
            (tmp / "16.11.1").mkdir(parents=True, exist_ok=True)
            orig = lv._DS_DATA_DIR
            try:
                lv._DS_DATA_DIR = tmp  # type: ignore[assignment]
                out = lv.laning_choices(
                    {"champion": "Caitlyn", "level": 6, "enemy_comp": ["Ezreal"]},
                    mode="SR",
                )
                self.assertEqual(len(out), 2)  # no build choice, no error
            finally:
                lv._DS_DATA_DIR = orig  # type: ignore[assignment]
                lv.matchup = orig_matchup  # type: ignore[assignment]

    def test_laning_choices_three_when_build_file_present(self) -> None:
        import tempfile

        orig_matchup = lv.matchup
        lv.matchup = lambda *a, **k: _matchup_dict("trade", 0.2)  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_fixture(tmp)
            orig = lv._DS_DATA_DIR
            try:
                lv._DS_DATA_DIR = tmp  # type: ignore[assignment]
                out = lv.laning_choices(
                    {"champion": "Caitlyn", "level": 6, "items": [], "enemy_comp": ["Ezreal"]},
                    mode="SR",
                )
                self.assertEqual(len(out), 3)
                self.assertEqual(out[2].source_tag, "ds-build")
                self.assertEqual(out[2].label, "Buy Infinity Edge")
            finally:
                lv._DS_DATA_DIR = orig  # type: ignore[assignment]
                lv.matchup = orig_matchup  # type: ignore[assignment]


class ClientMatchupFnTests(unittest.TestCase):
    """The thin core.daemon_slayer_client.matchup wraps POST /v2/matchup."""

    def test_matchup_posts_expected_body(self) -> None:
        import core.daemon_slayer_client as dsc

        captured: dict = {}

        def fake_post(path, body, timeout=0.5):  # noqa: ANN001
            captured["path"] = path
            captured["body"] = body
            return {"verdict": "trade", "net_swing": 0.1}

        orig = dsc._post_json
        try:
            dsc._post_json = fake_post  # type: ignore[assignment]
            out = dsc.matchup(
                "Caitlyn", "Ezreal",
                level_a=6, level_b=5,
                item_ids_a=["3031"], item_ids_b=["3508"],
                mode="SR", hp_a_pct=0.9, hp_b_pct=0.8,
            )
            self.assertEqual(out, {"verdict": "trade", "net_swing": 0.1})
            self.assertEqual(captured["path"], "/v2/matchup")
            b = captured["body"]
            self.assertEqual(b["champ_a"], "Caitlyn")
            self.assertEqual(b["champ_b"], "Ezreal")
            self.assertEqual(b["level_a"], 6)
            self.assertEqual(b["level_b"], 5)
            self.assertEqual(b["item_ids_a"], ["3031"])
            self.assertEqual(b["item_ids_b"], ["3508"])
            self.assertEqual(b["mode"], "SR")
            self.assertEqual(b["hp_a_pct"], 0.9)
            self.assertEqual(b["hp_b_pct"], 0.8)
        finally:
            dsc._post_json = orig  # type: ignore[assignment]

    def test_matchup_returns_none_on_engine_down(self) -> None:
        import core.daemon_slayer_client as dsc

        orig = dsc._post_json
        try:
            dsc._post_json = lambda *a, **k: None  # type: ignore[assignment]
            self.assertIsNone(dsc.matchup("Caitlyn", "Ezreal"))
        finally:
            dsc._post_json = orig  # type: ignore[assignment]


class AsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        src = Path(lv.__file__).read_text(encoding="utf-8")
        non_ascii = [(i, ch) for i, ch in enumerate(src) if ord(ch) > 127]
        self.assertEqual(non_ascii, [], f"non-ASCII in laning_verdicts.py: {non_ascii[:5]}")


if __name__ == "__main__":
    unittest.main()
