"""gated_g236_loadout_push.py - read-only grader for G2-36 (mid-game LCU item push).

G2-36 owes ONE piece of live evidence: the LCU agent's push log line for an
item set pushed from the in-game build switcher while a game is InProgress.
The render half and the generic-build path were confirmed live 2026-07-04
(LEDGER 779); no drain ever captured the push line.

What the mid-game push is (measured at source, s144 lane gated c41):

- The in-game switcher is the ITEM BUILD panel's build list
  (``web/js/panels/item_build.js`` ``_ibMaybeRenderBuilds`` /
  ``_ibOnRowClick`` / ``_ibPushItems``). A row click POSTs
  ``/api/loadout/apply`` with ``push_items: true`` and ``push_runes`` /
  ``push_summoners`` FALSE: runes and summoner spells are locked at game start
  (the panel's own comment), so the mid-game push is ITEMS ONLY by design.
- ``dashboard/routes_loadout.py`` ``_serve_loadout_apply_post`` queues the
  resolved ``apply_item_set`` command through the vision server's
  ``/lcu-cmd`` queue; ``tools/lcu_agent.py`` ``drain_once`` executes it and
  logs ``  [cmd] apply_item_set -> {result}`` (or ``  [cmd-exc] ...``) to
  ``logs/lcu_agent.log`` with the format ``%(asctime)s %(levelname)s
  %(message)s`` (local wall clock, no offset). A good result is
  ``{'ok': True, 'set_uid': 'RC-...', 'title': '...'}``.
- The dashboard logs only a FAILED enqueue (``loadout enqueue ...``); success
  leaves no RC-side line, so the agent log is the one push record.

Sub-commands (all READ-ONLY: no network, no LCU call, no write, no tick):

  state FILE
      Grade one saved ``/api/state`` JSON: IN_GAME iff ``lcu.phase`` is
      ``InProgress`` or ``liveclient`` is non-empty (the lane's in-game gate),
      else NOT_IN_GAME.
  log FILE --before-state F1 --after-state F2 [--champion NAME]
      The push window is [mtime(F1), mtime(F2)]: two ``/api/state`` files
      saved just before and just after the row click. Both must grade
      IN_GAME (else NOT_MID_GAME). Every ``[cmd]`` / ``[cmd-exc]`` line of the
      agent log inside the window is read; the ``apply_item_set`` lines are
      graded. Verdicts: PUSH_OK (at least one ``ok: True`` result whose
      ``set_uid`` starts with ``RC-``, and with ``RC-<norm(NAME)>-`` when
      ``--champion`` is given: the resolvers build the uid from
      ``coaches/loadout_resolver.py`` ``_norm``, lowercase with every
      non-alphanumeric dropped, so ``Kai'Sa`` is ``RC-kaisa-``),
      PUSH_FAILED (apply_item_set lines, none good), NO_PUSH (none in the
      window), NOT_MID_GAME, BAD_WINDOW (F2 older than F1).

Exit 0 = IN_GAME / PUSH_OK; 3 = any other verdict; 2 = an input file is
missing or unreadable.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# The verb the in-game switcher's /api/loadout/apply push resolves to
# (dashboard/routes_loadout.py item_cmd; pinned by the tests).
PUSH_VERB = "apply_item_set"
IN_GAME_PHASE = "InProgress"

# One agent log line: "<asctime> <LEVEL>   [cmd] <verb> -> <result repr>".
# asctime is logging's default "YYYY-MM-DD HH:MM:SS,mmm" (local time).
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(?P<ms>\d{3}) "
    r"(?P<level>[A-Z]+) +\[(?P<tag>cmd|cmd-exc)\] (?P<verb>\S+) -> (?P<result>.*)$")


def grade_state(state: Any) -> dict:
    """In-game gate over one saved /api/state envelope."""
    out: dict = {"verdict": "NOT_IN_GAME", "phase": None, "mode_key": None,
                 "game_time_s": None, "liveclient": False}
    if not isinstance(state, dict):
        return out
    lcu = state.get("lcu")
    phase = lcu.get("phase") if isinstance(lcu, dict) else None
    out["phase"] = phase if isinstance(phase, str) else None
    mk = state.get("mode_key")
    out["mode_key"] = mk if isinstance(mk, str) else None
    lc = state.get("liveclient")
    out["liveclient"] = isinstance(lc, dict) and bool(lc)
    if out["liveclient"]:
        gt = lc.get("game_time_s")
        if isinstance(gt, (int, float)) and not isinstance(gt, bool):
            out["game_time_s"] = float(gt)
    if out["phase"] == IN_GAME_PHASE or out["liveclient"]:
        out["verdict"] = "IN_GAME"
    return out


def _parse_result(text: str) -> Optional[dict]:
    try:
        val = ast.literal_eval(text.strip())
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return val if isinstance(val, dict) else None


def parse_log_lines(lines: list[str]) -> list[dict]:
    """Every [cmd] / [cmd-exc] line, with its local time and parsed result."""
    out = []
    for raw in lines:
        m = _LINE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        try:
            when = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        when = when.replace(microsecond=int(m.group("ms")) * 1000)
        out.append({"when": when, "tag": m.group("tag"), "verb": m.group("verb"),
                    "result": _parse_result(m.group("result")),
                    "result_text": m.group("result")})
    return out


def norm_champion(name: str) -> str:
    """Restates coaches/loadout_resolver.py ``_norm`` (pinned by the tests)."""
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def uid_prefix_for(champion: str) -> str:
    """The set_uid prefix the resolvers give this champion's item sets."""
    return f"RC-{norm_champion(champion)}-" if champion else ""


