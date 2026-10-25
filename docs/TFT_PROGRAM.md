# TFT program - per-round capture, TFT-centric dashboard, Augur engine

Living doc. Status: SPEC, written session 134 (2026-10-25); slices below are the
build plan for parallel agents. Engine decision: `docs/adr/ADR-018-tft-engine-separate-from-daemon-slayer.md`.
Update this file when a slice lands (section 9 change log), never a dated copy.

Operator ask (chat, 2026-10-25, paraphrased): a TFT-centric dashboard in lobby, match and
post-match; save every on-screen category for every round (composition at round start,
gold, items on units, HP, traits, every shop refresh, board hex positions, round verdict,
the enemy faced versus the player), usable for bug tests and for analysis during and
after the match; remove LLM calls; enemy profile / history digest; a movable overlay
toggle icon; and an in-game picker of prior top-4 team plans with a hover digest and the
milestone decisions the operator used on average. The comp/item engine is separate from
Daemon Slayer (ADR-018) and is provisionally named **Augur** (one constant,
`tft.engine.ENGINE_NAME`; the operator may rename it).

Built in parallel by other session-134 agents and NOT re-specified here (this program
depends on them): the overlay show/hide toggle icon (rc-shell), the lobby / opponent
scouting digest (Riot TFT API), the standalone-TFT-client P0 fix (mode detection, vision
gate, live source: `tft/tft_standalone.py`), T1 honest no-live-feed panels (landed:
`59a26f100`, `9dab16aeb`), RM-615 stage-round gate (`core/tft_stage_gate.py`), and the
LCU TFT endpoint + websocket inventory (gitignored
`ops/runtime/tft_qa/LCU_TFT_INVENTORY.md`, landed 2026-10-25; its verdicts fill the LCU
column of section 1.4).

---

## 0. Ground truth this spec is built on (measured 2026-10-25)

Recall gate: `python tools/perseus_recall.py "TFT vision round capture database"` (and
four narrower TFT queries) returned NO closed / refuted hit for per-round TFT capture.
Fences that DO bind this program:

- CLAUDE.md Settled: "the phase-driven view-router is proven correct. Do not re-pitch a
  router change" - so section 4 adds no view id and changes no transition.
- CLAUDE.md Settled: "The augment LCU / :2999 API is a confirmed dead-end; augment-OCR is
  the path" - augments here are OCR / icon reads.
- LEDGER 839: the League 2560x1440 recalibration and native-crop / colour-correction
  wiring in `core/vision_tesseract.py` are SHIPPED (do not re-pitch); wiring
  `core/screen_grab.grab_native()` into the shared relay OCR path is LIVE-GATED (a wrong
  native grab is worse than the halved frame). The TFT capture path in section 3 calls
  `grab_native` itself, foreground-gated, and does NOT change the relay.
- RM-846 / NOTICE "Teamfight Tactics": no third-party tier list, comp, augment rating or
  ladder statistic may enter the tree. Augur learns only from game data and the
  operator's own matches.

Measured facts (sources cited; the recorder dir is gitignored):

1. The game runs as the standalone Unreal client `TFTClient-Win64-Shipping.exe`;
   NOTHING listens on `:2999` (P0 probe notes, gitignored
   `ops/runtime/tft_qa/TFT_CLIENT_PROBE.md` in the P0 worktree; T1 defects
   `ops/runtime/tft_qa/T1_defects.md`). Window 2560x1440 borderless, display affinity 0,
   a GDI grab returns real frames. LCU `/help` has no in-game board / shop / gold / level
   / stage endpoint (P0 probe).
2. **Passive per-round file feed.** `%LOCALAPPDATA%\TFT\Saved\Logs\TFTEoGStats.json` is
   rewritten once per round at planning start (P0 probe; wired by the P0 slice in
   `tft/tft_standalone.py` `read_eog` / `clean_unit_name`). Shape read this session from
   the final file of match 20261025-070350: `gameId`, `queueId`, `queueType`,
   `statsBlock.gameLengthSeconds`, `statsBlock.setCoreName` (`TFTSet18`),
   `statsBlock.players[8]` each with `health`, `ffaStanding`, `isInteractable` (local
   player), `augments[]`, `boardPieces[]` of `{championName (e.g. DA_18_Yorick),
   starLevel, itemNames[] (components and emblems included), price}`, plus identity
   fields RC must never copy (PUUID, riotIdGameName, riotIdTagLine, summonerName,
   playerId, companion ids). Measured: eliminated players carry NEGATIVE health
   (overkill, -3 to -18); the winner 100; `augments` empty for all 8 players although
   augments were taken (LCU inventory: 3 taken) - so augments are vision-only; NO hex
   position and NO bench field anywhere. `championName` joins
   `data/meta/tft_set18_cdragon.json` `units[].apiName` directly.
3. **LCU inventory verdict** (`ops/runtime/tft_qa/LCU_TFT_INVENTORY.md`, GET-only, 1450
   functions / 923 events enumerated): the LCU carries NOTHING per round - every per-round
   category needs vision. Post-game it carries the final boards of all 8 players (units,
   star, cost, items; no hex positions) through two routes:
   `/lol-end-of-game/v1/tft-eog-stats` (PreEndOfGame / EndOfGame only - 404 once the
   client is back in Lobby; also pushed as an event) and
   `/lol-match-history/v1/products/tft/{puuid}/matches` (any phase, durable, MORE fields:
   level, gold_left, last_round, time_eliminated, per-player trait tiers, placement).
   EoG `health` is valid for the local player only (238-253 for non-winners here: NOT hit
   points). `total_damage_to_players` read 0 for all 8 in the sampled match (re-check; the
   sample may be atypical). Set: `/lol-game-data/assets/v1/tftsets.json`
   `mDefaultSet` in any phase, paired with the queue id because queue 6110 is a Set 17
   revival. Static set data in any phase: `tftchampions-teamplanner.json` (cost, traits,
   `team_planner_code` per champion), `tfttraits.json`, `tftitems.json` (names + icon
   paths; augments live here). Team planner read: `/lol-tft-team-planner/v1/sets/dirty`.
   The frozen client's planner routes (`lcu/lcu_client.py:470-477`, `/v1/team/local`,
   `/v1/team/import`) answer 404 and have no caller; the live write routes are under
   `/v1/sets/{set}/teams/{team}/...` (import, champions) plus `/v1/sets/{set}/team-code/{team}`,
   `/v1/team-code/clipboard/{set}` and `/v1/sets/push-to-server` - none called by the
   inventory. Available TFT queues: 1090 Normal, 1100 Ranked, 1160 Double Up, 1220, 1230
   (event queues), 6110 Set 17 revival. In-game (InProgress) LCU contents, for example
   whether `/lol-gameflow/v1/session` `teamOne` lists all 8 players, are UNVERIFIED; the
   inventory's passive listener records them in the next match
   (`ops/runtime/tft_qa/lcu_events.jsonl`).
