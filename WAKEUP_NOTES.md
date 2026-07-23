# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-23e - patch-impact aggregator + route + Session card (+ the flagged ds_shaper red)

Three commits (all pushed): `ff77164f` `ad99cec7` `86b40fe7` + LEDGER 1009.
ENGINE-IMPACT NONE (aggregator + route + asset layer; no DS bump, no :8893 bounce, no Share).

- **ds_shaper red closed first** `ff77164f`: the 5/6 failure was the test file's own
  FakeEl shim missing `setAttribute` (prod `renderShaperStrip` marks the strip
  `[data-rc-zone]` for the overlay clickthrough zones). Added the attribute trio +
  a regression assert on `data-rc-zone`. 6/6. The task chip can be dismissed.
- **NEW `core/patch_impact.py`** `ad99cec7` (Haiku-to-ZERO sibling; closes the BACKLOG
  "patch-diff what changed for YOUR champs" tail): RM-110 cross-patch DS snapshot diff
  x the player's own rewind play counts. `_open_ro` + injectable `diff_fn`/`patches`/
  `key_map`, laplace winrate, never-raises with a stated reason. Join is on
  `champions.json` `key` (numeric), NOT the display name; item changes attribute only
  when the item is in that champ's build order for the mode. 29 tests.
- **NEW `/api/patch-impact`** same commit: `?mode&top&min_games&old&new`, 5min cache,
  structured 400/500, patch names gated on the ON-DISK allowlist (`ds_patch_diff._resolve`
  takes any existing dir - never hand it the raw query). 16 tests.
- **NEW Session `#patch-impact-card`** `86b40fe7` (`web/js/panels/patch_impact.js` + .css,
  21 tests): per-champ stat/ability/build/item chips, detail in tooltips, `-` sentinel on
  a no-change champ (no reflow). Descriptive-only is TEST-PINNED (no buff/nerf wording).
  5-phase audit PASS, zero MUST-FIX.
- Live: 16.13.1 -> 16.14.1 over 2044 ARAM matches in 76ms; the 8 changed items are Arena
  mirrors + components + Rocketbelt, so zero ARAM-build attributions is correct.
- Doc drift corrected against git: ROADMAP RM-111 "consumer surface NOT wired" was stale
  (shipped `a626ece0`); BACKLOG `/api/personal-build` UI tail likewise already shipped.

NEXT: RM-01 (Haiku-to-ZERO Lane E CV substrate) is still the top open thread and is
live-gated - `data/fusion_shadow.jsonl` does not exist yet, so the flip gate is genuinely
unmet. Do NOT flip blind. Non-gated BACKLOG siblings left in this lane: the radar
target-profile reference polygon and the predicted roam/invade route. Premade detection
stays BLOCKED (tracked-only matches table). Do NOT touch RM-99b Heartsteel cadence.

---

# 2026-07-23d - Haiku-to-ZERO: all 3 aggregator routes wired to UI cards + scaling layer activated

Three commits (all pushed): `7c86c4fa` `6f1b6d11` `703af159` + LEDGER 1008.
ENGINE-IMPACT NONE (asset + route-layer only; no DS bump, no :8893 bounce, no Share).

- **draft-score card** `7c86c4fa` -> Champ Select `#csv-draft-score`: 42-58 score +
  HIGH/MED/LOW chip + 5-layer contributed/inert breakdown, "-" sentinel on inert.
  SR-draft-only, hidden until 5 ally committed. NEW `web/js/panels/draft_score.js`
  (+ .css, 12 tests). 5-phase audit caught+fixed a flex horizontal-overflow MUST-FIX.
- **session-hygiene + playstyle cards** `6f1b6d11` -> Session view: NEW
  `session_hygiene.js` (`#session-hygiene-card` "SHOULD I QUEUE" 0-100 readiness +
  signed factor nudges + 8-bar tilt strip, 10 tests) + `playstyle_labels.js`
  (`#playstyle-labels-card` labeled-only champs, top-12 + "+N more", 9 tests). Both
  self-fetch on the session view switch (`main.js`). 5-phase audit PASS both.
- **scaling layer activated** `703af159`: `routes_draft_score._SpikeScalingResolver`
  derives per-champ power-timing 0..1 by reusing `routes_spike_curve._build_champ_curve`
  + the 70%-crossing minute (pure `_peak_timing` helper). Layer now CONTRIBUTES
  (live: contributing 4->5, scaling sub 0.65, score 55.5). 10 route tests. Cold
  1518ms / warm 0ms / 24h per-champ curve cache. All 5 draft-score layers now live.
- Verified: ruff clean, hygiene 13, py 42, node 31 green; RC pid 21616 alive+reload_ok.

NEXT: nothing pending on the Haiku-to-ZERO aggregator lane (BACKLOG lines 56-57
consumer surfaces DONE). Premade detection stays BLOCKED (tracked-only matches
table). Pre-existing `ds_shaper.test.mjs` red (5/6, unrelated) flagged as a chip.
Do NOT touch RM-99b Heartsteel cadence (operator-gated).

---

# 2026-07-23c - Haiku-to-ZERO: five-layer deterministic draft score aggregator + route

Commit pending push. ENGINE-IMPACT NONE (no DS bump, no :8893 bounce, no Share touch). LEDGER 1007.

- **NEW `core/draft_score.py`** (Haiku-to-ZERO sibling of session_hygiene / playstyle_labels): closes
  the BACKLOG "Five-layer deterministic draft score" NOW item. ZERO API/LLM. Fuses lane-matchup 30pct /
  pairwise-synergy 20pct / AD-AP-tank damage-balance 15pct / early-late scaling 10pct / base-WR 25pct
  into ONE bounded score + HIGH/MED/LOW confidence.
- **Data sources (all owned):** matchup / synergy / base-WR from `core.draft_elo_db` (the `participants`
  table = full 10-player Match-V5 rows, DISTINCT from the tracked-only `matches` table playstyle/hygiene
  read; Laplace-smoothed via core.smoothed_rates). Damage-balance from an injectable DS kit-mix resolver
  (`core.damage_mix` with EMPTY items = kit-only physical/magical lean). Synergy nudged by item-277 101qq.
- **HONEST 42-58 band** (no-fake-spread): trust-weighted (weight x shrink(n)) mean of layer WR-deviations,
  50 + delta*100, hard-clamped [42,58]. A layer with no evidence is marked contributed=False and drops
  out of the blend - NOT dragged toward 50. Scaling layer ships INERT by design (no cheap per-champ
  power-timing primitive; declared with reserved 10pct weight, activates when a scaling_resolver is fed).
  Pure `fuse_layers()` split out DB-free for the math proof. Never-raises.
- **NEW route `/api/draft-score`** (`routes_draft_score.py`): ?ally + ?enemy + ?queue, 5min LRU cache,
  structured 400/500, wires the default DS + 101qq + name resolvers. Into `_dispatch.py` GET chain (110 routes).
- Verified: 23 aggregator/route tests + 1435 dispatch/route/draft suite green, ruff clean, RC restart
  alive+reload_ok (pid 9584), live HTTPS probe served score 54.4/MED (4 layers contributing from real
  corpus + DS kit-mix), 400 on bad-length, matchup inert with no enemy comp.

NEXT: Haiku-to-ZERO consumer/UI wiring for the three new routes (session-hygiene / playstyle-labels /
draft-score) is operator-present-preferred (do NOT build headless). Premade detection stays BLOCKED
(tracked-only matches table). Do NOT touch RM-99b Heartsteel cadence. A DS spike-derived scaling_resolver
would activate the draft-score scaling layer (future, when the operator wants it).
