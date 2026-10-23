"""MAIN FIX 2026-10-21 1254 item 6, redesigned as RM-781: the openai sk- shape
loses a finding in ONE allowlisted name context, and nowhere else.

Item 6 asked for a left edge on the openai / anthropic shapes because
"disk-" plus 24 characters in a branch or decision file name read as a key.
C1b-3 S1 tried twice to suppress an identifier glued to sk- and both rounds
leaked, because each was an EXCLUSION of the characters that "cannot" sit
before a real key:

* a regex left edge lost 92 real leak contexts the old pattern caught
  (ANSI colour codes, hex / octal / unicode escapes, double-encoded URLs,
  quoted-printable, PowerShell backtick escapes, markdown emphasis);
* a post-match filter that kept the match when an escape character sat
  earlier on the line still lost 33 contexts in an independent corpus
  (cmd's `^` escape, C1 controls 0x80-0x9f such as the 8-bit CSI 0x9B).

The 2-round cap fired and the parent pattern was kept (`135e1bcd0`). RM-781
replaces the exclusion with an ALLOWLIST of what a name looks like, conjoined
with the parent: a parent openai match is dropped only when the match itself
is a lowercase kebab-case name glued onto a lowercase word
(`tools/credential_patterns.py` `_is_name_context`). Real keys are mixed
case, so the left context (escape, colour code, identifier) no longer
decides anything. The anthropic shapes keep the parent pattern: no false hit
was measured on them, and the one glued lowercase anthropic shape in the
tree is a test key after a `\\n` escape.

What is pinned here:

1. the safety property, statically: every sk- key shape is still detected
   after each named context a left edge or an escape filter lost;
2. the allowlist: the measured false-hit shapes (a decision file, a branch
   and a proposal id) no longer fire, and every near miss of the name shape
   still does;
3. a seeded differential against the parent (the same module with the name
   filter switched off): no (line, class) pair is gained, and every lost
   pair is an openai pair whose every parent match is a name by the test's
   OWN oracle, written here with string operations, not the module's regex.

All keys are synthetic fakes; every line that holds one carries the
credential-scan fixture pragma.
"""
from __future__ import annotations

import random
import string

import pytest

from tools import credential_patterns as cp

ESC = chr(27)
BS = chr(92)

# shape label -> (fake key, the pattern class that must report it)
KEYS = {
    "sk-ant-api03": ("sk-ant-api03-TESTONLYfake0123456789abcdefXYZ", "anthropic"),  # rc-credential-scan: allow-fixture
    "sk-ant-admin01": ("sk-ant-admin01-TESTONLYfake0123456789abcdefXYZ", "anthropic_admin"),  # rc-credential-scan: allow-fixture
    "sk-proj-": ("sk-proj-TESTONLYfake0123456789abcdefXYZ", "openai"),  # rc-credential-scan: allow-fixture
    "generic-sk-": ("sk-TESTONLYfake0123456789abcdefXYZ", "openai"),  # rc-credential-scan: allow-fixture
}

# The contexts the #6 attempts lost (or that sit closest to the reported
# false-positive shape), each glued straight onto the key.
PREFIXES = {
    "ansi-bold": ESC + "[1m",
    "grep-color": ESC + "[01;31m" + ESC + "[K",
    "c1-csi-0x9b": chr(0x9B) + "01;31m",
    "hex-escape-x22": BS + "x22",
    "unicode-escape-u0022": BS + "u0022",
    "percent-22": "%22",
    "quoted-printable-3D": "=3D",
    "cmd-caret-echo": "echo ^> ",
    "markdown-underscore": "__",
    "backup_": "backup_",
    "xdisk": "xdisk",
    "v2": "v2",
    "key=": "key=",
    "line-start": "",
}


@pytest.mark.parametrize("prefix", list(PREFIXES.values()), ids=list(PREFIXES))
@pytest.mark.parametrize("shape", list(KEYS))
def test_every_key_shape_is_detected_after_every_named_context(shape, prefix):
    """Over-report, never under-report: the key is found on its own line,
    by the per-line arm, under the class its shape belongs to."""
    key, cls = KEYS[shape]
    findings = cp.scan_text("header line\n" + prefix + key + "\n" + "footer\n")
    assert (2, cls, "line") in [tuple(f) for f in findings], findings


def test_a_single_hex_word_after_disk_is_not_a_name_and_still_fires():
    """The synthetic stand-in for the report ("disk-" plus one 24-char hex
    word) is not a kebab-case name, so it still reads as a generic sk- key."""
    classes = {f.pattern_class for f in cp.scan_text("lane/xdi" + "s" + "k-" + "a1b2c3d4e5f6a1b2c3d4e5f6\n")}
    assert classes == {"openai"}


