"""Pure helpers behind ops/migrate/e_move.ps1 (the RC C: -> E: move).

Pins the two rewrites that must be exact because a wrong byte is a silent
breakage after the move: every spelling of a path literal, and the Claude Code
``.claude.json`` project-key clone (never remove, never overwrite).
"""
from __future__ import annotations

import codecs
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "ops" / "migrate" / "e_move_helpers.py"
_spec = importlib.util.spec_from_file_location("e_move_helpers_under_test", _PATH)
em = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = em
_spec.loader.exec_module(em)

SRC, DST = r"C:\Riot Commander", r"E:\Riot Commander"
WT_SRC, WT_DST = r"C:\rc-worktrees", r"E:\rc-worktrees"
MAPS = [(SRC, DST), (WT_SRC, WT_DST)]


@pytest.fixture()
def rw():
    return em.PathRewriter(MAPS)


@pytest.mark.parametrize("before, after", [
    (r'"C:\Riot Commander\tools\x.py"', r'"E:\Riot Commander\tools\x.py"'),
    ("C:/Riot Commander/.git/worktrees/a", "E:/Riot Commander/.git/worktrees/a"),
    (r'"cmd": "C:\\Riot Commander\\tools\\x.py"', r'"cmd": "E:\\Riot Commander\\tools\\x.py"'),
    ('Bash(node --check "/c/Riot Commander/web/x.js")', 'Bash(node --check "/e/Riot Commander/web/x.js")'),
    ("C:\\Riot Commander", "E:\\Riot Commander"),
    ("cd c:\\riot commander\\ops", "cd e:\\Riot Commander\\ops"),
    ("C:/RIOT COMMANDER", "E:/Riot Commander"),
    ("gitdir: C:/rc-worktrees/lane-ds/.git", "gitdir: E:/rc-worktrees/lane-ds/.git"),
    ("WD=C:\\rc-worktrees", "WD=E:\\rc-worktrees"),
])
def test_every_spelling_is_rewritten(rw, before, after):
    new, n = rw.rewrite(before)
    assert new == after
    assert n == 1


@pytest.mark.parametrize("text", [
    r"C:\Riot Commander.pre-E-move-20261008\x",
    r"C:\Riot Commander2\x",
    r"C:\Riot Commander_old",
    r"XC:\Riot Commander\x",
    r"D:\Riot Commander\x",
    "C--Riot-Commander",
    '--name "Riot Commander"',
    r"C:\Riot\Commander",
])
def test_lookalikes_are_not_rewritten(rw, text):
    assert rw.rewrite(text) == (text, 0)
    assert not rw.matches(text)


def test_mixed_line_rewrites_all_and_is_idempotent(rw):
    line = (r'"C:\Riot Commander\ops\rc_supervisor.py" --config "C:\Riot Commander\ops\rc_config.json"'
            r' && cd /c/rc-worktrees/a')
    once, n = rw.rewrite(line)
    assert n == 3
    assert "C:" not in once and "/c/" not in once
    assert rw.rewrite(once) == (once, 0)


def test_destination_never_rematched_by_a_later_pair():
    # A chain C->E and E->F must not turn C into F in one pass.
    chain = em.PathRewriter([(r"C:\A", r"E:\A"), (r"E:\A", r"F:\A")])
    assert chain.rewrite(r"C:\A\x") == (r"E:\A\x", 1)


def test_bare_drive_root_is_refused():
    with pytest.raises(ValueError):
        em.PathRewriter([("C:\\", "E:\\")])


def test_rewrite_bytes_preserves_crlf_bom_and_non_ascii(rw):
    raw = codecs.BOM_UTF8 + "x = 'C:\\Riot Commander\\a'\r\nname = 'caf\u00e9'\r\n".encode("utf-8")
    new, n, kind = em.rewrite_bytes(raw, rw)
    assert (n, kind) == (1, "bytes")
    assert new == codecs.BOM_UTF8 + "x = 'E:\\Riot Commander\\a'\r\nname = 'caf\u00e9'\r\n".encode("utf-8")


def test_rewrite_bytes_handles_utf16_and_skips_binary(rw):
    raw = codecs.BOM_UTF16_LE + "<Command>C:\\Riot Commander\\x.py</Command>\r\n".encode("utf-16-le")
    new, n, kind = em.rewrite_bytes(raw, rw)
    assert (n, kind) == (1, "utf-16-le")
    assert new.startswith(codecs.BOM_UTF16_LE)
    assert new[2:].decode("utf-16-le") == "<Command>E:\\Riot Commander\\x.py</Command>\r\n"
    blob = b"\x00\x01C:\\Riot Commander\\x"
    assert em.rewrite_bytes(blob, rw) == (blob, 0, "binary")


def test_rewrite_bytes_untouched_file_is_identical(rw):
    raw = b"nothing to see\nhere\n"
    assert em.rewrite_bytes(raw, rw) == (raw, 0, "bytes")


