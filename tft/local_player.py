# arch: the ONE local-player selector for TFT per-round / EoG player lists | section=tft | frozen=no
"""tft.local_player - which entry of a TFT ``players`` list is the local player.

Measured 2026-10-25 (S135 N13, match-4 QA): the standalone client's per-round
``TFTEoGStats.json`` (and the game client's gameclient-eog-stats-block, the
same document) marked ONE entry ``isInteractable`` in the three bot-like
lobbies, but ALL 8 in the first human lobby. ``next(isInteractable)`` then took
players[0] - the opponent who finished 8th - and RC served that stranger's HP,
standing and board for a whole match. In that lobby every entry carried a
non-zero ``playerId`` and ``PUUID``; exactly ONE ``playerId`` equalled the LCU
summoner id (``/lol-summoner/v1/current-summoner`` summonerId, stamped on the
LCU snapshot as ``summoner_id``) and the same entry's PUUID equalled the LCU
EOG ``isLocalPlayer`` puuid.

Rule (``local_player_index``), in order:
  1. An LCU id is known (summoner id and / or puuid): the ONE entry whose
     ``playerId`` / ``PUUID`` matches it. Two matches -> unknown. No match ->
     unknown, unless the file carries no ids at all (every id absent or zeroed)
     - then the id cannot be compared and rule 2 decides.
  2. No usable id: the entry flagged ``isInteractable``, only when EXACTLY one
     entry is flagged (the bot-lobby shape).
  3. Otherwise unknown: (None, reason). Never a guess - a stranger's HP / board
     is worse than none, and the caller logs the reason.

The same module owns the ONE alive / eliminated rule for those lists
(``player_status`` / ``count_alive`` / ``lobby_counts``, verifier round 4b):
eliminated = health <= 0 on a SCORED entry; the start-of-game placeholder
(-1 / -1) is unknown, and a count over unknowns is None, never a number.

Pure and fail-soft (junk in -> (None, reason)); stdlib only, so every TFT
consumer can import it: tft/tft_standalone.py (live source), tft/tft_placement.py
(gameclient EoG block), tft/tft_scouting.py (round-file opponents),
tools/tft_cv_accuracy.py (oracle A), and the round-store source
tft/sources/eog_file.py once it lands. The reason strings carry counts only -
never a name, Riot id, puuid or player id.
"""
from __future__ import annotations

from typing import Any, Optional

BASIS_SUMMONER_ID = "summoner_id"
BASIS_PUUID = "puuid"
BASIS_INTERACTABLE = "isInteractable"


def real_id(v: Any) -> int:
    """A usable summoner / player id: a positive int (bool excluded), an
    int-valued float or a digit string; anything else is 0 (no id)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return v if v > 0 else 0
    if isinstance(v, float):
        return int(v) if v.is_integer() and v > 0 else 0
    if isinstance(v, str) and v.strip().isdigit():
        n = int(v.strip())
        return n if n > 0 else 0
    return 0


def real_puuid(v: Any) -> str:
    """A usable puuid, lower-cased, or "" (missing, junk, or the all-zero
    privacy form the client writes for other players)."""
    s = str(v or "").strip().lower() if isinstance(v, str) else ""
    if len(s) < 8 or not s.strip("0-"):
        return ""
    return s


def _entry_ids(p: dict) -> tuple:
    return real_id(p.get("playerId")), real_puuid(p.get("PUUID") or p.get("puuid"))


def local_player_index(players: Any, *, summoner_id: Any = None,
                       puuid: Any = None) -> tuple:
    """``(index, basis)`` of the local player's entry in ``players`` (the
    position in the list as given, non-dict rows included), or
    ``(None, reason)`` when it cannot be told. ``basis`` is one of
    ``BASIS_SUMMONER_ID`` / ``BASIS_PUUID`` / ``BASIS_INTERACTABLE``."""
    if not isinstance(players, list):
        return None, "no players list"
    rows = [(i, p) for i, p in enumerate(players) if isinstance(p, dict)]
    if not rows:
        return None, "no player entries"
    sid, me_p = real_id(summoner_id), real_puuid(puuid)
    if sid or me_p:
        by_sid, by_puuid = [], []
        for i, p in rows:
            pid, pp = _entry_ids(p)
            if (sid and pid == sid) or (me_p and pp == me_p):
                (by_sid if sid and pid == sid else by_puuid).append(i)
        hits = by_sid + by_puuid
        if len(hits) == 1:
            return hits[0], (BASIS_SUMMONER_ID if by_sid else BASIS_PUUID)
        if len(hits) > 1:
            return None, f"{len(hits)} entries match the LCU id"
        if any(any(_entry_ids(p)) for _, p in rows):
            return None, "the LCU id matches no entry"
    flagged = [i for i, p in rows if p.get("isInteractable") is True]
    if len(flagged) == 1:
        return flagged[0], BASIS_INTERACTABLE
    return None, (f"{len(flagged)} entries are isInteractable and no LCU id "
                  f"names one")


def local_player(players: Any, *, summoner_id: Any = None,
                 puuid: Any = None) -> tuple:
    """``(entry, basis)`` - the local player's dict - or ``(None, reason)``."""
    idx, why = local_player_index(players, summoner_id=summoner_id, puuid=puuid)
    if idx is None:
        return None, why
    return players[idx], why


