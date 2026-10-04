"""Offline HTTP replay client for the game-data pipeline (P1-4).

Serves bodies recorded from the real upstreams, keyed by exact URL, from a
directory holding ``_index.json`` ({"responses": {url: filename}}). It never
touches the network: an unrecorded URL raises ``ReplayMiss`` instead of being
fetched, so a test that drifts onto a new URL fails rather than going live.

It has the same ``get(url) -> Response`` shape as ``lib.http.client.HttpClient``
so the pipeline cannot tell the difference.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lib.http.client import Response


class ReplayMiss(LookupError):
    """The URL was never recorded; a replay client never goes to the network."""


class ReplayClient:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        index = json.loads((self._root / "_index.json").read_text(encoding="utf-8"))
        self._responses: dict[str, str] = dict(index.get("responses") or {})
        self.calls = 0

    def get(self, url: str, **_kw: Any) -> Response:
        self.calls += 1
        name = self._responses.get(url)
        if name is None:
            raise ReplayMiss(f"not recorded: {url}")
        body = (self._root / name).read_bytes()
        return Response(200, {}, body, url)
