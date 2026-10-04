"""P1-3 (RC part): spec / patch watch over the game-data version feed and data index.

Hermetic: every fetch goes through the offline replay client
(lib/game_data/replay.py) over the bodies recorded for P1-4
(tests/fixtures/game_data_replay). A "new patch" is planted by editing a
private copy of those bodies.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lib.game_data.replay import ReplayClient
from tools import spec_watch as sw

FIX = Path(__file__).resolve().parent / "fixtures" / "game_data_replay"
VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"


@pytest.fixture()
def env(tmp_path):
    rep = tmp_path / "replay"
    shutil.copytree(FIX, rep)
    return {
        "replay": rep,
        "state": tmp_path / "runtime" / "spec_watch_state.json",
        "events": tmp_path / "runtime" / "spec_watch_events.jsonl",
    }


def _run(env, apply=True, deliver=None):
    return sw.run(
        apply=apply,
        client=ReplayClient(env["replay"]),
        state_path=env["state"],
        events_path=env["events"],
        deliver=deliver,
    )


def _events(env):
    if not env["events"].is_file():
        return []
    return [json.loads(line) for line in env["events"].read_text(encoding="ascii").splitlines() if line.strip()]


def _plant_new_patch(env, *, new_field=False, new_item=False):
    """Make the replayed feed announce 16.20.1 whose tables differ from 16.19.1."""
    rep = env["replay"]
    idx_p = rep / "_index.json"
    idx = json.loads(idx_p.read_text(encoding="ascii"))
    champ = json.loads((rep / "ddragon_champion.json").read_text(encoding="ascii"))
    item = json.loads((rep / "ddragon_item.json").read_text(encoding="ascii"))
    champ["version"] = item["version"] = "16.20.1"
    if new_field:
        champ["data"]["Ahri"]["stats"]["tenacity"] = 0
    if new_item:
        item["data"]["773161"] = dict(item["data"]["1055"], name="planted")
    (rep / "c20.json").write_text(json.dumps(champ), encoding="ascii")
    (rep / "i20.json").write_text(json.dumps(item), encoding="ascii")
    idx["responses"]["https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/champion.json"] = "c20.json"
    idx["responses"]["https://ddragon.leagueoflegends.com/cdn/16.20.1/data/en_US/item.json"] = "i20.json"
    (rep / "v20.json").write_text(json.dumps(["16.20.1", "16.19.1", "16.18.1"]), encoding="ascii")
    idx["responses"][VERSIONS] = "v20.json"
    idx_p.write_text(json.dumps(idx), encoding="ascii")


def test_first_run_is_a_baseline_and_posts_nothing(env):
    code, summary = _run(env)
    assert code == 0 and summary["outcome"] == "baseline"
    assert _events(env) == []
    snap = json.loads(env["state"].read_text(encoding="ascii"))["snapshot"]
    assert snap["version"] == "16.19.1" and "Ahri" in snap["champions"] and "stats.hp" in snap["fields"]["champion"]


def test_planted_change_posts_exactly_once_across_three_runs(env):
    _run(env)  # baseline on 16.19.1
    _plant_new_patch(env, new_field=True, new_item=True)
    outcomes = [_run(env)[1]["outcome"] for _ in range(3)]
    assert outcomes == ["posted", "nothing-new", "nothing-new"]
    ev = _events(env)
    assert len(ev) == 1
    ch = ev[0]["change"]
    assert ch["from_version"] == "16.19.1" and ch["to_version"] == "16.20.1"
    assert ch["items"]["added"] == ["773161"]
    assert ch["fields"]["champion"]["added"] == ["stats.tenacity"]
    assert ev[0]["status"] == "open" and len(ev[0]["marker"]) == 16


def test_marker_prevents_a_second_post_even_if_the_snapshot_did_not_advance(env):
    _run(env)
    _plant_new_patch(env, new_item=True)
    before = env["state"].read_bytes()
    assert _run(env)[1]["outcome"] == "posted"
    env["state"].write_bytes(before)  # e.g. a crash lost the snapshot advance
    assert _run(env)[1]["outcome"] == "already-said"
    assert len(_events(env)) == 1


def test_closed_tracker_counts_as_said(env):
    _run(env)
    _plant_new_patch(env, new_item=True)
    _code, dry = _run(env, apply=False)
    marker = dry["marker"]
    env["events"].parent.mkdir(parents=True, exist_ok=True)
    env["events"].write_text(json.dumps({"marker": marker, "status": "closed"}) + "\n", encoding="ascii")
    code, summary = _run(env)
    assert code == 0 and summary["outcome"] == "already-said"
    assert len(_events(env)) == 1  # only the operator's closed record


@pytest.mark.parametrize("body", [b"<html>down</html>", b"[]", b"{\"v\": 1}", b"[1, 2]"])
def test_unparseable_version_feed_exits_2_and_changes_nothing(env, body):
    _run(env)
    before = env["state"].read_bytes()
    (env["replay"] / "ddragon_versions.json").write_bytes(body)
    code, summary = _run(env)
    assert code == 2 and summary["outcome"] == "fetch-failed"
    assert env["state"].read_bytes() == before and _events(env) == []


def test_unparseable_data_index_exits_2(env):
    _run(env)
    before = env["state"].read_bytes()
    (env["replay"] / "ddragon_item.json").write_text("{\"type\": \"item\"}", encoding="ascii")
    code, _summary = _run(env)
    assert code == 2 and env["state"].read_bytes() == before


def test_unavailable_spec_exits_2_and_changes_nothing(env):
    _run(env)
    before = env["state"].read_bytes()
    idx_p = env["replay"] / "_index.json"
    idx = json.loads(idx_p.read_text(encoding="ascii"))
    del idx["responses"][VERSIONS]
    idx_p.write_text(json.dumps(idx), encoding="ascii")
    code, _summary = _run(env)
    assert code == 2 and env["state"].read_bytes() == before


def test_baseline_fetch_failure_also_exits_2_and_writes_nothing(env):
    (env["replay"] / "ddragon_versions.json").write_bytes(b"not json")
    code, _summary = _run(env)
    assert code == 2 and not env["state"].exists()


def test_dry_run_is_the_default_and_writes_nothing(env):
    code, summary = sw.run(
        client=ReplayClient(env["replay"]), state_path=env["state"], events_path=env["events"]
    )
    assert code == 0 and summary["outcome"] == "baseline" and summary["dry_run"] is True
    assert not env["state"].exists()
    _run(env)
    _plant_new_patch(env, new_item=True)
    before = env["state"].read_bytes()
    code, summary = _run(env, apply=False)
    assert summary["outcome"] == "would-post"
    assert env["state"].read_bytes() == before and _events(env) == []


def test_cli_defaults_to_dry_run(monkeypatch):
    ns = sw._parse_args([])
    assert ns.apply is False
    assert sw._parse_args(["--apply"]).apply is True


def test_delivery_failure_keeps_the_change_on_offer(env):
    _run(env)
    _plant_new_patch(env, new_item=True)
    code, summary = _run(env, deliver=lambda rec: {"ok": False, "detail": "sink down"})
    assert code == 1 and summary["outcome"] == "deliver-failed"
    assert _run(env)[1]["outcome"] == "posted"
    assert len(_events(env)) == 1


def test_deliver_raising_counts_as_failed_delivery(env):
    _run(env)
    _plant_new_patch(env, new_item=True)

    def boom(_rec):
        raise OSError("disk full")

    code, summary = _run(env, deliver=boom)
    assert code == 1 and summary["outcome"] == "deliver-failed"


def test_same_version_with_no_key_change_posts_nothing(env):
    _run(env)
    assert _run(env)[1]["outcome"] == "nothing-new"
    assert _events(env) == []


def test_upstream_drift_check_runs_the_watch_only_when_asked(monkeypatch):
    from tools import upstream_drift_check as udc

    calls = []
    monkeypatch.setattr(udc, "_run_spec_watch", lambda: calls.append(1) or 0)
    for name in ("probe_ddragon_version", "probe_meraki_content_patch", "probe_cdragon_content_version",
                 "probe_qq_synergy_shape", "probe_cdragon_queue_catalog"):
        monkeypatch.setattr(udc, name, lambda: "x")
    monkeypatch.setattr(udc, "load_sentinel", lambda: {})
    monkeypatch.setattr(udc, "advance_sentinel", lambda *a, **k: None)
    assert udc.main([]) == 0 and calls == []
    assert udc.main(["--spec-watch"]) == 0 and calls == [1]
    monkeypatch.setattr(udc, "_run_spec_watch", lambda: 2)
    # A spec that cannot be fetched or parsed fails the daily run, never quietly.
    assert udc.main(["--spec-watch"]) == 2
    assert udc.main(["--check-only", "--spec-watch"]) == 0  # check-only fires no side effects


def test_scheduled_task_installer_passes_spec_watch():
    root = Path(__file__).resolve().parent.parent
    text = (root / "ops" / "install_RC_UpstreamDriftCheck.ps1").read_text(encoding="ascii")
    assert "--spec-watch" in text
