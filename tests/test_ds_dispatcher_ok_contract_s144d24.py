"""Guard (RM-1000): ``rank_for_primary_archetype`` never returns ``ok=False``.

The dispatcher docstring in ``core/daemon_slayer_client.py`` said "``ok=False``
means the engine was unreachable" and typed the key as ``"ok": bool``. No
path builds that dict: every branch does ``if rows is None: return None`` and
every dict it returns carries ``"ok": True``. The ``None`` is also wider than
"unreachable": ``_post_json`` collapses a timeout, a refused connection, ANY
HTTP error status and a non-JSON body into the same ``None``.
``docs/DAEMON_SLAYER.md`` (the Dispatch bullet) gave the return shape without
the ``None`` at all. Every caller already tests ``out is None``
(``coach_integration/archetype_dispatch.py``, ``core/archetype_mismatch.py``),
so the docs, not the code, were wrong.

The AST half re-derives the contract from the function body; the behaviour
half drives each branch with ``_post_json`` stubbed or ``urlopen`` raising, so
it never touches the live :8860 server. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import io
from pathlib import Path
from urllib.error import HTTPError

import pytest

from core import daemon_slayer_client as ds

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_CLIENT = _REPO_ROOT / "core" / "daemon_slayer_client.py"
_DISPATCHER = "rank_for_primary_archetype"
_ARCHETYPES = ("carry", "tank", "bruiser", "mage", "assassin", "enchanter", "onhit", "")


def _dispatcher() -> ast.FunctionDef:
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == _DISPATCHER:
            return node
    raise AssertionError(f"{_DISPATCHER} not found in {_CLIENT.name}")


def _returns(fn: ast.FunctionDef) -> list[ast.Return]:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Return)]


def _ok_value(node: ast.Dict) -> object:
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and key.value == "ok":
            assert isinstance(value, ast.Constant), ast.unparse(value)
            return value.value
    raise AssertionError(f"returned dict has no 'ok' key: {ast.unparse(node)[:80]}")


def test_every_return_is_none_or_an_ok_true_dict():
    returns = _returns(_dispatcher())
    dicts = [r.value for r in returns if isinstance(r.value, ast.Dict)]
    others = [
        r for r in returns
        if not isinstance(r.value, ast.Dict)
        and not (isinstance(r.value, ast.Constant) and r.value.value is None)
    ]
    assert not others, [ast.unparse(r) for r in others]
    # Seven routed branches (tank, bruiser, mage, assassin, enchanter, onhit,
    # carry) each build one result dict; an empty set would pass vacuously.
    assert len(dicts) >= 7, len(dicts)
    assert {_ok_value(d) for d in dicts} == {True}


def test_docstring_does_not_promise_ok_false():
    doc = ast.get_docstring(_dispatcher()) or ""
    assert "ok=False" not in doc
    assert '"ok":          bool' not in doc
    assert "returns ``None``" in doc


def test_ds_doc_dispatch_bullet_names_the_none_return():
    lines = [
        ln for ln in _DOC.read_text(encoding="utf-8").splitlines()
        if ln.startswith("- **Dispatch**:") and _DISPATCHER in ln
    ]
    assert len(lines) == 1, lines
    assert "`None`" in lines[0], lines[0]


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_failed_post_returns_none_for_every_branch(monkeypatch, archetype):
    monkeypatch.setattr(ds, "_post_json", lambda *a, **k: None)
    out = ds.rank_for_primary_archetype(
        "Ahri", archetype, level=11, item_ids=["3020"], mode="SR",
    )
    assert out is None


@pytest.mark.parametrize("archetype", _ARCHETYPES)
def test_http_error_status_also_collapses_to_none(monkeypatch, archetype):
    def _raise(req, timeout=None):
        raise HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(ds, "urlopen", _raise)
    out = ds.rank_for_primary_archetype(
        "Ahri", archetype, level=11, item_ids=["3020"], mode="SR",
    )
    assert out is None


def test_guard_files_are_ascii():
    for path in (_DOC, _CLIENT, Path(__file__)):
        path.read_bytes().decode("ascii")
