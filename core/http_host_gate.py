# arch: shared HTTP Host-header gate (DNS rebinding) for every RC server | section=core
"""The Host-header gate every RC HTTP server runs (RM-759, RM-773, RM-774).

RM-819 (2026-10-23): lifted here from ``dashboard/_handler.py`` so the
servers that are deliberately decoupled from ``dashboard/`` - the DS :8860
shell, Mission Control (``mc/``), the vision server (:8889), the DS +
match-DB MCP server and the replay server - run the SAME gate rather than a
copy, the ``core.log_scrub`` precedent (RM-321). ``dashboard._handler``
re-exports every public name, so its callers and the :8890 supervisor
server are unchanged. Imports are stdlib plus ``core.local_hosts`` and
``core.log_scrub`` (both stdlib-only), so the DS shell can take it without
closing a cycle with the core modules that import DS.

``HostAllowlistMixin`` is listed FIRST in a handler's bases, before
``HeadDeadlineMixin`` and the ``BaseHTTPRequestHandler`` base. The
allowlist is process-wide (``_allowed_names_cache``, built on first use);
tests inject it there, never by reading the live per-host file.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
import time
from email import errors as _email_errors

from core import local_hosts as _local_hosts
from core.log_scrub import scrub_log as _scrub_log

log = logging.getLogger("rc.http_host_gate")


# RM-759 (2026-10-22): DNS rebinding. Neither the :8888 dashboard nor the
# :8890 supervisor server looked at the Host header, so a page on an
# attacker's domain whose DNS answer is re-pointed at 127.0.0.1 is, to the
# browser, SAME-ORIGIN with that domain on these ports: it reads every GET
# response, and its POSTs carry Origin == Host, which the same-origin rule
# (dashboard._handler._same_origin_ok) passed. Measured live before the fix:
# `curl --resolve rebind.example:8890:127.0.0.1
# http://rebind.example:8890/api/queue` -> 200 (and :8888 -> 200 under -k;
# only its certificate name stood in the way). RM-819: the same held on every
# other RC server, which now runs this gate too.
#
# The gate: the Host must name loopback, an IP LITERAL, or one of this
# machine's configured names (core.local_hosts: the cert SANs and the tailnet
# name / FQDN, all per-host config) plus the RC_ALLOWED_HOSTS env extras
# (comma-separated). Any IP literal passes because a rebinding needs a NAME
# whose answer changes - an IP-literal Host cannot come from one - and that
# keeps a LAN viewer working across a DHCP move. A missing or empty Host
# passes: browsers always send one, HTTP/1.0 scripts may not. The names are
# read once per process (a config change takes a restart, like the cert).
_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
_HOST_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-._")
_allowed_names_cache: frozenset[str] | None = None

# A refused POST's body is drained before the 421 (when small), because
# closing with it unread makes Windows send an RST and the client then reads
# a reset instead of the refusal. Bounded in size and in total time.
_HOST_REFUSAL_DRAIN_CAP = 64 * 1024
_HOST_REFUSAL_DRAIN_TIMEOUT_S = 2.0


def _canon_host(name: str) -> str:
    """``name`` lower-cased, with an IP literal in its canonical text form."""
    try:
        return str(ipaddress.ip_address(name))
    except ValueError:
        return name.lower()


def _norm_host_name(raw) -> str:
    """A configured name, normalised like a parsed Host; '' when unusable."""
    if not isinstance(raw, str):
        return ""
    name = raw.strip().lower()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    if name.endswith("."):
        name = name[:-1]
    return _canon_host(name) if name else ""


def _ascii_digits(text: str) -> bool:
    # NOT str.isdigit: header values are latin-1 decoded and isdigit() is
    # True for U+00B2 / U+00B3 / U+00B9.
    return bool(text) and all("0" <= ch <= "9" for ch in text)


def host_header_hostname(value: str) -> str | None:
    """The hostname a Host header value names, '' for an empty value, or
    None when the value is malformed.

    Bracket-aware (``[::1]:8888`` -> ``::1``), the port dropped (ASCII digits
    only), lower-cased, one trailing dot dropped, IP literals canonical. An
    unbracketed value with more than one colon is read as a bare IPv6
    literal (``Host: ::1`` - some clients send it). Any character outside
    the hostname / address alphabet makes the value malformed, so userinfo,
    paths, whitespace and control bytes never reach a comparison.
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return None
        rest = v[end + 1:]
        if rest and not (rest.startswith(":") and _ascii_digits(rest[1:])):
            return None
        try:
            return str(ipaddress.IPv6Address(v[1:end]))
        except ValueError:
            return None
    if v.count(":") > 1:
        try:
            return str(ipaddress.IPv6Address(v))
        except ValueError:
            return None
    name, sep, port = v.rpartition(":")
    if not sep:
        name = v
    elif not _ascii_digits(port):
        return None
    name = name.lower()
    if name.endswith("."):
        name = name[:-1]
    if not name or any(ch not in _HOST_NAME_CHARS for ch in name):
        return None
    return _canon_host(name)


