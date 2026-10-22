# arch: the ONE Anthropic API key lookup (env, then repo-root key file) | section=core | frozen=no
"""core/anthropic_key.py - the single Anthropic API key lookup (ENV-APIKEY).

MAIN ORDER ENV-APIKEY (2026-10-13): every RC reader of the Anthropic key uses
ONE lookup, in this order:

  1. the process environment variable ANTHROPIC_API_KEY - present only when a
     launcher set it for that one process (start.bat / restart.bat do);
  2. API-Key-Claude.txt at the RC repo root (gitignored).

So no reader depends on a Machine- or User-scope variable: once MAIN removes
the Machine variable, every consumer still finds the key in the file.

"First" means first VALID, not first PRESENT: a junk or header-hostile env
value falls through to the file instead of shadowing it. A valid key starts
with ``sk-ant-``, is ASCII and has no whitespace inside it (the SDK sends it
in an HTTP header; a key with an internal newline or a non-ASCII character
fails every request, and clients are cached on first use).

Never raises, never logs or prints the value, never writes os.environ - so a
key read from the file is never re-exported into the environment that
spawned ``claude`` children inherit. "" means degrade to no coaching: an
unusable env value with no usable key file is "" too, never the raw value
(ENV-APIKEY nit 4; it used to come back as-is, so a junk or whitespace-only
variable reached the SDK as a truthy key and failed at request time).

Consumers call ``read_anthropic_key`` through the MODULE attribute
(``anthropic_key.read_anthropic_key(...)``), not a from-import, so a single
patch point covers every reader. ``coaches._base_coach.read_api_key`` is the
long-standing re-export. Pinned by tests/test_api_key_single_lookup_env_apikey.py
and tests/test_api_key_load_order.py.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "ANTHROPIC_API_KEY"
KEY_FILENAME = "API-Key-Claude.txt"
KEY_PREFIX = "sk-ant-"

# The RC repo root, derived from this file (core/ is one level down).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Where the key file is looked up when a caller passes no root. Production
# never rebinds it; tests/conftest.py points it at tmp so no test can ever
# resolve the real key file.
_KEY_ROOT = REPO_ROOT


def usable_key(key) -> bool:
    """A key that can survive being sent as an HTTP header."""
    return (
        isinstance(key, str)
        and key.startswith(KEY_PREFIX)
        and key.isascii()
        and not any(c.isspace() for c in key)
    )


def key_file_path(root: Path | str | None = None) -> Path:
    """The key file under ``root`` (default: the RC repo root)."""
    return Path(_KEY_ROOT if root is None else root) / KEY_FILENAME


def _read_key_file(root: Path | str | None) -> str:
    try:
        p = key_file_path(root)
        if not p.is_file():
            return ""
        # utf-8-sig drops a BOM (PowerShell 5.1 `-Encoding UTF8` writes one);
        # strip() drops CR/LF and padding.
        key = p.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return ""
    return key if usable_key(key) else ""


def read_anthropic_key(root: Path | str | None = None) -> str:
    """ENVIRONMENT first, then ``<root>/API-Key-Claude.txt``. Never raises.

    ``root`` defaults to the RC repo root; callers that already hold the repo
    root (``SCRIPT_DIR`` / ``APP_DIR``) may pass it.
    """
    env = os.environ.get(ENV_VAR, "")
    if usable_key(env.strip()):
        return env.strip()
    return _read_key_file(root)
