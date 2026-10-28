"""RM-258 residual: the DS calibration report write goes through core.polled_json.

`write_atomic` in tools/ds_calibration_report.py hand-rolled a
destination-derived `<file>.json.tmp` plus a bare `Path.replace`: no fsync, no
WinError 5 retry, a scratch name shared by every concurrent run, and a failed
rename left the scratch file beside the report.

Each test spies on `core.polled_json.atomic_write_bytes`, then checks the
exact on-disk bytes (`json.dumps(payload, indent=2, sort_keys=True,
ensure_ascii=True)` UTF-8, LF only, unchanged from the old writer) and that no
scratch file is left beside the report.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from tools import ds_calibration_report as dcr  # noqa: E402


def _payload() -> dict:
    return dcr.build_payload({
        "ok": True, "min_n": 20, "observations": 3, "followed": 1,
        "cells": [{"mode": "SR", "scorer": "dps", "n": 3}],
        "games": {"joined": 3}, "coverage": {"records": 3},
        "elapsed_ms": 12.5,
    })


def _expected_bytes(payload: dict) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True,
                      ensure_ascii=True).encode("utf-8")


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_report_write_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "ds_calibration_agreement.json"
    payload = _payload()

    dcr.write_atomic(payload, out)

    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == _expected_bytes(payload)
    assert b"\r" not in on_disk
    assert "elapsed_ms" not in json.loads(on_disk)
    assert _scratch(out.parent) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "ds_calibration_agreement.json"
    before = b'{"schema": "prior"}'
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        dcr.write_atomic(_payload(), out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []
