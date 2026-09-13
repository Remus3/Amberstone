"""Tally the three blind scorings of the 60-row overlap sample.

Reads `docs/_overlap/scores_{A,B,C}.md`, parses the four scored fields per row,
and computes the four pre-registered agreement statistics for each of the three
pairs (A-B, A-C, B-C) and pooled over all three pairs.

This script does NOT score, re-score or correct anything. It is arithmetic only.
A disagreement is the measurement, never an error to be repaired.

NOTE ADDED 2026-09-12, correcting a claim made ABOUT this script in RESULT.md.
This script computes NO ATTRIBUTION of any kind. The "disagreeing rows" blocks
below are a NAMED-ROW DUMP and nothing more: they say WHICH rows differ, never
WHY. RESULT.md section 4.3 assigns each disagreeing row to a declared
definitional divergence (D1..D8); that assignment is the author's editorial
judgement over this dump, not output of this script, and RESULT.md's original
"Every figure below is script output" claim was false for that section. Do not
cite this script as the source of any 4.3 figure.

FAILS LOUDLY. A row missing from any scorer's file, a field that does not parse,
a duplicate id, an id-order mismatch between files, or a value outside the
convention's declared vocabulary is counted and NAMED, never silently dropped.

Run:
    python docs/_overlap/tally_overlap.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SCORERS = ("A", "B", "C")
PAIRS = (("A", "B"), ("A", "C"), ("B", "C"))

# Convention section 2: the eight values, grouped in and out of family.
# The convention supplies this grouping and NO per-value definitions.
IN_FAMILY = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
    "CONTRACT",
    "CONTRACT-MISFIRED",
}
OUT_FAMILY = {"PROXY-MEASURE", "ADVERSARY"}
LEGAL_PREVENTION = IN_FAMILY | OUT_FAMILY

# Convention section 3: FRESH, or INHERITED with a required sub-value.
LEGAL_ORIGIN = {
    "FRESH",
    "INHERITED / DECAYED",
    "INHERITED / BORN-WRONG",
    "INHERITED / OVER-GENERALISED",
}

ROW_HEADING = re.compile(r"^## (chunk\d+-\d+)\s*$")
FIELD = re.compile(r"^- `([a-z_]+)`: (.+?)\s*$")

REQUIRED_FIELDS = ("prevention", "origin_time", "fix_chain")


class TallyError(Exception):
    """Raised with every problem found, all at once, so none is hidden."""


def parse_scorer(path: Path) -> tuple[list[str], dict[str, dict[str, object]]]:
    """Return (ids in file order, id -> parsed fields). Raises on any defect."""
    problems: list[str] = []
    order: list[str] = []
    rows: dict[str, dict[str, object]] = {}
    current: str | None = None

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        heading = ROW_HEADING.match(raw)
        if heading:
            current = heading.group(1)
            if current in rows:
                problems.append(f"{path.name}:{lineno} duplicate id {current}")
            rows[current] = {}
            order.append(current)
            continue
        if raw.startswith("## "):
            # A non-row section (for example "Ambiguities I resolved") ends rows.
            current = None
            continue
        field = FIELD.match(raw)
        if not field or current is None:
            continue
        name, value = field.group(1), field.group(2)
        if name not in REQUIRED_FIELDS:
            continue
        if name in rows[current]:
            problems.append(f"{path.name}:{lineno} duplicate field {name} on {current}")
        if name == "prevention":
            values = [v.strip() for v in value.split(",")]
            for v in values:
                if v not in LEGAL_PREVENTION:
                    problems.append(
                        f"{path.name}:{lineno} {current} prevention value "
                        f"'{v}' is outside the convention's eight"
                    )
            if len(set(values)) != len(values):
                problems.append(
                    f"{path.name}:{lineno} {current} prevention set repeats a value"
                )
            rows[current][name] = frozenset(values)
        elif name == "origin_time":
            if value not in LEGAL_ORIGIN:
                problems.append(
                    f"{path.name}:{lineno} {current} origin_time value "
                    f"'{value}' is outside the convention's vocabulary"
                )
            rows[current][name] = value
        elif name == "fix_chain":
            if not re.fullmatch(r"\d+", value):
                problems.append(
                    f"{path.name}:{lineno} {current} fix_chain '{value}' is not "
                    f"a non-negative integer"
                )
                rows[current][name] = None
            else:
                rows[current][name] = int(value)

    for rid in order:
        for name in REQUIRED_FIELDS:
            if name not in rows[rid]:
                problems.append(f"{path.name} row {rid} is missing field {name}")

    if problems:
        raise TallyError(
            f"{len(problems)} parse problem(s) in {path.name}:\n  "
            + "\n  ".join(problems)
        )
    return order, rows


def family(values: frozenset[str]) -> str:
    """Convention section 2: TRUE all in-family, FALSE all out, SPLIT straddling."""
    ins = any(v in IN_FAMILY for v in values)
    outs = any(v in OUT_FAMILY for v in values)
    if ins and outs:
        return "SPLIT"
    if ins:
        return "TRUE"
    return "FALSE"


def pct(num: int, den: int) -> float:
    return 100.0 * num / den


def main() -> int:
    parsed = {}
    for s in SCORERS:
        path = HERE / f"scores_{s}.md"
        if not path.exists():
            raise TallyError(f"missing scorer file {path}")
        parsed[s] = parse_scorer(path)

    orders = {s: parsed[s][0] for s in SCORERS}
    ref = orders["A"]
    problems = []
    if len(ref) != 60:
        problems.append(f"scorer A carries {len(ref)} rows, expected 60")
    for s in ("B", "C"):
        if orders[s] != ref:
            missing = [i for i in ref if i not in orders[s]]
            extra = [i for i in orders[s] if i not in ref]
            problems.append(
                f"scorer {s} id sequence differs from A "
                f"(len {len(orders[s])}; missing {missing}; extra {extra})"
            )
    if problems:
        raise TallyError("id-set check failed:\n  " + "\n  ".join(problems))

    ids = ref
    n = len(ids)
    rows = {s: parsed[s][1] for s in SCORERS}

    stats = {
        "prevention SET identity": lambda r: r["prevention"],
        "prevention FAMILY": lambda r: family(r["prevention"]),
        "origin_time (family+sub-value)": lambda r: r["origin_time"],
        "origin_time (family only)": lambda r: r["origin_time"].split(" / ")[0],
        "fix_chain >= 1": lambda r: (r["fix_chain"] or 0) >= 1,
    }

    out: list[str] = []
    out.append(f"rows compared: {n}; scorers: {', '.join(SCORERS)}; "
               f"pairs: {len(PAIRS)}; pairwise comparisons pooled: {n * len(PAIRS)}")
    out.append("")

    disagreements: dict[str, dict[tuple[str, str], list[str]]] = {}
    pooled_counts: dict[str, int] = {}

    for label, key in stats.items():
        out.append(f"== {label} ==")
        disagreements[label] = {}
        agree_total = 0
        for x, y in PAIRS:
            agree = [i for i in ids if key(rows[x][i]) == key(rows[y][i])]
            differ = [i for i in ids if key(rows[x][i]) != key(rows[y][i])]
            disagreements[label][(x, y)] = differ
            agree_total += len(agree)
            out.append(
                f"  {x}-{y}: agree {len(agree)}/{n} = {pct(len(agree), n):.1f} pct; "
                f"disagree {len(differ)}/{n} = {pct(len(differ), n):.1f} pct"
            )
        den = n * len(PAIRS)
        pooled_counts[label] = den - agree_total
        out.append(
            f"  pooled: agree {agree_total}/{den} = {pct(agree_total, den):.1f} pct; "
            f"disagree {den - agree_total}/{den} = "
            f"{pct(den - agree_total, den):.1f} pct"
        )
        unan = sum(
            1
            for i in ids
            if key(rows["A"][i]) == key(rows["B"][i]) == key(rows["C"][i])
        )
        out.append(f"  three-way unanimous: {unan}/{n} = {pct(unan, n):.1f} pct")
        out.append("")

    # Pre-registered verdict, section 7a, applied to SET identity only.
    set_lab = "prevention SET identity"
    d = {p: len(disagreements[set_lab][p]) for p in PAIRS}
    pair_rates = {p: pct(d[p], n) for p in PAIRS}
    pooled_rate = pct(sum(d.values()), n * len(PAIRS))
    out.append("== PRE-REGISTERED VERDICT (PREREGISTRATION.md section 7a) ==")
    for p in PAIRS:
        out.append(f"  d_{p[0]}{p[1]} = {d[p]} of {n} = {pair_rates[p]:.1f} pct")
    out.append(f"  pooled p = {sum(d.values())} of {n * len(PAIRS)} = "
               f"{pooled_rate:.4f} pct")
    confirmed = pooled_rate >= 15.0 and all(r >= 10.0 for r in pair_rates.values())
    refuted = all(r < 10.0 for r in pair_rates.values())
    verdict = "CONFIRMED" if confirmed else "REFUTED" if refuted else "INDETERMINATE"
    out.append(f"  VERDICT: {verdict}")
    out.append("")

    # SPLIT counts per scorer (convention section 8 check).
    out.append("== SPLIT count per scorer (convention section 8) ==")
    for s in SCORERS:
        splits = [i for i in ids if family(rows[s][i]["prevention"]) == "SPLIT"]
        multi = [i for i in ids if len(rows[s][i]["prevention"]) > 1]
        out.append(
            f"  {s}: SPLIT {len(splits)}/{n} ({', '.join(splits) or 'none'}); "
            f"multi-value sets {len(multi)}"
        )
    out.append("")

    # Named disagreeing rows, so attribution can be done against the record.
    out.append("== disagreeing rows, per statistic, per pair ==")
    for label in stats:
        out.append(f"  {label}:")
        for p in PAIRS:
            rowsd = disagreements[label][p]
            out.append(f"    {p[0]}-{p[1]} ({len(rowsd)}): "
                       f"{', '.join(rowsd) or 'none'}")
    out.append("")

    # Every row where any pair's prevention SET differs, with all three values.
    out.append("== prevention SET: every row with any pairwise difference ==")
    union = sorted(
        {i for p in PAIRS for i in disagreements[set_lab][p]},
        key=ids.index,
    )
    for i in union:
        cells = " | ".join(
            f"{s}={'+'.join(sorted(rows[s][i]['prevention']))}" for s in SCORERS
        )
        fams = " | ".join(f"{s}={family(rows[s][i]['prevention'])}" for s in SCORERS)
        out.append(f"  {i}: {cells}   [{fams}]")
    out.append(f"  total distinct rows with any SET disagreement: {len(union)}/{n}")

    text = "\n".join(out)
    print(text)
    nonascii = [c for c in text if ord(c) > 0x7E]
    if nonascii:
        raise TallyError(f"non-ASCII output characters: {sorted(set(nonascii))}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TallyError as exc:
        print(f"TALLY FAILED: {exc}", file=sys.stderr)
        sys.exit(2)
