"""s144 true-audit of vision_server/_frame.py (RM-1046; closes the _frame.py
half of RM-1045).

Findings pinned here, one test class each:

1. get_latest_frame aged the cached frame with a bare ``time.time() - ts``.
   After a backward wall-clock step that age is negative, the self-grab never
   fires, and the coaches are served an arbitrarily old frame as current
   (RM-269 class). It now routes through core.relay_age.is_stale.
2. The self-grab throttle compared wall-clock stamps, so a backward step of
   an hour stopped every self-grab for an hour (the vision feed went dark).
   It now runs on the monotonic clock.
3. The Y-03 foreground grace window compared wall-clock stamps, so a backward
   step held the grace window open and the GDI grab kept shipping DESKTOP
   frames while the operator was alt-tabbed out (the gate failed OPEN). It
   now runs on the monotonic clock, and "never seen" is a sentinel, not 0.0.
4. /upload-frame took a non-str ``image_b64``: an int raised TypeError (an
   HTTP 500), a list or a non-ASCII string slipped past the fail-open magic
   check and was CACHED as the frame every coach decodes.
5. A non-str ``source`` raised TypeError on the slot dict (unhashable) or was
   cached under a key no ``?source=`` query can name; an empty or oversized
   one was accepted. Distinct source names were also unbounded: each holds a
   full frame (up to ~7 MB) for the process lifetime.
6. ``primary`` went through ``bool()``, so the string "false" was TRUE and a
   secondary stream clobbered the League frame the coaches read.
7. The cached width / height / format were the uploader's CLAIM, not the
   payload: a 1x1 JPEG claiming 1920 wide and "png" was cached as such.
8. Upload latency was measured on the wall clock, so a backward step recorded
   a negative duration into the stats totals.
"""
from __future__ import annotations

import base64
import io
import json
import time
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from core.relay_age import FUTURE_TOLERANCE_S  # noqa: E402
from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402


def _jpeg_b64(w=1, h=1) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _png_b64(w=2, h=3) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


_JPEG = _jpeg_b64()


def _upload(**fields) -> dict:
    return _frame.handle_upload_frame(json.dumps(fields).encode())


def _grab_payload() -> dict:
    return {"b64": _JPEG, "size": len(_JPEG), "width": 1, "height": 1,
            "format": "jpeg", "source": "self_grab"}


class _Clock:
    """Stand-in for the ``time`` module inside _frame: a wall clock and a
    monotonic clock that the test steps independently."""

    def __init__(self):
        self.wall = time.time()
        self.mono = time.monotonic()

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    monkeypatch.setattr(_frame, "GAME_HOST", "127.0.0.1")
    monkeypatch.setattr(_frame, "_input_desktop_locked", lambda: False)
    yield
    _frame._reset_self_read_state()


@pytest.fixture
def grabs(monkeypatch):
    calls = []

    def _fetch():
        calls.append(1)
        return _grab_payload()
    monkeypatch.setattr(_frame, "_fetch_frame_direct", _fetch)
    return calls


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(_frame, "time",
                        types.SimpleNamespace(time=c.time,
                                              monotonic=c.monotonic))
    return c


# -- 1. future frame ts is stale ----------------------------------------------

class TestFutureFrameTsSelfGrabs:
    def _seed(self, ts):
        with _frame._frame_lock:
            _frame._latest_frame.update({"b64": _JPEG, "ts": ts,
                                         "source": "league"})

    def test_future_ts_beyond_tolerance_self_grabs(self, grabs):
        self._seed(time.time() + 3600.0)
        out = _frame.get_latest_frame()
        assert grabs == [1]
        assert out["source"] == "self_grab"

    def test_fresh_ts_is_served_without_a_grab(self, grabs):
        self._seed(time.time())
        out = _frame.get_latest_frame()
        assert grabs == []
        assert out["source"] == "league"

    def test_jitter_inside_tolerance_is_still_fresh(self, grabs):
        self._seed(time.time() + FUTURE_TOLERANCE_S / 4)
        assert _frame.get_latest_frame()["source"] == "league"
        assert grabs == []

    @pytest.mark.parametrize("ts", ["junk", None, float("nan"), 10 ** 400],
                             ids=["text", "none", "nan", "bigint"])
    def test_junk_ts_is_stale_not_a_crash(self, grabs, ts):
        with _frame._frame_lock:
            _frame._latest_frame.update({"b64": _JPEG, "ts": ts})
        out = _frame.get_latest_frame()
        assert grabs == [1]
        assert out["source"] == "self_grab"

    def test_backward_clock_step_after_a_grab_regrabs(self, grabs, clock):
        _frame.get_latest_frame()
        assert grabs == [1]
        clock.wall -= 3600.0   # NTP steps the wall clock back an hour
        clock.mono += 1.0      # real time keeps moving
        out = _frame.get_latest_frame()
        assert grabs == [1, 1]
        assert out["source"] == "self_grab"


