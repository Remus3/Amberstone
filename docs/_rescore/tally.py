"""Tally the four per-event re-score row files against REFUTATION_TAXONOMY_PIN v1.2.

Read-only. Parses docs/_rescore/chunk{1,2,3,4}_rows.md, validates every field
against the pin's legal value set (sections 2 to 6), and prints the
distributions. Designed to FAIL LOUDLY: a row that cannot be parsed, is missing
a required field, or carries an illegal value is COUNTED AND NAMED, never
dropped. A silent skip would under-count exactly like the defect this job
exists to avoid.

Run:
  "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" \
      "C:\\Riot Commander\\docs\\_rescore\\tally.py"
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Scorer-claimed event counts, taken from the task brief. Deliberately NOT
# trusted: they are compared against the parsed counts and every mismatch is
# named.
CLAIMED = {"chunk1": 60, "chunk2": 48, "chunk3": 47, "chunk4": 43}

# Pin section 2.
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
GATE_FAMILY = {
    "GATE-EXISTING",
    "GATE-ABSENT",
    "GATE-FIRED-IGNORED",
    "GATE-FIRED-CAUGHT",
}
# Pin section 3.
DISCOVERY = {"CODE-READ", "RUN", "SIBLING", "OPERATOR", "CI", "SELF-AUDIT", "RESEARCH"}
# Pin section 4.
INHERITED_SUB = {"DECAYED", "BORN-WRONG", "OVER-GENERALISED", "UNDER-PROVEN", "UNKNOWN"}
# Pin section 5.
CORRECT = {"YES", "NO", "UNCLEAR"}
# Pin section 6.
CHAIN_KIND = {"SELF", "INTRODUCED", "SIBLING-SURFACE", "INHERITED-SHARED", "SAME-ARTIFACT"}
CHAIN_KIND_IN_RATIO = CHAIN_KIND - {"SAME-ARTIFACT"}

REQUIRED = (
    "id",
    "entry",
    "claim",
    "quote",
    "refuter",
    "prevention",
    "discovery",
    "origin_time",
    "correct",
    "fix_chain",
)

WINDOW_LO, WINDOW_HI = 1365, 1406

ROW_HEADING = re.compile(r"^##\s+(chunk\d+-\d+)\s*$")
ANY_HEADING = re.compile(r"^##\s+(.*)$")
FIELD_LINE = re.compile(r"^-\s+`([a-z_]+)`:\s*(.*)$")


# Kinds that do NOT threaten the count: a markdown horizontal rule between
# rows, a non-row prose heading, and a free-text "- Note ..." bullet that
# carries no backticked field key. Everything else is BLOCKING and means a row
# may be mis-counted or mis-valued.
BENIGN_KINDS = {"SEPARATOR", "NON-ROW-HEADING", "NOTE-LINE"}


class Problem:
    def __init__(self, chunk, row_id, kind, detail):
        self.chunk = chunk
        self.row_id = row_id
        self.kind = kind
        self.detail = detail

    @property
    def blocking(self):
        return self.kind not in BENIGN_KINDS

    def __str__(self):
        return "{}\t{}\t{}\t{}\t{}".format(
            "BLOCKING" if self.blocking else "benign",
            self.chunk,
            self.row_id,
            self.kind,
            self.detail,
        )


def split_blocks(path, chunk):
    """Yield (row_id, [lines]) per '## chunk-NN' heading.

    Non-row '##' headings are reported as skipped-prose, not silently dropped.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    blocks = []
    prose_headings = []
    current_id = None
    current = []
    for line in lines:
        m = ANY_HEADING.match(line)
        if m:
            if current_id is not None:
                blocks.append((current_id, current))
            rm = ROW_HEADING.match(line)
            if rm:
                current_id = rm.group(1)
                current = []
            else:
                current_id = None
                current = []
                prose_headings.append(m.group(1).strip())
            continue
        if current_id is not None:
            current.append(line)
    if current_id is not None:
        blocks.append((current_id, current))
    return blocks, prose_headings


