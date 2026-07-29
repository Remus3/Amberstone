# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-29c - ROADMAP + BACKLOG reconciliation: relocated done/shipped items, kept fences.

**Read-only-ish / docs session. Tier-0: NO engine edit, no ENGINE bump, no DS bounce, no Share, no restart.** `50e621a7`.

Operator ask: check upstream, then move done/completed/shipped items out of the two live
trackers. Upstream re-checked at start - NO drift (ddragon 16.15.1, meraki 25.15, cdragon
16.14 ok, sentinel advanced). Two read-only Explore agents built a ground-truth-verified
relocation plan (all cited SHAs/LEDGER numbers resolve; 0 UNVERIFIED).

**BACKLOG.md 71350 -> 59699B:** removed 9 fully-shipped rows already in LEDGER (R129 XOR +
superseded original, R67 Terminus SR + superseded original, draft-score, session-hygiene,
playstyle-labels, overlay-HUD-microlifts, patch-impact); trimmed 3 KEEP-RESIDUAL rows to
their open tails (boot-utility kite/poke, radar CHI-bands, R190 kit-pen d/e); trimmed 2
do-not-re-pitch fences (champ-select brief FLIP, F1/F5) to thin pointers.

**ROADMAP.md 73097 -> 72143B (under 80KB budget):** relocated the 2 remaining full-narrative
closed RM-04 sub-bullets (RC-2 follow-on, A-27b Golden Spatula) to fences, keeping the
base-id mirror trap + ID-SUFFIX-not-name lessons.

**Decision logged:** RM-106b left in place - labelled OPEN, not relocated without operator
call. CI docs-guards green. Do NOT re-relocate: ROADMAP was already pruned 4x, near its floor.

---

# 2026-07-29b - Ability-haste reopen RE-CLOSED by gating experiment; link-ingest Phase 1 kicked off.

**Read-only / docs session. Tier-0: NO engine edit, no ENGINE bump, no DS bounce, no Share, no restart.** `e8c67f4b`.

**Ability-haste class RE-CLOSED.** Operator reopened RM-39/RM-43 2026-07-29 (authored
per-spell-coeff design, existing ids). Ran the mandated amplification gating experiment
first. Since RM-39's L0 "0 calls" result, L1 shipped (ENGINE 1.222.0): with
`apply_ad_axis_ability_damage` ON the first-order ability path IS now reachable (compute
x1e6 -> item 3143 #1 for Aatrox + Ambessa). BUT driving the haste cooldown to ~0 under
the same flag is BYTE-IDENTICAL - their spells score on the `measured>0` cast-rate branch,
so `theoretical=1/cooldown` never fires. **Haste inert no matter how authored; both options
moot; class closed.** Audit `ops/audit/RM39_RM43_haste_gating_2026-07-29.md`. Do NOT re-open
without a NEW mechanism that changes which cast-rate branch these champs take.

**Link-ingest Phase 1 (of 7) started** per `RC maybe.txt`. 119 MCP-marketplace links ->
CCR-01..CCR-119, triaged by 8 parallel agents, scored 1-10. `First-Pass.md` on desktop =
all 119 + ranked index. **NEXT: operator leaves `**!= =!**` notes in First-Pass.md, THEN
Phase 2 (cull) runs.** Do NOT re-triage - Phase 1 is done. Continuity: memory
`project_ccr_link_ingest`.

---

# 2026-07-29a - Perseus Vault adopted; 5 new core modules lifted from cleared client plugins.

**Operator session. Tier-1 throughout; NO engine, no ENGINE bump, no DS bounce, no Share.**
`dc2b4e7a` `a454f76b` `543ed57c` `d0c5237f` `9a119161` `5b6bdbf2` `7bb033fd` `df92ffb7`.

**Perseus Vault is LIVE** (`~/.perseus-vault/`, local, no key). 1202 entities, **1202
embedded**. Wired via `.mcp.json` + SessionStart/SessionEnd hooks - all LOCAL and
gitignored, so a fresh clone has NO wiring (same trap as the git hooks). Re-sync with
`python tools/perseus_sync.py`. **mnemoverse and pathmode both REMOVED** (pathmode was
registered at two sites, which is why its tools appeared twice).

**Three traps measured during install - do not rediscover:** `status: healthy` is a LIE
about coverage (a fresh ingest left 91 of 1197 embedded and still reported
`semantic_recall: available` with zero warnings - only `embedded == active` proves it,
which `--verify` asserts); `init` reports encryption while `entities.body_json` stays
PLAINTEXT on disk, so encryption was dropped; `connect --hooks` writes a bash-ism
(`$(basename "$PWD")`) on Windows.

**Five new modules, 158 tests, all green:** `core/lcu_events.py` (WAMP push replacing
poll), `core/sgp_client.py`, `core/meta_crawl.py`, `core/lcu_mastery.py`,
`core/provider_cascade.py`, plus `tools/perseus_recall.py`. All re-implemented from
protocol facts - NOTHING vendored.

**A filed puzzle closed itself:** the 2026-07-05 probe recording
`na-red.lol.sgp.pvp.net` 404 on match-history-query was hitting the COMMON host. SGP
splits match-history from common; NA1 match-history is `usw2-red.pp.sgp.pvp.net`. A test
pins them apart.

**RECALL BEFORE BUILDING - I violated my own new rule and paid for it.** I "discovered"
the ability-haste inertness mechanism by grep; `project_ds_ability_haste_measured_inert`
already had it in more detail, and Perseus returns that memory at RANK 1. That is why
`tools/perseus_recall.py` exists: raw recall is ~13.4k tokens per query, the projection
is ~223 (98.3 pct smaller), because a mandatory step that expensive gets skipped.

**Do NOT redo:** Perseus install/ingest is DONE. mnemoverse + pathmode are GONE (revoke
the PATHMODE_API_KEY operator-side; removing config does not invalidate it). The license
gate + third-party lift rule is in CLAUDE.md. newDodgeTracker was reviewed and NOT built
from - GPL-3 with three credited contributors.

**Next:** the ability-haste class is REOPENED against RM-39/RM-43 (operator decision) -
**run the amplification gating experiment FIRST**; both candidate designs are moot if the
ability path is still unreachable. DDragon moved to 16.15.1 but Meraki/cdragon have NOT,
so a patch refresh now would pull a half-landed patch - wait.