# -- 2. throttle on the monotonic clock ---------------------------------------

class TestThrottleIsMonotonic:
    def test_backward_wall_step_does_not_freeze_self_grab(self, grabs, clock):
        assert _frame._maybe_self_grab() is not None
        clock.wall -= 3600.0
        clock.mono += _frame._SELF_GRAB_MIN_INTERVAL_S + 0.1
        assert _frame._maybe_self_grab() is not None
        assert grabs == [1, 1]

    def test_throttle_still_holds_inside_the_interval(self, grabs, clock):
        assert _frame._maybe_self_grab() is not None
        clock.wall += 3600.0   # a FORWARD wall step must not bypass it either
        clock.mono += _frame._SELF_GRAB_MIN_INTERVAL_S / 4
        assert _frame._maybe_self_grab() is None
        assert grabs == [1]

    def test_frame_ts_stays_wall_clock(self, grabs, clock):
        out = _frame._maybe_self_grab()
        assert out["ts"] == clock.wall


# -- 3. Y-03 grace window on the monotonic clock ------------------------------

class TestForegroundGraceIsMonotonic:
    def test_backward_wall_step_does_not_hold_grace_open(self, monkeypatch,
                                                        clock):
        monkeypatch.setattr(_frame, "_league_foreground", lambda: True)
        assert _frame._gdi_gate() is None
        monkeypatch.setattr(_frame, "_league_foreground", lambda: False)
        clock.wall -= 3600.0
        clock.mono += _frame._FOREGROUND_GRACE_S + 1.0
        assert _frame._gdi_gate() == "not_foreground"

    def test_grace_inside_window_still_allows(self, monkeypatch, clock):
        monkeypatch.setattr(_frame, "_league_foreground", lambda: True)
        assert _frame._gdi_gate() is None
        monkeypatch.setattr(_frame, "_league_foreground", lambda: False)
        clock.wall += 3600.0
        clock.mono += _frame._FOREGROUND_GRACE_S / 2
        assert _frame._gdi_gate() is None

    def test_never_seen_is_refused_even_just_after_boot(self, monkeypatch,
                                                         clock):
        monkeypatch.setattr(_frame, "_league_foreground", lambda: False)
        clock.mono = 1.0   # monotonic origin is unspecified; may be tiny
        assert _frame._gdi_gate() == "not_foreground"


# -- 4. image_b64 shape -------------------------------------------------------

class TestImageB64Shape:
    @pytest.mark.parametrize("img", [5, 5.5, True, ["A" * 200], {"a": 1},
                                     chr(0xE9) * 200, _JPEG[:40] + chr(0xE9)],
                             ids=["int", "float", "bool", "list", "dict",
                                  "non_ascii", "non_ascii_tail"])
    def test_non_str_or_non_ascii_is_refused_and_not_cached(self, img):
        out = _upload(image_b64=img, source="league")
        assert out == {"error": "bad_image_b64"}
        assert _frame._frames_by_source == {}
        assert _frame._latest_frame["b64"] is None

    def test_missing_still_reports_no_image(self):
        assert _upload(source="league") == {"error": "no image_b64"}

    def test_valid_jpeg_still_cached(self):
        out = _upload(image_b64=_JPEG, source="league")
        assert out["ok"] is True
        assert _frame._latest_frame["b64"] == _JPEG


# -- 5. source shape and slot cap ---------------------------------------------

