"""S144-T-697 (lane 8 true-audit): core/mayhem_augment_source.py hardening.

Each test pins one measured weakness of the RM-866 CommunityDragon kiwi.bin
extract:

* An overflowing number literal (``1e999``) is NOT one of the three literals
  ``parse_constant`` sees (NaN / Infinity / -Infinity), so the shared
  NaN-rejecting fetcher hands back ``float('inf')``; ``_per_rank`` accepted
  it and ``json.dumps`` (allow_nan default True) wrote a bare ``Infinity``
  token into the data file, which is not JSON.
* ``re.match`` with a ``$`` anchor accepts a trailing newline, so
  ``"16.21.1\\n"`` passed as an RC patch (a directory name with a newline)
  and ``"16.21\\n"`` as a CommunityDragon dir (a URL with a newline).
* ``current.txt`` saved with a UTF-8 BOM (PowerShell 5.1 ``-Encoding UTF8``)
  read as ``"\\ufeff16.21.1"`` and was refused as junk.
* The CLI caught only AugmentSourceError / ValueError: a missing
  ``current.txt`` or a failed write raised a raw traceback.
* ``--ids-from`` was parsed AFTER the ~13.7 MB fetch and the write, outside
  the try, so a missing / junk ids file raised a traceback after the data
  file had already been replaced; a scalar string iterated its characters,
  and ``true`` counted as id 1.

No test touches the network: every fetch goes through a monkeypatched
``_http_get``.
"""
from __future__ import annotations

import json
import math

import pytest

import core.mayhem_augment_source as M
from core import augment_external_source as _aes

_AUG = "Maps/ModeSpecificData/Augments"


def _bin(n_rows: int, extra_values=None) -> dict:
    """A bin with ``n_rows`` resolvable augments, each with one value; the
    first row's DataValues get ``extra_values`` appended when given."""
    out: dict = {}
    for i in range(n_rows):
        path = f"{_AUG}/A{i}"
        spell = f"{path}/Augment_A{i}"
        out[path] = {
            "__type": "AugmentData",
            "AugmentPlatformId": 5000 + i,
            "AugmentNameId": f"A{i}",
            "RootSpell": spell,
        }
        dvs = [{"name": "V", "values": [float(i)] * 7}]
        if i == 0 and extra_values is not None:
            dvs.extend(extra_values)
        out[spell] = {"__type": "SpellObject", "mSpell": {"DataValues": dvs}}
    return out


def _floor_bin(extra_values=None) -> dict:
    return _bin(max(M.MIN_ROWS, M.MIN_WITH_VALUES), extra_values)


# --- non-finite magnitudes ---------------------------------------------------


def test_overflowing_literal_through_the_real_parser_is_null_not_infinity(tmp_path, monkeypatch):
    # The real fetch path: the shared guard lets 1e999 through as inf.
    raw = json.loads('{"name": "Huge", "values": [1e999, 1, 1, 1, 1, 1, 1]}',
                     parse_constant=_aes._reject_non_finite)
    assert math.isinf(raw["values"][0])  # the premise: the guard misses it
    monkeypatch.setattr(M, "_http_get", lambda url, timeout_s: _floor_bin([raw]))
    snap = M.refresh("99.1.1", data_dir=tmp_path)
    entry = snap["augments"]["5000"]["values"][1]
    assert entry == {"name": "Huge", "per_rank": None}
    data = (tmp_path / "99.1.1" / M.FILENAME).read_bytes()
    assert b"Infinity" not in data and b"NaN" not in data

    def _strict(tok):
        raise AssertionError(f"non-JSON literal {tok!r} in the written file")

    json.loads(data, parse_constant=_strict)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_rank_value_makes_the_entry_null(bad):
    assert M._per_rank([1.0, bad, 1.0]) is None


def test_serialize_refuses_a_non_finite_number_rather_than_writing_invalid_json():
    snap = {"schema": 1, "augments": {"1": {"values": [
        {"name": "X", "per_rank": [float("inf")]}]}}}
    with pytest.raises(ValueError):
        M.serialize(snap)


def test_finite_values_are_still_kept():
    assert M._per_rank([0, 1.5, -2, 10 ** 6]) == [0, 1.5, -2, 10 ** 6]


# --- trailing-newline patch strings ------------------------------------------


