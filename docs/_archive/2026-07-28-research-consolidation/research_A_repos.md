# Research A: three ReformedDoge repos vs Riot Commander

Probed live 2026-07-28. All three repos EXIST and are public. None is empty, none 404s.
Method: GitHub REST API for metadata, `raw.githubusercontent.com` for README + source,
`git/trees/main?recursive=1` for full file trees, direct HTTP probes for LICENSE files.
Source files downloaded and read locally (not summarised from README claims).

Cross-cutting fact, established by probe and not by inference:

    LICENSE     -> 404 on main AND master, all three repos
    LICENSE.md  -> 404 on main AND master, all three repos
    LICENSE.txt -> 404 on main AND master, all three repos
    COPYING     -> 404 on main AND master, all three repos
    api.github.com "license" field -> null, all three repos

No licence file exists in any of the three. Under the Berne default they are
"all rights reserved". NONE of them can be vendored into RC. Same precedent as
KebsCS (CLAUDE.md Settled list: "no license - do not vendor").

---

## 1. ReformedDoge/riot-invoke-api

### WHAT IT IS

A documentation-only repo. Five files, 6 KB total:

    .gitattributes              66 bytes
    README.md                   19,947 bytes
    assets/maintained.svg       1,030 bytes
    riot_invoke_commands.json   12,051 bytes

No code. `language: null`. It catalogs the native C++ IPC endpoints that the
League client's CEF renderer can call through the `window.riotInvoke` JS bridge.

I parsed `riot_invoke_commands.json` directly: 36 entries, four fields each
(`command`, `module`, `description`, `params`). The complete namespace census:

    Window.*      22  Activate, AddToTaskbar, ApplyMask, CenterToScreen,
                      CenterWithinParent, Flash, GetValidWindowSizes, Hide,
                      Minimize, MoveBy, MoveTo, RemoveFromTaskbar, ResizeBy,
                      ResizeTo, Restore, ScreenData, SetDebugWindowFrameVisibility,
                      SetResizeBounds, SetTitle, Show, ShowDevTools, SyncMinimize
    Mouse.*        4  SetDragBarHeight, SetDragEnabled, SetResizeBounds,
                      SetResizeEnabled
    RiotClient.*   3  Copy, Exit, Paste
    File.*         2  RequestDirectoryPath, RequestSaveFilePath
    path-style     5  /error-monitor/v1/ux/logs, /plugin-manager/v3/plugins-manifest,
                      /process-control/v1/process/quit,
                      /tracing/v1/performance/ux_run, /tracing/v1/trace/critical-flow

That is the entire surface. It is OS window management, mouse drag-bar config,
native file dialogs, and clipboard. There is ZERO game data, ZERO champion data,
ZERO match data, ZERO LCU REST.

Auth model: none, and none is needed - because the bridge is only reachable from
JavaScript already executing inside the client's own CEF renderer process. It is
NOT lockfile-based and NOT Riot-API-key based. It is not a network API at all;
it is an in-process IPC bridge. Reaching it requires code injection into the
client (Pengu Loader or equivalent).

### LICENCE

No licence file. The README's closing section, quoted verbatim:

> "## Disclaimer & License
>
> This project is an independent reverse-engineering and documentation effort
> intended for educational, research, and plugin development purposes. All
> associated native layouts and designs are property of Riot Games."

A heading called "License" that grants nothing. CANNOT be vendored.

### LAST ACTIVITY

Created 2026-05-24T07:28:37Z. Last push 2026-05-24T10:09:49Z. Roughly three
hours of work, then nothing for two months. 0 stars, 0 forks, 6 KB, not archived.

### WHAT RC ALREADY HAS

`lcu/lcu_client.py` (631 lines) is a lockfile-authenticated HTTP client against
the LCU REST API - the surface that actually carries summoner, ranked, lobby,
champ-select and gameflow data. RC is an EXTERNAL Python process. It has no CEF
renderer to inject into, so `window.riotInvoke` is not merely redundant, it is
unreachable from RC's architecture.

