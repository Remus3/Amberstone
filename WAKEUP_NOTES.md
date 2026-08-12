# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-09, weekly-hygiene pass (relocated headless lane 6 RM-176 `2026-08-08`; newest 3 = DS coverage saturated `2026-08-08d` + orchestrated run `2026-08-08c` + RM-177 HSP flip `2026-08-08b`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

---

# 2026-08-11 - Overlay Platform M submission compliance (operator-directed, interactive)

Commit `25fce0df`, pushed to main. RC `tests/` 18470 passed / 104 skipped / 0 failed. DS 10495 passed / 83 skipped / 0 failed. `ds_share_sync --check` in sync (engine 1.277.0, 533 files). Plan: `docs/OVERLAY_COMPLIANCE_PLAN.md`. Full detail: LEDGER 1238.

**What this session was.** Reviewed the Overlay Platform M app-proposal form + Riot's third-party rules, then cut every RC surface those rules ban and rebuilt the one worth keeping. Framework verdict for a future port: **ow-electron, not Overlay Platform M Native** (RC already ships an Electron shell and needs native node + a Python sidecar; Native is a CEF UI wrapper with no story for either).

**Removed:** enemy summoner-spell tap-tracker; summoner + ultimate cooldown ledger; ultimate power-spike cue; `/api/cooldown-watch` + `agents/daemon_slayer/cooldown_watch.py`. Every removal left an INVERTED guard test where the old case asserted the banned surface must exist - reinstating any of them turns a test red.

**Two things worth carrying forward:**
1. **B7 was a live routing bug, not just compliance.** `mode_from_game_mode_string` matched no branch on `"BRAWL"`, so a real Riot Brawl game defaulted to `MODE_SR` and got coached. Three OTHER sites tested substring `"BRAWL"` and so matched ONLY Riot Brawl, never RC's rotating modes. Gate is now `is_forbidden_game_mode()` + `MODE_UNSUPPORTED`, checked first, in `core/game_snapshot.py` (FROZEN file, edited with explicit operator approval).
2. **My own filed blocker B6 was wrong.** RC displays no TFT Legend/Augment win rates or average placements, and `core/augment_external_source.py` is an ARENA prior the TFT-scoped rule does not reach. Acting on the row as filed would have deleted a working Arena feature. Filed rows stay hypotheses until probed.

**The line, for any future session:** Riot bans **tracking** enemy cooldowns - the verb carries the rule. DDragon publishes every per-rank cooldown and the client shows them. The DS engine's cooldown math is untouched and must stay so; champ-select CC advice ("enemy comp has 4 hard-CC abilities, consider Cleanse") is legal; a per-instance countdown is not. `cc_threat_cell` is the compliant rebuild - CC duration and threat spell, no cooldown scalar, guarded against the scalar returning under a new name.

**OPERATOR ACTIONS OPEN (cannot be automated):**
- **RENAME the product.** "Amberstone" uses Riot's trademark and BLOCKS the Riot 3rd-party application. Operator has kept **Salt Circle** and **Lane Oracle**; full shortlist with domain-probe results is in `docs/OVERLAY_COMPLIANCE_PLAN.md` section 6b2. "Daemon Slayer" is NOT usable publicly (Shueisha's DEMON SLAYER covers computer game software; homophone, same class) - keep it as the internal engine codename.
- Riot Developer Portal product registration needs a Riot account login + form submission.
- A production key needs a public website, Terms of Service and Privacy Policy. None exist.

**NOT started:** B4 (move coach imperatives to pre/post-game, decision recorded in plan 6c - compute branches live, render nothing, review post-game), B8 (vision/OCR capture - DevRel question), B9 (LCU declaration), and the rename sweep itself.

---

# 2026-08-09 - weekly-hygiene pass (automated, unattended)

Relocated: `# 2026-08-08` (headless lane 6 RM-176, 43 lines) to `docs/history_notes.md`. WAKEUP_NOTES now holds 3 sessions.

CLAUDE.md: 40.6 KB, no stray ledger entries. CLEAN.

Memory suspects (operator judgment calls - do not act on these autonomously):
- `feedback_oauth_flip_injection_vectors.md` (45 days old, MEDIUM): "How to apply" step 1 cites `C:/RC-Agent/gamepc_bridge_daemon.py` on a retired machine as a live example. The NOTE (2026-06-24) says bridge files are deleted; core lesson transfers. Consider updating step 1 to remove the dead path citation.
- `feedback_gamepc_league_fullscreen_lockup.md` (Game-PC retired ADR-011): documents FS lockup on retired hardware. Low harm (filename self-labels it). Could move to `_retired/` when convenient.

Anomaly triage (all EXPECTED): RC pid=17624 alive, last_reload_ok=True; DS :8860 alive patch=16.15.1; all 24 RC-* tasks healthy (Ready or Running).
Open operator action (not new): bare `Amberstone` scheduled task (noted 2026-08-08c) - races RC-Supervisor for :8888 and loses, LastTaskResult=1. Deletion = system-settings change, operator territory.
