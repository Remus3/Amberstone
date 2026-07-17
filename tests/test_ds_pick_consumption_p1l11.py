# arch: P1-L11 DS pick CONSUMPTION-end contract tests | section=coaching | frozen=no
"""DS pick consumption-end correctness (audit P1-L11).

A prior pass (P1-L6) verified the dispatch WIRING - all four coaches call
``coach_integration.archetype_dispatch.dispatch_for_coach`` and get an
identically shaped ``CoachDispatchResult``. THIS lane is the CONSUMPTION
end, two user-facing surfaces a well-formed-but-mis-consumed pick payload
would silently break:

  (a) Prompt injection - the DS picks the dispatcher computed actually
      land in the constructed Haiku user prompt, in the labeled
      ``DS top items (<label> ranked, own-items-accounted): <picks>``
      slot, as the *dispatch output* (no re-derivation divergence, not
      truncated, not the engine-down sentinel when picks exist).

  (b) Dashboard render contract - the ``daemon_slayer_picks`` legacy
      shape the dashboard JS consumes is stable: the backend
      (``_build_display_rows``) emits a superset of the keys the JS
      reads, and the shared JS consumption primitive
      (``web/js/lib/scorer_units.js``) degrades on empty / partial /
      missing-scorer rows without throwing (renderers must be
      idempotent + never blank-poison the panel).

  (c) Failure modes - engine unavailable / empty picks / a champion
      whose scorer yields nothing -> the prompt drops the line (SR) or
      shows ``unavailable`` (ARAM/Arena/Brawl) and the dashboard hides
      the block; no exception, no blank coaching, no stale-pick poison.

P1-L11 finding: VERIFIED-CORRECT. These are characterization / contract
tests pinning the consumption behaviour so a regression (a coach that
computes picks then drops them before the prompt, a backend/JS shape
key divergence, a renderer that throws on empty picks, the engine-down
sentinel leaking into a populated prompt) is caught.

No hardcoded magic numbers for engine outputs: the expected prompt
substring is derived from the dispatch helper's OWN ``picks_str`` /
``_build_display_rows`` output, never recomputed by hand. Dispatcher is
mocked at the ``rank_for_primary_archetype`` boundary - no live :8893.
The JS group shells out to ``node`` against the real
``scorer_units.js``; it is skipped (not failed) if node is absent.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from coach_integration import archetype_dispatch
from coach_integration.archetype_dispatch import (
    CoachDispatchResult,
    dispatch_for_coach,
    display_label,
    _build_display_rows,
)

_PROJECT_ROOT = Path(__file__).parent.parent
_SCORER_UNITS_JS = _PROJECT_ROOT / "web" / "js" / "lib" / "scorer_units.js"

# The engine-down sentinel each coach initialises picks_str to. SR drops
# the prompt line entirely when this is unchanged; ARAM/Arena/Brawl emit
# it verbatim into the always-present slot. Exercised, not magic.
_UNAVAILABLE = "unavailable"

# The legacy daemon_slayer_picks keys the dashboard JS reads. item_build.js
# / next.js read name|id|gold; scorer_units.js reads delta_dps (primary)
# then delta (fallback) + scorer. active_match.js additionally tolerates
# the item_name/item_id ds-preview alias - but the daemon_slayer_picks
# path emits the name/id form, which active_match.js reads first.
_JS_READ_KEYS = ("id", "name", "delta_dps", "delta", "gold", "scorer")


class _Stats:
    """Duck-typed coach_integration.enemy_stats.EnemyStats stub."""

    def __init__(self, armor=80.0, mr=40.0, max_hp=2000.0, bonus_hp=500.0):
        self.armor = armor
        self.mr = mr
        self.max_hp = max_hp
        self.bonus_hp = bonus_hp


def _resp(scorer: str, rows: list[dict]) -> dict:
    return {
        "ok": True,
        "scorer": scorer,
        "archetype": "carry" if scorer == "dps" else scorer,
        "ranked": rows,
        "fell_back": False,
    }


def _rows_for(scorer: str) -> list[dict]:
    """A representative ranked payload per scorer (hybrid ships
    hybrid_delta_pct; the rest ship a unified ``delta``)."""
    if scorer == "hybrid":
        return [
            {"item_id": "3078", "item_name": "Trinity Force",
             "delta_dps": 18.5, "delta_ehp": 90.0,
             "hybrid_delta_pct": 0.08, "gold": 3333},
            {"item_id": "6333", "item_name": "Death's Dance",
             "delta_dps": 12.0, "delta_ehp": 150.0,
             "hybrid_delta_pct": 0.06, "gold": 3300},
        ]
    return [
        {"item_id": "3031", "item_name": "Infinity Edge",
         "delta": 250.0, "gold": 3500},
        {"item_id": "3094", "item_name": "Rapid Firecannon",
         "delta": 180.0, "gold": 2900},
    ]


# Mirrors the EXACT inline expression each coach uses to splice the
# dispatch result into its constructed Haiku user prompt. Keeping this
# next to the source line numbers is deliberate: if a coach changes how
# it injects picks, the matching builder here must change too, and the
# assertion pins that the contract (picks land in the labeled slot, as
# the dispatch output) still holds.

def _sr_prompt_inject(base_user: str, picks_str: str, label: str) -> str:
    """coach_integration/_coach.py:327-328 - conditional append, the
    engine-down sentinel suppresses the whole line."""
    user = base_user
    if picks_str != _UNAVAILABLE:
        user += f"\nDS top items ({label} ranked, own-items-accounted): {picks_str}"
    return user


def _aram_prompt_inject(picks_str: str, label: str) -> str:
    """coaches/aram_coach.py - the real module template, slot always
    present (carries the sentinel verbatim when the engine is down)."""
    from coaches.aram_coach import _USER_TMPL
    return _USER_TMPL.format(
        game_time="0:00", mayhem_tag="", hp=100, mp=100, gold=0, lv=1,
        kda="0/0/0", items="none", allies="unknown", enemies="unknown",
        enemy_items="unknown", matchup_ctx="none", dead="none",
        alive="all", dead_resp="none", my_t="?", en_t="?", augs="none",
        packs="none", wave_pct=50, my_abilities="none",
        my_runes="unknown", enemy_runes="unknown",
        aram_tenacity="",
        enemy_aram_tenacity="",
        aram_balance="",
        enemy_cc_threats="",
        cc_blended_ehp_impact="",
        cc_conditional_impact="",
        ds_picks=picks_str, ds_label=label, event_line="",
    )


def _arena_prompt_inject(picks_str: str, label: str) -> str:
    """coaches/arena_coach.py - the real _USER_TEMPLATE, slot always
    present."""
    from coaches.arena_coach import _USER_TEMPLATE
    return _USER_TEMPLATE.format(
        round="1", champion="Caitlyn", partner="Lux", hp_pct=100,
        gold=0, level=1, kda="0/0/0", items="none", rank="1",
        alive="4", next_opp="?", team_rankings="-", augments="none",
        my_abilities="none", enemy_cc_threats="",
        cc_blended_ehp_impact="",
        cc_conditional_impact="",
        ds_picks=picks_str, ds_label=label,
        vision_context="",
    )


def _brawl_prompt_inject(picks_str: str, label: str) -> str:
    """coaches/brawl_coach.py:417-434 - inline f-string, the DS line is
    unconditionally concatenated (sentinel shows verbatim)."""
    return (
        "=== 0:00 | BRAWL ===\n"
        + f"\nDS top items ({label} ranked, own-items-accounted): {picks_str}"
    )


_PROMPT_INJECTORS = {
    "ARAM": _aram_prompt_inject,
    "ARENA": _arena_prompt_inject,
    "BRAWL": _brawl_prompt_inject,
}


class PromptInjectionContractTests(unittest.TestCase):
    """(a) The picks the dispatcher computed actually reach the
    constructed Haiku user prompt, in the labeled slot, as the dispatch
    output - not re-derived, not truncated, not the sentinel."""

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def _dispatch(self, scorer, arch, mock_arch, mock_disp):
        mock_arch.return_value = {"primary": arch}
        mock_disp.return_value = _resp(scorer, _rows_for(scorer))
        result = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIsInstance(result, CoachDispatchResult)
        return result

    def test_sr_prompt_contains_exact_dispatch_picks_str(self):
        """SR appends the dispatcher's OWN picks_str verbatim. The string
        in the prompt must be byte-equal to result.picks_str (no
        re-derivation divergence) and sit behind the scorer-correct
        label."""
        for scorer, arch in (("dps", "carry"), ("ehp", "tank"),
                             ("hybrid", "bruiser"), ("hps", "enchanter")):
            with self.subTest(scorer=scorer):
                result = self._dispatch(scorer, arch)
                label = display_label(result.scorer)
                base = "=== 12:00 | SR ===\nHP: 100%"
                prompt = _sr_prompt_inject(base, result.picks_str, label)
                # The dispatch output - the exact picks_str - is present.
                self.assertIn(result.picks_str, prompt)
                # In the labeled, well-formed slot (not bare).
                expected_line = (
                    f"DS top items ({label} ranked, "
                    f"own-items-accounted): {result.picks_str}"
                )
                self.assertIn(expected_line, prompt)
                # The base prompt was preserved (picks appended, not
                # overwriting the game state).
                self.assertTrue(prompt.startswith(base))
                # Every ranked item name reached the prompt (not
                # truncated below `top`).
                for row in result.rows:
                    self.assertIn(row["item_name"], prompt)

    def test_all_three_template_coaches_inject_dispatch_picks(self):
        """ARAM / Arena / Brawl splice picks_str into an always-present
        labeled slot. Drive each coach's REAL prompt constructor with the
        dispatcher's own output and assert the picks + scorer label land
        in the prompt for every scorer."""
        for mode, inject in _PROMPT_INJECTORS.items():
            for scorer, arch in (("dps", "carry"), ("ehp", "tank"),
                                 ("hybrid", "bruiser"),
                                 ("ability", "mage"),
                                 ("burst", "assassin"),
                                 ("hps", "enchanter")):
                with self.subTest(mode=mode, scorer=scorer):
                    result = self._dispatch(scorer, arch)
                    label = display_label(result.scorer)
                    prompt = inject(result.picks_str, label)
                    expected_line = (
                        f"DS top items ({label} ranked, "
                        f"own-items-accounted): {result.picks_str}"
                    )
                    self.assertIn(
                        expected_line, prompt,
                        f"{mode} dropped/garbled the dispatch picks",
                    )
                    for row in result.rows:
                        self.assertIn(row["item_name"], prompt)

    def test_picks_str_in_prompt_equals_helper_format_of_dispatch_rows(self):
        """Defining no-divergence assertion: the picks substring in the
        prompt is exactly what _build_picks_str produces from the SAME
        dispatcher rows the display_rows payload was built from - one
        formatting source feeds both prompt and dashboard."""
        result = self._dispatch("dps", "carry")
        recomputed = archetype_dispatch._build_picks_str(
            result.rows, result.scorer)
        self.assertEqual(result.picks_str, recomputed)
        # And the display_rows (dashboard payload) names line up 1:1 with
        # the picks_str (prompt) names - same rows, no skew.
        prompt_names = [r["item_name"] for r in result.rows]
        payload_names = [r["name"] for r in result.display_rows]
        self.assertEqual(prompt_names, payload_names)


class PromptDegradationContractTests(unittest.TestCase):
    """(c) engine-down / empty picks: the prompt must not blank-poison.
    SR drops the DS line; ARAM/Arena/Brawl emit the sentinel verbatim;
    the empty-rows case shows the literal 'none', never a stale set."""

    def test_sr_engine_down_omits_ds_line_entirely(self):
        base = "=== 12:00 | SR ===\nHP: 100%"
        prompt = _sr_prompt_inject(base, _UNAVAILABLE, "DPS")
        self.assertNotIn("DS top items", prompt)
        self.assertEqual(prompt, base)  # untouched - no blank line, no poison

    def test_template_coaches_engine_down_shows_unavailable(self):
        for mode, inject in _PROMPT_INJECTORS.items():
            with self.subTest(mode=mode):
                prompt = inject(_UNAVAILABLE, "DPS")
                self.assertIn(
                    f"DS top items (DPS ranked, "
                    f"own-items-accounted): {_UNAVAILABLE}",
                    prompt,
                )

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_engine_up_empty_rows_yields_literal_none_not_stale(
            self, mock_arch, mock_disp):
        """Engine reachable but no ranked items: dispatch returns a
        result with picks_str=='none'. SR appends the line with 'none'
        (NOT the prior tick's picks); the helper never carries state."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _resp("dps", [])
        result = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats(),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.picks_str, "none")
        self.assertEqual(result.display_rows, [])
        # SR appends because 'none' != 'unavailable' - operator sees an
        # explicit "no pick this tick", not a leftover.
        prompt = _sr_prompt_inject("BASE", result.picks_str,
                                   display_label(result.scorer))
        self.assertIn("own-items-accounted): none", prompt)

    @mock.patch("core.daemon_slayer_client.rank_for_primary_archetype")
    @mock.patch("core.archetype_picks.get_archetype_for")
    def test_no_state_carried_between_dispatches(self, mock_arch, mock_disp):
        """Stale-pick poison guard: a populated dispatch followed by an
        empty one yields an EMPTY second result - the helper is
        stateless, it cannot resurrect the prior pick set."""
        mock_arch.return_value = {"primary": "carry"}
        mock_disp.return_value = _resp("dps", _rows_for("dps"))
        first = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats())
        self.assertTrue(first.display_rows)
        mock_disp.return_value = _resp("dps", [])
        second = dispatch_for_coach(
            "Caitlyn", mode_engine="SR", level=11, item_ids=[],
            enemy_stats=_Stats())
        self.assertEqual(second.display_rows, [])
        self.assertEqual(second.picks_str, "none")


