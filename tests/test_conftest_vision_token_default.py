"""RM-383: the suite supplies a vision token ONLY where no real one exists.

WHY THIS EXISTS. `core/vision_token.py` raises at IMPORT when neither
`RC_VISION_TOKEN` nor `config/vision_token.txt` is present - deliberately, so a
misconfigured deploy fails loud. The file is gitignored, so every worktree and
every hermetic checkout lacks it, and the suite went red there (measured
2026-09-17 in a fresh agent worktree: `tests/test_gated_live_probe_relay_auth.py`
3 failed, `RuntimeError: vision_token: no token configured`) while the primary
checkout stayed green. CI got its own dummy in the workflow env (LEDGER 1357);
a local worktree had nothing.

`tests/conftest.py` now sets a throwaway default at IMPORT, before collection,
under exactly one condition: the env var is absent (or blank, which the resolver
also treats as absent) AND the config file is absent. The four env x file
combinations are each asserted below, because the failure this must never have
is the inverse one: an env var set by the suite BEATS the config file in the
resolver, so a default applied in the primary checkout would silently swap the
operator's real token for a dummy in every test that reads it.

The production resolver is untouched, so the hard failure for the real runtime
path is preserved.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from tests import conftest as rc_conftest

_REPO = Path(__file__).resolve().parent.parent
_REAL_TOKEN_SHAPE = re.compile(r"\A[0-9a-fA-F]{32}\Z")


def _config(tmp_path: Path, present: bool) -> Path:
    cfg = tmp_path / "config" / "vision_token.txt"
    if present:
        cfg.parent.mkdir(parents=True)
        cfg.write_text("operator-real-token-stand-in\n", encoding="utf-8")
    return cfg


def test_env_absent_file_absent_applies_the_default(tmp_path):
    environ: dict = {}
    applied = rc_conftest._apply_vision_token_test_default(environ, _config(tmp_path, False))
    assert applied is True
    assert environ["RC_VISION_TOKEN"] == rc_conftest._VISION_TOKEN_TEST_DEFAULT


def test_env_absent_file_present_never_overrides_the_config(tmp_path):
    """The primary checkout's case. Setting the env here would beat the file."""
    environ: dict = {}
    applied = rc_conftest._apply_vision_token_test_default(environ, _config(tmp_path, True))
    assert applied is False
    assert "RC_VISION_TOKEN" not in environ


def test_env_present_file_absent_keeps_the_env(tmp_path):
    environ = {"RC_VISION_TOKEN": "operator-env-token"}
    applied = rc_conftest._apply_vision_token_test_default(environ, _config(tmp_path, False))
    assert applied is False
    assert environ == {"RC_VISION_TOKEN": "operator-env-token"}


def test_env_present_file_present_keeps_both(tmp_path):
    environ = {"RC_VISION_TOKEN": "operator-env-token"}
    cfg = _config(tmp_path, True)
    applied = rc_conftest._apply_vision_token_test_default(environ, cfg)
    assert applied is False
    assert environ == {"RC_VISION_TOKEN": "operator-env-token"}
    assert cfg.read_text(encoding="utf-8") == "operator-real-token-stand-in\n"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_env_counts_as_absent_like_the_resolver(tmp_path, blank):
    environ = {"RC_VISION_TOKEN": blank}
    applied = rc_conftest._apply_vision_token_test_default(environ, _config(tmp_path, False))
    assert applied is True
    assert environ["RC_VISION_TOKEN"] == rc_conftest._VISION_TOKEN_TEST_DEFAULT


def test_the_helper_never_writes_the_config_file(tmp_path):
    cfg = _config(tmp_path, False)
    rc_conftest._apply_vision_token_test_default({}, cfg)
    assert not cfg.exists()
    assert not cfg.parent.exists()


def test_default_is_not_shaped_like_a_real_token():
    """Same fence as tests/test_ci_vision_token_env.py: never a pasted real one."""
    value = rc_conftest._VISION_TOKEN_TEST_DEFAULT
    assert value.strip()
    assert not _REAL_TOKEN_SHAPE.match(value)


def test_conftest_checks_the_same_file_the_resolver_reads():
    """Anchor: a typo in the conftest path would apply the default in main."""
    import core.vision_token as vt

    expected = (_REPO / "config" / "vision_token.txt").resolve()
    assert rc_conftest._VISION_TOKEN_CONFIG_PATH.resolve() == vt._CONFIG_PATH.resolve()
    assert rc_conftest._VISION_TOKEN_CONFIG_PATH.resolve() == expected


def test_import_time_decision_matches_this_tree():
    """Live check of what conftest actually did in THIS checkout.

    In the primary checkout (file present) nothing is applied and the resolver
    reports `config` unless the operator set the env; in a worktree or a
    hermetic checkout (file absent, env absent) the default is applied.
    """
    applied = rc_conftest._VISION_TOKEN_DEFAULT_APPLIED
    file_present = rc_conftest._VISION_TOKEN_CONFIG_PATH.exists()
    if file_present:
        assert applied is False
        assert os.environ.get("RC_VISION_TOKEN") != rc_conftest._VISION_TOKEN_TEST_DEFAULT
    if applied:
        assert not file_present
        assert os.environ.get("RC_VISION_TOKEN") == rc_conftest._VISION_TOKEN_TEST_DEFAULT


def test_resolver_imports_in_this_tree():
    """The RM-383 regression itself: collection-time import must not raise."""
    import core.vision_token as vt

    assert vt.get_vision_token()
    assert vt.get_vision_token_source() in ("env", "config")
