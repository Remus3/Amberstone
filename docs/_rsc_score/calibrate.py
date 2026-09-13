"""CALIBRATION of RC_SCORING_CONVENTION_v1 against RC's own 198 published rows.

This is the validation GATE pinned in `docs/_rsc_score/PREREGISTRATION.md`
section 2. It does three jobs, each a subcommand:

  blind   Parse `docs/_rescore/chunk{1,2,3,4}_rows.md` and emit the BLINDED row
          file the three scorers read - `id`, `entry`, `claim`, `quote`,
          `refuter` and an `uncertain` presence FLAG only. Every filed value
          (`prevention`, `prevention_why`, `discovery`, `origin_time`,
          `correct`, `fix_chain`, `chain_kind`, `pin_gap`) is removed, and the
          `uncertain` BODY is removed because RC measured that 31 of 56 such
          notes name a candidate value outright.

  check   The two-grep-per-stripped-name blinding check, scoped to the rows
          section of the blinded file. Field-key form and bare token. Every
          non-zero cell is printed with its hits so a reader can classify them.

  tally   Read the three scorer output files, aggregate at majority-of-three per
          row per field, and compute the four anchor quantities plus every floor
          and denominator the convention requires to be published beside them.

FAIL LOUDLY. A row that cannot be parsed, is missing a required field, or
carries a value outside the convention's legal set is named and raises. Nothing
is dropped: a silent skip would under-count exactly like the defect this whole
lane exists to avoid.

Run (from the repo root):
  py docs/_rsc_score/calibrate.py blind  --out <path>
  py docs/_rsc_score/calibrate.py check  --blinded <path>
  py docs/_rsc_score/calibrate.py tally  --scorers <A.md> <B.md> <C.md>
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROWS_DIR = HERE.parent / "_rescore"

# ---------------------------------------------------------------------------
# Convention v1 legal value sets. Section numbers refer to
# docs/_rsc_score/RC_SCORING_CONVENTION_v1.md.
# ---------------------------------------------------------------------------

PREVENTION = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "PROXY-MEASURE",
    "CONTRACT",
    "CONTRACT-MISFIRED",
    "ADVERSARY",
}
# Section 4.1.
IN_FAMILY = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "CONTRACT",
    "CONTRACT-MISFIRED",
}
OUT_FAMILY = {"PROXY-MEASURE", "ADVERSARY"}
WHY = {"WRONG-SCOPE", "WRONG-TIME", "VACUOUS", "-"}
# Section 5.
SUBVALUE = {"DECAYED", "BORN-WRONG", "OVER-GENERALISED", "UNDER-PROVEN", "UNKNOWN"}
# Section 6.
CHAIN_KIND = {
    "SELF",
    "INTRODUCED",
    "SIBLING-SURFACE",
    "INHERITED-SHARED",
    "SAME-ARTIFACT",
}
CORRECT = {"YES", "NO", "UNCLEAR"}
YESNO = {"Y", "N"}
GFCK = {"MECH", "DIR", "-"}

# ---------------------------------------------------------------------------
# RC's published anchors and the pinned tolerances (PREREGISTRATION 2.1, 2.3).
# ---------------------------------------------------------------------------

ANCHORS = {
    "inherited_pct": (48.5, 5.0),
    "fix_of_a_fix_pct": (12.1, 5.0),
    "bw_dec_ratio": (2.62, 0.50),
    "gate_or_contract_pct": (85.4, 5.0),
}

# Fields stripped by the blinding, for the section 2.1 check.
STRIPPED = (
    "prevention",
    "prevention_why",
    "discovery",
    "origin_time",
    "correct",
    "fix_chain",
    "chain_kind",
    "pin_gap",
)

KEEP = ("id", "entry", "claim", "quote", "refuter")

ROW_HEADING = re.compile(r"^##\s+(chunk\d+-\d+)\s*$")
ANY_HEADING = re.compile(r"^##\s+(.*)$")
FIELD_LINE = re.compile(r"^-\s+`([a-z_]+)`:\s*(.*)$")


class ParseError(RuntimeError):
    """Raised on any row this script cannot account for. Never swallowed."""


# ---------------------------------------------------------------------------
# Source row parsing. Shape reused from docs/_rescore/tally.py.
# ---------------------------------------------------------------------------


def split_blocks(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    current_id = None
    current = []
    for line in lines:
        m = ANY_HEADING.match(line)
        if m:
            if current_id is not None:
                blocks.append((current_id, current))
            rm = ROW_HEADING.match(line)
            current_id = rm.group(1) if rm else None
            current = []
            continue
        if current_id is not None:
            current.append(line)
    if current_id is not None:
        blocks.append((current_id, current))
    return blocks


def parse_fields(body_lines):
    fields = {}
    key = None
    for line in body_lines:
        m = FIELD_LINE.match(line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip()
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if key is not None and (line.startswith("  ") or line.startswith("\t")):
            fields[key] = (fields[key] + " " + stripped).strip()
    return fields


def load_source_rows():
    rows = []
    for n in (1, 2, 3, 4):
        path = ROWS_DIR / f"chunk{n}_rows.md"
        if not path.exists():
            raise ParseError(f"missing source row file: {path}")
        for row_id, body in split_blocks(path):
            fields = parse_fields(body)
            for k in KEEP:
                if k not in fields:
                    raise ParseError(f"{row_id}: missing required source field {k!r}")
            if fields["id"].strip() != row_id:
                raise ParseError(
                    f"{row_id}: heading/field id mismatch ({fields['id']!r})"
                )
            rows.append(
                {
                    "id": row_id,
                    "entry": fields["entry"],
                    "claim": fields["claim"],
                    "quote": fields["quote"],
                    "refuter": fields["refuter"],
                    "uncertain": "uncertain" in fields,
                }
            )
    ids = [r["id"] for r in rows]
    dupes = sorted(i for i, c in Counter(ids).items() if c > 1)
    if dupes:
        raise ParseError(f"duplicate source row ids: {dupes}")
    if len(rows) != 198:
        raise ParseError(f"expected 198 source rows, parsed {len(rows)}")
    return rows


# ---------------------------------------------------------------------------
# blind
# ---------------------------------------------------------------------------

BLIND_PREAMBLE = """# RC's 198 published rows, BLINDED for the convention-v1 calibration pass

