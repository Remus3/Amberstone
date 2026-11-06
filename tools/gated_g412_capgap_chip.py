"""gated_g412_capgap_chip.py - read-only grader for G4-12 (capability-gap chip).

G4-12 asks for the in-game eyeball of the L4 capability-gap chip CONTENT against a
real enemy comp. The chip is the dashboard Active Match BUILD-pane mount
``#am-sugg-capability-gap`` (``web/index.html``), painted by
``web/js/panels/active_match.js`` ``_amRenderCapabilityGap`` from the
``capability_gap`` field of ``POST /api/ds-preview`` (``dashboard/routes_state.py``,
flag ``RC_CAPGAP_SURFACE``, default ON; computed by
``core/ds_capability_gap.py`` ``build_capability_gap``).

Facts measured at source (s144 lane gated c72) that shape the check:

- The CLIENT builds the roster it posts: every ``liveclient.allPlayers`` row whose
  ``team`` differs from the team ``_resolveMyTeam`` finds. When that resolve
  returns null (no activePlayer name match) the skip never fires, so all 10
  players, me and my allies included, are posted as "enemies". The server has its
  own rule (``dashboard/_liveclient.py``: ``enemy_team`` by ``summonerName``
  equality). A roster the two rules disagree on is a live-only defect class this
  grader names (ROSTER_BAD) before it grades any content.
- The client posts ``{champion, enemies, mode, level: 6, items: []}`` and caches
  the answer per champion + roster + mode key for the life of the page, so one
  roster is fetched once. ``champion`` is ``/api/state`` ``coach.champion``
  (``web/js/main.js`` ``coachPayload = st.coach || st``), ``mode`` is
  ``mode_key`` upper-cased. The server canonicalises the champion
  (``canonical_champion_id``) before ``build_capability_gap``; so does the
  in-process path here, or multi-word names grade differently.
- The chip is NOT behind the B4 live-directive gate (``live_directive_gate.js`` is
  applied to the coach imperatives only). It is only REPAINTED while live and
  while ``_amDsSyntheticCs`` resolves the coach champion to a numeric id:
  ``renderActiveMatch`` and ``_amRenderDsCluster`` both return before the chip
  call otherwise, so the chip keeps its LAST paint (a post-game page can still
  show the previous game's gap). Only a capture inside a live game counts.

Sub-commands (READ-ONLY: reads the files named; no network, no write, no tick):

  snippet
      Print the JS expression a HEADLESS Chromium page on the dashboard evaluates
      to capture the chip's DOM state as JSON (save it as the --dom file).
  grade --state FILE --dom FILE [--preview FILE] [--state-ts EPOCH] [--json]
      FILE for --state is a saved ``/api/state`` body; --preview is a saved
      ``POST /api/ds-preview`` body for the same champion + roster (else the
      expected verdict is computed in-process by ``build_capability_gap``, and
      the output says so). Verdicts and exit codes:
        RENDER_MATCH (0)      chip visible, axis label and verdict text equal the
                              expected payload; the operator eyeball is STILL owed
        ROSTER_BAD (3)        team unresolved, enemy count not 5, the posted coach
                              champion missing or not my row's champion, or the
                              client and server rules disagree
        CHIP_ABSENT (3)       the mount is not in the captured DOM
        RENDER_MISMATCH (3)   visibility, axis or verdict differs from expected
        NO_GAME (4)           liveclient empty, no roster, mode_key not sr, or an
                              LCU phase other than InProgress (EndOfGame etc.)
        STALE_DOM (4)         DOM and state captures more than MAX_SKEW_S apart
        NO_GAP_CONSISTENT (4) no gap expected and the chip is hidden: consistent,
                              but it proves no content (the row needs a gap comp)

RENDER_MATCH never ticks G4-12: render == compute is the SUBSTITUTION half. Only
the operator's yes / no that the named gap is real for the comp on screen, written
with the values this tool prints, answers the row. Prints champion names only, no
player name, game id or player id.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TOOL = "gated_g412_capgap_chip"
MOUNT_ID = "am-sugg-capability-gap"
MAX_SKEW_S = 5.0
SR_ENEMIES = 5
# Mirrors web/js/panels/active_match.js _AM_CAPGAP_AXIS_LABEL (pinned by a test).
AXIS_LABEL = {
    "anti_tank": "Anti-tank",
    "sustain": "Anti-heal",
    "poke": "Anti-poke",
    "zone_control": "Anti-zone",
    "objective_damage": "Anti-siege",
}
# Mirrors dashboard/routes_state.py _DS_PREVIEW_MODE_ALIASES (pinned by a test).
MODE_ALIASES = {"KIWI": "ARAM", "ARAM_5V5": "ARAM", "ARAM_MAYHEM": "ARAM",
                "CHERRY": "ARENA"}
EXIT = {"RENDER_MATCH": 0, "ROSTER_BAD": 3, "CHIP_ABSENT": 3,
        "RENDER_MISMATCH": 3}

DOM_SNIPPET = (
    "(() => { const b = document.getElementById('" + MOUNT_ID + "');"
    " if (!b) return {ts: Date.now() / 1000, present: false};"
    " const r = b.getBoundingClientRect();"
    " const q = (s) => { const e = b.querySelector(s);"
    " return e ? e.textContent.trim() : ''; };"
    " return {ts: Date.now() / 1000, present: true, hidden: b.hidden,"
    " display: getComputedStyle(b).display, w: r.width, h: r.height,"
    " offset_parent: b.offsetParent !== null,"
    " axis_attr: b.dataset.capgapAxis || '',"
    " axis_text: q('.capability-gap-axis'),"
    " verdict_text: q('.capability-gap-verdict')}; })()"
)


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split())


def axis_label(axis: str) -> str:
    """The label the client paints for an axis key (the JS fallback included)."""
    axis = str(axis or "")
    return AXIS_LABEL.get(axis) or (axis.replace("_", " ") if axis else "Gap")


def _me_name(lc: dict) -> str:
    ap = lc.get("activePlayer") if isinstance(lc.get("activePlayer"), dict) else {}
    return str(ap.get("summonerName") or ap.get("riotIdGameName") or "")


def _is_me(pl: dict, me: str) -> bool:
    rid = str(pl.get("riotIdGameName") or pl.get("summonerName") or "")
    return rid == me or me.startswith(rid + "#") or rid == me.split("#", 1)[0]


def _me_row(lc: dict) -> Optional[dict]:
    """Port of active_match.js _resolveMyTeam's match: the first row naming me."""
    me = _me_name(lc)
    if not me:
        return None
    for pl in lc.get("allPlayers") or []:
        if isinstance(pl, dict) and _is_me(pl, me):
            return pl
    return None


