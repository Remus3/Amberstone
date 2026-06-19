"""tools/replay_build_order_validate.py - the Lane-B BUILD-ORDER flip gate (HZ-C2).

Replay-validation harness for the SHIPPED build-order recommendation - the
``anti_tank`` vs ``anti_squishy`` BUILD A/B chip that ``core.precomputed_build_coach``
serves over the HZ-B2 ``build_order_variants`` table. It REPORTS one headline
number: when a player's ACTUAL itemization FOLLOWED the chip's recommended
durability lean, did they win more often than when it did not. That number is the
gate that decides whether the deterministic build recommendation is trustworthy
enough to FLIP the live coach off its Claude Haiku "do I pivot anti-tank" call.

How this differs from the two sibling gates
-------------------------------------------
``replay_matchup_validate`` gates the 1v1 matchup ENGINE (net_swing vs lane
gold / solo-kill duel). ``replay_laning_verdict_validate`` gates the HZ-A laning
VERDICT artifact (trade/all-in/back-off vs the same lane proxies). Both proved a
COIN-FLIP against those 1v1 proxies. THIS gate asks a different, comp-level
question with a stronger truth signal: the build recommendation is a WHOLE-GAME
itemization call, so the ground truth is the WIN, not a 10-minute lane proxy.

How it works
------------
1. Reuse the proven SR-match selection from ``replay_matchup_validate``
   (game_mode='CLASSIC', has_timeline=1, most-recent first; ``--limit N``).
2. Per match, read every participant: their champion, the 5-champion ENEMY comp
   (the other team), their final item set (item0..item6), and whether they won.
3. recommended_lean = ``core.precomputed_build_coach.comp_lean(enemy_comp)`` -
   the EXACT classifier the live chip uses (frontline wall -> anti_tank, else
   anti_squishy). An unresolvable comp is uncovered (skipped).
4. actual_lean is read from the SHIPPED HZ-B2 table itself, so the gate uses the
   artifact's OWN notion of what each build means: for the champion, AT_only =
   items in the anti_tank order but not the anti_squishy order, AS_only = the
   inverse. The player's real build is classified by which distinctive set it
   intersects more. A tie / no distinctive hit is ambiguous (excluded). An
   uncovered champion is skipped.
5. GROUND TRUTH = the WIN. The headline accumulator splits decisive rows into
   FOLLOWED (actual_lean == recommended) vs NOT-FOLLOWED and reports the win
   rate + 95% Wilson interval of each, plus a recommended x actual 2x2 win table
   and a per-recommended-variant breakdown.
6. SECONDARY (completion-timing): for the FOLLOWED rows, read ITEM_PURCHASED and
   find the earliest purchase-minute of any recommended-lean distinctive item;
   bucket win rate by fast (<= median) vs slow (> median completion). Tests
   whether COMPLETING the recommended build sooner correlates with winning.

Interpreting the result
-----------------------
- followed winrate ~ not-followed winrate = the recommendation carries no
  decision signal (do NOT flip the build coach off Haiku).
- followed winrate meaningfully > not-followed, with the two-proportion 95%
  difference interval excluding 0 at large n, = the recommendation is a
  defensible deterministic substitute. Honest caveat: the win is a 10-player
  TEAM outcome and itemization is one lever, so any true effect is DILUTED -
  treat a small but CI-clean separation as real, and a noisy one as none.

Output
------
- A JSON gate artifact at ``ops/runtime/build_order_validation.json`` (override
  with ``--out``). The durable deliverable.
- A concise human summary on stdout.

Fail-soft: a malformed match / participant / cell never aborts the run - it is
skipped and counted. ASCII-only by hard rule.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Resolve project root + tools dir so both package imports (core.*) and the
# sibling-module reuse (replay_matchup_validate) work regardless of CWD.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
for _p in (str(_ROOT), str(_THIS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse the proven SR-match selection + Wilson interval (no rebuild).
from replay_matchup_validate import (  # noqa: E402
    select_sr_match_ids,
    wilson_interval,
)

# ----------------------------------------------------------------- tunable defaults
_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "build_order_validation.json"
_DEFAULT_LIMIT = 400
# The flip-readiness rail the operator-proxy pre-authorized: FLIP only when the
# followed-vs-not winrate difference 95% interval excludes 0 AND each arm has at
# least this many decisive rows. Below it, hold Haiku.
_FLIP_MIN_N = 300
# Per-item carrier flag: an individual recommended-lean item is a "carrier" only
# when its bought-vs-not win-diff 95% interval excludes 0 AND it has at least this
# many bought rows. The item-granularity analogue of the lean-level flip rail.
_PER_ITEM_MIN_N = 50

_VARIANTS = ("anti_tank", "anti_squishy")


# ------------------------------------------------------------------------- datatypes
@dataclass
class BuildRow:
    """One participant's build decision extracted from a replay."""

    match_id: str
    champion: str          # the participant's champion (DB canonical-ish name)
    enemy_comp: Tuple[str, ...]  # the 5 enemy champion names
    items: Tuple[str, ...]       # final non-zero item ids (str), order irrelevant
    win: bool
    participant_id: int = 0


