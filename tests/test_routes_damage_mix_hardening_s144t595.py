"""S144-T-595: GET /api/damage-mix validates its query at the trust boundary.

``dashboard/routes_damage_mix.py`` is reachable by any LAN / tailnet peer of
the :8888 listener (it is not a control endpoint). Measured before the fix:

- a non-integer ``level`` was echoed back raw in the 400 body
  (``level_invalid:<whatever was sent>``, unbounded) and an out-of-range one
  as ``level_out_of_range:<n>`` - the RM-1255 echo class;
- ``int()`` accepted ``1_1`` and non-ASCII digits (Arabic-Indic, fullwidth)
  as a level, and a blank ``level=`` was a 400 although a blank ``mode=``
  reads the default;
- ``champ_id`` went to ``resolve_champ_id`` unshaped: a fullwidth ``86``
  passed ``str.isdigit`` and resolved to Garen, and an unbounded or markup
  value cost a full snapshot load before it was refused;
- ``items`` had no count or shape check before the snapshot load and a walk
  over every token, so 7+ tokens or a non-numeric id were only refused deep
  in ``normalize_items``;
- ``mode`` was upper-cased with Unicode rules, so ``\\u017fr`` read as SR;
- every ``ValueError`` raised anywhere under ``compute_damage_mix`` - the
  DS engine's own included - was answered as a client 400
  ``invalid_request``, so an engine fault read as the caller's mistake;
- a non-finite engine number was serialised as a bare ``NaN`` token, which
  the browser's ``JSON.parse`` rejects, under status 200.

Each test drives the route entry point. Validation-only cases hand the route
a tiny fake snapshot; the happy path uses the real DS snapshot.
"""
from __future__ import annotations

import json
import math
import types
import unittest
from unittest.mock import patch

from core import damage_mix as core_dm
from dashboard import routes_damage_mix as rdm

_SENTINEL = "zqxSENTINELqxz"


class _Harness:
    def __init__(self, qs: str):
        self.path = f"/api/damage-mix?{qs}"
        self.status = None
        self.body = b""

    def _send(self, status, body, content_type):
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        # Strict parse: a bare NaN / Infinity token fails like JSON.parse.
        def _refuse(tok):
            raise ValueError(f"non-strict JSON token {tok}")
        return json.loads(self.body.decode("utf-8"), parse_constant=_refuse)


def _fake_snapshot():
    return types.SimpleNamespace(
        patch="0.0.0",
        champions={"Garen": {"key": "86"}, "Ahri": {"key": "103"}},
        items={"3071": {}, "3074": {}, "3047": {}, "1001": {},
               "3006": {}, "3153": {}, "6672": {}},
    )


def _fake_mix(**over):
    vals = {"physical_dps": 10.0, "magical_dps": 0.0, "true_dps": 0.0,
            "on_hit_dps": 0.0, "total_dps": 10.0,
            "mix": {"physical": 1.0, "magical": 0.0, "true": 0.0,
                    "on_hit": 0.0}}
    vals.update(over)
    return core_dm.DamageMix(champ_id="Garen", champ_key=86, items=("3071",),
                             level=11, mode="SR", **vals)


class _Base(unittest.TestCase):
    """Fake snapshot + recording compute; nothing heavy runs."""

    def setUp(self) -> None:
        self.loads = 0
        self.calls: list[tuple] = []

        def _snap():
            self.loads += 1
            return _fake_snapshot()

        def _compute(snapshot, champ, items, level=11, mode="SR", **kw):
            self.calls.append((champ, tuple(items), level, mode))
            return _fake_mix(), False

        p1 = patch.object(rdm, "_get_snapshot", _snap)
        p2 = patch.object(core_dm, "compute_damage_mix", _compute)
        p1.start()
        p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)

    def serve(self, qs: str) -> _Harness:
        h = _Harness(qs)
        rdm._serve_damage_mix(h)
        return h