The one thing RC does not have is an LCU event-subscription socket (grep of
`lcu/`, `core/`, `agents/` finds `websockets` only in `core/obs_publisher.py`,
`core/obs_frame_source.py`, and `agents/agent2_backend/ws_server.py` - none of
them LCU). This repo does not help with that either: it documents zero
subscription endpoints.

### VERDICT

**NO VALUE.**

Not thinner than what RC ships - orthogonal to it, and architecturally
unreachable. Window.Minimize and RiotClient.Paste do not advance a coaching
dashboard. Nothing to adopt, nothing to reference, nothing to lift.

### EVIDENCE

- https://api.github.com/repos/ReformedDoge/riot-invoke-api -> `"license": null`,
  `"language": null`, `"size": 6`, `"stargazers_count": 0`,
  `"pushed_at": "2026-05-24T10:09:49Z"`
- https://api.github.com/repos/ReformedDoge/riot-invoke-api/git/trees/main?recursive=1
  -> 5 paths, listed above
- https://raw.githubusercontent.com/ReformedDoge/riot-invoke-api/main/riot_invoke_commands.json
  -> 36 entries, namespace census computed above
- https://raw.githubusercontent.com/ReformedDoge/riot-invoke-api/main/README.md
  line 4: "This document catalogs the native C++ Inter-Process Communication
  (IPC) endpoints exposed to the League of Legends CEF process via the
  `window.riotInvoke` bridge."
- LICENSE/LICENSE.md/LICENSE.txt/COPYING on main and master -> all HTTP 404

---

## 2. ReformedDoge/Snooze-Manager

### WHAT IT IS

A Pengu Loader plugin manager, JavaScript, 635 KB, 30 files. It runs INSIDE the
League client. 19 QoL modules plus a shared `generalUtils.js` (73,750 bytes) and
seven locale files. Largest modules: `whaleHelper.js` (128 KB, loot/reroll
previewer), `gameAnalysisPopup.js` (115 KB, player rank + match history modal),
`nameSpoofer.js` (105 KB, cosmetic local name spoofing), `autoLockChampion.js`
(56 KB), `socialPanelTweaks.js` (59 KB).

README, verbatim on its own design claim:

> "Everything is built to be lightweight and event driven: no embedded React
> application, no bloat, no constant polling of the client for changes and so on."

I read the LCU layer in `generalUtils.js` to check that claim. It is true and
the mechanism is `ctx.socket.observe(uri, listener)` (line 756) - Pengu Loader
hands the plugin an already-connected client socket context, and the plugin
registers per-URI observers over it. There is no lockfile parsing and no
independent WSS handshake; the socket is injected by the host loader.

Data surfaces it touches, extracted by grep across all modules:

    LCU:   /lol-champ-select/v1/session, /lol-gameflow/v1/session,
           /lol-gameflow/v1/gameflow-phase, /lol-lobby/v2/lobby,
           /lol-ranked/v1/ranked-stats/, /lol-summoner/v1/current,
           /lol-summoner/v1/summoners/, /lol-summoner/v2/summoners/puuid/,
           /lol-summoner/v1/alias/lookup, /lol-challenges/v1/challenges/local,
           /lol-game-data/assets/v1/cherry-augments.json,
           /lol-game-data/assets/v1/{champion-icons,items,perks}
    Web:   https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw
           https://api.github.com/repos/ReformedDoge/Snooze-Manager/releases/latest

That wiki URL is the only non-LCU data source in the repo, and it is the single
module worth a serious look: `SnoozeBalanceTooltip.js`.

### THE ONE MODULE THAT OVERLAPS RC: SnoozeBalanceTooltip

