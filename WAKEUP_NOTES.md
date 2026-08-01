# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-01e - RM-127's last two operator calls, then the armed gate blocked a TRUE claim

2 commits `039b3393`, `f4878fd2`, both pushed. Tier-1. DS untouched.

**Shipped**
- **CCR-123: operator chose B, and the `<3.14` ceiling is DECLARED-ONLY.** `talkthrough-mcp
  0.2.5` installs (72 packages, real wheels for `ctranslate2` + `onnxruntime`), imports, and
  serves a full MCP stdio handshake on **Python 3.14.4** with all 7 tools. Why nobody had an
  answer for three sessions: **pip filters on `requires_python` BEFORE attempting a build**, so
  `pip index versions` reports "No matching distribution found" - gated reads as unavailable.
  543 MB throwaway venv, deleted. Nothing in RC's env, no second interpreter, nothing vendored.
  Option C is dead. Row moves HOLD -> FUTURE lift candidate. **Not adopted** - measuring was
  the whole scope. Still untested: real media through Whisper/OCR/ffmpeg.
- **The Stop claim gate STAYS ARMED, plus `ops/runtime/stop_claim_history.jsonl`** (one line
  per audit, rolled to 500). The per-Stop report is overwritten, so it can only say "was the
  LAST session clean" - the re-affirm rested on n=1, and that is why the same call shipped code.
- **Then the armed gate blocked THIS session's Stop on `17784 passed` - and the claim was TRUE.**
  Two distinct false-positive classes, both fixed by NARROWING: (1) a `run_in_background` pytest
  run answers with a launcher handoff, so its real summary arrives later via an unrelated `tail`
  and was never collected - the collector was blind to a TRANSPORT; (2) `Test 1 passed` was read
  as a one-test suite count. **This session's own transcript now replays to `findings 0`.**
- Fixed a red suite RM-136 shipped 2026-08-01 (`pytest.skip` on a TRACKED fixture - an
  always-passing guard). Confirmed pre-existing by stashing only my two files.

**Do NOT redo**
- Do NOT re-open CCR-123 compatibility. It is MEASURED on 3.14.4. The open question is FIT.
- Do NOT disarm the gate or loosen a check to quiet it. If it flags you, REPLAY the transcript
  first; if it is a false positive, narrow the PARSER. Its must-not-fire negatives are now 6.
- Do NOT re-run any RM-127 CCR pass. RM-127 has ZERO residue.

**Next:** RM-131, RM-128, RM-130, RM-132, RM-133, RM-134, RM-135, or the DS RM-118 seams.

---

---

# 2026-08-01b - RM-127 link-ingest Phases 2+3, and the hook hard rule was WRONG

3 commits `997157f1`, `ba4ff0fe`, `e47ce29a`, all pushed. Tier-0 throughout. DS untouched.

**Shipped**
- **RM-127 Phases 2 AND 3 both done.** `Desktop/Second-Pass.md` + `Desktop/Third-Pass.md`,
  24 KB each. Threshold **cull below 5**, INFERRED from the operator-label cross-tab (at 5+
  they kept 50/51, at 4- culled 83/93). 146 -> 60 survive -> **6 LIFT, 26 concept, 28 DROP**.
- **`997157f1` corrected a CLAUDE.md HARD RULE against measurement.** Hooks DO fire under
  headless `bypassPermissions` on CLI 2.1.220 - SessionStart, PreToolUse, PostToolUse AND Stop.
- `e47ce29a` filed **RM-135**: no backup of irreplaceable single-copy data.
- **`c1ad4ddc` killed the `assert 21378 == 2` CI flake at its root.** `mod.time IS`
  the global time module, so `patch("mod.time.sleep")` is PROCESS-WIDE and tallied
  every thread; the mock also made those threads busy-spin. New `tests/_sleep_probe.py`
  (`record_sleeps` / `thread_scoped`) records only the calling thread and passes other
  threads through to the real sleep. **5 tests across 2 files shared the root cause**,
  not just the reported one. Mutation-tested; no production code touched.

**Do NOT redo**
- Do NOT re-run Phase 1 or Phase 2 triage, and do NOT trust "119 rows / no 8-10" - First-Pass
  holds **146 rows topping out at 9**. ROADMAP + LEDGER 1108 both carried the stale count.
- Do NOT re-measure the hook rule; it is measured and corrected in CLAUDE.md + the memory.
- Do NOT re-derive Phase 2/3 detail into ROADMAP - it lives in LEDGER 1145 on purpose. ROADMAP
  breached its doc budget this session (91%, was 89%) and was trimmed back to 89% / guard clean.

