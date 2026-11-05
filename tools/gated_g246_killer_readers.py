"""gated_g246_killer_readers.py - grade captured Live Client payloads for G2-46 (RM-307).

G2-46 asks which player field the Live Client ``events.Events[].KillerName``
actually carries: a CHAMPION name or a PLAYER name. One real capture answers it
permanently. The row names two readers; there are FIVE, and they do not all read
the same event type:

  reader                 impl    scope (EventName)        matches KillerName against
  dashboard_liveclient   mirror  objective events         raw championName only
  decision_detector      real    ChampionKill             summonerName, else riotIdGameName
  live_event_deriver     real    objective events         championName or raw identities
  death_recap            real    ChampionKill             player names, then a unique champion
  snapshot_normalizer    mirror  DragonKill (not Elder)   folded player + champion names

``real`` = the production function is called on the capture
(``core.decision_detector._team_of``, ``core.live_event_deriver.derive_events``,
``core.death_recap.resolve_player``). ``mirror`` = the module cannot be imported
without a vision token (``dashboard/_liveclient.py``, ``game_reader/snapshot_normalizer.py``
both pull ``core.vision_token``), so its rule is re-stated here and pinned against
its source by ``tests/test_gated_g246_killer_readers.py``. The dashboard mirror is
the one ``tools/gated_lx02_payload_check.py`` already carries (``reader_sets`` /
``reader_team``), reused, not copied.

Because the readers split by event type, the row's premise ("the SAME field,
at most one can be right") holds only if ChampionKill and the objective events
carry the SAME form. The tool records the form PER CLASS and says which.

It is READ-ONLY: it parses the capture files and prints. No network call, no
write, no tick. NO NAME IS EVER PRINTED (RM-906): names are reduced to forms by
``gated_lx02_payload_check.name_form``; only counts, fixed reader names and the
fixed in-scope EventNames reach the output.

VERDICTS (stated before any game):
  - per reader, over its in-scope events whose killer is a roster member
    (form ``champion`` or ``player``) and where the reader could identify the
    active player when it needs to: RESOLVES (every one put on a side / row),
    BLIND (none), PARTIAL, NO_DATA. ``no_self``, ``ambiguous`` (a mirror
    champion) and ``both`` forms are counted, never graded.
  - per class (``ChampionKill``, ``objective``): CHAMPION / PLAYER / MIXED /
    NONE over the roster-member killer forms.
  - ``g246.verdict``: NO_RESULT (capture set not VALID: synthetic, duplicate,
    fewer than 2 payloads, a relay ts span under 30 s, or fewer than 2
    distinct ``gameTime`` values), SETTLED (both
    classes CHAMPION or PLAYER), MIXED (a class carries both forms), PARTIAL
    (one class still NONE). ``row_premise``: SAME_FORM / FORM_BY_EVENT.
    ``silent_features`` (epic_buff_callouts, dragon_soul_callout and the soul
    suppression in _dynamic_epic_callouts all read the dashboard's
    ``objective_events.killer_team``, dragon / baron takes only): graded on the
    dashboard reader over DragonKill / BaronKill roster-member killers only
    (``dashboard_epic_counts``) - CONFIRMED when BLIND there, REFUTED when it
    RESOLVES, else UNDETERMINED (a grub-only capture cannot decide it).

USAGE (the capture is the drain's act - the LX-02 relay captures serve both rows)
    python tools/gated_g246_killer_readers.py ops/runtime/liveclient_captures/ --json

Exit 0 = SETTLED, 3 = any other verdict (record and re-capture or file),
2 = nothing loadable at the path.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import death_recap, decision_detector, live_event_deriver  # noqa: E402
from core.live_event_deriver import OBJECTIVE_EVENT_NAMES  # noqa: E402
from tools import gated_lx02_payload_check as lx02  # noqa: E402

READERS = {
    "dashboard_liveclient": "mirror",
    "decision_detector": "real",
    "live_event_deriver": "real",
    "death_recap": "real",
    "snapshot_normalizer": "mirror",
}
MIN_SPAN_S = 30.0
MEMBER_FORMS = ("champion", "player")
# The three callouts silent_features speaks for read dragon / baron takes only
# (core/event_callouts.py _epic_kind / _elemental_drake_counts); a grub take
# feeds voidgrub_callout instead and does not decide them.
EPIC_EVENTS = ("DragonKill", "BaronKill")
_NAME_KEYS = ("championName", "summonerName", "riotIdGameName", "riotId",
              "riotIdPlusTagLine", "team")


def _sn_side_keys(rows: list) -> set:
    """Mirror of game_reader/snapshot_normalizer.py ``_side_keys``."""
    keys = set()
    for p in rows:
        for field in ("riotIdGameName", "summonerName", "riotIdPlusTagLine",
                      "riotId", "championName"):
            v = p.get(field)
            v = lx02._norm(v) if isinstance(v, str) else ""
            if v:
                keys.add(v)
    return keys


def sn_resolves(killer: Any, rows: list) -> bool:
    """Mirror of the RM-236(b) ``_dragon_tally`` attribution: folded KillerName
    in exactly one side's keys, keys shared by both sides dropped. The side is
    split on ``team`` here; the normalizer splits on my row's team, which gives
    the same two sets whenever every row carries ORDER / CHAOS."""
    order = _sn_side_keys([p for p in rows if p.get("team") == "ORDER"])
    chaos = _sn_side_keys([p for p in rows if p.get("team") == "CHAOS"])
    shared = order & chaos
    k = lx02._norm(killer) if isinstance(killer, str) else ""
    return bool(k) and (k in order - shared or k in chaos - shared)


def _deriver_teams(payload: dict) -> tuple[bool, dict]:
    """(self_identified, {EventID: killer_team}) from the REAL derive_events,
    fed the capture against a copy of itself with an empty event list, so every
    objective in the capture is new to it. No other field differs, so no death,
    level or item event is emitted."""
    prev = copy.deepcopy(payload)
    if isinstance(prev.get("events"), dict):
        prev["events"]["Events"] = []
    cp = live_event_deriver._players(payload)
    active = live_event_deriver._active_ids(payload)
    me_ok = any(active & live_event_deriver._identities(r)
                and isinstance(r.get("team"), str) for r in cp.values())
    teams: dict = {}
    for ev in live_event_deriver.derive_events(prev, payload, completed_ids=()):
        if ev.get("kind") == live_event_deriver.OBJECTIVE_TAKEN:
            teams[ev.get("event_id")] = ev.get("killer_team")
    return me_ok, teams


def _grade(t: dict) -> str:
    ok, bad = t.get("resolved", 0), t.get("unresolved", 0)
    if not ok and not bad:
        return "NO_DATA"
    if not bad:
        return "RESOLVES"
    if not ok:
        return "BLIND"
    return "PARTIAL"


def _class_form(forms: dict) -> str:
    c, p = forms.get("champion", 0), forms.get("player", 0)
    if c and p:
        return "MIXED"
    if c:
        return "CHAMPION"
    if p:
        return "PLAYER"
    return "NONE"


def _sane(payload: dict) -> dict:
    """A shallow copy whose allPlayers is a list of dicts and whose events is a
    dict. The lx02 helpers iterate ``allPlayers`` unguarded (a non-list raises
    there); a real wire payload always passes through unchanged."""
    out = dict(payload)
    rows = out.get("allPlayers")
    rows = [dict(r) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    for r in rows:
        # a non-string name field cannot match on the wire; an unhashable one
        # would raise inside the lx02 set builders
        for k in _NAME_KEYS:
            if k in r and not isinstance(r[k], str):
                r[k] = None
    out["allPlayers"] = rows
    if not isinstance(out.get("events"), dict):
        out["events"] = {}
    if not isinstance(out.get("activePlayer"), dict):
        out["activePlayer"] = {}
    return out


def check(loaded: list[tuple[dict, Optional[float], str]]) -> dict:
    """Summarise the loaded captures. Never returns a raw name."""
    payloads = [_sane(p) for p, _ts, _sha in loaded]
    shas = [s for _p, _ts, s in loaded]
    tss = [t for _p, t, _s in loaded if t is not None]
    span = (max(tss) - min(tss)) if tss else None
    gts = [lx02._num(p["gameData"].get("gameTime")) if isinstance(p.get("gameData"), dict)
           else None for p in payloads]
    out: dict = {
        "payloads": len(payloads),
        "synthetic": sum(1 for p in payloads if lx02._looks_synthetic(p)),
        "duplicates": len(shas) - len(set(shas)),
        "relay_ts_span_s": span,
        "distinct_game_times": len({t for t in gts if t is not None}),
        "game_time_max": max((t for t in gts if t is not None), default=None),
        "game_modes": sorted({str(p["gameData"].get("gameMode"))
                              if isinstance(p.get("gameData"), dict) else "None"
                              for p in payloads}),
    }
    # two files of one relay body re-stamped with a new ts are one read: each
    # capture must also be a distinct game moment
    valid = (out["synthetic"] == 0 and out["duplicates"] == 0
             and len(payloads) >= 2 and span is not None and span >= MIN_SPAN_S
             and out["distinct_game_times"] >= 2)
    out["valid"] = valid
    tally = {r: {} for r in READERS}
    epic: dict = {}
    selfs = dict.fromkeys(("dashboard_liveclient", "decision_detector",
                           "live_event_deriver"), 0)
    forms_by_class: dict = {"ChampionKill": {}, "objective": {}}
    forms_by_event: dict = {}
    for p in payloads:
        champs, players = lx02._roster(p)
        rows = decision_detector._all_players(p)
        dash_me, enemy, ally = lx02.reader_sets(p)
        dd_self = decision_detector._team_of(rows, decision_detector._self_name(p))
        led_me, led_teams = _deriver_teams(p)
        selfs["dashboard_liveclient"] += int(dash_me)
        selfs["decision_detector"] += int(dd_self is not None)
        selfs["live_event_deriver"] += int(led_me)
        for e in lx02._events(p):
            en = e.get("EventName")
            if not isinstance(en, str):
                continue
            is_obj = en in OBJECTIVE_EVENT_NAMES
            if not (is_obj or en == "ChampionKill") or "KillerName" not in e:
                continue
            killer = e.get("KillerName")
            fm = lx02.name_form(killer, champs, players)
            lx02._bump(forms_by_class, "objective" if is_obj else "ChampionKill", fm)
            lx02._bump(forms_by_event, en, fm)
            member = fm in MEMBER_FORMS

            def mark(reader: str, outcome: str, member: bool = member) -> None:
                if outcome in ("resolved", "unresolved") and not member:
                    outcome = "not_member_" + outcome
                lx02._bump(tally[reader], outcome)

            if is_obj:
                if not dash_me:
                    mark("dashboard_liveclient", "no_self")
                else:
                    side = lx02.reader_team(killer, enemy, ally)
                    oc = ("ambiguous" if side == "ambiguous"
                          else "resolved" if side in ("ally", "enemy") else "unresolved")
                    mark("dashboard_liveclient", oc)
                    if en in EPIC_EVENTS and member:
                        lx02._bump(epic, oc)
                eid = live_event_deriver._int(e.get("EventID"))
                if eid is None or eid not in led_teams:
                    mark("live_event_deriver", "not_emitted")
                elif not led_me:
                    mark("live_event_deriver", "no_self")
                else:
                    mark("live_event_deriver",
                         "resolved" if led_teams[eid] in ("ally", "enemy") else "unresolved")
                dt = e.get("DragonType")
                if en == "DragonKill" and not (isinstance(dt, str)
                                               and dt.strip().lower() == "elder"):
                    mark("snapshot_normalizer",
                         "resolved" if sn_resolves(killer, rows) else "unresolved")
            else:
                if dd_self is None:
                    mark("decision_detector", "no_self")
                else:
                    mark("decision_detector",
                         "resolved" if decision_detector._team_of(rows, killer)
                         else "unresolved")
                mark("death_recap",
                     "resolved" if death_recap.resolve_player(killer, rows) is not None
                     else "unresolved")
    out["forms_by_class"] = forms_by_class
    out["forms_by_event"] = forms_by_event
    out["self_identified"] = selfs
    out["readers"] = {r: {"impl": READERS[r], "counts": tally[r],
                          "verdict": _grade(tally[r])} for r in READERS}
    ck = _class_form(forms_by_class["ChampionKill"])
    ob = _class_form(forms_by_class["objective"])
    g = {"championkill_form": ck, "objective_form": ob}
    if not valid:
        g["verdict"] = "NO_RESULT"
    elif "MIXED" in (ck, ob):
        g["verdict"] = "MIXED"
    elif "NONE" in (ck, ob):
        g["verdict"] = "PARTIAL"
    else:
        g["verdict"] = "SETTLED"
    g["row_premise"] = (None if g["verdict"] != "SETTLED"
                        else "SAME_FORM" if ck == ob else "FORM_BY_EVENT")
    out["dashboard_epic_counts"] = epic
    dash = _grade(epic)
    g["silent_features"] = ("UNDETERMINED" if not valid
                            else "CONFIRMED" if dash == "BLIND"
                            else "REFUTED" if dash == "RESOLVES" else "UNDETERMINED")
    g["blind_readers"] = sorted(r for r, v in out["readers"].items()
                                if v["verdict"] == "BLIND")
    out["g246"] = g
    return out


def render(s: dict) -> str:
    g = s["g246"]
    lines = [
        f"payloads={s['payloads']} synthetic={s['synthetic']} duplicates={s['duplicates']} "
        f"relay_ts_span_s={s['relay_ts_span_s']} valid={s['valid']}",
        f"g246 verdict={g['verdict']} championkill_form={g['championkill_form']} "
        f"objective_form={g['objective_form']} row_premise={g['row_premise']} "
        f"silent_features={g['silent_features']} blind_readers={','.join(g['blind_readers'])}",
        "forms_by_class=" + json.dumps(s["forms_by_class"], sort_keys=True),
        "self_identified=" + json.dumps(s["self_identified"], sort_keys=True),
        "dashboard_epic_counts=" + json.dumps(s["dashboard_epic_counts"], sort_keys=True),
    ]
    for r, v in s["readers"].items():
        lines.append(f"reader {r} ({v['impl']}) verdict={v['verdict']} counts="
                     + json.dumps(v["counts"], sort_keys=True))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Grade captured Live Client payloads for G2-46 (read-only).")
    ap.add_argument("path", help="a captured allgamedata JSON file or a directory of them")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    p = Path(args.path)
    if not p.exists():
        print(f"no such path: {p}", file=sys.stderr)
        return 2
    loaded = lx02.load(p)
    if not loaded:
        print(f"no loadable payload at: {p}", file=sys.stderr)
        return 2
    s = check(loaded)
    print(json.dumps(s, indent=2, sort_keys=True) if args.json else render(s))
    return 0 if s["g246"]["verdict"] == "SETTLED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
