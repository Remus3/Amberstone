"""Tests for the CREDENTIAL arm of the PostToolUse Edit|Write hook.

Closes defect D2 of `docs/specs/2026-09-20-shared-git-root-bucket-rc-share-scan.md`:
`tools/edit_lint_check.py` is registered at `.claude/settings.json:32` as a
PostToolUse `Edit|Write` hook and is **the only RC control whose population
already includes UNTRACKED files** - it reads the exact file just written
(`$CLAUDE_FILE_PATHS`) and already scans its CONTENT for banned glyphs. Until
this arm landed it evaluated ZERO credential patterns, which is the binding
constraint recorded in that report's Q2 and Q3.

THE SINGLE MOST IMPORTANT PROPERTY PINNED HERE: the arm NEVER emits a matched
value. `test_hook_output_never_contains_the_matched_value` and
`test_finding_carries_no_value_field` are the two assertions that protect it.
A gate that prints the secret it caught has copied that secret somewhere new.

FIXTURE SAFETY: every credential-shaped literal below is assembled at RUNTIME
by `_fake()` from an inert prefix plus an obviously-fake body (a run of `A`s,
or a body no issuer would ever mint). No whole credential-shaped literal is
committed to this tracked, PUBLIC repository.
`test_this_test_file_does_not_trip_the_arm` proves that mechanically rather
than by assertion, and it is the test to keep green if this file is edited.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import credential_patterns, edit_lint_check  # noqa: E402


def _fake(prefix: str, body: str) -> str:
    """Join a real-SHAPED prefix to an obviously-FAKE body, at runtime.

    Neither half matches any pattern on its own, so this source file stays
    clean while the assembled value still exercises the detector.
    """
    return prefix + body


# An obviously-fake body for the classes whose shape forbids a run of one char.
_FAKE_WORD = "FAKEfake0123456789abcd"

# class name -> a synthetic literal of that shape. Bodies are deliberately
# degenerate (runs of `A`) so they cannot collide with any issued credential.
_FAKE_BY_CLASS = {
    "anthropic_admin": _fake("sk-ant-admin", "A" * 40),
    "anthropic": _fake("sk-ant-api03-", "A" * 40),
    "openai": _fake("sk-proj-", "A" * 40),
    "aws_access_key_id": _fake("AKIA", "A" * 16),
    "github_token": _fake("ghp_", "A" * 36),
    "github_pat": _fake("github_pat_", "A" * 44),
    "google_api_key": _fake("AIza", "A" * 35),
    "google_oauth": _fake("ya29.", "A" * 30),
    "slack_token": _fake("xoxb-", "A" * 24),
    "riot_api_key": _fake("RGAPI-", "A" * 30),
    "private_key_pem": _fake("-----BEGIN PRIVATE ", "KEY-----"),
    "bearer_token": _fake("Bearer ", "A" * 32),
    "connection_string_password": (
        "postgres://svc" + ":" + _FAKE_WORD + "@" + "db.invalid:5432/rc"
    ),
    "jwt": _fake("eyJ", "A" * 20) + "." + _fake("eyJ", "B" * 20) + "." + "C" * 20,
    "generic_secret_assignment": "api_key" + " = " + '"' + _FAKE_WORD + '"',
}

_REQUIRED_CLASSES = frozenset(_FAKE_BY_CLASS)


# --------------------------------------------------------------------------
# family coverage
# --------------------------------------------------------------------------


def test_every_required_pattern_class_is_registered():
    missing = _REQUIRED_CLASSES - set(credential_patterns.PATTERN_CLASSES)
    assert not missing, f"pattern classes missing from the arm: {sorted(missing)}"


@pytest.mark.parametrize("cls", sorted(_FAKE_BY_CLASS))
def test_each_pattern_family_is_detected(cls):
    findings = credential_patterns.scan_text(f"value = {_FAKE_BY_CLASS[cls]}\n")
    assert cls in {f.pattern_class for f in findings}, (
        f"{cls} was not detected"
    )


def test_every_pattern_class_has_a_prefilter_row():
    """A family with no trigger row, or a stale one, is silently blinded."""
    assert set(credential_patterns.PATTERN_CLASSES) == set(
        credential_patterns._TRIGGERS
    )


@pytest.mark.parametrize("cls", sorted(_FAKE_BY_CLASS))
def test_prefilter_arms_the_family_it_gates(cls):
    """The trigger literal must really occur inside a match of that family."""
    lowered = _FAKE_BY_CLASS[cls].lower()
    assert any(
        literal in lowered for literal in credential_patterns._TRIGGERS[cls]
    ), f"{cls} prefilter would skip its own family"


def test_anthropic_admin_is_its_own_named_class():
    """Not accidental prefix-subsumption under the generic `sk-ant-` arm.

    The report (Q2) found RC's only admin-key coverage was a side effect of a
    redactor sharing the `sk-ant-` prefix, and recorded that accidental
    coverage is not coverage. This pins the admin family by NAME.
    """
    findings = credential_patterns.scan_text(_FAKE_BY_CLASS["anthropic_admin"])
    classes = {f.pattern_class for f in findings}
    assert "anthropic_admin" in classes
    assert "anthropic_admin" in credential_patterns.PATTERN_CLASSES


def test_riot_api_key_family_exists():
    """RC's own provider had neither a scanner nor a redactor (report Q2)."""
    findings = credential_patterns.scan_text(_FAKE_BY_CLASS["riot_api_key"])
    assert "riot_api_key" in {f.pattern_class for f in findings}


