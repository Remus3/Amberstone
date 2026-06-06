# Orchestration Plan - Gemini-Directed Fanout Run

LIVING DOC. The gemini director reads this each cycle and picks the next OPEN
session (top-to-bottom, phase order A -> F). The executor cycle updates it:
flip the picked session OPEN -> WIP -> DONE, fill the Commit sha, and append any
newly discovered work to the Findings log at the bottom. When no session is OPEN,
the director emits NO_WORK and the loop self-terminates.

Per-cycle contract (enforced by ops/loop/director_prompt.md):
orchestrator multi-agent fanout (disjoint-file worktree subagents, sole merger,
verifier-gate each slice before merge) -> TDD (failing test first) -> py_compile
before any restart -> full pytest suite green -> UI sessions also pass the 5-phase
fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + a
Claude_Preview visual check vs /api/state -> commit with a descriptive message ->
push to origin/main -> /done ritual (append docs/LEDGER.md, sync ROADMAP + this
file) -> py ops/loop/done_sentinel.py. No AskUserQuestion; auto-pick safest option.

ASCII only. No em-dashes, en-dashes, or smart quotes.

## Sessions

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| A1 | DS-surface | DS Profile panel (design + axes batch 1: mobility, sustain, scaling, waveclear). New dashboard/routes_ds_profile.py + web/js/panels/ds_profile.js + CSS + web/data/ui_mock fixtures. Mirror dashboard/routes_ds_sweep.py + web/js/panels/ds_sweep.js. 5-phase UI audit + visual check. | OPEN | - |
| A2 | DS-surface | DS Profile axes batch 2: add threat-range, zone-control, objective-damage, extended-duel, matchup to the A1 surface. Re-audit the panel. | OPEN | - |
| A3 | DS-coach | Wire the 2 highest-value axes into coach context: anti-tank build hint (vs high-HP enemies) + scaling power-curve, into modes/* prompts. Shadow-log first, then surface. | OPEN | - |
| B1 | coach-wire | Wire core/laning_verdicts.py + core/event_callouts.py + core/lead_projection.py (pure generators, zero live-coach consumer) into the live coach dict + callouts.js / right_now.js / next.js. Shadow-log validation first. | OPEN | - |
| C1 | ui-audit | Champ-Select ARAM + Champ-Select Arena: 5-phase fixture audit + Claude_Preview visual validation vs /api/state. Per docs/UI_SCALE_SPEC_V2.md. | OPEN | - |
| C2 | ui-audit | Active Match SR + ARAM + Arena: 5-phase audit + visual validation. | OPEN | - |
| C3 | ui-audit | Post Game Review SR + ARAM + Arena: 5-phase audit + visual validation. | OPEN | - |
| D1 | lift | DS relative-score bar (Aggregator P lift, BACKLOG.md:21): per-row score_pct fill (delta_dps/top_delta*100). Codeable with fixtures; render-gated on locked champ. | OPEN | - |
| D2 | lift | draft tool L (the community fork) Elo log-odds draft aggregator (BACKLOG.md:78): clean algorithm reimplement (NO vendor) over pairwise WR from rewind_history.db. | OPEN | - |
| E1 | research | Per-role grading rubric calibration (BACKLOG.md:100): tune core/post_game_rubric.py weight vectors from public per-role reference data. | OPEN | - |
| E2 | research | LCU data.json diff vs the reference catalog (BACKLOG.md:19) for richer endpoints. Log findings only; no live capture. | OPEN | - |
| E3 | research | Competitor-tool lift secondary sweep, framed by technical substance only (keep third-party names out of repo). Output new NOW/FUTURE/CLOSED candidates into the Findings log. | OPEN | - |
| F1 | monitoring | Phone monitoring loop-status panel reading ops/loop/control/{cycle.txt,controller.log,claude.done} + last commit (Tailscale-viewable) + daily upstream content-drift poll (tools/upstream_drift_check.py + scheduled task). | OPEN | - |

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (MCP down post-1PC). C-phase visual validation uses the Claude_Preview MCP against :8888 instead.
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.

## Findings log (executor appends; newest first)

- (none yet)
