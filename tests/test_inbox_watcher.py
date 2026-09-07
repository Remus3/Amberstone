"""Guards for the cross-repo inbox watcher in tools/rc_facts.py.

Every assertion here started life as a MEASURED defect, not a hypothetical.
The watcher has now been wrong in four distinct ways, and each one shared a
shape: the key it recorded could stay equal while the thing it named had
moved, so the report was confident, precise and silently stale.

  1. Top-level `*.md` only, so a whole subdirectory payload was invisible.
  2. Directory payloads keyed on a file COUNT, so a replaced file kept the key.
  3. Directory payloads keyed on the MANIFEST FILE, so a payload edited
     without regenerating its manifest kept the key.
  4. Notes keyed on NAME alone, so a sibling correcting a note in place kept
     the key. Sibling repos have shipped at least two "CORRECTION" notes.

The tests deliberately build a fixture inbox rather than touching the real
`moon_sync_inbox/`, and they call the SHIPPED functions so the thing under
test is what the hook actually runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.rc_facts import (  # noqa: E402
    _entry_name,
    _file_digest,
    _inbox_entries,
    _inbox_withdrawn,
    _payload_key,
)


@pytest.fixture()
def inbox(tmp_path: Path) -> Path:
    d = tmp_path / "moon_sync_inbox"
    d.mkdir()
    return d


def _only(entries: set[str], needle: str) -> str | None:
    hits = [e for e in entries if needle in e]
    return hits[0] if hits else None


def test_plain_note_is_listed(inbox: Path):
    (inbox / "2026-01-01-from-XX-note.md").write_text("hello", encoding="utf-8")
    assert _only(_inbox_entries(inbox), "note.md") is not None


def test_empty_subdirectory_is_surfaced(inbox: Path):
    """Sibling-D's one-line test: a directory has no .md suffix."""
    (inbox / "from-XX-verbatim").mkdir()
    assert _only(_inbox_entries(inbox), "from-XX-verbatim") is not None


def test_non_md_payload_inside_a_drop_moves_the_key(inbox: Path):
    drop = inbox / "from-XX-verbatim"
    drop.mkdir()
    before = _only(_inbox_entries(inbox), "verbatim")
    (drop / "tool.py").write_text("x = 1", encoding="utf-8")
    assert _only(_inbox_entries(inbox), "verbatim") != before


def test_content_edit_at_equal_file_count_is_detected(inbox: Path):
    """Defect 2. A count-keyed watcher calls this unchanged."""
    drop = inbox / "from-XX-verbatim"
    drop.mkdir()
    (drop / "tool.py").write_text("x = 1", encoding="utf-8")
    before = _only(_inbox_entries(inbox), "verbatim")
    (drop / "tool.py").write_text("x = 2", encoding="utf-8")
    assert _only(_inbox_entries(inbox), "verbatim") != before


def test_payload_edit_without_a_manifest_refresh_is_detected(inbox: Path):
    """Defect 3, and the reason the manifest is reported but never trusted.

    Trusting a sender's manifest means trusting that they remembered to
    rebuild it. The watcher exists to remove exactly that assumption.
    """
    drop = inbox / "from-YY-verbatim"
    drop.mkdir()
    (drop / "a.py").write_text("a", encoding="utf-8")
    (drop / "MANIFEST.sha256").write_text("stale-digest", encoding="utf-8")
    before = _payload_key(drop)
    (drop / "a.py").write_text("COMPLETELY DIFFERENT", encoding="utf-8")
    assert _payload_key(drop) != before, "a stale manifest must not mask an edit"


def test_note_edited_in_place_is_detected(inbox: Path):
    """Defect 4. Rename surfaces it, and now an edit does too."""
    n = inbox / "2026-01-01-from-LW-CORRECTION.md"
    n.write_text("original", encoding="utf-8")
    before = _only(_inbox_entries(inbox), "CORRECTION")
    n.write_text("corrected", encoding="utf-8")
    assert _only(_inbox_entries(inbox), "CORRECTION") != before


