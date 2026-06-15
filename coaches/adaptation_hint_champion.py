"""Champion / matchup adaptation-hint surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the coach hot-path API
(`for_champion`, `matchup_delta`, `format_hint_line`, `insight_card`).
`coaches.adaptation_hint` re-exports these names so existing call sites
keep working unchanged; function bodies are extracted byte-verbatim -
behavior is pinned by the test_adaptation_hint + test_round* suites.
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Iterable

from coaches._adaptation_common import (
    _DEFAULT_TOP_COUNTERS,
    _MIN_ABSOLUTE_DELTA,
    _MIN_SAMPLE,
    _db,
    logger,
)


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
                # NaN passes the abs() gate below (NaN < x is False) and
                # would surface as "nan%" in coach hint text - exclude
                # any non-finite modifier outright.
                if not math.isfinite(delta) or abs(delta) < _MIN_ABSOLUTE_DELTA:
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
    (champion x opponent x mode) matchup, or None if not activated /
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
    delta = float(mj.get("delta") or 0.0)
    # Treat a non-finite stored delta as no-data rather than returning
    # NaN/inf into coach math.
    return delta if math.isfinite(delta) else None


def format_hint_line(
    champion: str,
    mode: str,
    enemies: Iterable[str] | None = None,
    top_n: int = _DEFAULT_TOP_COUNTERS,
) -> str:
    """One-liner suitable for inlining into a coach prompt.

    Returns ``""`` (empty string) when there's nothing useful to say -
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
        direction = "^" if recent > wr + 0.05 else ("v" if recent < wr - 0.05 else "-")
        parts.append(f"recent {recent*100:.0f}% {direction}")

    # 30-day meta-trend bucket (separate from last-N rolling).
    r30 = data.get("recency_30d")
    if r30 and r30.get("games", 0) >= 5:
        dv = r30.get("delta_vs_alltime", 0.0) or 0.0
        direction = "^" if dv > 0.05 else ("v" if dv < -0.05 else "-")
        parts.append(
            f"30d {r30.get('win_rate', 0)*100:.0f}% {direction} "
            f"(n={r30.get('games')})"
        )

    # Typical KDA - survivability signal, independent of win/loss so it
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
            direction = "^" if delta > 0.3 else ("v" if delta < -0.3 else "-")
            sign = "+" if delta >= 0 else ""
            seg += (
                f" | recent {rkda['ratio']} {direction} "
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
        # Matchup KDA delta - only surface if meaningful (|delta| >= 0.3).
        if "kda_delta" in c and abs(c["kda_delta"]) >= 0.3:
            ksign = "+" if c["kda_delta"] >= 0 else ""
            seg += f" KDA {c['kda_ratio']} ({ksign}{c['kda_delta']})"
        flagged.append(seg)
        if len(flagged) >= top_n:
            break

    if flagged:
        parts.append("active matchups: " + ", ".join(flagged))

    # First-legendary signal (most actionable - tells the coach "rush X")
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

    # Generic item-outcome signals (any pickup) - lower priority, smaller list
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
    """Compact copy-to-clipboard summary - one line, bounded.

    Returns "" when no champion data. Format:
      "Tristana ARAM 72% wr (n=61) ^ | rush Statikk Shiv (+19%) |
       vs Morgana -52% (n=5)"

    Always ends after cutting at a ``|`` boundary so the card never
    ends mid-phrase. ``max_chars`` defaults to 240 - long enough for
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
        arrow = "^" if dv > 0.05 else ("v" if dv < -0.05 else "-")
        head += f" {arrow}30d {r30.get('win_rate',0)*100:.0f}%"
    segs.append(head)

    # KDA segment - only if we have enough sample to be meaningful.
    kda = data.get("avg_kda")
    if kda and kda.get("sample", 0) >= 5:
        kseg = f"KDA {kda['ratio']}"
        rkda = data.get("recent_kda")
        if rkda and rkda.get("sample", 0) >= 5:
            dr = rkda.get("delta_ratio", 0.0) or 0.0
            if abs(dr) >= 0.3:
                arrow = "^" if dr > 0 else "v"
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

    # Top items - one mention if space
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

    out = " | ".join(segs)
    if len(out) <= max_chars:
        return out
    # Trim at a separator boundary to keep the card grammatical.
    trimmed = out[:max_chars]
    if " | " in trimmed:
        trimmed = trimmed.rsplit(" | ", 1)[0]
    return trimmed
