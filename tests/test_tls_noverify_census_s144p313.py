"""S144-P-313 - every production TLS context that switches certificate checks off is named, and talks to a local peer.

Two guards already cover neighbouring ground. ``tests/test_tls_floor_rm752.py`` pins WHERE an ``SSLContext`` is built
(the protocol floor); ``tests/test_public_fetch_tls_verified_s144p24.py`` pins that ``scripts/`` fetches from a public host
verify the certificate. Neither covers the rest of the tree: nothing stopped a NEW production module from copying the
verify-off lines of an LCU reader and pointing them at a public host, and nothing named why each of the existing ones may
run unverified.

Measured 2026-11-07 over every tracked, non-test ``.py``: 35 files carry a verify-off marker, all of them for a peer that
is local by design - Riot's LCU and ``:2999`` Live Client (a self-signed Riot certificate, ADR-011: the game host is this
box), RC's own ``:8888`` dashboard (an mkcert leaf), or the ``:8889`` vision relay. This guard pins that census.

A site is any of: a ``CERT_NONE`` attribute, a call or reference to ``ssl._create_unverified_context``, or an assignment of
``False`` to ``check_hostname``. Per file the site count is pinned EXACTLY (a second unverified context in a listed file is
a new site; a removed one must shrink the row), and every file not in the census must carry none.

Peer proof, as far as static code reaches: the string constants of a census file (docstrings excluded) may name a
``http(s)`` / ``ws(s)`` host only if it is loopback or the file lists it in ``_PUBLIC_HOST_OK`` with its reason. A host
written as a placeholder (``https://{GAME_HOST}:2999``) is config, out of reach of an AST read: ``core/game_host.py``
defaults it to loopback and a remote value is the operator's explicit choice. So this is a census plus a literal-host
fence, not a proof that no runtime value can point elsewhere - say that, never "cannot reach a public host".

Excluded from the scan: test code (``tests/``, any ``tests`` directory, ``test_*.py``, ``conftest.py``) and
``ops/fleet_kit/`` (vendored byte-for-byte, pinned by its MANIFEST).
"""
from __future__ import annotations

import ast
import re

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

_LOCAL = "local"

# file -> (verify-off sites, what the peer is). Exact: a new site, or a removed one, fails until the row is updated.
_CENSUS: dict[str, tuple[int, str]] = {
    "coaches/_base_coach.py": (2, "Live Client :2999 on GAME_HOST (self-signed Riot cert)"),
    "core/lcu_events.py": (2, "LCU websocket on the game host (self-signed Riot cert)"),
    "core/lcu_pool.py": (2, "LCU / :2999 loopback readers (self-signed Riot cert)"),
    "core/replay_camera.py": (2, "Live Client replay API https://127.0.0.1:2999"),
    "core/replay_seek.py": (2, "Live Client replay API https://127.0.0.1:2999"),
    "core/tls_policy.py": (2, "the RC floor factory client_context_noverify(): loopback peers only, by its docstring"),
    "game_reader/__init__.py": (2, "Live Client :2999 + LCU on GAME_HOST"),
    "lcu/lcu_client.py": (2, "LCU on GAME_HOST (frozen client)"),
    "lcu/lcu_postgame_collector.py": (2, "LCU post-game endpoints on GAME_HOST"),
    "lcu/lcu_pregame.py": (4, "LCU champion-icon and pre-game endpoints on GAME_HOST"),
    "ops/launcher/service_host.py": (2, "fetch_health_origin(): RC's own dashboard on loopback (mkcert leaf)"),
    "ops/launcher/update_cycle.py": (2, "reads the service host's own health origin (loopback mkcert leaf)"),
    "scripts/discover_champion_codes.py": (2, "LCU on 127.0.0.1"),
    "scripts/probe_missing_codes.py": (2, "LCU on 127.0.0.1"),
    "scripts/team_planner_sync.py": (2, "LCU on 127.0.0.1"),
    "tft/tft_state_reader.py": (2, "Live Client :2999 on GAME_HOST"),
    "tools/gated_g238_top_pick_flip.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_g313_mayhem_aug.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_g314_tower_input.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_g506_debounce_lag.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_live_probe.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_lx01_draft_check.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/gated_lx06_events_check.py": (2, "loopback :8888 dashboard and Riot :2999"),
    "tools/gated_tls_2999_probe.py": (2, "the TLS probe of Riot :2999 on 127.0.0.1"),
    "tools/hotkey_listener.py": (2, "loopback :8888 dashboard and Riot :2999 on GAME_HOST"),
    "tools/keybind_listener.py": (2, "dashboard on RC_LEGION_HOST (default 127.0.0.1, per-host config)"),
    "tools/lcu_push_watcher.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/live_flip_watcher.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/liveclient_relay.py": (2, "Live Client :2999 on 127.0.0.1"),
    "tools/overlay_live_frame_probe.py": (2, "loopback :8888 dashboard"),
    "tools/phase_watcher.py": (3, "LCU websocket wss://127.0.0.1 and Riot :2999"),
    "tools/rc_facts.py": (2, "loopback :8888 mkcert dashboard"),
    "tools/recover_match_via_match_v5.py": (1, "loopback :8888 dashboard ingest POST"),
    "tools/rofl_archiver.py": (4, "LCU on 127.0.0.1"),
    "vision_server/_relay.py": (1, "Live Client :2999 on GAME_HOST (self-read)"),
}

