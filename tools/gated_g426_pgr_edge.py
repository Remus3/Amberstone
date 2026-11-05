"""gated_g426_pgr_edge.py - read-only game-end sampler + grader for G4-26.

G4-26 asks for a live confirm that the Post Game Review auto-shows at game end.
The row was filed off a 2026-07-04 miss; the 2026-07-20 drain root-caused it and
``51dfc0cef`` fixed it: the item-281 null-phase in-game promotion now ARMS the
sticky ``_VIEW.gameStarted`` (``web/js/main.js`` ``_viewAutoDerive``, the
``!phase && live && inGame`` arm), mirrored in ``dashboard/view_router_state.py``
``update_game_started(..., mode=)``. Without it a page that never saw an explicit
ChampSelect / GameStart / InProgress phase reached game end with the sticky
``None``, so the auto-PGR arm (``_viewSaveManual("last-match")`` +
``fetchAndRenderLastMatch()``) was skipped and the companion landed on Home.

Facts measured at source (s144 lane gated c64) that shape the check:

- The arm fires on the page only when a ``/api/state.lcu.phase`` in
  ``EndOfGame / PreEndOfGame / WaitingForStats / TerminatedInError / Lobby``
  reaches it while the sticky is ``in-progress``
  (``view_router_state.is_postgame_pgr_edge``). The page's inputs are
  ``state.latest.lcu`` and ``state.mode`` (main.js ``_viewResolveAndApply``).
- ``/api/state.lcu`` is ``{}`` whenever the relayed LCU snapshot is older than
  5 s (``dashboard/_liveclient.py``), and the in-game LCU capture runs 8-11 s
  behind (``tools/lcu_agent.py`` ``capture_state``). That TTL gap is the
  "broader unfixed bug" at the head of docs/LIVE_GAME_GATED_SYNC.md, so a game
  end whose post-game phase never survives the TTL would still miss the arm.
- The overlay shell (``body[data-shell=overlay]``) never derives a view; the arm
  can only fire in the companion window.

``sample`` polls ``/api/state`` across a game end and replays the stream through
the Python mirror from a ``None`` sticky (a page opened at the first sample, the
mid-game-open case the fix targets), twice: with the fix (``mode=`` passed) and
in the pre-fix shape (no ``mode``). Verdicts:

  EDGE_DELIVERED (exit 0)  the game ended in the window and the stream fired the
                           edge inside the END RUN; ``fix_path_exercised`` is
                           True only when the pre-fix replay did NOT fire there.
  EDGE_MISSED    (exit 3)  the game ended in the window and no end edge fired.
                           ``miss_cause``: ``no_postgame_phase`` (armed at the
                           last in-game sample, no post-game phase fired it: the
                           5 s TTL side) or ``not_armed_at_end`` (the page could
                           not fire whatever came: the arm / mode-signal side).
  NO_EVIDENCE    (exit 4)  no live game, or the game did not end in the window.

ENDED means the window runs on END_SPAN_S past the last live sample with no live
data coming back; a post-game phase alone is not an end (a stale one shows up
mid-game). The END RUN is the final unbroken run of samples that are non-live or
carry a post-game phase (the cached liveclient stays non-empty up to 5 s after
:2999 stops, so the real post-game phase can land on live samples); the last
in-game sample is the one just before it. An edge BEFORE the end run fired on a
stale mid-game phase, or ended an EARLIER game in a window that spans two (only
the last game is graded); it never counts as the end edge and is reported as
``mid_game_edges``. The replay keeps the last in-game ``mode_key`` (``onState``
calls ``setMode`` only for an in-game tag); a health-envelope change of the page
mode is not visible from /api/state.

READ-ONLY: GETs to :8888 only; no write, no restart, no LCU call, no tick. Prints
phase, mode and counts only: no path, game id or player id. EDGE_DELIVERED never
ticks G4-26: it proves the INPUT reached /api/state, i.e. the compute half. The
row also needs the RENDER half, the operator's eyeball that the companion showed
the Post Game Review of the game just played, which no tool here can see.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.view_router_state import (  # noqa: E402
    _POSTGAME_PHASES as POSTGAME_PHASES,
    IN_GAME_MODES,
    derive_view,
    is_postgame_pgr_edge,
    update_game_started,
)

TOOL = "gated_g426_pgr_edge"
MAX_SAMPLES = 3600
# A non-live tail must run this long after the last live sample to count as a
# game end: /api/state.liveclient reads {} on any >5 s stale cache, so a few
# empty samples are a blip, not an end.
END_SPAN_S = 15.0


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def sample_from_state(state: Any, state_err: Optional[str], now: float) -> dict:
    """One sample: the two inputs the page's ``_viewAutoDerive`` reads, plus live.

    ``live`` mirrors main.js: ``Object.keys(liveclient).length`` > 0, so the TFT
    standalone fill-in counts as live there and here.
    """
    if not isinstance(state, dict):
        return {"t": now, "dash_down": True, "phase": None, "mode": None,
                "live": False, "lcu_keys": None}
    lcu = state.get("lcu")
    lcu = lcu if isinstance(lcu, dict) else {}
    phase = lcu.get("phase")
    lc = state.get("liveclient")
    mode = state.get("mode_key")
    return {"t": now, "dash_down": False,
            "phase": phase if isinstance(phase, str) and phase else None,
            "mode": mode if isinstance(mode, str) else None,
            "live": isinstance(lc, dict) and len(lc) > 0,
            "lcu_keys": len(lcu)}


def _replay(samples: list, with_fix: bool) -> tuple:
    """(indices of EVERY edge, sticky AFTER each sample) - the page fires on each.

    The page's ``state.mode`` comes from ``onState``, which calls ``setMode`` only
    for an in-game tag (a missing ``mode_key`` reads as "client" there), and from
    the health envelope, which this tool cannot see. So the replay keeps the last
    in-game ``mode_key`` and never models a health-driven change back to client.
    """
    edges: list = []
    after: list = []
    sticky: Optional[str] = None
    mode: Optional[str] = None
    for i, s in enumerate(samples):
        if s.get("dash_down"):
            after.append(sticky)
            continue  # no envelope reaches the page, so it does not re-derive
        if s["mode"] in IN_GAME_MODES:
            mode = s["mode"]
        phase, live = s["phase"], s["live"]
        if is_postgame_pgr_edge(phase, sticky):
            edges.append(i)
        if with_fix:
            sticky = derive_view(phase, mode, sticky, live=live).game_started
        else:
            sticky = update_game_started(phase, sticky, live=live)
        after.append(sticky)
    return edges, after


def _ended(samples: list, last_live: int) -> bool:
    """Did the game end in the window? Judged only AFTER the last live sample.

    The window must run on END_SPAN_S past the last live sample with no live data
    coming back (every later sample is non-live by definition of "last live"). A
    liveclient or stale-phase blip that live data recovers from is not an end, and
    nor is a stale post-game phase, or a short non-live tail, at the window end.
    """
    t0 = samples[last_live]["t"]
    return any(not s.get("dash_down") and s["t"] - t0 >= END_SPAN_S
               for s in samples[last_live + 1:])


def _last_in_game(samples: list) -> Optional[int]:
    """Index of the last live sample with no post-game phase, else None."""
    for i in range(len(samples) - 1, -1, -1):
        s = samples[i]
        if not s.get("dash_down") and s["live"] and s["phase"] not in POSTGAME_PHASES:
            return i
    return None


def grade_stream(samples: list) -> dict:
    """EDGE_DELIVERED / EDGE_MISSED / NO_EVIDENCE over samples in time order."""
    up = [s for s in samples if not s.get("dash_down")]
    live_idx = [i for i, s in enumerate(samples) if s.get("live")]
    last_live = live_idx[-1] if live_idx else None
    ended = last_live is not None and _ended(samples, last_live)
    edges, sticky_after = _replay(samples, with_fix=True)
    pre_fix, _ = _replay(samples, with_fix=False)
    # The END RUN is the final unbroken run of samples that are non-live or carry
    # a post-game phase (the cached liveclient can stay non-empty for up to 5 s
    # after :2999 stops, so the real post-game phase may land on live samples).
    # ``in_game`` is the last sample before it. Only an edge inside the end run is
    # the game-end edge; one before it fired on a stale mid-game phase, or ended
    # an EARLIER game in a window that spans two (only the last game is graded).
    in_game = _last_in_game(samples)
    run_start = in_game + 1 if in_game is not None else 0
    end_edges = [i for i in edges if i >= run_start]
    edge = end_edges[0] if end_edges else None
    pre_fix_end = [i for i in pre_fix if i >= run_start]
    miss_cause = None
    if edge is not None and ended:
        verdict = "EDGE_DELIVERED"
    elif ended:
        verdict = "EDGE_MISSED"
        # Armed at the last in-game sample but no post-game phase fired it: the
        # 5 s TTL side. Not armed there: the page could not fire whatever phase
        # came, so it is the arm / mode-signal side, never the TTL.
        armed = in_game is not None and sticky_after[in_game] == "in-progress"
        miss_cause = "no_postgame_phase" if armed else "not_armed_at_end"
    else:
        verdict = "NO_EVIDENCE"
    end_to_edge = (round(samples[edge]["t"] - samples[in_game]["t"], 2)
                   if edge is not None and in_game is not None else None)
    phases: dict = {}
    for s in up:
        key = s["phase"] or "null"
        phases[key] = phases.get(key, 0) + 1
    return {"tool": TOOL, "verdict": verdict,
            "samples": len(samples), "dash_down": len(samples) - len(up),
            "live_samples": len(live_idx),
            "null_phase_live_samples": sum(1 for s in up if s["live"] and not s["phase"]),
            "phase_counts": phases,
            "modes": sorted({s["mode"] for s in up if s["mode"]}),
            "game_ended_in_window": bool(ended),
            "miss_cause": miss_cause,
            "edge_phase": samples[edge]["phase"] if edge is not None else None,
            "last_in_game_to_edge_s": end_to_edge,
            "mid_game_edges": len(edges) - len(end_edges),
            "pre_fix_would_fire": bool(pre_fix_end),
            "fix_path_exercised": edge is not None and not pre_fix_end,
            "note": "not a tick: the input reached /api/state only; the companion "
                    "rendering the Post Game Review is the operator's eyeball"}


def _probe_once() -> dict:
    from tools.gated_live_probe import _DASH_BASE, _get_json
    state, err = _get_json(f"{_DASH_BASE}/api/state", None)
    return sample_from_state(state, err, time.time())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G4-26 PGR game-end edge check (read-only)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("sample")
    ps.add_argument("--samples", type=int, default=240)
    ps.add_argument("--interval", type=float, default=1.0)
    ps.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace, probe=_probe_once, sleep=time.sleep) -> int:
    if not 1 <= args.samples <= MAX_SAMPLES or not _finite(args.interval) \
            or args.interval < 0:
        raise ValueError("samples must be 1..3600 and interval a finite >= 0")
    samples = []
    for i in range(args.samples):
        if i:
            sleep(args.interval)
        samples.append(probe())
    result = grade_stream(samples)
    if args.json:
        result["stream"] = [{k: s[k] for k in ("t", "dash_down", "phase", "mode", "live")}
                            for s in samples]
    print(json.dumps(result, indent=2))
    return {"EDGE_DELIVERED": 0, "EDGE_MISSED": 3}.get(result["verdict"], 4)


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
