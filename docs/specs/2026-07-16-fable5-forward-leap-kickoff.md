# Fable 5 Forward Leap - kickoff prompt pack (2026-07-16)

Operator intent: burn the Fable 5 window (0 percent weekly Fable used) on ANALYSIS + SPEC AUTHORING only,
so every future Opus 4.8 (Max20) session is pure execution against a pre-thought spec. Fable thinks; Opus types.

## Model / effort map (the answer to "which model per stage")

| Stage | Where | Model | Effort | Why |
|---|---|---|---|---|
| P0 Recon | subagents (read-only) | sonnet | low | mechanical inventory; do not spend Fable on grep |
| P1 Leverage analysis | main thread | fable-5 | max | the actual forward-leap synthesis; Fable-only value |
| P2 Portfolio specs | main + spec subagents | fable-5 main / opus subagents | high | Fable ranks + frames; Opus drafts spec bodies |
| P3 Adversarial review | 3 judge subagents | opus | high | refute ghosts before they cost sessions |
| P4 Emit + commit | main thread | fable-5 | low | file writes, commit, banner |
| Tonight md-cleanup loop | AHK headless executor | opus-4.8 | medium | Tier-0 doc work; never spend Fable here |
| Future execution sessions | one spec per session | opus-4.8 | high (max for Tier-2 engine work) | Max20 workhorse |
| Verifier gates | read-only subagent | sonnet | low | claim re-check only |

Budget frame: 18 percent weekly all-models, 0 percent Fable. Fable planning session costs weekly-Fable only;
keeps Opus headroom for the week's execution sessions. Never use Fable for Tier-0/Tier-1 edits.

## PROMPT A - paste into a FRESH session with /model fable-5 (max effort)

```
MISSION: author docs/specs/FORWARD_LEAP_PLAN.md - a ranked portfolio of the highest-leverage RC
development thrusts, each pre-analyzed to spec level so future Opus 4.8 sessions execute without
re-deriving strategy. You are the strategist; spend capacity on analysis + synthesis, not typing.
Subagent-first protocol applies. Chat output caveman ultra; all real output to files.

P0 RECON - parallel read-only subagents (model sonnet, effort low), main thread spot-checks 1
citation from each before trusting:
  A: ROADMAP.md + BACKLOG.md + docs/LEDGER.md (newest 40) + WAKEUP_NOTES.md -> open-work inventory;
     every item tagged OPEN / SHIPPED / STALE with LEDGER id or commit SHA citation.
  B: docs/ARCHITECTURE.md + docs/DAEMON_SLAYER.md + git log --oneline -100 -> engine/UI state map.
  C: live ground truth: ops/runtime/health.json, curl -k https://127.0.0.1:8888/api/health/all,
     DS :8893 /health, data/daemon_slayer/current.txt.
  D: docs/ORCHESTRATION_PLAN.md + docs/LIVE_GAME_GATED_SYNC.md -> what is queued vs live-gated.
No fix work in P0.

P1 LEVERAGE ANALYSIS - main thread only, no subagents. Rank candidate thrusts by
(dev-velocity unlock x operator value) / token cost. Candidates MUST trace to P0 evidence or
ROADMAP/BACKLOG lines - invent nothing without a cited gap. CLAUDE.md Settled list is absolute;
re-pitching a settled item is a defect. Known standing directions to weigh, not presume:
haiku-zero precompute lanes, Post Game Review S2-S5, overlay/in-game UI tail (LEDGER 859/860),
DS next-lift seams, ops/cost levers.

P2 PORTFOLIO SPECS - pick 5-8 items max. One spec subagent per item (model opus, effort high),
Fable frames each brief first. Every spec: goal, testable acceptance criteria, R5 tier
(Tier-0/1/2), files touched, est sessions, model+effort assignment, DONE-ritual hooks, and a
GHOST LIST - named things the executor must NOT investigate.

P3 ADVERSARIAL REVIEW - 3 parallel judge subagents (opus, high) per portfolio: already shipped?
settled? live-gated? mis-tiered? spec self-contained enough for a cold Opus session? Kill or
amend any item on 2/3 refute.

P4 EMIT - write docs/specs/FORWARD_LEAP_PLAN.md (ranked portfolio + per-item spec links) plus
one PASTE-READY kickoff prompt per item (<= 40 lines each, self-contained: /clear boundary,
tier + verification scope, commit + LEDGER + push ritual). Commit + push. 5-line chat summary.

HARD GUARDRAILS: 7-bit ASCII, no em/en dashes. Frozen files untouched. docs/LEDGER.md +
docs/history_notes.md + docs/_archive append-only/immutable. Max 2 verification tool calls per
claim, then mark UNVERIFIED-SKIP and continue - never rabbit-hole. Tier-0 items get NO suite
runs. No mid-run questions to operator; log ambiguity + move on.
```

## Explicits checklist (fold into ANY future kickoff prompt)

1. Goal line verbatim: "front-load the thinking into specs; execution sessions are typing, not deciding".
2. Anti-ghost: citation-or-skip (LEDGER id / SHA / live probe), 2-probe cap per claim, Settled-list
   supremacy, second probe before declaring anything broken, never recompute DS coverage prose.
3. Anti-overkill: declare R5 tier up front; Tier-0 = no suite, no restart, no verifier subagent,
   single pass (R6); verifier subagent only for parallel-slice claims (R7).
4. Output contract: files not chat, caveman chat, paste-ready prompts as the deliverable.
5. Boundaries: frozen-file list, append-only ledgers, ASCII, CLAUDE.md under 60KB, archive-do-not-delete.
6. Autonomy: no questions mid-run; UNVERIFIED-SKIP + report instead.
7. Session shape: one portfolio item per session, /clear between, /done ritual to close.

## Tonight (2026-07-16): autonomous md-cleanup via AHK loop

Directive: docs/specs/2026-07-16-md-cleanup-headless-directive.md
Config: ops/loop/config.mdclean.json (opus executor, cycle cap 8)
Launch: open the executor Claude window first, set /model opus-4.8, then
powershell -File "C:\Riot Commander\ops\loop\launch_loop.ps1" -Mode live -Cfg "C:\Riot Commander\ops\loop\config.mdclean.json"
(launcher self-starts the AHK bridge + controller; verified against launch_loop.ps1 params 2026-07-16.)