def build_allowed_host_names(cfg: dict | None = None,
                             env: str | None = None) -> frozenset[str]:
    """Loopback names + this machine's configured names + env extras.

    ``cfg`` is the ``core.local_hosts`` config dict (read from disk when
    None); ``env`` the RC_ALLOWED_HOSTS text (read from the environment
    when None). Injectable so tests never read the live per-host file.
    """
    if cfg is None:
        cfg = _local_hosts.load()
    if env is None:
        env = os.environ.get("RC_ALLOWED_HOSTS", "")
    raw: list = list(_local_hosts.cert_sans(cfg))
    raw.extend(cfg.get(key) for key in ("tailnet_name", "tailnet_fqdn"))
    raw.extend((env or "").split(","))
    names = set(_LOOPBACK_NAMES)
    names.update(n for n in map(_norm_host_name, raw) if n)
    return frozenset(names)


def allowed_host_names() -> frozenset[str]:
    """The process-wide allowlist, built on first use."""
    global _allowed_names_cache
    names = _allowed_names_cache
    if names is None:
        try:
            names = build_allowed_host_names()
        except Exception:  # noqa: BLE001 - a bad config must not open the gate
            log.warning("RM-759 host allowlist: per-host config unreadable; "
                        "loopback and IP literals only")
            names = _LOOPBACK_NAMES
        _allowed_names_cache = names
    return names


def is_allowed_host(hostname) -> bool:
    """True when ``hostname`` (already parsed) may address these servers."""
    if not hostname or not isinstance(hostname, str):
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    return hostname in allowed_host_names()


# RM-773 (2026-10-23): the stdlib reads the header block with
# http.client.parse_headers, i.e. the email feed parser (compat32), and that
# parser does not refuse a malformed block - it LOSES lines of it. A line that
# is not a header (no colon, `Host : x`, a NUL or non-ASCII byte in a name)
# ends the headers there and it and every later line become a "body"; a bare
# CR line is read as the header/body separator with no defect at all; a first
# line that starts with whitespace, a `: value` line and a `From ` envelope
# line are each dropped. A Host on a lost line never reaches the gate below,
# which then passes the request as Host-less. Measured live before the fix on
# :8888 and :8890: `X-Junk` then `Host: rebind.example` -> 200, while the same
# Host on a clean head -> 421.
#
# So a head is refused (400, before the Host gate) when its parse lost or
# misread any part of the block: one of these header-structure defects, an
# envelope line, or any text the parser filed as a body (a request head has
# none: the block ends at its blank line). NOT every defect: the parser also
# flags the empty body of a multipart / message Content-Type (no start
# boundary, no boundary parameter), which says nothing about the head.
#
# RM-773 follow-up (verifier bypass, 2026-10-23): the parser also lets the
# block's own Content-Type STEER that "body" into a multipart or message
# parse, which files swallowed lines where the first fix never looked - the
# root's preamble or epilogue (`multipart/mixed; boundary=x`, a bare CR, then
# `Host: rebind.example` before or after the `--x` lines -> 200), consumed
# boundary lines, a part's dropped first line. Closed at the root: the
# handlers parse heads with `HeadOnlyMessage`, which reports no Content-Type
# while the parse runs, so a header-only block always parses FLAT and every
# swallowed line is root payload text or a root defect; it is
# `HeadOnlyMessage` that closes the class. `_parsed_body_text` is strict on
# top of that (any structured body, preamble or epilogue refuses), but only as
# defence in depth for the known preamble / epilogue shapes: under the stdlib
# class it does NOT hold - `multipart/mixed; boundary=x`, a bare CR, `--x--`,
# then a Host line loses every line after the close boundary with no payload,
# preamble or epilogue left to find.
_HEAD_STRUCTURE_DEFECTS = (
    _email_errors.MissingHeaderBodySeparatorDefect,
    _email_errors.FirstHeaderLineIsContinuationDefect,
    _email_errors.MisplacedEnvelopeHeaderDefect,
    _email_errors.InvalidHeaderDefect,
)


