"""RM-230 - lcu/lcu_client.py must reject an out-of-range port and an empty
password from the LCU lockfile, on BOTH parse sites (connect() and the
rotation path _refresh_conn_if_changed()).

Before: `int(parts[2])` accepted "99999" (every later request went to an
unbindable port) and a torn read with an empty password field produced a
Basic header that authenticates nothing. Mirrors the guard
game_reader/poller.py:_ensure_lcu got in lane 8 cycle 14.
"""
from __future__ import annotations

import os

import pytest

from lcu import lcu_client


def _client_with_lockfile(tmp_path, monkeypatch, text):
    lf = tmp_path / "lockfile"
    lf.write_text(text, encoding="utf-8")
    monkeypatch.setattr(lcu_client, "_LOCKFILE_PATHS", [lf])
    return lcu_client.LcuClient(), lf


@pytest.mark.parametrize("text", [
    "LeagueClient:1234:99999:pw:https",   # above 65535
    "LeagueClient:1234:0:pw:https",       # zero
    "LeagueClient:1234:-5:pw:https",      # negative
    "LeagueClient:1234:+443:pw:https",    # int() accepts, not all digits
    "LeagueClient:1234:54321::https",     # empty password
    "LeagueClient:1234:54321:   :https",  # whitespace password
])
def test_connect_rejects_bad_fields(tmp_path, monkeypatch, text):
    c, _ = _client_with_lockfile(tmp_path, monkeypatch, text)
    assert c.connect() is False
    assert c._port is None
    assert c._auth is None


def test_connect_accepts_valid_lockfile(tmp_path, monkeypatch):
    c, lf = _client_with_lockfile(
        tmp_path, monkeypatch, "LeagueClient:1234:54321:secret:https")
    assert c.connect() is True
    assert c._port == 54321
    assert c._auth


@pytest.mark.parametrize("text", [
    "LeagueClient:1234:99999:pw:https",
    "LeagueClient:1234:54321::https",
])
def test_rotation_rejects_bad_fields_and_keeps_good_creds(tmp_path, monkeypatch, text):
    c, lf = _client_with_lockfile(
        tmp_path, monkeypatch, "LeagueClient:1234:54321:secret:https")
    assert c.connect() is True
    good_port, good_auth = c._port, c._auth
    lf.write_text(text, encoding="utf-8")
    st = lf.stat()
    os.utime(lf, (st.st_atime, st.st_mtime + 10))
    c._refresh_conn_if_changed()
    assert (c._port, c._auth) == (good_port, good_auth)
