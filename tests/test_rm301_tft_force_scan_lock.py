# arch: regression - RM-301 TFT force_scan RMW serialized against loop-thread writers | section=tft | frozen=no
"""RM-301 - `force_scan()` (hotkey thread) read-modify-wrote the live data
file with NO lock while the `_loop` thread's writers RMW the same file, so
the loser's fields were lost. Both sides now take `_DATA_FILE_LOCK`, held
only across file I/O, and force_scan waits a BOUNDED time then gives up.
"""

import json
import threading
import time

import tft.tft_live_analysis as tla


def _bare(path):
    obj = object.__new__(tla.TftLiveAnalysis)
    obj._data_file = path
    obj._force_flag = False
    obj._last_write = {}
    return obj


def _seed(path):
    path.write_text(json.dumps({
        "mode": "tft_live", "augment_select": True,
        "augment_choices": ["Old A", "Old B"], "aug_take": "Old A",
    }), encoding="utf-8")


def test_concurrent_writers_lose_no_field(tmp_path, monkeypatch):
    p = tmp_path / "tft_live_data.json"
    _seed(p)
    real_load = tla._load

    def slow_load(path):
        d = real_load(path)
        time.sleep(0.4)   # loop-thread RMW in flight
        return d

    monkeypatch.setattr(tla, "_load", slow_load)
    obj = _bare(p)
    t = threading.Thread(target=obj._publish_degraded,
                         args=({"hp": 50}, {"stage_round": "3-2"}))
    t.start()
    time.sleep(0.1)
    obj.force_scan()          # hotkey thread, mid-RMW of the loop writer
    t.join()
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["degraded"] is True                 # loop writer's field kept
    assert d["augment_choices"] == []            # force_scan's clear kept
    assert obj._force_flag is True


def test_force_scan_gives_up_bounded(tmp_path, monkeypatch):
    p = tmp_path / "tft_live_data.json"
    _seed(p)
    monkeypatch.setattr(tla, "FORCE_SCAN_LOCK_TIMEOUT_S", 0.1)
    obj = _bare(p)
    tla._DATA_FILE_LOCK.acquire()
    try:
        t0 = time.monotonic()
        obj.force_scan()
        assert time.monotonic() - t0 < 1.0
    finally:
        tla._DATA_FILE_LOCK.release()
    assert obj._force_flag is True               # scan still forced
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["augment_choices"] == ["Old A", "Old B"]   # pre-clear skipped
