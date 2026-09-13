"""Tally the three calibration score blocks against RC's four published anchors.

Why this exists rather than `calibrate.py tally`: `calibrate.py`'s `parse_scorer`
expects a `ROW <id> | k=v | ...` line carrying THIRTEEN keys, and expects each
scorer file to hold all 198 rows (majority-of-three over a full overlap). The
files actually produced - `scores_cal_{1,2,3}.md` - are markdown blocks of 66
DISJOINT rows carrying FOUR keys (`prevention`, `origin_time`, `fix_chain`,
`note`). The blind/check half of `calibrate.py` was reused as-is and is not
touched here; only the tally half is unusable against this output shape, so this
script replaces that half and nothing else.

Every figure it prints names its grain and its aggregation rule. It invents
nothing: fields the score files do not carry are reported ABSENT, never defaulted.

Usage:
    python tally_cal.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

BLOCKS = (
    ("S1", HERE / "scores_cal_1.md", 1, 66),
    ("S2", HERE / "scores_cal_2.md", 67, 132),
    ("S3", HERE / "scores_cal_3.md", 133, 198),
)

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
IN_FAMILY = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "CONTRACT",
    "CONTRACT-MISFIRED",
}
OUT_FAMILY = {"PROXY-MEASURE", "ADVERSARY"}
SUBVALUE = {"DECAYED", "BORN-WRONG", "OVER-GENERALISED", "UNDER-PROVEN", "UNKNOWN"}

ANCHORS = {
    "inherited_pct": (48.5, 5.0),
    "fix_of_a_fix_pct": (12.1, 5.0),
    "bw_dec_ratio": (2.62, 0.50),
    "gate_or_contract_pct": (85.4, 5.0),
}

ROW_HEAD = re.compile(r"^##\s+(chunk\d+-\d+)\s*$")
FIELD = re.compile(r"^-\s+`([a-z_]+)`\s*:\s*(.*)$")


class ParseError(Exception):
    pass


def parse_block(label: str, path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    rows: dict[str, dict] = {}
    current = None
    in_ambiguities = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.startswith("## ") and "Ambiguities" in line:
            in_ambiguities = True
            current = None
            continue
        head = ROW_HEAD.match(line)
        if head:
            if in_ambiguities:
                raise ParseError(f"{path}:{lineno}: row heading after ambiguities")
            current = head.group(1)
            if current in rows:
                raise ParseError(f"{path}:{lineno}: duplicate row id {current}")
            rows[current] = {"id": current, "scorer": label}
            continue
        if current is None:
            continue
        field = FIELD.match(line)
        if not field:
            continue
        key, value = field.group(1), field.group(2).strip()
        rows[current][key] = value

    out = {}
    for rid, rec in rows.items():
        for required in ("prevention", "origin_time", "fix_chain"):
            if required not in rec:
                raise ParseError(f"{path}: {rid}: missing {required}")
        prev = [p.strip() for p in rec["prevention"].split(",") if p.strip()]
        if not prev:
            raise ParseError(f"{path}: {rid}: empty prevention set")
        for p in prev:
            if p not in PREVENTION:
                raise ParseError(f"{path}: {rid}: illegal prevention {p!r}")
        if len(set(prev)) != len(prev):
            raise ParseError(f"{path}: {rid}: repeated prevention value")

        origin = rec["origin_time"]
        norm = origin.replace(" ", "")
        if norm == "FRESH":
            family, sub = "FRESH", None
        elif norm.startswith("INHERITED/"):
            family = "INHERITED"
            sub = norm.split("/", 1)[1]
            if sub not in SUBVALUE:
                raise ParseError(f"{path}: {rid}: illegal sub-value {sub!r}")
        else:
            raise ParseError(f"{path}: {rid}: illegal origin_time {origin!r}")

        fix_raw = rec["fix_chain"].strip()
        if not re.fullmatch(r"\d+", fix_raw):
            raise ParseError(f"{path}: {rid}: illegal fix_chain {fix_raw!r}")

        out[rid] = {
            "id": rid,
            "scorer": label,
            "prev": frozenset(prev),
            "family": family,
            "sub": sub,
            "fix": int(fix_raw),
            "note": rec.get("note", ""),
        }
    if len(out) != 66:
        raise ParseError(f"{path}: expected 66 rows, parsed {len(out)}")
    return out


def family_label(prev: frozenset) -> str:
    ins = any(p in IN_FAMILY for p in prev)
    outs = any(p in OUT_FAMILY for p in prev)
    if ins and outs:
        return "SPLIT"
    return "TRUE" if ins else "FALSE"


def pct(n: int, d: int) -> float:
    return 0.0 if not d else round(100.0 * n / d, 1)


def main() -> int:
    rows: dict[str, dict] = {}
    per_block = {}
    for label, path, lo, hi in BLOCKS:
        block = parse_block(label, path)
        per_block[label] = block
        span = f"{lo}-{hi}"
        overlap = set(block) & set(rows)
        if overlap:
            raise ParseError(f"{label} overlaps an earlier block: {sorted(overlap)}")
        rows.update(block)
        print(f"parsed {label} ({path.name}) positions {span}: {len(block)} rows")

    n_events = len(rows)
    print(f"\nN_events (filed rows, no split/merge field collected) = {n_events}")
    if n_events != 198:
        raise ParseError(f"expected 198 rows total, got {n_events}")

    fams = Counter(family_label(r["prev"]) for r in rows.values())
    goc = pct(fams["TRUE"], n_events)
    print("\n-- gate_or_contract, FAMILY grain, per-row TRUE/FALSE/SPLIT (4.1)")
    print(f"   TRUE={fams['TRUE']}  SPLIT={fams['SPLIT']}  FALSE={fams['FALSE']}")
    print(f"   share = TRUE / N_events = {goc} pct")

    inh = sum(1 for r in rows.values() if r["family"] == "INHERITED")
    print("\n-- origin_time, FAMILY grain")
    print(f"   INHERITED={inh}  FRESH={n_events - inh}  share = {pct(inh, n_events)} pct")

    subs = Counter(r["sub"] for r in rows.values() if r["sub"])
    print("\n-- origin_time, FAMILY-plus-SUB-VALUE grain")
    for k in sorted(SUBVALUE):
        print(f"   {k}={subs.get(k, 0)}")
    bw, dec = subs.get("BORN-WRONG", 0), subs.get("DECAYED", 0)
    ratio = round(bw / dec, 2) if dec else None
    print(f"   BORN-WRONG : DECAYED = {bw} : {dec} = {ratio}")

    fofx = sum(1 for r in rows.values() if r["fix"] >= 1)
    n_links = sum(r["fix"] for r in rows.values())
    chain_zero = n_events - fofx
    print("\n-- fix_chain, BOOLEAN grain (fix_chain >= 1) over N_events")
    print(f"   rows with a link = {fofx}  share = {pct(fofx, n_events)} pct")
    print(f"   N_links = {n_links}   N_decomp = N_events + N_links = {n_events + n_links}")
    print(f"   fix_chain == 0 rows = {chain_zero} (FLOOR per 6.1)")
    print(f"   fix_chain distribution = {dict(sorted(Counter(r['fix'] for r in rows.values()).items()))}")

    print("\n-- prevention, PER-VALUE grain (a row contributes to EVERY value)")
    pv = Counter()
    for r in rows.values():
        pv.update(r["prev"])
    for k in sorted(PREVENTION):
        side = "IN" if k in IN_FAMILY else "OUT"
        print(f"   {k:<20} {pv.get(k, 0):>4}  ({side}-FAMILY)")
    print(f"   sum of per-value counts = {sum(pv.values())}  (NOT a partition)")
    multi = [r for r in rows.values() if len(r["prev"]) > 1]
    print(f"   multi-value rows = {len(multi)}")
    print(f"   set-size distribution = {dict(sorted(Counter(len(r['prev']) for r in rows.values()).items()))}")
    for label in ("S1", "S2", "S3"):
        blk = per_block[label]
        m = sum(1 for r in blk.values() if len(r["prev"]) > 1)
        f = Counter(family_label(r["prev"]) for r in blk.values())
        i = sum(1 for r in blk.values() if r["family"] == "INHERITED")
        x = sum(1 for r in blk.values() if r["fix"] >= 1)
        print(
            f"   {label}: multi={m} TRUE={f['TRUE']} SPLIT={f['SPLIT']} "
            f"FALSE={f['FALSE']} INHERITED={i} fix>=1={x}"
        )
    three_plus = sorted(r["id"] for r in rows.values() if len(r["prev"]) >= 3)
    print(f"   rows with a set of THREE or more (3.0 asks these be listed): {three_plus}")

    print("\n-- ANCHOR COMPARISON (pinned tolerances, PREREGISTRATION 2.3)")
    measured = {
        "inherited_pct": pct(inh, n_events),
        "fix_of_a_fix_pct": pct(fofx, n_events),
        "bw_dec_ratio": ratio if ratio is not None else float("nan"),
        "gate_or_contract_pct": goc,
    }
    reproduced = 0
    for name, (anchor, tol) in ANCHORS.items():
        got = measured[name]
        delta = round(got - anchor, 2)
        ok = abs(delta) <= tol
        reproduced += int(ok)
        print(
            f"   {name:<22} measured={got:<8} anchor={anchor:<7} "
            f"delta={delta:+.2f}  tol=+/-{tol}  {'REPRODUCES' if ok else 'MISSES'}"
        )
    if reproduced == 4:
        verdict = "CALIBRATED"
    elif reproduced == 3:
        verdict = "CALIBRATED-WITH-A-MISS"
    else:
        verdict = "NOT CALIBRATED"
    print(f"\n   anchors reproduced: {reproduced} of 4  ->  VERDICT: {verdict}")

    print("\n-- FIELDS THE SCORER OUTPUT SCHEMA DID NOT COLLECT (absent, not zero)")
    for f in (
        "prevention_why (3.1)",
        "chain_kind (6.0)",
        "chain_undetermined (6.1)",
        "cross-row link count (6.1)",
        "gfck MECH/DIR + strict fallback (3.4)",
        "correct (7)",
        "refuting-instrument present (4.x)",
        "indiv KEEP/SPLIT/MERGE (1.3)",
    ):
        print(f"   ABSENT: {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
