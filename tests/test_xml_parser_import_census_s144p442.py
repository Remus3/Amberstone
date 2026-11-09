"""S144-P-442 - the one production module that can parse XML is named, and it reads an operator-local file.

ruff S314 ("use defusedxml") reports exactly two lines over the whole production tree, both in
``core/pro_match_index.py``. Nothing pinned that count: a NEW module that copied ``ET.fromstring`` onto
a network response (an RSS feed, a SOAP-ish reply, a downloaded manifest) would carry the stdlib
parser's entity-expansion and external-reference exposure with no guard noticing, and the existing
bug-class bundle ratchet only covers S313 (the removed ``cElementTree`` spelling).

Measured 2026-11-08 over every tracked, non-test ``.py``: ONE file imports an XML parser,
``core/pro_match_index.py``. It opens the operator's own ``Played with Pro List.xlsx`` as a zip and
parses two parts of it; the module says "Unwired" in its own docstring and is pinned test-only by
``tests/test_test_only_modules_baseline_s144p233.py`` (RM-1732), so no live path feeds it. ``core/operator_notify.py`` imports ``xml.sax.saxutils`` for ``escape`` / ``quoteattr``
only (it BUILDS toast XML, never parses), so that submodule is not a parser import here.

A parser import is any import of ``xml.etree``, ``xml.dom``, ``xml.parsers``, ``xml.sax`` (other than
``xml.sax.saxutils``), ``xmlrpc`` (its client parses server replies with expat), ``lxml`` or
``xmltodict``. ``defusedxml`` is the hardened family the rule asks
for: importing it is allowed anywhere and is not counted. Per census file the number of import
statements is pinned EXACTLY, and a file outside the census must carry none.

Named blind spots: an import spelled through ``importlib`` / ``__import__`` is invisible to an AST
read (``tests/test_dynamic_load_census_s144p342.py`` covers dynamic loads), and a census row proves
where a parser is imported, not that its input is trusted - the row's reason is the operator's claim,
read it before extending it.

Excluded from the scan: test code (``tests/``, any ``tests`` directory, ``test_*.py``, ``conftest.py``)
and ``ops/fleet_kit/`` (vendored byte-for-byte, pinned by its MANIFEST).
"""
from __future__ import annotations

import ast

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

# file -> (parser import statements, where the XML comes from). Exact: a new import, or a removed one,
# fails until the row is updated.
_CENSUS: dict[str, tuple[int, str]] = {
    "core/pro_match_index.py": (
        1,
        "two parts of the operator's own local .xlsx (a zip on the operator's Desktop); unwired module, "
        "no network or third-party input",
    ),
}

_PARSER_PREFIXES = ("xml.etree", "xml.dom", "xml.parsers", "lxml")
_PARSER_ROOTS = ("xmltodict", "xmlrpc")
# Submodules of a parser package that only WRITE XML.
_WRITE_ONLY = ("xml.sax.saxutils",)
_SKIP_DIRS = ("ops/fleet_kit/",)


def _is_parser_module(name: str) -> bool:
    if not name:
        return False
    if name in _WRITE_ONLY or name.startswith(tuple(w + "." for w in _WRITE_ONLY)):
        return False
    if name == "xml.sax" or name.startswith("xml.sax."):
        return True
    root = name.split(".", maxsplit=1)[0]
    if root in _PARSER_ROOTS or root == "lxml":
        return True
    return any(name == p or name.startswith(p + ".") for p in _PARSER_PREFIXES)


def _parser_imports(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            n += sum(1 for a in node.names if _is_parser_module(a.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "xml":
                # `from xml import etree` / `from xml import dom, sax` name the submodule in the alias.
                n += sum(1 for a in node.names if _is_parser_module("xml." + a.name))
            elif _is_parser_module(node.module):
                n += 1
    return n


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts[:-1] or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def _scan() -> tuple[dict[str, int], int]:
    self_check()
    found: dict[str, int] = {}
    scanned = 0
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if _is_test_path(rel) or rel.startswith(_SKIP_DIRS):
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        n = _parser_imports(tree)
        if n:
            found[rel] = n
    return found, scanned


def test_the_walk_is_not_vacuous():
    found, scanned = _scan()
    assert scanned > 300, f"scan reached only {scanned} production files"
    # A census that matched nothing would also read as "no new parser": anchor it on the known one.
    assert "core/pro_match_index.py" in found


def test_the_census_is_exact():
    found, _scanned = _scan()
    expected = {rel: n for rel, (n, _why) in _CENSUS.items()}
    new = {rel: n for rel, n in found.items() if rel not in expected}
    gone = sorted(rel for rel in expected if rel not in found)
    moved = {rel: (found[rel], expected[rel]) for rel in expected if rel in found and found[rel] != expected[rel]}
    assert not new, (
        f"production code that imports an XML parser and is not in the census: {new}. Input from the "
        "network or any third party goes through defusedxml; an operator-local file gets a row with its reason."
    )
    assert not gone, f"census rows whose file no longer imports an XML parser, drop them: {gone}"
    assert not moved, f"XML parser import count changed (found, pinned): {moved}"


def test_every_census_row_states_its_input():
    for rel, (n, why) in _CENSUS.items():
        assert n >= 1 and why.strip(), rel


def test_the_writer_only_import_is_still_the_only_xml_use_outside_the_census():
    """operator_notify builds toast XML with xml.sax.saxutils; it must stay a non-parser in this census."""
    text = (REPO_ROOT / "core" / "operator_notify.py").read_text(encoding="utf-8")
    assert "from xml.sax.saxutils import escape, quoteattr" in text
    assert _parser_imports(ast.parse(text)) == 0


# -- the detector bites ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("src, want", [
    ("import xml.etree.ElementTree as ET\n", 1),
    ("from xml.etree import ElementTree\n", 1),
    ("from xml.etree.ElementTree import fromstring\n", 1),
    ("import xml.dom.minidom\n", 1),
    ("from xml import etree\n", 1),
    ("from xml import dom, sax\n", 2),
    ("import xml.sax\n", 1),
    ("from xml.sax import make_parser\n", 1),
    ("import xml.parsers.expat\n", 1),
    ("from lxml import etree\n", 1),
    ("import xmltodict\n", 1),
    ("import xml.etree.ElementTree as A, xml.dom.minidom as B\n", 2),
    ("from xml.sax.saxutils import escape, quoteattr\n", 0),
    ("import xml.sax.saxutils\n", 0),
    ("import defusedxml.ElementTree\n", 0),
    ("from defusedxml import minidom\n", 0),
    ("import xmlrpc.client\n", 1),
    ("import xmlrpcx\n", 0),
    ("from . import xml\n", 0),
])
def test_the_import_detector_counts_each_spelling(src, want):
    assert _parser_imports(ast.parse(src)) == want
