"""The DDragon mirror's JSON writer must emit LF bytes, not platform text.

WHY THIS EXISTS (2026-09-11). ``tools/ddragon_mirror_refresh._atomic_write_json``
used ``Path.write_text``, which on Windows rewrites every LF as CRLF while
``read_text`` translates it back - so the extra bytes are invisible to every
reader yet real on disk. Six tracked mirror bundles under
``data/meta_build/ddragon/`` shipped that way (profileicon.json alone carried
60510 CRLF pairs) and ``git status`` stayed EMPTY the whole time, because git
normalizes them to LF in the index. Only the on-disk bytes were wrong, which is
exactly the class of defect ``tests/test_text_line_endings.py`` was written to
catch after the fact. This test catches it at the producer instead.

Asserting on BYTES is the whole point - a ``read_text`` round trip is blind to
the defect by construction, so a version of this test written that way would
pass against the broken function.
"""
from __future__ import annotations

import json

from tools.ddragon_mirror_refresh import _atomic_write_json

# Multi-line by construction: a single-line payload cannot expose the defect,
# since text mode only rewrites newlines that are already there.
_PAYLOAD = {
    "bundles": ["champion", "item", "runesReforged", "summoner"],
    "latest_pulled": "16.18.1",
    "locale": "en_US",
    "nested": {"a": 1, "b": [2, 3, 4]},
}


def test_atomic_write_json_emits_no_crlf(tmp_path):
    target = tmp_path / "_index.json"
    _atomic_write_json(target, _PAYLOAD)
    raw = target.read_bytes()
    pairs = raw.count(b"\r\n")
    assert pairs == 0, f"{target.name} carries {pairs} CRLF pairs on disk"
    assert b"\r" not in raw


def test_atomic_write_json_payload_is_unchanged_apart_from_line_endings(tmp_path):
    target = tmp_path / "manifest.json"
    _atomic_write_json(target, _PAYLOAD)
    raw = target.read_bytes()
    expected = (json.dumps(_PAYLOAD, indent=2, sort_keys=True) + "\n").encode("utf-8")
    assert raw == expected
    assert json.loads(raw.decode("utf-8")) == _PAYLOAD


def test_atomic_write_json_byte_length_matches_line_count(tmp_path):
    """A size/digest compare over the written file must be platform-stable."""
    target = tmp_path / "sized.json"
    _atomic_write_json(target, _PAYLOAD)
    text = json.dumps(_PAYLOAD, indent=2, sort_keys=True) + "\n"
    assert target.stat().st_size == len(text.encode("utf-8"))
