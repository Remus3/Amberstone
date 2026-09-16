"""RM-442: scripts/data_pipeline.py `...Z` stamps must be the UTC instant.

`time.strftime(fmt)` with no time tuple formats LOCAL time, so a stamp built
that way and suffixed `Z` is off by the host's UTC offset while claiming UTC.
Two sites carried it: `downloaded_at` in data/meta/ddragon_version.json
(cmd_ddragon) and `generated_at` in the rank-tier artifact (cmd_rank_tiers).

`time.tzset` does not exist on Windows and CI hosts run in UTC, where local
time and UTC coincide, so the TZ environment cannot be relied on to expose the
bug. Instead `fake_offset_zone` routes a tuple-less `time.strftime` through a
patched `time.localtime` that is five hours ahead of UTC. The positive control
shows that under this harness a local-time stamp really does miss UTC.

No network and no real repo file: every path is redirected into tmp_path.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

import scripts.data_pipeline as dp

_OFFSET_S = 5 * 3600
_FMT = "%Y-%m-%dT%H:%M:%SZ"


@pytest.fixture
def fake_offset_zone(monkeypatch):
    real_strftime = time.strftime

    def _local(secs=None):
        return time.gmtime((time.time() if secs is None else secs) + _OFFSET_S)

    def _strftime(fmt, t=None):
        return real_strftime(fmt, _local() if t is None else t)

    monkeypatch.setattr(time, "localtime", _local)
    monkeypatch.setattr(time, "strftime", _strftime)


def _utc_error_s(stamp: str) -> float:
    parsed = datetime.strptime(stamp, _FMT).replace(tzinfo=timezone.utc)
    return abs((datetime.now(timezone.utc) - parsed).total_seconds())


def test_harness_makes_a_local_time_stamp_miss_utc(fake_offset_zone):
    assert _utc_error_s(time.strftime(_FMT)) > _OFFSET_S - 60


def test_ddragon_version_downloaded_at_is_utc(tmp_path, monkeypatch, fake_offset_zone):
    meta = tmp_path / "data" / "meta"
    meta.mkdir(parents=True)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "META", meta)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.1.1")
    monkeypatch.setattr(dp, "_fetch_json",
                        lambda url, timeout=15: {"type": "x", "data": {}})
    assert dp.cmd_ddragon(force=True) is True
    doc = json.loads((meta / "ddragon_version.json").read_bytes().decode("utf-8"))
    assert _utc_error_s(doc["downloaded_at"]) < 120, doc["downloaded_at"]


def test_rank_tiers_generated_at_is_utc(tmp_path, monkeypatch, fake_offset_zone):
    rt = tmp_path / "rank_tiers"
    rt.mkdir()
    seed = rt / "rank_tier_averages.seed.json"
    live = rt / "rank_tier_averages.json"
    seed.write_bytes(json.dumps({"schema": 1, "patch": "1.1.1",
                                 "generated_at": None, "tiers": {}}).encode("utf-8"))
    monkeypatch.setattr(dp, "RANK_TIERS_DIR", rt)
    monkeypatch.setattr(dp, "RANK_TIERS_SEED", seed)
    monkeypatch.setattr(dp, "RANK_TIERS_LIVE", live)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.1.1")
    assert dp.cmd_rank_tiers(force=True) is True
    doc = json.loads(live.read_bytes().decode("utf-8"))
    assert _utc_error_s(doc["generated_at"]) < 120, doc["generated_at"]
