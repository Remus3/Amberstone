"""RM-481 residual (s144, RM-1710): the last three script log handlers write LF.

tools/liveclient_relay.py, tools/phase_watcher.py and tools/screen_agent.py
built a stdlib ``logging.FileHandler``, whose ``_open`` passes no ``newline=``,
so every record is CRLF on Windows. Unlike the RM-1707/197 sites they cannot
import ``core.log_rotation``: each is served to a standalone the RC-Agent folder
copy with no repo above it (the files say so in their own prose). Each
therefore carries an inline ``_LFFileHandler`` subclass, and this test pins the
three copies identical so they cannot drift.

CI is Linux, where the text layer does not translate, so the behaviour test
runs the real class source under a harness that forces CRLF on any text-mode
open that passes no ``newline=``; the stdlib-handler positive control proves
the harness bites.
"""
from __future__ import annotations

import ast
import logging

import pytest

from tests._crlf_text_layer import install_crlf_text_layer
from tests._repo_walk import REPO_ROOT
from tests.test_log_handlers_lf_s144p196 import _stdlib_handler_calls

_FILES = (
    "tools/liveclient_relay.py",
    "tools/phase_watcher.py",
    "tools/screen_agent.py",
)


def _class_node(rel: str) -> ast.ClassDef:
    src = (REPO_ROOT / rel).read_bytes().decode("utf-8")
    nodes = [n for n in ast.parse(src).body
             if isinstance(n, ast.ClassDef) and n.name == "_LFFileHandler"]
    assert len(nodes) == 1, f"{rel}: expected one module-level _LFFileHandler"
    return nodes[0]


@pytest.mark.parametrize("rel", _FILES)
def test_no_stdlib_file_handler_is_built_and_the_lf_one_is(rel):
    src = (REPO_ROOT / rel).read_bytes().decode("utf-8")
    assert _stdlib_handler_calls(src) == [], (
        f"{rel}: stdlib file handler writes CRLF records on Windows "
        f"(lines {_stdlib_handler_calls(src)})")
    assert "_LFFileHandler(str(_LOG_FILE)" in src, (
        f"{rel} builds no LF handler - the scan above would pass with no file log")


@pytest.mark.parametrize("rel", _FILES)
def test_no_core_import_for_the_standalone_copy(rel):
    # The deployed copy has no core/ above it: a core import would crash it.
    tree = ast.parse((REPO_ROOT / rel).read_bytes().decode("utf-8"))
    mods = [n.module for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module]
    assert not [m for m in mods if m.split(".")[0] == "core"], rel


def test_three_copies_are_identical():
    dumps = {rel: ast.dump(_class_node(rel)) for rel in _FILES}
    assert len(set(dumps.values())) == 1, "the inline _LFFileHandler copies drifted"


@pytest.fixture
def crlf_text_layer(monkeypatch):
    """Reproduce the Windows LF -> CRLF text translation on every OS (the shared
    harness, tests/_crlf_text_layer.py; a handler built under it binds it)."""
    return install_crlf_text_layer(monkeypatch)


def _emit_two(handler: logging.Handler) -> None:
    # A bare Logger is not registered with the manager: no NOW-7 logger leak.
    lg = logging.Logger("s144p199.probe", logging.INFO)
    lg.addHandler(handler)
    try:
        lg.info("first")
        lg.info("second")
    finally:
        lg.removeHandler(handler)
        handler.close()


def test_positive_control_stdlib_handler_writes_crlf(tmp_path, crlf_text_layer):
    target = tmp_path / "stdlib.log"
    _emit_two(logging.FileHandler(str(target), encoding="utf-8"))
    assert crlf_text_layer.forced_for(target), "harness missed the FileHandler open"
    assert target.read_bytes().count(b"\r\n") == 2, "harness failed to force CRLF"


@pytest.mark.parametrize("rel", _FILES)
def test_inline_handler_writes_lf(rel, tmp_path, crlf_text_layer):
    module = ast.Module(body=[_class_node(rel)], type_ignores=[])
    ns = {"logging": logging}
    exec(compile(ast.fix_missing_locations(module), rel, "exec"), ns)  # noqa: S102
    target = tmp_path / "lf.log"
    _emit_two(ns["_LFFileHandler"](str(target), encoding="utf-8"))
    raw = target.read_bytes()
    assert b"\r" not in raw
    assert raw.count(b"\n") == 2
