"""Phone push to the operator over the tailnet (Y-45 / RM-568, external reference K).

``NtfyNotifier`` is an OPTIONAL entry in the one-notify-path chain
(core/operator_notify, Y-02). It publishes to a self-hosted ntfy server - an
open-source push service we RUN, never vendor - that is reachable only over
Tailscale. It is DEFAULT-OFF: ``default_chain`` inserts it (first, ahead of the
desktop toast) only when the gitignored config file exists, parses, and says
``"enabled": true``. Absent, unparseable or disabled config = no push entry.

CONFIG (gitignored ``config/push_notify.json``; template
``config/push_notify.example.json``; ``RC_PUSH_CONFIG`` points elsewhere):

    {"enabled": true,
     "server": "https://<host>.<tailnet>.ts.net:<port>",
     "topic":  {"env": "RC_PUSH_TOPIC"},
     "token":  {"env": "RC_PUSH_TOKEN"},          # or {"file": "<path>"}
     "tailnet_suffix": ".<tailnet>.ts.net",
     "timeout_s": 4}

``tailnet_suffix`` MUST name the operator's own tailnet: unset, the generic
``.ts.net`` or the template placeholder makes ``from_config`` return None
(not armed) and log the reason (the reason only, never a value).

``token`` MUST be a reference (``{"env": NAME}`` or ``{"file": path}``, the
same shape as the fleet kit's secret references); a literal is refused.
``server`` and ``topic`` may be literals in the gitignored file or references.
All three are resolved at SEND time, in-process: no subprocess, so nothing is
ever on an argv; ``repr`` shows none of them; the only log line is the not-armed reason
above, which carries no value; every detail
string is scrubbed of all three before it is returned.

WIRE RULES
* Publish as JSON to the server root. Header values are latin-1, so a
  non-Latin title sent as a header raises and the alert never leaves; in a
  JSON body it is just text. Only Content-Type and Authorization are headers.
* Two loopback facts, deliberately different:
  - the SERVER url may be loopback (the ntfy service runs on Legion itself,
    and the tests use a stdlib server on 127.0.0.1). It must be loopback, a
    tailnet host, or a tailnet (100.64.0.0/10) address - never a public host;
  - a click / attach / action URL inside the message is opened ON THE PHONE,
    where loopback means the phone. Those are refused (whole message), and
    must name a tailnet HOSTNAME (no IP literal), per CLAUDE.md topology.
* Short timeouts (default 4 s, capped at 10 s). No proxies (an env proxy must
  not see the bearer token). Redirects are NOT followed (a 30x must not carry
  the token to another URL).
* Every outgoing title/body/tag/link first passes a privacy sweep (no email
  address, no drive / UNC / home-style path - allowlisted roots included),
  then the sibling-name sweep (tools/sibling_name_sweep.py). Any finding, or
  a sibling sweep that is not
  ARMED, refuses the push - fail closed - and the chain falls to the floor.

HOLD: ``holdable = True``, so RC_NOTIFY_HOLD=1 sends nothing (base class);
``poll`` honours the same hold. Never raises.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from core import operator_notify as _on

_ROOT = Path(__file__).resolve().parents[1]

CONFIG_ENV = "RC_PUSH_CONFIG"
DEFAULT_CONFIG = _ROOT / "config" / "push_notify.json"
DEFAULT_TAILNET_SUFFIX = ".ts.net"
DEFAULT_TIMEOUT_S = 4.0
MAX_TIMEOUT_S = 10.0
_MAX_READ = 1 << 20

# RC priority word -> ntfy's 1..5 scale.
NTFY_PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}

# Bearer token charset: anything else (a newline above all) could inject a header.
_TOKEN_OK = re.compile(r"^[A-Za-z0-9._~+/=-]{8,512}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")
_log = logging.getLogger(__name__)

# Privacy sweep (verifier fix): an outgoing push never carries an email address
# or ANY filesystem path - even an allowlisted root like C:\Users, which the
# sibling sweep's structural arm deliberately passes. The drive pattern needs a
# non-letter before the drive letter, so "https://" is not read as "s:/".
_PRIVACY = (
    ("email address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("drive path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")),
    ("UNC path", re.compile(r"\\\\[^\\/\s]+[\\/]")),
    ("home path", re.compile(r"(?:/Users/|/home/|~/|~\\)")),
)


def privacy_refusal(text: str) -> str | None:
    """A refusal naming the KIND found (never the match), or None."""
    kinds = [kind for kind, rx in _PRIVACY if rx.search(text or "")]
    if kinds:
        return f"privacy sweep: {', '.join(kinds)} in outgoing text, refused"
    return None


def suffix_refusal(suffix: object) -> str | None:
    """Why a configured tailnet suffix cannot arm the push, or None.

    The suffix must name the operator's OWN tailnet (<name>.ts.net): unset,
    the generic ".ts.net", a template placeholder, or a non-tailnet domain
    would let a link to ANY tailnet (or anywhere) through, so it refuses.
    """
    if not isinstance(suffix, str) or not suffix.strip():
        return "is unset"
    s = suffix.strip().lower().strip(".")
    if "<" in s or ">" in s:
        return "is still the template placeholder"
    if s == "ts.net":
        return "is the generic .ts.net; set the operator's own tailnet"
    if not s.endswith(".ts.net") or not re.fullmatch(r"[a-z0-9.-]+", s):
        return "is not a <tailnet>.ts.net name"
    return None


class _Refused(Exception):
    """Internal: a reason this push must not leave. Message names refs only."""


# ---------------------------------------------------------------- hosts


def _inet_aton_forms(host: str) -> ipaddress.IPv4Address | None:
    """The classic inet_aton spellings a browser still resolves: 127.1,
    2130706433, 0x7f.1, 0177.0.0.1. None when ``host`` is not one."""
    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return None
    nums = []
    for p in parts:
        try:
            if re.fullmatch(r"0[xX][0-9a-fA-F]*", p):
                nums.append(int(p[2:] or "0", 16))
            elif re.fullmatch(r"0[0-7]+", p):
                nums.append(int(p, 8))
            elif re.fullmatch(r"[0-9]+", p):
                nums.append(int(p, 10))
            else:
                return None
        except ValueError:
            return None
    last_bytes = 5 - len(nums)
    if any(n > 255 for n in nums[:-1]) or nums[-1] >= 256 ** last_bytes:
        return None
    value = 0
    for n in nums[:-1]:
        value = value * 256 + n
    value = value * (256 ** last_bytes) + nums[-1]
    return ipaddress.IPv4Address(value)


def _ip_of(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return _inet_aton_forms(host)


def _is_loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    ip = _ip_of(host)
    if ip is None:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_unspecified


def _host_of(url: str) -> tuple[str, str]:
    """(scheme, normalised host). Raises ValueError on an unparseable URL."""
    parts = urllib.parse.urlsplit(str(url).strip())
    host = (parts.hostname or "").rstrip(".").lower()
    return parts.scheme.lower(), host


def _norm_suffix(suffix: str | None) -> str:
    s = str(suffix or DEFAULT_TAILNET_SUFFIX).strip().lower().strip(".")
    return s or DEFAULT_TAILNET_SUFFIX.strip(".")


def link_refusal(url: str, tailnet_suffix: str | None = None) -> str | None:
    """Why a URL the PHONE will open must not be sent, or None when it may.

    Refused: non-http(s) schemes, no host, any loopback spelling (127/8,
    localhost, ::1, mapped, 0.0.0.0, inet_aton shorthands), any IP literal
    (links name the tailnet HOSTNAME), any host outside the tailnet suffix.
    """
    try:
        scheme, host = _host_of(url)
    except ValueError:
        return "unparseable url"
    if scheme not in ("http", "https"):
        return "scheme is not http(s)"
    if not host:
        return "url has no host"
    if _is_loopback(host):
        return "loopback host (the phone would open itself)"
    if _ip_of(host) is not None:
        return "IP literal; links must use the tailnet hostname"
    suffix = _norm_suffix(tailnet_suffix)
    if not host.endswith("." + suffix):
        return "host is not on the tailnet"
    return None


def server_refusal(url: str, tailnet_suffix: str | None = None) -> str | None:
    """Why the SERVER url is unusable. Loopback is ALLOWED here (see module doc)."""
    try:
        scheme, host = _host_of(url)
    except ValueError:
        return "server url unparseable"
    if scheme not in ("http", "https"):
        return "server url scheme is not http(s)"
    if not host:
        return "server url has no host"
    if _is_loopback(host):
        return None
    ip = _ip_of(host)
    if ip is not None:
        return None if (ip.version == 4 and ip in _TAILNET_NET) else \
            "server is not loopback or a tailnet address"
    if host.endswith("." + _norm_suffix(tailnet_suffix)):
        return None
    return "server is not loopback or a tailnet host"


# ---------------------------------------------------------------- refs


def _resolve(ref: object, label: str, allow_literal: bool) -> str:
    """A config value or secret reference -> its string. Errors name the REF."""
    if isinstance(ref, str):
        if not allow_literal:
            raise _Refused(f"{label} must be a reference ({{'env': NAME}} or {{'file': path}}), "
                           "not a literal")
        if not ref.strip():
            raise _Refused(f"{label} is empty")
        return ref.strip()
    if not isinstance(ref, Mapping) or len(ref) != 1:
        raise _Refused(f"{label} reference needs exactly one of env / file")
    (kind, val), = ref.items()
    if kind == "env":
        if not isinstance(val, str) or not _ENV_NAME.match(val):
            raise _Refused(f"{label} env reference needs a variable name")
        value = str(os.environ.get(val) or "").strip()
        if not value:
            raise _Refused(f"{label} ref env:{val} is unset or empty")
        return value
    if kind == "file":
        if not isinstance(val, str) or not val:
            raise _Refused(f"{label} file reference needs a path")
        p = Path(val)
        if not p.is_absolute():
            p = _ROOT / p
        try:
            text = p.read_bytes().decode("utf-8-sig", errors="replace")
        except OSError:
            raise _Refused(f"{label} ref file:{p.name} is missing or unreadable") from None
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        raise _Refused(f"{label} ref file:{p.name} is empty")
    raise _Refused(f"{label} reference kind must be env or file")


# ---------------------------------------------------------------- sweep


_SWEEP_MOD = None


def _sweep_module():
    global _SWEEP_MOD
    if _SWEEP_MOD is None:
        from tools import sibling_name_sweep  # noqa: PLC0415 - lazy, heavy
        _SWEEP_MOD = sibling_name_sweep
    return _SWEEP_MOD


def sweep_refusal(text: str, root: Path | None = None) -> str | None:
    """Run the sibling-name sweep (both arms) over outgoing text.

    Fails CLOSED: a sweep that cannot load, is DEGRADED (needle arm inert) or
    FAULT refuses, as does any finding. Never prints the matched literal.
    """
    try:
        s = _sweep_module()
        cfg = s.load_config(root=root if root is not None else _ROOT)
        if cfg.mode != s.MODE_ARMED:
            return f"sibling-name sweep {cfg.mode}: refused (needle arm not armed)"
        needles = s.build_needles(cfg)
        s.assert_non_vacuous(needles)
        found = s.scan_text(needles, cfg.codes, text, path="push", source="push")
        found += s.structural_findings(text, path="push", source="push")
    except Exception as exc:  # noqa: BLE001 - fail closed, never raise
        return f"sibling-name sweep could not run ({type(exc).__name__}): refused"
    if found:
        return f"sibling-name sweep: {len(found)} finding(s), refused"
    return None


# ---------------------------------------------------------------- http


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None  # urllib then raises HTTPError(code): reported, not followed


def _opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def since_hours_from_days(days: float) -> str:
    """ntfy's ``since`` takes durations; RC thinks in days. At least 1h."""
    try:
        h = int(round(float(days) * 24))
    except (TypeError, ValueError):
        h = 24
    return f"{max(1, h)}h"