@pytest.mark.parametrize("glue", ["xdi", "branch_", "ta", "name_", "echo ^> backup_", chr(0x9B) + "01;31mv2"],
                         ids=["xdi", "branch_", "ta", "name_", "cmd-caret", "c1-csi-v2"])
@pytest.mark.parametrize("shape", list(KEYS))
def test_a_key_glued_to_an_identifier_fires_on_every_shape(glue, shape):
    key, cls = KEYS[shape]
    assert cls in {f.pattern_class for f in cp.scan_text(glue + key + "\n")}


# --------------------------------------------------------------------------
# 2. the allowlisted name context
# --------------------------------------------------------------------------

# Each is assembled so "sk-" never sits glued in this source: the measured
# shapes are a decision file name, a branch name and a backticked proposal id.
_SK = "s" + "k-"
NAMES = {
    "decision-file": "docs/decisions/2026-10-21-di" + _SK + "cleanup-plan-for-the-lanes.md",
    "branch": "lane/ta" + _SK + "queue-ordering-fix-round-two",
    "proposal-id": "`P-audit8-h02-ta" + _SK + "queue-drain-cycle-notes-v2`",
    "digit-glue": "run2" + _SK + "usage-report-for-weekly-review.txt",
}


@pytest.mark.parametrize("text", list(NAMES.values()), ids=list(NAMES))
def test_a_lowercase_kebab_name_glued_to_sk_is_not_a_key(text):
    for body in (text, "see " + text + " here", "a = '" + text + "'"):
        assert cp.scan_text(body + "\n") == [], body


def test_a_name_on_a_wrapped_line_is_not_a_key_either():
    """The dewrap arm applies the same allowlist to the joined text."""
    text = 'x = "docs/2026-di' + _SK + 'cleanup-"\n' + '"plan-for-the-lanes.md"\n'
    assert cp.scan_text(text) == []


_BASE = "ta" + _SK + "queue-ordering-fix-round-two"
NEAR_MISSES = {
    "upper-in-span": "ta" + _SK + "queue-Ordering-fix-round-two",
    "upper-glue": "tA" + _SK + "queue-ordering-fix-round-two",
    "underscore-word": "ta" + _SK + "queue_ordering-fix-round-two",
    "word-over-16": "ta" + _SK + "queue-orderingorderingx-fix-round",
    "single-word": "ta" + _SK + "queueorderingfixroundtwo",
    "double-hyphen": "ta" + _SK + "queue--ordering-fix-round-two",
    "trailing-hyphen": "ta" + _SK + "queue-ordering-fix-round-two-",
    "hex-groups": "ta" + _SK + "3f2a1b4c-9d8e-4f7a-b6c5-d4e3f2a1b0c9",
    "proj-then-hex": "ta" + _SK + "proj-3f2a1b4c-9d8e-4f7a-b6c5-d4e3f2a1",
    "slash-glue": "lane/" + _SK + "queue-ordering-fix-round-two",
    "underscore-glue": "name_" + _SK + "queue-ordering-fix-round-two",
    "hyphen-glue": "lane-" + _SK + "queue-ordering-fix-round-two",
    "line-start": _SK + "queue-ordering-fix-round-two",
    "ansi-glue": ESC + "[1m" + _SK + "queue-ordering-fix-round-twoXYZ",
}


def test_the_base_of_the_near_misses_is_a_name():
    """The near-miss table is not vacuous: its base IS in the allowlist."""
    assert cp.scan_text(_BASE + "\n") == []


@pytest.mark.parametrize("text", list(NEAR_MISSES.values()), ids=list(NEAR_MISSES))
def test_every_near_miss_of_the_name_shape_still_fires(text):
    assert {f.pattern_class for f in cp.scan_text(text + "\n")} == {"openai"}


@pytest.mark.parametrize("glue", ["ta", "xdi", "run2"])
def test_the_anthropic_shapes_keep_the_parent_pattern(glue):
    """No false hit was measured on them: a lowercase name after sk-ant- or
    sk-ant-admin still fires (the per-line arm runs each family on its own,
    so an admin shape is also an anthropic shape, as in the parent)."""
    ant = glue + _SK + "ant-colony-notes-for-the-lanes\n"
    admin = glue + _SK + "ant-admin-notes-for-the-lanes\n"
    assert {f.pattern_class for f in cp.scan_text(ant)} == {"anthropic"}
    assert {f.pattern_class for f in cp.scan_text(admin)} == {"anthropic_admin", "anthropic"}


def test_the_name_context_is_conjoined_with_the_parent_pattern():
    """It is only ever asked about a parent match: text the parent pattern
    does not match is never a finding, whatever the filter would say."""
    short = "ta" + _SK + "queue-fix\n"
    assert cp.scan_text(short) == []
    assert cp._is_name_context(short, 2, len(short) - 1)


# --------------------------------------------------------------------------
# 3. differential against the parent (the module with the filter off)
# --------------------------------------------------------------------------

