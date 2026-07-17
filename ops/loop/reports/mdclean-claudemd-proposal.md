# CLAUDE.md proposal - mdclean C8 (2026-07-17, propose-only, NOT applied)

Directive: CLAUDE.md is propose-only for the mdclean loop; operator applies or discards.
Supersedes the C7 edition of this file; C7 items are carried forward below, marked [C7 carry].
Size check: CLAUDE.md = 25,362 bytes this cycle - well under the < 60KB CI budget. Nothing here
is budget-driven; every proposal is hygiene (accuracy / dedup / rule-consistency).

## Confirmations - no CLAUDE.md change owed

1. [C7 carry] restart.bat contradiction (C1 finding): RESOLVED in C5 on the OPERATIONS.md side
   to match CLAUDE.md (taskkill then restart.bat as hard fallback). "Restart workflow" section
   already correct; restart.bat present on disk (ls probe this cycle). No edit.
2. [C7 carry] Scorer count: header "all 7 archetype scorers wired (Slice B on-hit AP ds.onhit)"
   matches LEDGER 911 / ENGINE 1.216.0. Live DS /health this session: ok, patch=16.14.1,
   alive=True. Current.
3. [C7 carry] Topology: the CLAUDE.md Topology table is the canonical home; C5 deduped
   ARCHITECTURE.md to a pointer. No edit.
4. [C7 carry] Dated-artifact line ("Dated artifacts in docs/_archive/") still accurate; C7 moved
   33 more dated files there (COMPETITOR_LIFT_* set, EXTERNAL_REVIEW_* set, and 5 others). No
   wording change needed.
5. [new] Every concrete file CLAUDE.md cites exists on disk - single ls probe, 24/24 hits: all
   16 frozen-list files, tools/precommit_gate.py, tools/pytest_guard.py,
   tools/text_first_guard.py, tools/regen_rc_cert.ps1, tools/strip_em_dashes.py,
   core/game_host.py, restart.bat, data/brawl_coaching_data.json. No dead references found.
6. [new] Header DS identity (ENGINE_VERSION 1.216.0, patch 16.14.1) matches LEDGER 911 + live DS
   /health. Coverage prose ("706 items / 173 champs") NOT recomputed per directive rule 4 -
   quoted verbatim only, accuracy not re-derived here.
7. [new] RC health cross-check: pid=27616 alive=True mode=client last_reload_ok=True; 18 RC-*
   scheduled tasks live. The "Scheduled tasks (Legion)" section states no task count and defers
   to docs/OPERATIONS.md, so no drift.

## Proposals (operator-gated)

P1. [C7 carry, unchanged] Slim the header DS parenthetical (the "Deep references" line, currently
    L6: "(DS engine - 706 items / 173 champs - ENGINE_VERSION 1.216.0 ... Anivia/Zac)"). It
    restates engine-identity detail that drifts every DS batch; the WP-F6a standing rule keeps
    such counts ONLY in the docs/DAEMON_SLAYER.md banner. Suggested replacement clause:
    "DS engine - ENGINE_VERSION + coverage: see docs/DAEMON_SLAYER.md banner (7 archetype
    scorers + CC/survivability ecosystems COMPLETE)". NOTE: a 2026-06-29 F6a decision
    deliberately left CLAUDE.md untouched (24KB < 60KB, content current) - re-proposed only
    because the parenthetical has since grown again (Slice B). Saves ~600B. Risk: none
    functional; skip if the operator prefers the full recital in-header.

P2. [C7 carry, NOW VERIFIED] Intro line (L3): "RC is tkinter-free (scheduler is asyncio AppLoop;
    13 residual .after() files)". Measured this cycle: grep \.after\( across *.py = 3 files,
    identical with and without .gitignore filtering (app/__init__.py, app/_loop.py,
    app/_health_monitor.py - all three on the frozen list). The "13" is stale. Proposed
    replacement: "3 residual .after() files (all frozen app/ modules)" - or drop the number.
    Pinning 3 is low-drift going forward: the residual files are frozen, so the count can only
    move via operator-approved edits. ~10B saved; primarily an accuracy fix.