`fetchWikiData()` (line 243) fetches `Module:ChampionData/data?action=raw` and
brace-balance-parses the Lua to pull per-champion per-mode balance modifiers.
`parseStatsBlock()` (line 209) covers six mode keys:

    ['aram', 'ar', 'nb', 'ofa', 'urf', 'usb']

and renders 12 display axes (`DISPLAY_ORDER`): dmg_dealt, dmg_taken, healing,
shielding, attack_speed, total_as, ability_haste, movement_speed, tenacity,
crit_mod, energyregen_mod, manaregen_mod. Output is a hover tooltip in champ
select.

### WHAT RC ALREADY HAS

RC ships the SAME data from the SAME wiki module, already parsed, already
versioned per patch, already wired into the engine and the coach prompt.

`data/daemon_slayer/16.14.1/wiki_stats.json`, probed live:

    _source: "wiki.leagueoflegends.com Module:ChampionData/data (action=raw +
             getter fallback) PRIMARY; CommunityDragon character bins BACKFILL
             of nulls"
    _patch: 16.14.1
    _champ_count: 171
    _with_mode_modifiers: 170

    modes present: ar 45, aram 158, nb 32, ofa 81, swift 13, urf 100, usb 44
    stat keys:     ability_haste, arm_base, arm_lvl, as_lvl, dam_lvl, dmg_dealt,
                   dmg_taken, energyregen_mod, healing, hp_base, hp_lvl, ms_mod,
                   shielding, tenacity, total_as

RC covers 7 modes to Snooze's 6 - RC additionally carries `swift` (Swiftplay).
RC carries 15 stat keys to Snooze's 12, including the Arena/Swiftplay ADDEND
stat overrides (`hp_base`, `hp_lvl`, `dam_lvl`, `arm_base`, `arm_lvl`, `as_lvl`)
that Snooze's multiplier-only tooltip does not model at all.

Consumers already wired in RC:
- `agents/daemon_slayer/data_loader.py:520` `mode_modifier()` accessor, with
  `_WIKI_MODE_ALIASES` bridging engine mode strings to the wiki keys
- `core/aram_balance_context.py` - deterministic coach-prompt line for the
  operator's own champion
- `dashboard/routes_aram_balance.py` - the ARAM balance grid panel
- `agents/daemon_slayer/tests/test_mode_modifiers_item232.py` and
  `test_sidecar_accessors_item232.py` - regression-pinned

Every other module is client-side QoL with no RC analogue and no RC ambition:
auto-accept, auto-honor, auto-queue, auto-ban, dodge button, loot reroll
previewer, social panel tweaks, profile cosmetics, name spoofing. Several
(`nameSpoofer`, `PenaltyUISuppress`, `useClientDuringGame`) are client-behaviour
modification of exactly the kind RC deliberately stays clear of.

`gameAnalysisPopup.js` is the closest thing to an RC feature (pre-game player
rank + recent history). RC already reaches ranked-stats through `lcu_client.py`
and holds far deeper history in `rewind_history.db`.

### LICENCE

No licence file. No licence statement anywhere in the README. The README does
carry a credits block acknowledging third-party origin for several modules
("Name Spoofer By Lx", "Original balance buff viewer concept by Nomi",
"initial concept from wjz_p's Sona"), which compounds the provenance problem:
even the author does not hold clean title to all of it. CANNOT be vendored.

### LAST ACTIVITY

Created 2026-05-27T17:20:35Z. Last push 2026-07-28T03:12:48Z - actively
maintained, pushed the same day as this research. 3 stars, 6 forks, not archived.

### VERDICT

**REFERENCE-ONLY** - and even the reference value is close to nil.

The only overlapping module (Balance Tooltip) is strictly thinner than what RC
already ships: fewer modes, fewer stat axes, no Arena/Swiftplay addend handling,
no patch versioning, no engine consumer. Everything else is client-side QoL
outside RC's remit. Do not vendor - no licence, plus acknowledged third-party
code inside it.

