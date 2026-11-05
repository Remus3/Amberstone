"""Fail-closed refusal of automated League wiki requests (RM-1227).

Ruling 51 (``RM962-S146-R51``, s146; ``docs/_archive/2026-10/s146_rulings_40-51.md``)
decided NO AUTOMATED WIKI ACCESS: the wiki host's Terms of Use list "Attempting
to use our Sites in an automated fashion without prior consent" as misuse, and
its robots.txt disallows the exact paths RC's fetchers request. This module is
the one place every wiki request path asks before it opens a socket:

- ``lib/game_data/fetch.py`` (the ``wiki`` Source of ``lib/game_data/sources.py``)
- ``tools/daemon_slayer_wiki_ability_extract.py`` ``_fetch`` (and so
  ``tools/ds_wiki_staleness_check.py``, which imports it, and
  ``tools/upstream_drift_check.py --staleness-recent``)
- ``tools/daemon_slayer_wiki_stats_extract.py`` ``_fetch``
- ``tools/ds_windup_offset_compare.py`` ``_fetch_module``

The url a caller passes is checked, and so is every REDIRECT target (RM-1254):
the three tools open through ``open_consented`` and ``lib/http/client.py``
``HttpClient`` re-checks in its redirect handler, so a non-wiki url answering
with a redirect into the wiki host is refused the same way.

A request is allowed only when a CONSENT RECORD exists: the tracked JSON file
``ops/wiki_fetch_consent.json`` (absent today), holding an object with

    {"ruling": "RM962-S146-R51", "granted": "YYYY-MM-DD", "scope": "<what was granted>"}

and optionally ``"expires": "YYYY-MM-DD"`` (the last day it is valid). The
record mirrors the human record the ruling names as its reversal (the consent,
with its date and scope, written into ``docs/OVERLAY_COMPLIANCE_PLAN.md`` row
N9). Anything else - a missing, unreadable, non-object or incomplete record, an
unparsable date, a grant dated in the future or an expired one - refuses.

It refuses; it never deletes. Parsers fed operator-supplied text (a saved
module body, a replay fixture) keep working, because they open no socket.
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSENT_PATH = PROJECT_ROOT / "ops" / "wiki_fetch_consent.json"
RULING_ID = "RM962-S146-R51"

# Hosts of the League wiki (the Riot vanity alias, the wiki.gg backend it
# fronts, and the retired Fandom host). Any *.wiki.gg host counts too: the
# Terms are the wiki.gg operator's, not one subdomain's.
WIKI_HOSTS = frozenset({
    "wiki.leagueoflegends.com",
    "leagueoflegends.wiki.gg",
    "leagueoflegends.fandom.com",
})
_WIKI_SUFFIXES = (".wiki.gg",)


class WikiFetchRefused(RuntimeError):
    """An automated wiki request was refused: no valid consent record.

    A RuntimeError, deliberately not an OSError, so a caller's transport-error
    handler (``except OSError``) does not read a refusal as a network blip.
    """


def is_wiki_url(url: str) -> bool:
    """True when ``url`` names a League wiki host (scheme and port ignored)."""
    try:
        host = (urlsplit(str(url)).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not host:
        return False
    return host in WIKI_HOSTS or host == "wiki.gg" or host.endswith(_WIKI_SUFFIXES)


def _iso_date(value: Any) -> Optional[_dt.date]:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def consent_problem(path: Optional[Path] = None, today: Optional[_dt.date] = None) -> Optional[str]:
    """None when a valid consent record exists, else why there is none.

    Read on every call (no cache), so a record added or removed takes effect
    on the next request.
    """
    p = Path(path) if path is not None else CONSENT_PATH
    today = today or _dt.date.today()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"no consent record at {p.name}"
    except (OSError, UnicodeDecodeError) as exc:
        return f"consent record unreadable ({type(exc).__name__})"
    try:
        rec = json.loads(raw)
    except ValueError:
        return "consent record is not JSON"
    if not isinstance(rec, dict):
        return "consent record is not a JSON object"
    if rec.get("ruling") != RULING_ID:
        return f"consent record does not name ruling {RULING_ID}"
    granted = _iso_date(rec.get("granted"))
    if granted is None:
        return "consent record has no valid 'granted' date (YYYY-MM-DD)"
    if granted > today:
        return "consent record 'granted' date is in the future"
    scope = rec.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        return "consent record has no 'scope'"
    if "expires" in rec:
        expires = _iso_date(rec.get("expires"))
        if expires is None:
            return "consent record 'expires' is not a valid date (YYYY-MM-DD)"
        if expires < today:
            return "consent record has expired"
    return None


def require_consent(what: str = "an automated wiki request", path: Optional[Path] = None) -> None:
    """Raise ``WikiFetchRefused`` unless a valid consent record exists."""
    problem = consent_problem(path)
    if problem is not None:
        raise WikiFetchRefused(
            f"refused {what}: {problem} (ruling {RULING_ID}, NO AUTOMATED WIKI "
            f"ACCESS; consent is recorded in ops/wiki_fetch_consent.json and "
            f"docs/OVERLAY_COMPLIANCE_PLAN.md N9)"
        )


def refuse_unless_consented(url: str, path: Optional[Path] = None) -> None:
    """Raise ``WikiFetchRefused`` for a wiki ``url`` without consent.

    A non-wiki url (Data Dragon, CommunityDragon) always passes. Call it
    BEFORE any socket opens.
    """
    if is_wiki_url(url):
        require_consent("an automated request to the League wiki host", path)


class WikiConsentRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-checks consent on every redirect hop (RM-1254).

    ``refuse_unless_consented`` on the url a caller passes is not enough: the
    default opener follows a 3xx, so a CommunityDragon, Data Dragon or Meraki
    url answering with a redirect to the wiki host would open a socket to the
    wiki. ``newurl`` is already absolute here (urllib joins it before calling
    ``redirect_request``). The refused hop's response is closed, then the
    refusal propagates out of ``open``.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            refuse_unless_consented(newurl)
        except WikiFetchRefused:
            if fp is not None:
                fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_consented(req: Any, timeout: float):
    """``urllib.request.urlopen`` with the consent check on EVERY hop.

    The url passed and each redirect target are checked; a wiki url without a
    consent record raises ``WikiFetchRefused`` before its socket opens. For the
    stdlib urllib fetchers; ``lib.http.client.HttpClient`` carries the same
    check in its own redirect handler.
    """
    refuse_unless_consented(getattr(req, "full_url", req))
    opener = urllib.request.build_opener(WikiConsentRedirectHandler())
    return opener.open(req, timeout=timeout)
