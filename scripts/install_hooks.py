"""Point git at the TRACKED hooks in .githooks/.

WHY THIS SCRIPT NO LONGER WRITES A HOOK FILE
--------------------------------------------
It used to write `.git/hooks/pre-commit` containing ONLY the since-removed DS
review-package mirror sync, overwriting whatever was already there.
`.git/hooks/` is not version controlled, so that clobbered the tracked hooks in
`.githooks/` and nothing pointed the two at each other.

Measured consequence, found 2026-07-26: the tracked and active pre-commit hooks
had FULLY DIVERGED. `core.hooksPath` resolved to `.git\\hooks`, whose hook ran
only that one sync, so THREE tracked guards had silently stopped running -
`precommit_pycompile.py`, `gen_archmap.py --check`, and
`gen_state_schema.py --check`. Both generated artifacts had drifted by the time
it surfaced (25 lines of ARCHITECTURE.md, 10 of state_schema.js). The
`commit-msg` pair had split the same way: the co-author-trailer strip lived only
in the untracked copy, the Conventional-Commits check only in the tracked one, so
exactly one of the two ran depending on which file won.

So: setting `core.hooksPath` is the whole job. Every hook body belongs in
`.githooks/`, under version control, where a fresh clone and a sibling machine
both get it. Do not reintroduce a hook-writing installer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIRNAME = ".githooks"


def main() -> int:
    hooks_dir = REPO_ROOT / HOOKS_DIRNAME
    if not (REPO_ROOT / ".git").exists():
        print("Not a git repository.")
        return 1
    if not hooks_dir.is_dir():
        print(f"Missing tracked hooks directory: {hooks_dir}")
        return 1

    # Relative on purpose - an absolute path breaks the moment the repo is
    # cloned to a different location, which is precisely the portability the
    # tracked-hooks layout exists to provide.
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "core.hooksPath", HOOKS_DIRNAME],
        check=True,
    )
    active = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "config", "core.hooksPath"],
        capture_output=True, text=True,
    ).stdout.strip()

    print(f"core.hooksPath = {active}")
    for hook in sorted(p for p in hooks_dir.iterdir() if p.is_file()):
        print(f"  active: {hook.name}")
    print(
        "\nHook bodies are tracked in .githooks/. The untracked .git/hooks/ copies "
        "are now inert - git consults core.hooksPath instead."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
