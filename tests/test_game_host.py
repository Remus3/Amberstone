"""Regression guard for the 1-PC game-host config (core/game_host.py).

After the 2026-05 1-PC consolidation, every live reader of the Live Client
API (:2999) and the LCU lockfile API must resolve the host via
core.game_host.GAME_HOST (default 127.0.0.1), NOT a hardcoded legacy LAN IP.
"""
import ast
import contextlib
import importlib
import ipaddress
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_GAMEPC_IP = "192.0.2.237"

# Live-path modules that must never hardcode the legacy LAN IP again.
_GUARDED = [
    "game_reader/poller.py",
    "game_reader/__init__.py",
    "coaches/_base_coach.py",
    "lcu/lcu_client.py",
    "lcu/lcu_pregame.py",
    "lcu/lcu_postgame_collector.py",
    "dashboard/builders.py",
    "dashboard/routes_diag.py",
    "tft/tft_state_reader.py",
]


def test_default_host_is_localhost():
    import core.game_host as gh
    importlib.reload(gh)
    assert gh.GAME_HOST == "127.0.0.1"


def test_env_override():
    prev = os.environ.get("RC_GAME_HOST")
    os.environ["RC_GAME_HOST"] = "10.1.2.3"
    try:
        import core.game_host as gh
        importlib.reload(gh)
        assert gh.GAME_HOST == "10.1.2.3"
    finally:
        if prev is None:
            os.environ.pop("RC_GAME_HOST", None)
        else:
            os.environ["RC_GAME_HOST"] = prev
        import core.game_host as gh
        importlib.reload(gh)


def test_no_hardcoded_gamepc_ip_in_live_readers():
    offenders = []
    for rel in _GUARDED:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if _GAMEPC_IP in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, "hardcoded legacy LAN IP in live readers:\n" + "\n".join(offenders)


def test_ascii_only():
    # Only files authored by this slice; pre-existing modules carry operator-
    # gated non-ASCII (U+2192 arrows) swept separately.
    for rel in ["core/game_host.py", "tests/test_game_host.py"]:
        raw = (_ROOT / rel).read_bytes()
        bad = [b for b in raw if b > 0x7F]
        assert not bad, f"{rel} has {len(bad)} non-ASCII bytes"


# --- S144-T-765..769: RC_GAME_HOST is validated before it reaches a URL ----
#
# Every live reader interpolates GAME_HOST straight into an authority:
# f"https://{GAME_HOST}:{port}{path}" - and the LCU ones attach the lockfile
# password as Basic auth. A raw env value therefore steered the request (and
# the password) wherever its bytes pointed, and broke every reader on merely
# wrong input (trailing space, empty value, unbracketed IPv6, a port suffix).

@contextlib.contextmanager
def _reloaded(value):
    """Reload core.game_host with RC_GAME_HOST set to ``value`` (None = unset)."""
    import core.game_host as gh
    prev = os.environ.get("RC_GAME_HOST")
    try:
        if value is None:
            os.environ.pop("RC_GAME_HOST", None)
        else:
            os.environ["RC_GAME_HOST"] = value
        yield importlib.reload(gh)
    finally:
        if prev is None:
            os.environ.pop("RC_GAME_HOST", None)
        else:
            os.environ["RC_GAME_HOST"] = prev
        importlib.reload(gh)


# Values that must never become the request authority. Each one, used raw,
# either sends the request to a host other than the one it names, or yields
# a URL no reader can open.
_HOSTILE = [
    "127.0.0.1@evil.example",      # userinfo: urlsplit host is evil.example
    "evil.example/x",              # path smuggled into the authority
    "evil.example?a=",             # query smuggled into the authority
    "evil.example#frag",           # fragment swallows ":2999/path"
    "evil.example" + chr(0x5C) + "x",  # backslash: browsers read it as a path
    "127.0.0.1:2999",              # port suffix: "...:2999:2999" is invalid
    "evil.example:80",
    "http://evil.example",         # a scheme is not a host
    "evil example",                # inner whitespace
    "evil\texample",
    "evil\r\nHost: x",             # header / line injection bytes
    "ev\u00e9l.example",           # non-ASCII (IDNA is not done here)
    chr(0x212A) + "elvin.example",  # KELVIN SIGN lower()s to ASCII "k"
    "host_name.example",           # underscore is not a hostname byte
    "-bad.example",
    "bad-.example",
    "a" * 64 + ".example",         # label over 63
    ".".join(["a" * 63] * 4) + ".b",  # name over 253
    "a..b",
    ".",
    "..",
    "999.1.1.1",                   # dotted-numeric but not an IPv4 address
    "127.000.0.1",                 # leading zeros: octal on some resolvers
    "127.1",                       # inet_aton short form
    "1.2.3",
    "fe80::1%eth0",                # scope id: needs %25 in a URL
    "[fe80::1%25eth0]",
    "[127.0.0.1]",                 # brackets are for IPv6 only
    "[::1",
    "::1]",
    ":::",
]