def client_roster(lc: dict) -> dict:
    """The champion + enemy list the client would post, with its team read."""
    row = _me_row(lc)
    team = (row or {}).get("team") or None
    enemies = []
    for pl in lc.get("allPlayers") or []:
        if not isinstance(pl, dict):
            continue
        if team and pl.get("team") == team:
            continue
        name = str(pl.get("championName") or pl.get("rawChampionName") or "")
        if name:
            enemies.append(name)
    return {"team": team, "my_champion": str((row or {}).get("championName") or ""),
            "enemies": enemies}


def _key(name: Any) -> str:
    """Name-form-blind compare key ("Kai'Sa" == "KaiSa" == "kaisa")."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def posted_champion(state: dict) -> str:
    """The champion the client posts: ``(st.coach || st).champion`` (main.js)."""
    coach = state.get("coach")
    src = coach if isinstance(coach, dict) and coach else state
    return str(src.get("champion") or "")


def roster_problems(lc: dict, roster: dict, posted: str = "") -> list:
    out = []
    if not posted:
        out.append("no coach champion: the client never fetches the chip")
    elif _key(posted) != _key(roster["my_champion"]):
        out.append("posted coach champion != my roster row champion")
    if not roster["team"]:
        out.append("team unresolved: the client would post all players")
    if len(roster["enemies"]) != SR_ENEMIES:
        out.append(f"enemy count {len(roster['enemies'])} != {SR_ENEMIES}")
    served_me = str(lc.get("champion") or "")
    if served_me and _key(served_me) != _key(roster["my_champion"]):
        out.append("client and server disagree on my champion")
    served = lc.get("enemy_team")
    if isinstance(served, list) and sorted(map(str, served)) != sorted(roster["enemies"]):
        out.append("client roster != server enemy_team")
    return out


def expected_from_preview(body: dict) -> dict:
    cg = body.get("capability_gap") if isinstance(body, dict) else None
    return cg if isinstance(cg, dict) and cg.get("applies") else {"applies": False}


def expected_in_process(champion: str, enemies: list, mode: str) -> dict:
    """The route's own steps (routes_state.py _serve_ds_preview_post): canonical
    champion id, upper-cased aliased mode, then build_capability_gap."""
    from core.archetype_picks import canonical_champion_id
    from core.ds_capability_gap import build_capability_gap
    m = MODE_ALIASES.get(mode.upper(), mode.upper())
    champ = (canonical_champion_id(champion) or champion) if champion else ""
    cg = build_capability_gap(champ, enemies, m)
    return cg if cg.get("applies") else {"applies": False}


def dom_visible(dom: dict) -> bool:
    return bool(dom.get("present")) and not dom.get("hidden") \
        and str(dom.get("display") or "") != "none" \
        and float(dom.get("w") or 0) > 0 and float(dom.get("h") or 0) > 0 \
        and bool(dom.get("offset_parent"))


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def grade(state: dict, dom: dict, state_ts: float,
          expected_fn: Callable[[str, list, str], dict]) -> dict:
    """Grade one state + DOM capture pair. ``expected_fn`` gives the payload."""
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    ctx = {"tool": TOOL, "mode_key": state.get("mode_key"),
           "game_time_s": lc.get("game_time_s"), "state_ts": state_ts,
           "dom_ts": dom.get("ts")}

    def out(verdict: str, **kw) -> dict:
        return {"verdict": verdict, **ctx, **kw}

    lcu = state.get("lcu") if isinstance(state.get("lcu"), dict) else {}
    ctx["lcu_phase"] = lcu.get("phase")
    # The client repaints the chip only in a live game; an end-of-game screen
    # with a not-yet-stale feed can still carry the last paint.
    if lcu.get("phase") not in (None, "", "InProgress"):
        return out("NO_GAME")
    if not lc or not lc.get("allPlayers") or str(state.get("mode_key") or "") != "sr":
        return out("NO_GAME")
    if not _finite(dom.get("ts")) or not _finite(state_ts) \
            or abs(float(dom["ts"]) - float(state_ts)) > MAX_SKEW_S:
        return out("STALE_DOM")
    roster = client_roster(lc)
    posted = posted_champion(state)
    ctx.update(my_champion=roster["my_champion"], posted_champion=posted,
               enemies=roster["enemies"])
    probs = roster_problems(lc, roster, posted)
    if probs:
        return out("ROSTER_BAD", problems=probs)
    if not dom.get("present"):
        return out("CHIP_ABSENT")
    # main.js passes state.mode (the mode_key tag); active_match upper-cases it.
    exp = expected_fn(posted, roster["enemies"], str(state.get("mode_key")).upper())
    visible = dom_visible(dom)
    ctx.update(expected_applies=bool(exp.get("applies")), visible=visible)
    if not exp.get("applies"):
        return out("RENDER_MISMATCH", problems=["chip visible with no gap expected"]) \
            if visible else out("NO_GAP_CONSISTENT")
    want_label = axis_label(exp.get("top_gap"))
    want_verdict = _norm(exp.get("verdict"))
    ctx.update(top_gap=exp.get("top_gap"), axis_label=want_label,
               verdict_text=want_verdict, gaps=[g.get("axis") for g in exp.get("gaps") or []])
    probs = []
    if not visible:
        probs.append("gap expected but chip not visible")
    if _norm(dom.get("axis_text")) != want_label:
        probs.append("axis label differs")
    # renderCapabilityGapChip: block.dataset.capgapAxis = axis || "none".
    if str(dom.get("axis_attr") or "") != (str(exp.get("top_gap") or "") or "none"):
        probs.append("data-capgap-axis differs")
    if _norm(dom.get("verdict_text")) != want_verdict:
        probs.append("verdict text differs")
    if probs:
        return out("RENDER_MISMATCH", problems=probs)
    return out("RENDER_MATCH", operator_eyeball_owed=True)


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{Path(path).name}: not a JSON object")
    return data


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    g = sub.add_parser("grade")
    g.add_argument("--state", required=True)
    g.add_argument("--dom", required=True)
    g.add_argument("--preview")
    g.add_argument("--state-ts", type=float)
    g.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    if args.cmd == "snippet":
        print(DOM_SNIPPET)
        return 0
    state, dom = _load(args.state), _load(args.dom)
    ts = args.state_ts if args.state_ts is not None else Path(args.state).stat().st_mtime
    if args.preview:
        body = _load(args.preview)
        source = "preview"

        def fn(_c: str, _e: list, _m: str) -> dict:
            return expected_from_preview(body)
    else:
        source, fn = "in_process", expected_in_process
    result = grade(state, dom, ts, fn)
    result["expected_source"] = source
    print(json.dumps(result, indent=2 if args.json else None))
    return EXIT.get(result["verdict"], 4)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
