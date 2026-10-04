"""RM-492: credential-shape scan over git HISTORY, wired where a clone gets it.

`tools/credential_patterns.py` ran only as a Claude PostToolUse hook - absent
in a fresh clone, absent under `--no-verify`, blind to history - on a PUBLIC
repository. `tools/credential_history_scan.py` adds:
- `--pre-push`: scan the lines a push ADDS (wired in `.githooks/pre-push`);
- `--all`: scan every reachable blob against a reviewed sha+class baseline.

Every credential-shaped literal below is ASSEMBLED AT RUNTIME so this file
never carries one (the write-time hook and the push scan read it too).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import credential_history_scan as chs
from tools import credential_patterns as cp

ROOT = Path(__file__).resolve().parent.parent
_NW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FAKE_KEY = "sk-" + "ant-" + "Q7" * 12  # anthropic shape, assembled


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=True, creationflags=_NW).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "core.autocrlf", "false")
    (r / "a.py").write_text("x = 1\n", encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _commit(r: Path, name: str, body: str) -> str:
    (r / name).write_text(body, encoding="ascii")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")
    return _git(r, "rev-parse", "HEAD")


def test_push_scan_halts_on_an_added_credential(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "cfg.py", f'KEY = "{FAKE_KEY}"\n')
    rc = chs.run_push([["HEAD", "--not", base]], root=repo)
    assert rc == chs.EXIT_HALT


def test_push_scan_is_clean_on_ordinary_code(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "b.py", "def f():\n    return 2\n")
    assert chs.run_push([["HEAD", "--not", base]], root=repo) == chs.EXIT_CLEAN


def test_push_scan_honours_the_line_pragma(repo):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "t.py", f'KEY = "{FAKE_KEY}"  # {cp.PRAGMA}\n')
    assert chs.run_push([["HEAD", "--not", base]], root=repo) == chs.EXIT_CLEAN


def test_push_scan_does_not_reflag_old_content_on_an_unrelated_edit(repo):
    """The reason pre-push scans ADDED lines, not blobs: a reviewed fixture
    already in history must not halt a push that edits another line."""
    _commit(repo, "fx.py", f'KEY = "{FAKE_KEY}"\nY = 1\n')
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "fx.py", f'KEY = "{FAKE_KEY}"\nY = 2\n')
    added = chs.added_lines(["HEAD", "--not", base], root=repo)
    assert list(added.values()) == [["Y = 2"]]
    assert chs.run_push([["HEAD", "--not", base]], root=repo) == chs.EXIT_CLEAN


def test_push_scan_reports_no_value(repo, capsys):
    base = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "cfg.py", f'KEY = "{FAKE_KEY}"\n')
    chs.run_push([["HEAD", "--not", base]], root=repo)
    err = capsys.readouterr().err
    assert FAKE_KEY not in err and "class=anthropic" in err


def test_bad_range_is_a_fault_not_a_clean_verdict(repo):
    rc = chs.run_push([["deadbeef" * 5]], root=repo)
    assert rc == chs.EXIT_FAULT


def test_all_scan_baseline_accepts_only_reviewed_blob_and_class(repo, tmp_path):
    sha_commit = _commit(repo, "cfg.py", f'KEY = "{FAKE_KEY}"\n')
    blob = _git(repo, "rev-parse", f"{sha_commit}:cfg.py")
    empty = tmp_path / "empty.json"
    empty.write_text('{"accepted": []}', encoding="ascii")
    assert chs.run([["--all"]], root=repo, baseline_path=empty) == chs.EXIT_HALT
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"accepted": [
        {"blob": blob, "class": "anthropic", "path": "cfg.py"}]}), encoding="ascii")
    assert chs.run([["--all"]], root=repo, baseline_path=ok) == chs.EXIT_CLEAN
    wrong_class = tmp_path / "wc.json"
    wrong_class.write_text(json.dumps({"accepted": [
        {"blob": blob, "class": "openai", "path": "cfg.py"}]}), encoding="ascii")
    assert chs.run([["--all"]], root=repo, baseline_path=wrong_class) == chs.EXIT_HALT


def test_over_cap_blob_is_counted_not_silently_dropped(repo, tmp_path):
    _commit(repo, "big.txt", "y" * 5000 + "\n")
    blobs, sizes = {}, {}
    blobs.update(chs.list_blobs(["--all"], root=repo, sizes=sizes))
    _hits, stats = chs.scan_blobs(blobs, set(), root=repo, max_bytes=1000,
                                  sizes=sizes)
    assert stats["skipped_large"] == 1
    assert stats["scanned"] + stats["skipped_large"] + stats["skipped_binary"] == stats["blobs"]


def test_baseline_file_carries_shas_and_classes_never_values():
    data = json.loads((ROOT / "tools" / "credential_history_baseline.json")
                      .read_text(encoding="ascii"))
    rows = data["accepted"]
    assert rows, "baseline is empty - the reviewed --all census is missing"
    for r in rows:
        assert set(r) == {"blob", "class", "path"}
        assert len(r["blob"]) == 40 and all(c in "0123456789abcdef" for c in r["blob"])
        assert r["class"] in cp.PATTERN_CLASSES
    assert cp.scan_text(json.dumps(data)) == []


def test_pre_push_hook_runs_the_scan_before_lfs():
    hook = (ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    scan = hook.index("credential_history_scan.py\" --pre-push")
    lfs = hook.index('git lfs pre-push "$@"')
    assert scan < lfs
    assert 'printf \'%s\\n\' "$REFS" | "$PY" "$ROOT/tools/credential_history_scan.py"' in hook
    body = [ln for ln in hook.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert body[-1] == 'git lfs pre-push "$@"'
