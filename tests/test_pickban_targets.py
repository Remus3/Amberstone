"""tests/test_pickban_targets.py - pick/ban targets generator + reader.

Covers W3C (Haiku-elim): the precomputed pick/ban targets DB from the matchup
engine. Generator tests stub ``compute_matchup`` over a tiny roster so they do
NOT depend on the full ~29k generated file; reader tests point at a small temp
JSON. ASCII hygiene on the 2 source files + ensure_ascii on the data path.
"""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.pickban_targets as reader  # noqa: E402

_GEN_MOD = "tools.daemon_slayer_pickban_targets_generate"


# ---------------------------------------------------------------------------
# Deterministic stub matchup engine for the generator tests.
#
# Explicit 4-champ swing matrix M[A][B] = swing(A, B) (A favored when > 0),
# designed to expose the global-strength bias the de-bias fixes:
#   - Bully    beats EVERYONE (high colmean) - it is nobody's SPECIFIC counter.
#   - Specific beats Victim by 0.5 but loses to Bully + Neutral (low colmean) -
#     Victim is its standout matchup, so it IS Victim's specific counter.
#   - Bully beats Victim HARDER in raw terms (0.7) than Specific does (0.5), so a
#     RAW net_swing ranking would put Bully first; the de-bias must flip that.
# ---------------------------------------------------------------------------
_MATRIX = {
    ("Bully", "Specific"): 0.6, ("Bully", "Victim"): 0.7, ("Bully", "Neutral"): 0.6,
    ("Specific", "Bully"): -0.6, ("Specific", "Victim"): 0.5, ("Specific", "Neutral"): -0.4,
    ("Victim", "Bully"): -0.7, ("Victim", "Specific"): -0.5, ("Victim", "Neutral"): -0.3,
    ("Neutral", "Bully"): -0.6, ("Neutral", "Specific"): 0.4, ("Neutral", "Victim"): 0.3,
}
_ROSTER = ["Bully", "Specific", "Victim", "Neutral"]


class _StubResult:
    def __init__(self, net_swing: float) -> None:
        self.net_swing = net_swing


def _stub_compute_matchup(snapshot, champ_a, champ_b, *, level_a, level_b, mode):
    return _StubResult(_MATRIX[(champ_a, champ_b)])


class _StubSnapshot:
    """Minimal stand-in for DataSnapshot.load() return."""


def _load_gen():
    """Import (or reload) the generator module fresh."""
    if _GEN_MOD in sys.modules:
        return importlib.reload(sys.modules[_GEN_MOD])
    return importlib.import_module(_GEN_MOD)