# ------------------------------------------------------------------------- statistics
def two_prop_diff_ci(
    s1: int, n1: int, s2: int, n2: int, z: float = 1.96
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """95% Wald interval for the difference of two independent proportions
    ``p1 - p2`` (followed minus not-followed). Returns ``(diff, lo, hi)``; any
    component is None when a sample is empty. The gate's flip rail reads ``lo``:
    ``lo > 0`` means followed is cleanly better than not-followed."""
    if n1 <= 0 or n2 <= 0:
        return (None, None, None)
    p1 = s1 / n1
    p2 = s2 / n2
    diff = p1 - p2
    se = math.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    margin = z * se
    return (diff, diff - margin, diff + margin)


class _WinBucket:
    """A win/total accumulator with a Wilson interval."""

    def __init__(self) -> None:
        self.n = 0
        self.wins = 0

    def record(self, win: bool) -> None:
        self.n += 1
        if win:
            self.wins += 1

    def to_dict(self) -> dict:
        lo, hi = wilson_interval(self.wins, self.n)
        return {
            "n": self.n,
            "wins": self.wins,
            "winrate": (self.wins / self.n) if self.n else None,
            "wilson_95_lo": lo,
            "wilson_95_hi": hi,
        }


# --------------------------------------------------------------------------- db reads
def extract_build_rows(conn: sqlite3.Connection, match_id: str) -> List[BuildRow]:
    """Return one BuildRow per participant in a match (the enemy comp + final
    build + win). Fail-soft: any DB error -> empty list; a malformed participant
    row is skipped. Requires a clean two-team split to resolve the enemy comp."""
    try:
        prows = conn.execute(
            "SELECT participant_id, team_id, champion_name, win, "
            "item0, item1, item2, item3, item4, item5, item6 "
            "FROM participants WHERE match_id = ?",
            (match_id,),
        ).fetchall()
    except sqlite3.Error:
        return []

    # Group by team so each participant's enemy comp is the other team's champs.
    teams: Dict[int, List[tuple]] = {}
    for row in prows:
        pid, team_id, champ = row[0], row[1], row[2]
        if pid is None or not champ or team_id is None:
            continue
        teams.setdefault(int(team_id), []).append(row)
    if len(teams) != 2:
        return []

    champ_by_team = {
        t: tuple(str(r[2]) for r in members if r[2]) for t, members in teams.items()
    }
    team_ids = list(teams.keys())
    other_of = {team_ids[0]: team_ids[1], team_ids[1]: team_ids[0]}

    out: List[BuildRow] = []
    for team_id, members in teams.items():
        enemy = champ_by_team.get(other_of[team_id], ())
        if not enemy:
            continue
        for r in members:
            pid, _t, champ, win = r[0], r[1], r[2], r[3]
            items = tuple(
                str(x) for x in r[4:11] if x is not None and int(x) != 0
            )
            out.append(
                BuildRow(
                    match_id=match_id,
                    champion=str(champ),
                    enemy_comp=enemy,
                    items=items,
                    win=bool(win),
                    participant_id=int(pid),
                )
            )
    return out


def first_recommended_purchase_min(
    conn: sqlite3.Connection,
    match_id: str,
    participant_id: int,
    distinctive: frozenset,
) -> Optional[float]:
    """Earliest ITEM_PURCHASED minute (timestamp_ms/60000) at which ``participant_id``
    bought ANY item in ``distinctive``, or None if they never did / on any DB
    error. The completion-timing proxy: how soon the recommended build came
    online. Fail-soft, never raises."""
    if not distinctive:
        return None
    try:
        rows = conn.execute(
            "SELECT timestamp_ms, item_id FROM timeline_events "
            "WHERE match_id = ? AND event_type = 'ITEM_PURCHASED' "
            "AND participant_id = ?",
            (match_id, participant_id),
        ).fetchall()
    except sqlite3.Error:
        return None
    best: Optional[float] = None
    for ts, iid in rows:
        if ts is None or iid is None:
            continue
        if str(iid) not in distinctive:
            continue
        minute = float(ts) / 60000.0
        if best is None or minute < best:
            best = minute
    return best


# --------------------------------------------------------------------- classification
def distinctive_sets(
    champion: str,
    table_lookup_fn: Callable[[str, str], dict],
) -> Optional[Tuple[frozenset, frozenset]]:
    """``(AT_only, AS_only)`` distinctive item-id sets for a champion from the
    shipped HZ-B2 variant orders, or None when the champion is uncovered or
    neither order distinguishes the other. AT_only = anti_tank order minus
    anti_squishy order; AS_only = the inverse. Using the artifact's OWN orders
    keeps the gate self-consistent (no hard-coded item taxonomy)."""
    at_cell = table_lookup_fn(champion, "anti_tank") or {}
    as_cell = table_lookup_fn(champion, "anti_squishy") or {}
    at_order = at_cell.get("order") if isinstance(at_cell, dict) else None
    as_order = as_cell.get("order") if isinstance(as_cell, dict) else None
    if not at_order or not as_order:
        return None
    at_set = {str(x) for x in at_order}
    as_set = {str(x) for x in as_order}
    at_only = frozenset(at_set - as_set)
    as_only = frozenset(as_set - at_set)
    if not at_only and not as_only:
        # The two builds are identical for this champ - it cannot distinguish a
        # lean, so it carries no decision signal here.
        return None
    return (at_only, as_only)


def classify_actual_lean(
    items: Sequence[str], at_only: frozenset, as_only: frozenset
) -> Optional[str]:
    """Which lean the player's actual build expresses: ``anti_tank`` /
    ``anti_squishy`` / None (a tie or no distinctive item -> ambiguous, excluded).
    Scored by how many distinctive items of each lean the final build contains."""
    bag = {str(x) for x in items}
    at_hits = len(bag & at_only)
    as_hits = len(bag & as_only)
    if at_hits == as_hits:
        return None
    return "anti_tank" if at_hits > as_hits else "anti_squishy"


def score_row(
    row: BuildRow,
    comp_lean_fn: Callable[[Sequence[str]], Optional[Tuple[str, str]]],
    table_lookup_fn: Callable[[str, str], dict],
) -> Tuple[str, Optional[str], Optional[str], bool]:
    """Score one BuildRow.

    Returns ``(status, recommended, actual, win)`` where status is one of
    ``uncovered_comp`` (no resolvable enemy comp -> no recommendation),
    ``uncovered_champ`` (champion not in the variant table), ``ambiguous`` (the
    actual build did not lean either way), or ``decisive`` (a real comparison;
    ``recommended`` / ``actual`` are both set)."""
    lean = comp_lean_fn(row.enemy_comp)
    if not lean:
        return ("uncovered_comp", None, None, row.win)
    recommended = lean[0]
    sets = distinctive_sets(row.champion, table_lookup_fn)
    if sets is None:
        return ("uncovered_champ", recommended, None, row.win)
    at_only, as_only = sets
    actual = classify_actual_lean(row.items, at_only, as_only)
    if actual is None:
        return ("ambiguous", recommended, None, row.win)
    return ("decisive", recommended, actual, row.win)


def item_outcomes(
    row: BuildRow,
    comp_lean_fn: Callable[[Sequence[str]], Optional[Tuple[str, str]]],
    table_lookup_fn: Callable[[str, str], dict],
) -> List[Tuple[str, str, bool, bool]]:
    """Per-item bought-vs-win outcomes for one build row at ITEM granularity.

    For the recommended lean ``L = comp_lean_fn(enemy_comp)[0]`` and the champion's
    ``L``-distinctive item set (the items in the ``L`` variant order but not the
    other), emit one ``(lean, item_id, bought, win)`` tuple per distinctive item:
    whether the player's final build CONTAINED that item, and whether they won.

    Returns ``[]`` when the comp is unresolvable, the champion is uncovered, or the
    recommended lean has no distinctive item (nothing to attribute). This
    DECOMPOSES the lean-level followed-vs-not gate into per-item carriers and
    INCLUDES rows the lean gate calls ambiguous - a balanced build still bought or
    skipped each individual recommended item, so its per-item signal is recovered
    here where the lean gate discards the whole row."""
    lean = comp_lean_fn(row.enemy_comp)
    if not lean:
        return []
    recommended = lean[0]
    sets = distinctive_sets(row.champion, table_lookup_fn)
    if sets is None:
        return []
    at_only, as_only = sets
    distinctive = at_only if recommended == "anti_tank" else as_only
    if not distinctive:
        return []
    bag = {str(x) for x in row.items}
    return [
        (recommended, item_id, item_id in bag, row.win)
        for item_id in sorted(distinctive)
    ]


# ----------------------------------------------------------------------- orchestration
def run_validation(
    db_path: Path,
    limit: int,
    comp_lean_fn: Callable[[Sequence[str]], Optional[Tuple[str, str]]],
    table_lookup_fn: Callable[[str, str], dict],
    *,
    with_timing: bool = True,
) -> dict:
    """Walk the SR replays, score every participant build, build the report.

    The two injected callables are the live coach's own decision surfaces:
    ``comp_lean_fn`` = ``core.precomputed_build_coach.comp_lean`` and
    ``table_lookup_fn(champ, variant)`` = a closure over the loaded HZ-B2 table.
    Injecting them keeps the unit tests free of the real data files."""
    conn = sqlite3.connect(str(db_path))
    try:
        match_ids = select_sr_match_ids(conn, limit)

        followed = _WinBucket()
        not_followed = _WinBucket()
        by_variant: Dict[str, Dict[str, _WinBucket]] = {
            v: {"followed": _WinBucket(), "not_followed": _WinBucket()}
            for v in _VARIANTS
        }
        # recommended x actual 2x2 win table.
        matrix: Dict[str, Dict[str, _WinBucket]] = {
            rec: {act: _WinBucket() for act in _VARIANTS} for rec in _VARIANTS
        }
        # Completion-timing: collect (minute, win) for FOLLOWED rows that bought a
        # recommended-lean distinctive item, then split at the median.
        timing: List[Tuple[float, bool]] = []
        # Item granularity: per (recommended-lean, item_id) bought/not-bought win
        # buckets. Populated for EVERY covered row incl lean-ambiguous, so it mines
        # the rows the headline gate discards. Keyed lean -> item_id -> buckets.
        per_item: Dict[str, Dict[str, Dict[str, _WinBucket]]] = {
            v: {} for v in _VARIANTS
        }

        n_matches_used = 0
        n_matches_skipped = 0
        n_rows = 0
        status_counts = {
            "decisive": 0, "ambiguous": 0,
            "uncovered_comp": 0, "uncovered_champ": 0,
        }

        for mid in match_ids:
            try:
                rows = extract_build_rows(conn, mid)
            except Exception:  # noqa: BLE001
                n_matches_skipped += 1
                continue
            if not rows:
                n_matches_skipped += 1
                continue
            n_matches_used += 1
            n_rows += len(rows)
            for row in rows:
                status, recommended, actual, win = score_row(
                    row, comp_lean_fn, table_lookup_fn)
                status_counts[status] = status_counts.get(status, 0) + 1
                # Item-granularity pass first: runs on every covered row (decisive
                # AND ambiguous), unlike the lean headline below which gates on
                # decisive. This is where the ambiguous rows pay off.
                for lean_v, item_id, bought, iwin in item_outcomes(
                        row, comp_lean_fn, table_lookup_fn):
                    slot = per_item[lean_v].setdefault(
                        item_id,
                        {"bought": _WinBucket(), "not_bought": _WinBucket()})
                    slot["bought" if bought else "not_bought"].record(iwin)
                if status != "decisive" or recommended is None or actual is None:
                    continue
                did_follow = actual == recommended
                (followed if did_follow else not_followed).record(win)
                arm = "followed" if did_follow else "not_followed"
                by_variant[recommended][arm].record(win)
                matrix[recommended][actual].record(win)
                if with_timing and did_follow:
                    sets = distinctive_sets(row.champion, table_lookup_fn)
                    if sets is not None:
                        distinctive = sets[0] if recommended == "anti_tank" else sets[1]
                        minute = first_recommended_purchase_min(
                            conn, mid, row.participant_id, distinctive)
                        if minute is not None:
                            timing.append((minute, win))
    finally:
        conn.close()

    diff, diff_lo, diff_hi = two_prop_diff_ci(
        followed.wins, followed.n, not_followed.wins, not_followed.n)
    flip_ready = bool(
        diff_lo is not None and diff_lo > 0.0
        and followed.n >= _FLIP_MIN_N and not_followed.n >= _FLIP_MIN_N
    )

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "gate": "hz_c2_build_order_lean",
        "surface": "core.precomputed_build_coach (shipped HZ-B2 artifact)",
        "ground_truth": "win",
        "limit": limit,
        "matches_selected": len(match_ids),
        "matches_used": n_matches_used,
        "matches_skipped": n_matches_skipped,
        "rows_total": n_rows,
        "status_counts": status_counts,
        "followed": followed.to_dict(),
        "not_followed": not_followed.to_dict(),
        "difference": {
            "followed_minus_not": diff,
            "wald_95_lo": diff_lo,
            "wald_95_hi": diff_hi,
            "flip_min_n_each_arm": _FLIP_MIN_N,
            "flip_ready": flip_ready,
        },
        "by_variant": {
            v: {arm: by_variant[v][arm].to_dict() for arm in ("followed", "not_followed")}
            for v in _VARIANTS
        },
        "matrix": {
            rec: {act: matrix[rec][act].to_dict() for act in _VARIANTS}
            for rec in _VARIANTS
        },
        "timing": _timing_report(timing),
        "per_item": _per_item_report(per_item),
        "interpretation": (
            "Headline = winrate(actual build FOLLOWED the chip's recommended lean) "
            "vs winrate(did NOT). The win is a 10-player TEAM outcome and "
            "itemization is one lever, so a true effect is DILUTED: flip_ready is "
            "True only when the two-proportion 95% difference interval excludes 0 "
            "AND each arm has >= flip_min_n rows. flip_ready False (or a near-zero "
            "difference) = no decision signal, hold Haiku. timing tests whether "
            "completing the recommended build sooner (<= median minute) wins more."
        ),
    }


