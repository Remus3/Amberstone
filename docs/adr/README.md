# Architectural Decision Records - index

`docs/adr/` is a routing destination declared in `CLAUDE.md`: **before re-litigating a
past choice, check here first.** This index exists because the ADRs were cited 29 times
across the living docs by NAME and linked ZERO times, so a session that had not already
read `CLAUDE.md` had no path into them.

Add a new ADR by copying [TEMPLATE.md](TEMPLATE.md), numbering it sequentially, and
adding a row here in the same commit.

| ADR | Decision | Status |
|---|---|---|
| ~~001~~ | Remove tkinter overlays; keep `tk.Tk()` as scheduler | **RETIRED 2026-07-18** - its own "Watch for" note predicted the asyncio migration that has since happened. RC is tkinter-free (scheduler is the asyncio `AppLoop`), so the `tk.Tk()` half was stale guidance. The overlays-removed half is now just how RC works and needs no ADR. Record kept at `docs/_archive/ADR-001-tkinter-removal-RETIRED.md` |
| [002](ADR-002-ds-before-haiku.md) | Daemon Slayer item ranking runs BEFORE the Haiku coaching call | Accepted |
| [003](ADR-003-in-process-vision-server.md) | Vision server runs in-process on Legion at `127.0.0.1:8889` | Accepted |
| [004](ADR-004-bridge-watcher-daemon.md) | Bridge tasks processed by an always-on daemon, not `/loop` polling | **Superseded by ADR-012** |
| [005](ADR-005-tailscale-magicdns.md) | Cross-Claude bridge uses Tailscale MagicDNS hostnames, not LAN IPs | Accepted (bridge itself decommissioned - the MagicDNS preference still stands for the tailnet) |
| [006](ADR-006-riot-api-key-policy.md) | Riot API key permitted for full-team context enrichment | Accepted (supersedes the earlier no-key stance) |
| [007](ADR-007-event-coach-pivot.md) | Event-driven coaching pivot | Accepted |
| [008](ADR-008-unified-asset-hash.md) | Unified asset-hash for cache-busting + auto-reload | Accepted |
| [009](ADR-009-replay-events-cleanroom.md) | Replay-events sidecar over Match-V5 timeline; `league_record` GPLv3 cleanroom | Accepted |
| [010](ADR-010-arena-s2-augment-leveling.md) | Arena S2 Augment Level-Up pre-stage doctrine | Accepted |
| [011](ADR-011-one-pc-consolidation.md) | One-PC consolidation (Game-PC -> Legion) | Accepted |
| [012](ADR-012-bridge-decommissioned.md) | RC<->Peer cross-Claude bridge + lessons-sync decommissioned | Accepted (supersedes ADR-004) |
| [013](ADR-013-laning-verdict-flip-retired.md) | HZ-A laning-verdict flip RETIRED - the verdict carries zero information | Accepted (closes RM-155) |
| [014](ADR-014-aram-laning-table-known-wrong-not-regenerated.md) | Shipped ARAM laning tables are KNOWN-WRONG on economy (`gold_at_band` x `0.5/1.01`) and are deliberately NOT regenerated | Accepted (closes RM-175) |
| [015](ADR-015-shared-repo-enumeration.md) | Repo-root enumeration in tests goes through `tests/_repo_walk`, git index primary and directory skips as backstop | Accepted (records a 2026-09-07 decision that had no record; RM-394 shipped separately, RM-395 open for the two holdouts) |

## Reading order for a new session

Topology and where things run: **011** (one-PC), **003** (vision in-process),
**005** (tailnet naming). Coaching pipeline: **002** (DS before Haiku), **007**
(event-driven pivot), **010** (Arena augments), **013** (laning-verdict flip
retired - read before touching Lane A precompute or re-running its flip gate),
**014** (the shipped ARAM laning tables are known-wrong on economy - read before
trusting or regenerating any `laning_scenarios_*.json`).
Data policy: **006** (Riot key), **009** (replay cleanroom). Frontend: **008**
(asset hash). Test guards: **015** (repo-root enumeration - read before writing
or converting any guard that sweeps the whole tree). Retired: **004** -> **012**
(bridge).

Related routing: open work is `ROADMAP.md`, aspirational is `BACKLOG.md`, the per-item
completion ledger is `docs/LEDGER.md` (items 325+) with the deep archive in
`docs/history_notes.md` (items 1-324). Live-gated validation rows live in
`docs/LIVE_GAME_GATED_SYNC.md`.