# -- the ONE alive / eliminated rule (S135 verifier 4b) ------------------------------
# Measured: for ~20 s at game start the file writes health -1 / ffaStanding -1
# for EVERY player (QA N10); an eliminated player keeps a scored standing
# (1..8) and a health <= 0 (-11..0 in the human lobby). So HP <= 0 alone does
# not mean "eliminated": counting it that way fed the coach "Players alive: 1
# (8 eliminated)" at game start.

ALIVE = "alive"
ELIMINATED = "eliminated"


def _num(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f == f and abs(f) != float("inf") else None


def player_status(p: Any) -> Optional[str]:
    """``ALIVE`` (health > 0), ``ELIMINATED`` (health <= 0 on a scored entry,
    ffaStanding >= 1), or None when it is not knowable (the start-of-game
    placeholder, a missing health, junk)."""
    if not isinstance(p, dict):
        return None
    hp = _num(p.get("health"))
    if hp is None:
        return None
    if hp > 0:
        return ALIVE
    return ELIMINATED if (_num(p.get("ffaStanding")) or 0) >= 1 else None


def count_alive(players: Any) -> Optional[int]:
    """Players alive in the lobby, or None when ANY entry's status is not
    knowable (a count over placeholders is a guess, never a number to serve)."""
    rows = [p for p in players if isinstance(p, dict)] if isinstance(players, list) else []
    statuses = [player_status(p) for p in rows]
    if not statuses or any(s is None for s in statuses):
        return None
    return statuses.count(ALIVE)


def lobby_counts(players: Any, local_index: Optional[int] = None) -> dict:
    """``{"players_alive", "alive_others", "dead_others"}`` by the one rule,
    all None while not knowable. ``local_index`` is the local entry's position
    in ``players`` (``local_player_index``); when it is unknown the counts are
    lobby-wide with the local player taken as one of the alive."""
    unknown = {"players_alive": None, "alive_others": None, "dead_others": None}
    alive = count_alive(players)
    if alive is None:
        return unknown
    rows = [p for p in players if isinstance(p, dict)]
    dead = sum(1 for p in rows if player_status(p) == ELIMINATED)
    me = None
    if isinstance(local_index, int) and 0 <= local_index < len(players):
        me = player_status(players[local_index])
    if me is None:
        return {"players_alive": alive, "alive_others": max(0, alive - 1),
                "dead_others": dead}
    return {"players_alive": alive, "alive_others": alive - (me == ALIVE),
            "dead_others": dead - (me == ELIMINATED)}


def summoner_id_of(lcu: Any) -> Optional[int]:
    """The local summoner id the LCU snapshot carries (``summoner_id``, stamped
    by lcu/snapshot_shape.py), or None."""
    if not isinstance(lcu, dict):
        return None
    return real_id(lcu.get("summoner_id")) or None