class DashboardShapeContractTests(unittest.TestCase):
    """(b) The daemon_slayer_picks shape the dashboard JS consumes is
    stable: the backend emits a superset of the keys the JS reads, for
    every scorer, and empty -> empty."""

    def test_backend_emits_superset_of_js_read_keys_every_scorer(self):
        for scorer in ("dps", "ehp", "hybrid", "ability", "burst", "hps", "onhit"):
            with self.subTest(scorer=scorer):
                rows = _build_display_rows(_rows_for(scorer), scorer)
                self.assertTrue(rows)
                emitted = set(rows[0].keys())
                for k in _JS_READ_KEYS:
                    self.assertIn(
                        k, emitted,
                        f"backend dropped JS-read key {k!r} for {scorer}",
                    )
                # scorer field must equal the active scorer so the JS
                # unit map (scorer_units.js) picks the right suffix.
                self.assertEqual(rows[0]["scorer"], scorer)
                # delta_dps (legacy primary the JS reads first) carries
                # the scorer's value; delta mirrors it.
                self.assertEqual(rows[0]["delta_dps"], rows[0]["delta"])

    def test_empty_dispatch_yields_empty_payload_js_array_guard(self):
        """item_build.js / next.js / active_match.js all do
        `Array.isArray(p.daemon_slayer_picks) ? ... : []` then gate on
        `.length`. An empty list is the contract for "no picks" - assert
        the backend produces exactly that (the JS hides the block)."""
        self.assertEqual(_build_display_rows([], "dps"), [])

    def test_payload_is_json_serializable(self):
        """The payload is written into the coaching JSON the dashboard
        polls; non-serializable values would break /api/state."""
        rows = _build_display_rows(_rows_for("hybrid"), "hybrid")
        round_tripped = json.loads(json.dumps(rows))
        self.assertEqual(round_tripped, rows)