@pytest.mark.parametrize("rel, ok", [
    (".claude/settings.json", True),
    (".claude/settings.local.json", True),
    ("ops/loop/config.local.json", True),
    ("tools/run_me.ps1", True),
    ("x/y.TXT", True),
    ("logs/2026-10-08.log", False),
    ("data/aram_coaching_data.json", False),
    ("docs/_archive/old.json", False),
    ("moon_sync_inbox/note.txt", False),
    ("rc-shell/node_modules/pkg/package.json", False),
    ("a/.venv/pyvenv.cfg", False),
    ("ops/__pycache__/x.json", False),
    (".claude/worktrees/agent-1/.claude/settings.json", False),
    ("ops/runtime/e_move_backup/.claude/settings.json", False),
    ("ops/runtime/e_move_state.json", False),
    ("ops/migrate/e_move.ps1", False),
    ("ops/runtime/responder_export/0dcdf4ad0750/ops/rc_config.json", False),
    ("ops/runtime/history.jsonl", False),
    ("ops/runtime/run.log.1", False),
    ("tools/script.py", False),
])
def test_config_candidate_filter(rel, ok):
    assert em.config_candidate(rel)[0] is ok


def _claude_json():
    return {
        "numStartups": 3,
        "projects": {
            "C:/Riot Commander": {
                "hasTrustDialogAccepted": True,
                "allowedTools": ['Bash(node --check "/c/Riot Commander/web/x.js")'],
                "mcpServers": {"usage": {"command": "node",
                                         "args": ["C:\\Riot Commander\\tools\\usage-mcp-server.js"]}},
                "lastCost": 1.5,
            },
            "C:\\Riot Commander": {"hasTrustDialogAccepted": True},
            "C:/riot commander": {"hasTrustDialogAccepted": False},
            "C:\\Riot Commander\\.claude\\worktrees\\stale": {"hasTrustDialogAccepted": True},
            "/srv/unrelated": {"hasTrustDialogAccepted": True},
        },
    }


def test_clone_project_keys_clones_roots_and_rewrites_inside():
    data = _claude_json()
    before = json.loads(json.dumps(data))
    actions = em.clone_project_keys(data, MAPS)
    by_from = {a["from"]: a for a in actions}
    assert by_from["C:/Riot Commander"] == {"from": "C:/Riot Commander", "to": "E:/Riot Commander",
                                            "action": "cloned"}
    assert by_from["C:\\Riot Commander"]["action"] == "cloned"
    assert by_from["C:/riot commander"]["action"] == "exists"
    clone = data["projects"]["E:/Riot Commander"]
    assert clone["hasTrustDialogAccepted"] is True
    assert clone["allowedTools"] == ['Bash(node --check "/e/Riot Commander/web/x.js")']
    assert clone["mcpServers"]["usage"]["args"] == ["E:\\Riot Commander\\tools\\usage-mcp-server.js"]
    assert data["projects"]["E:\\Riot Commander"] == {"hasTrustDialogAccepted": True}
    # Nothing removed, nothing pre-existing changed, worktree keys not cloned.
    for k, v in before["projects"].items():
        assert data["projects"][k] == v
    assert not any("worktrees" in k and k.startswith("E:") for k in data["projects"])
    assert len(data["projects"]) == len(before["projects"]) + 2


def test_clone_project_keys_never_overwrites_existing_destination():
    data = _claude_json()
    data["projects"]["E:/Riot Commander"] = {"hasTrustDialogAccepted": False, "mine": 1}
    actions = em.clone_project_keys(data, MAPS)
    assert {"from": "C:/Riot Commander", "to": "E:/Riot Commander", "action": "exists"} in actions
    assert data["projects"]["E:/Riot Commander"] == {"hasTrustDialogAccepted": False, "mine": 1}


def test_clone_project_keys_without_projects_is_a_noop():
    assert em.clone_project_keys({"x": 1}, MAPS) == []


def test_clone_keys_in_file_preserves_format_and_dry_run_writes_nothing(tmp_path):
    f = tmp_path / ".claude.json"
    body = json.dumps(_claude_json(), indent=2, ensure_ascii=False)
    f.write_bytes(body.encode("utf-8"))
    dry = em.clone_keys_in_file(f, MAPS, tmp_path / "bak", dry_run=True)
    assert dry["format_preserved"] is True and dry["written"] is False
    assert f.read_bytes() == body.encode("utf-8")
    assert not (tmp_path / "bak").exists()
    res = em.clone_keys_in_file(f, MAPS, tmp_path / "bak", dry_run=False)
    assert res["written"] is True and res["verified"] is True
    after = json.loads(f.read_text(encoding="utf-8"))
    assert "E:/Riot Commander" in after["projects"]
    assert list((tmp_path / "bak").iterdir())
    # Second run is a no-op.
    again = em.clone_keys_in_file(f, MAPS, tmp_path / "bak", dry_run=False)
    assert again["written"] is False


