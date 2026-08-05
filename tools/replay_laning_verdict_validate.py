"""tools/replay_laning_verdict_validate.py - the HZ-A laning-VERDICT flip gate.

Replay-validation harness for the SHIPPED HZ-A laning precompute ARTIFACT - the
on-disk ``data/daemon_slayer/laning_scenarios/<patch>/*.json`` cells that
``core.precomputed_laning_coach`` serves as the live A/B "trade / all-in / back
off" chip. It REPORTS how often the verdict the chip would show actually matched
the real lane outcome, so the orchestrator can decide whether the precomputed
laning coach is trustworthy enough to FLIP off its live Claude Haiku call.

How this differs from ``tools/replay_matchup_validate.py``
---------------------------------------------------------
That harness gates the ``compute_matchup`` ENGINE FUNCTION (net_swing) called
fresh in-process. THIS harness gates the PRECOMPUTE ARTIFACT end-to-end: it
reads the shipped JSON through the exact live path the coach uses
(``load_laning_scenarios`` -> ``lookup`` at the unknown-state baseline cell
band/full/all_up) and scores the discrete VERDICT ACTION (all_in / trade /
back_off), not just the swing sign. If the table build dropped, rounded, or
mis-keyed a cell, only this gate catches it; and only this gate answers "when
the chip says ALL-IN, did committing actually win?".

How it works
------------
1. Reuse the proven SR-match selection + same-lane pairing + solo-kill-duel
   extraction from ``replay_matchup_validate`` (no rebuild).
2. Per lane pair (champ_a on team 100, champ_b on team 200), at each replay
   level, resolve the shipped cell ``lookup(table, canon(a), canon(b),
   band_for_level(level), "full", "all_up")``. The full/all_up state is the
   live coach's documented unknown-mana / unknown-ult baseline read
   (``mana_state_for(None)`` -> full, ``cd_state_for(None)`` -> all_up), so the
   gate scores exactly what the chip shows when the live inputs are unknown.
3. The cell verdict gives champ_a's stance: ``all_in`` / ``trade`` -> a is
   favored to win the exchange; ``back_off`` -> a is unfavored (b favored);
   ``even`` (or |net_swing| below the dead-band) -> excluded.
4. GROUND TRUTH (same proxies + caveats as the matchup gate): lane gold at the
   chosen frame, and the direct solo-kill duel differential. Agreement =
   favored side == the side that actually came out ahead.
5. Also reports a per-verdict-ACTION breakdown: for each of all_in / trade /
   back_off, how often the favored side won. That is the headline flip signal.

Interpreting the result
-----------------------
- agreement ~0.50 = the verdict carries no signal; do NOT flip the laning coach
  off Haiku on it.
- agreement meaningfully > 0.50 (e.g. >= 0.55 with large n) = the shipped
  verdict is a defensible deterministic substitute for the LLM trade judgment
  against this lane-outcome proxy. A human / orchestrator decides the flip; this
  harness only reports the number.

Axis sweep (``--cd-state`` / ``--item-state``)
----------------------------------------------
Step 2 above scores ONE cell per pair. That silently collapsed two real axes,
so a flip decision rested on a single slice of the table. The sweep flags score
the cartesian product of the requested cd_states x item_states, reported per
combination under ``axis_sweep``. Both flags default to unset, and an unset run
resolves the identical baseline cell it always did - that is what keeps a new
number comparable against the 2026-06 baseline artifact.

Note that ``item_state`` is INERT against every table currently on disk: they
are all schema ``laning_scenarios/v3``, whose cd node IS the leaf cell, so
``lookup``'s descend-only fallback returns the same cell for every item_state.
Measuring that inertness is the point - it was previously unobservable.

Output
------
- A JSON gate artifact at ``ops/runtime/laning_verdict_validation.json``
  (override with ``--out``). The durable deliverable.
- A concise human summary on stdout, including a BALANCE CENSUS
  (``label_base_rate_gold``) that separates "the verdict carries no signal"
  from "the harness cannot tell" - a ~0.50 agreement only indicts the verdict
  when the predictor and the label both actually vary.

Fail-soft: a malformed match / pair / cell never aborts the run - it is skipped
and counted. ASCII-only by hard rule.

"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Resolve project root + the tools dir so both the package imports (core.*) and
# the sibling-module reuse (replay_matchup_validate) work regardless of CWD.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
for _p in (str(_ROOT), str(_THIS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse the proven replay scaffolding (selection / pairing / duel truth / stats).
from replay_matchup_validate import (  # noqa: E402
    LanePair,
    LevelResult,
    extract_kill_counts,
    extract_lane_pairs,
    select_sr_match_ids,
    wilson_interval,
)

# ----------------------------------------------------------------- tunable defaults
_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "laning_verdict_validation.json"
_DEFAULT_LIMIT = 400
# Levels chosen to land in distinct bands: 6 -> L6 (first-ult spike), 11 -> L11
# (two-item mid). L2 mirrors are mostly even so are not a default.
_DEFAULT_LEVELS = (6, 11)
_DEFAULT_GOLD_FRAME_MIN = 10

# |net_swing| below this counts as "even" - excluded from the denominator. Same
# scale + default as the matchup gate (the table bakes the engine net_swing).
_EVEN_BAND = 0.02

# The unknown-state baseline cell: what the live chip resolves when mana / ult /
# items are unknown (``mana_state_for(None)`` -> full, ``cd_state_for(None)`` ->
# all_up, and ``lookup``'s own item_state default). These are pinned as module
# constants rather than call-site literals so the sweep can vary an axis WITHOUT
# moving the default - the 2026-06 baseline is only comparable against a run
# that still scores this exact cell.
_DEFAULT_MANA_STATE = "full"
_DEFAULT_CD_STATE = "all_up"
_DEFAULT_ITEM_STATE = "none"

# Verdict -> champ_a stance. all_in/trade = a commits (a favored); back_off = a
# yields (b favored); even = no decisive call.
_AGGRESSIVE = ("all_in", "trade")
_DEFENSIVE = ("back_off",)
_ACTION_VERDICTS = _AGGRESSIVE + _DEFENSIVE


# --------------------------------------------------------------------- verdict access
def make_verdict_fn(
    table: object,
    cd_state: str = _DEFAULT_CD_STATE,
    item_state: str = _DEFAULT_ITEM_STATE,
    mana_state: str = _DEFAULT_MANA_STATE,
) -> Callable[[str, str, str], Tuple[Optional[str], object]]:
    """Closure over the loaded HZ-A table -> ``(champ_a, champ_b, level) ->
    (verdict, net_swing)`` via the live coach lookup path. Missing cell / any
    error -> ``(None, None)`` (counted as uncovered). Imported lazily so unit
    tests that inject their own verdict_fn never need the real data files.

    The three state axes are keyword arguments defaulting to the unknown-state
    baseline, so an un-flagged call resolves exactly the cell this gate has
    always scored. ``item_state`` is a no-op against the v3 tables currently on
    disk (a v3 cd node IS the leaf cell), which is precisely why the axis needs
    to be sweepable rather than assumed - the collapse is invisible otherwise."""
    from core.archetype_picks import canonical_champion_id
    from core.laning_scenario_precompute import lookup
    from core.precomputed_laning_coach import band_for_level

    def _verdict(champ_a: str, champ_b: str, level: object) -> Tuple[Optional[str], object]:
        try:
            cell = lookup(
                table,
                canonical_champion_id(champ_a),
                canonical_champion_id(champ_b),
                band_for_level(level),
                mana_state,
                cd_state,
                item_state,
            )
        except Exception:  # noqa: BLE001
            return (None, None)
        if not isinstance(cell, dict):
            return (None, None)
        return (cell.get("verdict"), cell.get("net_swing"))

    return _verdict


def _parse_states(raw: Optional[str], default: str) -> List[str]:
    """Comma-separated axis states -> ordered, de-duplicated list. An absent or
    all-blank value yields ``[default]`` so the caller always has one column."""
    out: List[str] = []
    for chunk in str(raw or "").split(","):
        chunk = chunk.strip()
        if chunk and chunk not in out:
            out.append(chunk)
    return out or [default]


def sweep_axis_combos(
    cd_states: Sequence[str], item_states: Sequence[str]
) -> List[Tuple[str, str]]:
    """Cartesian product of the two swept axes, cd-major (so the printed sweep
    groups every item_state under its cd_state)."""
    return [(cd, item) for cd in cd_states for item in item_states]


def favored_side(verdict: Optional[str], net_swing: object, even_band: float) -> Optional[bool]:
    """Which side the shipped cell favors: ``True`` -> champ_a, ``False`` ->
    champ_b, ``None`` -> excluded (uncovered / even / below the dead-band).

    The discrete action verdict is authoritative when present (``all_in`` /
    ``trade`` -> a; ``back_off`` -> b); otherwise the net_swing sign decides.
    """
    if verdict in _AGGRESSIVE:
        return True
    if verdict in _DEFENSIVE:
        return False
    if verdict == "even":
        # An explicit even verdict is a decisive no-call - exclude it, do NOT
        # fall through to the swing sign (the table assigns even at |swing|~0,
        # but a defensive guard keeps a labelled even out of the denominator).
        return None
    # An unlabeled cell (verdict is None): fall back to the swing sign, dead-banded.
    try:
        swing = float(net_swing)
    except (TypeError, ValueError):
        return None
    if abs(swing) < even_band:
        return None
    return swing > 0.0


# --------------------------------------------------------------------------- scoring
def score_pair_gold(
    pair: LanePair,
    level: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool, Optional[str]]:
    """Score one lane pair against the lane-gold ground truth at one level.

    Returns ``(status, agreed, verdict)`` where status is one of ``uncovered``
    (no shipped cell), ``even`` (excluded), ``gold_tie`` (no decisive truth) or
    ``decisive`` (``agreed`` meaningful). ``verdict`` is echoed for the action
    breakdown.
    """
    verdict, swing = verdict_fn(pair.champ_a, pair.champ_b, level)
    if verdict is None and swing is None:
        return ("uncovered", False, None)
    fav_a = favored_side(verdict, swing, even_band)
    if fav_a is None:
        return ("even", False, verdict)
    if pair.gold_a == pair.gold_b:
        return ("gold_tie", False, verdict)
    gold_favors_a = pair.gold_a > pair.gold_b
    return ("decisive", fav_a == gold_favors_a, verdict)


def score_pair_duel(
    pair: LanePair,
    level: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    a_kills_b: int,
    b_kills_a: int,
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool, Optional[str]]:
    """Score one lane pair against the direct solo-kill duel differential.

    status adds ``no_duel`` (the pair never killed each other) and ``kill_tie``
    (equal kills) to the gold path's set. The duel winner is whoever killed the
    other more - the most direct proxy for the trade the chip claims.
    """
    verdict, swing = verdict_fn(pair.champ_a, pair.champ_b, level)
    if verdict is None and swing is None:
        return ("uncovered", False, None)
    fav_a = favored_side(verdict, swing, even_band)
    if fav_a is None:
        return ("even", False, verdict)
    if a_kills_b == 0 and b_kills_a == 0:
        return ("no_duel", False, verdict)
    if a_kills_b == b_kills_a:
        return ("kill_tie", False, verdict)
    duel_favors_a = a_kills_b > b_kills_a
    return ("decisive", fav_a == duel_favors_a, verdict)


class _LabelBaseRate:
    """Predictor-vs-label balance over the scored pairs.

    Exists to separate two readings of a ~0.50 agreement that look identical in
    the headline number: a verdict that carries no signal, versus a harness that
    cannot tell. If the predictor is degenerate (always one side) or the label is
    one-sided, the agreement is an artifact and says nothing about the verdict.
    Only when BOTH vary does 0.50 mean zero mutual information."""

    def __init__(self) -> None:
        self.n = 0
        self.pred_a = 0
        self.label_a = 0
        self.label_b = 0
        self.label_ties = 0

    def record(self, fav_a: bool, truth_a: float, truth_b: float) -> None:
        self.n += 1
        if fav_a:
            self.pred_a += 1
        if truth_a == truth_b:
            self.label_ties += 1
        elif truth_a > truth_b:
            self.label_a += 1
        else:
            self.label_b += 1

    def to_dict(self) -> dict:
        label_n = self.label_a + self.label_b
        return {
            "n": self.n,
            "predictor_favors_a_rate": (self.pred_a / self.n) if self.n else None,
            "label_favors_a_rate": (self.label_a / label_n) if label_n else None,
            "label_decisive_n": label_n,
            "label_ties": self.label_ties,
        }


class _ActionBreakdown:
    """Per-verdict-ACTION agreement accumulator (all_in / trade / back_off)."""

    def __init__(self) -> None:
        self.by_verdict: Dict[str, Dict[str, int]] = {
            v: {"n": 0, "agree": 0} for v in _ACTION_VERDICTS
        }

    def record(self, verdict: Optional[str], agreed: bool) -> None:
        slot = self.by_verdict.get(verdict or "")
        if slot is None:
            return
        slot["n"] += 1
        if agreed:
            slot["agree"] += 1

    def to_dict(self) -> dict:
        out = {}
        for verdict, slot in self.by_verdict.items():
            n = slot["n"]
            lo, hi = wilson_interval(slot["agree"], n)
            out[verdict] = {
                "n": n,
                "agree": slot["agree"],
                "agreement": (slot["agree"] / n) if n else None,
                "wilson_95_lo": lo,
                "wilson_95_hi": hi,
            }
        return out


# ----------------------------------------------------------------------- orchestration
def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the replay corpus read-only, falling back to a plain connect when
    the URI form is unavailable so an odd path never fails the whole gate."""
    try:
        uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return sqlite3.connect(str(db_path))


