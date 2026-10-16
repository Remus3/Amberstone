"""
scripts/precommit_msg_check.py - commit-msg hook (Conventional Commits).

# arch: phase 7 (2026-05-09) - make Conventional Commits subject lines mechanical

Validates the staged commit's subject line against the Conventional Commits
shape: `<type>(<scope>)?!?: <description>`. The repo already follows this
convention by hand (see `git log` - every commit since s125 matches);
this hook prevents drift.

The hook only inspects the SUBJECT line. Body and trailers are unrestricted.
Auto-generated subjects (Merge / Revert / fixup! / squash! / Reapply / amend!)
are skipped, with one exception below.

Merge template (MAIN PUBREPO order 1b, 2026-10-15): a merge commit's subject
reads `merge: <topic>` (an item id may sit in the scope, `merge(RM-123): ...`)
and carries no agent worktree name; branch, slice and session detail go in the
body. So `merge` is a type, and a MERGE subject - the `merge:` type or git's own
`Merge branch '...'` / `Merge remote-tracking branch '...'` text - that names an
agent worktree branch (`worktree-agent-<id>`, `agent-<8+ hex>`) is refused. A
git-generated merge of any other branch still passes through unparsed. The
template and the merge recipe live in `.github/CONTRIBUTING.md`.

Bypass with `--no-verify` if absolutely necessary; please don't make a habit
of it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
    "merge",
)

# <type>(<optional scope>)<optional !>: <space><non-space>...
SUBJECT_RE = re.compile(
    rf"^(?:{'|'.join(TYPES)})(?:\([\w./\- ]+\))?!?:\s+\S",
)

# A merge subject: the template's `merge` type, or git's generated `Merge ...`.
MERGE_SUBJECT_RE = re.compile(r"^(?:merge(?:\([^)]*\))?!?:|Merge )")

# An agent worktree branch name. `worktree-agent-` is unmistakable at any
# length; a bare `agent-` needs 8+ hex chars so prose such as `agent-dispatch`
# or `agent-abc1` is not caught. Bounded so `subagent-...` does not match.
AGENT_BRANCH_RE = re.compile(
    r"(?<![\w-])(?:worktree-agent-[\w-]+|agent-[0-9a-fA-F]{8,}(?![\w]))",
)

MERGE_TEMPLATE_DOC = ".github/CONTRIBUTING.md"

AGENT_MERGE_ERROR = (
    "merge subject names an agent worktree branch; use the merge template: "
    "subject `merge: <topic>` (an item id may sit in the scope, "
    "`merge(RM-123): <topic>`), branch / slice / session detail in the body - "
    f"see {MERGE_TEMPLATE_DOC} (Commit messages)"
)

SKIP_PREFIXES = (
    "Merge ",
    "Revert ",
    "Reapply ",
    "fixup!",
    "squash!",
    "amend!",
)

SOFT_LINE_LIMIT = 100


def validate(subject: str) -> tuple[bool, str | None]:
    """Return (ok, error_message). error_message is None on success."""
    if not subject.strip():
        return False, "empty subject line"
    if MERGE_SUBJECT_RE.match(subject) and AGENT_BRANCH_RE.search(subject):
        return False, AGENT_MERGE_ERROR
    if any(subject.startswith(p) for p in SKIP_PREFIXES):
        return True, None
    if not SUBJECT_RE.match(subject):
        return False, "subject does not match <type>(<scope>)?: <description>"
    return True, None


def _read_subject(msg_file: Path) -> str:
    raw = msg_file.read_text(encoding="utf-8", errors="replace")
    for line in raw.splitlines():
        if line.startswith("#"):
            continue
        if not line.strip():
            continue
        return line.rstrip()
    return ""


def main() -> int:
    if len(sys.argv) < 2:
        print("commit-msg: missing path argument", file=sys.stderr)
        return 1
    msg_file = Path(sys.argv[1])
    if not msg_file.exists():
        print(f"commit-msg: file not found: {msg_file}", file=sys.stderr)
        return 1

    subject = _read_subject(msg_file)
    ok, err = validate(subject)
    if not ok:
        example = (
            "merge(RM-123): stop-claim gate gaps"
            if MERGE_SUBJECT_RE.match(subject)
            else "feat(coaching): add Smite tier override"
        )
        print(
            "commit-msg: subject line rejected.\n"
            f"  reason:   {err}\n"
            f"  got:      {subject!r}\n"
            "  expected: <type>(<scope>)?: <description>\n"
            f"  types:    {', '.join(TYPES)}\n"
            f"  example:  {example}\n"
            "Bypass with --no-verify if absolutely necessary.",
            file=sys.stderr,
        )
        return 1

    if len(subject) > SOFT_LINE_LIMIT:
        # Warn-only: don't block, just nudge.
        print(
            f"commit-msg: subject is {len(subject)} chars (>{SOFT_LINE_LIMIT}); "
            "consider tightening.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
