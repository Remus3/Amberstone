"""s209: enemy-comp adaptive summoner recommendation.

GET /api/champ-select/adaptive-summoners
    ?champion=<Display Name>
    &enemy_ids=86,64,157,145,412
    &role=BOT|JUNGLE|...
    &base=4,7

Recommends the summoner spell pair for the operator's pick against the
locked-in enemy comp. The decision tree is deliberately small:

  - Flash (id 4) always stays, in whichever slot the base keeps it (D or
    F is a keybind preference); the swap replaces the OTHER slot. Only
    edge case is jungle on Smite-required queues, but the LCU rejects
    no-Smite picks so we keep Flash on as a safety net.
  - A swap never duplicates a spell: when the target is already in the
    base pair the base is kept as is. A short or duplicated base is
    filled from Flash then Heal, so the answer is always two distinct ids.
  - Secondary swaps to **Cleanse** (id 1) when >=2 hard-CC enemies are
    locked (scored over a full five-enemy team, so one hard-CC pick locked
    early does not count as a CC-heavy comp) AND the operator is
    BOT/MID/ADC-style role. Cleanse breaks
    the long-form CC that Heal can't outlast (Morgana root, Ashe arrow,
    Thresh hook chain, etc.).
  - Secondary swaps to **Barrier** (id 21) when burst_threat >= 6
    (assassin-heavy comp) and operator is a squishy back-line role.
    Barrier mitigates the one-shot window Heal can't.
  - Otherwise the secondary stays at the variant's stored value (usually
    Heal id 7 for BOT, Teleport id 12 for TOP/MID, Smite id 11 for
    JUNGLE) - no swap.

The endpoint is read-only and stateless. The apply path
(``/api/loadout/apply``) accepts an ``override_summoners: [d, f]``
payload to push the recommended pair instead of the variant's stored
pair; this endpoint computes the recommendation, the frontend decides
whether to apply it.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("rc.web_dashboard")


# Hard-CC champions that pressure ADC-style picks. Hook + long-form
# single-target CC + suppression are the cases where Heal under-performs
# Cleanse. Compiled from operator-observed comps + the standard "ADC
# needs Cleanse" matchups. Add to this set as new threats emerge.
_HARD_CC_CHAMPIONS: frozenset[str] = frozenset({
    # Hook champions
    "Blitzcrank", "Thresh", "Pyke", "Nautilus", "Skarner",
    # Long-form root / snare
    "Morgana", "Lillia", "Neeko", "Lulu", "Ivern", "Zyra", "Cassiopeia",
    # Multi-second stun chain
    "Leona", "Annie", "Veigar", "Pantheon", "Sett", "Taric",
    "TwistedFate", "Twisted Fate", "Vex", "Zilean",
    # Heavy followup CC engage
    "Ashe", "Sejuani", "Maokai", "Galio", "Amumu", "Sion", "Volibear",
    "Wukong", "MonkeyKing", "Alistar", "Braum", "Rakan", "Rell",
    "Jarvan IV", "JarvanIV", "Diana",
    # Suppression
    "Malzahar", "Warwick", "Urgot",
})

# Squishy back-line roles where Barrier vs burst makes sense. Top is
# excluded because Top usually keeps Teleport for split-push pressure;
# the swap to Barrier on Top is rarely correct.
_BARRIER_ELIGIBLE_ROLES: frozenset[str] = frozenset({
    "BOT", "BOTTOM", "ADC", "MID", "MIDDLE", "SUP", "SUPPORT", "UTILITY",
})

# Cleanse only really pays off for the carries - Top has Teleport,
# Jungle has Smite, those are non-negotiable slots in serious play.
_CLEANSE_ELIGIBLE_ROLES: frozenset[str] = frozenset({
    "BOT", "BOTTOM", "ADC", "MID", "MIDDLE",
})

# Score thresholds - these get tuned as we collect real-game data.
_CC_SWAP_THRESHOLD    = 4.0   # 0-10 scale; 4 ~ 2 hard-CC on a 5-team
_BURST_SWAP_THRESHOLD = 6.0   # 0-10 scale; 6 ~ assassin-heavy comp


# Riot summoner spell IDs we recommend swapping to. Mirror of the JS
# SUM_SPELLS map in web/js/lib/summoner_spells.js.
_FLASH    = 4
_HEAL     = 7
_CLEANSE  = 1
_BARRIER  = 21
_GHOST    = 6
_EXHAUST  = 3
_IGNITE   = 14
_TELEPORT = 12
_SMITE    = 11

_SPELL_NAMES: dict[int, str] = {
    _FLASH: "Flash", _HEAL: "Heal", _CLEANSE: "Cleanse", _BARRIER: "Barrier",
    _GHOST: "Ghost", _EXHAUST: "Exhaust", _IGNITE: "Ignite",
    _TELEPORT: "Teleport", _SMITE: "Smite",
}


# A query value is untrusted: only plain ASCII decimal ids of at most
# _MAX_ID_DIGITS digits, value > 0, are read, and at most _MAX_IDS of them
# (a lobby has at most five enemies; Arena lists more, still well under 16).
# int() alone also accepted a sign, an underscore, zero and non-ASCII digits.
_MAX_IDS = 16
_MAX_ID_DIGITS = 6

# Scores are over a full five-enemy team: the CC threshold below is
# "2 hard-CC of 5", so a partly locked roster must not inflate the fraction.
_TEAM_SIZE = 5


def _parse_int_csv(raw: str) -> list[int]:
    """Positive ASCII-decimal ids from a comma list, in order, duplicates
    kept (One for All locks one champion five times), at most _MAX_IDS."""
    out: list[int] = []
    if not isinstance(raw, str):
        return out
    for raw_chunk in raw.split(","):
        chunk = raw_chunk.strip()
        if not (chunk.isascii() and chunk.isdigit()
                and len(chunk) <= _MAX_ID_DIGITS):
            continue
        value = int(chunk)
        if value <= 0:
            continue
        out.append(value)
        if len(out) >= _MAX_IDS:
            break
    return out


# Module-level lazy cache: champion-id (int) -> display name (str).
# Built from data/meta/ddragon_champions.json on first call. The
# threat-profile classifier in core.defensive_picks already loads the
# same file with apostrophe-and-space variants under the same keys, so
# the names we return here flow cleanly through that pipeline.
# A good map is cached for the process; an EMPTY one (missing, unreadable
# or malformed file) is retried after _EMPTY_RETRY_S instead of pinning
# "no enemy names" until RC restarts, and is not re-read inside the window.
_ID_TO_NAME: dict[int, str] | None = None
_ID_TO_NAME_RETRY_AT = 0.0
_EMPTY_RETRY_S = 60.0
_ID_TO_NAME_LOCK = threading.Lock()
_monotonic = time.monotonic


def _champions_path() -> Path:
    return (Path(__file__).resolve().parent.parent
            / "data" / "meta" / "ddragon_champions.json")


def _read_id_to_name() -> dict[int, str]:
    out: dict[int, str] = {}
    try:
        # utf-8-sig: PowerShell 5.1 writes a BOM that plain utf-8 keeps.
        raw = json.loads(_champions_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        log.warning("adaptive-summoners: ddragon_champions load failed: %s",
                    type(exc).__name__)
        return out
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        log.warning("adaptive-summoners: ddragon_champions has no data object")
        return out
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        name = entry.get("name")
        if not (isinstance(key, str) and key.isascii() and key.isdigit()
                and len(key) <= _MAX_ID_DIGITS):
            continue
        if not isinstance(name, str) or not name.strip():
            continue
        cid = int(key)
        if cid > 0:
            out[cid] = name.strip()
    return out


def _load_id_to_name() -> dict[int, str]:
    global _ID_TO_NAME, _ID_TO_NAME_RETRY_AT
    cached = _ID_TO_NAME
    if cached or (cached is not None and _monotonic() < _ID_TO_NAME_RETRY_AT):
        return cached
    with _ID_TO_NAME_LOCK:
        cached = _ID_TO_NAME
        if cached or (cached is not None
                      and _monotonic() < _ID_TO_NAME_RETRY_AT):
            return cached
        out = _read_id_to_name()
        if not out:
            _ID_TO_NAME_RETRY_AT = _monotonic() + _EMPTY_RETRY_S
        _ID_TO_NAME = out
        return out


def _resolve_enemy_names(enemy_ids: list[int]) -> list[str]:
    """Convert champion-ids to display names via the DDragon index.
    Returns empty string for ids we can't resolve - the threat-profile
    classifier and the CC score both skip "" slots."""
    idx = _load_id_to_name()
    return [idx.get(cid) or "" for cid in enemy_ids]


def _compute_cc_score(enemy_names: list[str]) -> float:
    """Hard-CC enemies over a full team, scaled to 0-10.

    The denominator is max(_TEAM_SIZE, resolved enemies): unresolved ""
    slots do not dilute the score, and a roster still being locked does
    not inflate it (one hard-CC pick of one locked used to score 10)."""
    names = [nm for nm in (enemy_names or []) if isinstance(nm, str) and nm]
    if not names:
        return 0.0
    n_hits = sum(1 for nm in names if nm in _HARD_CC_CHAMPIONS)
    return min(10.0, (n_hits / max(_TEAM_SIZE, len(names))) * 10.0)


def _compute_threat(enemy_names: list[str]) -> dict:
    """Wraps core.defensive_picks.compute_threat_profile + adds cc_threat.
    Defensive against import failures (engine not installed) and a bad
    profile: the failure is logged and the route still answers with the
    CC score alone. The returned profile is a copy, never the callee's."""
    try:
        from core.defensive_picks import compute_threat_profile
        raw = compute_threat_profile(enemy_names)
    except Exception as exc:  # noqa: BLE001 - optional engine; degrade, log
        log.warning("adaptive-summoners: threat profile failed: %s",
                    type(exc).__name__)
        raw = None
    profile = dict(raw) if isinstance(raw, dict) else {}
    profile["cc_threat"] = round(_compute_cc_score(enemy_names), 1)
    return profile


