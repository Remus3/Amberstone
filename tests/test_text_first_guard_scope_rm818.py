"""RM-818 (b): TEXT_FIRST_FLAG could still name ANY regular file in the repo.

RM-784 kept the override inside the repo root, so every tracked file - this
guard's own source, README.md - was an always-present flag that switched the
guard off. The override now counts only as a regular file strictly inside
`ops/runtime/` (gitignored runtime state, where the default flag already
lives); one anywhere else is ignored and the default flag applies.

Same harness as tests/test_text_first_guard.py: a COPY of the guard in a
throwaway repo root under tmp_path, run as a child with JSON on stdin.
"""
from __future__ import annotations

import json

import pytest

from tests.test_text_first_guard import FLAG_REL, SCRAPE, _deny_reason, _repo, _run, _touch

PAYLOAD = json.dumps({"tool_name": SCRAPE})


@pytest.mark.parametrize("value", [
    "tools/text_first_guard.py", "README.md", "ops/other.flag", "ops/runtime/../other.flag",
    "ops/runtimex/a.flag",
])
def test_a_repo_file_outside_ops_runtime_is_not_the_flag(value, tmp_path):
    root = _repo(tmp_path)
    for rel in ("README.md", "ops/other.flag", "ops/runtimex/a.flag"):
        _touch(root / rel)
    (root / "ops" / "runtime").mkdir(parents=True, exist_ok=True)
    assert (root / value).is_file(), value
    for override in (value, str(root / value)):
        reason = _deny_reason(_run(PAYLOAD, tmp_path, TEXT_FIRST_FLAG=override))
        assert FLAG_REL in reason, "the reason names the flag that works"


def test_ops_runtime_itself_is_not_the_flag(tmp_path):
    (_repo(tmp_path) / "ops" / "runtime").mkdir(parents=True)
    _deny_reason(_run(PAYLOAD, tmp_path, TEXT_FIRST_FLAG="ops/runtime"))


def test_a_file_under_ops_runtime_is_the_flag(tmp_path):
    flag = _touch(_repo(tmp_path) / "ops" / "runtime" / "sub" / "host.flag")
    for override in ("ops/runtime/sub/host.flag", str(flag)):
        proc = _run(PAYLOAD, tmp_path, TEXT_FIRST_FLAG=override)
        assert (proc.returncode, proc.stdout) == (0, ""), override


def test_an_ignored_repo_override_still_honours_the_default_flag(tmp_path):
    _touch(_repo(tmp_path) / FLAG_REL)
    proc = _run(PAYLOAD, tmp_path, TEXT_FIRST_FLAG="tools/text_first_guard.py")
    assert (proc.returncode, proc.stdout) == (0, "")