class HeadOnlyMessage(http.client.HTTPMessage):
    """The request-head message class of ``HostAllowlistMixin`` (RM-773).

    While the stdlib parses the header block, ``get_content_type`` reports
    ``text/plain`` (the RFC default for no Content-Type), so the feed parser
    never runs a multipart / message parse over the block's tail.
    ``HostAllowlistMixin.parse_request`` calls ``head_parsed()`` as soon as
    the parse returns; from then on the real Content-Type is reported, so a
    route sees the same Content-Type, maintype, boundary, params and charset
    as under the stdlib class. ``is_multipart()`` differs: a message/rfc822
    or message/delivery-status head is True under the stdlib class and False
    here (the flat parse makes no sub-message); no in-tree route reads it.
    """

    _head_parsed = False

    def head_parsed(self) -> None:
        self._head_parsed = True

    def get_content_type(self) -> str:
        if not self._head_parsed:
            return "text/plain"
        return super().get_content_type()


def _parsed_body_text(msg) -> bool:
    """True when the parser filed any of the header block as a body.

    A header-only block has an EMPTY body, so any text there, a preamble or
    epilogue, or a body parsed into parts / sub-messages at all means lines
    of the block were swallowed."""
    if isinstance(msg.get_payload(), list):
        return True
    return bool(msg.get_payload()) or bool(msg.preamble) or bool(msg.epilogue)


def head_parse_defect(headers) -> str | None:
    """Why the parsed request head does not hold every line of its header
    block (RM-773), or None when it does - or when ``headers`` is not a
    parsed message at all (HTTP/0.9 sets a dict; the Host gate fails those
    closed itself)."""
    defects = getattr(headers, "defects", None)
    if not isinstance(defects, list):
        return None
    for defect in defects:
        if isinstance(defect, _HEAD_STRUCTURE_DEFECTS):
            return type(defect).__name__
    try:
        if headers.get_unixfrom():
            return "envelope line"
        if _parsed_body_text(headers):
            return "header lines read as a body"
    except Exception:  # noqa: BLE001 - an unreadable parse is a defect too
        return "unreadable header block"
    return None


# RM-774 (2026-10-23): RFC 9112 section 3.2.2 - for an absolute-form target
# (`GET http://<name>/<path>`) the target's authority REPLACES Host, and the
# gate below reads only the Host header. Measured live before the fix: a
# foreign name as the target's authority passed the gate on :8888 and :8890
# (404 from the anchored route matchers, where the same name in Host is
# 421), and :8890 SERVED the rootless target `index.html` (200).
#
# DECIDED: refuse (400) every target that is not origin-form, keeping
# asterisk-form for `OPTIONS *` only. Alternative considered: check the
# authority against the allowlist and rewrite the target to origin-form
# (RFC's "MUST accept" path) - rejected because these are origin servers
# that no browser and no in-tree client addresses in absolute-form, and it
# would put a URL parser in front of every route for a form nothing sends.
# Reverses if: a real client of these ports is measured sending one.
def request_target_ok(command, target) -> bool:
    """True for an origin-form target (``/...``), or ``*`` with OPTIONS."""
    if not isinstance(target, str):
        return False
    if target.startswith("/"):
        return True
    return target == "*" and command == "OPTIONS"


