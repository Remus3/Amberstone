"""gated_lx05_tape_check.py - read one game's live item tape for the LX-05 drain.

LX-05 (RM-607) asks whether ONE real ARAM Mayhem (KIWI) game, with
``RC_ITEM_TAPE=1`` set in the RC process, lands ``timeline_events`` rows with
``source='live_tape'`` after the 180 s delay; whether the folded tape equals
the players' final inventories; whether combines match DDragon recipes; and
whether anvil / augment grants are typed ITEM_GRANTED (never a purchase).
Checking that by hand means a fold and a recipe walk per row every pass; this
tool prints it in ONE command.

It is READ-ONLY: both SQLite files are opened with ``mode=ro`` URIs, and the
session file (if given) goes through the recorder's own reader. It never
writes, migrates, locks or deletes anything, and it never ticks a row - its
output is the INPUT to the four-part evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. Rows written by
``core.live_item_tape_store.persist_tape`` from a synthetic tape pass every
check just as well; that is the substitution the LX-05 row names.

THE FINAL-INVENTORY SOURCE (independent of the tape):
  - ``--eog-db`` (default ``data/postgame_stats.db``, table ``<mode>_player_stats``,
    mode default ``aram``; KIWI maps to ARAM in the collector): the LCU
    end-of-game item0..item6, keyed ``game_name#tag_line`` + team_id. Measured
    2026-10-28: every stored KIWI match holds ONE player row, so this source
    grades only the players it names (``all_players=false``).
  - ``--session``: the last frame with an ``allPlayers`` list in an LX-03
    recording (Live Client, so it also carries consumable flags and slot 6).
Only the tape's PERSISTED types are rows (PURCHASED / SOLD / COMBINED). The
fold therefore cannot see consumables, trinkets, grants or transforms; a diff
on one of those ids is reported as EXPLAINED (with its class), every other
diff as UNEXPLAINED. A transform is paired ONE COPY FOR ONE COPY (two
Manamunes in the tape against one Muramana leave one Manamune unexplained),
and the fold clamps at zero after every row as the writer's ``fold`` does.
``fold_match`` is true only when at least one player is compared, no diff is
unexplained, no final player is missing from the tape, and - for a session
source (all ten players) - no tape player is missing from the final. The DB
cannot show an ITEM_GRANTED
row (never persisted); it can only show that no grant id was typed as a
purchase, sale or combine (``grant_ids_persisted``).

Riot ids and the game id are printed only with ``--show-id`` (RM-906: never
paste them into a tracked file); players are ``p1``.. otherwise.

USAGE
    python tools/gated_lx05_tape_check.py --game-id <id>
    python tools/gated_lx05_tape_check.py --game-id <id> --session logs/sessions/<id>.jsonl --json

Exit 2 = a database or session file is missing or unreadable.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import live_item_tape as lit  # noqa: E402
from core.live_item_tape_store import (  # noqa: E402
    SOURCE_COLUMN, SOURCE_TAPE, V5_ITEM_TYPES, match_id_for)

DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
DEFAULT_EOG_DB = _ROOT / "data" / "postgame_stats.db"
_TEAM_ID = {"ORDER": 100, "CHAOS": 200}
_ITEM_TYPES = tuple(sorted(set(V5_ITEM_TYPES) | lit.PERSISTED_TYPES))


def _ro(path: Path) -> sqlite3.Connection:
    if not Path(path).is_file():
        raise FileNotFoundError("database not found")
    uri = "file:" + quote(Path(path).resolve().as_posix(), safe="/:") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10.0)


def _int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def tape_rows(conn: sqlite3.Connection, match_id: str) -> dict:
    """The tape rows for one match plus the counts the row asks about."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(timeline_events)")}
    has_src = SOURCE_COLUMN in cols
    ph = ",".join("?" * len(_ITEM_TYPES))
    out: dict = {"source_column": has_src, "rows": [], "non_tape_item_rows": 0}
    if not has_src:
        out["non_tape_item_rows"] = conn.execute(
            f"SELECT COUNT(*) FROM timeline_events WHERE match_id=? "
            f"AND event_type IN ({ph})", (match_id, *_ITEM_TYPES)).fetchone()[0]
        return out
    out["non_tape_item_rows"] = conn.execute(
        f"SELECT COUNT(*) FROM timeline_events WHERE match_id=? "
        f"AND event_type IN ({ph}) AND ({SOURCE_COLUMN} IS NULL "
        f"OR {SOURCE_COLUMN} != ?)", (match_id, *_ITEM_TYPES, SOURCE_TAPE)).fetchone()[0]
    out["rows"] = conn.execute(
        f"SELECT timestamp_ms, event_type, participant_id, item_id, team_id, raw_json "
        f"FROM timeline_events WHERE match_id=? AND {SOURCE_COLUMN}=? "
        f"ORDER BY timestamp_ms, id", (match_id, SOURCE_TAPE)).fetchall()
    return out


