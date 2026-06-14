"""
Aftergame summary generator.

Queries `match_metrics.db` for the just-completed match's metrics and
joins against `champion_benchmarks.json` to produce the aftergame
payload fields the dashboard reads in client mode:

  - advice_headline       - single line take on the match
  - advice_objective      - session/rank-goal framing
  - key_points_review     - 3 bullets to pay attention to in VOD review
  - clips_review          - single clip timestamp worth rewatching
  - what_went_good        - list of 2-5 positives
  - what_went_bad         - list of 2-5 negatives
  - game_sense_early/mid/late   - one word each from GAME_SENSE_VOCAB
  - game_sense_*_blurb    - short why-this-word
  - game_sense_trend      - aggregate of last-N game_sense_* ratings
  - digest_state          - none | ok | warn | alert
  - digest_* fields       - when state != none

This is a RULE-BASED generator (not LLM-driven). The logic compares
match metrics against the player's own historical benchmarks - above-p75
becomes a positive, below-p25 becomes a negative. Game Sense words
are selected by heuristic on match patterns (death count, kill spree,
time alive, comeback_flag, etc.). An LLM flavor pass can come later.

Designed to be called by `lcu_postgame_collector` after it ingests a
finished match into rewind_history, OR by a periodic hook from
`game_lifecycle.py` when it detects transition to end-of-game.

Usage:
    from core.aftergame_summary import build_summary
    summary = build_summary(match_id="NA1_...", puuid=..., outcome="win")
    # summary is a dict matching the p.* keys the UI reads
    # write into data/coaching_data.json so client-mode shows it
"""
from __future__ import annotations
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional, Any

_log = logging.getLogger("rc.aftergame_summary")

ROOT = Path(__file__).resolve().parent.parent
METRICS_DB = ROOT / "data" / "match_metrics.db"
REWIND_DB = ROOT / "data" / "rewind_history.db"

try:
    from core.benchmarks import get as _bench_get, rank_value, games_for
except ImportError:
    # Minimal fallback if benchmarks not yet generated
    def _bench_get(*a, **kw): return {}
    def rank_value(*a, **kw): return "no-data"
    def games_for(*a, **kw): return 0


# Metrics we consider "signal-rich" for positive/negative surfacing.
# Each entry: (metric_key, higher_is_better, friendly_label_template)
# Template gets .format(value=v, p25=p25, p50=p50, p75=p75) at the end.
_POSITIVE_CANDIDATES: list[tuple[str, bool, str]] = [
    ("kill_participation_pct",  True,  "Kill participation {value}% (above your {p75}% p75)"),
    ("damage_share",            True,  "Damage share {value}% (above your {p75}% p75)"),
    ("cs_at_10",                True,  "CS@10 {value} (above your {p75} p75)"),
    ("cs_at_15",                True,  "CS@15 {value} (above your {p75} p75)"),
    ("longest_alive_s",         True,  "Longest-alive streak {value}s (above your {p75}s p75)"),
    ("time_alive_pct",          True,  "Time alive {value}% (above your {p75}% p75)"),
    ("vision_score",            True,  "Vision score {value} (above your {p75} p75)"),
]
_NEGATIVE_CANDIDATES: list[tuple[str, bool, str]] = [
    ("kill_participation_pct",  True,  "Kill participation {value}% (below your {p25}% p25)"),
    ("damage_share",            True,  "Damage share {value}% (below your {p25}% p25)"),
    ("cs_at_10",                True,  "CS@10 {value} (below your {p25} p25)"),
    ("cs_at_15",                True,  "CS@15 {value} (below your {p25} p25)"),
    ("vision_score",            True,  "Vision score {value} - below your {p25} p25"),
    ("time_alive_pct",          True,  "Time alive {value}% (below your {p25}% p25)"),
]


def _metric_values_for_match(match_id: str) -> dict[str, str]:
    """Return {metric_key: metric_value} from match_metrics for this match,
    preferring game_end milestone rows when duplicates exist."""
    if not METRICS_DB.exists():
        return {}
    conn = sqlite3.connect(f"file:{METRICS_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT metric_key, metric_value, milestone_tag "
            "FROM match_metrics WHERE match_id=? "
            "ORDER BY CASE WHEN milestone_tag='game_end' THEN 0 ELSE 1 END",
            (match_id,),
        ).fetchall()
        out: dict[str, str] = {}
        for k, v, _tag in rows:
            if k not in out:
                out[k] = v
        return out
    finally:
        conn.close()


