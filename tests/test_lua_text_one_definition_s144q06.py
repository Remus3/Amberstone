"""RM-1091: ONE implementation of the RM-600 Lua-text rule.

RM-787 put the rule into ``lib/game_data/lua_text.py`` for the library parsers,
but ``tools/daemon_slayer_wiki_stats_extract.py`` kept its own copies of the
comment stripper, the long-bracket reader and the primary-record test, and
``tools/daemon_slayer_wiki_ability_extract.py`` imports those copies by their
private names. Two copies of a parser rule drift: they had already diverged on
the primary-record test, where the extractor's copy treats an id too long to
fit a float as "not primary" while the library copy raised OverflowError
(``int(float("inf"))``).

The stats extractor now imports the library helpers and keeps the private names
bound, so the ability extractor's import is unchanged. The guard below parses
every tracked ``*.py`` file and asserts each helper is DEFINED exactly once, in
the library; the anchor (the library definition must be found) keeps an empty
enumeration from passing.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

from lib.game_data import lua_text
from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import daemon_slayer_wiki_ability_extract as ability  # noqa: E402
import daemon_slayer_wiki_stats_extract as stats  # noqa: E402

_LIBRARY = "lib/game_data/lua_text.py"
# The helper stems; a definition matches with any leading underscores.
_HELPERS = ("strip_lua_comments", "long_bracket_level", "is_primary_record")


def _helper_definitions() -> dict[str, list[str]]:
    """``{stem: [repo-relative file, ...]}`` for every tracked def of a helper."""
    found: dict[str, list[str]] = {stem: [] for stem in _HELPERS}
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(stem in text for stem in _HELPERS):
            continue  # cheap pre-filter before the parse
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = relative_posix(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stem = node.name.lstrip("_")
                if stem in found:
                    found[stem].append(rel)
    return found


def test_each_rm600_helper_is_defined_once_in_the_library():
    found = _helper_definitions()
    for stem in _HELPERS:
        # Anchor: an empty walk would otherwise read as "no duplicates".
        assert _LIBRARY in found[stem], f"{stem}: library definition not found"
        assert found[stem] == [_LIBRARY], f"{stem} defined in {found[stem]}"


def test_stats_extractor_binds_the_library_helpers_under_its_old_names():
    assert stats._strip_lua_comments is lua_text.strip_lua_comments
    assert stats._is_primary_record is lua_text.is_primary_record


def test_ability_extractor_import_still_resolves_to_the_library_helpers():
    assert ability._strip_lua_comments is lua_text.strip_lua_comments
    assert ability._is_primary_record is lua_text.is_primary_record


def test_an_id_too_long_for_a_float_is_not_a_primary_record():
    # The extractor's old copy returned False here (its scalar parser drops a
    # non-finite value); the library copy raised OverflowError.
    block = '["id"] = ' + "9" * 400 + ', ["apiname"] = "X",'
    assert lua_text.is_primary_record(block) is False
    assert stats._is_primary_record(block) is False


def test_primary_record_rule_is_unchanged_for_ordinary_ids():
    assert lua_text.is_primary_record('["id"] = 240,') is True
    assert lua_text.is_primary_record('["id"] = 240.1,') is False
    assert lua_text.is_primary_record('["id"] = -3,') is True
    assert lua_text.is_primary_record('["id"] = 1.2.3,') is False
    assert lua_text.is_primary_record('["apiname"] = "X",') is False
