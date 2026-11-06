"""Guard: the champion-info override test cites its consumers by symbol (RM-1053).

Measured 2026-10-31 at ENGINE 1.290.0. tests/test_champion_info_overrides.py
(written 2026-07-28 at 0d5cada95) carried 21 ``<file>.py:<n>`` cite lines
naming the three live consumers of the DDragon attack / magic polarity rule,
in its module docstring, two helper docstrings, three test docstrings and
four assertion messages:

- dashboard/routes_dictionary.py ``:101`` / ``:99-100`` / ``:99-101`` /
  ``:91-98`` - ``_damage_profile_tag``: its final ``attack >= magic``
  return, the ``attack == 0 and magic == 0`` tag fallback, and the
  ``_HARD_CC_NAMES`` / ``_BURST_NAMES`` short-circuit. Still exact.
- dashboard/routes_pickban.py ``:218`` (the ``_cio.merged_info`` call in
  ``_load_champ_id_to_info``) and ``:255-260`` (the per-champ lean rule in
  ``_compute_team_damage_mix``). Exact when written; now 19 lines lower.
- core/build_planner/fed_threat.py ``:147-151`` (the final comparison in
  ``_champ_axis``) and ``:139-151`` (its try body). Exact when written;
  now 60 lines lower.

The tests below ratchet the file to zero line cites, pin the symbol cites,
re-derive every restated consumer claim by AST, and confirm the original
cites were exact at the authoring commit.
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_PY_LINE = re.compile(r"(?<![\w./])[\w/]+\.py:\s?\d")
_PROSE_LINE = re.compile(r"\blines? ~?\d{2,}")

TARGET = "tests/test_champion_info_overrides.py"
DICT = "dashboard/routes_dictionary.py"
PICKBAN = "dashboard/routes_pickban.py"
FED = "core/build_planner/fed_threat.py"
AUTHORED_SHA = "0d5cada95"

NEEDLES = (
    "  * dashboard.routes_dictionary._damage_profile_tag, final return",
    "  * dashboard.routes_pickban._compute_team_damage_mix, per-champ lean",
    '    TIE -> "EVEN". Fed by routes_pickban._load_champ_id_to_info, which',
    "  * core.build_planner.fed_threat._champ_axis, final comparison",
    "    live consumers agree (routes_dictionary._damage_profile_tag,",
    'f"routes_dictionary._damage_profile_tag prints AD on the tie while "',
    '"routes_dictionary._damage_profile_tag no longer resolves a tie to AD"',
    '"routes_pickban._compute_team_damage_mix no longer reports EVEN on a tie"',
    '"fed_threat._champ_axis no longer reports unknown on a tie"',
)


def _text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _func(rel: str, name: str) -> ast.FunctionDef:
    for node in ast.parse(_text(rel)).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not defined at top level of {rel}")


def _src(rel: str, name: str) -> str:
    return ast.unparse(_func(rel, name))


def test_patterns_match_the_rotted_shapes():
    for sample in (
        "  * dashboard/routes_dictionary.py:101",
        '    TIE -> "AD". Two things run BEFORE it: routes_dictionary.py:91-98',
        '    TIE -> "EVEN". Fed by routes_pickban.py:218, which merges first.',
        '        (fed_threat.py:139-151)."""',
        '            "routes_pickban.py:255-260 no longer reports EVEN on a tie")',
    ):
        assert _PY_LINE.search(sample), sample
    for needle in NEEDLES:
        assert not _PY_LINE.search(needle), needle
        assert not _PROSE_LINE.search(needle), needle


def test_target_cites_by_symbol():
    text = _text(TARGET)
    hits = [
        i for i, line in enumerate(text.splitlines(), 1)
        if _PY_LINE.search(line) or _PROSE_LINE.search(line)
    ]
    assert hits == [], hits
    for needle in NEEDLES:
        assert needle in text, needle


def test_dictionary_tag_has_the_three_cited_branches():
    func = _func(DICT, "_damage_profile_tag")
    src = ast.unparse(func)
    assert "_HARD_CC_NAMES" in src and "_BURST_NAMES" in src
    assert "if attack == 0 and magic == 0:" in src
    last = func.body[-1]
    assert isinstance(last, ast.Return)
    assert ast.unparse(last) == "return 'AD' if attack >= magic else 'AP'"


def test_pickban_mix_merges_in_its_loader_and_leans_even_on_a_tie():
    loader = _src(PICKBAN, "_load_champ_id_to_info")
    assert "_cio.merged_info(entry.get('name'), info)" in loader
    mix = _src(PICKBAN, "_compute_team_damage_mix")
    assert "_load_champ_id_to_info()" in mix
    assert ("if attack > magic:\n            lean = 'AD'\n"
            "        elif magic > attack:\n            lean = 'AP'\n"
            "        else:\n            lean = 'EVEN'") in mix


def test_fed_threat_axis_merges_and_returns_empty_on_a_tie():
    src = _src(FED, "_champ_axis")
    assert "merged_info(name.strip(), info)" in src
    assert ("if attack > magic:\n            return 'ad'\n"
            "        if magic > attack:\n            return 'ap'\n"
            "        return ''") in src


def _at(sha: str, rel: str) -> list[str] | None:
    out = subprocess.run(
        ["git", "show", f"{sha}:{rel}"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if out.returncode != 0:
        return None
    return out.stdout.splitlines()


def test_original_cites_were_exact_at_the_authoring_commit():
    dict_lines = _at(AUTHORED_SHA, DICT)
    if dict_lines is None:
        return  # shallow clone without that commit: the live halves above still run
    assert dict_lines[100].strip() == 'return "AD" if attack >= magic else "AP"'
    assert dict_lines[98].strip() == "if attack == 0 and magic == 0:"
    assert "_HARD_CC_NAMES" in dict_lines[90]
    assert dict_lines[97].strip() == 'return "BURST"'
    pick = _at(AUTHORED_SHA, PICKBAN)
    assert pick is not None
    assert "_cio.merged_info(" in pick[217]
    assert [ln.strip() for ln in pick[254:260]] == [
        "if attack > magic:", 'lean = "AD"', "elif magic > attack:",
        'lean = "AP"', "else:", 'lean = "EVEN"',
    ]
    fed = _at(AUTHORED_SHA, FED)
    assert fed is not None
    assert "import merged_info" in fed[138]
    assert [ln.strip() for ln in fed[146:151]] == [
        "if attack > magic:", 'return "ad"', "if magic > attack:",
        'return "ap"', 'return ""',
    ]
