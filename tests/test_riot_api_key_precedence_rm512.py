# arch: regression - RM-512 Riot key precedence is FILE-ONLY; RIOT_API_KEY env never read | section=core | frozen=no
"""RM-512 - RIOT_API_KEY precedence in core/riot_api.py (RM-487 residual).

Adjudicated FILE-ONLY: the key file holds the entitlement-bearing
product-app key, and on Legion a Machine-scope RIOT_API_KEY exists that
DIFFERS from it (measured 2026-10-03, values never printed). These pin both
halves of the decision so a future "make it env-first like RM-487" edit
fails here and has to re-open the policy call instead.
"""

import pytest

import core.riot_api as RA

_FILE_KEY = "RGAPI-file-0000-0000-0000-000000000000"
_ENV_KEY = "RGAPI-envv-1111-1111-1111-111111111111"


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    p = tmp_path / "API-Key-Riot.txt"
    monkeypatch.setattr(RA, "_API_KEY_FILE", p)
    monkeypatch.setenv("RIOT_API_KEY", _ENV_KEY)
    RA.reload_api_key()
    RA._KEY_WARNED_MISSING = True   # squelch the one-shot warning
    yield p
    RA.reload_api_key()


def test_file_key_wins_over_env(keyfile):
    keyfile.write_text(_FILE_KEY, encoding="utf-8")
    assert RA._get_api_key() == _FILE_KEY


def test_env_is_not_a_fallback_when_file_missing(keyfile):
    assert not keyfile.exists()
    assert RA._get_api_key() is None


def test_env_is_not_a_fallback_when_file_invalid(keyfile):
    keyfile.write_text("not-a-key", encoding="utf-8")
    assert RA._get_api_key() is None
