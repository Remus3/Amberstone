"""tools/laning_verdict_information_probe.py - why the HZ-A laning verdict was RETIRED.

The adjudication instrument behind ADR-013. ``tools/replay_laning_verdict_validate.py``
answers "how often does the shipped laning verdict agree with the lane outcome?"
and lands on ~0.489. That number ALONE cannot close the question, because a
~0.50 agreement has two completely different explanations:

  (a) the VERDICT carries no information about the lane outcome, or
  (b) the LABEL (lane gold at minute 10) carries no information about anything,
      in which case a perfect verdict would also score ~0.50 and the harness is
      the dead half.

The gate's own balance census separates "uninformative verdict" from "degenerate
label" (does the label vary at all?) but it CANNOT separate (a) from (b): a label
that varies while measuring the wrong thing still yields zero mutual information
against a correct predictor. This probe closes that gap with two measurements the
gate does not make:

1. MUTUAL INFORMATION. The raw 2x2 contingency table of
   (verdict favors side a) x (gold favors side a), reported as mutual
   information in bits against the label entropy, plus phi and a Yates-corrected
   chi-square. Also broken out per role, because an aggregate MI of zero can be
   two real subgroup effects of opposite sign cancelling - and it is.

2. LEARNABILITY CONTROL. A deliberately stupid baseline - the empirical mean
   lane-gold-at-10 per (role, champion), fitted on one half of the corpus and
   scored strictly held-out on the other - against the IDENTICAL label. If a
   champion-identity lookup beats 0.50 on held-out data, explanation (b) is
   dead: the label is learnable and the verdict simply does not learn it. A
   second control reports how often the direct solo-kill duel winner predicts
   the gold winner, which is the same question asked of a known-good predictor.

MEASURED 2026-08-06 (400 SR replays, levels 6 + 11, rewind_history.db; the
served table is 16.13.1 under the stale-patch fallback against a requested
16.15.1, which is what the chip would serve today):
  verdict vs gold      L6 n=1107 agree 0.4887, MI 0.00039 bits (0.039 pct of
                       label entropy), phi -0.023, chi2 0.51.
  bias-corrected MI    L6 -0.000262 bits, L11 -0.000329 bits. NEGATIVE: the
                       measured association is SMALLER than what pure noise
                       produces on average at this n. Not a weak signal - below
                       the noise floor.
  four genuine lanes   dropping JUNGLE entirely (the two junglers never lane):
                       n=1778 agree 0.5124 [0.4891, 0.5356], chi2 0.99. Still
                       straddles 0.50 in the most charitable framing available.
  fitted champ prior   held-out 0.5457 [0.5121, 0.5788] and 0.5394 [0.5030,
                       0.5754] - BOTH Wilson intervals exclude 0.50.
  duel -> gold         0.7705 [0.7429, 0.7960].
So the label is learnable by a per-champion mean and is strongly coupled to the
direct duel outcome, while the shipped verdict is beaten by both and does not
beat a coin. Explanation (a). See ADR-013.

The learnability control is the leg the whole retirement rests on, so its split
is a named function (``split_folds``) partitioned BY MATCH and pinned by test.
Two leaks would otherwise be invisible in the output - splitting by pair, and
fold_a == fold_b == the whole corpus - because both leave the report shape
identical and merely inflate the number.

TRAP - THE MODE FLAG. This probe REFUSES any mode but ``sr`` and it is not being
precious. ``replay_matchup_validate.select_sr_match_ids`` is
``WHERE game_mode = 'CLASSIC'`` unconditionally, so the sibling gate's ``--mode``
swaps the shipped TABLE and never the CORPUS: ``--mode aram`` scores the ARAM
table against SR lane outcomes and prints an identical
``pairs=1998 coverage=3978/3996``, differing only in the agreement column. That
number looks like a native ARAM measurement and is not one. There is no honest
non-SR run to offer, because Riot emits no ``team_position`` for ARAM or Arena
(measured: 20804 ARAM and 2792 CHERRY participant rows, every one empty), so
``extract_lane_pairs`` returns zero pairs for both - ARAM has no lane 1v1 to have
an outcome. Refusing beats returning a plausible wrong number.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
for _p in (str(_ROOT), str(_THIS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from replay_laning_verdict_validate import (  # noqa: E402
    _EVEN_BAND,
    _connect_readonly,
    _load_table,
    favored_side,
    make_verdict_fn,
)
from replay_matchup_validate import (  # noqa: E402
    extract_kill_counts,
    extract_lane_pairs,
    select_sr_match_ids,
    wilson_interval,
)

_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "laning_verdict_information_probe.json"
_DEFAULT_LIMIT = 400
_DEFAULT_LEVELS = (6, 11)
_DEFAULT_GOLD_FRAME_MIN = 10

# A champion needs at least this many observations in the FIT half before its
# mean gold is used as a prior - one observation is a memorised sample, not a
# prior, and it would flatter the control.
_MIN_PRIOR_OBS = 2

_ONLY_MODE = "sr"

# The harness pairs same-"lane" opponents, and Riot files both junglers under
# team_position JUNGLE - so a JUNGLE "lane pair" is two players who never lane
# against each other, scored on which of them banked more gold by minute 10.
# That is clear speed and pathing, not a lane trade. Excluded from the charitable
# pooled read; still reported per-role, because its association is real.
_NON_LANE_ROLE = "JUNGLE"


# ------------------------------------------------------------------ information math
def contingency(rows: Sequence[Tuple[bool, bool]]) -> Dict[str, object]:
    """Mutual information + association stats for one (pred, label) sample.

    ``rows`` are ``(verdict_favors_a, gold_favors_a)`` pairs, already filtered to
    the decisive set. Returns MI in bits, the label entropy it is measured
    against, phi, a Yates-corrected chi-square, and the raw cell counts - the
    cells are reported so the numbers can be re-derived by hand.
    """
    n11 = sum(1 for p, y in rows if p and y)
    n10 = sum(1 for p, y in rows if p and not y)
    n01 = sum(1 for p, y in rows if not p and y)
    n00 = sum(1 for p, y in rows if not p and not y)
    n = n11 + n10 + n01 + n00
    if n == 0:
        return {"n": 0}
    cells = {(1, 1): n11, (1, 0): n10, (0, 1): n01, (0, 0): n00}
    p_pred = ((n11 + n10) / n, (n01 + n00) / n)
    p_label = ((n11 + n01) / n, (n10 + n00) / n)

    mi = 0.0
    chi2 = 0.0
    for (x, y), c in cells.items():
        px = p_pred[0] if x == 1 else p_pred[1]
        py = p_label[0] if y == 1 else p_label[1]
        expected = n * px * py
        if c > 0 and px > 0 and py > 0:
            mi += (c / n) * math.log2((c / n) / (px * py))
        if expected > 0:
            chi2 += (abs(c - expected) - 0.5) ** 2 / expected

    h_label = -sum(p * math.log2(p) for p in p_label if p > 0)
    det = n11 * n00 - n10 * n01
    denom = math.sqrt((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00))
    agree = (n11 + n00) / n
    lo, hi = wilson_interval(n11 + n00, n)

    # MILLER-MADOW. The plug-in MI above is BIASED UPWARD: finite-sample noise
    # manufactures apparent association, so a truly independent pair of
    # variables scores above zero on average. The plug-in entropy bias is
    # (K - 1) / 2N nats for K occupied bins, and MI = H(X) + H(Y) - H(X,Y), so
    # the MI correction is ((Kx - 1) + (Ky - 1) - (Kxy - 1)) / 2N nats - which
    # for a fully-occupied 2x2 is exactly -1 / 2N. Reporting it matters here:
    # it is what turns "the association is small" into "the association is
    # SMALLER THAN NOISE PRODUCES AT THIS n", which is a strictly stronger
    # statement and the one ADR-013 rests on.
    k_x = sum(1 for p in p_pred if p > 0)
    k_y = sum(1 for p in p_label if p > 0)
    k_xy = sum(1 for c in cells.values() if c > 0)
    correction_bits = (((k_x - 1) + (k_y - 1) - (k_xy - 1)) / (2 * n)) / math.log(2)

    return {
        "n": n,
        "n_agree": n11 + n00,
        "agreement": agree,
        "wilson_95_lo": lo,
        "wilson_95_hi": hi,
        "predictor_favors_a_rate": p_pred[0],
        "label_favors_a_rate": p_label[0],
        "mutual_information_bits": mi,
        "miller_madow_correction_bits": correction_bits,
        "mutual_information_bits_miller_madow": mi + correction_bits,
        "below_noise_floor": (mi + correction_bits) < 0.0,
        "label_entropy_bits": h_label,
        "mi_fraction_of_label_entropy": (mi / h_label) if h_label > 0 else None,
        "phi": (det / denom) if denom else None,
        "chi2_yates": chi2,
        "cells": {"pred_a_label_a": n11, "pred_a_label_b": n10,
                  "pred_b_label_a": n01, "pred_b_label_b": n00},
    }


# ------------------------------------------------------------------------ collection
class _Pair:
    """One scored lane pair, flattened so both analyses share one corpus walk."""

    __slots__ = ("match_id", "lane", "champ_a", "champ_b", "gold_a", "gold_b",
                 "solo_a", "solo_b")

    def __init__(self, match_id, lane, champ_a, champ_b, gold_a, gold_b, solo_a, solo_b):
        self.match_id = match_id
        self.lane = lane
        self.champ_a = champ_a
        self.champ_b = champ_b
        self.gold_a = gold_a
        self.gold_b = gold_b
        self.solo_a = solo_a
        self.solo_b = solo_b


def collect_pairs(db_path: Path, limit: int, gold_frame_min: int) -> List[_Pair]:
    """One read-only walk of the SR replay corpus -> flat lane pairs.

    Read-only URI connect for the same reason the gate uses one: this is the
    operator's live multi-GB WAL history DB and a read-write handle would touch
    its sidecars for a run that only SELECTs.
    """
    conn = _connect_readonly(db_path)
    out: List[_Pair] = []
    try:
        for mid in select_sr_match_ids(conn, limit):
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except sqlite3.Error:
                continue
            for pair in pairs:
                try:
                    kc = extract_kill_counts(conn, mid, pair.pid_a, pair.pid_b)
                except sqlite3.Error:
                    kc = {"solo": (0, 0)}
                solo_a, solo_b = kc.get("solo", (0, 0))
                out.append(_Pair(mid, pair.lane, pair.champ_a, pair.champ_b,
                                 pair.gold_a, pair.gold_b, solo_a, solo_b))
    finally:
        conn.close()
    return out


def score_verdict(pairs: Sequence[_Pair], verdict_fn, levels: Sequence[int],
                  even_band: float) -> Dict[str, object]:
    """MI of the shipped verdict against the gold label, overall/per-level/per-role.

    NOTE on independence: a pair contributes one row per LEVEL against the SAME
    minute-10 gold label, so the pooled row is roughly half as independent as its
    n suggests. Per-level blocks are the honest unit and are reported first.
    """
    rows_all: List[Tuple[bool, bool]] = []
    by_level: Dict[int, List[Tuple[bool, bool]]] = {lvl: [] for lvl in levels}
    by_lane: Dict[str, List[Tuple[bool, bool]]] = defaultdict(list)
    for pair in pairs:
        if pair.gold_a == pair.gold_b:
            continue
        label = pair.gold_a > pair.gold_b
        for lvl in levels:
            verdict, swing = verdict_fn(pair.champ_a, pair.champ_b, lvl)
            fav = favored_side(verdict, swing, even_band)
            if fav is None:
                continue
            rows_all.append((fav, label))
            by_level[lvl].append((fav, label))
            by_lane[pair.lane].append((fav, label))
    # The most charitable framing available to the verdict: drop JUNGLE, whose
    # "lane pair" is the two junglers - players who never lane against each
    # other - and pool the four roles that are genuine lane 1v1s. JUNGLE is the
    # one role carrying real (anti-correlated) association, so excluding it
    # removes the strongest objection that the aggregate is a cancellation
    # artifact. If the remaining four still do not clear chance, no framing
    # rescues the verdict.
    genuine = [row for lane, rows in by_lane.items() if lane != _NON_LANE_ROLE
               for row in rows]
    return {
        "pooled_levels": contingency(rows_all),
        "pooled_excluding_jungle": contingency(genuine),
        "per_level": {str(lvl): contingency(by_level[lvl]) for lvl in levels},
        "per_role": {lane: contingency(by_lane[lane]) for lane in sorted(by_lane)},
    }


# -------------------------------------------------------------------------- controls
def _fit_gold_prior(pairs: Sequence[_Pair]) -> Dict[Tuple[str, str], float]:
    """Mean lane-gold-at-frame per (role, champion) over the given pairs."""
    total: Dict[Tuple[str, str], float] = defaultdict(float)
    count: Dict[Tuple[str, str], int] = defaultdict(int)
    for pair in pairs:
        total[(pair.lane, pair.champ_a)] += pair.gold_a
        count[(pair.lane, pair.champ_a)] += 1
        total[(pair.lane, pair.champ_b)] += pair.gold_b
        count[(pair.lane, pair.champ_b)] += 1
    return {k: total[k] / count[k] for k in total if count[k] >= _MIN_PRIOR_OBS}


def _score_prior(prior: Dict[Tuple[str, str], float],
                 pairs: Sequence[_Pair]) -> Dict[str, object]:
    n = k = skipped = 0
    for pair in pairs:
        pa = prior.get((pair.lane, pair.champ_a))
        pb = prior.get((pair.lane, pair.champ_b))
        if pa is None or pb is None or pa == pb or pair.gold_a == pair.gold_b:
            skipped += 1
            continue
        n += 1
        if (pa > pb) == (pair.gold_a > pair.gold_b):
            k += 1
    lo, hi = wilson_interval(k, n) if n else (None, None)
    return {"n": n, "n_agree": k, "skipped": skipped,
            "agreement": (k / n) if n else None,
            "wilson_95_lo": lo, "wilson_95_hi": hi,
            "beats_chance": bool(n and lo is not None and lo > 0.5)}


def split_folds(pairs: Sequence[_Pair]) -> Tuple[List[_Pair], List[_Pair]]:
    """Split the corpus into two DISJOINT folds, partitioned BY MATCH.

    Split by match and never by pair: up to five pairs come from one game and
    share a team gold state, a shared snowball and a shared jungler, so a
    pair-level split leaks the label across the fold boundary and flatters the
    held-out control - which is the single number the ADR-013 retirement rests
    on. Kept as a named function precisely so that property can be asserted
    directly instead of being inferred from a score.
    """
    order = list(dict.fromkeys(p.match_id for p in pairs))
    half = set(order[: len(order) // 2])
    fold_a = [p for p in pairs if p.match_id in half]
    fold_b = [p for p in pairs if p.match_id not in half]
    return fold_a, fold_b


def learnability_control(pairs: Sequence[_Pair]) -> Dict[str, object]:
    """Can ANY predictor beat 0.50 against this label? Split-half, held out."""
    fold_a, fold_b = split_folds(pairs)

    duel_n = duel_k = 0
    for pair in pairs:
        if pair.solo_a == pair.solo_b or pair.gold_a == pair.gold_b:
            continue
        duel_n += 1
        if (pair.solo_a > pair.solo_b) == (pair.gold_a > pair.gold_b):
            duel_k += 1
    d_lo, d_hi = wilson_interval(duel_k, duel_n) if duel_n else (None, None)

    return {
        "champion_gold_prior": {
            "fit_a_score_b": _score_prior(_fit_gold_prior(fold_a), fold_b),
            "fit_b_score_a": _score_prior(_fit_gold_prior(fold_b), fold_a),
            "in_sample_ceiling": _score_prior(_fit_gold_prior(pairs), pairs),
        },
        "duel_predicts_gold": {
            "n": duel_n, "n_agree": duel_k,
            "agreement": (duel_k / duel_n) if duel_n else None,
            "wilson_95_lo": d_lo, "wilson_95_hi": d_hi,
        },
    }


def label_is_learnable(control: Dict[str, object]) -> bool:
    """True when a held-out baseline provably beats chance on this label.

    Both held-out folds must clear 0.50 at the lower Wilson bound. One fold
    clearing it is a coin-flip away from noise; requiring both is what makes
    "the label is fine, the verdict is not" a claim and not a hope.
    """
    prior = control.get("champion_gold_prior") or {}
    folds = (prior.get("fit_a_score_b") or {}, prior.get("fit_b_score_a") or {})
    return all(bool(f.get("beats_chance")) for f in folds)


# ---------------------------------------------------------------------------- report
def build_report(db_path: Path, mode: str, limit: int, levels: Sequence[int],
                 gold_frame_min: int, even_band: float) -> Dict[str, object]:
    pairs = collect_pairs(db_path, limit, gold_frame_min)
    verdict_fn = make_verdict_fn(_load_table(mode))
    verdict = score_verdict(pairs, verdict_fn, levels, even_band)
    control = learnability_control(pairs)
    learnable = label_is_learnable(control)
    pooled = verdict.get("pooled_levels") or {}
    mi_fraction = pooled.get("mi_fraction_of_label_entropy")

    if learnable and mi_fraction is not None and mi_fraction < 0.01:
        finding = "verdict_uninformative"
        reading = (
            "The label is learnable held-out and the verdict's mutual information "
            "with it is under 1 pct of the label entropy. The VERDICT is the dead "
            "half, not the harness. This is the ADR-013 retirement finding."
        )
    elif not learnable:
        finding = "label_not_learnable"
        reading = (
            "No held-out baseline beat chance on this label, so a ~0.50 verdict "
            "agreement indicts the GROUND-TRUTH PROXY and not the verdict. Do not "
            "retire anything on this run - fix the label first."
        )
    else:
        finding = "verdict_carries_signal"
        reading = (
            "The verdict carries measurable information against a learnable label. "
            "This CONTRADICTS the 2026-08-06 measurement behind ADR-013; re-open "
            "the ADR with this artifact attached rather than flipping on it."
        )

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "probe": "hz_a_laning_verdict_information",
        "adr": "ADR-013",
        "db": str(db_path),
        "mode": mode,
        "limit": limit,
        "levels": list(levels),
        "gold_frame_min": gold_frame_min,
        "even_band": even_band,
        "pairs_collected": len(pairs),
        "matches_collected": len({p.match_id for p in pairs}),
        "verdict_vs_gold": verdict,
        "label_learnability_control": control,
        "label_is_learnable": learnable,
        "finding": finding,
        "reading": reading,
    }


def _fmt(x: object, nd: int = 4) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return "n/a"


def print_summary(report: Dict[str, object]) -> None:
    print("")
    print("=== HZ-A laning-verdict INFORMATION probe (ADR-013 evidence) ===")
    print(f"db={report['db']}  mode={report['mode']}  "
          f"pairs={report['pairs_collected']} over {report['matches_collected']} matches")
    print("")
    print("  -- VERDICT vs GOLD: mutual information --")
    print(f"  {'slice':16s} {'n':>6s} {'agree':>8s} {'MI bits':>10s} {'MI corr':>11s} "
          f"{'MI/H':>8s} {'phi':>8s} {'chi2':>7s}")
    print("  (MI corr = Miller-Madow bias-corrected; NEGATIVE = below the noise floor)")
    print("  " + "-" * 80)
    blocks = [(f"level {lvl}", blk) for lvl, blk in
              sorted((report["verdict_vs_gold"]["per_level"]).items())]
    blocks.append(("pooled", report["verdict_vs_gold"]["pooled_levels"]))
    blocks.append(("pooled no-JUNGLE", report["verdict_vs_gold"]["pooled_excluding_jungle"]))
    blocks += [(f"role {k}", v) for k, v in
               (report["verdict_vs_gold"]["per_role"]).items()]
    for tag, blk in blocks:
        if not blk.get("n"):
            continue
        frac = blk.get("mi_fraction_of_label_entropy")
        print(f"  {tag:16s} {blk['n']:6d} {_fmt(blk['agreement']):>8s} "
              f"{_fmt(blk['mutual_information_bits'], 6):>10s} "
              f"{_fmt(blk['mutual_information_bits_miller_madow'], 6):>11s} "
              f"{(_fmt(frac * 100, 3) + '%') if frac is not None else 'n/a':>8s} "
              f"{_fmt(blk['phi']):>8s} {_fmt(blk['chi2_yates'], 2):>7s}")
    print("")
    print("  -- CONTROL: is the LABEL learnable at all? --")
    ctl = report["label_learnability_control"]
    for tag, key in (("fit A -> score B", "fit_a_score_b"),
                     ("fit B -> score A", "fit_b_score_a"),
                     ("in-sample ceiling", "in_sample_ceiling")):
        blk = ctl["champion_gold_prior"][key]
        print(f"    champ gold prior {tag:18s} n={blk['n']:5d} "
              f"agree={_fmt(blk['agreement'])} "
              f"[{_fmt(blk['wilson_95_lo'])}, {_fmt(blk['wilson_95_hi'])}]"
              + ("  BEATS CHANCE" if blk.get("beats_chance") else ""))
    duel = ctl["duel_predicts_gold"]
    print(f"    solo-kill duel -> gold winner       n={duel['n']:5d} "
          f"agree={_fmt(duel['agreement'])} "
          f"[{_fmt(duel['wilson_95_lo'])}, {_fmt(duel['wilson_95_hi'])}]")
    print("")
    print(f"  finding: {report['finding']}")
    print(f"  {report['reading']}")
    print("")


def _write_report(report: Dict[str, object], out_path: Path) -> None:
    """Atomic JSON write (ASCII-only) - overlays and readers poll mid-write."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def _parse_levels(raw: str) -> List[int]:
    out: List[int] = []
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out or list(_DEFAULT_LEVELS)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Mutual-information + label-learnability probe behind ADR-013."
    )
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="Path to rewind_history.db")
    ap.add_argument("--mode", default=_ONLY_MODE,
                    help="Table mode. ONLY 'sr' is accepted - see the module "
                         "docstring; a non-sr run would score that table against "
                         "the SR corpus and return a plausible wrong number.")
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                    help="Max SR matches to walk (0 = all). Default %(default)s.")
    ap.add_argument("--levels", default=",".join(str(x) for x in _DEFAULT_LEVELS),
                    help="Comma-separated replay levels. Default %(default)s.")
    ap.add_argument("--gold-frame", type=int, default=_DEFAULT_GOLD_FRAME_MIN,
                    help="Minute of the timeline frame used as lane-gold truth.")
    ap.add_argument("--even-band", type=float, default=_EVEN_BAND,
                    help="|net_swing| below this is excluded as even.")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON path.")
    ap.add_argument("--json", action="store_true", help="Print the JSON, not a summary.")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    mode = str(args.mode or "").strip().lower()
    if mode != _ONLY_MODE:
        print(f"REFUSED: --mode {mode!r}. This probe only accepts {_ONLY_MODE!r}.",
              file=sys.stderr)
        print("The replay corpus is SR-only by construction "
              "(select_sr_match_ids is WHERE game_mode = 'CLASSIC'), and Riot emits "
              "no team_position for ARAM or Arena, so there are zero lane pairs to "
              "score in either. A non-sr run swaps the TABLE and not the CORPUS and "
              "returns a plausible wrong number. See ADR-013.", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"REFUSED: no replay DB at {db_path}", file=sys.stderr)
        return 2

    report = build_report(db_path, mode, args.limit, _parse_levels(args.levels),
                          args.gold_frame, args.even_band)
    out_path = Path(args.out)
    _write_report(report, out_path)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    else:
        print(f"probe artifact written: {out_path}")
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
