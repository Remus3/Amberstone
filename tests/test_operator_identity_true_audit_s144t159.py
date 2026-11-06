"""True-audit s144 cycle 159: core/operator_identity.py.

Every test points the module at a tmp_path config and clears the three env
overrides, so no test reads the live install's identity. All Riot IDs here are
synthetic (RM-906).
"""
from __future__ import annotations

import json
import logging

import pytest

from core import operator_identity as oi

_ENV = ("RC_OPERATOR_GAME_NAME", "RC_OPERATOR_ACCOUNTS", "RC_RIOT_PLATFORM")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "operator_identity.json"
    monkeypatch.setattr(oi, "_CONFIG", path)
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)
    getattr(oi, "_WARNED", set()).clear()

    def write(blob, *, raw: bytes | None = None):
        if raw is None:
            raw = json.dumps(blob).encode("utf-8")
        path.write_bytes(raw)
        return path

    return write


# --- characterization: the shipped contract stays -------------------------

def test_unconfigured_install_reads_placeholder_and_no_accounts(cfg):
    assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
    assert oi.accounts() == []
    assert oi.platform() == oi.DEFAULT_PLATFORM
    assert oi.is_configured() is False


def test_env_wins_over_config(cfg, monkeypatch):
    cfg({"game_name": "FileName", "accounts": ["File#AAA"], "platform": "KR"})
    monkeypatch.setenv("RC_OPERATOR_GAME_NAME", "EnvName")
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "Env#BBB, Env2#CCC")
    monkeypatch.setenv("RC_RIOT_PLATFORM", "euw1")
    assert oi.game_name() == "EnvName"
    assert oi.accounts() == [("Env", "BBB"), ("Env2", "CCC")]
    assert oi.platform() == "EUW1"


def test_config_values_read_when_env_absent(cfg):
    cfg({"game_name": "FileName", "accounts": ["File#AAA", "File#BBB"],
         "platform": "euw1"})
    assert oi.game_name() == "FileName"
    assert oi.accounts() == [("File", "AAA"), ("File", "BBB")]
    assert oi.platform() == "EUW1"
    assert oi.is_configured() is True


def test_non_alnum_platform_is_ignored(cfg, monkeypatch):
    monkeypatch.setenv("RC_RIOT_PLATFORM", "NA1/../x")
    assert oi.platform() == oi.DEFAULT_PLATFORM


# --- F1: a BOM-prefixed config (PowerShell 5.1 Out-File) must still read ---

def test_bom_prefixed_config_is_read_not_silently_unconfigured(cfg):
    body = json.dumps({"game_name": "BomName", "accounts": ["Bom#AAA"],
                       "platform": "KR"}).encode("utf-8")
    cfg(None, raw=b"\xef\xbb\xbf" + body)
    assert oi.game_name() == "BomName"
    assert oi.accounts() == [("Bom", "AAA")]
    assert oi.platform() == "KR"


# --- F2: a non-string game_name is not stringified into a junk name --------

@pytest.mark.parametrize("bad", [None, 0, 123, True, [], ["x"], {"a": 1}])
def test_non_string_game_name_reads_as_unconfigured(cfg, bad):
    cfg({"game_name": bad})
    assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
    assert oi.is_configured() is False


# --- F3: a junk accounts value never raises and never iterates characters --

@pytest.mark.parametrize("bad", [5, True, 1.5, {"Name#TAG": 1}])
def test_non_list_accounts_value_never_raises(cfg, bad):
    cfg({"accounts": bad})
    assert oi.accounts() == []


def test_string_accounts_value_reads_as_the_comma_list_form(cfg):
    cfg({"accounts": "Alpha#AAA, Beta#BBB"})
    assert oi.accounts() == [("Alpha", "AAA"), ("Beta", "BBB")]


def test_non_string_items_in_accounts_list_are_skipped(cfg):
    cfg({"accounts": [None, 7, ["Alpha#AAA"], "Beta#BBB"]})
    assert oi.accounts() == [("Beta", "BBB")]


# --- F4: whitespace-only env is UNSET, as game_name and platform treat it --

def test_blank_accounts_env_falls_back_to_config(cfg, monkeypatch):
    cfg({"accounts": ["File#AAA"]})
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "   ")
    assert oi.accounts() == [("File", "AAA")]


# --- F5: Riot IDs are case-insensitive; one account is pulled once ---------

def test_case_variants_of_one_riot_id_dedupe_keeping_first_spelling(cfg, monkeypatch):
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "Alpha#AAA,alpha#aaa,ALPHA#Aaa,Beta#BBB")
    assert oi.accounts() == [("Alpha", "AAA"), ("Beta", "BBB")]


# --- F6: a tagline can never contain '#' or a control character -----------

@pytest.mark.parametrize("bad", ["Alpha#AA#A", "Al\npha#AAA", "Alpha#A\tA", "Alpha#AAA\x00",
                                 "Al\x85pha#AAA", "Alpha#AA\x9f", "\ud800#TAG", "Alpha#\udc00"])
def test_malformed_riot_id_is_rejected(cfg, bad):
    # Config path: a process environment cannot carry a NUL on Windows.
    cfg({"accounts": [bad, "Beta#BBB"]})
    assert oi.accounts() == [("Beta", "BBB")]


def test_interior_space_in_game_name_is_kept(cfg, monkeypatch):
    # Riot game names may contain spaces; only the ends are trimmed.
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", " Two Words # TAG ")
    assert oi.accounts() == [("Two Words", "TAG")]


