# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-21 (interactive, continue) - overlay CALL focal hierarchy + ASCII arrow MUST-FIX

Continued item 558's overlay-audit NEXT queue. Two commits (pushed): `a4d6e6ba`
overlay.css sec 3b - the CALL pane now out-weights peers (4px `--signal-info`
indigo rail + tinted `rgba(28,30,48,0.93)` backing + accent head; overlay-scoped,
higher-specificity than the sec-3 base) so the eye lands on the time-critical
RIGHT NOW/ACTION first in the ~1.5s glance. `806c77dd` ascii-clean arrows - the
audit's ASCII phase caught coach.action "CRASH BOT -> SETUP DRAKE" with a real
U+2192; item 558's `_ascii_clean` missed arrows. Extended `_ASCII_PUNCT`
(arrow/symbol family) + a NFKD+ascii-ignore fallback so NO codepoint>127 can
reach the HUD; +11 TDD cases (chr(0xNNNN) inputs so the test stays 7-bit ASCII).

Tier-1 (overlay CSS + one dashboard module + test), no engine/DS/Share. RC
restarted (pid 8904, reload_ok, game re-detected mode=sr). LIVE-VERIFIED on the
legion-rc origin (live SR bot-practice game): CALL hierarchy renders, live
/api/state coach ASCII-CLEAN (action 'SETUP DRAKE'), WS SecurityError gone (item
558 fix holds; 1 console error = favicon 404). Read-only 5-phase fixture audit =
ship-ready, no MUST-FIX. This also CLOSED item 558's owed live-render verify.

NEXT (item-558 queue tail): L1 minimap-anchored objective timers (needs an
overlay minimap canvas), L3 live spike cue (HIGH, computed). Background chip
spawned: FIGHT MODEL pane (`#am-pane-ovds`) clips in the default subset - gate it
to the build panelset (pre-existing, audit-found, NOT this slice).

---

# 2026-06-21 (interactive) - overlay live-render TRUE root-cause (WS mixed-content) + ds-503 + ASCII coach

CORRECTS the prior entry. The "overlay dead/placeholder in-game" bug was NOT
backgroundThrottling (red herring; `8c7319f5` kept as harmless hardening). TRUE cause:
the overlay loads HTTPS at legion-rc:8888 and main.js opened an INSECURE
ws://legion-rc:8891 -> browsers BLOCK mixed-content ws:// for non-localhost hosts ->
SecurityError at boot aborted init -> placeholders. It hid for months because the
"test in a normal browser" step used 127.0.0.1, which is EXEMPT from the block and
masked it. RULE: test the overlay on the legion-rc origin, NOT 127.0.0.1.

Commits (all pushed): `91cf480a` overlay WS fix + SR-coach PRACTICETOOL re-enable +
rc-shell occlusion switches ; `44174fb1` ds-preview/ds-knobs graceful build_complete 200
(was 503 spam on a full 6-item build) ; `d2170d4d` ASCII-clean coach text in build_state
(Haiku em-dash reached the HUD) ; `0a70a547` route WS to ws://127.0.0.1:8891 (kills
SSL-handshake spam; :8891 has no TLS, 127.0.0.1 is exempt + co-located). Updated memory
reference_electron_overlay_throttling. rc-shell bounced to a fresh instance (pid 4996).

NEXT (operator AFK in a practice match for this): UI passes from the live UI/UX audit -
pop-out/hierarchy SHOULD-FIX (CALL action must out-weight peers), L1 minimap-anchored
objective timers, L3 live spike cue (HIGH, computed, gated out of overlay.css). Verify the
in-game overlay now renders live coach. Tail: :8891 no TLS (push via ws://127.0.0.1, fine on 1-PC).

---

# 2026-06-20/21 (interactive) - overlay OPEN batch + live overlay-throttling root-cause

Shipped 4 commits, all CI-green (run 27892032332): `cdd494fa` QA1 ward-ready glyph
cue (LIVE-verified in a real game - Caitlyn `trinket_ready` on the wire + glyph
rendered in a browser) + `2e5326b5` QA9 combat-mode declutter (`body[data-fight]`
sheds non-urgent panes, hysteresis latch, respects explicit panelsets) +
`8c7319f5` rc-shell `backgroundThrottling=false` + `f570f527` QA4 objective
respawn chips (dragon/baron/herald). Local gate green: hygiene 13 / ruff / ward_cue
11 / web/js node 46 / rc-shell node 253. RC pid 11268 healthy.

BIGGEST FIND - the recurring "overlay dead/empty in-game" bug is ROOT-CAUSED + FIXED
(`8c7319f5`). Electron throttles an OCCLUDED renderer; the always-on-top overlay is
always covered by the game, so its `/api/state-stream` SSE re-render was suspended
and it froze on the scaffold. PROVEN: the identical `?overlay=1` page renders
perfectly in a normal browser against the live backend mid-game (SSE + panes + the
QA1 glyph). Relaunch never helped (re-throttles the new window). Fix =
`backgroundThrottling: false`. AWAITING operator relaunch (`npm start`, no rebuild)
to confirm live - root cause is proven, so this is verification not an open question.

OPEN THREADS (do NOT redo the shipped work):
- Screen capture: `self_grab` = `PIL.ImageGrab` (GDI BitBlt, `vision_server/_frame.py:67`)
  returns BLACK for the game's accelerated DirectX surface; only the overlay grabs.
  Operator to foreground the game / confirm Borderless. Ties into QA6.
- Remaining overlay queue: QA6 (Win32 fullscreen hint), QA12 [L] restructure, QA13
  UIPI, QA14 display-pick, QA4-ZoI tail. QA4 camp chips INFEASIBLE (no Live Client
  camp events). [[project_rc2_build]] [[reference_gamepc_League_fullscreen_lockup]]

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