@pytest.mark.parametrize("bad", ["16.21.1\n", "16.21.1\r\n", " 16.21.1", "16.21.1 "])
def test_an_rc_patch_with_surrounding_whitespace_is_refused(bad):
    with pytest.raises(ValueError):
        M.cdragon_patch_for(bad)
    with pytest.raises(ValueError):
        M.output_path(bad)


@pytest.mark.parametrize("bad", ["16.21\n", "latest\n", "pbe\n"])
def test_a_cdragon_dir_with_a_trailing_newline_is_refused(bad):
    with pytest.raises(ValueError):
        M.kiwi_bin_url(bad)


def test_refresh_with_a_newline_patch_fetches_and_writes_nothing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(M, "_http_get", lambda url, timeout_s: calls.append(url))
    with pytest.raises(ValueError):
        M.refresh("99.1.1\n", data_dir=tmp_path)
    with pytest.raises(ValueError):
        M.refresh("99.1.1", cdragon_patch="99.1\n", data_dir=tmp_path)
    assert calls == []
    assert list(tmp_path.iterdir()) == []


# --- current.txt -------------------------------------------------------------


def test_live_patch_tolerates_a_utf8_bom(tmp_path, monkeypatch):
    pf = tmp_path / "current.txt"
    pf.write_bytes(b"\xef\xbb\xbf16.21.1\r\n")
    monkeypatch.setattr(M, "_PATCH_FILE", pf)
    assert M.live_patch() == "16.21.1"


# --- the CLI fails clean -------------------------------------------------------


def _no_fetch(calls):
    def fake(url, timeout_s):
        calls.append(url)
        return _floor_bin()
    return fake


def test_cli_missing_current_txt_is_a_clean_failure(tmp_path, monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(M, "_PATCH_FILE", tmp_path / "absent.txt")
    monkeypatch.setattr(M, "_DS_DATA_DIR", tmp_path)
    monkeypatch.setattr(M, "_http_get", _no_fetch(calls))
    assert M.main([]) == 1
    assert capsys.readouterr().err.startswith("FAILED:")
    assert calls == []


def test_cli_write_failure_is_a_clean_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "_DS_DATA_DIR", tmp_path)
    monkeypatch.setattr(M, "_http_get", _no_fetch([]))

    def boom(path, snap):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(M, "write_snapshot", boom)
    assert M.main(["--patch", "99.1.1"]) == 1
    assert capsys.readouterr().err.startswith("FAILED:")


@pytest.mark.parametrize("content", [
    None,                              # file absent
    b"{not json",
    b'"12317"',                        # a bare string would iterate chars
    b"5",
    b"null",
    b'[1, "x"]',
    b"[true]",
    b"[1.5]",
    b"[-1]",
    b'["-1"]',
    b'[" 12"]',
    b'{"augments": {"12a": {}}}',
    b'{"augments": 7}',
    b"\xff\xfe",
])
def test_cli_junk_ids_file_fails_before_any_fetch_or_write(tmp_path, monkeypatch, capsys, content):
    calls: list = []
    monkeypatch.setattr(M, "_DS_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(M, "_http_get", _no_fetch(calls))
    ids = tmp_path / "ids.json"
    if content is not None:
        ids.write_bytes(content)
    assert M.main(["--patch", "99.1.1", "--ids-from", str(ids)]) == 1
    assert capsys.readouterr().err.startswith("FAILED:")
    assert calls == []
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("content,expected", [
    (b"[5000, 5001, 999999]", [5000, 5001, 999999]),
    (b'["5000", "5001"]', [5000, 5001]),
    (b'{"5000": {}, "5002": {}}', [5000, 5002]),
    (b'{"augments": {"5000": {}}, "schema": 1}', [5000]),
    (b'\xef\xbb\xbf[5000]', [5000]),
])
def test_ids_file_shapes_still_parse(tmp_path, content, expected):
    ids = tmp_path / "ids.json"
    ids.write_bytes(content)
    assert M._ids_from(ids) == expected


def test_cli_subset_census_still_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(M, "_DS_DATA_DIR", tmp_path)
    monkeypatch.setattr(M, "_http_get", _no_fetch([]))
    ids = tmp_path / "ids.json"
    ids.write_bytes(b"[5000, 5001, 999999]")
    assert M.main(["--patch", "99.1.1", "--ids-from", str(ids)]) == 0
    out = capsys.readouterr().out
    assert "subset ids 3 with_row 2 with_values 2" in out
    assert (tmp_path / "99.1.1" / M.FILENAME).exists()
