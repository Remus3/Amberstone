"""
tft/tft_final_board.py - the ended TFT game's final placement, board, traits
and comp, for the end-of-game rating (session 134 defect N8).

N8, measured (ops/runtime/tft_qa/20261025-085349/QA_REPORT.md): a 1st-place
Set 18 game was rated "8TH - full rebuild", grade F, comp "Dark Star
Vertical". performance_tracker.save_tft_rating read only two inputs, and at
TFT game end both are blank: data/tft_live_data.json (the vision feed, which
the standalone client never fills) and data/tft_coaching_data.json (reset to
the declared blank, which carries no alive_others). Its placement fallback
`alive_others` defaulted to 7, so EVERY unknown placement became 8th; its comp
came from data/comp_state.json, the overlay comp PLANNER's selection, dated
2026-09-03 (a Set 17 comp), and replaced the board with that comp's meta units.

The real record of the game exists in two places this module reads:

  1. the RM-616 store (tft/tft_placement.py, data/tft_matches/<gameId>.eog.json
     and .history.json): placement, final board with items, trait unit counts
     (EOG) and trait tiers, level and last round (history). Authoritative.
  2. the standalone client's per-round file TFTEoGStats.json
     (tft/tft_standalone.read_eog): the same document shape as the
     gameclient-eog-stats-block (tft_placement.parse_gameclient_eog), rewritten
     at every planning phase and at eliminations, so at game end it holds the
     final standing (QA N8: standing 1, players alive 1 at 14:28:29 UTC). Used
     only when the store has no record of that game yet - the post-game capture
     can land AFTER the lifecycle game-end rating (match 3: 09:29:44 vs
     09:28:52), and then the collector re-rates from the store
     (performance_tracker.rate_tft_game). Only when the file is POSITIVELY
     the ended game's (S136 T10, per_round_record): the file survives the
     game, so fresh is not proof of whose it is.

Trait activation and the comp name come from the GAME'S OWN set's CommunityDragon
breakpoints (data/meta/tft_set<N>_cdragon.json, N from the record's
setCoreName). A set that is not ingested gets no breakpoints - never another
set's file - and the naming then falls back to raw unit counts.

Read-only: this module writes nothing. Nothing identifying is read or kept
(tft_placement records hold no riot id / puuid).
"""
from __future__ import annotations

import logging
import time
from typing import Optional

_log = logging.getLogger("rc.tft.final_board")

# Same freshness bound as tft/tft_standalone.EOG_MAX_AGE_S: the client rewrites
# the per-round file at least once a round, and the game-end rating runs within
# seconds of the last write.
PER_ROUND_MAX_AGE_S = 300.0

# Double Up queue / type spellings (queue 1160 "Double Up (Workshop)" / PAIRS).
_DUO_QUEUE_IDS = frozenset({1160})
_DUO_MARKERS = ("PAIRS", "DOUBLE")

SOURCE_STORE = "store"
SOURCE_PER_ROUND = "per_round_file"


# -- small helpers -----------------------------------------------------------------

def _int(v) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v and v.is_integer():
        return int(v)
    return None


def stage_from_last_round(last_round) -> int:
    """Stage of a match-history `last_round` (1-based round counter): stage 1
    has four rounds (1-1..1-4), every later stage seven, so round 33 = 6-1
    (QA match 3: last_round 33, ended at 6-1). 0 when unknown."""
    r = _int(last_round)
    if r is None or r < 1:
        return 0
    if r <= 4:
        return 1
    return 2 + (r - 5) // 7


def set_number_of(rec, root=None) -> Optional[int]:
    """The record's own set (setCoreName "TFTSet18" -> 18, else set_number)."""
    if not isinstance(rec, dict):
        return None
    try:
        from tft import tft_set
    except Exception:  # noqa: BLE001
        return None
    n = tft_set.parse_set_id(rec.get("set_core_name"))
    if n is None:
        n = _int(rec.get("set_number"))
    return n


def _cdragon(set_number, root=None) -> dict:
    if set_number is None:
        return {}
    try:
        from tft import tft_set
        cd = tft_set.load_cdragon(set_number, root=root)
    except Exception as exc:  # noqa: BLE001
        _log.debug("TFT CommunityDragon data for set %s: %s", set_number, exc)
        return {}
    return cd if isinstance(cd, dict) else {}


