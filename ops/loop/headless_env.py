"""Headless account routing: the ONE gate every headless `claude` spawn passes.

Operator contract 2026-10-02. Every headless Claude run this tree starts - the
inbox responder, the lanes, the loop executor and adjudicator, the CI watchdog,
the ephemeral supervisor agent, weekly hygiene - reaches Claude through a local
subscription proxy. The proxy's URL is NOT repo content: it lives only in the
USER environment variable `CLAUDE_HEADLESS_BASE_URL`, and this module copies it
into the CHILD environment as `ANTHROPIC_BASE_URL`. Nothing here ever sets that
variable user-wide or machine-wide, and the parent's own environment is never
mutated.

FAIL CLOSED. The spawn is refused - never sent direct, never sent through the
proxy's own fallback mode - when:
  * the variable is unset or empty (`unset`);
  * it is not an http(s) URL with a host (`bad_url`);
  * its host is not loopback (`not_loopback`);
  * a TCP connect to its host:port does not succeed (`proxy_down`).
A refusal raises `HeadlessRouteRefused` and appends one JSON line (caller,
reason, timestamp - never the URL) to `REFUSAL_LOG`. A caller that hits a
usage-limit refusal from the proxy backs off on its own cadence; nothing here
retries, and nothing anywhere retries another way.

WHERE THE VALUE IS READ. The user environment store (HKCU\\Environment) is the
authority whenever it is readable, so DELETING the variable is a kill switch
that also stops a long-lived parent (a loop controller, a supervisor) that
inherited the value before it was deleted. The process environment is only the
fallback for a host where that store cannot be opened at all.

STDLIB ONLY, and runnable as a bare script: the PowerShell runners call
`python <repo>/ops/loop/headless_env.py --url` from a worktree cwd, and the
loop modules load siblings by file path with no repo root on sys.path.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Mapping, Optional, Union
from urllib.parse import urlsplit

ENV_VAR = "CLAUDE_HEADLESS_BASE_URL"
CHILD_VAR = "ANTHROPIC_BASE_URL"
PROBE_TIMEOUT_S = 2.0
EXIT_REFUSED = 3

ROOT = Path(__file__).resolve().parents[2]
# Gitignored (logs/). Overridable by env for the bare-script test only.
REFUSAL_LOG = Path(os.environ.get("RC_HEADLESS_ENV_LOG") or (ROOT / "logs" / "headless_route.log"))


class _Absent:
    """Sentinel: the user environment store itself could not be read."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "REGISTRY_ABSENT"


REGISTRY_ABSENT = _Absent()


class HeadlessRouteRefused(RuntimeError):
    """The spawn must not happen. `reason` is a short constant code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"headless route refused: {reason}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.detail = detail


def _read_user_var(name: str) -> Union[str, None, _Absent]:
    """The value from HKCU\\Environment, None if absent there, or REGISTRY_ABSENT.

    REGISTRY_ABSENT means the store could not be opened (non-Windows, or no
    user hive loaded). Never raises.
    """
    if os.environ.get("RC_HEADLESS_ENV_FORCE_UNSET") == "1":
        return None
    try:
        import winreg  # noqa: PLC0415 - Windows only
    except ImportError:
        return REGISTRY_ABSENT
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
    except OSError:
        return REGISTRY_ABSENT
    try:
        with key:
            value, kind = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if not isinstance(value, str):
        return None
    if kind == getattr(winreg, "REG_EXPAND_SZ", -1):
        value = os.path.expandvars(value)
    return value


def _probe(host: str, port: int, timeout: float) -> Optional[str]:
    """None when a TCP connect succeeds, else a short failure class name."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError as exc:
        return type(exc).__name__


def _log_refusal(caller: str, reason: str) -> None:
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "caller": caller or "?",
           "reason": reason, "pid": os.getpid()}
    try:
        REFUSAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(REFUSAL_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass
    try:
        sys.stderr.write(f"[headless_env] spawn refused: {reason} (caller={caller or '?'})\n")
    except (OSError, ValueError, AttributeError):
        pass


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _refuse(caller: str, reason: str, detail: str = "") -> HeadlessRouteRefused:
    _log_refusal(caller, reason)
    return HeadlessRouteRefused(reason, detail)


def resolve_base_url(environ: Optional[Mapping[str, str]] = None, *, caller: str = "") -> str:
    """The validated, listening proxy URL, or raise `HeadlessRouteRefused`."""
    env = os.environ if environ is None else environ
    stored = _read_user_var(ENV_VAR)
    raw = env.get(ENV_VAR) if stored is REGISTRY_ABSENT else stored
    url = (raw or "").strip() if isinstance(raw, str) else ""
    if not url:
        raise _refuse(caller, "unset")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise _refuse(caller, "bad_url") from None
    if parts.scheme not in ("http", "https") or not host:
        raise _refuse(caller, "bad_url")
    if not _is_loopback(host):
        raise _refuse(caller, "not_loopback")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    failure = _probe(host, port, PROBE_TIMEOUT_S)
    if failure is not None:
        raise _refuse(caller, "proxy_down", failure)
    return url


def headless_child_env(base_env: Optional[Mapping[str, str]] = None, *,
                       caller: str = "") -> dict:
    """A COPY of `base_env` (default os.environ) with `ANTHROPIC_BASE_URL` set.

    Raises `HeadlessRouteRefused` instead of returning an unrouted env. Neither
    `base_env` nor os.environ is mutated.
    """
    url = resolve_base_url(caller=caller)
    env = dict(os.environ if base_env is None else base_env)
    for key in [k for k in env if k.upper() == CHILD_VAR]:
        del env[key]
    env[CHILD_VAR] = url
    return env


def main(argv=None, *, environ: Optional[Mapping[str, str]] = None) -> int:
    """`--url [--caller NAME]`: print the URL (exit 0) or refuse (exit 3)."""
    args = list(sys.argv[1:] if argv is None else argv)
    caller = "cli"
    if "--caller" in args:
        i = args.index("--caller")
        if i + 1 < len(args):
            caller = args[i + 1]
    if "--url" not in args:
        sys.stderr.write("usage: headless_env.py --url [--caller NAME]\n")
        return 2
    try:
        url = resolve_base_url(environ, caller=caller)
    except HeadlessRouteRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_REFUSED
    sys.stdout.write(url + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
