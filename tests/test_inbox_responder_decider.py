"""Guards for the responder's decider - what fires, and what must never fire.

THE ONE THAT MATTERS MOST. The responder keeps its OWN record of what it has
answered, in its OWN file, and never touches `sync_inbox_seen.json`. That
separation is not tidiness. LL measured the opposite design this week: a
session hook that marked mail seen, firing for every subagent start, so the
first subagent consumed the operator's queue and the operator's own session
then honestly reported "nothing new". RSC's watcher keeps its report record in
a separate file for the same reason and pins it with an arm nobody asked for.

An automated responder is that defect with a bigger engine: it would answer a
note and, as a side effect, tell the operator there was nothing to read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.inbox_responder import (  # noqa: E402
    is_stopped,
    pending_notes,
    record_responded,
    responder_state_path,
)


def _inbox(tmp_path, *names):
    box = tmp_path / "moon_sync_inbox"
    box.mkdir(exist_ok=True)
    for n in names:
        (box / n).write_text("body", encoding="utf-8")
    return box


# ------------------------------------------------- the operator's queue is not ours


def test_responder_record_is_a_different_file_from_the_operator_seen_set(tmp_path):
    assert responder_state_path(tmp_path).name != "sync_inbox_seen.json"


def test_responding_does_not_consume_the_operator_queue(tmp_path):
    """The whole reason this module keeps its own record.

    If this ever fails, answering a note silently marks it read for the human,
    and the operator's next session reports an empty inbox that is not empty.
    """
    seen = tmp_path / "ops" / "runtime" / "sync_inbox_seen.json"
    seen.parent.mkdir(parents=True)
    seen.write_text(json.dumps({"seen": ["a.md"]}), encoding="utf-8")
    before = seen.read_bytes()

    record_responded(tmp_path, "2026-09-07-1800-from-RSC-x.md")

    assert seen.read_bytes() == before


# ------------------------------------------------------------------ what fires


def test_a_new_note_from_a_participant_is_pending(tmp_path):
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == [
        "2026-09-07-1800-from-RSC-x.md"
    ]


def test_an_answered_note_does_not_fire_again(tmp_path):
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    record_responded(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []


def test_a_note_from_a_repo_that_has_not_opted_in_never_fires(tmp_path):
    """Consent is per repo and does not carry over from the polling agreement."""
    box = _inbox(tmp_path, "2026-09-07-1800-from-LL-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []


def test_rc_never_answers_its_own_note(tmp_path):
    """A responder that answers itself is a loop needing no second participant."""
    box = _inbox(tmp_path, "2026-09-07-1806-from-RC-x.md")
    assert pending_notes(box, tmp_path, participants=("RC", "RSC")) == []


def test_non_note_entries_are_ignored(tmp_path):
    """Verbatim payload directories and stray files are not notes to answer."""
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md", "winmutex.py.from-lw", "notes.txt")
    (box / "from-CS-verbatim").mkdir()
    assert pending_notes(box, tmp_path, participants=("RSC", "CS", "LW")) == [
        "2026-09-07-1800-from-RSC-x.md"
    ]


# ---------------------------------------------------------------------------
# RM-385 - what is NOT a note still has to be SEEN
#
# `pending_notes` used to drop two classes silently, on `Path.is_file()` and on
# a missing sender code. Both are invisible-forever conditions rather than
# refusals: the entry sits in the inbox and every later tick reports `empty /
# none_pending`, which is the responder saying nothing is pending while
# something is. Admitting them here does not admit them to the model - gate 6
# judges every one, and anything that is not a plain file with a legal name is
# refused and held for the operator.
# ---------------------------------------------------------------------------


TRANSPOSED = "from-LL-2026-09-07-2035-correction-our-git-identity-count-is-now-two.md"


def test_an_entry_named_like_a_note_but_not_a_file_is_pending(tmp_path):
    """A directory stands in for the junction: both fail `Path.is_file()`."""
    box = tmp_path / "moon_sync_inbox"
    box.mkdir()
    (box / "2026-09-07-1800-from-RSC-x.md").mkdir()
    assert pending_notes(box, tmp_path, participants=("RSC",)) == [
        "2026-09-07-1800-from-RSC-x.md"
    ]


def test_an_md_with_no_sender_code_is_pending_so_gate_6_can_refuse_it(tmp_path):
    """The live instance: a real note with its sender and date TRANSPOSED.

    `_sender_code` looks for `-from-`, and this name begins with `from-`, so
    it returned None and the note was dropped. The live file has sat in RC's
    inbox unseen since 2026-09-07 - and is separately inside the answered
    record, so admitting the CLASS does not put that one file back in the live
    queue.
    """
    box = _inbox(tmp_path, TRANSPOSED)
    assert pending_notes(box, tmp_path, participants=("RSC",)) == [TRANSPOSED]


def test_a_note_from_a_non_participant_is_still_dropped_not_refused(tmp_path):
    """The line RM-385 must NOT cross.

    A note from a repo outside this agreement is not a silent failure - it is
    somebody else's correspondence, and refusing it would put a hold on a note
    RC was never asked to answer. Only an entry with NO identifiable sender is
    admitted for refusal.
    """
    box = _inbox(tmp_path, "2026-09-07-1800-from-LL-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []


def test_pending_is_ordered_by_arrival_not_by_filename(tmp_path):
    """RC retired its own timestamp tie-break after measuring the skew.

    LL's note was stamped 1815 in its filename and hit RC's disk at 17:57:01,
    while RSC's stamped 1800 landed at 17:59:53 - filename order was the exact
    REVERSE of arrival order. Arrival time on the receiving disk is one clock;
    five senders' filenames are five.
    """
    box = tmp_path / "moon_sync_inbox"
    box.mkdir()
    late_name = box / "2026-09-07-1900-from-RSC-stamped-later.md"
    early_name = box / "2026-09-07-1700-from-RSC-stamped-earlier.md"
    late_name.write_text("a", encoding="utf-8")
    import os
    import time

    time.sleep(0.02)
    early_name.write_text("b", encoding="utf-8")
    os.utime(late_name, (1, 1))  # arrived first despite the later stamp

    got = pending_notes(box, tmp_path, participants=("RSC",))
    assert got[0] == late_name.name


# ----------------------------------------------------------------- kill switch


def test_kill_switch_stops_everything(tmp_path):
    (tmp_path / "ops" / "runtime").mkdir(parents=True)
    (tmp_path / "ops" / "runtime" / "INBOX_RESPONDER_STOP").write_text("x", encoding="utf-8")
    assert is_stopped(tmp_path)
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []


def test_not_stopped_by_default(tmp_path):
    assert not is_stopped(tmp_path)


def test_kill_switch_is_checked_even_with_an_unreadable_state_file(tmp_path):
    """A corrupt record must not become a way to bypass the stop flag."""
    (tmp_path / "ops" / "runtime").mkdir(parents=True)
    (tmp_path / "ops" / "runtime" / "INBOX_RESPONDER_STOP").write_text("x", encoding="utf-8")
    responder_state_path(tmp_path).write_text("{{{ not json", encoding="utf-8")
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []


def test_corrupt_state_does_not_replay_every_note(tmp_path):
    """A record that cannot be read must fail CLOSED, not open.

    Failing open would answer the entire back catalogue - 97 notes here - in
    one burst the first time the file is truncated by a crash.
    """
    box = _inbox(tmp_path, "2026-09-07-1800-from-RSC-x.md")
    responder_state_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    responder_state_path(tmp_path).write_text("{{{ not json", encoding="utf-8")
    assert pending_notes(box, tmp_path, participants=("RSC",)) == []