_LOWER_DIGITS = frozenset(string.ascii_lowercase + string.digits)
_NON_HEX = frozenset("ghijklmnopqrstuvwxyz")


def _oracle_is_name(text: str, start: int, end: int) -> bool:
    """The allowlist, restated with string operations only."""
    if start == 0 or text[start - 1] not in _LOWER_DIGITS:
        return False
    span = text[start:end]
    if not span.startswith(_SK):
        return False
    words = span[3:].split("-")
    if len(words) < 2:
        return False
    if any(not (1 <= len(w) <= 16) or not set(w) <= _LOWER_DIGITS for w in words):
        return False
    return sum(1 for w in words if set(w) & _NON_HEX) >= 2


def _openai_rx():
    return dict(cp._COMPILED)["openai"]


def _parent_scan(monkeypatch, text):
    with monkeypatch.context() as patch:
        patch.setattr(cp, "_is_name_context", lambda *_a: False)
        return cp.scan_text(text)


def _pairs(findings):
    return {(f.line_no, f.pattern_class) for f in findings}


_ALPHA = string.ascii_letters + string.digits
_FUZZ_PREFIXES = list(PREFIXES.values()) + [
    "", " ", "ta", "xdi", "run2", "P-audit8-h02-ta", "lane/", "docs/2026-10-21-di",
    "a", "Z", "9", "_", "-", "/", "`", "'", '"', BS + "n", BS + "x1b[0m", "%3d", "^",
    chr(0x85), chr(0x9B) + "0m", "key = '", "Bearer ",
]
_FUZZ_SUFFIXES = ["", " ", ".md", ".txt", "`", "'", '"', "/x", BS, " here", "\r", ".", "-"]


def _word(rng, lo=1, hi=12, alphabet=string.ascii_lowercase + string.digits):
    return "".join(rng.choice(alphabet) for _ in range(rng.randint(lo, hi)))


def _body(rng):
    """A span body after sk-: real-like keys, names, and near misses."""
    pick = rng.random()
    if pick < 0.25:
        return "".join(rng.choice(_ALPHA + "-_") for _ in range(rng.randint(24, 60)))
    if pick < 0.30:
        return "proj-" + "".join(rng.choice(_ALPHA + "-_") for _ in range(rng.randint(24, 60)))
    words = [_word(rng) for _ in range(rng.randint(2, 7))]
    if pick < 0.55:
        return "-".join(words)
    if pick < 0.65:
        return "-".join(_word(rng, 4, 12, "0123456789abcdef") for _ in range(rng.randint(3, 6)))
    mutated = "-".join(words)
    i = rng.randint(0, len(mutated))
    return mutated[:i] + rng.choice(["A", "_", "--", "Q", "x" * 17, "-"]) + mutated[i:]


def _fuzz_text(rng):
    lines = []
    for _ in range(rng.randint(1, 3)):
        line = rng.choice(_FUZZ_PREFIXES) + _SK + _body(rng) + rng.choice(_FUZZ_SUFFIXES)
        if rng.random() < 0.3:
            line += " " + rng.choice(_FUZZ_PREFIXES) + _SK + _body(rng)
        lines.append(line)
    if rng.random() < 0.2:
        cut = rng.randint(0, len(lines[0]))
        lines[0:1] = ['"' + lines[0][:cut] + '"', '"' + lines[0][cut:] + '"']
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("seed", [7, 13, 23])
def test_differential_against_the_parent_loses_only_allowlisted_names(seed, monkeypatch):
    rng = random.Random(seed)
    rx = _openai_rx()
    lost_total = 0
    exact_checked = 0
    for _ in range(1500):
        text = _fuzz_text(rng)
        new = cp.scan_text(text)
        parent = _parent_scan(monkeypatch, text)
        gained = _pairs(new) - _pairs(parent)
        assert gained == set(), (seed, sorted(gained))
        lines = text.split("\n")
        lost = _pairs(parent) - _pairs(new)
        lost_total += len(lost)
        for line_no, cls in lost:
            assert cls == "openai", (seed, line_no, cls)
            row = lines[line_no - 1]
            matches = list(rx.finditer(row))
            if matches:
                assert all(_oracle_is_name(row, m.start(), m.end()) for m in matches), (seed, line_no)
        # Exactness on texts with no wrapped run: an openai pair is lost
        # exactly when every parent match on its line is a name.
        if not cp._wrapped_blocks(text.splitlines()):
            for index, row in enumerate(lines, start=1):
                matches = list(rx.finditer(row))
                if not matches or cp.PRAGMA in row:
                    continue
                exact_checked += 1
                all_names = all(_oracle_is_name(row, m.start(), m.end()) for m in matches)
                assert ((index, "openai") in _pairs(new)) is (not all_names), (seed, index)
    assert lost_total > 0, "the corpus never reached the allowlist"
    assert exact_checked > 500