# --------------------------------------------------------------------------
# clean files stay clean
# --------------------------------------------------------------------------


def test_clean_text_produces_no_findings():
    clean = (
        "def add(a, b):\n"
        "    # ordinary code with a url https://example.invalid/path\n"
        "    return a + b\n"
    )
    assert credential_patterns.scan_text(clean) == []


def test_placeholder_values_are_not_reported_as_generic_secrets():
    for placeholder in (
        'api_key = "YOUR_API_KEY_GOES_HERE"',
        'password = "changeme_changeme_changeme"',
        'token = "xxxxxxxxxxxxxxxxxxxxxxxx"',
    ):
        findings = credential_patterns.scan_text(placeholder + "\n")
        assert "generic_secret_assignment" not in {
            f.pattern_class for f in findings
        }, placeholder


def test_this_test_file_does_not_trip_the_arm():
    """The fixture file must not itself be a credential-shaped literal."""
    findings = credential_patterns.scan_file(Path(__file__))
    assert findings == [], [
        (f.line_no, f.pattern_class, f.arm) for f in findings
    ]


def test_patterns_module_does_not_trip_the_arm():
    findings = credential_patterns.scan_file(
        REPO_ROOT / "tools" / "credential_patterns.py"
    )
    assert findings == [], [
        (f.line_no, f.pattern_class, f.arm) for f in findings
    ]


# --------------------------------------------------------------------------
# NO VALUE EVER LEAVES THE SCANNER
# --------------------------------------------------------------------------


def test_finding_carries_no_value_field():
    """Structural guarantee: the record has nowhere to put a value."""
    findings = credential_patterns.scan_text(_FAKE_BY_CLASS["anthropic"])
    assert findings
    assert set(findings[0]._fields) == {"line_no", "pattern_class", "arm"}


def test_format_findings_emits_only_path_line_and_class():
    findings = credential_patterns.scan_text(_FAKE_BY_CLASS["anthropic"])
    rendered = "\n".join(credential_patterns.format_findings("some/file.py", findings))
    assert "some/file.py" in rendered
    assert "anthropic" in rendered
    assert "A" * 8 not in rendered
    assert "sk-ant-" not in rendered


def test_hook_output_never_contains_the_matched_value(tmp_path, monkeypatch, capsys):
    """THE requirement-1 test. Run the real hook; assert the value is absent."""
    target = tmp_path / "leaky.txt"
    target.write_text(
        "config line " + _FAKE_BY_CLASS["anthropic_admin"] + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))
    edit_lint_check.main()
    err = capsys.readouterr().err

    # It fired, and it said WHERE.
    assert "CREDENTIAL" in err.upper()
    assert "leaky.txt" in err
    assert "anthropic_admin" in err

    # It did NOT say WHAT.
    assert "A" * 8 not in err
    assert "sk-ant-" not in err
    assert "sk-ant-admin" not in err


def test_hook_reports_the_line_number(tmp_path, monkeypatch, capsys):
    target = tmp_path / "leaky2.txt"
    target.write_text(
        "clean\nclean\n" + _FAKE_BY_CLASS["riot_api_key"] + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))
    edit_lint_check.main()
    err = capsys.readouterr().err
    assert ":3" in err
    assert "riot_api_key" in err
    assert "RGAPI-" not in err


# --------------------------------------------------------------------------
# line-wrap evasion
# --------------------------------------------------------------------------


def test_adjacent_string_literal_split_is_detected():
    head = _fake("sk-ant-", "api")  # too short to match on its own
    wrapped = 'KEY = ("' + head + '"\n       "' + "A" * 30 + '")\n'
    # control: the normal per-line arm must NOT see it
    line_arm = [f for f in credential_patterns.scan_text(wrapped) if f.arm == "line"]
    assert line_arm == []
    # the dewrap arm must
    dewrap = [f for f in credential_patterns.scan_text(wrapped) if f.arm == "dewrap"]
    assert {f.pattern_class for f in dewrap} == {"anthropic"}
    assert dewrap[0].line_no == 1


