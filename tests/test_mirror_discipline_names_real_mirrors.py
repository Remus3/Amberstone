"""A skill doc's "Mirror discipline" section names only mirrors that are checked.

WHY THIS EXISTS
---------------
`tools/ship-batch.md` and `tools/test-first-autopilot.md` each said a gitignored
`.claude/skills/<name>/SKILL.md` was a byte-identical mirror of the tracked doc.
That copy has not existed since 2026-05-28 (the main checkout's `.claude/skills/`
is empty), and nothing re-mirrored or compared it, so the doc told every reader
to keep a file in step that no tool checks (RM-856). The one mirror that IS real
is `.claude/commands/<name>.md`, and it is checked by `tools/drift_guard.py`
`MIRROR_PAIRS` (`("tools", ".claude/commands")`), which compares same-basename
`.md` content at every /done.

The rule this pins: a "Mirror discipline" section may name a `.claude/<dir>/`
mirror only when `<dir>` is a `MIRROR_PAIRS` destination, and it must say the
mirror is checked by `tools/drift_guard.py`. `MIRROR_PAIRS` is read from the
guard's source with `ast` (importing the guard would run its module-level
project lookups).

Universe: tracked `tools/*.md` from the git index; the two known carriers are
anchored by name so an empty enumeration cannot pass.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_GUARD = _REPO / "tools" / "drift_guard.py"
_HEADING = "## Mirror discipline"
_KNOWN = ("tools/ship-batch.md", "tools/test-first-autopilot.md")
_CLAUDE_DIR = re.compile(r"\.claude/([A-Za-z0-9_-]+)/")


def _mirror_destinations() -> set[str]:
    tree = ast.parse(_GUARD.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "MIRROR_PAIRS" for t in node.targets
        ):
            pairs = ast.literal_eval(node.value)
            return {dst for _src, dst in pairs}
    raise AssertionError("MIRROR_PAIRS not found in tools/drift_guard.py")


def _tracked_tool_docs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", "tools/*.md"],
        cwd=_REPO, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.splitlines() if p]


def _section(text: str) -> str | None:
    if _HEADING not in text:
        return None
    body = text.split(_HEADING, 1)[1]
    nxt = re.search(r"^## ", body, flags=re.MULTILINE)
    return body[: nxt.start()] if nxt else body


def _carriers() -> dict[str, str]:
    out = {}
    for rel in _tracked_tool_docs():
        sec = _section((_REPO / rel).read_text(encoding="utf-8"))
        if sec is not None:
            out[rel] = sec
    return out


def test_destinations_are_read_from_the_guard() -> None:
    assert ".claude/commands" in _mirror_destinations()


def test_known_carriers_are_enumerated() -> None:
    found = _carriers()
    for rel in _KNOWN:
        assert rel in found, f"{rel} lost its {_HEADING!r} section"


@pytest.mark.parametrize("rel", sorted(_carriers()))
def test_section_names_only_checked_mirrors(rel: str) -> None:
    sec = _carriers()[rel]
    allowed = {d.split("/", 1)[1] for d in _mirror_destinations()
               if d.startswith(".claude/")}
    named = set(_CLAUDE_DIR.findall(sec))
    assert named, f"{rel}: {_HEADING!r} names no .claude/ mirror"
    stray = sorted(named - allowed)
    assert not stray, (
        f"{rel}: {_HEADING!r} names .claude/{stray} as a mirror, but "
        f"tools/drift_guard.py MIRROR_PAIRS checks only {sorted(allowed)}; "
        "name only mirrors a tool compares (RM-856)"
    )


@pytest.mark.parametrize("rel", sorted(_carriers()))
def test_section_says_how_the_mirror_is_checked(rel: str) -> None:
    sec = " ".join(_carriers()[rel].split())
    assert "tools/drift_guard.py" in sec, (
        f"{rel}: {_HEADING!r} must say the mirror is checked by "
        "tools/drift_guard.py (MIRROR_PAIRS)"
    )
