# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-19 - caveman fleet default + CLAUDE.md ledger prune (`ae07bdf` `85624c3`, pushed)

Operator: review the caveman ecosystem (caveman/cavemem/cavekit/cavegemma), implement fleet-wide default-on; then do the latency lever, then /done.

- **`ae07bdf`** - caveman full = fleet-wide session default. New `tools/caveman_default.py` emits the full-level directive; wired as a 2nd SessionStart hook in the (gitignored, machine-local) `.claude/settings.json` alongside `rc_facts.py`. Verified on Legion (clean output, JSON parses, 0 non-ASCII). Peer + Game-PC installed the equivalent via bridge and reported back (Peer committed `f0c5ce0`; Game-PC confirmed settings.json + CLAUDE.md). Exemptions stay normal prose (clarifying Qs / AskUserQuestion forks / errors-needing-context / per-page UI-audit ritual); "normal mode" disables per-session. Level full over ultra (operator-confirmed - full keeps the one "why" clause for at-a-glance sanity-check).
- **Only caveman** maps to "default on load": cavemem deferred (memory-recall, duplicates existing memory/WAKEUP/history/bridge-lessons, NOT the latency lever), cavekit = skills-only, cavegemma = N/A (62GB local Gemma model; fleet runs Claude). Memory `feedback_caveman_default_fleet.md` + MEMORY.md index added.
- **`85624c3`** - CLAUDE.md Active-priorities prune (operator-approved, the real latency lever). 100 completed entries (items 1-93) relocated VERBATIM to `docs/history_notes.md` (zero rewrite; ROADMAP-95 "keep history" honored via archive-not-delete). Items 94-96 stay inline at full fidelity + a compact `### Settled - do not re-litigate` digest preserves load-bearing don't-redo guardrails in the always-loaded file. CLAUDE.md 251,618 -> 20,179 bytes (~231 KB off EVERY turn). Integrity verified: 3 inline + digest + closing line, 100 archived, byte deltas conserved, s245/older sessions intact below the new archive header.
- **Don't-redo:** caveman-default is intentional fleet config, NOT drift - do NOT revert it. cavemem/cavegemma are CLOSED for this purpose - do NOT re-pitch cavemem as a speed fix (it does not touch the per-turn bottleneck). Items 1-93 are in `docs/history_notes.md` verbatim, NOT lost - do NOT restore them inline or treat their absence as drift.
- **NEXT:** operator said "then start whats up next" post-/clear - no specific item carried; resume from ROADMAP/CLAUDE active priorities + the new Settled digest. Operator-gated pending unchanged: s220 aggregator G PGR reframe (live game), 101.qq.com one-off capture. Optional 2nd latency lever (operator declined this round): scoping the full-pytest PostToolUse hook to skip docs-only edits.

---

# 2026-05-19 - sync-all-md self-fix + draft tool L (the community fork) triage (`c923eb0` `d12a98a`, pushed)

Operator housekeeping batch: 4 items off one terse message. No code, no RC/DS restart.

