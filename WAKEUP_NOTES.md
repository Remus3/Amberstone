# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-17 (RM-02 live-plumbing session relocated the mdclean C1-C8 block LEDGER 912 to `docs/history_notes.md`; newest 3 kept below).

---

# 2026-07-17 (RM-02 counter-hint live-plumbing fix - allPlayers roster in the browser summary; LEDGER 916; 318e7e3a + d8fa0e1c)

Focused headless fix closing the TOP RM-02 blocker flagged in the orchestrated round's Round-2 note (below). mode_key=client, no live game. TDD RED-first (test-driven-development skill); verified vs ground truth before scaffolding (grepped the JS extractor field shape in active_match.js + the ui_mock fixture contract, confirmed state.liveclient = liveclient_summary() at _state_builder.py:663).
- **Root cause (confirmed):** `liveclient_summary()` (dashboard/_liveclient.py) emitted derived enemy slices (enemy_team/enemy_item_ids/players) but NO raw `allPlayers`; active_match.js:655 `_hasRoster` keys on `lc.allPlayers`, so C2 antiheal / C6 tenacity / C3 fed / R102/R103 chips were DARK in every live game (ui_mock-only).
- **Fix (`318e7e3a`):** new pure module-scope `_lean_roster` + `_as_int` -> emit `out["allPlayers"]` (championName/rawChampionName/team + summoner identity + level + items[{itemID,slot}] + scores{kills,deaths,assists}) + `out["activePlayer"]`{summonerName,riotIdGameName}. Faithful SUPERSET of the ui_mock fixture (adds the live-only scores+level the C3 fed path needs). Emitted independent of me_pl (the JS _resolveMyTeam does its own active-player match); empty list -> honest COUNTER hide (byte-identical to the pre-fix live-absent path).
- **TDD:** new tests/test_liveclient_allplayers_roster.py (14 tests) RED (11 fail - roster absent) -> GREEN; replicates _resolveMyTeam + the enemy/ally filters vs the real emitted shape. Verified 14 + 84 sibling + 153 consumer + 380 snapshot_panels + budget green; ruff clean; CI run 29583216769 SUCCESS.
- **Deploy:** RC restarted live (pid 17296, alive, last_reload_ok); /api/state 200 (liveclient {} = honest hide, no game). Docs `d8fa0e1c`: ROADMAP RM-02 -> CODE-COMPLETE + LEDGER 916.

OWED (do-not-flip-blind): the operator eyeballs the antiheal/tenacity/fed/roster chips in a REAL game (Electron overlay agent-blind). The WHOLE counter-hint program is now CODE-COMPLETE - the JS POST side (S9) + the server routes were already verifier-CONFIRMED, only this summary key was missing. Do NOT redo. NEXT: accrue real-game fusion_shadow toward the Lane E OCR flip (RM-01); the DS meta-valuation per-champ sweep remains the standing headless lane.

**DS-sweep research (this session, read-only - NO engine change): TWO candidates closed REFUTE, both live-verified + memory-recorded.**
- **Kai'Sa poke->Manamune = REFUTE.** Manamune 3004 IS in Kai'Sa's SR pool + correctly ranked 20/111 (delta 39.90 @L11), fully modeled (Awe/Muramana internal); Muramana 3042 correctly excluded. Poke build is niche off-meta (~36% WR); forcing Manamune up = valuation distortion / AD->AP kit-axis flip (barred by project_ds_build_reco_optimal_not_winrate). Memory `project_ds_sweep_kaisa_poke_manamune` (RESOLVED-REFUTE).
- **Jhin lethality-crit (the documented pilot gap) = REFUTE, comprehensively CLOSED.** fight_length=0.5 (ds_champion_fight_length.py) + L1 coherence_rerank + L3 crit-burst table + **L4 squishy-carry target swap (daemon_slayer_client.py:1533, default apply_squishy_burst_target=True)** ALL shipped + live. Verified: `rank_for_primary_archetype('Jhin','carry',L16)` surfaces the lethality core - Collector 6676 #2, IE 3031 #7, Youmuu's 3142 #8, Serylda's 6694 #9, Hubris 6697 #10 (vs raw no-fight_length: Collector #11, Youmuu's #31). GOTCHA: tanky==squishy identical rank is INTENDED L4 behavior (mapped burst carries always eval vs squishy_carry_target), NOT a bug - read the code before logging a "target-insensitivity" thread. Memory `project_ds_sweep_jhin_lethality`. Two MINOR cosmetic threads for a future pass: (1) ds_champion_fight_length.py docstring lines ~89-95 say "L4 out of scope / lethality buried at tanky" - STALE, L4 shipped; (2) client effective_score reads 0 (server reorder is correct; see reference_ds_client_effective_score_parse).

