"""Sweep RC's four published quantities over EVERY defensible aggregation rule.

Read-only. Third script in this directory, and it deliberately IMPORTS
`tally.parse_rows` so that the fine grain, the coarse grain and every
aggregation rule come out of ONE extraction. `band_recompute.py` established
that discipline; this script follows it and does not duplicate or modify it.

WHY THIS EXISTS
---------------
RC published four quantities as BANDS across two event-individuation
conventions (fine = one row per claim, N=198; coarse = one event per ledger
entry, N=40). RC then reported to the fleet that the contract defines the
EVENT but never says how sub-values AGGREGATE when a coarser reader collapses
rows to an entry - and measured a factor of three on BORN-WRONG : DECAYED from
the rule alone.

The contract owner measured that same gap on their own corpus and found it
LARGER than the fatal beside it, and - decisively - found that some rules put
the COARSE value BELOW the FINE value. If that happens, the coarse end is not
an upper bound, the interval is not monotonic, and what was published as a
BAND is not a band. This script asks that question of RC's own corpus.

THE RULES SWEPT, and what each one means for a per-entry value
--------------------------------------------------------------
* ANY-OF     - the entry carries the property if ANY of its rows does.
* ALL-OF     - the entry carries it only if EVERY row does.
* MAJORITY   - strictly more than half of the entry's rows carry it.
* PLURALITY  - the modal value among the entry's rows wins. On a BINARY
               predicate this differs from MAJORITY only on an exact tie, so
               the two tie policies are reported separately and the tie count
               is printed. MAJORITY is identical to PLURALITY-ties-to-FALSE on
               a binary predicate; that identity is a result, not a shortcut.
* PRECEDENCE - resolve the entry to ONE value by a total order, then read the
               quantity off that value. This is only DEFINED where the
               contract supplies the order. It does for `prevention`
               (clause 2). It does NOT for `origin_time` or `fix_chain`.

Run from the repo root with the project Python (path in CLAUDE.md, Paths):

  <project-python> docs/_rescore/aggregation_sweep.py
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tally  # noqa: E402  (same-directory sibling; parser reuse is the point)

GATE_FAMILY = tally.GATE_FAMILY
CHAIN_KIND_IN_RATIO = tally.CHAIN_KIND_IN_RATIO

# PIN v1.3 clause 2: total precedence order over `prevention`, FIRST match wins.
# This is the ONLY precedence order the contract actually supplies.
V13_PREVENTION_PRECEDENCE = [
    "GATE-FIRED-CAUGHT",
    "GATE-FIRED-IGNORED",
    "GATE-EXISTING",
    "PROXY-MEASURE",
    "CONTRACT-MISFIRED",
    "GATE-ABSENT",
    "CONTRACT",
    "ADVERSARY",
]

# The fine-grain figures this run must reproduce before ANY sweep is printed.
# Source: docs/_rescore/tally_report.md, re-verified by band_recompute.py.
# A sweep whose fine anchor cannot be reproduced is measuring the parser.
FINE_EXPECTED = {
    "gate_or_contract_pct": 85.4,
    "inherited_pct": 48.5,
    "born_wrong_to_decayed": 2.62,
    "fix_of_a_fix_pct": 12.1,
}

# What RC actually published, so the withdrawal can be stated against it.
RC_PUBLISHED = {
    "gate_or_contract": "85.4 to 95.0 pct",
    "inherited": "48.5 to 85.0 pct",
    "born_wrong_to_decayed": "1.73 to 2.62 : 1",
    "fix_of_a_fix": "12.1 to 47.5 pct",
}

RULES = ["ANY-OF", "ALL-OF", "MAJORITY", "PLURALITY", "PRECEDENCE"]


def pct(n, d):
    return None if not d else round(100.0 * n / d, 1)


def ratio(a, b):
    return None if not b else round(float(a) / float(b), 2)


def load_rows():
    problems = []
    rows = []
    for n in (1, 2, 3, 4):
        chunk = f"chunk{n:d}"
        path = HERE / f"{chunk}_rows.md"
        if not path.exists():
            raise SystemExit(f"MISSING ROW FILE: {path}")
        rows.extend(tally.parse_rows(chunk, path, problems))
    blocking = [p for p in problems if p.blocking]
    return rows, problems, blocking


def group_by_entry(rows):
    by_entry = defaultdict(list)
    for r in rows:
        by_entry[r["entry"]].append(r)
    return by_entry


# --------------------------------------------------------------------------
# Per-row predicates for the three PERCENTAGE quantities.
# --------------------------------------------------------------------------


def is_gate_or_contract(row):
    return row["prevention"] in GATE_FAMILY or row["prevention"] == "CONTRACT"


def is_inherited(row):
    return row["origin_family"] == "INHERITED"


def is_fix_of_a_fix(row):
    """Does this row count in the fix-of-a-fix numerator, per pin section 6."""
    fc = row.get("fix_chain") or 0
    if fc < 1:
        return False
    ck = row.get("chain_kind")
    return ck is None or ck in CHAIN_KIND_IN_RATIO


# --------------------------------------------------------------------------
# Boolean aggregation. Returns True / False / None, where None means the rule
# is UNDEFINED for this quantity (and saying so is a result).
# --------------------------------------------------------------------------


def agg_bool(rule, flags):
    n = len(flags)
    t = sum(1 for f in flags if f)
    if rule == "ANY-OF":
        return t >= 1
    if rule == "ALL-OF":
        return t == n
    if rule == "MAJORITY":
        return t * 2 > n
    if rule == "PLURALITY":
        # modal value; exact ties resolved toward TRUE. The tie-to-FALSE
        # variant is exactly MAJORITY on a binary predicate and is reported
        # beside it rather than duplicated as a sixth column.
        return t * 2 >= n
    raise ValueError(rule)


def tie_count(flag_lists):
    return sum(1 for fl in flag_lists if len(fl) % 2 == 0 and sum(1 for f in fl if f) * 2 == len(fl))


def prevention_precedence_value(entry_rows):
    vals = {r["prevention"] for r in entry_rows}
    for v in V13_PREVENTION_PRECEDENCE:
        if v in vals:
            return v
    return None


def sweep_percentage(by_entry, predicate, precedence_note):
    """Sweep one boolean quantity. Returns {rule: pct or None} plus detail."""
    entries = sorted(by_entry)
    n = len(entries)
    flag_lists = [[predicate(r) for r in by_entry[e]] for e in entries]
    out = {}
    counts = {}
    for rule in ("ANY-OF", "ALL-OF", "MAJORITY", "PLURALITY"):
        c = sum(1 for fl in flag_lists if agg_bool(rule, fl))
        counts[rule] = c
        out[rule] = pct(c, n)
    if precedence_note == "prevention":
        c = 0
        for e in entries:
            v = prevention_precedence_value(by_entry[e])
            if v in GATE_FAMILY or v == "CONTRACT":
                c += 1
        counts["PRECEDENCE"] = c
        out["PRECEDENCE"] = pct(c, n)
    else:
        counts["PRECEDENCE"] = None
        out["PRECEDENCE"] = None
    return out, counts, n, tie_count(flag_lists)


# --------------------------------------------------------------------------
# The RATIO. A ratio is not a boolean, so several rules mean something
# different here and one of them is genuinely undefined.
# --------------------------------------------------------------------------


def sweep_ratio(by_entry):
    """BORN-WRONG : DECAYED at entry grain, under every rule that is defined.

    ANY-OF      - numerator = entries with >=1 BORN-WRONG row, denominator =
                  entries with >=1 DECAYED row. The two sets OVERLAP, so an
                  entry can count on both sides. That is the honest reading of
                  any-of for a ratio and it is what RC published.
    ALL-OF      - entries ALL of whose rows are BORN-WRONG, over entries ALL of
                  whose rows are DECAYED. Defined only when the denominator is
                  non-zero; on a corpus where most entries mix sub-values this
                  degenerates, and a degenerate denominator makes the rule
                  UNDEFINED rather than large.
    MAJORITY    - strictly more than half the entry's rows carry the sub-value.
    PLURALITY   - the modal sub-value among the entry's INHERITED rows wins;
                  exact ties are counted in NEITHER side and reported. A
                  variant taken over ALL rows (FRESH as its own label) is
                  computed beside it because the scoping choice is itself a
                  free parameter.
    PRECEDENCE  - BORN-WRONG outranks DECAYED within an entry. NOTE: the
                  contract supplies NO precedence order over `origin_time`.
                  This order is an AUTHOR'S CHOICE, not a contract clause, and
                  it is the more damning of the two directions.
    """
    entries = sorted(by_entry)
    res = {}

    bw_any = sum(1 for e in entries if any(r["origin_sub"] == "BORN-WRONG" for r in by_entry[e]))
    dec_any = sum(1 for e in entries if any(r["origin_sub"] == "DECAYED" for r in by_entry[e]))
    res["ANY-OF"] = (bw_any, dec_any, ratio(bw_any, dec_any))

    bw_all = sum(1 for e in entries if all(r["origin_sub"] == "BORN-WRONG" for r in by_entry[e]))
    dec_all = sum(1 for e in entries if all(r["origin_sub"] == "DECAYED" for r in by_entry[e]))
    res["ALL-OF"] = (bw_all, dec_all, ratio(bw_all, dec_all))

    bw_maj = 0
    dec_maj = 0
    for e in entries:
        rs = by_entry[e]
        if sum(1 for r in rs if r["origin_sub"] == "BORN-WRONG") * 2 > len(rs):
            bw_maj += 1
        if sum(1 for r in rs if r["origin_sub"] == "DECAYED") * 2 > len(rs):
            dec_maj += 1
    res["MAJORITY"] = (bw_maj, dec_maj, ratio(bw_maj, dec_maj))

    bw_plu = 0
    dec_plu = 0
    plu_ties = 0
    for e in entries:
        subs = [r["origin_sub"] for r in by_entry[e] if r["origin_family"] == "INHERITED"]
        if not subs:
            continue
        c = Counter(subs)
        top = max(c.values())
        winners = sorted(k for k, v in c.items() if v == top)
        if len(winners) > 1:
            plu_ties += 1
            continue
        if winners[0] == "BORN-WRONG":
            bw_plu += 1
        elif winners[0] == "DECAYED":
            dec_plu += 1
    res["PLURALITY"] = (bw_plu, dec_plu, ratio(bw_plu, dec_plu))

    bw_plu_all = 0
    dec_plu_all = 0
    plu_all_ties = 0
    for e in entries:
        labels = [r["origin_sub"] if r["origin_family"] == "INHERITED" else "FRESH" for r in by_entry[e]]
        c = Counter(labels)
        top = max(c.values())
        winners = sorted(k for k, v in c.items() if v == top)
        if len(winners) > 1:
            plu_all_ties += 1
            continue
        if winners[0] == "BORN-WRONG":
            bw_plu_all += 1
        elif winners[0] == "DECAYED":
            dec_plu_all += 1
    res["PLURALITY-ALLROWS"] = (bw_plu_all, dec_plu_all, ratio(bw_plu_all, dec_plu_all))

    bw_prec = 0
    dec_prec = 0
    for e in entries:
        subs = {r["origin_sub"] for r in by_entry[e]}
        if "BORN-WRONG" in subs:
            bw_prec += 1
        elif "DECAYED" in subs:
            dec_prec += 1
    res["PRECEDENCE"] = (bw_prec, dec_prec, ratio(bw_prec, dec_prec))

    return res, plu_ties, plu_all_ties


# --------------------------------------------------------------------------
# Monotonicity. The decisive question.
# --------------------------------------------------------------------------


def monotonic_verdict(fine_value, coarse_values):
    """Is the published interval a BAND?

    RC published fine .. coarse(any-of) and read the coarse end as the far end.
    That reading survives only if EVERY defensible coarse rule lands on the
    same side of the fine value. If any rule crosses it, the interval is not
    monotonic in the individuation parameter and it is not a band.
    """
    defined = [v for v in coarse_values.values() if v is not None]
    if not defined:
        return "UNDEFINED", None, None, None
    lo = min(defined)
    hi = max(defined)
    spread = round(hi - lo, 2)
    above = [v for v in defined if v > fine_value]
    below = [v for v in defined if v < fine_value]
    if above and below:
        verdict = "NOT MONOTONIC - coarse rules straddle the fine value"
    elif below:
        verdict = "NOT MONOTONIC vs PUBLICATION - every coarse rule sits BELOW fine"
    else:
        verdict = "monotonic - every coarse rule sits at or above fine"
    return verdict, lo, hi, spread


def fmt(v, suffix=""):
    return "n/a" if v is None else f"{v}{suffix}"


def main():
    rows, problems, blocking = load_rows()
    w = print

    w("=" * 78)
    w("PARSE")
    w("=" * 78)
    w(f"rows parsed: {len(rows):d}")
    w(f"problems: {len(problems):d} total, {len(blocking):d} BLOCKING")
    for p in blocking:
        w(f"  BLOCKING {p}")
    if blocking:
        raise SystemExit("blocking parse problems - sweep not printed")

    by_entry = group_by_entry(rows)
    n_fine = len(rows)
    n_coarse = len(by_entry)

    # ---- fine anchor, verified before anything else is printed -------------
    fine = {
        "gate_or_contract_pct": pct(sum(1 for r in rows if is_gate_or_contract(r)), n_fine),
        "inherited_pct": pct(sum(1 for r in rows if is_inherited(r)), n_fine),
        "born_wrong_to_decayed": ratio(
            sum(1 for r in rows if r["origin_sub"] == "BORN-WRONG"),
            sum(1 for r in rows if r["origin_sub"] == "DECAYED"),
        ),
        "fix_of_a_fix_pct": pct(sum(1 for r in rows if is_fix_of_a_fix(r)), n_fine),
    }
    w("")
    w("=" * 78)
    w("FINE ANCHOR verification (must reproduce tally_report.md)")
    w("=" * 78)
    ok = True
    for k in sorted(FINE_EXPECTED):
        got = fine[k]
        match = got is not None and abs(float(got) - float(FINE_EXPECTED[k])) < 0.051
        ok = ok and match
        w("  {!s:<26} expected {!s:<8} got {!s:<8} {}".format(
            k, FINE_EXPECTED[k], got, "MATCH" if match else "MISMATCH"))
    if not ok:
        raise SystemExit("fine anchor does not reproduce - sweep not printed")
    w(f"  fine N = {n_fine:d} rows      coarse N = {n_coarse:d} entries")

    # ---- the three percentage quantities -----------------------------------
    quantities = [
        ("gate-or-contract", is_gate_or_contract, "prevention", fine["gate_or_contract_pct"]),
        ("inherited", is_inherited, None, fine["inherited_pct"]),
        ("fix-of-a-fix", is_fix_of_a_fix, None, fine["fix_of_a_fix_pct"]),
    ]

    w("")
    w("=" * 78)
    w("PART 1 - COARSE VALUE UNDER EVERY DEFENSIBLE AGGREGATION RULE")
    w("=" * 78)
    w("")
    w("{:<18} {:>6} {:>9} {:>9} {:>9} {:>10} {:>11}".format(
        "quantity", "fine", "ANY-OF", "ALL-OF", "MAJORITY", "PLURALITY", "PRECEDENCE"))

    summary = {}
    for name, predicate, prec_note, fine_val in quantities:
        vals, counts, n, ties = sweep_percentage(by_entry, predicate, prec_note)
        summary[name] = (fine_val, vals, counts, ties)
        w("{:<18} {:>6} {:>9} {:>9} {:>9} {:>10} {:>11}".format(
            name, fine_val,
            fmt(vals["ANY-OF"]), fmt(vals["ALL-OF"]), fmt(vals["MAJORITY"]),
            fmt(vals["PLURALITY"]), fmt(vals["PRECEDENCE"])))

    w("")
    w("  all figures pct of N. counts, and the tie population behind PLURALITY:")
    for name, _p, _pn, _f in quantities:
        _fv, vals, counts, ties = summary[name]
        w("    {:<18} any {:>2}/{:d}  all {:>2}  maj {:>2}  plu {:>2}  prec {!s:>4}   even-split entries: {:d}".format(
            name, counts["ANY-OF"], n_coarse, counts["ALL-OF"], counts["MAJORITY"],
            counts["PLURALITY"], counts["PRECEDENCE"], ties))
    w("")
    w("  PRECEDENCE is n/a for `inherited` and `fix-of-a-fix` BY CONSTRUCTION:")
    w("    the contract supplies a total precedence order for `prevention` only")
    w("    (clause 2). It defines none over `origin_time` or `fix_chain`. And on")
    w("    a BINARY field any invented order that ranks the positive value first")
    w("    IS any-of, so inventing one would add no information, only a name.")

    # ---- the ratio ---------------------------------------------------------
    rres, plu_ties, plu_all_ties = sweep_ratio(by_entry)
    w("")
    w("=" * 78)
    w("BORN-WRONG : DECAYED at entry grain, by rule")
    w("=" * 78)
    w("  fine grain                      {} : 1".format(fine["born_wrong_to_decayed"]))
    for rule in ("ANY-OF", "ALL-OF", "MAJORITY", "PLURALITY", "PLURALITY-ALLROWS", "PRECEDENCE"):
        bw, dec, rat = rres[rule]
        note = ""
        if rat is None:
            note = f"   UNDEFINED - denominator is {dec:d}"
        w(f"  {rule:<18} {bw:>3} : {dec:<3}  = {rat!s:>6} : 1{note}")
    w(f"  PLURALITY ties (no single modal sub-value), inherited-scoped: {plu_ties:d}")
    w(f"  PLURALITY ties, all-rows-scoped: {plu_all_ties:d}")
    w("")
    w("  ALL-OF on a RATIO is where 'defensible' runs out. An entry every one of")
    w("  whose rows is DECAYED is a rare object on this corpus, and when that")
    w("  count reaches zero the ratio is not large, it is UNDEFINED. Reporting")
    w("  that is the result; silently dropping the rule would have hidden it.")
    w("")
    w("  PRECEDENCE here is NOT a contract rule. Clause 2 orders `prevention`.")
    w("  Nothing orders `origin_time`. 'BORN-WRONG outranks DECAYED' is an")
    w("  author's choice, and it is the choice that maximises the headline.")

    # ---- monotonicity ------------------------------------------------------
    w("")
    w("=" * 78)
    w("IS THE INTERVAL MONOTONIC?")
    w("=" * 78)
    mono = {}
    for name, _p, _pn, fine_val in quantities:
        _fv, vals, _c, _t = summary[name]
        verdict, lo, hi, spread = monotonic_verdict(fine_val, vals)
        mono[name] = (verdict, lo, hi, spread)
        w("")
        w(f"  {name}")
        w(f"    fine {fine_val}   coarse rules span {fmt(lo)} to {fmt(hi)}   SPREAD {fmt(spread)} points")
        w("    published: {}".format(RC_PUBLISHED[name.replace("-", "_")]))
        w(f"    {verdict}")
        below = sorted(k for k, v in vals.items() if v is not None and v < fine_val)
        if below:
            w("    rules landing BELOW the fine value: {}".format(", ".join(below)))

    ratio_vals = {k: v[2] for k, v in rres.items() if k != "PLURALITY-ALLROWS"}
    rverdict, rlo, rhi, rspread = monotonic_verdict(fine["born_wrong_to_decayed"], ratio_vals)
    mono["born-wrong:decayed"] = (rverdict, rlo, rhi, rspread)
    w("")
    w("  BORN-WRONG:DECAYED")
    w("    fine {}   coarse rules span {} to {}   SPREAD {} ratio units".format(
        fine["born_wrong_to_decayed"], fmt(rlo), fmt(rhi), fmt(rspread)))
    w("    published: {}".format(RC_PUBLISHED["born_wrong_to_decayed"]))
    w(f"    {rverdict}")
    rbelow = sorted(k for k, v in ratio_vals.items() if v is not None and v < fine["born_wrong_to_decayed"])
    if rbelow:
        w("    rules landing BELOW the fine value: {}".format(", ".join(rbelow)))

    largest = None
    for name, _p, _pn, _f in quantities:
        sp = mono[name][3]
        if sp is not None and (largest is None or sp > largest[1]):
            largest = (name, sp)
    w("")
    w(f"  LARGEST SPREAD among the percentage quantities: {largest[0]} at {largest[1]} points")
    w(f"  (the ratio's spread is {fmt(rspread)} ratio units and is not commensurable in points)")

    # ---- part 2 ------------------------------------------------------------
    w("")
    w("=" * 78)
    w("PART 2 - AGGREGATION SENSITIVITY vs INDIVIDUATION SENSITIVITY")
    w("=" * 78)
    w("")
    w("  individuation term = |coarse(ANY-OF) - fine|, the pairing RC PUBLISHED")
    w("  aggregation  term = max(coarse rule) - min(coarse rule) at fixed grain")
    w("")
    w("  {:<18} {:>14} {:>14}   dominant".format("quantity", "individuation", "aggregation"))
    agg_wins = 0
    ind_wins = 0
    for name, _p, _pn, fine_val in quantities:
        _fv, vals, _c, _t = summary[name]
        ind = round(abs(vals["ANY-OF"] - fine_val), 1)
        agg = mono[name][3]
        dom = "AGGREGATION" if agg > ind else ("INDIVIDUATION" if ind > agg else "TIED")
        if dom == "AGGREGATION":
            agg_wins += 1
        elif dom == "INDIVIDUATION":
            ind_wins += 1
        w(f"  {name:<18} {ind:>14} {agg:>14}   {dom}")
    rind = round(abs(rres["ANY-OF"][2] - fine["born_wrong_to_decayed"]), 2)
    rdom = "AGGREGATION" if rspread > rind else ("INDIVIDUATION" if rind > rspread else "TIED")
    if rdom == "AGGREGATION":
        agg_wins += 1
    elif rdom == "INDIVIDUATION":
        ind_wins += 1
    w("  {:<18} {:>14} {:>14}   {}  (ratio units)".format(
        "born-wrong:decayed", rind, rspread, rdom))
    w("")
    w(f"  quantities where AGGREGATION dominates: {agg_wins:d} of 4")
    w(f"  quantities where INDIVIDUATION dominates: {ind_wins:d} of 4")

    w("")
    w("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
