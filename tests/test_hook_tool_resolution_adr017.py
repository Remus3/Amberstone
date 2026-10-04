"""ADR-017 / RM-432: hooks resolve gate tools from the committing checkout.

The ADR records worktree-relative resolution as a deliberate, documented
exposure. This pins the code to the record: if a hook starts resolving tools
via `--git-common-dir` (the rejected option (a)), or stops resolving them at
all, this fails until ADR-017 is revised.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ("pre-commit", "commit-msg", "pre-push")


def _hook(name: str) -> str:
    return (ROOT / ".githooks" / name).read_text(encoding="utf-8")


def test_hooks_resolve_tools_from_show_toplevel():
    for name in HOOKS:
        src = _hook(name)
        assert 'ROOT="$(git rev-parse --show-toplevel)"' in src, name
        assert "--git-common-dir" not in src, (
            f"{name} resolves via --git-common-dir; ADR-017 records the "
            "opposite decision - revise the ADR in the same change")


def test_adr_is_indexed_and_names_the_reversal():
    adr = (ROOT / "docs" / "adr" / "ADR-017-worktree-relative-hook-tools.md")
    text = adr.read_text(encoding="utf-8")
    assert "Reverses if:" in text
    index = (ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert "ADR-017-worktree-relative-hook-tools.md" in index
