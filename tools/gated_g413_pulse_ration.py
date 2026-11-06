"""gated_g413_pulse_ration.py - read-only grader for G4-13 (RC2 P3.3 pulse rationing).

G4-13 asks for the live eyeball that, with the S0 motion rationing flipped LIVE
(operator-approved 2026-06-22), the pulses it now SUPPRESSES were all benign
re-emits AND the Emergency tier / one-shot Urgent cross still GLOWS under real
combat pressure.

Facts measured at source (s144 lane gated c76) that shape the check:

- ``web/js/panels/right_now.js`` ``renderRightNow`` computes
  ``selectPrimary(signalFromState(p, band))`` and ``shouldPulse(prevCue, sel)``
  (``web/js/lib/overlay_priority.js``) on every envelope and stamps
  ``data-s0-cue`` / ``data-s0-tier`` / ``data-s0-pulse`` on ``#right-now``.
  ``shouldPulse`` is true only on a CUE CROSS (``prevCue !== sel.cue``) into
  the emergency tier (cues lethal / objective_steal / urgent_headline) or into a
  one-shot cue (spike / choices).
- Two glows consume the stamp. (1) The headline ``.action`` gains
  ``rn-pulse-bad|warn|good`` only when the headline TEXT also changed
  (``isFreshAction && _s0Pulse``). (2) ``web/js/overlay_pulse.js`` adds
  ``.ov-pulse`` to an observed container when its mount mutates while
  ``data-s0-pulse == "1"`` (mounts ``am-call-body``, ``am-build-body``,
  ``rn-lead``, ``rn-choices``, ``rn-callouts``; 1500 ms per-container
  throttle; muted by the ``pulseNotify`` overlay setting).
- On the overlay shell ``#rn-action`` is HIDDEN (``web/css/overlay.css``: every
  ``#right-now .panel-body`` child but rn-lead / rn-choices / rn-callouts is
  ``display: none``), so glow (1) never shows there. The overlay's Emergency
  glow is glow (2), and it lands on ``.am-pane-call`` because the live CALL pane
  (``web/js/panels/active_match.js``) is rebuilt with ``innerHTML`` on every
  envelope in the same dispatch (``web/js/main.js``), while rn-lead / rn-choices
  / rn-callouts are signature-deduped and mutate only on a change.
- A lethal cross derived from ``coach.hp_pct`` (low HP at a fight or urgent band) can arm
  the stamp with the headline text unchanged; glow (1) then stays dark by
  construction, so only glow (2) answers that case.

The recorder snippet runs in a HEADLESS Chromium page on the dashboard with
``?overlay=1``. It records every stamp write (a same-value ``dataset`` write
still queues an attribute mutation record) and every glow class added, with
wall-clock seconds. The page runs its OWN ``_s0PrevCue`` against the same state
stream, so it is a parallel instance, not the operator's Electron overlay.

Sub-commands (READ-ONLY: reads the files named; no network, no write, no tick):

  snippet
      Print the JS expression that ARMS the in-page recorder (evaluate once).
  dump
      Print the JS expression that returns the recorded log as JSON (save it
      as the --log file).
  grade --state FILE --log FILE [--state-ts EPOCH] [--json]
      Verdicts and exit codes:
        RATIONED (0)        every armed stamp glowed or was CALL-pane
                            throttled, every stamp matches the shipped
                            decision, no glow fired unarmed, and at least one
                            armed stamp got its own glow; the operator eyeball
                            is STILL owed (suppressed list + the Electron glow)
        DECISION_DRIFT (3)  a stamp's tier or pulse differs from the decision
                            the shipped overlay_priority.js makes (a stale
                            bundle, or the code moved under this tool)
        GLOW_MISSING (3)    an armed stamp got no glow and the CALL pane had
                            not glowed in the previous 1.5 s (throttle)
        GLOW_LEAK (3)       a glow was added while the latest stamp was unarmed
        NO_GAME (4)         LCU phase not exactly InProgress, empty liveclient,
                            or mode_key not sr / aram
        STALE_LOG (4)       the dump and the state capture more than
                            MAX_SKEW_S apart
        NOT_OVERLAY (4)     the page was not the overlay shell
        MUTED (4)           pulseNotify is off (re-run with the toggle on)
        TOO_SHORT (4)       fewer than MIN_STAMPS stamps recorded
        NO_ARMED (4)        no armed stamp with a credited glow yet (none seen, or
                            all throttled): the Emergency half is unanswered
                            (keep recording into real combat)

RATIONED never ticks G4-13: a recorded class change is the COMPUTE-plus-DOM
half, and a headless page is not the operator's Electron overlay. Only the
operator's eyeball of the glow on a real lethal / urgent cross, plus a read of
the ``suppressed`` list, answers the row. Prints cue names and coach headline
prose only, never a player name, game id or player id.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.gated_g417_onhit_render import LIVE_MODES, MAX_SKEW_S, _finite, _load  # noqa: E402

TOOL = "gated_g413_pulse_ration"
# Mirrors _CUE_TIER in web/js/lib/overlay_priority.js (pinned by the test).
CUE_TIER = {"lethal": "emergency", "objective_steal": "emergency",
            "urgent_headline": "emergency", "choices": "urgent", "spike": "urgent",
            "fight": "urgent", "good": "ambient", "none": "empty"}
ONE_SHOT = ("spike", "choices")
# Mirrors overlay_pulse.js THROTTLE_MS and its TARGETS containers (pinned).
THROTTLE_S = 1.5
GLOW_TARGETS = (".am-pane-call", ".am-pane-build", "#rn-lead", "#rn-choices",
                "#rn-callouts")
CALL_PANE = ".am-pane-call"
GLOW_WINDOW_S = 1.0
MIN_STAMPS = 2
EXIT = {"RATIONED": 0, "DECISION_DRIFT": 3, "GLOW_MISSING": 3, "GLOW_LEAK": 3}

RECORDER_SNIPPET = r"""(() => {
  if (window.__g413) return "already armed";
  const rn = document.getElementById("right-now");
  if (!rn) return "no #right-now";
  const log = [];
  window.__g413 = { log: log, armed_at: Date.now() / 1000 };
  const now = () => Date.now() / 1000;
  new MutationObserver(() => {
    const act = document.getElementById("rn-action");
    log.push({ k: "stamp", t: now(), cue: rn.dataset.s0Cue || "",
               tier: rn.dataset.s0Tier || "", pulse: rn.dataset.s0Pulse || "",
               raw: act ? (act.dataset.raw || "") : "",
               band: act ? act.className : "" });
  }).observe(rn, { attributes: true, attributeFilter: ["data-s0-pulse"] });
  const watch = (node, target, cls) => {
    let had = node.classList.contains(cls);
    new MutationObserver(() => {
      const has = node.classList.contains(cls);
      if (has && !had) log.push({ k: "glow", t: now(), target: target, cls: cls });
      had = has;
    }).observe(node, { attributes: true, attributeFilter: ["class"] });
  };
  const targets = %TARGETS%;
  let wired = 0;
  for (const sel of targets) {
    const n = document.querySelector(sel);
    if (n) { watch(n, sel, "ov-pulse"); wired += 1; }
  }
  const act = document.getElementById("rn-action");
  if (act) {
    for (const c of ["rn-pulse-bad", "rn-pulse-warn", "rn-pulse-good"]) {
      watch(act, "#rn-action", c);
    }
  }
  return "armed " + wired + " glow targets";
})()""".replace("%TARGETS%", json.dumps(list(GLOW_TARGETS)))

DUMP_SNIPPET = r"""(() => {
  let notify = true;
  try {
    const o = JSON.parse(localStorage.getItem("rc_overlay_settings") || "{}");
    if (o && typeof o.pulseNotify === "boolean") notify = o.pulseNotify;
  } catch (_e) { /* default stays true */ }
  const r = window.__g413 || null;
  return JSON.stringify({ ts: Date.now() / 1000,
    shell: (document.body && document.body.dataset.shell) || "",
    pulse_notify: notify, armed_at: r ? r.armed_at : null,
    log: r ? r.log : [] });
})()"""


def expected_pulse(prev_cue: str, cue: str) -> bool:
    """The shipped shouldPulse(prevCue, sel) for a stamped cue."""
    eligible = CUE_TIER.get(cue) == "emergency" or cue in ONE_SHOT
    return eligible and prev_cue != cue


def _records(log: dict, kind: str) -> list:
    rows = [r for r in log.get("log") or [] if isinstance(r, dict) and r.get("k") == kind
            and _finite(r.get("t"))]
    return sorted(rows, key=lambda r: float(r["t"]))


def grade(state: dict, log: dict, state_ts: float) -> dict:
    lc = state.get("liveclient") if isinstance(state.get("liveclient"), dict) else {}
    lcu = state.get("lcu") if isinstance(state.get("lcu"), dict) else {}
    ctx: dict = {"tool": TOOL, "mode_key": state.get("mode_key"),
                 "lcu_phase": lcu.get("phase"), "game_time_s": lc.get("game_time_s"),
                 "state_ts": state_ts, "log_ts": log.get("ts")}

    def out(verdict: str, **kw) -> dict:
        return {"verdict": verdict, **ctx, **kw}

    if lcu.get("phase") != "InProgress" or not lc \
            or str(state.get("mode_key") or "") not in LIVE_MODES:
        return out("NO_GAME")
    if not _finite(log.get("ts")) or not _finite(state_ts) \
            or abs(float(log["ts"]) - float(state_ts)) > MAX_SKEW_S:
        return out("STALE_LOG")
    if log.get("shell") != "overlay":
        return out("NOT_OVERLAY", shell=log.get("shell"))
    if log.get("pulse_notify") is False:
        return out("MUTED")
    stamps, glows = _records(log, "stamp"), _records(log, "glow")
    ctx["stamps"] = len(stamps)
    if len(stamps) < MIN_STAMPS:
        return out("TOO_SHORT")
    ov_glows = [g for g in glows if g.get("cls") == "ov-pulse"]
    drift, missing, throttled, suppressed, armed = [], [], [], [], []
    glowed = 0
    # The first stamp is the baseline: its prevCue predates the recorder.
    for i in range(1, len(stamps)):
        prev, s = stamps[i - 1], stamps[i]
        cue, tier, t = str(s.get("cue")), str(s.get("tier")), float(s["t"])
        want = expected_pulse(str(prev.get("cue")), cue)
        got = s.get("pulse") == "1"
        if CUE_TIER.get(cue) != tier or got != want:
            drift.append({"t": t, "prev_cue": prev.get("cue"), "cue": cue, "tier": tier,
                          "pulse": s.get("pulse"), "expected_pulse": "1" if want else "0"})
            continue
        changed = str(s.get("raw")) != str(prev.get("raw"))
        if not got:
            if changed:
                item = {"t": t, "cue": cue, "tier": tier, "prev_cue": prev.get("cue"),
                        "headline": s.get("raw"),
                        "class": "reemit_same_cue" if cue == prev.get("cue")
                        else "steady_tier"}
                if cue == prev.get("cue") and tier == "emergency":
                    item["class"] = "sustained_emergency_new_text"
                suppressed.append(item)
            continue
        end = float(stamps[i + 1]["t"]) if i + 1 < len(stamps) else t + GLOW_WINDOW_S
        window = [g for g in glows if t <= float(g["t"]) <= min(end, t + GLOW_WINDOW_S)]
        # Only .ov-pulse shows on the overlay shell (#rn-action is hidden there);
        # a headline rn-pulse-* is reported as context, never counted as the glow.
        hit = [g for g in window if g.get("cls") == "ov-pulse"]
        armed.append({"t": t, "cue": cue, "headline_changed": changed,
                      "glows": sorted({str(g.get("target")) + ":" + str(g.get("cls"))
                                       for g in window})})
        if hit:
            glowed += 1
        else:
            # The page throttles per container; the CALL pane is the one mount
            # that mutates on every envelope, so only ITS recent glow excuses a
            # dark armed stamp.
            recent = [g for g in ov_glows if g.get("target") == CALL_PANE
                      and t - THROTTLE_S <= float(g["t"]) < t]
            (throttled if recent else missing).append({"t": t, "cue": cue})
    leaks = []
    for g in ov_glows:
        before = [s for s in stamps if float(s["t"]) <= float(g["t"])]
        if before and before[-1].get("pulse") != "1":
            leaks.append({"t": float(g["t"]), "target": g.get("target"),
                          "latest_stamp_cue": before[-1].get("cue")})
    ctx.update(armed=armed, suppressed=suppressed, throttled=throttled,
               sustained_emergency_new_text=sum(
                   1 for x in suppressed if x["class"] == "sustained_emergency_new_text"))
    if drift:
        return out("DECISION_DRIFT", problems=drift)
    if leaks:
        return out("GLOW_LEAK", problems=leaks)
    if missing:
        return out("GLOW_MISSING", problems=missing)
    if not glowed:
        # Armed stamps that were all throttled credit no glow to a graded stamp.
        return out("NO_ARMED", armed_but_throttled=len(throttled))
    return out("RATIONED", operator_eyeball_owed=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL, description=__doc__.split("\n", 1)[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snippet")
    sub.add_parser("dump")
    g = sub.add_parser("grade")
    g.add_argument("--state", required=True)
    g.add_argument("--log", required=True)
    g.add_argument("--state-ts", type=float)
    g.add_argument("--json", action="store_true")
    return p


def run(args: argparse.Namespace) -> int:
    if args.cmd == "snippet":
        print(RECORDER_SNIPPET)
        return 0
    if args.cmd == "dump":
        print(DUMP_SNIPPET)
        return 0
    state, log = _load(args.state), _load(args.log)
    ts = args.state_ts if args.state_ts is not None else Path(args.state).stat().st_mtime
    result = grade(state, log, ts)
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
