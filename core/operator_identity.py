"""Who the operator is, as CONFIGURATION rather than as source.

The Riot accounts a given install pulls replays for, and the game name it joins
its own match rows on, are per-person facts. Baked into source they are two
defects at once: a personal identifier published with the code, and a default
that is WRONG for every install but one - a fresh clone would silently pull
nobody's replays and silently match nobody's rows, with no error to read.

Resolution order, first hit wins:
  1. environment (`RC_OPERATOR_GAME_NAME`, `RC_OPERATOR_ACCOUNTS`)
  2. `config/operator_identity.json` (gitignored; see the .example beside it)
  3. the placeholder below, which is deliberately inert-looking so a missing
     config reads as "not configured" rather than as somebody else's account.

`RC_OPERATOR_ACCOUNTS` is a comma-separated list of Riot IDs, e.g.
`Name#TAG,Name#TAG2`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PLACEHOLDER_GAME_NAME = "SamplePlayer"

_CONFIG = Path(__file__).parent.parent / "config" / "operator_identity.json"


def _blob() -> dict:
    try:
        data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _split_riot_id(riot_id: str):
    name, sep, tag = str(riot_id or "").partition("#")
    if not sep or not name.strip() or not tag.strip():
        return None
    return name.strip(), tag.strip()


def game_name() -> str:
    """The operator's Riot game name (no tagline), or the placeholder."""
    env = os.environ.get("RC_OPERATOR_GAME_NAME", "").strip()
    if env:
        return env
    val = str(_blob().get("game_name", "")).strip()
    return val or PLACEHOLDER_GAME_NAME


def accounts() -> list[tuple[str, str]]:
    """Every (game_name, tagline) pair this install archives replays for.

    Empty is a legitimate answer and callers must treat it as "nothing to
    pull", never as an error: an unconfigured clone has no accounts.
    """
    raw = os.environ.get("RC_OPERATOR_ACCOUNTS", "")
    ids = [p for p in raw.split(",") if p.strip()] if raw else _blob().get("accounts") or []
    out: list[tuple[str, str]] = []
    for rid in ids:
        pair = _split_riot_id(str(rid))
        if pair and pair not in out:
            out.append(pair)
    return out


def is_configured() -> bool:
    """True when this install carries a real identity, not the placeholder."""
    return game_name() != PLACEHOLDER_GAME_NAME or bool(accounts())
