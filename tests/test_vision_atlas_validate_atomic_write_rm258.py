"""RM-258 residual: the vision_atlas_validate report goes through core.polled_json.

`main()` in tools/vision_atlas_validate.py (the `--out` markdown report,
default data/vision_atlas_accuracy.md, TRACKED) hand-rolled a
destination-derived `<out>.tmp`, wrote it with Path.write_bytes and swapped it
in with a bare Path.replace: no fsync, no WinError 5 retry, a scratch name
shared by every concurrent run, and a failed rename left the scratch file
beside the report.

Each test calls `_write_report()` on a small synthetic markdown body in
tmp_path, spies on `core.polled_json.atomic_write_bytes`, then checks the exact
on-disk bytes (UTF-8, LF only) and that no scratch file is left beside the
report. Every path lives under tmp_path; no atlas icon is matched. cv2 is
required only because the tool imports core.vision_template_match.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("cv2")

from core import polled_json  # noqa: E402 - after the cv2 skip gate
import tools.vision_atlas_validate as vav  # noqa: E402

_MD = "# CV atlas accuracy\n\n| a | b |\n|---|---|\n| caf" + chr(0xE9) + " | 1 |\n"


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


def test_write_report_routes_through_polled_json(tmp_path, spy):
    out = tmp_path / "sub" / "vision_atlas_accuracy.md"

    vav._write_report(_MD, out)

    expected = _MD.encode("utf-8")
    assert [p for p, _ in spy] == [out]
    on_disk = out.read_bytes()
    assert on_disk == spy[0][1] == expected
    assert b"\r" not in on_disk
    assert _scratch(out.parent) == []


def test_write_report_replaces_a_prior_report(tmp_path, spy):
    out = tmp_path / "vision_atlas_accuracy.md"
    out.write_bytes(b"# prior\n")

    vav._write_report(_MD, out)

    assert out.read_bytes() == _MD.encode("utf-8")
    assert _scratch(tmp_path) == []


def test_failed_swap_keeps_the_prior_report_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    out = tmp_path / "vision_atlas_accuracy.md"
    before = b"# prior\n"
    out.write_bytes(before)

    def _deny(src, dst):
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(polled_json, "_replace_with_retry", _deny)
    monkeypatch.setattr(os, "replace", _deny)
    monkeypatch.setattr(Path, "replace", lambda self, dst: _deny(self, dst))

    with pytest.raises(PermissionError):
        vav._write_report(_MD, out)

    assert out.read_bytes() == before
    assert _scratch(tmp_path) == []


def test_main_writes_the_report_through_the_helper(tmp_path, monkeypatch,
                                                   capsys):
    out = tmp_path / "report.md"
    seen = []
    monkeypatch.setattr(vav, "render_report", lambda results: _MD)
    monkeypatch.setattr(
        vav, "_write_report", lambda md, path: seen.append((md, path)),
        raising=False)

    rc = vav.main(["--categories", "", "--out", str(out)])

    assert rc == 0
    assert seen == [(_MD, out)]
    assert not out.exists()
    assert "wrote " + str(out) in capsys.readouterr().out
