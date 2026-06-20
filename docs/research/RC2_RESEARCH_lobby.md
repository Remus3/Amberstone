# RC 2.0 Phase-1 Research (stage 1.3): Pre-Game LOBBY UX

Grounded, cited survey of what League companion apps surface BEFORE champ
select (the queue/lobby phase), what LCU endpoints drive it, and a LIFT
verdict for each pattern against RC's current lobby surface.

ASCII only. Cited from live repo greps + web sources (URLs at bottom).
Date: 2026-06-19. Author: research subagent.

---

## 0. Scope clarification: "lobby" vs "champ select"

The League gameflow runs: `None -> Lobby -> Matchmaking -> ReadyCheck ->
ChampSelect -> InProgress -> ... -> PreEndOfGame -> EndOfGame`. RC tracks
these phases (`lcu/lcu_pregame.py:254` `get_gameflow_phase`, returns
`Lobby` / `ChampSelect` / `InProgress` / etc.; `web/js/main.js:659` maps
`Lobby | Matchmaking | ReadyCheck -> "lobby"` view).

This doc is the LOBBY phase only - the screen where you pick a queue,
invite a party, set lane prefs, and hit Find Match. Champ-select-phase UX
(pick/ban recs, counter hints, rune import) is a sibling stage and is
NOT re-covered here except where a competitor blurs the two.

---

## 1. RC's CURRENT lobby surface (ground truth)

RC already has the deepest LCU lobby integration of any tool surveyed.
The "Pre-Game Lobby" dashboard view is live and operator-driven.

### 1a. LCU lobby actions RC already issues
All via `tools/gamepc_lcu_agent.py` (relocated Legion-local agent; the
dashboard POSTs queued commands, JS polls `/api/lcu-cmd-result`):

| Action | LCU call | repo cite |
|---|---|---|
| Find Match (start search) | `POST /lol-lobby/v2/lobby/matchmaking/search` | `tools/gamepc_lcu_agent.py:1463` |
| Cancel Queue | `DELETE /lol-lobby/v2/lobby/matchmaking/search` | `tools/gamepc_lcu_agent.py:1466` |
| Change queue / create lobby | `POST /lol-lobby/v2/lobby {"queueId": qid}` | `tools/gamepc_lcu_agent.py:1474`, `:1662` |
| Set lane prefs (primary/secondary) | `PUT /lol-lobby/v2/lobby/members/localMember/position-preferences` | `tools/gamepc_lcu_agent.py:1540` |
| Party Open/Closed toggle | `PUT /lol-lobby/v2/lobby/partyType` | `tools/gamepc_lcu_agent.py:1549` |
| Invite player | `POST /lol-lobby/v2/lobby/invitations` | `tools/gamepc_lcu_agent.py:1569` |
| Promote member | `POST /lol-lobby/v2/lobby/members/{sid}/promote` | `tools/gamepc_lcu_agent.py:1602` |
| Kick member | `POST /lol-lobby/v2/lobby/members/{sid}/kick` | `tools/gamepc_lcu_agent.py:1632` |
| Read lobby (members enrich) | `GET /lol-lobby/v2/lobby` | `tools/gamepc_lcu_agent.py:680` |
| Ready-check accept | `POST /lol-matchmaking/v1/ready-check/accept` | `lcu/lcu_client.py:96` |
| Ready-check read | `GET /lol-matchmaking/v1/ready-check` | `lcu/lcu_client.py:99` |
| Gameflow phase | `GET /lol-gameflow/v1/phase` | `lcu/lcu_pregame.py:261` |

### 1b. Dashboard lobby VIEW pieces (all live)
`web/js/main.js` `_lobbyViewRefresh` (`:4715`) + `_lobbyViewWireOnce`
(`:4510`) render:
- Queue name header + leader tag + queue selector (leader-only)
  (`main.js:4734`, `:4803`).
- Controls strip: Find Match (gold pulse when searching), Cancel Queue,
  Party Open/Closed toggle, Auto-Accept toggle, primary/secondary lane
  prefs (SR-only lane-pair hidden on ARAM/Arena) (`main.js:4744`-`4824`).
- Match-found state from `lobby.search_state === "MatchFound"` or
  `phase === "ReadyCheck"` (`main.js:4816`).
