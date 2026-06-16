"""Guard: the Gemini CLI wrappers degrade gracefully under quota/credit failure.

Regression for the live 2026-06-16 outage: the Google/Gemini prepay credits
depleted (429 RESOURCE_EXHAUSTED), so every ``& gemini`` call fails. Two latent
robustness gaps surfaced in the wrappers that the scheduled RC-GeminiAudit task
and mid-session calls depend on:

1. EXIT-CODE MASKING. ``gemini_ask.ps1`` used ``Write-Error <msg>; exit N`` while
   ``$ErrorActionPreference='Stop'`` was in effect. Under Stop, Write-Error is a
   TERMINATING error - the script dies BEFORE ``exit N``, so the intended code
   (2 = no key, 3 = empty) is masked as a bare 1 with no logged diagnostic. This
   is the exact 2026-06-07 RC-GeminiAudit incident that ``gemini_audit.ps1``
   already fixed with its ``Fail()`` helper (Write-Warning + ``exit $code``,
   never the terminating Write-Error). Both wrappers must use that safe pattern.

2. NO WALL-CLOCK CAP on the retry loop. On a 429 the gemini CLI runs its own
   escalating backoff, and the wrapper then layers more Start-Sleep retries on
   top with no overall deadline - a slow/hung CLI stalls the scheduled run
   (P2_FINDINGS W4 deferred). Both wrappers must bound their retry loop by a
   wall-clock deadline so a stuck call cannot stall a headless/scheduled run.

These are static-text guards (the test_ps1_encoding_hygiene / test_bare_py_ban
precedent) - PowerShell is not executed in CI.
"""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WRAPPERS = ("tools/gemini_ask.ps1", "tools/gemini_audit.ps1")


def _read(rel):
    return (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _code_only(text):
    # Strip PowerShell line-comments so a Write-Error mention inside the Fail()
    # explanatory comment is not mistaken for a live Write-Error command. Neither
    # wrapper has a '#' inside a string on a relevant line, so split-on-# is safe.
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_wrappers_exist():
    for rel in _WRAPPERS:
        assert (_REPO_ROOT / rel).is_file(), f"missing {rel}"


def test_no_write_error_masking():
    # Write-Error under EAP=Stop terminates before `exit N`, masking the code.
    # Both wrappers must route failures through the Fail() helper / Write-Warning.
    offenders = [rel for rel in _WRAPPERS if "Write-Error" in _code_only(_read(rel))]
    assert not offenders, (
        "Write-Error masks the intended exit code under EAP=Stop (see the "
        "gemini_audit.ps1 Fail() helper docstring); use Fail/Write-Warning: "
        + ", ".join(offenders)
    )


def test_both_wrappers_define_fail_helper():
    # The shared safe-exit pattern: log + Write-Warning + exit $code.
    for rel in _WRAPPERS:
        assert "function Fail" in _read(rel), f"{rel} lacks the Fail() exit helper"


def test_retry_loop_has_wall_clock_deadline():
    # A 429-backoff or hung CLI must not stall the scheduled/headless run.
    for rel in _WRAPPERS:
        text = _read(rel)
        assert "AddSeconds(" in text and "$deadline" in text, (
            f"{rel} retry loop is not bounded by a wall-clock deadline "
            "(no AddSeconds(/$deadline) - a hung gemini CLI can stall the run)"
        )


def test_wrappers_stay_ascii():
    # Hard rule: 7-bit ASCII authored content (PS5.1 ANSI-decode mojibake hazard).
    for rel in _WRAPPERS:
        raw = (_REPO_ROOT / rel).read_bytes()
        bad = [i for i, b in enumerate(raw) if b > 0x7F]
        assert not bad, f"{rel} has non-ASCII bytes at offsets {bad[:5]}"