One idea is worth naming, though it is NOT this repo's invention and NOT
liftable from it: event-driven LCU subscription instead of polling. RC has no
LCU event socket. Snooze gets its socket handed to it by Pengu Loader
(`ctx.socket.observe`), so there is no portable implementation here to copy;
RC would have to build a lockfile-authenticated `OnJsonApiEvent` WSS client from
scratch. That is a standard, well-documented LCU capability. Note it as an RC
backlog idea if desired; do not credit or copy this repo for it.

### EVIDENCE

- https://api.github.com/repos/ReformedDoge/Snooze-Manager -> `"license": null`,
  `"language": "JavaScript"`, `"size": 635`, `"stargazers_count": 3`,
  `"forks_count": 6`, `"pushed_at": "2026-07-28T03:12:48Z"`
- https://api.github.com/repos/ReformedDoge/Snooze-Manager/git/trees/main?recursive=1
  -> 30 files, not truncated
- https://raw.githubusercontent.com/ReformedDoge/Snooze-Manager/main/modules/SnoozeBalanceTooltip.js
  line 209: `const modes = ['aram', 'ar', 'nb', 'ofa', 'urf', 'usb'];`
  line 243: `const res = await fetch('https://wiki.leagueoflegends.com/en-us/Module:ChampionData/data?action=raw');`
- https://raw.githubusercontent.com/ReformedDoge/Snooze-Manager/main/modules/generalUtils.js
  line 756: `subscription = ctx.socket.observe(uri, listener);`
- RC live probe of `C:\Riot Commander\data\daemon_slayer\16.14.1\wiki_stats.json`:
  170 of 171 champions carry `mode_modifiers`; 7 modes; 15 stat keys (above)
- RC `agents/daemon_slayer/data_loader.py:520` `mode_modifier()`;
  `core/aram_balance_context.py`; `dashboard/routes_aram_balance.py`
- LICENSE/LICENSE.md/LICENSE.txt/COPYING on main and master -> all HTTP 404

---

## 3. ReformedDoge/Snooze-CSS

### WHAT IT IS

A Pengu Loader plugin for theming the League of Legends CLIENT. JavaScript,
3,047 KB, 20 files. The bulk is two generated data blobs:

    src/catalog.js     448,484 bytes   470+ pre-mapped client CSS selectors
    src/builder.js     321,040 bytes   visual property builder UI
    src/assets.js       69,084 bytes
    src/analyzer.js     58,744 bytes
    src/generalUtils.js 54,464 bytes
    src/styles.js       49,334 bytes
    src/raw.js          45,328 bytes
    demo-showcase.css   27,928 bytes

Feature set per README: a Quick Theme Builder, an Omni-Inspector element picker,
the Visual Builder Catalog, a Raw CSS editor with autocomplete, and an Analyzer
that "captures the current view state to generate spatial maps, identify
flex/grid constraints, and map z-index stacks" for feeding to an LLM. Activated
by Alt+C inside the client.

I read `src/analyzer.js`. Its `CLIENT_ZONES` array is hard-bound to Riot's own
Ember/CEF DOM roots:

    rcp-fe-viewport-main, rcp-fe-viewport-overlay, rcp-fe-viewport-sidebar,
    rcp-fe-viewport-persistent, #lol-uikit-layer-manager

Every selector in the 448 KB catalog is a Riot client selector. The entire asset
is worthless outside the League client DOM.

### WHAT RC ALREADY HAS

RC's UI is its own HTTPS dashboard at `:8888` plus an Electron overlay, with its
own design-token CSS system in `web/css/` and `docs/design`, authored to a
1920x1080 baseline. RC does not theme the League client and has no plan to -
memory `feedback_electron_overlay_only` and `feedback_companion_not_ingame_viewing_source`
both point the other way.

