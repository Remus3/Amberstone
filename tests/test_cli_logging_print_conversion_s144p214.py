"""RM-1722 - the precompute CLIs speak: no logger call takes a print keyword, and a CLI run shows its progress.

Commit c08d2e433 (2026-06-17) turned the progress / refusal ``print`` calls of the three DS precompute CLIs
(``core/build_order_precompute.py``, ``core/build_order_variants.py``, ``core/laning_scenario_precompute.py``)
into ``logger.info`` calls and kept them as logger on purpose. Two defects survived it, both measured
2026-11-06 at HEAD:

1. Four of the converted calls kept their old ``file=sys.stderr`` keyword. ``Logger.info`` forwards unknown
   keywords to ``Logger._log``, so the moment INFO is enabled they raise
   ``TypeError: Logger._log() got an unexpected keyword argument 'file'``. With INFO off (the default) they
   print nothing, so the refusal ("DS engine ... is not responding", "unknown band", "DataSnapshot.load()
   failed") exited 2 with no message at all.
2. None of the three modules configures logging, so ``python -m core.<module> --dry-run`` printed nothing
   (the root logger sits at WARNING): the operator never saw "gen patch=...", the per-mode counts or
   "done in ...".

The refusals are now ``logger.error`` calls (a WARNING-or-higher record reaches stderr through the logging
last-resort handler even unconfigured), and each module's ``__main__`` block configures a bare-message INFO
handler so a CLI run prints its progress. The aftergame_summary CLI logged its success line at ERROR; that
is INFO now, with the same ``__main__`` handler.
"""
from __future__ import annotations

import ast
import logging
import subprocess
import sys

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_LEVELS = {"debug", "info", "warning", "warn", "error", "critical", "exception", "log"}
_PRINT_ONLY_KEYWORDS = {"file", "end", "flush", "sep"}


def _run_module(module: str, *args: str) -> subprocess.CompletedProcess:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120, **kwargs,
    )


def test_no_logging_call_takes_a_print_keyword():
    """``logger.info(..., file=sys.stderr)`` is a print() call that survived a print -> logger conversion."""
    assert len(repo_files(REPO_ROOT, ("*.py",))) > 100, "the tracked-file walk returned almost nothing"
    bad: list[str] = []
    for path in repo_files(REPO_ROOT, ("*.py",)):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _LEVELS):
                hit = {k.arg for k in node.keywords if k.arg} & _PRINT_ONLY_KEYWORDS
                if hit:
                    bad.append(f"{relative_posix(path)}:{node.lineno} {sorted(hit)}")
    assert not bad, f"logging calls that pass a print() keyword: {bad}"


def test_probe_is_live():
    """The scan reports a minimal offender, so an empty tree result is a real scan."""
    tree = ast.parse("import logging\nlogging.getLogger('x').info('m', file=None)\n")
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in _LEVELS and {k.arg for k in n.keywords} & _PRINT_ONLY_KEYWORDS]
    assert len(calls) == 1


_DRY_RUN_CLIS = [
    ("core.build_order_precompute", "build-order precompute gen patch="),
    ("core.build_order_variants", "build-order VARIANTS gen patch="),
]


@pytest.mark.parametrize(("module", "banner"), _DRY_RUN_CLIS)
def test_a_build_order_cli_dry_run_prints_its_progress(module, banner, tmp_path):
    proc = _run_module(module, "--dry-run", "--static", "--champions", "Ahri", "--mode", "sr",
                       "--out", str(tmp_path))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-600:]
    assert banner in out, out[-600:]
    assert "done in " in out, out[-600:]
    assert not list(tmp_path.iterdir()), "a dry run must write nothing"


def test_laning_cli_dry_run_prints_its_progress(tmp_path):
    from core.laning_scenario_precompute import GEN_BANDS

    proc = _run_module("core.laning_scenario_precompute", "--dry-run", "--champions", "Ahri",
                       "--enemies", "Ahri", "--bands", GEN_BANDS[0], "--mode", "sr",
                       "--out", str(tmp_path))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-600:]
    assert "laning-scenarios gen patch=" in out, out[-600:]
    assert "done in " in out, out[-600:]
    assert not list(tmp_path.iterdir()), "a dry run must write nothing"


def test_laning_cli_names_an_unknown_band_and_exits_2():
    proc = _run_module("core.laning_scenario_precompute", "--bands", "no_such_band")
    assert proc.returncode == 2
    assert "unknown band" in proc.stdout + proc.stderr
    assert "TypeError" not in proc.stderr


@pytest.mark.parametrize("module", ["core.build_order_precompute", "core.build_order_variants"])
def test_a_dead_engine_is_refused_with_a_message_not_a_typeerror(module, monkeypatch, caplog, tmp_path):
    import importlib

    mod = importlib.import_module(module)
    monkeypatch.setattr(mod, "_engine_up", lambda: False)
    # INFO enabled: the old file= keyword raised TypeError here.
    with caplog.at_level(logging.INFO):
        rc = mod.main(["--champions", "Ahri", "--mode", "sr", "--out", str(tmp_path)])
    assert rc == 2
    assert any("is not responding" in r.getMessage() for r in caplog.records)
    assert not list(tmp_path.iterdir())


def test_laning_refusals_are_logged_not_print_keyworded(monkeypatch, caplog):
    from core import laning_scenario_precompute as mod

    class _Boom:
        @staticmethod
        def load():
            raise RuntimeError("no data set")

    monkeypatch.setattr(mod, "DataSnapshot", _Boom)
    with caplog.at_level(logging.INFO):
        assert mod.main(["--bands", mod.GEN_BANDS[0]]) == 2
        assert mod.main(["--bands", "no_such_band"]) == 2
    messages = [r.getMessage() for r in caplog.records]
    assert any("DataSnapshot.load() failed" in m for m in messages)
    assert any("unknown band" in m for m in messages)


def test_aftergame_success_line_is_not_logged_at_error():
    source = (REPO_ROOT / "core" / "aftergame_summary.py").read_text(encoding="utf-8")
    assert 'logger.error(f"wrote data/coaching_data.json' not in source
    assert "wrote data/coaching_data.json" in source
