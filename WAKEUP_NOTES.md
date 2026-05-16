# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# memory-consolidation wrap — 2026-05-16 (/consolidate-memory pass)

**Operator:** ran `/consolidate-memory` (the s222 NEXT optional item) — reflective pass over the auto-memory system. **No RC code touched; repo clean, nothing committed/pushed.**

## Done — memory dir only (lives outside the repo at `.claude/projects/C--Riot-Commander/memory/`)
- Read all 81 topic files + index. Net **81 → 66 files**.
- Retired 15: 6 stale/resolved orphans (never indexed), 6 merged-then-deleted, 3 re-derivable (bridge `--suggestions` / `diagnose`+`caveman` skills / stale champ-select build-chooser memory that s215 autogen had made misleading).
- Collapsed the 7-file Peer-bridge/bridge sprawl → 3; folded the Yunara-dup-match, RC-PatchRefresh, and bridge-404 lessons into existing reference memories.
- **Resolved the s222-flagged deferral**: `project_daemon_slayer_engine.md` rewritten — dropped the stale 929-tests / ENGINE 0.60.0 / Batch-64 numbers, now durable-architecture-only and points to `docs/DAEMON_SLAYER.md` + `ROADMAP.md` + `agents/daemon_slayer/__init__.py` for live state. `reference_no_riot_api_key.md` slimmed to the current ADR-006 policy pointer.
- Created `user_operator_profile.md` (there were **zero** user-type memories before this).
- Rebuilt `MEMORY.md`: 66 semantically-grouped entries, 89 lines / 10.6 KB; verified 0 orphans + 0 dangling pointers; fixed the `gh_cli` double-index.

## Don't-redo
- The DS-memory staleness flagged in s222 is **FIXED** — don't re-investigate or re-defer it.
- Memory files are outside `C:/Riot Commander` — they never show in repo `git status`; there is nothing to commit for memory work.

## NEXT
- s220 aggregator-G-style Post-Game-Review reframe remains the big pending UI item (untouched this session).

# s222 wrap — 2026-05-16 (/sync-all-md skill + repo-wide md congruence pass)

**Operator:** "update the readme … be sure all parts are congruent across the other .mds … make this a skill /sync all md" → built the skill, dry-ran it, operator approved 4 decisions, ran it for real + committed, then /done.

## Shipped — `014eef0` + this docs commit
- **New `/sync-all-md` skill** — tracked canonical `tools/sync-all-md.md` (`.claude/commands/` mirror is gitignored local runtime, per the `done.md` house pattern). 10 ordered sections: canonical-facts-once → classify every .md → reconcile LIVING only → locked-s207 README → cross-ref integrity → orphan/deprecation → history-protect → self-congruence → report. Args `--dry-run` / `commit` / `readme`.
- **Congruence pass applied**: ENGINE_VERSION 0.92.0→0.94.0; DS tests→2060; block_index coverage→193 entries / 124 champions (72%); rewind matches→2851; README "2,022 tests"→"2,060" + "two-thirds"→"three-quarters"; BRIEF stale 922/1426/0.69.0/2,846 → canonical (BOM + portfolio voice preserved).
- **Broken ref**: dead `docs/_archive/CHANGELOG.md` (cited 3×, never existed) repointed → `docs/history_notes.md` (CLAUDE.md ×2 + ROADMAP.md).
- **Structural**: DAEMON_SLAYER.md Phase-3 stale "three implemented / next session's lift" → all six scorers wired via `archetype_dispatch` (s174–s182).
- **Quarantine**: `audit-notes.md`, `AUDIT_PHASE_2_STATUS.md`, `rc-tutor-decision-matrix.md` → `docs/_archive/2026-05-16-doc-sync/`.

## Key decisions / don't-redo
- **block_index registry is the canonical champion-coverage denominator** for DS docs (operator-confirmed; s205=185/118 → s217=193/124). README prose mirrors it ("about three-quarters").
- `.claude/` + `_archive/` are gitignored → only `tools/sync-all-md.md` is version-controlled; the two `git mv`'d orphans stay tracked at the archive path, untracked `rc-tutor-decision-matrix.md` just physically moved.
- Skill **never rewrites history**; memory `project_daemon_slayer_engine.md` index staleness (929 tests / ENGINE 0.60.0) was FLAGGED not fixed — deferred to `/consolidate-memory` by design.

## NEXT
- Optional: `/consolidate-memory` to refresh the stale DS memory index line. `/sync-all-md` now available for routine pre-audit doc hygiene. s220 aggregator G Post-Game-Review reframe remains the big pending UI item (untouched this session).

# s221 wrap — 2026-05-16 (Game-PC BSOD root-cause + view-router fix + lobby settings)

**Operator:** Recent-5 item icons missing → Game-PC game-end BSOD report → view auto-switch bug + lobby-settings feature → fix scheduled-task paths → /done.

