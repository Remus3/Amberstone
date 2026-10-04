"""RM-317: `match:v5:<id>` and `match:v5:timeline:<id>` are prefix-ambiguous
in the never-expiring immutable cache: a match_id of `timeline:NA1_123`
would build exactly the timeline key for `NA1_123`.

Containment (acceptance option b): both entry points reject any match_id
containing `:` before a cache key is built, so the collision is
unconstructible. Riot match ids are `<PLATFORM>_<gameId>` and never carry a
colon, so no real caller is affected and the 18575 on-disk rows keep their
keys (no migration needed). Recording spy, never a raising one.
"""
from __future__ import annotations

import pytest

from core import riot_api


@pytest.fixture()
def keys(monkeypatch):
    seen = []

    def spy(kind, cache_key, url_fn):
        seen.append(cache_key)
        return {"ok": True}

    monkeypatch.setattr(riot_api, "_cached_or_fetch", spy)
    return seen


@pytest.mark.parametrize("fn", [riot_api.get_match, riot_api.get_match_timeline])
@pytest.mark.parametrize("bad", ["timeline:NA1_123", "NA1:123", ":"])
def test_colon_match_id_is_refused_before_any_cache_key(keys, fn, bad):
    assert fn(bad) is None
    assert keys == []


def test_collision_is_unconstructible(keys):
    riot_api.get_match("timeline:NA1_123")
    riot_api.get_match_timeline("NA1_123")
    assert keys == ["match:v5:timeline:NA1_123"]


@pytest.mark.parametrize("fn,expected", [
    (riot_api.get_match, "match:v5:NA1_5012345678"),
    (riot_api.get_match_timeline, "match:v5:timeline:NA1_5012345678"),
])
def test_real_ids_keep_their_existing_key_shape(keys, fn, expected):
    # Positive control and the no-migration proof: old-shape keys unchanged.
    assert fn("NA1_5012345678") == {"ok": True}
    assert keys == [expected]
