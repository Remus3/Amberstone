"""RM-258 residual: the staleness report writers go through core.polled_json.

`write_report` and `reannotate_report` in tools/ds_wiki_staleness_check.py
hand-rolled a destination-derived `ability_staleness.tmp` plus a bare rename:
no fsync, no WinError 5 retry, and one scratch name shared by any two writers
(a manual --recent run and an `upstream_drift_check.py --staleness-recent`
run). The running RC app reads the same report
(core/daemon_slayer_client.py, the ABSENT / STALE / CURRENT badge index), so
a torn or failed swap is a reader-visible fault, not just litter.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (unchanged: `json.dumps(..., indent=1)` UTF-8, LF only)
and that no scratch file is left beside the report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
for _p in (str(_ROOT), str(_TOOLS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ds_wiki_staleness_check as M  # noqa: E402

_PATCH = "16.14.1"


def _report(champs: set[str], mode: str = "recent") -> dict:
    return {
        "_patch": _PATCH,
        "_mode": mode,
        "stale_champions": sorted(champs),
        "skipped_pages": [],
        "skipped_labels": [],
        "findings": [
            {"champion": c, "ability": "Q", "field": "base:Magic Damage"}
            for c in sorted(champs)
        ],
    }


@pytest.fixture
def write_spy(monkeypatch):
    """Record every core.polled_json.atomic_write_bytes call, then write."""
    import core.polled_json as pj

    calls = []
    real = pj.atomic_write_bytes

    def spy(path, data):
        calls.append(Path(path))
        real(path, data)

    monkeypatch.setattr(pj, "atomic_write_bytes", spy)
    return calls


@pytest.fixture
def patch_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    d = tmp_path / _PATCH
    d.mkdir(parents=True)
    return d


def _assert_only_the_report(patch_dir: Path, out: Path) -> bytes:
    assert sorted(p.name for p in patch_dir.iterdir()) == [M.REPORT_NAME]
    raw = out.read_bytes()
    assert b"\r" not in raw
    return raw


def test_full_write_report_routes_through_polled_json(write_spy, patch_dir):
    rep = _report({"Mel", "Maokai"}, mode="full")
    out = M.write_report(rep, _PATCH)

    assert write_spy == [out]
    raw = _assert_only_the_report(patch_dir, out)
    assert raw == json.dumps(rep, indent=1).encode("utf-8")


def test_partial_write_report_routes_through_polled_json(write_spy, patch_dir):
    M.write_report(_report({"Mel", "Maokai"}, mode="full"), _PATCH)
    out = M.write_report(_report({"Zyra"}), _PATCH, checked={"Zyra"})

    assert write_spy == [out, out]
    raw = _assert_only_the_report(patch_dir, out)
    got = json.loads(raw)
    assert got["stale_champions"] == ["Maokai", "Mel", "Zyra"]
    assert raw == json.dumps(got, indent=1).encode("utf-8")


def test_reannotate_report_routes_through_polled_json(
    write_spy, patch_dir, monkeypatch
):
    monkeypatch.setattr(M, "_override_lookup", lambda patch: None)
    out = patch_dir / M.REPORT_NAME
    rep = _report({"Mel"}, mode="full")
    out.write_bytes(json.dumps(rep, indent=1).encode("utf-8"))

    assert M.reannotate_report(_PATCH) == out
    assert write_spy == [out]
    raw = _assert_only_the_report(patch_dir, out)
    assert json.loads(raw)["stale_champions"] == ["Mel"]
    assert raw == json.dumps(json.loads(raw), indent=1).encode("utf-8")


def test_a_failed_swap_leaves_the_prior_report_and_no_scratch(
    patch_dir, monkeypatch
):
    """The old writer left `ability_staleness.tmp` behind when the rename
    failed; core.polled_json removes its scratch and re-raises."""
    import core.polled_json as pj

    out = M.write_report(_report({"Mel"}, mode="full"), _PATCH)
    before = out.read_bytes()

    def boom(src, dst):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(pj, "_replace_with_retry", boom)
    with pytest.raises(PermissionError):
        M.write_report(_report({"Zyra"}, mode="full"), _PATCH)

    assert _assert_only_the_report(patch_dir, out) == before
