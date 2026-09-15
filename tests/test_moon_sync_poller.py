"""Guards for the shared cross-repo inbox poller.

The failure modes worth pinning are the quiet ones: a ladder that escalates
when it should not, a reset that is computed correctly and then ignored for
twelve hours, and a poller that acknowledges mail instead of merely reporting
it. All three are cheap to get wrong and expensive to notice.

THE FIXTURE IS PART OF THE GUARD. `state` patches every path the module can
resolve - the writer form, the reader form, the state env var and the module's
own repo root - because the poller now reads a ping file under ITS OWN root as
well as the legacy shared activity.json. Patching only the writer left the
readers pointed at the real machine state, which is how an isolation test can
be green while the thing it names is broken.
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import moon_sync_poller as P  # noqa: E402


@pytest.fixture()
def state(tmp_path: Path, monkeypatch) -> Path:
    """Every reader AND every writer resolves under tmp_path.

    The `_SELF_REPO` patch is MANDATORY, not decorative: the module constant is
    the real RC root at import time and a UserPromptSubmit hook pings it on
    every prompt, so without the patch the ladder tests would see the
    implementing session's own fresh ping. It only works because
    last_prompt_epoch resolves _SELF_REPO at CALL time.
    """
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(tmp_path))
    monkeypatch.setattr(P, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(P, "_state_dir_path", lambda: tmp_path)
    monkeypatch.setattr(P, "_SELF_REPO", str(tmp_path / "self-root"))
    (tmp_path / "self-root").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _self_root(state_dir: Path) -> Path:
    return Path(P._SELF_REPO)


def _plant_ping(root: Path, stamp: float) -> Path:
    d = Path(root) / "ops" / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "moon_sync_activity.json"
    p.write_text(json.dumps({"stamp": stamp, "updated": "x"}), encoding="utf-8")
    return p


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
    P.ping(str(_self_root(state)))
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_desktop_input_alone_resets_without_any_prompt(state: Path, monkeypatch):
    _plant_ping(_self_root(state), time.time() - 9 * 60 * 60)
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 5.0)
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_unknown_input_probe_is_not_treated_as_idle(state: Path, monkeypatch):
    """A failed probe must never escalate the ladder on its own.

    Reporting unknown as idle would silently push a working machine to the
    12 hour tier, and nothing would error.
    """
    monkeypatch.setattr(P, "input_idle_seconds", lambda: None)
    P.ping(str(_self_root(state)))
    assert P.interval_for(P.effective_idle_seconds()) == 5 * 60


def test_no_activity_file_at_all_does_not_crash(state: Path, monkeypatch):
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 30.0)
    assert P.effective_idle_seconds() == 30.0


# ---------------------------------------------------------------- ping file


def test_ping_writes_under_the_repo_root_never_the_state_dir(state: Path, tmp_path: Path):
    root = tmp_path / "sibling-a"
    root.mkdir()
    before = sorted(p.name for p in state.iterdir())
    assert P.ping(str(root)) == 0
    written = root / "ops" / "runtime" / "moon_sync_activity.json"
    assert written.exists(), "the ping must land under the repo root"
    blob = json.loads(written.read_text(encoding="utf-8"))
    assert isinstance(blob["stamp"], float)
    assert not (state / "activity.json").exists()
    assert sorted(p.name for p in state.iterdir()) == before


def test_ping_to_an_absent_repo_root_writes_nothing(state: Path, tmp_path: Path):
    control = tmp_path / "sibling-b"
    control.mkdir()
    assert P.ping(str(control)) == 0
    assert (control / "ops" / "runtime" / "moon_sync_activity.json").exists()

    missing = tmp_path / "nope"
    assert P.ping(str(missing)) == 0
    assert not missing.exists()


def test_ping_creates_ops_runtime_and_never_raises(state: Path, tmp_path: Path, monkeypatch):
    root = tmp_path / "sibling-c"
    root.mkdir()
    assert P.ping(str(root)) == 0
    assert (root / "ops" / "runtime" / "moon_sync_activity.json").exists()

    def boom(*_a, **_k):
        raise PermissionError(5, "held")

    monkeypatch.setattr(P, "_replace_with_retry", boom)
    assert P.ping(str(root)) == 0


def test_no_state_dir_writer_is_reachable_from_ping(state: Path, tmp_path: Path, monkeypatch):
    def boom():
        raise AssertionError("ping must never touch the state dir")

    monkeypatch.setattr(P, "state_dir", boom)
    root = tmp_path / "sibling-d"
    root.mkdir()
    assert P.ping(str(root)) == 0
    assert (root / "ops" / "runtime" / "moon_sync_activity.json").exists()


def test_last_prompt_epoch_takes_the_max_over_legacy_and_repo_root_pings(state: Path, tmp_path: Path):
    base = time.time() - 10_000
    (state / "activity.json").write_text(json.dumps({"repos": {"x": base}, "updated": "x"}), encoding="utf-8")
    _plant_ping(_self_root(state), base + 100)
    assert P.last_prompt_epoch() == pytest.approx(base + 100)

    (state / "activity.json").write_text(json.dumps({"repos": {"x": base + 100}, "updated": "x"}), encoding="utf-8")
    _plant_ping(_self_root(state), base)
    assert P.last_prompt_epoch() == pytest.approx(base + 100)

    # A sibling root is NEVER read: plant a much newer ping there, remove the
    # self-root file, and the legacy stamp must still win.
    (_self_root(state) / "ops" / "runtime" / "moon_sync_activity.json").unlink()
    (state / "activity.json").write_text(json.dumps({"repos": {"x": base}, "updated": "x"}), encoding="utf-8")
    _plant_ping(tmp_path / "sibling-a", base + 200)
    assert P.last_prompt_epoch() == pytest.approx(base)


# ------------------------------------------------------------------ scanning


def _repo_with_note(root: Path, name: str, body: str = "x") -> str:
    (root / "moon_sync_inbox").mkdir(parents=True, exist_ok=True)
    (root / "moon_sync_inbox" / name).write_text(body, encoding="utf-8")
    return str(root)


def _participants(*pairs) -> dict:
    return {P._norm_root(str(root)): code for root, code in pairs}


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
    assert not (own / "sync_inbox_reported.json").exists()


def test_missing_repo_is_skipped_not_fatal(state: Path, tmp_path: Path):
    assert P.scan_once((str(tmp_path / "nope"),)) == {}


def test_status_file_is_written_even_when_nothing_found(state: Path):
    p = P.write_status({}, idle=42.0, interval=300)
    assert p.exists()
    assert "No new or withdrawn" in p.read_text(encoding="utf-8")


def test_scan_once_rewrites_the_updated_stamp_on_every_call(state: Path, tmp_path: Path, monkeypatch):
    repo = _repo_with_note(tmp_path / "RepoE", "a.md")
    stamps = iter(["2026-01-01T00:00:00+00:00", "2026-01-01T00:05:00+00:00"])
    monkeypatch.setattr(P, "_utcnow", lambda: next(stamps))
    P.scan_once((repo,))
    first = json.loads((state / "poller_seen.json").read_text(encoding="utf-8"))["updated"]
    P.scan_once((repo,))
    second = json.loads((state / "poller_seen.json").read_text(encoding="utf-8"))["updated"]
    assert first != second


def test_a_raising_repo_scan_does_not_stop_the_status_write(state: Path, tmp_path: Path, monkeypatch):
    good = Path(_repo_with_note(tmp_path / "sibling-a", "old.md"))
    bad = Path(_repo_with_note(tmp_path / "sibling-b", "x.md"))
    parts = _participants((good, "AAA"), (bad, "BBB"))
    P.scan_fleet((str(good), str(bad)), parts)  # baseline both
    (good / "moon_sync_inbox" / "arrived.md").write_text("n", encoding="utf-8")

    real = P._inbox_entries

    def flaky(inbox: Path):
        if "sibling-b" in str(inbox):
            raise RuntimeError("boom")
        return real(inbox)

    monkeypatch.setattr(P, "_inbox_entries", flaky)
    out = P.scan_fleet((str(good), str(bad)), parts)
    statuses = {r["code"]: r["status"] for r in out["rows"]}
    assert statuses["BBB"] == "SCAN FAULT RuntimeError"
    assert statuses["AAA"] == "OK"
    assert any("arrived.md" in n for n in out["rows"][0]["new"])
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    text = p.read_text(encoding="utf-8")
    assert "SCAN FAULT RuntimeError" in text
    assert "arrived.md" in text


def test_absent_inbox_renders_inbox_absent_not_silence(state: Path, tmp_path: Path):
    root = tmp_path / "sibling-a"
    root.mkdir()
    parts = _participants((root, "AAA"))
    out = P.scan_fleet((str(root),), parts)
    assert out["rows"][0]["status"] == "INBOX ABSENT"
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    assert "AAA: INBOX ABSENT" in p.read_text(encoding="utf-8")
    assert P.scan_once((str(root),)) == {}


# ------------------------------------------------------------ boot baseline


def _plant_seen(state_dir: Path, updated_epoch: float, repos: dict) -> None:
    from datetime import datetime, timezone

    stamp = datetime.fromtimestamp(updated_epoch, timezone.utc).isoformat(timespec="seconds")
    (state_dir / "poller_seen.json").write_text(
        json.dumps({"updated": stamp, "repos": repos}, indent=2), encoding="utf-8"
    )


def test_boot_rebaselines_a_stale_store_with_one_line_and_no_new_lines(state: Path, tmp_path: Path):
    root = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    (root / "moon_sync_inbox" / "b.md").write_text("b", encoding="utf-8")
    parts = _participants((root, "AAA"))
    now = time.time()

    # CONTROL: with the stale store in place the unreset scan WOULD flood.
    _plant_seen(state, now - 25 * 3600, {str(root): ["ghost.md [000000000000]"]})
    control = P.scan_once((str(root),))
    n = len(control[str(root)]["new"])
    assert n == 2, "the control arm must prove the fixture would have flooded"

    _plant_seen(state, now - 25 * 3600, {str(root): ["ghost.md [000000000000]"]})
    note = P._boot_rebaseline(now, (str(root),), parts)
    assert note is not None
    assert note.startswith("baseline reset at boot")
    assert f"would have reported: {n} NEW" in note
    assert "AAA:2" in note
    after = P.scan_fleet((str(root),), parts)
    assert after["findings"] == {}

    # UNREADABLE: never a silent restart from {}.
    (state / "poller_seen.json").write_text("{not json", encoding="utf-8")
    note2 = P._boot_rebaseline(now, (str(root),), parts)
    assert note2 is not None
    assert "persisted seen unreadable (ValueError)" in note2
    assert "would have reported: UNMEASURED" in note2

    # ABSENT: a fresh install is a legitimate silent baseline.
    (state / "poller_seen.json").unlink()
    assert P._boot_rebaseline(now, (str(root),), parts) is None


def test_boot_keeps_a_fresh_store(state: Path, tmp_path: Path):
    root = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    parts = _participants((root, "AAA"))
    now = time.time()
    _plant_seen(state, now - 300, {str(root): []})
    assert P._boot_rebaseline(now, (str(root),), parts) is None
    out = P.scan_fleet((str(root),), parts)
    assert out["findings"][str(root)]["new"], "a fresh store must keep reporting"

    # A routine deep-tier restart: 12h 5m old is legitimate, not stale.
    _plant_seen(state, now - (12 * 3600 + 300), {str(root): []})
    assert P._boot_rebaseline(now, (str(root),), parts) is None


# ---------------------------------------------------------- findings ledger


def test_findings_ledger_carries_names_and_is_bounded_and_rewritten(state: Path, tmp_path: Path):
    root = Path(_repo_with_note(tmp_path / "sibling-a", "note.md"))
    (root / "moon_sync_inbox" / "from-AAA-verbatim").mkdir()
    (root / "moon_sync_inbox" / "from-AAA-verbatim" / "f.txt").write_text("f", encoding="utf-8")
    parts = _participants((root, "AAA"))
    P.scan_fleet((str(root),), parts)  # baseline
    (root / "moon_sync_inbox" / "arrived.md").write_text("n", encoding="utf-8")
    out = P.scan_fleet((str(root),), parts)
    P._record_findings(out["rows"])
    blob = json.loads((state / "findings.json").read_text(encoding="utf-8"))
    assert blob["schema"] == 1
    arrived = [r for r in blob["findings"] if r["name"] == "arrived.md"]
    assert arrived and arrived[0]["kind"] == "NEW" and arrived[0]["code"] == "AAA"
    assert len(arrived[0]["digest12"]) == 12

    (root / "moon_sync_inbox" / "arrived.md").unlink()
    out2 = P.scan_fleet((str(root),), parts)
    size_before = (state / "findings.json").stat().st_size
    P._record_findings(out2["rows"])
    blob2 = json.loads((state / "findings.json").read_text(encoding="utf-8"))
    kinds = {(r["name"], r["kind"]) for r in blob2["findings"]}
    assert ("arrived.md", "NEW") in kinds and ("arrived.md", "WITHDRAWN") in kinds
    assert (state / "findings.json").stat().st_size < size_before * 3, "never appended"

    # A directory payload carries a null digest.
    dirs = [r for r in blob2["findings"] if r["name"].endswith("/")]
    assert dirs == [] or dirs[0]["digest12"] is None

    # 250 synthetic NEW rows for one code -> exactly 200 kept, oldest dropped.
    rows = [
        {"code": "AAA", "status": "OK", "entries": 0, "new": [f"n{i:04d}.md [0123456789ab]"], "withdrawn": []}
        for i in range(250)
    ]
    (state / "findings.json").unlink()
    for i, row in enumerate(rows):
        P._record_findings([row], now=time.time() - (250 - i))
    kept = json.loads((state / "findings.json").read_text(encoding="utf-8"))["findings"]
    assert len(kept) == 200
    names = [r["name"] for r in kept]
    assert "n0249.md" in names and "n0000.md" not in names


def test_corrupt_findings_ledger_is_unmeasured_not_zero(state: Path, tmp_path: Path):
    root = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    parts = _participants((root, "AAA"))
    P.scan_fleet((str(root),), parts)
    (root / "moon_sync_inbox" / "arrived.md").write_text("n", encoding="utf-8")
    out = P.scan_fleet((str(root),), parts)

    (state / "findings.json").write_text("{not json", encoding="utf-8")
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    assert "- findings: UNMEASURED (ValueError)" in p.read_text(encoding="utf-8")
    P._record_findings(out["rows"])
    blob = json.loads((state / "findings.json").read_text(encoding="utf-8"))
    assert len(blob["findings"]) == 1

    p2 = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    assert "UNMEASURED" not in p2.read_text(encoding="utf-8")


# -------------------------------------------------------------- status file


def test_status_md_is_persistent_state_with_pid_and_expect_next_poll(state: Path, tmp_path: Path):
    p = P.write_status({}, idle=10.0, interval=300, rows=[])
    text = p.read_text(encoding="utf-8")
    assert f"- pid: {os.getpid()}" in text
    h = P.parse_status_header(text)
    assert h["pid"] == os.getpid()
    assert h["fleet_view"] is True
    assert h["expect_next_poll_by"] == pytest.approx(h["checked"] + 300 + 60, abs=2)
    assert "No new or withdrawn inbox entries in any participating repo." in text


def test_status_md_renders_codes_never_paths(state: Path, tmp_path: Path):
    import re

    a = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    b = Path(_repo_with_note(tmp_path / "sibling-b", "b.md"))
    parts = _participants((a, "AAA"), (b, "BBB"))
    P.scan_fleet((str(a), str(b)), parts)
    (a / "moon_sync_inbox" / "arrived.md").write_text("n", encoding="utf-8")
    out = P.scan_fleet((str(a), str(b)), parts)
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    P._record_findings(out["rows"])
    text = p.read_text(encoding="utf-8")
    ledger = (state / "findings.json").read_text(encoding="utf-8")
    assert "AAA" in text and "BBB" in text
    for blob in (text, ledger):
        assert not re.search(r"[A-Za-z]:[\\/]", blob)
        assert "sibling-a" not in blob and "sibling-b" not in blob


def test_status_md_quiet_state_under_1kb(state: Path, tmp_path: Path):
    rows = [
        {"code": c, "status": "OK", "entries": 0, "new": [], "withdrawn": []}
        for c in ("AAA", "BBB", "CCC", "DDD", "EEE")
    ]
    p = P.write_status({}, 1.0, 300, rows=rows)
    raw = p.read_bytes()
    assert len(raw) < 1024, len(raw)
    for c in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        assert c in raw.decode("utf-8")


def test_status_md_size_cap_5x250(state: Path, tmp_path: Path):
    codes = ("AAA", "BBB", "CCC", "DDD", "EEE")
    long_name = "z" * 130
    roots = []
    for i, code in enumerate(codes):
        root = tmp_path / f"sibling-{chr(ord('a') + i)}"
        (root / "moon_sync_inbox").mkdir(parents=True)
        for n in range(250):
            (root / "moon_sync_inbox" / f"{n:03d}{long_name}.md").write_text("x", encoding="utf-8")
        roots.append(root)
    parts = _participants(*zip(roots, codes))
    _plant_seen(state, time.time(), {str(r): [] for r in roots})
    out = P.scan_fleet(tuple(str(r) for r in roots), parts)
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    raw = p.read_bytes()
    # The bound is the LITERAL, never P.STATUS_MAX_BYTES: an assertion that
    # reads the constant it is pinning follows the constant anywhere it moves
    # and proves nothing (mutating it to 10**9 left this test green).
    assert len(raw) <= 4096, len(raw)
    text = raw.decode("utf-8")
    for code in codes:
        assert f"- {code}: 250 entries" in text
    assert text.count("more - findings.json") >= 5


def test_status_md_bytes_on_disk_are_lf_only(state: Path):
    """The LF hold in _atomic_write is a GUARD, so it gets an assertion.

    Read the RAW BYTES. A text read normalises the ending on the way in, so a
    file written CRLF reads back LF and the check passes over the defect it
    exists to catch. Both writers are covered: the normal render and the
    minimal fault render, because they share the one atomic writer.
    """
    rows = [P._fleet_row("AAA", "OK", 3), P._fleet_row("BBB", "INBOX ABSENT")]
    raw = P.write_status({}, 1.0, 300, rows=rows).read_bytes()
    assert b"\r\n" not in raw, "status.md must be LF on disk"
    assert raw.count(b"\n") > 5, raw

    raw_fault = P._write_minimal_status(RuntimeError("boom")).read_bytes()
    assert b"\r\n" not in raw_fault, "the fault render must be LF on disk too"


def test_status_md_size_cap_holds_when_the_render_lands_just_under_the_bound(state: Path):
    """The cap is measured in memory and enforced on DISK, and the two agree
    only while the writer holds LF.

    The 5x250 fixture cannot see this: it renders 3337 bytes over 42 lines, so
    even CRLF reaches 3379 - nowhere near 4096, and the bound never binds. The
    production shape is the opposite one. _render_status steps the name count
    3 -> 2 -> 1 -> 0 and stops at the FIRST size that fits, so a wide fleet
    routinely lands JUST under 4096, which is exactly the band where one extra
    byte per line overflows the bound the render believed it had respected.

    So the fixture is SEARCHED, not hardcoded: pick the fleet width whose LF
    render fits the bound while its CRLF twin would not. If no width in the
    sweep lands in that band this test fails loudly rather than quietly
    degrading into a non-discriminating one.
    """
    now = time.time()
    checked = P._iso(now)
    chosen = None
    for n in range(2, 200):
        rows = [P._fleet_row(f"R{i:03d}", "OK", 7) for i in range(n)]
        window, failure = P._window_view(rows, now)
        text = P._render_status({}, 1.0, 300, rows, None, 0, now, 0, window, failure, checked)
        size = len(text.encode("utf-8"))
        crlf_size = size + text.count("\n")
        if size <= 4096 < crlf_size:
            chosen = (rows, size, crlf_size)
            break
    assert chosen is not None, "no fleet width lands in the CRLF-discriminating band"
    rows, lf_size, crlf_size = chosen

    raw = P.write_status({}, 1.0, 300, rows=rows).read_bytes()
    # The bound is the LITERAL, never P.STATUS_MAX_BYTES - see the 5x250 note.
    assert len(raw) <= 4096, (len(raw), lf_size, crlf_size)
    assert b"\r\n" not in raw
    assert f"- {rows[-1]['code']}: 7 entries" in raw.decode("utf-8")


def test_status_md_carries_the_prompt_half_line_and_dead_when_blind(state: Path, tmp_path: Path):
    root = _self_root(state)
    now = time.time()
    _plant_ping(root, now - 10_000)
    log = root / "ops" / "runtime" / "hook_invocations.jsonl"

    def write_log(rows):
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def row(event, offset, payload=True):
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 10_000 + offset)),
            "event": event,
            "payload": payload,
        }

    write_log([row("UserPromptSubmit", 2 * P.TICK_SECONDS)])
    text = P.write_status({}, 1.0, 300, rows=[]).read_text(encoding="utf-8")
    assert "- prompt half:" in text
    assert P.parse_status_header(text)["prompt_half_dead"] is True
    assert [ln for ln in text.splitlines() if ln.startswith("- prompt half:")][0].endswith(" DEAD")
    assert any("prompt half DEAD" in ln for ln in P.status_report(self_root=str(root)))

    write_log([row("UserPromptSubmit", 10)])
    text = P.write_status({}, 1.0, 300, rows=[]).read_text(encoding="utf-8")
    assert P.parse_status_header(text)["prompt_half_dead"] is False

    write_log([row("SessionStart", 2 * P.TICK_SECONDS)])
    text = P.write_status({}, 1.0, 300, rows=[]).read_text(encoding="utf-8")
    assert P.parse_status_header(text)["prompt_half_dead"] is False


def test_unmapped_root_prints_a_participants_map_absent_line(state: Path, tmp_path: Path):
    a = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    b = Path(_repo_with_note(tmp_path / "sibling-b", "b.md"))
    out = P.scan_fleet((str(a), str(b)), {})
    p = P.write_status(out["findings"], 1.0, 300, rows=out["rows"])
    text = p.read_text(encoding="utf-8")
    assert "- participants map absent: 2 roots UNMAPPED" in text
    assert any("participants map absent: 2 roots UNMAPPED" in ln for ln in P.status_report(state_path=state))

    out2 = P.scan_fleet((str(a), str(b)), _participants((a, "AAA"), (b, "BBB")))
    p2 = P.write_status(out2["findings"], 1.0, 300, rows=out2["rows"])
    assert "participants map absent" not in p2.read_text(encoding="utf-8")


# ------------------------------------------------------------------ verdict


def _header(
    checked: float, interval: int, pid: int | None = 4242, fault: str | None = None, fleet_view: bool = True
) -> dict:
    return {
        "checked": checked,
        "interval": interval,
        "pid": pid,
        "expect_next_poll_by": checked + interval + 60,
        "fleet_view": fleet_view,
        "fault": fault,
        "boot": None,
        "unmapped_roots": 0,
        "prompt_half": None,
        "prompt_half_dead": False,
    }


def test_status_verdict_six_way(state: Path, monkeypatch):
    t0 = 1_000_000.0
    h = _header(t0, 300)
    assert P.status_verdict(h, t0 + 100, True) == "LIVE"
    assert P.status_verdict(h, t0 + 400, True) == "OVERDUE"
    assert P.status_verdict(h, t0 + 5000, True) == "STALE"
    assert P.status_verdict(h, t0 + 100, False) == "DEAD"

    # A pre-fleet-view file carries no pid line, so pid_alive is None. The time
    # rule must apply and the verdict must never be DEAD.
    pre = _header(t0, 300, pid=None, fleet_view=False)
    assert P.status_verdict(pre, t0 + 500, None) == "OVERDUE"
    assert P.status_verdict(pre, t0 + 5000, None) == "STALE"

    faulted = _header(t0, 300, fault="RuntimeError")
    assert P.status_verdict(faulted, t0 + 1, True) == "FAULT"

    monkeypatch.setattr(P, "_open_process", lambda pid: (0, 87))
    assert P._pid_alive(4242) is False
    monkeypatch.setattr(P, "_open_process", lambda pid: (0, 5))
    assert P._pid_alive(4242) is None
    assert P.status_verdict(h, t0 + 400, P._pid_alive(4242)) == "OVERDUE"
    monkeypatch.setattr(P, "_open_process", lambda pid: (7, 0))
    monkeypatch.setattr(P, "_process_exit_code", lambda h_: 259)
    assert P._pid_alive(4242) is True


# ----------------------------------------------------------------- run loop


def test_a_tier_climb_between_polls_keeps_the_written_promise(state: Path, tmp_path: Path, monkeypatch):
    """run() recomputes the ladder every tick; the FILE promised an interval.

    Before the fix run() waited the NEW 30 minute interval after the tier
    climbed while status.md still promised 5 minutes, so a healthy poller read
    OVERDUE from +6 minutes and STALE from +11.
    """
    repo = _repo_with_note(tmp_path / "sibling-a", "a.md")
    clock = {"t": 1_000_000.0}
    polls: list[float] = []
    texts: list[str] = []

    monkeypatch.setattr(P.time, "time", lambda: clock["t"])

    def fake_sleep(sec):
        clock["t"] += sec
        if len(polls) >= 2:
            raise StopIteration

    monkeypatch.setattr(P.time, "sleep", fake_sleep)
    monkeypatch.setattr(P, "_acquire_singleton", lambda *a, **k: True)
    monkeypatch.setattr(P, "effective_idle_seconds", lambda now=None: 16 * 60 if not polls else 21 * 60)

    real_write = P.write_status

    def spy(*a, **k):
        polls.append(clock["t"])
        out = real_write(*a, **k)
        texts.append(out.read_text(encoding="utf-8"))
        return out

    monkeypatch.setattr(P, "write_status", spy)
    with pytest.raises(StopIteration):
        P.run((repo,))

    assert len(polls) >= 2
    gap = polls[1] - polls[0]
    assert gap <= 300 + P.TICK_SECONDS, f"the written 5 minute promise was not honoured (gap {gap}s)"

    h = P.parse_status_header(texts[0])
    for offset in range(0, int(gap), 60):
        assert P.status_verdict(h, h["checked"] + offset, True) == "LIVE"


def test_write_status_survives_a_reader_holding_the_target(state: Path):
    P.write_status({}, 1.0, 300, rows=[])
    target = state / "status.md"
    before = target.read_bytes()
    handle = open(target, encoding="utf-8")
    try:
        P.write_status({}, 2.0, 300, rows=[])
    finally:
        handle.close()
    log = (state / "poller.log").read_text(encoding="utf-8") if (state / "poller.log").exists() else ""
    assert target.read_bytes() != before or "FAULT PermissionError" in log


def test_replace_retries_once_then_a_permanent_failure_logs_fault_and_the_loop_continues(
    state: Path, tmp_path: Path, monkeypatch
):
    calls = {"n": 0}
    real_replace = os.replace

    def once(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(5, "held")
        return real_replace(src, dst)

    monkeypatch.setattr(P.os, "replace", once)
    p = P.write_status({}, 1.0, 300, rows=[])
    assert p.exists() and "- pid:" in p.read_text(encoding="utf-8")
    monkeypatch.undo()

    repo = _repo_with_note(tmp_path / "sibling-a", "a.md")
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(state))
    monkeypatch.setattr(P, "state_dir", lambda: state)
    monkeypatch.setattr(P, "_state_dir_path", lambda: state)
    monkeypatch.setattr(P, "_SELF_REPO", str(state / "self-root"))
    monkeypatch.setattr(P, "_acquire_singleton", lambda *a, **k: True)
    ticks = {"n": 0}

    def always(src, dst):
        raise PermissionError(5, "held")

    def fake_sleep(sec):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            raise StopIteration

    monkeypatch.setattr(P, "write_status", lambda *a, **k: (_ for _ in ()).throw(PermissionError(5, "held")))
    monkeypatch.setattr(P.time, "sleep", fake_sleep)
    monkeypatch.setattr(P, "_write_minimal_status", lambda *a, **k: always)
    with pytest.raises(StopIteration):
        P.run((repo,))
    assert ticks["n"] >= 2, "the loop must survive a write fault"
    assert "FAULT PermissionError" in (state / "poller.log").read_text(encoding="utf-8")


# -------------------------------------------------------------- status view


def test_status_command_writes_nothing_and_takes_no_singleton(state: Path, monkeypatch, capsys):
    P.write_status({}, 1.0, 300, rows=[])
    text = (state / "status.md").read_text(encoding="utf-8")
    checked = P.parse_status_header(text)["checked"]

    def refuse(*_a, **_k):
        raise AssertionError("--status must never take the singleton")

    monkeypatch.setattr(P, "_acquire_singleton", refuse)
    monkeypatch.setattr(P, "input_idle_seconds", lambda: 1.0)

    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in state.iterdir() if p.is_file()}
    assert P.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert f"pid {os.getpid()}" in out
    age = [ln for ln in out.splitlines() if ln.startswith("status.md age ")]
    assert age, out
    assert int(age[0].split()[2].rstrip("s")) <= int(time.time() - checked) + 5
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in state.iterdir() if p.is_file()}
    assert after == before


def test_status_command_prints_the_seen_store_stamp_line(state: Path, tmp_path: Path):
    root = Path(_repo_with_note(tmp_path / "sibling-a", "a.md"))
    P.write_status({}, 1.0, 300, rows=[])
    old = time.time() - 4 * 3600
    _plant_seen(state, old, {str(root): []})
    lines = P.status_report()
    seen_lines = [ln for ln in lines if ln.startswith("seen store: updated ")]
    assert seen_lines, lines
    assert "2026" in seen_lines[0] or "updated" in seen_lines[0]
    assert f"{(state / 'poller_seen.json').stat().st_size} B" in seen_lines[0]
    stale_stamp = seen_lines[0]

    _plant_seen(state, time.time(), {str(root): []})
    fresh = [ln for ln in P.status_report() if ln.startswith("seen store: updated ")]
    assert fresh and fresh[0] != stale_stamp


def test_status_command_reports_prompt_half_dead_when_invocations_outrun_pings(state: Path):
    root = _self_root(state)
    now = time.time()
    _plant_ping(root, now - 10_000)
    log = root / "ops" / "runtime" / "hook_invocations.jsonl"

    def row(event, offset, payload=True):
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 10_000 + offset)),
            "event": event,
            "payload": payload,
        }

    log.write_text(json.dumps(row("UserPromptSubmit", 2 * P.TICK_SECONDS)) + "\n", encoding="utf-8")
    out = P.status_report(now=now, self_root=str(root))
    assert any("prompt half DEAD" in ln for ln in out)
    half = [ln for ln in out if ln.startswith("prompt half: ")][0]
    assert f"last ping {int(now - (now - 10_000))}s" in half

    log.write_text(json.dumps(row("UserPromptSubmit", 10)) + "\n", encoding="utf-8")
    assert not any("prompt half DEAD" in ln for ln in P.status_report(now=now, self_root=str(root)))

    log.write_text(json.dumps(row("SessionStart", 2 * P.TICK_SECONDS)) + "\n", encoding="utf-8")
    assert not any("prompt half DEAD" in ln for ln in P.status_report(now=now, self_root=str(root)))


def test_virtualized_view_line_when_final_path_is_under_localcache(state: Path, monkeypatch):
    P.write_status({}, 1.0, 300, rows=[])
    monkeypatch.setattr(
        P, "_final_path", lambda p: r"\\?\C:\Users\x\AppData\Local\Packages\x\LocalCache\Local\moonsync\status.md"
    )
    assert any("VIRTUALIZED VIEW: status.md" in ln for ln in P.status_report())
    monkeypatch.setattr(P, "_final_path", lambda p: str(p))
    assert not any("VIRTUALIZED VIEW" in ln for ln in P.status_report())


# ------------------------------------------------------------- isolation


def test_fixture_isolates_every_reader(state: Path, tmp_path: Path):
    assert P._state_dir_path() == tmp_path
    assert P.state_dir() == tmp_path
    # BEHAVIOUR FIRST. Round one asserted only the attribute equality below and
    # stayed green while the isolation it named was broken, so the planted-ping
    # arm is the real guard and the attribute check is corroboration.
    assert P.last_prompt_epoch() == 0.0
    stamp = time.time() - 42
    _plant_ping(_self_root(state), stamp)
    assert P.last_prompt_epoch() == pytest.approx(stamp)
    assert P.last_prompt_epoch.__defaults__ == (None,)
    out = "\n".join(P.status_report())
    assert str(tmp_path) in out
    assert "Packages\\" not in out


def test_state_dir_env_override_wins_over_localappdata(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("RC_MOON_SYNC_STATE", str(tmp_path / "x"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "y"))
    assert P._state_dir_path() == tmp_path / "x"
    assert not (tmp_path / "x").exists(), "the reader form must never mkdir"


def test_state_dir_is_resolved_from_env_not_hardcoded(monkeypatch, tmp_path: Path):
    """No account name or home path may be baked in."""
    monkeypatch.delenv("RC_MOON_SYNC_STATE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert P.state_dir() == tmp_path / "moonsync"
    src = Path(P.__file__).read_text(encoding="utf-8")
    assert "Users\\\\Administrator" not in src and "Users/Administrator" not in src


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


# ------------------------------------------------------------ source guards


def test_poller_never_imports_subprocess():
    """A spawn from this file is the console-flash class. It has none today."""
    src = Path(P.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] != "subprocess" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "subprocess"
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert node.value.id != "subprocess"


def test_status_and_fleet_flags_are_not_wired_to_any_hook():
    settings = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"
    if not settings.exists():
        pytest.skip("settings.json is gitignored and absent in this checkout")
    blob = json.loads(settings.read_text(encoding="utf-8"))
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str) and ("--status" in node or "--fleet" in node):
            found.append(node)

    walk(blob)
    assert found == [], found