def _first_int(s: str) -> Optional[int]:
    m = re.search(r"-?\d+", s or "")
    return int(m.group(0)) if m else None


def _match_meta(match_id: str) -> dict:
    """Pull match-level facts from rewind_history (champion, mode, result)."""
    if not REWIND_DB.exists():
        return {}
    conn = sqlite3.connect(f"file:{REWIND_DB}?mode=ro", uri=True)
    try:
        r = conn.execute(
            "SELECT tracked_champion_name, queue_id, game_duration_s, "
            "       tracked_win, tracked_kills, tracked_deaths, tracked_assists "
            "FROM matches WHERE match_id=?",
            (match_id,),
        ).fetchone()
        if not r:
            return {}
        return {
            "champion": r[0],
            "queue_id": r[1],
            "duration_s": r[2],
            "win": bool(r[3]),
            "kills": r[4],
            "deaths": r[5],
            "assists": r[6],
            "mode": "sr_ranked" if r[1] == 420 else ("sr_flex" if r[1] == 440 else "sr"),
        }
    finally:
        conn.close()


def _pick_game_sense(metrics: dict, meta: dict) -> dict:
    """Heuristic Game Sense picker. Returns {early, mid, late, *_blurb}.

    The heuristic is deliberately simple and rule-based - an LLM flavor
    pass can re-select words with richer context later. For now:
      EARLY - picks from {Composed, Hesitant, Reactive, Steady, Chaotic}
      MID   - picks from {Opportunistic, Patient, Reactive, Scattered, Tilted}
      LATE  - picks from {Dominant, On Point, Steady, Drowning, Chaotic}
    based on match features we can see: CS@10 diff, kill-spree size,
    time_dead %, damage share, death count.
    """
    deaths = meta.get("deaths", 0)
    duration = meta.get("duration_s", 1) or 1
    win = meta.get("win", False)

    # EARLY phase: look at CS@10, lane prio signals
    cs_at_10 = _first_int(metrics.get("cs_at_10", ""))
    first_blood_self = _first_int(metrics.get("first_blood_self", ""))
    if cs_at_10 is not None and cs_at_10 >= 75:
        early, early_blurb = "Composed", f"CS@10 {cs_at_10} - clean early execution."
    elif first_blood_self == 1:
        early, early_blurb = "Opportunistic", "First-blood in the first 4 minutes."
    elif cs_at_10 is not None and cs_at_10 < 55:
        early, early_blurb = "Hesitant", f"CS@10 {cs_at_10} - early bleed vs lane opp."
    elif deaths >= 3 and duration < 900:
        early, early_blurb = "Chaotic", "Multiple deaths before 15min - lost early tempo."
    else:
        early, early_blurb = "Steady", "No early standout, no early mistakes."

    # MID phase: KP, time_dead, damage_share
    kp = _first_int(metrics.get("kill_participation_pct", ""))
    time_dead = _first_int(metrics.get("time_dead_summary", ""))
    dmg_share = _first_int(metrics.get("damage_share", ""))
    if kp is not None and kp >= 65 and time_dead is not None and time_dead <= 60:
        mid, mid_blurb = "Opportunistic", f"KP {kp}% with only {time_dead}s dead - you showed up for fights."
    elif time_dead is not None and time_dead >= 180:
        mid, mid_blurb = "Tilted", f"Spent {time_dead}s dead through mid - kept rolling into bad fights."
    elif dmg_share is not None and dmg_share >= 30:
        mid, mid_blurb = "Dominant", f"Carrying dmg share at {dmg_share}% mid."
    elif kp is not None and kp < 40:
        mid, mid_blurb = "Scattered", f"Low KP {kp}% through mid - off-map."
    elif deaths >= 6:
        mid, mid_blurb = "Chaotic", "Deaths compounded through mid."
    else:
        mid, mid_blurb = "Reactive", "Arrived at most fights, none decisively won or lost."

    # LATE phase: match outcome, longest_alive
    longest = _first_int(metrics.get("longest_alive_s", ""))
    turret_kills = _first_int(metrics.get("tower_kills", ""))
    if win and longest and longest >= 420:
        late, late_blurb = "Dominant", f"Held {longest}s alive in late - closed the game clean."
    elif win and turret_kills and turret_kills >= 3:
        late, late_blurb = "On Point", f"{turret_kills} turret kills - read the siege window."
    elif not win and deaths >= 8:
        late, late_blurb = "Drowning", "Deaths piled up in late - tempo fully reset."
    elif not win and longest and longest < 180:
        late, late_blurb = "Scattered", "No long alive streaks in late - caught repeatedly."
    elif win:
        late, late_blurb = "Steady", "Closed the game without standout late plays."
    else:
        late, late_blurb = "Hesitant", "Late game stayed defensive; no reclamation attempt."

    return {
        "game_sense_early": early,
        "game_sense_early_blurb": early_blurb,
        "game_sense_mid": mid,
        "game_sense_mid_blurb": mid_blurb,
        "game_sense_late": late,
        "game_sense_late_blurb": late_blurb,
    }


