# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-20 (interactive/RC2) - E12+E7 swarm + rc-shell standalone-app live fixes

Commits (all CI-green): `48fcee51` E12-L2 RuneWriter lobby-mode memoization + `64591d5f`
E7a ARAM bench-swap fast re-poll (orchestrated: 7-agent recon swarm -> 2 worktree build
agents -> cherry-pick merge -> fresh re-verify) + `96178904`/`cdb4af12` docs + `cac1df3a`
rc-shell overlay surface gate + `81f74d88` rc-shell focus-on-launch. RC2 banner 54->56/62
~90% (E12 + E7 DONE). RC bounced 17176->1896 (mode=client).

Live firefight (operator ARAM Mayhem Riven): overlay was DOWN (relaunched electron);
LCUAgent/Hotkey/Relay dead since 01:33 boot + LCUAgent posting stale None after the RC
bounce (restarted all 4); RC stuck mode=game post-match (bounced -> client). "coaches not
firing" = NON-ISSUE (backend fired every ~10s; empty immediate/objective is BY DESIGN
item 189 - choices chips are the surface; the dead overlay shell was the cause). always-
on-top OFF (state file; verified WS_EX_TOPMOST=False - works, DON'T re-investigate).

NEXT (don't redo E7/E12/always-on-top - shipped+verified):
- members[] ROOT CAUSE PINPOINTED (don't re-investigate): agent forwards members
  (lcu.lobby.members=1 live) but it lands at /api/state.lcu.lobby while the UI
  (_lobbyViewRefresh/_renderTop8) reads TOP-LEVEL /api/state.lobby = ABSENT. Fix = lift
  lcu.lobby -> top-level state.lobby in dashboard build_state (or repoint the UI). Small.
- agent restart-resilience (task chip 8277de5d) - systemic root cause of the cascade.
- RC2 open: E11 Hextech reskin, E10 history rewrite, E2 DS 3-game flip.

---

# 2026-06-20 (interactive) - Game-PC purge COMPLETE + open-items review + flash fix

Commits (all CI-green): `f508046e` loop-status git CREATE_NO_WINDOW (the "terminal
flashing every ~4s" = the /loop-monitor page polling /api/loop-status, whose
`_last_commit()` git call lacked the no-window flag) + `aa5f9756` Game-PC purge CORE
(66 files: rename the 6 relocated gamepc_*.py agents -> Legion names + re-register
the 3 LIVE tasks via Set-ScheduledTask; sever the Game-PC bridge peer + gamepc MCP;
purge living docs) + `a459b737` purge TAIL (87 files: bridge node-enum de-scope incl
3 frozen configs + supervisor `_BRIDGE_PUB_PEERS` + scattered comments + web + tests)
+ `9a2e9a5f` operator-review decisions. RC is now Legion-only: /api/health/all peers
= peer-only, overall GREEN, pid 17176. Dated history + memory cross-refs preserved.

OPEN-ITEMS REVIEW: operator went top-to-bottom; the queue now lives in the UNTRACKED
repo-root `RC_WORK_TRACKER.md` (Claude-synced; `[^Reviewed]` = operator input, rows
removed as shipped). Decisions: Stage 8.3 flipped DONE (the held flip from item 551,
now committed; banner 54/62 ~87%); L103/L104 CLOSED (Electron overlays self-audit);
mobile-native + tft-vision-relay REMOVED; ~13 backlog items moved to OPEN; Overlay App E
enemy-CD DEFERRED; DS target-current-HP% -> (B) per-archetype (burst ~100%,
juggernaut/sustained ~50%). DATA: 507 ranked-solo games (L109 unblocked); 0
auto-action samples.

STANDING DIRECTIVE: decisions are NO LONGER operator-gated - act autonomously
([[feedback_decisions_not_operator_gated]]). Also [[feedback_avoid_console_flash_legion]].

NEXT / DO-NOT-REDO: (1) auto-action lanes (L116) NOT armed - arming costs API ($5/day
sub-Claude `claude --print`); operator wants FREE -> pick (A) accept the capped cost
or (B) build a $0 deterministic verb->command lane. (2) NEXT SESSION: validate
lolmath's ~50% EHP baseline from their site BEFORE building the DS per-archetype flip
(pinned in the tracker). (3) Resume /rc2-continue (E7 priority-HIGH). The flash is
FIXED (`f508046e`) - do not re-investigate. [[project_rc2_build]]

---

# 2026-06-20 (/RC2-Continue - Phase 8.3 operator Q/A consolidation)

Shipped the 8.3 deliverable: `docs/RC2_QA_CONSOLIDATED.md` (commit `f05b853d`,
pushed). Reconciled all 97 raw Q/A items (docs/RC2_TODO_QA.md, the 8.1 list)
against HEAD via 6 read-only agents; every SHIPPED/CLOSED verdict evidence-cited,
a sample (6 shas / 9 files / 6 greps) independently re-verified. Result:
33 SHIPPED / 13 GATED-LIVE / 18 GATED / 31 OPEN (headless-buildable) / 2 CLOSED.
The old TOP-10 are fully spent (-> E1-E12). RC2_TODO_QA.md now points to the
consolidated doc for current status.

CONCURRENCY: ran alongside the loop-monitor session below; their /done recorded
their commits but NOT f05b853d, so this entry records it. f05b853d is in git +
pushed regardless.

HELD: the RC2_PLAN.md 8.3 -> DONE stage flip + banner 53->54/62 (~87%) is staged
in the working tree but UNCOMMITTED - the operator rejected that exact edit
earlier in-session. Left for operator confirm; the deliverable itself is shipped.

NEXT: operator confirms the 8.3 DONE flip, then /RC2-Continue picks the next
non-DONE (E-batch E2/E7/E10/E11/E12 - mostly live/release-gated - + Phase 9).
[[project_rc2_build]]