def run_validation(
    db_path: Path,
    levels: Sequence[int],
    limit: int,
    gold_frame_min: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    even_band: float = _EVEN_BAND,
) -> dict:
    """Walk the SR replays, score every lane pair vs gold + duel truth at each
    level, and build the report (gold agreement, duel agreement, per-action
    breakdown, coverage)."""
    # Read-only URI connect: this is the operator's live 1.8GB history DB in WAL
    # mode, and a read-write handle would touch its -wal/-shm sidecars for a run
    # that only ever SELECTs.
    conn = _connect_readonly(db_path)
    try:
        match_ids = select_sr_match_ids(conn, limit)
        gold: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}
        duel: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}
        action_gold = _ActionBreakdown()
        action_duel = _ActionBreakdown()
        base_rate = _LabelBaseRate()

        n_matches_used = 0
        n_matches_skipped = 0
        n_pairs_total = 0
        n_uncovered = 0
        n_covered = 0

        for mid in match_ids:
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except Exception:  # noqa: BLE001
                n_matches_skipped += 1
                continue
            if not pairs:
                n_matches_skipped += 1
                continue
            n_matches_used += 1
            n_pairs_total += len(pairs)
            for pair in pairs:
                try:
                    kc = extract_kill_counts(conn, mid, pair.pid_a, pair.pid_b)
                except Exception:  # noqa: BLE001
                    kc = {"solo": (0, 0), "any": (0, 0)}
                a_solo, b_solo = kc["solo"]
                for lvl in levels:
                    # Balance census, kept independent of the agreement tally so
                    # a 0.50 headline can be attributed to the verdict rather
                    # than to a degenerate predictor or a one-sided label.
                    _bv, _bs = verdict_fn(pair.champ_a, pair.champ_b, lvl)
                    _bfav = favored_side(_bv, _bs, even_band)
                    if _bfav is not None:
                        base_rate.record(_bfav, pair.gold_a, pair.gold_b)

                    g_status, g_agree, g_verdict = score_pair_gold(
                        pair, lvl, verdict_fn, even_band)
                    if g_status == "uncovered":
                        n_uncovered += 1
                    else:
                        n_covered += 1
                    _tally_gold(gold[lvl], g_status, g_agree, pair.lane)
                    if g_status == "decisive":
                        action_gold.record(g_verdict, g_agree)

                    d_status, d_agree, d_verdict = score_pair_duel(
                        pair, lvl, verdict_fn, a_solo, b_solo, even_band)
                    _tally_duel(duel[lvl], d_status, d_agree, pair.lane)
                    if d_status == "decisive":
                        action_duel.record(d_verdict, d_agree)
    finally:
        conn.close()

    covered_total = n_covered + n_uncovered
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "gate": "hz_a_laning_verdict",
        "surface": "core.precomputed_laning_coach (shipped artifact)",
        "gold_frame_min": gold_frame_min,
        "even_band": even_band,
        "limit": limit,
        "matches_selected": len(match_ids),
        "matches_used": n_matches_used,
        "matches_skipped": n_matches_skipped,
        "pairs_total": n_pairs_total,
        "coverage": {
            "covered": n_covered,
            "uncovered": n_uncovered,
            "covered_fraction": (n_covered / covered_total) if covered_total else None,
        },
        "levels_gold": [gold[lvl].to_dict() for lvl in levels],
        "levels_duel": [duel[lvl].to_dict() for lvl in levels],
        "action_breakdown_gold": action_gold.to_dict(),
        "action_breakdown_duel": action_duel.to_dict(),
        "label_base_rate_gold": base_rate.to_dict(),
        "interpretation": (
            "Gold + solo-kill duel are noisy lane-outcome proxies (ganks / roams "
            "/ missed-assist kills), so treat the agreement as an honest lower-"
            "fidelity signal, not a 1v1 oracle. The full/all_up baseline cell is "
            "scored because that is what the chip shows when live mana/ult are "
            "unknown. agreement ~0.50 = no signal (do NOT flip the laning coach "
            "off Haiku); >0.50 with large n = a defensible deterministic "
            "substitute. action_breakdown is the headline: when the chip says "
            "all_in/trade, how often the aggressor actually came out ahead."
        ),
    }


