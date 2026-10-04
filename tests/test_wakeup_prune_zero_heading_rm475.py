"""RM-475: keep/move accounting counted a ZERO-HEADING block as a session in
FILE ORDER, so `--keep 3` over `H, S1, ZERO, S2, S3` kept `[S1, ZERO, S2]`
and archived the REAL session S3 - only 2 real sessions retained.

The keep budget now counts only REAL sessions (blocks with a SESSION_RE
match). A zero-heading block rides in position and never consumes a slot.
Driven through the real `scripts/wakeup_prune.py` `prune()`.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "wakeup_prune_rm475", _ROOT / "scripts" / "wakeup_prune.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


WP = _load()
SEP = WP.SEP


@pytest.fixture()
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(WP, "WAKEUP", tmp_path / "WAKEUP_NOTES.md")
    monkeypatch.setattr(WP, "ARCHIVE", tmp_path / "docs" / "history_notes.md")
    return WP.WAKEUP, WP.ARCHIVE


def _fixture(order):
    bodies = {
        "S1": "# 2026-09-03 - session one\nbody1\n",
        "S2": "# 2026-09-02 - session two\nbody2\n",
        "S3": "# 2026-09-01 - session three\nbody3\n",
        "S4": "# 2026-08-31 - session four\nbody4\n",
        "ZERO": "a stray note with no heading\n",
    }
    return "# Wakeup notes\n" + "".join(SEP + bodies[k] for k in order)


def _real(text):
    _, sessions = WP.split_sessions(text)
    return [s for s in sessions if WP.SESSION_RE.search(s)]


def test_zero_heading_block_does_not_consume_a_keep_slot(files):
    wakeup, archive = files
    wakeup.write_text(_fixture(["S1", "ZERO", "S2", "S3"]), encoding="utf-8")
    assert WP.prune(keep=3, dry_run=False) == 0
    kept = wakeup.read_text(encoding="utf-8")
    assert len(_real(kept)) == 3
    assert "session three" in kept
    assert "a stray note" in kept
    assert not archive.exists() or "session three" not in archive.read_text(encoding="utf-8")


def test_no_real_session_archived_while_a_zero_block_is_kept(files):
    wakeup, archive = files
    wakeup.write_text(_fixture(["S1", "ZERO", "S2", "S3", "S4"]), encoding="utf-8")
    assert WP.prune(keep=3, dry_run=False) == 0
    kept = wakeup.read_text(encoding="utf-8")
    moved = archive.read_text(encoding="utf-8")
    assert [ln.splitlines()[0] for ln in _real(kept)] == [
        "# 2026-09-03 - session one", "# 2026-09-02 - session two",
        "# 2026-09-01 - session three"]
    assert "session four" in moved
    assert "session three" not in moved


def test_check_counts_real_sessions_only(files):
    wakeup, _ = files
    wakeup.write_text(_fixture(["S1", "ZERO", "S2", "S3"]), encoding="utf-8")
    assert WP.check(3) == 0
    wakeup.write_text(_fixture(["S1", "ZERO", "S2", "S3", "S4"]), encoding="utf-8")
    assert WP.check(3) == 1