def trait_breakpoints(set_number, root=None) -> dict:
    """{trait display name: sorted distinct breakpoints} from the set's own
    CommunityDragon extract; {} when that set is not ingested."""
    out = {}
    for t in _cdragon(set_number, root).get("traits") or []:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            continue
        bps = sorted({b for b in (t.get("breakpoints") or [])
                      if isinstance(b, int) and not isinstance(b, bool) and b > 0})
        if bps:
            out[t["name"]] = bps
    return out


def unit_traits(set_number, root=None) -> dict:
    """{champion display name: [trait names]} from the set's own extract."""
    raw = _cdragon(set_number, root).get("unit_traits")
    if not isinstance(raw, dict):
        return {}
    return {k: [t for t in v if isinstance(t, str)] for k, v in raw.items()
            if isinstance(k, str) and isinstance(v, list)}


def trait_counts_from_board(board, traits_by_unit: dict) -> list[dict]:
    """Unique-unit trait counts of a board whose units carry no traits (the
    per-round file, the gameclient block), from the set's unit -> traits
    table plus "<Trait> Emblem" items - the count rule of
    tft_placement._eog_trait_counts."""
    counts: dict = {}
    seen = set()
    for u in board or []:
        name = u.get("name") if isinstance(u, dict) else None
        if not name or name in seen:
            continue
        seen.add(name)
        names = set(traits_by_unit.get(name) or [])
        for it in u.get("items") or []:
            nm = it.get("name") if isinstance(it, dict) else None
            if isinstance(nm, str) and nm.endswith(" Emblem") and len(nm) > 7:
                names.add(nm[:-7])
        for nm in names:
            counts[nm] = counts.get(nm, 0) + 1
    return [{"name": nm, "units": n} for nm, n in
            sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def classify_traits(traits, breakpoints: dict) -> list[dict]:
    """Each trait as {name, units, tier, tiers, active, unique}.

    `tier` = breakpoints reached (history's tier_current when the record
    carries one), `tiers` = breakpoints the set defines. With no breakpoint
    for the trait, `active` is the history tier when known, else units >= 2
    (the pre-N8 heuristic), and `tiers` is 0."""
    out = []
    for t in traits or []:
        if not isinstance(t, dict):
            continue
        name = t.get("name") or t.get("id")
        if not isinstance(name, str) or not name:
            continue
        units = _int(t.get("units")) or 0
        hist_tier = _int(t.get("tier"))
        bps = breakpoints.get(name) or []
        if bps:
            tier = sum(1 for b in bps if units >= b)
            if hist_tier is not None:
                tier = hist_tier
            active = tier > 0
        else:
            tier = hist_tier if hist_tier is not None else (1 if units >= 2 else 0)
            active = tier > 0
        out.append({"name": name, "units": units, "tier": tier, "tiers": len(bps),
                    "active": active, "unique": bool(bps) and bps[-1] <= 1})
    return out


def _rank_key(t: dict):
    frac = (t["tier"] / t["tiers"]) if t["tiers"] else 0.0
    return (-frac, -t["units"], t["name"])


def ordered_active(classified: list[dict]) -> list[dict]:
    """Active traits, strongest first: share of the trait's breakpoints
    reached, then unit count, then name. Unique one-unit traits last."""
    act = [t for t in classified if t["active"]]
    return (sorted([t for t in act if not t["unique"]], key=_rank_key)
            + sorted([t for t in act if t["unique"]], key=_rank_key))


def comp_name(classified: list[dict], limit: int = 3) -> str:
    """"Flora Fatalis 2 / Lunar 3 / Executioner 2" - the strongest active
    non-unique traits (the format performance_tracker._identify_comp uses)."""
    act = [t for t in ordered_active(classified) if not t["unique"]]
    if not act:
        act = ordered_active(classified)
    return " / ".join(f"{t['name']} {t['units']}" for t in act[:limit])


def is_duo_record(rec) -> bool:
    if not isinstance(rec, dict):
        return False
    if _int(rec.get("queue_id")) in _DUO_QUEUE_IDS:
        return True
    for k in ("queue_type", "game_type"):
        v = rec.get(k)
        if isinstance(v, str) and any(m in v.upper() for m in _DUO_MARKERS):
            return True
    return False


def local_player(rec) -> Optional[dict]:
    players = rec.get("players") if isinstance(rec, dict) else None
    for p in players if isinstance(players, list) else []:
        if isinstance(p, dict) and p.get("is_local") is True:
            return p
    return None


def _unit_label(u: dict) -> str:
    star = _int(u.get("star"))
    return f"{u.get('name')} {star}-star" if star else str(u.get("name"))


def final_from_record(rec, *, root=None, source: str = SOURCE_STORE) -> Optional[dict]:
    """The rating inputs of a merged tft_placement record (tft_placement.load /
    merge), or None when it names no local placement."""
    if not isinstance(rec, dict):
        return None
    placement = _int(rec.get("local_placement"))
    if placement is None or not 1 <= placement <= 8:
        return None
    me = local_player(rec) or {}
    board = [u for u in (me.get("board") or []) if isinstance(u, dict) and u.get("name")]
    # Carries first: star, then cost, then items held (EOG lists boardPieces in
    # board order, which is not a strength order).
    board = sorted(board, key=lambda u: (-(_int(u.get("star")) or 0),
                                         -(_int(u.get("cost")) or 0),
                                         -len(u.get("items") or [])))
    set_n = set_number_of(rec, root)
    traits = me.get("traits") or []
    if not traits and board:
        traits = trait_counts_from_board(board, unit_traits(set_n, root))
    classified = classify_traits(traits, trait_breakpoints(set_n, root))
    active = ordered_active(classified)
    last_round = _int(me.get("last_round"))
    duo = is_duo_record(rec)
    shown = placement
    if duo and placement > 4:
        shown = (placement + 1) // 2
    ended = rec.get("ended_at_effective_unix") or rec.get("captured_at_unix")
    return {
        "game_id": _int(rec.get("game_id")) or 0,
        "placement": shown,
        "lobby_placement": placement,
        "is_duo": duo,
        "level": _int(me.get("level")) or 0,
        "last_round": last_round or 0,
        "stage": stage_from_last_round(last_round),
        "game_length_s": _int(rec.get("game_length_s")) or 0,
        "hp": _int(rec.get("local_hp")),
        "set_number": set_n or 0,
        "queue_id": _int(rec.get("queue_id")) or 0,
        "units": [_unit_label(u) for u in board],
        "board": [{"name": u.get("name"), "star": _int(u.get("star")),
                   "cost": _int(u.get("cost")),
                   "items": [i.get("name") for i in (u.get("items") or [])
                             if isinstance(i, dict) and i.get("name")]}
                  for u in board],
        "traits": [f"{t['name']} {t['units']}" for t in active],
        "comp": comp_name(classified),
        "augments": [a for a in (me.get("augments") or []) if isinstance(a, str)],
        "source": source,
        "sources": list(rec.get("sources") or []),
        "ended_at_unix": float(ended) if isinstance(ended, (int, float))
        and not isinstance(ended, bool) else None,
    }


# -- sources -------------------------------------------------------------------------

def per_round_is_final(doc, *, summoner_id=None) -> bool:
    """True when a per-round document records a FINISHED game for the local
    player: they are eliminated, or every opponent outside their Double Up
    team is. A mid-game write - local alive, someone else alive - holds a
    standing, not a result.

    S135 N13 (merged at the s135 landing): the local entry is the one
    tft/local_player.py picks - by the LCU summoner id; a human lobby flags all
    8 ``isInteractable`` - and an unknown local is NOT final, never a
    stranger's result. "Eliminated" is the ONE rule (``player_status``):
    health <= 0 on a scored entry (an eliminated player keeps a real standing
    and a health of -11..0); the game-start -1 / -1 placeholders (QA N10) are
    neither alive nor eliminated, so they never end a game."""
    from tft import local_player as _lp
    sb = doc.get("statsBlock") if isinstance(doc, dict) else None
    players = sb.get("players") if isinstance(sb, dict) else None
    if not isinstance(players, list):
        return False
    players = [p for p in players if isinstance(p, dict)]
    local, _basis = _lp.local_player(players, summoner_id=summoner_id)
    if local is None:
        return False
    if _lp.player_status(local) == _lp.ELIMINATED:
        return True
    team = _int(local.get("partnerGroupId")) or 0
    others = [p for p in players if p is not local
              and not (team and (_int(p.get("partnerGroupId")) or 0) == team)]
    return bool(others) and all(_lp.player_status(p) == _lp.ELIMINATED for p in others)


def per_round_record(now: Optional[float] = None, game_id=None) -> Optional[dict]:
    """The standalone client's per-round file as a merged tft_placement
    record, or None (missing, stale, not TFT, unparsable, or not POSITIVELY
    the game). The file read goes through tft_standalone.read_eog - its path
    seam is what tests redirect. The record carries `per_round_final`
    (per_round_is_final).

    S136 T10: the game is `game_id` when the caller knows it, else
    tft_standalone.current_game_id (the LCU snapshot's id, else the live game
    this process served); a file that is not that game's - another game's
    id, no id, or no current game at all - is no file (the T9 rule,
    tft_standalone.eog_for_game). It used to be taken whatever its game."""
    try:
        from tft import tft_placement, tft_standalone
        doc = tft_standalone.read_eog(now=now, max_age_s=PER_ROUND_MAX_AGE_S)
        if doc is None:
            return None
        lcu = tft_standalone.relay_lcu_snapshot()
        gid = str(game_id or "") or tft_standalone.current_game_id(lcu, now=now)
        doc = tft_standalone.eog_for_game(doc, gid)
        if doc is None:
            return None
        # S135 N13: the local entry by the LCU summoner id (the relay snapshot
        # the live source already reads), never the first isInteractable one.
        from tft.local_player import summoner_id_of
        sid = summoner_id_of(lcu)
        rec = tft_placement.parse_gameclient_eog(doc, now=now, local_summoner_id=sid)
        if not rec:
            return None
        rec = tft_placement.merge(rec, None)
        rec["per_round_final"] = per_round_is_final(doc, summoner_id=sid)
        return rec
    except Exception as exc:  # noqa: BLE001 - a bad file is "no file"
        _log.debug("TFT per-round file unusable: %s", exc)
        return None


def store_final(game_id, *, root=None, store_dir=None) -> Optional[dict]:
    """The rating inputs from the store record of `game_id`, or None."""
    try:
        from tft import tft_placement
        rec = tft_placement.load(game_id, store_dir=store_dir)
    except Exception as exc:  # noqa: BLE001
        _log.warning("TFT store read for game %s failed: %s", game_id, exc)
        return None
    return final_from_record(rec, root=root, source=SOURCE_STORE)


def resolve_final(root=None, *, game_id=None, now: Optional[float] = None,
                  store_dir=None) -> Optional[dict]:
    """The just-ended game's rating inputs: the store record of that game,
    else the per-round file's standing when that file records a finished
    game (per_round_is_final). The game is `game_id` when the caller knows
    it, else tft_standalone.current_game_id - never the per-round file's own
    gameId (S136 T10: a fresh file of ANOTHER game named "the game", so its
    store record or standing was rated as the one that just ended); the file
    counts only when it is positively that game's (per_round_record). None
    when neither source holds the game's result - the caller then has no
    placement, and must not invent one; the collector re-rates when the
    store record lands."""
    gid = _int(game_id) if game_id is not None else None
    if gid is not None and gid <= 0:
        gid = None
    pr = per_round_record(now=now if now is not None else time.time(), game_id=gid)
    pr_gid = _int(pr.get("game_id")) if pr else None
    if gid is None:
        gid = pr_gid       # matched to the current game, so it IS that game
    if gid:
        fin = store_final(gid, root=root, store_dir=store_dir)
        if fin:
            return fin
    if pr and pr.get("per_round_final") and pr_gid == gid:
        return final_from_record(pr, root=root, source=SOURCE_PER_ROUND)
    return None