def _per_item_report(
    per_item: Dict[str, Dict[str, Dict[str, "_WinBucket"]]],
    min_n: int = _PER_ITEM_MIN_N,
) -> dict:
    """Rank per-item carriers by bought-minus-not win-diff (highest first).

    Each entry carries the two-proportion 95% (Wald) interval of
    ``winrate(bought item) - winrate(did not buy item)`` among rows whose
    recommended lean owns the item. ``carrier`` flags an item whose ``lo > 0`` at
    ``>= min_n`` bought rows = a clean per-item win contributor (the item-level
    analogue of the headline flip rail). None-diff (an empty arm) sorts last."""
    items_out: List[dict] = []
    for lean in _VARIANTS:
        for item_id, slot in per_item.get(lean, {}).items():
            b, nb = slot["bought"], slot["not_bought"]
            diff, lo, hi = two_prop_diff_ci(b.wins, b.n, nb.wins, nb.n)
            items_out.append({
                "lean": lean,
                "item_id": item_id,
                "bought": b.to_dict(),
                "not_bought": nb.to_dict(),
                "diff_bought_minus_not": diff,
                "wald_95_lo": lo,
                "wald_95_hi": hi,
                "carrier": bool(lo is not None and lo > 0.0 and b.n >= min_n),
            })
    items_out.sort(key=lambda d: (d["diff_bought_minus_not"] is None,
                                  -(d["diff_bought_minus_not"] or 0.0)))
    return {
        "min_n": min_n,
        "n_items": len(items_out),
        "n_carriers": sum(1 for d in items_out if d["carrier"]),
        "items": items_out,
    }


