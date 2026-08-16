---
description: Generate a grounded, on-command repo insights report for Amberstone - the actualized variant of /insights that reads git + LEDGER + ORCHESTRATION_PLAN + ROADMAP (never transcript inference, so it cannot re-pitch already-shipped work). Use when the operator asks for "repo insights", a "Legion work report", or a periodic activity report.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

The operator wants a personalized, GROUNDED insights report for the work done on
Legion - structured like the Claude Code /insights HTML report, but every figure
traced to a real repo source instead of chat-transcript inference. The whole point:
/insights suggested already-shipped work (verifier, truth_gate, the active-match
sentinel) because it never reads the codebase; this report does.

This is a Tier-0/1 tooling pass. It makes NO engine/schema changes, does NOT bump
ENGINE_VERSION, does NOT restart RC or DS, and does NOT touch `data/`.

## Contract

1. Run the generator with the canonical interpreter (NOT the `py` launcher):

   ```
   "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" "C:\Riot Commander\tools\repo_insights.py" --days 30
   ```

   - Pass `--days N` to widen/narrow the window (default 30).
   - Pass `--out <path>` to override the destination.
   - Default output: `C:\Users\Administrator\.claude\usage-data\repo-insights-<YYYY-MM-DD>.html`
     plus a sidecar `.json` facts blob.

2. The script is fully self-contained and prints `report:` / `facts:` / `window:`
   lines. It reads, in order of authority:
   - git history in the date window (commit/type/area histograms, churn, active days)
   - `docs/LEDGER.md` (items closed in window + recurring-friction phrase counts)
   - `docs/ORCHESTRATION_PLAN.md` (DONE/CLOSED/OPEN status + the EXCLUDED gated work
     that becomes the real "On the Horizon" - not invented suggestions)
   - `ROADMAP.md` (open-item fallback for the horizon)
   - `agents/daemon_slayer/__init__.py` ENGINE_VERSION + `data/daemon_slayer/current.txt` patch

3. Report the output path to the operator as a `file://` link they can open in Chrome.
   Quote the printed `window:` summary line (commit count + ledger-item count) so the
   operator sees the scope at a glance. Do NOT screenshot it (R3 - it is a text-grounded
   artifact, not a rendered-pixel check).

4. OPTIONAL enrichment (only if the operator asks for narrative): read the sidecar
   `.json` facts and add a short grounded synthesis paragraph in chat - but never
   invent a suggestion the facts do not support, and never claim work is needed that
   the LEDGER/ORCHESTRATION_PLAN already shows DONE (verify-premise-before-acting,
   `feedback_audit_proposals_are_intent`).

## Molding the look later

The report layout is data-driven in `tools/repo_insights.py`:
- Re-skin: edit the `CSS` constant + `PALETTE` colors in `render_html()`.
- Add/remove a section: each section is a marked `# SECTION:` block in `render_html()`;
  new sections only need a new key in the facts dict + a builder call.
- Change what counts as friction: edit `_FRICTION_PATTERNS` (real grep-able ledger phrases).
- Change area names: edit the `_AREA` dir->label map.

Keep it ASCII-only (repo hard rule) and LF-normalized on save.
