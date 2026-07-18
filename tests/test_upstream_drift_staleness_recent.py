"""RM-81 daily watchdog folded into the existing RC-UpstreamDriftCheck run.

Two properties matter and both are easy to get wrong:

1. It must NOT be drift-gated. A champion's live values can change with no
   ddragon/meraki/cdragon version moving, and when a version DOES move a full
   re-extract runs anyway - so gating on drift fires it exactly when it is
   least useful.
2. It must never flip the detector's exit code. The daily task's contract is
   "0 = no drift"; an unreachable wiki is not drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import upstream_drift_check as M  # noqa: E402


def _stub_probes(monkeypatch, version="16.14.1"):
    monkeypatch.setattr(M, "probe_ddragon_version", lambda: version)
    monkeypatch.setattr(M, "probe_meraki_content_patch", lambda: "25.15")
    monkeypatch.setattr(M, "probe_cdragon_content_version", lambda: version)
    monkeypatch.setattr(M, "load_sentinel", lambda: {
        "ddragon_version": version,
        "meraki_content_patch": "25.15",
        "cdragon_content_version": version,
    })
    monkeypatch.setattr(M, "advance_sentinel", lambda *a, **k: None)


def test_runs_even_when_there_is_no_drift(monkeypatch):
    _stub_probes(monkeypatch)
    calls = []
    monkeypatch.setattr(M, "run_staleness_recent",
                        lambda days=7: calls.append(days) or (True, "ok"))
    assert M.main(["--staleness-recent"]) == 0
    assert calls == [7], "must not be gated on any_drift"


def test_not_run_when_flag_absent(monkeypatch):
    _stub_probes(monkeypatch)
    calls = []
    monkeypatch.setattr(M, "run_staleness_recent",
                        lambda days=7: calls.append(days) or (True, "ok"))
    assert M.main([]) == 0
    assert calls == []


def test_honours_custom_lookback_window(monkeypatch):
    _stub_probes(monkeypatch)
    calls = []
    monkeypatch.setattr(M, "run_staleness_recent",
                        lambda days=7: calls.append(days) or (True, "ok"))
    M.main(["--staleness-recent", "--staleness-days", "30"])
    assert calls == [30]


def test_wiki_failure_never_changes_exit_code(monkeypatch):
    _stub_probes(monkeypatch)

    def _boom(days=7):
        raise RuntimeError("wiki unreachable")

    monkeypatch.setattr(M, "run_staleness_recent", _boom)
    # The helper is fail-soft in its own right, but the CALL SITE must be too:
    # without its own guard the raise lands in main()'s outer handler and the
    # daily task exits 2 ("hard error") on a mere wiki outage.
    assert M.main(["--staleness-recent"]) == 0


def test_run_staleness_recent_is_fail_soft_on_network_error(monkeypatch):
    import ds_wiki_staleness_check as sc

    def _boom(days=7, limit=500):
        raise OSError("edge blocked")

    monkeypatch.setattr(sc, "fetch_recent_titles", _boom)
    ok, detail = M.run_staleness_recent(days=1)
    assert ok is False
    assert "OSError" in detail


def test_run_staleness_recent_short_circuits_on_empty_window(monkeypatch):
    import ds_wiki_staleness_check as sc

    monkeypatch.setattr(sc, "fetch_recent_titles", lambda days=7, limit=500: [])
    called = []
    monkeypatch.setattr(sc, "run", lambda *a, **k: called.append(1) or {})
    ok, detail = M.run_staleness_recent(days=1)
    assert ok is True
    assert called == [], "no edits means no page fetches"
    assert "no Data-template edits" in detail
