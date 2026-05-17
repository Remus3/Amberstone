# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# ⚠ KNOWN BUG (logged 2026-05-17, operator) — champ-select screen wrong for ARAM / ARAM-Mayhem / Arena

Operator report, verbatim: *"the champ select screen is all wrong for aram + aram mayhem + arena."*
No detail captured yet — "all wrong" is unspecified (layout vs data vs render vs which elements). When picked up, gather specifics live: needs a champ-select pop in **each** of ARAM, ARAM-Mayhem, and Arena to see what's broken (a Game-PC `capture_monitor` of the dashboard during champ-select is fine — capture is only Vanguard-unsafe *in-game*, not in champ-select/client).
Leads for whoever investigates: champ-select had heavy recent churn (s164–s214 redesign, s208 legacy `#cs-overlay` retirement) and this 2026-05-17 session disabled the Game-PC screen agents + reworked the shortcut-only boot model — view-router / mode-detection regressions are plausible suspects. Not yet investigated; fix not started.

**2026-05-17 live-session leads (operator detail + code probe — partial diagnosis):**
- **Operator-reported specific symptom:** the **quick-swap (ARAM bench champion swap) is not active** on RC's champ-select screen for ARAM **and** ARAM-Mayhem.
- **Code path EXISTS end-to-end (capture-free probe this session) — the bug is NOT missing UI code:** `web/js/panels/champ_select.js` has `_csvBenchHtml(cs)` (renders the 5-cell bench from `cs.bench`) + `_csvWireBench(body)` (wires `.csv-bench-cell` click → `bench_swap` LCU cmd), both gated `if (mode === "aram")`; `_csvDetectMode(cs)` maps queue **450 AND 920 (Mayhem)** + `cs.is_aram` → `"aram"`; Game-PC `tools/gamepc_lcu_agent.py` populates `cs.bench` from `sess.benchChampions` and has the `bench_swap` POST handler (`/lol-champ-select/v1/session/bench/swap/{cid}`).
- **Strong hypothesis (root cause lead):** across **3 ARAM-Mayhem games this session**, every `/api/state` check during/just-after "champ-select" showed `lcu.phase: InProgress` **already** + `champ_select: {}` (`cs.keys: []`). RC never observed a populated champ-select state for ARAM-Mayhem. With empty `cs`, `_csvDetectMode` falls through to `"sr"` (no queue_id/is_aram) → the bench/quick-swap branch never fires → matches BOTH "champ-select all wrong" AND "quick swap not active". So the defect is **upstream of the UI**: the Game-PC LCU agent isn't forwarding (or RC isn't retaining) the ARAM-Mayhem champ-select session through the very fast ChampSelect→InProgress transition.
- **Next step for the fix (not done):** instrument/inspect `gamepc_lcu_agent.py` champ-select handling for **KIWI / queue 920** specifically — verify the agent even enters its champ-select poll/forward path for Mayhem (it may gate on queue types that exclude Mayhem), and/or add last-champ-select-snapshot retention in the RC state-builder so the dashboard view survives the sub-second transition. Needs a live ARAM-Mayhem champ-select with the agent instrumented (champ-select capture/curl is Vanguard-safe). The "fast transition" is itself a bug signature, not just bad luck — RC has missed the champ-select window on 3/3 Mayhem games.

---

# 2026-05-17 (eve) — build-order UI (B+C) + live augment-OCR PROVEN + KNOWN-BUG keystone lead

Operator-driven session off the OVERNIGHT RUN-1 hand-off.

**Shipped:** `2d7da9e` build-order UI — (B) collapsible vertical "Build Order"
card in the champ-select My Pick panel + (C) in-game `#ds-pill` next-2-in-order
glance, both consuming the already-live `/api/build-order`. New
`web/js/panels/build_order.{js,css}` + hooks in champ_select.js/item_build.js;
ADR-008 auto-served (no RC restart — go-live was already serving from the
morning restart). Headless-verified: node --check, 38 snapshot+view-router
green. Density pass applied (collapsed→1-line for the tight My Pick panel).

