# MD cleanup - headless directive (2026-07-16, AHK loop, opus-4.8 executor)

GOAL: prune repo .md files of content that is provably DONE, restructure item lines, reorganize
sections, remove redundant/expired notations. Relocate-do-not-delete where residual value exists.
Tier-0 work throughout: no test suite, no RC restart, no verifier subagent (single-thread edits).

## Scope

IN: ROADMAP.md, BACKLOG.md, WAKEUP_NOTES.md, README.md cross-refs, docs/ARCHITECTURE.md,
docs/OPERATIONS.md, docs/API.md, docs/DAEMON_SLAYER.md, docs/AGENTS.md, docs/ORCHESTRATION_PLAN.md,
docs/LIVE_GAME_GATED_SYNC.md, docs/OVERLAY_BUILD_MASTER_PLAN.md, docs/RC2_PLAN.md, other living docs/*.md.

OUT (never edit): docs/LEDGER.md (append-only), docs/history_notes.md (archive - append allowed for
relocations, never rewrite), docs/_archive/**, logs, .jsonl, frozen files (tools/diagnose.md,
tools/caveman.md), .claude/**, memory files. CLAUDE.md = PROPOSE-ONLY: write suggested diff to
ops/loop/reports/mdclean-claudemd-proposal.md, do not apply.

## Rules (every cycle)

1. Citation-or-skip: a line may be pruned/marked-done ONLY with evidence - LEDGER item id, commit
   SHA, or live probe (health.json / /api/health/all / DS /health). Max 2 probe tool-calls per
   claim, then UNVERIFIED-SKIP + log to ops/loop/reports/mdclean-findings.md.
2. Relocate not delete: shipped-work narratives -> docs/history_notes.md (append). WAKEUP_NOTES
   keeps newest 2-3 sessions verbatim (mind the --- separator gotcha in tools/wakeup_prune).
3. Restructure: ROADMAP -> NOW / NEXT / LATER with stable item ids; BACKLOG entries get a
   path-stale check (cited paths must exist; else tag STALE-PATH). Dedup cross-doc repeats:
   one canonical home + pointer links.
4. DS coverage percent / match-row prose: NEVER recompute (nested registry mis-parses). Copy
   existing strings verbatim or leave untouched.
5. ASCII 7-bit only, no em/en dashes, no smart quotes. Run tools/strip_em_dashes.py check mode on
   touched files before each commit; precommit gate is the backstop.
6. No Settled-list re-litigation; no new work items invented. Pruning pass, not planning pass.
7. Commit per cluster with descriptive message (git commit -F tmpfile, ASCII), push, confirm CI
   green at end of run. /done ritual final cycle.

## Cycle plan (max_cycles 8)

C1: inventory - every in-scope .md: size, last-touch SHA, candidate-prune lines w/ citations ->
    ops/loop/reports/mdclean-inventory.md. No edits.
C2: ROADMAP.md restructure + prune. C3: BACKLOG.md + path-stale sweep. C4: WAKEUP_NOTES relocate
    trim. C5: docs living set (ARCHITECTURE/OPERATIONS/API/AGENTS). C6: DAEMON_SLAYER.md +
    ORCHESTRATION_PLAN.md + LIVE_GAME_GATED_SYNC.md status-tag refresh. C7: cross-ref sweep -
    broken links, README, dedup pointers; CLAUDE.md proposal file. C8: final glyph check, commit,
    push, CI confirm, /done, print summary banner.

STOP conditions: any frozen-file or LEDGER-content edit attempt; 3 consecutive UNVERIFIED-SKIP
clusters; CI red after push (fix-forward once, else halt + report).
