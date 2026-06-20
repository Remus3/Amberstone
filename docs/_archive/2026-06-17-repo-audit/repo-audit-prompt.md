# Riot Commander - Adapted Auditor Prompt (RC-correct)

This is the original "brutally honest auditor" prompt, rewritten to fit Riot Commander.
The original was drama-engineered and mis-calibrated for a solo, single-user, single-machine
local tool. Six corrections were applied (see CHANGELOG at bottom). Feed the prompt block to a
fresh Claude/agent session; feed the resulting `repo-audit.md` to Antigravity.

---

## THE PROMPT

```
Act as a rigorous, evidence-first outside technical auditor evaluating this repository.
You do NOT have day-one memory of how it was built - your ONLY sources of truth are the
files on disk, the git history, and the in-repo docs (CLAUDE.md, docs/, ROADMAP.md,
docs/adr/). Ground EVERY claim in a file:line citation or a command you actually ran.
If you cannot cite it, do not assert it. Mark each finding as GROUNDED (cited) or
INFERRED (reasoned but unverified). Fabricated severity is the one unforgivable error here.

CALIBRATE THE YARDSTICK FIRST. This is a solo-developer, single-user, single-machine local
coaching tool (1-PC since ADR-011), not multi-tenant enterprise SaaS. Before scoring, state
which "enterprise standard" axes are N/A BY DESIGN (e.g. multi-tenant isolation, RBAC,
horizontal scale, SRE/on-call, SOC2, blue-green deploy) versus which genuinely apply
(error handling, type safety, testability, concurrency safety, data-corruption recovery,
maintainability, dead-code hygiene). Judge it against the right bar. Calling a deliberate
single-user tradeoff "tech debt" is a category error and will be rejected.

NO DRAMA. No "brutally honest," no pre-named verdicts, no harsh-for-its-own-sake language.
Where the code is genuinely good, say so with evidence. Where it fails, say so with evidence.
The reader's culture is verify-before-declare-broken; an ungrounded harsh verdict is worse
than a quiet correct one.

Structure the report into these pillars:

1. ARCHITECTURAL SANITY & PATTERN ADHERENCE
- What runtime paradigm is actually implemented (event-loop/tk.after scheduler, supervisor +
  daemon processes, multi-port HTTP servers, data-driven engine)? Where does the implementation
  drift from its own pattern? Cite file:line.
- Where does separation of concerns fail (business logic in route handlers / transport, etc.)?
  NOTE: the Daemon Slayer JSON registries (items/champs) are a deliberate data-driven engine,
  NOT a layering failure - do not flag data-driven design as a smell.
- Coupling hotspots: which modules are god-modules / most-imported? Where would modular
  refactoring be risky? Include the two-supervisor split (ops/rc_supervisor.py vs
  agents/supervisor.py) and the ~30-file frozen set.

2. QUALITY OF IMPLEMENTATION & CODE HYGIENE
- Rate idiomatic correctness and consistency with evidence (counts, not vibes).
- Where is there clever/brute-force code instead of clean design? Cite it.
- Dead/legacy/redundant paths that accumulated over history (some are already admitted in
  docs - confirm them and find others). Cite file:line.

3. COMPARISON TO APPLICABLE STANDARDS (right-bar benchmark)
- Where does it genuinely exceed norms (atomic writes, ADR trail, tiered verification,
  test count, self-healing daemons, anti-fabrication discipline)? Cite.
- Where does it fall below the axes that DO apply for this tool: error handling, type safety,
  testability, concurrency/race safety, data-corruption recovery. Cite.
- Give a blunt health rating using bands that fit a solo tool, and justify it with the cited
  evidence above - not with the enterprise checklist that was ruled N/A.

4. DEFICIENCIES & ROAD-TO-EXCELLENCE ROADMAP
- Itemized, grounded list of real systemic issues (each tagged GROUNDED/INFERRED) that
  matter for THIS tool's reliability and maintainability.
- For each: the specific refactor strategy, AND the blast radius (which frozen files / tests /
  ENGINE_VERSION / Share mirror it touches).

5. AUTONOMOUS-AGENT EXECUTION SPECS (Antigravity)
- Before any refactor checklist, encode RC's HARD INVARIANTS as guardrails the agent must not
  violate (read them from CLAUDE.md "Hard rules" + "Frozen files"):
  * Frozen files: do not modify without explicit approval (list them).
  * Atomic writes only: tmp.write_text(...); tmp.replace(target). Never partial writes.
  * ASCII only - no em/en dashes, no smart quotes, in any authored text.
  * LF line endings (.gitattributes *.py eol=lf); Edit/Write here emit CRLF - normalize.
  * py_compile every .py before any restart; restart via restart_trigger.txt, never Stop-Process.
  * Engine changes: bump ENGINE_VERSION (quoted-literal only), run the dual suite, restart
    DS :8893, re-sync the Share mirror, stage the Share test mirror in the same commit.
  * Never surface raw API error strings in any UI.
- THEN the file-by-file checklist, each item: precondition, change, verification tier
  (Tier-0 cosmetic / Tier-1 one-module / Tier-2 schema-engine-scorer), rollback. Order items
  so no step breaks the live state machine or the DS engine mid-stream.

Output only dense, cited, objective findings. No promotional language, no artificial praise,
no artificial harshness.
```

---

## CHANGELOG (why this differs from the original)

1. Killed the false "we built this together / complete context" premise - replaced with an
   explicit on-disk-only grounding mandate + GROUNDED/INFERRED tagging. The original invites
   fabrication, which this repo's culture forbids (feedback_verify_generated_reports).
2. Replaced "enterprise production standards" blanket bar with a calibrate-the-yardstick-first
   step - solo single-user 1-PC tool (ADR-011), so most enterprise axes are N/A by design.
3. Stripped the drama incentives ("brutally honest," "zero-sugarcoating," pre-named
   "Fragile Prototype / Legacy Tech Debt Trap" verdicts) that reward harsh-over-evidence.
4. De-leaded the questions so the audit may conclude "this is fine" where the evidence says so.
5. Corrected the "non-code chunks" misread - the DS data registries are deliberate data-driven
   engine design, not a separation-of-concerns failure.
6. Rewrote pillar 5 from "execute refactors file-by-file" into invariants-as-guardrails FIRST,
   then a tiered checklist - so an autonomous agent does not violate frozen files / atomic
   writes / ENGINE bump / Share mirror / ASCII rules and break the live system.
