"""Banned glyphs can hide inside a JSON file that is pure ASCII on disk.

The repo's ASCII rule is enforced by byte-level scanners (`test_smart_quote_hygiene`,
`test_mojibake_hygiene`, `tools/strip_em_dashes.py`). A JSON writer that emits
`\\u2014` escapes defeats every one of them: the bytes are 7-bit clean, so the
scanners pass, while the string a consumer actually decodes still carries an
em-dash. `data/daemon_slayer/spell_cast_rates.json` shipped that way.

These guards close the class by decoding the JSON first, then checking the
authored metadata fields - the strings this project writes about its own data,
as opposed to champion and item text mirrored verbatim from upstream, which
legitimately carries non-ASCII and is out of scope for an authored-content rule.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Keys this project authors. Deliberately excludes `description`, which upstream
# Data Dragon uses for item and ability text.
AUTHORED_KEYS = ("note", "notes", "generated_note", "source")

# Written as escapes, not literals: `test_smart_quote_hygiene` byte-scans this
# very file, so spelling the glyphs out here would make the detector trip the
# detector. The escapes decode to the same characters at runtime.
BANNED_GLYPHS = {
    "\u2014": "EM DASH",
    "\u2013": "EN DASH",
    "\u00d7": "MULTIPLICATION SIGN",
    "\u2018": "LEFT SINGLE QUOTE",
    "\u2019": "RIGHT SINGLE QUOTE",
    "\u201c": "LEFT DOUBLE QUOTE",
    "\u201d": "RIGHT DOUBLE QUOTE",
}

DATA_ROOTS = (
    pathlib.Path("data/daemon_slayer"),
)

# The generator behind the offending file. Authored source, so the byte-level
# rule applies to it directly.
CAST_RATE_GENERATOR = pathlib.Path("scripts/build_spell_cast_rates.py")


def _ds_json_files() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for root in DATA_ROOTS:
        abs_root = REPO_ROOT / root
        if abs_root.is_dir():
            found.extend(sorted(abs_root.rglob("*.json")))
    return found


def _authored_strings(doc: object) -> list[tuple[str, str]]:
    if not isinstance(doc, dict):
        return []
    out = []
    for key in AUTHORED_KEYS:
        val = doc.get(key)
        if isinstance(val, str):
            out.append((key, val))
    return out


def _banned_in(text: str) -> list[str]:
    return sorted({name for glyph, name in BANNED_GLYPHS.items() if glyph in text})


def test_ds_json_authored_fields_are_ascii_after_decode():
    """No authored metadata string decodes to a banned glyph."""
    files = _ds_json_files()
    assert files, "expected to find Daemon Slayer JSON data files"

    offenders = []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for key, val in _authored_strings(doc):
            hits = _banned_in(val)
            if hits:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel} [{key}]: {', '.join(hits)}")

    assert not offenders, (
        "authored JSON metadata decodes to banned glyphs (byte scanners miss "
        "these because they are stored as \\uXXXX escapes):\n  "
        + "\n  ".join(offenders)
    )


def test_spell_cast_rates_note_matches_its_generator():
    """The shipped note is the ASCII wording the generator emits.

    A backfilled data file that drifts from its generator would silently revert
    on the next regeneration run.
    """
    data_path = REPO_ROOT / "data/daemon_slayer/spell_cast_rates.json"
    # TRACKED in git - present in every checkout. Its absence is a deleted
    # shipped artifact, which must fail rather than green-skip the glyph guard.
    assert data_path.is_file(), f"tracked {data_path} is missing from this checkout"

    note = json.loads(data_path.read_text(encoding="utf-8")).get("note", "")
    assert note, "spell_cast_rates.json carries a note field"
    assert not _banned_in(note)
    assert "Casts/sec - measured median" in note
    assert "per champion x mode" in note


def test_cast_rate_generator_source_is_seven_bit_ascii():
    """The generator itself carries no non-ASCII byte."""
    path = REPO_ROOT / CAST_RATE_GENERATOR
    # scripts/build_spell_cast_rates.py is TRACKED - see the sibling test above.
    assert path.is_file(), f"tracked {CAST_RATE_GENERATOR.as_posix()} is missing"

    raw = path.read_bytes()
    bad = [(i, hex(b)) for i, b in enumerate(raw) if b > 127]
    assert not bad, f"{CAST_RATE_GENERATOR.as_posix()} has non-ASCII bytes: {bad[:5]}"