def _pick_what_went(metrics: dict, meta: dict) -> tuple[list[str], list[str]]:
    """Return (what_went_good, what_went_bad) - each list of 2-5 bullets.
    Rule: top quartile hits vs personal benchmark -> positives; bottom
    quartile -> negatives. If no benchmark data, fall back to hard
    thresholds."""
    champ = meta.get("champion") or ""
    mode  = meta.get("mode") or ""
    have_benchmarks = games_for(champ, mode) >= 5

    goods: list[str] = []
    bads: list[str] = []

    for (metric_key, _higher, template) in _POSITIVE_CANDIDATES:
        raw = metrics.get(metric_key)
        if not raw:
            continue
        v = _first_int(raw)
        if v is None:
            continue
        if have_benchmarks:
            if rank_value(champ, mode, metric_key, v) == "above-p75":
                b = _bench_get(champ, mode, metric_key)
                goods.append(template.format(
                    value=v, p25=b.get("p25","?"), p50=b.get("p50","?"), p75=b.get("p75","?"),
                ))
        else:
            # Fallback hard thresholds when no benchmark data yet
            fallbacks = {
                "kill_participation_pct": 65,
                "damage_share": 28,
                "cs_at_10": 75,
                "cs_at_15": 115,
                "longest_alive_s": 480,
                "time_alive_pct": 93,
                "vision_score": 30,
            }
            th = fallbacks.get(metric_key)
            if th and v >= th:
                goods.append(f"{metric_key.replace('_',' ').title()}: {v} (strong)")

    for (metric_key, _higher, template) in _NEGATIVE_CANDIDATES:
        raw = metrics.get(metric_key)
        if not raw:
            continue
        v = _first_int(raw)
        if v is None:
            continue
        if have_benchmarks:
            if rank_value(champ, mode, metric_key, v) == "below-p25":
                b = _bench_get(champ, mode, metric_key)
                bads.append(template.format(
                    value=v, p25=b.get("p25","?"), p50=b.get("p50","?"), p75=b.get("p75","?"),
                ))
        else:
            fallbacks = {
                "kill_participation_pct": 40,
                "damage_share": 18,
                "cs_at_10": 55,
                "cs_at_15": 85,
                "vision_score": 12,
                "time_alive_pct": 85,
            }
            th = fallbacks.get(metric_key)
            if th is not None and v <= th:
                bads.append(f"{metric_key.replace('_',' ').title()}: {v} (below threshold)")

    # Death-specific negative if heavy
    deaths = meta.get("deaths", 0)
    if deaths >= 8:
        bads.append(f"Died {deaths} times - position/discipline issue.")

    # Cap lists
    return goods[:5], bads[:5]


def _pick_advice(metrics: dict, meta: dict, goods: list[str], bads: list[str]) -> dict:
    """Pick advice_headline + objective + key points + clips line."""
    win = meta.get("win", False)
    deaths = meta.get("deaths", 0)

    if win and deaths <= 3:
        headline = "Clean win - preserve the streak"
        objective = "Next game: same build, same map pace"
    elif win:
        headline = f"Won despite {deaths} deaths - cheese-it-out win"
        objective = "Next game: tighten death discipline, keep the aggression"
    elif deaths >= 8:
        headline = "Heavy loss - consider a break"
        objective = "Break 15min, single clip review, requeue only if calm"
    else:
        headline = "Close loss - fixable"
        objective = "Review: laning phase + mid-game rotations"

    # Key points: invert the bads into action items
    key_points = []
    for bad in bads[:3]:
        # Turn "Vision Score 12 - below your 22 p25" into
        # "Push vision to 20+ (you were 12)"
        if "Vision" in bad:
            key_points.append("Push vision score to match your personal p50 target")
        elif "CS" in bad:
            key_points.append("Target matching lane opponent's CS at each 5-minute checkpoint")
        elif "Kill participation" in bad:
            key_points.append("Roam and show up to fights more actively")
        elif "Died" in bad:
            key_points.append("Cut 2 deaths: identify repeated positional error in clips")
        else:
            key_points.append(f"Re-watch and address: {bad}")
    if not key_points:
        key_points = ["Continue current approach - metrics are at your baseline"]

    clips_review = "Full match - no single clip flagged; review around each death cluster."
    # Try to find a death cluster from match_metrics timeline (if it has death events)
    # For MVP just keep the generic line.

    return {
        "advice_headline": headline,
        "advice_objective": objective,
        "key_points_review": " · ".join(key_points),
        "clips_review": clips_review,
    }


