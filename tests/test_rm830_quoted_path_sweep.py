"""RM-830: git path output read by tools/ with neither -z nor core.quotepath=false.

With core.quotePath on (git's default) a path holding a byte over 0x7F is
written C-QUOTED - `"d\\304\\201.py"` - by `diff --name-only`, `ls-files`,
`status --porcelain`, `log --name-status` / `-p` and `log --name-only`. And a
child decoded through the locale (cp1252 on a Windows console) turns the raw
UTF-8 of an unquoted name into mojibake, or faults on a byte cp1252 lacks.
Either way the tool keys a name that is not on disk:

- tools/ci_impact_selector.py `changed_paths` / `git_tracked`: a changed
  non-ASCII path misses the path rules, so a needed CI job can be skipped;
- tools/sibling_name_sweep.py `collect_push_blobs`: a PATH / DIFF-ADDED blob
  carries the quoted name, so an allowlist match on it fails closed;
- tools/drift_guard.py `check_untracked_authored`: a tracked non-ASCII doc (or
  one with a space - the output was also split on whitespace) is reported as
  "authored but NOT tracked";
- tools/ds_feed_index.py `_tracked_feeds`: a tracked feed is dropped;
- tools/freeze_witness.py `git_witness`, tools/p3_ascii_census.py `tracked`,
  tools/ci_watchdog.py `diff_names` (+ `_run`), tools/repo_insights.py
  `gather_git`: the same quoted or mojibake name.

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off, `GIT_CONFIG_COUNT` cleared and
core.quotePath set ON in the repo, so no host-wide setting decides the result.

RM-818 N3 (tools/precommit_gate.py `_CHILD_TEXT` errors="replace") is
ACCEPTED, not changed: the last test pins that a staged non-UTF-8 byte is still
BLOCKED, only named as U+FFFD (decision and Reverses-if in LEDGER).

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "tools"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

_A_MACRON = chr(0x0101)   # UTF-8 C4 81 (cp1252 has no 0x81)
_E_ACUTE = chr(0x00E9)    # UTF-8 C3 A9 (cp1252 maps both bytes: mojibake)
_NAME = "d" + _A_MACRON + _E_ACUTE


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_rm830_{name}", _TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclasses resolve their module by name
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)
    return dict(os.environ)


def _repo(tmp_path: Path, env: dict) -> tuple[Path, callable]:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> str:
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env,
                              check=True).stdout.decode("utf-8", errors="replace").strip()

    run("init", "-q", ".")
    run("config", "user.email", "rm830@test")
    run("config", "user.name", "rm830")
    run("config", "core.quotepath", "true")
    run("config", "core.autocrlf", "false")
    (repo / "base.txt").write_text("base\n", encoding="ascii")
    run("add", "-A")
    run("commit", "-qm", "base")
    return repo, run


def _add(repo: Path, run, rel: str, text: str = "x\n") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("ascii"))
    run("add", "--", rel)
    run("commit", "-qm", "add " + rel.encode("ascii", "replace").decode("ascii"))
    return run("rev-parse", "HEAD")


def test_control_git_really_quotes_the_name_here(tmp_path, git_env):
    repo, run = _repo(tmp_path, git_env)
    _add(repo, run, "core/" + _NAME + ".py")
    assert '"core/d\\304\\201\\303\\251.py"' in run("ls-files")


# --- ci_impact_selector (MEDIUM: a needed CI job can be skipped) -----------

def test_ci_impact_selector_changed_paths_carry_the_real_name(tmp_path, git_env):
    sel = _load("ci_impact_selector")
    repo, run = _repo(tmp_path, git_env)
    base = run("rev-parse", "HEAD")
    rel = "core/" + _NAME + ".py"
    head = _add(repo, run, rel)
    assert sel.changed_paths(repo, base, head) == [rel]


def test_ci_impact_selector_git_tracked_decodes_utf8(tmp_path, git_env):
    """`ls-files -z` was already used; the decode went through the locale. Run
    in a child with UTF-8 mode OFF (a plain Windows console is cp1252), so the
    interpreter's own utf8 mode cannot mask a locale decode."""
    repo, run = _repo(tmp_path, git_env)
    rel = "core/" + _NAME + ".py"
    _add(repo, run, rel)
    code = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location('sel', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec); sys.modules['sel'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "from pathlib import Path\n"
        "sys.stdout.write(json.dumps(sorted(mod.git_tracked(Path(sys.argv[2])))))\n"
    )
    env = {k: v for k, v in git_env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    out = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code,
         str(_TOOLS / "ci_impact_selector.py"), str(repo)],
        capture_output=True, env=env,
    )
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[-600:]
    assert json.loads(out.stdout.decode("ascii")) == ["base.txt", rel]