def _timing_report(timing: List[Tuple[float, bool]]) -> dict:
    """Split the collected (minute, win) FOLLOWED rows at the median completion
    minute into fast/slow win buckets."""
    n = len(timing)
    if n == 0:
        return {"n": 0, "median_min": None, "fast": _WinBucket().to_dict(),
                "slow": _WinBucket().to_dict()}
    minutes = sorted(m for m, _w in timing)
    mid = n // 2
    median = minutes[mid] if n % 2 else (minutes[mid - 1] + minutes[mid]) / 2.0
    fast, slow = _WinBucket(), _WinBucket()
    for minute, win in timing:
        (fast if minute <= median else slow).record(win)
    return {
        "n": n,
        "median_min": round(median, 2),
        "fast": fast.to_dict(),
        "slow": slow.to_dict(),
    }


# ----------------------------------------------------------------------------- output
def _load_item_names() -> Dict[str, str]:
    """Best-effort ``{item_id: name}`` from the newest DDragon ``item.json`` for
    the per-item carrier summary. Fail-soft: ANY problem returns ``{}`` (the
    printer then shows bare ids). Never raises; never touched by the unit tests."""
    try:
        base = _ROOT / "data" / "meta_build" / "ddragon"
        patches = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
        for pdir in patches:
            path = pdir / "item.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8")).get("data") or {}
            return {str(k): str(v.get("name", "")) for k, v in data.items()}
    except Exception:  # noqa: BLE001
        return {}
    return {}