@pytest.mark.parametrize("raw", _HOSTILE)
def test_resolve_rejects_hostile_or_malformed_value(raw):
    from core.game_host import DEFAULT_GAME_HOST, resolve_game_host
    assert resolve_game_host(raw) == DEFAULT_GAME_HOST


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_resolve_blank_or_unset_is_default(raw):
    from core.game_host import resolve_game_host
    assert resolve_game_host(raw) == "127.0.0.1"


@pytest.mark.parametrize("raw", [
    b"10.1.2.3", 10123, ["10.1.2.3"], object(),
    ipaddress.ip_address("10.1.2.3"),   # str() is a valid host: still not text
])
def test_resolve_non_text_is_default(raw):
    from core.game_host import resolve_game_host
    assert resolve_game_host(raw) == "127.0.0.1"


@pytest.mark.parametrize("raw,want", [
    ("127.0.0.1", "127.0.0.1"),
    (" 10.1.2.3 ", "10.1.2.3"),          # a trailing space from a .bat `set`
    ("10.1.2.3\n", "10.1.2.3"),
    ("localhost", "localhost"),
    ("LocalHost", "localhost"),          # DNS is case-insensitive
    ("localhost.", "localhost"),         # absolute FQDN form
    ("RC-Host.Example-Tailnet.ts.net", "rc-host.example-tailnet.ts.net"),
    ("rc-host", "rc-host"),
    ("a" * 63 + ".example", "a" * 63 + ".example"),
    ("::1", "[::1]"),                    # IPv6 is bracketed for the URL
    ("[::1]", "[::1]"),
    ("0:0:0:0:0:0:0:1", "[::1]"),
    ("2001:DB8::5", "[2001:db8::5]"),
])
def test_resolve_accepts_and_canonicalizes(raw, want):
    from core.game_host import resolve_game_host
    assert resolve_game_host(raw) == want


@pytest.mark.parametrize("raw", [
    "127.0.0.1", "10.1.2.3", "localhost", "rc-host.example-tailnet.ts.net",
    "::1", "2001:db8::5",
])
def test_resolved_host_is_exactly_the_url_authority(raw):
    """The property every reader relies on: the URL a reader builds from the
    resolved host targets that host and the reader's port, nothing else."""
    from core.game_host import resolve_game_host
    host = resolve_game_host(raw)
    parts = urlsplit(f"https://{host}:2999/liveclientdata/allgamedata")
    assert parts.hostname == host.strip("[]")
    assert parts.port == 2999
    assert parts.username is None
    assert parts.password is None
    assert parts.path == "/liveclientdata/allgamedata"
    assert parts.query == ""
    assert parts.fragment == ""


def test_module_constant_rejects_userinfo_redirect():
    with _reloaded("127.0.0.1@evil.example") as gh:
        assert gh.GAME_HOST == "127.0.0.1"


def test_module_constant_strips_whitespace():
    with _reloaded(" 10.1.2.3 ") as gh:
        assert gh.GAME_HOST == "10.1.2.3"


def test_module_constant_empty_env_is_default():
    with _reloaded("") as gh:
        assert gh.GAME_HOST == "127.0.0.1"


def test_invalid_value_logs_one_bounded_warning(caplog):
    raw = "evil.example/" + "x" * 500
    with caplog.at_level(logging.WARNING, logger="core.game_host"), _reloaded(raw) as gh:
        assert gh.GAME_HOST == "127.0.0.1"
    recs = [r for r in caplog.records if r.name == "core.game_host"]
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "RC_GAME_HOST" in msg
    assert "127.0.0.1" in msg
    assert "x" * 100 not in msg          # the raw value is truncated


@pytest.mark.parametrize("raw", [None, "", "10.1.2.3", "localhost"])
def test_valid_or_unset_value_logs_nothing(caplog, raw):
    with caplog.at_level(logging.DEBUG, logger="core.game_host"), _reloaded(raw):
        pass
    assert not [r for r in caplog.records if r.name == "core.game_host"]


@pytest.mark.parametrize("rel", ["vision_server/_relay.py", "vision_server/_frame.py"])
def test_vision_local_host_sets_know_the_bracketed_ipv6_loopback(rel):
    """GAME_HOST now carries an IPv6 literal bracketed, so the vision
    self-heal gate (``GAME_HOST in _LOCAL_HOSTS``) must list "[::1]" or an
    IPv6 loopback config silently loses the in-process self-heal."""
    tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
    sets = [ast.literal_eval(n.value) for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "_LOCAL_HOSTS" for t in n.targets)]
    assert len(sets) == 1
    from core.game_host import resolve_game_host
    for raw in ("127.0.0.1", "localhost", "::1", "LOCALHOST"):
        assert resolve_game_host(raw) in sets[0], raw
