"""
tests/_css_split.py - read a split stylesheet as ONE text (RM-726 (c),
docs/WEB_CSS_SPLIT_PLAN.md rule 5, READERS FIRST).

The plan cuts web/css/panels/header.css (and later champ_select_view.css)
into contiguous pieces. Each piece is @imported in web/css/dashboard.css
right after its source, so the browser still reads the same rules in the
same order. A test that reads the source as text must read the whole
family the same way, or a presence check fails with a misleading message
and an absence check passes while it checks nothing.

family_paths(rel) returns the source plus every LANDED target of the plan
slices whose File is `rel`, ordered by dashboard.css @import order (the
cascade order). A target is landed when its file exists. family_text(rel)
joins those files' text with nothing in between: plan rule 2 says the
source plus its targets, joined in import order, equal the old source.

Fails loudly (AssertionError) instead of reading less than the family: a
missing source, a missing plan, a landed target dashboard.css does not
import, or one imported before its source.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests._repo_walk import REPO_ROOT

PLAN_REL = "docs/WEB_CSS_SPLIT_PLAN.md"
DASHBOARD_REL = "web/css/dashboard.css"
PANELS_REL = "web/css/panels"

_HEAD = re.compile(r"^### [A-Z]+-\d+\b.*$", re.MULTILINE)
_FILE = re.compile(r"^- File:\s*`([^`]+)`", re.MULTILINE)
_TARGET = re.compile(r"^- Target:\s*`([^`]+)`", re.MULTILINE)
_IMPORT = re.compile(r"""^@import\s+['"]\./([^'"]+)['"]\s*;""", re.MULTILINE)


def planned_targets(rel: str, root: Path = REPO_ROOT) -> list[str]:
    """Target file names (bare, under web/css/panels/) of every plan slice
    whose File is `rel`, in plan order."""
    plan = root / PLAN_REL
    assert plan.is_file(), (
        f"{PLAN_REL} is missing; tests/_css_split.py reads the split "
        "targets from it (re-point this helper if the plan moved)")
    text = plan.read_text(encoding="utf-8")
    heads = list(_HEAD.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        nxt = text.find("\n## ", m.end(), end)
        body = text[m.end():end if nxt == -1 else nxt]
        f, t = _FILE.search(body), _TARGET.search(body)
        if f and t and f.group(1) == rel:
            out.append(t.group(1))
    return out


def family_paths(rel: str, root: Path = REPO_ROOT) -> list[Path]:
    """The source, then its landed targets in dashboard.css import order."""
    src = root / rel
    assert src.is_file(), f"premise: {rel} exists"
    landed = [n for n in planned_targets(rel, root)
              if (root / PANELS_REL / n).is_file()]
    if not landed:
        return [src]
    css = (root / DASHBOARD_REL).read_text(encoding="utf-8")
    imports = ["web/css/" + m for m in _IMPORT.findall(css)]
    assert rel in imports, f"{DASHBOARD_REL} does not import {rel}"
    at = imports.index(rel)
    order = {}
    for name in landed:
        tgt = f"{PANELS_REL}/{name}"
        assert tgt in imports, (
            f"{tgt} exists (a landed {rel} slice) but {DASHBOARD_REL} "
            "does not import it")
        i = imports.index(tgt)
        assert i > at, (
            f"{DASHBOARD_REL} imports {tgt} before its source {rel}; "
            "the cascade order is broken")
        order[name] = i
    return [src] + [root / PANELS_REL / n
                    for n in sorted(landed, key=order.__getitem__)]


def family_text(rel: str, root: Path = REPO_ROOT) -> str:
    """The family's text, joined in cascade order (see family_paths)."""
    return "".join(p.read_text(encoding="utf-8")
                   for p in family_paths(rel, root))
