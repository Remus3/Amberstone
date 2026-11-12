"""FLEET-KIT v28 (MAIN 2026-11-01 0825 ORDER to all seven, cumulative): pre-push
tolerates a remote old tip absent after a history rewrite (KIT-PREPUSH-REWRITE).

The ORDER's section 5 asks RC to vendor all 24 files + MANIFEST byte-for-byte and
confirm conformance() == []; FLEET-COMMON.md and settings are unchanged, so no
re-embed. These run the vendored gate against a real clone and a real bare remote,
so an absent old tip is a real missing object, never a test double's answer.
CLAUDE.md carries the RC "KIT v28" rules line naming this guard.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "ops" / "fleet_kit"
# Kit v30 (MAIN 2026-11-12 0345 ORDER, cumulative v29 + v30) superseded v28
# (manifest 34347174...b9e52a6d93, block cacc3ca3...4e77dd0); the pins below now
# hold the v30 bytes (24 files). fleet_identity is unchanged in v30.
V28_MANIFEST_SHA256 = "d2ac40250bd0efc071f0eb11c1e92ae04af88d750de200cf8ed4dc5714d07ea2"
V28_COMMON_BLOCK_SHA256 = "6205943cb187258bdd72f9799fd03cbd90354562d8f561ccf2e4c19fbedea5ee"
END = "<!-- FLEET-COMMON END -->"
OPERATOR = "Op Erator <op@example.invalid>"
ABSENT_TIP = "ab" * 20


def _load(name):
    spec = importlib.util.spec_from_file_location(f"rc_v28_probe_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args, who="Op Erator", mail="op@example.invalid"):
    env = dict(os.environ, GIT_AUTHOR_NAME=who, GIT_AUTHOR_EMAIL=mail,
               GIT_COMMITTER_NAME=who, GIT_COMMITTER_EMAIL=mail)
    out = subprocess.run(["git", "-c", "core.hooksPath=", "-c", "commit.gpgsign=false", *args],
                         cwd=cwd, env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _repo(tmp_path):
    """A clone whose remote holds its first commit; returns (clone, bare, base sha)."""
    bare = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(tmp_path, "init", "--bare", "-b", "main", str(bare))
    _git(clone, "init", "-b", "main")
    _git(clone, "commit", "--allow-empty", "-m", "base")
    _git(clone, "push", str(bare), "main")
    return clone, bare, _git(clone, "rev-parse", "HEAD")


def _force_push_line(lsha, old=ABSENT_TIP):
    return f"refs/heads/main {lsha} refs/heads/main {old}\n"


def test_the_vendored_kit_is_the_v28_order_bytes_and_conforms():
    raw = (KIT / "MANIFEST.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == V28_MANIFEST_SHA256
    man = json.loads(raw.decode("ascii"))
    assert man["version"] == 30 and len(man["files"]) == 24
    assert man["common_block_sha256"] == V28_COMMON_BLOCK_SHA256
    fh = _load("fleet_headless")
    assert (fh.KIT_VERSION, fh.KIT_PATCH) == (30, 0)
    for name, want in man["files"].items():
        assert hashlib.sha256((KIT / name).read_bytes()).hexdigest() == want, name
    assert fh.conformance(ROOT) == []


def test_absent_old_tips_names_only_the_missing_old_tip(tmp_path):
    ident = _load("fleet_identity")
    clone, _bare, base = _repo(tmp_path)
    stdin = _force_push_line(base) + f"refs/heads/kept {base} refs/heads/kept {base}\n"
    assert ident.absent_old_tips(clone, stdin) == {ABSENT_TIP}
    assert ident.absent_old_tips(clone, f"refs/heads/n {base} refs/heads/n {'0' * 40}\n") == set()


def test_a_clean_force_push_over_an_absent_old_tip_is_scanned_and_passes(tmp_path):
    ident = _load("fleet_identity")
    clone, bare, _base = _repo(tmp_path)
    _git(clone, "commit", "--allow-empty", "-m", "rewritten")
    lsha = _git(clone, "rev-parse", "HEAD")
    assert ident.pre_push(str(bare), _force_push_line(lsha), cwd=clone,
                          idents=ident.operator_idents(clone, reader=lambda _c: OPERATOR)) == 0


def test_a_bad_author_in_that_range_still_refuses(tmp_path, capsys):
    ident = _load("fleet_identity")
    clone, bare, _base = _repo(tmp_path)
    _git(clone, "commit", "--allow-empty", "-m", "bad", who="Claude", mail="noreply@anthropic.com")
    _git(clone, "commit", "--allow-empty", "-m", "clean tip")
    lsha = _git(clone, "rev-parse", "HEAD")
    assert ident.pre_push(str(bare), _force_push_line(lsha), cwd=clone,
                          idents=ident.operator_idents(clone, reader=lambda _c: OPERATOR)) == 1
    assert "could not list" not in capsys.readouterr().err


def test_an_unreadable_remote_with_an_absent_old_tip_refuses(tmp_path, capsys):
    ident = _load("fleet_identity")
    clone, _bare, base = _repo(tmp_path)
    missing = str(tmp_path / "no-such-remote.git")
    assert ident.pre_push(missing, _force_push_line(base), cwd=clone,
                          idents=ident.operator_idents(clone, reader=lambda _c: OPERATOR)) == 1
    assert "nothing bounds the scan" in capsys.readouterr().err


def test_claude_md_carries_the_kit_v28_rules_line():
    text = (ROOT / "CLAUDE.md").read_bytes().decode("utf-8").replace("\r\n", "\n")
    rc = text[text.index(END):]
    line = next(ln for ln in rc.split("\n") if ln.startswith("**KIT v28 (MAIN 2026-11-01 0825"))
    for needle in ("absent", "Guard `tests/test_fleet_kit_v28.py`"):
        assert needle in line, needle
    assert (ROOT / "CLAUDE.md").stat().st_size <= 60 * 1024
