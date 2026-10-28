"""gated_lx02_payload_check.py - grade captured Live Client payloads for the LX-02 drain.

LX-02 (RM-601 / RM-602) asks three things of ONE real ``/liveclientdata/allgamedata``
payload: does ``tools/liveclient_shape_audit.py`` run clean on it, does a real
``HordeKill`` event carry the fields the synthetic fixture
(``tests/fixtures/liveclient/allgamedata_synthetic_rm601.json``) models, and does
``KillerName`` carry a CHAMPION name or a PLAYER name. The last one decides
RM-673: ``dashboard/_liveclient.py`` matches an objective's ``KillerName``
against champion names only, while ``game_reader/snapshot_normalizer.py``
``_side_keys`` matches player names AND champion names. The same capture also
answers RM-674 (does the wire say ``FirstBlood`` or ``FirstBloodKill``) and the
LX-07 name form. Answering all of that by hand means walking the event list
per pass; this tool prints it in ONE command.

It is READ-ONLY: it parses the capture files and prints. It never writes,
moves, locks or deletes a capture, it makes no network call, and it never
ticks a row - its output is the INPUT to the four-part evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. A hand-built
payload passes these checks just as well; that is the substitution the LX-02
row names, and why a real game's capture is the only thing that closes it.

NO NAME IS EVER PRINTED (RM-906): every name field is reduced to its FORM
(``champion`` / ``player`` / ``both`` / ``nonplayer`` / ``unmapped`` /
``empty``) against the same payload's ``allPlayers`` roster, and the shape
audit's type-mismatch examples (which quote raw values) are cut off. Event
names, game modes and key names ARE printed verbatim: on a real wire payload
they are fixed Riot strings, so the output is safe to paste into a tracked
file; on a hand-edited file it is only as safe as those strings.

WHAT IT REPORTS:
  - payloads loaded, how many look synthetic (a ``_comment`` saying SYNTHETIC,
    or every roster ``riotIdGameName`` starting with ``Synthetic``), how many
    are byte-identical duplicates, the game modes, the max ``gameTime``, the
    events per payload, and the relay wrapper ``ts`` span when present.
  - ``name_forms``: per EventName, per name field (KillerName, VictimName,
    Recipient, Acer, Assisters[]), the count of each form.
  - ``rm673``: the KillerName forms over the objective events
    (``core.live_event_deriver.OBJECTIVE_EVENT_NAMES``), how many of the
    ``champion``-form killers equal a roster ``championName`` EXACTLY (the
    ``dashboard/_liveclient.py`` rule: a raw ``in`` test, no case fold, no tag
    strip), the killer_team that reader would give each objective row
    (``reader_sets`` / ``reader_team``: its self-identification and its
    champion sets, plus ``ambiguous`` for a mirror champion), how many
    payloads self-identify, and a verdict: PLAYER_NAME (RM-673 confirmed),
    CHAMPION_NAME (every killer an exact champion name AND the reader puts
    every row on a side: RM-673 refuted), CHAMPION_NAME_INEXACT (champion
    names that only match after the fold, so ``_liveclient.py`` still reads
    ``unknown``: RM-673 confirmed on that reader), CHAMPION_NAME_READER_FAILS
    (exact champion names, but the reader still reads ``unknown`` or a mirror
    in this capture: the name premise is refuted, the reader is not cleared),
    MIXED (champion forms beside ANY other form: player, unmapped, nonplayer,
    empty or both), or NO_RESULT (no objective killer in champion or player
    form).
  - ``rm674``: every EventName that reads ``firstblood`` once lowercased and
    stripped of underscores, and a verdict:
    FIRSTBLOOD / FIRSTBLOODKILL / BOTH / OTHER (a FirstBlood-like name that
    is neither) / NO_RESULT.
  - ``horde``: HordeKill count, the key-set difference against the fixture's
    HordeKill keys, the observed JSON types of every key against the
    fixture's own type for it, and a verdict MATCH (same keys, one type per
    key, equal to the fixture's) / DIFFERS / NO_RESULT.
  - ``shape_audit``: the three ``liveclient_shape_audit.audit`` lists, with
    the type-mismatch examples dropped.

USAGE (the capture is the drain's act; this tool only reads it)
    python tools/gated_lx02_payload_check.py ops/runtime/liveclient_captures/
    python tools/gated_lx02_payload_check.py <capture.json> --json

Exit 2 = nothing loadable at the path (no file, no ``*.json``, no payload).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.live_event_deriver import OBJECTIVE_EVENT_NAMES  # noqa: E402
from tools import liveclient_shape_audit  # noqa: E402

FIXTURE = _ROOT / "tests" / "fixtures" / "liveclient" / "allgamedata_synthetic_rm601.json"
NAME_FIELDS = ("KillerName", "VictimName", "Recipient", "Acer")
LIST_NAME_FIELDS = ("Assisters",)
PLAYER_FIELDS = ("riotIdGameName", "summonerName", "riotIdPlusTagLine", "riotId")
FORMS = ("champion", "player", "both", "nonplayer", "unmapped", "empty")
# A non-roster killer (minion, turret, jungle monster) reads like
# ``Minion_T100L1S04N0003`` / ``Turret_T2_L_03_A`` / ``SRU_Baron12.1.1``.
_NONPLAYER = re.compile(r"^[A-Za-z]+_")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except OverflowError:
        return None
    return f if math.isfinite(f) else None


def _norm(name: Any) -> str:
    """Same rule as snapshot_normalizer._normalize_name: drop the tag, lower."""
    if not isinstance(name, str) or not name:
        return ""
    return name.split("#")[0].strip().lower()


def load(path: Path) -> list[tuple[dict, Optional[float], str]]:
    """(payload, wrapper ts or None, sha256 of the file bytes) per capture.

    Same unwrap rule as liveclient_shape_audit.load_payloads: a ``{"data":
    {...}}`` relay wrapper is opened; unreadable files are skipped.
    """
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    out: list[tuple[dict, Optional[float], str]] = []
    for f in files:
        try:
            raw = f.read_bytes()
            obj = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            continue
        ts = None
        if (isinstance(obj, dict) and "gameData" not in obj
                and isinstance(obj.get("data"), dict)):
            ts = _num(obj.get("ts"))
            obj = obj["data"]
        if isinstance(obj, dict):
            out.append((obj, ts, hashlib.sha256(raw).hexdigest()))
    return out


def _roster(payload: dict) -> tuple[set, set]:
    champs: set = set()
    players: set = set()
    for p in payload.get("allPlayers") or []:
        if not isinstance(p, dict):
            continue
        c = _norm(p.get("championName"))
        if c:
            champs.add(c)
        for k in PLAYER_FIELDS:
            v = _norm(p.get(k))
            if v:
                players.add(v)
    return champs, players


def name_form(name: Any, champs: set, players: set) -> str:
    """The FORM of one name field against the payload's own roster."""
    if not isinstance(name, str) or not name.strip():
        return "empty"
    n = _norm(name)
    in_c, in_p = n in champs, n in players
    if in_c and in_p:
        return "both"
    if in_c:
        return "champion"
    if in_p:
        return "player"
    if _NONPLAYER.match(name.strip()):
        return "nonplayer"
    return "unmapped"


