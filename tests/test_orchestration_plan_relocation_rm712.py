"""RM-712: docs/ORCHESTRATION_PLAN.md holds only live rows, and what left it
is provably verbatim.

WHY
---
The loop director reads the plan through ``cap_bytes_head_tail`` (first
PLAN_CTX_HEAD bytes plus the tail, PLAN_CTX_CAP in all), so everything in the
middle of an oversized plan is invisible to it. The plan had grown to 385,551
bytes of DONE rounds, a duplicated ``## Sessions - DIRECTOR REFILL 2026-07-21``
heading and an old findings log, while the only live rows were the newest
round and one WIP row. RM-712 moved the DONE blocks verbatim into
``docs/ORCHESTRATION_PLAN_HISTORY.md`` and recorded, per moved block, its
original plan lines, byte count and sha256.

These guards keep that true:

* the plan stays under the 60,000-byte budget the row set (a cycle appends
  about one row and one findings block, so this reds after several cycles
  rather than after the plan is unreadable again);
* no level-2 heading appears twice in the plan;
* no OPEN / WIP row exists only in a history file - a relocation that moves
  a live row out of the plan reds here (the row set's "no OPEN row lost");
* every RM-712 block in the history file still hashes to the sha256 its
  provenance line records, so the archive cannot be edited silently.

Bytes are read with CRLF folded to LF, because the recorded hashes are of the
git-normalised (LF) text and a worktree may materialise CRLF.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_PLAN = _REPO / "docs" / "ORCHESTRATION_PLAN.md"
_HISTORY = _REPO / "docs" / "ORCHESTRATION_PLAN_HISTORY.md"
_ARCHIVE = _REPO / "docs" / "ORCHESTRATION_FINDINGS_ARCHIVE.md"

PLAN_BUDGET_BYTES = 60_000
RM712_SECTION = b"## Relocated 2026-11-07 (RM-712)"
RM712_BLOCKS = 4

_ROW = re.compile(r"^\| (R\d+[\w-]*) \|(.*)$", re.M)
# A status cell that STARTS with OPEN / WIP, bold or annotated ("**WIP**",
# "OPEN (gated)") included; "OPENED ..." prose is not a status.
_UNCLOSED = re.compile(r"\|\s*\**\s*(OPEN|WIP)\b[^|]*\|")
_PROVENANCE = re.compile(
    rb"^Block (\d+) of (\d+): plan lines (\d+)-(\d+), (\d+) bytes, "
    rb"sha256 ([0-9a-f]{64})\.\n\n",
    re.M,
)


def _lf_bytes(path: Path) -> bytes:
    assert path.is_file(), f"tracked doc missing from the checkout: {path}"
    return path.read_bytes().replace(b"\r\n", b"\n")


def _unclosed_rows(text: str) -> set[str]:
    """Ids of `| R<n> |` table rows that carry an OPEN or WIP status cell."""
    return {m.group(1) for m in _ROW.finditer(text) if _UNCLOSED.search(m.group(2))}


def _level2_headings(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("## ")]


def test_plan_is_under_the_relocation_budget():
    size = len(_lf_bytes(_PLAN))
    assert size < PLAN_BUDGET_BYTES, (
        f"docs/ORCHESTRATION_PLAN.md is {size} bytes, over the {PLAN_BUDGET_BYTES}"
        "-byte RM-712 budget. Move the oldest DONE round or findings block "
        "VERBATIM into docs/ORCHESTRATION_PLAN_HISTORY.md (with a provenance "
        "line and sha256); never drop an OPEN / WIP row."
    )


def test_plan_has_no_duplicate_level2_heading():
    heads = _level2_headings(_lf_bytes(_PLAN).decode("utf-8"))
    dupes = sorted({h for h in heads if heads.count(h) > 1})
    assert not dupes, f"duplicate level-2 headings in the plan: {dupes}"


def test_unclosed_row_matcher_has_a_positive_control():
    sample = (
        "| R1 | a | b | DONE | `abc` |\n"
        "| R2 | a | b | WIP | 7121ca85 |\n"
        "| R3-U1 | a | b | OPEN | - |\n"
        "| R4 | a | b | **WIP** | - |\n"
        "| R5 | a | b | OPEN (gated) | - |\n"
        "| R6 | a | OPENED by the executor | DONE | - |\n"
        "| Item | Slug | Scope | Status | Commit |\n"
    )
    assert _unclosed_rows(sample) == {"R2", "R3-U1", "R4", "R5"}


def test_no_open_or_wip_row_lives_only_in_history():
    plan_rows = {m.group(1) for m in _ROW.finditer(_lf_bytes(_PLAN).decode("utf-8"))}
    assert plan_rows, "no | R<n> | rows found in the plan - the row shape changed"
    stranded = {}
    for doc in (_HISTORY, _ARCHIVE):
        lost = _unclosed_rows(_lf_bytes(doc).decode("utf-8")) - plan_rows
        if lost:
            stranded[doc.name] = sorted(lost)
    assert not stranded, (
        "OPEN / WIP rows exist only in a history file, so the director can no "
        f"longer see them: {stranded}. Keep live rows in docs/ORCHESTRATION_PLAN.md."
    )


def test_rm712_relocated_blocks_are_verbatim():
    data = _lf_bytes(_HISTORY)
    start = data.find(RM712_SECTION)
    assert start >= 0, f"history file has no '{RM712_SECTION.decode()}' section"
    pos = start
    seen = []
    for k in range(1, RM712_BLOCKS + 1):
        m = _PROVENANCE.search(data, pos)
        assert m, f"RM-712 provenance line for block {k} not found"
        idx, total, first, last, size, digest = m.groups()
        assert (int(idx), int(total)) == (k, RM712_BLOCKS), m.group(0)
        assert int(first) <= int(last), m.group(0)
        block = data[m.end(): m.end() + int(size)]
        assert len(block) == int(size), f"block {k} is truncated"
        assert block.endswith(b"\n"), f"block {k} does not end on a line boundary"
        assert block.count(b"\n") == int(last) - int(first) + 1, (
            f"block {k} line count disagrees with plan lines {first.decode()}-"
            f"{last.decode()}"
        )
        assert hashlib.sha256(block).hexdigest() == digest.decode(), (
            f"RM-712 block {k} no longer matches its recorded sha256 - the "
            "relocated text was edited; the history file is append-only"
        )
        seen.append((int(first), int(last)))
        pos = m.end() + int(size)
    assert seen == sorted(seen), f"blocks are not in original plan order: {seen}"
    for (_, prev_last), (nxt_first, _) in zip(seen, seen[1:]):
        assert nxt_first > prev_last, f"overlapping plan line ranges: {seen}"