class LevelTests(_Base):
    def test_non_integer_level_is_not_echoed(self) -> None:
        a = self.serve(f"champ_id=86&items=3071&level={_SENTINEL}")
        b = self.serve("champ_id=86&items=3071&level=other-junk")
        self.assertEqual(a.status, 400)
        self.assertNotIn(_SENTINEL.encode(), a.body)
        self.assertEqual(a.body, b.body)
        self.assertIn("level", a.parsed()["error"])

    def test_out_of_range_level_is_not_echoed(self) -> None:
        a = self.serve("champ_id=86&items=3071&level=987654")
        b = self.serve("champ_id=86&items=3071&level=19")
        c = self.serve("champ_id=86&items=3071&level=0")
        self.assertEqual((a.status, b.status, c.status), (400, 400, 400))
        self.assertNotIn(b"987654", a.body)
        self.assertEqual(a.body, b.body)
        self.assertEqual(a.body, c.body)

    def test_non_ascii_or_underscored_digits_refused(self) -> None:
        for raw in ("%D9%A1%D9%A1", "%EF%BC%91%EF%BC%91", "1_1", "%2B11",
                    "11.0", "-1", "011x"):
            with self.subTest(raw=raw):
                h = self.serve(f"champ_id=86&items=3071&level={raw}")
                self.assertEqual(h.status, 400, h.body)
        self.assertEqual(self.calls, [])

    def test_blank_level_reads_default(self) -> None:
        h = self.serve("champ_id=86&items=3071&level=")
        self.assertEqual(h.status, 200, h.body)
        self.assertEqual(self.calls[-1][2], 11)

    def test_valid_levels_pass_through(self) -> None:
        for lvl in (1, 9, 11, 18):
            h = self.serve(f"champ_id=86&items=3071&level={lvl}")
            self.assertEqual(h.status, 200, h.body)
            self.assertEqual(self.calls[-1][2], lvl)
        h = self.serve("champ_id=86&items=3071&level=07")
        self.assertEqual(h.status, 200, h.body)
        self.assertEqual(self.calls[-1][2], 7)


class ItemsTests(_Base):
    def test_more_than_six_items_refused_before_snapshot_load(self) -> None:
        items = ",".join(["3071"] * 7)
        h = self.serve(f"champ_id=86&items={items}")
        self.assertEqual(h.status, 400)
        self.assertEqual(self.loads, 0)
        self.assertEqual(self.calls, [])

    def test_huge_item_list_refused_before_snapshot_load(self) -> None:
        items = ",".join(["3071"] * 5000)
        h = self.serve(f"champ_id=86&items={items}")
        self.assertEqual(h.status, 400)
        self.assertEqual(self.loads, 0)

    def test_non_numeric_item_token_refused_without_echo(self) -> None:
        for raw in (f"3071,{_SENTINEL}", "%EF%BC%93%EF%BC%90%EF%BC%97%EF%BC%91",
                    "3071,123456789", "3071,-1", "3071,%2B3074"):
            with self.subTest(raw=raw):
                h = self.serve(f"champ_id=86&items={raw}")
                self.assertEqual(h.status, 400, h.body)
                self.assertNotIn(_SENTINEL.encode(), h.body)
        self.assertEqual(self.loads, 0)

    def test_six_items_with_blanks_and_padding_pass(self) -> None:
        h = self.serve("champ_id=86&items=3071,,%203074%20,3047,1001,3006,3153,")
        self.assertEqual(h.status, 200, h.body)
        self.assertEqual(self.calls[-1][1],
                         ("3071", "3074", "3047", "1001", "3006", "3153"))

    def test_unknown_item_is_a_400_without_echo(self) -> None:
        h = self.serve("champ_id=86&items=3071,9999")
        self.assertEqual(h.status, 400)
        self.assertNotIn(b"9999", h.body)
        self.assertEqual(self.calls, [])


class ChampTests(_Base):
    def test_fullwidth_digit_key_refused(self) -> None:
        h = self.serve("champ_id=%EF%BC%98%EF%BC%96&items=3071")
        self.assertEqual(h.status, 400, h.body)
        self.assertEqual(self.calls, [])

    def test_overlong_or_markup_champ_refused_before_snapshot_load(self) -> None:
        for raw in ("A" * 200, "Garen%3Cscript%3E", "Gar%20en", "12345",
                    "_Garen", "Garen%00"):
            with self.subTest(raw=raw[:20]):
                h = self.serve(f"champ_id={raw}&items=3071")
                self.assertEqual(h.status, 400, h.body)
                self.assertNotIn(b"script", h.body)
        self.assertEqual(self.loads, 0)

    def test_unknown_champ_is_a_400_without_echo(self) -> None:
        h = self.serve(f"champ_id={_SENTINEL}&items=3071")
        self.assertEqual(h.status, 400)
        self.assertNotIn(_SENTINEL.encode(), h.body)

    def test_key_and_id_both_resolve(self) -> None:
        for raw in ("86", "Garen", "%20Garen%20"):
            h = self.serve(f"champ_id={raw}&items=3071")
            self.assertEqual(h.status, 200, h.body)
            self.assertEqual(self.calls[-1][0], "Garen")