def _take(c: Counter, iid: int, cat: Optional[lit.ItemCatalog], stats: dict) -> None:
    """Remove one ``iid``. When none is held but a held item TRANSFORMS into it
    (ITEM_TRANSFORMED is tape-only, never a row), remove that source instead."""
    if c[iid] <= 0 and cat is not None:
        for src in sorted(c):
            if c[src] > 0 and is_transform(src, iid, cat):
                c[src] -= 1
                stats["implicit_transforms"] = stats.get("implicit_transforms", 0) + 1
                return
    c[iid] -= 1


def fold_rows(rows: list, cat: Optional[lit.ItemCatalog] = None,
              stats: Optional[dict] = None) -> dict:
    """``(riot id, team_id) -> Counter`` from persisted rows (one row per copy).
    Clamps at zero after EVERY row, as ``core.live_item_tape.fold`` does, so a
    sale of an item the tape never bought cannot cancel a later purchase. With
    ``cat``, a sale or combine of a transform TARGET the fold never saw (Muramana
    sold after a Manamune buy) consumes its held source; counted in ``stats``."""
    stats = {} if stats is None else stats
    inv: dict = {}
    for _ts, etype, _pid, raw_iid, team_id, raw in rows:
        try:
            meta = json.loads(raw or "{}")
        except ValueError:
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
        c = inv.setdefault((meta.get("riot_id"), team_id), Counter())
        iid = _int(raw_iid) or 0
        if etype == lit.EV_PURCHASED:
            c[iid] += 1
        elif etype == lit.EV_SOLD:
            _take(c, iid, cat, stats)
        elif etype == lit.EV_COMBINED:
            for comp in meta.get("components") or ():
                if _int(comp) is not None:
                    _take(c, _int(comp), cat, stats)
            c[iid] += 1
        for k in [k for k, n in c.items() if n <= 0]:
            del c[k]
    return inv


def final_from_eog(conn: sqlite3.Connection, game_id: str, mode: str) -> dict:
    """LCU end-of-game items per player (``<mode>_player_stats``)."""
    tbl = f"{mode.lower()}_player_stats"
    if not tbl.replace("_", "").isalnum():
        raise ValueError("bad mode")
    cols = ", ".join(f"item{i}_id" for i in range(7))
    out: dict = {}
    for row in conn.execute(
            f"SELECT game_name, tag_line, team_id, {cols} FROM {tbl} "
            f"WHERE match_id=?", (str(game_id),)).fetchall():
        name, tag, team_id = row[0], row[1], row[2]
        key = (f"{name}#{tag}" if tag else name, team_id)
        c = out.setdefault(key, Counter())
        for raw_iid in row[3:]:
            iid = _int(raw_iid)
            if iid and iid > 0:
                c[iid] += 1
    return out


def final_from_session(path: Path) -> tuple[dict, dict]:
    """Last ``allPlayers`` in an LX-03 recording: inventories, and per player
    the slot-6 / consumable-flagged ids (never pooled across players)."""
    from core.live_session_recorder import read_session
    _header, frames = read_session(path)
    players = None
    for f in reversed(frames):
        snap = f.get("snapshot")
        cand = snap.get("allPlayers") if isinstance(snap, dict) else None
        if isinstance(cand, list) and cand:
            players = cand
            break
    out: dict = {}
    flagged: dict = {}
    for p in players or ():
        key = lit.player_key(p)
        inv = lit._inventory(p.get("items")) if isinstance(p, dict) else None
        if key is None or inv is None:
            continue
        counts, slot6, cons = inv
        k = (key[0], _TEAM_ID.get(key[1]))
        out[k] = counts
        flagged[k] = slot6 | cons
    return out, flagged