def _tally_gold(lr: LevelResult, status: str, agreed: bool, lane: str) -> None:
    if status == "uncovered" or status == "even":
        lr.n_even += 1
    elif status == "gold_tie":
        lr.n_gold_tie += 1
    elif status == "decisive":
        lr.record(lane, agreed)


def _tally_duel(lr: LevelResult, status: str, agreed: bool, lane: str) -> None:
    if status == "uncovered" or status == "even":
        lr.n_even += 1
    elif status == "no_duel":
        lr.n_no_duel += 1
    elif status == "kill_tie":
        lr.n_kill_tie += 1
    elif status == "decisive":
        lr.record(lane, agreed)


# ----------------------------------------------------------------------------- output
def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_summary(report: dict) -> None:
    """Concise human-readable summary on stdout (ASCII only)."""
    print("")
    print("=== Replay HZ-A laning-VERDICT validation (laning-coach Haiku-flip gate) ===")
    cov = report["coverage"]
    print(
        f"db={report['db']}  gate={report['gate']}  even_band={report['even_band']}"
    )
    print(
        f"matches: selected={report['matches_selected']} used={report['matches_used']} "
        f"skipped={report['matches_skipped']}  pairs={report['pairs_total']}  "
        f"coverage={cov['covered']}/{cov['covered'] + cov['uncovered']}"
    )
    for label, key in (("GOLD@frame", "levels_gold"), ("SOLO-KILL DUEL", "levels_duel")):
        print("")
        print(f"  -- {label} --")
        print(f"  {'level':>5}  {'n':>6}  {'agree':>6}  {'95% Wilson':>16}")
        print("  " + "-" * 44)
        for lv in report[key]:
            ci = ""
            if lv["wilson_95_lo"] is not None:
                ci = f"[{lv['wilson_95_lo'] * 100:4.1f}, {lv['wilson_95_hi'] * 100:4.1f}]"
            print(
                f"  {lv['level']:>5}  {lv['n_decisive']:>6}  {_fmt_pct(lv['agreement'])}  "
                f"{ci:>16}"
            )
    for label, key in (("ACTION vs GOLD", "action_breakdown_gold"),
                       ("ACTION vs DUEL", "action_breakdown_duel")):
        print("")
        print(f"  -- {label} (per-verdict agreement) --")
        for verdict, slot in report[key].items():
            print(f"    {verdict:<9} n={slot['n']:>5}  agree={_fmt_pct(slot['agreement'])}")
    br = report.get("label_base_rate_gold") or {}
    if br.get("n"):
        print("")
        print("  -- BALANCE CENSUS (is 0.50 the verdict, or the harness?) --")
        print(f"    scored pairs          n={br['n']}")
        print(f"    predictor favors a    {_fmt_pct(br['predictor_favors_a_rate'])}")
        print(f"    label     favors a    {_fmt_pct(br['label_favors_a_rate'])}"
              f"  (n={br['label_decisive_n']}, ties={br['label_ties']})")
        print("    Both near 50% + agreement near 50% = zero mutual information,")
        print("    i.e. the VERDICT is uninformative (not a broken label).")
    for entry in report.get("axis_sweep") or []:
        print("")
        print(f"  -- AXIS SWEEP cd_state={entry['cd_state']} "
              f"item_state={entry['item_state']} --")
        for lv in entry["levels_gold"]:
            print(f"    gold L{lv['level']:<3} n={lv['n_decisive']:>6}  "
                  f"agree={_fmt_pct(lv['agreement'])}")
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


