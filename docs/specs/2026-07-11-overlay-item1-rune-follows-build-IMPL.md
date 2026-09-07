# Item 1 - Rune-Follows-Build - Implementation Plan (grounded)

Status: grounded against real code (Plan agent, 2026-07-11). Design = 2026-07-11-overlay-item1-rune-follows-build-design.md (approved). Re-verify cited anchors at build time.

SHIPPED: (commit `64056670`, LEDGER 861) the missing Phase-1 GET route (POST /api/loadout/rune-pages) + Phase 2 (side panel + follow precedence + override-sticky + always-star) + Phase 3 (save-as-default -> localStorage rc-cs-rune-default); (commit `e158c6b2`, LEDGER 862) Phase 4 (custom user-build fold-in - enumerate_pages folds sr_user_builds.list_for keyed userbuild_<id>, exact-match deduped by resolved perk_ids; BACKEND-ONLY - the side panel + /api/loadout/list already consume userbuild_ generically, so no frontend change); (commit `14899723`, LEDGER 863) Phase 5 (auto-push toggles relocated from the in-panel build-chooser control to the CHAMP SELECT settings card via an inverted dev.js binder; _csvGetPushFlags flipped to default-ON reading 3 flat keys rc-cs-push-{runes,spells,build}; the in-panel [PUSH] button + checkboxes removed; the build-selection auto-push + _csvPushCategory/_csvPushCheckedCategories kept for Phase 6). SHIPPED (commit `0c8f8877`, LEDGER 864) Phase 6 (LCU push of the FOLLOWED rune page via the non-frozen _csvApplyLoadout -> /api/loadout/apply seam). NEW builds[].pushPageId (coaches/rune_pages.py) = the page resolve(buildId) ACTUALLY produces (variant OWN / path / userbuild runes), distinct from recommendedPageId (the auto page the frozen writer applies - they differ for e.g. Caitlyn loadout=PTA vs auto=Comet); the JS _csvPushFollowedRune reverse-maps the selected pageId to that resolver-producible buildId and pushes it runes-only, gated on the default-ON runes flag, with a per-champ latch + one deferred re-assert so it lands AFTER the frozen auto RuneWriter (last-writer-wins). A pure-auto page (no pushPageId match) is left to the frozen writer - never push wrong runes, never clobber. NO frozen-file or backend-route change (override_runes stays removed). **ALL 6 PHASES SHIPPED.** LIVE-GATED: the actual in-game LCU push validates via tools/lcu_push_watcher.py in a real champ select (deferred to operator play).

## 0. Ground truth (the two facts that reshape the plan)

A. **Subrunes are DERIVED, not stored.** A build's rune page is a pure function of
{keystone, primary, secondary} via build_perk_ids (lcu/lcu_rune_writer.py:150-214,
called from coaches/loadout_resolver.py:352-364). Generic builds store only those 3
names (loadout_resolver.py:223-225). ONLY user builds carry explicit minor_primary/
minor_secondary overrides. Consequence: the dedup key "tree + keystone + subrunes" =
the resolved 9-element perk_ids tuple + primary_id/sub_id. There is NO source that
enumerates "every full rune page with curated subrunes" per champ - only per-build
keystones + one auto page + user pages. THIS IS THE PHASE-1 DATA RISK.

B. **Two push paths; one FROZEN.**
- Auto RuneWriter (lcu/lcu_rune_writer.py:496/595/933/974 - FROZEN): polls champ
  select ~1s, writes `RC: {champ} {SR|ARAM}` ONCE per (champ,mode) from
  rune_recommendations_{sr,aram}.json; deletes all `RC:` pages then POSTs + sets
  current. This is the path A1 / tools/lcu_push_watcher.py guards.
- Manual apply (NON-frozen): champ_select.js _csvApplyLoadout (:3110) -> POST
  /api/loadout/apply -> dashboard/routes_loadout.py:231 -> resolve()/_resolve_user_build
  -> enqueues rune_cmd to :8889 -> tools/lcu_agent.py apply_runes (:1157).
Wire runes-follow-build ENTIRELY through the manual seam. Both writers
delete-all-RC-then-write, so LAST-WRITER-WINS: the panel re-pushes the followed page
AFTER the auto push. Do NOT modify the frozen writer/client.

## Data / storage model
- Generic variants + keystone/trees: data/champion_loadouts.json (committed), via
  loadout_resolver.list_variants (:149).
- Auto recommended page: data/meta_build/rune_recommendations_{sr,aram}.json
  (committed). File HAS secondary_runes+stat_shards, but load_rune_rec (:238-242,
  FROZEN) reads ONLY keystone+trees (subrunes discarded).
- Custom user builds (item build + rune tree incl. subrunes): data/daemon_slayer/
  user_builds.json - GITIGNORED (coaches/sr_user_builds.py, full add/update/delete CRUD).
- Build choice (sticky): localStorage rc-ingame-build-<champ> (shared with item_build.js
  - format is load-bearing, do NOT change).
