# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-09, weekly-hygiene pass (relocated headless lane 6 RM-176 `2026-08-08`; newest 3 = DS coverage saturated `2026-08-08d` + orchestrated run `2026-08-08c` + RM-177 HSP flip `2026-08-08b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-13b - new-project design QA: portable conventions extracted, Sibling-E specced

Commit `afd98bd3` (`docs/PORTABLE_PROJECT_CONVENTIONS.md`, 723 lines / 36.9 KB) plus this ledger/notes sync. **Tier-0, documentation only** - no code, no `data/` write, no RC or DS restart. Gate: `drift_guard` 0 breaches, `perseus_sync` **embedded 1415/1415**, both authored files verified **0 non-ASCII bytes** and **0 project-noun hits**.

**What shipped.** A planning + QA session (4 rounds of framed questions, no building) producing two documents. (1) `docs/PORTABLE_PROJECT_CONVENTIONS.md` - this repo's operating doctrine with every project noun stripped, meant to be dropped into any new repo unchanged. 19 sections: doc topology with one owner per fact, file-size budgets, open/closed/gated item organization, the orchestrated multi-agent self-adjudicating self-adversarial default, R1-R11, TDD + 9 test-quality failure classes, 4 CI tiers, ASCII/Windows encoding, markdown-SSoT memory + semantic mirror, agent/command/skill/MCP roster, visual+OCR policy, the 5-trap license gate, 13 verification failure classes, 4 hook confounds, private-to-public flip gate. **Section 18 is its refresh protocol - re-diff it, never rewrite it.** (2) A bootstrap spec for a second project at `C:\Sibling-E` (Satisfactory planning/advisory system), written outside this repo along with a byte-copy of the conventions. Memory: `project_sibling_e_bootstrap`.

**Method note worth carrying forward.** The bootstrap was not written from recollection. Every environmental claim was probed live before it was written (install path, shipped data files with real byte sizes, free port band, toolchain), and every claim that could NOT be probed was labelled as a numbered spike carrying a binary acceptance criterion **and** a stated fallback. When the operator supplied two screenshots mid-session, a further probing round settled an open design question outright and surfaced a hazard that assumption would have missed. That is the shape: probe what is knowable, label what is not, re-probe when new evidence arrives.

**Do NOT redo:** the 4-round QA. All decisions are fenced in that project's own decision log (its section 11) - name, private-first, Python core, deterministic zero-LLM advisor, three explain tiers, per-world ledger + global mute, four v1 advice domains, mods architecture-first, no external optimizer in phase 3, no community datasets. Re-opening any of them re-litigates a settled call.

**Not done, by scope:** nothing in `C:\Sibling-E` is initialized - no git, no hooks, no code. That is its own first session's phase 0.

---

# 2026-08-13 - /sync-all-md: five drifted numbers, one of them a provenance error

Commits `24df6595` (the reconcile). Documentation only - no code, no `data/` write, no restart. Gate: ruff clean, **95 doc-guard tests passed**, `drift_guard` 0 breaches, both edited files 7-bit ASCII, CLAUDE.md 41.7 KB / 60 KB budget.

