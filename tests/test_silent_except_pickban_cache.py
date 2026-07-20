"""BATCH 4 (spec docs/specs/2026-07-19-silent-except-triage.md, finding A5).

The four module-level lazy loaders in ``dashboard/routes_pickban.py`` used to
assign their module-level cache OUTSIDE the ``try``, so a failed load pinned an
empty map for the whole process lifetime (the A1 cache-the-failure shape).

Recovery test per spec section 4 shape 2: inject a fault, call, remove the
fault, call again, assert the SECOND call succeeds. This test FAILS while the
failed load is cached (the second call returns the pinned empty map).
"""
from __future__ import annotations

import pytest

from dashboard import routes_pickban as rp

_COUNTERS_JSON = '{"counters": {"Ahri": ["Zed", "Kassadin"]}}'
_DDRAGON_JSON = (
    '{"data": {"Ahri": {"id": "Ahri", "key": "103", "name": "Ahri",'
    ' "info": {"attack": 3, "magic": 8}}}}'
)


class _FaultyPath:
    """Stands in for a module-level ``Path``; raises until ``fail`` clears."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.fail = True

    def read_text(self, encoding: str = "utf-8") -> str:
        if self.fail:
            raise OSError("injected read failure")
        return self.payload


@pytest.fixture(autouse=True)
def _clear_loader_caches():
    rp._COUNTERS_INDEX = None
    rp._CHAMP_NAME_TO_ID = None
    rp._CHAMP_ID_TO_NAME = None
    rp._CHAMP_ID_TO_INFO = None
    yield
    rp._COUNTERS_INDEX = None
    rp._CHAMP_NAME_TO_ID = None
    rp._CHAMP_ID_TO_NAME = None
    rp._CHAMP_ID_TO_INFO = None


@pytest.mark.parametrize(
    ("loader_name", "path_attr", "payload"),
    [
        ("_load_counters_index", "_COUNTERS_PATH", _COUNTERS_JSON),
        ("_load_champ_name_to_id", "_DDRAGON_CHAMPS_PATH", _DDRAGON_JSON),
        ("_load_champ_id_to_name", "_DDRAGON_CHAMPS_PATH", _DDRAGON_JSON),
        ("_load_champ_id_to_info", "_DDRAGON_CHAMPS_PATH", _DDRAGON_JSON),
    ],
)
def test_failed_load_is_not_cached(monkeypatch, loader_name, path_attr, payload):
    loader = getattr(rp, loader_name)
    stub = _FaultyPath(payload)
    monkeypatch.setattr(rp, path_attr, stub)

    # 1. Faulted call - degrades to an empty map rather than raising.
    first = loader()
    assert first == {}, f"{loader_name} should degrade to an empty map on fault"

    # 2. Fault removed - the loader MUST retry, not serve a pinned empty map.
    stub.fail = False
    second = loader()
    assert second, (
        f"{loader_name} cached the failed load: the recovered call still "
        f"returned {second!r}"
    )