def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_summary(report: dict) -> None:
    """Concise human-readable summary on stdout (ASCII only)."""
    print("")
    print("=== Replay BUILD-ORDER validation (build-coach Haiku-flip gate) ===")
    print(f"db={report['db']}  gate={report['gate']}  truth={report['ground_truth']}")
    sc = report["status_counts"]
    print(
        f"matches: selected={report['matches_selected']} used={report['matches_used']} "
        f"skipped={report['matches_skipped']}  rows={report['rows_total']}"
    )
    print(
        f"status: decisive={sc['decisive']} ambiguous={sc['ambiguous']} "
        f"uncovered_comp={sc['uncovered_comp']} uncovered_champ={sc['uncovered_champ']}"
    )
    print("")
    for label, key in (("FOLLOWED recommendation", "followed"),
                       ("NOT followed", "not_followed")):
        b = report[key]
        ci = ""
        if b["wilson_95_lo"] is not None:
            ci = f"[{b['wilson_95_lo'] * 100:4.1f}, {b['wilson_95_hi'] * 100:4.1f}]"
        print(f"  {label:<24} n={b['n']:>5}  winrate={_fmt_pct(b['winrate'])}  {ci}")
    d = report["difference"]
    if d["followed_minus_not"] is not None:
        print("")
        print(
            f"  difference (followed - not) = {d['followed_minus_not'] * 100:+5.1f}%  "
            f"95%=[{d['wald_95_lo'] * 100:+5.1f}, {d['wald_95_hi'] * 100:+5.1f}]  "
            f"flip_ready={d['flip_ready']}"
        )
    print("")
    print("  -- per recommended-variant (followed winrate) --")
    for v in _VARIANTS:
        f = report["by_variant"][v]["followed"]
        nf = report["by_variant"][v]["not_followed"]
        print(
            f"    {v:<13} followed n={f['n']:>5} wr={_fmt_pct(f['winrate'])}   "
            f"not n={nf['n']:>5} wr={_fmt_pct(nf['winrate'])}"
        )
    t = report["timing"]
    print("")
    print(f"  -- completion-timing (followed rows, median={t['median_min']}min) --")
    print(
        f"    fast(<=med) n={t['fast']['n']:>5} wr={_fmt_pct(t['fast']['winrate'])}   "
        f"slow(>med) n={t['slow']['n']:>5} wr={_fmt_pct(t['slow']['winrate'])}"
    )
    pi = report.get("per_item") or {}
    items = pi.get("items") or []
    if items:
        names = _load_item_names()
        print("")
        print(
            f"  -- per-ITEM carriers (bought-vs-not win-diff, min_n={pi.get('min_n')}, "
            f"{pi.get('n_carriers', 0)}/{pi.get('n_items', 0)} carriers) --"
        )
        shown = [d for d in items if d["bought"]["n"] >= pi.get("min_n", 0)][:12]
        for d in shown:
            nm = names.get(str(d["item_id"]), "")
            tag = "*" if d["carrier"] else " "
            lo = d["wald_95_lo"]
            ci = f"[{lo * 100:+5.1f},{d['wald_95_hi'] * 100:+5.1f}]" if lo is not None else ""
            print(
                f"   {tag} {d['lean']:<12} {str(d['item_id']):>6} {nm[:18]:<18} "
                f"bought n={d['bought']['n']:>5} wr={_fmt_pct(d['bought']['winrate'])} "
                f"diff={_fmt_pct(d['diff_bought_minus_not'])} {ci}"
            )
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


