# mdclean findings - UNVERIFIED-SKIP log (cluster C1, 2026-07-17)

Items whose prune/relocate claim could not be proven within the 2-probe budget. Rule: later
clusters must NOT prune these on the C1 citation alone - re-verify or leave in place. In-doc DONE
markers alone (sha-level unverified) permit RELOCATE-not-delete but never hard PRUNE.

## ROADMAP.md
- L40 | DEEP-AUDIT PROGRAM run banner 2026-06-11 | loop-end not probed; LEDGER 901-903 show later loop activity
- L48 | item 312 | pre-LEDGER-floor, no LEDGER entry found
- L56 | item 265 Haiku-elim foundations | cited SHAs cb46386/77c3647 not in local git
- L57 | item 243/244 live UI watch | cited SHA 25b0be3 not in local git
- L75 | item 214 Electron shell narrative | self-declares phases 1-5 shipped; cited merges 0b2eea62/33dc9b3a not in local git
- L95 | build-ORDER go-live | cited SHAs 2d7da9e/3eb2e2d not in local git; self-declares SHIPPED

## README.md
- L46 | roster-coverage prose | canonical = docs/DAEMON_SLAYER.md; COPY-VERBATIM-ONLY (DS-batch job), do not touch in general cleanup

## BACKLOG.md
- L51 | obj_participation OPTION (c) | SHA 7b3d351 unresolvable; self-marked CLOSED twice (relocate-only allowed)
- L52 | Dead Man's Plate stacks-schema | SHA ce563c4 unresolvable; pre-LEDGER-floor item 122
- L86-L88 | Developer experience closed item | items 153-155 pre-LEDGER-floor, SHAs unresolvable

## docs/ARCHITECTURE.md
- L219-L224 | deploy-allowlist prune plan-text | no LEDGER/SHA anchor found for the plan's status

## docs/OPERATIONS.md
- L113 | memory-topic citation | style issue only, no ground-truth anchor needed but no proof of intended replacement
- L247-L248 | play-cadence dated rationale | no anchor

## docs/DAEMON_SLAYER.md
- L10 + L123 | 547/547 items vs CLAUDE.md 706/173 | scopes may differ; NEVER recompute - DS-batch docs-sync job
- L127 | 171/172 champions x P/Q/W/E/R | roster count at 16.14.1 unverified; COPY-VERBATIM-ONLY
- L192-L194 | calibration "Status: accumulating" | core/ds_calibration.py exists; status freshness unprobed

## C2 cycle notes (2026-07-17, ROADMAP.md executed)
- Kept in place verbatim with RM ids (UNVERIFIED-SKIP per C1; only an `- **RM-NN** ` prefix added):
  L40->RM-28, L48->RM-27, L56->RM-12, L57->RM-13, L75->RM-15, L95->RM-17.
- Relocation-target deviation: the directive said docs/history_notes.md; used docs/ROADMAP_HISTORY.md
  instead - it is ROADMAP.md's self-declared append-only archive ("Entries relocated verbatim") and
  every prior ROADMAP sweep (2026-06-20 / 2026-06-25 / 2026-07-13) used it; splitting the ROADMAP
  archive across two files would orphan the existing "(full record: docs/ROADMAP_HISTORY.md)" pointers.
- docs/ORCHESTRATION_PLAN.md: no mdclean row exists (grep 0 hits) - directive said update "if exists";
  skipped.
- L28 punch-list DEDUP -> docs/LIVE_GAME_GATED_SYNC.md deferred to C6 (that doc is C6 scope);
  punch-list survives as ROADMAP RM-05 + the verbatim archive copy.
- Slice-manifest / TaskCreate phases skipped per the directive's Tier-0 single-thread override.

## docs/ORCHESTRATION_PLAN.md (sha-level only; in-doc DONE markers present -> relocate-only OK)
- L105-L132 | DSP swarm round | 0c2b88e5 not in local git (LEDGER 876/889 do anchor the lane)
- L133-L157 | 2026-06-17 ROUND 2 | faeaeb4a not in local git
- L158-L170 | 2026-06-18 refill | e9f70e7d not in local git
- L171-L191 | 2026-06-19 refill | SHAs uncheckable in budget
- L9-L16 | contract summary vs ops/loop/director_prompt.md | no diff performed; dedup unconfirmed
