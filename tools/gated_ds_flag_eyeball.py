"""gated_ds_flag_eyeball.py - read-only OFF/ON served-list diff for the DS eyeball rows.

One helper for the four GATE 2 DS flag rows whose headless half is DONE and
whose live half is a player's sanity read of the served list with a
DEFAULT-OFF seam turned ON (s144 lane gated c48):

- G2-43 RM-41  ``exclude_off_axis_items`` on POST /rank-assassin (strip seam).
- G2-44 RM-35  ``exclude_off_axis_items`` on POST /rank (carry; strip seam).
- G2-46 RM-36  ``apply_ad_axis_ability_damage`` on POST /rank (reorder seam).
- G2-47 RM-42  ``apply_passive_damage`` + ``apply_extra_shot_procs`` on
  POST /rank, ALWAYS TOGETHER (the row's own rule: the two flags model two
  halves of one event and are never flipped singly).

Facts that shape the check (measured at source, s144 lane gated c48):

- All four flags are parsed off the request body by the DS routes
  (``agents/daemon_slayer/server.py`` ``_route_rank`` and
  ``_route_rank_assassin``) and default OFF, and the RC clients
  (``core/daemon_slayer_client.py`` ``rank_for`` / ``rank_assassin_for``)
  emit them only when set. So the ON list is NEVER rendered on screen today:
  the row's question is a human judgement of a list the tool computes in the
  LIVE context (champion, level, owned items read off /api/state the way the
  Meta Build panel reads them - ``tools/gated_g238_top_pick_flip.py``
  ``panel_inputs``). The tool never decides "sane"; the operator does.
- A strip seam is invisible in the UI (an excluded item simply is not
  there), so the useful output is the list of what LEFT the top-N, which is
  exactly what a glance at the panel cannot show.
- The pair is the RAW route list for the live champion, level and owned items
  (with the carry chokepoint's ``fight_length`` allow-map value on /rank), not
  the Meta Build panel's plan: ``rank_for_primary_archetype`` also swaps in a
  squishy target for allow-mapped champions and filters the window after the
  call. So the OFF list need not equal what renders; the row grades the
  flag's DELTA in a live context, never the panel.
- A strip seam can only REMOVE candidates. When both captured pools are
  complete (fewer rows than requested), an ON row that is absent from the OFF
  pool is an ANOMALY, not a judgement call.

Sub-commands:

  capture --row ROW [--champion C --level N --items a,b --mode SR]
      NETWORK, compute only (GET /api/state on :8888 unless all four inputs
      are given - a partial override, --mode alone included, is refused -
      then two POSTs to the DS :8860 route with the same body, flag(s)
      OFF and ON; no RC or DS state write, no LCU call). Prints ONE pair line
      (JSON) on stdout; the caller redirects it to its own evidence file. The
      tool writes no file. For the drain session only, never PREP.

  grade PAIRS_JSONL --row ROW [--top N] [--json]
      OFFLINE. Reads pair lines, keeps those for ROW, and prints per champion
      what left the top-N, what entered it, and what moved. Verdicts:
      NEEDS_EYEBALL (coverage met, every graded pair live and well-formed, no
      anomaly: the lists are ready for the operator's read, which is the
      tick), INCOMPLETE (a required champion is missing, or no live pair),
      ANOMALY (a strip seam added a candidate, or a pair is malformed).
      A well-formed pair that is not evidence is rejected without being
      graded: no ``game_time_s`` (not live), a body mode other than SR (the
      rows are SR rows), or owned items not read off
      ``liveclient.owned_item_ids`` (``items_source`` other than
      "owned_item_ids": the panel then falls back to sources this tool does
      not replicate, ``tools/gated_g238_top_pick_flip.py`` ``panel_inputs``).
      There is no PASS verdict: the tool never ticks the row.

Exit 0 = NEEDS_EYEBALL (grade) or success (capture); 3 = INCOMPLETE / ANOMALY;
2 = input missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# Per-row contract. ``need`` is a list of champion groups; coverage needs at
# least one live pair from EVERY group. ``null_control`` champions are graded
# but required to be byte-identical when present (G2-46: Ezreal's only
# PHYSICAL row carries ap_pct_sum 200.0 and the term drops it).
ROWS: dict[str, dict[str, Any]] = {
    "G2-43": {"route": "/rank-assassin", "flags": ("exclude_off_axis_items",),
              "kind": "strip",
              "need": (("akali", "katarina", "fizz"), ("zed", "talon")),
              "null_control": ()},
    "G2-44": {"route": "/rank", "flags": ("exclude_off_axis_items",),
              "kind": "strip",
              "need": (("jhin", "jinx", "caitlyn", "twitch"),),
              "null_control": ()},
    "G2-46": {"route": "/rank", "flags": ("apply_ad_axis_ability_damage",),
              "kind": "reorder",
              "need": (("corki",),),
              "null_control": ("ezreal",)},
    "G2-47": {"route": "/rank",
              "flags": ("apply_passive_damage", "apply_extra_shot_procs"),
              "kind": "reorder",
              "need": (("akshan",), ("warwick", "gwen", "kogmaw")),
              "null_control": ()},
}

POOL_TOP = 200     # ask for the whole pool so a strip anomaly is decidable
DEFAULT_TOP = 8    # the served list length the panel shows
LIVE_ITEMS_SOURCE = "owned_item_ids"   # panel_inputs' only graded items source


def not_evidence(pair: dict) -> Optional[str]:
    """None when a well-formed pair is live SR panel-input evidence, else why.

    Checked after ``check_pair``. Every reason starts with "not " so the grade
    keeps these apart from malformed pairs (ANOMALY): a non-evidence pair
    leaves the row INCOMPLETE, it never raises a finding."""
    gt = pair.get("game_time_s")
    if not isinstance(gt, (int, float)) or isinstance(gt, bool):
        return "not live (no game_time_s)"
    mode = str((pair.get("body_off") or {}).get("mode") or "")
    if mode != "SR":
        return f"not SR (body mode {mode!r})"
    src = pair.get("items_source")
    if src != LIVE_ITEMS_SOURCE:
        return f"not panel items (items_source {src!r})"
    return None


def _norm(name: Any) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _rows_of(resp: Any) -> Optional[list[dict]]:
    """``{"ranked": [...]}`` or a bare list -> rows with a non-empty item_id."""
    ranked = resp.get("ranked") if isinstance(resp, dict) else resp
    if not isinstance(ranked, list):
        return None
    out = []
    for r in ranked:
        if isinstance(r, dict) and str(r.get("item_id") or "").strip():
            out.append(r)
    return out


def _raw_len(resp: Any) -> int:
    ranked = resp.get("ranked") if isinstance(resp, dict) else resp
    return len(ranked) if isinstance(ranked, list) else 0


def build_bodies(row: str, inputs: dict, *, top: int = POOL_TOP) -> tuple[dict, dict]:
    """The OFF body and the ON body: identical except the row's flag(s)."""
    spec = ROWS[row]
    off = {"champion": inputs["champion"], "level": int(inputs["level"]),
           "items": [str(i) for i in inputs.get("items") or []],
           "mode": str(inputs.get("mode") or "SR"), "top": int(top)}
    if spec["route"] == "/rank":
        # The carry chokepoint (core/daemon_slayer_client.py
        # rank_for_primary_archetype) forwards the per-champion allow-map
        # value; without it a Twitch / Jhin pair would grade a list the
        # coach never asks for.
        from core.ds_champion_fight_length import champion_fight_length
        fl = champion_fight_length(str(inputs["champion"]))
        if fl is not None:
            off["fight_length"] = float(fl)
    on = dict(off)
    for flag in spec["flags"]:
        on[flag] = True
    return off, on


