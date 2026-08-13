# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-09, weekly-hygiene pass (relocated headless lane 6 RM-176 `2026-08-08`; newest 3 = DS coverage saturated `2026-08-08d` + orchestrated run `2026-08-08c` + RM-177 HSP flip `2026-08-08b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-11b - the product rename: Riot Commander -> Amberstone

Commits `d0785c5e` (Tier 0), `a847a343` (gate), `119dff5a` (Tier 1), `0a70b6cf` (frozen record), `044351af` (repo rename). All pushed. RC `tests/` 18481 passed / 104 skipped / 0 failed; rc-shell 328 passed / 0 failed; drift_guard 0; ds_share_sync --check in sync. Full detail: LEDGER 1239. Plan: `docs/RENAME_SWEEP_AMBERSTONE.md`.

**The name is DONE and the Riot application is no longer blocked on it.** Amberstone is the product name everywhere a reviewer looks: packaging, appId, installer, dashboard brand, PWA manifest, window titles, User-Agent headers, README, disclaimer, and the GitHub repo (`Remus3/amberstone`).

**Do NOT redo:**
- The rename itself. Tiers 0 and 1 shipped; the repo rename landed with its two dependents (`publish.repo` + README badge URLs) in ONE step, which is the only safe order.
- `appId` is now `com.amberstone.shell`. Operator-approved BREAKING change - an existing install co-installs rather than upgrading.
- Frozen-file edits (8 lines in main.py / core/log_setup.py / core/game_snapshot.py / ops/rc_dev_runtime.py) were reviewed and APPROVED. Do not revert them.

**Do NOT re-attempt, with reasons on file:**
- **Tier 2** (renaming the `C:\Riot Commander` directory): recommended DEFER INDEFINITELY. No outsider sees it, so it buys zero compliance, and it risks every absolute path at once - including the Claude workspace-trust key in `~/.claude.json`, which is keyed per path STRING, so a rename silently drops trust and headless runs start discarding `permissions.allow`.
- **Tier 3** (the `RC` abbreviation): recommended NEVER. Initials are not a trademark.
- A blind find-replace on the token `Riot`. Only ~946 of 4163 occurrences are the product name; ~77 percent are nominative and REQUIRED, and the mandated disclaimer must literally contain "Riot Games".

**Still open (operator-only):** Riot Developer Portal product registration needs the operator's account login; a production key needs a public website + Terms of Service + Privacy Policy, none of which exist. Then B4 (move coach imperatives to pre/post-game - decision recorded in the compliance plan 6c), B8 (vision/OCR capture) and B9 (LCU) are DevRel questions.

**Two guard lessons worth carrying:** a self-destructing guard must assert its exemption is still LOAD-BEARING, not merely that the remainder is clean (mine did not, and sat green through the very rename it was supposed to detect); and `tools/stop_claim_gate.py` now parses node test output, closing a blind spot where the whole rc-shell suite was invisible to it.
