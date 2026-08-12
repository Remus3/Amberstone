"""s209: enemy-comp adaptive summoner recommendation.

GET /api/champ-select/adaptive-summoners
    ?champion=<Display Name>
    &enemy_ids=86,64,157,145,412
    &role=BOT|JUNGLE|...
    &base=4,7

Recommends the summoner spell pair for the operator's pick against the
locked-in enemy comp. The decision tree is deliberately small:

  - Flash always stays primary (slot D = id 4) - only edge case is jungle
    on Smite-required queues, but the LCU rejects no-Smite picks so we
    keep Flash on as a safety net.
  - Secondary swaps to **Cleanse** (id 1) when >=2 hard-CC enemies are
    locked AND the operator is BOT/MID/ADC-style role. Cleanse breaks
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


def _parse_int_csv(raw: str) -> list[int]:
    out: list[int] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out


# Module-level lazy cache: champion-id (int) -> display name (str).
# Built from data/meta/ddragon_champions.json on first call. The
# threat-profile classifier in core.defensive_picks already loads the
# same file with apostrophe-and-space variants under the same keys, so
# the names we return here flow cleanly through that pipeline.
_ID_TO_NAME: dict[int, str] | None = None


def _load_id_to_name() -> dict[int, str]:
    global _ID_TO_NAME
    if _ID_TO_NAME is not None:
        return _ID_TO_NAME
    out: dict[int, str] = {}
    try:
        from pathlib import Path
        raw = json.loads(
            (Path(__file__).resolve().parent.parent
             / "data" / "meta" / "ddragon_champions.json").read_text(encoding="utf-8")
        )
        data = raw.get("data", raw)
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            name = entry.get("name")
            if key and name:
                try:
                    out[int(key)] = str(name)
                except (TypeError, ValueError):
                    continue
    except Exception as exc:  # noqa: BLE001
        log.warning("adaptive-summoners: ddragon_champions load failed: %s", exc)
    _ID_TO_NAME = out
    return out


def _resolve_enemy_names(enemy_ids: list[int]) -> list[str]:
    """Convert champion-ids to display names via the DDragon index.
    Returns empty string for ids we can't resolve - the threat-profile
    classifier tolerates "" silently."""
    idx = _load_id_to_name()
    return [str(idx.get(int(cid)) or "") for cid in enemy_ids]


def _compute_cc_score(enemy_names: list[str]) -> float:
    """Fraction of enemies in _HARD_CC_CHAMPIONS, scaled to 0-10."""
    if not enemy_names:
        return 0.0
    n_total = max(1, len(enemy_names))
    n_hits = sum(1 for nm in enemy_names if nm and nm in _HARD_CC_CHAMPIONS)
    return min(10.0, (n_hits / n_total) * 10.0)


def _compute_threat(enemy_names: list[str]) -> dict:
    """Wraps core.defensive_picks.compute_threat_profile + adds cc_threat.
    Defensive against import failures (engine not installed) - returns a
    zero-threat profile so the route still answers."""
    try:
        from core.defensive_picks import compute_threat_profile
        profile = compute_threat_profile(enemy_names) or {}
    except Exception:  # noqa: BLE001
        profile = {}
    profile["cc_threat"] = round(_compute_cc_score(enemy_names), 1)
    return profile


def _recommend(base: list[int], role: str, threat: dict) -> dict:
    """Decision tree -> (summoners, swap_to_name, reason). When no swap
    fires, returns the base pair with swap_to=None.

    base : the variant's stored summoner pair (often [4, 21] = Flash+Barrier
           for carry; [4, 7] retained for support duo + Senna/Kalista).
    role : LCU/dashboard form; we accept either via _BARRIER_ELIGIBLE_ROLES.
    """
    primary   = base[0] if base else _FLASH
    secondary = base[1] if len(base) > 1 else _HEAL
    base_secondary = secondary

    cc_threat    = float(threat.get("cc_threat") or 0.0)
    burst_threat = float(threat.get("burst_threat") or 0.0)
    role_upper = (role or "").upper()

    if cc_threat >= _CC_SWAP_THRESHOLD and role_upper in _CLEANSE_ELIGIBLE_ROLES:
        secondary = _CLEANSE
        reason = f"CC threat {cc_threat:.0f}/10 · Cleanse > Heal"
    elif burst_threat >= _BURST_SWAP_THRESHOLD and role_upper in _BARRIER_ELIGIBLE_ROLES:
        secondary = _BARRIER
        reason = f"burst threat {burst_threat:.0f}/10 · Barrier > Heal"
    else:
        reason = (
            f"baseline · {_SPELL_NAMES.get(secondary, str(secondary))}"
            + (f" (CC {cc_threat:.0f} / burst {burst_threat:.0f})"
               if (cc_threat or burst_threat) else "")
        )

    swapped = secondary != base_secondary
    return {
        "summoners":     [primary, secondary],
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
# the WR lookup keys the same table the collector writes.
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
    except Exception as exc:  # noqa: BLE001 - missing table / bad champ -> empty
        log.debug("spell-winrates: query failed for %s/%s: %s",
                  champion, mode, exc)
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
def _postgame_db_path():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent
            / "data" / "postgame_stats.db")


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
            import sqlite3
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
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
        log.warning("api/champ-select/spell-winrates: %s", exc)
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
        log.warning("api/champ-select/adaptive-summoners: %s", exc)
        # Raw exception text stays in the log only.
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
