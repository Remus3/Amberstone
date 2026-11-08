# arch: true-audit lane regression tests for dashboard/routes_static.py | section=tests | frozen=no
"""True-audit lane (s144 cycle 226): dashboard/routes_static.py.

Four findings, each reproduced here against a throwaway APP_DIR (tmp_path),
never the live tree:

  F1  The /icons/* and /agent/* handlers sliced the RAW request target, so a
      query string (a cache-buster such as ``?v=3``) became part of the file
      name and an existing icon or agent file answered 404. ``_serve_web_asset``
      in the same module already strips the query; these handlers did not.
  F2  An allowlisted agent file that is absent on this host (``rc_rootCA.pem``
      is gitignored, so a fresh clone or a worktree has none) answered 500
      ``agent_read_failed`` and logged a WARNING on every hit - a server error
      and a log line any client could farm - instead of a plain 404.
  F3  The 4 MiB agent-file cap TRUNCATED silently: a file over the cap was
      served 200 with its first 4 MiB, i.e. a broken script presented as a
      complete one. Over the cap is now refused, never truncated.
  F4  ``?ui=legacy`` was a substring test over the whole target, so
      ``/?xui=legacy`` or ``/?next=ui=legacy`` served the legacy page and
      ``/?ui=legacy2`` did too. It is now the ``ui`` query parameter only.
"""
from __future__ import annotations

import logging

import pytest

from dashboard import routes_static

_NEW_BODY = b"<html>new ui</html>"
_LEGACY_BODY = b"<html>legacy ui</html>"
_PNG = b"\x89PNG\r\n\x1a\nfake"


class _StubHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.sent: list[tuple[int, bytes, str]] = []

    def _send(self, code: int, body: bytes, ctype: str, *a, **k) -> None:
        self.sent.append((code, body, ctype))


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_bytes(_NEW_BODY)
    for sub in ("champions", "aram_items"):
        d = tmp_path / "data" / "icons" / sub
        d.mkdir(parents=True)
        (d / "Ahri.png").write_bytes(_PNG)
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "screen_agent.py").write_bytes(b"print('agent')\n")
    monkeypatch.setattr(routes_static, "APP_DIR", tmp_path)
    monkeypatch.setattr(routes_static, "legacy_index_html", lambda: _LEGACY_BODY)
    monkeypatch.setattr(routes_static, "inject_asset_hash", lambda b: b)
    return tmp_path


def _call(handler, path: str) -> tuple[int, bytes, str]:
    h = _StubHandler(path)
    handler(h)
    assert len(h.sent) == 1, h.sent
    return h.sent[0]


# --------------------------------------------------------------------------- F1
@pytest.mark.parametrize("path", ["/icons/champions/Ahri.png", "/icons/champions/Ahri.png?v=3"])
def test_f1_champion_icon_serves_with_or_without_a_query(app_dir, path):
    code, body, ctype = _call(routes_static._make_icon_handler("champions"), path)
    assert (code, body, ctype) == (200, _PNG, "image/png")


@pytest.mark.parametrize("path", ["/icons/items/Ahri.png", "/icons/items/Ahri.png?v=3"])
def test_f1_item_icon_serves_with_or_without_a_query(app_dir, path):
    code, body, ctype = _call(routes_static._serve_icon_items_route, path)
    assert (code, body, ctype) == (200, _PNG, "image/png")


@pytest.mark.parametrize("path", ["/agent/screen_agent.py", "/agent/screen_agent.py?x=1"])
def test_f1_agent_file_serves_with_or_without_a_query(app_dir, path):
    code, body, _ctype = _call(routes_static._serve_agent_file, path)
    assert (code, body) == (200, b"print('agent')\n")


@pytest.mark.parametrize("path", [
    "/agent/evil.py?x=screen_agent.py",
    "/agent/?screen_agent.py",
    "/icons/champions/x?/../Ahri.png",
])
def test_f1_the_query_never_widens_what_is_served(app_dir, path):
    handler = (routes_static._serve_agent_file if path.startswith("/agent/")
               else routes_static._make_icon_handler("champions"))
    code, _body, _ctype = _call(handler, path)
    assert code == 404


# --------------------------------------------------------------------------- F2
def test_f2_absent_allowlisted_agent_file_is_a_quiet_404(app_dir, caplog):
    assert "rc_rootCA.pem" in routes_static._AGENT_ALLOWED
    assert not (app_dir / "tools" / "rc_rootCA.pem").exists()
    with caplog.at_level(logging.DEBUG, logger="rc.web_dashboard"):
        code, body, _ctype = _call(routes_static._serve_agent_file, "/agent/rc_rootCA.pem")
    assert (code, body) == (404, b"not found")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_f2_an_unreadable_agent_file_is_still_a_logged_500(app_dir, caplog):
    """Only ABSENCE is a 404; any other read failure stays a visible 500."""
    (app_dir / "tools" / "lcu_agent.py").mkdir()  # a directory cannot be read
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        code, body, _ctype = _call(routes_static._serve_agent_file, "/agent/lcu_agent.py")
    assert (code, body) == (500, b"agent_read_failed")
    assert any("agent serve" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- F3
def test_f3_agent_file_over_the_cap_is_refused_not_truncated(app_dir, monkeypatch, caplog):
    monkeypatch.setattr(routes_static, "_AGENT_FILE_CAP", 8)
    (app_dir / "tools" / "screen_agent.py").write_bytes(b"0123456789")
    with caplog.at_level(logging.WARNING, logger="rc.web_dashboard"):
        code, body, _ctype = _call(routes_static._serve_agent_file, "/agent/screen_agent.py")
    assert (code, body) == (500, b"agent_file_too_large")
    assert any("over the" in r.getMessage() for r in caplog.records)


def test_f3_agent_file_exactly_at_the_cap_is_served_whole(app_dir, monkeypatch):
    monkeypatch.setattr(routes_static, "_AGENT_FILE_CAP", 10)
    (app_dir / "tools" / "screen_agent.py").write_bytes(b"0123456789")
    code, body, _ctype = _call(routes_static._serve_agent_file, "/agent/screen_agent.py")
    assert (code, body) == (200, b"0123456789")


def test_f3_the_real_cap_covers_every_allowlisted_file_on_disk():
    tools = routes_static.APP_DIR / "tools"
    for name in sorted(routes_static._AGENT_ALLOWED):
        p = tools / name
        if p.is_file():
            assert p.stat().st_size <= routes_static._AGENT_FILE_CAP, name


# --------------------------------------------------------------------------- F4
@pytest.mark.parametrize("path", [
    "/?ui=legacy", "/index.html?ui=legacy", "/?a=1&ui=legacy", "/?ui=legacy&a=1",
])
def test_f4_the_ui_parameter_selects_the_legacy_page(app_dir, path):
    assert _call(routes_static._serve_index, path) == (200, _LEGACY_BODY, "text/html; charset=utf-8")


@pytest.mark.parametrize("path", [
    "/", "/?xui=legacy", "/?next=ui=legacy", "/?ui=legacy2", "/?ui=", "/index.html?v=1",
])
def test_f4_anything_else_serves_the_new_ui(app_dir, path):
    assert _call(routes_static._serve_index, path) == (200, _NEW_BODY, "text/html; charset=utf-8")
