"""RM-860: the ARAM Mayhem augment reco gets a render surface.

KIWI (ARAM Mayhem) routes to the ARAM coach (core/game_snapshot.py), so
coaches/arena_coach.py never runs in a Mayhem game. Before this fix
`coaches/aram_coach.py` `Coach._handle_augment_select` paid a Haiku call and
wrote `aug_take` / `aug_why` / `aug_plan`, which no web file reads, while the
only augment panel (`web/js/panels/augment_reco.js` `renderAugmentReco`)
hides unless `p.aug_reco` is a non-empty array - a key only
`coaches/arena_coach.py` `_augment_recommendation` stamps. On top of that,
`Coach._run_vision` loaded the artifact BEFORE calling the handler and wrote
its stale copy back AFTER, so even the handler's own fields were clobbered.

Pinned here (no network, no DB: the external prior and own history are
stubbed, the meta table is built in-test, and the REAL
`core.augment_recommender.recommend` ranks):
  - a Mayhem augment state stamps `aug_reco*` in exactly the field shape the
    arena helper produces, with zero Haiku calls;
  - plain ARAM gets no Mayhem reco;
  - the Haiku `aram_aug_select` fallback is RETIRED (RM-877): an unrankable
    Mayhem offer or a plain-ARAM augment state makes zero client calls and
    writes no `aug_*` key, because its `aug_take` / `aug_why` / `aug_plan`
    had no reader in `web/` or `dashboard/`;
  - a new unrankable offer drops the previous panel's ranking;
  - `_run_vision` persists the reco and clears `augment_select` once a scan
    reports the panel gone, keeping the standing reco;
  - the stage is counted from the game-start pick, never guessed mid-game;
  - the real ES module renders the handler's artifact through a stub DOM.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import aram_coach  # noqa: E402
from core import augment_external_source as X  # noqa: E402
from core import augment_recommender as R  # noqa: E402

PANEL_JS = _PROJECT_ROOT / "web" / "js" / "panels" / "augment_reco.js"
NODE = shutil.which("node")

# Live ARAM Mayhem offer from the 2026-07-12 eyeball (memory
# open_bug_aram_augment_reco_cadence_miss): Kayle, OCR timer 0:05. All three
# resolve in the tracked cherry_augments.json at 16.21.1 (1133 / 2100 / 2132);
# the in-test meta below mirrors those ids.
_CHOICES = ["Magic Missile", "Pursuit of Haste", "Warlock Juicebox"]
_IDS = {"Magic Missile": 1133, "Pursuit of Haste": 2100, "Warlock Juicebox": 2132}
_EXT_WR = {"1133": 0.52, "2100": 0.55, "2132": 0.49}
_EXT_STAGE_WR = {"2100": {"1": 0.58, "2": 0.51}}


def _meta() -> X.AugmentMetaTable:
    return X.AugmentMetaTable(
        augments={str(v): {"name": k, "rarity": "kGold", "icon": ""}
                  for k, v in _IDS.items()},
        _name_index={X._norm_name(k): v for k, v in _IDS.items()},
    )


def _priors() -> X.AugmentPriorTable:
    return X.AugmentPriorTable(
        mode="mayhem",
        augments={aid: {"win_rate": wr,
                        "stage_win_rate": _EXT_STAGE_WR.get(aid, {})}
                  for aid, wr in _EXT_WR.items()},
    )


class _CaptureClient:
    """Stand-in for anthropic.Anthropic: records every messages.create."""

    def __init__(self, reply: str = "Take: Aug A\nWhy: w\nGameplan: g") -> None:
        self.calls: list[dict] = []
        outer = self

        class _Msgs:
            def create(self, **kw):
                outer.calls.append(kw)
                resp = mock.MagicMock()
                resp.content = [mock.MagicMock(text=reply)]
                resp.usage = None
                return resp

        self.messages = _Msgs()


def _coach(out: Path, *, mode: str = "KIWI", game_seconds: float = 5.0,
           client=None) -> aram_coach.Coach:
    c = aram_coach.Coach.__new__(aram_coach.Coach)
    c._MODE_NAME = "aram"
    c._out = out
    c._overlay = {}
    c._vision_state = {}
    c._client = client
    c._api_key = "sk-ant-test"
    c._last_state = {
        "game_mode": mode, "champion": "Kayle", "hp_pct": 100,
        "game_seconds": game_seconds,
        "ally_comp": ["Ahri"], "enemy_comp": ["Sion"],
    }
    c._init_extra()
    # _record_coach_call is BaseCoach telemetry. No augment path reaches it
    # since RM-877 retired the Haiku fallback; stubbed so a regression that
    # brings a call back fails on the call count, not on missing telemetry.
    c._record_coach_call = lambda *a, **k: None
    return c


class _Stubbed(unittest.TestCase):
    """Network-free recommender: stubbed prior + empty own history."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name) / "aram_coaching_data.json"
        self.out.write_text('{"mode": "aram"}', encoding="utf-8")
        R.reset_cache()
        self._patches = [
            mock.patch.object(X, "get_augment_meta", lambda **k: _meta()),
            mock.patch.object(X, "get_priors", lambda *a, **k: _priors()),
            mock.patch.object(R, "load_own_history",
                              lambda *a, **k: R.OwnHistory(mode="mayhem")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        R.reset_cache()
        self._tmp.cleanup()

    def artifact(self) -> dict:
        return json.loads(self.out.read_text(encoding="utf-8"))


class MayhemRecoShapeTests(_Stubbed):

    def test_mayhem_state_stamps_aug_reco_in_the_arena_shape(self) -> None:
        client = _CaptureClient()
        c = _coach(self.out, client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        art = self.artifact()

        self.assertTrue(art.get("aug_reco"), "Mayhem reco must be stamped")
        self.assertEqual(art["aug_reco_mode"], "mayhem")
        self.assertEqual(art["aug_reco_top"], "Pursuit of Haste",
                         "highest external prior must rank first")
        self.assertIs(art["augment_select"], True)
        self.assertEqual(art["augment_choices"], _CHOICES)
        self.assertEqual(client.calls, [],
                         "a ranked offer must cost zero Haiku calls")

        # Shape parity with the arena helper the panel was written against.
        # Same inputs (stage None, nothing picked) -> identical payload.
        from coaches import arena_coach
        ref = arena_coach._augment_recommendation(
            {"game_mode": "KIWI"}, list(_CHOICES), [])
        self.assertTrue(ref, "arena reference helper produced nothing")
        got = {k: v for k, v in art.items() if k.startswith("aug_reco")}
        self.assertEqual(set(got), set(ref))
        self.assertEqual(set(got["aug_reco"][0]), set(ref["aug_reco"][0]))
        self.assertEqual(got, ref)
        self.assertEqual(set(aram_coach._AUG_RECO_KEYS), set(ref))

    def test_plain_aram_gets_no_mayhem_reco(self) -> None:
        client = _CaptureClient()
        c = _coach(self.out, mode="ARAM", client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        art = self.artifact()
        self.assertFalse([k for k in art if k.startswith("aug_reco")],
                         f"plain ARAM must carry no Mayhem reco: {art}")

    def test_ranked_offer_drops_a_stale_haiku_take(self) -> None:
        self.out.write_text(json.dumps(
            {"mode": "aram", "aug_take": "Old", "aug_why": "w", "aug_plan": "p"}),
            encoding="utf-8")
        c = _coach(self.out, client=_CaptureClient())
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        art = self.artifact()
        for k in ("aug_take", "aug_why", "aug_plan"):
            self.assertNotIn(k, art)

    def test_unrankable_new_offer_drops_the_previous_ranking(self) -> None:
        c = _coach(self.out, client=None)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        self.assertTrue(self.artifact().get("aug_reco"))
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": ["Unknown Card"]})
        art = self.artifact()
        self.assertFalse([k for k in art if k.startswith("aug_reco")],
                         "a previous panel's ranking must not show for a new offer")


def _aug_keys(art: dict) -> list[str]:
    return sorted(k for k in art if k.startswith("aug_"))


class HaikuAugSelectRetiredTests(_Stubbed):
    """RM-877: the residual Haiku `aram_aug_select` call is retired.

    After RM-860 the call still fired whenever no offered name resolved, and
    in plain ARAM, and wrote `aug_take` / `aug_why` / `aug_plan`. No file in
    `web/` or `dashboard/` reads any of the three (the panel reads only
    `aug_reco*` and `augment_select`), so it was a paid call whose output
    nothing read. Each test hands the coach a counting client and asserts the
    count stays at zero.
    """

    def test_unrankable_mayhem_offer_makes_zero_calls_and_no_aug_keys(self) -> None:
        client = _CaptureClient()
        c = _coach(self.out, client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": ["Aug A", "Aug B"]})
        self.assertEqual(client.calls, [],
                         "an unrankable Mayhem offer must cost zero Haiku calls")
        self.assertEqual(_aug_keys(self.artifact()), [])

    def test_plain_aram_augment_state_makes_zero_calls_and_no_aug_keys(self) -> None:
        # _CHOICES all resolve, so only the plain-ARAM mode keeps them unranked.
        client = _CaptureClient()
        c = _coach(self.out, mode="ARAM", client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        self.assertEqual(client.calls, [],
                         "a plain-ARAM augment state must cost zero Haiku calls")
        self.assertEqual(_aug_keys(self.artifact()), [])

    def test_resolvable_mayhem_offer_still_gets_the_deterministic_reco(self) -> None:
        client = _CaptureClient()
        c = _coach(self.out, client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        art = self.artifact()
        self.assertEqual(client.calls, [])
        self.assertEqual(art["aug_reco_top"], "Pursuit of Haste")
        self.assertEqual(art["aug_reco_mode"], "mayhem")
        self.assertEqual(_aug_keys(art), sorted(aram_coach._AUG_RECO_KEYS),
                         "a ranked offer writes the aug_reco* keys and no other aug_ key")

    def test_unrankable_offer_drops_a_legacy_haiku_take(self) -> None:
        """An artifact written before the retirement must not keep a take."""
        self.out.write_text(json.dumps(
            {"mode": "aram", "aug_take": "Old", "aug_why": "w", "aug_plan": "p"}),
            encoding="utf-8")
        client = _CaptureClient()
        c = _coach(self.out, client=client)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": ["Unknown Card"]})
        self.assertEqual(client.calls, [])
        self.assertEqual(_aug_keys(self.artifact()), [])

    def test_the_aram_aug_select_call_path_is_gone(self) -> None:
        import inspect
        self.assertFalse(hasattr(aram_coach, "_AUG_SELECT_PROMPT"),
                         "the retired Haiku augment prompt is back")
        src = inspect.getsource(aram_coach.Coach._handle_augment_select)
        self.assertNotIn("messages.create", src)
        self.assertNotIn("aram_aug_select\"", src)


class RunVisionLifecycleTests(_Stubbed):

    def _scan(self, c: aram_coach.Coach, vision: dict) -> None:
        from modes.shared_vision import GameVisionReader
        with (
            mock.patch.object(GameVisionReader, "read_tiered",
                              lambda _self, *a, **k: dict(vision)),
            mock.patch.object(aram_coach.Coach, "_fetch_game_data",
                              lambda _self: {}),
        ):
            c._run_vision()

    def test_run_vision_persists_reco_then_clears_augment_select(self) -> None:
        c = _coach(self.out, client=_CaptureClient())
        self._scan(c, {"timer": "0:05", "augment_select": True,
                       "augment_choices": list(_CHOICES), "my_tower_hp": 90})
        art = self.artifact()
        self.assertTrue(art.get("aug_reco"),
                        "_run_vision must not clobber the handler's write")
        self.assertIs(art.get("augment_select"), True)
        self.assertEqual(art.get("my_tower_hp"), 90)

        self._scan(c, {"timer": "0:40", "augment_select": False,
                       "augment_choices": []})
        art = self.artifact()
        self.assertIs(art.get("augment_select"), False,
                      "augment_select must clear once the panel is gone")
        self.assertTrue(art.get("aug_reco"),
                        "the standing reco stays (panel shows TOP PICK)")

    def test_a_scan_without_the_flag_does_not_clear(self) -> None:
        """A partial read (Sonnet escalation missing) is not 'panel gone'."""
        c = _coach(self.out, client=_CaptureClient())
        self._scan(c, {"augment_select": True,
                       "augment_choices": list(_CHOICES)})
        self._scan(c, {"timer": "0:10"})
        self.assertIs(self.artifact().get("augment_select"), True)


class StageTests(_Stubbed):

    def _open(self, c, gs: float) -> None:
        c._last_state["game_seconds"] = gs
        c._track_augment_panel(True)

    def test_stage_counts_panels_from_the_game_start_pick(self) -> None:
        c = _coach(self.out, client=None)
        self._open(c, 5.0)
        self.assertEqual(c._augment_stage(), 1)
        self._open(c, 6.0)  # same panel, repeat scan / reroll
        self.assertEqual(c._augment_stage(), 1)
        c._track_augment_panel(False)
        self._open(c, 420.0)
        self.assertEqual(c._augment_stage(), 2)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        self.assertEqual(self.artifact()["aug_reco_stage"], 2)

    def test_mid_game_start_never_guesses_a_stage(self) -> None:
        c = _coach(self.out, game_seconds=420.0, client=None)
        self._open(c, 420.0)
        self.assertIsNone(c._augment_stage())
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        self.assertIsNone(self.artifact()["aug_reco_stage"])

    def test_reset_extra_clears_the_stage(self) -> None:
        c = _coach(self.out, client=None)
        self._open(c, 5.0)
        c._reset_extra()
        self.assertIsNone(c._augment_stage())
        self.assertFalse(c._aug_panel_open)


_DOM_STUB = """
class StubEl {
  constructor(id) {
    this.id = id; this.innerHTML = ""; this.textContent = ""; this.hidden = true;
    const set = new Set(); this._cls = set;
    this.classList = {
      add: (c) => set.add(c), remove: (c) => set.delete(c),
      toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
      contains: (c) => set.has(c),
    };
  }
}
const ELS = new Map();
globalThis.document = {
  getElementById: (id) => { if (!ELS.has(id)) ELS.set(id, new StubEl(id)); return ELS.get(id); },
  createElement: (t) => new StubEl(t),
  querySelector: () => null, querySelectorAll: () => [],
  addEventListener: () => {}, dispatchEvent: () => {},
};
"""


@unittest.skipIf(NODE is None, "node not available")
class PanelRenderTests(_Stubbed):

    def _render(self, payload: dict) -> dict:
        program = (
            _DOM_STUB
            + "(async () => {\n"
            + f"  const m = await import({json.dumps(PANEL_JS.as_uri())});\n"
            + "  m._resetAugmentRecoSig();\n"
            + f"  m.renderAugmentReco({json.dumps(payload)});\n"
            + "  const b = document.getElementById('ib-aug-reco-block');\n"
            + "  console.log(JSON.stringify({\n"
            + "    hidden: b.hidden, active: b.classList.contains('is-active'),\n"
            + "    top: document.getElementById('ib-aug-reco-top').innerHTML,\n"
            + "    list: document.getElementById('ib-aug-reco-list').innerHTML,\n"
            + "    meta: document.getElementById('ib-aug-reco-meta').textContent,\n"
            + "  }));\n"
            + "})();\n"
        )
        proc = subprocess.run([NODE, "-e", program], capture_output=True,
                              text=True, timeout=60, encoding="utf-8")
        if proc.returncode != 0:
            raise AssertionError(f"node exited {proc.returncode}\n"
                                 f"{proc.stdout}\n{proc.stderr}")
        return json.loads(proc.stdout.strip())

    def test_handler_artifact_populates_the_panel(self) -> None:
        c = _coach(self.out, client=None)
        c._track_augment_panel(True)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        r = self._render(self.artifact())
        self.assertFalse(r["hidden"], "panel must un-hide in ARAM Mayhem")
        self.assertTrue(r["active"])
        self.assertIn("PICK NOW", r["top"])
        self.assertIn("Pursuit of Haste", r["top"])
        self.assertEqual(r["list"].count('class="ar-row'), 3)
        self.assertIn("mayhem", r["meta"])
        self.assertIn("stage 1", r["meta"])

    def test_real_rarity_tokens_colour_the_pip(self) -> None:
        """UI-audit MUST-FIX: the meta table carries CommunityDragon rarity
        tokens (`kGold` / `kSilver` / `kPrismatic`, data/daemon_slayer/<patch>/
        cherry_augments.json), but web/css/panels/augment_reco.css colours only
        `.ar-rar.gold` / `.silver` / `.prismatic`. The raw token lower-cased to
        `kgold`, so with every real payload the tier pip fell back to grey."""
        payload = {
            "augment_select": True, "aug_reco_mode": "mayhem",
            "aug_reco": [
                {"id": 1, "name": "A", "rarity": "kGold", "score": 0.6},
                {"id": 2, "name": "B", "rarity": "kSilver", "score": 0.5},
                {"id": 3, "name": "C", "rarity": "kPrismatic", "score": 0.4},
                {"id": 4, "name": "D", "rarity": "gold", "score": 0.3},
                {"id": 5, "name": "E", "rarity": "kEventChoice", "score": 0.2},
            ],
        }
        r = self._render(payload)
        for cls in ("gold", "silver", "prismatic"):
            self.assertIn(f'class="ar-rar {cls}"', r["list"])
        self.assertNotIn("ar-rar kgold", r["list"])
        self.assertNotIn("ar-rar ksilver", r["list"])
        self.assertEqual(r["list"].count('class="ar-rar gold"'), 2,
                         "the fixture-style plain token must still map")

    def test_every_emitted_rarity_maps_to_a_styled_class(self) -> None:
        """Every rarity the emitters can produce gets a pip class that
        augment_reco.css actually colours.

        Emitter chain: core/augment_recommender.py `AugmentScore.rarity` <-
        core/augment_external_source.py `AugmentMetaTable.rarity`, which is
        the raw CommunityDragon `rarity` of a tracked
        data/daemon_slayer/<patch>/cherry_augments.json snapshot (a degraded
        load can serve any of them). The universe is read from those files,
        so a token CommunityDragon adds later fails here instead of greying
        out silently; the plain tokens are the snapshot fixtures' shape.
        """
        emitted = set()
        for p in sorted((_PROJECT_ROOT / "data" / "daemon_slayer").glob(
                "*/cherry_augments.json")):
            snap = json.loads(p.read_text(encoding="utf-8"))
            for row in (snap.get("augments") or {}).values():
                emitted.add(row.get("rarity"))
        # Anchor: an empty or partial enumeration must not pass vacuously.
        self.assertTrue({"kSilver", "kGold", "kPrismatic", "kEventChoice"} <= emitted,
                        emitted)
        none_seen = None in emitted
        emitted.discard(None)
        universe = sorted(emitted | {"kBronze", "silver", "gold", "prismatic"})

        css = (_PROJECT_ROOT / "web" / "css" / "panels" / "augment_reco.css"
               ).read_text(encoding="utf-8")
        styled = set(re.findall(
            r"\.ar-rar\.([a-z]+)\s*\{\s*background\s*:", css))
        self.assertTrue({"silver", "gold", "prismatic"} <= styled, styled)

        rows = [{"id": i + 1, "name": f"R{i}", "rarity": r, "score": 0.5}
                for i, r in enumerate(universe)]
        program = (
            _DOM_STUB
            + "(async () => {\n"
            + f"  const m = await import({json.dumps(PANEL_JS.as_uri())});\n"
            + "  const out = {};\n"
            + f"  for (const row of {json.dumps(rows)}) {{\n"
            + "    m._resetAugmentRecoSig();\n"
            + "    m.renderAugmentReco({aug_reco: [row]});\n"
            + "    const h = document.getElementById('ib-aug-reco-list').innerHTML;\n"
            + "    const mm = h.match(/class=\"ar-rar ([^\"]*)\"/);\n"
            + "    out[row.rarity] = mm ? mm[1] : null;\n"
            + "  }\n"
            + "  m._resetAugmentRecoSig();\n"
            + "  m.renderAugmentReco({aug_reco: [{id: 9, name: 'N', rarity: null, score: 0.5}]});\n"
            + "  out.__null__ = document.getElementById('ib-aug-reco-list').innerHTML.includes('ar-rar');\n"
            + "  console.log(JSON.stringify(out));\n"
            + "})();\n"
        )
        proc = subprocess.run([NODE, "-e", program], capture_output=True,
                              text=True, timeout=60, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = json.loads(proc.stdout.strip())
        unstyled = {r: got.get(r) for r in universe if got.get(r) not in styled}
        self.assertEqual(unstyled, {}, f"rarities with no coloured pip class: {unstyled}")
        self.assertEqual(got["kEventChoice"], "event")
        self.assertEqual(got["kBronze"], "bronze")
        self.assertFalse(got["__null__"],
                         f"a null rarity renders no pip (seen in data: {none_seen})")

    def test_plain_aram_artifact_keeps_the_panel_hidden(self) -> None:
        c = _coach(self.out, mode="ARAM", client=None)
        c._handle_augment_select(
            {"augment_select": True, "augment_choices": list(_CHOICES)})
        r = self._render(self.artifact())
        self.assertTrue(r["hidden"])


if __name__ == "__main__":
    unittest.main()