**Fixed (all measured this turn, none carried from a doc):** `CLAUDE.md:6` ENGINE **1.275.3 -> 1.277.1** (three bumps missed); `CLAUDE.md:7` **11 -> 12 live ADRs** (013 + 014 had landed; ADR-004's supersession by ADR-012 now named); `DAEMON_SLAYER.md:5` banner **10594 -> 10578 tests**; `_effects_data` row **547 -> 548** entries; and the `tests/` module-map row **11754 -> 10578**, which was a PROVENANCE error - 11754 is the RC `tests/` dir at ENGINE 1.216.0 (LEDGER 911) filed against the **DS** module map. The wrong attribution is written into the row so it does not get restored.

**Canonical facts as measured 2026-08-13:** patch 16.15.1, ENGINE 1.277.1, DS **10578** collected, RC `tests/` **19105** collected, ITEM_EFFECTS **548**, DDragon purchasable **544** / total **706**, champion overrides **167 entries / 132 champs**, `rewind_history.db` **2966** rows. Zero broken relative links across all nine living docs.

**Do NOT redo / do NOT "correct" back:**
- The **10578** figure. Collected TWICE this turn, both `agents/daemon_slayer` and `agents/daemon_slayer/tests`. The 2026-08-12 note above says **10584 passed**; the 6-test delta is UNEXPLAINED and was not reconciled by preferring either doc. If you re-measure and get 10584, say so - do not assume one of us fat-fingered it.
- The **`547/547 DDragon purchasable items`** line in `DAEMON_SLAYER.md:10`. Left ALONE on purpose - three denominators measure out and none reproduces the pair (registry 548, purchasable 544, total 706). Coverage prose is a DS-batch job (`feedback_ds_coverage_prose_recompute`), not a general sync.
- The README. It carries zero hard numbers by design; it needed no edit and still does not.

**Filed for the operator, deliberately NOT given RM ids** (ids come from `docs/DS_SWEEP_TRACKER.md` and I did not want to mis-allocate one for what are decision items, not scoped work): (1) the `547/547` denominator above; (2) **the `/sync-all-md` skill cites three paths ADR-012 deleted** - section 2 names `docs/BRIDGE.md`, section 5 compares `docs io RC peer/RC_PHASE1_LESSON_SCHEMA_2026-05-02.md` against `core/bridge_envelope.py`; its two mirror copies are byte-identical and glyph-clean, so this is a content defect, not drift; (3) `RC_WORK_TRACKER.md` untracked, self-labelled "living", 26 days cold. Minor: `MEMORY.md` has 48 index lines over the 150-char cap, and DS `/health` answers **http** - the skill's `curl -k https://...:8860/health` exits 35.

**Next:** operator call on the three filed findings, else the top open ROADMAP row.

---

# 2026-08-12 - RM-190 decided (a1), the heartbeat rename retries, RM-191 filed

Commits `f2e162e3` (RM-190), `603a8fd2` (heartbeat retry), `26f4ff87` (LEDGER 1242), `ed23d8fa` (RM-191 + size-budget pass), `6720ba7e` (drift-guard fix). All pushed. Local: DS **10584 passed / 13338 subtests**, RC `tests/` **19009 passed / 96 skipped / 0 failed**, ruff clean, drift_guard 0, `ds_share_sync --check` in sync at 533 files.

**RM-190 CLOSED - operator chose a1.** 16.16.1 DDragon mirror committed; item 3175 flat magic pen 18 -> 20 carried into the DS registry; **ENGINE 1.277.0 -> 1.277.1**; DS deliberately left PINNED to data patch 16.15.1. `:8860` reporting patch **16.15.1** at engine 1.277.1 is **CORRECT, not drift** - do not file the gap as a defect. Full detail + traps: LEDGER 1241, body in `docs/ROADMAP_HISTORY.md`.

**Heartbeat rename now retries (LEDGER 1242).** `ops/rc_dev_runtime.py` is FROZEN; the operator approved it this session - record that. The prior note's mechanism was wrong twice: **nothing crashed** (`write_fatal` writes a marker and RETURNS, so the loop kept running and `health.json` just froze while the pid stayed live), and it is **nine call sites**, not one, because `_atomic_write_json` is shared. 3 attempts, 0.15s worst case, under the 1.0s heartbeat interval.

**RM-191 filed (operator-gated).** `write_fatal` is a WRITE-ONLY channel with **zero readers** - measured, `grep -rn last_fatal` returns only its own writes, and `health.json` has no `fatal` key. That is why the 2026-08-09 outage was found by hand three days later.

**Do NOT redo / do NOT re-investigate:**
- RM-190 in any form. Do not bump the DS per-patch snapshot casually (21 files / ~12 MB, needs a Meraki extract, never `--force`).
- `core.build_order_precompute --static` does NOT restamp `build_order_variants_*.json` - separate `core.build_order_variants` run. `ds_share_sync` does NOT author release history; `Share/CHANGELOG.md` + `Share/README.md` are hand-written even when the sync reports clean.
- The `docs/OVERLAY_COMPLIANCE_PLAN.md:35` "1.277.0" anchor is CORRECT - it is a dated `STATUS as of 2026-08-11` snapshot. The drift guard was taught this (`6720ba7e`); do not "fix" the doc.
- B4-a..e, the B3 correction, the `enemy_summs_tracked` removal - all still shipped from the prior session.

**Next:** RM-191 if you want it (needs a frozen-file grant), else the top open ROADMAP row.

---

# 2026-08-12 - RC recovered from a 3-day outage, then B4 built end to end

Commits `f0501048` (B4-a), `543f738c` (B4-b), `3ca8ecd2` (RM-190), `12fc506c` (B4-c), `149468f9` (B4-d), `66914b81` (B4-e), `42e5c659` (B3 correction), `4920867d` (B1 residual). All pushed. RC `tests/` **19000 passed / 96 skipped**; ruff clean; drift_guard 0. Design: `docs/OVERLAY_B4_DESIGN.md`.

**RC had been DOWN since 2026-08-09** and the cause is worth keeping: `ops/runtime/last_fatal.txt` shows a `PermissionError [WinError 5]` on `os.replace(health.json.tmp -> health.json)` in the heartbeat (`ops/rc_dev_runtime.py:42`) - a Windows sharing violation from a reader holding the file at the swap. The supervisor was already dead, so nothing restarted it. Fixed by `schtasks /run /tn RC-Supervisor`. **The heartbeat still has no retry around `os.replace`, so one transient handle kills the whole app** - a 3-try backoff would convert a fatal into a logged blip, but `rc_dev_runtime.py` is FROZEN and needs operator approval.

**B4 is BUILT (a through e); only B4-f is open** and it is a DevRel question, not code.

**Do NOT redo:**
- B4-a..e. Producer suppression (`suppress_live_directives` + `suppress_live_envelope`), the client gate (`web/js/lib/live_directive_gate.js`), the voice gate, `game_id` / `game_run_id` on the shadow record, and the post-game DECISION BRANCHES card + `/api/branch-review`.
- The B3 row correction and the `enemy_summs_tracked` removal.

**Three findings that changed the work, all recorded in `docs/OVERLAY_B4_DESIGN.md`:**
- **The capture half was already shipped.** `core/hz_choice_shadow.py` has been writing the branch set to a 68 MB corpus all along, so B4 was a render-gate plus a reader, not a new recorder.
- **B4-a's field list was incomplete and B4-b caught it.** `callouts` and `lead_projection` are TOP-LEVEL `/api/state` keys, not `coach` fields, and they feed two of the only three mounts the overlay keeps.
- **B3 was recorded DONE while its artefact was still firing.** `spike_cue.js` was deleted but the spike lines live in `core/event_callouts.py` and shipped through `#rn-callouts` for another day. Lesson, now in plan section 6c2: **a banned artefact is a BEHAVIOUR, not a file** - grep the string the user sees, not the component named after the rule. Applied back over B1/B2/B10; found one dead registry key, now removed.

**Open, all needing the operator or DevRel:** RM-190 (the uncommitted DDragon 16.16.1 bump vs DS pinned 16.15.1 - decide commit-and-carry or revert; it is the ONLY thing in the working tree and it fails 2 DS pen tests), B4-f / B8 / B9 (DevRel), the Riot portal registration, and G3-14 (one live ARAM row closes it).
