# arch: the ONE Anthropic API key lookup (env, then repo-root key file) | section=core | frozen=no
"""core/anthropic_key.py - the single Anthropic API key lookup (ENV-APIKEY).

MAIN ORDER ENV-APIKEY (2026-10-13): every RC reader of the Anthropic key uses
ONE lookup, in this order:

  1. the process environment variable ANTHROPIC_API_KEY, when the parent
     environment carries it. No launcher sets it: start.bat,
     scripts/restart.bat and scripts/start_debug.bat run THIS file (by path)
     to check the key, keep a usable inherited value and clear an unusable
     one (RM-810);
  2. API-Key-Claude.txt at the RC repo root (gitignored).

So no reader depends on a Machine- or User-scope variable: once MAIN removes
the Machine variable, every consumer still finds the key in the file.

"First" means first VALID, not first PRESENT: a junk or header-hostile env
value falls through to the file instead of shadowing it. A valid key starts
with ``sk-ant-``, has something after the prefix, is not the template
install.bat writes (``sk-ant-YOUR-KEY-HERE``), and is printable ASCII with  # rc-credential-scan: allow-fixture
no whitespace or control character anywhere (the SDK sends it in an HTTP
header; a key with an internal newline, a Ctrl-Z, a DEL or a non-ASCII
character fails every request, and clients are cached on first use).

The key file is read as UTF-8 (a BOM is dropped) or, when it opens with a
UTF-16 BOM, as UTF-16 - PowerShell 5.1 ``>`` and ``Out-File`` write UTF-16LE.
A file over MAX_KEY_FILE_BYTES is not a key file and is never read whole.

Never raises, never logs or prints the value, never writes os.environ - so a
key read from the file is never re-exported into the environment that
spawned ``claude`` children inherit. "" means degrade to no coaching: an
unusable env value with no usable key file is "" too, never the raw value
(ENV-APIKEY nit 4; it used to come back as-is, so a junk or whitespace-only
variable reached the SDK as a truthy key and failed at request time). A key
that is PRESENT but refused is warned once per streak, naming the source and
the reason only (s144 true-audit, RM-1043); both absent is the quiet
no-coaching state. The logger carries a NullHandler, so the launchers' runpy
check, which configures no logging, prints nothing.

Consumers call ``read_anthropic_key`` through the MODULE attribute
(``anthropic_key.read_anthropic_key(...)``), not a from-import, so a single
patch point covers every reader. ``coaches._base_coach.read_api_key`` is the
long-standing re-export. Stdlib only: the launchers load this file with
``python -I`` through runpy. Pinned by
tests/test_api_key_single_lookup_env_apikey.py,
tests/test_api_key_load_order.py and tests/test_anthropic_key_true_audit_s144.py.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

ENV_VAR = "ANTHROPIC_API_KEY"
KEY_FILENAME = "API-Key-Claude.txt"
KEY_PREFIX = "sk-ant-"

# install.bat step 3 writes this line when the key file is missing.
TEMPLATE_PLACEHOLDER = "sk-ant-YOUR-KEY-HERE"  # rc-credential-scan: allow-fixture

# A real key is about 110 characters (twice that as UTF-16); a file past
# this is not a key file.
MAX_KEY_FILE_BYTES = 4096

# The RC repo root, derived from this file (core/ is one level down).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Where the key file is looked up when a caller passes no root. Production
# never rebinds it; tests/conftest.py points it at tmp so no test can ever
# resolve the real key file.
_KEY_ROOT = REPO_ROOT

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

# The rejection last warned, so a streak of the same one is warned once.
_warn_lock = threading.Lock()
_last_warning: str | None = None


def _key_problem(key) -> str | None:
    """Why ``key`` cannot be sent as an HTTP header, or None when it can.

    The reason never quotes the value.
    """
    if not isinstance(key, str):
        return "is not text"
    if key == "":
        return "is empty"
    if not key.isascii():
        return "contains a non-ASCII character"
    if not key.startswith(KEY_PREFIX):
        return "is missing the " + KEY_PREFIX + " prefix"
    # Printable ASCII only: space, tab, CR / LF, NUL, Ctrl-Z, ESC and DEL
    # are all refused by an HTTP client as a header value.
    if any(not ("!" <= c <= "~") for c in key):
        return "contains whitespace or a control character"
    if key == KEY_PREFIX:
        return "has nothing after the " + KEY_PREFIX + " prefix"
    if key == TEMPLATE_PLACEHOLDER:
        return "is the install.bat template placeholder"
    return None


def usable_key(key) -> bool:
    """A key that can survive being sent as an HTTP header."""
    return _key_problem(key) is None


def key_file_path(root: Path | str | None = None) -> Path:
    """The key file under ``root`` (default: the RC repo root)."""
    return Path(_KEY_ROOT if root is None else root) / KEY_FILENAME


def _decode(raw: bytes) -> str:
    """UTF-16 when the bytes open with a UTF-16 BOM, else UTF-8 (BOM dropped)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _read_key_file(root: Path | str | None) -> tuple[str, str | None]:
    """(usable key or "", why a PRESENT file was refused or None)."""
    try:
        p = key_file_path(root)
        if not p.is_file():
            return "", None
        with p.open("rb") as fh:
            raw = fh.read(MAX_KEY_FILE_BYTES + 1)
    except (OSError, ValueError, TypeError) as exc:
        # The class only: an OSError message carries the full path.
        return "", "is unreadable (" + type(exc).__name__ + ")"
    if len(raw) > MAX_KEY_FILE_BYTES:
        return "", "is larger than " + str(MAX_KEY_FILE_BYTES) + " bytes"
    try:
        # strip() drops CR/LF and padding (Notepad, PowerShell, echo).
        key = _decode(raw).strip()
    except UnicodeDecodeError:
        return "", "is not valid UTF-8 or UTF-16"
    problem = _key_problem(key)
    return ("", problem) if problem else (key, None)


def _report(problems: list[str]) -> None:
    """Warn once per streak of the same rejection; a clean read ends it."""
    global _last_warning
    message = "; ".join(problems) if problems else None
    with _warn_lock:
        if message == _last_warning:
            return
        _last_warning = message
    if message:
        _log.warning("Anthropic API key not usable: %s", message)


def read_anthropic_key(root: Path | str | None = None) -> str:
    """ENVIRONMENT first, then ``<root>/API-Key-Claude.txt``. Never raises.

    ``root`` defaults to the RC repo root; callers that already hold the repo
    root (``SCRIPT_DIR`` / ``APP_DIR``) may pass it.
    """
    problems: list[str] = []
    env = os.environ.get(ENV_VAR, "").strip()
    if env:
        env_problem = _key_problem(env)
        if env_problem is None:
            _report(problems)
            return env
        problems.append(ENV_VAR + " " + env_problem)
    key, file_problem = _read_key_file(root)
    if file_problem:
        problems.append(KEY_FILENAME + " " + file_problem)
    elif key and problems:
        problems[-1] += ", so " + KEY_FILENAME + " is used"
    _report(problems)
    return key
