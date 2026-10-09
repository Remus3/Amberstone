"""Guard: nothing tracked lands a commit on main as a bot or through a GitHub merge.

Source: MAIN's kit-v13 ORDER section 4 (GH-HYGIENE ruling 2026-10-08) and the
kit-v14 ORDER section 4 (ruling 2026-10-09), both relayed operator authority:

- No commit reachable from the default branch may carry a non-operator author
  or committer. A PR merged with GitHub's merge button or `gh pr merge` in ANY
  mode (squash, merge, rebase, auto) writes the web-merge committer - a
  non-operator committer - so no tracked tool may run that merge. A fix lands
  LOCALLY as an operator commit through ops/fleet_kit/fleet_gitlock.py, then
  is pushed.
- No workflow pushes to a default branch. A workflow that commits does so
  under a bot identity (the runner has no operator), so a tracked workflow may
  neither commit, push, set a git identity, nor hold `contents: write`.
- No tracked script invents a git identity: a placeholder `user.name` /
  `user.email` makes every later commit on that box non-operator.

Offenders this guard was written against (2026-10-09, all fixed in the same
slice): tools/ci_watchdog.py (`pr_merge` step), the patch-day-ddragon-sync and
docs-guards workflows (bot identity + push to main, `contents: write`), and
the dev bootstrap script, now scripts/bootstrap_dev.ps1 (placeholder global
identity).

Spelling rule for authors: a prohibition in a CODE comment must not spell the
literal invocation (write "a GitHub-side PR merge", not the gh command), or this
guard reads it as a call. Prose docs and tests are outside the scanned set.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

# Code that RUNS things. Markdown / prose is excluded on purpose: hand-off and
# ledger prose legitimately STATE the prohibition and would read as a call.
_CODE_PATTERNS = ("*.py", "*.ps1", "*.psm1", "*.sh", "*.bat", "*.cmd", "*.js",
                  "*.mjs", "*.cjs", "*.yml", "*.yaml")

# Repo-relative prefixes skipped by THIS guard (its own scope skips only):
#   tests/        - tests carry these strings as fixture DATA (claim-gate
#                   samples, throwaway-repo identities), never as a live call.
#   ops/fleet_kit/ - vendored byte-for-byte from MAIN; a defect there is
#                   reported to MAIN, never fixed locally (FLEET item 11).
_SKIP_PREFIXES = ("tests/", "ops/fleet_kit/")

# Files that DETECT a PR merge in other commands' text without ever running one.
# Each entry carries its reason; a new entry needs the same.
_DETECTORS = {
    "tools/stop_claim_gate.py": "matches a `pr merge` in a transcript command to "
                                "grade a merge CLAIM; it runs nothing",
}

# A PR merge on GitHub, in shell, argv-list or API form.
_PR_MERGE = (
    re.compile(r"\bgh(?:\.exe)?[\"']?\s+pr\s+merge\b", re.I),
    re.compile(r"\$\{?gh\}?[\"']?\s+pr\s+merge\b", re.I),
    re.compile(r"[\"']pr[\"']\s*,\s*[\"']merge[\"']", re.I),
    re.compile(r"pulls/[^\s\"']*/merge\b", re.I),
    re.compile(r"enablePullRequestAutoMerge", re.I),
)

# Setting (not reading) a git identity. The read form `user.name 2>$null` and
# `user.name)` are let through by the lookahead.
_SET_IDENTITY = (
    re.compile(r"\bconfig\s+(?:--(?:global|local|system|worktree)\s+)?"
               r"user\.(?:name|email)\s+(?!2?>|\)|$)\S", re.I),
    re.compile(r"[\"']config[\"']\s*,\s*(?:[\"']--\w+[\"']\s*,\s*)?"
               r"[\"']user\.(?:name|email)[\"']\s*,", re.I),
    re.compile(r"-c[\"',\s]+user\.(?:name|email)=", re.I),
    re.compile(r"\bGIT_(?:AUTHOR|COMMITTER)_(?:NAME|EMAIL)[\"']?\]?\s*[=:]", re.I),
)

# Inside a workflow `run:` block or `permissions:` map.
_WORKFLOW_WRITES = (
    ("git push", re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b")),
    ("git commit", re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?commit\b")),
    ("contents: write", re.compile(r"^\s*contents\s*:\s*write\b")),
    ("a push action", re.compile(
        r"uses:\s*(?:stefanzweifel/git-auto-commit-action|EndBug/add-and-commit|"
        r"ad-m/github-push-action)", re.I)),
)

_WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _code_files() -> list[Path]:
    out = []
    for p in iter_repo_files(REPO_ROOT, _CODE_PATTERNS):
        rel = relative_posix(p)
        if rel.startswith(_SKIP_PREFIXES):
            continue
        out.append(p)
    return out


def _code_lines(path: Path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    yield from enumerate(text.splitlines(), 1)


def _workflow_lines(path: Path):
    """Non-comment lines of a workflow. Comments may narrate what a lane USED to
    do; only what it does now is graded."""
    for n, line in _code_lines(path):
        if line.lstrip().startswith("#"):
            continue
        yield n, line


def _scan(patterns, files, *, skip=()) -> list[str]:
    hits = []
    for p in files:
        rel = relative_posix(p)
        if rel in skip:
            continue
        for n, line in _code_lines(p):
            if any(rx.search(line) for rx in patterns):
                hits.append(f"{rel}:{n}: {line.strip()[:160]}")
    return hits


# ---------------------------------------------------------------- anchors

def test_the_code_universe_is_not_vacuous():
    """An empty enumeration would pass every check below, so pin known members."""
    rels = {relative_posix(p) for p in _code_files()}
    assert len(rels) > 300, f"code universe collapsed to {len(rels)} files"
    for anchor in ("tools/ci_watchdog.py", ".github/workflows/ci.yml",
                   ".github/workflows/patch-day-ddragon-sync.yml",
                   ".github/workflows/docs-guards.yml",
                   "scripts/bootstrap_dev.ps1"):
        assert anchor in rels, f"{anchor} missing from the scanned universe"
    for det in _DETECTORS:
        assert (REPO_ROOT / det).is_file(), f"stale detector entry {det}"


@pytest.mark.parametrize("line", [
    '("pr_merge", ["gh", "pr", "merge", branch, "--repo", repo, "--squash"]),',
    "gh pr merge 12 --squash",
    '"$GH" pr merge 12 --auto',
    "& $gh pr merge $n --rebase",
    "gh api -X PUT repos/o/r/pulls/7/merge",
])
def test_the_merge_patterns_catch_every_known_form(line):
    assert any(rx.search(line) for rx in _PR_MERGE), line


@pytest.mark.parametrize("line,hit", [
    ('git config user.name "patch-day-sync"', True),
    ('git config user.email "41898282+github-actions[bot]@users.noreply.github.com"', True),
    ('& $git config --global user.name "Riot Commander AI"', True),
    ('subprocess.run(["git", "config", "user.email", "x@y"])', True),
    ('["git", "-c", "user.name=bot", "commit"]', True),
    ('env["GIT_AUTHOR_NAME"] = "bot"', True),
    ('{"GIT_COMMITTER_NAME": "bot"}', True),
    ('$env:GIT_AUTHOR_EMAIL = "bot@x"', True),
    ("GIT_COMMITTER_EMAIL=bot@x git commit", True),
    ('os.environ.get("GIT_AUTHOR_NAME")', False),
    ("$userName = (& $git config --global user.name 2>$null)", False),
    ("name = $(git config user.name)", False),
])
def test_the_identity_patterns_split_set_from_read(line, hit):
    assert any(rx.search(line) for rx in _SET_IDENTITY) is hit, line


# ---------------------------------------------------------------- the rules

def test_no_tracked_code_merges_a_pr_on_github():
    hits = _scan(_PR_MERGE, _code_files(), skip=set(_DETECTORS))
    assert not hits, (
        "A GitHub-side PR merge writes a non-operator (web-merge) committer onto "
        "main (kit v13/v14 ORDER section 4). Land the change locally as an "
        "operator commit through ops/fleet_kit/fleet_gitlock.py and push:\n  "
        + "\n  ".join(hits))


def test_no_tracked_script_sets_a_git_identity():
    hits = _scan(_SET_IDENTITY, _code_files())
    assert not hits, (
        "A tracked script sets a git identity. Every commit is the operator's "
        "(FLEET-COMMON 17); a missing identity must stop the commit, never be "
        "filled with a placeholder or a bot:\n  " + "\n  ".join(hits))


def test_no_workflow_commits_pushes_or_holds_contents_write():
    workflows = sorted(_WORKFLOWS_DIR.glob("*.yml")) + sorted(_WORKFLOWS_DIR.glob("*.yaml"))
    names = {p.name for p in workflows}
    assert {"ci.yml", "docs-guards.yml", "patch-day-ddragon-sync.yml"} <= names, names
    hits = []
    for p in workflows:
        for n, line in _workflow_lines(p):
            for what, rx in _WORKFLOW_WRITES:
                if rx.search(line):
                    hits.append(f"{relative_posix(p)}:{n}: {what}: {line.strip()[:120]}")
    assert not hits, (
        "No workflow pushes to a default branch (kit v13 ORDER section 4): a "
        "runner commit is a bot commit. Make the job REPORT (step summary, "
        "warning, failure) and land the change locally as an operator commit:\n  "
        + "\n  ".join(hits))


def test_the_workflow_rule_sees_through_comments_only():
    """The comment skip must not hide a real step: a `run:` line is graded."""
    sample = ["      # used to git push origin main", "          git push origin main"]
    graded = [ln for ln in sample if not ln.lstrip().startswith("#")]
    assert graded == ["          git push origin main"]
    assert _WORKFLOW_WRITES[0][1].search(graded[0])
