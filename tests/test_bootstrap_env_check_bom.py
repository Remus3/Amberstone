"""ENV-APIKEY residual (4), verifier nit: tools/bootstrap_env_check.py read
API-Key-Claude.txt with `utf-8`, not `utf-8-sig`.

A key file saved by PowerShell 5.1 `-Encoding UTF8` (or Notepad's "UTF-8
with BOM") starts with EF BB BF. The runtime lookup (core/anthropic_key.py)
drops the BOM and accepts the key, but the diagnostic kept it, so the key
failed the `startswith("sk-ant-")` test and the check reported "API key
format invalid" for a key the app actually loads.

The check runs against a tmp project root (`_PROJECT_ROOT` rebound): every
other section reports MISS there, and only the API key lines are asserted.
`shutil.which` is stubbed to None so the pip probe subprocess never runs.
Every key value here is fake.
"""
from __future__ import annotations

import pytest

from tools import bootstrap_env_check as bec

FAKE_KEY = "sk-ant-TESTONLY111bootstrap"  # rc-credential-scan: allow-fixture
KEY_FILE = "API-Key-Claude.txt"
VALID = "API key format valid"
INVALID = "API key format invalid"


@pytest.fixture
def run_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bec, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bec, "_issues", [])
    monkeypatch.setattr(bec.shutil, "which", lambda *_a, **_kw: None)

    def _run(raw: bytes) -> tuple[str, list]:
        (tmp_path / KEY_FILE).write_bytes(raw)
        bec.main()
        return capsys.readouterr().out, list(bec._issues)

    return _run


def _key_issues(issues: list) -> list:
    return [(kind, label) for kind, label in issues if "API key" in label]


def test_key_file_with_a_utf8_bom_is_reported_valid(run_check):
    out, issues = run_check(b"\xef\xbb\xbf" + FAKE_KEY.encode("ascii") + b"\r\n")
    assert VALID in out
    assert INVALID not in out
    assert _key_issues(issues) == []


def test_key_file_without_a_bom_is_still_reported_valid(run_check):
    out, issues = run_check(FAKE_KEY.encode("ascii") + b"\n")
    assert VALID in out
    assert _key_issues(issues) == []


def test_junk_key_file_is_still_reported_invalid(run_check):
    out, issues = run_check(b"\xef\xbb\xbfnot-a-key\n")
    assert INVALID in out
    assert ("ERROR", INVALID) in issues


def test_the_key_value_never_reaches_the_report(run_check):
    out, _ = run_check(b"\xef\xbb\xbf" + FAKE_KEY.encode("ascii") + b"\n")
    assert FAKE_KEY not in out
