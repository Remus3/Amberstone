# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-01a - LANE-RESEARCH REFILL (headless lane 5): 5 rows filed RM-130..RM-134, one NEW drift-guard gap.

**MERGE NOTE (added by the merger, 2026-08-01):** the five rows this run filed were authored
as RM-129..RM-133 and were RENUMBERED +1 to **RM-130..RM-134** at merge, because a DS
port-block-migration RM-129 landed on `main` while this lane was running - the lane branched
before it existed. Its LEDGER entry likewise moved 1142 -> **1143**. Whichever lands second
renumbers. The ids above are already corrected; `docs/DS_SWEEP_TRACKER.md` records the shift.

## Start here next session

REFILL pass on `lane/research` (Mission Control lane 5), docs-only, no live game
(`/api/state` `mode_key=client`, `liveclient` empty). Branch is READY TO MERGE (Tier-0
docs; no engine, no Share, no restart) - leave the merge to the merger, do not merge from
the worktree. Full detail in LEDGER 1142.

## What shipped (all docs, all PROBED this run)

- **RM-131 filed (NEW gap, flagship)** - 101.qq.com duo-synergy has NO drift guard while
  ddragon / meraki / cdragon / wiki all do. `tools/upstream_drift_check.py` tracks exactly 3
  signals and carries zero qq reference; `core/synergy_external_source.py:33` fetches the
  Tencent endpoint and fails SILENTLY back to the frozen May-25 seed. Acceptance = a 4th
  `probe_qq_synergy()` + `test_upstream_drift_qq_synergy_probe`. Lane 6/7, Tier-1. Companion
  to RM-128.
- **RM-130 / RM-132 / RM-133 / RM-134** - promoted thin BACKLOG cites to well-formed,
  id-carrying, acceptance-bearing rows; each re-grepped live. Corrected one STALE cite
  (RM-133 Arena chip: `_csvArenaPaneHtml` is now at `web/js/panels/champ_select.js:3512`,
  not the filed `:931`).
- Registered RM-130..RM-134 in `docs/DS_SWEEP_TRACKER.md`; next free is now **RM-134**.

## Do NOT redo

- Drift-guard coverage for ddragon / meraki / cdragon / wiki is CLOSED-COMPLETE (all
  GUARDED with cited guards) - do NOT re-audit those four. Only 101.qq.com (RM-131) is open.
- SGP / Match-V5 drift guard was CONSIDERED and DECLINED (live-gated reachability, no
  hand-maintained mirror, official versioned API) - do NOT file it.
- Competitor-lift research stays RETIRED / drained 4x - not re-opened this run.
- Before taking a new RM id run the grep recipe in `DS_SWEEP_TRACKER.md` (next free RM-134).

## Next

Lanes have well-formed work waiting: RM-131 (lane 6/7, the drift probe), RM-130 + RM-132
(lane 7 ASCII / token hygiene), RM-133 (lane 4 Arena chip), RM-134 (lane 8 MC error scrub),
plus still-open RM-128 (lane 6/7) and the DS RM-118 4 wireable seams (lane 6).
