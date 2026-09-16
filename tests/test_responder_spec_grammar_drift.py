"""The spec's recital of gate 6's note-name grammar must match the code.

RM-386 (commit 3384787f0, 2026-09-08) raised the topic group of
`NOTE_NAME_RE` from `{1,80}` to `{1,160}` and `NOTE_NAME_MAX` from 120 to 200
in `tools/inbox_responder_runner.py`, on a five-inbox census. It did not touch
`docs/RESPONDER_RUNNER_SPEC.md`, which kept reciting `{1,80}`, a 120 cap and a
"121 chars" negative in three places. Nothing bound the doc to the code, so
the doc drifted silently.

These arms bind them. Every number is PARSED from the doc and compared with a
number DERIVED from the imported constants - nothing here hardcodes 160 or
200, so the guard follows a future deliberate change of the code and fails
only when the doc is left behind. Every parse asserts that it matched, so an
empty or reworded doc fails loudly instead of passing vacuously.

The code side is the authority: the constants carry the census in-comment and
the grammar is a wire format siblings parse. This test never edits either.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.inbox_responder_runner import NOTE_NAME_MAX, NOTE_NAME_RE  # noqa: E402

SPEC = REPO_ROOT / "docs" / "RESPONDER_RUNNER_SPEC.md"

# The topic group, spelled as the code spells it. `ROW_NOTE_RE` uses a
# DIFFERENT class (`[A-Za-z0-9._?-]`, with `?`) and bounds the safe_name
# projection, not the note name, so it is deliberately not matched here.
TOPIC_GROUP_RE = re.compile(r"\[A-Za-z0-9\._-\]\{1,(\d+)\}")


def _spec_lines() -> list[str]:
    text = SPEC.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) > 100, f"{SPEC} read as {len(lines)} lines; the guard would be vacuous"
    return lines


def _one_line(lines: list[str], prefix: str) -> str:
    hits = [line for line in lines if line.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly one spec line starting {prefix!r}, found {len(hits)}"
    return hits[0]


def _one_int(pattern: str, line: str) -> int:
    found = re.findall(pattern, line)
    assert len(found) == 1, f"expected exactly one {pattern!r} in the line, found {found!r}: {line[:160]}"
    return int(found[0])


def _code_topic_bound() -> int:
    match = TOPIC_GROUP_RE.search(NOTE_NAME_RE.pattern)
    assert match is not None, f"topic group not found in code pattern {NOTE_NAME_RE.pattern!r}"
    return int(match.group(1))


def test_code_side_parses_to_real_bounds():
    """Anchor: if the code-side parse ever returns nothing, every arm is moot."""
    topic = _code_topic_bound()
    assert topic > 0 and NOTE_NAME_MAX > 0
    # The length cap is the OUTER bound (the in-code comment's composition).
    assert NOTE_NAME_MAX > topic


def test_spec_recites_the_exact_note_name_regex():
    line = _one_line(_spec_lines(), "- `NOTE_NAME_RE = r'")
    match = re.match(r"- `NOTE_NAME_RE = r'(.+?)'`", line)
    assert match is not None, f"could not parse the recited regex: {line[:160]}"
    assert match.group(1) == NOTE_NAME_RE.pattern


def test_spec_note_shape_bullet_bounds_match_code():
    line = _one_line(_spec_lines(), "- `NOTE_NAME_RE = r'")
    topic = _code_topic_bound()
    assert _one_int(r"\{1,(\d+)\}\\\.md", line) == topic
    assert _one_int(r"len\(name\) <= (\d+)", line) == NOTE_NAME_MAX
    assert _one_int(r"\b(\d+) chars\b", line) == NOTE_NAME_MAX + 1
    assert _one_int(r"\b(\d+)-char topic\b", line) == topic + 1


def test_spec_gate_table_row_6_length_matches_code():
    line = _one_line(_spec_lines(), "| 6 | `note_shape_ok`")
    assert _one_int(r"total length <= (\d+)", line) == NOTE_NAME_MAX


def test_spec_test_table_note_shape_negatives_match_code():
    line = _one_line(_spec_lines(), "| note-shape |")
    assert _one_int(r"\b(\d+) chars\b", line) == NOTE_NAME_MAX + 1
    assert _one_int(r"\b(\d+)-char topic\b", line) == _code_topic_bound() + 1


def test_no_other_spec_recital_of_the_grammar_drifts():
    """Sibling sweep over the WHOLE spec, not just the three known lines."""
    text = SPEC.read_text(encoding="utf-8")
    topics = [int(n) for n in TOPIC_GROUP_RE.findall(text)]
    lengths = [int(n) for n in re.findall(r"(?:len\(name\)|total length) <= (\d+)", text)]
    # Anchor: the known recitals must be found, or the sweep proves nothing.
    assert len(topics) >= 1, "no topic-group recital found in the spec"
    assert len(lengths) >= 2, f"expected >= 2 length-cap recitals, found {lengths!r}"
    assert set(topics) == {_code_topic_bound()}, topics
    assert set(lengths) == {NOTE_NAME_MAX}, lengths