def _score(value) -> float:
    """A finite threat score, or 0.0 for anything else (str, bool, NaN)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    try:
        value = float(value)
    except OverflowError:  # an int past the float range is not a score
        return 0.0
    return value if math.isfinite(value) else 0.0


def _normalise_base(base: list[int]) -> list[int]:
    """The variant's stored pair as two distinct positive ids: the first
    two distinct ids of ``base``, any missing slot filled from Flash then
    Heal (so [7] becomes [7, 4] and [4, 4] becomes [4, 7])."""
    pair: list[int] = []
    for sid in base or []:
        if isinstance(sid, bool) or not isinstance(sid, int) or sid <= 0:
            continue
        if sid not in pair:
            pair.append(sid)
        if len(pair) == 2:
            return pair
    for filler in (_FLASH, _HEAL):
        if len(pair) < 2 and filler not in pair:
            pair.append(filler)
    return pair


def _recommend(base: list[int], role: str, threat: dict) -> dict:
    """Decision tree -> (summoners, swap_to_name, reason). When no swap
    fires, returns the base pair with swap_to=None.

    base : the variant's stored summoner pair (often [4, 21] = Flash+Barrier
           for carry; [4, 7] retained for support duo + Senna/Kalista).
    role : LCU/dashboard form; we accept either via _BARRIER_ELIGIBLE_ROLES.
    """
    pair = _normalise_base(base)
    # Flash stays in whichever slot it holds; the swap targets the other.
    swap_slot = 0 if pair[1] == _FLASH else 1
    base_secondary = pair[swap_slot]
    secondary = base_secondary

    threat = threat if isinstance(threat, dict) else {}
    cc_threat    = _score(threat.get("cc_threat"))
    burst_threat = _score(threat.get("burst_threat"))
    role_upper = role.strip().upper() if isinstance(role, str) else ""

    target = None
    if cc_threat >= _CC_SWAP_THRESHOLD and role_upper in _CLEANSE_ELIGIBLE_ROLES:
        target = _CLEANSE
        reason = f"CC threat {cc_threat:.0f}/10 \xb7 Cleanse > Heal"
    elif burst_threat >= _BURST_SWAP_THRESHOLD and role_upper in _BARRIER_ELIGIBLE_ROLES:
        target = _BARRIER
        reason = f"burst threat {burst_threat:.0f}/10 \xb7 Barrier > Heal"
    if target is not None and target not in pair:
        secondary = target
        pair[swap_slot] = target
    # A target already in the base pair (a swap would duplicate it, e.g.
    # [21, 21]) keeps the base pair and the threat reason; no swap fired
    # at all gives the baseline reason.
    if target is None:
        reason = (
            f"baseline \xb7 {_SPELL_NAMES.get(secondary, str(secondary))}"
            + (f" (CC {cc_threat:.0f} / burst {burst_threat:.0f})"
               if (cc_threat or burst_threat) else "")
        )

    swapped = secondary != base_secondary
    return {
        "summoners":     pair,
        "swapped":       swapped,
        "swap_from_id":  base_secondary if swapped else None,
        "swap_from":     _SPELL_NAMES.get(base_secondary) if swapped else None,
        "swap_to_id":    secondary if swapped else None,
        "swap_to":       _SPELL_NAMES.get(secondary) if swapped else None,
        "reason":        reason,
    }


# ---------------------------------------------------------------------------
# E6: per-champion-per-mode summoner-spell win rates over RC's OWN postgame
# corpus (data/postgame_stats.db, written by lcu.lcu_postgame_collector).
#
# The corpus has one {mode}_player_stats table per mode with champion_name,
# spell1_id, spell2_id, team_result (WIN/LOSS) columns. We group by the
# UNORDERED spell pair (D-vs-F slot order is a keybind preference, not a
# distinct choice) and report observed local win rate + sample size per pair.
#
# HONEST FRAMING: this is the operator's PERSONAL corpus, not a global meta
# winrate and not redistributable - same lens as core.summoner_spell_wpa.
# It is the WR source the RuneWriter uses to tailor the FIRST-lock spell pair
# and what the dashboard surfaces as the per-pair %.
# ---------------------------------------------------------------------------

# Maps an LCU game-mode string (CLASSIC / KIWI / CHERRY / ...) to the
# postgame DB table prefix. Mirrors lcu.lcu_postgame_collector._MODE_MAP so
# the WR lookup keys the same table the collector writes; a mode the
# collector does not map is written to the SR tables, so it reads "sr" here
# too. SR and ARENA are extra dashboard spellings. RM-1330: ONEFORALL and
# ULTBOOK were missing, so their lookups read sr while the collector filed
# those games under brawl. Parity guard:
# tests/test_spell_winrates_mode_table_parity_s144q60.py.
_MODE_TO_TBL: dict[str, str] = {
    "CLASSIC": "sr", "SR": "sr",
    "ARAM": "aram", "KIWI": "aram", "ARAM_5V5": "aram", "ARAM_MAYHEM": "aram",
    "CHERRY": "arena", "ARENA": "arena",
    # Riot compliance 2026-08-11: "BRAWL" (Riot's own mode) was REMOVED from
    # this map. Riot's third-party rules ban aggregating or displaying Brawl
    # data, and this table is what routes a game into an aggregation bucket.
    # The rotating modes below are RC's MODE_BRAWL (a name collision, not Riot
    # Brawl) and are unaffected. See docs/OVERLAY_COMPLIANCE_PLAN.md.
    "NEXUSBLITZ": "brawl", "URF": "brawl",
    "ONEFORALL": "brawl", "ULTBOOK": "brawl",
    "TFT": "tft",
}


def _mode_table_prefix(mode: str) -> str:
    """LCU/dashboard mode string -> postgame DB table prefix ('sr' default)."""
    m = (mode or "").upper()
    if m in _MODE_TO_TBL:
        return _MODE_TO_TBL[m]
    if "ARAM" in m:
        return "aram"
    return "sr"


def compute_champ_spell_winrates(
    conn, champion: str, mode: str, min_n: int = 1,
) -> list[dict]:
    """Per-spell-pair observed win rate for a champion in one mode.

    Reads the {prefix}_player_stats table out of the supplied sqlite
    connection (injected so a test can pass an in-memory fixture; the route
    opens data/postgame_stats.db read-only). Returns a list of
    ``{"pair": [s1, s2], "n": int, "wins": int, "wr_pct": float}`` sorted by
    win rate descending then sample size descending, filtered to pairs with
    ``n >= min_n``. The pair is normalised so the lower spell-id is first,
    collapsing D/F slot-order duplicates. Empty list when the table is
    missing, the champion is absent, or no pair clears ``min_n``.
    """
    prefix = _mode_table_prefix(mode)
    tbl = f"{prefix}_player_stats"
    try:
        rows = conn.execute(
            f"SELECT spell1_id, spell2_id, team_result FROM {tbl} "
            f"WHERE champion_name = ?",
            (champion,),
        ).fetchall()
    except sqlite3.Error as exc:  # missing table / bad champ -> empty
        log.debug("spell-winrates: query failed for %r/%r: %s",
                  champion, mode, type(exc).__name__)
        return []

    agg: dict[tuple[int, int], list[int]] = {}  # pair -> [n, wins]
    for r in rows:
        try:
            s1 = int(r[0] or 0)
            s2 = int(r[1] or 0)
        except (TypeError, ValueError):
            continue
        if s1 <= 0 or s2 <= 0:
            continue
        pair = (s1, s2) if s1 <= s2 else (s2, s1)  # order-insensitive
        win = 1 if str(r[2] or "").upper() == "WIN" else 0
        slot = agg.setdefault(pair, [0, 0])
        slot[0] += 1
        slot[1] += win

    out: list[dict] = []
    for pair, (n, wins) in agg.items():
        if n < min_n:
            continue
        out.append({
            "pair":   [pair[0], pair[1]],
            "n":      n,
            "wins":   wins,
            "wr_pct": round(100.0 * wins / n, 1) if n else 0.0,
            "spell_names": [
                _SPELL_NAMES.get(pair[0], str(pair[0])),
                _SPELL_NAMES.get(pair[1], str(pair[1])),
            ],
        })
    out.sort(key=lambda d: (d["wr_pct"], d["n"]), reverse=True)
    return out


def best_wr_spell_pair(
    conn, champion: str, mode: str, min_n: int = 4,
) -> tuple[int, int] | None:
    """Highest-win-rate spell pair for a champion+mode, or None.

    Thin wrapper over compute_champ_spell_winrates: returns the top pair as
    an ordered (s1, s2) tuple, or None when no pair clears ``min_n``. The
    RuneWriter uses this to tailor the FIRST-lock spell pair, falling back to
    spells_for_role when this returns None.
    """
    ranked = compute_champ_spell_winrates(conn, champion, mode, min_n=min_n)
    if not ranked:
        return None
    top = ranked[0]["pair"]
    return (int(top[0]), int(top[1]))


# Anchored on the package root (not CWD) so a non-root working directory
# does not silently fail-soft - mirrors routes_summspell_wpa._REWIND_DB.
def _postgame_db_path() -> Path:
    return (Path(__file__).resolve().parent.parent
            / "data" / "postgame_stats.db")


def _postgame_db_uri(db: Path) -> str:
    """Read-only SQLite URI for ``db``, built with Path.as_uri() so a '#',
    '?' or '%' in the path is percent-encoded. The hand-built
    ``file:{path}?mode=ro`` read a '#' as the start of a URI fragment and
    opened a different file."""
    return Path(db).resolve().as_uri() + "?mode=ro"


def _serve_spell_winrates(h) -> None:
    """GET /api/champ-select/spell-winrates?champion=<Name>&mode=<LCU mode>&min_n=

    Read-only. Exposes the per-pair regional WR% for the operator's pick so
    the (separate, later) champ-select UI pass can render the % under each
    candidate spell pair. Data-only here - no UI coupling.
    """
    try:
        qs = parse_qs(urlparse(h.path).query)
        champion = (qs.get("champion") or [""])[0].strip()
        mode     = (qs.get("mode")     or ["CLASSIC"])[0].strip() or "CLASSIC"
        min_n    = (qs.get("min_n")    or ["1"])[0].strip()
        try:
            min_n_i = max(1, int(min_n))
        except ValueError:
            min_n_i = 1

        if not champion:
            h._send(400, b'{"ok":false,"error":"champion required"}',
                    "application/json")
            return

        db = _postgame_db_path()
        pairs: list[dict] = []
        if db.exists():
            conn = sqlite3.connect(_postgame_db_uri(db), uri=True, timeout=5.0)
            try:
                pairs = compute_champ_spell_winrates(
                    conn, champion, mode, min_n=min_n_i)
            finally:
                conn.close()

        h._send(200, json.dumps({
            "ok":       True,
            "champion": champion,
            "mode":     mode,
            "min_n":    min_n_i,
            "pairs":    pairs,          # [] when corpus empty / no data
            "best":     (pairs[0]["pair"] if pairs else None),
        }).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/spell-winrates: %s", type(exc).__name__)
        h._send(500, json.dumps(
            {"ok": False, "error": "internal error - see logs"}).encode(),
            "application/json")


def _serve_adaptive_summoners(h) -> None:
    try:
        qs = parse_qs(urlparse(h.path).query)
        champion = (qs.get("champion") or [""])[0].strip()
        role     = (qs.get("role")     or [""])[0].strip().upper()
        enemy_ids = _parse_int_csv((qs.get("enemy_ids") or [""])[0])
        base      = _parse_int_csv((qs.get("base")      or [""])[0])

        if not champion:
            h._send(400, b'{"ok":false,"error":"champion required"}', "application/json")
            return

        enemy_names = _resolve_enemy_names(enemy_ids)
        threat = _compute_threat(enemy_names)
        rec = _recommend(base, role, threat)
        base = base[:2]

        h._send(200, json.dumps({
            "ok":          True,
            "champion":    champion,
            "role":        role,
            "enemy_count": len(enemy_ids),
            "enemy_names": enemy_names,
            "base":        base,
            "summoners":   rec["summoners"],
            "swapped":     rec["swapped"],
            "swap_from_id": rec["swap_from_id"],
            "swap_from":    rec["swap_from"],
            "swap_to_id":   rec["swap_to_id"],
            "swap_to":      rec["swap_to"],
            "reason":      rec["reason"],
            "threat":      threat,
        }).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001
        log.warning("api/champ-select/adaptive-summoners: %s",
                    type(exc).__name__)
        # Raw exception text reaches neither the response nor the log; the
        # log carries the exception type.
        h._send(500, json.dumps(
            {"ok": False, "error": "internal error - see logs"}).encode(),
            "application/json")


# Route table - imported by dashboard/_dispatch.py at module load.
def _equals(p: str):
    def m(path: str) -> bool: return path.split("?", 1)[0] == p
    return m


GET_ROUTES = [
    (_equals("/api/champ-select/adaptive-summoners"), _serve_adaptive_summoners),
    (_equals("/api/champ-select/spell-winrates"), _serve_spell_winrates),
]
POST_ROUTES: list = []
