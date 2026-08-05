#!/usr/bin/env python
"""Replay recorded live-Haiku ARAM responses through the REAL coach parser.

The Haiku-to-ZERO program scores a deterministic ARAM coach against the live
Haiku coach. The deterministic column is reproducible offline; the live column
was not, because the only durable record of a live response is the
``ARAM Haiku raw`` line the coach writes to ``logs/``. That made every parser
question unanswerable after the fact - most sharply for ``choices``, where a
zero yield could mean the parser dropped it, the model omitted it, or the log
clipped it, with no way to tell the three apart.

This tool answers the question offline. It reads those log lines back, feeds
each one through ``coaches._base_coach.parse_fields`` and
``core.coach_output.CoachOutput.from_fields`` - the actual production parse, not
a copy of it, because a replay through a reimplementation proves nothing about
the real one - and reports per-field yield.

The bucket that matters is TRUNCATION. The log header carries the response's
true character count while the body that follows may have been clipped, so a
record whose body is shorter than its declared length is evidence-limited: it
says nothing about what the model emitted. Those records are counted apart from
genuine misses. Folding them together is what made the live column look empty.

READ-ONLY by construction: this opens files for reading and writes only to
stdout. It must never touch a file the runtime reads.

Usage:
    python tools/aram_raw_replay.py                    # all of logs/
    python tools/aram_raw_replay.py logs/2026-08-02.log.2 logs/2026-08-02.log.3
    python tools/aram_raw_replay.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coaches._base_coach import parse_fields  # noqa: E402
from core.coach_output import CoachOutput  # noqa: E402

# The exact key list coaches/aram_coach.py hands to parse_fields. Replaying
# with a different list would measure a parse the runtime never performs.
ARAM_KEYS = [
    "action", "immediate", "fight rule",
    "reset / item", "risk", "item build", "item extra",
    "item reasons", "choices",
]

# The coach logs one record per response with newlines flattened to " | " and
# the TRUE length in the header. Deliberately anchored on the message text
# rather than the "[aram_coach.py:NNNN]" frame, which drifts with every edit.
_RAW_RE = re.compile(r"ARAM Haiku raw \((\d+) chars\): (.*)$")

# The flattening the coach applies before writing the line.
_NEWLINE_MARKER = " | "


@dataclass(frozen=True)
class RawRecord:
    """One recorded live response, restored to its pre-log shape."""

    source: str
    lineno: int
    declared_chars: int
    body: str

    @property
    def truncated(self) -> bool:
        """True when the log kept less than the response actually contained."""
        return len(self.body) < self.declared_chars

    @property
    def source_kind(self) -> str:
        return "truncated" if self.truncated else "complete"


@dataclass
class ReplayReport:
    """Aggregate outcome of replaying a set of records."""

    total: int = 0
    truncated: int = 0
    parsed: int = 0
    no_fields: int = 0
    choices_decoded: int = 0
    choices_undecodable_truncated: int = 0
    choices_undecodable_complete: int = 0
    choices_missing_truncated: int = 0
    choices_missing_clean: int = 0
    field_yield: dict = field(default_factory=dict)
    clean_misses: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "truncated": self.truncated,
            "parsed": self.parsed,
            "no_fields": self.no_fields,
            "choices_decoded": self.choices_decoded,
            "choices_undecodable_truncated":
                self.choices_undecodable_truncated,
            "choices_undecodable_complete": self.choices_undecodable_complete,
            "choices_missing_truncated": self.choices_missing_truncated,
            "choices_missing_clean": self.choices_missing_clean,
            "field_yield": dict(self.field_yield),
        }


def discover_logs(logs_dir: Path) -> list:
    """Every log file under `logs_dir`, rotated ``.log.N`` siblings included."""
    if not logs_dir.is_dir():
        return []
    out = [p for p in logs_dir.iterdir()
           if p.is_file() and (p.suffix == ".log" or ".log." in p.name)]
    return sorted(out)


def iter_raw_records(paths):
    """Yield a RawRecord for every ``ARAM Haiku raw`` line in `paths`."""
    for p in paths:
        path = Path(p)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            m = _RAW_RE.search(line)
            if not m:
                continue
            declared = int(m.group(1))
            body = m.group(2).replace(_NEWLINE_MARKER, "\n")
            yield RawRecord(source=str(path), lineno=i,
                            declared_chars=declared, body=body)


def replay_one(rec: RawRecord) -> CoachOutput:
    """Run one record through the production parse chain."""
    return CoachOutput.from_fields(parse_fields(rec.body, ARAM_KEYS))


def replay(records) -> ReplayReport:
    """Replay every record and bucket the outcomes."""
    rep = ReplayReport()
    rep.field_yield = {k: 0 for k in ARAM_KEYS}
    for rec in records:
        rep.total += 1
        if rec.truncated:
            rep.truncated += 1
        flds = parse_fields(rec.body, ARAM_KEYS)
        if not flds:
            rep.no_fields += 1
        else:
            rep.parsed += 1
        for k, v in flds.items():
            if k in rep.field_yield and str(v).strip():
                rep.field_yield[k] += 1
        raw_choices = str(flds.get("choices", "") or "").strip()
        decoded = CoachOutput.from_fields(flds).choices
        if decoded:
            rep.choices_decoded += 1
        elif raw_choices:
            # The field WAS logged but did not decode. On a truncated record
            # that is still evidence-limited: the array was cut mid-payload, so
            # it is the LOG that is malformed, not the model's output. Only an
            # undecodable value on a complete record is a real emit finding.
            if rec.truncated:
                rep.choices_undecodable_truncated += 1
            else:
                rep.choices_undecodable_complete += 1
        elif rec.truncated:
            rep.choices_missing_truncated += 1
        else:
            rep.choices_missing_clean += 1
            rep.clean_misses.append(rec)
    return rep


def format_report(rep: ReplayReport) -> str:
    lines = [
        "ARAM live-Haiku raw replay",
        f"  records found            : {rep.total}",
        f"  truncated in the log     : {rep.truncated}",
        f"  yielded >=1 field        : {rep.parsed}",
        f"  yielded no fields at all : {rep.no_fields}",
        "",
        f"  choices decoded          : {rep.choices_decoded}",
        f"  choices cut mid-array    : {rep.choices_undecodable_truncated}"
        "   (evidence-limited, not a miss)",
        f"  choices present, bad JSON: {rep.choices_undecodable_complete}"
        "   (real emit/parse finding)",
        f"  choices absent, TRUNCATED: {rep.choices_missing_truncated}"
        "   (evidence-limited, not a miss)",
        f"  choices absent, complete : {rep.choices_missing_clean}"
        "   (model genuinely omitted it)",
        "",
        "  per-field yield:",
    ]
    for k in ARAM_KEYS:
        lines.append(f"    {k:<14} {rep.field_yield.get(k, 0)}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*",
                    help="log files to replay (default: every file in logs/)")
    ap.add_argument("--logs-dir", default=str(ROOT / "logs"),
                    help="directory scanned when no paths are given")
    ap.add_argument("--json", action="store_true",
                    help="emit the report as JSON instead of text")
    args = ap.parse_args(argv)

    paths = [Path(p) for p in args.paths] or discover_logs(Path(args.logs_dir))
    rep = replay(iter_raw_records(paths))
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2, sort_keys=True))
    else:
        print(format_report(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
