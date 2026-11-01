"""RM-1297 - coaches._base_coach.load_json returns a dict, always.

load_json is annotated ``-> dict`` and documented "Returns {} on any
error", and the arena / aram / brawl coaches use its result as a dict
straight away (``cur.get(...)``, ``cur.update(...)``,
``current["k"] = ...``). The aram my_team D-class comment (coaches/
aram_coach.py, Coach._on_state_received) goes further and calls its broad
except "mechanically unreachable".

Before this fix load_json returned ``json.loads(...)`` unchecked. A JSON
array or scalar document (``[]``, ``3``, ``"x"``, ``null``, ``true``) came
back as a non-dict. The caller's ``.get`` / ``.update`` / item assignment
then raised AttributeError or TypeError, and that DID reach the
"unreachable" handlers. The fix is acceptance (a) of the filing: a non-object
document reads as {}, so the contract, the annotation and the D-class prose
are all true.

Caller audit (git grep, this cycle): every importer of load_json outside
tests/ is coaches/arena_coach.py, coaches/aram_coach.py or
coaches/brawl_coach.py, and every call loads ``self._out`` (the mode's
coaching artifact, a JSON object) and uses the result as a dict. No caller
loads a list. core/coaching_data_lock.py names load_json only in a docstring
example.

The fix keeps the line count of coaches/_base_coach.py unchanged, so the
line cites into that file from other tracked files do not move.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from coaches import _base_coach
from coaches._base_coach import load_json

REPO = Path(__file__).resolve().parents[1]
BASE = REPO / "coaches" / "_base_coach.py"

# Each of these is valid JSON but not a JSON object.
NON_OBJECT_DOCS = ("[]", "[1, 2]", '[{"a": 1}]', "3", "1.5", '"x"', "null",
                   "true", "false")


@pytest.mark.parametrize("doc", NON_OBJECT_DOCS)
def test_non_object_document_reads_as_empty_dict(tmp_path, doc):
    p = tmp_path / "artifact.json"
    p.write_bytes(doc.encode("utf-8"))
    got = load_json(p)
    assert type(got) is dict
    assert got == {}


@pytest.mark.parametrize("doc", NON_OBJECT_DOCS)
def test_caller_shape_survives_non_object_document(tmp_path, doc):
    """The exact shape the coaches use must not raise."""
    p = tmp_path / "artifact.json"
    p.write_bytes(doc.encode("utf-8"))
    cur = load_json(p)
    assert cur.get("my_team") is None
    cur["my_team"] = ["synthetic"]
    cur.update({"action": "X"})
    assert cur == {"my_team": ["synthetic"], "action": "X"}


def test_object_document_round_trips(tmp_path):
    p = tmp_path / "artifact.json"
    p.write_bytes(b'{"action": "FIGHT", "n": 2, "nested": {"k": [1]}}')
    assert load_json(p) == {"action": "FIGHT", "n": 2, "nested": {"k": [1]}}


def test_empty_object_document(tmp_path):
    p = tmp_path / "artifact.json"
    p.write_bytes(b"{}")
    got = load_json(p)
    assert type(got) is dict and got == {}


def test_missing_file_reads_as_empty_dict(tmp_path):
    got = load_json(tmp_path / "absent.json")
    assert type(got) is dict and got == {}


@pytest.mark.parametrize("raw", (b"", b"{", b"not json", b"\xff\xfe\x00"))
def test_unreadable_document_reads_as_empty_dict(tmp_path, raw):
    p = tmp_path / "artifact.json"
    p.write_bytes(raw)
    got = load_json(p)
    assert type(got) is dict and got == {}


def test_directory_path_reads_as_empty_dict(tmp_path):
    got = load_json(tmp_path)
    assert type(got) is dict and got == {}


def test_each_call_returns_a_fresh_dict(tmp_path):
    """A caller mutates the result; the next call must not see it."""
    p = tmp_path / "artifact.json"
    p.write_bytes(b"[]")
    first = load_json(p)
    first["poison"] = 1
    assert load_json(p) == {}
    assert load_json(tmp_path / "absent.json") == {}


def test_docstring_names_the_non_object_case():
    doc = _base_coach.load_json.__doc__ or ""
    assert "Returns {} on any error" in doc
    assert "non-object" in doc


def test_load_json_holds_no_raise_and_keeps_its_broad_except():
    """The D-class prose in arena / aram relies on both facts."""
    tree = ast.parse(BASE.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "load_json")
    assert not any(isinstance(n, ast.Raise) for n in ast.walk(fn))
    handlers = [n for n in ast.walk(fn) if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1
    assert isinstance(handlers[0].type, ast.Name)
    assert handlers[0].type.id == "Exception"
