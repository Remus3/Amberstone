# arch: service-gateway match-history client - serves event modes Match-V5 refuses | section=core | frozen=no
"""Service-gateway (SGP) match-history client.

Riot's public Match-V5 refuses event modes: ARAM Mayhem (``gameMode=KIWI``,
queue 2400) returns 403/empty, and that is correct behaviour, not a key
fault. The client's own session-authenticated match-history backend does NOT
refuse them - queue 2400 is first class there - so this module is how RC
reads event-mode history at all.

Two facts here are load-bearing and were each expensive to learn:

1. SGP splits MATCH-HISTORY hosts from COMMON hosts. For NA1 the
   match-history host is ``usw2-red.pp.sgp.pvp.net`` while
   ``na-red.lol.sgp.pvp.net`` is the common host. A 2026-07-05 probe hit the
   common host with ``match-history-query`` and recorded a 404
   ``NO_METHOD_MATCHING_PATH``, which then sat filed as an open puzzle. It
   was never a puzzle - it was the wrong host class. ``hosts_for_region``
   keeps the two apart and a test pins it.

2. Port ``21019`` is TENCENT-only. Riot's regional hosts are plain 443. An
   earlier filing carried 21019 as the headline port, which would have cost a
   wasted probe.

The auth token is also unsettled: one prior RC probe recorded the
entitlements token being rejected while the league-session token worked, and
a reviewed client plugin (kept non-repo per the name-scrub rule) comments
that either works. Rather than encode a guess, ``acquire_token`` walks
``TOKEN_ENDPOINTS`` in order and REPORTS which source authenticated, so the
question is answered by observation instead of staying filed.

Kill switch: ``RC_SGP=0``.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterator

_log = logging.getLogger(__name__)

DEFAULT_REGION = "EUW"
_REQUEST_TIMEOUT = 15

# Client region strings are not SGP routing codes. Normalizing first means the
# host table only ever sees canonical keys.
_REGION_ALIASES = {
    "EUW1": "EUW",
    "NA": "NA1",
    "EUNE": "EUN1",
    "TR": "TR1",
    "JP": "JP1",
    "BR": "BR1",
    "OCE": "OC1",
    "LAN": "LA1",
    "LAS": "LA2",
}

# Token candidates, tried in order. The first that yields a usable string wins
# and its endpoint is reported back to the caller.
TOKEN_ENDPOINTS = (
    "/lol-rso-auth/v1/authorization/access-token",
    "/entitlements/v1/token",
    "/lol-league-session/v1/league-session-token",
)


@dataclass(frozen=True)
class SgpHosts:
    """The two host classes for a region. Conflating them yields a 404."""

    match_history: str
    common: str


_HOSTS: dict[str, SgpHosts] = {
    "NA1": SgpHosts("https://usw2-red.pp.sgp.pvp.net", "https://na-red.lol.sgp.pvp.net"),
    "BR1": SgpHosts("https://usw2-red.pp.sgp.pvp.net", "https://br-red.lol.sgp.pvp.net"),
    "LA1": SgpHosts("https://usw2-red.pp.sgp.pvp.net", "https://lan-red.lol.sgp.pvp.net"),
    "LA2": SgpHosts("https://usw2-red.pp.sgp.pvp.net", "https://las-red.lol.sgp.pvp.net"),
    "PBE": SgpHosts("https://usw2-red.pp.sgp.pvp.net", "https://pbe-red.lol.sgp.pvp.net"),
    "EUW": SgpHosts("https://euc1-red.pp.sgp.pvp.net", "https://euw-red.lol.sgp.pvp.net"),
    "EUN1": SgpHosts("https://euc1-red.pp.sgp.pvp.net", "https://eune-red.lol.sgp.pvp.net"),
    "TR1": SgpHosts("https://euc1-red.pp.sgp.pvp.net", "https://tr-red.lol.sgp.pvp.net"),
    "RU": SgpHosts("https://euc1-red.pp.sgp.pvp.net", "https://ru-red.lol.sgp.pvp.net"),
    "KR": SgpHosts("https://apne1-red.pp.sgp.pvp.net", "https://kr-red.lol.sgp.pvp.net"),
    "JP1": SgpHosts("https://apne1-red.pp.sgp.pvp.net", "https://jp-red.lol.sgp.pvp.net"),
    "SG2": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://sg2-red.lol.sgp.pvp.net"),
    "TW2": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://tw2-red.lol.sgp.pvp.net"),
    "PH2": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://ph2-red.lol.sgp.pvp.net"),
    "VN2": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://vn2-red.lol.sgp.pvp.net"),
    "TH2": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://th2-red.lol.sgp.pvp.net"),
    "OC1": SgpHosts("https://apse1-red.pp.sgp.pvp.net", "https://oce-red.lol.sgp.pvp.net"),
}


def sgp_enabled() -> bool:
    """False only when the operator sets RC_SGP=0."""
    return os.environ.get("RC_SGP", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def normalize_region(raw: str | None) -> str:
    """Client region string -> SGP routing code."""
    if not raw or not str(raw).strip():
        return DEFAULT_REGION
    code = str(raw).strip().upper()
    return _REGION_ALIASES.get(code, code)


def hosts_for_region(region: str | None) -> SgpHosts:
    """Both host classes for ``region``, falling back rather than raising."""
    return _HOSTS.get(normalize_region(region), _HOSTS[DEFAULT_REGION])


def match_history_url(host: str, puuid: str, start: int, count: int) -> str:
    return (
        f"{host}/match-history-query/v1/products/lol/player/{puuid}/SUMMARY"
        f"?startIndex={int(start)}&count={int(count)}"
    )


def acquire_token(lcu_get: Callable[[str], Any]) -> tuple[str | None, str | None]:
    """Walk TOKEN_ENDPOINTS, returning ``(token, winning_endpoint)``.

    ``lcu_get`` takes an LCU path and returns parsed JSON (or None). The
    league-session endpoint answers with a bare string; the others answer
    with an object carrying ``accessToken``, so both shapes are accepted.
    """
    for endpoint in TOKEN_ENDPOINTS:
        try:
            payload = lcu_get(endpoint)
        except Exception:  # noqa: BLE001 - any LCU fault just tries the next
            _log.debug("SGP token candidate raised: %s", endpoint)
            continue
        token = _extract_token(payload)
        if token:
            _log.info("SGP token acquired from %s", endpoint)
            return token, endpoint
    _log.warning("SGP token unavailable - every candidate endpoint failed")
    return None, None


def _extract_token(payload: Any) -> str | None:
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("accessToken", "token"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _urllib_transport(url: str, headers: dict) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        _log.info("SGP request failed (%s): %s", type(exc).__name__, exc)
        return 0, b""


class SgpClient:
    """Reads match history for an arbitrary PUUID from the regional SGP host."""

    def __init__(
        self,
        region: str,
        token: str,
        transport: Callable[[str, dict], tuple[int, bytes]] | None = None,
    ) -> None:
        self.region = normalize_region(region)
        self.hosts = hosts_for_region(self.region)
        self._token = token
        self._transport = transport or _urllib_transport

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def match_history(self, puuid: str, start: int = 0, count: int = 20) -> list[dict]:
        """One page of games. Returns [] on any fault - never raises."""
        url = match_history_url(self.hosts.match_history, puuid, start, count)
        status, body = self._transport(url, self._headers())
        if status != 200 or not body:
            if status not in (0, 200):
                _log.info("SGP match-history %s for %s", status, puuid[:8])
            return []
        try:
            payload = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            _log.info("SGP match-history returned unparseable body")
            return []
        games = payload.get("games") if isinstance(payload, dict) else None
        return games if isinstance(games, list) else []

    def iter_match_history(
        self,
        puuid: str,
        page_size: int = 20,
        max_games: int = 200,
    ) -> Iterator[dict]:
        """Page until the history is exhausted or ``max_games`` is reached.

        A short page means the tail was reached, so paging stops there rather
        than issuing a further request that would return nothing.
        """
        fetched = 0
        start = 0
        while fetched < max_games:
            want = min(page_size, max_games - fetched)
            page = self.match_history(puuid, start=start, count=want)
            if not page:
                return
            for game in page:
                yield game
                fetched += 1
                if fetched >= max_games:
                    return
            if len(page) < want:
                return
            start += len(page)
