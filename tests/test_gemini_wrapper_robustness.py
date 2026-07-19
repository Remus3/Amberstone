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

3. SILENT MARKER WEDGE. ``gemini_audit.ps1`` resumes from the sha in
   ``ops/runtime/gemini_last_audit.txt``. Worktree-slice shas that never survive
   cherry-pick are an EXPECTED class in this repo (see the docs/LEDGER.md
   preamble), and once the marker pins one, ``git log <dangling>..HEAD`` fatals,
   ``$commits`` comes back empty and the run takes the "nothing to audit" exit 0
   having written NO review and NO log line. That wedged the nightly audit for 28
   nights (last review 2026-06-21, marker pinned at edd76db3). The marker must be
   validated and self-heal, and every run must log unconditionally so a silent
   no-op is never again indistinguishable from a task that failed to start.

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


def test_audit_validates_resume_marker_before_use():
    # A dangling marker sha must self-heal, not wedge the nightly at exit 0.
    text = _code_only(_read("tools/gemini_audit.ps1"))
    assert "Test-CommitResolves" in text and "cat-file -e" in text, (
        "gemini_audit.ps1 uses the gemini_last_audit.txt sha as a git range "
        "endpoint without checking it still resolves; a pruned worktree-slice "
        "sha then silently no-ops every nightly run (2026-06-22..07-19 outage)"
    )


def test_audit_logs_unconditionally_at_start():
    # Without a first-line write, a run that dies before any conditional branch
    # is indistinguishable from one that never started - the exact ambiguity that
    # made the 0xC000013A run unattributable.
    text = _code_only(_read("tools/gemini_audit.ps1"))
    assert 'Log "START' in text, (
        "gemini_audit.ps1 has no unconditional start-of-run log line"
    )


def test_audit_logs_the_nothing_to_audit_path():
    # This branch exits 0 and used to write nothing at all.
    text = _code_only(_read("tools/gemini_audit.ps1"))
    assert "nothing to audit" in text and "SKIP code=0 no new commits" in text, (
        "the 'nothing to audit' early exit must log, or a wedged resume marker "
        "looks identical to a healthy quiet night"
    )


def test_wrappers_stay_ascii():
    # Hard rule: 7-bit ASCII authored content (PS5.1 ANSI-decode mojibake hazard).
    for rel in _WRAPPERS:
        raw = (_REPO_ROOT / rel).read_bytes()
        bad = [i for i, b in enumerate(raw) if b > 0x7F]
        assert not bad, f"{rel} has non-ASCII bytes at offsets {bad[:5]}"