def _looks_synthetic(payload: dict) -> bool:
    if "SYNTHETIC" in str(payload.get("_comment", "")).upper():
        return True
    names = [p.get("riotIdGameName") for p in payload.get("allPlayers") or []
             if isinstance(p, dict)]
    return bool(names) and all(isinstance(n, str) and n.startswith("Synthetic")
                               for n in names)


def _events(payload: dict) -> list:
    ev = (payload.get("events") or {}).get("Events") if isinstance(
        payload.get("events"), dict) else None
    return [e for e in ev if isinstance(e, dict)] if isinstance(ev, list) else []


def _bump(d: dict, *keys: str) -> None:
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = d.get(keys[-1], 0) + 1


def fixture_horde_event(fixture: Path = FIXTURE) -> dict:
    """The first HordeKill event the synthetic fixture models ({} if none)."""
    obj = json.loads(fixture.read_text(encoding="utf-8"))
    for e in _events(obj):
        if e.get("EventName") == "HordeKill":
            return e
    return {}


def fixture_horde_keys(fixture: Path = FIXTURE) -> set:
    """The key set the synthetic fixture models for a HordeKill event."""
    return set(fixture_horde_event(fixture))


def _jtype(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "null" if v is None else type(v).__name__


def reader_sets(payload: dict) -> tuple[bool, set, set]:
    """(self_identified, enemy_set, ally_set) by the dashboard/_liveclient.py rule.

    That reader finds "me" as the FIRST ``allPlayers`` row whose raw
    ``summonerName`` equals ``activePlayer.summonerName`` (no fold); with no
    match both sets stay empty. The sets hold raw ``championName`` of rows
    with a truthy ``team``, split on my row's ``team``. Kept in step with that
    reader by hand: importing it pulls core.vision_token, which refuses to
    load without a configured token.
    """
    ap = payload.get("activePlayer") if isinstance(payload.get("activePlayer"), dict) else {}
    me_name = ap.get("summonerName", "")
    rows = [p for p in payload.get("allPlayers") or [] if isinstance(p, dict)]
    me = next((p for p in rows if p.get("summonerName") == me_name), None)
    if me is None:
        return False, set(), set()
    my_team = me.get("team")
    enemy = {p.get("championName", "") for p in rows
             if p.get("team") and p.get("team") != my_team}
    ally = {p.get("championName", "") for p in rows
            if p.get("team") and p.get("team") == my_team}
    return True, {c for c in enemy if c}, {c for c in ally if c}


def reader_team(killer: Any, enemy: set, ally: set) -> str:
    """The reader's killer_team, plus ``ambiguous`` for a mirror champion
    (the reader checks enemy first, so it would say ``enemy`` - wrong for
    the ally who carries the same champion)."""
    if not isinstance(killer, str):
        return "unknown"
    if killer in enemy and killer in ally:
        return "ambiguous"
    if killer in enemy:
        return "enemy"
    if killer in ally:
        return "ally"
    return "unknown"


def _rm673(forms: dict, champion_exact: int, reader: dict) -> str:
    c = forms.get("champion", 0)
    p = forms.get("player", 0)
    # CHAMPION_NAME closes RM-673 as a non-defect, so it needs EVERY objective
    # killer in champion form: any other form beside champion names (unmapped,
    # nonplayer, empty, both - each a row _liveclient.py reads "unknown")
    # reads MIXED instead
    if c and sum(forms.values()) != c:
        return "MIXED"
    if p:
        return "PLAYER_NAME"
    if c:
        if champion_exact != c:
            return "CHAMPION_NAME_INEXACT"
        # the wire form is right, but the reader still fails on this capture
        # (no self-identification, or a mirror champion)
        if reader.get("unknown", 0) or reader.get("ambiguous", 0):
            return "CHAMPION_NAME_READER_FAILS"
        return "CHAMPION_NAME"
    return "NO_RESULT"


def check(loaded: list[tuple[dict, Optional[float], str]],
          fixture: Path = FIXTURE) -> dict:
    """Summarise the loaded captures. Never returns a raw name."""
    payloads = [p for p, _ts, _sha in loaded]
    shas = [s for _p, _ts, s in loaded]
    tss = [t for _p, t, _s in loaded if t is not None]
    out: dict = {
        "payloads": len(payloads),
        "synthetic": sum(1 for p in payloads if _looks_synthetic(p)),
        "duplicates": len(shas) - len(set(shas)),
        "game_modes": sorted({str((p.get("gameData") or {}).get("gameMode"))
                              for p in payloads}),
        "game_time_max": max((t for t in (_num((p.get("gameData") or {}).get("gameTime"))
                                          for p in payloads) if t is not None),
                             default=None),
        "events_per_payload": [len(_events(p)) for p in payloads],
        "relay_ts_span_s": (max(tss) - min(tss)) if tss else None,
    }
    forms: dict = {}
    obj_forms: dict = {}
    first_blood: set = set()
    want_event = fixture_horde_event(fixture)
    want = set(want_event)
    want_types = {k: _jtype(v) for k, v in want_event.items()}
    horde = {"count": 0, "missing_keys": set(), "extra_keys": set(), "types": {}}
    champion_exact = 0
    reader: dict = {}
    self_identified = 0
    for p in payloads:
        champs, players = _roster(p)
        me_ok, enemy, ally = reader_sets(p)
        self_identified += int(me_ok)
        # _liveclient.py builds its sets only from players with a team
        raw_champs = {pl.get("championName") for pl in p.get("allPlayers") or []
                      if isinstance(pl, dict) and pl.get("team")
                      and isinstance(pl.get("championName"), str)}
        for e in _events(p):
            en = e.get("EventName")
            en = en if isinstance(en, str) else "<non-string>"
            if "firstblood" in en.lower().replace("_", ""):
                first_blood.add(en)
            for f in NAME_FIELDS:
                if f in e:
                    fm = name_form(e.get(f), champs, players)
                    _bump(forms, en, f, fm)
                    if f == "KillerName" and en in OBJECTIVE_EVENT_NAMES:
                        _bump(obj_forms, fm)
                        _bump(reader, reader_team(e.get(f), enemy, ally))
                        if fm == "champion" and e.get(f) in raw_champs:
                            champion_exact += 1
            for f in LIST_NAME_FIELDS:
                if isinstance(e.get(f), list):
                    for n in e[f]:
                        _bump(forms, en, f + "[]", name_form(n, champs, players))
            if en == "HordeKill":
                horde["count"] += 1
                horde["missing_keys"] |= want - set(e)
                horde["extra_keys"] |= set(e) - want
                for k in sorted(e):
                    _bump(horde["types"], k, _jtype(e[k]))
    out["name_forms"] = forms
    out["rm673"] = {"objective_killer_forms": obj_forms,
                    "champion_exact": champion_exact,
                    "reader_killer_team": reader,
                    "reader_self_identified": self_identified,
                    "verdict": _rm673(obj_forms, champion_exact, reader)}
    fb = sorted(first_blood)
    if not fb:
        fb_verdict = "NO_RESULT"
    elif fb == ["FirstBlood"]:
        fb_verdict = "FIRSTBLOOD"
    elif fb == ["FirstBloodKill"]:
        fb_verdict = "FIRSTBLOODKILL"
    elif "FirstBlood" in fb and "FirstBloodKill" in fb:
        fb_verdict = "BOTH"
    else:
        fb_verdict = "OTHER"
    out["rm674"] = {"first_blood_event_names": fb, "verdict": fb_verdict}
    if not horde["count"]:
        h_verdict = "NO_RESULT"
    elif horde["missing_keys"] or horde["extra_keys"] or any(
            set(v) != {want_types.get(k)} for k, v in horde["types"].items()):
        h_verdict = "DIFFERS"
    else:
        h_verdict = "MATCH"
    out["horde"] = {
        "count": horde["count"],
        "fixture_keys": sorted(want),
        "fixture_types": want_types,
        "missing_keys": sorted(horde["missing_keys"]),
        "extra_keys": sorted(horde["extra_keys"]),
        "types": horde["types"],
        "verdict": h_verdict,
    }
    rep = liveclient_shape_audit.audit(payloads) if payloads else {
        "unconsumed_events": [], "type_mismatches": [], "unread_keys": []}
    rep = dict(rep)
    rep["type_mismatches"] = [m.split(" (e.g. ")[0] for m in rep["type_mismatches"]]
    out["shape_audit"] = rep
    return out


def render(s: dict) -> str:
    """Human-readable text summary (no names, by construction of check)."""
    lines = [
        f"payloads {s['payloads']} synthetic={s['synthetic']} "
        f"duplicates={s['duplicates']} modes={','.join(s['game_modes'])} "
        f"game_time_max={s['game_time_max']} relay_ts_span_s={s['relay_ts_span_s']}",
        "events_per_payload " + ",".join(str(n) for n in s["events_per_payload"]),
        f"rm673 verdict={s['rm673']['verdict']} "
        f"champion_exact={s['rm673']['champion_exact']} "
        f"reader_self_identified={s['rm673']['reader_self_identified']} objective_killer_forms="
        + json.dumps(s["rm673"]["objective_killer_forms"], sort_keys=True)
        + " reader_killer_team=" + json.dumps(s["rm673"]["reader_killer_team"], sort_keys=True),
        f"rm674 verdict={s['rm674']['verdict']} names="
        + ",".join(s["rm674"]["first_blood_event_names"]),
        f"horde verdict={s['horde']['verdict']} count={s['horde']['count']} "
        f"missing={','.join(s['horde']['missing_keys'])} "
        f"extra={','.join(s['horde']['extra_keys'])} types="
        + json.dumps(s["horde"]["types"], sort_keys=True),
        "name_forms:",
    ]
    for en in sorted(s["name_forms"]):
        for f in sorted(s["name_forms"][en]):
            lines.append(f"  {en}.{f} " + json.dumps(s["name_forms"][en][f], sort_keys=True))
    for title, key in (("unconsumed_events", "unconsumed_events"),
                       ("type_mismatches", "type_mismatches"),
                       ("unread_keys", "unread_keys")):
        rows = s["shape_audit"][key]
        lines.append(f"shape_audit {title} ({len(rows)})")
        lines.extend(f"  {r}" for r in rows)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Grade captured Live Client payloads for LX-02 (read-only).")
    ap.add_argument("path", help="a captured allgamedata JSON file or a directory of them")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    p = Path(args.path)
    if not p.exists():
        print(f"no such path: {p}", file=sys.stderr)
        return 2
    loaded = load(p)
    if not loaded:
        print(f"no loadable payload at: {p}", file=sys.stderr)
        return 2
    s = check(loaded)
    print(json.dumps(s, indent=2, sort_keys=True) if args.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