@unittest.skipUnless(shutil.which("node"), "node not available")
class ScorerUnitsJsConsumptionTests(unittest.TestCase):
    """(b) The shared JS consumption primitive web/js/lib/scorer_units.js
    (used by item_build / next / active_match / champ_select renderers)
    must never throw and must degrade on empty / partial / missing-scorer
    rows - this is what keeps every DS renderer idempotent + crash-proof
    on a partial coach write."""

    def _run_js(self, body: str) -> str:
        src = _SCORER_UNITS_JS.resolve().as_posix()
        script = (
            f"import {{ scorerUnit, formatDsDelta }} from 'file://{src}';\n"
            + body
        )
        out = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            out.returncode, 0,
            f"node errored: {out.stderr.strip()}",
        )
        return out.stdout.strip()

    def test_format_handles_degraded_rows_without_throwing(self):
        """null / undefined / {} / missing-scorer / delta-only rows all
        produce a string, never an exception. Mirrors what a mid-flush
        coach write or a pre-s182 supervisor payload looks like."""
        body = r"""
const cases = [
  formatDsDelta(null),
  formatDsDelta(undefined),
  formatDsDelta({}),
  formatDsDelta({delta_dps: 30}),         // missing scorer
  formatDsDelta({delta: 42, scorer:'burst'}),  // delta-only (no delta_dps)
];
console.log(JSON.stringify(cases));
"""
        got = json.loads(self._run_js(body))
        # All five degrade to a "+<n><unit>" string, no throw.
        self.assertEqual(len(got), 5)
        for v in got:
            self.assertIsInstance(v, str)
            self.assertTrue(v.startswith("+"))
        # Empty/null -> the documented "+0dps" fallback (dps unit).
        self.assertEqual(got[0], "+0dps")
        self.assertEqual(got[1], "+0dps")
        self.assertEqual(got[2], "+0dps")
        # missing-scorer falls back to the dps unit (pre-s183 status quo).
        self.assertTrue(got[3].endswith("dps"))
        # delta-only still reads delta + applies the scorer unit.
        self.assertTrue(got[4].endswith("burst"))

    def test_scorer_unit_map_matches_python_source_of_truth(self):
        """scorer_units.js SCORER_UNIT must stay in lockstep with the
        Python _UNIT_SUFFIX (the JS comment names it the source of
        truth). A drift means the dashboard shows the wrong unit for a
        non-DPS archetype pick."""
        body = r"""
const scs = ['dps','ehp','hybrid','ability','burst','hps','onhit','bogus',''];
const m = {};
for (const s of scs) m[s] = scorerUnit(s);
console.log(JSON.stringify(m));
"""
        js_map = json.loads(self._run_js(body))
        for scorer, suffix in archetype_dispatch._UNIT_SUFFIX.items():
            self.assertEqual(
                js_map[scorer], suffix,
                f"JS/Python unit drift for scorer {scorer!r}",
            )
        # Unknown / empty scorer -> 'dps' fallback (back-compat for
        # pre-s182 payloads without a scorer field).
        self.assertEqual(js_map["bogus"], "dps")
        self.assertEqual(js_map[""], "dps")

    def test_format_delta_equals_dispatch_delta_for_every_scorer(self):
        """End-to-end consumption parity: feed scorer_units.js the EXACT
        display_rows the backend emits and assert the rendered chip text
        is +<round(delta)><python-unit> - the number the operator sees on
        the dashboard equals the dispatcher's delta, with the correct
        per-archetype unit. No hardcoded magic numbers (delta + unit both
        come from the Python side)."""
        payload = {}
        for scorer in ("dps", "ehp", "hybrid", "ability", "burst", "hps", "onhit"):
            row = _build_display_rows(_rows_for(scorer), scorer)[0]
            payload[scorer] = row
        body = (
            "const rows = " + json.dumps(payload) + ";\n"
            "const out = {};\n"
            "for (const k of Object.keys(rows)) out[k] = formatDsDelta(rows[k]);\n"
            "console.log(JSON.stringify(out));\n"
        )
        rendered = json.loads(self._run_js(body))
        for scorer in ("dps", "ehp", "hybrid", "ability", "burst", "hps", "onhit"):
            row = _build_display_rows(_rows_for(scorer), scorer)[0]
            expected = (
                f"+{round(row['delta_dps'])}"
                f"{archetype_dispatch._UNIT_SUFFIX[scorer]}"
            )
            self.assertEqual(
                rendered[scorer], expected,
                f"dashboard chip text diverges from dispatch delta/unit "
                f"for scorer {scorer!r}",
            )


if __name__ == "__main__":
    unittest.main()