- Rune choice (sticky, session): localStorage rc-cs-rune-<champ> (today a keystone string).
- Push flags: localStorage rc-cs-push-flags (global JSON, today default all-OFF).
NEW (all client-side or gitignored - NEVER a committed file, per LEDGER 823):
- Saved default (champ,buildId)->pageId: localStorage rc-cs-rune-default (JSON map).
- Session override (champ,buildId)->pageId: in-memory, cleared on build change / new session.
- pageId = stable hash of resolved (primary_id, sub_id, perk_ids[9]) = the dedup key.

## Phases (each shippable, TDD via Python-mirror/grep convention + per-page UI audit)
1. Rune-page model + data: new non-frozen helper (coaches/rune_pages.py) enumerates
   candidate pages = distinct (keystone,primary,secondary) across variants/build_paths
   + auto page + user pages; resolve perk_ids; pageId = hash; exact-match dedup. Map
   buildId -> recommendedPageId. Expose via a GET route (mirror /api/loadout/list).
2. Runes-follow-build: promote the rune panel from nested column (_csvRunePanelHtml:2844,
   grid at :3077) to a SIDE panel (sibling of .csv-builds). Follow precedence on build
   change: sessionOverride ?? savedDefault ?? recommendedPageId (build change discards
   an unsaved override - the approved literal rule). Override sticky on the build.
   Always render the star on recommendedPageId even when selected != recommended.
3. Save-as-default: button in the side panel header; write rc-cs-rune-default; helpers
   mirror _csvSavedRuneChoice/_csvSaveRuneChoice. Survives games + modes.
4. Custom user builds: backend CRUD + nesting already exist (routes_loadout.py:104-129
   merges userbuild_<id> rows; _resolve_user_build honors minor_*). This phase = wire the
   user page into the Phase-1 list + dedup (identical perk_ids -> reuse pageId; 1-subrune
   delta -> new page). NOT authoring (CRUD exists, no HTTP route yet).
5. Relocate push toggles to Settings: add Runes/Items/Spells toggles to the CHAMP SELECT
   settings card (web/index.html:1473) via dev.js cb() - BUT cb defaults UNCHECKED, so add
   an inverted binder (checked unless "0") + flip _csvGetPushFlags (:2120) to default-ON.
   Remove/hide the in-panel header push control. Land in today's CHAMP SELECT card
   (item-4's Client Settings rename is separate/later).
6. LCU push wiring (manual seam): reuse _csvApplyLoadout -> /api/loadout/apply. Push on
   champ-select enter (follow), build change, override - gated by the default-ON runes
   flag. Panel re-pushes AFTER the auto RuneWriter so saved-default/override wins.
7. Tests + UI audit: per-phase Python-mirror/grep files + the champ-select UI-audit ritual.

## Open choices (recommended default - CONFIRM)
(a) Custom-build AUTHORING UI: OUT of scope (design line 62); Phase 4 uses existing
    sr_user_builds CRUD. A minimal authoring surface is a cheap later add (no HTTP route yet).
(b) Storage: SPLIT - custom builds on-disk gitignored (user_builds.json, existing);
    saved-defaults + override in localStorage. Override: move defaults on-disk if
    cross-device persistence wanted.
(c) Full page with curated subrunes per generic build: DEFAULT NO - use the resolved
    perk_ids (accurate to what actually pushes); generic builds show DERIVED subrunes.
    Override: source curated subrunes by wiring the secondary_runes/stat_shards already
    in rune_recommendations_*.json through a NON-frozen reader (not the frozen load_rune_rec).
(d) pageId/dedup key: hash of resolved (primary_id, sub_id, perk_ids[9]) via build_perk_ids
    in a non-frozen helper. Makes generic/user dedup automatic.

## Risks
- Rune-page DATA availability (Phase 1): only keystone+trees per build today; "every page
  with real subrunes" is thin until user builds or a new subrune source lands. Biggest risk.
- LCU push race (Phase 6): the frozen auto RuneWriter pushes the generic rec once on enter
  and can momentarily precede the panel's saved-default push. Mitigated by last-writer-wins
  + panel re-push; validate with tools/lcu_push_watcher.py (A1). 3-page account cap + retry
  backoff are real.
- Frozen files: lcu/lcu_rune_writer.py + lcu/lcu_client.py import-only, never modify.
- No committed file: saved defaults + custom builds go to localStorage/gitignored only.
- Format coupling: rc-ingame-build-<champ> is shared with item_build.js; keep new rune
  state in sibling keys.
- Item-4 dependency (Phase 5): land toggles in the current CHAMP SELECT card to stay
  independent of the not-yet-approved Client Settings rename.

## Critical files
web/js/panels/champ_select.js (rune panel :2844, wiring :3160-3333, _csvApplyLoadout :3110,
storage :2073-2140); coaches/loadout_resolver.py (list_variants :149, resolve :266, page
build :347-364); coaches/sr_user_builds.py (custom CRUD, gitignored home); dashboard/
routes_loadout.py (/api/loadout/apply :231, user-build resolve :156); web/index.html
(CHAMP SELECT card :1473) + web/js/panels/dev.js (cb binder :15-25).
FROZEN (import-only): lcu/lcu_rune_writer.py (build_perk_ids :150, load_rune_rec :217,
RuneWriter :496-1038); tools/lcu_agent.py (apply_runes :1157).
