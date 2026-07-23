"""Runtime-ASCII guard for performance_tracker user-facing label tables.

The repo's no-em-dash rule is enforced by source-byte scanners (pytest_guard,
the strip_em_dashes purge, the panel banned-char guards). Those all read the
file bytes, where a Python string escape such as ``\\u2014`` is six ASCII
characters and passes clean - yet at runtime the same literal is an em-dash and
renders one in the dashboard grade panel. GRADE_LABEL carried 6 such escaped
em-dashes and the TFT placement tables carried more; every source scanner missed
them (2026-07-23 headless fix).

This guard closes that blind spot for the label tables by asserting the RUNTIME
value is 7-bit ASCII, so a re-introduced ``\\uXXXX`` punctuation escape fails
here even though it is invisible to a byte scan.
"""
from __future__ import annotations

import performance_tracker as pt


def _assert_ascii(container_name: str, values) -> None:
    bad = []
    for v in values:
        if isinstance(v, str):
            bad += [(v, hex(ord(c))) for c in v if ord(c) > 0x7F]
    assert not bad, (
        f"{container_name} has non-ASCII runtime characters (a \\uXXXX escape "
        f"that renders a smart-quote or em/en dash): {bad}"
    )


def test_grade_label_is_runtime_ascii():
    _assert_ascii("GRADE_LABEL", pt.GRADE_LABEL.values())


def test_grade_colors_keys_ascii():
    _assert_ascii("GRADE_COLORS", pt.GRADE_COLORS.values())


def test_tft_label_tables_are_runtime_ascii():
    _assert_ascii("_TFT_LABEL", pt._TFT_LABEL.values())
    _assert_ascii("_TFT_LABEL_DUO", pt._TFT_LABEL_DUO.values())
