"""The process-side S6 read-back: which Pillow the running vision process has mapped.

tests/test_gated_vision_pillow.py

`tools/gated_vision_pillow.py` reads the process side of the S6 read-back: which
Pillow the RUNNING :8889 vision process has mapped, and whether that Pillow was
installed before the process started. Every test here runs on tmp_path and fake
psutil objects; no test touches the live vision process or the live relay.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

from tools import gated_vision_pillow as gvp


def _site(tmp_path, *dists, mtime=1000.0):
    site = tmp_path / "site-packages"
    (site / "PIL").mkdir(parents=True)
    for name, version in dists:
        d = site / name
        d.mkdir()
        meta = d / "METADATA"
        meta.write_text(f"Metadata-Version: 2.4\nName: pillow\nVersion: {version}\n",
                        encoding="utf-8")
        os.utime(meta, (mtime, mtime))
    return site


def _conn(port, pid, status="LISTEN"):
    return SimpleNamespace(laddr=SimpleNamespace(port=port), pid=pid, status=status)


class _FakePsutil:
    def __init__(self, conns, maps, create_time=2000.0, raise_maps=None):
        self._conns = conns
        self._maps = maps
        self._create = create_time
        self._raise = raise_maps

    def net_connections(self, kind):
        assert kind == "tcp"
        return self._conns

    def Process(self, pid):  # noqa: N802 - mirrors psutil
        outer = self

        class _P:
            def exe(self):
                return "interp.exe"

            def create_time(self):
                return outer._create

            def memory_maps(self):
                if outer._raise:
                    raise outer._raise
                return [SimpleNamespace(path=p) for p in outer._maps]

        return _P()


def test_loaded_pil_dir_matches_only_the_imaging_extension(tmp_path):
    pyd = str(tmp_path / "site-packages" / "PIL" / "_imaging.cp314-win_amd64.pyd")
    other = str(tmp_path / "site-packages" / "PIL" / "_imagingft.cp314-win_amd64.pyd")
    assert gvp.loaded_pil_dir([other]) is None
    assert gvp.loaded_pil_dir(["x\\DLLs\\_ctypes.pyd", pyd]) == \
        (tmp_path / "site-packages" / "PIL")


def test_loaded_pil_dir_none_when_pillow_never_imported():
    assert gvp.loaded_pil_dir(["a\\DLLs\\select.pyd", "b\\python314.dll"]) is None


def test_dist_facts_reads_version_and_mtime(tmp_path):
    site = _site(tmp_path, ("pillow-13.0.0.dist-info", "13.0.0"), mtime=1234.0)
    facts = gvp.dist_facts(site)
    assert facts == [{"dist_info": "pillow-13.0.0.dist-info", "version": "13.0.0",
                      "installed_ts": 1234.0}]


def test_dist_facts_missing_dir_is_empty(tmp_path):
    assert gvp.dist_facts(tmp_path / "absent") == []


def test_s6_checks_pass_shape():
    report = {"pil_loaded": True, "create_time": 2000.0,
              "dists": [{"version": "13.0.0", "installed_ts": 1000.0}]}
    assert gvp.s6_checks(report) == {
        "pil_loaded_in_process": True, "single_pillow_dist": True,
        "version_is_13.0.0": True, "installed_before_process_start": True}


def test_s6_checks_flags_install_after_start_and_old_version():
    report = {"pil_loaded": True, "create_time": 1000.0,
              "dists": [{"version": "12.0.0", "installed_ts": 2000.0}]}
    checks = gvp.s6_checks(report)
    assert checks["version_is_13.0.0"] is False
    assert checks["installed_before_process_start"] is False


def test_s6_checks_two_dists_is_not_a_pass():
    report = {"pil_loaded": True, "create_time": 2000.0,
              "dists": [{"version": "12.0.0", "installed_ts": 1.0},
                        {"version": "13.0.0", "installed_ts": 1.0}]}
    checks = gvp.s6_checks(report)
    assert checks["single_pillow_dist"] is False
    assert checks["version_is_13.0.0"] is False
    assert checks["installed_before_process_start"] is None


def test_s6_checks_unknown_when_pillow_not_loaded():
    checks = gvp.s6_checks({"pil_loaded": False, "create_time": 1.0, "dists": []})
    assert checks["pil_loaded_in_process"] is False
    assert checks["single_pillow_dist"] is None
    assert checks["version_is_13.0.0"] is None


def test_find_listener_ignores_other_ports_and_states():
    conns = [_conn(8888, 1), _conn(8889, 2, "ESTABLISHED"), _conn(8889, 3)]
    assert gvp.find_listener(conns) == 3
    assert gvp.find_listener([_conn(8888, 1)]) is None


def test_read_process_full_path(tmp_path):
    site = _site(tmp_path, ("pillow-13.0.0.dist-info", "13.0.0"), mtime=1000.0)
    pyd = str(site / "PIL" / "_imaging.cp314-win_amd64.pyd")
    fake = _FakePsutil([_conn(8889, 42)], ["x\\select.pyd", pyd], create_time=2000.0)
    code, report = gvp.read_process(fake)
    assert code == 0
    assert report["pid"] == 42 and report["pil_loaded"] is True
    assert report["s6"]["version_is_13.0.0"] is True
    assert report["s6"]["installed_before_process_start"] is True


def test_read_process_no_listener_exit_1():
    code, report = gvp.read_process(_FakePsutil([], []))
    assert code == 1 and "nothing listens" in report["error"]


def test_read_process_access_denied_exit_2():
    fake = _FakePsutil([_conn(8889, 7)], [], raise_maps=PermissionError("denied"))
    code, report = gvp.read_process(fake)
    assert code == 2 and report["error"] == "process read: PermissionError"


def test_stats_counters_keeps_decode_counters_and_skips():
    body = {"uptime_s": 5, "stats": {
        "ocr": {"calls": 3, "errors": 0, "total_ms": 9},
        "vision": {"calls": 1, "errors": 1, "total_ms": 2, "tokens_est": 7},
        "lcu_upload": {"calls": 99, "errors": 0}},
        "capture_skip": {"not_foreground": 2, "blank": 0, "locked": 0,
                         "last_reason": "not_foreground", "last_ts": 1.0}}
    out = gvp.stats_counters(body)
    assert out["ocr"] == {"calls": 3, "errors": 0}
    assert out["vision"] == {"calls": 1, "errors": 1}
    assert "lcu_upload" not in out and "frame_upload" not in out
    assert out["capture_skip"]["last_reason"] == "not_foreground"
    assert out["uptime_s"] == 5


def test_stats_counters_keeps_obs_lane_failures():
    """RM-1054: the OBS decode / encode failure counters reach the readback."""
    body = {"stats": {}, "obs_lane": {"undecodable": 3, "error": 1,
                                      "last_reason": "undecodable",
                                      "last_ts": 2.0}}
    out = gvp.stats_counters(body)
    assert out["obs_lane"] == {"undecodable": 3, "error": 1,
                               "last_reason": "undecodable"}


def test_stats_counters_omits_obs_lane_from_an_older_server():
    out = gvp.stats_counters({"stats": {}})
    assert "obs_lane" not in out
    assert "gdi_lane" not in out


def test_stats_counters_keeps_obs_fetch_and_gdi_failures():
    """RM-1214: the OBS fetch reasons and the GDI self-grab counters reach
    the readback."""
    body = {"stats": {},
            "obs_lane": {"undecodable": 0, "error": 0, "ws_error": 4,
                         "auth": 1, "timeout": 2, "last_reason": "ws_error",
                         "last_ts": 3.0},
            "gdi_lane": {"unavailable": 0, "error": 5, "last_reason": "error",
                         "last_ts": 3.0}}
    out = gvp.stats_counters(body)
    assert out["obs_lane"] == {"undecodable": 0, "error": 0, "ws_error": 4,
                               "auth": 1, "timeout": 2,
                               "last_reason": "ws_error"}
    assert out["gdi_lane"] == {"unavailable": 0, "error": 5,
                               "last_reason": "error"}


def test_stats_counters_tolerates_junk():
    assert gvp.stats_counters(["not", "a", "dict"]) == {}
    assert gvp.stats_counters({"stats": "x"}) == {}


def test_two_listeners_is_no_single_listener():
    conns = [_conn(8889, 5), _conn(8889, 9), _conn(8889, 5)]
    assert gvp.find_listeners(conns) == [5, 9]
    assert gvp.find_listener(conns) is None
    code, report = gvp.read_process(_FakePsutil(conns, []))
    assert code == 2 and report["listener_pids"] == [5, 9]


def test_stats_tie_same_process_and_uptime():
    report = {"pid": 42, "create_time": 1000.0}
    tie = gvp.stats_tie(report, {"pid": 42, "create_time": 1000.0},
                        wall=1500.5, uptime_s=500)
    assert tie == {"same_process_after_get": True,
                   "uptime_matches_create_time": True}


def test_stats_tie_refuses_a_successor_on_the_port():
    report = {"pid": 42, "create_time": 1000.0}
    swapped = gvp.stats_tie(report, {"pid": 43, "create_time": 1490.0},
                            wall=1500.0, uptime_s=10)
    assert swapped["same_process_after_get"] is False
    assert swapped["uptime_matches_create_time"] is False


def test_stats_tie_pid_reuse_caught_by_create_time():
    report = {"pid": 42, "create_time": 1000.0}
    tie = gvp.stats_tie(report, {"pid": 42, "create_time": 1400.0},
                        wall=1500.0, uptime_s=500)
    assert tie["same_process_after_get"] is False


def test_stats_tie_unknown_uptime_and_missing_reread():
    report = {"pid": 42, "create_time": 1000.0}
    tie = gvp.stats_tie(report, {"error": "nothing listens on :8889"},
                        wall=1500.0, uptime_s=None)
    assert tie == {"same_process_after_get": False,
                   "uptime_matches_create_time": None}


def test_main_with_stats_rereads_the_listener(monkeypatch, capsys):
    calls = []

    def fake_read():
        calls.append(1)
        return 0, {"pid": 7, "create_time": 100.0, "pil_loaded": False,
                   "dists": [], "s6": {}}

    monkeypatch.setattr(gvp, "read_process", fake_read)
    monkeypatch.setattr(gvp, "_fetch_stats",
                        lambda: {"frame_upload": {"calls": 0, "errors": 0}})
    assert gvp.main(["--json"]) == 0
    out = capsys.readouterr().out
    assert len(calls) == 2
    assert '"same_process_after_get": true' in out
    assert '"uptime_matches_create_time": null' in out


def test_main_no_stats_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(gvp, "read_process",
                        lambda: (0, {"pid": 1, "pil_loaded": False, "dists": [],
                                     "s6": {}}))
    monkeypatch.setattr(gvp, "_fetch_stats",
                        lambda: (_ for _ in ()).throw(AssertionError("no GET")))
    assert gvp.main(["--json", "--no-stats"]) == 0
    assert '"pid": 1' in capsys.readouterr().out