4. **`TFT.log`** (`%LOCALAPPDATA%\TFT\Saved\Logs\`, live Unreal log): 23.6 MB / 76,233
   lines for one 34-minute match. Allowlisted signals counted this session: 55 phase
   lines (`ETFTPhaseType::` 28 CombatDeparture, 21 PlanningDeparture, 5 DraftDeparture
   (carousel), 1 Planning) with wall-clock stamps; carousel / gameplay music switches
   (11 / 13); VO cues `Unit.Purchase` 34, `Unit.StarUp` 10,
   `Army.Round.UnitCombatVictory` 27; `TFTPlannerSubsystem` "Player TeamPlanner data
   saved" 7 and "Data received" 1. Purchase VO is PARTIAL (interrupt channels block
   cues), so it is a hint, never a purchase ledger. The log also carries auth / chat /
   telemetry lines: parse by allowlist only.
5. **Frames:** 2560x1440 native; the recorder kept 80 game frames at 1280x720
   (`ops/runtime/tft_qa/20261025-070350/frames/game_*.jpg`; vision relay downscale
   `vision_server/_frame.py:71`). HUD inventory read off those frames is section 1.4.
   Observed occluders: collapsed shop, the unit inspect panel covering the scoreboard,
   a third-party media widget top-left.
6. **OCR feasibility probe** (Tesseract 5.4, psm 7, digit whitelist, 4x upscale +
   threshold, on the 1280x720 frames - no native grab): stage read 4/4 frames; gold,
   level, XP digits and the flame counter 3/3 where the shop was open; the frame with
   the shop collapsed correctly yielded no gold / level. XP lost its `/` (34/36 read as
   3436) and the timer read noisy - both need field-specific handling. The flame counter
   read 8, 11, 14, 17 at 3-2, 3-6, 4-3, 5-1 in a game the operator won with 100 HP
   throughout: consistent with a win streak, sign handling for loss streaks unverified.
7. **Existing match store is unusable for mining.** `data/match_history.db` (via
   `core/match_db.py`) holds 8,209 `mode='TFT'` rows dated 2026-04-08 .. 2026-09-11 with
   ONE distinct `game_id`, 28 distinct unit lists and 7,816 rows at placement 8 (read-only
   query this session). Augur must not train on it; the new store (section 2) is separate.
8. **Existing TFT lane** (all built on, none frozen): `tft/tft_set.py` (set resolver,
   `resolve_set` :145, `load_cdragon` :193, `roster` :214, `trait_names` :228);
   `tft/tft_roll_odds.py` (deterministic shop odds, `shop_hit_probability` :201,
   `rolls_for_confidence` :246; tables STALE until LT-02 closes); `tft/tft_ocr_reader.py`
   (Tesseract reader with 1600x900 regions :29, superseded by section 3);
   `tft/tft_state_reader.py` (`:2999` reader, `detect_variant` :127 maps mapNumber 22 to
   Double Up although the measured Normal session reports mapId 22 - variant must come
   from the queue id); `core/tft_worker.py` (`_run` :252, the TFT poll thread);
   `core/vision_template_match.py` (two-stage icon match, `_match_score` :300,
   `match_icon` :382, default-OFF, atlas dirs under tracked `data/icons/`);
   `core/screen_grab.py` (`grab_native` :108); `core/vision_tesseract.py`
   (`_scale_bbox` :156, `_preprocess` :227); `core/queue_modes.py` (TFT queues 1090 /
   1100 / 1130 at :89-91, `mode_key_from_queue_id` :127; its RM-140 note :85-88 says
   these are the only client-visible queues, which the inventory now contradicts:
   1160, 1220, 1230 and 6110 are offered too); `dashboard/_state_builder.py` (`resolve_mode_key` :216, being
   changed by P0); `lcu/lcu_client.py` (FROZEN; team planner `import_team_code` /
   `get_team_planner` / `set_team` at :470-477).
9. **LLM call sites in the TFT lane** (the "remove LLM calls" target):
   `tft/tft_coach_engine.py:770` (Haiku coaching), `tft/tft_live_analysis.py:609` /
   `:613` (comp coaching) and `:682` / `:686` (augment pick), `tft/tft_vision_reader.py:198`
   (Haiku vision extraction).

---

## 1. Per-round record schema

### 1.1 Value envelope - every measured value carries confidence and source

Every measured scalar `X` is stored as three columns: `X`, `X_conf` (REAL 0..1), `X_src`
(TEXT). List-valued entities (units, offers, traits, players) carry `conf` and `src` per
row. A value that was not observed is NULL with `X_src = 'absent'` - never 0 (memory
`feedback_no_reflow_on_data_absence`; T1 rule "producer zero defaults count as no data").

`src` enum (closed; a guard rejects anything else):

| src | meaning | conf rule |
|---|---|---|
| `eog_file` | TFTEoGStats.json per-round snapshot | 1.0 when the snapshot parsed and is for this round |
| `tft_log` | allowlisted TFT.log line | 1.0 for phase stamps; 0.6 for VO-cue hints |
| `lcu` | passive LCU GET | 1.0 |
| `riot_match_v1` | Riot TFT-Match-V1 (post-match) | 1.0 |
| `ocr` | Tesseract field read | calibrated per field from the accuracy harness (section 3.4) |
| `icon` | template match | the matcher's Pearson score, recalibrated per category |
| `geom` | board geometry (hex / bench / star-pip detection) | calibrated per field |
| `derived` | computed from other values (traits from units, verdict from HP deltas) | min of the inputs' conf |
| `llm_fallback` | Sonnet vision, only where section 3.5 allows | 0.5 cap; never an oracle |
| `manual_label` | hand / agent label in the accuracy corpus | 1.0, corpus only |
| `absent` | not observable this capture | value NULL |

### 1.2 Identity and privacy

- No Riot id, summoner name, PUUID, playerId or account id is persisted in the store,
  an export, a fixture, a log line or a doc. Players are `player_key` = first 12 hex of
  HMAC-SHA256(per-install salt, PUUID or, when absent, the display name); the salt lives
  in gitignored `data/tft/.salt`. The name-to-key join (EoG file row <-> scoreboard OCR
  <-> combat banner OCR) happens in memory only. The P0 module already carries the local
  player as the fixed token `LOCAL_NAME`; the store marks it `is_local = 1`.
- Identities for the lobby scouting digest belong to the scouting slice's own cache, not
  to this store.
- Frames contain other players' names and Riot art: they stay under gitignored
  `data/tft/frames/` and are never exported in a fixture or committed.

### 1.3 Round identity

`round_seq` (INTEGER, 1-based, monotonic within a match) is the primary round key,
advanced by phase events (TFT.log PlanningDeparture / DraftDeparture, or an EoG-file
rewrite, or a gated OCR stage change). `stage` / `round` / `label` ("3-2") are measured
values with conf/src like any other, so an OCR misread never re-keys a round (RM-615
gate `core/tft_stage_gate.py` judges each stage read). `kind` = `pvp` | `pve` |
`carousel` | `augment` | `unknown` (Set 18's schedule is unverified - LT-01 / RM-855 -
so `kind` starts `unknown` except carousel, which TFT.log marks by DraftDeparture and
music).

### 1.4 Category inventory - everything on screen, per round

LCU column: the inventory's verdict (section 0 item 3). NONE-IN-GAME means the LCU has no
per-round source; "final" names the post-game route that later serves as ground truth
(EoG = `tft-eog-stats`, MH = TFT match history).

| # | Category (operator words) | Fields | Primary source | Cross-check / fallback | LCU (inventory 2026-10-25) | Captured at |
|---|---|---|---|---|---|---|
| 1 | Round id | round_seq, stage, round, label, kind, planning / combat / end timestamps | `tft_log` phase stamps + `ocr` stage label (RM-615 gated) | `eog_file` rewrite times and gameLengthSeconds | NONE-IN-GAME; final: MH `last_round` per player | every phase |
| 2 | Player composition at round start | own board units: champion_api, star, items[], cost | `eog_file` (local row) | `icon` item row + `geom` star pips | NONE-IN-GAME; final: EoG + MH boards | planning start |
| 3 | Champion board positions on the grid | hex_row, hex_col per board unit (4 x 7 own half) | `geom` occupancy, identity assigned from row 2 (item multiset, then exemplars) | none - no file carries positions | NONE in any phase | planning end (final placement) |
| 4 | Bench | 9 slots: unit, star, items | `geom` + `icon` | `tft_log` purchase VO (partial); `eog_file` if it proves to include bench (unverified) | NONE in any phase | planning start and end |
| 5 | Gold | gold at planning start, after each shop action, at planning end | `ocr` | `derived` parity (income + interest + streak - spend) | NONE-IN-GAME; final: MH `gold_left` | planning start / end, each refresh |
| 6 | Level / XP | level, xp_cur, xp_max | `ocr` (level box, XP text) | `ocr` scoreboard level badge; monotone | NONE-IN-GAME; final: MH `level`; XP never | planning start / end |
| 7 | Player HP | own hp | `eog_file` | `ocr` scoreboard | NONE-IN-GAME; final: EoG local `health` | planning start |
| 8 | All 8 players' HP | hp, level badge, alive, standing per player | `eog_file` (all 8) | `ocr` scoreboard rows | NONE (EoG non-local `health` is not HP) | planning start |
| 9 | Traits | trait, count, tier index, active, breakpoints (own; derived for opponents) | `derived` from units + set breakpoints (`load_cdragon` traits) | `ocr` trait panel (name lexicon + count) | NONE-IN-GAME; final: MH `traits[]` tiers; static `tfttraits.json` | planning start / end |
| 10 | Shop choices at each refresh | refresh_idx, cause, 5 offers (champion or special card, cost), bought flags, gold before / after | `ocr` card name against the set roster lexicon + cost digit | `icon` portrait; `eog_file` board diff; gold delta; purchase VO | NONE in any phase | every shop refresh (change detection) |
| 11 | Shop odds | p1..p5 percent at the current level | `ocr` odds strip | `tft/tft_roll_odds.py` tables (closes LT-02) | NONE (no odds or pool table anywhere) | on level change |
| 12 | Items equipped / item bench | items per unit (board and bench), loose components on the item bench | `eog_file` (board units) | `icon` (item row over each health bar, item-bench orbs) | NONE-IN-GAME; final: EoG + MH `itemNames` | planning start / end |
| 13 | Augments | offered options, chosen | `ocr` / `icon` on the choice overlay (Settled: augment OCR is the path) | none - EoG file and LCU EoG `augments` are empty although taken | NONE (catalogue only, `tftitems.json`) | augment rounds |
| 14 | Streak | signed streak count | `ocr` flame counter | `derived` from the verdict sequence | NONE | planning start |
| 15 | Round verdict + damage | result (win / loss / draw / pve_win / pve_loss), damage_taken, damage_dealt | `derived` from own and opponent HP deltas across EoG rewrites | `tft_log` UnitCombatVictory VO; `ocr` combat banner | NONE-IN-GAME; final: MH `last_round`, `time_eliminated`; damage 0 in the sample | next planning start |
| 16 | Enemy faced + their board | opponent player_key, ghost flag, opponent units / stars / items | `ocr` combat banner name -> player_key; that player's `eog_file` row | `geom` / `icon` on the far half during combat | NONE-IN-GAME (identities in `gameflow/session` UNVERIFIED in game); final boards only | combat start |
| 17 | Enemy details versus player | power compare: unit count, star-weighted cost, completed items, active trait tiers, contested units | `derived` (Augur `compare`) | - | n/a | planning start |
| 18 | Carousel | offered units + their items, pick | `icon` | `eog_file` diff | NONE | carousel rounds |
| 19 | Other HUD numbers | timer, Buy XP cost, Reroll cost, bottom-right counter box (meaning unidentified) | `ocr` | - | NONE | planning |
| 20 | Occluders / layout | shop open, inspect panel open, scoreboard covered, overlay widgets, phase banner | layout classifier (section 3.2) | - | n/a | every capture |
| 21 | Match metadata | set, queue, variant, placement | `lcu` (`tftsets.json` `mDefaultSet` + queue id from `gameflow/session`; placement post-game) | `eog_file` `setCoreName`; MH `tft_set_number` | YES (any phase for set + queue; post-game placement) | match start / end |

Rows with NO non-vision per-round source (so CV accuracy decides them): 3, 4, 5, 6, 10,
11, 13, 14, 16 (identity of the opponent faced), 18, 19. Rows 2, 7, 8, 12 and the
opponent boards of row 16 have the per-round EoG FILE (not the LCU) as their source.

### 1.5 Tables (SQLite, schema v1)

DDL lives in `tft/rounds/schema.py` (slice TFT-01); this is the contract. `(c/s)` =
the `_conf` / `_src` sibling columns of section 1.1.

- `schema_meta(key PK, value)` - `schema_version`, `created_at`.
- `match(match_id PK TEXT, game_id INT, set_id INT, set_core_name, queue_id INT,
  queue_kind (normal / ranked / hyper_roll / double_up / other - from the queue id, never
  mapNumber), started_at REAL, ended_at REAL, placement INT (c/s), capture_profile
  (e.g. "2560x1440@ui1"), extractor_version, rc_commit, gt_status (none / partial /
  full), gt_sources (JSON list of the `gt_board.source` values present))`.
- `player(match_id, player_key, slot INT 1-8 (1 = local), is_local INT, final_standing
  INT (c/s), eliminated_round_seq INT)`; PK (match_id, player_key).
- `round(match_id, round_seq, stage (c/s), round (c/s), label, kind (c/s), planning_ts,
  combat_ts, end_ts, gold_start (c/s), gold_end (c/s), level (c/s), xp_cur (c/s), xp_max
  (c/s), hp_start (c/s), hp_end (c/s), streak (c/s), verdict (c/s), damage_taken (c/s),
  damage_dealt (c/s), opponent_key (c/s), opponent_is_ghost (c/s))`; PK (match_id,
  round_seq).
- `unit_obs(id PK, match_id, round_seq, phase (planning_start / planning_end / combat /
  carousel), player_key, zone (board / bench / carousel), hex_row, hex_col, bench_idx,
  champion_api, star, items_json, cost, conf, src, pos_conf, pos_src, frame_id)`.
- `shop_refresh(match_id, round_seq, refresh_idx, cause (round_start / reroll / locked /
  unknown), ts, gold_before, gold_after, conf, src)`; PK (match_id, round_seq,
  refresh_idx).
- `shop_offer(match_id, round_seq, refresh_idx, slot 0-4, kind (champion / special /
  empty), champion_api, name_text, cost, bought INT, bought_conf, bought_src, conf, src)`.
- `shop_odds(match_id, round_seq, level, p1, p2, p3, p4, p5, conf, src)`.
- `trait_state(match_id, round_seq, phase, player_key, trait_api, count, tier_index,
  active INT, conf, src)`.
- `augment(match_id, round_seq, pick_idx, offered_json, chosen_api, conf, src)`.
- `player_round(match_id, round_seq, player_key, hp, level_badge, alive, standing, conf,
  src)` - all 8 players.
- `event(id PK, match_id, ts, round_seq NULL, kind (phase / purchase_vo / starup_vo /
  victory_vo / planner_saved / carousel_music / eog_rewrite / capture_skip / disagreement),
  payload_json, src)`.
- `frame(frame_id PK, match_id, round_seq, phase, ts, relpath (under data/tft/frames),
  sha256, width, height, kept_reason NULL)`.
- `obs(id PK, match_id, round_seq, phase, field, value_json, conf, src,
  extractor_version, frame_id, ts)` - raw append-only evidence; the resolver (TFT-07)
  writes the typed tables above from it, so a better extractor can re-resolve history.
- `gt_board(match_id, player_key, source (lcu_eog / lcu_mh / match_v1 / eog_file_final),
  champion_api, star, items_json, cost)` and `gt_player(match_id, player_key, placement,
  level, last_round, gold_left, damage_to_players, eliminated_at)` - post-match ground
  truth (TFT-08).
- `accuracy(match_id, field, n, correct, coverage, extractor_version, computed_at)`.

---

## 2. Storage

- **Path:** `data/tft/tft_rounds.db` (already gitignored by `**/*.db`, `.gitignore:32`).
  Sibling dirs `data/tft/frames/`, `data/tft/icon_cache/`, `data/tft/exports/`,
  `data/tft/exemplars/` are NOT ignored today (`git check-ignore` measured) - TFT-01 adds
  `data/tft/` to `.gitignore` (no tracked file lives there). Note `data/icons/` is
  TRACKED (460 files), so the TFT icon cache must not go under it.
- **Engine:** stdlib `sqlite3`, WAL, `busy_timeout` 5 s, one writer thread fed by a
  bounded queue (the TFT poll thread never blocks on disk), readers open their own
  read-only connections. Forward-only migrations keyed on `schema_meta.schema_version`.
- **Writer API** (`tft/rounds/store.py`): `RoundStore.open(path=None)`;
  `begin_match(meta) -> match_id`; `record_obs(match_id, round_seq, phase, field, value,
  conf, src, frame_id=None)`; `upsert_round(match_id, round_seq, **envelopes)`;
  `put_units(...)`, `put_shop_refresh(...)`, `put_player_round(...)`,
  `put_event(...)`, `put_frame(...)`; `end_match(match_id, placement, ...)`;
  `attach_ground_truth(match_id, source, boards, players)`; `close()`. Every write is
  fail-soft (a write error logs once per streak and drops the row; it never raises into
  the poll loop - LEDGER 1309 / 1300 lessons on TFT writers that could not report failure).
- **Read API:** `list_matches(set_id=None, queue_kind=None, top4_only=False)`,
  `get_match(match_id)`, `iter_rounds(match_id)`, `live_round()` (latest round of the
  open match, for `/api/tft/live`).
- **Exports:**
  - `export_fixture(match_id, out_dir)` - scrubbed JSON for bug tests: player_key ->
    `P1`..`P8` (P1 = local), timestamps relative to match start, `game_id` replaced by a
    stable placeholder, frames dropped. Committed fixtures go to
    `tests/fixtures/tft_rounds/` only after the scrub guard passes (it fails on any key
    or value matching name / PUUID / riotId / summoner / a 36-char UUID).
  - `export_jsonl(match_ids, out)` / `export_csv(...)` for analysis into
    `data/tft/exports/` (gitignored).
  - A fixture can be served through `/api/tft/match/<id>?fixture=<name>` (TFT-09) so UI
    tests and bug reproductions drive the real panels from a recorded match.
- **Retention:** structured rows are kept indefinitely (target under 2 MB per match;
  TFT-01 measures it). Frames: keep the last 10 matches whole plus frames flagged by
  `frame.kept_reason` (disagreement / low confidence / bug evidence) for the last 50
  matches, hard cap 3 GB. Pruning is dry-run by default and, when armed, deletes through
  the Recycle Bin (FLEET item 9) only inside `data/tft/frames/` - the ADR-016 retention
  pattern (TFT-20).

---

## 3. Computer-vision pipeline (LLM-free) and how accuracy is measured

### 3.1 Source priority

`eog_file` > `tft_log` > `lcu` > `ocr` / `icon` / `geom` > `derived` > `llm_fallback`.
Files and logs are passive local reads (no injection, no network); the LCU is passive
GET only; the only write-shaped LCU calls in the whole program are the operator-clicked
planner calls of section 6.

### 3.2 Stages

0. **Clock.** Tail `TFT.log` (bounded read from the last offset, allowlisted patterns)
   for phase transitions; watch the EoG file mtime (planning start). Fallback when the
   log is unreadable: OCR stage label every 2 s through the RM-615 gate.
1. **Capture.** Only while the TFT game window is foreground and the input desktop is
   unlocked (`core/screen_grab.input_desktop_locked`; the P0 slice extends the vision
   foreground image set in `vision_server/_frame.py`). Bursts, not a stream:
   planning start +1.5 s (board, bench, shop, scoreboard); shop-region change detection
   at 4 Hz during planning on a cheap downscaled hash (each change = one refresh capture);
   planning end -1 s (final positions); combat start +2 s (opponent banner and far half);
   carousel / augment overlays when the layout classifier sees them. Text fields read
   the 1280x720 relay frame first (measured adequate, section 0 item 6); small icons and
   star pips use `core/screen_grab.grab_native` (`:108`) called from the TFT capture
   path only. Every capture skip is an `event` row with its reason. No console window
   (pythonw children use CREATE_NO_WINDOW); TFT-07 measures grab + encode cost per burst.
2. **Profile.** Regions are authored once at 2560x1440 native in tracked
   `config/tft_regions/2560x1440.json` (rectangles only, no art) and scaled to the frame
   size (`core/vision_tesseract._scale_bbox` semantics). The profile key is resolution +
   UI scale read from the client's `GameUserSettings.ini` (P0 probe: FullscreenMode=1,
   2560x1440). Another resolution needs its own profile file; until then fields read
   `absent`.
3. **Layout classifier.** Cheap colour / template checks decide which panels are visible
   (shop open, inspect panel, scoreboard, phase banner, carousel, augment choice, end
   screen). A hidden panel yields `absent`, never a guess.
4. **OCR fields** (Tesseract, per-field preprocessing via `core/vision_tesseract`
   helpers): stage label, timer, gold, level, XP (split on the bar glyph, not a `/`),
   flame counter, odds strip (5 percents), shop card names (closed vocabulary = the set
   roster from `tft/tft_set.py` `roster`, edit-distance match) and costs, scoreboard rows
   (HP digits, level badge; names matched in memory against the EoG names then dropped),
   trait panel (trait-name lexicon + count), combat banner name.
5. **Icon matching** (`core/vision_template_match.py` two-stage match, extended by TFT-05
   with an optional atlas directory so the TFT categories come from the gitignored cache
   of section 3.6): item icons in the row above each unit's health bar, item-bench orbs,
   augment icons, shop portraits as a fallback to name OCR.
6. **Board geometry.** Hex-centre maps for the own 4 x 7 half, the opponent half and the
   9 bench slots, calibrated per profile from corpus frames. Occupancy = health-bar
   anchor nearest a hex centre; star = pip count over the bar. Identity at a hex =
   assignment of the EoG board list (row 2) to occupied hexes, first by exact item
   multiset, then by cost / star, then (TFT-18) by learned per-champion appearance
   exemplars. Unresolved duplicates stay a candidate set with conf < 1.
7. **Fusion / resolver** (TFT-07): pick the highest-priority source at or above the
   field gate; cross-checks write `disagreement` events and keep the frame:
   gold parity across a round, HP non-increasing, level / XP monotone, offer cost equals
   the unit's cost, bought offers match the EoG board diff, opponent board equals that
   player's EoG row.
8. **Write** through the store API (section 2).

### 3.3 Per-field extraction summary

| Field | Method | Validation |
|---|---|---|
| stage / round | OCR digit-dash, RM-615 gate | TFT.log phase count; EoG rewrite count |
| gold | OCR digits | parity model; never negative |
| level / XP | OCR; XP split at the bar glyph | level 1-10; xp_cur <= xp_max |
| streak | OCR flame counter (+ icon variant for sign) | verdict sequence |
| odds | OCR 5 percents | sum = 100 +- 1 |
| shop offers | name OCR vs roster lexicon + cost digit | cost = unit_costs[unit] |
| own board identity / stars / items | EoG file | icon + geom per round (accuracy oracle) |
| positions | geom + assignment | count = EoG board size |
| bench | geom + icon | purchases / sells reconcile |
| traits | derived from units + breakpoints | OCR trait panel |
| all-8 HP | EoG file | OCR scoreboard |
| verdict / damage | HP deltas | victory VO; streak |
| opponent faced | OCR banner name -> key | the HP delta lands on that player (not on a ghost) |
| augments | OCR / icon on the overlay | EoG augments[] when non-empty |

### 3.4 Accuracy measurement

Four oracles, from strongest to weakest:

- **A. Per-round file oracle.** Each EoG rewrite is ground truth for all 8 boards (units,
  stars, items) and HP at that round, so the vision board path (identity, stars, item
  multisets, opponent board on combat) is scored EVERY round of every match, not just at
  the end.
- **B. Post-match oracle.** LCU `tft-eog-stats` (final boards, placement; must be read
  inside the post-game window or caught from its event) merged with LCU TFT match history
  (durable, any phase: units / tier / itemNames, per-player trait tiers, level,
  gold_left, last_round, placement), with Riot TFT-Match-V1 only as the route for history
  older than the LCU's window. Compared with the last resolved round: final boards of all
  8, final level, final gold, placement (TFT-08). Neither LCU route carries augments or a
  usable damage figure (section 0 item 3).
- **C. Labelled frames.** `tests/fixtures/tft_cv/labels_20261025-070350.json` (scrubbed:
  players as P1..P8) labels the fields with no file oracle - gold, level, XP, stage,
  timer, streak, odds, shop offers, trait panel, scoreboard HP - for the recorded corpus.
  Frames stay local; the corpus test skips when they are absent. Labels are authored by
  one agent and verified by a second (the producer never grades its own labels).
- **D. Self-consistency** (no oracle): the resolver cross-checks of 3.2 step 7, counted
  per match.

Metrics per field: accuracy (exact match), coverage (rounds with a value at or above
the gate), calibration (accuracy per conf bin). Gates: **SHOW** a field plainly when
corpus accuracy >= 0.98 AND live accuracy >= 0.95 over 3 matches; **MARK** it with `?`
below that; **HIDE** it when coverage < 0.5. Tool: `tools/tft_cv_accuracy.py --corpus
<dir> --labels <json>` prints the per-field table; per-match rows land in the `accuracy`
table and show on the post-match view, which doubles as the bug-test entry point.

### 3.5 Sonnet fallback policy

Off by default. Enabled per field only when (i) deterministic coverage is below 0.9 on
the corpus AND (ii) an A/B on the labelled corpus shows a measured gain; capped calls per
match; results tagged `llm_fallback` (conf cap 0.5) and never used as an oracle. Raw API
errors never reach a panel (CLAUDE.md error-handling rule).

### 3.6 Icons and the licence gate (verdict)

- **Sources, in order:** (1) the League client's own local `lol-game-data` assets over
  the LCU (`tftchampions-teamplanner.json`, `tftitems.json`, `tfttraits.json` carry icon
  paths, and the EoG documents already cite `/lol-game-data/assets/ASSETS/...` icon
  paths) - local, no internet, exactly the running client's art; (2) CommunityDragon
  (`raw.communitydragon.org`) when the client is not running. The tracked reduced extract
  `data/meta/tft_set18_cdragon.json` carries no icon paths (measured), so a CDragon fetch
  resolves them from the raw `cdragon/tft/en_us.json`.
- **Licence verdict: DO-NOT-VENDOR.** Both are Riot art: CommunityDragon publishes no
  licence and mirrors Riot game files (NOTICE "CommunityDragon (CDragon)";
  `scripts/fetch_cdragon_tft.py` header), and the LCU assets are Riot's client files. RC
  is PUBLIC Apache-2.0. Icons are cached at runtime into gitignored
  `data/tft/icon_cache/<set>/<category>/` with an index of apiName -> file + sha256, used
  locally only, never committed, never exported in a fixture. NOTICE gains one line
  saying so (TFT-03).
- The tracked `data/icons/` tree (460 files, League art) is pre-existing and out of this
  program's scope; the TFT program adds nothing to it.
- No other third-party payload is lifted. Anything else proposed later runs the CLAUDE.md
  licence gate first.

---

## 4. TFT-centric dashboard views and the mode rule

### 4.1 The rule (no router change)

The view router (`web/js/main.js` `_viewAutoDerive`, Python mirror
`dashboard/view_router_state.py`, `IN_GAME_MODES` already includes `tft` at :47) is
Settled and stays untouched: no new view id, no new transition. TFT-centric means the
SAME views (`lobby`, `active-match`, `last-match`) swap their pane set when the server
says the context is TFT.

One server-side authority, `state.tft_context` on `/api/state` (TFT-09, in
`dashboard/_state_builder.py` after the P0 change to that file lands):

```
tft_context = {
  "active": bool,
  "phase": "lobby" | "match" | "post" | null,
  "queue_id": int | null,
  "source": "mode_key" | "lcu_queue" | "standalone" | "last_match"
}
```

- `match`: `mode_key == "tft"` (P0 keeps it through an RC restart mid-match, T1 B1) or
  the P0 standalone verdict says a TFT game is running.
- `lobby`: LCU lobby / champ-select queue id maps to `tft` via
  `core/queue_modes.mode_key_from_queue_id` (:127). The map holds only 1090 / 1100 /
  1130 today; TFT-09 adds the queues the client measurably offers (1160 Double Up, 1220,
  1230, 6110 Set 17 revival) with a test, recording that the RM-140 "only three
  client-visible queues" note (:85-88) was reversed by the 2026-10-25 inventory.
- `post`: phase in EndOfGame / PreEndOfGame / WaitingForStats right after a TFT match, or
  the last-match view is showing a TFT match from the store.

The JS side reads `state.tft_context` only (no second queue table in JS). Panes mount
their own root inside the existing view container, so `web/index.html` is not edited.

### 4.2 LOBBY (TFT queue)

Scouting digest of the lobby / opponents (built by the parallel scouting slice; this
program only mounts it), Augur "your top-4 comps this set" list (same data as the
picker, section 6), the operator's recent TFT placements trend from the store, current
set and patch line. League lobby panes unchanged.

### 4.3 IN-MATCH

- Header strip: label + kind, timer, phase, gold, level + XP bar, HP, streak (each with
  a `?` mark below its gate).
- Board: 4 x 7 hex grid of unit chips (name, star, item icons served from the local cache
  via `/api/tft/icon/...`), bench row of 9, item bench.
- Shop: the 5 offers of the latest refresh with cost, "fits target comp" flag, and hit
  odds for wanted units (`tft/tft_roll_odds.py` `shop_hit_probability`, with pool counts
  reduced by every board in the EoG file = contested copies; marked STALE until LT-02).
- Econ curve: gold / level / HP per round_seq, roll-down and level-up markers.
- Opponents table: 8 rows by HP - HP sparkline, level, last-seen board summary (top
  traits, carry + items), contested units versus mine, last result against them.
- Round log: verdict and damage per round; capture health (source + conf per field).
- T1's honest no-feed state remains the fallback when `/api/tft/live` has no fresh round.

### 4.4 POST-MATCH

Placement, queue, set; round timeline of verdict chips; econ curve with milestone
markers; final boards of all 8 from ground truth; the Augur comp label assigned to the
operator's board; the operator's milestones in this match versus their own top-4 average
for that comp; per-field CV accuracy for the match; "export fixture" (writes the scrubbed
fixture under `data/tft/exports/`; committing it is a separate, deliberate act).

---

## 5. Augur engine scope (ADR-018)

Package `tft/engine/`: `ENGINE_NAME = "Augur"` and `ENGINE_SCHEMA` in `__init__.py`,
pure stdlib functions, deterministic, no network, no LLM, no import of
`agents/daemon_slayer`.

Inputs: set data through `tft/tft_set.py` (units, costs, traits + breakpoints, item
recipes from the extract's `items[].composition`); the round store; the operator's own
final boards from LCU TFT match history (any phase, durable; read by TFT-08) and, for
older history, Riot TFT-Match-V1 via the scouting slice's helper - final boards only, no
per-round data. The running set is `tftsets.json` `mDefaultSet` unless the queue says
otherwise (6110 = Set 17), confirmed post-game by match history `tft_set_number`.

Outputs:

1. **Comp catalogue** (cold-startable from LCU match history): deterministic clustering of
   the operator's final boards in the resolved set by active-trait signature and unit
   Jaccard. Per comp: stable id (hash of core units), label (top two traits + carry),
   games, average placement, top-4 rate, core units (in >= 70% of its games), flex units,
   carry (most-itemized unit) with its most common completed-item sets, augments when the
   set has them.
2. **Milestones** (needs per-round history, so it grows as the operator plays; Match-V1
   has no rounds): per comp, over the operator's TOP-4 matches only, median and IQR of
   the round at which level 4..9 was reached; first roll-down (a round with >= 3 rerolls
   or >= 20 gold spent on rerolls); first completed-item slam; gold at 3-2 and 4-1; HP at
   4-1; when key units hit 2 and 3 stars. These are the "milestone decisions used on
   average" the picker shows.
3. **Live recommendations:** nearest comps to the current board + bench + held items;
   shop picks (an offer that advances a target comp's core or a star-up, with hit odds);
   item slams (held components -> completable items ranked by the catalogue's frequency
   on the target carry); level / roll advice against the operator's own milestone for
   that comp ("Lv5 at 3-2; your top-4 median is Lv6 at 3-2"), roll depth via
   `rolls_for_confidence`.
4. **Board compare** (category 17): own versus the opponent faced, and versus each
   opponent's last-seen board.

Non-goals: third-party tier lists or meta comps (RM-846); fight simulation (would reopen
ADR-018 alternative 2); any LLM. Augur plus the CV pipeline replace the LLM call sites of
section 0 item 9, which go default-OFF only after measured parity (TFT-16).

---

## 6. In-game prior-top-4 team-planner picker

- **Surface:** the rc-shell overlay page (`rc-shell/src/overlay_state.js` `overlayUrl`
  :177 loads the dashboard with `?overlay=1`). The picker button and list are
  `[data-rc-zone]` controls (`rc-shell/src/clickthrough_zones.js` generic opt-in), so
  they take clicks without the ACTIVE hotkey while the rest of the HUD stays
  click-through. It hides with the overlay toggle icon (parallel slice). Prerequisite:
  the overlay appears in TFT at all (T1 F4 / P0 standalone summary).
- **Choice list:** up to 8 rows from the Augur catalogue for the current set, top-4
  matches only. Each row: comp label, "N games, avg X.X, top-4 Y%", core-unit icons
  (cost-coloured border), carry item icons.
- **Hover digest tooltip** (<= 6 short lines, readable at a glance): core units and
  3-star targets; carry + item set; milestones ("Lv6 by 3-2, Lv8 by 4-2, roll at 4-1 to
  ~20g, first slam 2-5" - the operator's own medians); usual opener by stage 2; live
  contest count = core units currently on other boards (from the EoG file's 8 boards).
- **Click to apply - two paths:**
  - **A. Copy (default, no LCU mutation).** The click handler writes a planner code to the
    clipboard (`navigator.clipboard.writeText` inside the user gesture). The code format
    is UNMEASURED: TFT-15 derives it offline if it can (inputs on hand: the per-champion
    `team_planner_code` in the LCU's `tftchampions-teamplanner.json`, the tracked
    `data/meta/tft_set18_champion_codes.json`). If no offline encoder can be derived, the
    click instead asks the client for the code (`POST
    /lol-tft-team-planner/v1/sets/{set}/team-code/{team}` or `/v1/team-code/clipboard/{set}`,
    write-shaped calls, so they follow path B's explicit-click rule), and as a last resort
    path A copies a plain unit list.
  - **B. Apply to planner (mutating LCU call, explicit click only).** Click, then a
    confirm click within 3 s; the server keeps the arm / confirm state (pattern of
    `dashboard/_arm_confirm.py`), then writes one team through the LIVE routes under
    `/lol-tft-team-planner/v1/sets/{set}/teams/{team}/...` (import or champions), reading
    current teams from `/v1/sets/dirty` first so an existing team is never overwritten
    silently. The frozen client's planner methods (`lcu/lcu_client.py:470-477`:
    `import_team_code`, `get_team_planner`, `set_team`) target routes that answer 404 and
    have no caller; the operator granted frozen-file edits for session 134 ("global
    frozen edit allowed", chat 2026-10-25: minimal edit + test + verifier + a
    commit-message note), so TFT-14 repoints those three methods to the live routes. If
    TFT-14 runs in a later session, it re-confirms the grant first or puts the calls in a
    new non-frozen module instead. Never automatic, never on hover, never from a headless
    run; every apply is logged with the comp id. Whether a mid-match LCU planner write
    reaches the in-game planner is UNMEASURED (TFT.log shows the in-game planner subsystem
    receiving data once per match; `/v1/sets/push-to-server` may be the step that makes it
    visible); if TFT-15 finds it does not propagate, path B is offered in the lobby only
    and the in-game overlay offers path A.
- Vanguard-safe: no input injection into the game window and no memory read; clipboard
  and LCU only.

---

## 7. Slice list (execution order)

Legend: OFFLINE = buildable and verifiable from recorded evidence, fixtures and synthetic
data; LIVE = needs a real TFT lobby or match to close (the build may start offline).
Tier per CLAUDE.md (no slice touches DS or `ENGINE_VERSION`; the only frozen file touched
is `lcu/lcu_client.py` in TFT-14, under the operator's session-134 grant). File sets are
disjoint within a wave; "after X" means rebase on X's merge.

**Can start NOW in parallel (wave 0):** TFT-01, TFT-02, TFT-03, TFT-04, TFT-06, TFT-13,
plus TFT-15 whenever the operator is in a TFT lobby / match. TFT-02 must rebase onto the
P0 merge and import `tft/tft_standalone.py` helpers rather than re-implement them.

| Id | One-line acceptance | Files (disjoint set) | Gate | Deps | Tier |
|---|---|---|---|---|---|
| TFT-01 | Schema v1 creates every section 1.5 table; a synthetic 30-round match round-trips through the writer / read API; scrubbed fixture export passes the no-identity guard; `data/tft/` ignored (`git check-ignore`) | `tft/rounds/__init__.py`, `tft/rounds/schema.py`, `tft/rounds/store.py`, `tests/test_tft_rounds_store.py`, `.gitignore` | OFFLINE | none | 1 |
| TFT-02 | From synthetic EoG snapshots and a synthetic TFT.log excerpt, emits per-round obs for all 8 players (HP, standing, board units / star / items) and phase / VO events with timestamps; copies no identity key (guard enumerates them); log tail is bounded and allowlist-only | `tft/sources/__init__.py`, `tft/sources/eog_file.py`, `tft/sources/tft_log.py`, `tests/test_tft_sources_eog_file.py`, `tests/test_tft_sources_tft_log.py`, `tests/fixtures/tft_sources/` | OFFLINE | P0 merge (import its helpers) | 1 |
| TFT-03 | `scripts/fetch_tft_icons.py --set 18` fills the gitignored icon cache with an index, from the LCU-local `lol-game-data` assets first and CommunityDragon second; offline-safe, rate-limited, passive GET only; guard: no tracked file under `data/tft/` and no new tracked png under `tft/`; NOTICE line added | `tft/assets/__init__.py`, `tft/assets/icon_cache.py`, `scripts/fetch_tft_icons.py`, `tests/test_tft_icon_cache.py`, `NOTICE` | OFFLINE | none | 1 |
| TFT-04 | Region map at 2560x1440 + scaling; `ocr_fields` reads stage, timer, gold, level, XP, streak, odds, shop names + costs, scoreboard HP, trait panel; layout classifier yields absent for hidden panels; per-field accuracy on the TFT-06 labels reported; unit tests run without Tesseract via a seam | `tft/cv/__init__.py`, `tft/cv/profile.py`, `tft/cv/ocr_fields.py`, `tft/cv/layout.py`, `config/tft_regions/2560x1440.json`, `tests/test_tft_cv_ocr_fields.py` | OFFLINE (corpus) | none (labels from TFT-06 for the accuracy number) | 1 |
| TFT-06 | Scrubbed labels for >= 40 of the 80 corpus frames, authored by one agent and verified by another; `tools/tft_cv_accuracy.py` prints per-field accuracy / coverage, skips cleanly without the local corpus; harness test on a synthetic mini corpus | `tools/tft_cv_accuracy.py`, `tests/fixtures/tft_cv/labels_20261025-070350.json`, `tests/test_tft_cv_accuracy_harness.py` | OFFLINE | none | 1 |
| TFT-13 | `tft/engine` with `ENGINE_NAME = "Augur"` in exactly one source file (guard) and no `agents.daemon_slayer` import (guard); comp catalogue, milestones, recommendations and board compare deterministic on synthetic history; reads no third-party data | `tft/engine/__init__.py`, `tft/engine/comps.py`, `tft/engine/milestones.py`, `tft/engine/recommend.py`, `tft/engine/compare.py`, `tests/test_tft_engine_*.py` | OFFLINE | none (switch to the TFT-01 read API and TFT-08 `final_boards` at merge) | 1 |
| TFT-15 | Probe notes `ops/runtime/tft_qa/PLANNER_PROBE.md`: team-code format from `team_planner_code` values (encoder spec or "no offline encoder"), and whether a mid-match write to the live `/v1/sets/{set}/teams/{team}` routes (with or without `push-to-server`) reaches the in-game planner; any planner write only with the operator present | gitignored notes only (no tracked file) | LIVE | operator in a TFT lobby + match | 0 |
| TFT-05 | Hex-centre maps (own half, far half, bench) calibrated from the corpus; occupancy + star from health-bar / pip detection; item-row icons matched through an additive atlas-dir option on the shared matcher (existing callers unchanged); per-round accuracy versus EoG boards reported | `tft/cv/board.py`, `tft/cv/icons.py`, `core/vision_template_match.py`, `tests/test_tft_cv_board.py`, `tests/test_tft_cv_icons.py` | OFFLINE then LIVE | after TFT-03, TFT-04 | 1 |
| TFT-09 | `GET /api/tft/live`, `/api/tft/matches`, `/api/tft/match/<id>` (+ `?fixture=`), `/api/tft/icon/<cat>/<api>` (404 when not cached), `POST /api/tft/match/<id>/export`; `/api/state.tft_context` per section 4.1; the measured TFT queues (1160, 1220, 1230, 6110) map to `tft`; route tests on a fixture store; no raw upstream error surfaced | `dashboard/routes_tft.py`, `dashboard/_dispatch.py`, `dashboard/_state_builder.py`, `core/queue_modes.py`, `tests/test_routes_tft.py`, `tests/test_tft_context.py` | OFFLINE | after TFT-01 and the P0 merge | 1 |
| TFT-20 | Frame retention per section 2: dry-run default, Recycle-Bin deletes when armed, only inside `data/tft/frames/`, caps enforced | `tft/rounds/retention.py`, `tests/test_tft_rounds_retention.py` | OFFLINE | after TFT-01 | 1 |
| TFT-08 | On the recorded LCU EoG JSON and a scrubbed match-history fixture, merges EoG (read inside the post-game window or from its event) with LCU TFT match history (durable) into `gt_*` rows plus per-field accuracy; exposes `final_boards(set_id)` for the Augur catalogue; passive GET only; closes BACKLOG RM-616 | `tft/rounds/ground_truth.py`, `tft/rounds/accuracy.py`, `tests/test_tft_ground_truth.py` | OFFLINE then LIVE (one real match end to end) | after TFT-01; Riot TFT-Match-V1 (older history) via the scouting slice's helper, optional | 1 |
| TFT-07 | Replaying the corpus + synthetic sources, the scheduler captures only at the section 3.2 moments; the resolver writes envelopes with conf / src and flags injected contradictions; `TftWorker` writes the store live without blocking its poll loop; set from `tftsets.json` + queue id, variant from queue id | `tft/capture/__init__.py`, `tft/capture/scheduler.py`, `tft/capture/resolver.py`, `core/tft_worker.py`, `tests/test_tft_capture_scheduler.py`, `tests/test_tft_capture_resolver.py` | LIVE (>= 1 match) | after TFT-01, TFT-02, TFT-04, RM-615 merge; TFT-05 optional | 1 |
| TFT-10 | In TFT context the active-match view renders header, hex board, bench, shop + odds, econ curve, opponents table, round log from `/api/tft/live`; no SR text (T1 guards green); no reflow on absence; 5-phase UI audit passes; ships `web/css/panels/tft.css` + empty per-pane CSS files and their imports | `web/js/panels/tft_match.js`, `web/js/panels/tft_match.test.mjs`, `web/js/panels/active_match.js`, `web/css/panels/tft.css`, `web/css/panels/tft_postmatch.css`, `web/css/panels/tft_lobby.css`, `web/css/panels/tft_planner.css`, `web/css/dashboard.css` | OFFLINE then LIVE | after TFT-09 | 1 |
| TFT-11 | Last-match view renders the TFT digest for a TFT match (placement, timeline, econ + milestones, 8 final boards, accuracy, export); League last-match unchanged; UI audit passes | `web/js/panels/tft_postmatch.js`, `web/js/panels/tft_postmatch.test.mjs`, `web/js/panels/last_match.js`, `web/css/panels/tft_postmatch.css` | OFFLINE | after TFT-09, TFT-10; TFT-08 for the ground-truth block | 1 |
| TFT-12 | Lobby view in a TFT queue mounts the scouting digest + Augur top-4 list; League lobby unchanged; UI audit passes | `web/js/panels/tft_lobby.js`, `web/js/panels/tft_lobby.test.mjs`, `web/js/panels/champ_select.js`, `web/css/panels/tft_lobby.css` | OFFLINE then LIVE | after TFT-09, TFT-10, TFT-13, scouting slice | 1 |
| TFT-14 | Overlay picker lists prior top-4 comps with the hover digest; Copy works inside the user gesture; Apply needs click + confirm, writes through the live `/v1/sets/{set}/teams/{team}` routes after a `/v1/sets/dirty` read, is logged, never fires without confirm (test); the three dead frozen-client planner methods repointed (operator grant, commit-message note) or replaced by a non-frozen module; hides with the overlay toggle | `web/js/panels/tft_planner_picker.js`, `web/js/panels/tft_planner_picker.test.mjs`, `web/css/panels/tft_planner.css`, `dashboard/routes_tft_planner.py`, `dashboard/_dispatch.py`, `lcu/lcu_client.py` (frozen, granted), `tests/test_routes_tft_planner.py`, `tests/test_lcu_tft_planner_routes.py` | LIVE (in-game click) | after TFT-10, TFT-13, TFT-15, overlay-toggle slice | 1 |
| TFT-17 | Odds strip recorded per level 3-9 across >= 1 match -> Set 18 tier odds pinned by a test (closes the LT-02 odds half); carousel / PvE / augment round indices recorded (closes the LT-01 RM-855 schedule half) | `tft/tft_data.py`, `tft/tft_state_reader.py` (round schedule), `tests/test_tft_set18_odds_lt02.py`, `docs/LIVE_GAME_GATED_SYNC.md` | LIVE | after TFT-04, TFT-07 | 1 |
| TFT-18 | Per-champion appearance exemplars learned from certain assignments into gitignored `data/tft/exemplars/`; position-identity accuracy for unitemized units improves on the corpus (measured before / after) | `tft/cv/exemplars.py`, `tests/test_tft_cv_exemplars.py` | OFFLINE then LIVE | after TFT-05, TFT-07 | 1 |
| TFT-16 | After 3 live matches show Augur + CV cover their fields, the TFT LLM call sites (section 0 item 9) go default-OFF behind one flag; Sonnet fallback only per field with a measured gain; Haiku calls per TFT match measure 0 by default | `tft/tft_coach_engine.py`, `tft/tft_live_analysis.py`, `tft/tft_vision_reader.py`, `tests/test_tft_llm_default_off.py` | LIVE (3 matches) | after TFT-07, TFT-13, TFT-06 numbers | 1 |
| TFT-19 | The 1600x900 OCR reader and the `:2999`-only reader dependence retired or rewired; `tft/placement_aggregator.py` replaced by store queries; no live importer of retired code; docs synced | `tft/tft_ocr_reader.py`, `tft/tft_state_reader.py`, `tft/placement_aggregator.py`, `docs/TFT_PROGRAM.md`, `docs/ARCHITECTURE.md` | OFFLINE | after TFT-16, TFT-17 | 1 |

Ordering constraints worth stating once: `dashboard/_dispatch.py` is shared by TFT-09 and
TFT-14 (serial: TFT-14 after TFT-09); `tft/tft_state_reader.py` by TFT-17 and TFT-19
(serial); `web/css/panels/tft_*.css` are created empty by TFT-10 and then owned by one
slice each.

---

## 8. Open risks and live-gated questions

1. `TFTEoGStats.json` is an undocumented client file: format or cadence can change any
   patch. Whether it lists bench units is unverified; its `augments` (like the LCU's) was
   empty although augments were taken, so augments rely on vision alone. Mitigation:
   schema check + fail-soft parse; vision-only fallback per field.
2. `TFT.log` grows ~24 MB per match and mixes in auth / chat lines; VO cues are partial.
   Allowlist parse, offset tail, never a whole-file read on the poll path.
3. Unit identity at a hex for unitemized duplicates is the hardest field; it stays
   candidate-set / partial confidence until TFT-18 measures an improvement.
4. Planner code format and mid-match planner propagation are unknown (TFT-15).
5. Riot TFT-Match-V1 entitlement on the product-app key (`core/riot_api.py:76` key note)
   is unmeasured; the scouting slice measures it. Augur no longer depends on it: LCU TFT
   match history (any phase) cold-starts the catalogue; Match-V1 only extends history
   past the LCU's window.
6. Regions are per resolution + UI scale; only 2560x1440 is authored.
7. Native grab + encode cost per burst is unmeasured (TFT-07 measures; bursts stay small).
8. Third-party overlays occlude HUD regions (observed at 5-1); the layout classifier must
   mark occluded fields absent.
9. Set churn: icons, roster lexicon and regions follow `tft/tft_set.py` resolution; Set 17
   stays playable beside Set 18.
10. `core/queue_modes.py` misses four TFT queues the client offers (1160 Double Up, 1220,
    1230, 6110 Set 17 revival), so a lobby in one of them would not read as TFT until
    TFT-09 maps them. The legacy `detect_variant` mapNumber-22 rule contradicts the
    measured Normal session (mapId 22); TFT-07 takes the variant from the queue id (Double
    Up also carries `assetMutator` TFT_PAIRS). Double Up boards and the shared-HP model
    are not specified here; a Double Up match is stored with `queue_kind = double_up` and
    its team-level fields stay `absent` until a slice specifies them.
11. The bottom-right HUD counter box (read 6 at both Lv6 and Lv8) and the flame counter's
    loss-streak rendering are unidentified; both stay `?` until labelled live.
12. In-game LCU contents are UNVERIFIED (the inventory probed Lobby and post-game only);
    its passive listener (`ops/runtime/tft_qa/lcu_events.jsonl`) answers them in the next
    match, notably whether `gameflow/session` lists all 8 players in game (a scrubbed
    opponent-identity source for row 16).
13. The LCU EoG document disappears once the client returns to Lobby; TFT-08 must read it
    in the post-game window (or from its event) and fall back to match history.

---

## 9. Change log

- 2026-10-25 (session 134): spec written; ADR-018 accepted (engine separate from DS,
  provisional name Augur). Slices TFT-01..TFT-20 filed in section 7. The LCU TFT
  inventory landed during the write and fills the section 1.4 LCU column; the operator's
  session-134 frozen-file grant is recorded for TFT-14's planner-route fix.
- 2026-10-25 (session 135): TFT-09 landed (LEDGER 1891; commit `351cded1d`):
  `dashboard/routes_tft.py` serves `/api/tft/live`, `/api/tft/matches`,
  `/api/tft/match/<id>` (+ `?fixture=`), the icon, scouting and engine routes and the POST
  export; `/api/state.tft_context` is built in `dashboard/_state_builder.py`; the engine
  recommendation is withheld while a game is live.
- 2026-10-25 (session 135): TFT-04 landed (LEDGER 1892; commit `8e473a81f`): `tft/cv/`
  reads the HUD from the 2560x1440 region profile scaled to any 16:9 frame, OCR behind a
  Tesseract seam; the live `TftOcrReader` moved onto it (QA N7: 1280x720 relay frames,
  match-3 stage 83/89 right, was 0/12); TFT-06 47-frame accuracy has 9 fields with no
  wrong answer.
- 2026-10-25 (session 135): TFT-08 landed (LEDGER 1894; commit `234c1449e`; live backfill
  LEDGER 1900): `tft/rounds/ground_truth.py` bridges the RM-616 EoG / match-history store
  into `gt_*` rows with per-field accuracy (`tft/rounds/accuracy.py`) and exposes
  `final_boards` for Augur; backfill CLI with `--eog-raw` and a byte-read-only `--dry-run`.
  The live run over 5 recorded matches wrote 562 gt_board and 25 accuracy rows; the rerun
  was unchanged.
- 2026-10-25 (session 135): TFT-02 landed (LEDGER 1895; redo of the interrupted s134
  builder): `tft/sources/eog_file.py` and `tft/sources/tft_log.py` write the per-round EoG
  file and TFT.log into the TFT-01 store (all-8 HP / standing / boards, phase / VO events,
  identity-free, bounded allowlist tail, restart-idempotent by event key); the local player
  comes only from an injected id, never `isInteractable`. Nothing calls `tft/sources` yet;
  TFT-07 wires it.
