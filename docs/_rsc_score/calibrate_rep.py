"""INDEPENDENT REPLICATION harness for the convention-v1 calibration gate.

A second, separately-authored pass at the validation step pinned in
`docs/_rsc_score/PREREGISTRATION.md` section 2. It does NOT supersede
`calibrate.py` or `CALIBRATION.md`, which were produced by a concurrent session
in this same tree; it is committed beside them so the two passes can be compared
rather than one silently overwriting the other.

Subcommands:

  blind   Parse `docs/_rescore/chunk{1,2,3,4}_rows.md` and emit the BLINDED row
          file the scorers read - `id`, `entry`, `claim`, `quote`, `refuter` and
          an `uncertain` presence FLAG only. Every filed value is removed, and
          the `uncertain` BODY is removed because RC measured that 31 of 56 such
          notes name a candidate value outright.

  check   The two-grep-per-stripped-name blinding check plus a value-token
          sweep, scoped to the rows section. Every hit is enumerated.

  tally   Read three scorer files, aggregate at majority-of-three per row per
          field, and compute the four anchors plus every floor and denominator
          the convention requires to be published beside them.

FAIL LOUDLY. A row that cannot be parsed, is missing a required field, or
carries a value outside the convention's legal set is NAMED and raises. Nothing
is dropped: a silent skip would under-count exactly like the defect this lane
exists to avoid.

Run (from the repo root):
  "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" docs/_rsc_score/calibrate_rep.py blind --out <path>
  "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" docs/_rsc_score/calibrate_rep.py check --blinded <path>
  "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" docs/_rsc_score/calibrate_rep.py tally --scorers <A.md> <B.md> <C.md>
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROWS_DIR = HERE.parent / "_rescore"

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
# Convention 4.1.
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
SUBVALUE = {"DECAYED", "BORN-WRONG", "OVER-GENERALISED", "UNDER-PROVEN", "UNKNOWN"}
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

# PREREGISTRATION 2.1 and 2.3.
ANCHORS = {
    "inherited_pct": (48.5, 5.0),
    "fix_of_a_fix_pct": (12.1, 5.0),
    "bw_dec_ratio": (2.62, 0.50),
    "gate_or_contract_pct": (85.4, 5.0),
}

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


def split_blocks(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks, current_id, current = [], None, []
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
    fields, key = {}, None
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
                    raise ParseError(f"{row_id}: missing source field {k!r}")
            if fields["id"].strip() != row_id:
                raise ParseError(f"{row_id}: id mismatch ({fields['id']!r})")
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
    dupes = sorted(i for i, c in Counter(r["id"] for r in rows).items() if c > 1)
    if dupes:
        raise ParseError(f"duplicate source row ids: {dupes}")
    if len(rows) != 198:
        raise ParseError(f"expected 198 source rows, parsed {len(rows)}")
    return rows


BLIND_PREAMBLE = """# RC's 198 published rows, BLINDED for the convention-v1 calibration

Generated by `docs/_rsc_score/calibrate_rep.py blind`. Every filed value is
removed: `prevention`, `prevention_why`, `discovery`, `origin_time`, `correct`,
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


def cmd_check(args):
    text = Path(args.blinded).read_text(encoding="utf-8")
    if "## ROWS" not in text:
        raise ParseError("blinded file carries no '## ROWS' marker to scope to")
    lines = text.split("## ROWS", 1)[1].splitlines()
    print("field\tkey-form\tbare-token")
    detail, total_key = [], 0
    for name in STRIPPED:
        key_re = re.compile(r"`" + re.escape(name) + r"`\s*:")
        bare_re = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        key_hits = [ln for ln in lines if key_re.search(ln)]
        bare_hits = [ln for ln in lines if bare_re.search(ln)]
        total_key += len(key_hits)
        print(f"{name}\t{len(key_hits)}\t{len(bare_hits)}")
        detail += [f"KEY   {name}: {ln[:160]}" for ln in key_hits]
        detail += [f"BARE  {name}: {ln[:160]}" for ln in bare_hits]
    print()
    print("value-token sweep")
    for value in sorted(PREVENTION | SUBVALUE | CHAIN_KIND):
        hits = [ln for ln in lines if re.search(r"\b" + re.escape(value) + r"\b", ln)]
        if hits:
            print(f"{value}\t{len(hits)}")
            detail += [f"VALUE {value}: {ln[:160]}" for ln in hits]
    print()
    print(f"key-form hits over all stripped names: {total_key} (0 is the pass)")
    for d in detail:
        print(d)
    return 0


