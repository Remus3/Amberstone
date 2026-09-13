"""Tally scorer A against scorer B over the 198-row RC corpus.

Two-scorer, FULL-OVERLAP comparison. Both scorers graded all 198 rows blind
from `rc198_blinded.md` under `RC_SCORING_CONVENTION_v1.md`.

This script FAILS LOUDLY. A row missing from either file, an unparseable
field, or a value outside the convention's set is COUNTED AND NAMED in the
`DEFECTS` section of the output. Nothing is dropped silently.

Run:  python docs/_rsc_score/tally_ab.py
"""

from __future__ import annotations

import sys
import textwrap
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

FILE_A = HERE / "scores_A.md"
FILE_B = HERE / "scores_B.md"

# ---------------------------------------------------------------------------
# The convention's value sets, taken VERBATIM from RC_SCORING_CONVENTION_v1.md
# ---------------------------------------------------------------------------

# Section 3, "The value set is exactly these eight."
PREVENTION_VALUES = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "PROXY-MEASURE",
    "CONTRACT",
    "CONTRACT-MISFIRED",
    "ADVERSARY",
}

# Section 4.1, the IN-FAMILY / OUT-FAMILY grouping, taken verbatim.
IN_FAMILY = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "CONTRACT",
    "CONTRACT-MISFIRED",
}
OUT_FAMILY = {"PROXY-MEASURE", "ADVERSARY"}

assert IN_FAMILY | OUT_FAMILY == PREVENTION_VALUES
assert not (IN_FAMILY & OUT_FAMILY)

# Section 3.1, prevention_why.
WHY_VALUES = {"WRONG-SCOPE", "WRONG-TIME", "VACUOUS"}

# Section 5, origin_time sub-values (REQUIRED on INHERITED).
ORIGIN_SUBVALUES = {
    "DECAYED",
    "BORN-WRONG",
    "OVER-GENERALISED",
    "UNDER-PROVEN",
    "UNKNOWN",
}

# Section 6, chain_kind.
CHAIN_KINDS = {
    "SELF",
    "INTRODUCED",
    "SIBLING-SURFACE",
    "INHERITED-SHARED",
    "SAME-ARTIFACT",
}

# Section 7, correct.
CORRECT_VALUES = {"YES", "NO", "UNCLEAR"}

# Fields NOT governed by the convention's own value sets. Both scorers
# invented these; the convention MANDATES the sfb column (3.4) without
# saying what values it takes, and never mentions gfck or odf as emitted
# fields at all. Compared, but flagged.
UNGOVERNED_FIELDS = {"gfck", "sfb", "odf", "cu", "xrow", "instr", "indiv"}


class Defect:
    def __init__(self, kind: str, where: str, detail: str) -> None:
        self.kind = kind
        self.where = where
        self.detail = detail

    def __str__(self) -> str:
        return f"[{self.kind}] {self.where}: {self.detail}"


DEFECTS: list[Defect] = []


def defect(kind: str, where: str, detail: str) -> None:
    DEFECTS.append(Defect(kind, where, detail))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse(path: Path, label: str) -> tuple[dict[str, dict[str, str]], set[str]]:
    """Return {row_id: {field: raw_value}} plus the set of field keys seen."""
    if not path.exists():
        print(f"FATAL: {path} does not exist", file=sys.stderr)
        raise SystemExit(2)
    rows: dict[str, dict[str, str]] = {}
    keys_seen: set[str] = set()
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.startswith("ROW "):
            continue
        parts = [p.strip() for p in line[4:].split("|")]
        row_id = parts[0]
        if not row_id:
            defect("UNPARSEABLE-ROW", f"{label}:{lineno}", "empty row id")
            continue
        fields: dict[str, str] = {}
        for chunk in parts[1:]:
            if "=" not in chunk:
                defect(
                    "UNPARSEABLE-FIELD",
                    f"{label}:{lineno}:{row_id}",
                    f"field chunk has no '=': {chunk!r}",
                )
                continue
            key, _, value = chunk.partition("=")
            key = key.strip()
            value = value.strip()
            if key in fields:
                defect(
                    "DUPLICATE-FIELD",
                    f"{label}:{lineno}:{row_id}",
                    f"field {key!r} appears twice",
                )
            fields[key] = value
            keys_seen.add(key)
        if row_id in rows:
            defect(
                "DUPLICATE-ROW",
                f"{label}:{lineno}",
                f"row id {row_id} already seen",
            )
        rows[row_id] = fields
    return rows, keys_seen


