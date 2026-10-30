"""RM-1121 (ops/audit/p0_inventory.py): the full CSV lands LF only.

`main()` opened ops/audit/p0_inventory_full.csv with newline="" and wrote the
provenance line with an explicit "\\n", then handed the file to a bare
`csv.writer(f)`. The csv module's default lineterminator is "\\r\\n" on every
OS, so the file came out MIXED: one LF line, then CRLF rows. The writer now
passes lineterminator="\\n"; P0_INVENTORY.md was already LF (newline="\\n").

The repo is a throwaway under tmp_path with git's global config pinned to an
empty file, the system config off and `GIT_CONFIG_COUNT` cleared, so no
host-wide setting decides the result (the RM-861 test's fixture shape).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_P0 = _ROOT / "ops" / "audit" / "p0_inventory.py"


def _load():
    spec = importlib.util.spec_from_file_location("_s144p10_p0_inventory", _P0)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)
    env = dict(os.environ)

    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> None:
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "s144p10@test")
    run("config", "user.name", "s144p10")
    run("config", "core.autocrlf", "false")
    for rel in ("a.txt", "b.txt", "c.txt"):
        (repo / rel).write_bytes(b"x" * 8 + b"\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")

    out = tmp_path / "out"
    out.mkdir()
    p0 = _load()
    monkeypatch.setattr(p0, "ROOT", repo)
    monkeypatch.setattr(p0, "OUT_DIR", out)
    assert p0.main() == 0
    return out


def test_full_csv_has_no_crlf(inventory):
    data = (inventory / "p0_inventory_full.csv").read_bytes()
    assert b"\r" not in data, data[:200]


def test_full_csv_is_one_lf_line_per_row(inventory):
    lines = (inventory / "p0_inventory_full.csv").read_bytes().split(b"\n")
    # provenance + header + 3 files, then the empty tail after the last "\n".
    assert lines[-1] == b""
    body = lines[:-1]
    assert len(body) == 5, body
    assert body[0].startswith(b"# point-in-time snapshot generated ")
    assert body[1] == b"relpath,bytes,ext,top"
    assert sorted(row.split(b",")[0] for row in body[2:]) == [b"a.txt", b"b.txt", b"c.txt"]


def test_markdown_report_stays_lf(inventory):
    data = (inventory / "P0_INVENTORY.md").read_bytes()
    assert b"\r" not in data
    assert data.startswith(b"# P0 baseline tree inventory\n")


def test_positive_control_bare_csv_writer_is_crlf(tmp_path):
    # The defect class itself, no harness: a bare csv.writer on a newline=""
    # file writes "\r\n" on any OS, so the two CSV tests above are not green
    # merely because the platform never emits CR.
    import csv
    target = tmp_path / "control.csv"
    with target.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["a", "b"], ["c", "d"]])
    assert target.read_bytes() == b"a,b\r\nc,d\r\n"