def explain(iid: int, cat: lit.ItemCatalog, excluded: frozenset,
            flagged: set) -> Optional[str]:
    """Why a fold-vs-final diff on ``iid`` is expected, or None. Transforms
    are paired copy for copy in ``compare`` before this runs."""
    if iid in excluded:
        return "grant"
    if cat.is_consumable(iid) or (iid in flagged and not cat.has(iid)):
        return "consumable"
    if cat.is_trinket(iid):
        return "trinket"
    if iid in flagged:
        return "consumable_or_trinket"
    return None


def is_transform(src: int, dst: int, cat: lit.ItemCatalog) -> bool:
    """``src`` (in the tape) turned into ``dst`` (in the final) without a shop
    buy: a DDragon specialRecipe, or a zero-cost upgrade built from ``src``."""
    return (cat.special_recipe(dst) == src
            or (cat.base_gold(dst) == 0 and src in cat.recipe(dst)))


def _pair_transforms(extra: Counter, missing: Counter,
                     cat: lit.ItemCatalog) -> tuple[Counter, Counter, Counter, Counter]:
    """Explain transforms ONE COPY FOR ONE COPY: a tape-extra source and a
    final-extra target pair off up to the smaller count; the rest stays a diff."""
    extra, missing = Counter(extra), Counter(missing)
    t_done, f_done = Counter(), Counter()
    for src in sorted(extra):
        for dst in sorted(missing):
            if extra[src] <= 0 or missing[dst] <= 0 or not is_transform(src, dst, cat):
                continue
            k = min(extra[src], missing[dst])
            extra[src] -= k
            missing[dst] -= k
            t_done[src] += k
            f_done[dst] += k
    return +extra, +missing, t_done, f_done


def compare(tape: dict, final: dict, cat: lit.ItemCatalog,
            flagged: Optional[dict] = None, all_players: bool = True) -> dict:
    """Fold vs final, per player. ``all_players=False`` (the EOG source, which
    may hold fewer players than the game) diffs only players the final names
    and reports the rest as ``players_tape_only`` without failing on them."""
    excluded = lit.build_exclusions(cat)
    keys = sorted(set(tape) | set(final), key=lambda k: (str(k[1]), str(k[0])))
    players, unexplained = [], 0
    for i, k in enumerate(keys, 1):
        row = {"label": f"p{i}", "riot_id": k[0], "team_id": k[1],
               "in_tape": k in tape, "in_final": k in final,
               "tape_extra": {}, "final_extra": {}}
        players.append(row)
        if not all_players and k not in final:
            continue
        t, f = tape.get(k, Counter()), final.get(k, Counter())
        extra, missing, t_tr, f_tr = _pair_transforms(t - f, f - t, cat)
        for side, diff, tr in (("tape_extra", extra, t_tr),
                               ("final_extra", missing, f_tr)):
            for iid, n in sorted(tr.items()):
                row[side][str(iid)] = {"count": n, "explained": "transform"}
            for iid, n in sorted(diff.items()):
                why = explain(iid, cat, excluded, (flagged or {}).get(k, set()))
                key = str(iid) if str(iid) not in row[side] else f"{iid}+"
                row[side][key] = {"count": n, "explained": why}
                if why is None:
                    unexplained += 1
    both = sum(1 for p in players if p["in_tape"] and p["in_final"])
    tape_only = sum(1 for p in players if not p["in_final"])
    final_only = sum(1 for p in players if not p["in_tape"])
    return {"players": players, "players_compared": both,
            "players_tape_only": tape_only, "players_final_only": final_only,
            "all_players": all_players, "unexplained_diffs": unexplained,
            "fold_match": both > 0 and unexplained == 0 and final_only == 0
            and (tape_only == 0 or not all_players)}


def check(conn: sqlite3.Connection, match_id: str, cat: lit.ItemCatalog,
          final: Optional[dict] = None, flagged: Optional[dict] = None,
          all_players: bool = True) -> dict:
    t = tape_rows(conn, match_id)
    rows = t["rows"]
    excluded = lit.build_exclusions(cat)
    by_type = Counter(r[1] for r in rows)
    bad_combines = []
    for _ts, etype, _pid, iid, _team, raw in rows:
        if etype != lit.EV_COMBINED:
            continue
        try:
            comps = Counter(_int(c) for c in (json.loads(raw or "{}").get("components") or ()))
        except (ValueError, AttributeError):
            comps = Counter({None: 1})
        if not comps or comps - cat.recipe_closure(_int(iid) or 0):
            bad_combines.append(_int(iid))
    stamps = [r[0] for r in rows if isinstance(r[0], int)]
    out = {
        "source_column": t["source_column"],
        "tape_rows": len(rows),
        "rows_by_type": dict(sorted(by_type.items())),
        "non_tape_item_rows": t["non_tape_item_rows"],
        "timestamp_ms_first": min(stamps) if stamps else None,
        "timestamp_ms_last": max(stamps) if stamps else None,
        "participant_id_null": sum(1 for r in rows if r[2] is None),
        "combine_rows": by_type.get(lit.EV_COMBINED, 0),
        "combine_recipe_bad": sorted(set(bad_combines), key=str),
        "grant_ids_persisted": sorted({_int(r[3]) for r in rows if _int(r[3]) in excluded}),
        "fold": None,
    }
    if final is not None:
        stats: dict = {}
        out["fold"] = compare(fold_rows(rows, cat, stats), final, cat, flagged, all_players)
        out["fold"]["implicit_transforms"] = stats.get("implicit_transforms", 0)
    return out


