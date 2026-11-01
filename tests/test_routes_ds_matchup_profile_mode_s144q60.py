"""RM-1330 (part) - /api/ds-matchup and /api/ds-profile refuse an unsupported mode.

Defect (measured 2026-11-01 on the lane base, real DataSnapshot, in process, no
:8860 call):
  * compute_matchup(Vayne, Lux, L11, side A items 3031 + 3085 + 3006, side B none)
    gave net_swing 0.1695 for both mode=SR and mode=ZZQ, and all 173 champions
    against Lux at L11 with no items matched too. /api/ds-matchup passes the
    caller's mode through and echoes it, so a mode the engine never applied read
    as if it had.
  * The eight /api/ds-profile scorers gave the same headlines for SR and ZZQ over
    all 173 champions, and the route echoed the label with ok=true.

Contract pinned here (the RM-1327 routes_ds_sweep discipline):
  * a mode outside SR / ARAM / ARENA / BRAWL is a 400 with a fixed text and the
    supported list, never the caller's value;
  * the engine is not called and nothing is cached for it;
  * a missing or blank champion still wins over a bad mode;
  * a supported mode in any case reaches the engine upper-cased;
  * a blank or absent mode still defaults to SR.

The engine is stubbed, so these tests pin the route contract, not the numbers.
Neither route needs a consumer fold today: each panel's render path fetches with
a literal SR. A caller that sends a live mode has to fold it first (see
_amDsComboMode). ConsumerPinTests is a tripwire for the plain edit only; its
docstring lists what it catches and what it cannot see.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from core import daemon_slayer_client
from dashboard import routes_ds_matchup as matchup
from dashboard import routes_ds_profile as profile

_SUPPORTED = ["SR", "ARAM", "ARENA", "BRAWL"]
_MARKER = "zzqmode"
_PANELS = pathlib.Path(__file__).resolve().parent.parent / "web" / "js" / "panels"


class _Harness:
    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.status = status
        self.body = body

    def parsed(self) -> dict:
        return json.loads(self.body.decode("utf-8"))


class _ModeContract:
    """The shared contract; each subclass names its route and its stub."""

    mod = None
    url = ""

    def _serve(self, h: _Harness) -> None:
        raise NotImplementedError

    def _do(self, query: str) -> _Harness:
        h = _Harness(f"{self.url}{query}")
        self._serve(h)
        return h

    def test_unknown_mode_is_400_with_fixed_text(self) -> None:
        h = self._do(f"&mode={_MARKER}")
        self.assertEqual(h.status, 400)
        body = h.parsed()
        self.assertIs(body["ok"], False)
        self.assertEqual(body["error"], "unsupported mode")
        self.assertEqual(body["supported"], _SUPPORTED)

    def test_unknown_mode_is_not_echoed(self) -> None:
        raw = self._do(f"&mode={_MARKER}").body.decode("utf-8")
        self.assertNotIn(_MARKER, raw.lower())

    def test_unknown_mode_never_reaches_the_engine(self) -> None:
        self._do(f"&mode={_MARKER}")
        self.assertEqual(self.calls, [])

    def test_unknown_mode_is_not_cached(self) -> None:
        self._do("&mode=URF")
        self.assertEqual(len(self.mod._CACHE), 0)

    def test_lcu_spellings_are_not_aliases(self) -> None:
        for raw in ("CLASSIC", "CHERRY", "KIWI", "TFT", "CLIENT"):
            with self.subTest(mode=raw):
                self.assertEqual(self._do(f"&mode={raw}").status, 400)
        self.assertEqual(self.calls, [])

    def test_supported_modes_reach_engine_uppercased(self) -> None:
        for raw in ("sr", "Aram", "ARENA", "brawl", " aram "):
            with self.subTest(mode=raw):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(f"&mode={raw.replace(' ', '%20')}")
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, [raw.strip().upper()])
                self.assertEqual(h.parsed()["mode"], raw.strip().upper())

    def test_blank_and_absent_mode_default_to_sr(self) -> None:
        for query in ("", "&mode=", "&mode=%20"):
            with self.subTest(query=query):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(query)
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, ["SR"])


class MatchupModeTests(_ModeContract, unittest.TestCase):
    mod = matchup
    url = "/api/ds-matchup?champ_a=Vayne&champ_b=Lux"

    def setUp(self) -> None:
        matchup._reset_caches()
        self.calls: list[str] = []
        self._orig = daemon_slayer_client.matchup

        def _fake(champ_a, champ_b, **kwargs):
            self.calls.append(kwargs["mode"])
            return {"verdict": "even", "net_swing": 0.0}

        daemon_slayer_client.matchup = _fake

    def tearDown(self) -> None:
        daemon_slayer_client.matchup = self._orig
        matchup._reset_caches()

    def _serve(self, h: _Harness) -> None:
        matchup._serve_ds_matchup(h)

    def test_missing_champion_still_wins_over_a_bad_mode(self) -> None:
        h = _Harness(f"/api/ds-matchup?champ_a=Vayne&mode={_MARKER}")
        matchup._serve_ds_matchup(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"],
                         "champ_a and champ_b params required")


class ProfileModeTests(_ModeContract, unittest.TestCase):
    mod = profile
    url = "/api/ds-profile?champion=Vayne"

    def setUp(self) -> None:
        profile._reset_caches()
        self.calls: list[str] = []
        self._orig = profile._compute

        def _fake(champion, mode):
            self.calls.append(mode)
            return {"ok": True, "champion": champion, "mode": mode, "axes": []}

        profile._compute = _fake

    def tearDown(self) -> None:
        profile._compute = self._orig
        profile._reset_caches()

    def _serve(self, h: _Harness) -> None:
        profile._serve_ds_profile(h)

    def test_missing_champion_still_wins_over_a_bad_mode(self) -> None:
        h = _Harness(f"/api/ds-profile?mode={_MARKER}")
        profile._serve_ds_profile(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "champion param required")


def _code_lines(path: pathlib.Path) -> str:
    """Panel source minus whole-line ``//`` comments. Not a JS parser."""
    text = path.read_text(encoding="utf-8")
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