**NEXT SESSION (operator directive 2026-07-17): continue the DS meta-valuation sweep with a FRESH champion candidate** (Kai'Sa + Jhin now closed). Candidates: Varus (3 distinct builds lethality-poke / on-hit / crit - rich valuation question), or an AD-assassin / lethality carry not yet swept. Run the read-only research pass FIRST (GAP or REFUTE, per feedback_ds_sweep_meta_valuation_research) before any Tier-2 build; a REFUTE is a valid outcome.

---

# 2026-07-17 (headless-upgrade orchestrated round - 6 verifier-gated slices; LEDGER 914; 1e0ecfa6..255e119d)

Full-authority headless run (operator away, model switched to opus-4-8 mid-run via /model - a config change, not an interrupt). mode_key=client, no live game. One merger + 6 worktree slice agents on disjoint file sets, each gated by a read-only verifier CONFIRM, then truth_gate PROCEED (175 pytest/0 fail on the merged tree) before ONE batch push. No ENGINE bump; RC restarted clean (new pid, alive, last_reload_ok, dashboard 200); web slices auto-served (ADR-008). CI run 29572251333 (in_progress at wrap - verify green).
- **S1 DS C3 fed counter-hint (HINT-ONLY, `1e3cab6c`):** new `core/build_planner/fed_threat.py` lights the dead `fed` criterion; situational.py byte-identical; ranked build unchanged; 104/0 + 27. Chip dark until a JS slice POSTs enemy_scores/enemy_levels.
- **S2 overlay drag fix (`255e119d`):** all 3 symptoms root-caused in overlay_layout.js (_effectiveXY origin + window pointer capture + handle-only border hit-test); 15/15 + 6/6 + rc-shell 309/309.
- **S3 enemy-spell cd timer (`905982de`):** upgraded-Smite displayNames + cd=0 sticky "USED" chip; node 11/0 + pytest 28/0.
- **S6 Lane E fuse_reads shadow-first (`1e0ecfa6`):** per-tick fusion record to data/fusion_shadow.jsonl at read_tiered; served output byte-identical; 49/0. Advances RM-01.
- **S7 arena/tft mounts (`e880994b`):** S4 read-only DISPROVED the panelset hypothesis (mounts are data-gated); split the E6 poller gate so coaching mounts feed arena/tft; 8 + 11 subtests.
- **S8 cost lever-4 (`243967e8`):** suppress GET /api/state debug trace (58% of HTTP log volume); S5 sweep found the other 6 levers CLEAN.

OWED live-verify (Electron overlay agent-blind + no live game): S1 fed chip render, S2 drag per-panel + the empty-backing-press-inert behavior call, S3 upgraded-Smite countdown, S7 arena/tft mounts in-game. Do NOT redo: S1-S9 (all pushed + verifier-CONFIRMED + truth_gate PROCEED). Manifest run 2026-07-17-01.

Round 2 (LEDGER 915, `566e472b`): S9 shipped the C3 fed-chip JS POST (active_match.js sends enemy_scores/enemy_levels fail-soft) - completes the S1 vertical. **KEY FINDING (ground-truth-verified):** the browser `liveclient_summary()` (dashboard/_liveclient.py:68) emits derived enemy slices but NO raw `allPlayers` key, and active_match.js:655 guards the counter-hint roster on `lc.allPlayers` - so the WHOLE counter-hint program (C2 antiheal / C6 tenacity / C3 fed / R102/R103 roster) is DARK in every live game and lights only under ui_mock. NOT fixed this run (activates 4+ live surfaces blind; operator away). NEXT = the server-side plumbing fix (add a lean enemy roster with scores+levels+item ids to the browser summary) is now the TOP RM-02 live-gated blocker; land it WITH a real-game eyeball. Also NEXT: accrue real-game fusion_shadow toward the Lane E OCR flip.

---

# 2026-07-17 (teardown fold-in + F4 swap-wipe fix + headless queue drain; LEDGER 913; b35783a2..4b4aeb67)

Post-loop interactive-headless hybrid (operator: research doc drop, then "f4 now and continue open tasks headlessly"). mode_key=client, no live game. Subagent-first: read-only trace agent + UI-audit agent + TDD build agent.
- **Fold-in (b35783a2):** AI-companion teardown (Desktop `research-20260716.md`, non-repo, brands withheld) -> BACKLOG section. NOW-list corrected vs ground truth: F3 grade card = existing s220 PGR reframe; F6 chatbot stays R2-CLOSED (charter); F2/F8/F1 -> FUTURE. Companion family DRAINED 5x - rotate categories.
- **F4 (the owed swap sanity-check):** parity CONFIRMED by trace; 1 defect FIXED (`4b4aeb67`): build-less swap left old champ's RC-* item sets (wipe below both empty-guards). Hoisted wipe + `_CSV_LAST_WIPE_KEY` dedup + push-latch reset (hover-back re-push crux) + CS-exit clear; 13 RED-first tests, 33 green fresh.
- **Queue:** L-02 proposal already landed (`afdd20eb`) - artifacts + APPLIED marker committed (`facc01cc`), don't re-implement. LANE-U item-4 Slice 1 merged (`090fc62d`) after fresh 30/30 + the deferred 5-phase audit: MUST-FIX in-slice (`936fcc23` grid `align-items:start` + subhead token inversion); 1 SHOULD + 3 NICE -> FUTURE (handoff doc); id-wiring INTACT; remote branch deleted.

OWED carry-forward: settings-reorg PIXEL capture (browser screenshot pipe stuck; DOM verified live) + the item-4 Sections D/E/F interactive session (handoff doc TODO). NEXT: operator calls from the fold-in - (a) re-open F6 chatbot? (b) schedule the s220 PGR reframe session. Do NOT redo: F4 trace/fix, L-02, lane-U merge (all pushed; CI run 29569968111).
