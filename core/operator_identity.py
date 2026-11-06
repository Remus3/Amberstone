"""Who the operator is, as CONFIGURATION rather than as source.

The Riot accounts a given install pulls replays for, and the game name it joins
its own match rows on, are per-person facts. Baked into source they are two
defects at once: a personal identifier published with the code, and a default
that is WRONG for every install but one - a fresh clone would silently pull
nobody's replays and silently match nobody's rows, with no error to read.

Resolution order, first hit wins:
  1. environment (`RC_OPERATOR_GAME_NAME`, `RC_OPERATOR_ACCOUNTS`,
     `RC_RIOT_PLATFORM`); a blank or whitespace-only value counts as unset
  2. `config/operator_identity.json` (gitignored; see the .example beside it),
     read as UTF-8 with or without a BOM (PowerShell 5.1 writes one)
  3. the placeholder below, which is deliberately inert-looking so a missing
     config reads as "not configured" rather than as somebody else's account.

`RC_OPERATOR_ACCOUNTS` is a comma-separated list of Riot IDs, e.g.
`Name#TAG,Name#TAG2`; the config's `accounts` key takes a JSON list of the same
strings (or one comma-separated string).

Validation (true-audit s144t159): a value of the wrong JSON type is ignored,
never stringified into an identifier (`null` must not become a game name called
"None", `true` must not become a platform called "TRUE"); a Riot ID whose
tagline holds a second '#' or any part holds a control character (C0 or C1)
or a lone surrogate is rejected, and so is a game name holding one;
Riot IDs are case-insensitive, so case variants of one account are pulled
once. A config file that is PRESENT but unreadable, malformed or not a JSON
object reads as unconfigured and logs ONE warning naming the file and the
error class - never its content, which is personal. A missing file is silent:
that is the legitimate unconfigured state.
"""
from __future__ import annotations

import json
import logging
import os
import unicodedata
from pathlib import Path

log = logging.getLogger(__name__)

PLACEHOLDER_GAME_NAME = "SamplePlayer"

DEFAULT_PLATFORM = "NA1"

_CONFIG = Path(__file__).parent.parent / "config" / "operator_identity.json"

# Keys already warned about, so a per-tick caller does not flood the log. Keyed
# on the failure kind plus a digest of what failed (in memory only, never
# logged), so fixing the file and breaking it differently warns again.
_WARNED: set[tuple] = set()


def _warn_once(key: tuple, msg: str, *args) -> None:
    if key in _WARNED:
        return
    _WARNED.add(key)
    log.warning(msg, *args)


def _blob() -> dict:
    """The config object, or ``{}`` when absent, unreadable or malformed."""
    try:
        raw = _CONFIG.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _warn_once(("read", type(exc).__name__),
                   "operator identity config %s unreadable (%s); treating "
                   "this install as unconfigured", _CONFIG.name,
                   type(exc).__name__)
        return {}
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        # UnicodeDecodeError and JSONDecodeError are both ValueError; a deeply
        # nested document raises RecursionError from the C decoder.
        _warn_once(("parse", hash(raw)),
                   "operator identity config %s is not valid JSON (%s); "
                   "treating this install as unconfigured", _CONFIG.name,
                   type(exc).__name__)
        return {}
    if not isinstance(data, dict):
        _warn_once(("shape", hash(raw)),
                   "operator identity config %s is a JSON %s, not an object; "
                   "treating this install as unconfigured", _CONFIG.name,
                   type(data).__name__)
        return {}
    return data


def _field(blob: dict, key: str, types: tuple):
    """``blob[key]`` when it has one of ``types``, else ``None``.

    An absent key or a JSON ``null`` is the unset state and is silent; a
    present value of the wrong type is a config mistake and warns once.
    """
    val = blob.get(key)
    if val is None:
        return None
    if not isinstance(val, types):
        _warn_once(("type", key, type(val).__name__),
                   "operator identity config key %r is a %s; ignored",
                   key, type(val).__name__)
        return None
    return val


