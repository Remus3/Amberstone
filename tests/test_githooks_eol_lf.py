"""Guard: the tracked git hooks are LF on disk and ASCII (MAIN FIX 2026-10-21
1254 item 18, C1b-3 S5).

`.githooks/` is the AUTHORITATIVE gate (CLAUDE.md hard rule; core.hooksPath
points at it). Its blobs were already LF, but no `.gitattributes` rule covered
the extension-less hook files, so under `core.autocrlf=true` every fresh
checkout wrote them CRLF (measured 2026-10-22: all six CRLF in a new worktree;
three of six CRLF in the long-lived checkout). The fleet rule is ASCII + LF
(FLEET-COMMON item 8), and an exported copy of a CRLF `#!/bin/sh` script fails
on a shell that does not strip CR.

The fix is the `.githooks/* text eol=lf` pin; a checkout made before it must
re-materialise the six files once (delete them, then `git checkout -- .githooks/`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NUL = "\0"


def _hook_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", ".githooks/"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return sorted(p for p in out.split(NUL) if p)


def _attrs(paths: list[str]) -> dict[str, dict[str, str]]:
    proc = subprocess.run(
        ["git", "check-attr", "--stdin", "-z", "text", "eol"],
        cwd=ROOT, input=NUL.join(paths),
        capture_output=True, text=True, check=True,
    )
    fields = proc.stdout.split(NUL)
    attrs: dict[str, dict[str, str]] = {}
    for i in range(0, len(fields) - 2, 3):
        path, attr, value = fields[i], fields[i + 1], fields[i + 2]
        if path:
            attrs.setdefault(path, {})[attr] = value
    return attrs


def test_hook_enumeration_is_not_empty() -> None:
    # Guards the guard: an empty `git ls-files` would pass every check below.
    hooks = _hook_files()
    assert ".githooks/pre-commit" in hooks
    assert ".githooks/pre-push" in hooks
    assert ".githooks/commit-msg" in hooks
    assert len(hooks) >= 6, hooks


def test_every_hook_is_pinned_text_eol_lf() -> None:
    hooks = _hook_files()
    attrs = _attrs(hooks)
    unpinned = [
        p for p in hooks
        if attrs.get(p, {}).get("text") != "set"
        or attrs.get(p, {}).get("eol") != "lf"
    ]
    assert unpinned == [], (
        "these tracked git hooks are not pinned `text eol=lf` in .gitattributes, "
        f"so core.autocrlf=true checks them out CRLF: {unpinned}"
    )


@pytest.mark.parametrize("rel", _hook_files())
def test_hook_on_disk_has_no_cr(rel: str) -> None:
    data = (ROOT / rel).read_bytes()
    n_cr = data.count(b"\r")
    assert n_cr == 0, (
        f"{rel} carries {n_cr} CR byte(s) on disk; re-materialise it: "
        "delete the file, then `git checkout -- .githooks/`"
    )


@pytest.mark.parametrize("rel", _hook_files())
def test_hook_blob_is_lf_and_ascii(rel: str) -> None:
    blob = subprocess.run(
        ["git", "show", f":{rel}"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    assert b"\r" not in blob, f"{rel}: the index blob itself carries CR"
    high = sum(1 for b in blob if b > 127)
    assert high == 0, f"{rel}: {high} byte(s) above 127 (ASCII rule)"
