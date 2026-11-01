"""RM-1330 (part) - /api/ds-relscore and /api/ds-skill-order refuse an unsupported mode.

Defect (measured 2026-11-01 on the lane base, real DataSnapshot, in process):
  * /api/ds-relscore: rank._is_legal_in_mode allows every item for a mode missing
    from MODE_MAP_ID. ZZQ, CLASSIC, URF, KIWI, CHERRY and TFT each differed from SR
    on all 173 champions (L11, no items) and answered ok=true under the caller's
    label. The resists did not explain it for most of them: compute_enemy_stats at
    L11 gave ZZQ, CLASSIC, URF, KIWI and TFT the SR values (95 armor / 63 MR), and
    CHERRY the ARENA values (128 / 96).
    Example: Caitlyn's top row under ZZQ was Ultra Hydra, item 226668, which is
    not legal on map 11; under SR it was Runaan's Hurricane, item 3085.
  * /api/ds-skill-order: _compute uses mode only as a label, so Aatrox under ZZQ
    equalled SR except for the echoed label, with ok=true.

Contract pinned here (the RM-1327 routes_ds_sweep discipline):
  * a mode outside SR / ARAM / ARENA / BRAWL is a 400 with a fixed text and the
    supported list, never the caller's value;
  * _compute is not called and nothing is cached for it;
  * a missing or blank champion still wins over a bad mode;
  * a supported mode in any case reaches _compute upper-cased;
  * a blank or absent mode still defaults to SR.

_compute is stubbed, so these tests pin the route contract, not the numbers.
Neither route needs a consumer fold today; ConsumerPinTests says what it can and
cannot show about that.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from dashboard import routes_ds_relscore as relscore
from dashboard import routes_ds_skill_order as skill_order

_SUPPORTED = ["SR", "ARAM", "ARENA", "BRAWL"]
_MARKER = "zzqmode"
_WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
_PANELS = _WEB / "js" / "panels"


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

    def _echoed_mode(self, body: dict) -> str:
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

    def test_unknown_mode_never_reaches_compute(self) -> None:
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

    def test_supported_modes_reach_compute_uppercased(self) -> None:
        for raw in ("sr", "Aram", "ARENA", "brawl", " aram "):
            with self.subTest(mode=raw):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(f"&mode={raw.replace(' ', '%20')}")
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, [raw.strip().upper()])
                self.assertEqual(self._echoed_mode(h.parsed()),
                                 raw.strip().upper())

    def test_blank_and_absent_mode_default_to_sr(self) -> None:
        for query in ("", "&mode=", "&mode=%20"):
            with self.subTest(query=query):
                self.mod._reset_caches()
                self.calls.clear()
                h = self._do(query)
                self.assertEqual(h.status, 200)
                self.assertEqual(self.calls, ["SR"])


class RelscoreModeTests(_ModeContract, unittest.TestCase):
    mod = relscore
    url = "/api/ds-relscore?champion=Caitlyn"

    def setUp(self) -> None:
        relscore._reset_caches()
        self.calls: list[str] = []
        self._orig = relscore._compute

        def _fake(champion, mode, items, level):
            self.calls.append(mode)
            return {"ok": True, "champion": champion,
                    "target": {"mode": mode}, "rows": [], "count": 0}

        relscore._compute = _fake

    def tearDown(self) -> None:
        relscore._compute = self._orig
        relscore._reset_caches()

    def _serve(self, h: _Harness) -> None:
        relscore._serve_ds_relscore(h)

    def _echoed_mode(self, body: dict) -> str:
        return body["target"]["mode"]

    def test_missing_champion_still_wins_over_a_bad_mode(self) -> None:
        h = _Harness(f"/api/ds-relscore?mode={_MARKER}")
        relscore._serve_ds_relscore(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "champion param required")


class SkillOrderModeTests(_ModeContract, unittest.TestCase):
    mod = skill_order
    url = "/api/ds-skill-order?champion=Aatrox"

    def setUp(self) -> None:
        skill_order._reset_caches()
        self.calls: list[str] = []
        self._orig = skill_order._compute

        def _fake(champion, mode):
            self.calls.append(mode)
            return {"ok": True, "champion": champion, "mode": mode,
                    "skill_order": []}

        skill_order._compute = _fake

    def tearDown(self) -> None:
        skill_order._compute = self._orig
        skill_order._reset_caches()

    def _serve(self, h: _Harness) -> None:
        skill_order._serve_ds_skill_order(h)

    def _echoed_mode(self, body: dict) -> str:
        return body["mode"]

    def test_missing_champion_still_wins_over_a_bad_mode(self) -> None:
        h = _Harness(f"/api/ds-skill-order?mode={_MARKER}")
        skill_order._serve_ds_skill_order(h)
        self.assertEqual(h.status, 400)
        self.assertEqual(h.parsed()["error"], "champion param required")


def _code_lines(path: pathlib.Path) -> str:
    """JS source minus whole-line ``//`` comments. Not a JS parser."""
    text = path.read_text(encoding="utf-8")
    return re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)


