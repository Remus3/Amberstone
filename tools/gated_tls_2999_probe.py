"""gated_tls_2999_probe.py - which TLS contexts does Riot's :2999 Live Client accept?

RM-752 (LEDGER 1744; ``docs/OPERATIONS.md`` "TLS protocol floor (RM-752)") put
every RC-built ``ssl.SSLContext`` on ``core/tls_policy.py`` ``TLS_MIN_VERSION``
(TLSv1_2) except ONE: ``tools/liveclient_relay.py`` keeps ``minimum_version =
TLSv1`` plus ``set_ciphers("ALL:@SECLEVEL=0")`` until an in-game probe shows that
``https://127.0.0.1:2999`` handshakes with a TLSv1_2-floor, default-cipher
context. :2999 listens only while a League game is up (the standalone TFT client
serves none), so that probe is live-gated. This tool makes it ONE command.

With a game up, it opens one HTTPS GET of ``/liveclientdata/gamestats`` per
candidate context, in a fixed order. For each it records the handshake outcome,
the negotiated protocol and cipher, the HTTP status, the top-level JSON KEYS
(never values), the error class and the elapsed time. ``gamestats`` carries no
player names or ids (gameMode, gameTime, mapName, mapNumber, mapTerrain), so
nothing personal is read or printed.

Contexts, in probe order:
  relay           the relay's own context rebuilt here (TLSv1 floor, SECLEVEL=0).
                  The CONTROL: if it gets no 200, nothing else is evidence.
                  ``relay_parity`` pins the relay's TLS-relevant code (a digest
                  of its parsed statements), so any change to it reads False.
  floor12         ``core.tls_policy.client_context_noverify()``: TLSv1_2 floor,
                  default ciphers. The RM-752 reversal condition, verbatim.
  floor12_legacy  TLSv1_2 floor with the relay's SECLEVEL=0 ciphers: the middle
                  option if floor12 is rejected.
  tls13_only      TLSv1_3 floor. Context only, never a verdict input.

Verdict (the predicate in ``docs/LIVE_GAME_GATED_SYNC.md`` "RM-752 follow-up
READY"). "In a League game" = ``/api/state`` reads a League mode with a non-empty
liveclient, AND the one :2999 listener is named League of Legends.exe
(``read_listener``; a NAME check, no path or signature), both before and after
the handshakes:
  RAISE                     in a League game, relay parity, relay OK, floor12 OK
  RAISE-FLOOR-KEEP-CIPHERS  same, but floor12 REJECTED and floor12_legacy OK
  KEEP                      same, but floor12 and floor12_legacy both REJECTED
  NOT-YET                   anything else (no game, TFT, refused, timeout, 404)
OK = handshake, HTTP 200 and a JSON object carrying ``gameTime``. REJECTED = no
handshake and an ``ssl.SSLError`` or a connection reset during the handshake. A
refused connect or a timeout is NEVER a rejection: on Windows a connect to a
closed loopback port itself takes about 2 s.

Context only, never a verdict input: ``/api/state`` mode and game time, and the
``:8889/latest-liveclient`` envelope's ``source`` and age (``agent_push`` = the
relay agent delivered, ``self_read`` = the vision process read :2999 itself with
a TLSv1_2-floor default-cipher context, ``vision_server/_relay.py``).

READ-ONLY: it never writes, never touches the relay or vision process, never
prints the token or a payload value, and never ticks a row.

USAGE
    python tools/gated_tls_2999_probe.py           # text to stdout
    python tools/gated_tls_2999_probe.py --json    # machine-readable

Exit 0 = a decisive verdict (RAISE / RAISE-FLOOR-KEEP-CIPHERS / KEEP); 1 = NOT-YET.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import http.client
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.tls_policy import client_context_noverify  # noqa: E402
from tools.gated_frame_readback import _OPENER, resolve_token  # noqa: E402
from tools.gated_vision_pillow import find_listeners  # noqa: E402

_HOST = "127.0.0.1"
_PORT = 2999
_PATH = "/liveclientdata/gamestats"
_TIMEOUT = 3.0
_MAX_BODY = 1 << 20
_STATE_URL = "https://127.0.0.1:8888/api/state"
_LIVECLIENT_URL = "http://127.0.0.1:8889/latest-liveclient"
_RELAY_SRC = _ROOT / "tools" / "liveclient_relay.py"
_LEGACY_CIPHERS = "ALL:@SECLEVEL=0"
# relay_parity(): a top-level relay statement is TLS-relevant when it names one
# of these modules or attributes, passes a ``context=`` keyword, or imports from
# one of these modules. Their canonical AST is pinned by _RELAY_TLS_SHA256.
# LIVE_URLS and the fetch path are in it too: they decide whether the relay
# speaks TLS to :2999 at all, and through which function.
_TLS_NAMES = frozenset({"_ssl_ctx", "ssl", "urllib", "urllib3", "requests", "httpx",
                        "http", "socket", "LIVE_URLS", "fetch_live", "_try_one"})
_TLS_ATTRS = frozenset({"urlopen", "build_opener", "install_opener", "HTTPSHandler",
                        "HTTPSConnection", "SSLContext", "create_default_context",
                        "_create_unverified_context", "wrap_socket", "minimum_version",
                        "maximum_version", "set_ciphers", "options", "verify_mode",
                        "check_hostname"})
# The digest of tools/liveclient_relay.py's TLS-relevant statements at the time
# relay_context() was checked against them. When the relay changes one, re-read
# its context and request path against relay_context(), then re-pin this
# (tests/test_gated_tls_2999_probe.py prints the new value).
# Re-pinned s156: the repo lane (90fd2d5ba) made upload()'s urlopen response a
# with-item; that POST goes to the local :8889 relay over plain http, and
# _ssl_ctx, _try_one and fetch_live are unchanged, so relay_context() holds.
_RELAY_TLS_SHA256 = "95bcd1e1d6bcd5ca69ebd9a303a3f6a3e7658f67701a9f08056735a498b9d19c"
# :2999 exists only for a League game; TFT's standalone client serves none.
_LEAGUE_MODES = {"sr", "aram", "arena", "brawl", "jade"}
_LEAGUE_EXE = "League of Legends.exe"
_REJECT_CLASSES = {"ssl", "reset"}
DECISIVE = ("RAISE", "RAISE-FLOOR-KEEP-CIPHERS", "KEEP")


def _noverify(ctx: ssl.SSLContext) -> ssl.SSLContext:
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def relay_context() -> ssl.SSLContext:
    """The relay's ``_ssl_ctx``, rebuilt without importing the relay.

    Importing ``tools/liveclient_relay.py`` would attach a FileHandler to the
    live ``logs/liveclient_relay.log`` and resolve the vision token at import.
    """
    ctx = _noverify(ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    try:  # the relay swallows this too, keeping the default ciphers
        ctx.set_ciphers(_LEGACY_CIPHERS)
    except ssl.SSLError:
        pass
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    return ctx


def floor12_legacy_context() -> ssl.SSLContext:
    ctx = client_context_noverify()
    ctx.set_ciphers(_LEGACY_CIPHERS)
    return ctx


def tls13_only_context() -> ssl.SSLContext:
    ctx = client_context_noverify()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


CONTEXTS = (
    ("relay", relay_context),
    ("floor12", client_context_noverify),
    ("floor12_legacy", floor12_legacy_context),
    ("tls13_only", tls13_only_context),
)


def _canon(node) -> object:
    """A version-stable canonical form of an AST: no positions, and no field
    whose value is None or an empty list (fields Python versions add or drop)."""
    if isinstance(node, ast.AST):
        fields = [[f, _canon(v)] for f in node._fields
                  if (v := getattr(node, f, None)) is not None and v != []]
        return [type(node).__name__, fields]
    if isinstance(node, list):
        return [_canon(x) for x in node]
    return repr(node)


def _touches_tls(stmt: ast.stmt) -> bool:
    for n in ast.walk(stmt):
        if isinstance(n, ast.Name) and n.id in _TLS_NAMES:
            return True
        if isinstance(n, ast.Attribute) and n.attr in _TLS_ATTRS:
            return True
        if isinstance(n, ast.keyword) and n.arg == "context":
            return True
        if isinstance(n, ast.Import) and any(
                a.name.split(".")[0] in _TLS_NAMES for a in n.names):
            return True
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in _TLS_NAMES:
            return True
    return False


def relay_tls_digest(src: Path = _RELAY_SRC) -> str | None:
    """SHA-256 over the canonical AST of every TLS-relevant top-level statement
    of the relay, in order; None when the source cannot be read or parsed."""
    try:
        tree = ast.parse(src.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return None
    pinned = [_canon(s) for s in tree.body if _touches_tls(s)]
    blob = json.dumps(pinned, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def relay_parity(src: Path = _RELAY_SRC) -> bool:
    """True iff the relay's TLS-relevant code is the code ``relay_context`` was
    checked against.

    Fail-closed pin, parsed rather than grepped: a change to any top-level
    statement that builds or tunes ``_ssl_ctx``, makes a request, or imports or
    names a TLS / HTTP module reads False. That includes moving the floor under
    an ``if`` or into a function, an augmented ``options |=``, an alias, and a
    request that passes another context, and ``LIVE_URLS`` or ``fetch_live``
    dropping https. Comments and formatting do not count. Still out of reach:
    a write through ``globals()`` or ``sys.modules``, the process environment
    (``OPENSSL_CONF``), or another module's code the relay calls into.
    """
    return relay_tls_digest(src) == _RELAY_TLS_SHA256


def _error_class(exc: BaseException) -> str:
    if isinstance(exc, ssl.SSLError):
        return "ssl"
    if isinstance(exc, ConnectionRefusedError):
        return "refused"
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        return "reset"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, http.client.HTTPException):
        return "http"
    return "os"


def probe_one(name: str, ctx: ssl.SSLContext, host: str = _HOST, port: int = _PORT,
              path: str = _PATH, timeout: float = _TIMEOUT,
              conn_factory=http.client.HTTPSConnection) -> dict:
    """One HTTPS GET with ``ctx``; never raises. Records keys, never values."""
    out: dict = {"context": name, "handshake": False, "tls_version": None,
                 "cipher": None, "status": None, "json_keys": None,
                 "error_class": None, "error": None}
    t0 = time.perf_counter()
    conn = conn_factory(host, port, context=ctx, timeout=timeout)
    try:
        conn.connect()
        out["handshake"] = True
        out["tls_version"] = conn.sock.version()
        cipher = conn.sock.cipher()
        out["cipher"] = cipher[0] if cipher else None
        conn.request("GET", path)
        resp = conn.getresponse()
        out["status"] = resp.status
        body = resp.read(_MAX_BODY)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            out["json_keys"] = sorted(str(k) for k in parsed)
    except (OSError, http.client.HTTPException) as exc:
        out["error_class"] = _error_class(exc)
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        conn.close()
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return out


def is_ok(result: dict | None) -> bool:
    return bool(result) and result["handshake"] and result["status"] == 200 \
        and "gameTime" in (result["json_keys"] or [])


def is_rejected(result: dict | None) -> bool:
    return bool(result) and not result["handshake"] \
        and result["error_class"] in _REJECT_CLASSES


def verdict(in_league_game: bool, parity: bool, results: list[dict]) -> str:
    by = {r["context"]: r for r in results}
    if not (in_league_game and parity and is_ok(by.get("relay"))):
        return "NOT-YET"
    if is_ok(by.get("floor12")):
        return "RAISE"
    if is_rejected(by.get("floor12")):
        if is_ok(by.get("floor12_legacy")):
            return "RAISE-FLOOR-KEEP-CIPHERS"
        if is_rejected(by.get("floor12_legacy")):
            return "KEEP"
    return "NOT-YET"


def read_state(url: str = _STATE_URL, timeout: float = _TIMEOUT) -> dict:
    """``/api/state`` context: mode, liveclient summary facts, in-League-game."""
    out: dict = {"mode_key": None, "liveclient_nonempty": False,
                 "game_mode": None, "game_time": None, "game_time_s": None,
                 "error": None}
    try:
        with urllib.request.urlopen(url, timeout=timeout,
                                    context=client_context_noverify()) as r:
            state = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
        out["in_league_game"] = False
        return out
    lc = state.get("liveclient") if isinstance(state, dict) else None
    out["mode_key"] = state.get("mode_key") if isinstance(state, dict) else None
    out["liveclient_nonempty"] = isinstance(lc, dict) and len(lc) > 0
    if out["liveclient_nonempty"]:
        out["game_mode"] = lc.get("game_mode")
        out["game_time"] = lc.get("game_time")
        out["game_time_s"] = lc.get("game_time_s")
    out["in_league_game"] = out["mode_key"] in _LEAGUE_MODES and out["liveclient_nonempty"]
    return out


def read_listener(psutil_mod=None, port: int = _PORT) -> dict:
    """Who holds the :2999 LISTEN socket: pids and process NAMES (never paths).

    ``is_league`` is true only for exactly one listener named League of
    Legends.exe, so a portproxy or any other process on :2999 cannot stand in.
    Fails closed: psutil missing or a denied read leaves it false.
    """
    out: dict = {"pids": [], "names": [], "is_league": False, "error": None}
    if psutil_mod is None:
        try:
            import psutil as psutil_mod  # noqa: PLC0415
        except ImportError:
            out["error"] = "psutil not installed"
            return out
    try:
        out["pids"] = find_listeners(psutil_mod.net_connections("tcp"), port)
        out["names"] = [psutil_mod.Process(p).name() for p in out["pids"]]
    except Exception as exc:  # noqa: BLE001 - fail closed, never raise
        out["error"] = f"{type(exc).__name__}"
        return out
    out["is_league"] = out["names"] == [_LEAGUE_EXE]
    return out


def read_liveclient_source(url: str = _LIVECLIENT_URL, now=time.time,
                           timeout: float = _TIMEOUT) -> dict:
    """The :8889 envelope's ``source`` and age only; the payload is never kept."""
    token, tok_source = resolve_token()
    out: dict = {"token_source": tok_source, "status": None, "source": None,
                 "age_s": None, "error": None}
    if not token:
        out["error"] = "no vision token"
        return out
    req = urllib.request.Request(url, headers={"X-RC-Token": token})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            out["status"] = r.status
            env = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        out["status"] = exc.code
        return out
    except (OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"[:200]
        return out
    if isinstance(env, dict):
        out["source"] = env.get("source")
        ts = env.get("ts")
        if isinstance(ts, (int, float)) and ts > 0:
            out["age_s"] = round(now() - ts, 2)
    return out


def collect(state_fn=read_state, source_fn=read_liveclient_source,
            probe_fn=probe_one, parity_fn=relay_parity, listener_fn=read_listener,
            contexts=CONTEXTS, now=time.time) -> dict:
    report: dict = {
        "wall": now(),
        "python": sys.version.split()[0],
        "openssl": ssl.OPENSSL_VERSION,
        "relay_parity": parity_fn(),
        "state_before": state_fn(),
        "listener": listener_fn(),
    }
    report["results"] = [probe_fn(name, build()) for name, build in contexts]
    report["state_after"] = state_fn()
    report["listener_after"] = listener_fn()
    report["liveclient_envelope"] = source_fn()
    # In a League game = /api/state says so, and the one :2999 listener is the
    # League game process itself, both before AND after the handshakes; and the
    # game is past the loading screen (numeric game_time_s above 0).
    gts = report["state_before"].get("game_time_s")
    report["past_loading"] = isinstance(gts, (int, float)) \
        and not isinstance(gts, bool) and gts > 0
    in_game = report["past_loading"] and all(bool(report[k].get(f)) for k, f in (
        ("state_before", "in_league_game"), ("state_after", "in_league_game"),
        ("listener", "is_league"), ("listener_after", "is_league")))
    report["in_league_game"] = in_game
    report["verdict"] = verdict(in_game, report["relay_parity"], report["results"])
    return report


def _render(report: dict) -> str:
    sb, env = report["state_before"], report["liveclient_envelope"]
    lines = [
        f"verdict        {report['verdict']}",
        f"in_league_game {report['in_league_game']} (mode_key {sb.get('mode_key')}, "
        f"game_mode {sb.get('game_mode')}, game_time_s {sb.get('game_time_s')})",
        f"listener       {report['listener'].get('names')} "
        f"is_league {report['listener'].get('is_league')}",
        f"relay_parity   {report['relay_parity']}",
        f"interpreter    python {report['python']}, {report['openssl']}",
        f"envelope       status {env.get('status')} source {env.get('source')} "
        f"age_s {env.get('age_s')}",
    ]
    for r in report["results"]:
        lines.append(
            f"{r['context']:<15} handshake {r['handshake']} {r['tls_version']} "
            f"{r['cipher']} status {r['status']} keys {r['json_keys']} "
            f"err {r['error_class']} {r['elapsed_ms']} ms")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    report = collect()
    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0 if report["verdict"] in DECISIVE else 1


if __name__ == "__main__":
    raise SystemExit(main())