def check_pair(pair: dict) -> Optional[str]:
    """None when the pair is well-formed for its row, else the reason."""
    row = pair.get("row")
    if row not in ROWS:
        return f"unknown row {row!r}"
    spec = ROWS[row]
    off, on = pair.get("body_off"), pair.get("body_on")
    if not isinstance(off, dict) or not isinstance(on, dict):
        return "missing body_off / body_on"
    if any(f in off for f in spec["flags"]):
        return "OFF body carries a row flag"
    if any(on.get(f) is not True for f in spec["flags"]):
        # G2-47: a single flag is a partial model, never graded.
        return "ON body lacks {}".format("+".join(spec["flags"]))
    rest = {k: v for k, v in on.items() if k not in spec["flags"]}
    if rest != off:
        return "ON body differs from OFF body beyond the row flag(s)"
    if _rows_of(pair.get("off")) is None or _rows_of(pair.get("on")) is None:
        return "missing off / on ranked rows"
    return None


def diff_pair(pair: dict, *, top: int = DEFAULT_TOP) -> dict:
    """What left the top-N, what entered it, what moved, and strip anomalies."""
    spec = ROWS[pair["row"]]
    off_rows, on_rows = _rows_of(pair["off"]) or [], _rows_of(pair["on"]) or []
    off_ids = [str(r["item_id"]) for r in off_rows]
    on_ids = [str(r["item_id"]) for r in on_rows]
    names = {str(r["item_id"]): str(r.get("item_name") or "") for r in off_rows + on_rows}
    off_top, on_top = off_ids[:top], on_ids[:top]
    left = [i for i in off_top if i not in on_top]
    entered = [i for i in on_top if i not in off_top]
    moved = [{"item_id": i, "from": off_top.index(i) + 1, "to": on_top.index(i) + 1}
             for i in on_top if i in off_top and off_top.index(i) != on_top.index(i)]
    asked = int((pair.get("body_off") or {}).get("top") or 0)
    # Count the RAW response rows: a dropped empty-id row must not make a full
    # (truncated) response look complete.
    complete = (bool(asked) and _raw_len(pair["off"]) < asked
                and _raw_len(pair["on"]) < asked)
    anomalies = []
    if spec["kind"] == "strip":
        if complete:
            added = [i for i in on_ids if i not in set(off_ids)]
            if added:
                anomalies.append("strip seam ADDED {}".format(",".join(added)))
        stripped = [i for i in off_ids if i not in set(on_ids)] if complete else None
    else:
        stripped = None
    return {"champion": pair.get("champion"), "level": pair.get("level"),
            "ts": pair.get("ts"), "game_time_s": pair.get("game_time_s"),
            "identical_top": off_top == on_top, "off_top": off_top, "on_top": on_top,
            "left_top": left, "entered_top": entered, "moved": moved,
            "stripped_pool": stripped, "pool_complete": complete,
            "names": {i: names.get(i, "") for i in set(off_top + on_top + (stripped or []))},
            "anomalies": anomalies}