class ConsumerPinTests(unittest.TestCase):
    """Text pins on JS source: a tripwire for the plain edit, not a JS parse and
    not a proof of what a browser sends. The lists name the edits that were tried;
    an edit in no list is unmeasured, not covered.

    Red on, in the plain one-line form: a value in the _DSR_MODE_MAP literal that
    is not a double-quoted supported name; the map name used anywhere but its
    declaration and its one lookup; the map fallback changing from "SR"; either
    panel's ``const mode`` value changing, or a second ``const mode``; any change
    to either call's arguments other than whitespace or a whole-line comment, or
    a second call in the same spelling; a ``*.js`` file elsewhere under web/
    naming the route (with or without its leading slash) or the fetch function
    outside a whole-line comment.

    Blind to: a ``let``, ``var`` or parameter named ``mode`` shadowing the
    constant, or a ``const`` that declares it another way; a spread or a shorthand
    key inside the map literal, or a map value continued on the next line; an early
    return inside _modeForQueue; an alias inside the owner file, or a split route
    string; a second call spelled differently (a space before the paren, ``.call``,
    ``?.(``) beside the literal one; a trailing or block comment keeping a literal
    alive while other code carries the real value; what ``cs.queue_id`` holds; a
    rewrite inside the fetch function; a file elsewhere that shares an owner's file
    name; ``.mjs`` or ``.ts`` files, inline script in HTML, and any caller outside
    web/.

    Also red on some harmless edits (a trailing comma in a call, single quotes on
    a ``const mode`` or map value, a lowercase map value the route would
    upper-case, a trailing comment holding a ``:`` inside the map literal). Those
    fail closed: re-read the consumer, then update the pin.
    """

    _OWNERS = {
        "ds_relscore.js": ("fetchDsRelscore", "api/ds-relscore"),
        "ds_skill_order.js": ("fetchDsSkillOrder", "api/ds-skill-order"),
    }

    def _const_modes(self, code: str) -> list[str]:
        found = re.findall(r"\bconst mode\s*=\s*([^;]+);", code)
        return [value.strip() for value in found]

    def _calls(self, code: str, fetch_fn: str) -> list[str]:
        """Each call's whole argument text, all whitespace removed. Parens are
        balanced by count; string contents are not treated specially."""
        found = []
        for match in re.finditer(rf"(?<!function ){fetch_fn}\(", code):
            depth = 1
            end = match.end()
            while depth and end < len(code):
                depth += {"(": 1, ")": -1}.get(code[end], 0)
                end += 1
            self.assertEqual(depth, 0, f"unbalanced call to {fetch_fn}")
            found.append("".join(code[match.end():end - 1].split()))
        return found

    def test_relscore_map_values_are_all_supported(self) -> None:
        code = _code_lines(_PANELS / "ds_relscore.js")
        block = re.search(r"const _DSR_MODE_MAP = \{(.*?)\};", code, re.DOTALL)
        self.assertIsNotNone(block)
        values = [v.strip() for v in re.findall(r":\s*([^,\n}]+)", block.group(1))]
        # An empty findall would pass the subset check, so anchor it.
        self.assertTrue(values)
        self.assertLessEqual(set(values), {f'"{m}"' for m in _SUPPORTED})
        self.assertEqual(code.count("_DSR_MODE_MAP"), 2)
        self.assertIn('return _DSR_MODE_MAP[queueId | 0] || "SR";', code)

    def test_relscore_render_sends_the_mapped_mode(self) -> None:
        code = _code_lines(_PANELS / "ds_relscore.js")
        self.assertEqual(self._const_modes(code), ["_modeForQueue(cs.queue_id)"])
        self.assertEqual(
            self._calls(code, "fetchDsRelscore"),
            ["champ,mode,items,_DSR_LEVEL,()=>renderDsRelscore(blockEl,cs)"],
        )

    def test_skill_order_render_sends_literal_sr(self) -> None:
        code = _code_lines(_PANELS / "ds_skill_order.js")
        self.assertEqual(self._const_modes(code), ['"SR"'])
        self.assertEqual(self._calls(code, "fetchDsSkillOrder"),
                         ["champ,mode,_dssoOnLand"])

    def test_no_other_web_module_names_either_route(self) -> None:
        paths = sorted(_WEB.rglob("*.js"))
        # An empty glob would pass the loop below, so anchor it on the owners.
        self.assertLessEqual(set(self._OWNERS), {p.name for p in paths})
        for path in paths:
            code = _code_lines(path)
            for owner, names in self._OWNERS.items():
                if path.name == owner:
                    continue
                for name in names:
                    with self.subTest(file=path.name, name=name):
                        self.assertNotIn(name, code)


if __name__ == "__main__":
    unittest.main()
