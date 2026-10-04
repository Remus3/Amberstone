"""RM-448 / RM-481: the Daemon Slayer regenerators must not write text-mode CRLF.

On Windows a text-mode write with no ``newline=`` translates every ``\\n`` to
``\\r\\n``. RM-441 fixed the non-DS writers; this guard covers the DS
generators, extractors and report tools: every text-mode write call in the
scoped files must pin ``newline=`` (``"\\n"`` or ``""``), or write bytes.

Scope (the RM-448 writer list, re-derived): ``tools/ds_*.py``,
``tools/daemon_slayer_*.py``, ``tools/ds_cross_eval/*.py`` and
``scripts/build_spell_cast_rates.py``. One-shot historical hotfix scripts
outside these globs are deliberately excluded - they will not re-run.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_GLOBS = ("tools/ds_*.py", "tools/daemon_slayer_*.py", "tools/ds_cross_eval/*.py",
          "scripts/build_spell_cast_rates.py",
          # RC-side writers of DS tables under data/daemon_slayer/ (found by the
          # RM-513 Arena regen, which left CRLF on disk):
          "core/build_order_precompute.py", "core/build_order_variants.py",
          "core/laning_scenario_precompute.py")


def _scoped_files() -> list[Path]:
    out: list[Path] = []
    for g in _GLOBS:
        out.extend(sorted(ROOT.glob(g)))
    return out


def _mode_of(call: ast.Call, positional_index: int) -> str | None:
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    if len(call.args) > positional_index and isinstance(call.args[positional_index], ast.Constant):
        return str(call.args[positional_index].value)
    return None


def text_mode_writes_without_newline(source: str) -> list[int]:
    """Line numbers of text-mode write calls that do not pin ``newline=``."""
    bad: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        has_newline = any(kw.arg == "newline" for kw in node.keywords)
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "write_text":
            if not has_newline:
                bad.append(node.lineno)
            continue
        mode = None
        if isinstance(f, ast.Name) and f.id == "open":
            mode = _mode_of(node, 1)
        elif isinstance(f, ast.Attribute) and f.attr in ("open", "fdopen"):
            # os.fdopen(fd, mode) / io.open(path, mode) / Path.open(mode)
            is_module_call = isinstance(f.value, ast.Name) and f.value.id in ("os", "io")
            mode = _mode_of(node, 1 if is_module_call else 0)
        if mode and any(ch in mode for ch in "wax") and "b" not in mode and not has_newline:
            bad.append(node.lineno)
    return bad


def test_scope_is_not_empty():
    files = _scoped_files()
    assert len(files) >= 20, files
    assert (ROOT / "tools" / "ds_cc_conditional_to_json.py") in files


def test_detector_positive_control():
    src = (
        "from pathlib import Path\n"
        "import os\n"
        "Path('a').write_text('x', encoding='utf-8')\n"
        "open('b', 'w', encoding='utf-8')\n"
        "os.fdopen(3, 'w')\n"
        "Path('c').open('w')\n"
        "Path('ok').write_text('x', encoding='utf-8', newline='\\n')\n"
        "open('ok2', 'wb')\n"
        "open('ok3', 'w', newline='')\n"
        "open('read')\n"
    )
    assert text_mode_writes_without_newline(src) == [3, 4, 5, 6]


@pytest.mark.skipif(os.linesep != "\r\n", reason="CRLF translation only happens on Windows")
def test_forced_crlf_positive_control(tmp_path):
    """Proves the defect is real on this host and that newline='\\n' cures it."""
    bad = tmp_path / "bad.json"
    good = tmp_path / "good.json"
    bad.write_text("{\n}\n", encoding="utf-8")
    good.write_text("{\n}\n", encoding="utf-8", newline="\n")
    assert b"\r\n" in bad.read_bytes()
    assert b"\r" not in good.read_bytes()


@pytest.mark.parametrize("path", _scoped_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_ds_writer_pins_newline(path: Path):
    bad = text_mode_writes_without_newline(path.read_bytes().decode("utf-8"))
    assert not bad, f"{path.relative_to(ROOT).as_posix()} text-mode writes without newline= at lines {bad}"
