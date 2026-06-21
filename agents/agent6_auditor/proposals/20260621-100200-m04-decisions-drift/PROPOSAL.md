# M-04 resolved_decisions.json drift vs CLAUDE.md Settled (audit-10)

- Target agent: 1 (lead) - source-of-truth file
- Severity: MEDIUM
- Audit: `20260621-100200-tenth-audit-phase3.md`

## Problem

`agents/state/resolved_decisions.json` is locked_at 2026-04-22 with
20 entries; last touched in the audit-9 backfill. Meanwhile CLAUDE.md
"Settled - do not re-litigate" has accreted important new decisions
that future audits and agents cannot cite.

## Proposed appends (draft)

```jsonc
{
  "id": "phase3-d021",
  "title": "ADR-011 Legion 1-PC consolidation - Game-PC retired from pipeline",
  "decided_at": "2026-05-29",
  "summary": "Item 215 executed: Legion is the only runtime host. League + Vanguard + RC + supervisor + vision server + dashboard + OBS all on Legion. Game-PC retired from the live pipeline. RC_GAME_HOST defaults to 127.0.0.1; bridge no longer routes to gamepc-rc. Relocated agents (RC-LCUAgent, RC-LiveClientRelay, RC-HotkeyListener) run local as ONLOGON tasks on Legion. gamepc_*.py modules remain in tree for archival until Phase 11 relay collapse completes. Frozen-file list is unchanged. Do NOT re-pitch Game-PC as a live host.",
  "source": "CLAUDE.md / Settled / ADR-011 + item 215",
  "authority": "operator"
},
{
  "id": "phase3-d022",
  "title": "101.qq.com duo-synergy live-wired with kill switch (item 277)",
  "decided_at": "2026-06-xx",
  "summary": "core/synergy_external_source.fetch_rows feeds existing core/smoothed_rates_101qq lane: live-first with static May-25 seed fallback. Kill switch RC_DUO_SYNERGY_LIVE=0. /api/duo-synergy + bot/sup grid unchanged. Raw payload gitignored (redistributable). NOT geo-fenced, reachable from Legion. Do NOT re-pitch a static-only path.",
  "source": "CLAUDE.md / Settled / item 277",
  "authority": "operator"
},
{
  "id": "phase3-d023",
  "title": "DS live truth = data/daemon_slayer/current.txt + /health, NOT recomputed",
  "decided_at": "2026-06-01",
  "summary": "Daemon Slayer coverage %, match-row prose, patch, and ENGINE_VERSION must be read from data/daemon_slayer/current.txt + agents/daemon_slayer/__init__.py + /health. The registry is nested - a flat count mis-parses. DS coverage prose recompute is a DS-batch docs-sync job, never executed in a general sync. memory: feedback_ds_coverage_prose_recompute.",
  "source": "CLAUDE.md / Settled / DS live truth",
  "authority": "operator"
}
```

Header update:
- `"version": "phase3-1.2"`
- `"locked_at": "2026-06-21"`

## Why this matters

The charter line "`agents/state/resolved_decisions.json` is the source
of truth for locked decisions; any code that drifts from it is a
finding" is structurally weakening. Future audits cannot flag drift
against a 2026-04-22 snapshot when 21 days of new locked decisions
sit only in CLAUDE.md prose.

## Acceptance

- Three entries appended verbatim (or with operator wording tweaks).
- Version bumped to phase3-1.2.
- `locked_at` advanced to 2026-06-21.
- A reverse-grep from CLAUDE.md "Settled" key phrases hits the new
  entries.

## Why this is a proposal (not autonomous)

The charter grants autonomous-edit authority on `source_quality.json`
but NOT on `resolved_decisions.json` (which is in Agent 1's
source-of-truth lane). Filing for Agent 1 / operator review.
