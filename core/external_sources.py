"""Third-party fetch targets, as CONFIGURATION rather than as source.

Which stats host this install pulls tier tables, build pages and TFT comp
data from is a per-install fact, not a property of the code. Baked into
source it is two defects at once: a named third party shipped inside a
public repo, and a target nobody downstream can point somewhere else
without editing the module.

Resolution order per key, first hit wins:
  1. environment (``RC_EXTERNAL_<KEY>``, upper-cased; a list-valued key
     takes a comma-separated string)
  2. ``config/external_sources.json`` (gitignored; see the .example beside it)
  3. the inert placeholder in ``_INERT``, which resolves to nothing real so
     an unconfigured clone degrades down its caller's existing failure path
     instead of quietly fetching from somebody else's host.

Every lookup re-reads the file, deliberately. The targets are read at CALL
time - never frozen into a default argument or an import-time constant -
so a test can point a consumer somewhere else without reloading modules,
and an operator edit takes effect without a restart. The callers are all
rate-limited to at most one request per second per host, so the extra
stat() per fetch is free.

This is a leaf module (stdlib only) and is the one place ``lib/`` reaches
into ``core/``; it is a config reader, not a runtime dependency.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_CONFIG = Path(__file__).parent.parent / "config" / "external_sources.json"

# Scheme + host that resolves nowhere. Used for the two scraper base URLs,
# which cannot be empty: ScraperBase asserts a non-empty base_url when it is
# CONSTRUCTED, so an empty string would turn "unconfigured" into a crash at
# pipeline start-up instead of the per-source fetch error the orchestrator
# already degrades through.
UNCONFIGURED_BASE_URL = "https://unconfigured.invalid"

_INERT: dict[str, object] = {
    "site_d_base_url": UNCONFIGURED_BASE_URL,
    "site_b_base_url": UNCONFIGURED_BASE_URL,
}


def _blob() -> dict:
    try:
        data = json.loads(_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def value(key: str) -> str:
    """The configured single value for `key`, or its inert placeholder.

    An empty string is the normal answer for an unconfigured install and
    callers must treat it as "no target", never as an error.
    """
    env = os.environ.get("RC_EXTERNAL_" + key.upper(), "").strip()
    if env:
        return env
    raw = _blob().get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    fallback = _INERT.get(key, "")
    return fallback if isinstance(fallback, str) else ""


def values(key: str) -> list[str]:
    """The configured list for `key`, or an empty list.

    Empty is legitimate: a caller that sweeps several endpoints simply
    sweeps none. The environment override is comma-separated, since that
    is the only shape an env var can carry.
    """
    env = os.environ.get("RC_EXTERNAL_" + key.upper(), "")
    if env.strip():
        return [p.strip() for p in env.split(",") if p.strip()]
    raw = _blob().get(key)
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if isinstance(x, str) and str(x).strip()]


def is_configured(key: str) -> bool:
    """True when `key` carries a real target rather than a placeholder."""
    resolved = value(key)
    return bool(resolved) and resolved != UNCONFIGURED_BASE_URL