class HostAllowlistMixin:
    """RM-759: 421 Misdirected Request for a Host this machine does not
    answer to, before any route runs. List it FIRST, before
    ``HeadDeadlineMixin`` and the ``BaseHTTPRequestHandler`` base, so the
    check runs on the parsed head with the head deadline already removed.
    ``host_refusal_log`` is the logger the refusal is reported on; each
    server sets its own.

    RM-773: a head whose header block the stdlib parse lost lines of
    (``head_parse_defect``) is 400 first, since a lost Host reads as none.
    RM-774: so is a target that is not origin-form (``request_target_ok``),
    since an absolute-form target's authority would replace Host."""

    host_refusal_log = log
    # RM-773 follow-up: heads parse flat, never steered by their Content-Type.
    MessageClass = HeadOnlyMessage

    def parse_request(self) -> bool:
        parsed = super().parse_request()
        headers = getattr(self, "headers", None)
        if isinstance(headers, HeadOnlyMessage):
            headers.head_parsed()   # routes see the real Content-Type
        if not parsed:
            return False
        # HTTP/0.9 carries no headers at all (Python 3.14 sets headers =
        # {}), so no Host: letting it through would be a headerless bypass
        # of this gate, and calling get_all on that dict crashed the handler
        # (empty reply plus a traceback via socketserver's handle_error).
        # No browser or in-tree client speaks 0.9, and it has no status
        # line to refuse with, so the connection is simply closed.
        if getattr(self, "request_version", None) == "HTTP/0.9":
            self.close_connection = True
            self._note_host_refusal("HTTP/0.9 request refused, closed")
            return False
        # RM-773: a head whose parse lost lines (a Host among them, possibly)
        # is refused before the Host gate, which would see no Host and pass.
        defect = head_parse_defect(getattr(self, "headers", None))
        if defect:
            self._note_host_refusal(
                f"header block parse defect ({defect}) refused (400)",
                tag="RM-773")
            self._refuse_head(400, "Bad Request", "bad_header_block")
            return False
        # RM-774: an absolute-form target's authority would replace Host
        # (RFC 9112 3.2.2), so only origin-form (and OPTIONS *) reaches it.
        if not request_target_ok(getattr(self, "command", None),
                                 getattr(self, "path", None)):
            self._note_host_refusal(
                "non-origin-form request target refused (400)", tag="RM-774")
            self._refuse_head(400, "Bad Request", "bad_request_target")
            return False
        if self._host_header_allowed():
            return True
        self._refuse_misdirected_host()
        return False

    def _host_lines(self) -> list | None:
        """Every Host line, or None when the headers are not a Message."""
        get_all = getattr(getattr(self, "headers", None), "get_all", None)
        if not callable(get_all):
            return None
        return get_all("Host") or []

    def _host_header_allowed(self) -> bool:
        lines = self._host_lines()
        if lines is None:
            return False        # no parsed head to check: fail closed
        # EVERY Host line must pass, never just the first: `Message.get`
        # returns only the first of a repeated name (the RM-152 / chunked
        # lesson). Two allowed lines pass - http.client's putrequest adds a
        # Host itself, so a caller that also puts one sends two.
        for value in lines:
            hostname = host_header_hostname(value)
            if hostname == "":
                continue
            if not is_allowed_host(hostname):
                return False
        return True

    def _note_host_refusal(self, what: str, tag: str = "RM-759") -> None:
        server = getattr(self, "server", None)
        count = getattr(server, "host_refusals", 0) + 1
        try:
            server.host_refusals = count
        except AttributeError:
            pass
        # First, then every 100th per server: a looping page must not be
        # able to flood logs/ with one line per request.
        if count == 1 or count % 100 == 0:
            try:
                peer = self.address_string()
            except (AttributeError, IndexError, TypeError):
                peer = "?"
            self.host_refusal_log.warning(
                "%s %s peer=%s host=%s path=%s count=%d", tag, what, peer,
                _scrub_log(repr(self._host_lines())),
                _scrub_log(repr(getattr(self, "path", ""))), count)

    def _refuse_misdirected_host(self) -> None:
        self._note_host_refusal("misdirected Host refused (421)")
        self._refuse_head(421, "Misdirected Request", "misdirected_host")

    def _refuse_head(self, code: int, phrase: str, error: str) -> None:
        """A fixed JSON refusal of the parsed head; the connection closes."""
        self._drain_small_body()
        body = json.dumps({"error": error}, separators=(",", ":")).encode()
        self.close_connection = True
        self.send_response(code, phrase)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except OSError:
                pass

    def _drain_small_body(self) -> None:
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except (AttributeError, TypeError, ValueError):
            return
        if n <= 0 or n > _HOST_REFUSAL_DRAIN_CAP:
            return
        sock = getattr(self, "connection", None)
        can_arm = callable(getattr(sock, "settimeout", None))
        prior = None
        if can_arm:
            try:
                prior = sock.gettimeout()
            except OSError:
                can_arm = False
        read = getattr(self.rfile, "read1", None) or self.rfile.read
        deadline = time.monotonic() + _HOST_REFUSAL_DRAIN_TIMEOUT_S
        remaining = n
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                if can_arm:
                    sock.settimeout(left)
                chunk = read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            if can_arm:
                try:
                    sock.settimeout(prior)
                except OSError:
                    pass
