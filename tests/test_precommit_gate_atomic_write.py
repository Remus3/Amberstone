"""Advisory non-atomic-write check on NET-NEW staged lines (precommit_gate).

CLAUDE.md hard rule: "Atomic writes only: tmp.write_text(...); tmp.replace(target).
Overlays poll mid-write." The canonical writer is core/polled_json.atomic_write_json
(tmp via _scratch_path, publish via _replace_with_retry). Nothing at commit time
enforced that rule - a net-new `Path(...).write_text(...)` straight onto a polled
file passed the gate unremarked.

This pins `_atomic_write_hits(added_lines, path)` plus its wiring into main():

  * production dirs only (app/ core/ coaches/ dashboard/ game_reader/ agents/
    modes/ lcu/ vision_server/ web_dashboard.py); tests/ tools/ scripts/ docs/
    and ops/loop/ (byte-pinned sibling files) are exempt;
  * a line is a hit when it calls .write_text( / .write_bytes( / open(x, "w..")
    / json.dump( AND the same line carries no scratch marker (tmp / scratch /
    .part) AND the file's added-line set carries no publish step (.replace( /
    os.replace( / atomic_write* / _atomic_write / _write_then_replace);
  * RC_ATOMIC_WRITE_GATE: unset or "warn" reports to stderr and exits 0;
    "block" exits 2 like a glyph hit; "off" checks nothing.

Default is WARN. This is a first-cycle MEASUREMENT of the false-positive rate,
not enforcement - the whole-tree count decides whether block mode is viable.

Harness follows tests/test_precommit_gate.py: import the module, monkeypatch
_git with a synthetic `diff --cached` so no real repo is touched. Source stays
7-bit ASCII.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import precommit_gate as G  # noqa: E402

# The exact positive control named in the slice brief.
_POSITIVE = 'Path("data/x.json").write_text(s)'


def _hits(lines: list[str], path: str) -> list[str]:
    return G._atomic_write_hits(list(enumerate(lines, start=1)), path)


class TestScannerPositiveControl:
    def test_write_text_in_app_is_reported(self):
        out = _hits([_POSITIVE], "app/foo.py")
        assert len(out) == 1, out
        assert "app/foo.py:1" in out[0]
        assert "write_text" in out[0]

    def test_anti_vacuity_positive_before_negatives(self):
        """An inert scanner (always []) must red HERE, before any negative
        control gets a chance to pass for free."""
        assert _hits([_POSITIVE], "core/bar.py"), "scanner returned nothing for the positive control"
        # Only now are the negatives meaningful.
        assert _hits(["tmp.write_text(s)", "tmp.replace(target)"], "core/bar.py") == []
        assert _hits(["atomic_write_json(path, payload)"], "core/bar.py") == []
        assert _hits([_POSITIVE], "tests/test_x.py") == []

    @pytest.mark.parametrize(
        "line",
        [
            'with open(path, "w", encoding="utf-8") as fh:',
            "with open(path, 'wb') as fh:",
            'fh = open(path, mode="w")',
            "json.dump(payload, fh, indent=2)",
            "target.write_bytes(blob)",
            'Path(out).write_text(json.dumps(d), encoding="utf-8")',
        ],
    )
    def test_each_write_shape_is_reported(self, line):
        assert _hits([line], "dashboard/x.py"), line

    @pytest.mark.parametrize(
        "path",
        [
            "app/foo.py",
            "core/foo.py",
            "coaches/foo.py",
            "dashboard/foo.py",
            "game_reader/foo.py",
            "agents/agent1_lead/foo.py",
            "modes/foo.py",
            "lcu/foo.py",
            "vision_server/foo.py",
            "web_dashboard.py",
        ],
    )
    def test_every_production_dir_is_in_scope(self, path):
        assert _hits([_POSITIVE], path), path


class TestScannerNegativeControls:
    def test_tmp_then_replace_idiom_not_reported(self):
        lines = [
            "tmp = target.with_suffix('.json.tmp')",
            "tmp.write_text(body, encoding='utf-8')",
            "tmp.replace(target)",
        ]
        assert _hits(lines, "core/foo.py") == []

    def test_os_replace_in_hunk_exempts_the_write(self):
        lines = ['open(scratch, "w").write(body)', "os.replace(scratch, target)"]
        assert _hits(lines, "core/foo.py") == []

    def test_atomic_write_json_usage_not_reported(self):
        assert _hits(["atomic_write_json(path, payload)"], "core/foo.py") == []

    def test_private_atomic_helper_in_hunk_exempts(self):
        lines = ['f.write_text("x")', "_atomic_write(target, data)"]
        assert _hits(lines, "agents/agent4_coach_mentor/ui_applier.py") == []

    def test_scratch_marker_on_the_line_alone_is_enough(self):
        # The SAME-LINE half of the rule: a scratch target is the first half of
        # the idiom even when the publish step is not in this hunk.
        for line in (
            "tmp.write_text(s)",
            "scratch.write_bytes(b)",
            "_tmp_path.write_text(s)",
            'open(str(dest) + ".part", "w").write(s)',
        ):
            assert _hits([line], "core/foo.py") == [], line

    def test_comment_lines_are_skipped(self):
        assert _hits(["# never call path.write_text( directly"], "core/foo.py") == []

    def test_read_and_append_are_not_write_hits(self):
        for line in (
            'open(path, "r", encoding="utf-8")',
            "open(path, 'rb')",
            "json.load(fh)",
            "json.dumps(payload)",
            "path.read_text()",
        ):
            assert _hits([line], "core/foo.py") == [], line

    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_x.py",
            "agents/daemon_slayer/tests/test_y.py",
            "tools/x.py",
            "scripts/x.py",
            "docs/x.md",
            "ops/loop/slots.py",
            "ops/loop/winmutex.py",
            "ops/rc_incident_log.py",
            "web/js/main.js",
            # MEASURED 2026-09-11: 14 of the 18 whole-tree hits were this
            # pytest suite, which lives under an in-scope prefix with no
            # tests/ segment. pytest's own discovery convention is the fence.
            "agents/agent3_testing/suite/test_round42.py",
            "agents/agent3_testing/suite/conftest.py",
        ],
    )
    def test_exempt_paths_never_report(self, path):
        assert _hits([_POSITIVE], path) == [], path

    def test_test_basename_fence_does_not_leak_to_production(self):
        # The fence is the BASENAME, so a module that merely mentions test in
        # its name (or a helper next to a suite) stays in scope.
        assert _hits([_POSITIVE], "agents/agent3_testing/runner.py")
        assert _hits([_POSITIVE], "core/latest_health.py")


# ---------------------------------------------------------------- main() wiring

_DIFF = (
    "diff --git a/app/foo.py b/app/foo.py\n"
    "--- a/app/foo.py\n"
    "+++ b/app/foo.py\n"
    "@@ -10,0 +11,2 @@ def save():\n"
    "+    s = json.dumps(d)\n"
    f"+    {_POSITIVE}\n"
)


def _drive_main(monkeypatch, tmp_path, mode: str | None) -> int:
    """Run main() against a synthetic staged diff with NO real git and NO ruff.

    cwd is an empty tmp dir so `os.path.isfile(root/app/foo.py)` is False and
    the ruff half never resolves an interpreter.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(G, "_git", lambda args, root: _DIFF if args and args[0] == "diff" else "")
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
    if mode is None:
        monkeypatch.delenv("RC_ATOMIC_WRITE_GATE", raising=False)
    else:
        monkeypatch.setenv("RC_ATOMIC_WRITE_GATE", mode)
    return G.main()


