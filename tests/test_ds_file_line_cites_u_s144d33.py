"""Guard: abilities, the wiki form registry and passive overrides cite by
symbol (u).

Measured 2026-10-30 at ENGINE 1.290.0. Four line cites in three DS modules
had drifted (three point at unrelated code; the extractor range is one line
off and still spans the two constants):

- ``abilities.py`` cited ``tools/ds_wiki_staleness_check.py:454-455`` for
  the dict literal that writes ``_patch`` and ``_generated_at`` together
  (that range is now the tail of ``_ratio_term``; the literal is the
  ``report`` dict in ``run``).
- ``_ability_wiki_form_damage.py`` cited
  ``tools/daemon_slayer_wiki_ability_extract.py:108-110`` for the wiki host
  and endpoint (line 108 is now a comment; the values are ``WIKI_HOST``
  and ``WIKI_API``).
- ``_passive_damage_overrides.py`` cited ``dps.py:1195`` for the AA-routing
  consumer (now an HP-scaled AP amp line; the consumer is the
  ``apply_passive_damage`` block of ``dps.compute_dps``), and its own
  ``:1041-1051`` for the v1 routing note (now K'Sante prose; the note sits
  above ``_AA_ROUTED_ON_HIT_KEYS``).

The tests below pin the cites, and the facts they restated, by symbol.
"""
from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import dps

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
TOOLS = REPO / "tools"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|(?<![\w.]):\d|\blines? \d")
# Guard s's strip, plus the in-game "1%:2%" level-ratio notation.
_NOT_A_CITE = re.compile(r"\[:\d+\]|(?<!\w):8860\b|%:\d+%")

TARGETS = {
    "abilities.py": (
        "tools/ds_wiki_staleness_check.py ``run`` writes ``_patch`` and "
        "``_generated_at`` into the SAME dict literal",
    ),
    "_ability_wiki_form_damage.py": (
        "``tools/daemon_slayer_wiki_ability_extract.py`` builds as "
        "``WIKI_API`` from ``WIKI_HOST``",
    ),
    "_passive_damage_overrides.py": (
        "the AA-routing consumer (the ``apply_passive_damage`` block of "
        "``dps.compute_dps``) evaluates",
        "scope as the v1 routing note above ``_AA_ROUTED_ON_HIT_KEYS``).",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_pattern_matches_the_old_shapes():
    for sample in (
        "# tools/ds_wiki_staleness_check.py:454-455 writes ``_patch`` and",
        "endpoint ``tools/daemon_slayer_wiki_ability_extract.py:108-110``",
        "# the scorer's L13 target): the AA-routing consumer (dps.py:1195)",
        "# scope as the :1041-1051 v1 routing note).",
    ):
        assert _LINE_CITE.search(_NOT_A_CITE.sub("", sample)), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


def test_strip_drops_only_the_level_ratio():
    assert not _LINE_CITE.search(
        _NOT_A_CITE.sub("", "Renata P Leverage (1%:2% level"))
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "see 1%:2% and :1041"))
    assert _LINE_CITE.search(_NOT_A_CITE.sub("", "see dps.py:1195"))


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(_NOT_A_CITE.sub("", line))
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_staleness_run_stamps_patch_and_generated_at_in_one_literal():
    tree = _tree(TOOLS / "ds_wiki_staleness_check.py")
    run = next(n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "run")
    keysets = [
        {k.value for k in node.keys if isinstance(k, ast.Constant)}
        for node in ast.walk(run) if isinstance(node, ast.Dict)
    ]
    assert any({"_patch", "_generated_at"} <= ks for ks in keysets)


def test_extractor_builds_wiki_api_from_wiki_host():
    tree = _tree(TOOLS / "daemon_slayer_wiki_ability_extract.py")
    assigns = {
        t.id: node.value
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Name)
    }
    assert ast.literal_eval(assigns["WIKI_HOST"]) == (
        "https://wiki.leagueoflegends.com")
    assert ast.unparse(assigns["WIKI_API"]) == (
        "WIKI_HOST + '/en-us/api.php'")


def test_compute_dps_routes_the_entry_at_the_p_rank():
    src = inspect.getsource(dps.compute_dps)
    assert "if apply_passive_damage:" in src
    assert "aa_routed_on_hit_entry(resolved.champion_id)" in src
    assert re.search(
        r'_evaluate_block\(_pblock, _rank_at_level\("P", level\), _pctx\)',
        src)


def test_v1_routing_note_sits_above_the_allowlist():
    lines = (DS / "_passive_damage_overrides.py").read_text(
        encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines)
              if line.startswith("_AA_ROUTED_ON_HIT_KEYS"))
    block = []
    for line in reversed(lines[:at]):
        if not line.startswith("#"):
            break
        block.append(line)
    note = _flat("\n".join(reversed(block)))
    assert "v1 routes ONLY the verified every-AA on_hit passives" in note