def grade(pairs: list[dict], row: str, *, top: int = DEFAULT_TOP) -> dict:
    spec = ROWS[row]
    graded, rejected, anomalies = [], [], []
    for p in pairs:
        if not isinstance(p, dict) or p.get("row") != row:
            continue
        why = check_pair(p)
        if why:
            rejected.append({"ts": p.get("ts"), "champion": p.get("champion"), "why": why})
            continue
        why = not_evidence(p)
        if why:
            rejected.append({"ts": p.get("ts"), "champion": p.get("champion"), "why": why})
            continue
        d = diff_pair(p, top=top)
        if _norm(p.get("champion")) in spec["null_control"] and not d["identical_top"]:
            d["anomalies"].append("null control {} moved".format(p.get("champion")))
        anomalies.extend("{}: {}".format(p.get("champion"), a) for a in d["anomalies"])
        graded.append(d)
    seen = {_norm(d["champion"]) for d in graded}
    missing = [list(g) for g in spec["need"] if not seen.intersection(g)]
    malformed = [r for r in rejected if not r["why"].startswith("not ")]
    if anomalies or malformed:
        verdict = "ANOMALY"
    elif missing or not graded:
        verdict = "INCOMPLETE"
    else:
        verdict = "NEEDS_EYEBALL"
    return {"row": row, "verdict": verdict, "graded": graded, "rejected": rejected,
            "missing_groups": missing, "anomalies": anomalies,
            "flags": list(spec["flags"]), "route": spec["route"]}


