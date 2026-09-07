"""Guards for the shared cross-repo inbox poller.

The failure modes worth pinning are the quiet ones: a ladder that escalates
when it should not, a reset that is computed correctly and then ignored for
twelve hours, and a poller that acknowledges mail instead of merely reporting
it. All three are cheap to get wrong and expensive to notice.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import moon_sync_poller as P  # noqa: E402


@pytest.fixture()
def state(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(P, "state_dir", lambda: tmp_path)
    return tmp_path


# ------------------------------------------------------------------- ladder


@pytest.mark.parametrize(
    "idle_seconds,expected_minutes",
    [
        (0, 5),
        (60, 5),
        (19 * 60, 5),
        (20 * 60, 30),
        (60 * 60, 30),
        (4 * 60 * 60 - 1, 30),
        (4 * 60 * 60, 4 * 60),
        (23 * 60 * 60, 4 * 60),
        (24 * 60 * 60, 12 * 60),
        (7 * 24 * 60 * 60, 12 * 60),
    ],
)
def test_interval_ladder(idle_seconds: int, expected_minutes: int):
    assert P.interval_for(idle_seconds) == expected_minutes * 60


def test_ladder_is_monotonic_non_decreasing():
    """More idle must never mean a FASTER poll."""
    prev = 0
    for minutes in range(0, 60 * 30, 7):
        cur = P.interval_for(minutes * 60)
        assert cur >= prev, f"ladder went backwards at {minutes}m"
        prev = cur


def test_every_tier_is_reachable_and_distinct():
    """A tier nobody can sit in is a step that does no work."""
    seen = {P.interval_for(i * 60) for i in range(0, 60 * 48)}
    assert seen == {5 * 60, 30 * 60, 4 * 3600, 12 * 3600}


# -------------------------------------------------------------------- reset


def test_ping_resets_the_ladder(state: Path, monkeypatch):
    """A session prompt is activity even with no mouse movement - the pasted
    hand-off prompt is the common case on this channel."""
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 9 * 60 * 60)
    assert P.interval_for(P.effective_idle_seconds()) == 4 * 3600
    P.ping(r"C:\Some Repo")
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_desktop_input_alone_resets_without_any_prompt(state: Path, monkeypatch):
    P.ping(r"C:\Some Repo")
    old = json.loads((state / "activity.json").read_text(encoding="utf-8"))
    old["repos"][r"C:\Some Repo"] = time.time() - 9 * 60 * 60
    (state / "activity.json").write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 5.0)
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_unknown_input_probe_is_not_treated_as_idle(state: Path, monkeypatch):
    """A failed probe must never escalate the ladder on its own.

    Reporting unknown as idle would silently push a working machine to the
    12 hour tier, and nothing would error.
    """
    monkeypatch.setattr(P, "input_idle_seconds", lambda: None)
    P.ping(r"C:\Some Repo")
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_no_activity_file_at_all_does_not_crash(state: Path, monkeypatch):
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 30.0)
    assert P.effective_idle_seconds() == 30.0


# ------------------------------------------------------------------ scanning


def _repo_with_note(root: Path, name: str, body: str = "x") -> str:
    (root / "moon_sync_inbox").mkdir(parents=True, exist_ok=True)
    (root / "moon_sync_inbox" / name).write_text(body, encoding="utf-8")
    return str(root)


def test_first_sight_of_a_repo_is_a_baseline_not_news(state: Path, tmp_path: Path):
    """The real first run reported hundreds of notes across five repos. A
    report that long is one nobody reads."""
    repo = _repo_with_note(tmp_path / "RepoA0", "old.md")
    assert P.scan_once((repo,)) == {}, "cold start must be silent"
    (Path(repo) / "moon_sync_inbox" / "fresh.md").write_text("new", encoding="utf-8")
    assert P.scan_once((repo,))[repo]["new"], "the note AFTER baseline is news"


def test_scan_reports_new_then_goes_quiet(state: Path, tmp_path: Path):
    repo = _repo_with_note(tmp_path / "RepoA", "a.md")
    P.scan_once((repo,))  # baseline
    (Path(repo) / "moon_sync_inbox" / "b.md").write_text("b", encoding="utf-8")
    first = P.scan_once((repo,))
    assert first[repo]["new"], "a brand new note must be reported"
    assert P.scan_once((repo,)) == {}, "an unchanged inbox must be silent"


def test_an_emptied_inbox_does_not_silently_rebaseline(state: Path, tmp_path: Path):
    """A repo whose inbox empties keeps its entry, so the next arrival is
    still news rather than a fresh baseline."""
    repo = _repo_with_note(tmp_path / "RepoA1", "a.md")
    P.scan_once((repo,))
    (Path(repo) / "moon_sync_inbox" / "a.md").unlink()
    assert P.scan_once((repo,))[repo]["withdrawn"] == ["a.md"]
    (Path(repo) / "moon_sync_inbox" / "c.md").write_text("c", encoding="utf-8")
    assert P.scan_once((repo,))[repo]["new"]


def test_scan_reports_an_edit_in_place(state: Path, tmp_path: Path):
    repo = _repo_with_note(tmp_path / "RepoB", "a.md", "original")
    P.scan_once((repo,))
    (Path(repo) / "moon_sync_inbox" / "a.md").write_text("CORRECTED", encoding="utf-8")
    assert P.scan_once((repo,))[repo]["new"]


def test_scan_reports_a_withdrawal(state: Path, tmp_path: Path):
    repo = _repo_with_note(tmp_path / "RepoC", "a.md")
    P.scan_once((repo,))
    (Path(repo) / "moon_sync_inbox" / "a.md").unlink()
    assert P.scan_once((repo,))[repo]["withdrawn"] == ["a.md"]


def test_scan_never_touches_a_repos_own_watcher_state(state: Path, tmp_path: Path):
    """The poller reports; it must not acknowledge on any repo's behalf.

    A sibling shipped the opposite and their first subagent marked the
    operator's whole queue read.
    """
    repo = Path(tmp_path / "RepoD")
    _repo_with_note(repo, "a.md")
    own = repo / "ops" / "runtime"
    own.mkdir(parents=True)
    seen_file = own / "sync_inbox_seen.json"
    seen_file.write_text(json.dumps({"seen": []}), encoding="utf-8")
    before = seen_file.read_bytes()
    P.scan_once((str(repo),))
    assert seen_file.read_bytes() == before


def test_missing_repo_is_skipped_not_fatal(state: Path, tmp_path: Path):
    assert P.scan_once((str(tmp_path / "nope"),)) == {}


def test_status_file_is_written_even_when_nothing_found(state: Path):
    p = P.write_status({}, idle=42.0, interval=300)
    assert p.exists()
    assert "No new or withdrawn" in p.read_text(encoding="utf-8")


# ----------------------------------------------------------------- singleton


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows named mutex")
def test_second_acquire_of_the_same_name_is_refused():
    """The whole point of "one timer, not five".

    This regressed once already: the guard read the thread error with
    `ctypes.windll.kernel32.GetLastError()`, which the ctypes machinery has
    already reset, so ERROR_ALREADY_EXISTS was never observed and every caller
    was told it had acquired. A unique name per run keeps this independent of
    any poller actually running on the machine.
    """
    import uuid

    name = f"Local\\msp-test-{uuid.uuid4().hex}"
    assert P._acquire_singleton(name) is True, "first acquire must succeed"
    assert P._acquire_singleton(name) is False, "second acquire must be refused"


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows named mutex")
def test_distinct_names_do_not_collide():
    import uuid

    assert P._acquire_singleton(f"Local\\msp-a-{uuid.uuid4().hex}") is True
    assert P._acquire_singleton(f"Local\\msp-b-{uuid.uuid4().hex}") is True


def test_state_dir_is_resolved_from_env_not_hardcoded(monkeypatch, tmp_path: Path):
    """No account name or home path may be baked in."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert P.state_dir() == tmp_path / "moonsync"
    src = Path(P.__file__).read_text(encoding="utf-8")
    assert "Users\\\\Administrator" not in src and "Users/Administrator" not in src