Generated by `docs/_rsc_score/calibrate.py blind`. Every filed value is removed:
`prevention`, `prevention_why`, `discovery`, `origin_time`, `correct`,
`fix_chain`, `chain_kind` and `pin_gap`. The `uncertain` BODY is removed and
only a presence FLAG is kept.

Score each row from `claim`, `quote` and `refuter` alone, under
`docs/_rsc_score/RC_SCORING_CONVENTION_v1.md`, applied exactly as written.

## ROWS
"""


def cmd_blind(args):
    rows = load_source_rows()
    out = [BLIND_PREAMBLE]
    for r in rows:
        out.append(f"### {r['id']}")
        out.append(f"- `entry`: {r['entry']}")
        out.append(f"- `claim`: {r['claim']}")
        out.append(f"- `quote`: {r['quote']}")
        out.append(f"- `refuter`: {r['refuter']}")
        out.append(f"- `uncertain_present`: {'YES' if r['uncertain'] else 'NO'}")
        out.append("")
    text = "\n".join(out) + "\n"
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} - {len(rows)} blinded rows, {len(text)} chars")
    return 0


# ---------------------------------------------------------------------------
# check - the two-grep-per-stripped-name blinding verification
# ---------------------------------------------------------------------------


def cmd_check(args):
    text = Path(args.blinded).read_text(encoding="utf-8")
    marker = "## ROWS"
    if marker not in text:
        raise ParseError("blinded file carries no '## ROWS' marker to scope to")
    body = text.split(marker, 1)[1]
    lines = body.splitlines()
    print("field\tkey-form hits\tbare-token hits")
    total_key = 0
    detail = []
    for name in STRIPPED:
        key_re = re.compile(r"`" + re.escape(name) + r"`\s*:")
        bare_re = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        key_hits = [ln for ln in lines if key_re.search(ln)]
        bare_hits = [ln for ln in lines if bare_re.search(ln)]
        total_key += len(key_hits)
        print(f"{name}\t{len(key_hits)}\t{len(bare_hits)}")
        for ln in key_hits:
            detail.append(f"KEY   {name}: {ln[:160]}")
        for ln in bare_hits:
            detail.append(f"BARE  {name}: {ln[:160]}")
    # Value tokens are the leak that matters more than the field names.
    print()
    print("value-token sweep (any legal value name appearing in a blinded row)")
    for value in sorted(PREVENTION | SUBVALUE | CHAIN_KIND):
        hits = [ln for ln in lines if re.search(r"\b" + re.escape(value) + r"\b", ln)]
        if hits:
            print(f"{value}\t{len(hits)}")
            for ln in hits:
                detail.append(f"VALUE {value}: {ln[:160]}")
    print()
    print(f"key-form hits over all stripped names: {total_key} (0 is the pass)")
    if detail:
        print()
        print("ENUMERATED HITS")
        for d in detail:
            print(d)
    return 0


# ---------------------------------------------------------------------------
# tally - scorer output parsing and aggregation
# ---------------------------------------------------------------------------

SCORE_LINE = re.compile(r"^ROW\s+(chunk\d+-\d+)\s*\|\s*(.*)$")


def parse_scorer(path):
    text = Path(path).read_text(encoding="utf-8")
    rows = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.rstrip()
        if not line.startswith("ROW "):
            continue
        m = SCORE_LINE.match(line)
        if not m:
            raise ParseError(f"{path}:{lineno}: unparseable ROW line: {line[:120]!r}")
        row_id = m.group(1)
        kv = {}
        for part in m.group(2).split("|"):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise ParseError(
                    f"{path}:{lineno}: field without '=' in {row_id}: {part!r}"
                )
            k, v = part.split("=", 1)
            kv[k.strip()] = v.strip()
        rec = validate_score(path, lineno, row_id, kv)
        if row_id in rows:
            raise ParseError(f"{path}:{lineno}: duplicate row id {row_id}")
        rows[row_id] = rec
    if len(rows) != 198:
        raise ParseError(f"{path}: expected 198 scored rows, parsed {len(rows)}")
    return rows


REQUIRED_SCORE_KEYS = (
    "prev",
    "why",
    "origin",
    "odf",
    "fix",
    "kinds",
    "cu",
    "xrow",
    "correct",
    "instr",
    "gfck",
    "sfb",
    "indiv",
)


def validate_score(path, lineno, row_id, kv):
    def bad(msg):
        raise ParseError(f"{path}:{lineno}: {row_id}: {msg}")

    for k in REQUIRED_SCORE_KEYS:
        if k not in kv:
            bad(f"missing field {k!r}")

    prev = [p.strip() for p in kv["prev"].split(",") if p.strip()]
    if not prev:
        bad("empty prevention set")
    for p in prev:
        if p not in PREVENTION:
            bad(f"illegal prevention value {p!r}")
    if len(set(prev)) != len(prev):
        bad(f"repeated prevention value in {prev}")

    if kv["why"] not in WHY:
        bad(f"illegal prevention_why {kv['why']!r}")
    if "GATE-EXISTING" in prev and kv["why"] == "-":
        bad("GATE-EXISTING without prevention_why")

    origin = kv["origin"]
    if origin == "FRESH":
        family, sub = "FRESH", None
    elif origin.startswith("INHERITED/"):
        family = "INHERITED"
        sub = origin.split("/", 1)[1]
        if sub not in SUBVALUE:
            bad(f"illegal origin_time sub-value {sub!r}")
    else:
        bad(f"illegal origin_time {origin!r}")

    if kv["odf"] not in YESNO:
        bad(f"illegal odf {kv['odf']!r}")
    if kv["odf"] == "Y" and family != "FRESH":
        bad("odf=Y on a non-FRESH row")

    if not re.fullmatch(r"\d+", kv["fix"]):
        bad(f"illegal fix_chain {kv['fix']!r}")
    fix = int(kv["fix"])

    kinds = [] if kv["kinds"] == "-" else [k.strip() for k in kv["kinds"].split(",")]
    for k in kinds:
        if k not in CHAIN_KIND:
            bad(f"illegal chain_kind {k!r}")
    if len(kinds) != fix:
        bad(f"chain_kind list length {len(kinds)} != fix_chain {fix}")

    if kv["cu"] not in YESNO:
        bad(f"illegal cu {kv['cu']!r}")
    if kv["cu"] == "Y" and fix != 0:
        bad("cu=Y on a row carrying a link")
    if not re.fullmatch(r"\d+", kv["xrow"]):
        bad(f"illegal xrow {kv['xrow']!r}")
    if int(kv["xrow"]) > fix:
        bad(f"cross-row links {kv['xrow']} exceed fix_chain {fix}")

    if kv["correct"] not in CORRECT:
        bad(f"illegal correct {kv['correct']!r}")
    if kv["instr"] not in YESNO:
        bad(f"illegal instr {kv['instr']!r}")
    if kv["gfck"] not in GFCK:
        bad(f"illegal gfck {kv['gfck']!r}")
    if "GATE-FIRED-CAUGHT" in prev and kv["gfck"] == "-":
        bad("GATE-FIRED-CAUGHT without gfck")
    if kv["gfck"] != "-" and "GATE-FIRED-CAUGHT" not in prev:
        bad("gfck set on a row that is not GATE-FIRED-CAUGHT")
    sfb = kv["sfb"]
    if kv["gfck"] == "DIR":
        if sfb not in PREVENTION:
            bad(f"DIRECTED GATE-FIRED-CAUGHT needs a strict fallback, got {sfb!r}")
    elif sfb != "-":
        bad(f"strict fallback set where it does not apply: {sfb!r}")

    indiv = kv["indiv"]
    if indiv != "KEEP" and not re.fullmatch(r"(SPLIT:\d+|MERGE:chunk\d+-\d+)", indiv):
        bad(f"illegal indiv {indiv!r}")

    return {
        "id": row_id,
        "prev": frozenset(prev),
        "why": kv["why"],
        "family": family,
        "sub": sub,
        "odf": kv["odf"] == "Y",
        "fix": fix,
        "kinds": kinds,
        "cu": kv["cu"] == "Y",
        "xrow": int(kv["xrow"]),
        "correct": kv["correct"],
        "instr": kv["instr"] == "Y",
        "gfck": kv["gfck"],
        "sfb": sfb,
        "indiv": indiv,
    }


def family_label(prev_set):
    """Section 4.1: TRUE / FALSE / SPLIT over the co-applying values."""
    ins = any(p in IN_FAMILY for p in prev_set)
    outs = any(p in OUT_FAMILY for p in prev_set)
    if ins and outs:
        return "SPLIT"
    return "TRUE" if ins else "FALSE"


def strict_family_label(rec):
    """LW's STRICT standing-check reading (convention 3.4, mandatory column).

    A GATE-FIRED-CAUGHT reached by a DIRECTED pass is replaced by the scorer's
    declared strict fallback before the family label is computed.
    """
    prev = set(rec["prev"])
    if "GATE-FIRED-CAUGHT" in prev and rec["gfck"] == "DIR":
        prev.discard("GATE-FIRED-CAUGHT")
        prev.add(rec["sfb"])
    return family_label(frozenset(prev))


def majority(values):
    """Majority of three. Returns (value, True) or (None, False) when all differ."""
    c = Counter(values)
    top, n = c.most_common(1)[0]
    if n >= 2:
        return top, True
    return None, False


def pct(n, d):
    return 0.0 if not d else round(100.0 * n / d, 1)


def cmd_tally(args):
    scorers = {}
    for label, path in zip(("A", "B", "C"), args.scorers):
        scorers[label] = parse_scorer(path)
    ids = sorted(scorers["A"], key=lambda s: (s.split("-")[0], int(s.split("-")[1])))
    for label in ("B", "C"):
        missing = set(ids) ^ set(scorers[label])
        if missing:
            raise ParseError(f"scorer {label} row-id set differs: {sorted(missing)}")

    out = []
    w = out.append

    # ---- majority-of-three per row per field -----------------------------
    maj = {}
    nomaj = Counter()
    for rid in ids:
        recs = [scorers[s][rid] for s in ("A", "B", "C")]
        m = {"id": rid}
        for field, key in (
            ("prev", lambda r: r["prev"]),
            ("famlabel", lambda r: family_label(r["prev"])),
            ("strictfam", strict_family_label),
            ("family", lambda r: r["family"]),
            ("origin", lambda r: (r["family"], r["sub"])),
            ("fixbool", lambda r: r["fix"] >= 1),
            ("fix", lambda r: r["fix"]),
            ("correct", lambda r: r["correct"]),
            ("indiv", lambda r: r["indiv"]),
        ):
            val, ok = majority([key(r) for r in recs])
            m[field] = val
            if not ok:
                nomaj[field] += 1
        m["odf"] = majority([r["odf"] for r in recs])[0]
        m["cu"] = majority([r["cu"] for r in recs])[0]
        m["instr"] = majority([r["instr"] for r in recs])[0]
        m["kinds"] = max(
            ([r["kinds"] for r in recs]), key=lambda k: sum(1 for r in recs if r["kinds"] == k)
        )
        m["xrow"] = majority([r["xrow"] for r in recs])[0]
        maj[rid] = m

    n = len(ids)

    # ---- individuation delta (convention 1.3, 1.2) ------------------------
    splits = 0
    merges = 0
    for rid in ids:
        iv = maj[rid]["indiv"]
        if iv is None or iv == "KEEP":
            continue
        if iv.startswith("SPLIT:"):
            splits += int(iv.split(":")[1]) - 1
        elif iv.startswith("MERGE:"):
            merges += 1
    n_events = n + splits - merges
    n_links = sum(maj[r]["fix"] or 0 for r in ids)
    n_decomp = n_events + n_links

    w("DENOMINATORS (convention 1.2, 1.3)")
    w(f"filed rows                : {n}")
    w(f"rows SPLIT (extra events) : {splits}")
    w(f"rows MERGED away          : {merges}")
    w(f"N_events                  : {n_events}")
    w(f"N_links                   : {n_links}")
    w(f"N_decomp                  : {n_decomp}")
    if splits or merges:
        w("GRAIN WARNING: every share below takes its NUMERATOR over the "
          f"{n} FILED rows and its DENOMINATOR over N_events = {n_events}. "
          "A scorer emits one value set per FILED row, so a split row's two "
          "sub-events cannot be scored separately by this harness. Read every "
          "share below as a FLOOR of at most "
          f"{round(100.0 * splits / n_events, 2)} points low.")
    w("")

    # ---- anchor 1: inherited share ---------------------------------------
    inh = sum(1 for r in ids if maj[r]["family"] == "INHERITED")
    odf = sum(1 for r in ids if maj[r]["odf"])
    w("ANCHOR 1 - inherited share, FRESH/INHERITED grain, majority-of-three")
    w(f"INHERITED {inh} of {n_events} = {pct(inh, n_events)} pct (FLOOR; "
      f"origin_default_fresh = {odf})")
    w("")

    # ---- anchor 2: fix-of-a-fix ------------------------------------------
    chained = [r for r in ids if maj[r]["fixbool"]]
    non_sa = [
        r for r in chained if any(k != "SAME-ARTIFACT" for k in (maj[r]["kinds"] or []))
    ]
    cu = sum(1 for r in ids if maj[r]["cu"])
    xrow = sum(maj[r]["xrow"] or 0 for r in ids)
    w("ANCHOR 2 - fix-of-a-fix share, boolean grain, majority-of-three")
    w(f"all chains        : {len(chained)} of {n_events} = {pct(len(chained), n_events)} pct")
    w(f"non-SAME-ARTIFACT : {len(non_sa)} of {n_events} = {pct(len(non_sa), n_events)} pct")
    w(f"(FLOOR; chain_undetermined = {cu}, cross-row links = {xrow})")
    w("")

    # ---- anchor 3: BORN-WRONG : DECAYED ----------------------------------
    subs = Counter()
    for r in ids:
        fam, sub = maj[r]["origin"] if maj[r]["origin"] else (None, None)
        if fam == "INHERITED":
            subs[sub] += 1
    bw, dec, unk = subs["BORN-WRONG"], subs["DECAYED"], subs["UNKNOWN"]
    ratio = round(bw / dec, 2) if dec else None
    w("ANCHOR 3 - BORN-WRONG : DECAYED, sub-value grain, majority-of-three")
    for k in sorted(SUBVALUE):
        w(f"{k}: {subs[k]}")
    w(f"ratio = {ratio} : 1 (UNKNOWN = {unk}, excluded from both sides)")
    if unk > bw + dec:
        w("UNKNOWN exceeds BORN-WRONG + DECAYED: convention weakness 7 fires, "
          "ratio is UNCOMPUTABLE on this corpus")
    w("")

    # ---- anchor 4: gate-or-contract --------------------------------------
    fam_counts = Counter(maj[r]["famlabel"] for r in ids)
    strict_counts = Counter(maj[r]["strictfam"] for r in ids)
    w("ANCHOR 4 - gate_or_contract, FAMILY grain, majority-of-three, over N_events")
    w(f"BROAD  TRUE {fam_counts['TRUE']} / SPLIT {fam_counts['SPLIT']} / "
      f"FALSE {fam_counts['FALSE']} = {pct(fam_counts['TRUE'], n_events)} pct")
    w(f"STRICT TRUE {strict_counts['TRUE']} / SPLIT {strict_counts['SPLIT']} / "
      f"FALSE {strict_counts['FALSE']} = {pct(strict_counts['TRUE'], n_events)} pct")
    w("")

    # ---- per-value SET grain counts --------------------------------------
    w("PREVENTION per-value counts, SET grain, majority-of-three")
    pv = Counter()
    multi = 0
    for r in ids:
        s = maj[r]["prev"] or frozenset()
        if len(s) > 1:
            multi += 1
        for v in s:
            pv[v] += 1
    for v in sorted(PREVENTION):
        w(f"{v}\t{pv[v]}")
    w(f"sum of per-value counts: {sum(pv.values())} (not a partition)")
    w(f"multi-value rows: {multi}")
    w(f"rows with no identifiable refuting instrument: "
      f"{sum(1 for r in ids if not maj[r]['instr'])}")
    w("")

    # ---- correct (section 7: one sentence, never a headline) -------------
    cc = Counter(maj[r]["correct"] for r in ids)
    w(f"correct: NO = {cc['NO']}, UNCLEAR = {cc['UNCLEAR']} "
      "(a ledger-derived corpus cannot measure this field; not evidence)")
    w("")

    # ---- no-majority --------------------------------------------------------
    w("NO-MAJORITY ROWS (all three scorers differ), per field")
    for field in sorted(nomaj):
        w(f"{field}\t{nomaj[field]}")
    if not nomaj:
        w("none")
    w("")

    # ---- pairwise disagreement ------------------------------------------
    w("INTER-SCORER DISAGREEMENT (pairwise and pooled)")
    pairs = (("A", "B"), ("A", "C"), ("B", "C"))
    quantities = {
        "prevention SET": lambda r: r["prev"],
        "prevention FAMILY": lambda r: family_label(r["prev"]),
        "origin_time family": lambda r: r["family"],
        "origin_time family+sub": lambda r: (r["family"], r["sub"]),
        "fix_chain >= 1": lambda r: r["fix"] >= 1,
    }
    for qname, fn in quantities.items():
        cells = []
        pooled_d = 0
        for x, y in pairs:
            d = sum(1 for r in ids if fn(scorers[x][r]) != fn(scorers[y][r]))
            pooled_d += d
            cells.append(f"{x}-{y} {pct(d, n)} pct")
        unanimous = sum(
            1
            for r in ids
            if fn(scorers["A"][r]) == fn(scorers["B"][r]) == fn(scorers["C"][r])
        )
        w(f"{qname}: " + ", ".join(cells)
          + f", pooled {pct(pooled_d, 3 * n)} pct, unanimity {pct(unanimous, n)} pct")
    w("")

    # ---- THE CALIBRATION VERDICT ----------------------------------------
    measured = {
        "inherited_pct": pct(inh, n_events),
        "fix_of_a_fix_pct": pct(len(chained), n_events),
        "bw_dec_ratio": ratio,
        "gate_or_contract_pct": pct(fam_counts["TRUE"], n_events),
    }
    w("CALIBRATION VERDICT (PREREGISTRATION 2.3, applied literally)")
    w("anchor\tpublished\tmeasured\tdelta\ttolerance\tresult")
    reproduced = 0
    for key, (anchor, tol) in ANCHORS.items():
        got = measured[key]
        if got is None:
            w(f"{key}\t{anchor}\tUNCOMPUTABLE\t-\t+/-{tol}\tMISS")
            continue
        delta = round(got - anchor, 2)
        ok = abs(delta) <= tol
        reproduced += 1 if ok else 0
        w(f"{key}\t{anchor}\t{got}\t{delta:+.2f}\t+/-{tol}\t"
          f"{'REPRODUCES' if ok else 'MISS'}")
    if reproduced == 4:
        verdict = "CALIBRATED"
    elif reproduced == 3:
        verdict = "CALIBRATED-WITH-A-MISS"
    else:
        verdict = "NOT CALIBRATED"
    w(f"anchors reproduced: {reproduced} of 4")
    w(f"VERDICT: {verdict}")

    print("\n".join(out))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("blind")
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_blind)

    c = sub.add_parser("check")
    c.add_argument("--blinded", required=True)
    c.set_defaults(func=cmd_check)

    t = sub.add_parser("tally")
    t.add_argument("--scorers", nargs=3, required=True)
    t.set_defaults(func=cmd_tally)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
