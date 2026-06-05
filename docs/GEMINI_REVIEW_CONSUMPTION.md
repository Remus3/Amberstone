# Gemini Review Consumption Hook (PROVISIONAL)

How Claude ingests Gemini's read-only reviews. Gemini advises; Claude is the SOLE
writer and verifies every claim before acting. See docs/GEMINI_AUDIT_CONFIG.md.

## When
- Start of a normal session (after the CLAUDE.md/MEMORY bootstrap).
- Start of a headless-upgrade run, before picking the next task.

## Inputs
- `docs/EXTERNAL_REVIEW_<date>.md` - newest nightly audit (runner-written).
- `gemini_io/answer_*.md` - on-demand Q/A replies (if the in-session channel is used).

## Protocol (per finding)
1. READ the newest unconsumed review. Track the last-consumed filename in
   `ops/runtime/gemini_review_consumed.txt` so a review is not re-worked.
2. VERIFY before trusting - Gemini is treated exactly like an unverified subagent
   claim (CLAUDE.md verification discipline):
   - Re-open the cited file:line; confirm the issue is real on disk NOW.
   - Re-run the cited analyzer (ruff / C901 / pytest) yourself; do not take
     Gemini's numbers on faith.
   - If a claim cannot be reproduced -> DISCARD it, note "unverified" in the
     session log, move on. Do not implement unverified findings.
3. TRIAGE the verified findings:
   - FROZEN file (CLAUDE.md list) -> flag only, never edit without operator OK.
   - `Share/` -> ignore (byte-mirror of agents/daemon_slayer).
   - Real + in-scope -> becomes a candidate task.
4. TDD-FIRST on every accepted code change: write the failing
   characterization/regression test FIRST, then implement, then run the full
   relevant suite green before commit. (Same rule as all RC/DS work.)
5. NOTHING auto-applies. Each accepted finding is a normal scoped change the
   operator/loop approves like any other.

## Anti-loop
- The runner already excludes `docs/EXTERNAL_REVIEW_*.md` + `gemini_io/` via
  `.geminiignore`, so Gemini never audits its own output.
- Claude marks a review consumed (move/append the filename to the consumed
  marker) so the same findings are not re-triaged next session.

## Status
PROVISIONAL - revisit after the first real nightly review lands and is triaged.