# --- F7: a non-string or digit-leading platform never becomes an id prefix -

@pytest.mark.parametrize("bad", [True, 1, 1.0, ["NA1"], "1", "123"])
def test_junk_platform_value_falls_back_to_default(cfg, bad):
    cfg({"platform": bad})
    assert oi.platform() == oi.DEFAULT_PLATFORM


def test_junk_env_platform_falls_through_to_config(cfg, monkeypatch):
    cfg({"platform": "kr"})
    monkeypatch.setenv("RC_RIOT_PLATFORM", "9")
    assert oi.platform() == "KR"


# --- F8: a full Riot ID given as the game name joins on the name part ------

def test_full_riot_id_in_game_name_env_uses_the_name_part(cfg, monkeypatch):
    monkeypatch.setenv("RC_OPERATOR_GAME_NAME", "EnvName#TAG")
    assert oi.game_name() == "EnvName"


def test_full_riot_id_in_game_name_config_uses_the_name_part(cfg):
    cfg({"game_name": "FileName#TAG"})
    assert oi.game_name() == "FileName"


@pytest.mark.parametrize("bad", ["Na\x85me", "\ud800", "Na\x07me"])
def test_unsafe_game_name_in_config_reads_as_unconfigured(cfg, bad):
    cfg({"game_name": bad})
    assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
    assert oi.is_configured() is False


def test_non_bmp_and_accented_names_are_kept(cfg):
    # Only controls and lone surrogates are refused; real Unicode names pass.
    cafe = "Caf" + chr(0xE9)
    cfg({"game_name": cafe, "accounts": [cafe + "#EUW", "Na\U0001f600#TAG"]})
    assert oi.game_name() == cafe
    assert oi.accounts() == [(cafe, "EUW"), ("Na\U0001f600", "TAG")]


def test_tag_only_game_name_env_falls_through_to_config(cfg, monkeypatch):
    cfg({"game_name": "FileName"})
    monkeypatch.setenv("RC_OPERATOR_GAME_NAME", "#TAG")
    assert oi.game_name() == "FileName"


# --- F9: a PRESENT but unreadable config is logged, once, without content --

def test_malformed_config_logs_one_warning_without_its_content(cfg, caplog):
    cfg(None, raw=b'{"game_name": "SecretName", ')
    with caplog.at_level(logging.WARNING, logger=oi.__name__):
        assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
        assert oi.accounts() == []
        assert oi.platform() == oi.DEFAULT_PLATFORM
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "SecretName" not in warnings[0].getMessage()
    assert "operator_identity.json" in warnings[0].getMessage()


def test_non_object_config_logs_a_warning(cfg, caplog):
    cfg(["Alpha#AAA"])
    with caplog.at_level(logging.WARNING, logger=oi.__name__):
        assert oi.accounts() == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_deeply_nested_config_never_raises(cfg, caplog):
    # json.loads raises RecursionError, not ValueError, on deep nesting.
    cfg(None, raw=b"[" * 200000)
    with caplog.at_level(logging.WARNING, logger=oi.__name__):
        assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
        assert oi.accounts() == []
    assert any(r.levelno >= logging.WARNING for r in caplog.records)


def test_wrong_typed_field_warns_once_and_null_is_silent(cfg, caplog):
    cfg({"accounts": 5, "game_name": None, "platform": None})
    with caplog.at_level(logging.WARNING, logger=oi.__name__):
        assert oi.accounts() == []
        assert oi.accounts() == []
        assert oi.game_name() == oi.PLACEHOLDER_GAME_NAME
        assert oi.platform() == oi.DEFAULT_PLATFORM
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "accounts" in warnings[0]


def test_env_set_skips_reading_the_config(cfg, monkeypatch):
    def boom():
        raise AssertionError("config read although env was set")
    monkeypatch.setattr(oi, "_blob", boom)
    monkeypatch.setenv("RC_OPERATOR_GAME_NAME", "EnvName")
    monkeypatch.setenv("RC_OPERATOR_ACCOUNTS", "Env#AAA")
    monkeypatch.setenv("RC_RIOT_PLATFORM", "KR")
    assert (oi.game_name(), oi.accounts(), oi.platform()) == ("EnvName", [("Env", "AAA")], "KR")


def test_normalize_platform_contract():
    assert oi.normalize_platform(" euw1 ") == "EUW1"
    for bad in ("", "  ", "1", "NA-1", "N A", chr(0x399) * 2, None, 1, True):
        assert oi.normalize_platform(bad) == ""


@pytest.mark.parametrize("value, want", [
    ("euw1", "EUW1"), (True, "NA1"), ("1", "NA1"), (["KR"], "NA1"), (None, "NA1")])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_y01_reader_platform_uses_the_module_rule(tmp_path, monkeypatch, value, want, bom):
    # tools/gated_y01_chain_report._platform re-reads another checkout's config;
    # it must agree with platform() on every value, BOM file included.
    from tools import gated_y01_chain_report as y
    monkeypatch.delenv("RC_RIOT_PLATFORM", raising=False)
    (tmp_path / "config").mkdir()
    body = json.dumps({"platform": value}).encode("utf-8")
    (tmp_path / "config" / "operator_identity.json").write_bytes(bom + body)
    assert y._platform(tmp_path) == want


def test_missing_config_is_silent(cfg, caplog):
    with caplog.at_level(logging.DEBUG, logger=oi.__name__):
        assert oi.is_configured() is False
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
