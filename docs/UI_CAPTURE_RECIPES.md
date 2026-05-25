# UI capture recipes

Per-page operator recipes for Live UI captures (Game-PC monitor 1).
All routes assume the dashboard is open in Chrome on Game-PC at
`https://legion-rc:8888/` (or `https://192.168.8.230:8888/` LAN fallback).

For mock-data captures (when operator is between games): append
`?ui_mock=1` to the URL, then add `&mode=<sr|aram|arena>` where the
page splits per-mode. Hard-reload (Ctrl+Shift+R) to bypass the service
worker cache. Capture via `mcp__gamepc__capture_monitor` (monitor 1,
max_width 1280, jpeg q75).

## Page #3 - Replay

Live: select a real match from `rewind_history.db` (populated as of
item 187 with 2904+ matches). The 10-row participant table renders
correctly per the item 185 flex-allocation re-tune
(`.replay-grid-wrap min-height: 360px` + `.replay-events-list max-height: 320px`).

Mock: `https://legion-rc:8888/?ui_mock=1#replay`
Fixture: `web/data/ui_mock/replay.json` (4 matches: Normal Draft 10p +
Arena overflow + ARAM empty + 2p ranked-solo).

Capture step: navigate, hard-reload, then capture monitor 1.

## Pages #11/12/13 - Active Match (SR/ARAM/Arena)

Live: requires the operator in an active game with LCU
phase=InProgress. The view auto-promotes via `_viewAutoDerive`
(`web/js/main.js:548`) once liveclient + LCU phase resolve. Capture
during the in-game window.

Mock per mode (item 188):
- SR:    `https://legion-rc:8888/?ui_mock=1&mode=sr#active-match`
- ARAM:  `https://legion-rc:8888/?ui_mock=1&mode=aram#active-match`
- Arena: `https://legion-rc:8888/?ui_mock=1&mode=arena#active-match`

Fixtures:
- `web/data/ui_mock/active_match_sr.json` (5v5 standard, coach
  payload + 10-player liveclient + summoner_cooldowns)
- `web/data/ui_mock/active_match_aram.json` (5v5 shared vision,
  ARAM coach payload, dot overlay suppressed via
  `_AM_SHARED_VISION` set)
- `web/data/ui_mock/active_match_arena.json` (6x2 = 12 players per
  item 180 `_arena_teams()` distil; NOT 6x3 - that was a stale
  c3a1e23 premise corrected at item 183)

Capture step: navigate to URL, hard-reload, wait 2s for the mock
fetch + DS rerank + spike_curve + ward_heat + draft_elo modules to
hydrate, then capture monitor 1.

Render verification: dispatcher wired at `web/js/main.js`
`_amMockLoad` (around the `_csMockLoad` helper); the `applyState`
call-site short-circuits to mock when `body.dataset.uiMock === "1"`
+ `?mode=<X>` is present; the `applyView("active-match")` kick
fires the dispatcher on first navigation too.

## Pages #14/15/16 - Post Game Review (SR/ARAM/Arena)

Live: navigate to `#last-match` after completing a game. SR baseline
captured at item 182; ARAM + Arena captured via item 183 mock fixtures.

Mock per mode:
- SR:    `https://legion-rc:8888/?ui_mock=1#last-match` (default fixture)
- ARAM:  `https://legion-rc:8888/?ui_mock=1&mode=aram#last-match`
- Arena: `https://legion-rc:8888/?ui_mock=1&mode=arena#last-match`

Fixtures:
- `web/data/ui_mock/last_match_aram.json` (10p ARAM mapId 12 queue 450,
  `data-aug="0"` empty augment grid)
- `web/data/ui_mock/last_match_arena.json` (12p Arena 6x2 mapId 30
  queue 1750 CHERRY, `data-aug="1"` 9-col augment grid)

## Notes

- ADR-008 asset-hash auto-serves CSS/JS/JSON edits; never restart RC
  for asset-only changes.
- The `?ui_mock=1` flag also clears `rc-view-manual` localStorage
  sticky so the audit-capture hash route survives the PWA reload race
  (item 163 + 184 carries).
- For Active Match captures, the spike_curve + ward_heat + draft_elo
  panels still call live endpoints; mock fixture only overrides the
  coach payload + liveclient + summoner_cooldowns ctx.