def _redact(s: dict) -> dict:
    for p in (s.get("fold") or {}).get("players", ()):
        p["riot_id"] = None
    return s


def render(s: dict, show_id: bool = False) -> str:
    lines = [
        f"source_column={s['source_column']} tape_rows={s['tape_rows']} "
        f"non_tape_item_rows={s['non_tape_item_rows']} by_type={s['rows_by_type']}",
        f"timestamp_ms {s['timestamp_ms_first']} .. {s['timestamp_ms_last']} "
        f"participant_id_null={s['participant_id_null']}",
        f"combine_rows={s['combine_rows']} combine_recipe_bad={s['combine_recipe_bad']} "
        f"grant_ids_persisted={s['grant_ids_persisted']}",
    ]
    f = s.get("fold")
    if f is None:
        lines.append("fold not compared (no final-inventory source)")
    else:
        lines.append(f"fold_match={f['fold_match']} all_players={f['all_players']} "
                     f"compared={f['players_compared']} "
                     f"tape_only={f['players_tape_only']} final_only={f['players_final_only']} "
                     f"unexplained={f['unexplained_diffs']} "
                     f"implicit_transforms={f.get('implicit_transforms', 0)}")
        for p in f["players"]:
            who = p["riot_id"] if show_id else p["label"]
            lines.append(f"  {who} team={p['team_id']} tape_extra={p['tape_extra']} "
                         f"final_extra={p['final_extra']}")
    if show_id and s.get("match_id"):
        lines.insert(0, f"match_id={s['match_id']}")
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only LX-05 check of one game's item tape")
    ap.add_argument("--game-id", required=True, help="the LCU / EOG gameId (digits)")
    ap.add_argument("--platform", default=None, help="default: core.operator_identity.platform()")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--eog-db", default=str(DEFAULT_EOG_DB))
    src.add_argument("--session", default=None, help="an LX-03 logs/sessions/<id>.jsonl")
    ap.add_argument("--no-final", action="store_true", help="skip the fold comparison")
    ap.add_argument("--eog-mode", default="aram", help="<mode>_player_stats table (KIWI -> aram)")
    ap.add_argument("--items-json", default=None, help="DDragon items json (default: tracked catalog)")
    ap.add_argument("--show-id", action="store_true",
                    help="print riot ids and the match id (never paste them into a tracked file)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    platform = args.platform
    if platform is None:
        from core.operator_identity import platform as _platform
        platform = _platform()
    match_id = match_id_for(platform, args.game_id)
    if match_id is None:
        print("bad --game-id / --platform (need digits and a platform)", file=sys.stderr)
        return 2
    cat = lit.load_default_catalog(Path(args.items_json) if args.items_json else None)
    final, flagged = None, {}
    try:
        if not args.no_final:
            if args.session:
                final, flagged = final_from_session(Path(args.session))
            else:
                econn = _ro(Path(args.eog_db))
                try:
                    final = final_from_eog(econn, args.game_id, args.eog_mode)
                finally:
                    econn.close()
        conn = _ro(Path(args.db))
        try:
            # EOG rows are measured at ONE player per KIWI match (2026-10-28),
            # so only a session file can grade all ten.
            s = check(conn, match_id, cat, final, flagged,
                      all_players=bool(args.session))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - a reader reports, never raises
        print(f"not readable: {type(exc).__name__}", file=sys.stderr)
        return 2
    if args.show_id:
        s["match_id"] = match_id
    else:
        _redact(s)
    print(json.dumps(s, indent=1, ensure_ascii=True, default=str) if args.json
          else render(s, show_id=args.show_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