def test_backslash_continuation_split_is_detected():
    wrapped = "export K=" + _fake("sk-ant-", "api") + "\\\n" + "A" * 30 + "\n"
    findings = credential_patterns.scan_text(wrapped)
    assert "anthropic" in {f.pattern_class for f in findings}
    assert any(f.arm == "dewrap" for f in findings)


def test_unrelated_adjacent_lines_are_not_joined():
    """The dewrap join is narrow: no quote pairing, no join, no false hit."""
    text = 'a = "sk-ant-"\nb = "' + "A" * 30 + '"\n'
    dewrap = [f for f in credential_patterns.scan_text(text) if f.arm == "dewrap"]
    assert dewrap == []


# --------------------------------------------------------------------------
# fixture pragma
# --------------------------------------------------------------------------


def test_pragma_exempts_a_single_line():
    line = _FAKE_BY_CLASS["github_token"]
    assert credential_patterns.scan_text(line + "\n")  # control: it fires
    exempted = line + "  # " + credential_patterns.PRAGMA + "\n"
    assert credential_patterns.scan_text(exempted) == []


def test_pragma_does_not_exempt_the_next_line():
    exempt = _FAKE_BY_CLASS["github_token"] + "  # " + credential_patterns.PRAGMA
    following = _FAKE_BY_CLASS["aws_access_key_id"]
    findings = credential_patterns.scan_text(exempt + "\n" + following + "\n")
    assert {f.pattern_class for f in findings} == {"aws_access_key_id"}


# --------------------------------------------------------------------------
# fail-safe, and the finding that must NOT be swallowed by it
# --------------------------------------------------------------------------


def test_hook_survives_a_scanner_exception(tmp_path, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic scanner fault")

    monkeypatch.setattr(edit_lint_check.credential_patterns, "scan_file", boom)
    target = tmp_path / "ordinary.txt"
    target.write_text("hello\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))

    rc = edit_lint_check.main()

    assert rc == 0
    err = capsys.readouterr().err
    assert "credential" in err.lower()
    assert "synthetic scanner fault" not in err  # no raw trace spew


def test_glyph_arm_still_runs_when_the_credential_arm_faults(tmp_path, monkeypatch, capsys):
    def boom(*_args, **_kwargs):
        raise RuntimeError("synthetic scanner fault")

    monkeypatch.setattr(edit_lint_check.credential_patterns, "scan_file", boom)
    target = tmp_path / "glyphy.txt"
    target.write_text("a " + chr(0x2014) + " b\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))

    edit_lint_check.main()

    assert "BANNED-GLYPH FOUND" in capsys.readouterr().err


def test_genuine_finding_is_not_swallowed(tmp_path, monkeypatch, capsys):
    """The emit path sits OUTSIDE the try/except that guards scanner bugs."""
    target = tmp_path / "real.txt"
    target.write_text(_FAKE_BY_CLASS["aws_access_key_id"] + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))

    rc = edit_lint_check.main()

    assert rc == 2, "a credential hit must exit loudly, not silently"
    assert "aws_access_key_id" in capsys.readouterr().err


def test_clean_edit_still_exits_zero(tmp_path, monkeypatch):
    target = tmp_path / "fine.txt"
    target.write_text("nothing to see\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))
    assert edit_lint_check.main() == 0


def test_unreadable_file_does_not_raise(tmp_path):
    assert credential_patterns.scan_file(tmp_path / "does_not_exist.txt") == []


def test_binary_file_does_not_raise(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(bytes(range(256)) * 8)
    assert isinstance(credential_patterns.scan_file(blob), list)


# --------------------------------------------------------------------------
# latency budget - this hook runs on EVERY agent write
# --------------------------------------------------------------------------


def test_large_file_scan_stays_cheap(tmp_path):
    big = tmp_path / "big.txt"
    line = "the quick brown fox jumps over the lazy dog 0123456789 abcdef\n"
    big.write_text(line * 16000, encoding="utf-8")  # roughly 1 MB
    started = time.perf_counter()
    findings = credential_patterns.scan_file(big)
    elapsed = time.perf_counter() - started
    assert findings == []
    assert elapsed < 5.0, f"credential arm took {elapsed:.3f}s on 1 MB"


def test_hook_skips_when_no_file_paths(monkeypatch):
    monkeypatch.delenv("CLAUDE_FILE_PATHS", raising=False)
    assert edit_lint_check.main() == 0


def test_skippable_paths_are_not_scanned(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "logs"
    logs.mkdir()
    target = logs / "today.log"
    target.write_text(_FAKE_BY_CLASS["anthropic"] + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_FILE_PATHS", str(target))
    assert edit_lint_check.main() == 0
    assert "CREDENTIAL" not in capsys.readouterr().err.upper()


def test_pragma_constant_is_ascii():
    assert credential_patterns.PRAGMA.isascii()
