"""Coach-facing read API for Agent 4's adaptation aggregates.

Opt-in helper — existing coaches stay unchanged unless they explicitly
import this module. That preserves the "coach Python is propose-and-
queue" charter rule: wiring this into ``_base_coach.py`` or any
mode-specific coach is a future proposal, not this round's work.

Typical use:

    from coaches.adaptation_hint import format_hint_line

    hint = format_hint_line(champion="Ahri", mode="aram",
                            enemies=["Xerath", "Jinx", "Garen"])
    # hint is either "" or a short prose line like:
    #   "Ahri ARAM baseline 54% wr (n=61). Enemy Xerath flags: +46% "
    #   "(strongest counter of active matchups)."

Contracts:
  * Never raises in the happy path — missing DB, missing bucket, missing
    matchup all return empty / None. Coaches call this from a hot path
    and can't tolerate exceptions.
  * Read-only. Agent 4 owns the writes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("coaches.adaptation_hint")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = _PROJECT_ROOT / "data" / "db"

from lib.modes import PHASE3_MODES as SUPPORTED_MODES

# How many top counter-matchups to surface.
_DEFAULT_TOP_COUNTERS = 3
# Matchup must have at least this sample size to be considered for a hint.
_MIN_SAMPLE = 5
# Only flag a matchup when it meaningfully deviates from baseline.
_MIN_ABSOLUTE_DELTA = 0.15


def _db(mode: str) -> Path | None:
    if mode not in SUPPORTED_MODES:
        return None
    p = DB_DIR / f"{mode}.db"
    return p if p.exists() else None


def for_champion(champion: str, mode: str) -> dict:
    """Return the bucket + top activated matchups for (champion, mode).

    Shape::

        {
          "champion": "Ahri",
          "mode": "aram",
          "present": True,
          "games_played": 61,
          "wins": 33,
          "losses": 28,
          "win_rate": 0.541,
          "recent_win_rate": 0.40,
          "recent_sample_size": 10,
          "avg_duration_sec": 1142.3,
          "counters": [
              {"opponent": "Xerath", "sample": 5, "observed_wr": 1.0,
               "baseline_wr": 0.54, "delta": 0.459},
              ...
          ]
        }

    ``present=False`` on missing DB / missing row. Never raises.
    """
    out: dict = {
        "champion": champion,
        "mode": mode,
        "present": False,
        "games_played": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "recent_win_rate": None,
        "recent_sample_size": 0,
        "avg_duration_sec": None,
        "counters": [],
    }
    db = _db(mode)
    if db is None:
        return out
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM adaptation_buckets WHERE champion = ?",
                (champion,),
            ).fetchone()
            if row is None:
                return out
            out["present"] = True
            out["games_played"] = int(row["games_played"])
            out["wins"] = int(row["wins"])
            out["losses"] = int(row["losses"])
            out["win_rate"] = float(row["avg_rating"])
            try:
                aj = json.loads(row["aggregates_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                aj = {}
            out["recent_win_rate"] = aj.get("recent_win_rate")
            out["recent_sample_size"] = int(aj.get("recent_sample_size") or 0)
            out["avg_duration_sec"] = aj.get("avg_duration_sec")
            out["top_items"] = aj.get("top_items") or []
            out["first_legendary"] = aj.get("first_legendary") or []
            out["recency_30d"] = aj.get("recency_30d") or None
            out["avg_kda"] = aj.get("avg_kda") or None
            out["recent_kda"] = aj.get("recent_kda") or None

            # Activated matchups sorted by |delta| desc.
            mrows = conn.execute(
                """
                SELECT opponent_signature, sample_count, modifier_json
                FROM matchup_modifiers
                WHERE champion = ? AND activated = 1
                """,
                (champion,),
            ).fetchall()
            scored = []
            for m in mrows:
                try:
                    mj = json.loads(m["modifier_json"] or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue
                delta = float(mj.get("delta") or 0.0)
                if abs(delta) < _MIN_ABSOLUTE_DELTA:
                    continue
                entry = {
                    "opponent": m["opponent_signature"],
                    "sample": int(m["sample_count"]),
                    "observed_wr": float(mj.get("observed_wr") or 0.0),
                    "baseline_wr": float(mj.get("baseline_wr") or 0.0),
                    "delta": delta,
                }
                if "kda_ratio" in mj:
                    entry["kda_ratio"] = float(mj["kda_ratio"])
                    entry["kda_sample"] = int(mj.get("kda_sample") or 0)
                    if "kda_delta" in mj:
                        entry["kda_delta"] = float(mj["kda_delta"])
                scored.append(entry)
            scored.sort(key=lambda d: abs(d["delta"]), reverse=True)
            out["counters"] = scored
    except sqlite3.Error as e:
        logger.debug("for_champion sqlite err %s/%s: %s", champion, mode, e)
    return out


def matchup_delta(champion: str, mode: str, opponent: str) -> float | None:
    """Return the ``delta`` (observed_wr - baseline_wr) for a specific
    (champion × opponent × mode) matchup, or None if not activated /
    below sample threshold. Cheap single-row lookup."""
    db = _db(mode)
    if db is None:
        return None
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT sample_count, modifier_json
                FROM matchup_modifiers
                WHERE champion = ? AND opponent_signature = ?
                """,
                (champion, opponent),
            ).fetchone()
    except sqlite3.Error as e:
        logger.debug("matchup_delta err %s/%s vs %s: %s", champion, mode, opponent, e)
        return None
    if row is None or int(row["sample_count"]) < _MIN_SAMPLE:
        return None
    try:
        mj = json.loads(row["modifier_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    return float(mj.get("delta") or 0.0)


def format_hint_line(
    champion: str,
    mode: str,
    enemies: Iterable[str] | None = None,
    top_n: int = _DEFAULT_TOP_COUNTERS,
) -> str:
    """One-liner suitable for inlining into a coach prompt.

    Returns ``""`` (empty string) when there's nothing useful to say —
    so the coach can safely concatenate without conditionals.
    """
    data = for_champion(champion, mode)
    if not data["present"] or not data["games_played"]:
        return ""

    wr = data["win_rate"]
    n = data["games_played"]
    recent = data["recent_win_rate"]
    parts = [
        f"{champion} {mode.upper().replace('_', ' ')} baseline "
        f"{wr*100:.0f}% wr (n={n})"
    ]
    if recent is not None and data["recent_sample_size"] >= 5:
        direction = "↑" if recent > wr + 0.05 else ("↓" if recent < wr - 0.05 else "·")
        parts.append(f"recent {recent*100:.0f}% {direction}")

    # 30-day meta-trend bucket (separate from last-N rolling).
    r30 = data.get("recency_30d")
    if r30 and r30.get("games", 0) >= 5:
        dv = r30.get("delta_vs_alltime", 0.0) or 0.0
        direction = "↑" if dv > 0.05 else ("↓" if dv < -0.05 else "·")
        parts.append(
            f"30d {r30.get('win_rate', 0)*100:.0f}% {direction} "
            f"(n={r30.get('games')})"
        )

    # Typical KDA — survivability signal, independent of win/loss so it
    # lights up even before the first live reconcile.
    kda = data.get("avg_kda")
    if kda and kda.get("sample", 0) >= 5:
        seg = (
            f"typical KDA {kda['ratio']} "
            f"({kda['k']}/{kda['d']}/{kda['a']}, n={kda['sample']})"
        )
        rkda = data.get("recent_kda")
        if rkda and rkda.get("sample", 0) >= 5:
            delta = rkda.get("delta_ratio", 0.0)
            direction = "↑" if delta > 0.3 else ("↓" if delta < -0.3 else "·")
            sign = "+" if delta >= 0 else ""
            seg += (
                f" · recent {rkda['ratio']} {direction} "
                f"({sign}{delta} vs baseline, n={rkda['sample']})"
            )
        parts.append(seg)

    # Highlight matchups actually present on the enemy team, if given.
    enemy_set = set(enemies) if enemies else None
    flagged: list[str] = []
    for c in data["counters"]:
        if enemy_set is not None and c["opponent"] not in enemy_set:
            continue
        sign = "+" if c["delta"] >= 0 else ""
        seg = f"vs {c['opponent']} {sign}{c['delta']*100:.0f}% (n={c['sample']})"
        # Matchup KDA delta — only surface if meaningful (|Δ| ≥ 0.3).
        if "kda_delta" in c and abs(c["kda_delta"]) >= 0.3:
            ksign = "+" if c["kda_delta"] >= 0 else ""
            seg += f" KDA {c['kda_ratio']} ({ksign}{c['kda_delta']})"
        flagged.append(seg)
        if len(flagged) >= top_n:
            break

    if flagged:
        parts.append("active matchups: " + ", ".join(flagged))

    # First-legendary signal (most actionable — tells the coach "rush X")
    first_leg = data.get("first_legendary") or []
    if first_leg:
        fl_parts = []
        for it in first_leg[:2]:
            sign = "+" if it.get("delta", 0) >= 0 else ""
            name = it.get("name") or it.get("item_id")
            fl_parts.append(
                f"{name} {sign}{it['delta']*100:.0f}% (n={it['matches']})"
            )
        parts.append("first-leg signal: " + "; ".join(fl_parts))

    # Generic item-outcome signals (any pickup) — lower priority, smaller list
    items = data.get("top_items") or []
    item_parts = []
    for it in items[:2]:
        sign = "+" if it.get("delta", 0) >= 0 else ""
        name = it.get("name") or it.get("item_id")
        item_parts.append(
            f"{name} {sign}{it['delta']*100:.0f}% (n={it['matches']})"
        )
    if item_parts:
        parts.append("historic items: " + "; ".join(item_parts))

    return ". ".join(parts) + "."


def insight_card(
    champion: str,
    mode: str,
    enemies: Iterable[str] | None = None,
    max_chars: int = 240,
) -> str:
    """Compact copy-to-clipboard summary — one line, bounded.

    Returns "" when no champion data. Format:
      "Tristana ARAM 72% wr (n=61) ↑ · rush Statikk Shiv (+19%) ·
       vs Morgana -52% (n=5)"

    Always ends after cutting at a ``·`` boundary so the card never
    ends mid-phrase. ``max_chars`` defaults to 240 — long enough for
    two lines on iPad, short enough for a Discord paste.
    """
    data = for_champion(champion, mode)
    if not data["present"] or not data["games_played"]:
        return ""
    segs: list[str] = []
    wr = data["win_rate"]
    n = data["games_played"]
    head = f"{champion} {mode.upper().replace('_',' ')} {wr*100:.0f}% wr (n={n})"
    r30 = data.get("recency_30d")
    if r30 and r30.get("games", 0) >= 5:
        dv = r30.get("delta_vs_alltime") or 0
        arrow = "↑" if dv > 0.05 else ("↓" if dv < -0.05 else "·")
        head += f" {arrow}30d {r30.get('win_rate',0)*100:.0f}%"
    segs.append(head)

    # KDA segment — only if we have enough sample to be meaningful.
    kda = data.get("avg_kda")
    if kda and kda.get("sample", 0) >= 5:
        kseg = f"KDA {kda['ratio']}"
        rkda = data.get("recent_kda")
        if rkda and rkda.get("sample", 0) >= 5:
            dr = rkda.get("delta_ratio", 0.0) or 0.0
            if abs(dr) >= 0.3:
                arrow = "↑" if dr > 0 else "↓"
                kseg += f" {arrow}{rkda['ratio']}"
        segs.append(kseg)

    # First-legendary (most actionable, short)
    first_leg = data.get("first_legendary") or []
    if first_leg:
        it = first_leg[0]
        sign = "+" if it.get("delta", 0) >= 0 else ""
        name = it.get("name") or it.get("item_id")
        verb = "rush" if it.get("delta", 0) > 0 else "avoid"
        segs.append(f"{verb} {name} ({sign}{it['delta']*100:.0f}%)")

    # Top items — one mention if space
    items = data.get("top_items") or []
    if items and len(first_leg) < 2:
        it = items[0]
        sign = "+" if it.get("delta", 0) >= 0 else ""
        name = it.get("name") or it.get("item_id")
        segs.append(f"{name} {sign}{it['delta']*100:.0f}%")

    # Enemy-specific counter if provided and in counters list
    enemy_set = set(enemies) if enemies else None
    for c in data.get("counters", []):
        if enemy_set is None or c["opponent"] in enemy_set:
            sign = "+" if c["delta"] >= 0 else ""
            segs.append(f"vs {c['opponent']} {sign}{c['delta']*100:.0f}% (n={c['sample']})")
            break

    out = " · ".join(segs)
    if len(out) <= max_chars:
        return out
    # Trim at a bullet boundary to keep the card grammatical.
    trimmed = out[:max_chars]
    if " · " in trimmed:
        trimmed = trimmed.rsplit(" · ", 1)[0]
    return trimmed


def top_champions(mode: str, n: int = 10, min_games: int = 20) -> list[dict]:
    """Top-N champions by games_played in ``mode`` with at least
    ``min_games`` sample. Useful for dashboards + LLM context.
    """
    db = _db(mode)
    if db is None:
        return []
    out: list[dict] = []
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT champion, games_played, wins, losses,
                       avg_rating, aggregates_json
                FROM adaptation_buckets
                WHERE games_played >= ?
                ORDER BY games_played DESC
                LIMIT ?
                """,
                (min_games, n),
            ).fetchall()
    except sqlite3.Error as e:
        logger.debug("top_champions err %s: %s", mode, e)
        return []
    for r in rows:
        try:
            aj = json.loads(r["aggregates_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            aj = {}
        out.append({
            "champion": r["champion"],
            "games_played": int(r["games_played"]),
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_rate": float(r["avg_rating"]),
            "recent_win_rate": aj.get("recent_win_rate"),
            "recent_sample_size": int(aj.get("recent_sample_size") or 0),
            "avg_duration_sec": aj.get("avg_duration_sec"),
            "avg_kda": aj.get("avg_kda"),
            "recent_kda": aj.get("recent_kda"),
        })
    return out


def kda_trends(mode: str, n: int = 3, min_sample: int = 5) -> dict:
    """Identify champions on KDA streaks (hot or cold) in ``mode``.

    Uses ``recent_kda.delta_ratio`` — positive means the last-N window
    is outperforming the all-time baseline, negative means the player
    is underperforming on that champion recently.

    Returns ``{"mode": mode, "hot": [...], "cold": [...]}`` where each
    entry has ``{champion, baseline_ratio, recent_ratio, delta,
    sample}``. Both lists are sorted by |delta| desc. Empty lists if
    the mode DB is missing or no champion has enough sample.
    """
    db = _db(mode)
    empty = {"mode": mode, "hot": [], "cold": []}
    if db is None:
        return empty
    entries: list[dict] = []
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT champion, aggregates_json FROM adaptation_buckets"
            ).fetchall()
    except sqlite3.Error as e:
        logger.debug("kda_trends err %s: %s", mode, e)
        return empty
    for r in rows:
        try:
            aj = json.loads(r["aggregates_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        avg = aj.get("avg_kda")
        rec = aj.get("recent_kda")
        if not avg or not rec:
            continue
        if int(rec.get("sample") or 0) < min_sample:
            continue
        delta = float(rec.get("delta_ratio") or 0.0)
        entries.append({
            "champion": r["champion"],
            "baseline_ratio": float(avg.get("ratio") or 0.0),
            "recent_ratio": float(rec.get("ratio") or 0.0),
            "delta": delta,
            "sample": int(rec.get("sample") or 0),
        })
    hot = sorted((e for e in entries if e["delta"] > 0),
                 key=lambda e: e["delta"], reverse=True)[:n]
    cold = sorted((e for e in entries if e["delta"] < 0),
                  key=lambda e: e["delta"])[:n]
    return {"mode": mode, "hot": hot, "cold": cold}


def _start_of_today_iso() -> str:
    """Local midnight, ISO-8601 with tz — used as default ``since`` for
    session_summary."""
    from datetime import datetime, timezone
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


def session_summary(since_iso: str | None = None) -> dict:
    """Aggregate every ``matches`` row across all mode DBs where
    ``started_at >= since_iso``.

    Default ``since_iso``: start of today, local timezone.

    Returns::

        {
          "since": "<iso>",
          "games": 12,
          "wins": 7,
          "losses": 5,
          "win_rate": 0.583,
          "avg_kda": {"k": 9.5, "d": 6.1, "a": 14.3, "ratio": 3.9, "sample": 12},
          "per_mode": {"aram": {...}, "sr_ranked": {...}},
          "champions": [
            {"champion": "Ahri", "games": 4, "wins": 3, "kda_ratio": 4.1, ...},
            ...
          ]
        }

    Never raises on missing DBs; each absent mode becomes an empty slot
    in ``per_mode`` with zero counts.
    """
    since = since_iso or _start_of_today_iso()
    totals = {"games": 0, "wins": 0, "losses": 0,
              "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
    per_mode: dict[str, dict] = {}
    champ_acc: dict[str, dict] = {}   # keyed by champion only (cross-mode)

    for mode in SUPPORTED_MODES:
        db = _db(mode)
        mode_slot = {"games": 0, "wins": 0, "losses": 0,
                     "kda_sample": 0, "kda_ratio": None}
        per_mode[mode] = mode_slot
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                # KDA columns may not exist if this DB predates round 23
                # *and* startup migration hasn't run.
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                rows = conn.execute(
                    f"""SELECT champion, win, duration_sec{extra}
                        FROM matches WHERE started_at >= ?""",
                    (since,),
                ).fetchall()
        except sqlite3.Error as e:
            logger.debug("session_summary err %s: %s", mode, e)
            continue
        mode_k = mode_d = mode_a = mode_ksample = 0
        for r in rows:
            champ = r["champion"] or "Unknown"
            totals["games"] += 1
            mode_slot["games"] += 1
            ca = champ_acc.setdefault(champ, {
                "champion": champ, "games": 0, "wins": 0, "losses": 0,
                "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0,
                "modes": set(),
            })
            ca["games"] += 1
            ca["modes"].add(mode)
            win = r["win"]
            if win == 1:
                totals["wins"] += 1; mode_slot["wins"] += 1; ca["wins"] += 1
            elif win == 0:
                totals["losses"] += 1; mode_slot["losses"] += 1; ca["losses"] += 1
            if has_kda:
                k, d, a = r["kills"], r["deaths"], r["assists"]
                if k is not None and d is not None and a is not None:
                    totals["k_sum"] += k; totals["d_sum"] += d; totals["a_sum"] += a
                    totals["kda_sample"] += 1
                    ca["k_sum"] += k; ca["d_sum"] += d; ca["a_sum"] += a
                    ca["kda_sample"] += 1
                    mode_k += k; mode_d += d; mode_a += a; mode_ksample += 1
        if mode_ksample:
            mk = mode_k / mode_ksample
            md = mode_d / mode_ksample
            ma = mode_a / mode_ksample
            mode_slot["kda_sample"] = mode_ksample
            mode_slot["kda_ratio"] = round((mk + ma) / max(md, 1.0), 2)

    # Overall KDA.
    avg_kda: dict | None = None
    if totals["kda_sample"]:
        k = totals["k_sum"] / totals["kda_sample"]
        d = totals["d_sum"] / totals["kda_sample"]
        a = totals["a_sum"] / totals["kda_sample"]
        avg_kda = {
            "k": round(k, 2), "d": round(d, 2), "a": round(a, 2),
            "ratio": round((k + a) / max(d, 1.0), 2),
            "sample": totals["kda_sample"],
        }

    wr = (totals["wins"] / (totals["wins"] + totals["losses"])
          if (totals["wins"] + totals["losses"]) else None)

    champs_list = []
    for ca in champ_acc.values():
        c_games = ca["games"]
        c_kda = None
        if ca["kda_sample"]:
            k = ca["k_sum"] / ca["kda_sample"]
            d = ca["d_sum"] / ca["kda_sample"]
            a = ca["a_sum"] / ca["kda_sample"]
            c_kda = round((k + a) / max(d, 1.0), 2)
        reported = ca["wins"] + ca["losses"]
        champs_list.append({
            "champion": ca["champion"],
            "games": c_games,
            "wins": ca["wins"],
            "losses": ca["losses"],
            "win_rate": (round(ca["wins"] / reported, 3) if reported else None),
            "kda_ratio": c_kda,
            "kda_sample": ca["kda_sample"],
            "modes": sorted(ca["modes"]),
        })
    champs_list.sort(key=lambda c: (-c["games"], -(c["kda_ratio"] or 0.0)))

    return {
        "since": since,
        "games": totals["games"],
        "wins": totals["wins"],
        "losses": totals["losses"],
        "win_rate": (round(wr, 3) if wr is not None else None),
        "avg_kda": avg_kda,
        "per_mode": per_mode,
        "champions": champs_list,
    }


# ── CLI ─────────────────────────────────────────────────────────────

def session_games(since_iso: str | None = None, limit: int | None = None) -> list[dict]:
    """Chronological timeline of matches across all mode DBs since
    ``since_iso`` (default: start of today, local time).

    Each row::

        {
          "started_at": "<iso>", "ended_at": "<iso or None>",
          "mode": "aram", "champion": "Ahri",
          "win": 1 or 0 or None,
          "duration_sec": 1234,
          "kda": {"k": 10, "d": 3, "a": 15} or None,
          "kda_ratio": 8.33 or None,
          "source": "live-phase3",
        }

    Sorted oldest-first so the dashboard can render a simple scrolling
    feed without re-sorting. ``limit`` clamps the tail (most recent N).
    Missing DBs / missing KDA cols are handled gracefully.
    """
    since = since_iso or _start_of_today_iso()
    rows: list[dict] = []
    for mode in SUPPORTED_MODES:
        db = _db(mode)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                cur = conn.execute(
                    f"""SELECT started_at, ended_at, champion, win,
                               duration_sec, source{extra}
                        FROM matches WHERE started_at >= ?
                        ORDER BY started_at""",
                    (since,),
                )
                for r in cur:
                    kda = None
                    kda_ratio = None
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            kda = {"k": k, "d": d, "a": a}
                            kda_ratio = round((k + a) / max(d, 1), 2)
                    rows.append({
                        "started_at": r["started_at"],
                        "ended_at": r["ended_at"],
                        "mode": mode,
                        "champion": r["champion"],
                        "win": r["win"],
                        "duration_sec": r["duration_sec"],
                        "kda": kda,
                        "kda_ratio": kda_ratio,
                        "source": r["source"],
                    })
        except sqlite3.Error as e:
            logger.debug("session_games err %s: %s", mode, e)
            continue
    rows.sort(key=lambda r: r["started_at"] or "")
    if limit is not None and limit > 0 and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def time_of_day_analysis(
    mode: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by local hour-of-day and return per-hour stats.

    ``mode`` restricts to a single mode DB; ``None`` sums across all.
    ``since_iso`` clamps history (default: all time).
    ``min_games`` controls what counts as an insight-worthy bucket —
    buckets below threshold are still returned but flagged
    ``insight=False`` so callers can filter cheaply.

    Returns::

        {
          "mode": mode or "all",
          "since": since_iso or None,
          "buckets": [
            {"hour": 0, "games": N, "wins": W, "losses": L,
             "win_rate": 0.5 or None, "kda_ratio": 2.3 or None,
             "insight": True or False},
            ...
          ],
          "best": {"hour": 15, ...} or None,
          "worst": {"hour": 2, ...} or None,
          "total_games": M,
        }
    """
    from datetime import datetime
    modes = (mode,) if mode else SUPPORTED_MODES

    # bucket[h] = {"games","wins","losses","k","d","a","kda_sample"}
    buckets: dict[int, dict] = {
        h: {"games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
        for h in range(24)
    }
    total_games = 0

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                where = ""
                params: tuple = ()
                if since_iso:
                    where = "WHERE started_at >= ?"
                    params = (since_iso,)
                cur = conn.execute(
                    f"SELECT started_at, win{extra} FROM matches {where}",
                    params,
                )
                for r in cur:
                    ts = r["started_at"]
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    # Convert to local time — rewind history is UTC; the
                    # user cares what wall-clock hour they played at.
                    hour = dt.astimezone().hour
                    b = buckets[hour]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("time_of_day err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for h in range(24):
        b = buckets[h]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            k = b["k_sum"] / b["kda_sample"]
            d = b["d_sum"] / b["kda_sample"]
            a = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((k + a) / max(d, 1.0), 2)
        out_buckets.append({
            "hour": h,
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    # Best/worst based on win_rate, broken by KDA ratio. Only consider
    # insight-worthy buckets so a single-game outlier can't top the list.
    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }


_WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Duration tiers in seconds. Tuned to LoL ARAM (fast) + SR (slower)
# combined — short (<15) captures stomps / surrenders, long (35+)
# captures scaling-dependent outcomes.
_DURATION_TIERS = (
    ("stomp",    0,    15 * 60),
    ("quick",    15 * 60, 25 * 60),
    ("standard", 25 * 60, 35 * 60),
    ("long",     35 * 60, 10 ** 9),   # open-ended upper bound
)


def duration_analysis(
    mode: str | None = None,
    champion: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by game duration and return per-tier win-rate + KDA.

    Tiers: stomp (<15min), quick (15-25), standard (25-35), long (35+).
    ``champion`` filters to one champ (cross-mode if ``mode`` is None).
    Returns the same shape as time_of_day_analysis: per-tier buckets
    plus ``best`` / ``worst`` picked from insight-worthy tiers.
    """
    modes = (mode,) if mode else SUPPORTED_MODES

    # Per-tier accumulator indexed by tier name.
    buckets: dict[str, dict] = {
        name: {
            "games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0,
            "lo_sec": lo, "hi_sec": hi,
        }
        for (name, lo, hi) in _DURATION_TIERS
    }
    total_games = 0

    def _tier_for(dur: int) -> str | None:
        for (name, lo, hi) in _DURATION_TIERS:
            if lo <= dur < hi:
                return name
        return None

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                clauses = ["duration_sec IS NOT NULL", "duration_sec > 0"]
                params: list = []
                if since_iso:
                    clauses.append("started_at >= ?")
                    params.append(since_iso)
                if champion:
                    clauses.append("champion = ?")
                    params.append(champion)
                where = "WHERE " + " AND ".join(clauses)
                cur = conn.execute(
                    f"SELECT duration_sec, win{extra} FROM matches {where}",
                    tuple(params),
                )
                for r in cur:
                    dur = int(r["duration_sec"])
                    tier = _tier_for(dur)
                    if tier is None:
                        continue
                    b = buckets[tier]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("duration_analysis err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for (name, _, _) in _DURATION_TIERS:
        b = buckets[name]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            kk = b["k_sum"] / b["kda_sample"]
            dd = b["d_sum"] / b["kda_sample"]
            aa = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((kk + aa) / max(dd, 1.0), 2)
        out_buckets.append({
            "tier": name,
            "lo_sec": b["lo_sec"],
            "hi_sec": b["hi_sec"] if b["hi_sec"] < 10 ** 8 else None,
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "champion": champion,
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }



def day_of_week_analysis(
    mode: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by local weekday (0=Mon .. 6=Sun).

    Same shape as :func:`time_of_day_analysis` but axis is weekday
    instead of hour. ``best``/``worst`` are picked only from buckets
    meeting ``min_games``.
    """
    from datetime import datetime
    modes = (mode,) if mode else SUPPORTED_MODES

    buckets: dict[int, dict] = {
        d: {"games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
        for d in range(7)
    }
    total_games = 0

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                where = ""
                params: tuple = ()
                if since_iso:
                    where = "WHERE started_at >= ?"
                    params = (since_iso,)
                cur = conn.execute(
                    f"SELECT started_at, win{extra} FROM matches {where}",
                    params,
                )
                for r in cur:
                    ts = r["started_at"]
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    wd = dt.astimezone().weekday()   # 0=Mon
                    b = buckets[wd]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("day_of_week err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for d in range(7):
        b = buckets[d]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            kk = b["k_sum"] / b["kda_sample"]
            dd = b["d_sum"] / b["kda_sample"]
            aa = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((kk + aa) / max(dd, 1.0), 2)
        out_buckets.append({
            "weekday": d,
            "name": _WEEKDAY_NAMES[d],
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }


def coaching_digest(
    mode: str | None = None,
    since_iso: str | None = None,
    top_n: int = 5,
) -> dict:
    """Assemble a ranked list of actionable insights across all
    analysis dimensions — kda streaks, time-of-day, day-of-week,
    and game duration. Produces one-endpoint "what should I focus
    on?" output for dashboards, Discord pastes, and the CLI.

    Each insight: ``{type, severity (0-1), message, mode, champion?,
    data}``. Insights are sorted by severity desc and clipped to
    ``top_n``.

    ``mode=None`` assembles from every supported mode (per-mode
    insights tagged with the originating mode).
    """
    insights: list[dict] = []
    modes = (mode,) if mode else SUPPORTED_MODES

    # --- KDA streak insights (cold more severe than hot) --------
    for m in modes:
        t = kda_trends(m, n=3, min_sample=5)
        for e in t.get("cold", []):
            severity = min(1.0, abs(e["delta"]) / 2.0)
            insights.append({
                "type": "cold_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"→ {e['recent_ratio']:.2f} ({e['delta']:+.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })
        for e in t.get("hot", []):
            severity = min(0.7, e["delta"] / 2.0)
            insights.append({
                "type": "hot_streak",
                "severity": round(severity, 3),
                "mode": m,
                "champion": e["champion"],
                "message": (
                    f"{e['champion']} ({m}) KDA {e['baseline_ratio']:.2f} "
                    f"→ {e['recent_ratio']:.2f} (+{e['delta']:.2f}) over "
                    f"last {e['sample']} games"
                ),
                "data": e,
            })

    # --- Time-of-day outliers -----------------------------------
    tod = time_of_day_analysis(mode=mode, since_iso=since_iso, min_games=5)
    insightful_buckets = [b for b in tod["buckets"]
                          if b["insight"] and b["win_rate"] is not None]
    if insightful_buckets:
        avg_wr = sum(b["win_rate"] for b in insightful_buckets) / len(insightful_buckets)
        worst = tod["worst"]
        best = tod["best"]
        if worst and worst["win_rate"] is not None and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_hour",
                "severity": round(min(0.8, gap * 4), 3),
                "mode": mode or "all",
                "message": (
                    f"Slump at {worst['hour']:02d}h: "
                    f"{worst['win_rate']*100:.0f}% wr (n={worst['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and best["win_rate"] is not None and (best["win_rate"] - avg_wr) >= 0.08:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_hour",
                "severity": round(min(0.6, gap * 3), 3),
                "mode": mode or "all",
                "message": (
                    f"Peak at {best['hour']:02d}h: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']}, "
                    f"avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Day-of-week outliers -----------------------------------
    dow = day_of_week_analysis(mode=mode, since_iso=since_iso, min_games=5)
    dow_insightful = [b for b in dow["buckets"]
                      if b["insight"] and b["win_rate"] is not None]
    if dow_insightful:
        avg_wr = sum(b["win_rate"] for b in dow_insightful) / len(dow_insightful)
        worst = dow["worst"]
        best = dow["best"]
        if worst and worst["win_rate"] is not None and (avg_wr - worst["win_rate"]) >= 0.05:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "worst_day",
                "severity": round(min(0.7, gap * 4), 3),
                "mode": mode or "all",
                "message": (
                    f"Weak {worst['name']}: {worst['win_rate']*100:.0f}% wr "
                    f"(n={worst['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": worst,
            })
        if best and best["win_rate"] is not None and (best["win_rate"] - avg_wr) >= 0.05:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "best_day",
                "severity": round(min(0.5, gap * 3), 3),
                "mode": mode or "all",
                "message": (
                    f"Strong {best['name']}: {best['win_rate']*100:.0f}% wr "
                    f"(n={best['games']}, avg {avg_wr*100:.0f}%)"
                ),
                "data": best,
            })

    # --- Duration outliers --------------------------------------
    dur = duration_analysis(mode=mode, since_iso=since_iso, min_games=5)
    dur_insightful = [b for b in dur["buckets"]
                      if b["insight"] and b["win_rate"] is not None]
    if len(dur_insightful) >= 2:
        avg_wr = sum(b["win_rate"] for b in dur_insightful) / len(dur_insightful)
        worst = dur["worst"]
        best = dur["best"]
        if worst and (avg_wr - worst["win_rate"]) >= 0.08:
            gap = avg_wr - worst["win_rate"]
            insights.append({
                "type": "bad_duration",
                "severity": round(min(0.7, gap * 3), 3),
                "mode": mode or "all",
                "message": (
                    f"Struggle in {worst['tier']} games: "
                    f"{worst['win_rate']*100:.0f}% wr (n={worst['games']})"
                ),
                "data": worst,
            })
        if best and (best["win_rate"] - avg_wr) >= 0.08:
            gap = best["win_rate"] - avg_wr
            insights.append({
                "type": "good_duration",
                "severity": round(min(0.5, gap * 2.5), 3),
                "mode": mode or "all",
                "message": (
                    f"Strong in {best['tier']} games: "
                    f"{best['win_rate']*100:.0f}% wr (n={best['games']})"
                ),
                "data": best,
            })

    insights.sort(key=lambda x: -x["severity"])
    return {
        "mode": mode or "all",
        "since": since_iso,
        "count": len(insights),
        "insights": insights[:top_n],
    }


def _parse_since(spec: str) -> str:
    """Map --since CLI values to ISO strings.

    Accepts: ``today`` (default), ``24h`` / ``48h`` / etc., ``Nh`` where
    N is a positive int, or a full ISO-8601 string (passed through).
    """
    from datetime import datetime, timedelta, timezone
    s = (spec or "today").strip().lower()
    if s in ("today", ""):
        return _start_of_today_iso()
    if s.endswith("h"):
        try:
            hours = int(s[:-1])
            return (datetime.now().astimezone() - timedelta(hours=hours)).isoformat()
        except ValueError:
            pass
    if s.endswith("d"):
        try:
            days = int(s[:-1])
            return (datetime.now().astimezone() - timedelta(days=days)).isoformat()
        except ValueError:
            pass
    # Fall through: assume ISO-8601 string the caller supplied.
    return spec


def _format_session_text(data: dict) -> str:
    lines = [f"=== Session summary since {data['since']} ==="]
    if not data["games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    wr = data["win_rate"]
    wr_str = f"{wr*100:.0f}%" if wr is not None else "—"
    lines.append(
        f"{data['games']} games · {data['wins']}W-{data['losses']}L · wr {wr_str}"
    )
    if data["avg_kda"]:
        k = data["avg_kda"]
        lines.append(
            f"avg KDA {k['ratio']} ({k['k']}/{k['d']}/{k['a']}, n={k['sample']})"
        )
    lines.append("— by mode —")
    for mode, slot in data["per_mode"].items():
        if not slot["games"]:
            continue
        kr = slot.get("kda_ratio")
        kseg = f" KDA {kr}" if kr is not None else ""
        lines.append(
            f"  {mode:<10} {slot['games']}g · {slot['wins']}W-{slot['losses']}L{kseg}"
        )
    if data["champions"]:
        lines.append("— champions —")
        for c in data["champions"]:
            wr = c.get("win_rate")
            wr_str = f"{wr*100:.0f}%" if wr is not None else "—"
            kr = c.get("kda_ratio")
            kseg = f" KDA {kr}" if kr is not None else ""
            lines.append(
                f"  {c['champion']:<18} {c['games']}g · "
                f"{c['wins']}W-{c['losses']}L · wr {wr_str}{kseg}"
            )
    return "\n".join(lines)


_SEVERITY_BAND = (
    (0.8, "!!"),
    (0.5, "!"),
    (0.0, " "),
)


def _severity_tag(sev: float) -> str:
    for floor, tag in _SEVERITY_BAND:
        if sev >= floor:
            return tag
    return " "


def _format_digest_text(data: dict) -> str:
    lines = [
        f"=== Coaching digest ({data['mode']}, {data['count']} insights) ==="
    ]
    if not data["insights"]:
        lines.append("(no actionable insights yet — play more games)")
        return "\n".join(lines)
    for ins in data["insights"]:
        tag = _severity_tag(ins["severity"])
        lines.append(
            f"  {tag} [{ins['type']:<14}] sev {ins['severity']:.2f}  {ins['message']}"
        )
    return "\n".join(lines)


def _format_duration_text(data: dict) -> str:
    scope = data.get("mode", "all")
    if data.get("champion"):
        scope = f"{data['champion']} in {scope}"
    lines = [
        f"=== Duration breakdown ({scope}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  tier       games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  — "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  —"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['tier']:<8}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['tier']} wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['tier']} wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_day_of_week_text(data: dict) -> str:
    lines = [
        f"=== Day-of-week breakdown ({data['mode']}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  day   games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  — "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  —"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['name']}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['name']} wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['name']} wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_time_of_day_text(data: dict) -> str:
    lines = [
        f"=== Time-of-day breakdown ({data['mode']}, n={data['total_games']}) ==="
    ]
    if not data["total_games"]:
        lines.append("(no games)")
        return "\n".join(lines)
    lines.append("  hr   games   W- L    wr    KDA")
    for b in data["buckets"]:
        if not b["games"]:
            continue
        wr = b["win_rate"]
        wr_str = f"{wr*100:>3.0f}%" if wr is not None else "  — "
        kda = b["kda_ratio"]
        kda_str = f"{kda:>4.2f}" if kda is not None else "  —"
        flag = "*" if b["insight"] else " "
        lines.append(
            f"  {b['hour']:02d}{flag}  {b['games']:>4}   "
            f"{b['wins']:>2}-{b['losses']:<2}  {wr_str}   {kda_str}"
        )
    if data["best"]:
        bb = data["best"]
        lines.append(
            f"best: {bb['hour']:02d}h "
            f"wr {bb['win_rate']*100:.0f}% (n={bb['games']})"
        )
    if data["worst"]:
        ww = data["worst"]
        lines.append(
            f"worst: {ww['hour']:02d}h "
            f"wr {ww['win_rate']*100:.0f}% (n={ww['games']})"
        )
    return "\n".join(lines)


def _format_games_text(rows: list[dict], since_spec: str = "today") -> str:
    lines = [f"=== Games since {since_spec} ({len(rows)} rows) ==="]
    if not rows:
        lines.append("(no games)")
        return "\n".join(lines)
    for r in rows:
        # Pull just the time portion for compactness when it's today.
        ts = (r["started_at"] or "")[:16].replace("T", " ")
        win = r.get("win")
        outcome = "W" if win == 1 else ("L" if win == 0 else "·")
        kda = r.get("kda")
        kda_str = (
            f"{kda['k']:>2}/{kda['d']:>2}/{kda['a']:>2}"
            if kda else "   -   "
        )
        ratio = r.get("kda_ratio")
        ratio_str = f"KDA {ratio:>4.2f}" if ratio is not None else "KDA  —  "
        dur = r.get("duration_sec") or 0
        dur_str = f"{dur // 60:>2}:{dur % 60:02d}" if dur else "  :  "
        lines.append(
            f"  {ts}  {r['mode']:<9}  {r['champion']:<16}  {outcome}  "
            f"{kda_str}  {ratio_str}  {dur_str}"
        )
    return "\n".join(lines)


def _format_trends_text(data: dict) -> str:
    """Human-readable version of kda_trends() output — for --trends."""
    lines = [f"=== {data.get('mode', '?').upper()} KDA streaks (last 10) ==="]
    hot = data.get("hot") or []
    cold = data.get("cold") or []
    if not hot and not cold:
        lines.append("(no recent-window sample yet)")
        return "\n".join(lines)
    if hot:
        lines.append("↑ HOT:")
        for e in hot:
            lines.append(
                f"  {e['champion']:<18} baseline {e['baseline_ratio']:.2f}"
                f" → recent {e['recent_ratio']:.2f}  (+{e['delta']:.2f})"
            )
    if cold:
        lines.append("↓ COLD:")
        for e in cold:
            lines.append(
                f"  {e['champion']:<18} baseline {e['baseline_ratio']:.2f}"
                f" → recent {e['recent_ratio']:.2f}  ({e['delta']:+.2f})"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — see ``python -m coaches.adaptation_hint --help``."""
    import argparse
    p = argparse.ArgumentParser(
        description="Query Agent 4's adaptation aggregates from the terminal."
    )
    p.add_argument("--champion", "-c", help="Champion name (required unless --trends)")
    p.add_argument("--mode", "-m", default="aram",
                   choices=list(SUPPORTED_MODES),
                   help="Mode DB to query (default: aram)")
    p.add_argument("--enemies", "-e", default="",
                   help="Comma-separated enemy champions for matchup hints")
    p.add_argument("--format", "-f", default="hint",
                   choices=("hint", "card", "json"),
                   help="Output format (default: hint)")
    p.add_argument("--trends", action="store_true",
                   help="Dump hot/cold KDA streaks for --mode and exit")
    p.add_argument("--session", action="store_true",
                   help="Dump session summary (today's games across all modes) and exit")
    p.add_argument("--games", action="store_true",
                   help="Dump chronological game-by-game timeline and exit")
    p.add_argument("--hourly", action="store_true",
                   help="Time-of-day breakdown across --mode (or all modes) and exit")
    p.add_argument("--weekday", action="store_true",
                   help="Day-of-week breakdown across --mode (or all modes) and exit")
    p.add_argument("--duration", action="store_true",
                   help="Game-duration breakdown (stomp/quick/standard/long) and exit")
    p.add_argument("--digest", action="store_true",
                   help="Top actionable insights across all dimensions and exit")
    p.add_argument("--min-games", type=int, default=3,
                   help="Minimum games per hour bucket to qualify for best/worst (default: 3)")
    p.add_argument("--since", default="today",
                   help="Session/games since spec: today|24h|7d|<ISO> (default: today)")
    p.add_argument("--limit", type=int, default=0,
                   help="Tail-clamp for --games (default: unlimited)")
    p.add_argument("--top-n", type=int, default=3,
                   help="Top N for --trends (default: 3)")
    args = p.parse_args(argv)

    if args.trends:
        data = kda_trends(args.mode, n=args.top_n)
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_trends_text(data))
        return 0

    if args.session:
        data = session_summary(_parse_since(args.since))
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_session_text(data))
        return 0

    if args.games:
        limit = args.limit if args.limit > 0 else None
        rows = session_games(_parse_since(args.since), limit=limit)
        if args.format == "json":
            print(json.dumps(rows, indent=2))
        else:
            print(_format_games_text(rows, since_spec=args.since))
        return 0

    if args.hourly:
        # `--mode` defaults to "aram" from argparse but we treat that as
        # "all modes" here unless the user passed it explicitly; default
        # intent for a time-of-day view is cross-mode. Detect by checking
        # whether the user-supplied argv contained --mode/-m.
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = time_of_day_analysis(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_time_of_day_text(data))
        return 0

    if args.weekday:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = day_of_week_analysis(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_day_of_week_text(data))
        return 0

    if args.duration:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = duration_analysis(
            mode=(args.mode if mode_explicit else None),
            champion=args.champion or None,
            since_iso=since,
            min_games=args.min_games,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_duration_text(data))
        return 0

    if args.digest:
        import sys as _sys
        _argv = argv if argv is not None else _sys.argv[1:]
        mode_explicit = any(a in ("--mode", "-m") or a.startswith(("--mode=",))
                            for a in _argv)
        since = _parse_since(args.since) if args.since != "today" else None
        data = coaching_digest(
            mode=(args.mode if mode_explicit else None),
            since_iso=since,
            top_n=args.top_n,
        )
        if args.format == "json":
            print(json.dumps(data, indent=2))
        else:
            print(_format_digest_text(data))
        return 0

    if not args.champion:
        p.error("--champion is required unless --trends, --session, --games, --hourly, --weekday, --duration, or --digest is given")

    enemies = [e.strip() for e in args.enemies.split(",") if e.strip()] or None

    if args.format == "hint":
        line = format_hint_line(args.champion, args.mode, enemies=enemies)
        print(line or f"(no data for {args.champion} in {args.mode})")
    elif args.format == "card":
        card = insight_card(args.champion, args.mode, enemies=enemies)
        print(card or f"(no data for {args.champion} in {args.mode})")
    else:
        data = for_champion(args.champion, args.mode)
        data["hint"] = format_hint_line(args.champion, args.mode, enemies=enemies)
        print(json.dumps(data, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