SCORE_LINE = re.compile(r"^ROW\s+(chunk\d+-\d+)\s*\|\s*(.*)$")
REQUIRED_SCORE_KEYS = (
    "prev", "why", "origin", "odf", "fix", "kinds", "cu", "xrow",
    "correct", "instr", "gfck", "sfb", "indiv",
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
        family, sub = "INHERITED", origin.split("/", 1)[1]
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
        bad(f"chain_kind length {len(kinds)} != fix_chain {fix}")
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
        bad("gfck set on a non-GATE-FIRED-CAUGHT row")
    if kv["gfck"] == "DIR":
        if kv["sfb"] not in PREVENTION:
            bad(f"DIRECTED row needs a strict fallback, got {kv['sfb']!r}")
    elif kv["sfb"] != "-":
        bad(f"strict fallback set where it does not apply: {kv['sfb']!r}")
    indiv = kv["indiv"]
    if indiv != "KEEP" and not re.fullmatch(r"(SPLIT:\d+|MERGE:chunk\d+-\d+)", indiv):
        bad(f"illegal indiv {indiv!r}")

    return {
        "id": row_id, "prev": frozenset(prev), "why": kv["why"], "family": family,
        "sub": sub, "odf": kv["odf"] == "Y", "fix": fix, "kinds": kinds,
        "cu": kv["cu"] == "Y", "xrow": int(kv["xrow"]), "correct": kv["correct"],
        "instr": kv["instr"] == "Y", "gfck": kv["gfck"], "sfb": kv["sfb"],
        "indiv": indiv,
    }


def parse_scorer(path):
    rows = {}
    for lineno, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.startswith("ROW "):
            continue
        m = SCORE_LINE.match(line.rstrip())
        if not m:
            raise ParseError(f"{path}:{lineno}: unparseable ROW line: {line[:120]!r}")
        row_id, kv = m.group(1), {}
        for part in m.group(2).split("|"):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise ParseError(f"{path}:{lineno}: {row_id}: no '=' in {part!r}")
            k, v = part.split("=", 1)
            kv[k.strip()] = v.strip()
        if row_id in rows:
            raise ParseError(f"{path}:{lineno}: duplicate row id {row_id}")
        rows[row_id] = validate_score(path, lineno, row_id, kv)
    if len(rows) != 198:
        raise ParseError(f"{path}: expected 198 scored rows, parsed {len(rows)}")
    return rows


def family_label(prev_set):
    """Convention 4.1: TRUE / FALSE / SPLIT over the co-applying values."""
    ins = any(p in IN_FAMILY for p in prev_set)
    outs = any(p in OUT_FAMILY for p in prev_set)
    if ins and outs:
        return "SPLIT"
    return "TRUE" if ins else "FALSE"


def strict_family_label(rec):
    """LW's STRICT standing-check reading (convention 3.4, mandatory column)."""
    prev = set(rec["prev"])
    if "GATE-FIRED-CAUGHT" in prev and rec["gfck"] == "DIR":
        prev.discard("GATE-FIRED-CAUGHT")
        prev.add(rec["sfb"])
    return family_label(frozenset(prev))


def majority(values):
    top, n = Counter(values).most_common(1)[0]
    return (top, True) if n >= 2 else (None, False)


def pct(n, d):
    return 0.0 if not d else round(100.0 * n / d, 1)


def cmd_tally(args):
    scorers = {
        label: parse_scorer(path)
        for label, path in zip(("A", "B", "C"), args.scorers)
    }
    ids = sorted(scorers["A"], key=lambda s: (s.split("-")[0], int(s.split("-")[1])))
    for label in ("B", "C"):
        diff = set(ids) ^ set(scorers[label])
        if diff:
            raise ParseError(f"scorer {label} row-id set differs: {sorted(diff)}")

    out = []
    w = out.append

    maj, nomaj = {}, Counter()
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
        for f in ("odf", "cu", "instr", "xrow"):
            m[f] = majority([r[f] for r in recs])[0]
        m["kinds"] = max(
            [r["kinds"] for r in recs],
            key=lambda k: sum(1 for r in recs if r["kinds"] == k),
        )
        maj[rid] = m

    n = len(ids)
    splits = merges = 0
    for rid in ids:
        iv = maj[rid]["indiv"]
        if not iv or iv == "KEEP":
            continue
        if iv.startswith("SPLIT:"):
            splits += int(iv.split(":")[1]) - 1
        elif iv.startswith("MERGE:"):
            merges += 1
    n_events = n + splits - merges
    n_links = sum(maj[r]["fix"] or 0 for r in ids)

    w("DENOMINATORS (convention 1.2, 1.3)")
    w(f"filed rows {n} | SPLIT extra {splits} | MERGED away {merges}")
    w(f"N_events {n_events} | N_links {n_links} | N_decomp {n_events + n_links}")
    w("GRAIN NOTE: every numerator below is counted over the 198 FILED rows,")
    w("because a scorer emits one value set per filed row and this harness")
    w("cannot score a split row's sub-events separately. Shares are shown over")
    w("BOTH denominators. The verdict uses N_events, which the convention pins.")
    w("")

    inh = sum(1 for r in ids if maj[r]["family"] == "INHERITED")
    odf = sum(1 for r in ids if maj[r]["odf"])
    w("ANCHOR 1 - inherited share, FRESH/INHERITED grain, majority-of-three")
    w(f"INHERITED {inh}: over N_events {pct(inh, n_events)} pct | "
      f"over filed 198 {pct(inh, n)} pct (FLOOR; origin_default_fresh {odf})")
    w("")

    chained = [r for r in ids if maj[r]["fixbool"]]
    non_sa = [
        r for r in chained if any(k != "SAME-ARTIFACT" for k in (maj[r]["kinds"] or []))
    ]
    cu = sum(1 for r in ids if maj[r]["cu"])
    xrow = sum(maj[r]["xrow"] or 0 for r in ids)
    w("ANCHOR 2 - fix-of-a-fix share, boolean grain, majority-of-three")
    w(f"all chains {len(chained)}: over N_events {pct(len(chained), n_events)} pct | "
      f"over filed 198 {pct(len(chained), n)} pct")
    w(f"non-SAME-ARTIFACT {len(non_sa)}: over N_events {pct(len(non_sa), n_events)} pct")
    w(f"(FLOOR; chain_undetermined {cu}, cross-row links {xrow})")
    w("")

    subs = Counter()
    for r in ids:
        fam, sub = maj[r]["origin"] or (None, None)
        if fam == "INHERITED":
            subs[sub] += 1
    bw, dec, unk = subs["BORN-WRONG"], subs["DECAYED"], subs["UNKNOWN"]
    ratio = round(bw / dec, 2) if dec else None
    w("ANCHOR 3 - BORN-WRONG : DECAYED, sub-value grain, majority-of-three")
    w(" | ".join(f"{k} {subs[k]}" for k in sorted(SUBVALUE)))
    w(f"ratio = {ratio} : 1 (UNKNOWN {unk} excluded from both sides)")
    if unk > bw + dec:
        w("UNKNOWN exceeds BORN-WRONG + DECAYED: convention weakness 7 fires, "
          "ratio is UNCOMPUTABLE on this corpus")
    w("")

    fam_counts = Counter(maj[r]["famlabel"] for r in ids)
    strict_counts = Counter(maj[r]["strictfam"] for r in ids)
    w("ANCHOR 4 - gate_or_contract, FAMILY grain, majority-of-three")
    w(f"BROAD  TRUE {fam_counts['TRUE']} / SPLIT {fam_counts['SPLIT']} / "
      f"FALSE {fam_counts['FALSE']}: over N_events "
      f"{pct(fam_counts['TRUE'], n_events)} pct | over filed 198 "
      f"{pct(fam_counts['TRUE'], n)} pct")
    w(f"STRICT TRUE {strict_counts['TRUE']} / SPLIT {strict_counts['SPLIT']} / "
      f"FALSE {strict_counts['FALSE']}: over N_events "
      f"{pct(strict_counts['TRUE'], n_events)} pct")
    w("")

    w("PREVENTION per-value counts, SET grain, majority-of-three")
    pv, multi = Counter(), 0
    for r in ids:
        s = maj[r]["prev"] or frozenset()
        if len(s) > 1:
            multi += 1
        for v in s:
            pv[v] += 1
    for v in sorted(PREVENTION):
        w(f"{v}\t{pv[v]}")
    w(f"sum of per-value counts {sum(pv.values())} (NOT a partition) | "
      f"multi-value rows {multi}")
    w(f"rows with no identifiable refuting instrument: "
      f"{sum(1 for r in ids if not maj[r]['instr'])}")
    w("")

    cc = Counter(maj[r]["correct"] for r in ids)
    w(f"correct: NO {cc['NO']}, UNCLEAR {cc['UNCLEAR']} - a ledger-derived corpus "
      "cannot measure this field, so this is not evidence about refutation quality")
    w("")

    w("NO-MAJORITY ROWS (all three scorers differ), per field")
    w(" | ".join(f"{k} {v}" for k, v in sorted(nomaj.items())) if nomaj else "none")
    w("")

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
        cells, pooled_d = [], 0
        for x, y in pairs:
            d = sum(1 for r in ids if fn(scorers[x][r]) != fn(scorers[y][r]))
            pooled_d += d
            cells.append(f"{x}-{y} {pct(d, n)} pct")
        unan = sum(
            1 for r in ids
            if fn(scorers["A"][r]) == fn(scorers["B"][r]) == fn(scorers["C"][r])
        )
        w(f"{qname}: " + ", ".join(cells)
          + f", pooled {pct(pooled_d, 3 * n)} pct, unanimity {pct(unan, n)} pct")
    w("")

    measured = {
        "inherited_pct": pct(inh, n_events),
        "fix_of_a_fix_pct": pct(len(chained), n_events),
        "bw_dec_ratio": ratio,
        "gate_or_contract_pct": pct(fam_counts["TRUE"], n_events),
    }
    alt = {
        "inherited_pct": pct(inh, n),
        "fix_of_a_fix_pct": pct(len(chained), n),
        "bw_dec_ratio": ratio,
        "gate_or_contract_pct": pct(fam_counts["TRUE"], n),
    }
    w("CALIBRATION VERDICT (PREREGISTRATION 2.3, applied literally over N_events)")
    w("anchor\tpublished\tmeasured\tdelta\ttol\tresult\t(over filed 198)")
    reproduced = 0
    for key, (anchor, tol) in ANCHORS.items():
        got = measured[key]
        if got is None:
            w(f"{key}\t{anchor}\tUNCOMPUTABLE\t-\t+/-{tol}\tMISS\t-")
            continue
        delta = round(got - anchor, 2)
        ok = abs(delta) <= tol
        reproduced += 1 if ok else 0
        w(f"{key}\t{anchor}\t{got}\t{delta:+.2f}\t+/-{tol}\t"
          f"{'REPRODUCES' if ok else 'MISS'}\t{alt[key]}")
    verdict = (
        "CALIBRATED" if reproduced == 4
        else "CALIBRATED-WITH-A-MISS" if reproduced == 3
        else "NOT CALIBRATED"
    )
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