# ----------------------------------------------------------------------------- loaders
def _load_table(mode: str):
    """Load the shipped HZ-A laning table for ``mode`` (lazy import)."""
    from core.precomputed_laning_coach import load_laning_scenarios

    return load_laning_scenarios(mode)


def _write_report(report: dict, out_path: Path) -> None:
    """Atomic JSON write of the gate artifact (ASCII-only)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def _parse_levels(raw: str) -> List[int]:
    out: List[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out or list(_DEFAULT_LEVELS)


def build_arg_parser() -> argparse.ArgumentParser:
    """The CLI surface, split out so the flag defaults are directly testable -
    an accidentally-defaulted sweep flag would silently move the scored cell."""
    ap = argparse.ArgumentParser(
        description="Replay-validate the shipped HZ-A laning verdict (laning-coach Haiku-flip gate)."
    )
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="Path to rewind_history.db")
    ap.add_argument("--mode", default="sr", help="Table mode (sr/aram/arena). Default %(default)s.")
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                    help="Max SR matches to replay (0 = all). Default %(default)s.")
    ap.add_argument("--levels", default=",".join(str(x) for x in _DEFAULT_LEVELS),
                    help="Comma-separated replay levels. Default %(default)s.")
    ap.add_argument("--gold-frame", type=int, default=_DEFAULT_GOLD_FRAME_MIN,
                    help="Minute of the timeline frame used as lane-gold truth. Default %(default)s.")
    ap.add_argument("--even-band", type=float, default=_EVEN_BAND,
                    help="|net_swing| below this is excluded as even. Default %(default)s.")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON gate artifact path.")
    # Both default to None, NOT to the baseline state: an explicit None is how
    # main() tells "no sweep requested" from "sweep the baseline column", which
    # keeps an un-flagged run byte-comparable with the 2026-06 baseline.
    ap.add_argument("--cd-state", default=None,
                    help="Comma-separated cd_states to sweep (e.g. all_up,no_ult). "
                         "Absent = score only the all_up baseline, as before.")
    ap.add_argument("--item-state", default=None,
                    help="Comma-separated item_states to sweep (e.g. none,first_item). "
                         "Absent = score only the lookup default. No-op on v3 tables.")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    levels = _parse_levels(args.levels)
    print(f"Loading shipped HZ-A table (mode={args.mode})...", file=sys.stderr)
    table = _load_table(args.mode)
    verdict_fn = make_verdict_fn(table)

    report = run_validation(
        db_path=db_path, levels=levels, limit=args.limit,
        gold_frame_min=args.gold_frame, verdict_fn=verdict_fn, even_band=args.even_band,
    )

    if args.cd_state is not None or args.item_state is not None:
        combos = sweep_axis_combos(
            _parse_states(args.cd_state, _DEFAULT_CD_STATE),
            _parse_states(args.item_state, _DEFAULT_ITEM_STATE),
        )
        sweep = []
        for cd, item in combos:
            print(f"sweeping cd_state={cd} item_state={item}...", file=sys.stderr)
            sub = run_validation(
                db_path=db_path, levels=levels, limit=args.limit,
                gold_frame_min=args.gold_frame,
                verdict_fn=make_verdict_fn(table, cd_state=cd, item_state=item),
                even_band=args.even_band,
            )
            sweep.append({
                "cd_state": cd,
                "item_state": item,
                "mana_state": _DEFAULT_MANA_STATE,
                "coverage": sub["coverage"],
                "levels_gold": sub["levels_gold"],
                "levels_duel": sub["levels_duel"],
                "action_breakdown_gold": sub["action_breakdown_gold"],
                "label_base_rate_gold": sub["label_base_rate_gold"],
            })
        report["axis_sweep"] = sweep

    out_path = Path(args.out)
    _write_report(report, out_path)
    print_summary(report)
    print(f"gate artifact written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