def capture(row: str, *, champion: Optional[str] = None, level: Optional[int] = None,
            items: Optional[list[str]] = None, mode: Optional[str] = None,
            state_fn: Optional[Callable[[], dict]] = None,
            post_fn: Optional[Callable[[str, dict], Optional[dict]]] = None,
            now: Optional[str] = None) -> dict:
    """One OFF/ON pair in the live context. Compute only."""
    overrides = [v is not None for v in (champion, level, items, mode)]
    if any(overrides):
        # Any hand-given input means the pair is NOT the live context: it is
        # stamped "args" with no game_time_s, so grade rejects it as not live.
        # A partial override is refused outright rather than mixed with the
        # live state (a Zed pair built from an Akali game's level and items
        # would otherwise pose as live coverage; a hand-given --mode SR would
        # dress a live ARAM pair up as an SR one).
        if not all(overrides):
            raise ValueError("give all of --champion --level --items --mode, or none")
        source, game_time, items_source = "args", None, "args"
    else:
        from tools.gated_g238_top_pick_flip import _get_state, panel_inputs
        inp = panel_inputs((state_fn or _get_state)())
        source, game_time = "api_state", inp.get("game_time_s")
        champion, level, items = inp["champion"], inp["level"], inp["items"]
        mode, items_source = inp["mode"], inp["items_source"]
    inputs = {"champion": champion, "level": level, "items": items, "mode": mode or "SR"}
    off_body, on_body = build_bodies(row, inputs)
    if post_fn is None:
        from core.daemon_slayer_client import _post_json

        def post_fn(path: str, body: dict) -> Optional[dict]:
            return _post_json(path, body, timeout=10.0)
    path = ROWS[row]["route"]
    off, on = post_fn(path, off_body), post_fn(path, on_body)
    return {"ts": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "row": row, "route": path, "source": source, "champion": champion,
            "level": level, "items": list(items), "mode": inputs["mode"],
            "items_source": items_source,
            "game_time_s": game_time, "body_off": off_body, "body_on": on_body,
            "off": off, "on": on, "ok": off is not None and on is not None}


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _print_grade(res: dict) -> None:
    print("{} {} via {} flags={}".format(res["row"], res["verdict"], res["route"],
                                       "+".join(res["flags"])))
    for d in res["graded"]:
        nm = d["names"]
        print("- {} L{} gt={} identical_top={}".format(d["champion"], d["level"],
                                                  d["game_time_s"], d["identical_top"]))
        print("  left top: {}".format(", ".join("{} {}".format(i, nm.get(i, "")) for i in d["left_top"])))
        print("  entered top: {}".format(", ".join("{} {}".format(i, nm.get(i, "")) for i in d["entered_top"])))
        if d["stripped_pool"] is not None:
            print("  stripped from pool: {}".format(len(d["stripped_pool"])))
    for r in res["rejected"]:
        print("- rejected {} {}: {}".format(r["ts"], r["champion"], r["why"]))
    if res["missing_groups"]:
        print("missing one of: {}".format("; ".join("/".join(g) for g in res["missing_groups"])))
    for a in res["anomalies"]:
        print(f"ANOMALY {a}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--row", required=True, choices=sorted(ROWS))
    c.add_argument("--champion")
    c.add_argument("--level", type=int)
    c.add_argument("--items", help="comma list of owned item ids")
    c.add_argument("--mode")
    g = sub.add_parser("grade")
    g.add_argument("pairs")
    g.add_argument("--row", required=True, choices=sorted(ROWS))
    g.add_argument("--top", type=int, default=DEFAULT_TOP)
    g.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "capture":
        items = None if args.items is None else [s for s in args.items.split(",") if s.strip()]
        try:
            rec = capture(args.row, champion=args.champion, level=args.level,
                          items=items, mode=args.mode)
        except Exception as e:  # noqa: BLE001
            print(f"capture failed: {e}", file=sys.stderr)
            return 2
        if not rec["ok"]:
            # Engine down: keep the record OFF stdout so a redirect into the
            # pairs file does not turn an outage into an ANOMALY finding.
            print("capture failed: DS route gave no response", file=sys.stderr)
            return 2
        print(json.dumps(rec, sort_keys=True))
        return 0
    path = Path(args.pairs)
    try:
        pairs = _load_jsonl(path)
    except (OSError, ValueError) as e:
        print(f"cannot read {path}: {e}", file=sys.stderr)
        return 2
    res = grade(pairs, args.row, top=args.top)
    if args.json:
        print(json.dumps(res, sort_keys=True))
    else:
        _print_grade(res)
    return 0 if res["verdict"] == "NEEDS_EYEBALL" else 3


if __name__ == "__main__":
    raise SystemExit(main())
