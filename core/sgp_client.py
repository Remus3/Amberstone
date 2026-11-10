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

Trust rules (s144 true-audit, S144-T-586). The request carries the player's
session Bearer token and the reply is foreign JSON, so:

* a 30x is REPORTED as its status, never followed - urllib's redirect handler
  copies every header but Content-Length / Content-Type onto the new request,
  so following one would hand the token to whatever host and scheme the
  Location header names;
* the PUUID is one URL path segment (``_PUUID_OK`` charset, quoted anyway),
  start is an int >= 0 and count an int >= 1 (bool is not an int here), and
  the token is one Bearer word (``_TOKEN_OK``); anything else sends nothing;
* ``match_history`` never raises: a transport fault, a malformed transport
  reply or an unparseable body is ``[]``, and only dict games are returned;
* the token never reaches a log line, an exception text or ``repr()``.

Kill switch: ``RC_SGP=0``.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import urllib.error
import urllib.parse
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


# A PUUID is a base64url-style word (78 chars on the live wire); the bound is
# generous on purpose - it only has to keep the value one path segment.
_PUUID_OK = re.compile(r"[A-Za-z0-9_-]{1,128}")
# A Bearer token is one header word: the RFC 6750 b64token charset. CR / LF
# would inject a header, a space would split the scheme. JWTs from the client
# run to a few KB; 16 KiB bounds a runaway value.
_TOKEN_OK = re.compile(r"[A-Za-z0-9._~+/=-]{1,16384}")