# ---------------------------------------------------------------------------
# Field validation - every value outside the convention's set is NAMED
# ---------------------------------------------------------------------------


def prevention_set(raw: str, where: str) -> frozenset[str]:
    if raw in ("", "-"):
        defect("EMPTY-PREVENTION", where, "prevention is empty or '-'")
        return frozenset()
    values = [v.strip() for v in raw.split(",") if v.strip()]
    out: set[str] = set()
    for v in values:
        if v not in PREVENTION_VALUES:
            defect("VALUE-OUTSIDE-SET", where, f"prevention value {v!r} is not one of the eight")
        out.add(v)
    if len(out) != len(values):
        defect("REPEATED-VALUE", where, f"prevention list repeats a value: {raw!r}")
    return frozenset(out)


def family_label(pset: frozenset[str], where: str) -> str:
    """Convention 3.9 / 4.1: TRUE if every value IN, FALSE if every value OUT,
    SPLIT if the set straddles. A SPLIT row is NEVER silently assigned to a
    side and NEVER given partial credit."""
    if not pset:
        defect("FAMILY-UNDEFINED", where, "empty prevention set has no family label")
        return "UNDEFINED"
    known = {v for v in pset if v in PREVENTION_VALUES}
    if known != pset:
        defect("FAMILY-UNDEFINED", where, f"unknown value in set {sorted(pset)}")
    ins = known & IN_FAMILY
    outs = known & OUT_FAMILY
    if ins and outs:
        return "SPLIT"
    if ins:
        return "TRUE"
    if outs:
        return "FALSE"
    return "UNDEFINED"


def origin_parts(raw: str, where: str) -> tuple[str, str]:
    """Return (family, subvalue). Subvalue is '' for FRESH."""
    if raw == "FRESH":
        return ("FRESH", "")
    if raw.startswith("INHERITED/"):
        sub = raw.split("/", 1)[1]
        if sub not in ORIGIN_SUBVALUES:
            defect("VALUE-OUTSIDE-SET", where, f"origin sub-value {sub!r} is not one of the five")
        return ("INHERITED", sub)
    if raw == "INHERITED":
        defect(
            "MISSING-SUBVALUE",
            where,
            "origin is INHERITED with no sub-value; section 5 REQUIRES one",
        )
        return ("INHERITED", "")
    defect("VALUE-OUTSIDE-SET", where, f"origin {raw!r} is neither FRESH nor INHERITED/<sub>")
    return (raw, "")


def fix_int(raw: str, where: str) -> int:
    try:
        n = int(raw)
    except ValueError:
        defect("UNPARSEABLE-FIELD", where, f"fix_chain {raw!r} is not an integer")
        return -1
    if n < 0:
        defect("VALUE-OUTSIDE-SET", where, f"fix_chain {n} is negative")
    return n


