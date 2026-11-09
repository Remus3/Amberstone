# arch: GET /api/skins | section=dashboard | frozen=no
"""GET /api/skins?champion=<Slug>[&skin=<id>] - read-only skin + chroma lookup.

Always HTTP 200 JSON ``{"champion", "count", "skins": [...], "chromas": [...]}``;
an unknown champion or missing data degrades to empty lists (spec:
docs/SKINS_CHROMAS.md). No art is served; names and numeric ids only.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from core import skins
from dashboard._dispatch import equals


def build_payload(query: dict, *, detail_dir=None, cache=None) -> dict:
    champ = (query.get("champion") or [""])[0]
    lst = skins.skins_for(champ, detail_dir=detail_dir)
    out = {"champion": champ, "count": sum(1 for s in lst if s["num"] > 0),
           "skins": lst, "chromas": []}
    raw = (query.get("skin") or [""])[0]
    if raw:
        out["chromas"] = skins.chromas_for(raw, cache=cache)
    return out


def _serve_skins(h) -> None:
    q = parse_qs(urlparse(h.path).query)
    h._send(200, json.dumps(build_payload(q)).encode("utf-8"), "application/json")


GET_ROUTES = [
    (equals("/api/skins"), _serve_skins),
]
