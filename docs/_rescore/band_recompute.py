"""Recompute RC's re-score headlines under the COARSE individuation convention.

Read-only. Companion to `tally.py`, which produced the FINE end (one row per
claim, N=198). This script produces the COARSE end (one event per ledger entry,
N = distinct entries carrying at least one row), exactly as LW re-derived its
own corpus when pricing FATAL-1, and prints both ends as a BAND.

It deliberately IMPORTS `tally.parse_rows` rather than re-implementing the
parser. Two ends of a band must come from the same extraction or the band is
measuring the parser, not the convention.

It also measures, where the rows allow it, how many rows would CHANGE under
PIN v1.3's five clauses, and prints the deterministic conformance sample that
`band_recompute.md` hand-grades.

Run from the repo root with the project Python (path in CLAUDE.md, Paths):

  <project-python> docs/_rescore/band_recompute.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tally  # noqa: E402  (same-directory sibling, parser reuse is the point)

GATE_FAMILY = tally.GATE_FAMILY
CHAIN_KIND_IN_RATIO = tally.CHAIN_KIND_IN_RATIO

# The fine-end figures this run must reproduce before any band is printed.
# Source: docs/_rescore/tally_report.md sections 3, 4 and 2. If any of these
# fails, the band is not printed - a band whose fine end cannot be reproduced
# is not a band.
FINE_EXPECTED = {
    "gate_or_contract_pct": 85.4,
    "inherited_pct": 48.5,
    "born_wrong_to_decayed": 2.62,
    "fix_of_a_fix_pct": 12.1,
}

# PIN v1.3 clause 2: total precedence order, FIRST match wins.
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


def pct(n, d):
    return 0.0 if not d else round(100.0 * n / d, 1)


def ratio(a, b):
    return None if not b else round(float(a) / float(b), 2)


def load_rows():
    problems = []
    rows = []
    for n in (1, 2, 3, 4):
        chunk = f"chunk{n}"
        path = HERE / (f"{chunk}_rows.md")
        if not path.exists():
            raise SystemExit(f"MISSING ROW FILE: {path}")
        rows.extend(tally.parse_rows(chunk, path, problems))
    blocking = [p for p in problems if p.blocking]
    return rows, problems, blocking


def in_ratio(row):
    """Does this row count in the fix-of-a-fix numerator, per pin section 6."""
    fc = row.get("fix_chain") or 0
    if fc < 1:
        return False
    ck = row.get("chain_kind")
    # SAME-ARTIFACT is excluded; a missing kind on a >=1 row would have been
    # named as a problem by the parser, and none exists on this corpus.
    return ck is None or ck in CHAIN_KIND_IN_RATIO


def fine_end(rows):
    n = len(rows)
    gate_or_contract = sum(
        1 for r in rows if r["prevention"] in GATE_FAMILY or r["prevention"] == "CONTRACT"
    )
    inherited = sum(1 for r in rows if r["origin_family"] == "INHERITED")
    born = sum(1 for r in rows if r["origin_sub"] == "BORN-WRONG")
    decayed = sum(1 for r in rows if r["origin_sub"] == "DECAYED")
    fof = sum(1 for r in rows if in_ratio(r))
    return {
        "n": n,
        "gate_or_contract": gate_or_contract,
        "gate_or_contract_pct": pct(gate_or_contract, n),
        "inherited": inherited,
        "inherited_pct": pct(inherited, n),
        "born_wrong": born,
        "decayed": decayed,
        "born_wrong_to_decayed": ratio(born, decayed),
        "fix_of_a_fix": fof,
        "fix_of_a_fix_pct": pct(fof, n),
    }


def coarse_end(rows):
    """One event per ledger entry.

    AGGREGATION RULE, stated because it is itself a finding:

    * gate-or-contract, inherited, fix-of-a-fix: ANY-OF. The entry counts for
      the bucket if ANY of its rows carries a qualifying value. This is the
      only rule that reproduces LW's direction of movement, and it is the
      rule LW's own prose describes ("collapsing rows makes 'did ANY link
      need a further fix' monotonically more likely to be true").
    * BORN-WRONG and DECAYED: ANY-OF each, INDEPENDENTLY, so one entry can
      count toward both. A precedence variant is computed beside it, because
      the choice moves the ratio and the reader is entitled to both.
    * prevention as a per-entry DISTRIBUTION: reported BOTH ways - ANY-OF
      (an entry appears in every bucket present among its rows, so the
      columns sum above N) and v1.3 clause 2 FIRST-MATCH precedence (exactly
      one bucket per entry). There is no neutral choice here.
    """
    by_entry = defaultdict(list)
    for r in rows:
        by_entry[r["entry"]].append(r)
    entries = sorted(by_entry)
    n = len(entries)

    goc = sum(
        1
        for e in entries
        if any(
            r["prevention"] in GATE_FAMILY or r["prevention"] == "CONTRACT"
            for r in by_entry[e]
        )
    )
    inh = sum(1 for e in entries if any(r["origin_family"] == "INHERITED" for r in by_entry[e]))
    born_any = sum(
        1 for e in entries if any(r["origin_sub"] == "BORN-WRONG" for r in by_entry[e])
    )
    dec_any = sum(1 for e in entries if any(r["origin_sub"] == "DECAYED" for r in by_entry[e]))
    fof = sum(1 for e in entries if any(in_ratio(r) for r in by_entry[e]))

    # Precedence variant for the inherited split: BORN-WRONG outranks DECAYED
    # when both appear under one entry.
    born_prec = 0
    dec_prec = 0
    for e in entries:
        subs = {r["origin_sub"] for r in by_entry[e]}
        if "BORN-WRONG" in subs:
            born_prec += 1
        elif "DECAYED" in subs:
            dec_prec += 1

    prev_anyof = Counter()
    prev_prec = Counter()
    for e in entries:
        vals = {r["prevention"] for r in by_entry[e]}
        for v in vals:
            prev_anyof[v] += 1
        for v in V13_PREVENTION_PRECEDENCE:
            if v in vals:
                prev_prec[v] += 1
                break

    return {
        "n": n,
        "entries": entries,
        "rows_per_entry": {e: len(by_entry[e]) for e in entries},
        "gate_or_contract": goc,
        "gate_or_contract_pct": pct(goc, n),
        "inherited": inh,
        "inherited_pct": pct(inh, n),
        "born_wrong_any": born_any,
        "decayed_any": dec_any,
        "born_wrong_to_decayed_any": ratio(born_any, dec_any),
        "born_wrong_prec": born_prec,
        "decayed_prec": dec_prec,
        "born_wrong_to_decayed_prec": ratio(born_prec, dec_prec),
        "fix_of_a_fix": fof,
        "fix_of_a_fix_pct": pct(fof, n),
        "prev_anyof": prev_anyof,
        "prev_prec": prev_prec,
    }


def conformance_sample(rows, per_chunk=6):
    """Deterministic, stated-before-reading sample for the v1.3 clause-1 check.

    Same spreading rule as the adjudication pass, at a different stride so the
    two samples are not the same rows: index(k) = round((k-1)*(N-1)/(K-1)) + 1
    over each chunk's rows in file order, K = per_chunk.
    """
    out = []
    by_chunk = defaultdict(list)
    for r in rows:
        by_chunk[r["chunk"]].append(r)
    for chunk in ("chunk1", "chunk2", "chunk3", "chunk4"):
        rs = by_chunk[chunk]
        n = len(rs)
        for k in range(1, per_chunk + 1):
            idx = round((k - 1) * (n - 1) / (per_chunk - 1)) + 1
            out.append(rs[idx - 1])
    return out


AGENT_WORDS = re.compile(
    r"\b(subagent|sub-agent|verifier|slice agent|slice's|agent's report|"
    r"parallel agent|parallel agents|adjudicator|auditor|scorer)\b",
    re.I,
)


def v13_clause_deltas(rows):
    """How many rows would CHANGE under each v1.3 clause, where measurable."""
    out = {}

    # CLAUSE 2 - prevention precedence. Mechanically bounded, not decidable:
    # the rows record the value the scorer chose, not the full fact pattern,
    # so only an UPPER BOUND on movement is derivable from them.
    out["c2_proxy_measure_rows"] = sum(1 for r in rows if r["prevention"] == "PROXY-MEASURE")
    out["c2_gate_existing_rows"] = sum(1 for r in rows if r["prevention"] == "GATE-EXISTING")
    out["c2_gate_existing_vacuous"] = sum(
        1
        for r in rows
        if r["prevention"] == "GATE-EXISTING"
        and (r.get("prevention_why") or "").upper().startswith("VACUOUS")
    )
    # Rows whose refuter names a standing check that fired, but which are NOT
    # scored GATE-FIRED-CAUGHT. Under clause 2 these outrank their filed value.
    gate_fired_words = re.compile(
        r"\b(pre-commit gate|precommit gate|the gate|standing gate|adversarial gate|"
        r"pre-push|hook|CI run|the verifier|verifier pass|verifier gate)\b",
        re.I,
    )
    cands = [
        r
        for r in rows
        if r["prevention"] != "GATE-FIRED-CAUGHT"
        and gate_fired_words.search(r["raw"].get("refuter", ""))
    ]
    out["c2_gate_fired_candidates"] = len(cands)
    out["c2_gate_fired_candidate_ids"] = [r["id"] for r in cands]

    # CLAUSE 3 - chain_kind becomes a per-link LIST. A row CHANGES SHAPE iff it
    # has more than one link but a scalar kind. Ratio MEMBERSHIP changes for
    # nobody, because the corpus carries zero SAME-ARTIFACT.
    multi = [r for r in rows if (r.get("fix_chain") or 0) >= 2]
    out["c3_multi_link_rows"] = len(multi)
    out["c3_multi_link_ids"] = [(r["id"], r["fix_chain"], r["chain_kind"]) for r in multi]
    out["c3_same_artifact_rows"] = sum(1 for r in rows if r.get("chain_kind") == "SAME-ARTIFACT")

    # CLAUSE 4 - correctness filter on a link. The rows carry NO per-link
    # correctness field, so this is UNEVALUABLE from the rows. Only the
    # population at risk is derivable.
    out["c4_rows_with_links"] = sum(1 for r in rows if (r.get("fix_chain") or 0) >= 1)
    out["c4_total_links"] = sum(r.get("fix_chain") or 0 for r in rows)

    # CLAUSE 5 - an in-session agent report is FRESH unless durably written
    # first. A row CHANGES only if it is INHERITED and its inherited source is
    # an in-session agent report. Derivable as an upper bound by text match.
    inh_agent = [
        r
        for r in rows
        if r["origin_family"] == "INHERITED"
        and AGENT_WORDS.search(r["raw"].get("claim", "") + " " + r["raw"].get("refuter", ""))
    ]
    out["c5_inherited_agent_mentions"] = len(inh_agent)
    out["c5_inherited_agent_ids"] = [r["id"] for r in inh_agent]
    out["c5_fresh_agent_mentions"] = sum(
        1
        for r in rows
        if r["origin_family"] == "FRESH"
        and AGENT_WORDS.search(r["raw"].get("claim", "") + " " + r["raw"].get("refuter", ""))
    )
    return out


def main():
    rows, problems, blocking = load_rows()
    w = print

    w("=" * 72)
    w("PARSE")
    w("=" * 72)
    w(f"rows parsed: {len(rows):d}")
    w(f"problems: {len(problems):d} total, {len(blocking):d} BLOCKING")
    for p in blocking:
        w(f"  BLOCKING {p}")
    if blocking:
        raise SystemExit("blocking parse problems - band not printed")
    w("malformed rows: {:d}".format(sum(1 for r in rows if r["malformed"])))

    fine = fine_end(rows)
    w("")
    w("=" * 72)
    w("FINE END verification against docs/_rescore/tally_report.md")
    w("=" * 72)
    ok = True
    for k, expected in FINE_EXPECTED.items():
        got = fine[k]
        match = abs(float(got) - float(expected)) < 0.051
        ok = ok and match
        w("  {!s:<24} expected {!s:<8} got {!s:<8} {}".format(k, expected, got, "MATCH" if match else "MISMATCH"))
    if not ok:
        raise SystemExit("fine end does not reproduce tally_report.md - band not printed")
    w("  fine N = {:d}".format(fine["n"]))
    w("  gate-or-contract {:d}/{:d}  inherited {:d}/{:d}  BORN-WRONG {:d} : DECAYED {:d}  fof {:d}/{:d}"
      .format(fine["gate_or_contract"], fine["n"], fine["inherited"], fine["n"],
              fine["born_wrong"], fine["decayed"], fine["fix_of_a_fix"], fine["n"]))

    coarse = coarse_end(rows)
    w("")
    w("=" * 72)
    w("COARSE END - one event per ledger entry")
    w("=" * 72)
    w("coarse N = {:d} distinct entries carrying at least one row".format(coarse["n"]))
    w("rows per entry: min {:d} max {:d}"
      .format(min(coarse["rows_per_entry"].values()), max(coarse["rows_per_entry"].values())))
    w("  gate-or-contract (any-of)  {:d}/{:d} = {} pct"
      .format(coarse["gate_or_contract"], coarse["n"], coarse["gate_or_contract_pct"]))
    w("  inherited (any-of)         {:d}/{:d} = {} pct"
      .format(coarse["inherited"], coarse["n"], coarse["inherited_pct"]))
    w("  BORN-WRONG:DECAYED any-of  {:d} : {:d} = {} : 1"
      .format(coarse["born_wrong_any"], coarse["decayed_any"], coarse["born_wrong_to_decayed_any"]))
    w("  BORN-WRONG:DECAYED prec    {:d} : {:d} = {} : 1"
      .format(coarse["born_wrong_prec"], coarse["decayed_prec"], coarse["born_wrong_to_decayed_prec"]))
    w("  fix-of-a-fix (any-of)      {:d}/{:d} = {} pct"
      .format(coarse["fix_of_a_fix"], coarse["n"], coarse["fix_of_a_fix_pct"]))

    w("")
    w("  prevention, ANY-OF (columns sum above N by construction):")
    for v, c in coarse["prev_anyof"].most_common():
        w("    {!s:<20} {:3d}  ({} pct of {:d} entries)".format(v, c, pct(c, coarse["n"]), coarse["n"]))
    w("  prevention, v1.3 clause 2 FIRST-MATCH precedence (sums to N):")
    for v, c in coarse["prev_prec"].most_common():
        w("    {!s:<20} {:3d}  ({} pct)".format(v, c, pct(c, coarse["n"])))
    w("    TOTAL {:d}".format(sum(coarse["prev_prec"].values())))

    w("")
    w("=" * 72)
    w("BANDS  (fine end .. coarse end)")
    w("=" * 72)
    w("  gate-or-contract    {} to {} pct".format(fine["gate_or_contract_pct"], coarse["gate_or_contract_pct"]))
    w("  inherited           {} to {} pct".format(fine["inherited_pct"], coarse["inherited_pct"]))
    w("  BORN-WRONG:DECAYED  {} to {} : 1".format(min(fine["born_wrong_to_decayed"], coarse["born_wrong_to_decayed_any"]),
         max(fine["born_wrong_to_decayed"], coarse["born_wrong_to_decayed_any"])))
    w("  fix-of-a-fix        {} to {} pct".format(fine["fix_of_a_fix_pct"], coarse["fix_of_a_fix_pct"]))

    w("")
    w("=" * 72)
    w("RC'S OWN PUBLISHED POSITIONS, re-measured against this corpus")
    w("=" * 72)
    ga = sum(1 for r in rows if r["prevention"] == "GATE-ABSENT")
    ge = sum(1 for r in rows if r["prevention"] == "GATE-EXISTING")
    w(f"  fine: GATE-ABSENT {ga:d} vs GATE-EXISTING {ge:d} = {ratio(ga, ge)} : 1 toward never-graded")
    ga_c = coarse["prev_anyof"].get("GATE-ABSENT", 0)
    ge_c = coarse["prev_anyof"].get("GATE-EXISTING", 0)
    w(f"  coarse any-of: GATE-ABSENT {ga_c:d} vs GATE-EXISTING {ge_c:d} = {ratio(ga_c, ge_c)} : 1")
    w("  fine: DECAYED alone {:d}/{:d} = {} pct of all events"
      .format(fine["decayed"], fine["n"], pct(fine["decayed"], fine["n"])))
    w("  fine: DECAYED as a share of INHERITED = {} pct".format(pct(fine["decayed"], fine["inherited"])))
    w("  coarse any-of: DECAYED alone {:d}/{:d} = {} pct of all events"
      .format(coarse["decayed_any"], coarse["n"], pct(coarse["decayed_any"], coarse["n"])))

    d = v13_clause_deltas(rows)
    w("")
    w("=" * 72)
    w("PIN v1.3 CLAUSE DELTAS over the existing rows")
    w("=" * 72)
    for k in sorted(d):
        if k.endswith("_ids"):
            w(f"  {k!s:<32} {d[k]}")
        else:
            w(f"  {k!s:<32} {d[k]}")

    w("")
    w("=" * 72)
    w("CLAUSE 1 CONFORMANCE SAMPLE (deterministic, 6 per chunk = 24 rows)")
    w("=" * 72)
    for r in conformance_sample(rows):
        w("--- {} (entry {})".format(r["id"], r["entry"]))
        w("    claim: {}".format(r["raw"].get("claim", "")[:300]))

    w("")
    w("DONE")


if __name__ == "__main__":
    main()