def validate_row(label: str, row_id: str, f: dict[str, str]) -> None:
    where = f"{label}:{row_id}"
    for required in ("prev", "origin", "fix", "correct"):
        if required not in f:
            defect("MISSING-FIELD", where, f"required field {required!r} absent")
    why = f.get("why", "-")
    if why != "-" and why not in WHY_VALUES:
        defect("VALUE-OUTSIDE-SET", where, f"prevention_why {why!r} is not one of the three")
    if why != "-" and "GATE-EXISTING" not in f.get("prev", ""):
        defect(
            "WHY-WITHOUT-GATE-EXISTING",
            where,
            f"prevention_why={why} recorded but GATE-EXISTING not in the set",
        )
    kinds = f.get("kinds", "-")
    if kinds != "-":
        klist = [k.strip() for k in kinds.split(",") if k.strip()]
        for k in klist:
            if k not in CHAIN_KINDS:
                defect("VALUE-OUTSIDE-SET", where, f"chain_kind {k!r} is not one of the five")
        n = fix_int(f.get("fix", "-1"), where)
        if n >= 0 and len(klist) != n:
            defect(
                "CHAIN-LENGTH-MISMATCH",
                where,
                f"fix_chain={n} but {len(klist)} chain_kind entries",
            )
    else:
        n = fix_int(f.get("fix", "-1"), where)
        if n > 0:
            defect(
                "CHAIN-LENGTH-MISMATCH",
                where,
                f"fix_chain={n} but chain_kind is '-'",
            )
    corr = f.get("correct", "")
    if corr not in CORRECT_VALUES:
        defect("VALUE-OUTSIDE-SET", where, f"correct {corr!r} is not YES/NO/UNCLEAR")
    for boolean in ("odf", "cu", "instr"):
        v = f.get(boolean)
        if v is not None and v not in ("Y", "N"):
            defect("VALUE-OUTSIDE-SET", where, f"{boolean} {v!r} is not Y/N")
    sfb = f.get("sfb", "-")
    if sfb != "-" and sfb not in PREVENTION_VALUES:
        defect("VALUE-OUTSIDE-SET", where, f"sfb {sfb!r} is not one of the eight")
    indiv = f.get("indiv", "")
    if indiv and not (
        indiv == "KEEP"
        or (indiv.startswith("SPLIT:") and indiv[6:].isdigit())
        or indiv.startswith("MERGE:")
    ):
        defect("VALUE-OUTSIDE-SET", where, f"indiv {indiv!r} is not KEEP/SPLIT:n/MERGE:<id>")


# ---------------------------------------------------------------------------
# Attribution of SET disagreements to NAMED forced resolutions
# ---------------------------------------------------------------------------
#
# Each rule names a divergence that BOTH scorers declared in their own
# "Ambiguities I resolved" sections, and a signature over the symmetric
# difference that only that divergence produces. Rules are tried in order;
# the FIRST match wins, and its name is recorded. A disagreement matching no
# rule is counted as UNATTRIBUTED - it is NOT forced into a bucket.

ATTRIBUTION_RULES = [
    (
        "D-VACUITY-CARVEOUT",
        "B item 6 (3.5's vacuity carve-out vs PROXY-MEASURE, where a clean zero "
        "is indistinguishable from a clean tree - B scores GATE-EXISTING/VACUOUS "
        "where the instrument could not tell a real pass from a no-op, and "
        "PROXY-MEASURE where it measured a real quantity read as another; B "
        "cites chunk1-55 BY ID as the proxy side) vs "
        "A, which declared no vacuity resolution.",
        lambda a, b, sym: sym == {"GATE-EXISTING", "PROXY-MEASURE"},
    ),
    (
        "D-PROXY-STANDALONE",
        "A item 3 (PROXY-MEASURE stands ALONE where the substitution IS the "
        "whole defect, so GATE-ABSENT is not independently grounded) vs "
        "B item 5 (3.5's three conditions applied hard - PROXY-MEASURE only "
        "where the row names BOTH substituted quantities, so several "
        "proxy-shaped rows come out as bare GATE-ABSENT).",
        lambda a, b, sym: sym == {"GATE-ABSENT", "PROXY-MEASURE"},
    ),
    (
        "D-GATE-EXISTING-TIEBREAK",
        "B item 1 (the section-3 tie-breaker WINS over 3.2's boundary, so "
        "WRONG-SCOPE is emitted on ZERO rows and GATE-EXISTING survives only "
        "for WRONG-TIME and VACUOUS) vs A, which declared no such resolution "
        "and reaches GATE-EXISTING on rows B does not.",
        lambda a, b, sym: "GATE-EXISTING" in sym,
    ),
    (
        "D-STANDING-CHECK",
        "A item 1 and B item 2, both on 3.4's 'NAMED instrument WITH A FIRING "
        "VERB which a STANDING RULE REQUIRED to run' - the two scorers drew "
        "the named-pass list differently, moving rows between "
        "GATE-FIRED-CAUGHT and GATE-ABSENT.",
        lambda a, b, sym: sym <= {"GATE-FIRED-CAUGHT", "GATE-ABSENT"}
        and "GATE-FIRED-CAUGHT" in sym,
    ),
    (
        "D-ADVERSARY-SHAPE",
        "B item 3 (GATE-FIRED-CAUGHT takes precedence over 3.8's SHAPE test, "
        "which is written to police the ADVERSARY / GATE-ABSENT boundary "
        "only) against A's reading of the same boundary - moving rows between "
        "ADVERSARY and the gate values.",
        lambda a, b, sym: "ADVERSARY" in sym,
    ),
    (
        "D-CONTRACT-NARROW",
        "B item 7 (CONTRACT only where the ROW's text names the rule; reached "
        "on exactly one row) vs A, which declared no CONTRACT resolution.",
        lambda a, b, sym: "CONTRACT" in sym or "CONTRACT-MISFIRED" in sym,
    ),
]


