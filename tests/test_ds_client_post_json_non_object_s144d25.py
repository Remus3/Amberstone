"""Guard (RM-1001): ``_post_json`` returns ``None`` for a JSON body that is not an object.

``core/daemon_slayer_client.py`` ``_post_json`` is annotated ``Optional[dict]``
but returned whatever ``json.loads`` produced. A 200 whose body was valid JSON
yet not an object (a list, a number, a string, a bool) reached the seven
rank clients as a non-dict, and each one's ``data.get("ranked")`` raised
AttributeError, so ``rank_for_primary_archetype`` raised instead of returning
the ``None`` its docstring promises for a failed POST. Callers wrap the call in
a broad ``except``, so the defect was latent (the DS server always sends an
object), but the annotation was the contract and the code did not keep it.

The fix is at the one transport choke point, so every one of the fifteen
``_post_json`` call sites inherits it. A malformed ROW inside a real object
(for example a non-numeric ``delta_dps``) is a different contract and is not
covered here.

``urlopen`` is stubbed, so nothing touches the live :8860 server. ASCII only
(CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core import daemon_slayer_client as ds

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLIENT = _REPO_ROOT / "core" / "daemon_slayer_client.py"
_ARCHETYPES = ("carry", "tank", "bruiser", "mage", "assassin", "enchanter", "onhit", "")
_NON_OBJECT_BODIES = (b"[]", b"[{\"item_id\": \"3031\"}]", b"7", b"\"ranked\"", b"null", b"true")


class _FakeResp:
    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _serve(monkeypatch, raw: bytes) -> list:
    seen: list = []

    def _urlopen(req, timeout=None):
        seen.append(req.full_url)
        return _FakeResp(raw)

    monkeypatch.setattr(ds, "urlopen", _urlopen)
    return seen


@pytest.mark.parametrize("raw", _NON_OBJECT_BODIES)
def test_post_json_returns_none_for_a_non_object_body(monkeypatch, raw):
    seen = _serve(monkeypatch, raw)
    assert ds._post_json("/rank", {"champion": "Ahri"}) is None
    assert len(seen) == 1, seen


def test_post_json_still_returns_an_object_body(monkeypatch):
    # Positive control: the stub transport is real, so a None above is the
    # type check, not a broken fake.
    _serve(monkeypatch, b"{\"ranked\": []}")
    assert ds._post_json("/rank", {"champion": "Ahri"}) == {"ranked": []}


@pytest.mark.parametrize("archetype", _ARCHETYPES)
@pytest.mark.parametrize("raw", (b"[]", b"7"))
def test_dispatcher_returns_none_not_raises_for_every_branch(monkeypatch, archetype, raw):
    seen = _serve(monkeypatch, raw)
    out = ds.rank_for_primary_archetype(
        "Ahri", archetype, level=11, item_ids=["3020"], mode="SR",
    )
    assert out is None
    assert seen, "the branch never reached the transport"


_PASSTHROUGH_CALLS = {
    "ehp_for": lambda: ds.ehp_for("Ahri", level=11, item_ids=["3020"]),
    "sustain_for": lambda: ds.sustain_for("Ahri"),
    "ability_dps_for": lambda: ds.ability_dps_for("Ahri", level=11, item_ids=["3020"]),
    "burst_for": lambda: ds.burst_for("Ahri", level=11, item_ids=["3020"]),
    "hybrid_for": lambda: ds.hybrid_for("Ahri", level=11, item_ids=["3020"]),
    "hps_for": lambda: ds.hps_for("Ahri", level=11, item_ids=["3020"]),
    "dps_for": lambda: ds.dps_for("Ahri", level=11, item_ids=["3020"]),
    "matchup": lambda: ds.matchup("Ahri", "Zed"),
}


@pytest.mark.parametrize("fn", sorted(_PASSTHROUGH_CALLS))
def test_passthrough_clients_return_none(monkeypatch, fn):
    # These return _post_json's value as-is, so a list body used to reach the
    # caller typed as Optional[dict].
    seen = _serve(monkeypatch, b"[]")
    assert _PASSTHROUGH_CALLS[fn]() is None
    assert seen, f"{fn} never reached the transport"


def test_post_json_type_checks_the_decoded_body():
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_post_json"
    )
    checks = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "isinstance"
        and any(isinstance(a, ast.Name) and a.id == "dict" for a in n.args)
    ]
    assert checks, "_post_json no longer checks that the body is a dict"


def test_dispatcher_docstring_names_the_non_object_body():
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    fn = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "rank_for_primary_archetype"
    )
    doc = " ".join((ast.get_docstring(fn) or "").split())
    assert "not a JSON object" in doc, doc[:200]


def test_guard_files_are_ascii():
    for path in (_CLIENT, Path(__file__)):
        path.read_bytes().decode("ascii")