# ---------------------------------------------------------------- notifier


class NtfyNotifier(_on.Notifier):
    """JSON publish to a self-hosted ntfy server on the tailnet. Holdable."""

    name = "ntfy"
    holdable = True

    def __init__(self, cfg: Mapping, *, sweep_root: Path | None = None,
                 sweep: Callable[[str], str | None] | None = None):
        cfg = dict(cfg or {})
        self._server_ref = cfg.get("server")
        self._topic_ref = cfg.get("topic")
        self._token_ref = cfg.get("token")
        self.tailnet_suffix = "." + _norm_suffix(cfg.get("tailnet_suffix"))
        try:
            t = float(cfg.get("timeout_s", DEFAULT_TIMEOUT_S))
            if not t > 0:
                raise ValueError
        except (TypeError, ValueError):
            t = DEFAULT_TIMEOUT_S
        self.timeout_s = min(t, MAX_TIMEOUT_S)
        self._sweep_root = sweep_root
        self._sweep = sweep

    def __repr__(self) -> str:
        # Server, topic and token are all capabilities: none is shown.
        return (f"NtfyNotifier(timeout_s={self.timeout_s}, "
                f"tailnet_suffix={self.tailnet_suffix!r})")

    __str__ = __repr__

    @classmethod
    def from_config(cls, path: str | os.PathLike | None = None) -> NtfyNotifier | None:
        """The enabled notifier, or None (absent / unparseable / disabled)."""
        try:
            if path is None:
                env = os.environ.get(CONFIG_ENV)
                path = env if env else DEFAULT_CONFIG
            p = Path(path)
            if not p.is_file():
                return None
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict) or cfg.get("enabled") is not True:
                return None
            why = suffix_refusal(cfg.get("tailnet_suffix"))
            if why:
                _log.info("phone push not armed: tailnet_suffix %s", why)
                return None
            return cls(cfg)
        except Exception:  # noqa: BLE001 - default-off on any doubt
            return None

    # -- pieces

    def _secrets(self) -> tuple[str, str, str]:
        server = _resolve(self._server_ref, "server", allow_literal=True)
        topic = _resolve(self._topic_ref, "topic", allow_literal=True)
        token = _resolve(self._token_ref, "token", allow_literal=False)
        if not _TOKEN_OK.match(token):
            raise _Refused("token ref resolves to a value that is not header-safe")
        why = server_refusal(server, self.tailnet_suffix)
        if why:
            raise _Refused(why)
        return server, topic, token

    def build_payload(self, n: _on.Notification, *, attach: str | None = None,
                      actions: Sequence[Mapping] = ()) -> tuple[dict | None, str]:
        """(payload-without-topic, "") or (None, reason). Checks every URL."""
        urls = []
        if n.link:
            urls.append(("click", n.link))
        if attach:
            urls.append(("attach", attach))
        for a in actions or ():
            if a.get("url"):
                urls.append(("action", str(a["url"])))
        for kind, url in urls:
            why = link_refusal(url, self.tailnet_suffix)
            if why:
                return None, f"refused: {kind} url {why}"
        payload: dict = {
            "title": _on._clean(n.title, _on._MAX_TITLE),
            "message": _on._clean(n.body, _on._MAX_BODY),
            "priority": NTFY_PRIORITY.get(n.priority, 3),
        }
        if n.tags:
            payload["tags"] = [str(t) for t in n.tags]
        if n.link:
            payload["click"] = n.link
        if attach:
            payload["attach"] = attach
        if actions:
            payload["actions"] = [dict(a) for a in actions]
        return payload, ""

    def _sweep_text(self, payload: dict) -> str | None:
        bits = [payload.get("title", ""), payload.get("message", ""),
                *payload.get("tags", []), payload.get("click", ""),
                payload.get("attach", "")]
        for a in payload.get("actions", []):
            bits += [str(v) for v in a.values()]
        text = "\n".join(str(b) for b in bits if b)
        why = privacy_refusal(text)
        if why:
            return why
        if self._sweep is not None:
            return self._sweep(text)
        return sweep_refusal(text, self._sweep_root)

    @staticmethod
    def _scrub(detail: str, secrets: Sequence[str]) -> str:
        for s in secrets:
            if s:
                detail = detail.replace(s, "***")
        return detail

    def _http(self, req: urllib.request.Request) -> tuple[bool, bytes, str]:
        try:
            with _opener().open(req, timeout=self.timeout_s) as resp:
                return True, resp.read(_MAX_READ), f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()  # body never read: a server may echo the credential
            return False, b"", f"HTTP {code}"
        except urllib.error.URLError as exc:
            return False, b"", f"unreachable ({type(exc.reason).__name__})"
        except TimeoutError:
            return False, b"", f"timeout after {self.timeout_s}s"
        except OSError as exc:
            return False, b"", f"network error ({type(exc).__name__})"

    # -- publish

    def publish(self, n: _on.Notification, *, attach: str | None = None,
                actions: Sequence[Mapping] = ()) -> tuple[bool, str]:
        """Holdable, never-raising publish with optional attach / actions."""
        if _on.is_held():
            return False, f"held: {_on.HOLD_ENV}=1, {self.name} sent nothing"
        return self._publish(n, attach=attach, actions=actions)

    def _send(self, n: _on.Notification) -> tuple[bool, str]:
        return self._publish(n)

    def _publish(self, n, *, attach=None, actions=()) -> tuple[bool, str]:
        secrets: list[str] = []
        try:
            payload, why = self.build_payload(n, attach=attach, actions=actions)
            if payload is None:
                return False, why
            server, topic, token = self._secrets()
            secrets = [token, topic, server]
            why = self._sweep_text(payload)
            if why:
                return False, why
            body = json.dumps({"topic": topic, **payload}, ensure_ascii=True).encode("ascii")
            req = urllib.request.Request(
                server.rstrip("/") + "/", data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + token})
            ok, raw, status = self._http(req)
            if not ok:
                return False, self._scrub(status, secrets)
            msg_id = ""
            try:
                msg_id = str(json.loads(raw.decode("utf-8", "replace")).get("id", ""))
            except (ValueError, AttributeError):
                pass
            msg_id = re.sub(r"[^A-Za-z0-9]", "", msg_id)[:32]
            return True, f"published {status} id={msg_id or '?'}"
        except _Refused as exc:
            return False, self._scrub(str(exc), secrets)
        except Exception as exc:  # noqa: BLE001 - contract: never raises, never leaks
            return False, self._scrub(f"{type(exc).__name__}", secrets)

    # -- read back

    def poll(self, since_hours: int | str = 12) -> tuple[bool, list[dict], str]:
        """What the server holds for the topic: (ok, messages, detail). Holdable,
        never raises. ``since_hours`` is an int (hours) or a ready "Nh" string."""
        if _on.is_held():
            return False, [], f"held: {_on.HOLD_ENV}=1, {self.name} polled nothing"
        secrets: list[str] = []
        try:
            server, topic, token = self._secrets()
            secrets = [token, topic, server]
            since = since_hours if isinstance(since_hours, str) and \
                re.fullmatch(r"[0-9]{1,5}h", since_hours) else f"{max(1, int(since_hours))}h"
            url = (server.rstrip("/") + "/" + urllib.parse.quote(topic, safe="")
                   + "/json?poll=1&since=" + since)
            req = urllib.request.Request(url, method="GET",
                                         headers={"Authorization": "Bearer " + token})
            ok, raw, status = self._http(req)
            if not ok:
                return False, [], self._scrub(status, secrets)
            items = []
            for line in raw.decode("utf-8", "replace").splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("event") == "message":
                    items.append({k: ev.get(k) for k in
                                  ("id", "time", "title", "message", "priority",
                                   "tags", "click")})
            return True, items, f"polled {status}, {len(items)} message(s)"
        except _Refused as exc:
            return False, [], self._scrub(str(exc), secrets)
        except Exception as exc:  # noqa: BLE001 - contract: never raises
            return False, [], self._scrub(f"{type(exc).__name__}", secrets)


# ---------------------------------------------------------------- fleet kit


def fleet_deliver(notifier: _on.Notifier,
                  render: Callable[[list], tuple[str, str]] | None = None):
    """Adapter to the fleet kit (v5) watcher's injected ``deliver(ids)``
    contract: returns {"delivered": bool, "detail": str}, never raises."""

    def deliver(ids):
        try:
            ids = [str(i) for i in ids]
            if render is not None:
                title, body = render(ids)
            else:
                title, body = f"{len(ids)} new", ", ".join(ids[:20])
            ok, detail = notifier.notify(_on.Notification(str(title), str(body)))
            return {"delivered": bool(ok), "detail": str(detail)}
        except Exception as exc:  # noqa: BLE001 - deliver must not raise
            return {"delivered": False, "detail": type(exc).__name__}

    return deliver