- Party panel: per-member IGN, YOU/LEADER pips, rank/peak/most-played
  role, copy/promote/kick action pips (`_renderPartyMembers`,
  `main.js:4830`).
- "Your Mains / Party Mains" tab-switched panel (`_renderMains`,
  `main.js:4833`).
- "My Top 8" operator-curated friends short-list with localStorage +
  server `/api/top8` persistence; rows that are lobby members get a
  green `.is-top8-mate` hue (`_renderTop8`, `main.js:4839`, `:3997`).

### 1c. Members enrichment + invite resolution (hard-won)
- Lobby members forwarded with `members[]`, `local_member`, cellId +
  championId, gameName/tagLine enriched by summoner-id (TTL cache)
  (`tools/gamepc_lcu_agent.py:210`-`326`, `:680`-`714`).
- Invite resolution is a LAYERED chain (summonerId -> puuid-cached ->
  friends-scan -> dead legacy by-name) because Riot removed
  `/lol-summoner/v1/summoners/by-name` in the Riot ID migration; Top 8
  invites 100% failed until this fix (LOBBY1 regression,
  `tests/test_lobby_invite_resolution.py:1`-`21`, fix at
  `gamepc_lcu_agent.py:_resolve_invitee_summoner_id`, `:1564`).

### 1d. Confirmed GAPS in RC's lobby surface
- NO last-session / "today's record" / win-streak / tilt recap shown in
  the lobby. The only `tilt_meter` is an IN-GAME widget
  (`web/js/panels/right_now.js:434`), and a `yesterday/avg-of-last-N`
  baseline is explicitly noted as not-yet-wired (`main.js:2871`).
- NO mode-specific lobby prep (e.g. ARAM bench/reroll preview - that is
  a champ-select-phase thing, absent at lobby).
- NO duo/synergy hint AT THE LOBBY phase (RC has a champ-select duo grid
  via `/api/duo-synergy` + `core/smoothed_rates_101qq`, but it does not
  surface for a 2-man party at the lobby/queue screen).
- Auto-Accept is operator-toggle-state only (Phase A); reading the live
  LCU auto-accept and auto-firing the accept is noted as Phase B / not
  wired (`main.js:4777`-`4787`).

---

## 2. External patterns + 6-point LIFT checklist

LIFT verdict scale: HIGH (clear value, low/med effort, legal
re-implementation, slots into existing RC surface), MED (value but
effort or fit friction), LOW (RC already has it, or poor solo-tool fit,
or legal/scope concern). Legal note: all verdicts assume clean-room
re-implementation reading only the public LCU + RC's own data - NEVER
copying a competitor's code, assets, or scraping their private API.

### Pattern A - Opponent / teammate scouting tags at lobby (Overlay App F "Player Tags")
- WHAT: Short labels per lobby player describing habits/trends from
  recent games ("on a winning streak", "first-time on this champ",
  KDA-of-most-played). Overlay App F summarizes "how good or bad the
  opponents and teammates are" and shows winning/losing streaks
  [overlay app F, aggregator Z17].
- HOW: Riot Match-V5 history per summoner -> derive tags. Lobby members
  come from `GET /lol-lobby/v2/lobby` (RC already reads this).
- RC ALREADY HAS IT?: Partial. RC enriches lobby members with rank/peak/
  most-played role in the party panel (`main.js:_renderPartyMembers`,
  `:4830`) and has `rewind_history.db` (~2846 matches, full participant
  +timeline) plus Match-V5 access (ADR-006). It does NOT compute
  habit/streak TAGS, and it only sees the PARTY (pre-champ-select you
  cannot see enemies; the lobby has no enemy list until champ select).
- WHERE IT INTEGRATES: Extend `_renderPartyMembers` /
  `_renderTop8`; new derive step reading `rewind_history.db` +
  Match-V5. Tag computation belongs server-side (route under
  `dashboard/`), not in JS.
- EFFORT+RISK: MED effort (tag heuristics + a route). Risk LOW (own
  data). Caveat: solo tool = you only ever see your own party at the
  LOBBY phase, so enemy scouting is a champ-select-phase feature, not
  lobby. Value at lobby is limited to your duo partner + Top 8.
