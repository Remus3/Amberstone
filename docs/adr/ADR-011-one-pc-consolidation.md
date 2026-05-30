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
   edges is the same crash class as the disabled screen agent
   (feedback_gamepc_lcu_phase_watcher_bsod / feedback_gamepc_screen_capture_bsod).
   RC-PhaseWatcher disabled on Game-PC.
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
- The poller reads the :8889 relay cache FIRST and only falls back to direct
  127.0.0.1:2999 when the relay is UNREACHABLE (not on a relay 404). If the
  local `gamepc_liveclient_relay` dies, a relay 404 wrongly short-circuits to
  "no game." Keep RC-LiveClientRelay healthy, or refactor the poller to prefer
  direct local :2999 (now that it is reachable).
- OBS Display Capture is continuous DXGI/WGC capture - the same surface that
  caused the Game-PC game-end 0x50 BSOD (Duet + resolution swap at match end).
  Legion likely lacks that root (no Duet, lock one resolution, League
  Borderless) but watch for match-end BSOD while recording.
- Tailscale kept the node name `legion-rc` despite the Windows hostname
  rename to DESKTOP-JKZECV9. `legion-rc` MagicDNS stays canonical for RC and
  the Peer bridge; do not "reconcile" it to the local hostname.
- Deferred Phase-11 cleanup: Legion<->Game-PC bridge teardown (pending
  Game-PC's fate), in-process vision collapse, archive of the `gamepc_*.py`
  originals, ARCHITECTURE topology rewrite.
