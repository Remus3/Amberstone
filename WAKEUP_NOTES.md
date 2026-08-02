# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-01f - five non-gated rows, and the verifier caught three of my own defects

1 commit, pushed. Tier-1. DS untouched. Full `tests/` 17831 passed / 108 skipped / 0 failed.

**Shipped** - RM-128, RM-130, RM-131, RM-132, RM-134 (LEDGER 1157).
- **RM-134** `dashboard/_errors.send_error` stops leaking `str(exc)[:200]`; one back-compatible
  edit covers 21 call sites and BOTH surfaces (`mc/routes.py` splices the same handlers into
  `:8895`). Leak proven end-to-end through the MC route first, then fixed. 7 of 8 tests kill
  the old body.
- **RM-131 + RM-128** take `tools/upstream_drift_check.py` from 3 signals to 5. Both
  fingerprints are SHAPE-only - a value-sensitive signal would report drift every single run,
  which is the same as reporting nothing.
- **RM-130** 24 `U+2192` in `tft/` -> `->`, byte-level so the mixed CRLF/LF survived.
- **RM-132** met its acceptance and is still INERT - see below.

**Three defects the adversarial verifier found in my own work**
- **RM-132's token reference can never resolve.** `--fs-ov-chip` is on
  `body[data-shell="overlay"]`; both widgets `documentElement.appendChild(...)`, so they are
  SIBLINGS of `<body>` and custom props inherit downward only. Renders fine (the 13px fallback
  is load-bearing), tracks nothing. I reasoned about the scope and still got it half wrong.
  Filed **RM-139** with three costed routes and a computed-style acceptance.
- **A tautological test.** The qq carry-forward case re-implemented
  `upstream_drift_check.py:387` in its own body. Rewritten to exercise `advance_sentinel`
  against a tmp sentinel; mutation-proven red, plus a negative control.
- **An overclaiming docstring.** RM-128's offline half does NOT catch a regroup between two
  known groups (mutant M2 survives); only the live fingerprint does. Docstring says so now.

**RM-128's filed acceptance was REFUTED in two places** - implementing it as written would
have shipped a forever-red test. (a) 16 kARAM / 256 kAlt records vs a 21-entry map, so
"every live kARAM/kAlt id must be mapped" is impossible. (b) 8 ids (900/920/1020/1400/1700/
1710/1750/1900) sit in `kAlternativeLeagueGameModes` while mapping to sr/aram/arena -
`gameSelectModeGroup` is a client MENU grouping, not a mode classifier.

**Two process notes**
- The LEDGER-1155 lesson repeated the same day: the first full run went RED on
  `test_web_ascii_sweep.py` (RM-132 moved the web LIVE-half digest), invisible from any
  touched-module scoping. Re-captured per the file's ritual after measuring 173 sources on
  both sides. **Run the repo-wide guards whenever a web/ byte or a test FILE changes.**
- The Stop gate flagged my wrap summary and was RIGHT: I called the queue snapshot
  "committed" while it was `??` and HEAD was unchanged. Retracted the wording, parser untouched.

**Do NOT redo**
- Do NOT reinstate either refuted half of RM-128's acceptance. Both are measured.
- Do NOT "fix" RM-132 by adding the overlay type tokens to `:root` without reading RM-139 -
  the body-scoping is deliberate (the `tokens.css` >=16px floor is relaxed only in overlay).
- A bash ANSI-C quoted grep for the arrow (a raw U+2192 inside `$'...'`) does NOT expand the
  escape - it reports a false 0. Count with ripgrep `-o`; ripgrep `--count` gives LINES,
  not occurrences (14 vs 24 here).

**Next (operator-directed at wrap 2026-08-01):** THREE things in one session, orchestrated
subagent-first / parallel as standing protocol requires.
1. **RM-140** - a COMPLETE upstream patch + data check / ingest / coverage-expand pass. This
   is the INGEST half; RM-128/RM-131 shipped only the DETECT half. Probe `current.txt` +
   ENGINE_VERSION + DS `:8860` `/health` + the now-5-signal `ops/runtime/upstream_drift.json`
   before anything else. Never `--force` a Meraki re-extract.
2. **RM-141** - QA THE OPERATOR on "League Classic" before scoping it. Three readings are on
   the table (the `CLASSIC` gameMode / SR depth, a distinct legacy-client offering, or the
   retired-mode class). Ask, do not guess.
3. **Then the next 5 open items** as usual: RM-135 (backup of irreplaceable single-copy data -
   big enough to own a session), RM-139 (overlay tokens unreachable from documentElement),
   RM-133, RM-122 residue, or the DS RM-118 wireable seams (exactly 4).
4. **AFTER 1-3 are done AND cleared, a WHOLE SESSION dedicated to nothing but
   `ops/audit/P6_LOLMATH_PARITY.md`** (184 lines, operator-appended 2026-06-15). Own session,
   not a slice appended to this batch - the operator asked for it explicitly. Highest-priority
   slice in the doc is **G1: DS builds the WRONG damage axis on 20 champions** (18 AD-on-AP
   kits incl. Gwen / Teemo / Rumble / Diana, plus Pyke / Taric inverse), which is a
   correctness bug, not a tuning gap. Inputs are in-repo: `ops/audit/LOLMATH_VS_DS_SWEEP.md`
   + `ops/audit/lolmath_ds_sweep/` (reproducer; `npm install` to re-scrape, `node_modules`
   gitignored). **The doc's own numbers are STALE by design and it says so** - it cites engine
   1.120.0 / patch 16.12.1 against today's 1.268.0 / 16.15.1, so RE-DERIVE off live
   `data/daemon_slayer/current.txt` + `:8860` `/health` + the current `build_orders_sr.json`
   before acting on any row. Tier-2: ENGINE bump, four doc anchor sites, Share mirror, dual
   suite. Root-cause-first, validated PER CHAMPION (Engine/Build Conventions hard rule - a
   single generic ADC-crit shape is exactly how the last two build fixes shipped incomplete).

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