- LIFT VERDICT: MED. Genuinely useful for a duo partner / Top 8 recap,
  but the headline competitor value (enemy tags) is structurally
  unavailable until champ select. Scope it as "your party + Top 8
  recent-form chips", not enemy scouting.

### Pattern B - Last-session / "today's record" recap on the home/lobby screen
- WHAT: When you open the app pre-queue, show a quick recap: today's
  W/L, current win/loss streak, a tilt/recovery nudge. (Aggregator C +
  aggregator A both lead with a summoner dashboard of recent form before you
  queue [aggregator C, screenrant].)
- HOW: Read local match store; compute since-midnight / last-session
  W/L + streak. No LCU needed beyond knowing it is the Lobby phase.
- RC ALREADY HAS IT?: NO (confirmed gap 1d). RC has the data
  (`rewind_history.db`, session-boundary rules already defined in
  memory `reference_session_boundary_rules`) and an in-game tilt_meter
  (`right_now.js:434`) but renders NO lobby-phase recap; the
  `yesterday/avg-of-last-N` baseline is unwired (`main.js:2871`).
- WHERE IT INTEGRATES: `renderHomePanel` (`main.js:3183`) and/or the
  lobby view header (`lv-window` area, `main.js:4718`). New server
  route to compute the session record from `rewind_history.db`.
- EFFORT+RISK: LOW-MED effort (one query + one panel; the session
  boundary logic already exists). Risk LOW (own data, no Claude/Riot
  live dependency - same posture operator chose for the PGR 0-100
  heuristic).
- LIFT VERDICT: HIGH. Directly fills a confirmed gap, fits the
  solo-tool model perfectly (it is YOUR record), reuses existing data +
  boundary rules, no external dependency, slots into an existing panel.

### Pattern C - Duo synergy hint for a 2-man party AT the lobby
- WHAT: When two friends are in a party pre-queue, suggest a strong
  pairing / show synergy for likely picks before champ select.
  Aggregator C: "suggest to your pal who they should pick ... breaks down
  the top synergies" [aggregator C].
- HOW: Party composition from `GET /lol-lobby/v2/lobby` members (>=2 and
  not self-only). Synergy from a duo win-rate source.
- RC ALREADY HAS IT?: Partial / mis-staged. RC has a LIVE duo-synergy
  lane: `/api/duo-synergy` route + `core/synergy_external_source.fetch_rows`
  feeding `core/smoothed_rates_101qq` (item 277, CLAUDE.md Settled), but
  it surfaces in the CHAMP-SELECT bot/sup grid, not at the lobby when a
  2-man party forms. RC already detects party size >= 2
  (`_renderPartyMembers`, `main.js:4830`).
- WHERE IT INTEGRATES: Gate the existing `/api/duo-synergy` consumer on
  `lobby.members.length >= 2` and render a compact "your duo's best
  pairings" strip in the lobby party panel.
- EFFORT+RISK: LOW-MED (data + route exist; this is a render-placement
  + gating job, not new plumbing). Risk LOW. `RC_DUO_SYNERGY_LIVE=0`
  kill switch already exists.
- LIFT VERDICT: HIGH. Reuses an already-shipped data lane, fills a real
  pre-champ-select moment for the operator's duo, minimal new code.

### Pattern D - Runes / summoner spells / item build auto-import on lock-in
- WHAT: Overlay App E's headline feature - auto-import runes/spells/builds the
  moment you lock a champion [build tool Z18, overlay app E, aggregator Z17].
- HOW: LCU writes to `/lol-perks/v1/pages` (runes),
  `/lol-champ-select/v1/session/my-selection` (spells), item sets.
- RC ALREADY HAS IT?: YES. `lcu/lcu_rune_writer.py` auto-pushes runes on
  champ-select; spells via `/lol-champ-select/v1/session/my-selection`
  (`lcu/lcu_pregame.py:243`-`249`); DS-backed prebuilt item/build orders
  exist. (Known bug: RuneWriter fires only first champ-select per RC
  session, memory `reference_runewriter_dies_after_game1`.)