# --- sibling_name_sweep ----------------------------------------------------

def test_sibling_sweep_push_blobs_key_the_real_name(tmp_path, git_env):
    sweep = _load("sibling_name_sweep")
    repo, run = _repo(tmp_path, git_env)
    base = run("rev-parse", "HEAD")
    rel = "docs/" + _NAME + ".md"
    tip = _add(repo, run, rel, "hello\n")
    line = f"refs/heads/main {tip} refs/heads/main {base}"
    stats = sweep.ScanStats()
    blobs = sweep.collect_push_blobs(repo, [line], "origin", stats)
    paths = {b.path for b in blobs if b.source == "PATH"}
    diffs = {b.path for b in blobs if b.source == "DIFF-ADDED"}
    assert paths == {rel}, paths
    assert diffs == {rel}, diffs


# --- drift_guard ------------------------------------------------------------

@pytest.mark.parametrize("stem", [_NAME, "two words"])
def test_drift_guard_a_tracked_doc_is_not_reported_untracked(stem, tmp_path, git_env):
    dg = _load("drift_guard")
    repo, run = _repo(tmp_path, git_env)
    _add(repo, run, f"docs/{stem}.md")
    findings = dg.check_untracked_authored(repo, [("docs", "docs")])
    assert [f for f in findings if "untracked" in str(f)] == []


def test_drift_guard_control_an_untracked_doc_is_still_reported(tmp_path, git_env):
    dg = _load("drift_guard")
    repo, run = _repo(tmp_path, git_env)
    _add(repo, run, "docs/tracked.md")
    (repo / "docs" / (_NAME + ".md")).write_bytes(b"x\n")
    findings = dg.check_untracked_authored(repo, [("docs", "docs")])
    assert len(findings) == 1 and _NAME in str(findings[0]), findings


# --- ds_feed_index ----------------------------------------------------------

def test_ds_feed_index_tracked_feeds_keep_a_non_ascii_feed(tmp_path, git_env, monkeypatch):
    dfi = _load("ds_feed_index")
    repo, run = _repo(tmp_path, git_env)
    rel = "data/daemon_slayer/16.1.1/" + _NAME + ".json"
    _add(repo, run, rel, "{}\n")
    monkeypatch.setattr(dfi, "ROOT", repo)
    assert dfi._tracked_feeds() == {rel}


# --- freeze_witness ---------------------------------------------------------

def test_freeze_witness_git_witness_names_the_real_file(tmp_path, git_env):
    fw = _load("freeze_witness")
    repo, _run = _repo(tmp_path, git_env)
    (repo / (_NAME + ".txt")).write_bytes(b"x\n")
    assert fw.git_witness(repo).strip() == "?? " + _NAME + ".txt"


# --- p3_ascii_census --------------------------------------------------------

def test_p3_ascii_census_tracked_lists_the_real_name(tmp_path, git_env, monkeypatch):
    p3 = _load("p3_ascii_census")
    repo, run = _repo(tmp_path, git_env)
    rel = "web/" + _NAME + ".js"
    _add(repo, run, rel)
    monkeypatch.setattr(p3, "ROOT", str(repo))
    assert sorted(p3.tracked()) == ["base.txt", rel]


# --- ci_watchdog (diagnostics: the frozen guard reads diff_names) -----------

def test_ci_watchdog_diff_names_step_reads_the_real_name(tmp_path, git_env):
    cw = _load("ci_watchdog")
    repo, run = _repo(tmp_path, git_env)
    rel = "core/" + _NAME + ".py"
    _add(repo, run, rel)
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    (repo / rel).write_bytes(b"changed\n")
    steps = dict(cw.plan_dispatch(1, "0" * 40, worktree=repo, repo="o/r"))
    rc, out = cw._run(steps["diff_names"], cwd=repo)
    assert rc == 0, out
    assert out.splitlines() == [rel]