class ConsumerPinTests(unittest.TestCase):
    """Text pins on panel source. They are a tripwire for the plain edit, not a
    proof of what a browser sends and not a JS parse.

    Red on: the ``const mode`` value changing, the literal call no longer naming
    ``mode``, a second literal call, or a panel module under web/js/panels (top
    level, ``*.js``) naming the other panel's fetch function or route.

    Blind to: a shadowed ``mode``, an alias or a split route string, a literal
    kept alive by a trailing or block comment, a rewrite inside the fetch
    function, and any caller outside that directory.

    Also red on some harmless edits (the call reflowed over two lines, single
    quotes, a second unrelated ``const mode``). Those fail closed: re-read the
    consumer, then update the pin.
    """

    _OWNERS = {
        "ds_matchup.js": ("fetchDsMatchup", "/api/ds-matchup"),
        "ds_profile.js": ("fetchDsProfile", "/api/ds-profile"),
    }

    def _assert_one_sr_fetch(self, panel: str, fetch_fn: str, call: str) -> None:
        code = _code_lines(_PANELS / panel)
        calls = re.findall(rf"(?<!function ){fetch_fn}\(([^)]*)\)", code)
        self.assertEqual([c.strip() for c in calls], [call])
        self.assertEqual(re.findall(r"\bconst mode\s*=\s*([^;]+);", code), ['"SR"'])

    def test_matchup_panel_fetches_with_literal_sr(self) -> None:
        self._assert_one_sr_fetch("ds_matchup.js", "fetchDsMatchup",
                                  "champA, champB, mode, _dsmOnLand")

    def test_profile_panel_fetches_with_literal_sr(self) -> None:
        self._assert_one_sr_fetch("ds_profile.js", "fetchDsProfile",
                                  "champ, mode, _dspOnLand")

    def test_no_other_panel_module_names_either_route(self) -> None:
        paths = sorted(_PANELS.glob("*.js"))
        # An empty glob would pass the loop below, so anchor it on the owners.
        self.assertLessEqual(set(self._OWNERS), {p.name for p in paths})
        for path in paths:
            code = _code_lines(path)
            for owner, names in self._OWNERS.items():
                if path.name == owner:
                    continue
                for name in names:
                    with self.subTest(panel=path.name, name=name):
                        self.assertNotIn(name, code)


if __name__ == "__main__":
    unittest.main()