def _is_index(value: object, minimum: int) -> bool:
    """True for a real int (never bool) of at least ``minimum``."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _usable_puuid(puuid: object) -> bool:
    return isinstance(puuid, str) and _PUUID_OK.fullmatch(puuid) is not None


def _usable_token(token: object) -> bool:
    return isinstance(token, str) and _TOKEN_OK.fullmatch(token) is not None


def match_history_url(host: str, puuid: str, start: int, count: int) -> str:
    """The SUMMARY page URL. ``puuid`` is quoted as ONE path segment; start
    must be an int >= 0 and count an int >= 1, else ValueError."""
    if not _is_index(start, 0) or not _is_index(count, 1):
        raise ValueError("startIndex must be an int >= 0 and count an int >= 1")
    segment = urllib.parse.quote(str(puuid), safe="")
    return (
        f"{host}/match-history-query/v1/products/lol/player/{segment}/SUMMARY"
        f"?startIndex={start}&count={count}"
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
    """The token in ``payload`` when it is one usable Bearer word, else None,
    so a candidate carrying CR / LF or a space falls through to the next."""
    candidates: list[object] = [payload]
    if isinstance(payload, dict):
        candidates = [payload.get("accessToken"), payload.get("token")]
    for value in candidates:
        if isinstance(value, str) and _usable_token(value.strip()):
            return value.strip()
    return None


# RM-371: the default transport bypasses lib/http/client.py and read an
# UNBOUNDED body. One match-history page is well under 1 MiB.
_MAX_BODY_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every 30x: urllib's redirect_request copies the Authorization
    header onto the new request whatever host or scheme it names, so a
    followed redirect would carry the session token off the SGP host. None
    makes urllib raise HTTPError(code), which the transport reports."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002
        return None


def _open(request: urllib.request.Request, timeout: float):
    """One request through a no-redirect opener (proxy env still honoured).
    Built per call so a proxy variable set after import is read. Patchable
    seam for tests."""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _urllib_transport(url: str, headers: dict) -> tuple[int, bytes]:
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with _open(request, _REQUEST_TIMEOUT) as response:
            body = response.read(_MAX_BODY_BYTES + 1)
            if len(body) > _MAX_BODY_BYTES:
                # OSError, so the arm below turns it into (0, b"").
                raise OSError(f"SGP response over {_MAX_BODY_BYTES} bytes refused")
            return response.status, body
    except urllib.error.HTTPError as exc:
        # Every non-2xx (and every refused 30x) lands here holding the open
        # response; close it, or each refused page leaks a socket.
        exc.close()
        return exc.code, b""
    except (OSError, http.client.HTTPException, ValueError) as exc:
        # OSError covers URLError, timeouts and the size refusal above;
        # HTTPException covers IncompleteRead / BadStatusLine mid-read;
        # ValueError covers InvalidURL and an invalid header value. Only the
        # type is logged: an exception text can quote the request URL.
        _log.info("SGP request failed (%s)", type(exc).__name__)
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

    def __repr__(self) -> str:
        """Return a repr that carries the region and never the token."""
        # Explicit so a later field addition cannot pull the token into a log.
        return f"SgpClient(region={self.region!r})"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}

    def match_history(self, puuid: str, start: int = 0, count: int = 20) -> list[dict]:
        """One page of games (dict entries only). Returns [] on any fault -
        never raises."""
        return self._page(puuid, start, count)[1]

    def _page(self, puuid: object, start: object, count: object) -> tuple[int, list[dict]]:
        """``(raw entry count, dict games)`` for one page; ``(0, [])`` on any
        fault. The raw count drives paging, so a dropped non-dict entry does
        not read as the short tail page."""
        if not sgp_enabled():
            # RM-194: the RC_SGP kill switch gates the only request path.
            _log.info("SGP disabled via RC_SGP")
            return 0, []
        if not _usable_puuid(puuid):
            _log.info("SGP match-history refused: puuid is not one path segment")
            return 0, []
        if not _is_index(start, 0) or not _is_index(count, 1):
            _log.info("SGP match-history refused: start/count out of range")
            return 0, []
        if not _usable_token(self._token):
            _log.warning("SGP match-history refused: token is not one Bearer word")
            return 0, []
        url = match_history_url(self.hosts.match_history, puuid, start, count)
        try:
            reply = self._transport(url, self._headers())
        except (OSError, http.client.HTTPException, ValueError) as exc:
            _log.info("SGP transport raised %s", type(exc).__name__)
            return 0, []
        if not (isinstance(reply, tuple) and len(reply) == 2):
            _log.info("SGP transport returned a malformed reply")
            return 0, []
        status, body = reply
        if not _is_index(status, 0) or not isinstance(body, (bytes, bytearray)):
            _log.info("SGP transport returned a malformed reply")
            return 0, []
        if status != 200 or not body:
            if status not in (0, 200):
                _log.info("SGP match-history %s for %s", status, puuid[:8])
            return 0, []
        try:
            payload = json.loads(bytes(body).decode("utf-8"))
        except (ValueError, RecursionError):
            # ValueError covers JSONDecodeError, UnicodeDecodeError and an
            # int past the digit limit; RecursionError a deeply nested body.
            _log.info("SGP match-history returned unparseable body")
            return 0, []
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, list):
            return 0, []
        return len(games), [g for g in games if isinstance(g, dict)]

    def iter_match_history(
        self,
        puuid: str,
        page_size: int = 20,
        max_games: int = 200,
    ) -> Iterator[dict]:
        """Page until the history is exhausted or ``max_games`` is reached.

        A short page means the tail was reached, so paging stops there rather
        than issuing a further request that would return nothing. page_size
        and max_games must be ints >= 1 (bool is not), else nothing is read.
        ``max_games`` bounds the RAW entries read as well as the games
        yielded, so a host answering full pages of non-dict entries cannot
        keep the loop requesting forever.
        """
        if not _is_index(page_size, 1) or not _is_index(max_games, 1):
            _log.info("SGP match-history refused: page_size/max_games out of range")
            return
        read = 0
        yielded = 0
        start = 0
        while read < max_games:
            want = min(page_size, max_games - read)
            raw, page = self._page(puuid, start, want)
            if raw == 0:
                return
            for game in page:
                yield game
                yielded += 1
                if yielded >= max_games:
                    return
            read += raw
            if raw < want:
                return
            start += raw