class TestMainModes:
    def test_block_mode_returns_the_glyph_exit_code(self, monkeypatch, tmp_path, capsys):
        rc = _drive_main(monkeypatch, tmp_path, "block")
        err = capsys.readouterr().err
        assert rc == 2, err
        assert "app/foo.py:12" in err
        assert "write_text" in err

    def test_warn_mode_returns_zero_with_report_on_stderr(self, monkeypatch, tmp_path, capsys):
        rc = _drive_main(monkeypatch, tmp_path, "warn")
        err = capsys.readouterr().err
        assert rc == 0, err
        assert "app/foo.py:12" in err
        assert "atomic" in err.lower()

    def test_unset_defaults_to_warn(self, monkeypatch, tmp_path, capsys):
        rc = _drive_main(monkeypatch, tmp_path, None)
        err = capsys.readouterr().err
        assert rc == 0, err
        assert "app/foo.py:12" in err

    def test_off_mode_reports_nothing(self, monkeypatch, tmp_path, capsys):
        rc = _drive_main(monkeypatch, tmp_path, "off")
        err = capsys.readouterr().err
        assert rc == 0, err
        assert "app/foo.py" not in err
        assert "atomic" not in err.lower()

    def test_mode_parse_is_case_insensitive_and_defaults_warn(self, monkeypatch):
        monkeypatch.setenv("RC_ATOMIC_WRITE_GATE", "BLOCK")
        assert G._atomic_write_mode() == "block"
        monkeypatch.setenv("RC_ATOMIC_WRITE_GATE", " Off ")
        assert G._atomic_write_mode() == "off"
        monkeypatch.setenv("RC_ATOMIC_WRITE_GATE", "garbage")
        assert G._atomic_write_mode() == "warn"
        monkeypatch.delenv("RC_ATOMIC_WRITE_GATE")
        assert G._atomic_write_mode() == "warn"


def test_this_file_is_ascii():
    raw = Path(__file__).read_bytes()
    assert [b for b in raw if b > 127] == []
