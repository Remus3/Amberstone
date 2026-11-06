"""RM-713 (a) slice: the RM-504 hold-corpus sample lives under docs/_archive/.

ops/loop/hold_corpus_rc.json is a one-off sample written on 2026-10-03 by
`tools/slot_bucket_audit.py --hold-corpus <log> --out <path>`. The tool takes
its output path from the caller and has no default, so no code names the old
file, and no test or tool reads it back. It is RM-504 evidence, so it sits in
the dated archive instead of in the live ops/loop code directory.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OLD = "ops/loop/hold_corpus_rc.json"
NEW = "docs/_archive/2026-10/hold_corpus_rc.json"


def _tracked() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    return set(out.splitlines())


def test_old_path_is_gone_and_archive_path_is_tracked():
    tracked = _tracked()
    assert tracked, "git ls-files enumerated nothing"
    assert OLD not in tracked, f"{OLD} is still tracked"
    assert NEW in tracked, f"{NEW} is not tracked"


def test_archived_bytes_are_ascii_lf_and_still_the_corpus():
    raw = (REPO / NEW).read_bytes()
    assert raw, f"{NEW} is empty"
    assert b"\r" not in raw, f"{NEW} has CR bytes"
    raw.decode("ascii")
    corpus = json.loads(raw)
    assert corpus["basis"].startswith("controller.log acquire/release pairs")
    assert corpus["pairs"] == len(corpus["holds"])


def test_the_tool_has_no_default_output_path():
    """The tool writes where the caller says; nothing regenerates the old file."""
    text = (REPO / "tools" / "slot_bucket_audit.py").read_text(encoding="utf-8")
    assert OLD not in text
    assert 'ap.add_argument("--out", type=Path,' in text
    assert "default" not in text.split('ap.add_argument("--out"', 1)[1].split(")", 1)[0]