**Open / next**
- **Phase 4 is GATED on operator notes on `Desktop/Third-Pass.md`** - same gate that held
  Phase 1 for two days. Read Third-Pass section 7 (six named traps) before starting it.
- **BURIED OPERATOR GO:** ADDENDUM A in First-Pass ends `after review - build and implement` -
  the only note of 155 authorizing a build, covering 6 dashboard concepts. SEPARATE Tier-2 row.
- CCR-124/136/139 unverified-at-source (reddit 403s every default path).
- Session file hit 25 MB - `/clear` was overdue.
- **STALE DOC, worth acting on: the `/done` skill claims `-n 8` yields 6 failures and
  is therefore "not trustworthy as a gate".** MEASURED 2026-08-01 after `c1ad4ddc`:
  `pytest tests agents/daemon_slayer/tests -q -n 8 --dist loadfile` = **27964 passed,
  108 skipped, 7283 subtests, 0 FAILED in 166s**. None of the 6 named failures
  reproduced. If that holds on a second run, the skill's own precondition for
  replacing the ~17-min CI dispatch with a ~3-min local gate is MET - but the skill
  text lives in BOTH `tools/done.md` and `.claude/commands/done.md` (drift_guard
  enforces mirror parity), so edit them together. Not done: it changes the wrap
  ritual and that is an operator call.

---

# 2026-08-01 - Gemini decommissioned, tri-project headless contract, N=3 round closed

6 commits `15ddff90..8450dd2b`, all pushed. RC-side only; DS untouched (no Share sync).

**Shipped**
- `c926470a` port blocks folded - LW 8900-8919 and RM 8770-8789 both CONFIRMED in writing.
  Adopted LW's `next_free()` with a guard LW's version lacks: RC may only answer for its OWN
  blocks - a confident wrong number handed to a sibling is worse than no answer.
- `aee3bb96` + `13350e43` GEMINI FULLY DECOMMISSIONED (operator directive). Backend, failover,
  exhaustion matcher, ceiling accounting, 2 ps1 wrappers, 3 docs, the scheduled task: gone.
  `gemini()` -> `adjudicate()`, `/gemini-headless-upgrade` -> `/directed-headless-upgrade`.
- `666d2547` + `8b292a98` N=3 coordinated round with LW and RM; all three trees hash equal on
  `slots.py` (`5297f2d0...1cb0a6`).
- `8450dd2b` Claude co-author trailer swept - `gist_share_sync.py` was still EMITTING it into a
  SEPARATE repo the commit-msg hook does not cover.
- NEW: `docs/CONCURRENT_HEADLESS_CONTRACT.md` - portable 3-project headless contract.

**Decisions worth keeping**
- Removing `ceiling_usd` was REQUIRED, not tidy: with the metered vendor gone the only spend
  left was Claude's, so the check would have inverted into a cap on exactly the spend policy
  says is uncapped.
- A cross-repo equality guard makes an atomic change IMPOSSIBLE - whoever moves first is red.
  Rule 4.2a in the contract. Deciding rule: whoever is red should be the party NOT shipping.
- Contract section 10 was WRONG about the cause of the hooks finding: it is settings DISCOVERY
  (cwd), not headlessness. Verified locally - `.claude/` is gitignored, so every lane worktree
  has no settings.json and runs with ZERO agent hooks.
- Removed dangling machine-wide `"model": "rc-main"` from user settings (backup kept). It broke
  headless for EVERY project, and RC's earlier "Not logged in" reading was wrong - `claude -p`
  works now. A headless launch has several independent preconditions that all fail as "the run
  did nothing"; do not accept the first plausible cause.

**Do NOT redo**
- Gemini is gone; a decommission-guard test fails if any of the 8 deleted names return.
- N=3 and the slots re-pin are APPLIED on all three trees. Do not re-negotiate.
- `winmutex.py` GEMINI_MUTEX constant STAYS - shared byte-identical, LW has a live consumer.
- LW owns the hook probe. Do not duplicate it.

**Next:** link-ingest Phase 2. `Desktop/First-Pass.md` has 147 scored rows and 155 operator
`**!=` notes ALREADY PRESENT - the gate the memory calls "awaiting operator notes" is CLEARED.

**Loose end (not blocking):** `NIMBLE_API_KEY` sits in plaintext in user-level
`.claude/settings.json` env. Worth relocating; not touched this session.