def test_ci_watchdog_run_decodes_utf8_and_never_raises(tmp_path):
    cw = _load("ci_watchdog")
    code = "import sys; sys.stdout.buffer.write(b'a\\xc4\\x81 b\\x81\\x9d')"
    rc, out = cw._run([sys.executable, "-c", code], cwd=tmp_path)
    assert rc == 0
    assert out.startswith("a" + _A_MACRON + " b"), ascii(out)


# --- repo_insights ----------------------------------------------------------

def test_repo_insights_dir_histogram_uses_the_real_name(tmp_path, git_env, monkeypatch):
    ri = _load("repo_insights")
    repo, run = _repo(tmp_path, git_env)
    _add(repo, run, _NAME + "/x.py")
    monkeypatch.setattr(ri, "ROOT", repo)
    dirs = dict(ri.gather_git(30, None)["dirs"])
    assert dirs.get(_NAME) == 1, dirs


# --- precommit_gate N3: ACCEPTED (still blocked, named U+FFFD) ---------------

def test_precommit_gate_a_non_utf8_staged_byte_still_blocks(tmp_path, git_env):
    pg = _load("precommit_gate")
    repo, run = _repo(tmp_path, git_env)
    (repo / "notes.txt").write_bytes(b"smart \x93quote\n")
    run("add", "--", "notes.txt")
    staged = pg._staged_added(str(repo))
    lines = [text for _n, text in staged["notes.txt"]["lines"]]
    assert lines == ["smart " + chr(0xFFFD) + "quote"]
    assert pg._glyph_hits(lines[0], "notes.txt"), "a non-UTF-8 byte must stay a glyph finding"


# --- same-root siblings found by the RM-830 sweep (outside the filed list) ---
#
# Each runs in a child with UTF-8 mode OFF: a plain Windows console decodes a
# text-mode child through cp1252, and this interpreter's own utf8 mode would
# otherwise mask the locale decode these sites carried.

def _child(module_path: Path, body: str, *args: str):
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('m', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec); sys.modules['m'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        + body
    )
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    out = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code, str(module_path), *args],
                         capture_output=True, env=env)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")[-600:]
    return json.loads(out.stdout.decode("ascii"))


def test_precommit_pycompile_compiles_a_non_ascii_staged_file(tmp_path, git_env):
    """The commit gate's py_compile pass: a quoted name ended in `.py"`, so a
    staged non-ASCII .py with a syntax error was never compiled."""
    repo, run = _repo(tmp_path, git_env)
    rel = "core/" + _NAME + ".py"
    (repo / "core").mkdir()
    (repo / rel).write_bytes(b"def broken(:\n")
    run("add", "--", rel)
    got = _child(_ROOT / "scripts" / "precommit_pycompile.py",
                 "mod.ROOT = Path(sys.argv[2])\n"
                 "sys.stdout.write(json.dumps([p.relative_to(mod.ROOT).as_posix()"
                 " for p in mod.staged_python_files()]))\n", str(repo))
    assert got == [rel]


def test_citation_audit_tracked_files_decode_utf8(tmp_path, git_env):
    repo, run = _repo(tmp_path, git_env)
    rel = "docs/" + _NAME + ".md"
    _add(repo, run, rel)
    got = _child(_TOOLS / "citation_audit.py",
                 "sys.stdout.write(json.dumps(sorted(mod.tracked_files(Path(sys.argv[2])))))\n",
                 str(repo))
    assert got == ["base.txt", rel]


def test_md_guard_selector_git_tracked_decodes_utf8(tmp_path, git_env):
    repo, run = _repo(tmp_path, git_env)
    rel = "docs/" + _NAME + ".md"
    _add(repo, run, rel)
    got = _child(_TOOLS / "md_guard_selector.py",
                 "sys.stdout.write(json.dumps(sorted(mod._git_tracked(Path(sys.argv[2])))))\n",
                 str(repo))
    assert got == ["base.txt", rel]


def test_lane_launcher_content_dirty_names_a_non_ascii_edit(tmp_path, git_env):
    repo, run = _repo(tmp_path, git_env)
    rel = "core/" + _NAME + ".py"
    _add(repo, run, rel)
    (repo / rel).write_bytes(b"changed\n")
    got = _child(_ROOT / "ops" / "loop" / "lane_launcher.py",
                 "sys.stdout.write(json.dumps(sorted(mod._content_dirty(Path(sys.argv[2])))))\n",
                 str(repo))
    assert got == [rel]