def test_find_strays_reports_destination_only_entries_and_deletes_nothing(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    for root in (src, dst):
        (root / "a").mkdir(parents=True)
        (root / "a" / "b.txt").write_bytes(b"x")
        (root / "keep").mkdir()
    # Same case as the mkdir above: "A" only reached "a" on a case-INsensitive
    # filesystem, so the CI (Linux) runner raised FileNotFoundError here.
    (dst / "a" / "EXTRA.txt").write_bytes(b"x")
    (dst / "gone_dir" / "sub").mkdir(parents=True)
    (dst / "gone_dir" / "x.txt").write_bytes(b"x")
    (dst / "gone_dir" / "sub" / "y.txt").write_bytes(b"x")
    for own in (".git/HEAD", "ops/runtime/e_move_backup/z.json", "ops/runtime/e_move_state.json", "logs/e_move.log"):
        (dst / own).parent.mkdir(parents=True, exist_ok=True)
        (dst / own).write_bytes(b"x")
    (src / "ops" / "runtime").mkdir(parents=True)
    (src / "logs").mkdir()
    before = sorted(str(p) for p in dst.rglob("*"))
    res = em.find_strays(src, dst)
    assert {(s["rel"], s["kind"], s["files"]) for s in res["sample"]} == {
        ("a/EXTRA.txt", "file", 1), ("gone_dir", "dir", 2)}
    assert (res["count"], res["files"], res["errors"]) == (2, 3, 0)
    assert sorted(str(p) for p in dst.rglob("*")) == before
    assert em.find_strays(src, tmp_path / "nope")["missing"] is True


# The maps here are built from tmp_path, and PathRewriter accepts only
# drive-absolute Windows paths (DrivePath.parse) - by design, it is the C: -> E:
# move tool. A POSIX tmp_path ("/tmp/...") is refused with ValueError.
@pytest.mark.skipif(os.name != "nt", reason="PathRewriter maps drive-absolute Windows paths only")
def test_repoint_gitdirs_rewrites_links_and_classifies(tmp_path):
    src, dst = tmp_path / "src repo", tmp_path / "dst repo"
    wt_src, wt_dst = tmp_path / "wt-src", tmp_path / "wt-dst"
    maps = [(str(src), str(dst)), (str(wt_src), str(wt_dst))]
    rw = em.PathRewriter(maps)
    (dst / ".git" / "worktrees" / "a").mkdir(parents=True)
    (dst / ".git" / "worktrees" / "b").mkdir(parents=True)
    (dst / ".git" / "worktrees" / "ext").mkdir(parents=True)
    (dst / ".claude" / "worktrees" / "a").mkdir(parents=True)
    (wt_dst / "b").mkdir(parents=True)
    fwd = lambda p: str(p).replace("\\", "/")  # noqa: E731
    (dst / ".git" / "worktrees" / "a" / "gitdir").write_bytes(
        (fwd(src / ".claude" / "worktrees" / "a" / ".git") + "\n").encode())
    (dst / ".git" / "worktrees" / "b" / "gitdir").write_bytes((fwd(wt_src / "b" / ".git") + "\n").encode())
    (dst / ".git" / "worktrees" / "ext" / "gitdir").write_bytes(
        (fwd(tmp_path / "elsewhere" / ".git") + "\n").encode())
    (dst / ".claude" / "worktrees" / "a" / ".git").write_bytes(
        ("gitdir: " + fwd(src / ".git" / "worktrees" / "a") + "\n").encode())
    (wt_dst / "b" / ".git").write_bytes(("gitdir: " + fwd(src / ".git" / "worktrees" / "b") + "\r\n").encode())

    dry = em.repoint_gitdirs(dst, wt_dst, rw, dry_run=True, backup_root=None)
    assert len(dry["rewritten"]) == 4
    assert (wt_dst / "b" / ".git").read_bytes().startswith(b"gitdir: " + fwd(src).encode())

    res = em.repoint_gitdirs(dst, wt_dst, rw, dry_run=False, backup_root=dst / "bak")
    assert len(res["rewritten"]) == 4 and res["errors"] == []
    assert (wt_dst / "b" / ".git").read_bytes() == ("gitdir: " + fwd(dst / ".git" / "worktrees" / "b")
                                                    + "\r\n").encode()
    assert {r["worktree"] for r in res["internal_worktrees"]} == {
        fwd(dst / ".claude" / "worktrees" / "a"), fwd(wt_dst / "b")}
    assert [r["worktree"] for r in res["external_worktrees"]] == [fwd(tmp_path / "elsewhere")]
    assert res["dangling_pointers"] == []
    assert (dst / "bak" / "gitlinks" / ".git" / "worktrees" / "a" / "gitdir").is_file()
    again = em.repoint_gitdirs(dst, wt_dst, rw, dry_run=False, backup_root=dst / "bak")
    assert again["rewritten"] == []