def test_two_files_swapping_contents_is_a_change(inbox: Path):
    """The path is inside each digest line precisely so this is visible."""
    drop = inbox / "from-XX-verbatim"
    drop.mkdir()
    (drop / "a.py").write_text("AAA", encoding="utf-8")
    (drop / "b.py").write_text("BBB", encoding="utf-8")
    before = _payload_key(drop)
    (drop / "a.py").write_text("BBB", encoding="utf-8")
    (drop / "b.py").write_text("AAA", encoding="utf-8")
    assert _payload_key(drop) != before


def test_nested_subdirectories_are_included(inbox: Path):
    drop = inbox / "from-XX-verbatim"
    (drop / "tools" / "deep").mkdir(parents=True)
    before = _payload_key(drop)
    (drop / "tools" / "deep" / "buried.py").write_text("x", encoding="utf-8")
    assert _payload_key(drop) != before


def test_underscore_prefixed_drafts_stay_excluded(inbox: Path):
    (inbox / "_draft.md").write_text("mine, not inbound", encoding="utf-8")
    assert _only(_inbox_entries(inbox), "_draft") is None


def test_a_drop_and_a_same_named_note_cannot_collide(inbox: Path):
    """The trailing slash on a drop key is load-bearing."""
    (inbox / "payload").mkdir()
    (inbox / "payload").joinpath("f.txt").write_text("x", encoding="utf-8")
    entries = _inbox_entries(inbox)
    assert any(e.startswith("payload/ ") for e in entries)


def test_unreadable_file_moves_the_digest_rather_than_vanishing(tmp_path: Path):
    """An unreadable file must not silently drop out of the key."""
    missing = tmp_path / "gone.bin"
    d = _file_digest(missing)
    assert d.startswith("UNREADABLE:"), d


def test_missing_inbox_is_not_an_error(tmp_path: Path):
    assert _inbox_entries(tmp_path / "does_not_exist") == set()


# -- Withdrawals (Sibling-D's sixth property, 2026-09-07) ---------------
#
# `names - seen` cannot see a deletion: a retracted note simply stops
# appearing, so the watcher goes quiet exactly when a sibling retracts
# something. RC has already performed a withdrawal on this channel - 50 files
# pulled from four inboxes - so this is a measured gap, not a hypothetical.


def test_retracted_note_is_reported_as_withdrawn(inbox: Path):
    (inbox / "a.md").write_text("one", encoding="utf-8")
    (inbox / "b.md").write_text("two", encoding="utf-8")
    seen = _inbox_entries(inbox)
    (inbox / "b.md").unlink()
    assert _inbox_withdrawn(_inbox_entries(inbox), seen) == ["b.md"]


def test_an_edit_is_unread_and_NOT_a_withdrawal(inbox: Path):
    """The whole reason the digest is stripped before comparing.

    An edited note changes its key. Comparing raw keys would report the old
    key as withdrawn and the new one as unread - the same note, twice, in two
    contradictory sections.
    """
    note = inbox / "a.md"
    note.write_text("one", encoding="utf-8")
    seen = _inbox_entries(inbox)
    note.write_text("EDITED", encoding="utf-8")
    now = _inbox_entries(inbox)
    assert _inbox_withdrawn(now, seen) == []
    assert len(now - seen) == 1


def test_whole_drop_removed_is_reported(inbox: Path):
    drop = inbox / "from-XX-verbatim"
    drop.mkdir()
    (drop / "f.py").write_text("x", encoding="utf-8")
    seen = _inbox_entries(inbox)
    (drop / "f.py").unlink()
    drop.rmdir()
    assert _inbox_withdrawn(_inbox_entries(inbox), seen) == ["from-XX-verbatim/"]


def test_steady_state_reports_nothing(inbox: Path):
    (inbox / "a.md").write_text("one", encoding="utf-8")
    seen = _inbox_entries(inbox)
    assert _inbox_withdrawn(seen, seen) == []
    assert seen - seen == set()


@pytest.mark.parametrize(
    "key,expected",
    [
        ("a.md [7692c3ad3540]", "a.md"),
        ("from-XX-verbatim/ [3 files, content abc123abc123]", "from-XX-verbatim/"),
        ("from-YY/ [2 files, content ff00ff00ff00, MANIFEST.sha256 present]", "from-YY/"),
        ("no-digest.md", "no-digest.md"),
    ],
)
def test_entry_name_strips_only_the_digest(key: str, expected: str):
    assert _entry_name(key) == expected