def parse_fields(body_lines):
    """Field lines, with continuation lines folded into the previous value."""
    fields = {}
    order = []
    dupes = []
    orphan_lines = []
    key = None
    for line in body_lines:
        m = FIELD_LINE.match(line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key in fields:
                dupes.append(key)
            else:
                order.append(key)
            fields[key] = value
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if key is not None and (line.startswith("  ") or line.startswith("\t")):
            fields[key] = (fields[key] + " " + stripped).strip()
        else:
            orphan_lines.append(stripped)
    return fields, order, dupes, orphan_lines


def head_token(value):
    """First whitespace/parenthesis-delimited token of a field value."""
    v = value.strip()
    v = v.split("(")[0]
    v = v.split(" - ")[0]
    return v.strip().rstrip(".,").strip()


def parse_rows(chunk, path, problems):
    blocks, prose_headings = split_blocks(path, chunk)
    for h in prose_headings:
        problems.append(Problem(chunk, "-", "NON-ROW-HEADING", f"skipped prose heading: {h!r}"))
    rows = []
    for row_id, body in blocks:
        fields, _order, dupes, orphans = parse_fields(body)
        for d in dupes:
            problems.append(Problem(chunk, row_id, "DUPLICATE-FIELD", d))
        for o in orphans:
            if set(o) == {"-"} and len(o) >= 3:
                kind = "SEPARATOR"
            elif o.startswith("- ") and "`" not in o.split(":")[0]:
                kind = "NOTE-LINE"
            else:
                kind = "UNPARSED-LINE"
            problems.append(Problem(chunk, row_id, kind, o[:110]))
        missing = [k for k in REQUIRED if k not in fields]
        for k in missing:
            problems.append(Problem(chunk, row_id, "MISSING-FIELD", k))

        rec = {"chunk": chunk, "id": row_id, "raw": fields, "malformed": bool(missing)}

        # id consistency
        if fields.get("id") and fields["id"].strip() != row_id:
            problems.append(
                Problem(chunk, row_id, "ID-MISMATCH", "heading {!r} vs field {!r}".format(row_id, fields["id"]))
            )

        # entry
        ent = fields.get("entry", "")
        em = re.match(r"^(\d+)\b", ent.strip())
        if not em:
            problems.append(Problem(chunk, row_id, "BAD-ENTRY", repr(ent)))
            rec["entry"] = None
            rec["malformed"] = True
        else:
            rec["entry"] = int(em.group(1))
            if not (WINDOW_LO <= rec["entry"] <= WINDOW_HI):
                problems.append(
                    Problem(chunk, row_id, "ENTRY-OUT-OF-WINDOW", str(rec["entry"]))
                )

        # prevention
        prev = head_token(fields.get("prevention", ""))
        if prev not in PREVENTION:
            problems.append(Problem(chunk, row_id, "ILLEGAL-prevention", repr(fields.get("prevention"))))
            rec["malformed"] = True
        rec["prevention"] = prev

        # prevention_why required by pin section 2 when GATE-EXISTING
        rec["prevention_why"] = fields.get("prevention_why")
        if prev == "GATE-EXISTING" and not rec["prevention_why"]:
            problems.append(
                Problem(chunk, row_id, "MISSING-prevention_why", "GATE-EXISTING without prevention_why")
            )

        # discovery
        disc = head_token(fields.get("discovery", ""))
        if disc not in DISCOVERY:
            problems.append(Problem(chunk, row_id, "ILLEGAL-discovery", repr(fields.get("discovery"))))
            rec["malformed"] = True
        rec["discovery"] = disc

        # origin_time
        ot_raw = fields.get("origin_time", "").strip()
        ot_head = ot_raw.split("(")[0].strip().rstrip(".")
        parts = [p.strip() for p in ot_head.split("/")]
        family = parts[0] if parts else ""
        sub = parts[1] if len(parts) > 1 else None
        if family == "FRESH":
            if sub:
                problems.append(Problem(chunk, row_id, "ILLEGAL-origin_time", repr(ot_raw)))
        elif family == "INHERITED":
            if sub not in INHERITED_SUB:
                problems.append(
                    Problem(chunk, row_id, "ILLEGAL-origin_time-sub", repr(ot_raw))
                )
                rec["malformed"] = True
        else:
            problems.append(Problem(chunk, row_id, "ILLEGAL-origin_time", repr(ot_raw)))
            rec["malformed"] = True
        rec["origin_family"] = family
        rec["origin_sub"] = sub

        # correct
        cor = head_token(fields.get("correct", ""))
        if cor not in CORRECT:
            problems.append(Problem(chunk, row_id, "ILLEGAL-correct", repr(fields.get("correct"))))
            rec["malformed"] = True
        rec["correct"] = cor

        # fix_chain
        fc_raw = fields.get("fix_chain", "").strip()
        fm = re.match(r"^(\d+)\b", fc_raw)
        if not fm:
            problems.append(Problem(chunk, row_id, "BAD-fix_chain", repr(fc_raw)))
            rec["fix_chain"] = None
            rec["malformed"] = True
        else:
            rec["fix_chain"] = int(fm.group(1))

        # chain_kind: either its own field or inline in fix_chain as
        # "(chain_kind: X)" or the abbreviated "(X)".
        ck = None
        if fields.get("chain_kind"):
            ck = head_token(fields["chain_kind"]).upper()
        else:
            cm = re.search(r"\((?:chain_kind:\s*)?([A-Z][A-Z-]+)\)", fc_raw)
            if cm:
                ck = cm.group(1)
        rec["chain_kind"] = ck
        if rec["fix_chain"] and rec["fix_chain"] >= 1:
            if ck is None:
                problems.append(
                    Problem(chunk, row_id, "MISSING-chain_kind", "fix_chain={}".format(rec["fix_chain"]))
                )
            elif ck not in CHAIN_KIND:
                problems.append(Problem(chunk, row_id, "ILLEGAL-chain_kind", repr(ck)))
                rec["malformed"] = True
        elif ck is not None and rec["fix_chain"] == 0:
            problems.append(
                Problem(chunk, row_id, "CHAIN-KIND-ON-ZERO", repr(ck))
            )

        rec["uncertain"] = "uncertain" in fields
        rec["pin_gap"] = "pin_gap" in fields
        rows.append(rec)
    return rows


def dist_table(rows, key, universe=None):
    c = Counter(r[key] for r in rows)
    keys = sorted(universe) if universe else sorted(c)
    return [(k, c.get(k, 0)) for k in keys], c


def pct(n, d):
    return 0.0 if not d else round(100.0 * n / d, 1)


def main():
    problems = []
    per_chunk = {}
    for n in (1, 2, 3, 4):
        chunk = f"chunk{n}"
        path = HERE / (f"{chunk}_rows.md")
        if not path.exists():
            problems.append(Problem(chunk, "-", "MISSING-FILE", str(path)))
            per_chunk[chunk] = []
            continue
        per_chunk[chunk] = parse_rows(chunk, path, problems)

    allrows = [r for rs in per_chunk.values() for r in rs]

    out = []
    w = out.append
    w("PARSED EVENT COUNTS")
    w("chunk\tclaimed\tparsed\tmatch")
    for chunk in ("chunk1", "chunk2", "chunk3", "chunk4"):
        p = len(per_chunk[chunk])
        c = CLAIMED[chunk]
        w(f"{chunk}\t{c:d}\t{p:d}\t{'YES' if c == p else f'NO (delta {p - c:+d})'}")
    w("TOTAL\t{:d}\t{:d}\t{}".format(sum(CLAIMED.values()), len(allrows),
                                     "YES" if sum(CLAIMED.values()) == len(allrows) else "NO"))
    w("")

    nblock = sum(1 for p in problems if p.blocking)
    w(f"PARSE PROBLEMS: {len(problems):d} total over {len(allrows):d} rows - "
      f"{nblock:d} BLOCKING, {len(problems) - nblock:d} benign")
    w("severity\tchunk\trow\tkind\tdetail")
    for p in problems:
        w(str(p))
    w("malformed rows retained in the tally (never dropped): {:d}"
      .format(sum(1 for r in allrows if r["malformed"])))
    w("")

    def emit(title, key, universe):
        w(title)
        w("value\t" + "\t".join(["chunk1", "chunk2", "chunk3", "chunk4", "TOTAL", "pct"]))
        counters = {c: Counter(r[key] for r in per_chunk[c]) for c in per_chunk}
        tot = Counter(r[key] for r in allrows)
        vals = sorted(set(list(universe) + [v for v in tot if v not in universe]),
                      key=lambda v: (v is None, str(v)))
        for v in vals:
            row = [counters[c].get(v, 0) for c in ("chunk1", "chunk2", "chunk3", "chunk4")]
            w("{}\t{}\t{:d}\t{}".format(v, "\t".join(str(x) for x in row), tot.get(v, 0),
                                        pct(tot.get(v, 0), len(allrows))))
        w("")

    emit("PREVENTION DISTRIBUTION", "prevention", sorted(PREVENTION))
    emit("DISCOVERY DISTRIBUTION", "discovery", sorted(DISCOVERY))
    emit("CORRECT DISTRIBUTION", "correct", sorted(CORRECT))

    # origin_time: family plus required sub-value
    w("ORIGIN_TIME DISTRIBUTION")
    w("value\tchunk1\tchunk2\tchunk3\tchunk4\tTOTAL\tpct")
    labels = ["FRESH"] + ["INHERITED / " + s for s in sorted(INHERITED_SUB)]

    def label_of(r):
        return "FRESH" if r["origin_family"] == "FRESH" else "{} / {}".format(r["origin_family"], r["origin_sub"])

    counters = {c: Counter(label_of(r) for r in per_chunk[c]) for c in per_chunk}
    tot = Counter(label_of(r) for r in allrows)
    for v in labels + [k for k in sorted(tot) if k not in labels]:
        row = [counters[c].get(v, 0) for c in ("chunk1", "chunk2", "chunk3", "chunk4")]
        w("{}\t{}\t{:d}\t{}".format(v, "\t".join(str(x) for x in row), tot.get(v, 0),
                                    pct(tot.get(v, 0), len(allrows))))
    w("")

    inherited = [r for r in allrows if r["origin_family"] == "INHERITED"]
    dec = sum(1 for r in inherited if r["origin_sub"] == "DECAYED")
    bw = sum(1 for r in inherited if r["origin_sub"] == "BORN-WRONG")
    w("INHERITED SPLIT")
    w(f"inherited total: {len(inherited):d} of {len(allrows):d} ({pct(len(inherited), len(allrows))} pct)")
    w(f"DECAYED: {dec:d}")
    w(f"BORN-WRONG: {bw:d}")
    w("BORN-WRONG : DECAYED ratio = %s : 1" % (round(bw / dec, 2) if dec else "inf"))
    w("")

    # fix_chain
    w("FIX_CHAIN DISTRIBUTION")
    w("value\tchunk1\tchunk2\tchunk3\tchunk4\tTOTAL\tpct")
    counters = {c: Counter(r["fix_chain"] for r in per_chunk[c]) for c in per_chunk}
    tot = Counter(r["fix_chain"] for r in allrows)
    for v in sorted(tot, key=lambda x: (x is None, x)):
        row = [counters[c].get(v, 0) for c in ("chunk1", "chunk2", "chunk3", "chunk4")]
        w("{}\t{}\t{:d}\t{}".format(v, "\t".join(str(x) for x in row), tot.get(v, 0),
                                    pct(tot.get(v, 0), len(allrows))))
    w("")

    w("CHAIN_KIND DISTRIBUTION (rows with fix_chain >= 1)")
    chained = [r for r in allrows if r["fix_chain"] and r["fix_chain"] >= 1]
    ckc = Counter(r["chain_kind"] for r in chained)
    for k in sorted(CHAIN_KIND) + [k for k in sorted(ckc, key=str) if k not in CHAIN_KIND]:
        w(f"{k}\t{ckc.get(k, 0):d}")
    w("")

    w("FIX-OF-A-FIX RATE (pin section 6)")
    incl = len(chained)
    same_artifact = sum(1 for r in chained if r["chain_kind"] == "SAME-ARTIFACT")
    excl = incl - same_artifact
    w(f"rows with fix_chain >= 1, SAME-ARTIFACT INCLUDED: {incl:d} of {len(allrows):d} = {pct(incl, len(allrows))} pct")
    w(f"rows with fix_chain >= 1, SAME-ARTIFACT EXCLUDED: {excl:d} of {len(allrows):d} = {pct(excl, len(allrows))} pct")
    w(f"SAME-ARTIFACT rows found: {same_artifact:d}")
    w("chain links total (sum of fix_chain, in-ratio kinds): {:d}"
      .format(sum(r["fix_chain"] for r in chained if r["chain_kind"] in CHAIN_KIND_IN_RATIO)))
    w("")

    w("UNCERTAIN / PIN_GAP")
    w("field\tchunk1\tchunk2\tchunk3\tchunk4\tTOTAL\tpct")
    for f in ("uncertain", "pin_gap"):
        row = [sum(1 for r in per_chunk[c] if r[f]) for c in ("chunk1", "chunk2", "chunk3", "chunk4")]
        t = sum(row)
        w("{}\t{}\t{:d}\t{}".format(f, "\t".join(str(x) for x in row), t, pct(t, len(allrows))))
    w("")

    gate = sum(1 for r in allrows if r["prevention"] in GATE_FAMILY)
    contract = sum(1 for r in allrows if r["prevention"] == "CONTRACT")
    contract_misfired = sum(1 for r in allrows if r["prevention"] == "CONTRACT-MISFIRED")
    w("GATE FAMILY + CONTRACT (fleet-comparable figure)")
    w(f"GATE family total: {gate:d} = {pct(gate, len(allrows))} pct")
    w(f"CONTRACT total: {contract:d} = {pct(contract, len(allrows))} pct")
    w(f"combined GATE + CONTRACT: {gate + contract:d} of {len(allrows):d} = {pct(gate + contract, len(allrows))} pct")
    w(f"(CONTRACT-MISFIRED is a distinct pin value, {contract_misfired:d} rows = "
      f"{pct(contract_misfired, len(allrows))} pct; shown separately, "
      "not folded into CONTRACT)")
    w(f"combined incl CONTRACT-MISFIRED: {gate + contract + contract_misfired:d} = "
      f"{pct(gate + contract + contract_misfired, len(allrows))} pct")
    w("")

    # SANITY CHECKS
    w("SANITY CHECKS")
    entries = [r["entry"] for r in allrows if r["entry"] is not None]
    oob = sorted({e for e in entries if not (WINDOW_LO <= e <= WINDOW_HI)})
    w("1. entry in {:d}-{:d}: {}{}".format(WINDOW_LO, WINDOW_HI,
                                           "PASS" if not oob else "FAIL",
                                           "" if not oob else f" out-of-window: {oob}"))
    ids = [r["id"] for r in allrows]
    dup_ids = sorted([i for i, n in Counter(ids).items() if n > 1])
    w("2. duplicate id: {}{}".format("PASS (none)" if not dup_ids else "FAIL", "" if not dup_ids else f" {dup_ids}"))

    ranges = {}
    for c in ("chunk1", "chunk2", "chunk3", "chunk4"):
        es = [r["entry"] for r in per_chunk[c] if r["entry"] is not None]
        ranges[c] = (min(es), max(es)) if es else (None, None)
    w("3. per-chunk entry ranges:")
    for c, (lo, hi) in ranges.items():
        w("   {}: {}-{} ({:d} distinct entries)".format(c, lo, hi,
          len({r["entry"] for r in per_chunk[c] if r["entry"] is not None})))
    overlaps = []
    names = list(ranges)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = ranges[names[i]], ranges[names[j]]
            if None in a or None in b:
                continue
            if a[0] <= b[1] and b[0] <= a[1]:
                overlaps.append((names[i], names[j], a, b))
    w("   overlap: %s" % ("PASS (none)" if not overlaps else f"FAIL {overlaps}"))

    covered = sorted(set(entries))
    window = list(range(WINDOW_LO, WINDOW_HI + 1))
    missing = [e for e in window if e not in set(covered)]
    w(f"4. window coverage: {len(covered):d} of {len(window):d} entries carry at least one event")
    w("   entries with ZERO events: %s" % (missing if missing else "none"))
    percentry = Counter(entries)
    w(f"   events per entry (min/median/max): {min(percentry.values()):d} / "
      f"{sorted(percentry.values())[len(percentry) // 2]:d} / {max(percentry.values()):d}")
    w("")
    w("EVENTS PER ENTRY")
    w("entry\tevents\tchunk")
    owner = defaultdict(set)
    for r in allrows:
        if r["entry"] is not None:
            owner[r["entry"]].add(r["chunk"])
    for e in window:
        w("{:d}\t{:d}\t{}".format(e, percentry.get(e, 0), ",".join(sorted(owner.get(e, ["-"])))))

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
