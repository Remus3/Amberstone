"""Guard (RM-998): the DS doc's archetype -> scorer claims match the dispatcher.

``docs/DAEMON_SLAYER.md`` writes the archetype -> scorer map out twice (the
substrate paragraph and the Archetype-picker Storage bullet), each time beside
``rank_for_primary_archetype()``. Both lists were accurate at 2026-10-27, but
no test read them. Three neighbouring claims were not accurate:

* The Storage bullet said "Seven canonical archetypes: ... `onhit`". The
  canonical tuple ``core/archetype_picks.py`` ``ARCHETYPES`` holds six;
  ``onhit`` is a seventh dispatch route that ``default_for_champion`` returns
  for the on-hit-AP roster, not a canonical archetype.
* The same bullet said "no dispatcher fallbacks remain (s174-s181)", and the
  ``rank_for_primary_archetype`` docstring said ``fell_back`` is "always False
  post-Phase-6". Both predate two kit-less guards: since LEDGER 907 the
  mage, assassin and enchanter branches set ``fell_back = True`` and fall
  through to ds.dps when ``_kitless_all_zero`` sees an all-zero ranking, and
  since LEDGER 931 (RM-79) the bruiser branch keeps ds.hybrid but reports
  ``fell_back=True`` when ``champion_has_ability_data`` is False.
* The ``IMPLEMENTED_SCORERS`` comment said "none fall back to ds.dps".

Every expected value is re-derived from the code's AST (the ``arch == "<x>"``
branches and the ``"scorer"`` key each one returns; the ``ARCHETYPES`` tuple),
never from a literal, so a re-routed archetype fails here instead of rotting
the prose. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_CLIENT = _REPO_ROOT / "core" / "daemon_slayer_client.py"
_PICKS = _REPO_ROOT / "core" / "archetype_picks.py"

_DISPATCHER = "rank_for_primary_archetype"
_ARROW = re.compile(r"(on-hit AP|carry|tank|bruiser|mage|assassin|enchanter) -> `?ds\.(\w+)`?")
_DOC_LABEL = {"on-hit AP": "onhit"}
_NUMBER_WORDS = {"five": 5, "six": 6, "seven": 7, "eight": 8}


def _dispatcher() -> ast.FunctionDef:
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == _DISPATCHER:
            return node
    raise AssertionError(f"{_DISPATCHER} not found in {_CLIENT.name}")


def _arch_of(test: ast.expr) -> str | None:
    if (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "arch"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and isinstance(test.comparators[0], ast.Constant)
        and isinstance(test.comparators[0].value, str)
    ):
        return test.comparators[0].value
    return None


def _scorer_keys(node: ast.AST) -> set[str]:
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Dict):
            for key, value in zip(sub.keys, sub.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "scorer"
                    and isinstance(value, ast.Constant)
                ):
                    found.add(value.value)
    return found


def _branches() -> dict[str, ast.If]:
    return {
        arch: node
        for node in _dispatcher().body
        if isinstance(node, ast.If) and (arch := _arch_of(node.test)) is not None
    }


def _code_map() -> dict[str, str]:
    mapping = {}
    for arch, node in _branches().items():
        scorers = _scorer_keys(node)
        assert len(scorers) == 1, f"branch arch == {arch!r} returns scorers {scorers}"
        mapping[arch] = scorers.pop()
    # carry is the fall-through: the dispatcher's own top-level return.
    tail = [node for node in _dispatcher().body if isinstance(node, ast.Return)]
    assert len(tail) == 1, f"expected one top-level return in {_DISPATCHER}, got {len(tail)}"
    carry = _scorer_keys(tail[0])
    assert len(carry) == 1, f"fall-through return carries scorers {carry}"
    mapping["carry"] = carry.pop()
    return mapping


def _fallback_branches() -> set[str]:
    out = set()
    for arch, node in _branches().items():
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "fell_back" for t in sub.targets)
                and isinstance(sub.value, ast.Constant)
                and sub.value.value is True
            ):
                out.add(arch)
    return out


def _flag_only_branches() -> set[str]:
    """Branches whose returned ``"fell_back"`` is computed, not the plain name."""
    out = set()
    for arch, node in _branches().items():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Dict):
                for key, value in zip(sub.keys, sub.values):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "fell_back"
                        and not isinstance(value, (ast.Name, ast.Constant))
                    ):
                        out.add(arch)
    return out


def _canonical_archetypes() -> tuple[str, ...]:
    tree = ast.parse(_PICKS.read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        )
        if isinstance(target, ast.Name) and target.id == "ARCHETYPES":
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("ARCHETYPES not found in core/archetype_picks.py")


def _doc_lines() -> list[str]:
    return _DOC.read_text(encoding="utf-8").splitlines()


def _storage_bullet() -> str:
    rows = [ln for ln in _doc_lines() if ln.startswith("- **Storage**: `core/archetype_picks.py`")]
    assert len(rows) == 1, f"expected one Storage bullet, got {len(rows)}"
    return rows[0]


def test_code_map_is_anchored():
    # An empty AST walk would make every comparison below agree with {}.
    mapping = _code_map()
    assert mapping["carry"] == "dps"
    assert len(mapping) >= 7, mapping


def test_every_doc_arrow_list_matches_the_dispatcher():
    expected = _code_map()
    sites = [ln for ln in _doc_lines() if f"{_DISPATCHER}()" in ln and _ARROW.search(ln)]
    assert len(sites) >= 2, f"expected the two archetype -> scorer lists, found {len(sites)}"
    for line in sites:
        doc_map = {_DOC_LABEL.get(a, a): s for a, s in _ARROW.findall(line)}
        assert doc_map == expected, f"doc arrow list {doc_map} != dispatcher {expected}"


def test_canonical_archetype_sentence_matches_the_tuple():
    canonical = _canonical_archetypes()
    match = re.search(r"(\w+) canonical archetypes in `ARCHETYPES`: ((?:`\w+`(?:, )?)+)", _storage_bullet())
    assert match, "Storage bullet no longer states 'N canonical archetypes in `ARCHETYPES`: ...'"
    assert _NUMBER_WORDS[match.group(1).lower()] == len(canonical)
    assert re.findall(r"`(\w+)`", match.group(2)) == list(canonical)


def test_onhit_is_a_route_not_a_canonical_archetype():
    assert "onhit" in _code_map()
    assert "onhit" not in _canonical_archetypes()
    src = _PICKS.read_text(encoding="utf-8")
    assert 'return ("onhit",' in src, "default_for_champion no longer returns the onhit route"
    assert "`default_for_champion` returns" in _storage_bullet()


def test_doc_records_the_kitless_fallback():
    fallbacks = _fallback_branches()
    assert fallbacks, "no arch branch sets fell_back = True; re-measure the fallback claim"
    assert "_kitless_all_zero" in _CLIENT.read_text(encoding="utf-8")
    bullet = _storage_bullet()
    assert "no dispatcher fallbacks remain" not in bullet
    assert "`_kitless_all_zero`" in bullet and "`fell_back=True`" in bullet
    match = re.search(r"kit-less guard: ([a-z /]+) serve", bullet)
    assert match, "Storage bullet no longer names the kit-less fallback branches"
    assert set(match.group(1).split(" / ")) == fallbacks


def test_doc_records_the_flag_only_kitless_branch():
    flagged = _flag_only_branches()
    assert flagged, "no branch computes its fell_back flag; re-measure the bruiser claim"
    assert "champion_has_ability_data(champion)" in _CLIENT.read_text(encoding="utf-8")
    bullet = _storage_bullet()
    for arch in flagged:
        assert f"{arch} keeps its ds.{_code_map()[arch]} build but also reports `fell_back=True`" in bullet
    assert "`champion_has_ability_data`" in bullet
    # The bruiser flag landed in LEDGER 931 (RM-79, eb5a520d0), not with the
    # LEDGER 907 fall-through; LEDGER 907 itself called ds.hybrid self-protecting.
    assert "is False (LEDGER 931, RM-79)" in bullet


def test_dispatcher_docstring_does_not_say_fell_back_is_always_false():
    doc = ast.get_docstring(_dispatcher()) or ""
    assert "always False" not in doc
    assert "all 7 archetype branches return" not in doc
    assert "kit-less" in doc


def test_implemented_scorers_comment_admits_the_kitless_fallback():
    src = _PICKS.read_text(encoding="utf-8")
    assert "none fall back to ds.dps." not in src


def test_touched_files_are_ascii():
    for path in (_DOC, _CLIENT, _PICKS, Path(__file__)):
        data = path.read_bytes()
        assert data.isascii(), f"{path.name} has non-ASCII bytes"
        assert b"\r" not in data, f"{path.name} has CR bytes"