class TestSourceShape:
    @pytest.mark.parametrize("src", [["a"], {"a": 1}, 5, True, "",
                                     "x" * (_frame._MAX_SOURCE_LEN + 1)],
                             ids=["list", "dict", "int", "bool", "empty",
                                  "too_long"])
    def test_bad_source_is_refused_and_not_cached(self, src):
        out = _upload(image_b64=_JPEG, source=src)
        assert out == {"error": "bad_source"}
        assert _frame._frames_by_source == {}
        assert _frame._latest_frame["b64"] is None

    def test_missing_source_is_unknown(self):
        out = _upload(image_b64=_JPEG)
        assert out["source"] == "unknown"
        assert "unknown" in _frame._frames_by_source

    def test_max_length_source_is_accepted(self):
        src = "s" * _frame._MAX_SOURCE_LEN
        assert _upload(image_b64=_JPEG, source=src)["ok"] is True

    def test_distinct_sources_are_capped_oldest_evicted(self):
        cap = _frame._MAX_SOURCE_SLOTS
        for i in range(cap + 5):
            assert _upload(image_b64=_JPEG, source=f"ch{i}",
                           primary=False)["ok"] is True
        slots = _frame._frames_by_source
        assert len(slots) == cap
        assert f"ch{cap + 4}" in slots          # newest kept
        assert "ch0" not in slots               # oldest evicted

    def test_rewriting_a_known_source_evicts_nothing(self):
        cap = _frame._MAX_SOURCE_SLOTS
        for i in range(cap):
            _upload(image_b64=_JPEG, source=f"ch{i}", primary=False)
        _upload(image_b64=_JPEG, source="ch0", primary=False)
        assert len(_frame._frames_by_source) == cap
        assert "ch1" in _frame._frames_by_source
        # The rewrite made ch0 the most recent, so the next new source
        # evicts ch1, the least recently written.
        _upload(image_b64=_JPEG, source="new", primary=False)
        slots = _frame._frames_by_source
        assert len(slots) == cap
        assert "ch0" in slots and "new" in slots and "ch1" not in slots


# -- 6. primary must be a bool ------------------------------------------------

class TestPrimaryShape:
    @pytest.mark.parametrize("val", ["false", "0", 0, 1, None, [], {}],
                             ids=["text_false", "text_0", "int_0", "int_1",
                                  "null", "list", "dict"])
    def test_non_bool_primary_is_refused(self, val):
        _upload(image_b64=_JPEG, source="league")
        before = dict(_frame._latest_frame)
        out = _upload(image_b64=_png_b64(), source="ui", primary=val)
        assert out == {"error": "bad_primary"}
        assert _frame._latest_frame == before
        assert "ui" not in _frame._frames_by_source

    def test_false_keeps_the_league_frame(self):
        _upload(image_b64=_JPEG, source="league")
        out = _upload(image_b64=_png_b64(), source="ui", primary=False)
        assert out["primary"] is False
        assert _frame._latest_frame["source"] == "league"
        assert "ui" in _frame._frames_by_source

    def test_missing_primary_defaults_true(self):
        assert _upload(image_b64=_JPEG, source="league")["primary"] is True
        assert _frame._latest_frame["source"] == "league"


# -- 7. cached metadata comes from the payload --------------------------------

class TestMetadataFromPayload:
    def test_jpeg_claiming_png_1920_is_cached_as_measured(self):
        _upload(image_b64=_JPEG, source="league", width=1920, height=1080,
                format="png")
        f = _frame._latest_frame
        assert (f["width"], f["height"], f["format"]) == (1, 1, "jpeg")

    def test_png_dims_and_format_measured(self):
        _upload(image_b64=_png_b64(2, 3), source="league", format="jpeg")
        f = _frame._latest_frame
        assert (f["width"], f["height"], f["format"]) == (2, 3, "png")

    def test_unreadable_header_keeps_only_sane_claims(self, monkeypatch):
        monkeypatch.setattr(_frame, "_frame_dims", lambda _img: None)
        _upload(image_b64=_JPEG, source="a", width="1920", height=-5,
                format="gif")
        f = _frame._frames_by_source["a"]
        assert (f["width"], f["height"], f["format"]) == (None, None, "jpeg")
        _upload(image_b64=_JPEG, source="b", width=1920, height=1080)
        f = _frame._frames_by_source["b"]
        assert (f["width"], f["height"]) == (1920, 1080)


# -- 8. upload latency on the monotonic clock ---------------------------------

class TestUploadLatencyMonotonic:
    def test_backward_wall_step_records_no_negative_ms(self, monkeypatch):
        state = {"wall": time.time(), "mono": time.monotonic()}

        def _wall():
            state["wall"] -= 3600.0   # every read is an hour earlier
            return state["wall"]

        def _mono():
            state["mono"] += 0.001
            return state["mono"]
        monkeypatch.setattr(_frame, "time",
                            types.SimpleNamespace(time=_wall, monotonic=_mono))
        before = stats_mod._stats.get("frame_upload", {}).get("total_ms", 0)
        assert _upload(image_b64=_JPEG, source="league")["ok"] is True
        after = stats_mod._stats["frame_upload"]["total_ms"]
        assert after - before >= 0