def _good_push(rec: dict, uid_prefix: str) -> bool:
    res = rec.get("result")
    if rec.get("tag") != "cmd" or not isinstance(res, dict) or res.get("ok") is not True:
        return False
    uid = res.get("set_uid")
    return isinstance(uid, str) and uid.startswith("RC-") and uid.startswith(uid_prefix)


def grade_log(records: list[dict], start: datetime, end: datetime,
              before: dict, after: dict, uid_prefix: str = "") -> dict:
    """Grade the agent log records inside [start, end] against the row."""
    in_window = [r for r in records if start <= r["when"] <= end]
    pushes = [r for r in in_window if r["verb"] == PUSH_VERB]
    out: dict = {
        "verdict": "NO_PUSH",
        "window": [start.isoformat(sep=" "), end.isoformat(sep=" ")],
        "before": before.get("verdict"), "after": after.get("verdict"),
        "pushes": [{"when": r["when"].isoformat(sep=" "), "tag": r["tag"],
                    "result": r["result_text"][:200]} for r in pushes],
        "other_cmds": sorted({r["verb"] for r in in_window if r["verb"] != PUSH_VERB}),
    }
    if end < start:
        out["verdict"] = "BAD_WINDOW"
    elif before.get("verdict") != "IN_GAME" or after.get("verdict") != "IN_GAME":
        out["verdict"] = "NOT_MID_GAME"
    elif any(_good_push(r, uid_prefix) for r in pushes):
        out["verdict"] = "PUSH_OK"
    elif pushes:
        out["verdict"] = "PUSH_FAILED"
    return out


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="sub", required=True)
    p_st = sub.add_parser("state")
    p_st.add_argument("file")
    p_lg = sub.add_parser("log")
    p_lg.add_argument("file")
    p_lg.add_argument("--before-state", required=True)
    p_lg.add_argument("--after-state", required=True)
    p_lg.add_argument("--champion", default="")
    for p in (p_st, p_lg):
        p.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.sub == "state":
            res = grade_state(_read_json(Path(args.file)))
            good = res["verdict"] == "IN_GAME"
        else:
            f1, f2 = Path(args.before_state), Path(args.after_state)
            before, after = grade_state(_read_json(f1)), grade_state(_read_json(f2))
            start = datetime.fromtimestamp(f1.stat().st_mtime)
            end = datetime.fromtimestamp(f2.stat().st_mtime)
            lines = Path(args.file).read_text(encoding="utf-8", errors="replace").splitlines()
            res = grade_log(parse_log_lines(lines), start, end, before, after,
                            uid_prefix_for(args.champion))
            good = res["verdict"] == "PUSH_OK"
    except (OSError, ValueError) as exc:
        print(f"unreadable input: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2, sort_keys=True))
    else:
        print(res["verdict"])
        for k in sorted(res):
            if k != "verdict":
                print(f"  {k}: {res[k]}")
    return 0 if good else 3


if __name__ == "__main__":
    sys.exit(main())