- **`c923eb0`** - `/sync-all-md` skill self-fix. The "CHANGELOG broken ref" + "sync-all-md self-drift" were the SAME root cause: skill self-staleness. Did NOT do the literal "repoint 3 cites": s222 already fixed the real cross-refs (`CLAUDE.md:301 Completed work: docs/history_notes.md` is correct); the 4 remaining `docs/_archive/CHANGELOG.md` hits are ledger NARRATIVE (2 literally describe the s222 fix) - repointing = history rewrite for zero gain. Instead retired the stale flag in skill §6 + §10 banner so it stops re-surfacing every run. §9 self-congruence precedence was BACKWARDS (gitignored `.claude/commands/` winning would re-inject em-dashes into tracked `tools/`, undoing s244) - inverted it (tracked `tools/` wins) + added a no-em-dash/no-smart-quote guard. Re-mirrored tools->commands; both copies now byte-identical AND ASCII-clean (verified). CLAUDE.md/ROADMAP.md ledger prose left untouched (explicit operator choice via AskUserQuestion).
- **`d12a98a`** - draft tool L (the community fork) liftability triage folded into BACKLOG "Research / inspiration". Verdict FUTURE/reference-algorithm-only: the Elo log-odds draft-composition aggregator is the team-vs-team layer `routes_pickban.py` lacks, composes on `core/smoothed_rates.py` (NOT a duplicate). CLOSED negatives recorded (no license on fork OR upstream `draft tool L`; data is a aggregator D scrape RC can't cache; "+" fork adds zero math) - never re-research.
- **Memory:** new `feedback_ds_coverage_prose_recompute` + MEMORY.md index - DS champ-coverage %/match-row prose must NOT be recomputed in a non-DS sync (nested registry schema; flat count mis-parses). Operator-confirmed scope rule this session.
- **Don't-redo:** the sync-all-md self-refute is fixed - do NOT re-flag the CHANGELOG ref or re-investigate the §9 drift. draft tool L (the community fork) is triaged - do NOT re-research (see BACKLOG). The DS coverage/match-row recompute is a DS-batch job, not a bug.
- **NEXT:** operator said "continue whats next" post-/clear - no specific item carried; resume from ROADMAP/CLAUDE active priorities. Operator-gated pending: s220 aggregator G PGR reframe (live game), 101.qq.com one-off capture.

---

# 2026-05-19 - DS stat-growth fix: linear -> Riot quadratic (`fd80bf3` + docs-sync `17c782e`, pushed)

Found cross-checking DS math vs lolmath `@lolmath/calc`. Focused TDD session in an isolated worktree (now removed; branch `fix/ds-stat-growth` FF-merged to main).

- **Bug:** `agents/daemon_slayer/stats.py` scaled champion per-level base stats LINEARLY (`base + perlevel*(level-1)`); Riot is QUADRATIC (`base + perlevel*(level-1)*(0.7025 + 0.0175*(level-1))`). Coincides with linear ONLY at level 1 (mult 0) + level 18 (mult exactly 17.0); over-stated every per-level stat (hp/mp/regen/armor/mr/ad) at levels 2-17. Real bug, not a modeling choice.
- **Fix:** new `growth_multiplier()` + `scaled()`; 8 `CHAMPION_SCALING_RULES` repointed off the deleted `linear`. AS math (`attack_speed_scaling`) was already correct Riot math - untouched. ENGINE_VERSION 1.4.0 -> 1.5.0 + 14 version pins. Adjacent: corrected the stale/backwards pen-pipeline comment in `ability_dps.py:1142` (no pen code touched).
- **Proof-first (DON'T redo):** engine hand-proven correct BEFORE rebaseline - 16 stat curves (Garen/Lux/Aatrox/Malphite x hp/ad/armor/mr @ L1/6/11/13/18) + DPS/EHP pipeline traces match the formula exactly; Garen/Lux HP match known in-game. Only 6 DS tests drifted: 4 genuine mid-level pins rebaselined + 2 pre-existing fragile exact-float assertions made tolerant - all INTENDED, do not re-investigate.
- **Verified:** DS 2283/748/0, wider RC 1457/0. Production :8893 restarted via RC-DaemonSlayer task -> serves 1.5.0; Garen L11=1549.95 (in-game 1550), L18=2356 (unchanged endpoint). Docs synced `17c782e` (ENGINE 1.5.0 + DS tests 2283 across CLAUDE/DAEMON_SLAYER/README/BRIEF).
- **Flagged, not blocking:** (a) DAEMON_SLAYER champ-coverage prose "196/125, 73%" + BRIEF "2,851 matches" left as prior-batch state - NOT affected by this fix; a correct recompute is a DS-batch session's own docs-sync job (the 4 registries use a nested `_meta`/`default`/overrides schema; a flat count mis-parses it - don't trust an ad-hoc one-liner). (b) Pre-existing broken ref `docs/_archive/CHANGELOG.md` (3 cites) + `.claude/commands` vs `tools/` sync-all-md.md drift - unrelated, operator decision pending. (c) Local branch `fix/ds-stat-growth` retained (merged+pushed; delete anytime).