- WHERE IT INTEGRATES: existing `lcu_rune_writer.py` / pregame path.
- EFFORT+RISK: N/A (already built). The only work is the known
  game-2 regression fix, already tracked.
- LIFT VERDICT: LOW (already have it). This is a champ-select-phase
  feature anyway, not lobby.

### Pattern E - Ready-check support / auto-accept
- WHAT: Surface the ReadyCheck and optionally auto-accept the queue pop
  so you do not miss it while alt-tabbed.
- HOW: `GET /lol-matchmaking/v1/ready-check` (state) +
  `POST .../ready-check/accept`, or the auto-accept toggle.
- RC ALREADY HAS IT?: Partial. RC has both read + accept calls
  (`lcu/lcu_client.py:96`,`:99`) and an Auto-Accept toggle in the lobby
  view, but the toggle is operator-state-only (Phase A); live-read +
  auto-fire is explicitly unwired (`main.js:4777`-`4787`,
  ready-check detected at `main.js:573`,`:611`).
- WHERE IT INTEGRATES: wire `_LV.autoAccept` to actually poll
  `/lol-matchmaking/v1/ready-check` and POST accept when state is
  `InProgress` and the toggle is on.
- EFFORT+RISK: LOW (both endpoints already wrapped; this is connecting
  an existing toggle to existing calls + a poll tick). Risk LOW.
- LIFT VERDICT: HIGH. Small, self-contained, finishes a half-built
  feature the operator already sees in the UI, real quality-of-life win
  (do not miss a pop while reading the dashboard).

### Pattern F - Mode-specific lobby prep (queue-aware UI)
- WHAT: Tailor the lobby UI to the selected mode - ARAM shows bench/
  reroll context, Arena shows duo-pairing, SR shows lane prefs. Apps
  adapt the pre-game panel to the queue [aggregator C, overlay app F].
- HOW: Queue id from `GET /lol-lobby/v2/lobby` `gameConfig` /
  `queueId`; branch the render.
- RC ALREADY HAS IT?: Partial. RC ALREADY branches the lobby view by
  queue: lane-pair shown only on SR queue ids, hidden on ARAM/Arena
  (`main.js:4752`); queue->label map (`champ_select.js:369`); queue->
  adapt-mode map (`champ_select.js:146`). It does NOT add per-mode
  PREP content (e.g. ARAM most-rolled champs, Arena prior duo results).
- WHERE IT INTEGRATES: extend the queue branch in `_lobbyViewRefresh`
  (`main.js:4744`-`4754`) with a per-mode prep block.
- EFFORT+RISK: MED (need a per-mode prep data source; ARAM/Arena lobby
  prep has thin pre-champ-select data). Risk LOW.
- LIFT VERDICT: MED. The structural branching already exists; the value
  add is content the operator may not need at the LOBBY phase (most ARAM
  prep is meaningful only after the bench appears in champ select).

### Pattern G - Friends list / invites / party management
- WHAT: See friends, invite them, manage the party (promote/kick),
  toggle open/closed. Core to every companion's lobby.
- HOW: `/lol-lobby/v2/lobby/invitations`, `.../members/{id}/promote`,
  `.../members/{id}/kick`, `/lol-lobby/v2/lobby/partyType`,
  `/lol-chat/v1/friends`.
- RC ALREADY HAS IT?: YES, fully. Invite (`:1569`), promote (`:1602`),
  kick (`:1632`), party-type toggle (`:1549`), friends-scan invite
  resolution (`:1564`), "My Top 8" curated list (`main.js:4839`).
- WHERE IT INTEGRATES: shipped in lobby view + agent.
- EFFORT+RISK: N/A (built).
- LIFT VERDICT: LOW (already have it, and arguably deeper than
  competitors via the layered invite-resolution + Top 8).

### Pattern H - Gameflow SESSION watch (vs single-shot phase poll)
- WHAT: Subscribe to `/lol-gameflow/v1/session` (or the LCU WebSocket
  `OnJsonApiEvent_lol-gameflow_v1_session`) for richer, event-driven
  phase + queue + map + game-data transitions, instead of polling
  `/phase`.
- HOW: WebSocket wildcard subscription `OnJsonApiEvent_lol-lobby_v1*` /
  gameflow session [riot-api-libraries].