# census file -> {public host literal: reason it is not a verify-off peer}. A host listed here is fetched with a
# context that verifies, or by a client that takes no ssl context at all.
_PUBLIC_HOST_OK: dict[str, dict[str, str]] = {
    "coaches/_base_coach.py": {
        "api.anthropic.com": "the Anthropic SDK client; make_ssl_ctx() is handed only to the :2999 fetch",
    },
}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
_URL = re.compile(r"\b(?:https?|wss?)://(\[[0-9a-fA-F:]+\]|[^/\s:\"'{}<>)\[\]]+)")
_SKIP_DIRS = ("ops/fleet_kit/",)


def _is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts[:-1] or parts[-1].startswith("test_") or parts[-1] == "conftest.py"


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _sites(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("CERT_NONE", "_create_unverified_context"):
            n += 1
        elif isinstance(node, ast.Assign):
            if (isinstance(node.value, ast.Constant) and node.value.value is False
                    and any(isinstance(t, ast.Attribute) and t.attr == "check_hostname" for t in node.targets)):
                n += 1
    return n


def _literal_hosts(tree: ast.AST) -> set[str]:
    skip = _docstring_ids(tree)
    hosts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            for m in _URL.finditer(node.value):
                hosts.add(m.group(1).lower())
    return hosts


def _scan() -> tuple[dict[str, int], dict[str, set[str]], int]:
    self_check()
    sites: dict[str, int] = {}
    hosts: dict[str, set[str]] = {}
    scanned = 0
    for path in iter_repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if _is_test_path(rel) or rel.startswith(_SKIP_DIRS):
            continue
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (SyntaxError, UnicodeDecodeError):
            continue
        n = _sites(tree)
        if n:
            sites[rel] = n
            hosts[rel] = _literal_hosts(tree)
    return sites, hosts, scanned


def test_the_walk_is_not_vacuous():
    sites, _hosts, scanned = _scan()
    assert scanned > 300, f"scan reached only {scanned} production files"
    # A census that matched nothing would also read as "no new site": anchor it on the factory itself.
    assert "core/tls_policy.py" in sites


def test_the_census_is_exact():
    sites, _hosts, _scanned = _scan()
    expected = {rel: n for rel, (n, _why) in _CENSUS.items()}
    new = {rel: n for rel, n in sites.items() if rel not in expected}
    gone = sorted(rel for rel in expected if rel not in sites)
    moved = {rel: (sites[rel], expected[rel]) for rel in expected if rel in sites and sites[rel] != expected[rel]}
    assert not new, (
        f"production code that turns certificate checks off and is not in the census: {new}. A peer that is "
        "not local needs verification (core.tls_policy.client_context_verified()); a local one gets a row with its reason."
    )
    assert not gone, f"census rows whose file no longer carries a verify-off site, drop them: {gone}"
    assert not moved, f"verify-off site count changed (found, pinned): {moved}"


def test_every_census_row_states_its_peer():
    for rel, (n, why) in _CENSUS.items():
        assert n >= 1 and why.strip(), rel
    for rel, extra in _PUBLIC_HOST_OK.items():
        assert rel in _CENSUS, f"_PUBLIC_HOST_OK names {rel}, which is not a census file"
        assert all(reason.strip() for reason in extra.values()), rel


def test_a_census_file_names_no_public_host_literal():
    _sites_found, hosts, _scanned = _scan()
    bad: dict[str, list[str]] = {}
    for rel in _CENSUS:
        allowed = _LOOPBACK_HOSTS | set(_PUBLIC_HOST_OK.get(rel, {}))
        extra = sorted(h for h in hosts.get(rel, set()) if h not in allowed)
        if extra:
            bad[rel] = extra
    assert not bad, (
        f"a file that turns certificate checks off names a non-loopback host literal: {bad}. Route that call through "
        "core.tls_policy.client_context_verified() and list the host in _PUBLIC_HOST_OK with the reason."
    )


# -- the detector bites ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("src, want", [
    ("import ssl\nc = ssl.create_default_context()\nc.verify_mode = ssl.CERT_NONE\n", 1),
    ("import ssl\nc = ssl._create_unverified_context()\n", 1),
    ("import ssl\nc = ssl.create_default_context()\nc.check_hostname = False\nc.verify_mode = ssl.CERT_NONE\n", 2),
    ("import ssl\nopt = {'cert_reqs': ssl.CERT_NONE}\n", 1),
    ("import ssl\nc = ssl.create_default_context()\nc.check_hostname = True\n", 0),
    ("import ssl\nc = ssl.create_default_context()\n", 0),
])
def test_the_site_detector_counts_each_spelling(src, want):
    assert _sites(ast.parse(src)) == want


def test_the_host_reader_finds_a_public_literal_and_skips_docstrings_and_placeholders():
    src = (
        '"""See https://github.com/example/docs for the keymap."""\n'
        "A = 'https://127.0.0.1:8888/api/state'\n"
        "B = f'https://{HOST}:2999/x'\n"
        "C = 'wss://[::1]:2999/'\n"
        "D = 'https://api.example.org/v1'\n"
    )
    assert _literal_hosts(ast.parse(src)) == {"127.0.0.1", "[::1]", "api.example.org"}