# ----------------------------------------------------------------------------- loaders
def make_table_lookup(mode: str) -> Callable[[str, str], dict]:
    """Closure over the shipped HZ-B2 table -> ``(champ, variant) -> cell``,
    canonicalizing the champion key at the boundary (item-439 class). Lazy import
    so unit tests that inject their own lookup never touch the real data files."""
    from core.archetype_picks import canonical_champion_id
    from core.build_order_variants import load_build_order_variants, lookup

    table = load_build_order_variants(mode)

    def _lookup(champion: str, variant: str) -> dict:
        try:
            return lookup(table, canonical_champion_id(str(champion)), variant)
        except Exception:  # noqa: BLE001
            return {}

    return _lookup


def make_comp_lean_fn() -> Callable[[Sequence[str]], Optional[Tuple[str, str]]]:
    """The live chip's own comp classifier (lazy import)."""
    from core.precomputed_build_coach import comp_lean

    def _lean(enemy_comp: Sequence[str]) -> Optional[Tuple[str, str]]:
        try:
            return comp_lean(list(enemy_comp or []))
        except Exception:  # noqa: BLE001
            return None

    return _lean


def _write_report(report: dict, out_path: Path) -> None:
    """Atomic JSON write of the gate artifact (ASCII-only)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Replay-validate the shipped build-order recommendation (build-coach Haiku-flip gate)."
    )
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="Path to rewind_history.db")
    ap.add_argument("--mode", default="sr", help="Variant table mode (sr/aram/arena). Default %(default)s.")
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                    help="Max SR matches to replay (0 = all). Default %(default)s.")
    ap.add_argument("--no-timing", action="store_true",
                    help="Skip the completion-timing secondary (faster; no ITEM_PURCHASED reads).")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON gate artifact path.")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    print(f"Loading shipped HZ-B2 variant table (mode={args.mode})...", file=sys.stderr)
    table_lookup_fn = make_table_lookup(args.mode)
    comp_lean_fn = make_comp_lean_fn()

    report = run_validation(
        db_path=db_path, limit=args.limit,
        comp_lean_fn=comp_lean_fn, table_lookup_fn=table_lookup_fn,
        with_timing=not args.no_timing,
    )
    out_path = Path(args.out)
    _write_report(report, out_path)
    print_summary(report)
    print(f"gate artifact written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
