"""RM-714 dry-run half: tools/ignored_prune_manifest.py prints a prune manifest
of stale IGNORED local files - path, bytes and a consumer verdict - and
deletes nothing.

Acceptance (BACKLOG.md RM-714, REFRESHED 2026-10-25): for each candidate
class the tool prints path, bytes and a consumer verdict (a ``git grep -l`` of
the basename over tracked files); dry-run only, with no delete code path at
all; it refuses to list a tracked path; a tmp tree with one consumed and one
orphan file pins the verdicts. The Recycle Bin apply after the operator's OK
stays out of scope (FLEET-COMMON item 9).

Every test builds its own git repository under tmp_path; nothing here reads
or writes the live checkout.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import ignored_prune_manifest as ipm

try:
    import _winapi  # Windows only: CreateJunction needs no symlink privilege
except ImportError:
    _winapi = None

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_OLD = time.time() - 60 * 86400  # 60 days ago: past the default 14-day age floor


def _git(root: Path, *args: str) -> None:
    flags = {"creationflags": _NO_WINDOW} if _NO_WINDOW else {}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, **flags)


def _touch(root: Path, rel: str, data: bytes = b"x", old: bool = True) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    if old:
        os.utime(p, (_OLD, _OLD))
    return p


def _age_dir(path: Path) -> None:
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            os.utime(os.path.join(dirpath, f), (_OLD, _OLD))
        os.utime(dirpath, (_OLD, _OLD))


RULES = (
    ipm.Rule("shadow_backup", "data/*_backup_shadow.jsonl", "test rule"),
    ipm.Rule("runtime_backup", "ops/runtime/e_move_backup", "test rule"),
    ipm.Rule("runtime_scratch", "ops/runtime/_*.log", "test rule"),
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _touch(root, ".gitignore",
           b"data/*_shadow.jsonl\nops/runtime/\n")
    # A tracked code file names e_move_backup: that directory is CONSUMED.
    _touch(root, "ops/migrate/helpers.py", b"SKIP = ('e_move_backup',)\n")
    # Prose and the ignore file name the shadow backup: NOT consumers.
    _touch(root, "docs/notes.md", b"hz_choice_prefix_backup_shadow.jsonl is stale\n")
    _touch(root, "README.md", b"see ops/runtime/_old.log\n")
    _git(root, "add", ".gitignore", "ops/migrate/helpers.py", "docs/notes.md", "README.md")
    # Ignored, untracked, old candidates.
    _touch(root, "data/hz_choice_prefix_backup_shadow.jsonl", b"0123456789")
    _touch(root, "ops/runtime/e_move_backup/a.json", b"abc")
    _touch(root, "ops/runtime/e_move_backup/sub/b.json", b"de")
    _age_dir(root / "ops/runtime/e_move_backup")
    _touch(root, "ops/runtime/_old.log", b"log")
    return root


def _by_rel(cands):
    return {c.rel: c for c in cands}


def test_one_consumed_and_one_orphan_verdict(repo: Path) -> None:
    got = _by_rel(ipm.find_candidates(repo, rules=RULES))
    orphan = got["data/hz_choice_prefix_backup_shadow.jsonl"]
    assert orphan.verdict == "orphan"
    assert orphan.consumers == ()
    consumed = got["ops/runtime/e_move_backup"]
    assert consumed.verdict == "consumed"
    assert consumed.consumers == ("ops/migrate/helpers.py",)
    assert consumed.is_dir


def test_markdown_and_gitignore_mentions_are_not_consumers(repo: Path) -> None:
    got = _by_rel(ipm.find_candidates(repo, rules=RULES))
    # docs/notes.md names the shadow file, README.md names _old.log and
    # .gitignore names ops/runtime/: none is a reader.
    assert got["data/hz_choice_prefix_backup_shadow.jsonl"].verdict == "orphan"
    assert got["ops/runtime/_old.log"].verdict == "orphan"


def test_bytes_are_reported_for_files_and_whole_directories(repo: Path) -> None:
    got = _by_rel(ipm.find_candidates(repo, rules=RULES))
    assert got["data/hz_choice_prefix_backup_shadow.jsonl"].size == 10
    assert got["ops/runtime/e_move_backup"].size == 5
    assert got["ops/runtime/_old.log"].size == 3


def test_classes_are_carried_and_output_is_sorted(repo: Path) -> None:
    cands = ipm.find_candidates(repo, rules=RULES)
    assert [c.rel for c in cands] == sorted(c.rel for c in cands)
    assert {c.rel: c.cls for c in cands} == {
        "data/hz_choice_prefix_backup_shadow.jsonl": "shadow_backup",
        "ops/runtime/e_move_backup": "runtime_backup",
        "ops/runtime/_old.log": "runtime_scratch",
    }


def test_a_tracked_path_is_refused(repo: Path) -> None:
    _touch(repo, "ops/runtime/_tracked.log")
    _git(repo, "add", "-f", "ops/runtime/_tracked.log")
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "ops/runtime/_tracked.log" not in got
    assert skipped.get("tracked") == 1


def test_a_directory_holding_a_tracked_file_is_refused(repo: Path) -> None:
    _touch(repo, "ops/runtime/e_move_backup/keep.txt")
    _git(repo, "add", "-f", "ops/runtime/e_move_backup/keep.txt")
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "ops/runtime/e_move_backup" not in got
    assert skipped.get("tracked") == 1


def test_an_untracked_path_that_is_not_ignored_is_not_listed(repo: Path) -> None:
    _touch(repo, "data/x_backup_shadow.jsonl.keep")  # not matched by the rule
    _git(repo, "rm", "-q", "--cached", ".gitignore")
    _touch(repo, ".gitignore", b"ops/runtime/\n")  # data/ shadow no longer ignored
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "data/hz_choice_prefix_backup_shadow.jsonl" not in got
    assert skipped.get("not_ignored") == 1


def test_a_fresh_file_or_directory_is_not_stale(repo: Path) -> None:
    _touch(repo, "ops/runtime/_fresh.log", old=False)
    _touch(repo, "ops/runtime/e_move_backup/sub/new.json", old=False)
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "ops/runtime/_fresh.log" not in got
    # One fresh file anywhere inside makes the whole directory fresh.
    assert "ops/runtime/e_move_backup" not in got
    assert skipped.get("too_new") == 2
    # A zero age floor lists both.
    got0 = _by_rel(ipm.find_candidates(repo, rules=RULES, min_age_days=0))
    assert "ops/runtime/_fresh.log" in got0
    assert "ops/runtime/e_move_backup" in got0


@pytest.mark.parametrize("git_rel", ["ops/runtime/e_move_backup/.git",
                                     "ops/runtime/e_move_backup/sub/clone/.git"])
def test_a_directory_holding_a_nested_checkout_at_any_depth_is_refused(
        repo: Path, git_rel: str) -> None:
    _touch(repo, git_rel, b"gitdir: elsewhere\n")
    _age_dir(repo / "ops/runtime/e_move_backup")
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "ops/runtime/e_move_backup" not in got
    assert skipped.get("nested_checkout") == 1


def test_a_rule_that_matches_nothing_lists_nothing(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q")
    assert ipm.find_candidates(root, rules=RULES) == []


@pytest.mark.skipif(_winapi is None, reason="junction test needs Windows")
def test_a_link_candidate_is_never_listed_or_followed(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    _touch(outside, "big.bin", b"0" * 100)
    link = repo / "ops/runtime/e_move_backup"
    import shutil
    shutil.rmtree(link)
    _winapi.CreateJunction(str(outside), str(link))
    skipped: dict[str, int] = {}
    got = _by_rel(ipm.find_candidates(repo, rules=RULES, skipped=skipped))
    assert "ops/runtime/e_move_backup" not in got
    assert skipped.get("link") == 1
    assert (outside / "big.bin").exists()


def test_main_prints_the_manifest_and_changes_nothing(repo: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(ipm, "RULES", RULES)
    before = sorted((p.relative_to(repo).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in repo.rglob("*") if ".git" not in p.parts)
    assert ipm.main(["--root", str(repo)]) == 0
    out = capsys.readouterr().out
    rows = [ln.split("\t") for ln in out.splitlines() if not ln.startswith("#")]
    assert ["orphan", "shadow_backup", "10", "data/hz_choice_prefix_backup_shadow.jsonl", "-"] in rows
    assert ["consumed", "runtime_backup", "5", "ops/runtime/e_move_backup/",
            "ops/migrate/helpers.py"] in rows
    assert "# dry run only: 3 candidates, nothing moved" in out
    after = sorted((p.relative_to(repo).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                   for p in repo.rglob("*") if ".git" not in p.parts)
    assert before == after


def test_main_refuses_a_bad_root(tmp_path: Path, capsys) -> None:
    assert ipm.main(["--root", str(tmp_path / "nope")]) == 2


def test_main_refuses_outside_a_repository(tmp_path: Path, capsys, monkeypatch) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    monkeypatch.setattr(ipm, "RULES", RULES)
    _touch(root, "ops/runtime/_old.log")
    assert ipm.main(["--root", str(root)]) == 2
    assert "ignored_prune_manifest:" in capsys.readouterr().err


def test_there_is_no_apply_flag(repo: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        ipm.main(["--root", str(repo), "--apply"])
    assert exc.value.code == 2


def test_the_module_has_no_delete_code_path() -> None:
    """Dry run ONLY in this slice: no call that removes, moves or recycles."""
    tree = ast.parse((REPO / "tools" / "ignored_prune_manifest.py").read_text(encoding="utf-8"))
    banned = {"unlink", "rmtree", "remove", "rmdir", "removedirs", "rename",
              "replace", "move", "send2trash", "recycle", "SHFileOperationW"}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name for a in node.names} | {getattr(node, "module", "") or ""}
            assert not names & {"shutil", "send2trash", "recycle_bin", "core.recycle_bin"}, names
    assert not called & banned, called & banned


def test_default_rules_are_anchored_and_cover_the_filed_classes() -> None:
    classes = {r.cls for r in ipm.RULES}
    assert {"settings_backup", "playwright_capture", "ui_audit", "docs_scratch",
            "external_review_copy", "archive_leftover", "shadow_backup",
            "pytest_dump", "runtime_scratch", "runtime_capture", "runtime_backup",
            "control_scratch", "lane_log", "tls_screenshot",
            "snapshot_png"} <= classes
    for r in ipm.RULES:
        parent, _, leaf = r.pattern.rpartition("/")
        # Wildcards only in the last segment: each rule lists ONE directory.
        assert not any(ch in parent for ch in "*?["), r.pattern
        assert leaf and ".." not in r.pattern.split("/"), r.pattern
        assert not r.pattern.startswith("/") and "\\" not in r.pattern, r.pattern
        assert r.reason.strip(), r.pattern


def test_default_rules_on_a_mirror_of_the_filed_layout(tmp_path: Path) -> None:
    root = tmp_path / "mirror"
    root.mkdir()
    _git(root, "init", "-q")
    _touch(root, ".gitignore", b"*.bak-*\n.playwright-mcp/\ndocs/ui_audit/\ndocs/_scratch/\n"
           b"data/*_shadow.jsonl\nlogs/\nops/runtime/\nops/tls/*.png\n"
           b"tests/snapshot_panels/screenshots/\n")
    _git(root, "add", ".gitignore")
    for rel in (".claude/settings.json.bak-perseus", ".playwright-mcp/page.yml",
                "docs/ui_audit/a/b.png", "docs/_scratch/x.md",
                "data/hz_choice_prefix_backup_shadow.jsonl", "data/live_shadow.jsonl",
                "logs/_baseline_pytest.txt", "logs/2026-11-01.log",
                "ops/runtime/_bop.log", "ops/runtime/health.json",
                "ops/tls/_dashboard.png", "tests/snapshot_panels/screenshots/home.png"):
        _touch(root, rel)
    _age_dir(root / "docs/ui_audit")
    _age_dir(root / ".playwright-mcp")
    _age_dir(root / "docs/_scratch")
    cands = ipm.find_candidates(root)
    # .gitignore names .playwright-mcp, ui_audit and _scratch: an ignore rule
    # is not a reader, so every one stays an orphan.
    assert {c.rel: c.verdict for c in cands if c.verdict != "orphan"} == {}
    got = {c.rel for c in cands}
    assert got == {".claude/settings.json.bak-perseus", ".playwright-mcp", "docs/ui_audit",
                   "docs/_scratch", "data/hz_choice_prefix_backup_shadow.jsonl",
                   "logs/_baseline_pytest.txt", "ops/runtime/_bop.log",
                   "ops/tls/_dashboard.png", "tests/snapshot_panels/screenshots/home.png"}
