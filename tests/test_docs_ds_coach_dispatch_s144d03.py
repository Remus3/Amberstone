"""Guard (RM-956): the DS doc's coach-wiring sections stay true.

``docs/DAEMON_SLAYER.md`` carried three stale claims about how the coaches
reach the engine, measured 2026-10-27:

* "DS-before-Haiku pattern" showed every coach calling
  ``_ds_client.rank_for(...)`` and reading ``r.delta_dps`` off the rows, but
  s182 (2026-05-13) swapped all four mode coaches to
  ``coach_integration.archetype_dispatch.dispatch_for_coach``, which routes
  through the champion's archetype scorer; no coach calls ``rank_for`` any
  more;
* "Coach integration status" named ``coach_integration.py`` (SR), which is a
  package now: the SR coach is ``coach_integration/_coach.py``;
* "Changelog" pointed new ENGINE entries at ``Share/CHANGELOG.md``, but the
  ``Share/`` mirror was removed on 2026-09-07 (7c0ff1624).

The sample is parsed and checked against the real dispatcher signature and
result fields, every coach in the table must call the dispatcher before its
first Haiku call, and every backticked path in the three sections must exist.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from pathlib import Path

from coach_integration import archetype_dispatch
from tests._repo_walk import tracked_relpaths

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"

_PATTERN = "## DS-before-Haiku pattern"
_TABLE = "## Coach integration status"
_CHANGELOG = "## Changelog"

_COACHES = (
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "coaches/brawl_coach.py",
    "coach_integration/_coach.py",
)

_PATH = re.compile(r"`([A-Za-z0-9_./-]+/[A-Za-z0-9_.-]+\.(?:py|md|json))`")


def _section(heading: str) -> str:
    text = _DOC.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def _sample() -> ast.Module:
    body = _section(_PATTERN)
    m = re.search(r"```python\n(.*?)```", body, re.S)
    assert m, "DS-before-Haiku section lost its python sample"
    return ast.parse(m.group(1))


def _calls(tree: ast.Module, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if fname == name:
                out.append(node)
    return out


def test_sample_calls_the_dispatcher_not_rank_for():
    tree = _sample()
    assert _calls(tree, "dispatch_for_coach"), "sample must call dispatch_for_coach"
    assert not _calls(tree, "rank_for"), "coaches stopped calling rank_for in s182"


def test_sample_keywords_exist_on_the_dispatcher():
    params = inspect.signature(archetype_dispatch.dispatch_for_coach).parameters
    for call in _calls(_sample(), "dispatch_for_coach"):
        for kw in call.keywords:
            assert kw.arg in params, f"dispatch_for_coach has no {kw.arg!r} parameter"


def test_sample_reads_only_real_result_fields():
    fields = {f.name for f in dataclasses.fields(archetype_dispatch.CoachDispatchResult)}
    tree = _sample()
    targets = {
        t.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and _calls(ast.Module(body=[ast.Expr(node.value)], type_ignores=[]), "dispatch_for_coach")
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert targets, "sample must bind the dispatch result to a name"
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in targets
    }
    assert read, "sample must read a field off the dispatch result"
    assert read <= fields, f"not CoachDispatchResult fields: {sorted(read - fields)}"
    for call in _calls(tree, "display_label"):
        assert hasattr(archetype_dispatch, "display_label")
        assert len(call.args) == 1


def test_sample_names_the_shipped_comment_contract():
    body = _section(_PATTERN)
    assert "dispatch_for_coach()" in body
    assert "daemon_slayer_picks" in body
    assert "rank_for()` must run" not in body
    # The post-Haiku reuse sits in a comment, so ast never sees it.
    fields = {f.name for f in dataclasses.fields(archetype_dispatch.CoachDispatchResult)}
    reused = re.findall(r'cur\["daemon_slayer_picks"\] = _ds_dispatch\.(\w+)', body)
    assert reused and set(reused) <= fields, f"post-Haiku reuse reads {reused}"


def test_every_coach_dispatches_before_its_first_haiku_call():
    for rel in _COACHES:
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        create = src.find("self._client.messages.create(")
        dispatch = src.find("dispatch_for_coach(")
        assert create >= 0, f"{rel}: no Haiku call found"
        assert 0 <= dispatch < create, f"{rel}: DS dispatch is not before the Haiku call"
        assert "rank_for(" not in src.replace("rank_for()", ""), f"{rel}: still calls rank_for"


def test_table_names_every_coach_and_no_retired_module():
    table = _section(_TABLE)
    for rel in _COACHES:
        assert f"`{rel}`" in table, f"coach table must name {rel}"
    assert "`coach_integration.py`" not in table, "coach_integration is a package"


def test_changelog_section_cites_no_retired_share_mirror():
    body = _section(_CHANGELOG)
    assert "Share/CHANGELOG.md" not in body
    # The mirror's removal is a fact about the git INDEX, not the disk: a
    # checkout made before 2026-09-07 keeps an ignored, untracked Share/ folder
    # (build caches, logs), so a filesystem check is red there and green in a
    # fresh worktree for the same tree (s144 L3 merger).
    tracked = tracked_relpaths()
    assert tracked is not None, "git index unreadable; the check would pass empty"
    assert "docs/DAEMON_SLAYER.md" in tracked, "index enumeration lost its anchor"
    assert not [p for p in tracked if p.startswith("Share/")]


def test_every_cited_path_in_the_three_sections_exists():
    seen = 0
    for heading in (_PATTERN, _TABLE, _CHANGELOG):
        for m in _PATH.finditer(_section(heading)):
            seen += 1
            assert (_REPO_ROOT / m.group(1)).exists(), f"{heading}: missing {m.group(1)}"
    assert seen >= 6, "path citations vanished; the guard would pass empty"


def test_doc_is_ascii():
    assert _DOC.read_bytes().isascii()