def attribute(a: frozenset[str], b: frozenset[str]) -> str:
    sym = set(a ^ b)
    for name, _why, pred in ATTRIBUTION_RULES:
        if pred(a, b, sym):
            return name
    return "UNATTRIBUTED"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def pct(k: int, n: int) -> str:
    return f"{100.0 * k / n:.4f}"


def main() -> int:
    rows_a, keys_a = parse(FILE_A, "A")
    rows_b, keys_b = parse(FILE_B, "B")

    ids_a, ids_b = set(rows_a), set(rows_b)
    for rid in sorted(ids_a - ids_b):
        defect("ROW-MISSING", f"B:{rid}", "row present in A, absent from B")
    for rid in sorted(ids_b - ids_a):
        defect("ROW-MISSING", f"A:{rid}", "row present in B, absent from A")
    common = sorted(ids_a & ids_b)

    for rid in sorted(ids_a):
        validate_row("A", rid, rows_a[rid])
    for rid in sorted(ids_b):
        validate_row("B", rid, rows_b[rid])

    n = len(common)

    out: list[str] = []
    w = out.append

    w("=" * 78)
    w("TALLY - scorer A vs scorer B, RC scoring convention v1, RC's own 198 rows")
    w("=" * 78)
    w("")
    w(f"rows in A               : {len(rows_a)} ({len(ids_a)} distinct ids)")
    w(f"rows in B               : {len(rows_b)} ({len(ids_b)} distinct ids)")
    w(f"full-overlap comparison : n = {n}")
    w("")

    # ---- schema reconciliation -------------------------------------------
    w("-" * 78)
    w("SCHEMA RECONCILIATION - what is genuinely common and what is not")
    w("-" * 78)
    w(f"field keys in A : {sorted(keys_a)}")
    w(f"field keys in B : {sorted(keys_b)}")
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    w(f"A-only keys     : {only_a if only_a else 'none'}")
    w(f"B-only keys     : {only_b if only_b else 'none'}")
    w(f"common keys     : {sorted(keys_a & keys_b)}")
    w("")
    w("NOT COMPARED, and why:")
    w("  why   - conditional on GATE-EXISTING membership, which is itself one of")
    w("          the disagreements being measured; a like-for-like comparison")
    w("          would be over a denominator the two scorers do not share.")
    w("          Counts are printed below instead of an agreement rate.")
    w("  kinds - conditional on fix_chain >= 1, same problem, same treatment.")
    w("COMPARED BUT NOT CONVENTION-GOVERNED (both scorers invented the values;")
    w("  the convention mandates the sfb COLUMN at 3.4 without defining what it")
    w("  holds, and never specifies odf / cu / xrow / instr / gfck / indiv as")
    w("  emitted fields at all):")
    w(f"  {sorted(UNGOVERNED_FIELDS & keys_a & keys_b)}")
    w("")

    # ---- 1. prevention SET identity ---------------------------------------
    sets_a = {r: prevention_set(rows_a[r].get("prev", ""), f"A:{r}") for r in common}
    sets_b = {r: prevention_set(rows_b[r].get("prev", ""), f"B:{r}") for r in common}

    set_agree = [r for r in common if sets_a[r] == sets_b[r]]
    set_disagree = [r for r in common if sets_a[r] != sets_b[r]]

    w("-" * 78)
    w("1. prevention SET IDENTITY")
    w("-" * 78)
    w("   GRAIN       : SET (exact unordered set equality over the eight values)")
    w("   AGGREGATION : single pair A-B, one comparison per row, n = 198")
    w("   ADJUDICATOR : this script (tally_ab.py); no majority rule exists at n=2")
    w("")
    w(f"   AGREEMENT    {len(set_agree)} of {n}  = {pct(len(set_agree), n)} pct")
    w(f"   DISAGREEMENT {len(set_disagree)} of {n}  = {pct(len(set_disagree), n)} pct")
    w("")

    # ---- 2. prevention FAMILY ---------------------------------------------
    fam_a = {r: family_label(sets_a[r], f"A:{r}") for r in common}
    fam_b = {r: family_label(sets_b[r], f"B:{r}") for r in common}
    fam_agree = [r for r in common if fam_a[r] == fam_b[r]]
    fam_disagree = [r for r in common if fam_a[r] != fam_b[r]]

    w("-" * 78)
    w("2. prevention FAMILY")
    w("-" * 78)
    w("   GRAIN       : FAMILY (convention 4.1 grouping, taken verbatim)")
    w("                 IN-FAMILY  = " + ", ".join(sorted(IN_FAMILY)))
    w("                 OUT-FAMILY = " + ", ".join(sorted(OUT_FAMILY)))
    w("   AGGREGATION : single pair A-B, one comparison per row, n = 198")
    w("   ADJUDICATOR : this script")
    w("")
    w("   MIXED-SET HANDLING, stated explicitly: a row whose set straddles the")
    w("   boundary is labelled SPLIT, per convention 3.9 - it is NOT assigned to")
    w("   a side, NOT dropped, and NOT given partial credit. SPLIT-vs-TRUE and")
    w("   SPLIT-vs-FALSE are counted as DISAGREEMENTS (PREREGISTRATION 4.2:")
    w("   'SPLIT-vs-TRUE is a DISAGREEMENT, never partial credit').")
    w("")
    w(f"   AGREEMENT    {len(fam_agree)} of {n}  = {pct(len(fam_agree), n)} pct")
    w(f"   DISAGREEMENT {len(fam_disagree)} of {n}  = {pct(len(fam_disagree), n)} pct")
    w("")
    w(f"   A label counts: {dict(sorted(Counter(fam_a.values()).items()))}")
    w(f"   B label counts: {dict(sorted(Counter(fam_b.values()).items()))}")
    pair_counts = Counter((fam_a[r], fam_b[r]) for r in common)
    w("   label pair counts (A, B):")
    for k, v in sorted(pair_counts.items()):
        w(f"     {k[0]:>9} / {k[1]:<9} {v}")
    w("")

    # ---- 3. origin_time ----------------------------------------------------
    orig_a = {r: origin_parts(rows_a[r].get("origin", ""), f"A:{r}") for r in common}
    orig_b = {r: origin_parts(rows_b[r].get("origin", ""), f"B:{r}") for r in common}
    of_agree = [r for r in common if orig_a[r][0] == orig_b[r][0]]
    os_agree = [r for r in common if orig_a[r] == orig_b[r]]

    w("-" * 78)
    w("3. origin_time")
    w("-" * 78)
    w("   GRAIN       : (a) FAMILY - FRESH vs INHERITED")
    w("                 (b) sub-value - FRESH vs INHERITED/<one of five>")
    w("   AGGREGATION : single pair A-B, one comparison per row, n = 198")
    w("   ADJUDICATOR : this script")
    w("")
    w(f"   (a) FAMILY    agreement {len(of_agree)} of {n} = {pct(len(of_agree), n)} pct"
      f"   disagreement {n - len(of_agree)} = {pct(n - len(of_agree), n)} pct")
    w(f"   (b) SUB-VALUE agreement {len(os_agree)} of {n} = {pct(len(os_agree), n)} pct"
      f"   disagreement {n - len(os_agree)} = {pct(n - len(os_agree), n)} pct")
    w("")
    w(f"   A FRESH/INHERITED: {dict(sorted(Counter(v[0] for v in orig_a.values()).items()))}")
    w(f"   B FRESH/INHERITED: {dict(sorted(Counter(v[0] for v in orig_b.values()).items()))}")
    w(f"   A sub-values: {dict(sorted(Counter(v[1] for v in orig_a.values() if v[1]).items()))}")
    w(f"   B sub-values: {dict(sorted(Counter(v[1] for v in orig_b.values() if v[1]).items()))}")
    w("")

    # ---- 4. fix_chain >= 1 boolean ----------------------------------------
    fb_a = {r: fix_int(rows_a[r].get("fix", "-1"), f"A:{r}") >= 1 for r in common}
    fb_b = {r: fix_int(rows_b[r].get("fix", "-1"), f"B:{r}") >= 1 for r in common}
    fb_agree = [r for r in common if fb_a[r] == fb_b[r]]

    w("-" * 78)
    w("4. fix_chain >= 1 (the BOOLEAN, not the integer)")
    w("-" * 78)
    w("   GRAIN       : boolean")
    w("   AGGREGATION : single pair A-B, one comparison per row, n = 198")
    w("   ADJUDICATOR : this script")
    w("")
    w(f"   AGREEMENT    {len(fb_agree)} of {n} = {pct(len(fb_agree), n)} pct")
    w(f"   DISAGREEMENT {n - len(fb_agree)} of {n} = {pct(n - len(fb_agree), n)} pct")
    w(f"   A true count: {sum(fb_a.values())}   B true count: {sum(fb_b.values())}")
    disagree_fb = [r for r in common if fb_a[r] != fb_b[r]]
    if disagree_fb:
        w(f"   rows: {', '.join(disagree_fb)}")
    w("")

    # ---- 5. anatomy of the SET disagreements -------------------------------
    pure_in = []
    involves_out = []
    moves_family = []
    for r in set_disagree:
        sym = sets_a[r] ^ sets_b[r]
        if sym <= IN_FAMILY:
            pure_in.append(r)
        else:
            involves_out.append(r)
        if fam_a[r] != fam_b[r]:
            moves_family.append(r)

    w("-" * 78)
    w("5. ANATOMY OF THE SET DISAGREEMENTS")
    w("-" * 78)
    w(f"   total SET disagreements            : {len(set_disagree)}")
    w(f"   purely IN-FAMILY swaps             : {len(pure_in)}"
      "   (symmetric difference entirely IN-FAMILY;")
    w("                                         cannot move a published family share)")
    w(f"   involving an OUT-FAMILY value      : {len(involves_out)}")
    w(f"   actually CHANGING the family label : {len(moves_family)}"
      "   (these are the headline-moving ones)")
    w("")
    w("   THE TWO-VALUE CHECK (LW reports 22 of 22 on RC's corpus and 24 of 24 on")
    w("   a third tree's, zero counterexamples in both - those figures are LW's")
    w("   OWN notes, attributed to LW, and are NOT RC measurements).")
    w("")
    w("   The claim has TWO readings and they give DIFFERENT answers here, so")
    w("   both are computed and neither is reported as the headline alone.")
    w("")
    strict = [r for r in moves_family if (sets_a[r] ^ sets_b[r]) & OUT_FAMILY]
    strict_ce = [r for r in moves_family if r not in strict]
    loose = [r for r in moves_family if (sets_a[r] | sets_b[r]) & OUT_FAMILY]
    loose_ce = [r for r in moves_family if r not in loose]
    w("   READING 1 (INFORMATIVE) - the value that DIFFERS between the two")
    w("   scorers is PROXY-MEASURE or ADVERSARY, i.e. the symmetric difference")
    w("   touches one of the two:")
    w(f"     headline-moving disagreements : {len(moves_family)}")
    w(f"     satisfying reading 1          : {len(strict)}")
    w(f"     COUNTEREXAMPLES               : {len(strict_ce)}")
    if strict_ce:
        for r in strict_ce:
            w(
                f"       {r}: A={{{','.join(sorted(sets_a[r]))}}} ({fam_a[r]}) "
                f"B={{{','.join(sorted(sets_b[r]))}}} ({fam_b[r]}) "
                f"differing value = {','.join(sorted(sets_a[r] ^ sets_b[r]))}"
            )
    w("")
    w("   READING 2 (TRIVIAL) - at least one of the two sets CARRIES")
    w("   PROXY-MEASURE or ADVERSARY:")
    w(f"     satisfying reading 2          : {len(loose)}")
    w(f"     COUNTEREXAMPLES               : {len(loose_ce)}")
    w("")
    w("   WHY READING 2 IS NOT EVIDENCE. Under convention 4.1 the OUT-FAMILY set")
    w("   IS exactly {PROXY-MEASURE, ADVERSARY}. If both sets were wholly")
    w("   IN-FAMILY both labels would be TRUE and the label could not differ, so")
    w("   a family-label change GUARANTEES that one side carries one of those")
    w("   two values. Reading 2 is an ANALYTIC IDENTITY of the grouping and")
    w("   cannot come out other than N of N. It is printed only so that an N-of-N")
    w("   result is not mistaken for a measurement.")
    w("")
    w("   WHY READING 1 CAN AND DOES FAIL. The differing value need not be the")
    w("   out-family one: where one scorer emits a STRADDLE and the other a")
    w("   single value, the label moves (FALSE -> SPLIT) while the value that")
    w("   actually differs is IN-FAMILY. Both counterexamples above are that")
    w("   shape. They exist only because this convention ADMITS a straddle at")
    w("   3.9; a convention that forced one value per row would collapse reading")
    w("   1 into reading 2 and could not produce them. Whether LW's zero")
    w("   counterexamples reflect a corpus fact or a single-value convention is")
    w("   NOT determinable from RC's side and is not asserted either way.")
    w("")
    per_value_moves = Counter()
    for r in moves_family:
        for v in sorted(sets_a[r] ^ sets_b[r]):
            per_value_moves[v] += 1
    w(f"   values appearing in headline-moving differences: "
      f"{dict(sorted(per_value_moves.items()))}")
    w("")

    # ---- attribution -------------------------------------------------------
    attrib = Counter()
    attrib_rows: dict[str, list[str]] = {}
    for r in set_disagree:
        name = attribute(sets_a[r], sets_b[r])
        attrib[name] += 1
        attrib_rows.setdefault(name, []).append(r)

    w("-" * 78)
    w("6. ATTRIBUTION OF SET DISAGREEMENTS TO NAMED FORCED RESOLUTIONS")
    w("-" * 78)
    w("   Both scorers logged, unprompted, that they were FORCED to resolve")
    w("   points the convention left undetermined before they could score at")
    w("   all. Where a disagreement's symmetric difference has the signature of")
    w("   one named divergence, it is attributed to that divergence by NAME.")
    w("   Rules are tried in the order below and the FIRST match wins.")
    w("   A disagreement matching none is UNATTRIBUTED and is left so.")
    w("")
    for name, why, _pred in ATTRIBUTION_RULES:
        w(f"   {name}  ({attrib.get(name, 0)} rows)")
        for chunk in textwrap.wrap(why, width=68):
            w(f"       {chunk}")
        w(f"       rows: {', '.join(attrib_rows.get(name, [])) or 'none'}")
    w(f"   UNATTRIBUTED  ({attrib.get('UNATTRIBUTED', 0)} rows)")
    w("")
    total_attr = len(set_disagree) - attrib.get("UNATTRIBUTED", 0)
    w(f"   ATTRIBUTED   {total_attr} of {len(set_disagree)}")
    w(f"   UNATTRIBUTED {attrib.get('UNATTRIBUTED', 0)} of {len(set_disagree)}")
    if attrib.get("UNATTRIBUTED"):
        w(f"     rows: {', '.join(attrib_rows['UNATTRIBUTED'])}")
    w("")

    # origin attribution - one named divergence, reported separately
    orig_dis = [r for r in common if orig_a[r] != orig_b[r]]
    directive_shape = [
        r
        for r in orig_dis
        if orig_a[r][0] == "INHERITED"
        and orig_b[r][0] == "FRESH"
        and rows_b[r].get("odf") == "Y"
    ]
    w("   origin_time, the one named divergence with a checkable signature:")
    w("     A item 5 files loop directives, dispatches, briefs, specs, filed rows")
    w("     and shipped code as INHERITED durable artifacts. B item 8 applies the")
    w("     5.2(a) FLOOR to the same rows, so they come out FRESH with odf=Y.")
    w(f"     origin sub-value disagreements total                : {len(orig_dis)}")
    w(f"     matching that signature (A INHERITED / B FRESH odf=Y): "
      f"{len(directive_shape)}")
    w("")

    # ---- 7. P1 -------------------------------------------------------------
    p = 100.0 * len(set_disagree) / n
    w("-" * 78)
    w("7. PRE-REGISTERED PREDICTION P1, applied literally")
    w("-" * 78)
    w("   PREREGISTRATION 5.2, verbatim thresholds:")
    w("     CONFIRMED     p < 26.1 pct AND all pairwise rates < 26.1 pct")
    w("     REFUTED       p >= 26.1 pct")
    w("     INDETERMINATE p < 26.1 pct while at least one pairwise rate is")
    w("                   >= 26.1 pct")
    w("")
    w(f"   p (pooled prevention SET-identity DISAGREEMENT) = {len(set_disagree)}/{n}"
      f" = {pct(len(set_disagree), n)} pct")
    w("   pairwise rates available: ONE (A-B). The pooled rate and the single")
    w("   pairwise rate are the same number, because there is one pair.")
    if p >= 26.1:
        verdict = "REFUTED"
    else:
        verdict = "CONFIRMED"
    w(f"   nothing rounded: {p!r} against the threshold 26.1")
    w(f"   VERDICT: P1 {verdict}")
    w("")
    w("   PREREGISTRATION 5.5, the separate per-row rate replication:")
    if 20.0 <= p <= 35.0:
        repl = "REPLICATED"
    elif p < 20.0:
        repl = "BELOW"
    else:
        repl = "ABOVE"
    w(f"     pooled SET disagreement {pct(len(set_disagree), n)} pct -> {repl}")
    w("     (in [20.0, 35.0] = REPLICATED, < 20.0 = BELOW, > 35.0 = ABOVE)")
    w("")

    # ---- conditional-field counts (not compared) ---------------------------
    w("-" * 78)
    w("8. FIELDS NOT COMPARED - counts printed instead of an agreement rate")
    w("-" * 78)
    w(f"   A prevention_why counts: "
      f"{dict(sorted(Counter(rows_a[r].get('why', '-') for r in common).items()))}")
    w(f"   B prevention_why counts: "
      f"{dict(sorted(Counter(rows_b[r].get('why', '-') for r in common).items()))}")
    w(f"   A chain_kind counts    : "
      f"{dict(sorted(Counter(rows_a[r].get('kinds', '-') for r in common).items()))}")
    w(f"   B chain_kind counts    : "
      f"{dict(sorted(Counter(rows_b[r].get('kinds', '-') for r in common).items()))}")
    w("")

    # ---- defects -----------------------------------------------------------
    w("-" * 78)
    w("DEFECTS - every row missing, field unparseable, or value outside the")
    w("convention's set. Counted and NAMED, never dropped.")
    w("-" * 78)
    if not DEFECTS:
        w("   none")
    else:
        by_kind = Counter(d.kind for d in DEFECTS)
        for k, v in sorted(by_kind.items()):
            w(f"   {k}: {v}")
        w("")
        for d in DEFECTS:
            w(f"   {d}")
    w("")
    w("=" * 78)

    text = "\n".join(out)
    print(text)
    non_ascii = [c for c in text if ord(c) > 127]
    if non_ascii:
        print(f"WARNING: output contains {len(non_ascii)} non-ASCII characters",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