P3. [new] Vision pipeline opener is stale context. Current text: "The `screen_agent.py` agent
    (Legion-local) POSTs frames every 2s to `:8889/upload-frame`." Ground truth:
    ARCHITECTURE.md:210 (C5-reconciled this loop) - screen_agent.py is "DISABLED (no task) ...
    retired in favor of the in-process self-grab relay (1-PC, ADR-011). Now non-integral: the
    frame relay self-grabs in-process (single GDI BitBlt fallback, item 276)". The file survives
    only as a kept reference at tools/screen_agent.py (glob probe); no scheduled task runs it.
    CLAUDE.md's own Settled list already says "Phase 11 vision relay full-collapse partly done
    items 267/276". Proposed replacement opener: "Game frames land at `:8889/upload-frame`;
    since item 276 the frame relay self-grabs in-process (GDI BitBlt fallback) - the legacy
    `tools/screen_agent.py` uploader is retired (no scheduled task; kept as reference)." Rest of
    the paragraph (coaches GET /latest-frame, _run_vision gate, OCR-first tiering, liveclient
    sibling relay) is current and stays. ~+40B (grows slightly). Risk: low - matches
    ARCHITECTURE + the Settled line.

P4. [new] Merge "Session-End Ritual" into "Session Wrap-up" - near-duplicate wrap sections
    triggering on the same phrases. Session-End Ritual (L59-61): "When user says 'wrap',
    '/done', or 'end session': run tests, commit with descriptive message, push, sync living
    docs (append the per-item ledger entry to `docs/LEDGER.md`, NOT CLAUDE.md), and confirm CI
    green before declaring done." Session Wrap-up (L191-193): "When invoked with `/done` or
    asked to wrap a session: (1) audit pending changes ... (5) print final banner." Wrap-up is
    the superset (5 steps, LEDGER routing + 60KB note, 2026-06-21 bridge-probe deprecation);
    the only unique Session-End content is the explicit "confirm CI green" clause - fold it
    into Wrap-up step (2) ("commit and push, confirm CI green") and delete the Session-End
    Ritual section. Saves ~320B. Risk: low; no unique guidance lost after the fold.

P5. [new] Prune the "Style Rules" section (L67-70, 2 bullets). Both bullets restate the L36
    hard rule "No em-dashes or en-dashes - ever (7-bit ASCII authored content)", which is
    longer, canonical, and already carries the PowerShell mojibake root cause. Bullet 1 ("No
    em-dashes anywhere (repo-wide hard rule, enforced)") is a pure restatement; bullet 2
    (em-dashes in PowerShell double-quoted strings cause mojibake parse failures) restates the
    rule's Why clause. Saves ~200B. Risk: none identified.

P6. [new] "TDD First ... verify full suite (20,190 tests)" (L135) - hardcoded total is
    stale-by-construction. Evidence: the DS-dir suite alone moved 11326 -> 11754 passed across
    recent LEDGER entries (newest, LEDGER 911, cites "11754 passed"), so a combined total
    pinned at 20,190 cannot have held; C1 inventory flagged the same figure in README L48 as
    drift-prone ("counts drift; canonical = /sync-all-md"). The true current combined total was
    NOT re-measured (a full suite run is outside Tier-0 scope; no claim made on the number).
    Proposed replacement: "then verify the full dual suite before committing (Tier-2 scope per
    R5)". Saves ~10B and removes a recurring sync obligation.

P7. [new] ASCII sweep inside CLAUDE.md itself. Grep [^\x00-\x7F] hits 5 lines: L5 + L121
    (U+00B7 middots), L100 (U+00D7 twice + U+2248), L108 + L112 (U+2192 arrows). Zero em/en
    dashes or smart quotes (clean on the gate-banned classes - the precommit gate only blocks
    those, so these other glyphs persist silently). The L36 hard rule says authored content
    stays 7-bit ASCII, and C5/C6 of this loop already swept the same glyph classes out of
    ARCHITECTURE/AGENTS/API/README (findings C5 notes: U+2192 / U+00B7 / U+00D7 -> ASCII).
    Proposed mapping: U+00B7 -> " - ", U+00D7 -> "x", U+2248 -> "~", U+2192 -> "->". ~0B net.
    Risk: none functional; pure rule-consistency in the rule's own home file.

## UNVERIFIED-SKIP

- None this cycle. (P6's one unknown - the true current combined test total - is declared
  inside P6 rather than skipped; the proposal does not depend on it.)

## Out of scope, recorded here for completeness

- [C7 carry] tools/sync-all-md.md still carries pre-existing non-ASCII glyphs (arrows /
  middots / box-drawing, no em/en dashes). The repo-wide retro-sweep of such glyphs stays
  operator-gated (the CLAUDE.md hard-rule section already marks the smart-quote sweep as a
  separate gated pass). P7 above is only the CLAUDE.md-local slice of that sweep, surfaced
  separately because CLAUDE.md is the rule's own home.

Net effect if all applied: ~1.1KB saved plus two accuracy fixes (P2 count, P3 vision opener);
CLAUDE.md stays ~24KB, comfortably under budget.
