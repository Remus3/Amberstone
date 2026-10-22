"""MAIN FIX 2026-10-21 1254 item 6 is DEFERRED: the sk- shapes keep no left
edge (C1b-3 S1 pre-committed fallback).

Item 6 asked for a left edge on the openai / anthropic shapes because
"disk-" plus 24 characters in a branch or decision file name read as a key.
Two rounds tried to suppress only an identifier glued to sk-:

* a regex left edge lost 92 real leak contexts the old pattern caught
  (ANSI colour codes, hex / octal / unicode escapes, double-encoded URLs,
  quoted-printable, PowerShell backtick escapes, markdown emphasis);
* a post-match filter that kept the match when an escape character sat
  earlier on the line still lost 33 contexts in an independent corpus
  (cmd's `^` escape, C1 controls 0x80-0x9f such as the 8-bit CSI 0x9B),
  because its escape set was an enumeration, and the test mirrored it.

The 2-round cap was reached, so the earlier pattern is kept: the scan
over-reports rather than under-reports. Reverses if: a design that
suppresses only an allowlisted file-name context (not an escape-set
exclusion) passes an independent differential with zero non-permitted
misses.

Parity with the earlier module was proven twice (the slice builder, 10112
cases; the merger's gate, 4980 cases, 0 differences) and is recorded in the
C1b-3 S1 commit body. This file does NOT re-run that differential: a test
pinned to an old commit needs git history (a shallow clone could only skip
it, and a skip here is an always-passing guard) and would block any later
legitimate pattern change. It pins the SAFETY PROPERTY of the deferral
instead, statically: every sk- key shape is still detected after each named
context that a left edge or an escape filter lost. The WSL checkout-path
change of the same slice is pinned in
tests/test_junction_drive_spellings_pubrepo_f.py.

All keys are synthetic fakes; every line that holds one carries the
credential-scan fixture pragma.
"""
from __future__ import annotations

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


def test_the_reported_false_positive_shape_still_fires_while_item_6_is_deferred():
    """The deferral itself: "disk-" plus 24 characters still reads as a
    generic sk- key until a design passes the reversal test."""
    classes = {f.pattern_class for f in cp.scan_text("lane/xdi" + "s" + "k-" + "a1b2c3d4e5f6a1b2c3d4e5f6\n")}
    assert classes == {"openai"}


@pytest.mark.parametrize("glue", ["xdi", "branch_", "ta", "name_", "echo ^> backup_", chr(0x9B) + "01;31mv2"],
                         ids=["xdi", "branch_", "ta", "name_", "cmd-caret", "c1-csi-v2"])
@pytest.mark.parametrize("shape", list(KEYS))
def test_a_key_glued_to_an_identifier_fires_on_every_shape(glue, shape):
    key, cls = KEYS[shape]
    assert cls in {f.pattern_class for f in cp.scan_text(glue + key + "\n")}
