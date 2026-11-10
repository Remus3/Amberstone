"""S144-Q-123 (RM-718 residue): data/ds_calibration.jsonl is size-capped.

``core/ds_calibration.py`` ``log_ds_run`` appended one JSON row per coaching
tick (about 30 s) forever, with no size cap. Measured 2026-11-10 on the live
box: 7,193,805 B, 10,469 rows, 2026-05-05 to 2026-08-02 - about 2.4 MB a
month while games are played.

The writer now rotates the file through core.log_rotation (5 MiB x 3, the
RM-718 bound) before an append once it is at or over the cap, under one
module lock. Unlike a plain log the file has a reader, so the rotation must
not cost it rows:

  * ``core.ds_calibration.log_generations`` names the rotation chain that
    exists, OLDEST first (``.2``, ``.1``, base);
  * ``core.ds_calibration_agreement.load_records`` reads every generation in
    that order, so the agreement join still sees the rotated rows;
  * ``scripts/prune_synthetic_matches.py`` ``prune_ds_calibration`` prunes
    every generation, since the reader now reads the rotated ones too.

Every write lands in tmp_path; the module paths are monkeypatched.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import ds_calibration  # noqa: E402
from core import ds_calibration_agreement as dca  # noqa: E402
from core import log_rotation  # noqa: E402
from scripts import prune_synthetic_matches as psm  # noqa: E402

_CAP = 400


@pytest.fixture
def log(tmp_path, monkeypatch):
    target = tmp_path / "ds_calibration.jsonl"
    monkeypatch.setattr(ds_calibration, "_LOG_PATH", target)
    monkeypatch.setattr(ds_calibration, "_MAX_BYTES", _CAP)
    return target


def _tick(game_id: str, champion: str = "Ahri") -> None:
    ds_calibration.log_ds_run(
        champion=champion, mode="ARAM", level=9, owned_items=[3089],
        ds_picks=[{"item_id": 3089, "delta_dps": 12.5}], game_id=game_id,
        match_key=game_id)


def _row(game_id: str, champion: str = "Ahri") -> str:
    return json.dumps({"champion": champion, "mode": "SR", "game_id": game_id})


def _game_ids(path: pathlib.Path) -> list[str]:
    return [json.loads(line)["game_id"]
            for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---- the bound -------------------------------------------------------------

def test_the_cap_is_the_rm718_bound():
    assert ds_calibration._MAX_BYTES == log_rotation.DEFAULT_MAX_BYTES
    assert ds_calibration._BACKUP_COUNT == log_rotation.DEFAULT_BACKUP_COUNT


def test_under_the_cap_the_row_is_appended_and_nothing_rotates(log):
    log.write_bytes(b"x" * (_CAP - 2) + b"\n")
    assert log.stat().st_size == _CAP - 1
    _tick("g-under")
    assert not log.with_name(log.name + ".1").exists()
    assert log.read_bytes().startswith(b"x" * (_CAP - 2) + b"\n")
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith("{")


def test_at_the_cap_the_file_rotates_before_the_append(log):
    old = (_row("g-old") + "\n").encode("utf-8")
    log.write_bytes(old + b"y" * (_CAP - len(old)))
    assert log.stat().st_size == _CAP
    _tick("g-new")
    rotated = log.with_name(log.name + ".1")
    assert rotated.read_bytes().startswith(old)
    assert _game_ids(log) == ["g-new"]


def test_the_chain_is_bounded_at_base_plus_backup_count(log):
    for i in range(60):
        _tick(f"g-{i:03d}")
    names = sorted(p.name for p in log.parent.iterdir())
    assert names == ["ds_calibration.jsonl", "ds_calibration.jsonl.1",
                     "ds_calibration.jsonl.2"]
    for p in log.parent.iterdir():
        assert p.stat().st_size < _CAP + 400


def test_the_rotation_runs_under_the_module_lock(log, monkeypatch):
    seen = []
    real = log_rotation.rotate_if_oversize

    def spy(path, *args, **kwargs):
        seen.append(ds_calibration._LOG_LOCK.locked())
        return real(path, *args, **kwargs)

    monkeypatch.setattr(log_rotation, "rotate_if_oversize", spy)
    log.write_bytes(b"z" * _CAP)
    _tick("g-locked")
    assert seen == [True]


@pytest.mark.parametrize("exc", [OSError(5, "Access is denied"),
                                 ValueError("max_bytes must be > 0"),
                                 RuntimeError("unexpected")],
                         ids=["oserror", "valueerror", "runtimeerror"])
def test_a_failing_rotation_still_appends_the_row(log, monkeypatch, exc):
    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(log_rotation, "rotate_if_oversize", boom)
    log.write_bytes(b"z" * _CAP + b"\n")
    _tick("g-kept")
    assert log.read_text(encoding="utf-8").splitlines()[-1].startswith("{")
    assert '"g-kept"' in log.read_text(encoding="utf-8")


def test_a_crashed_rotation_is_recovered_under_the_cap(log):
    staged = log.with_name(log.name + ".rotating.1234.abcd")
    staged.write_text(_row("g-staged") + "\n", encoding="utf-8")
    _tick("g-after")
    assert not staged.exists()
    assert _game_ids(log.with_name(log.name + ".1")) == ["g-staged"]


# ---- the chain, oldest first -----------------------------------------------

def test_log_generations_is_the_existing_chain_oldest_first(tmp_path):
    base = tmp_path / "ds_calibration.jsonl"
    assert ds_calibration.log_generations(base) == []
    base.write_text("", encoding="utf-8")
    two = base.with_name(base.name + ".2")
    two.write_text("", encoding="utf-8")
    assert ds_calibration.log_generations(base) == [two, base]
    one = base.with_name(base.name + ".1")
    one.write_text("", encoding="utf-8")
    assert ds_calibration.log_generations(base) == [two, one, base]


def test_log_generations_defaults_to_the_module_path(log):
    log.write_text("", encoding="utf-8")
    assert ds_calibration.log_generations() == [log]


def test_scratch_and_recovered_files_are_not_generations(tmp_path):
    base = tmp_path / "ds_calibration.jsonl"
    base.write_text("", encoding="utf-8")
    for name in ("ds_calibration.jsonl.3", "ds_calibration.jsonl.rotating.1.a",
                 "ds_calibration.jsonl.recovered-staged.1.a"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert ds_calibration.log_generations(base) == [base]


# ---- the reader --------------------------------------------------------------

def test_load_records_reads_every_generation_oldest_first(tmp_path):
    base = tmp_path / "ds_calibration.jsonl"
    base.with_name(base.name + ".2").write_text(_row("g1") + "\n", encoding="utf-8")
    base.with_name(base.name + ".1").write_text(
        _row("g2") + "\n" + _row("g3") + "\n", encoding="utf-8")
    base.write_text(_row("g4") + "\n", encoding="utf-8")
    assert [r["game_id"] for r in dca.load_records(base)] == ["g1", "g2", "g3", "g4"]


def test_load_records_reads_rotated_rows_when_the_base_is_gone(tmp_path):
    base = tmp_path / "ds_calibration.jsonl"
    base.with_name(base.name + ".1").write_text(_row("g-rot") + "\n",
                                                encoding="utf-8")
    assert [r["game_id"] for r in dca.load_records(base)] == ["g-rot"]


def test_load_records_skips_a_generation_renamed_after_the_listing(
        tmp_path, monkeypatch):
    base = tmp_path / "ds_calibration.jsonl"
    one = base.with_name(base.name + ".1")
    one.write_text(_row("g-old") + "\n", encoding="utf-8")
    base.write_text(_row("g-new") + "\n", encoding="utf-8")
    gone = base.with_name(base.name + ".2")  # listed, then rotated away
    monkeypatch.setattr(dca, "log_generations", lambda _p: [gone, one, base])
    assert [r["game_id"] for r in dca.load_records(base)] == ["g-old", "g-new"]


def test_load_records_still_fails_soft_on_another_os_error(tmp_path, monkeypatch):
    # Only a vanished generation is skipped: a denied read still fails the
    # whole load soft, as before the cap, even with a readable `.1`.
    base = tmp_path / "ds_calibration.jsonl"
    base.with_name(base.name + ".1").write_text(_row("g-old") + "\n",
                                                encoding="utf-8")
    base.write_text(_row("g-new") + "\n", encoding="utf-8")
    # load_records reads each generation through Path.open (PTH123), so the
    # read fault sits there.
    real_open = pathlib.Path.open

    def denied(self, *args, **kwargs):
        if self == base:
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", denied)
    assert dca.load_records(base) == []


def test_load_records_sees_every_row_across_a_live_rotation(log, monkeypatch):
    # About 170 B a row: 8 rows rotate once under a 1000 B cap and never reach
    # the bounded drop of the oldest generation.
    monkeypatch.setattr(ds_calibration, "_MAX_BYTES", 1000)
    for i in range(8):
        _tick(f"g-{i:02d}")
    assert log.with_name(log.name + ".1").exists(), "the cap never rotated"
    assert not log.with_name(log.name + ".2").exists()
    assert [r["game_id"] for r in dca.load_records(log)] == \
        [f"g-{i:02d}" for i in range(8)]


# ---- the prune -------------------------------------------------------------

def test_the_prune_drops_synthetic_rows_in_every_generation(tmp_path, monkeypatch):
    base = tmp_path / "ds_calibration.jsonl"
    monkeypatch.setattr(psm, "DS_JSONL", base)
    one = base.with_name(base.name + ".1")
    two = base.with_name(base.name + ".2")
    two.write_text(_row("g-clean", "Quinn") + "\n", encoding="utf-8")
    one.write_text(_row("g-a", "Quinn") + "\n" + _row("g-fake", "TestDummy") + "\n",
                   encoding="utf-8")
    base.write_text(_row("g-empty", "") + "\n" + _row("g-b", "Ahri") + "\n",
                    encoding="utf-8")
    clean_before = two.read_bytes()
    result = psm.prune_ds_calibration(dry_run=False)
    assert result == {"in": 5, "dropped": 2, "kept": 3}
    assert _game_ids(one) == ["g-a"]
    assert _game_ids(base) == ["g-b"]
    assert two.read_bytes() == clean_before
    backups = sorted(p.name for p in tmp_path.iterdir() if ".bak-" in p.name)
    assert len(backups) == 2
    assert not any(n.startswith("ds_calibration.jsonl.2.") for n in backups)


def test_the_prune_dry_run_counts_every_generation_and_writes_nothing(
        tmp_path, monkeypatch):
    base = tmp_path / "ds_calibration.jsonl"
    monkeypatch.setattr(psm, "DS_JSONL", base)
    one = base.with_name(base.name + ".1")
    one.write_text(_row("g-fake", "SimBot") + "\n", encoding="utf-8")
    base.write_text(_row("g-b", "Ahri") + "\n", encoding="utf-8")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = psm.prune_ds_calibration(dry_run=True)
    assert result == {"in": 2, "would_drop": 1, "dropped": 0, "kept": 1}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_the_prune_reads_a_rotated_generation_when_the_base_is_gone(
        tmp_path, monkeypatch):
    base = tmp_path / "ds_calibration.jsonl"
    monkeypatch.setattr(psm, "DS_JSONL", base)
    one = base.with_name(base.name + ".1")
    one.write_text(_row("g-fake", "TestDummy") + "\n" + _row("g-a", "Quinn") + "\n",
                   encoding="utf-8")
    result = psm.prune_ds_calibration(dry_run=False)
    assert result == {"in": 2, "dropped": 1, "kept": 1}
    assert _game_ids(one) == ["g-a"]
    assert not base.exists()
