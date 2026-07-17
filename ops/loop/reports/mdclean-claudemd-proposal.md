# CLAUDE.md proposal - mdclean C7 (2026-07-17, propose-only, NOT applied)

Directive: CLAUDE.md is propose-only for the mdclean loop. Operator applies or discards.

## Confirmations - no CLAUDE.md change owed

1. restart.bat contradiction (C1 finding): RESOLVED in C5 on the OPERATIONS.md side to match
   CLAUDE.md (taskkill then restart.bat as hard fallback). CLAUDE.md "Restart workflow" is
   already correct - no edit.
2. Scorer count: CLAUDE.md header already reads "all 7 archetype scorers wired (Slice B on-hit
   AP ds.onhit)" - matches LEDGER 911 / ENGINE 1.216.0. Current.
3. Topology: CLAUDE.md Topology table is the canonical home; C5 deduped ARCHITECTURE.md to a
   pointer. No CLAUDE.md edit.
4. Dated-artifact line ("Dated artifacts in docs/_archive/") - still accurate; C7 moved 33 more
   dated files there (COMPETITOR_LIFT_* set, EXTERNAL_REVIEW_* set, OVERLAY_QA_2026-06-29,
   AUDIT_2026-07-09_NEXT_SESSION_PLAN, OPERATOR_DECISION_QUEUE_2026-07-01, 2 superseded UI
   specs). No wording change needed.

## Proposals (optional, operator-gated)

P1. Slim the header DS parenthetical (line 4, "Daemon Slayer ... COMPLETE 4 consumers + per-spell
    CC wave 9 108/89 + ..."). It restates engine-identity detail that drifts every DS batch;
    WP-F6a's standing rule keeps such counts ONLY in the docs/DAEMON_SLAYER.md banner.
    Suggested replacement clause: "DS engine - ENGINE_VERSION + coverage: see
    docs/DAEMON_SLAYER.md banner (7 archetype scorers + CC/survivability ecosystems COMPLETE)".
    NOTE: a 2026-06-29 F6a decision deliberately left CLAUDE.md untouched (24KB < 60KB budget,
    content current) - re-propose only because the parenthetical has since grown again (Slice B).
    Saves ~600B; purely cosmetic. Skip if the operator prefers the full recital in-header.

P2. "RC is tkinter-free (scheduler is asyncio AppLoop; 13 residual .after() files)" - the "13"
    is a drift-prone count with no guard. Suggest dropping the number ("residual .after() files
    remain") or verifying at next /sync-all-md. Not verified this cycle (probe budget).

## Out of scope, recorded here for completeness

- tools/sync-all-md.md still carries pre-existing non-ASCII glyphs (arrows/middots/box-drawing,
  no em/en dashes). The repo-wide retro-sweep of such glyphs stays operator-gated (CLAUDE.md
  hard-rule section already says smart-quote sweep is a separate gated pass).