class DebiasRankingTests(unittest.TestCase):
    """The de-bias ranks a SPECIFIC counter above a global bully."""

    def setUp(self) -> None:
        self.gen = _load_gen()
        self.snap = _StubSnapshot()

    def test_specific_counter_outranks_global_bully(self) -> None:
        # Victim's counters: Bully beats Victim hardest in RAW swing (0.7 vs
        # Specific's 0.5), but Bully beats everyone so its rel is small; Specific
        # ESPECIALLY beats Victim so its rel is large -> Specific must rank #1.
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Victim", _ROSTER,
                                                top_k=8)
        counters = [r["champion"] for r in out["counters"]]
        self.assertEqual(counters[0], "Specific",
                         "de-bias must surface the specific counter over the bully")
        self.assertIn("Bully", counters)  # bully still a counter, just ranked lower
        self.assertLess(counters.index("Specific"), counters.index("Bully"))

    def test_counter_entries_carry_raw_and_rel(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Victim", _ROSTER,
                                                top_k=8)
        top = out["counters"][0]
        # net_swing stays Victim-vs-Specific (NEGATIVE, the reader contract).
        self.assertLess(top["net_swing"], 0.0)
        self.assertIn("rel", top)
        # Sorted strictly by descending rel.
        rels = [r["rel"] for r in out["counters"]]
        self.assertEqual(rels, sorted(rels, reverse=True))

    def test_counters_sign_filtered_to_actual_beats(self) -> None:
        # Bully loses to nobody, so Bully has an EMPTY counters list.
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Bully", _ROSTER,
                                                top_k=8)
        self.assertEqual(out["counters"], [])

    def test_good_against_sorted_by_rel(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Bully", _ROSTER,
                                                top_k=8)
        good = out["good_against"]
        # Bully beats all three; entries carry positive net_swing + a rel.
        self.assertEqual({r["champion"] for r in good},
                         {"Specific", "Victim", "Neutral"})
        self.assertTrue(all(r["net_swing"] > 0 for r in good))
        rels = [r["rel"] for r in good]
        self.assertEqual(rels, sorted(rels, reverse=True))

    def test_self_is_excluded(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Specific", _ROSTER,
                                                top_k=8)
        names = ({r["champion"] for r in out["counters"]}
                 | {r["champion"] for r in out["good_against"]})
        self.assertNotIn("Specific", names)

    def test_top_k_slices_each_list(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            out = self.gen.targets_for_champion(self.snap, "Victim", _ROSTER,
                                                top_k=1)
        self.assertEqual(len(out["counters"]), 1)
        self.assertEqual(out["counters"][0]["champion"], "Specific")

    def test_fail_soft_skips_none_pair(self) -> None:
        def flaky(snapshot, a, b, *, level_a, level_b, mode):
            if a == "Bully" and b == "Victim":
                return None  # engine "failed" for this directed pair
            return _stub_compute_matchup(snapshot, a, b, level_a=level_a,
                                         level_b=level_b, mode=mode)

        with mock.patch.object(self.gen, "compute_matchup", flaky):
            out = self.gen.targets_for_champion(self.snap, "Victim", _ROSTER,
                                                top_k=8)
        # Bully-vs-Victim cell is gone, but Victim-vs-Bully (-0.7) survives so
        # Bully is still counted as a counter via the reverse cell - the run
        # never raises (the point of fail-soft).
        self.assertIsInstance(out["counters"], list)


class GeneratorPayloadTests(unittest.TestCase):
    """generate_payload + atomic_write produce a valid JSON DB of the shape."""

    def setUp(self) -> None:
        self.gen = _load_gen()
        self.roster = list(_ROSTER)
        self.snap = _StubSnapshot()

    def test_payload_shape(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            payload = self.gen.generate_payload(self.snap, self.roster,
                                                "16.11.1", top_k=8,
                                                verbose=False)
        self.assertEqual(payload["patch"], "16.11.1")
        self.assertEqual(payload["mode"], "sr")
        self.assertEqual(payload["level"], 9)
        self.assertEqual(payload["top_k"], 8)
        self.assertEqual(payload["ranking"], "debiased_relative")
        self.assertEqual(set(payload["targets"]), set(self.roster))
        for champ, entry in payload["targets"].items():
            self.assertIn("counters", entry)
            self.assertIn("good_against", entry)

    def test_atomic_write_valid_json(self) -> None:
        import tempfile
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            payload = self.gen.generate_payload(self.snap, self.roster,
                                                "16.11.1", top_k=8,
                                                verbose=False)
        with tempfile.TemporaryDirectory() as td:
            out_path = Path(td) / "pickban_targets.json"
            self.gen.atomic_write(payload, out_path)
            text = out_path.read_text(encoding="utf-8")
            reloaded = json.loads(text)
            self.assertEqual(reloaded["patch"], "16.11.1")
            self.assertEqual(set(reloaded["targets"]), set(self.roster))
            # ensure_ascii: no raw non-ASCII bytes in the data file.
            self.assertTrue(text.isascii())

    def test_serialize_is_deterministic(self) -> None:
        with mock.patch.object(self.gen, "compute_matchup",
                               _stub_compute_matchup):
            payload = self.gen.generate_payload(self.snap, self.roster,
                                                "16.11.1", top_k=8,
                                                verbose=False)
        a = self.gen._serialize(payload)
        b = self.gen._serialize(payload)
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))


# ---------------------------------------------------------------------------
# Reader tests against a tiny temp DB (NOT the full generated file).
# ---------------------------------------------------------------------------
_TINY_DB = {
    "patch": "16.11.1",
    "mode": "sr",
    "level": 9,
    "top_k": 8,
    "targets": {
        "Lux": {
            "counters": [
                {"champion": "Zed", "net_swing": -0.5},
                {"champion": "Talon", "net_swing": -0.4},
                {"champion": "Kassadin", "net_swing": -0.2},
            ],
            "good_against": [
                {"champion": "Garen", "net_swing": 0.6},
                {"champion": "Malphite", "net_swing": 0.3},
            ],
        },
    },
}


def _fresh_reader(tmp_db_path: Path):
    """Reload the reader so its module-level cache + paths are pristine."""
    importlib.reload(reader)
    reader._CACHE.clear()
    return reader


class ReaderLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.patch_dir = Path(self._td.name) / "16.11.1"
        self.patch_dir.mkdir(parents=True)
        self.db_path = self.patch_dir / "pickban_targets.json"
        self.db_path.write_text(json.dumps(_TINY_DB), encoding="utf-8")
        # Point the reader's DS dir at our temp tree.
        self.rd = _fresh_reader(self.db_path)
        self._patcher = mock.patch.object(self.rd, "_DS_DIR",
                                          Path(self._td.name))
        self._patcher.start()
        self.rd._CACHE.clear()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._td.cleanup()
        importlib.reload(reader)

    def test_load_returns_payload(self) -> None:
        payload = self.rd.load_pickban_targets(mode="sr", patch="16.11.1")
        self.assertEqual(payload["patch"], "16.11.1")
        self.assertIn("Lux", payload["targets"])

    def test_counters_for_sorted_slice(self) -> None:
        out = self.rd.counters_for("Lux", patch="16.11.1", top_n=2)
        self.assertEqual([r["champion"] for r in out], ["Zed", "Talon"])
        # all net_swings negative (they beat Lux)
        self.assertTrue(all(r["net_swing"] < 0 for r in out))

    def test_good_against_sorted_slice(self) -> None:
        out = self.rd.good_against("Lux", patch="16.11.1", top_n=5)
        self.assertEqual([r["champion"] for r in out], ["Garen", "Malphite"])
        self.assertTrue(all(r["net_swing"] > 0 for r in out))

    def test_ban_suggestions_excludes_picked(self) -> None:
        # Zed already locked by enemy -> drop it; Talon + Kassadin remain.
        out = self.rd.ban_suggestions("Lux", enemy_comp=["Zed"],
                                      patch="16.11.1", top_n=3)
        names = [r["champion"] for r in out]
        self.assertNotIn("Zed", names)
        self.assertEqual(names, ["Talon", "Kassadin"])

    def test_ban_suggestions_caps_top_n(self) -> None:
        out = self.rd.ban_suggestions("Lux", enemy_comp=[],
                                      patch="16.11.1", top_n=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["champion"], "Zed")

    def test_unknown_champion_is_empty(self) -> None:
        self.assertEqual(self.rd.counters_for("Nobody", patch="16.11.1"), [])
        self.assertEqual(self.rd.good_against("Nobody", patch="16.11.1"), [])
        self.assertEqual(
            self.rd.ban_suggestions("Nobody", patch="16.11.1"), [])

    def test_blank_champion_is_empty(self) -> None:
        self.assertEqual(self.rd.counters_for("", patch="16.11.1"), [])

    def test_top_n_zero_is_empty(self) -> None:
        self.assertEqual(
            self.rd.counters_for("Lux", patch="16.11.1", top_n=0), [])


class ReaderFailSoftTests(unittest.TestCase):
    def test_missing_db_is_empty(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            rd = _fresh_reader(Path(td))
            with mock.patch.object(rd, "_DS_DIR", Path(td)):
                rd._CACHE.clear()
                # No 16.11.1/pickban_targets.json exists under td.
                self.assertEqual(
                    rd.load_pickban_targets(patch="16.11.1"), {})
                self.assertEqual(rd.counters_for("Lux", patch="16.11.1"), [])
                self.assertEqual(
                    rd.ban_suggestions("Lux", patch="16.11.1"), [])
        importlib.reload(reader)

    def test_malformed_db_is_empty(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            patch_dir = Path(td) / "16.11.1"
            patch_dir.mkdir(parents=True)
            (patch_dir / "pickban_targets.json").write_text(
                "{not valid json", encoding="utf-8")
            rd = _fresh_reader(patch_dir)
            with mock.patch.object(rd, "_DS_DIR", Path(td)):
                rd._CACHE.clear()
                self.assertEqual(
                    rd.load_pickban_targets(patch="16.11.1"), {})
        importlib.reload(reader)

    def test_non_dict_db_is_empty(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            patch_dir = Path(td) / "16.11.1"
            patch_dir.mkdir(parents=True)
            (patch_dir / "pickban_targets.json").write_text(
                "[1, 2, 3]", encoding="utf-8")
            rd = _fresh_reader(patch_dir)
            with mock.patch.object(rd, "_DS_DIR", Path(td)):
                rd._CACHE.clear()
                self.assertEqual(
                    rd.load_pickban_targets(patch="16.11.1"), {})
        importlib.reload(reader)


class AsciiHygieneTests(unittest.TestCase):
    """The 2 source files must be ASCII-only (no em/en-dash, no smart quotes)."""

    def test_reader_source_ascii(self) -> None:
        text = (_ROOT / "core" / "pickban_targets.py").read_text(
            encoding="utf-8")
        self.assertTrue(text.isascii(), "core/pickban_targets.py has non-ASCII")

    def test_generator_source_ascii(self) -> None:
        text = (_ROOT / "tools"
                / "daemon_slayer_pickban_targets_generate.py").read_text(
            encoding="utf-8")
        self.assertTrue(text.isascii(),
                        "generator source has non-ASCII bytes")


if __name__ == "__main__":
    unittest.main()
