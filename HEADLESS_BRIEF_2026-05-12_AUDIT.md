# HEADLESS BRIEF — anti-drift audit (morning/daytime run, operator-kicked)

> **Staged**: 2026-05-12 ~02:15 by Claude Opus 4.7
> **Mode**: `/loop` self-paced, 1M context
> **Cap**: 6 unified pairs OR 6 hours OR test failure (whichever first)
> **Risk profile**: MEDIUM — refactor/unify, full test suite gates every commit
> **Prereq**: only kick off AFTER the overnight doc/test brief
> (`HEADLESS_BRIEF_2026-05-12_DOCS_TESTS.md`) reports complete.

## Goal

Sweep RC for the class of bug that bit us in s171.8: **two implementations
of the same intent silently diverging** with no shared source of truth.
The canonical instance was `compute_asset_hash` (6 root files) +
`_serve_ui_version` (4 root files, missing 2 + all panels) — they drifted
since s164. Browsers served stale code for ~10 days. Hunt the pattern.

## Context — fresh session, no memory

Read first:
1. `CLAUDE.md` — project conventions + frozen files
2. `WAKEUP_NOTES.md` (top entry should be s171.8 wrap from overnight)
3. `git log --oneline -10`
4. `docs/adr/ADR-008-unified-asset-hash.md` (created during overnight)
   — the canonical example, frame other findings against this template

## Hunt targets (check each — confirm presence, decide if drift-prone)

For each pair, the question is: **"does this have one source of truth, or
are there N independent implementations of the same intent that could
silently disagree?"**

| # | Pair | Why it might be drifting |
|---|---|---|
| 1 | `dashboard/_state_builder.resolve_mode_key` vs `agents/agent2_backend/file_ingest._resolve_mode_key` import | Two callers, but s171.8 used the same one — verify, document |
| 2 | `WATCHED` tuple in `agents/agent2_backend/file_ingest.py` vs `dashboard/_state_builder.MODE_TO_FILE` | Both enumerate per-mode coaching JSON files |
| 3 | Frozen file list in `CLAUDE.md` vs `tools/process-bridge-tasks.md` | Two hand-maintained lists, easy to drift |
| 4 | View IDs in `web/js/lib/state.js:VIEW_IDS` vs HTML section ids vs CSS `body[data-view=…]` selectors in `header.css` | Three places enumerate the view set |
| 5 | Mode mappings in `web/js/panels/champ_select.js:_csvDsModeFor` vs `dashboard/_state_builder.MODE_TO_FILE` vs the various `mode === "aram"` checks scattered through JS | Mode string lookups in many places |
| 6 | LCU phase → "in-game-ish" check: `_viewAutoDerive` uses one set, `handleLcuEnvelope` uses another, `gamepc_lcu_agent.py:state["phase"] in (…)` uses a third | Three "what counts as in-game?" checks |
| 7 | DS engine version: `agents/daemon_slayer/dps.py:ENGINE_VERSION` vs the version exposed on `/api/health/all` vs the value baked into committed JSON outputs | Drift between code and data |
| 8 | LiveClient relay max-age constants: `core/decision_detector._RELAY_MAX_AGE_S` (8.0) vs `game_reader/poller.RELAY_MAX_AGE_S` (12.0) vs `LCU_RELAY_MAX_AGE` (20.0) | Three different thresholds — intentional? document. |
| 9 | Cache buster URL pattern in HTML (`?v=2026XXX`) vs `inject_asset_hash` regex (`?v=[^"']+`) vs `compute_asset_hash` output format | URL format drift |
| 10 | Riot champion name normalization: `CHAMPS.byId` in JS vs `core/champion_aliases.py` vs the hardcoded aliases in `tools/daemon_slayer_extract.py` | Three name-mapping tables |

## For each finding

1. **Confirm**: grep + read to verify both/all sides exist and disagree
2. **Decide**: is the drift intentional (different cost tradeoffs) or
   accidental (forgot to update one)?
3. **If accidental** + safe to unify:
   - Pick one as source of truth
   - Have the other(s) defer to it
   - Add a docstring explaining the choice
   - Commit + push + CI watch + wait green
4. **If intentional**: skip silently, move to next
5. **If unclear**: skip + note in WAKEUP_NOTES under "open audit findings"

## Stopping conditions

| Trigger | Action |
|---|---|
| 6 pairs unified (committed) | DONE. Final WAKEUP_NOTES update. |
| 6 hours elapsed | DONE. Note remaining candidates. |
| Any CI red | STOP, note, do not attempt fix. |
| Any test red | STOP, note. |
| Frozen file touched | REVERT immediately. STOP if revert fails. |
| Run out of hunt targets before hitting 6 | Done early — that's fine. |

## Safety rails (same as overnight brief)

- NEVER `--no-verify`
- NEVER force-push
- NEVER amend published commits
- One commit per finding, `gh run watch` between
- Conventional Commits enforced by hook
- Co-Authored-By trailer required
- Frozen files in CLAUDE.md — do NOT touch

## How to kick off

After /clear in a fresh session:

```
/loop Read HEADLESS_BRIEF_2026-05-12_AUDIT.md and execute it. Self-pace. Stop per its conditions.
```

Or paste the brief contents inline with `/loop`.

## End-of-run

Append a one-line summary to `WAKEUP_NOTES.md` top section:
`**audit run complete** — N pairs unified, T elapsed. <link to commits>`
