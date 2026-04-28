"""Agent 4 — Coach Mentor: analyzer.

Replays matches in a mode DB, rolls per-champion aggregates into
``adaptation_buckets``, and bumps ``matchup_modifiers`` sample counts.
Runs autonomously on the supervisor's idle pass per charter.

Per charter scope:

  * **Autonomous writes allowed** — ``adaptation_buckets`` rows,
    ``matchup_modifiers`` rows (both already in the §9 schema); files
    under ``data/meta_build/curated/``.
  * **Propose-and-queue only** — coach prompts, coach Python, decision
    heuristics, panel templates.

This module does not touch any propose-only surface. It reads ``matches``
(required) and ``match_events`` (optional) and writes only to
``adaptation_buckets`` / ``matchup_modifiers`` via atomic UPSERT.

Axis: per-champion × per-mode. Matchup modifiers activate at
``MATCHUP_ACTIVATE_THRESHOLD`` samples (spec §8). Below threshold the
modifier row exists but ``activated=0``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

logger = logging.getLogger("agent4.analyzer")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_DIR = _PROJECT_ROOT / "data" / "db"

from lib.modes import PHASE3_MODES as SUPPORTED_MODES

# Spec §8: matchup modifier activates only at ≥5 games sample size.
MATCHUP_ACTIVATE_THRESHOLD = 5

# How many recent matches to track for the "recent" rolling stats.
RECENT_N = 10

# Wall-clock recency window for meta-trend bucketing. 30 days catches
# at least one LoL patch cycle (~2 weeks) plus stabilisation, without
# being so long the meta has shifted mid-window.
RECENCY_WINDOW_DAYS = 30

# Item-outcome aggregation knobs. Matches the matchup threshold so
# items and opponents have consistent statistical confidence.
ITEM_MIN_SAMPLE = 5            # minimum distinct matches to surface an item
ITEM_TOP_N = 5                 # top items per champion in aggregates_json
ITEM_MIN_GOLD = 2200           # legendary/mythic filter; excludes consumables
ITEM_MIN_DELTA = 0.10          # ignore items whose win-rate matches baseline


def _load_item_metadata() -> dict[int, dict]:
    """Pull item names + gold cost from the newest cached DDragon bundle.

    Returns {item_id: {"name", "gold_total", "maps"}}. Empty dict if no
    cache — callers fall back to bare numeric item ids in that case.
    """
    ddragon_dir = _PROJECT_ROOT / "data" / "meta_build" / "ddragon"
    if not ddragon_dir.exists():
        return {}
    # Pick the newest versioned subdir that has item.json.
    candidates = sorted(
        (p for p in ddragon_dir.iterdir() if p.is_dir()),
        key=lambda p: p.name, reverse=True,
    )
    for vdir in candidates:
        item_json = vdir / "item.json"
        if not item_json.exists():
            continue
        try:
            data = json.loads(item_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        out: dict[int, dict] = {}
        for k, v in (data.get("data") or {}).items():
            try:
                iid = int(k)
            except (TypeError, ValueError):
                continue
            gold = ((v.get("gold") or {}).get("total")) or 0
            out[iid] = {
                "name": v.get("name") or str(iid),
                "gold_total": int(gold or 0),
                "maps": v.get("maps") or {},
            }
        return out
    return {}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _ChampionStats:
    champion: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    duration_sum: int = 0
    duration_count: int = 0
    recent_results: list[int] = None   # type: ignore[assignment]
    # 30-day window (meta-trend) — sparse, only populated for matches
    # inside RECENCY_WINDOW_DAYS of analysis time.
    recency_30d_games: int = 0
    recency_30d_wins: int = 0
    # KDA aggregation — decoupled from win/loss observation so that
    # recent live matches (win still NULL pending reconcile) still
    # contribute to avg_kda. Only counts rows with non-null k/d/a.
    kda_games: int = 0
    kills_sum: int = 0
    deaths_sum: int = 0
    assists_sum: int = 0
    # Rolling last-N KDA (newest RECENT_N matches with non-null k/d/a).
    recent_kda_samples: list[tuple[int, int, int]] = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.recent_results is None:
            self.recent_results = []
        if self.recent_kda_samples is None:
            self.recent_kda_samples = []

    def observe(
        self,
        win: int | None,
        duration_sec: int | None,
        within_30d: bool = False,
    ) -> None:
        if win is None:
            return      # rows without a recorded outcome aren't useful
        self.games += 1
        if win == 1:
            self.wins += 1
        else:
            self.losses += 1
        if duration_sec is not None and duration_sec > 0:
            self.duration_sum += int(duration_sec)
            self.duration_count += 1
        self.recent_results.append(int(win))
        if len(self.recent_results) > RECENT_N:
            self.recent_results = self.recent_results[-RECENT_N:]
        if within_30d:
            self.recency_30d_games += 1
            if win == 1:
                self.recency_30d_wins += 1

    def observe_kda(
        self,
        kills: int | None,
        deaths: int | None,
        assists: int | None,
    ) -> None:
        if kills is None or deaths is None or assists is None:
            return
        k, d, a = int(kills), int(deaths), int(assists)
        self.kda_games += 1
        self.kills_sum += k
        self.deaths_sum += d
        self.assists_sum += a
        self.recent_kda_samples.append((k, d, a))
        if len(self.recent_kda_samples) > RECENT_N:
            self.recent_kda_samples = self.recent_kda_samples[-RECENT_N:]

    @property
    def win_rate(self) -> float:
        return (self.wins / self.games) if self.games else 0.0

    @property
    def avg_duration_sec(self) -> float | None:
        if not self.duration_count:
            return None
        return self.duration_sum / self.duration_count

    @property
    def recent_win_rate(self) -> float | None:
        if not self.recent_results:
            return None
        return sum(self.recent_results) / len(self.recent_results)

    @property
    def recency_30d_wr(self) -> float | None:
        if not self.recency_30d_games:
            return None
        return self.recency_30d_wins / self.recency_30d_games

    def to_aggregates_json(self) -> dict:
        out = {
            "win_rate": round(self.win_rate, 4),
            "recent_win_rate": (
                round(self.recent_win_rate, 4) if self.recent_win_rate is not None else None
            ),
            "recent_sample_size": len(self.recent_results),
            "avg_duration_sec": (
                round(self.avg_duration_sec, 1) if self.avg_duration_sec is not None else None
            ),
        }
        if self.recency_30d_games:
            wr = self.recency_30d_wr or 0.0
            out["recency_30d"] = {
                "games": self.recency_30d_games,
                "wins": self.recency_30d_wins,
                "win_rate": round(wr, 4),
                "delta_vs_alltime": round(wr - self.win_rate, 4),
                "window_days": RECENCY_WINDOW_DAYS,
            }
        if self.kda_games:
            k = self.kills_sum / self.kda_games
            d = self.deaths_sum / self.kda_games
            a = self.assists_sum / self.kda_games
            # Canonical KDA ratio: (K+A)/max(D,1). Use D=1 floor so
            # perfect-run champions (0 deaths) still get a finite number
            # the coach can print.
            ratio = (k + a) / max(d, 1.0)
            out["avg_kda"] = {
                "k": round(k, 2),
                "d": round(d, 2),
                "a": round(a, 2),
                "ratio": round(ratio, 2),
                "sample": self.kda_games,
            }
            # Rolling last-N (≥5 floor so a single bad game doesn't
            # overwhelm the signal).
            if len(self.recent_kda_samples) >= 5:
                rk = sum(s[0] for s in self.recent_kda_samples) / len(self.recent_kda_samples)
                rd = sum(s[1] for s in self.recent_kda_samples) / len(self.recent_kda_samples)
                ra = sum(s[2] for s in self.recent_kda_samples) / len(self.recent_kda_samples)
                r_ratio = (rk + ra) / max(rd, 1.0)
                out["recent_kda"] = {
                    "k": round(rk, 2),
                    "d": round(rd, 2),
                    "a": round(ra, 2),
                    "ratio": round(r_ratio, 2),
                    "sample": len(self.recent_kda_samples),
                    "delta_ratio": round(r_ratio - ratio, 2),
                }
        return out


@dataclass
class _Matchup:
    champion: str
    opponent: str
    sample_count: int = 0
    wins: int = 0
    # KDA sums tracked only on rows where both win AND k/d/a are present.
    # Sample can lag behind sample_count (e.g. old rows lack KDA until the
    # backfill has run). Ratio is surfaced only when kda_sample ≥ 3.
    kda_sample: int = 0
    kills_sum: int = 0
    deaths_sum: int = 0
    assists_sum: int = 0

    def observe(self, win: int) -> None:
        self.sample_count += 1
        if win == 1:
            self.wins += 1

    def observe_kda(self, k: int | None, d: int | None, a: int | None) -> None:
        if k is None or d is None or a is None:
            return
        self.kda_sample += 1
        self.kills_sum += int(k)
        self.deaths_sum += int(d)
        self.assists_sum += int(a)

    @property
    def activated(self) -> int:
        return 1 if self.sample_count >= MATCHUP_ACTIVATE_THRESHOLD else 0

    @property
    def observed_win_rate(self) -> float:
        return (self.wins / self.sample_count) if self.sample_count else 0.0

    @property
    def observed_kda_ratio(self) -> float | None:
        if self.kda_sample < 3:
            return None
        k = self.kills_sum / self.kda_sample
        d = self.deaths_sum / self.kda_sample
        a = self.assists_sum / self.kda_sample
        return (k + a) / max(d, 1.0)

    def modifier_json(self, baseline_wr: float, baseline_kda_ratio: float | None) -> dict:
        # Delta vs the champion's baseline win rate. Negative means this
        # matchup is harder than average for the champion.
        out: dict = {
            "sample": self.sample_count,
            "observed_wr": round(self.observed_win_rate, 4),
            "baseline_wr": round(baseline_wr, 4),
            "delta": round(self.observed_win_rate - baseline_wr, 4),
        }
        kda_ratio = self.observed_kda_ratio
        if kda_ratio is not None:
            out["kda_sample"] = self.kda_sample
            out["kda_ratio"] = round(kda_ratio, 2)
            if baseline_kda_ratio is not None:
                out["kda_delta"] = round(kda_ratio - baseline_kda_ratio, 2)
        return out


class Analyzer:
    def __init__(self, mode: str) -> None:
        if mode not in SUPPORTED_MODES:
            raise ValueError(f"unsupported mode: {mode}")
        self._mode = mode
        self._db_path = DB_DIR / f"{mode}.db"

    # ---- main entry point -----------------------------------------
    def analyze(self) -> dict:
        if not self._db_path.exists():
            raise FileNotFoundError(f"mode DB missing: {self._db_path}")

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            return self._run(conn)
        finally:
            conn.close()

    def _run(self, conn: sqlite3.Connection) -> dict:
        t0 = time.time()

        champ_stats: dict[str, _ChampionStats] = {}
        matchups: dict[tuple[str, str], _Matchup] = {}
        item_meta = _load_item_metadata()

        # Cutoff ISO string for the 30-day recency window. Pure string
        # comparison works because started_at is ISO-8601 UTC.
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=RECENCY_WINDOW_DAYS)).isoformat()

        # KDA columns may not exist on very old DBs that haven't been
        # touched by db_migrate_kda yet. Probe once and pick the SELECT.
        existing_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(matches)")
        }
        has_kda = {"kills", "deaths", "assists"} <= existing_cols
        kda_cols = ", kills, deaths, assists" if has_kda else ""
        cur = conn.execute(
            f"""
            SELECT champion, ally_champions, enemy_champions,
                   duration_sec, win, started_at{kda_cols}
            FROM matches
            ORDER BY started_at
            """,
        )
        rows_scanned = 0
        for row in cur:
            rows_scanned += 1
            champ = row["champion"] or "Unknown"
            stats = champ_stats.setdefault(champ, _ChampionStats(champion=champ))
            started = row["started_at"] or ""
            within_30d = started >= cutoff
            stats.observe(row["win"], row["duration_sec"], within_30d=within_30d)
            if has_kda:
                stats.observe_kda(row["kills"], row["deaths"], row["assists"])

            # Matchup modifiers — only meaningful when we have a win signal.
            if row["win"] is None:
                continue
            try:
                enemies = json.loads(row["enemy_champions"] or "[]")
            except (json.JSONDecodeError, TypeError):
                enemies = []
            # Row-level KDA for matchup aggregation (None if missing).
            row_k = row["kills"] if has_kda else None
            row_d = row["deaths"] if has_kda else None
            row_a = row["assists"] if has_kda else None
            for e in enemies:
                if not isinstance(e, str) or not e or e == champ:
                    continue
                key = (champ, e)
                m = matchups.setdefault(key, _Matchup(champion=champ, opponent=e))
                m.observe(int(row["win"]))
                m.observe_kda(row_k, row_d, row_a)

        # ---- item-outcome aggregation (per champion × item_id) -----
        #
        # Pull DISTINCT (match_id, item_id) pairs so we count matches, not
        # individual buys (a player might buy the same component 3x in
        # one game — we want "games where this item was purchased").
        # Then group by (champion, item_id), count wins, compute delta
        # vs the champion's baseline. Filter to legendary/mythic items
        # by gold cost when DDragon metadata is available.
        item_stats: dict[tuple[str, int], dict[str, int]] = {}
        item_sql = """
            SELECT m.champion, m.win,
                   json_extract(e.state_json, '$.item_id') AS item_id,
                   e.match_id
            FROM match_events e
            JOIN matches m ON m.match_id = e.match_id
            WHERE e.event_type = 'ITEM_PURCHASED'
              AND m.win IS NOT NULL
              AND json_extract(e.state_json, '$.item_id') IS NOT NULL
            GROUP BY m.champion, item_id, e.match_id
        """
        for r in conn.execute(item_sql):
            try:
                iid = int(r["item_id"])
            except (TypeError, ValueError):
                continue
            if item_meta:
                meta = item_meta.get(iid)
                if meta is None or meta["gold_total"] < ITEM_MIN_GOLD:
                    continue
            elif iid < 3000:
                # No DDragon metadata — exclude consumables/wards by id range.
                continue
            champ = r["champion"] or "Unknown"
            bucket = item_stats.setdefault((champ, iid), {"matches": 0, "wins": 0})
            bucket["matches"] += 1
            if int(r["win"]) == 1:
                bucket["wins"] += 1

        # Attach per-champion top items to the aggregates_json dicts.
        items_per_champ: dict[str, list[dict]] = {}
        for (champ, iid), b in item_stats.items():
            if b["matches"] < ITEM_MIN_SAMPLE:
                continue
            observed = b["wins"] / b["matches"]
            baseline = champ_stats[champ].win_rate if champ in champ_stats else 0.0
            delta = observed - baseline
            if abs(delta) < ITEM_MIN_DELTA:
                continue
            name = (item_meta.get(iid) or {}).get("name") or str(iid)
            items_per_champ.setdefault(champ, []).append({
                "item_id": iid,
                "name": name,
                "matches": b["matches"],
                "wins": b["wins"],
                "observed_wr": round(observed, 4),
                "baseline_wr": round(baseline, 4),
                "delta": round(delta, 4),
            })
        for champ, lst in items_per_champ.items():
            lst.sort(key=lambda d: abs(d["delta"]), reverse=True)
            items_per_champ[champ] = lst[:ITEM_TOP_N]

        # ---- first-legendary-per-match aggregation ----------------
        #
        # For each match: earliest ITEM_PURCHASED whose item_id is a
        # legendary (gold_total >= ITEM_MIN_GOLD) → "first core item".
        # Grouped by (champion, first_legendary_id) with win rate + avg
        # timing. Surfaces as aggregates_json.first_legendary.
        first_leg_rows = conn.execute(
            """
            SELECT m.match_id, m.champion, m.win,
                   json_extract(e.state_json, '$.item_id') AS item_id,
                   e.ts_game_sec
            FROM match_events e
            JOIN matches m ON m.match_id = e.match_id
            WHERE e.event_type = 'ITEM_PURCHASED'
              AND m.win IS NOT NULL
              AND json_extract(e.state_json, '$.item_id') IS NOT NULL
            ORDER BY m.match_id, e.ts_game_sec
            """,
        )
        first_leg_seen: set[int] = set()          # match_ids with first-leg recorded
        first_leg_stats: dict[tuple[str, int], dict[str, float]] = {}
        for r in first_leg_rows:
            mid = int(r["match_id"])
            if mid in first_leg_seen:
                continue
            try:
                iid = int(r["item_id"])
            except (TypeError, ValueError):
                continue
            # Legendary-only filter.
            if item_meta:
                meta = item_meta.get(iid)
                if meta is None or meta["gold_total"] < ITEM_MIN_GOLD:
                    continue
            elif iid < 3000:
                continue
            first_leg_seen.add(mid)
            champ = r["champion"] or "Unknown"
            key = (champ, iid)
            bucket = first_leg_stats.setdefault(key, {
                "matches": 0, "wins": 0, "ts_sum": 0.0,
            })
            bucket["matches"] += 1
            if int(r["win"]) == 1:
                bucket["wins"] += 1
            bucket["ts_sum"] += float(r["ts_game_sec"] or 0)

        first_leg_per_champ: dict[str, list[dict]] = {}
        for (champ, iid), b in first_leg_stats.items():
            if b["matches"] < ITEM_MIN_SAMPLE:
                continue
            observed = b["wins"] / b["matches"]
            baseline = champ_stats[champ].win_rate if champ in champ_stats else 0.0
            delta = observed - baseline
            # For first-leg we show ALL significant signals (positive and
            # negative) but still filter by minimum delta.
            if abs(delta) < ITEM_MIN_DELTA:
                continue
            avg_ts = round(b["ts_sum"] / b["matches"], 1)
            name = (item_meta.get(iid) or {}).get("name") or str(iid)
            first_leg_per_champ.setdefault(champ, []).append({
                "item_id": iid,
                "name": name,
                "matches": int(b["matches"]),
                "wins": int(b["wins"]),
                "observed_wr": round(observed, 4),
                "baseline_wr": round(baseline, 4),
                "delta": round(delta, 4),
                "avg_timing_sec": avg_ts,
            })
        for champ, lst in first_leg_per_champ.items():
            lst.sort(key=lambda d: abs(d["delta"]), reverse=True)
            first_leg_per_champ[champ] = lst[:3]

        # ---- atomic UPSERT into adaptation_buckets -----------------
        now_iso = _iso_now()

        def _agg_json_for(s: _ChampionStats) -> str:
            agg = s.to_aggregates_json()
            top = items_per_champ.get(s.champion)
            if top:
                agg["top_items"] = top
            flg = first_leg_per_champ.get(s.champion)
            if flg:
                agg["first_legendary"] = flg
            return json.dumps(agg, separators=(",", ":"))

        bucket_rows = [
            (
                s.champion,
                s.games,
                s.wins,
                s.losses,
                round(s.win_rate, 4),
                now_iso,
                _agg_json_for(s),
            )
            for s in champ_stats.values()
            if s.games > 0
        ]
        conn.executemany(
            """
            INSERT INTO adaptation_buckets
              (champion, games_played, wins, losses, avg_rating, last_updated, aggregates_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(champion) DO UPDATE SET
              games_played = excluded.games_played,
              wins = excluded.wins,
              losses = excluded.losses,
              avg_rating = excluded.avg_rating,
              last_updated = excluded.last_updated,
              aggregates_json = excluded.aggregates_json
            """,
            bucket_rows,
        )

        # ---- atomic UPSERT into matchup_modifiers ------------------
        # Cache each champion's baseline KDA ratio so we can compute
        # per-matchup delta without recomputing inside the inner loop.
        baseline_kda_lookup: dict[str, float | None] = {}
        for c, s in champ_stats.items():
            if s.kda_games:
                k = s.kills_sum / s.kda_games
                d = s.deaths_sum / s.kda_games
                a = s.assists_sum / s.kda_games
                baseline_kda_lookup[c] = (k + a) / max(d, 1.0)
            else:
                baseline_kda_lookup[c] = None

        matchup_rows = []
        for (champ, opp), m in matchups.items():
            baseline = champ_stats[champ].win_rate
            baseline_kda = baseline_kda_lookup.get(champ)
            matchup_rows.append(
                (
                    champ,
                    opp,
                    m.sample_count,
                    m.activated,
                    json.dumps(
                        m.modifier_json(baseline, baseline_kda),
                        separators=(",", ":"),
                    ),
                    now_iso,
                )
            )
        conn.executemany(
            """
            INSERT INTO matchup_modifiers
              (champion, opponent_signature, sample_count, activated, modifier_json, last_updated)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(champion, opponent_signature) DO UPDATE SET
              sample_count = excluded.sample_count,
              activated = excluded.activated,
              modifier_json = excluded.modifier_json,
              last_updated = excluded.last_updated
            """,
            matchup_rows,
        )
        conn.commit()

        elapsed = time.time() - t0
        activated = sum(1 for m in matchups.values() if m.activated)
        top_items_total = sum(len(v) for v in items_per_champ.values())
        first_leg_total = sum(len(v) for v in first_leg_per_champ.values())
        champions_with_kda = sum(1 for s in champ_stats.values() if s.kda_games)
        summary = {
            "mode": self._mode,
            "matches_scanned": rows_scanned,
            "champion_buckets": len(bucket_rows),
            "matchups_tracked": len(matchup_rows),
            "matchups_activated": activated,
            "champions_with_top_items": len(items_per_champ),
            "top_items_total": top_items_total,
            "champions_with_first_legendary": len(first_leg_per_champ),
            "first_legendary_total": first_leg_total,
            "champions_with_kda": champions_with_kda,
            "elapsed_sec": round(elapsed, 2),
        }
        logger.info("analyze %s: %s", self._mode, summary)
        return summary


# ── public helpers used by Agent 1 dispatch payloads ────────────────

def analyze_mode(mode: str) -> dict:
    return Analyzer(mode).analyze()


def analyze_all() -> dict[str, dict]:
    results: dict[str, dict] = {}
    for m in SUPPORTED_MODES:
        try:
            results[m] = analyze_mode(m)
        except FileNotFoundError:
            results[m] = {"skipped": True, "reason": "mode DB missing"}
        except Exception as e:                 # noqa: BLE001
            logger.exception("analyze %s failed: %s", m, e)
            results[m] = {"error": str(e)}
    return results


# ── CLI ─────────────────────────────────────────────────────────────

def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agent 4 analyzer")
    p.add_argument("--mode", choices=SUPPORTED_MODES,
                   help="Run for one mode (default: all)")
    p.add_argument("--top", type=int, default=10,
                   help="Show top-N champions by games after analysis")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.mode:
        result = {args.mode: analyze_mode(args.mode)}
    else:
        result = analyze_all()
    print(json.dumps(result, indent=2))

    # Surface top-N champions per mode.
    for mode in result:
        db_path = DB_DIR / f"{mode}.db"
        if not db_path.exists():
            continue
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            top = conn.execute(
                """
                SELECT champion, games_played, wins, avg_rating, aggregates_json
                FROM adaptation_buckets
                ORDER BY games_played DESC
                LIMIT ?
                """,
                (args.top,),
            ).fetchall()
        if not top:
            continue
        print(f"\n  === {mode} top-{args.top} by games_played ===")
        for r in top:
            aj = {}
            try:
                aj = json.loads(r["aggregates_json"] or "{}")
            except json.JSONDecodeError:
                pass
            recent = aj.get("recent_win_rate")
            recent_str = f" recent {recent:.2f}" if recent is not None else ""
            print(
                f"    {r['champion']:<20} games={r['games_played']:>4} "
                f"wr={r['avg_rating']:.3f}{recent_str}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
