"""RM-481 residual (s144, RM-1701): the text-mode shadow-log appenders write LF.

The data/ shadow-log family has two spellings of the same append. The newer
writers (core/anvil_shadow.py, augment_shadow.py, champ_select_shadow.py,
hz_build_shadow.py, objective_playbook_shadow.py) open the file in BINARY
append mode and write LF rows. Ten older sites in nine modules used a text-mode
``open(..., "a", encoding="utf-8")`` with no ``newline=``: on Windows the text
layer turns every "\\n" into "\\r\\n", so ONE family of jsonl files carried CRLF
rows from some writers and LF rows from the others, and a byte-exact tool such
as tools/shadow_archive_split.py (which keeps each row's own end-of-line bytes
and hashes the file) saw both. Every text-mode append in the family now passes
``newline="\\n"``.

CI is Linux, where the text layer does not translate, so the behaviour
assertions would be vacuous without the harness below; positive controls prove
the harness turns a bare ``open`` and a bare ``Path.open`` append into CRLF
before a writer is trusted. The AST scan is the OS-independent half: it reads
every module in the family and fails on a text-mode append without ``newline=``.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests._crlf_text_layer import install_crlf_text_layer
from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

# The family: every core/*_shadow.py plus the two vision shadow lanes.
_EXTRA = ("core/vision_routing.py", "modes/shared_vision.py")

# Modules the s144 slice converted; the scan must keep reaching each of them so
# an empty walk cannot pass.
_CONVERTED = (
    "core/aram_coach_shadow.py",
    "core/arena_coach_shadow.py",
    "core/det_coach_shadow.py",
    "core/ds_coach_shadow.py",
    "core/hz_choice_shadow.py",
    "core/live_benchmark_band_shadow.py",
    "core/macro_response_shadow.py",
    "core/vision_routing.py",
    "modes/shared_vision.py",
)


def _family() -> list[str]:
    rels = [relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))]
    return sorted(r for r in rels
                  if (r.startswith("core/") and r.endswith("_shadow.py")
                      and "/" not in r[len("core/"):]) or r in _EXTRA)


def _append_offenders(src: str) -> list[int]:
    """Line numbers of text-mode append opens that pass no newline=."""
    out: list[int] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        is_open = (isinstance(f, ast.Name) and f.id == "open") or (
            isinstance(f, ast.Attribute) and f.attr == "open")
        if not is_open:
            continue
        # builtin open(path, mode) vs Path.open(mode): the mode is the first
        # string-constant positional argument that looks like a mode.
        mode = None
        for arg in node.args[:2]:
            if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                    and set(arg.value) <= set("rwxabt+")):
                mode = arg.value
                break
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if not isinstance(mode, str) or "a" not in mode or "b" in mode:
            continue
        if not any(kw.arg == "newline" for kw in node.keywords):
            out.append(node.lineno)
    return out


@pytest.mark.parametrize("snippet, expected", [
    ("with open(p, 'a', encoding='utf-8') as f:\n    f.write('x')\n", 1),
    ("with p.open('a', encoding='utf-8') as f:\n    f.write('x')\n", 1),
    ("with p.open('a', encoding='utf-8', newline='\\n') as f:\n    pass\n", 0),
    ("with p.open('ab') as f:\n    pass\n", 0),
    ("with p.open('a+b') as f:\n    pass\n", 0),
    ("with p.open('r', encoding='utf-8') as f:\n    pass\n", 0),
])
def test_detector_positive_and_negative_controls(snippet, expected):
    assert len(_append_offenders(snippet)) == expected


def test_the_scan_reaches_every_converted_module():
    fam = _family()
    assert fam, "empty walk"
    assert set(_CONVERTED) <= set(fam)
    # The binary-append precedents are in the family too (and stay clean).
    assert "core/anvil_shadow.py" in fam


def test_no_shadow_appender_writes_a_bare_text_mode_append():
    bad = {}
    for rel in _family():
        found = _append_offenders((REPO_ROOT / rel).read_bytes().decode("utf-8"))
        if found:
            bad[rel] = found
    assert bad == {}, (
        'text-mode append without newline="\\n" writes CRLF rows on Windows '
        f"beside the family's LF rows: {bad}")


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS (the shared
    harness reads a positional ``newline``, the shape ``Path.open`` uses)."""
    return install_crlf_text_layer(monkeypatch)


def test_positive_control_a_bare_text_append_produces_crlf(tmp_path,
                                                           crlf_text_layer):
    target = tmp_path / "control.jsonl"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness failed to force CRLF"


def test_positive_control_a_bare_path_open_append_produces_crlf(tmp_path,
                                                                crlf_text_layer):
    target = tmp_path / "control_path.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write("a\nb\n")
    assert crlf_text_layer.forced_for(target), "harness missed Path.open"
    assert target.read_bytes() == b"a\r\nb\r\n", "harness missed Path.open"


def test_ds_coach_shadow_appends_lf(tmp_path, crlf_text_layer):
    from core import ds_coach_shadow
    target = tmp_path / "ds_coach_hints_shadow.jsonl"
    for tag in ("one", "two"):
        rec = ds_coach_shadow.log_coach_hints(
            "SR", "Ahri", ["Zed", "Lux"], game_time_s=600.0,
            antitank_builder=lambda *a, _t=tag: {"t": _t},
            scaling_builder=lambda *a, _t=tag: {"t": _t},
            path=target, now_iso="2026-01-01T00:00:00+00:00")
        assert rec is not None
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert [json.loads(r)["antitank"]["t"]
            for r in raw.decode("utf-8").split("\n") if r] == ["one", "two"]


def test_macro_response_shadow_appends_lf(tmp_path, crlf_text_layer):
    from core import macro_response_shadow
    target = tmp_path / "macro_response_shadow.jsonl"
    for gt in (610.0, 700.0):
        rec = macro_response_shadow.log_macro_response(
            "SR", "Ahri", macro={"tag": f"t{gt}", "line": "x"},
            native_objective="synthetic", lead_state="even", phase="mid",
            game_time_s=gt, path=target, now_iso="2026-01-01T00:00:00+00:00")
        assert rec is not None
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2


def test_an_lf_row_then_a_new_append_keeps_the_file_pure_lf(tmp_path,
                                                            crlf_text_layer):
    """A file already holding an LF row (a binary-append sibling, or a
    byte-exact archive split) stays pure LF after a text-mode writer appends."""
    from core import ds_coach_shadow
    target = tmp_path / "ds_coach_hints_shadow.jsonl"
    target.write_bytes(b'{"kept": true}\n')
    ds_coach_shadow.log_coach_hints(
        "SR", "Ahri", ["Zed"], game_time_s=1.0,
        antitank_builder=lambda *a: {}, scaling_builder=lambda *a: {},
        path=target, now_iso="2026-01-01T00:00:00+00:00")
    raw = Path(target).read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
