"""RM-1194 - the UI scale spec states one --hit-min value, and its citers
name the section, not a line number.

WHY: the "Interaction rules" section of docs/UI_SCALE_SPEC_V2.md lists
--hit-min as 42px in its v2.1 table row (tokens.css carries the same 42px),
but the paragraph under that table still said "the interactive target is
`--hit-min` (36px)" - the v2 value the v2.1 bump replaced. A reader of the
paragraph alone sized hit targets 6px short.

Separately, four test docstrings / failure messages and one overlay.css
comment cited the spec as "line 112" (or "line 112 + 118"). Those cites held
only by luck: any edit above the section moves them onto unrelated prose.
They now name the "Interaction rules" section and its --hit-min row.

Guards:
  * every "`--hit-min` (Npx" mention in the spec, and the bold v2.1 value of
    its --hit-min table row, equal the --hit-min value in web/css/tokens.css;
  * the spec still has the "## Interaction rules" heading with the --hit-min
    row inside it (the anchor the citers name);
  * no citer carries a line-number cite into the spec, and each still names
    the "Interaction rules" section (non-vacuity: a citer that dropped the
    reference entirely would pass the no-line-cite check alone).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "docs" / "UI_SCALE_SPEC_V2.md"
TOKENS = ROOT / "web" / "css" / "tokens.css"

SECTION = "Interaction rules"

# A line-number cite into the spec: "UI_SCALE_SPEC_V2 line 112",
# "UI_SCALE_SPEC_V2.md line 112 + 118", "lines 112-118", "L112",
# "UI_SCALE_SPEC_V2.md:112".
_SPEC_LINE_CITE = re.compile(
    r"UI_SCALE_SPEC_V2(?:\.md)?(?:\s+lines?\s+\d+|\s+L\d+|:\d+)"
)

CITERS = (
    "tests/test_overlay_launcher_hit_targets.py",
    "tests/snapshot_panels/test_overlay_launcher_menu.py",
    "tests/test_overlay_stats_role_hit_target.py",
    "web/css/overlay.css",
)


def _read(path):
    return path.read_text(encoding="utf-8")


def _token_px():
    m = re.search(r"--hit-min:\s*(\d+)px\s*;", _read(TOKENS))
    assert m, "--hit-min declaration not found in web/css/tokens.css"
    return int(m.group(1))


def _section_text():
    text = _read(SPEC)
    m = re.search(r"^## " + re.escape(SECTION) + r"\n(.*?)(?=^## |\Z)",
                  text, re.S | re.M)
    assert m, f'docs/UI_SCALE_SPEC_V2.md lost its "## {SECTION}" heading'
    return m.group(1)


def test_spec_table_row_matches_token():
    """The --hit-min table row's bold v2.1 value is the tokens.css value."""
    row = re.search(r"^\|\s*`--hit-min`\s*\|[^|]*\|\s*\*\*(\d+)px\*\*\s*\|",
                    _section_text(), re.M)
    assert row, (
        f'the --hit-min table row is missing from the "{SECTION}" section '
        "(or its v2.1 value is no longer bold)"
    )
    assert int(row.group(1)) == _token_px()


def test_spec_prose_hit_min_matches_token():
    """Every prose "`--hit-min` (Npx" in the spec names the tokens.css value."""
    found = [int(n) for n in re.findall(r"`--hit-min`\s*\((\d+)px", _read(SPEC))]
    assert found, (
        "non-vacuity: the spec should still name the --hit-min value in its "
        "slider-thumb paragraph"
    )
    want = _token_px()
    assert all(n == want for n in found), (
        f"docs/UI_SCALE_SPEC_V2.md names --hit-min as {found}px in prose, "
        f"but tokens.css declares {want}px"
    )


@pytest.mark.parametrize("rel", CITERS)
def test_citer_names_section_not_line(rel):
    """Each citer names the spec section, never a line number in it."""
    text = _read(ROOT / rel)
    hits = _SPEC_LINE_CITE.findall(text)
    assert not hits, f"{rel} carries line cites into the spec: {hits}"
    assert "UI_SCALE_SPEC_V2" in text and SECTION in text, (
        f'{rel} should cite docs/UI_SCALE_SPEC_V2.md "{SECTION}" by section'
    )
