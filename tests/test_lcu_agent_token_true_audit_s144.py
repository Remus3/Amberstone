"""s144 lane 8 true-audit of tools/lcu_agent.py ``_resolve_auth_token``.

The RC-LCUAgent task runs this resolver at IMPORT (``TOKEN = ...``) under
pythonw, where an uncaught exception is a silent exit and a dead champ-select
UI. Findings, each pinned red-first:
- F1: an EMPTY config/vision_token.txt raised IndexError at import
  (``"".splitlines()[0]``); only OSError was caught.
- F2: a config file that is not UTF-8 (a PowerShell 5.1 ``"tok" > file``
  writes UTF-16) raised UnicodeDecodeError at import - a ValueError, not an
  OSError (the RM-291A class core/vision_token.py already handles).
- F3: no RM-241 header check. A token with an internal CR/LF (env, or a
  file line with a space / control char) was returned as is; urllib then
  raised ``Invalid header value b'<token>'`` on every request, and the push
  loop logs ``[push err Nx] <exc>`` once a second - the token went to
  logs/lcu_agent.log. Refused at resolve time now, by source, never by value.
- F4: a whitespace-only RC_VISION_TOKEN returned "" instead of falling
  through to the config file (core.vision_token falls through), so a stray
  ``set RC_VISION_TOKEN= `` killed the agent while the server ran fine.
- F5: a canonical config file that EXISTS but is unusable fell through to
  the legacy tools/vision_token.txt, which would authenticate with a token
  the server never reads (silent 401s). It is now named and refused, like
  core.vision_token does; the legacy file is read only when the canonical
  one is absent.
"""
from __future__ import annotations

import logging

import pytest

import tools.lcu_agent as agent

SECRET = "s144lcuagentsecretvalue"  # rc-credential-scan: allow-fixture


@pytest.fixture
def paths(tmp_path, monkeypatch):
    canonical = tmp_path / "config" / "vision_token.txt"
    legacy = tmp_path / "tools" / "vision_token.txt"
    canonical.parent.mkdir()
    legacy.parent.mkdir()
    monkeypatch.setattr(agent, "_token_candidates", lambda: [canonical, legacy])
    monkeypatch.delenv("RC_VISION_TOKEN", raising=False)
    return canonical, legacy


def _logged(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


class TestFileProblemsNeverRaise:
    def test_empty_config_returns_blank_and_names_it(self, paths, caplog):
        canonical, _ = paths
        canonical.write_bytes(b"")
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        assert "is empty" in _logged(caplog)

    def test_utf16_config_returns_blank_without_quoting_it(self, paths, caplog):
        canonical, _ = paths
        canonical.write_bytes(SECRET.encode("utf-16"))
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        text = _logged(caplog)
        assert "not UTF-8" in text
        assert SECRET[:6] not in text and "0xff" not in text

    def test_unreadable_config_returns_blank(self, paths, caplog, monkeypatch):
        canonical, _ = paths
        canonical.write_text(SECRET + "\n", encoding="utf-8")

        def _boom(self, *a, **k):
            raise PermissionError(13, "denied " + SECRET)

        monkeypatch.setattr(type(canonical), "read_text", _boom)
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        text = _logged(caplog)
        assert "PermissionError" in text and SECRET not in text

    def test_blank_first_line_is_refused_not_skipped(self, paths, caplog):
        canonical, legacy = paths
        canonical.write_text("\nsecond-line-token\n", encoding="utf-8")
        legacy.write_text("legacy-token\n", encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        assert "first line is empty" in _logged(caplog)


class TestHeaderSafety:
    @pytest.mark.parametrize("raw", [
        "abc\r\n" + SECRET, "abc\n" + SECRET, "abc " + SECRET, "abc\t" + SECRET,
        SECRET + chr(0xE9),
    ])
    def test_unsafe_env_token_is_refused_by_source(self, paths, caplog,
                                                   monkeypatch, raw):
        monkeypatch.setenv("RC_VISION_TOKEN", raw)
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        text = _logged(caplog)
        assert "RC_VISION_TOKEN" in text and SECRET not in text

    def test_unsafe_config_token_is_refused(self, paths, caplog):
        canonical, _ = paths
        canonical.write_text("abc " + SECRET + "\n", encoding="utf-8")
        with caplog.at_level(logging.ERROR, logger="lcu_agent"):
            assert agent._resolve_auth_token() == ""
        text = _logged(caplog)
        assert "header value" in text and SECRET not in text


class TestResolutionOrder:
    def test_env_wins_and_is_stripped(self, paths, monkeypatch):
        canonical, _ = paths
        canonical.write_text("from-config\n", encoding="utf-8")
        monkeypatch.setenv("RC_VISION_TOKEN", "  env-token  ")
        assert agent._resolve_auth_token() == "env-token"

    def test_whitespace_only_env_falls_through_to_config(self, paths,
                                                         monkeypatch):
        canonical, _ = paths
        canonical.write_text("from-config\n", encoding="utf-8")
        monkeypatch.setenv("RC_VISION_TOKEN", "   ")
        assert agent._resolve_auth_token() == "from-config"

    def test_config_first_line_is_read(self, paths):
        canonical, legacy = paths
        canonical.write_text("  from-config  \r\nignored\n", encoding="utf-8")
        legacy.write_text("legacy-token\n", encoding="utf-8")
        assert agent._resolve_auth_token() == "from-config"

    def test_legacy_sibling_used_only_when_canonical_absent(self, paths):
        _, legacy = paths
        legacy.write_text("legacy-token\n", encoding="utf-8")
        assert agent._resolve_auth_token() == "legacy-token"

    def test_nothing_configured_returns_blank(self, paths):
        assert agent._resolve_auth_token() == ""


def test_default_candidates_are_canonical_then_legacy():
    repo_tools = agent.Path(agent.__file__).resolve().parent
    assert agent._token_candidates() == [
        repo_tools.parent / "config" / "vision_token.txt",
        repo_tools / "vision_token.txt",
    ]
