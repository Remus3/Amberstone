"""RM-481: the DS build-table and pickban generators write LF bytes.

``tools/ds_wiki_staleness_check.py`` was fixed to LF (``newline="\\n"``), but
the two precomputed-table generators still wrote through
``os.fdopen(fd, "w", encoding="utf-8")`` with no ``newline=``, which emits
CRLF on Windows. Their outputs (``data/daemon_slayer/<patch>/build_orders_*``
and ``pickban_targets.json``) are TRACKED; ``.gitattributes`` renormalises
them in the index, so the damage was a dirty working tree on every regen, not
a corrupt blob - but the writer was still wrong.

CI is Linux, where text mode does not translate, so a plain LF assertion
would be vacuous there. ``force_crlf_fdopen`` reproduces the Windows
translation on any OS by injecting ``newline="\\r\\n"`` into every text-mode
``os.fdopen`` write that does not pin its own ``newline=``; the positive
control proves the harness bites.
"""
from __future__ import annotations

import os
import pathlib
import tempfile

import pytest

from tests.test_tracked_writer_lf_sweep import _violations
from tools import daemon_slayer_build_orders_generate as build_gen
from tools import daemon_slayer_pickban_targets_generate as pickban_gen

_ROOT = pathlib.Path(__file__).resolve().parent.parent

LF_WRITERS = (
    "tools/daemon_slayer_build_orders_generate.py",
    "tools/daemon_slayer_pickban_targets_generate.py",
)

_PAYLOAD = {"b": [1, 2], "a": {"c": None, "d": "x"}}


@pytest.fixture
def force_crlf_fdopen(monkeypatch):
    """Make text-mode ``os.fdopen`` writes translate LF -> CRLF on any OS."""
    orig = os.fdopen

    def _fdopen(fd, mode="r", *args, **kwargs):
        if "b" not in mode and any(c in mode for c in "wax+"):
            if len(args) < 3 and kwargs.get("newline") is None:
                kwargs["newline"] = "\r\n"
        return orig(fd, mode, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", _fdopen)


def _crlf_count(path: pathlib.Path) -> int:
    raw = path.read_bytes()
    assert raw.count(b"\n") > 1, f"{path.name} has no line structure to check"
    return raw.count(b"\r\n")


def test_positive_control_text_mode_fdopen_produces_crlf(tmp_path, force_crlf_fdopen):
    fd, name = tempfile.mkstemp(dir=str(tmp_path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("a\nb\nc\n")
    assert _crlf_count(pathlib.Path(name)) == 3


@pytest.mark.parametrize("mod", [build_gen, pickban_gen], ids=["build_orders", "pickban"])
def test_generator_atomic_write_emits_lf_bytes(tmp_path, force_crlf_fdopen, mod):
    out = tmp_path / "sub" / "table.json"
    mod.atomic_write(_PAYLOAD, out)
    assert _crlf_count(out) == 0
    # Atomic tmp + replace: no stray temp file left beside the output.
    assert sorted(p.name for p in out.parent.iterdir()) == ["table.json"]


def test_pickban_write_matches_check_serialization(tmp_path, force_crlf_fdopen):
    out = tmp_path / "pickban_targets.json"
    pickban_gen.atomic_write(_PAYLOAD, out)
    assert out.read_bytes() == pickban_gen._serialize(_PAYLOAD).encode("utf-8")


@pytest.mark.parametrize("rel", LF_WRITERS)
def test_generator_has_no_text_mode_write(rel):
    path = _ROOT / rel
    assert path.is_file(), f"{rel} missing - update LF_WRITERS"
    assert _violations(path.read_text(encoding="utf-8")) == []
