"""S144-Q-123 (RM-718 residue): the incident log is bounded even when the
self-monitor is off.

`ops/rc_incident_log.py` appends one JSON line per incident in plain append
mode. Its only bound was `purge_old` (age, `retention_days`), and the only
caller of `purge_old` is `ops/rc_self_monitor.py` `_maybe_write_summary`,
which `_tick` reaches only past `if not profile.get("enabled", False):
return`. The live `config/self_monitor_profile.json` carries
`"enabled": false`, while the FROZEN supervisor keeps calling `record()`, so
the purge never ran: measured 2026-11-08, the live
`ops/runtime/incident_log.jsonl` was 3,803,119 B holding 12,869 rows from
2026-04-13 to 2026-11-01 under a 7-day retention.

The fix lives in the writer, not in the monitor: the age purge runs once when
the log is constructed (every supervisor start), and every append enforces a
byte cap (the shared `core.log_rotation.DEFAULT_MAX_BYTES`): age purge first,
then the oldest lines go until the file is at or under half the cap, so the
next append does not rewrite again. Rewrites are atomic (scratch + replace),
because `core/metrics_cache.py` tail-reads this file from another process.
Every write here goes to tmp_path.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import ops.rc_incident_log as incident_mod  # noqa: E402
from core.log_rotation import DEFAULT_MAX_BYTES  # noqa: E402
from ops.rc_incident_log import IncidentLog  # noqa: E402


def _row(ts: datetime, what: str) -> str:
    return json.dumps({"ts": ts.isoformat(), "trigger": what})


def _seed(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("".join(r + "\n" for r in rows)).encode("utf-8"))


def _triggers(path: Path):
    return [json.loads(line)["trigger"]
            for line in path.read_bytes().decode("utf-8").splitlines()
            if line.strip()]


# - age retention no longer needs the monitor -------------------------------

def test_construction_purges_stale_rows_without_the_monitor(tmp_path):
    now = datetime.now(timezone.utc)
    _seed(tmp_path / "incident_log.jsonl", [
        _row(now - timedelta(days=200), "april"),
        _row(now - timedelta(days=8), "last_week"),
        _row(now - timedelta(hours=1), "fresh"),
    ])
    log = IncidentLog(runtime_dir=tmp_path, retention_days=7)
    assert _triggers(log.log_file) == ["fresh"]


def test_construction_keeps_malformed_lines_and_fresh_rows(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "incident_log.jsonl"
    path.write_bytes(b"not json\n" + (_row(now, "fresh") + "\n").encode())
    IncidentLog(runtime_dir=tmp_path, retention_days=7)
    assert path.read_bytes() == b"not json\n" + (_row(now, "fresh") + "\n").encode()


def test_construction_on_a_missing_log_creates_no_file(tmp_path):
    log = IncidentLog(runtime_dir=tmp_path, retention_days=7)
    assert not log.log_file.exists()


def test_construction_leaves_an_all_fresh_log_byte_identical(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "incident_log.jsonl"
    _seed(path, [_row(now, "a"), _row(now, "b")])
    before = path.read_bytes()
    IncidentLog(runtime_dir=tmp_path, retention_days=7)
    assert path.read_bytes() == before


# - the byte cap ---------------------------------------------------------------

def test_default_cap_is_the_shared_log_rotation_default(tmp_path):
    assert IncidentLog(runtime_dir=tmp_path).max_bytes == DEFAULT_MAX_BYTES


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_cap_is_rejected_before_any_side_effect(tmp_path, bad):
    runtime = tmp_path / "runtime"
    with pytest.raises(ValueError, match="max_bytes"):
        IncidentLog(runtime_dir=runtime, max_bytes=bad)
    assert not runtime.exists()


def test_appends_never_leave_the_file_over_the_cap(tmp_path):
    cap = 4000
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=cap)
    for i in range(200):
        log.record("INFO", "app", f"t{i:03d}", detail="x" * 40)
        assert log.log_file.stat().st_size <= cap, i
    got = _triggers(log.log_file)
    assert got[-1] == "t199", "the newest incident was dropped"
    assert "t000" not in got, "the oldest incident survived a trim"
    assert got == sorted(got), "rows are no longer in write order"


def test_a_trim_lands_at_or_under_half_the_cap(tmp_path):
    cap = 4000
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=cap)
    sizes = []
    for i in range(120):
        log.record("INFO", "app", f"t{i:03d}", detail="x" * 40)
        sizes.append(log.log_file.stat().st_size)
    trims = [i for i in range(1, len(sizes)) if sizes[i] < sizes[i - 1]]
    assert len(trims) >= 2, "the cap never trimmed twice"
    assert all(sizes[i] <= cap // 2 for i in trims), sizes
    gaps = [b - a for a, b in zip(trims, trims[1:])]
    # A row is about 200 B here, so half of a 4000 B cap refills over ~10
    # appends; trimming only down to the cap would rewrite on every append.
    assert min(gaps) >= 5, f"hysteresis lost: trims at {trims}"


def test_the_cap_drops_stale_rows_before_any_fresh_row(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "incident_log.jsonl"
    log = IncidentLog(runtime_dir=tmp_path, retention_days=7, max_bytes=3000)
    # Seeded AFTER construction, so only the append-time cap can purge them.
    stale = [_row(now - timedelta(days=30), "stale" + "s" * 60) for _ in range(30)]
    fresh = [_row(now, f"fresh{i}") for i in range(5)]
    _seed(path, stale + fresh)
    assert path.stat().st_size > 3000
    log.record("INFO", "app", "newest")
    assert _triggers(path) == [f"fresh{i}" for i in range(5)] + ["newest"]


def test_under_the_cap_an_append_only_appends(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "incident_log.jsonl"
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=10_000)
    stale = _row(now - timedelta(days=30), "stale")
    _seed(path, [stale])
    before = path.read_bytes()
    log.record("INFO", "app", "next")
    after = path.read_bytes()
    assert after.startswith(before), "an under-cap append rewrote the file"
    assert _triggers(path) == ["stale", "next"]


def test_an_oversize_newest_row_survives_the_trim(tmp_path):
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=1000)
    log.record("INFO", "app", "small")
    log.record("INFO", "app", "w" * 1200)
    got = _triggers(log.log_file)
    assert got == ["w" * 1200], "the trim emptied the file"


def test_trimmed_file_is_whole_lf_lines(tmp_path):
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=2500)
    for i in range(80):
        log.record("INFO", "app", f"t{i}", detail="y" * 30)
    raw = log.log_file.read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    for line in raw.decode("utf-8").splitlines():
        json.loads(line)


# - rewrites are atomic and never raise --------------------------------------

def test_purge_rewrites_through_the_atomic_writer(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed(tmp_path / "incident_log.jsonl",
          [_row(now - timedelta(days=30), "stale"), _row(now, "fresh")])
    calls = []
    real = incident_mod.atomic_write_bytes

    def spy(path, data):
        calls.append(Path(path).name)
        real(path, data)

    monkeypatch.setattr(incident_mod, "atomic_write_bytes", spy)
    log = IncidentLog(runtime_dir=tmp_path, retention_days=7)
    assert calls == ["incident_log.jsonl"]
    assert _triggers(log.log_file) == ["fresh"]


def test_a_failed_trim_keeps_the_log_and_never_raises(tmp_path, monkeypatch):
    log = IncidentLog(runtime_dir=tmp_path, max_bytes=2000)

    def boom(path, data):
        raise PermissionError("held by a reader")

    monkeypatch.setattr(incident_mod, "atomic_write_bytes", boom)
    for i in range(60):
        log.record("INFO", "app", f"t{i}", detail="z" * 30)
    got = _triggers(log.log_file)
    assert got[0] == "t0" and got[-1] == "t59", "a refused trim lost rows"
    assert not list(tmp_path.glob("*.tmp*")), "scratch left behind"