- RC ALREADY HAS IT?: Partial. RC polls `/lol-gameflow/v1/phase`
  (`lcu/lcu_pregame.py:261`) and there is a `gamepc_phase_watcher.py`,
  but RC is poll-based, not WS-subscribed to the gameflow SESSION
  object (which carries map/queue/gameData inline).
- WHERE IT INTEGRATES: the phase watcher / lcu agent loop.
- EFFORT+RISK: MED-HIGH (LCU WebSocket plumbing + auth; RC's current
  poll model works fine for a single-user local tool). Risk MED (more
  moving parts for marginal latency gain at 1-PC).
- LIFT VERDICT: LOW. Poll-based phase detection is adequate for a solo
  local tool; the session-WS upgrade is effort without a user-visible
  payoff here. Do not pursue unless a concrete latency problem appears.

---

## 3. LCU endpoint reference (lobby phase)

Confirmed paths RC uses or could use (LCU is unofficial/unsupported;
discover via Rift Explorer / swagger.dysolix.dev / lcu.kebs.dev
[hextechdocs, riot-api-libraries]):

- `GET  /lol-gameflow/v1/phase` - current phase string.
- `GET  /lol-gameflow/v1/session` - richer phase + queue + map + gameData
  (RC does NOT yet read this; Pattern H).
- `GET/POST /lol-lobby/v2/lobby` - read lobby / create-or-change (queueId).
- `POST /lol-lobby/v2/lobby/matchmaking/search` - Find Match.
- `DELETE /lol-lobby/v2/lobby/matchmaking/search` - Cancel.
- `POST /lol-lobby/v2/lobby/invitations` - invite (array of invitees).
- `GET  /lol-lobby/v2/lobby/invitations` - pending invitations
  (referenced in `tests/test_lobby_invite_resolution.py:39`; RC reads
  members but does not surface INBOUND invitations as a UI list - minor
  possible add).
- `PUT  /lol-lobby/v2/lobby/members/localMember/position-preferences`.
- `PUT  /lol-lobby/v2/lobby/partyType` - open|closed.
- `POST /lol-lobby/v2/lobby/members/{summonerId}/promote` | `/kick`.
- `GET  /lol-matchmaking/v1/ready-check` + `POST .../accept`.
- `GET  /lol-chat/v1/friends` - friends list (used for invite
  resolution; could back a richer friends picker).

Auth: lockfile (port + password), `verify=False` TLS - RC's
`lcu/lcu_client.py` already does this (memory `reference_no_riot_api_key`,
`reference_riot_ca_cert_install`).

---

## 4. Summary recommendation (solo-tool lens)

RC's lobby plumbing is already best-in-class (every write action +
layered invite resolution + Top 8). The gaps are presentation/insight,
not LCU coverage. The three HIGH-lift wins are all small and reuse
existing data/endpoints:

1. **Last-session recap on home/lobby (Pattern B)** - fills a real gap,
   own data, zero external dependency.
2. **Duo synergy at the lobby for a 2-man party (Pattern C)** - re-stage
   already-shipped `/api/duo-synergy` to fire when a party forms.
3. **Finish ready-check auto-accept (Pattern E)** - connect an existing
   UI toggle to already-wrapped endpoints.

Deliberately NOT recommended: enemy scouting tags at lobby (enemies are
not visible until champ select - structural), gameflow-session WebSocket
(effort without solo-tool payoff), anything already shipped (build
import, party management).

---

## Sources

- https://screenrant.com/best-companion-apps-league-of-legends/
- https://build-tool-z18.invalid/en/blog/best-league-of-legends-app-2026/
- https://aggregator-z17.invalid/best-league-of-legends-add-ons/
- https://overlay-app-e.invalid/lol
- https://aggregator-c.invalid/blog/how-to-use-the-aggregator-c-desktop-app-guide/
- https://aggregator-c.invalid/blog/lol-op-duo-queue-strats-for-strategist/
- https://overlay-app-f.invalid/support
- https://overlay-platform-m.invalid/app/overlay-app-f
- https://riot-api-libraries.readthedocs.io/en/latest/lcu.html
- https://hextechdocs.dev/getting-started-with-the-lcu-api/
