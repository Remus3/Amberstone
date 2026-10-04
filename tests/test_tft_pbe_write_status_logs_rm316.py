"""RM-316: `_write_status` - the one path that tells the user "coaching
paused" - swallowed its own failure with a bare `pass`. It now logs at
WARNING and stays fail-soft (it runs inside `_run_safe`'s handler, so a raise
would turn a silent degradation into a dead worker). Write mechanics are
fenced by RM-286 and are not changed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

from tft.tft_pbe_engine import TftPbeCoachEngine


def _engine(tmp: Path) -> TftPbeCoachEngine:
    with patch.object(TftPbeCoachEngine, "_read_key_file", return_value=""), \
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}, clear=False):
        return TftPbeCoachEngine(tmp / "tft_pbe_coaching_data.json")


def test_failed_status_write_is_logged_and_not_raised(tmp_path, caplog):
    eng = _engine(tmp_path)
    # RM-258 moved the write onto core.polled_json (os.replace + retry), so a
    # Path.replace patch no longer reaches it; fail the writer seam instead.
    with patch("tft.tft_pbe_engine.atomic_write_text",
               side_effect=PermissionError("held open")), \
            caplog.at_level(logging.WARNING, logger="rc.tft.pbe"):
        eng._write_status("Coaching paused - retrying")
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("held open" in m and "status" in m for m in msgs), msgs


def test_successful_status_write_lands(tmp_path):
    eng = _engine(tmp_path)
    eng._write_status("Coaching paused - retrying")
    data = json.loads((tmp_path / "tft_pbe_coaching_data.json").read_text())
    assert data["risk"] == "Coaching paused - retrying"
