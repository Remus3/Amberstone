"""Item 8 Phase 2: the `rank_tiers` subcommand of scripts/data_pipeline.py.

The rank-tier stats panel (overlay item 8) benchmarks the operator against a
selected rank-tier average. Phase 1 shipped the read side (core.rank_tier_bench
over a committed estimate seed). Phase 2 is the ingest/refresh side: a
`rank_tiers` pipeline subcommand that stamps the CURRENT live patch onto the
gitignored live artifact data/rank_tiers/rank_tier_averages.json (seeded from
the committed estimate seed today; where a live aggregate payload would land
once a source is configured). It rides the weekly/patch RC-PatchRefresh via the
`all` path, and mid-week patch drift via upstream_drift_check.trigger_refresh().

These tests touch NO network and NO real repo data dir: the seed + live paths
are monkeypatched into tmp_path, and _get_live_version is stubbed.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import scripts.data_pipeline as dp


_SEED = {
    "schema": 1,
    "patch": "16.13.1",
    "generated_at": None,
    "source": "estimate-not-measured (test seed)",
    "tiers": {
        "gold": {
            "SR": {"all": {"early": {"cs": {"avg": 205}}, "mid": {"cs": {"avg": 205}}}},
        },
    },
}


@pytest.fixture
def _paths(tmp_path, monkeypatch):
    """Redirect the rank-tier seed + live paths into tmp_path."""
    rt = tmp_path / "rank_tiers"
    rt.mkdir(parents=True, exist_ok=True)
    seed = rt / "rank_tier_averages.seed.json"
    live = rt / "rank_tier_averages.json"
    seed.write_text(json.dumps(_SEED), encoding="utf-8")
    monkeypatch.setattr(dp, "RANK_TIERS_DIR", rt, raising=False)
    monkeypatch.setattr(dp, "RANK_TIERS_SEED", seed, raising=False)
    monkeypatch.setattr(dp, "RANK_TIERS_LIVE", live, raising=False)
    return seed, live


def test_rank_tiers_registered_in_commands():
    assert "rank_tiers" in dp.COMMANDS
    assert dp.COMMANDS["rank_tiers"] is dp.cmd_rank_tiers


def test_rank_tiers_in_cmd_all():
    # cmd_all must invoke cmd_rank_tiers so the weekly/patch RC-PatchRefresh
    # covers the rank-tier artifact.
    src = inspect.getsource(dp.cmd_all)
    assert "cmd_rank_tiers" in src


def test_stamps_live_patch_and_generated_at(_paths, monkeypatch):
    seed, live = _paths
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    assert dp.cmd_rank_tiers(force=True) is True
    assert live.exists()
    out = json.loads(live.read_text(encoding="utf-8"))
    assert out["patch"] == "99.99.9"
    assert out["generated_at"]  # non-null ISO stamp
    # tier payload carried through verbatim from the seed
    assert out["tiers"]["gold"]["SR"]["all"]["early"]["cs"]["avg"] == 205


def test_source_provenance_preserved(_paths, monkeypatch):
    # The estimate-not-measured provenance must survive so the UI badges it.
    _seed, live = _paths
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    dp.cmd_rank_tiers(force=True)
    out = json.loads(live.read_text(encoding="utf-8"))
    assert "estimate-not-measured" in out["source"]


def test_skips_when_already_current(_paths, monkeypatch):
    seed, live = _paths
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    assert dp.cmd_rank_tiers(force=True) is True
    first = json.loads(live.read_text(encoding="utf-8"))["generated_at"]
    # A second non-forced run at the same live patch must NOT rewrite the file.
    assert dp.cmd_rank_tiers(force=False) is True
    second = json.loads(live.read_text(encoding="utf-8"))["generated_at"]
    assert first == second


def test_atomic_no_tmp_left(_paths, monkeypatch):
    seed, live = _paths
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    dp.cmd_rank_tiers(force=True)
    leftovers = list(live.parent.glob("*.tmp"))
    assert leftovers == []


def test_fail_soft_when_seed_missing(tmp_path, monkeypatch):
    # A missing seed is non-fatal (returns True) so cmd_all never aborts the
    # whole pipeline over the rank-tier artifact; no live file is produced.
    rt = tmp_path / "rank_tiers"
    rt.mkdir()
    seed = rt / "rank_tier_averages.seed.json"      # not created
    live = rt / "rank_tier_averages.json"
    monkeypatch.setattr(dp, "RANK_TIERS_DIR", rt, raising=False)
    monkeypatch.setattr(dp, "RANK_TIERS_SEED", seed, raising=False)
    monkeypatch.setattr(dp, "RANK_TIERS_LIVE", live, raising=False)
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    assert dp.cmd_rank_tiers(force=True) is True
    assert not live.exists()


def test_falls_back_to_seed_patch_when_version_unavailable(_paths, monkeypatch):
    # When the live version fetch fails, the seed's own patch stamp is used
    # rather than crashing (fail-soft).
    seed, live = _paths

    def _boom():
        raise OSError("no network")

    monkeypatch.setattr(dp, "_get_live_version", _boom)
    assert dp.cmd_rank_tiers(force=True) is True
    out = json.loads(live.read_text(encoding="utf-8"))
    assert out["patch"] == "16.13.1"  # seed patch preserved


def test_file_is_ascii(_paths, monkeypatch):
    seed, live = _paths
    monkeypatch.setattr(dp, "_get_live_version", lambda: "99.99.9")
    dp.cmd_rank_tiers(force=True)
    data = Path(live).read_bytes()
    assert all(b <= 0x7F for b in data), "rank-tier live artifact must be ASCII"