There is no shared surface. Snooze-CSS's catalog cannot be applied to RC's DOM,
and RC's tokens cannot be applied to Riot's. The Analyzer's "DOM state to text
to LLM to CSS" loop is a mildly interesting workflow pattern, but RC already has
a stronger, purpose-built equivalent in the 5-phase UI fixture-audit ritual
(`feedback_phase3_fixture_ritual`), which reviews STRUCTURE / TYPOGRAPHY /
HIT-TARGETS / ASCII / HIERARCHY against RC's own baseline rather than dumping a
DOM snapshot at a model.

### LICENCE

No licence file. The README contains a disclaimer only, no grant. Quoted
verbatim from the README's disclaimer: the project is
"a third-party modification and is not affiliated with or endorsed by Riot Games."
CANNOT be vendored.

### LAST ACTIVITY

Created 2026-03-23T23:55:21Z. Last push 2026-07-06T02:35:24Z - about three weeks
before this research. 4 stars, 0 forks, not archived.

### VERDICT

**NO VALUE.**

Wrong DOM, wrong process, wrong problem. It themes Riot's client; RC renders its
own dashboard. The one transferable idea (serialise DOM state for an LLM) is
already covered better by RC's existing fixture-audit ritual. And with no
licence, the 448 KB selector catalog - the only genuinely laborious artifact
here - is untouchable anyway.

### EVIDENCE

- https://api.github.com/repos/ReformedDoge/Snooze-CSS -> `"license": null`,
  `"language": "JavaScript"`, `"size": 3047`, `"stargazers_count": 4`,
  `"forks_count": 0`, `"pushed_at": "2026-07-06T02:35:24Z"`,
  description: "An advanced visual sculpting and analysis suite for theming the
  League of Legends client"
- https://api.github.com/repos/ReformedDoge/Snooze-CSS/git/trees/main?recursive=1
  -> 20 files, not truncated
- https://raw.githubusercontent.com/ReformedDoge/Snooze-CSS/main/src/analyzer.js
  lines 8-38: `CLIENT_ZONES` bound to `rcp-fe-viewport-*` and
  `#lol-uikit-layer-manager`
- https://raw.githubusercontent.com/ReformedDoge/Snooze-CSS/main/README.md
  "Requirements: Pengu Loader - A free, open-source tool that lets you run
  plugins inside the League client."
- RC side: `web/css/`, `docs/design`, `project_dashboard_ui_baseline`,
  `feedback_phase3_fixture_ritual`
- LICENSE/LICENSE.md/LICENSE.txt/COPYING on main and master -> all HTTP 404

---

## Incidental finding (not in scope, flagged for the operator)

The same owner also ships `ReformedDoge/Mayhem-Doctor`, described as "Your
personal ARAM Mayhem analyst, built right into the League client" (JavaScript,
last pushed 2026-07-24, licence: None). That is the only repo in the account
whose PROBLEM DOMAIN overlaps RC's ARAM Mayhem coaching. It was not part of this
task and has not been read. Same no-licence constraint would apply.
Source: https://api.github.com/users/ReformedDoge/repos

---

## BOTTOM LINE

1. All three repos exist and were read at source level; all three have NO licence
   file on main or master, so none can be vendored into RC under the KebsCS
   precedent - the question of usefulness is therefore moot for adoption.
2. Nothing here is thicker than what RC already ships: riot-invoke-api documents
   36 window/mouse/clipboard IPC calls with zero game data and is unreachable
   from an external Python process; Snooze-Manager's only overlapping module
   reads the same wiki balance module RC already parses, with 6 modes to RC's 7
   and 12 stat axes to RC's 15; Snooze-CSS themes Riot's DOM, not RC's.
3. Net verdicts - riot-invoke-api NO VALUE, Snooze-Manager REFERENCE-ONLY,
   Snooze-CSS NO VALUE; the single idea worth carrying away is that RC has no
   lockfile-authenticated LCU event socket and still polls, which is a standard
   LCU capability RC could build itself and owes nothing to these repos.