class ModeTests(_Base):
    def test_non_ascii_mode_refused(self) -> None:
        # U+017F LATIN SMALL LETTER LONG S upper-cases to "S".
        h = self.serve("champ_id=86&items=3071&mode=%C5%BFr")
        self.assertEqual(h.status, 400, h.body)
        self.assertEqual(self.calls, [])

    def test_supported_modes_any_case(self) -> None:
        for raw, want in (("sr", "SR"), ("Aram", "ARAM"), ("arena", "ARENA"),
                          ("BRAWL", "BRAWL"), ("", "SR")):
            h = self.serve(f"champ_id=86&items=3071&mode={raw}")
            self.assertEqual(h.status, 200, h.body)
            self.assertEqual(self.calls[-1][3], want)


class EngineFaultTests(unittest.TestCase):
    """The engine runs for real here (real compute, fake engine stub)."""

    def setUp(self) -> None:
        p = patch.object(rdm, "_get_snapshot", _fake_snapshot)
        p.start()
        self.addCleanup(p.stop)
        core_dm.clear_cache()
        self.addCleanup(core_dm.clear_cache)

    def test_engine_value_error_is_a_500_not_a_client_400(self) -> None:
        def _boom(*a, **kw):
            raise ValueError(f"math domain error {_SENTINEL}")

        with patch.object(core_dm, "compute_ability_dps", _boom), \
                self.assertLogs("rc.web_dashboard", level="WARNING"):
            h = _Harness("champ_id=86&items=3071")
            rdm._serve_damage_mix(h)
        self.assertEqual(h.status, 500, h.body)
        self.assertNotIn(_SENTINEL.encode(), h.body)
        self.assertEqual(h.parsed()["ok"], False)

    def test_non_finite_result_is_a_500_with_strict_json(self) -> None:
        def _nan(*a, **kw):
            return _fake_mix(physical_dps=math.nan, total_dps=math.nan,
                             mix={"physical": math.nan, "magical": 0.0,
                                  "true": 0.0, "on_hit": 0.0}), False

        with patch.object(core_dm, "compute_damage_mix", _nan), \
                self.assertLogs("rc.web_dashboard", level="WARNING"):
            h = _Harness("champ_id=86&items=3071")
            rdm._serve_damage_mix(h)
        self.assertEqual(h.status, 500, h.body)
        self.assertEqual(h.parsed()["ok"], False)


class RealSnapshotTests(unittest.TestCase):
    """Characterization on the real DS snapshot (no patching)."""

    def setUp(self) -> None:
        core_dm.clear_cache()
        self.addCleanup(core_dm.clear_cache)

    def test_key_and_id_give_the_same_mix(self) -> None:
        a = _Harness("champ_id=86&items=3071,3047&level=11&mode=SR")
        b = _Harness("champ_id=Garen&items=3071,3047&level=11&mode=sr")
        rdm._serve_damage_mix(a)
        rdm._serve_damage_mix(b)
        self.assertEqual((a.status, b.status), (200, 200), a.body)
        pa, pb = a.parsed(), b.parsed()
        self.assertTrue(pa["ok"])
        self.assertEqual(pa["champ_id"], "Garen")
        self.assertEqual(pa["champ_key"], 86)
        self.assertEqual(pa["items"], ["3071", "3047"])
        self.assertEqual(set(pa["mix"]), {"physical", "magical", "true",
                                          "on_hit"})
        self.assertEqual(pa["cache_key"], "Garen:3071,3047")
        self.assertFalse(pa["cached"])
        self.assertTrue(pb["cached"])
        pa.pop("cached")
        pb.pop("cached")
        self.assertEqual(pa, pb)


if __name__ == "__main__":
    unittest.main()
