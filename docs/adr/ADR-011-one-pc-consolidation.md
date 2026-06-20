# ADR-011: One-PC consolidation (Game-PC -> Legion)

**Date:** 2026-05-29
**Status:** Accepted (executed 2026-05-29; supersedes the 2-PC assumption in ADR-003/004/005 for the League/RC data path)

## Context

The original topology (ADR-003/004/005) split work across two machines:
Game-PC ran League + Vanguard and a set of agents (LCU agent, Live Client
relay, screen agent, phase watcher, hotkey listener) that pushed game state
to Legion over LAN/Tailscale; Legion ran RC (supervisor, vision server, web
dashboard). RC's live readers reached Game-PC's Live Client API (:2999) and
LCU directly via the hardcoded Game-PC LAN IP `192.168.8.237`, with a relay
cache on the vision server (:8889) because Riot's :2999 binds 127.0.0.1 only
and rejects LAN reads.

The s169 discussion (2026-05-11) decided option B: consolidate to one PC so
Legion drives the new 27-inch monitor at full spec and the architecture stops
paying for the LAN hop and the two-process model. The migration (firmware
spoof, fresh Vanguard identity, validation) executed 2026-05-29; League +
Vanguard now run on Legion. The operator then declared Game-PC out of the
League/RC pipeline entirely.

## Decision

League + Vanguard + RC + OBS all run on Legion. Concretely:

1. **Host is config, not code.** New `core/game_host.py` exposes
   `GAME_HOST = os.environ.get("RC_GAME_HOST", "127.0.0.1")`. Every live
   reader (game_reader/poller, coaches/_base_coach, lcu/lcu_client [frozen],
   lcu/lcu_pregame, lcu/lcu_postgame_collector, dashboard/builders,
   tft/tft_state_reader) imports it instead of hardcoding the Game-PC IP.
   Flip `RC_GAME_HOST` to point the game host elsewhere with zero code change.
2. **Agents relocate to Legion-local.** `gamepc_lcu_agent.py` (LCU writer for
   rune/item/summoner push), `gamepc_liveclient_relay.py` (feeds the :8889
   relay cache the poller reads first), and `gamepc_hotkey_listener.py`
   (RegisterHotKey A/B decision answers; anti-cheat-safe) now run on Legion
   as ONLOGON scheduled tasks (RC-LCUAgent, RC-LiveClientRelay,
   RC-HotkeyListener). Their Game-PC copies are stopped.
3. **phase_watcher is NOT relocated.** Its DXGI capture on gameflow phase
   edges is retired with the continuous screen agent under the 1-PC
   consolidation. RC-PhaseWatcher disabled on Game-PC.
4. **OBS records locally on Legion** via Display Capture (WGC), not Game
   Capture (hook injection trips Vanguard). No splitter/capture card.

## Consequences

**Good:**
- No LAN hop for LCU / Live Client reads; one power/heat/maintenance
  footprint; the 27-inch monitor runs at full native spec.
- `RC_GAME_HOST` makes the game host a single config value - testable
  (tests/test_game_host.py) and overridable without touching nine files.
- The relay-first poller path is preserved unchanged - the local relay
  agent just feeds :8889 from localhost instead of over LAN.

**Trade-off:**
- Hardware isolation and redundancy are gone. One machine, one failure mode;
  Legion's silicon is now what Vanguard fingerprints.
- Vision frames still flow through the :8889 relay cache rather than
  in-process mss - the full in-process vision collapse is deferred.

**Watch for:**
- The poller reads the :8889 relay cache FIRST and falls back to direct
  127.0.0.1:2999 only when the relay is UNREACHABLE. The dead-agent
  short-circuit risk is RESOLVED by the 2026-06-02 self-heal below - the relay
  endpoint stays fresh in-process even if RC-LiveClientRelay dies.
- OBS Display Capture is continuous DXGI/WGC capture. Keep one locked
  resolution and League Borderless on Legion while recording.
- Tailscale kept the node name `legion-rc` despite the Windows hostname
  rename to DESKTOP-JKZECV9. `legion-rc` MagicDNS stays canonical for RC and
  the Peer bridge; do not "reconcile" it to the local hostname.
- Phase-11 cleanup (DONE 2026-06-20): Legion<->Game-PC bridge teardown,
  relocated-agent `gamepc_*.py` rename (-> `lcu_agent` / `liveclient_relay` /
  `hotkey_listener` / `keybind_listener` / `screen_agent` / `phase_watcher`),
  and the ARCHITECTURE topology rewrite to Legion-only all executed. Game-PC is
  retired from the pipeline. (Full in-process vision-frame (mss) collapse is the
  one remaining deferred tail - the GDI BitBlt self-grab landed item 276.)

## Update 2026-06-02: relay self-heal (DS & RC are non-integral to Game-PC)

DS was already 1-PC: `agents/daemon_slayer/server.py` binds 127.0.0.1:8893,
pure compute over `data/daemon_slayer/`, zero Game-PC/network coupling.

The one remaining structural dependency was the :8889 liveclient relay: both
`game_reader.poller` and `core.liveclient_cache` read it, and it was fed ONLY
by the RC-LiveClientRelay agent - so a dead agent meant dead coaching (the relay
was *integral*). Now `vision_server/_relay.get_latest_liveclient()` self-reads
Riot's :2999 in-process when the relayed snapshot is stale (>2s) and
`GAME_HOST` is local, throttled to one attempt per 1.5s, fail-soft. A remote
`RC_GAME_HOST` disables the self-read (Riot's :2999 binds localhost-only on the
remote box) so the legacy 2-PC agent-push path is preserved.

Result: the RC-LiveClientRelay agent (and thus Game-PC) is now an
optimization, not a dependency. The Game-PC cross-Claude bridge may remain as a
comms convenience but is not integral to DS or RC. (Full vision-FRAME collapse
- dropping the mss frame relay - is still deferred.) Guarded by
`tests/test_liveclient_self_heal_1pc.py`. RC-VisionServer restarted to pid 476.

## Update 2026-06-20: Game-PC retired - Phase-11 cleanup executed

The operator declared Game-PC fully out of the pipeline, and the deferred
Phase-11 cleanup landed:

- **Bridge teardown.** The Legion<->Game-PC cross-Claude bridge peer was severed:
  the `gamepc` MCP entry, the `gamepc_bridge_daemon.py` / `gamepc_mcp_server.py`
  producers, the Game-PC peer slash-commands, and the `gamepc` health/dashboard
  peer rows were removed. Peer stays as the sole cross-Claude peer.
- **Relocated-agent rename.** The 2-PC-era `gamepc_*.py` filenames were renamed
  to Legion-neutral names (`lcu_agent`, `liveclient_relay`, `hotkey_listener`,
  `keybind_listener`, `screen_agent`, `phase_watcher`); every referencer + test +
  the `routes_static.py` deploy allowlist moved with them. Task NAMES
  (RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener) were already
  Legion-neutral and are unchanged - their live action paths re-point to the new
  filenames.
- **Topology rewrite.** ARCHITECTURE / OPERATIONS / BRIDGE / CLAUDE topology prose
  is now Legion-only.

Game-PC is referenced below only as the retired 2-PC origin of record.
