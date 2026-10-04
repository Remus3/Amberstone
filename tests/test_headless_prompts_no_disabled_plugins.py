"""Guard: headless prompt files never name the Firecrawl plugin.

MAIN note 2026-10-03 0850 (operator order) disabled ten plugins at user scope,
firecrawl among them, and ordered every tree to drop any prompt line that names
one of their tools. RC's headless prompts named Firecrawl as optional research
tooling (directed-headless-upgrade, headless-research, headless-upgrade); those
lines now point at the built-in WebFetch / WebSearch instead.

Universe: `tools/*headless*.md` is the TRACKED source of the headless slash
commands; `.claude/commands/*headless*.md` is a gitignored byte mirror
(`tools/drift_guard.py` MIRROR_PAIRS) that a worktree or fresh clone does not
carry. Both are scanned when present; the tracked half is anchored so an empty
enumeration cannot pass.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_TRACKED = _REPO / "tools"
_MIRROR = _REPO / ".claude" / "commands"

# Prompts known to exist at the time of writing; anchors the enumeration.
_ANCHORS = {
    "directed-headless-upgrade.md",
    "headless-research.md",
    "headless-upgrade.md",
}

_BANNED = re.compile(r"firecrawl", re.IGNORECASE)


def _prompt_files() -> list[Path]:
    files = sorted(_TRACKED.glob("*headless*.md"))
    if _MIRROR.is_dir():
        files += sorted(_MIRROR.glob("*headless*.md"))
    return files


def test_enumeration_is_anchored():
    names = {p.name for p in _TRACKED.glob("*headless*.md")}
    missing = _ANCHORS - names
    assert not missing, f"anchor prompt files missing from tools/: {sorted(missing)}"


def test_headless_prompts_do_not_name_firecrawl():
    hits = []
    for path in _prompt_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _BANNED.search(line):
                hits.append(f"{path.relative_to(_REPO)}:{lineno}")
    assert not hits, f"headless prompt names the disabled firecrawl plugin: {hits}"


def test_pattern_catches_a_planted_mention():
    # Positive control: the banned pattern must match the forms that shipped.
    for sample in ("Firecrawl", "`firecrawl-scrape`", "FIRECRAWL"):
        assert _BANNED.search(sample)