**Augment — RESOLVED + PROVEN:** rigorous AT-picker-open probe (Game-PC
`C:\RC-Agent\rc_augment_probe.py`) → **no capture-free LCU/:2999 augment API**
exists for Mayhem (all `/lol-cherry/*`+`/lol-game-augments/*` 404; :2999
"augment" = i18n red-herring). On-demand `mcp__gamepc__capture_monitor`
survived **2/2 full Mayhem matches** incl. match-end + augment pickers → no
BSOD → augment-OCR→coach **proven end-to-end live** (read Prismatic+Gold
pickers, operator took the rec'd Magic Missile). Upgraded to "working
augment-OCR substrate, operator-gated". DON'T re-pitch the augment API
(dead); continuous DXGI screen-agent stays DISABLED; capture stays
operator-gated. Latency protocol: operator says "now" AND holds pick until
"got it".

**KNOWN-BUG keystone (root-cause lead, see the ⚠ section up top):** 3/3
ARAM-Mayhem games showed `champ_select:{}` / `phase:InProgress` already —
RC never holds champ-select state for Mayhem. UI code IS present; defect is
upstream (gamepc_lcu_agent.py forwarding / state retention through the
sub-second ChampSelect→InProgress flip). **Blocks BOTH the KNOWN BUG fix
AND the build-order B-card live verify** — this is the next keystone.

**Other notes (in the docs commit):** ROADMAP — surrender-tag / pengu-list
(`Desktop/pengu list.txt`) / DS-augment-flag / augment-resolution. Lolmath
gap review at `Desktop/LOLMATH_GAP_REVIEW_2026-05-17.md` (no scrape drift,
no gaps where lolmath leads, reverse-gap shareables listed — don't re-run).

**NEXT:** (1) champ-select-state-for-Mayhem keystone (instrument
`gamepc_lcu_agent.py` for KIWI/queue-920 + state retention) — unblocks the
KNOWN BUG + B-card; (2) then C-pill curl-verify + B-card live-verify (a
non-Mayhem champ-select renders fine); (3) productize augment capture→OCR
→coach. Nothing mid-game; safe.

**⚠ TOOLING BUG (found this /done):** `scripts/wakeup_prune.py` crashes
(`SESSION_RE.search(b).group(0)` → None, line 105) — it treats every
`---`-delimited block as a dated session and chokes on the **pinned
`# ⚠ KNOWN BUG` non-session block** at the top of this file (added
2026-05-17; the pruner predates it). Prune was SKIPPED this /done — WAKEUP
is intact but unpruned (longer than the 3-session target → bridge cold-load
cost). **Fix before next /done:** make the pruner skip the file-header +
any non-`SESSION_RE` pinned block (or relocate the KNOWN BUG section out of
the `---` ledger). Until fixed, every /done's §6c will fail the same way —
don't re-investigate from scratch.

---

# 2026-05-17 wrap — Vanguard crash ROOT-CAUSED + Game-PC boot remodel + OVERNIGHT AUTONOMOUS RUN

Long crash-firefight session (not a numbered DS session). Operator flagged mid-session flip-flopping (borderless→Parsec→read-only→"definitive no API"→retraction) + memory over-churn — corrected; steady read below.

## Confirmed — do NOT re-investigate
- **Game-end AND mid-game `0x50` BSOD = `gamepc_screen_agent.py` DXGI screen capture vs Riot Vanguard (`vgk.sys`).** Isolation test proved it: RC fully up with the 3 screen agents NOT launched → full ~25min Mayhem match, no crash, Game-PC uptime continuous. Borderless / read-only-settings / Parsec-virtual-display all tested + RULED OUT. Full detail: memory `feedback_gamepc_screen_capture_bsod.md`.
- **Crash-safe state shipped:** `tools/gamepc_boot.ps1` remodeled → shortcut-only (no ONLOGON reinstall), version-agnostic Claude Code Desktop launch, LCU minimized. On Game-PC the 8 agent/boot ONLOGON tasks are DISABLED, 3 bridge tasks kept. **Screen agents DISABLED via an isolation stub** (commented-out launch block, step 4 of gamepc_boot.ps1) — KEEP disabled. Recovery: reboot → click "RC Agent claude" shortcut.

## Open / corrected
- **Augment-API question is OPEN (a prior "definitive no API" memory note was RETRACTED — probed off-window + shallow method).** Competitor overlays show augments instantly w/o crashing ⇒ a capture-free path almost certainly exists. Real discovery (LCU WebSocket `OnJsonApiEvent` capture AT the live augment-pick + full LCU resource enumeration + :2999 activeplayer/playerlist) is **TABLED until morning per operator** — do NOT pursue augment/Overlay App E discovery during the overnight run.
- **KNOWN BUG (top of this file):** champ-select wrong for ARAM/Mayhem/Arena — unspecified; detail it live (champ-select capture is Vanguard-safe; only *in-game* capture crashes).

## OVERNIGHT AUTONOMOUS DIRECTIVE (operator asleep ~6h; self-continuing headless loop armed)
**Primary goal:** plan + headless-test a **contextual, match-specific, DS-backed item BUILD ORDER** — fix "always the same items, not match-specific"; output an ORDER with contextual relevance from DS, NOT just max-damage/max-health. **HARD RULE:** unique passives cannot be doubled — never recommend two items sharing a unique passive (Sheen/Spellblade family: Trinity Force + Essence Reaver invalid together). DS already dedups spellblade via `unique_passive_key`; the build-ORDER layer must enforce this across ALL unique-passive families.
**Cascade** (advance when prior exhausted / blocked >5min / needs asleep operator): (1) DS headless tests toward the goal + a staged plan; (2) UI smoke-test with data + verify end-to-end wiring; (3) connect local match DB ↔ `rewind_history.db`, run DS against combined data; (4) self-continue + self-compact; (5) roadblock → full project audit (every line: deficiency/refactor/optimization); (6) → deep-dive research: feature options, UI iterations, competitor lifts, UI-density / information-overload UX best practices → staged plan `.md` on the **Legion desktop** (`C:\Users\Administrator\Desktop\`). Commit progress as it goes. No screen capture / no Vanguard-risk / no destructive unattended ops.

## NEXT-SESSION TRIGGER
Operator will `/clear` then paste the trigger text given at end of the wrap turn (resume this directive + read this wrap + the desktop plan .md).

---

# 2026-05-17 OVERNIGHT RUN-1 — contextual DS build-ORDER shipped (PRIMARY goal DONE)

Executed the OVERNIGHT AUTONOMOUS DIRECTIVE (above). The PRIMARY goal —
contextual, match-specific, DS-backed item BUILD ORDER with the hard
unique-passive no-double rule — is **functionally complete, proven
end-to-end against the live DS engine, wired, and hardened with a
machine guard**. 4 commits on `cc6aaa9`, all green, ruff+py_compile
clean, **0 engine changes, 0 DS restart, ENGINE stays 1.3.0**.

## Shipped (local main — NOT pushed; see "blocked on operator")

- `1a20424` `core/build_order.py` — `plan_build_order()`. Iterative
  greedy forward selection over `rank_for_primary_archetype`: one engine
  call per slot, each pick appended to `item_ids` so later slots re-rank
  vs the accumulated build + real enemy context. Kills "always the same
  items". 19 headless tests.
- `18139a5` opt-in wiring into `coach_integration/archetype_dispatch.py`
  (`with_build_order=False` default — per-tick path stays 1 call;
  `CoachDispatchResult.build_order`). +3 tests. **Live-proved vs real DS
  :8893**: flat bruiser ranking of {Trinity Force, Lich Bane, Essence
  Reaver} returns all 3 (the bug); planner picks Trinity Force then the
  engine's own `current_unique_keys` dedup filters the rest for every
  later slot → order stops at exactly 1.
- `240f709` read-only `POST /api/build-order`
  (`dashboard/routes_state._serve_build_order_post` + `BuildOrderRequest`
  schema + dispatch entry). The UI seam. +7 route tests.
- `da4f334` anti-drift / all-families machine guard
  (`tests/test_build_order_no_double_guard.py`, 5 tests).

## Key architectural facts (don't re-derive)

- **The no-double rule is engine-authoritative, not planner-side.** The
  planner forces `filter_shared_uniques=True` and *iterates* — the
  engine's `collect_effects`/`current_unique_keys` dedup (source of
  truth = `agents/daemon_slayer/effects.py`) does the actual exclusion.
  The planner carries **NO family map** on purpose (s173 anti-drift).
- **`effects.py` has 6 unique-passive families, not 3**: `spellblade`(16)
  `lifeline`(12) `immolate`(7) + single-item `fiendhunter_barrage`
  `hellfire_char` `innervating_fill`. The family-agnostic planner covers
  all 6 + any future one for free; the guard test machine-checks this
  (derives the set from `ITEM_EFFECTS` at runtime; ≥6 tripwire).
- **Gap found:** `only_item_ids` is silently ignored by the carry/dps
  branch (`rank_for` has no such param; only tank/bruiser/mage/assassin/
  enchanter thread it). Latent surprise for any caller. Fix is small
  (~1 file, thread `body["only"]`) but needs a DS restart → operator-gated.

## Blocked on operator (nothing blocks the backend; these are gated)

1. **Go-live:** `echo restart > restart_trigger.txt` on Legion to serve
   `/api/build-order` (deferred — unattended supervisor-restart risk vs
   marginal gain; route is headless-proven, planner live-proven).
2. **Push:** 4 commits are local-only. Directive said "commit", not
   "push" — deferred as a shared-state action (same discipline as the
   restart). Operator can push + restart + /clear in one reviewed step.
3. **Phase-3 UI render** of the ordered build — staged, NOT done blind
   overnight (UI-audit ritual + a live game to verify, per
   `feedback_phase3_fixture_ritual.md`). Desktop plan
   `BUILD_ORDER_PLAN_2026-05-17.md` §6b is a researched, decision-ready
   3-option UI menu (recommend: dedicated vertical "Build Order" card B
   + `#ds-pill` glance C; reject horizontal-cram A).
4. **`only_item_ids` carry-branch fix** (above) — needs DS restart.
5. **Champ-select KNOWN BUG (ARAM/Mayhem/Arena "all wrong")** — still
   unspecified, untouched (needs a live champ-select pop per mode to
   detail; champ-select capture is Vanguard-safe). Not the primary goal.
6. **Augment / LCU-WS discovery** — needs a live Mayhem/Arena augment
   window; can't be done headless. Un-tabled but operator-gated.

## Don't-redo

- DS engine + ENGINE_VERSION untouched (1.3.0) — `build_order.py` is
  pure orchestration. No DS restart was needed and none was done.
- Don't add a family map to `core/build_order.py` — it's deliberately
  family-agnostic; the guard test fails if a family literal appears.
- Vanguard BSOD = screen capture, CONFIRMED — screen agents stay
  disabled, do not re-litigate.
- Full `tests/` suite run post-change (schema/route discipline):
  **1141 passed, 0 failed** after `81af51e` synced the
  dispatch-validate path pin (the one regression RUN-1 introduced +
  fixed in-run). 5 commits total: `1a20424 18139a5 240f709 da4f334
  81af51e`.

## NEXT

Operator picks: (a) push + restart + verify `/api/build-order` live,
then the Phase-3 UI session (desktop plan §6b is the decision menu);
(b) the `only_item_ids` carry-branch fix (small, needs restart);
(c) the still-open non-build-order items (champ-select bug, augment
discovery) which need a live game; or (d) the long-pending s220 aggregator G
Post-Game-Review reframe. Recommend (a) — the primary feature is built +
proven and just needs the operator-gated go-live + the reviewed UI pass.

---

# s233 wrap — 2026-05-16 (operator decision: DS conditional arc CLOSED; next = s220 aggregator G reframe)

**Operator instruction:** asked what direction the DS Part-2 decision needed, chose to close the arc, then "plan what is next then /done".

## Decision (recorded in ROADMAP §High-priority s232 line + CLAUDE.md item 84)

- **DS conditional Part-2 — SHELVED PERMANENTLY.** s229 finding confirmed: Part-1 `"default"` is the correct strategic model for the only DS surface (item-build ranking); live per-tick target-state resolution would only be valid as a *separate live-advisory product surface* = out of scope / not wanted. **Do NOT re-pitch Part-2.**
- **DrMundo E `caster_low_hp` vocab — DECLINED.** Single instance, fails the s227/s229 5+-uses bar, moot with Part-2 shelved. No caster-state vocab family will be added.
- The 10 shipped conditionals (s228–s231) stay as latent correctness scaffolding, guarded by the s232 saturation test. **No further DS conditional-engine work.**

## Don't-redo / blockers

- The entire DS conditional vein (autonomous pure-data AND Part-2) is **closed by operator decision**. A future "continue ds" must NOT reopen it — zero remaining DS-engine ROI here.
- Docs-only session: no code/engine change, ENGINE stays **1.3.0**, no DS restart, no test delta (suite still 2255).

## NEXT

**s220 Post Game Review aggregator-G-style reframe** — the big non-engine UI item, already a 🟡 in ROADMAP with full scope (clickable match rows → persistent header + 10-player score strip → AI Analysis/Graph/Build tabs; 0–100 color-banded score; MVP purple card; carried polish: Sustain rename, hero section-1, aggregator G roster row, color-coding, #9 augments). **NOT blocked on the Riot key** (diagnosed s220 — only event-mode/KIWI queue-2400 403s; standard-queue last-matches populate fine; do NOT redo the key investigation). Per-player runes/ranks need an `_enrich_from_lcu` extension.

---

# s232 wrap — 2026-05-16 (DS Phase 5.9.32: conditional pure-data vein SATURATION PROOF — autonomous loop concluded)

**Operator instruction:** "Continue ds". s231's wrap flagged the vein approaching exhaustion; rather than churn low-value no-op conversions (the explicit s223-227 "don't churn low-value registry work" lesson + the no-padding principle), I ran a definitive saturation scan, surfaced the finding via `AskUserQuestion`, and **the operator chose "Accept loop complete."**

## What happened — rigorous exhaustion proof, then a decision

s231's constant-k pair scanner had a structural blind spot (it rejects the Kindred-E archetype, where the amp is a different-ratio bump concentrated in an HP coefficient). Built `tools/ds_execute_prefilter.py` (kept, durable per-patch) to catch exactly that. Result: **zero unaddressed clean execute candidates.**
- `target_full_hp` (execute): Evelynn R + KogMaw R (s231) + Kindred E (s228) were the clean ones. The only other true `target_missing_hp_pct` pairs are **already engine-default-correct** (Jinx R — block 0 holds the 25-35% max missing-HP coeff, confirms s217; verified live by inspecting blocks) or **deliberate R-entangled skips** (Varus W blocks 5/6 — s225 chose block 2 to keep W R-independent). Veigar R stays the deferred stable-int fixture.
- `target_no_setup` (self-debuff amp): the one genuine correctness fix was Fiddlesticks Q (s230). Everything else the pair scanner finds is already correctly plain-int mapped — conditional conversion is a pure Part-1 no-op, zero ranking value until a Part-2 live-advisory surface consumes the downgrade (deliberately not built; s229 reframed per-tick B-2 as a mis-feature for item ranking).
- All other discrete-pair hits are `target_max_hp_pct` — NOT the `target_full_hp` execute semantic (max-HP scaling is a flat fraction of the health bar, not HP-gated) and already mapped-correctly.

This is the s227 situation for the conditional vein: the autonomous pure-data DS work is mined out; the high-ROI remaining DS work is Part-2 (live target-state plumbing) — architectural, wants sign-off, NOT autonomous.

## Shipped (committed) — NO registry/engine change, ENGINE stays 1.3.0

- `tools/ds_execute_prefilter.py` (new, kept) + `tools/ds_cond_pair_prefilter.py` (s231, kept) — the durable per-patch saturation tools.
- New `test_conditional_block_index_s232_saturation.py` (8 tests) — the s223-style **machine-checked saturation guard**: `MissingHpExecuteVeinSaturationGuard.test_no_unaccounted_clean_execute_pair` enumerates EVERY same-shape monotone-execute-coeff block pair across all 171 champs and asserts each (champ,key) is accounted-for (already-conditional / engine-default-block-0-correct / documented-skip). A future Meraki re-extract that introduces a genuinely-new clean execute candidate **trips this test** = the signal to revisit. Plus vocab-stays-2, all-10-shipped-conditionals-intact, registry-still-125, and an **ENGINE-UNCHANGED** pin (1.3.0 — there is nothing behavioral to version; do NOT bump for a docs/tooling/guard commit).
- **No ENGINE bump, no DS restart, no stale-pin migrations** (nothing behavioral changed). DS suite 2247→**2255** (+8 guard tests); ruff+py_compile clean.

## Don't-redo / blockers

- **The autonomous pure-data conditional-seed-expansion vein is CONCLUDED** (operator decision). Do NOT re-run `ds_cond_pair_prefilter.py` / `ds_execute_prefilter.py` expecting yield, and do NOT ship no-op plain-int→conditional conversions to look busy — they add zero ranking value (Part-1 always resolves to default == the prior int) until Part-2 exists. The saturation guard is the tripwire if a patch re-extract genuinely changes this.
- **Don't bump ENGINE_VERSION for pure docs/tooling/guard commits.** s232 deliberately stays 1.3.0; the s232 test pins it unchanged. ENGINE tracks engine/registry *behavior*.
- The 10 shipped conditionals (s228-s231) are all **Part-1 no-ops by design** — they resolve to `"default"` == their prior int/list. Their value is latent until Part-2. Don't "fix" the no-op.

## NEXT (operator decision required — not autonomous)

The high-ROI remaining DS investment is **Part-2: live target-state plumbing** (thread liveclient target HP%/CC into the ranking call so the 10 shipped conditional downgrade branches actually fire). It is architectural and wants explicit sign-off — and note s229's open question stands: the literal per-tick "B-2" was reframed as a *mis-feature for item-ranking* (would flicker build recs), so Part-2 would need to be a **separate live-advisory product surface**, not item-build wiring. That scoping decision is the real blocker. Other non-DS directions also pending: the s220 aggregator G Post-Game-Review UI reframe (the big non-engine item, flagged ~12 sessions). DrMundo E still needs a `caster_low_hp` vocab decision if caster-state conditionals are ever wanted. Recommend the next "continue" be an explicit operator choice among {Part-2 scoping, s220 UI reframe, other} rather than more autonomous DS pure-data (that vein is provably empty).

---

# s231 wrap — 2026-05-16 (DS Phase 5.9.31: conditional seed-expansion — EXECUTE family: Evelynn R + KogMaw R)

**Operator instruction:** "Continue ds" (self-continuing loop). Continued the s230 NEXT bucket: more debuff-state-family conditional amps. NO vocab change (s227 "don't over-build" — both entries reuse the existing `target_full_hp` term, extending the s228 Kindred E execute pattern).

## What happened — built a reusable pre-filter, found the execute vein

Built `tools/ds_cond_pair_prefilter.py` (kept, reusable per-patch) — scans all 171 champions for the discrete amped/un-amped pair signature (same-shape damage blocks where B_hi = constant k×B_lo). Found 280 hits but most are channel/multi-hit totals already correctly mapped as plain ints (the s193/s198 pattern, NOT target-state conditionals). The genuine untapped vein: **the EXECUTE family** (`target_full_hp` vocab, the Kindred-E s228 shape) — champions whose R deals a clean discrete multiple more to sub-threshold-HP targets, currently mapped as a plain int to the execute block. Verified each by hand (rigor bar).

## Shipped (committed)

- **Evelynn R "Last Caress"** int `1` → `{default:1, target_full_hp:0}` — Meraki block 1 = EXACTLY **2.4×** block 0 every rank (base 125→300, ap 75→180); the bonus-vs-sub-30%-max-HP execute. TWO discrete Meraki blocks (clean amped/un-amped pair), NOT a continuous in-block missing-HP coefficient — the precise distinction that rejected Bel'Veth R. `default`=1 (the execute, operator-commits canonical, s191 model — same as Kindred E s228); `target_full_hp`=0 (un-amped downgrade when target above threshold, Part-2's signal). Evelynn's s228 sibling Q `{default:5,target_no_setup:0}` preserved through the dict-merge. Live A/B :8893 /burst lvl11 80/30/2000: registry **1220.34** == forced{R:1} == cond-dict (provable Part-1 no-op); forced{R:0} **951.11** (load-bearing downgrade).
- **KogMaw R "Living Artillery"** int `1` → `{default:1, target_full_hp:0}` — Meraki block 1 = EXACTLY **2.0×** block 0 (base/bonus_ad/ap all 2×); the double-damage-vs-low-HP execute. Live A/B: registry **640.68** == forced{R:1} == cond-dict; forced{R:0} **532.99**.
- Both provable Part-1 no-op (default == prior int 1, byte-identical; default == s204 Evelynn / s196 KogMaw). Registry stays **125 champions** (both converted in-place). `_meta` appended via surgical str.replace. New `test_conditional_block_index_s231.py` (15 tests) + 11 ENGINE pin bumps + 9 stale-pin migrations (Evelynn/KogMaw R shape pins in test_block_index_overrides ×5, s228 ×2, s229 ×1, s226 form/block-compose ×1). **Caught + migrated a latent s230 stale pin:** `ServerRouteSourceTests.test_ability_dps_champion_source` asserted the pre-s230 Cassi E int shape — it's a *live-server* test and s230 only re-ran phase8_smoke post-restart (not the full suite), so it had been silently stale since s230; now asserts the s230 conditional shape. ENGINE **1.2.0→1.3.0**. DS suite 2232→**2247**; wider RC **1107**; ruff+py_compile clean; DS restarted (taskkill 3724 → pythonw relaunch, not supervisor-watched) → `/health` **1.3.0**.

## Don't-redo / blockers

- **Veigar R stays the deferred non-converted exemplar.** It IS a clean 2.0× execute (verified: block0 base[175,250,325]ap[65,70,75] → block1 exactly 2.0×) but it's the canonical stable-int test fixture (s229 _meta: "pick non-fixture executes" — s231 did exactly that with Evelynn/KogMaw). Converting Veigar R cascades fixture repoints across test_sum_of_blocks + test_block_index_overrides GetBlockIndexFor/ResolveBlockIndex/known_champion_overrides — only do it as a deliberate, independently-scoped fixture migration, NOT as part of a pure-data batch.
- **Akali R/R2 NOT a conditional candidate to touch.** Its execute lives in the s192 token-variant special case ({R:0, R2:2}) carefully scoped to avoid double-counting R1 in the combo registry — layering a conditional on top is high-risk. Leave it.
- **post-restart full-suite check matters.** The s230→s231 latent stale pin (ServerRouteSourceTests) proves: live-server tests must be re-run against the *restarted* server, not just phase8_smoke. s231 re-verified live A/B post-restart and the migrated pin will pass against 1.3.0 (Cassi E shape unchanged s230→s231).
- Conversions are intentionally zero-numeric-change (Part-1 resolves to `"default"` == the prior int); don't "fix" the no-op.

## NEXT (self-continuing loop)

The execute (`target_full_hp`) vein has Evelynn R + KogMaw R shipped; remaining clean executes are scarce (Veigar R deferred-fixture; most other "2× vs low HP" hits are already plain-int mapped-correctly and converting adds no value without a real downgrade consumer). Next candidates need fresh Meraki verification each (the s229/s230/s231 lesson: ROADMAP/_meta recollection mis-names mechanics ~half the time — `tools/ds_cond_pair_prefilter.py` + `tools/ds_cond_inspect.py` are the durable rigor tools). Remaining `target_no_setup` debuff-amp candidates are mostly already-correctly-mapped plain ints; the conditional-conversion ROI is now low (each adds value only if a future Part-2 live-advisory surface consumes the downgrade). Consider flagging to the operator that the autonomous conditional-seed-expansion vein is approaching exhaustion (like the s223-227 pure-data sweep did) — the high-ROI remaining DS work may be Part-2 (live target-state plumbing) which is architectural and wants sign-off. DrMundo E still blocked on a `caster_low_hp` vocab decision. s220 aggregator G Post-Game-Review reframe remains the big pending UI item.
