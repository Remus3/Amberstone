"""CLI-level regression: a closed League client must not abort the archive pass.

The archiver runs on a 15-minute schedule, and the client is CLOSED for most of
that duty cycle. `--pull` is the ONLY step that needs the LCU; archiving,
highlight capture and stats extraction are pure file work.

Shipped defect (caught by the scheduled task reporting LastTaskResult=1): when
the lockfile was absent, main() printed an error and returned 1 BEFORE reaching
the archive/extract/highlights steps - so every run with the game closed did
nothing at all and reported failure. Same coupling shape as the supervisor A3
fix: one step's expected, benign failure taking unrelated work down with it.

A missing lockfile is a SKIP, not a failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import rofl_archiver  # noqa: E402


def _seed_replay(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(b"RIOT\x02\x00" + b"\x00" * 32)
    return p


def test_pull_with_no_client_still_archives_and_exits_zero(tmp_path, monkeypatch, capsys):
    """RED before the fix: returns 1 and copies nothing."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-5592802194.rofl")

    class _NoClient:
        def __init__(self, *a, **kw):
            raise OSError("lockfile absent")

    monkeypatch.setattr(rofl_archiver, "LcuReplayClient", _NoClient)

    # --no-api-pull: these two cases are about the LCU half of --pull. Without
    # it they would reach the live Riot API.
    rc = rofl_archiver.main([
        "--pull", "--no-api-pull", "--source", str(src), "--archive", str(arc),
    ])

    out = capsys.readouterr().out
    assert rc == 0, f"a closed client must not be a failure exit; got {rc}\n{out}"
    assert (arc / "NA1-5592802194.rofl").exists(), (
        "archive step was skipped because --pull could not reach the client"
    )


def test_pull_with_no_client_reports_the_skip(tmp_path, monkeypatch, capsys):
    """The skip must be visible - silently doing nothing is the defect this
    whole program exists to remove."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-1.rofl")

    class _NoClient:
        def __init__(self, *a, **kw):
            raise OSError("lockfile absent")

    monkeypatch.setattr(rofl_archiver, "LcuReplayClient", _NoClient)
    rofl_archiver.main(["--pull", "--no-api-pull",
                        "--source", str(src), "--archive", str(arc)])

    out = capsys.readouterr().out.lower()
    assert "skip" in out or "not running" in out, (
        "the pull skip was not reported to the caller"
    )


def test_archive_only_run_needs_no_client(tmp_path):
    """The common scheduled case: no --pull at all, client irrelevant."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-2.rofl")

    rc = rofl_archiver.main(["--source", str(src), "--archive", str(arc)])

    assert rc == 0
    assert (arc / "NA1-2.rofl").exists()


# ---------------------------------------------------------------------------
# sanctioned Match-V5 pull, wired under the same --pull the scheduled task uses
# ---------------------------------------------------------------------------

class _FakeApi:
    """Stand-in for core.riot_api. Resolves a PUUID per Riot ID, as the real
    flow must - a stored PUUID is scoped to whichever key resolved it."""

    def __init__(self, urls_by_puuid=None):
        self.urls_by_puuid = urls_by_puuid or {}
        self.resolved = []

    def get_account_by_riot_id(self, name, tag):
        self.resolved.append(f"{name}#{tag}")
        return {"puuid": f"PUUID_{tag}"}

    def get_replay_urls(self, puuid):
        return self.urls_by_puuid.get(puuid, [])


def _fake_body(url):
    return b"RIOT\x02\x00" + b"\x00" * 64


def test_pull_downloads_replays_from_the_api_for_both_accounts(
        tmp_path, monkeypatch, capsys):
    arc = tmp_path / "arc"
    api = _FakeApi({
        "PUUID_Trist": ["https://s3.example/NA1_11.rofl"],
        "PUUID_Vayne": ["https://s3.example/NA1_22.rofl"],
    })
    monkeypatch.setattr(rofl_archiver, "riot_api", api)
    monkeypatch.setattr(rofl_archiver.rofl_archive, "_http_get_bytes", _fake_body)

    class _NoClient:
        def __init__(self, *a, **kw):
            raise OSError("lockfile absent")

    monkeypatch.setattr(rofl_archiver, "LcuReplayClient", _NoClient)
    # The account list is per-install config, so pin a fixture pair rather than
    # asserting against whatever this machine happens to be configured for.
    monkeypatch.setattr(rofl_archiver.rofl_archive, "DEFAULT_ACCOUNTS",
                        [("SamplePlayer", "Trist"), ("SamplePlayer", "Vayne")])

    rc = rofl_archiver.main([
        "--pull", "--source", str(tmp_path / "none"), "--archive", str(arc),
    ])

    assert rc == 0
    assert api.resolved == ["SamplePlayer#Trist", "SamplePlayer#Vayne"]
    assert (arc / "NA1_11.rofl").exists()
    assert (arc / "NA1_22.rofl").exists()


def test_pull_records_an_observation_per_account_for_the_rotation_question(
        tmp_path, monkeypatch):
    arc = tmp_path / "arc"
    api = _FakeApi({"PUUID_Trist": ["https://s3.example/NA1_11.rofl"]})
    monkeypatch.setattr(rofl_archiver, "riot_api", api)
    monkeypatch.setattr(rofl_archiver.rofl_archive, "_http_get_bytes", _fake_body)
    monkeypatch.setattr(rofl_archiver.rofl_archive, "DEFAULT_ACCOUNTS",
                        [("SamplePlayer", "Trist"), ("SamplePlayer", "Vayne")])

    rofl_archiver.main([
        "--pull", "--no-lcu-pull", "--source", str(tmp_path / "none"),
        "--archive", str(arc),
    ])

    rows = rofl_archiver.rofl_archive.load_pull_observations(arc)
    accounts = {r["account"] for r in rows}
    assert accounts == {"SamplePlayer#Trist", "SamplePlayer#Vayne"}


def test_api_pull_with_an_unusable_key_is_a_skip_not_a_failure(
        tmp_path, monkeypatch, capsys):
    """No key / an unentitled key returns None from the wrapper. On a 15-minute
    schedule that must report a SKIP and still archive, exactly like a closed
    client does."""
    src = tmp_path / "Replays"
    arc = tmp_path / "arc"
    _seed_replay(src, "NA1-3.rofl")

    class _DeadApi:
        def get_account_by_riot_id(self, name, tag):
            return None

        def get_replay_urls(self, puuid):
            return None

    monkeypatch.setattr(rofl_archiver, "riot_api", _DeadApi())

    rc = rofl_archiver.main([
        "--pull", "--no-lcu-pull", "--source", str(src), "--archive", str(arc),
    ])

    out = capsys.readouterr().out.lower()
    assert rc == 0
    assert "skip" in out
    assert (arc / "NA1-3.rofl").exists()


def test_no_api_pull_opts_out_entirely(tmp_path, monkeypatch):
    arc = tmp_path / "arc"
    api = _FakeApi({"PUUID_Trist": ["https://s3.example/NA1_11.rofl"]})
    monkeypatch.setattr(rofl_archiver, "riot_api", api)

    rofl_archiver.main([
        "--pull", "--no-api-pull", "--no-lcu-pull",
        "--source", str(tmp_path / "none"), "--archive", str(arc),
    ])

    assert api.resolved == []
