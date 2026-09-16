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

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.inbox_responder_runner import (  # noqa: E402
    NOTE_NAME_MAX,
    NOTE_NAME_RE,
    name_grammar_bad,
)

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


# ---------------------------------------------------------------------------
# RM-436: the spec's refused-name EXAMPLES must be refused by the real gate and
# must agree with the test's `BAD_NAMES` parametrization.
#
# The spec recites refused examples twice (section 6 note-shape bullet, section
# 12 note-shape table row). Each recital carries a PRIMARY list, introduced by
# `Negatives` / `parametrized names`, and may carry an EXTRAS list introduced
# by `also refused outside that parametrization`. The matching rule:
#   1. every phrase parses to a known example (an unknown phrase fails, so a
#      reworded example forces this vocabulary to move with it);
#   2. every example's concrete name is REFUSED by the imported
#      `name_grammar_bad` - executed, never read;
#   3. the PRIMARY labels equal the `BAD_NAMES` labels read from
#      tests/test_inbox_responder_runner.py by AST (not import);
#   4. the EXTRAS labels are disjoint from `BAD_NAMES` and each is backed by
#      the named arm in `EXTRA_ARMS` (None = refused but no arm isolates it);
#   5. both recitals parse to the same (primary, extras) label sets.
# ---------------------------------------------------------------------------

RUNNER_TESTS = REPO_ROOT / "tests" / "test_inbox_responder_runner.py"
_PREFIX = "2026-09-07-1800-from-RSC-"

PRIMARY_RE = re.compile(r"(?:Negatives|parametrized names)(?:, the test's `BAD_NAMES`)?: ")
EXTRAS_RE = re.compile(r"[Aa]lso refused outside that parametrization: ")

# label -> the arm in the runner test file that exercises it, or None when the
# name is refused but the grammar refuses it before the clause it illustrates.
EXTRA_ARMS = {
    "lowercase-code": "test_a_lowercase_sender_code_never_reaches_the_shape_gate",
    "length-cap": None,
}


def _examples(phrase: str) -> list[tuple[str, str]]:
    """Map one spec phrase to its (label, concrete name) examples."""
    text = re.sub(r"\([^()]*\)", "", phrase).strip()
    text = re.sub(r"^(?:a|an) ", "", text)
    fixed = {
        "space": [("space", _PREFIX + "bad name.md")],
        "`?`": [("question", _PREFIX + "what?.md")],
        "non-ASCII byte": [("non-ascii", _PREFIX + "caf" + chr(0xE9) + ".md")],
        "`+`": [("plus", _PREFIX + "a+b.md")],
        "`..`": [("dotdot", _PREFIX + "..md")],
        "lowercase code": [("lowercase-code", "2026-09-07-1800-from-rsc-topic.md")],
        "lone surrogate": [
            ("lone-surrogate", _PREFIX + "\udcff.md"),
            ("high-surrogate", _PREFIX + "\ud800.md"),
        ],
    }
    if text in fixed:
        return fixed[text]
    m = re.fullmatch(r"(\d+)-char topic", text)
    if m:
        return [("too-long-topic", _PREFIX + "x" * int(m.group(1)) + ".md")]
    m = re.fullmatch(r"(\d+) chars", text)
    if m:
        n = int(m.group(1))
        return [("length-cap", _PREFIX + "x" * (n - len(_PREFIX) - 3) + ".md")]
    raise AssertionError(f"unknown refused-name phrase in the spec: {phrase!r}")


def _split_list(line: str, start: int) -> list[str]:
    """Split a comma list from `start` to the first top-level `;` or `. `/end.

    Backtick spans and parentheses are opaque, so `..`, `?` and the surrogate
    parenthetical (which holds its own `;`) do not end or split the list.
    """
    items, buf, depth, tick = [], [], 0, False
    i = start
    while i < len(line):
        ch = line[i]
        if ch == "`":
            tick = not tick
        elif not tick and ch == "(":
            depth += 1
        elif not tick and ch == ")":
            depth -= 1
        elif not tick and depth == 0:
            if ch == ";" or (ch == "." and (i + 1 == len(line) or line[i + 1] == " ")):
                break
            if ch == ",":
                items.append("".join(buf).strip())
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return [item for item in items if item]


def _refused_lists(line: str) -> tuple[list, list]:
    primary = PRIMARY_RE.search(line)
    assert primary is not None, f"no refused-name list found in: {line[:160]}"
    main = [ex for p in _split_list(line, primary.end()) for ex in _examples(p)]
    assert main, f"refused-name list parsed EMPTY; the guard would be vacuous: {line[:160]}"
    extras_match = EXTRAS_RE.search(line)
    extras = []
    if extras_match is not None:
        extras = [ex for p in _split_list(line, extras_match.end()) for ex in _examples(p)]
        assert extras, "extras marker present but its list parsed EMPTY"
    return main, extras


def _bad_names_labels() -> set[str]:
    tree = ast.parse(RUNNER_TESTS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "BAD_NAMES" for t in node.targets
        ):
            labels = {elt.elts[0].value for elt in node.value.elts}
            assert labels, "BAD_NAMES parsed EMPTY"
            return labels
    raise AssertionError(f"BAD_NAMES not found in {RUNNER_TESTS}")


def _runner_test_names() -> set[str]:
    tree = ast.parse(RUNNER_TESTS.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


RECITALS = ("- `NOTE_NAME_RE = r'", "| note-shape |")


def _check_recital(line: str) -> tuple[frozenset, frozenset]:
    main, extras = _refused_lists(line)
    for label, name in main + extras:
        assert name_grammar_bad(name), (
            f"spec lists {label!r} as refused but the gate ADMITS {name!r}"
        )
    bad = _bad_names_labels()
    main_labels = {label for label, _ in main}
    extra_labels = {label for label, _ in extras}
    assert main_labels == bad, (
        f"spec primary list {sorted(main_labels)} != BAD_NAMES {sorted(bad)}"
    )
    assert not (extra_labels & bad), extra_labels & bad
    assert extra_labels <= set(EXTRA_ARMS), extra_labels - set(EXTRA_ARMS)
    arms = _runner_test_names()
    for label in extra_labels:
        arm = EXTRA_ARMS[label]
        assert arm is None or arm in arms, f"{label!r} names arm {arm!r}, not in {RUNNER_TESTS.name}"
    return frozenset(main_labels), frozenset(extra_labels)


def test_spec_refused_name_examples_are_refused_and_match_bad_names():
    lines = _spec_lines()
    verdicts = [_check_recital(_one_line(lines, prefix)) for prefix in RECITALS]
    assert len(set(verdicts)) == 1, f"the two spec recitals disagree: {verdicts!r}"


def test_refused_list_guard_fails_on_an_empty_or_admitted_list():
    """Anchor: the guard must not pass vacuously, nor on an admitted example."""
    with pytest.raises(AssertionError):
        _refused_lists("- Negatives: ; nothing listed")
    with pytest.raises(AssertionError):
        _refused_lists("- no marker on this line at all")
    with pytest.raises(AssertionError):
        _check_recital("- Negatives: space, `..`.")
    assert not name_grammar_bad(_examples("`..`")[0][1]), "`..` is ADMITTED by the grammar"
