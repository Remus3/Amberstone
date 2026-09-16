"""RM-441 sibling sweep: regenerators of TRACKED files write LF bytes.

tests/test_tracked_writer_lf_bytes.py drives the originally filed writers end
to end. This module covers the wider sweep without a test per tool:

1. A parametrized positive control proving the ``force_crlf`` harness turns
   both text-mode write shapes (``Path.write_text`` and ``open(..., "w")``)
   into CRLF on ANY OS. CI is Linux, where neither translates natively, so
   without the harness an LF assertion there is vacuous.
2. The LF helpers the sweep routes through - ``core.polled_json
   .atomic_write_text`` and ``scripts.data_pipeline._atomic_write_text`` -
   stay LF under that harness (they write bytes).
3. A static AST guard over the swept regenerators: no ``.write_text(`` call,
   and no text-mode ``open`` / ``os.fdopen`` in write mode without an explicit
   ``newline=``. Append-mode log sinks are out of scope (never tracked).
"""
from __future__ import annotations

import ast
import builtins
import json
import pathlib

import pytest

import scripts.data_pipeline as dp
from core import polled_json

_ROOT = pathlib.Path(__file__).resolve().parent.parent

SWEPT_WRITERS = (
    "tools/aram_item_interaction_precompute.py",
    "tools/build_cohort_baseline.py",
    "tools/build_rank_baselines.py",
    "tools/champion_loadout_autogen.py",
    "tools/hz_mismatch_diagnose.py",
    "tools/mine_event_patterns.py",
    "tools/unresolved_token_scan.py",
    "tools/upstream_drift_check.py",
    "tools/vision_atlas_validate.py",
)

_PAYLOAD = json.dumps({"a": 1, "b": [1, 2], "c": {"d": None}}, indent=2) + "\n"


@pytest.fixture
def force_crlf(monkeypatch):
    """Reproduce the Windows LF -> CRLF text-mode translation on every OS."""
    orig_write_text = pathlib.Path.write_text
    orig_open = builtins.open

    def _write_text(self, data, encoding=None, errors=None, newline=None):
        return orig_write_text(self, data, encoding=encoding, errors=errors,
                               newline="\r\n" if newline is None else newline)

    def _open(file, mode="r", *args, **kwargs):
        if "b" not in mode and any(c in mode for c in "wax+"):
            if len(args) < 3 and kwargs.get("newline") is None:
                kwargs["newline"] = "\r\n"
        return orig_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", _write_text)
    monkeypatch.setattr(builtins, "open", _open)


def _crlf_count(path: pathlib.Path) -> int:
    raw = path.read_bytes()
    assert raw.count(b"\n") > 1, f"{path.name} has no line structure to check"
    return raw.count(b"\r\n")


def _via_write_text(p: pathlib.Path) -> None:
    p.write_text(_PAYLOAD, encoding="utf-8")


def _via_open_w(p: pathlib.Path) -> None:
    with open(p, "w", encoding="utf-8") as f:
        f.write(_PAYLOAD)


@pytest.mark.parametrize("writer", [_via_write_text, _via_open_w],
                         ids=["path_write_text", "open_w"])
def test_positive_control_text_mode_writes_produce_crlf(tmp_path, force_crlf, writer):
    target = tmp_path / "control.json"
    writer(target)
    assert _crlf_count(target) > 0, "harness failed to force CRLF - LF checks would be vacuous"


@pytest.mark.parametrize("helper", [polled_json.atomic_write_text, dp._atomic_write_text],
                         ids=["polled_json.atomic_write_text", "data_pipeline._atomic_write_text"])
def test_lf_helpers_write_lf_bytes_under_forced_crlf(tmp_path, force_crlf, helper):
    target = tmp_path / "out.json"
    helper(target, _PAYLOAD)
    assert _crlf_count(target) == 0
    assert target.read_bytes() == _PAYLOAD.encode("utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json"]


def _write_mode(call: ast.Call, mode_index: int) -> str | None:
    mode = None
    if len(call.args) > mode_index and isinstance(call.args[mode_index], ast.Constant):
        mode = call.args[mode_index].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return mode if isinstance(mode, str) else None


def _violations(source: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name == "write_text":
            out.append(f"line {node.lineno}: write_text")
            continue
        if name not in ("open", "fdopen"):
            continue
        # Path.open(mode) carries mode at 0; builtins/os.fdopen at 1.
        idx = 0 if (name == "open" and isinstance(fn, ast.Attribute)
                    and getattr(fn.value, "id", None) != "io") else 1
        mode = _write_mode(node, idx)
        if not mode or "b" in mode or "w" not in mode:
            continue
        if not any(kw.arg == "newline" for kw in node.keywords):
            out.append(f"line {node.lineno}: {name}({mode!r}) without newline=")
    return out


def test_guard_detects_both_shapes():
    bad = (
        "from pathlib import Path\nimport os\n"
        "Path('x').write_text('a')\n"
        "open('x', 'w', encoding='utf-8')\n"
        "os.fdopen(3, 'w', encoding='utf-8')\n"
        "Path('x').open('w')\n"
    )
    assert len(_violations(bad)) == 4
    good = (
        "import os\nfrom pathlib import Path\n"
        "Path('x').write_bytes(b'a')\n"
        "open('x', 'w', encoding='utf-8', newline='\\n')\n"
        "open('x', 'a', encoding='utf-8')\n"
        "open('x', 'rb')\n"
    )
    assert _violations(good) == []


@pytest.mark.parametrize("rel", SWEPT_WRITERS)
def test_swept_regenerator_has_no_text_mode_write(rel):
    path = _ROOT / rel
    assert path.is_file(), f"{rel} missing - update SWEPT_WRITERS"
    assert _violations(path.read_text(encoding="utf-8")) == []