def _game_sense_trend(champ: str, mode: str, phase: str) -> str:
    """Aggregate text_freq for game_sense_<phase> from benchmarks."""
    try:
        from core.benchmarks import text_freq
        freq = text_freq(champ, mode, f"game_sense_{phase}")
    except Exception:
        freq = {}
    if not freq:
        return ""
    ordered = sorted(freq.items(), key=lambda kv: -kv[1])
    top = ordered[:4]
    total = sum(freq.values())
    return " · ".join(f"{n}× {w}" for w, n in top) + f" (of {total})"


def _pick_digest(meta: dict, metrics: dict) -> dict:
    """Detect cold-streak / slump patterns from session state. Returns
    a digest_* dict. For MVP: leave as 'none' unless obvious signal.
    Real detection logic will query session-scope rows from
    match_metrics (session_id joins) in a future pass."""
    # MVP - no session_id threading yet; leave neutral.
    return {
        "digest_state": "none",
        "digest_label": "-",
        "digest_tooltip": "cross-session digest",
    }


def build_summary(match_id: str, *, puuid: Optional[str] = None,
                  outcome: Optional[str] = None) -> dict:
    """Produce the aftergame payload dict for a given match_id.

    Joins match_metrics + champion_benchmarks + match meta into a
    coherent summary. Safe to call repeatedly; deterministic given the
    same inputs. Returns {} if data is insufficient."""
    meta = _match_meta(match_id)
    if not meta:
        return {}
    metrics = _metric_values_for_match(match_id)

    champ = meta["champion"]
    mode  = meta["mode"]

    # Game Sense
    gs = _pick_game_sense(metrics, meta)

    # What went good / bad
    goods, bads = _pick_what_went(metrics, meta)

    # Advice
    adv = _pick_advice(metrics, meta, goods, bads)

    # Trend (across champion history)
    trend = _game_sense_trend(champ, mode, "early") or \
            _game_sense_trend(champ, mode, "mid")  or \
            _game_sense_trend(champ, mode, "late")
    if trend:
        trend = f"Last N games: {trend}"

    # Digest
    dig = _pick_digest(meta, metrics)

    out: dict[str, Any] = {
        **adv,
        **gs,
        **dig,
        "what_went_good": goods,
        "what_went_bad":  bads,
        "game_sense_trend": trend or "no trend data yet",
        "kda": f"{meta['kills']}/{meta['deaths']}/{meta['assists']}",
        "champion": champ,
    }
    # Outcome headline prefix
    if outcome is None:
        outcome = "VICTORY" if meta["win"] else "DEFEAT"
    out["action"] = f"{'✓' if meta['win'] else '⚠'} {outcome}"
    return out


def write_to_client_coaching_data(summary: dict,
                                   target: Optional[Path] = None) -> bool:
    """Merge the summary dict into data/coaching_data.json (client mode).

    Preserves any existing unrelated keys. Atomic write via tmp.replace.
    Returns True if the file was written.
    """
    if not summary:
        return False
    target = target or (ROOT / "data" / "coaching_data.json")
    try:
        current = {}
        if target.exists():
            try:
                current = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                current = {}
        # Client-mode payload - merge summary fields in
        current.update(summary)
        current["mode"] = current.get("mode") or "client"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(target)
        return True
    except Exception as exc:
        # Fail-soft boundary (caller treats False as "not written") but the
        # error must not vanish silently - log it for the ops trail.
        _log.warning("write_to_client_coaching_data failed for %s: %s",
                     target, exc)
        return False


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write_flag = "--write" in sys.argv
    mid = args[0] if args else "NA1_5182398158"
    s = build_summary(mid)
    if not s:
        print(f"no summary produced for match_id={mid}", file=sys.stderr)
        sys.exit(1)
    if write_flag:
        ok = write_to_client_coaching_data(s)
        print(f"wrote data/coaching_data.json: {ok}", file=sys.stderr)
    print(json.dumps(s, indent=2, ensure_ascii=False))
