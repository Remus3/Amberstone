"""core/data_retention.py - report-first retention policy over data/.

RM-117 (ii): data/ had no retention policy at all. The ROADMAP premise
("6 GB .rofl corpus growing hourly") is measured FALSE on both halves -
there are ZERO .rofl files under data/, and the real mass is 5.35 GB of
.db plus 3.72 GB of two one-off rewind_history.db backups.

These tests pin the four retention CLASSES apart. The whole point of the
module is that a stale one-off .bak from 2026-07-20 and a live growing
cache are NOT the same problem and must not share a mechanism, so the
tests assert the classifier separates them and that each class carries
its own verdict.

Safety is the headline assertion: plan() must never touch the filesystem.
`test_plan_is_read_only_and_deletes_nothing` is the guard that keeps a
future edit from turning a report into a delete.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.data_retention as dr


def _write(p: Path, size: int) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def _age(p: Path, days: float) -> None:
    import os
    import time
    t = time.time() - days * 86400
    os.utime(p, (t, t))


def _seed(root: Path) -> None:
    """A miniature of the real data/ tree, one file per retention class."""
    _write(root / "rewind_history.db", 4096)
    _write(root / "rewind_history.db.bak_predupe", 4096)
    _age(root / "rewind_history.db.bak_predupe", 45)
    _write(root / "rewind_history.db.bak-20260720", 4096)
    _age(root / "rewind_history.db.bak-20260720", 60)
    _write(root / "riot_api_cache.db", 8192)
    _write(root / "det_coach_shadow.jsonl", 2048)
    _write(root / "daemon_slayer" / "laning_scenarios" / "16.11.1" / "s.json", 512)
    _write(root / "daemon_slayer" / "laning_scenarios" / "16.12.1" / "s.json", 512)
    _write(root / "daemon_slayer" / "laning_scenarios" / "16.13.1" / "s.json", 512)


# -- classification -----------------------------------------------------


def test_stale_backup_and_live_db_land_in_different_classes(tmp_path):
    _seed(tmp_path)
    by_path = {c.path.name: c for c in dr.scan(tmp_path)}

    assert by_path["rewind_history.db.bak_predupe"].klass == dr.CLASS_STALE_BACKUP
    assert by_path["rewind_history.db"].klass != dr.CLASS_STALE_BACKUP


def test_unbounded_cache_is_its_own_class_not_a_backup(tmp_path):
    _seed(tmp_path)
    by_path = {c.path.name: c for c in dr.scan(tmp_path)}

    assert by_path["riot_api_cache.db"].klass == dr.CLASS_UNBOUNDED_CACHE


def test_shadow_jsonl_is_classified_as_an_append_log(tmp_path):
    _seed(tmp_path)
    by_path = {c.path.name: c for c in dr.scan(tmp_path)}

    assert by_path["det_coach_shadow.jsonl"].klass == dr.CLASS_APPEND_LOG


def test_superseded_patch_dirs_are_classified_by_generation(tmp_path):
    _seed(tmp_path)
    dirs = {c.path.name: c for c in dr.scan(tmp_path)
            if c.klass == dr.CLASS_SUPERSEDED_PATCH}

    # keep_patches=2 default: 16.12.1 + 16.13.1 survive, 16.11.1 does not.
    assert "16.11.1" in dirs
    assert "16.12.1" not in dirs
    assert "16.13.1" not in dirs


def test_unknown_files_are_classified_as_retain_not_dropped(tmp_path):
    _write(tmp_path / "aram_coaching_data.json", 128)
    by_path = {c.path.name: c for c in dr.scan(tmp_path)}

    assert by_path["aram_coaching_data.json"].klass == dr.CLASS_RETAIN


# -- policy: each class gets its OWN verdict ----------------------------


def test_each_class_carries_a_distinct_verdict(tmp_path):
    _seed(tmp_path)
    plan = dr.plan(tmp_path)
    verdicts = {k: plan.verdicts[k] for k in plan.verdicts}

    # A stale one-off backup is an operator call, never automatic.
    assert verdicts[dr.CLASS_STALE_BACKUP] == dr.VERDICT_RECOMMEND_OPERATOR
    # An unbounded live cache is deferred to RM-153; report + alarm only.
    assert verdicts[dr.CLASS_UNBOUNDED_CACHE] == dr.VERDICT_ALARM_ONLY
    # Append logs are the one class safe to age out automatically.
    assert verdicts[dr.CLASS_APPEND_LOG] == dr.VERDICT_AUTO_ELIGIBLE
    # Superseded patch generations are regenerable, but DS owns the seam.
    assert verdicts[dr.CLASS_SUPERSEDED_PATCH] == dr.VERDICT_RECOMMEND_OPERATOR


def test_plan_reports_reclaimable_bytes_per_class(tmp_path):
    _seed(tmp_path)
    plan = dr.plan(tmp_path)

    assert plan.bytes_by_class[dr.CLASS_STALE_BACKUP] == 8192
    assert plan.bytes_by_class[dr.CLASS_UNBOUNDED_CACHE] == 8192
    assert plan.bytes_by_class[dr.CLASS_SUPERSEDED_PATCH] == 512


def test_append_log_under_the_age_floor_is_not_eligible(tmp_path):
    _write(tmp_path / "det_coach_shadow.jsonl", 2048)
    plan = dr.plan(tmp_path, max_append_log_age_days=30)

    eligible = [c for c in plan.candidates
                if c.klass == dr.CLASS_APPEND_LOG and c.eligible]
    assert eligible == []


def test_append_log_past_the_age_floor_becomes_eligible(tmp_path):
    p = _write(tmp_path / "det_coach_shadow.jsonl", 2048)
    _age(p, 40)
    plan = dr.plan(tmp_path, max_append_log_age_days=30)

    eligible = [c for c in plan.candidates
                if c.klass == dr.CLASS_APPEND_LOG and c.eligible]
    assert [c.path.name for c in eligible] == ["det_coach_shadow.jsonl"]


def test_fresh_backup_is_reported_but_not_yet_recommended(tmp_path):
    p = _write(tmp_path / "match_history.db.bak-item211-20260528-201639", 4096)
    _age(p, 3)
    plan = dr.plan(tmp_path, max_backup_age_days=30)

    backups = [c for c in plan.candidates if c.klass == dr.CLASS_STALE_BACKUP]
    assert len(backups) == 1
    assert backups[0].eligible is False


# -- the safety guard ---------------------------------------------------


def test_plan_is_read_only_and_deletes_nothing(tmp_path):
    _seed(tmp_path)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    dr.plan(tmp_path)
    dr.scan(tmp_path)
    dr.render_report(dr.plan(tmp_path))

    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert after == before


def test_apply_refuses_without_explicit_confirmation(tmp_path):
    p = _write(tmp_path / "det_coach_shadow.jsonl", 2048)
    _age(p, 90)
    plan = dr.plan(tmp_path)

    result = dr.apply(plan)

    assert result["applied"] is False
    assert result["deleted"] == 0
    assert p.exists()


def test_apply_refuses_a_class_that_is_not_auto_eligible(tmp_path):
    p = _write(tmp_path / "rewind_history.db.bak_predupe", 4096)
    _age(p, 90)
    plan = dr.plan(tmp_path)

    result = dr.apply(plan, confirm=dr.CONFIRM_TOKEN)

    assert result["deleted"] == 0
    assert p.exists()
    assert dr.CLASS_STALE_BACKUP in result["refused_classes"]


# -- termination clause (Riot terms condition (v)) ----------------------


def test_game_information_manifest_covers_riot_derived_paths(tmp_path):
    _seed(tmp_path)
    _write(tmp_path / "aram_coaching_data.json", 128)
    manifest = dr.game_information_manifest(tmp_path)

    names = {p.name for p in manifest.paths}
    assert "rewind_history.db" in names
    assert "riot_api_cache.db" in names
    assert manifest.total_bytes > 0


def test_game_information_manifest_reaches_backups_of_game_information(tmp_path):
    """A termination clause reaches the COPIES too.

    Found by running the manifest against the live tree on 2026-08-04: the
    two rewind_history.db backups are 3.72 GB of the same match data and
    were invisible to the manifest because their names do not END with
    "rewind_history.db". A condition (v) purge that missed them would have
    left the majority of the corpus on disk.
    """
    _seed(tmp_path)
    names = {p.name for p in dr.game_information_manifest(tmp_path).paths}

    assert "rewind_history.db.bak_predupe" in names
    assert "rewind_history.db.bak-20260720" in names


def test_game_information_manifest_reaches_wal_sidecars(tmp_path):
    """The -wal/-shm sidecars hold unflushed rows and are part of the DB."""
    _write(tmp_path / "riot_api_cache.db", 8192)
    _write(tmp_path / "riot_api_cache.db-wal", 512)
    _write(tmp_path / "riot_api_cache.db-shm", 256)
    names = {p.name for p in dr.game_information_manifest(tmp_path).paths}

    assert names == {
        "riot_api_cache.db", "riot_api_cache.db-wal", "riot_api_cache.db-shm",
    }


def test_game_information_manifest_excludes_non_riot_data(tmp_path):
    _write(tmp_path / "icons" / "champions" / "Jinx.png", 64)
    _write(tmp_path / "riot_api_cache.db", 8192)
    manifest = dr.game_information_manifest(tmp_path)

    assert all(p.suffix != ".png" for p in manifest.paths)


def test_game_information_manifest_is_read_only(tmp_path):
    _seed(tmp_path)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    dr.game_information_manifest(tmp_path)

    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert after == before


# -- report rendering ---------------------------------------------------


def test_report_is_ascii_only(tmp_path):
    _seed(tmp_path)
    text = dr.render_report(dr.plan(tmp_path))

    text.encode("ascii")  # raises UnicodeEncodeError on any non-ASCII byte
    assert "STALE_BACKUP" in text


def test_report_names_exact_paths_and_sizes(tmp_path):
    _seed(tmp_path)
    text = dr.render_report(dr.plan(tmp_path))

    assert "rewind_history.db.bak_predupe" in text
    assert "4.0 KB" in text