def _has_control(text: str) -> bool:
    """True when ``text`` holds a C0 / C1 control or a lone surrogate.

    A lone surrogate (a JSON ``\\ud800`` escape decodes to one) cannot be
    encoded to UTF-8, so it would raise later in a sqlite bind or a URL.
    """
    return any(unicodedata.category(ch) in ("Cc", "Cs") for ch in text)


def _split_riot_id(riot_id):
    """``(game_name, tagline)`` for a well-formed ``Name#TAG``, else ``None``.

    Both parts are trimmed at the ends only (game names may hold interior
    spaces). A tagline holding a second '#', an empty part or a control
    character anywhere is rejected rather than trusted into an API call.
    """
    if not isinstance(riot_id, str):
        return None
    name, sep, tag = riot_id.partition("#")
    name, tag = name.strip(), tag.strip()
    if not sep or not name or not tag or "#" in tag:
        return None
    if _has_control(name) or _has_control(tag):
        return None
    return name, tag


def _name_part(raw) -> str:
    """The game name in ``raw``; a full ``Name#TAG`` yields ``Name``."""
    if not isinstance(raw, str):
        return ""
    name = raw.partition("#")[0].strip()
    return "" if _has_control(name) else name


def game_name() -> str:
    """The operator's Riot game name (no tagline), or the placeholder."""
    env = _name_part(os.environ.get("RC_OPERATOR_GAME_NAME", ""))
    if env:
        return env
    val = _name_part(_field(_blob(), "game_name", (str,)))
    return val or PLACEHOLDER_GAME_NAME


def accounts() -> list[tuple[str, str]]:
    """Every (game_name, tagline) pair this install archives replays for.

    Empty is a legitimate answer and callers must treat it as "nothing to
    pull", never as an error: an unconfigured clone has no accounts. The first
    spelling of a Riot ID wins; later case variants of it are dropped.
    """
    raw = os.environ.get("RC_OPERATOR_ACCOUNTS", "")
    if raw.strip():
        ids: list = raw.split(",")
    else:
        val = _field(_blob(), "accounts", (list, str))
        ids = val.split(",") if isinstance(val, str) else (val or [])
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for rid in ids:
        pair = _split_riot_id(rid)
        if pair is None:
            continue
        key = (pair[0].casefold(), pair[1].casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(pair)
    return out


def normalize_platform(raw) -> str:
    """``raw`` as an upper-cased platform id, or ``""`` when it is not one.

    A platform id is plain ASCII alphanumeric and starts with a letter
    (``NA1``, ``EUW1``, ``KR``); anything else - a non-string, a path, a bare
    number - is refused rather than trusted into a match id.
    """
    if not isinstance(raw, str):
        return ""
    val = raw.strip().upper()
    if val and val.isascii() and val.isalnum() and val[0].isalpha():
        return val
    return ""


def platform() -> str:
    """The operator's Riot PLATFORM id (``NA1``, ``EUW1``, ...), upper-cased.

    This is the prefix of a Match-V5 match id (``NA1_<gameId>``). It is NOT
    the regional route (``americas`` / ``europe`` / ``asia``) the Match-V5
    host uses, and the two must never be swapped. Resolution order matches
    the rest of this module: env ``RC_RIOT_PLATFORM``, then the ``platform``
    key of ``config/operator_identity.json``, then ``NA1`` (the default
    ``core/riot_api.py`` already documents for v1). A value that is not a
    plain alphanumeric, letter-led string is ignored rather than trusted into
    an id (``normalize_platform``), and the next source is tried.
    """
    val = normalize_platform(os.environ.get("RC_RIOT_PLATFORM", ""))
    if val:
        return val
    val = normalize_platform(_field(_blob(), "platform", (str,)))
    return val or DEFAULT_PLATFORM


def is_configured() -> bool:
    """True when this install carries a real identity, not the placeholder."""
    return game_name() != PLACEHOLDER_GAME_NAME or bool(accounts())
