"""RM-509: an unfetched LFS pointer must not pass as an enforced pin.

Default (CI, no LFS fetch by decision): explicit skip with a reason.
RC_REQUIRE_LFS_CONTENT=1: FAIL. Exercised through the real RM-175 helper so the
wiring, not only the policy module, is pinned.
"""
from __future__ import annotations

import pytest

import tests.test_rm175_aram_table_known_wrong as rm175
from tests import _lfs_policy as policy

POINTER = (b"version https://git-lfs.github.com/spec/v1\n"
           b"oid sha256:" + b"0" * 64 + b"\nsize 66000000\n")


@pytest.fixture()
def pointer_table(tmp_path, monkeypatch):
    d = tmp_path / "16.12.1"
    d.mkdir()
    (d / "laning_scenarios_aram.json").write_bytes(POINTER)
    monkeypatch.setattr(rm175, "_TABLE_DIR", tmp_path)
    return tmp_path


def test_default_is_an_explicit_skip(pointer_table, monkeypatch):
    monkeypatch.delenv(policy.REQUIRE_LFS_ENV, raising=False)
    with pytest.warns(UserWarning), pytest.raises(pytest.skip.Exception):
        rm175._table_bytes_or_skip("16.12.1")


def test_required_mode_fails_on_a_pointer(pointer_table, monkeypatch):
    monkeypatch.setenv(policy.REQUIRE_LFS_ENV, "1")
    with pytest.warns(UserWarning), pytest.raises(pytest.fail.Exception):
        rm175._table_bytes_or_skip("16.12.1")


def test_zero_does_not_arm(monkeypatch):
    monkeypatch.setenv(policy.REQUIRE_LFS_ENV, "0")
    assert policy.lfs_required() is False


def test_pointer_detection():
    assert policy.is_pointer_bytes(POINTER)
    assert not policy.is_pointer_bytes(b'{"real": "json"}')
