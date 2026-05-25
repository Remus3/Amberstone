# Cherry / Arena 1750 set_augment_intent scaffold notes

Item 188 Slice C closes the scaffold half of item 187 Slice E's research-only
findings. The handler at `tools/gamepc_lcu_agent.py:1179` replaces the
`augment_intent_unsupported` no-op with a 4-endpoint PATCH chain; first 2xx
wins; all-fail returns the per-attempt error list so a live operator can see
which LCU surface the current League patch exposes.

## Endpoint priority chain

The handler tries in order; the first 2xx response wins. Body shape on every
attempt is `{"augmentId": <int>, "slotIndex": 0..3}`.

1. `PATCH /lol-cherry-game-intra-event/v1/augment-select` - item 187 Slice E
   primary guess. Intra-event is the live-game phase surface Cherry uses for
   round-by-round augment picks (rounds 1-4: silver / gold / prismatic).
2. `PATCH /lol-cherry/v1/augment-select` - shorter namespace fallback for
   older patches that use the bare `/lol-cherry/v1/*` tree.
3. `PATCH /lol-cherry-summoner/v1/augments` - per-summoner namespace fallback.
4. `POST /lol-cherry-game-intra-event/v1/augment-select` - method fallback in
   case the surface expects POST not PATCH (mirrors item 180's queueId
   fallback discovery pattern for queue 1750 / Practice Tool queueId 3140).

## Live verification recipe (Arena 1750)

Requires operator at Game-PC + a real Arena lobby reaching the augment-select
phase. Cannot be scaffolded headless - the LCU endpoint is only live during
the in-game augment-pick window.

1. Operator commits to Arena queue 1750 (CHERRY mapId 30); accepts; reaches
   champ-select; locks in a champion; advances into the active match.
2. At the first augment round, operator triggers via the dashboard:
   `POST https://legion-rc:8888/api/lcu-cmd` with body
   `{"cmd": "set_augment_intent", "augment_id": <id>, "slot": 0}`. Dispatch
   chain: RC dashboard `_LCU_ALLOWED_CMDS` -> :8889 vision -> Game-PC agent
   `execute_command` -> `lcu_request` PATCH chain.
3. Inspect the response envelope. On success: `{"ok": True, "endpoint":
   "PATCH /lol-cherry-game-intra-event/v1/augment-select", ...}` - this is
   the truth that updates this doc + the handler's primary comment. On
   total failure: `{"ok": False, "tried": [...]}` lists each attempt with
   its HTTP error so the operator can pivot.
4. Once the live endpoint is known, the `attempts` tuple in the handler can
   shrink to just the verified surface for performance; for now the 4-entry
   chain costs ~50-200ms total on all-fail vs ~10-30ms on first-hit success.
5. Test the live PATCH chain via the gated suite:
   `RC_LIVE_ARENA=1 RC_LIVE_AUG_ID=<id> RC_LIVE_AUG_SLOT=0 py -m pytest
   tests/test_set_augment_intent_handler.py::LiveAugmentSelectIntegrationTests`.
   The test prints the live endpoint verdict to stdout.

## If all 4 paths 404

Likely surfaces to probe + add to the chain (operator-at-Game-PC + Chrome
DevTools, or LCU lockfile + curl):

- `/lol-cherry-game-intra-event/v1/augments` (list endpoint - GET first to
  confirm namespace alive, then find the write verb).
- `/lol-cherry-game-intra-event/v1/state` (envelope endpoint - may carry the
  augment-pick payload as a sub-object that PATCHes wholesale).
- `/lol-gameflow/v1/session/augment-select` (gameflow surface fallback - if
  Cherry routes augment picks through the generic session surface).
- Inspect `/help` on the live LCU port: filter for `cherry` + `augment`.

## Game-PC agent redeploy reminder

The handler change at `tools/gamepc_lcu_agent.py:1179` lives on Legion in
git; the live agent runs on Game-PC at `C:\RC-Agent\gamepc_lcu_agent.py`.
Redeploy OWED at the operator's next Arena window via the HTTP-pull dance
per the `reference_gamepc_http_server_redeploy` memory: Legion `py -m
http.server 8765 --bind 0.0.0.0 --directory tools`; Game-PC `Invoke-
WebRequest` to `.new` + sha256-verify + taskkill old pid + atomic
`Move-Item` + pythonw relaunch. This session did NOT redeploy - the
operator coordinates the swap when next in Arena.

## Dashboard allowlist (verified, no edit needed)

`dashboard/routes_loadout.py::_LCU_ALLOWED_CMDS` already contains
`set_augment_intent` per item 164's batch addition. The new handler is
allowlist-routable without any RC restart.
