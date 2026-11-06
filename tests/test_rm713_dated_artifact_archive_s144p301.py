"""RM-713 (a) slice: two dated, no-reader artifacts live under docs/_archive/.

ops/loop/CDRAGON_FLIP_FINDINGS.md is a 2026-06-06 history record (title says
FLIPPED + SHIPPED; the NOT FLIPPED body is kept verbatim for provenance) and
ops/tls/_bridge_msg.txt is a retired-bridge screenshot request. Neither has a
code reader; both sat in live directories. They now sit under the dated
archive, and the bare-py guard no longer carries a dead allowlist row for the
second one (docs/_archive/** is already allowlisted).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MOVED = {
    "ops/loop/CDRAGON_FLIP_FINDINGS.md": "docs/_archive/2026-06/CDRAGON_FLIP_FINDINGS.md",
    "ops/tls/_bridge_msg.txt": "docs/_archive/2026-04/_bridge_msg.txt",
}


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def test_old_paths_are_gone_and_archive_paths_are_tracked():
    tracked = _tracked()
    assert tracked, "git ls-files enumerated nothing"
    for old, new in MOVED.items():
        assert old not in tracked, f"{old} is still tracked"
        assert new in tracked, f"{new} is not tracked"


def test_archived_bytes_are_ascii_and_lf():
    for new in MOVED.values():
        raw = (REPO / new).read_bytes()
        assert raw, f"{new} is empty"
        assert b"\r" not in raw, f"{new} has CR bytes"
        raw.decode("ascii")


def test_cdragon_record_keeps_its_flipped_title_and_verbatim_body():
    text = (REPO / MOVED["ops/loop/CDRAGON_FLIP_FINDINGS.md"]).read_text(encoding="ascii")
    assert text.startswith("# prefer-CDragon flip: FLIPPED + SHIPPED")
    assert "INVESTIGATED, NOT FLIPPED" in text
    assert "POST-319 FLIP EXECUTED" in text


def test_bare_py_guard_carries_no_dead_row_for_the_moved_note():
    text = (REPO / "tests" / "test_bare_py_ban.py").read_text(encoding="ascii")
    assert "ops/tls/_bridge_msg.txt" not in text
    assert '"docs/_archive/**"' in text
