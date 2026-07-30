"""Guard: RC-AUTHORED JSON under data/meta/ stays 7-bit ASCII.

WHY: data/meta/tft_set17_meta.json shipped 294 non-ASCII bytes, including 17
DOUBLE-mangled and 4 single-mangled em-dashes (an em-dash's UTF-8 bytes
re-decoded as latin-1 and re-saved, twice). 30 string values carried them and
6 of those are `decision_note` fields that tft/tft_coach_engine.py feeds into
a live Haiku prompt. tools/strip_em_dashes.py scanned only for the RAW dash
bytes, so it reported the file clean - the repo's own drift check walked past
its worst offender. That tool is fixed; this is the standing gate.

SCOPE - deliberate, and stated because getting it wrong makes the guard
either useless or permanently red:

  INCLUDED: every *.json directly under data/meta/ that RC authors by hand or
  generates from its own pipeline. These are prose-bearing (decision notes,
  gameplans, source lines) and the no-em-dash hard rule in CLAUDE.md applies
  to them like any other authored text.

  EXCLUDED: data/meta/ddragon_*.json. Those are a MIRROR of Riot's Data
  Dragon payload, re-downloaded wholesale by the refresh tooling. Their
  non-ASCII is legitimate content - champion and item display names carry
  accented and typographic characters that Riot ships and that RC must match
  byte-for-byte to join on. Rewriting them would (a) corrupt the join keys and
  (b) be undone by the very next refresh, so a guard over them would be a
  permanent false alarm rather than a real gate.

The file set is READ OFF DISK, not pinned: a new authored data/meta/*.json is
covered the moment it lands, with no test edit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
META_DIR = REPO_ROOT / "data" / "meta"

# Third-party mirrors, excluded per the SCOPE note above.
_MIRROR_PREFIXES = ("ddragon_",)


def _authored_meta_json() -> list[Path]:
    if not META_DIR.is_dir():
        return []
    return sorted(
        p
        for p in META_DIR.glob("*.json")
        if not p.name.startswith(_MIRROR_PREFIXES)
    )


def test_scope_is_not_empty_and_excludes_only_the_mirror():
    """The guard must actually be guarding something.

    A glob that silently matches nothing is a green test that checks air.
    """
    authored = _authored_meta_json()
    assert authored, f"no authored *.json found under {META_DIR}"
    all_json = sorted(META_DIR.glob("*.json"))
    excluded = {p.name for p in all_json} - {p.name for p in authored}
    assert all(
        n.startswith(_MIRROR_PREFIXES) for n in excluded
    ), f"excluded files that are not DDragon mirrors: {sorted(excluded)}"


@pytest.mark.parametrize(
    "path", _authored_meta_json(), ids=lambda p: p.name
)
def test_authored_meta_json_is_7bit_ascii(path: Path):
    raw = path.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
    if offenders:
        i, _ = offenders[0]
        excerpt = raw[max(0, i - 60) : i + 40].decode("utf-8", "replace")
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)} has {len(offenders)} non-ASCII "
            f"byte(s); first at offset {i}. Context: {excerpt!r}\n"
            "Use ' - ' for a clause break and plain ASCII quotes. If this is "
            "mojibake, run tools/strip_em_dashes.py --apply."
        )


@pytest.mark.parametrize(
    "path", _authored_meta_json(), ids=lambda p: p.name
)
def test_authored_meta_json_still_parses(path: Path):
    """An ASCII repair that breaks the JSON is not a repair."""
    json.loads(path.read_text(encoding="utf-8"))