## Shipped — 3 code commits + docs
- **`a92e9e2`** Game-PC BSOD (`0x50 PAGE_FAULT_IN_NONPAGED_AREA`, ~30-50s after every match, first 2026-05-09, deterministic). Root cause: `gamepc_screen_agent.py` `ImageGrab(all_screens=True)` BitBlt across the virtual desktop (Parsec+Duet virtual display adapters) faulting a display driver at the game→desktop mode switch. → **bettercam DXGI** single real Intel adapter (out0=game / out1=Duet; BGRA→numpy RGB, no cv2; graceful access-loss rebuild). bettercam+numpy+comtypes in `pythoncore-3.14-64`. Deployed; 3 stream agents live. `gamepc_boot.ps1` `tasksOwn` marker → 3 RC-ScreenAgent-* tasks are sole launcher (no boot double-launch / double-primary race); refresh loop kept (durability).
- **`5dafe32`** View auto-switch: Home Find-Match pinned `#lobby`; `_viewResolveAndApply` skipped its stale-manual clear on ANY hash (`!hashView`) → stuck on lobby through CS+game. Fix: a stale *game-state* hash now clears; non-game-state hashes (#settings/#history) stay sticky. + PRE-GAME LOBBY settings card: Auto Accept = agent CONFIG source-of-truth (bidirectional w/ lobby toggle, persistent); Party = localStorage pref, no auto-apply.
- **`e9d921c`** Recent-5 items: `_lcu_build_items` from `raw_data.lcu_match_detail`; frontend → DDragon mirror icon path (old /icons/items/ is slug-named, 404s on numeric ids).
- Game-PC RC-ScreenAgent-League/Minimap/UI tasks repointed `py`→`pythoncore-3.14-64\pythonw.exe` + workdir (lastResult 0x80070002→0x41301). Scheduled-task defs are Game-PC OS state, not repo.

## Don't-redo
- **Never revert the screen agent to `ImageGrab(all_screens=True)`** — deterministic 0x50 BSOD. Memory `feedback_gamepc_screen_capture_bsod.md`. bettercam must use `output_color="BGRA"` (RGB path imports cv2).
- `/agent/gamepc_screen_agent.py` serves the working tree → fix is reboot-durable; `a92e9e2` makes it robust. `view_router_state.py` mirrors only `_viewAutoDerive`, NOT `_viewResolveAndApply` — the hash fix needs no test churn.

## NEXT
- Operator to confirm post-real-match: no BSOD; lobby→CS→game auto-switch; lobby↔settings toggles persist/sync (needs a real lobby/ready-check). s220 aggregator G Post-Game-Review reframe still the big pending UI item — untouched this session.

# s220 wrap — 2026-05-16 (Post Game Review: C/E/Settings + polish, then aggregator G reframe pivot)

**Operator instruction:** "continue the ui work" → executed the s219 hand-off priority order, then a long operator-driven polish + a scope pivot.

## Shipped — `920c9a3` (+1004/−99, 7 files) + the docs commit below
- **Item C** rich DDragon item tooltips on Comp tab (mirrors champ_select s213).
- **Item E phase 1** Timeline tab (per-min gold/XP/CS diff sparklines + objective ribbon). Source pivoted: **LCU has NO timeline endpoint (404)** → server-side **Match-V5** via `core.riot_api.get_match_timeline` (immutable-cached) in `dashboard/builders._attach_match_timeline`. 17 tests `tests/test_last_match_timeline.py`. Phase 2 (interactive minimap) deferred.
- **Settings** "POST GAME REVIEW" card: rank-tier selector (canonical `rc-pgr-rank-tier`) + baseline knob (`/api/last-match?baseline=`, clamped 5–50, in `_build_last_match`).
- **Polish:** tabs → Comp/Chart/Timeline/Insights/Review (Deep-Review→Review nav tab); Chart contrast; hero section separators; **section 3 rebuilt as 4-col grid mirroring section 2** (col1 = selector over KDA+KP% flex pair, selector widened via justify-self:stretch); per-side roster score + MVP/SVP; CS↔summoner swap; L##→##; **+1 then +3 font bumps** (44 decls, hero↔section3 parity preserved); uniform 17px column gap.

## Key decisions / don't-redo
- **gamepc_lcu_agent.py was edited then fully REVERTED** — LCU exposes no `/timeline`. Do NOT re-add an agent timeline push. Match-V5 server-side is the path.
- **Riot key was NEVER the problem (diagnosed 2026-05-16).** Product key in `API-Key-Riot.txt` is valid + in-scope — live-probed **200** on all 6 RC endpoints incl. Match-V5 timeline for a standard match. The Item-E timeline 403s because **Riot Match-V5 does not serve event-mode games**: operator's stashed last match is ARAM Mayhem (`gameMode=KIWI`, `queueId=2400`, `NA1_5560797021`) → both `/timeline` and `/matches/{id}` return app-JSON `403 Forbidden`, and Match-V5 `by-puuid/ids` omits the game entirely. NOT renewal/scope/routing/Cloudflare/stale-cache. RC restarted (pid 16424→17480) as hygiene; the 403 did not change — proof it was never a key/cache issue. **Item E + the reframe are unblocked for standard-queue matches**; event-mode last-matches will (correctly, permanently) placeholder. The earlier diagnostic `error code: 1010` was a Cloudflare UA block from a UA-less probe — irrelevant to RC's `rc-riot-api/1` path. Follow-up (not done): `_attach_match_timeline` should early-skip known event queues (2400 etc.) to kill the misleading "key may be invalid or revoked" WARN spam + error-metric noise.
- Section 3 went through ~5 layout iterations; **final = 4-col matching section 2's column pairing** (VISION↕DAMAGE, CS↕CS/MIN, TANKED↕HEAL, selector↕[KDA KP%]). Do not re-litigate — operator confirmed via spec table.
- `_rosterScores` is currently **per-side 1–5** (lobby-wide 1–10 caused gap-looking numbers — operator flagged, fixed).

## NEXT SESSION — major reframe (operator pivot, paint-tool iteration)
Operator wants Post Game Review reframed aggregator-G-style: **clickable, lightly explorable**; deep coach refinement routes to the **Replay page**. 6 reference screenshots analyzed this session (model: compact match rows → expand → persistent header + 10-player score strip → **AI Analysis / AI Graph / Build** tabs; 0–100 color-banded score + lobby-wide rank + 👑 best; MVP=purple card; AI-Graph = trend line, click event → minimap+detail+win-prob). Carried, NOT yet done: Sustain rename; hero section-1 (KDA `##/##/##` min-width, champ-name 2-line, remove "ARAM"); aggregator G roster row (level-on-icon, vertical summoners, runes, rank badge, score+rank, KDA 2-line, damage fill-bar, cs/min parens); color-coding feature; #9 per-player augments. Per-player runes/ranks need `_enrich_from_lcu` extension. Operator will paint-tool-annotate section by section.

# s219 wrap — 2026-05-15/16 (Post Game Review build — multi-session marathon)

**Operator instruction:** "ready for last match page - lets go to it" → 16+ iterations of build + redesign over ~6 hours of wall time. Closed with "do /done for a /clear then next session to finish C and E and settings page add".

## Shipped — 16 commits (`8228164` → `6c0728e`)

**Pre-work side ships (before the main build):**
- `8228164` — salvaged PR #3 (Boots + Spellblade tuples for `_ITEM_CLASS_PEERS`); 11 tests; closed PR #3, deleted both stale agent branches, GitHub now clean (0 PRs, 0 forks, 1 branch).
- `c78c004` — folded Phase 3 supervisor into main RC supervisor's watch (frozen-file edit, ~200 lines additive `_Phase3Watcher`, 15 unit tests). Restarted RC-Supervisor scheduled task (pid 184); auto-restarts dead Phase 3 process via `schtasks /Run` + heartbeat-stale check. `status.json` now carries a `phase3` block.

**Post Game Review page — backend ingest pipeline:**
- `eee6cfa` — s219 v1 scaffold: `/api/last-match` route + builder + HTML/CSS/JS panel. Source: `data/match_history.db` latest non-TFT row. Quick Review heuristics with `{text, why}` for tooltip-based explainability.
- `97cafcb` — rename "Last Match" → "Post Game Review" across menu/tile/h2/dropdown trigger/urgent-view banner/dead-dashboard label map. Internal view-id `last-match` preserved (view-router tests don't churn).
- `19d8027` — LCU `/lol-match-history/v1/games/{gameId}` ingest endpoint `POST /api/last-match/ingest`; raw_data stash (no normalized schema per operator); `_enrich_from_lcu` builder parses 10-player roster + items + summoners + runes + damage + objectives + W/L. Live verified via PowerShell ingest of gameId 5560797021.
- `3b46441` — Game-PC LCU agent edge-fires the POST on `EndOfGame` phase transition.
- `781f895` — agent crash-recovery: persists `last_game_id_ingested` to `C:\RC-Agent\agent_state.json`, runs one-shot `_recover_missed_ingest()` on boot to ship any game that was missed (covers Game-PC crash at end-of-game, agent offline at end-of-game).

**Post Game Review page — frontend iterations:**
- `9641648` — Quick Review team-level heuristics from LCU enrichment (lost first blood/tower, dragon control diff, soul/baron giveaway, tower diff, gold deficit, kill deficit — mode-aware for SR + ARAM, suppressed for Arena).
- `03f7fc5` — condense hero (cluster left + drop padding), fold Deep Review button into Quick Review section title, hide live-game pills on this view.
- `6883c32` — 2-up layout: stats|build same row, ally|enemy team comp same row.
- `62884cd` — drop BUILD section entirely (operator: redundant with team-comp items), stats fold into hero row, roster name col fixed at 130px so L## / KDA / CS columns align vertically.
- `dca7ffe` — rank-tier compare dropdown (Iron→Challenger), localStorage-persisted (`rc-pgr-rank-tier`); hand-curated `_RANK_TIER_AVERAGES` for v1.
- `09b6ed3` — fix panel snapshot tests: `/#last-match` URL was the legacy "show main panels" view-id; s219 made it hide `main`. Test now injects CSS override to nullify the hide rules for that URL only.
- `31c214b` — tabbed panel: Comp / Chart / Review tabs replace "TEAM COMPOSITION" title. Chart tab is new (ally-vs-enemy aggregate bars). Review tab is the relocated Quick Review. Tab choice persists.
- `740e8ee` — biggest hero rework: 3 sections (identity / 2-row match stats / 2-row rank-cmp). Stats now include Vision, Tanked, Damage, CS/min, Heal+Shield. Section 3 uses `grid-template-areas` for bulletproof cell positioning. `enriched.support.heal_plus_shield` added. Font bump (+1px). Team-comp row columns fully fixed-width so ally + enemy share identical column widths.
- `6c0728e` — per-player augments extracted into `enriched.roster[].augments` (LCU `playerAugment1-6`). Backend only — frontend rendering carried to next session.

**Other:**
- BACKLOG.md gained 4 research/inspiration items (coachless.gg teardown, DDragon mirror auto-refresh, Pengu.lol MCP adaptation, Pengu.lol Discord crawl).
- DDragon mirror at `web/data/ddragon/16.8.1` cloned to `16.10.1` (12 MB, gitignored) so the running patch's item/spell icons load locally without CDN-fallback hammering.

## Live in browser (verified by capture)

- 1080-viewport fits hero + tabbed panel without scroll.
- Hero shows: portrait + Quinn + ARAM + 3/11/11 + 1.27 KDA + DEFEAT + D grade clustered tight | centered match stats (CS 20 1.7/min, Tanked 21.6k, KP 56%, Damage 12.4k, etc.) | right rank-cmp (Diamond avg: CS 75 6.2/min, Tanked 31k, KDA 3.3, KP 68%, Damage 25k, Heal 3.2k).
- Quick Review heuristics fire 5 signals on Quinn match (Lost first blood, Lost first tower, Lost every tower trade, Team kill deficit 25-48, Death count cost the team).
- Chart tab renders ally-vs-enemy aggregate bars (Kills 25-48, Deaths 48-26, Damage 54.6k-98k, etc.).
- Team Comp tab renders both rosters with portraits + items + summoners + me-highlight on SamplePlayer row.
- LCU agent auto-ingest verified live: gameId 5560797021 ingested through `EndOfGame` → `agent_state.json` saved.

## What's next (carried into next session)

**Operator's deferred items (do these first per final s219 message):**
- **Item C — rich item tooltips on hover** (champ-select style with LoL content via `lol_descriptions.js` + `/api/dictionary/{items,runes,champion-tags}`). Backed by existing `data-tt-html` app-tooltip plumbing in `champ_select.js`. Should propagate to DS picks tiles + Comp tab item icons + augments (once shipped).
- **Item E — port LCU `/lol-match-history/v1/games/{gameId}/timeline` view OR final interactive minimap** into the Post Game Review page. Timeline has gold/cs/level deltas per minute + kill/death events; minimap would be the visual replay overlay. Operator's hint: "the final interactive minimap that is seen from the league client when looking at the match history results."
- **Settings page additions** — canonical home for the rank-tier dropdown persistence (currently localStorage `rc-pgr-rank-tier`), the baseline-count knob (currently fixed at 20 via `_build_last_match`'s SQL LIMIT 20), and any future post-game-review toggles. Existing `view-settings` section already in HTML.

**Operator's deferred polish items from final mid-session message — verbatim quotes preserved so nothing is lost in interpretation. Operator explicitly said: "i dont wish to reiterate on them":**

1. _"bump all font sizes up by 1 again, for all elements from hero row and down."_
   → This is the **3rd** font bump operator has asked for this session. v5 (`31c214b`) was bump #1, v6 (`740e8ee`) was bump #2. Bump #3 is still owed. Apply to **hero row AND down** (so: hero champ/KDA/grade/stats + tab nav labels + tab panel content including Quick Review li, team-comp roster row, Chart bars). Reference current sizes in `web/css/panels/last_match.css`.

2. _"tab titles should be uniformly spaced and likely will need some sort of tying color to the panel it controls.. not sure - we can ask the ui agent when its time."_
   → Uniform spacing DONE in v5/v6 (`.lm-tab { min-width: 96px }`). **Color-tying** deferred to UI agent. Don't ship until UI agent reviews.

3. _"for the ally enemy panels, the vertical alignment of the CS is off for both, they should be right aligned vertically insync"_
   → CLAIMED done in v6 (`740e8ee`) via fixed-width grid columns + `text-align: right` on `.lm-tc-cs`. **VERIFY in next session** — operator restated this AFTER v6 shipped, so they may still see misalignment or there may be a render bug I missed. Capture screenshot of both COMP-tab rosters and check that the CS column right-edges align column-for-column between ally + enemy.

4. _"move the Open Deep review button to be a 'tab' as Review, and change the current tab named review to be Insights"_
   → Tab strip becomes: **Comp / Chart / Insights / Review**. The current "Review" tab content (3-column Quick Review) becomes the "Insights" tab. The new "Review" tab is the **deep-review navigation tab** — it doesn't have its own panel; clicking it should navigate to `view-review` (or wherever the Deep Review page lives) with `sessionStorage.rc-review-focus-match` stash. The right-aligned "Open Deep Review →" button in the current tab nav gets removed (its functionality folds into the new Review tab).

5. _"in the tab panel, chart -- cant read the text, and is super bright...."_
   → Chart tab contrast. Current bars use `--ok` (#8ce5a8) and `--bad` (#e07a7a) at 0.85 opacity; white value text sits ON TOP of the bar fill and gets washed out. Fix candidates: (a) drop opacity to ~0.5; (b) move text to the dark surface background (outside the fill area); (c) use only-the-tip color highlight + neutral bar body; (d) add text-shadow / outline so text reads on any background. Pick one + verify on a real capture.

6. _"i have also noticed perhaps its my eyesight but the Ranking icon for S-D etc .. is harsh to view like it doesnt visually flow right something isnt correct when viewing it as compared to other icons or background n borders that we have used once we finish the ui agent and if it passes -- propagate this change to all pages that use the ranking icon n bg"_
   → **Grade letter badge (D in Quinn's case, S/A/B/C/F otherwise) in the hero row.** Current `.lm-hero-grade`: 44px bold colored grade letter on a `var(--surface-2)` background with `var(--radius-sm)` border. Operator finds it harsh — likely the **strong-tinted grade-color text on dark surface** creates excessive contrast vs the rest of the muted dashboard palette. Defer to UI agent pass for the redesign spec. **Once UI agent approves** → propagate the new style across all panels that show this badge: Home page Recent 5 row + This Week row, History view, Session view, Replay view, anywhere else it appears. Grep `.lm-hero-grade` and the `--grade-*` CSS variables to find consumers.

7. _"use a visual separator that we have seen used in the champ select page the 1 px wide line , just vertically. or the colored tabbing to distinctly show the 3 section separation for the hero row."_
   → Hero row currently has 3 sections (identity / match-stats / rank-tier-cmp) packed close. Section 3 already has `border-left: 1px dashed var(--border-soft)`. Section 2 has NO separator from section 1. Apply the same 1px dashed/solid vertical line between section 1 and section 2 (or operator's alternative: "colored tabbing" — likely means a subtle colored stripe at each section's left edge that ties to the section's content theme). The champ-select reference is `web/css/panels/champ_select_view.css` — search there for the 1px-line pattern operator likes.

8. _"for the hero row, section 3 - increase the fonts to match the rest of the hero row typography, and move the kp% to where the kda is , and shift kda over to the left more but not beyond the left side of the selectors left most side"_
   → Section 3 typography is currently smaller than sections 1+2 (rank-cell-value 14px, rank-cell-label 10px) — operator wants it to MATCH the hero row (so: rank-cell-value should go to ~23px to match `.lm-hero-stat-value`, rank-cell-label to ~13px to match `.lm-hero-stat-label`). **Plus a reordering**: in section 3, swap KP% and KDA — KP% takes the spot KDA currently occupies (row 2 col 1 — directly below selector), and KDA shifts LEFT (operator: "shift kda over to the left more but not beyond the left side of the selectors left most side" — so KDA's left edge can be ≤ selector's left edge but no further left). Likely target layout: selector at (1,1), KDA at (1,2) right next to selector, KP% at (2,1) below selector, then the other stats fill the remaining cells. Check the `grid-template-areas` definition in `.lm-hero-rank-compare`.

9. _"include in the comp tab, for each player - their selected augments. if aram mayhem or arnea *"_
   → Per-player augment icons in Comp tab roster rows. **ARAM Mayhem (KIWI mode, queue 2400) + Arena (CHERRY mode, queue 1700/1710) only.** Backend already ships the data: each `enriched.roster[N].augments` is a 6-element list of integer augment IDs (`playerAugment1-6` from LCU stats). Frontend lift remaining: (a) decide where in the team-comp row to place the icons (probably between summoner spells and items, or below the row as a sub-strip); (b) resolve augment ID → icon URL. Riot's augment icons aren't in DDragon. Likely CDN paths to investigate:
   - `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/cherry-augments-img/<id>.png` (Arena)
   - `https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perks/augments/<id>.png`
   - Pengu Loader Discord likely has the canonical map (covers our existing BACKLOG item to crawl)
   No icons for ARAM Mayhem augments yet — research needed.

**Deferred to UI agent review (don't ship until reviewed):**
- Item #6 above (grade-letter badge redesign) + post-approval propagation to all pages using the badge.
- Item #2 above (tab title color-tying).

**Operator's session closing instruction** (verbatim): _"do /done for a /clear then next session to finish C and E and settings page add, then a quick lookover for anything else"_
   → Priority order for next session: (1) Item C, (2) Item E, (3) Settings page additions, (4) sweep the 9 polish items above + verify CS alignment (#3) still holds + check for anything else missed across the session that didn't land in this list.

## Blockers / don't redo

- The **rename** is everywhere — don't add a new view-id (e.g. `post-game-review`); operator chose to keep internal id `last-match` so all 27 view_router_state tests don't churn. Display label is the only operator-visible surface.
- The DDragon **mirror at 16.10.1** is a clone of 16.8.1 (most item icons don't change between minor patches). Don't try to fetch the actual 16.10.1 assets from CDN — only do it when a specific icon goes missing AND CDN fallback fails. The auto-refresh BACKLOG item covers the durable fix.
- The `_RANK_TIER_AVERAGES` constants in `web/js/panels/last_match.js` are **hand-curated**. Don't pretend they're statistically grounded — real per-tier aggregates from rewind_history.db are a deferred backend feature; Settings page work could unlock this if it adds the calibration pipeline knob.
- The **Phase 3 supervisor watch** in `ops/rc_supervisor.py` is a frozen-file edit — operator authorized this session. Don't unfold without explicit reauthorization.
- `gamepc_lcu_agent.py` running at `C:\RC-Agent\` on Game-PC was redeployed twice this session via the http.server-on-Legion + Invoke-WebRequest dance. Pid is currently **2428** per last check; will be different on next reboot. Use the memory-documented redeploy steps for changes.
- `agent_state.json` at `C:\RC-Agent\agent_state.json` is the crash-recovery anchor — DON'T delete it. If corrupted, the agent treats the next launch as a fresh boot and recovers from LCU's latest gameId.
- Panel snapshot test override (`page.add_style_tag(...)`) in `tests/snapshot_panels/test_panel_snapshots.py` is load-bearing — without it, all 6 game-mode fixtures fail because the test's `/#last-match` URL now activates the Post Game Review view-section which hides `main`.
- Don't repeat the **CDN onerror fallback debug** — when ITEMS.version was 16.10.1 and the local 16.10.1 dir didn't exist, the inline `onerror="..."` chain to CDN didn't fire visibly. The proper fix was already taken (clone local mirror to 16.10.1). The real "why didn't onerror fire" investigation is still open but blocked on Chrome devtools access we don't have remotely. Don't re-investigate without a new approach.

---

# s218 wrap — 2026-05-15 (Home page redesign + foundation overhaul)

**Operator instruction:** "doing ui work" — open-ended iterative pass on the Home view. Closed out with "this page is done now. commit and /done".

## Shipped — single commit (`4518ed9`)

**Foundation (applies to all views going forward):**
- Pin RC menu width at 230px (static across views; fits longest case "AUTO · PRE-GAME LOBBY"). `.title-current` switched from min-width to fixed width per operator hard rule.
- Bump typography +1px globally — 414 declarations across 14 panel CSS files via Python script; RC menu rules (4 skipped) preserved per directive.
- Flip body zoom default 1.33 → 1.0 in `base.css`. Fixed dev.js/main.js localStorage key mismatch (slider wrote `rc-zoom`, page-load read `rc-body-zoom` — body was always 1.33 regardless of slider position). Both now use `rc-zoom`.

**Dev/Sim Preview removal** (separate concern operator green-lit mid-session):
- Drop `#view-dev` section + menu item + `#sim-banner` block.
- Delete `web/js/sim.js`, `web/css/panels/dev.css`, `dashboard/routes_dev.py`.
- Archive `data/sim/*` + `data/sim_states.json` → `docs/_archive/2026-05-15-dev-sim-removal/`.
- Scrub orphan refs across `agents/supervisor.py`, `dashboard/_state_builder.py`, `dashboard/_handler.py`, `dashboard/_static.py`, `riot-commander.spec`, `tools/extract_panels.py`, `web_dashboard.py`, `view_router_state.py`.

**Home view content:**
- **7-tile quick actions** in operator's order: Find Match · Last Match · Session · History · Replay · Builds · Settings. Equal-width centered tiles. Find Match accented with lavender gradient + info-soft border + lavender icon (primary action signal).
- **Find Match opens a Home-unique queue picker modal** (centered fixed-position, backdrop dimmer, Escape/outside-click close). Mirrors lobby-view's `#lv-mode-menu` queue list with `data-hfm-*` attributes. Click → fires `change_queue_type` LCU command → routes to Pre-Game Lobby. Two false-start iterations resolved: synthetic `.click()` on `#lv-mode-trigger` after route was racing with the document outside-click handler → final landed approach is `e.stopPropagation()` on tile click + direct DOM mutation of menu's `hidden` class.
- **Tonight's Pick 3-section restructure**: Section 1 = champion intro (icon + name + meta); Section 2 = THE GOOD / THE BAD / THE UGLY placeholder rows tagged `data-dummy-data="tonights-pick-tips"`; Section 3 = STREAK / ADVISORIES sub-header rows wired live to `_HOME.streaks` (play_days + good_grades) and `#advisory-count`. Layout: `grid-template-columns: auto 1fr 1fr` so Section 1 sizes to content + Section 2 starts at a finite boundary after "best B" text. Section 3 uses 88px label col + 16px gap (matches Section 2) for symmetric label-value spacing. "Open Advisories" → "Advisories" rename to fit column. 14px row-gap between Streak + Advisories rows.
- **Recent 5 row updates**: spell out "X Minutes" (was "Xm"), append CS + CS/min chip, 6-slot placeholder item strip tagged `data-dummy-data="items-pending-ingest"`. Card click → History view with `sessionStorage.rc-history-focus-ts` → auto-select date-matching session + scroll target row + pulse-highlight class for 3.5s.
- **This Week row updates**: KDA breakdown "1.8 22/10/18" (avg + raw totals), AVG CS per game + CS/min (operator clarified avg not total), grade-tint demoted from card-bg-tint to 3px left-border accent (transparent bg + bottom-only divider — operator wanted list, not cards). Bumped `.home-week-bar-kda-raw` 13 → 14px to separate hierarchy from 15px ratio pill.
- **Backend (`dashboard/builders.py`)**: `/api/home/summary` recent[] gains `cs`, `cs_per_min`, `items[]`, `mode_subtype`; this_week[] gains `kills`, `deaths`, `assists`, `cs_total`, `cs_per_min`. RC hard-restarted (pid 18628 → 15752) via `taskkill /F /PID + restart.bat` after `restart_trigger.txt` mechanism didn't consume two attempts.
- **Hero headline**: drop absolute-threshold `up/down` classifier (was rendering 1.27 KDA as `.down` salmon-red despite no comparison baseline). Always `.flat` text-dim until real yesterday-comparison baseline ships.
- **Tonight's Pick "Jinx" name → History filtered by champion**: clickable (cursor:pointer + green-tinted underline on hover) → `sessionStorage.rc-history-focus-champion` → `_historyFetchAndRender` finds most recent session containing that champion + highlights all matching match rows + scrolls to first.

**Footer + tooltip polish:**
- Footer height 44 → 36px, color `--text-faint` → `--text-dim`, line-height 1, all children `inline-flex; align-items: center`. ui-version pill opacity 0.6 → 0.85.
- `wrapSixWords` (tooltip system) was splitting on ALL whitespace (including `\n`) so multi-section tooltips collapsed into one long line. Now preserves explicit `\n` boundaries, wrapping each source line independently at 6 words → RC pip / health-dot multi-section tooltip renders per-row.

**Cleanup:**
- Drop orphan `.home-pick-btn*` CSS (advisory + digest pip-buttons that Section 3 redesign replaced).
- Drop orphan `wireAlertRow` calls in `_homeWireStartup`.
- Drop orphan `view-dev` CSS selectors in header.css.
- All edits verified: py_compile clean on touched Python files; 27/27 view-router tests; live dashboard auto-reloaded via asset-hash; cache-bust hash flipped to `b5f4bf09c6`.

## Visual audit
Mid-session ran a `general-purpose` Agent for independent UI review. Surfaced 3 must-fix + 4 should-consider + 5 leave-alone findings. Operator picked 6 of 7 to apply (skipped #1 as false positive after re-verification). All 6 applied + verified live.

## Tests / verification
- `tests/test_view_router_state.py`: 27 pass + 16 subtests.
- `tests/test_routes_ds_preview_scorer.py` + `tests/test_state_builder_archetype_pick.py` + `tests/snapshot_panels/`: 59 pass + 16 subtests in 18.65s combined.
- Manual: Recent 5 click → History deep-link pulse-highlight verified by operator. Find Match picker modal → operator clicked queue → routed to Pre-Game Lobby successfully.

## What's next
- **Operator signaled next session = next view.** Page order likely: Pre-Game Lobby → Champ Select → Active Match → Last Match → Session → History → Replay → User Builds → Settings.
- **Tagged-for-removal placeholders** stay until backend work catches up: `data-dummy-data="tonights-pick-tips"` (needs post-match Good/Bad/Ugly analyzer), `data-dummy-data="items-pending-ingest"` (needs `items[]` column in match_history.db ingest), `builders.py` `items: []` + `mode_subtype: null` placeholders (same).

## Blockers / don't redo
- **Heartbeat ♥ — in header top-right** flagged by operator: WS heartbeat envelope (`{type:"heartbeat", t:epoch}`) doesn't re-arm immediately after RC restart. The dashboard at `web/js/main.js:5026` populates `#heartbeat` only on WS envelope arrival; supervisor's broadcast loop needs investigation. Don't re-investigate the WS connection itself — `ws://192.168.8.230:8891/push` is confirmed connected (footer shows it).
- **`restart_trigger.txt` watcher wedge** confirmed pre-existing — the supervisor's poll loop at `ops/rc_supervisor.py:1240` didn't consume trigger files on 2 attempts this session. Workaround: hard `taskkill /F /PID + restart.bat` documented as standard. Don't re-debug; existing memory entry `project_rc_supervisor_restart.md` already covers.
- **Hero headline up/down classifier removed**: do not re-add until a proper yesterday-comparison baseline is wired into `/api/home/summary`. Operator explicitly prefers flat over wrong-direction-tinted.

---

# s217 wrap — 2026-05-15 (DS Phase 5.9.22 sum-of-blocks data batch — Taliyah E + DrMundo W)

**Operator instruction:** "continue ds" — keep DS engine moving from where s215 left off.

## Shipped — single commit (this session)

Second pure-data sum-of-blocks batch following s215's s207-schema-lift consumption. Closes the s215 carry-forward queue under the operator-commits-to-canonical-burst model. 2 entries (1 NEW key + 1 LIFT of existing single-int):

- **Taliyah.E = [0, 2]** — NEW key. Block 0 "Magic Damage" (60-240 base + 60% AP — initial shard-impact pass-through when each launched shard hits an enemy) + Block 2 "Total Maximum Detonation Damage" (62.5-262.5 base + 75% AP — aggregate of multiple stone detonations when target steps through the resulting Unraveled Earth terrain). Operator commits to landing the spell on target + target moving through resulting terrain. Closes s215's "Taliyah E likely no-op since block 2 already aggregates" framing — that missed that block 0 IS an additional damage source separate from the detonation aggregate (the initial pass-through is a distinct hit from the detonation step-through).
- **DrMundo.W = [1, 2]** — LIFT from s193's single-int `{W: 1}`. Block 1 "Total Magic Damage" (80-320 base — full 4-second Heart Zapper drain channel) + Block 2 "Magic Damage" (20-80 base — recast detonation burst when operator manually re-fires W at end of channel). Same in-batch lift pattern as s215's Thresh.E lift `{E: 2}` → `{E: [1, 2]}`. Operator commits to letting Heart Zapper run + manual recast for full Mundo W single-target burst.

ENGINE_VERSION 0.93.0 → 0.94.0. Registry stays at 124 champions (Taliyah gains E key alongside existing Q=2; DrMundo lifted from int to list, same key count). Total (champion, key) entries: 192 → 193 (Taliyah +1; DrMundo unchanged).

**Live A/B headlines on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP HTTP probe):**
- Taliyah E per-spell raw 60.00 → 122.50 (**+104%**, 60+62.5 sum confirmed) — small total lift (+5.95%) because Taliyah Q's Threaded Volley already dominates her ability_dps total.
- DrMundo W per-spell raw 200.00 → 250.00 (**+25%**, 200+50 sum confirmed) — modest total lift (+4.1%) because Mundo's other spells (Q/E) contribute meaningfully too.

Arithmetic parity exact: `s217 sum = forced_block_A + forced_block_B` to 4 decimal places in tests. Per-rank math verified against Meraki 16.10.1 snapshot — Taliyah rank 5: 240+262.5=502.5 raw base; DrMundo rank 5: 320+80=400 raw base.

**Investigation outcomes:** During scan, confirmed the other s215 carry-forwards stay deferred per their original rationale: Jinx R (block 0 "Maximum Physical Damage" 300-600 + 155% bAD IS the canonical primary-target maximum at max-distance + missing-HP scaling; blocks 2-3 are secondary AOE on enemies behind primary — engine default block 0 already correct for single-target focus, no registry entry needed); Kindred E / Kayle E / Belveth R remain in the nested missing-HP parser bucket (Phase 4a parser limitation around `target_missing_hp_pct` nested under `unparsed_modifiers`).

## Tests
- **19 new tests** in `agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s217.py` (Phase599_22RegistrySeedTests 3 / Phase599_22AbilityDpsTests 6 / Phase599_22BackwardCompatTests 9 / Phase599_22EngineVersionTests 1) mirroring s215's pattern.
- **2 ENGINE_VERSION pin bumps** in `test_effects_expansion.py` (0.93.0 → 0.94.0; one in `Phase599_20EngineVersionTests` per its 8-line s217 comment block, one in `test_batch64_version`).
- **1 ENGINE_VERSION pin update** in `test_sum_of_blocks_expansion_s215.py` (pin tracks current engine version per established convention).
- **3 existing assertions updated** in `test_block_index_overrides.py`: shape-pin in `test_assert_known_overrides` for DrMundo (`{W:1}` → `{W:[1,2]}`) + Taliyah (`{Q:2}` → `{Q:2,E:[0,2]}`); `test_drmundo_W_routes_to_block_1` renamed to `test_drmundo_W_routes_to_sum_of_blocks` with inline list-shape assertion replacing the `_delta_check` int-only helper (same pattern s215 used for Thresh.E lift); `test_pre_s202_taliyah_unchanged` backward-compat pinned to post-s217 shape.

DS suite 2041 → 2060 (+19). Wider RC `tests/` 953 green post-DS-restart (phase8_smoke probes live :8893 engine_version which was 0.93.0 pre-restart — fails until DS bounced; passes after restart). Full project test discovery (`py -m unittest discover -s . -p "test_*.py"`): 3013 tests green.

## DS server restart
- Killed pid 9696 (running 0.93.0).
- Cleaned stale 8893 listener (briefly bound by orphaned launcher).
- Restarted via `Start-Process pythonw tools\start_daemon_slayer.py`; new listener pid 19128.
- `/health` confirms `engine_version: "0.94.0", patch: 16.10.1, champions: 172, items: 705`.
- Note: HTTPS handshake returned SSL `WRONG_VERSION_NUMBER` on first attempt — DS server is serving HTTP not HTTPS at 127.0.0.1:8893. Live A/B used `http://127.0.0.1:8893` (matches the existing wider-test wire format). Not s217-introduced; pre-existing condition.

## What's next
- **Live ARAM Mayhem test** still scheduled by operator post-/clear (carried s214 → s215 → s216 → s217). Now also validates Phase 5.9.22 Taliyah/DrMundo ability_dps lifts ride through to `/api/ds-preview` for the build chooser's experimental row + Taliyah's Worked Ground commit + DrMundo Heart Zapper recast detonation.
- **DS Phase 5.9.23+ scoping** — sum-of-blocks bucket queue exhausted under current operator-commit framing. Next batch needs a different angle. Candidates for future work: (a) **Conditional target-state schema lift** — 6+ candidates queued since s195: Lux Illumination mark amp, DrMundo E missing-HP threshold, Renekton Q at full Fury (already routed via s197 single-int but conditional model would express the canonical Fury bar build-up), Zed shadow Q empowered, Aphelios weapon-form conditionals. Schema lift: `block_index: int | list[int] | dict[str, int]` where dict expresses conditional state → block_index mapping. (b) **Nested missing-HP parser bucket** — Kindred E / Kayle E / Belveth R execute curve still gated on Phase 4a parser learning nested `unparsed_modifiers` syntax. Upstream extractor work; not pure-data. (c) **Per-form block_index** — Heimerdinger.W form 1 (Upgrade!!!) has 20 rockets vs form 0's 5; current registry [0,1,1,1,1] under-counts upgrade form. Schema lift: registry value is per-form dict. (d) **Aphelios Q forms** — Meraki bulk parses all 6 Q weapon-form variants as `no_damage`; upstream data-quality fix required before any registry entry.
- **Loadout autogen calibration** unchanged from s215 (operator may flip `default_per_mode` pointers post-Mayhem).
- **Deadcode cleanup (carried, low priority)**: `coaches/brawl_coach.py` + brawl mode detection across 6 files.

## Blockers / don't redo
- DS server :8893 is HTTP, not HTTPS — don't waste cycles diagnosing SSL handshake errors. `curl -k -s https://...` returns RST/wrong-version; use `http://127.0.0.1:8893/...` instead. Pre-existing condition matches the wider-test wire format.
- `_delta_check(champion, key, expected_idx)` helper in `test_block_index_overrides.py` only handles int expected_idx — for sum-of-blocks (list-valued) entries, use the inline pattern from `test_drmundo_W_routes_to_sum_of_blocks` (assert `block_index_resolved.get(key) == [a, b]` + delta-check against forced single block). s215 established this pattern for Thresh.E; s217 extended to DrMundo.W.
- `_meta.rationale` in `champion_block_index.json` was NOT updated by s215 — last entries reference s205. s217 also only updated `_meta.description` (kept rationale append as future cleanup, since it's a 78KB file and rationale duplicates much of description's per-entry math). Not a regression — both fields are documentation.
