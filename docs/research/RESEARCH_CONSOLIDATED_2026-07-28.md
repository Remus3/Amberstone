# Consolidated research QA - 2026-07-28

This file replaces the 25 `.md` files that used to live in `docs/research/`.
Those files are archived verbatim under `docs/_archive/2026-07-28-research-consolidation/`
together with the three per-file extraction reports that carry the evidence
(every `file:line`, every empty grep) behind each verdict below.

**What this doc is.** 189 actionable items were extracted from those 25 files
and each one was re-probed against today's repo before it was written down.
The QA verdict IS the deliverable - not the extraction. These docs are five to
six weeks old and most of what they call open has since shipped, so a row
marked STILL OPEN without a cited empty search would manufacture work that is
already done.

**What this doc is NOT.** It is not a tracker. `ROADMAP.md` is the one tracker
(see its "WHERE WORK LIVES" table). Rows below that deserve to become work get
an `RM-NN` id there; this file is the QA'd inventory they are drawn from.

---

## Verdict roll-up

| Group | Files | Items | SHIPPED | STILL OPEN | LIVE-GATED | REFUTED | SUPERSEDED | SETTLED | DUP |
|---|---|---|---|---|---|---|---|---|---|
| G1 RC2 research (UI/UX) | 8 | 63 | 40 | 12 | 2 | 6 | 3 | - | 2 |
| G2 RC2 specs + audits | 9 | 48 | 19 | 14 | 5 | 4 | 4 | - | 2 |
| G3 DS + competitor + OQ | 8 | 78 | 24 | 30 | 8 | 9 | 1 | 12 | 4 |
| **Total** | **25** | **189** | **83** | **56** | **15** | **19** | **8** | **12** | **8** |

**Headline: 44 pct of everything these docs left open has shipped since they
were written.** G1 alone is two thirds shipped, and all 8 of its files landed
in a single commit (`03dfb1ba`) and were never touched again - the staleness is
uniform, not per-file, which is why archiving them wholesale is safe.

---

## Corrections that change what you would otherwise build

These are the rows where acting on the doc as-written would have been wrong.
They are listed first on purpose.

1. **The `ds-meta-valuation` headline ("Ezreal HIGH divergence") is REFUTED.**
   It rests on `prefer_kit_axis_by_win` being default-OFF live. That seam was
   flipped default-ON on 2026-07-04 (`coach_integration/archetype_dispatch.py:217`,
   LEDGER 778, proven live on Ezreal) - **12 days before the doc was written**.
   The measurement came from a throwaway worktree pinned at ENGINE 1.216.0.
   That file's number-one recommendation is dead; do not action it.
2. **`docs/RC2_QA_CONSOLIDATED.md` (2026-06-20) already reconciled this same
   material once, and it has itself drifted.** Two agents working disjoint file
   sets independently found wrong rows in it - 8+ rows it calls OPEN have since
   shipped (history filters, W/L pip strip, two-tier tokens, GPI match dot, ban
   reason labels, ally AD/AP mix, session W-L header, dark-values ratchet), and
   its item 33 is graded SHIPPED against the wrong artifact. **Do not carry its
   verdicts forward unre-probed.** It is deliberately NOT archived by this pass,
   because nobody re-probed all 97 of its rows - see "Owed" at the bottom.
3. **LEDGER 767 retired `web/` + `dashboard/` as standalone visual surfaces.**
   Any row whose payoff is a 1920-Chrome-dashboard layout now targets a surface
   nobody looks at. This reprices several "open" UI rows to declined.
4. **The weekly-digest card is REFUTED, not open.** It was built (LEDGER 733)
   then deliberately removed (LEDGER 767); re-proposing it fails deletion-guard
   tests.
5. **The lobby duo-synergy "re-stage" premise is false.** The champ-select duo
   grid was deleted by item 213 and `/api/duo-synergy` has zero frontend
   consumers.
6. **`docs io RC peer/` no longer exists on disk** (Peer decommission `62be5e4c`),
   which answers the folder-reorg doc's central open question outright. Only
   dead `.gitignore` globs remain.
7. **Three of the eight G3 files carry stale engine metadata** (1.216.0 /
   1.210.0 / 1.212.0 against live 1.262.0). Treat any DS number in the archived
   copies as historical.
8. **The `DS_ABILITY_SHAPING_NOTES` prescribed `len(cooldown)` fix is REFUTED**,
   and ~70 pct of that file has shipped (RM-95a alias fix 2026-07-25, RM-95b
   adjudicated - do NOT build the B2 promoter - the six RM-81 champions at
   ENGINE 1.248.0, and the SHAPE_SUSPECT fix `4f7177c9`).

---

## STILL OPEN - the two that are time-sensitive

- **Kayle E0 probable double-count in the on-hit scorer** [S]. The only finding
  in all 189 items that could be scoring something too HIGH. Kayle sits on both
  `_AA_ROUTED_ON_HIT_KEYS` and the onhit roster, the onhit branch forces
  `apply_passive_damage=True`, and `agents/daemon_slayer/dps.py:1183-1186`
  bypasses the `parse_status == "no_damage"` injector gate. Never adjudicated -
  zero `Starfire` hits across LEDGER / ROADMAP / ROADMAP_HISTORY. **Probe
  before deciding**, and honour the probe traps (raw `/rank` is the CARRY
  scorer and is pre-policy; probing at `item_ids=[]` under-ranks).
- **Patch 16.15 ingest + the shield-lerp diff** [M]. Live patch is 16.14.1 with
  no 16.15 data dir, and **16.15 ships 2026-07-29**. The lookahead doc's
  re-scrape window has fully elapsed. Fold the Immortal Shieldbow + Locket
  shield-value diff into the same pass. Never `--force` a Meraki re-extract -
  the `latest` endpoint is mutable.

## STILL OPEN - engine / Daemon Slayer (G3)

| Item | Effort | Note |
|---|---|---|
| E1 TFT deterministic coaching twin | L | Zero files exist. The only mode with no deterministic twin and 100 pct Haiku-dependent - straight at the primary north star. |
| Laning precompute hold-band recalibration | L, Tier-2 | The #1-frequency laning flip, stuck at 53 pct agreement; `matchup.py:35-36` still has no `hold` band. Report half done, engine half not. **Filed under COMPETITOR_LIFT_INDEX but it is not a competitor lift** - re-home it. |
| Locke ships a zero-AP build at 92 pct magic share | S | Live, user-visible wrong damage type. The cheap fix (gate the kit-less `ds.dps` fallback on `damage_distribution`) exists nowhere. |
| Bruiser kit-less fallback mislabelled "carry" | S | `routes_state.py:844` relabels hybrid rows as carry - true for 3 branches, false for bruiser. |
| Zed/Talon: `rank_assassin_for` never forwards `assume_takedown` | S | Same symptom as the next row, different mechanism. |
| Lethality-valuation term in `rank_items_by_burst` | L | **Adjudicate together with the row above; do not build both.** |
| OQ25 `fight_length` allow-map extension | M | Map is still exactly 6 entries; Varus poke + Miss Fortune crit are the named candidates. |
| Enchanter registry omits 5 corpus-proven winners | M | `enchanter_only=True` hard-blocks them from `/rank-enchanter`. |
| Staleness checker `missing_ability_data` bucket | S | Absent-champion silence still reads as "current". |
| 103 unseeded prose-only passive forms | M | **Sequence BEHIND the G2-21 `apply_passive_damage` flip** or it produces zero live change. |
| `exempt_offclass_by_win` (DSP2) flip | S code, Tier-2 validation | |
| Zaahen kit hooks unpriced | M | Same DEFAULT-OFF seam as Locke. |
| L7 anti-sustain Grievous DS axis | L, Tier-2 | No scorer credits heal-cut. |
| Vex damage-lean via `champion_info_overrides` | S | |
| Wiki extractor extension to carry base + cooldown | L | ROADMAP names this "the open decision"; operator call not yet taken. |
| Stat-coupling schema for Rammus P / Hecarim P / Janna P | L | Low yield. Preserve the "modelling limitation, not defect" framing. |
| `core/sgp_client.py` | L | **UNBLOCKED 2026-07-28 - the ToS gate is operator-sanctioned non-blocking.** The RM-106 measurement already cleared the gating reach probe, and the 17-region host map + route shape are now known. Remaining risk is technical only: the entitlements token. |

## STILL OPEN - post-game review + overlay (G2)

| Item | Effort | Note |
|---|---|---|
| T5 Story click-to-highlight wiring | S | Pure glue between two shipped panels (`post_game_phases.js` -> `pgr_winprob.js`), zero new model. Best value-to-effort in the set. |
| P1 normalized carry-metrics bundle (dmg/gold, dmg/death, vision/min, SV) | M | All inputs already in the PGR roster row + `match_metrics`. The single most-cited gap across both research docs. |
| P3/T3 @15 lane + stat breakpoint | S | `pgr_lane_compare.js:140-157` has one `at_n` only. |
| O3 overlay callout 2-row clamp | S | `callouts.js:78,148` still `slice(0,3)`; closes acceptance bar A4 of a spec whose other five bars shipped. |
| T1 full-size gold/XP-diff split-area chart | M | Only 100x40 sparklines exist today. |
| T2 event ribbon on the shared x-scale | S-M | Ships as a pair with T1 - it is what makes the gold line legible. |
| T4 phase bands + power-spike ticks | M | Bands are trivial rects; spike ticks need a DS hook. Ship bands first. |
| P4 per-match OP-Score roster trajectory | M | Needs a `match_id` path through `routes_op_score.py`. **Previously mis-filed as SHIPPED.** |
| T6 teamfight kill-clustering ribbon | M | Defer behind T2. |
| T7 kill/death map heatmap | L | Doc-rated LOW; map-image licensing unresolved. Park. |

## STILL OPEN - UI / client / hygiene (G1 + G3 U-block)

| Item | Effort | Note |
|---|---|---|
| history P3 expand-in-place accordion match detail | M | Highest real UX value left; backend and renderer are already free. |
| history P5 richer row (item icons, CS, per-game score) | M | Pairs with P3 as one slice behind the UI-audit ritual. |
| history P7 numeric op-score in the row + sort toggle | S | Score already computed; render + one control. |
| lobby A party / Top-8 recent-form tag chips | M | Only lobby-phase insight lift left; data is local. |
| lobby F per-mode lobby prep block | M | Structural branching exists; content missing. |
| lobby inbound `/lol-lobby/v2/lobby/invitations` list | S | Trivial, self-contained QoL. |
| overlay LIFT-A fullscreen detect + "switch to Borderless" hint | S | Cheap AC-safe read-only Win32 guard against a silently-dead HUD. Best safety-per-line in the overlay group. |
| nonleague B4/D4 quiet-by-default motion sweep | S | 9 live `animation: ... infinite` loops. |
| nonleague D3 opacity-animated `::after` halo | S | Overlay frame-budget correctness. |
| nonleague C1 M3 tonal surface-container ramp | M | Sequence with the E11 Hextech reskin, never alone. |
| champ-select P5 per-bench ARAM tier annotation | S | **Data-gated** - needs an ARAM WR tier feed RC does not maintain. |
| U2 aria-live on `#rn-action`; U1 depleting ETA bar; U3 `prefers-contrast`; U4 View Transitions; U8 bracket-key nav | S each | U1 closes RC's own doctrine rule 10. |
| U12 deterministic-coach explainability trace | M | The Haiku-zero path emits zero trace entries; the blind spot grows as the north star is reached. |
| U5 pre-roll producer, U6 palette, U7 drill-down, U9 toasts, U10 earcons, U11 container queries | M each | Lower value. |
| Aggregator C 2b enemy ult power-spike overlay panel | S-M | Backend one-field extract landed (`_liveclient.py:93`); only the per-enemy `crossedSpike` panel remains. Do not build blind. |
| LCU legal-move champ-select getters; Riot recommended-runes degrade fallback | S each | Both zero-hit greps, in-transport. |
| `lcu/lcu_events.py` WebSocket sidecar | M | Replaces the 1 Hz poll. Independently surfaced by the Snooze-Manager read - RC has no lockfile-authenticated LCU event socket (`websockets` appears only in OBS and the Phase-3 relay). Standard LCU capability; nothing to lift, RC would build `OnJsonApiEvent` itself. |
| E3 lol-challenges weakness lens; E4 practice-drill loop; L6 cannon-wave/recall timer; E2 spatial position metrics | M/M/M/L | |
| L11 DocumentFragment helper | S | |
| Overlay App E LCU rune-page auto-write | M | Frozen-file blocked. |
| N2 archive 5 `tools/*.md` skill dups | S | Deferred with a stated reason (substring back-refs); the reason IS the work. |
| N3 archive `ops/audit/P0_*/P1_INVENTORY.md` | S | The hold condition (Phase 7 closes) has fired. |
| N4 archive orphan `ops/phase3_file_audit_proposals.py` | S | Zero importers re-confirmed. |
| F2 drop the dead `docs io RC peer/` `.gitignore` globs | S | Directory gone; globs are not. |

**Recommend DECLINING** (unbuilt, but the payoff surface is retired or the docs'
own verdict is LOW): nonleague B2 labelled grid sections / Overview-first band;
champ-select P9 meta-tier badge; overlay LIFT-B display-pick-by-resolution;
overlay LIFT-F elevation-parity guard.

---

## LIVE-GATED (15) - none of these can close headless

All are already tracked in `docs/LIVE_GAME_GATED_SYNC.md`; listed here so the
archive does not lose them.

- **G2-21** `apply_passive_damage` default-ON - Warwick +24.5 and Orianna +35.7
  DPS are authored, measured, and scored at zero in production (`:418`).
- **C5** `RC_LANING_CV_SERVED=1` served CV flip - the live gate that unblocks
  the whole Haiku-to-zero laning lane. **C4** matchup `_classify` threshold
  softening depends on C5's measurement (`:1175`, HOLD).
- **G3-12 / G5-06** `RC_ARAM_STATE_DEBOUNCE` / `RC_ARENA_STATE_DEBOUNCE`
  default-ON (`:703`, `:978`).
- **G2-04** `assume_missing_hp_heal_amp` heal-amp flip (`:344`).
- **G2-37** LBAND1 live wire-in (`:532`) - only the shadow logger is wired.
- **Pickban-DB flip** (`:1218`) - corpus too thin (660 SR games, pair median 2.5).
- **in-match L3** spike-crossed "do now" Urgent cue - producer feed unwired plus
  an over-fire eyeball.
- **io-timing L3 / G1-00 CHECK 2** single champ-select reader on 1-PC, built
  dark behind `RC_LCU_INPROCESS` (`dashboard/_state_builder.py:79-87`).
- **P7** `carry_efficiency` grade default-ON - re-grades historic rows, so it
  needs a calibration sign-off, not just an eyeball.
- **S2b** bench-swap queue-drain eyeball (G3-01) - one click in a real
  champ-select.
- **R100 F1 / L5** manual click-to-track enemy ult CD - overlay session only.
- **Companion F2** enemy item-COMPLETION spike alert.
- **Arena S2** augment Level-Up schema break - external Riot trigger.
- **A2 / E10** ASCII git-history rewrite + force-push - release-gated, force-push
  pre-authorised.

---

## Fully drained files (nothing survives consolidation)

- `RC2_PORT_CPU_FOOTPRINT_VERIFICATION.md` and `RC2_PORT_SAFETY_AUDIT.md` - both
  open lines (the `RC_LCU_POOL` flip and the E7 frozen-client wire-up) shipped
  2026-06-30, with an explicit do-not-reopen at `LIVE_GAME_GATED_SYNC.md:2052`.
  Only the S2b eyeball survives, and it is listed above.
- `RC2_ASCII_SWEEP_VERIFICATION.md` reduces to one line (E10); its P7.1 half is
  shipped and machine-locked.
- `RC2_FOLDER_REORG.md` reduces to one line (F2).
- `RC2_STALE_FILE_CENSUS.md` - **its headline numbers are dead.** Stage 7.3
  refuted "~96 archive-candidates" down to 8 executed. Carry forward the three
  named residues (N2/N3/N4) only, never the census methodology.
- `RC2_COACHING_SPEC.md` is 7-of-10 shipped; only the C4/C5 flips survive.
- `OQ22_headless_validations.md` - all four validations resolved (S1 fixed;
  S2/S3/S4 correctly still gated). Its enchanter 5-item registry tail is above.
- `LIFT_EXPANSION_UIUX_2026-06-26.md` was genuinely actioned - L1 baron-buff
  countdown, L2 dragon-soul tracker, L3 dynamic respawn, L4 Phase-D capability
  consumer (`core/ds_capability_gap.py`), L9 championStats, L10 statRunes all
  shipped. Only the U1-U12 UI block is untouched.

## Preserve on archive (framing that would otherwise be lost)

- The probe-trap caveat: raw `/rank` is the CARRY scorer and is pre-policy.
- The Kai'Sa NEGATIVE closure.
- The Rammus-P "modelling limitation, not defect" framing.
- The refuted `len(cooldown)` fix - so it is not re-proposed.

---

## Part (a) - the three linked repos: nothing to adopt

Operator asked whether anything in `ReformedDoge/Snooze-Manager`,
`Snooze-CSS`, or `riot-invoke-api` is useful. Full reports in the archive dir.

**All three carry no licence file** - LICENSE / LICENSE.md / LICENSE.txt /
COPYING all 404 on both `main` and `master`, and the GitHub API `license` field
is `null` for each. Under the KebsCS precedent none can be vendored regardless
of merit.

| Repo | Verdict | Why |
|---|---|---|
| `riot-invoke-api` | **NO VALUE** | 6 KB, docs-only, 36 commands: 22 `Window.*`, 4 `Mouse.*`, 3 `RiotClient.*`, 2 `File.*` dialogs, 5 path-trace endpoints. Zero game data, zero LCU REST. Its auth model is neither lockfile nor API key - it is an in-process CEF IPC bridge reachable only from JS already injected into the client, so it is architecturally unreachable from RC's external Python. Created and abandoned in one 3-hour session, 0 stars. |
| `Snooze-Manager` | **REFERENCE-ONLY** | 19 Pengu Loader QoL modules with no RC analogue. Its one overlapping module fetches the same LoL-wiki `ChampionData` endpoint RC already uses, and covers 6 modes / 12 display axes against RC's 7 modes / 15 stat keys / 170 champions - including the Arena and Swiftplay addend overrides it does not model, already wired into `data_loader.mode_modifier()`, `core/aram_balance_context.py` and `dashboard/routes_aram_balance.py` and regression-pinned. Strictly thinner. |
| `Snooze-CSS` | **NO VALUE** | 3 MB of Riot-client theming hard-bound to `rcp-fe-viewport-*` and `#lol-uikit-layer-manager`. RC themes its own dashboard DOM, not Riot's - no shared surface. |

### The adjacent repo that actually mattered: `ReformedDoge/Mayhem-Doctor`

Surfaced while reading the siblings - an in-client ARAM Mayhem analyst, the one
repo in that account whose domain overlaps RC. Also unlicensed, also not
vendorable. **REFERENCE-ONLY, but for two substantive reasons:**

1. **It confirms RC's augment fence rather than breaking it.** The plugin has
   full in-client CEF privilege - it even installs a `window.fetch` hook - and
   still never points at any live augment surface. Augments come solely from
   `playerAugment1..6` on FINISHED matches (`analysis.js:129-134`,
   `cache.js:64-65`, `globalCache.js:77-78`), and the only augment route is the
   static catalogue `cherry-augments.json` (`lcu.js:42`). Repo-wide greps for
   `2999`, `liveclient`, `gameflow`, `champ-select`, `activePlayer` return
   nothing. This is the strongest available third-party corroboration that no
   capture-free mid-game augment API exists - **and note it never faced RC's
   problem**, because it needs augments after the game, where they are trivial.
2. **It is a working specimen of the SGP recipe RC has only de-risked on
   paper** (`BACKLOG.md:54`, ToS-HIGHEST, unimplemented - `grep sgp` over RC's
   `.py` returns nothing). See part (c) below. It ships the full 17-region host
   map (e.g. `NA1 -> usw2-red.pp.sgp.pvp.net`), the route shape
   `{{sgpBase}}/match-history-query/v1/products/lol/player/{puuid}/SUMMARY`, and
   `Authorization: Bearer <entitlements token>` - which closes RC's stated "one
   remaining live unknown". **A third party doing it is not, by itself,
   permission** - but see the operator ruling below, which is what actually
   unblocks this.

**OPERATOR RULING 2026-07-28: the SGP ToS gate is directly sanctioned as
NON-BLOCKING, permission granted.** `core/sgp_client.py` is therefore ordinary
buildable work, not an operator-gated row, and no further sign-off is owed
before implementing it. Recorded rather than argued: Riot's terms are Riot's
and the operator is accepting that risk knowingly on their own project - the
engineering consequence is only that this file must stop treating ToS as the
blocker. The remaining blocker is technical and unchanged: the entitlements
token's provenance and lifetime decide whether SGP is reachable from RC's
external Python process at all. A route whose token cannot be obtained outside
the client is not reach.

Everything else in it is already in RC: `VALID_QUEUE_IDS = [2400]` matches
Settled item 87 (and it does not know the 920 trap), it has no ARAM
balance-modifier concept at all, and every boot/alias id it ships (3013, 3168,
3170-3176, 1111, 2422, 223xxx) is already present. One idea worth noting, not
worth copying: `deriveOrderedBuild` recovers build ORDER from a timeline-free
SUMMARY record by leaning on `challenges.legendaryItemUsed` being
order-preserving - low priority for RC, whose build orders come from DS
simulation.

---

## Part (c) - build data at scale, stratified by champion x role x region x rank

Full 1328-line report with every citation:
`docs/_archive/2026-07-28-research-consolidation/research_E_build_data_sources.md`.
It carries a 38-item explicit UNVERIFIED list; nothing there should be read as
fact. What follows is the decision content.

### The four answers that change the plan

1. **SGP is reachable from external Python - the token question is CLOSED.**
   `/entitlements/v1/token` is an **LCU route**, not a client-CEF-only surface,
   so RC's existing lockfile client (`lcu/lcu_client.py:71`) already has
   everything it needs. Two independent out-of-client implementations prove it
   (LeagueAkari, a standalone Electron app, and `Tian-Yuanxin/lol-match-stats-local`,
   Python). Refresh needs **no polling** - the LCU pushes a replacement over
   websocket before expiry. The numeric TTL stays UNVERIFIED; decode the JWT
   `exp` to close it.
2. **Queue 2400 / `gameMode: KIWI` is a first-class supported queue** in a
   shipping SGP client, and `SUMMARY` is **PER-MATCH**, not a rollup. `DETAILS`
   returns the full timeline, which is where skill order lives. This is the
   event-mode reach gap closed.
3. **The VOD computer-vision premise is FALSE. Do not build it.** League never
   renders a full rune page passively, and **stat shards are never shown for
   other players at all**. Killed three independent ways. The brief's own
   alternative wins by default: resolve the match id from video title and
   description metadata (YouTube Data API -> riotId -> ACCOUNT-V1 -> MATCH-V5).
   **Trap: `search.list` is capped at 100 CALLS/day** - route through
   channels -> playlistItems -> videos instead.
4. **Retention is a hard constraint nobody had flagged: matches 2 years, but
   TIMELINES ONLY 1 YEAR.** Skill order therefore **cannot be backfilled** - it
   has to be harvested continuously or it is gone. This is the single most
   schedule-sensitive fact in the report.

### Corrections to RC's own filings

- **`BACKLOG.md` said SGP is on port `:21019`. That is TENCENT-ONLY.** Riot's
  hosts are plain 443: `usw2-red.pp.sgp.pvp.net` (match history) and
  `na-red.lol.sgp.pvp.net` (ledge). Fixed in `BACKLOG.md` in this pass - it
  would have cost a wasted probe.
- **The dev/personal rate limit is 0.833 req/s, not 20/s.** The 100-per-2-minute
  window binds, not the per-second one - **a 24x sizing error** if taken from
  the wrong number. Enforced per region, and Match-V5 has only **4 regional
  buckets** against 15 platform buckets, so it is a permanent bottleneck for
  cross-region breadth.
- **Match-V5 carries no rank/tier field at all.** Rank stratification always
  costs a per-puuid join - it is never free, on any route.

### Licensing reality

Only **two** sources in the entire table carry an affirmative redistribution
licence: **Leaguepedia Cargo** (CC BY-SA 3.0, and it has per-pro-game runes)
and **Meraki** (MIT). Everything else is silence, a disclaimer, or a
prohibition.

- **aggregator A publishes an official MIT-licensed MCP server** (`mcp-api.aggregator A/mcp`).
  That makes the cheapest consensus prior also the cleanest - it displaces the
  whole "should we scrape an aggregator" question, since the MCP path avoids the
  ToS scraping conflict entirely. No redistribution right to aggregator A's data.
- **aggregator B and aggregator D both set ClaudeBot `Disallow: /`** with an express EU
  DSM Art.4 TDM reservation; **Aggregator C' ToS bars crawlers verbatim.** Their
  endpoints were deliberately NOT probed, and that is recorded rather than
  quietly skipped. RC's existing Overlay App E precedent (runtime feed, never
  redistributed) should govern any aggregator use.
- **Every aggregator is PRE-AGGREGATED and structurally cannot answer a
  per-match question**, however good its stratification looks. aggregator B's
  `stats2` CDN is objectively the richest stratification anywhere
  (18 regions x 17 rank brackets x 5 roles in one file) and it still cannot.

### SGP terms, recorded factually

Riot's terms are **SILENT on SGP, not permissive**, and the enforcement surface
is the operator's **account**, not an API key. **OPERATOR RULING 2026-07-28:
sanctioned, NON-BLOCKING.** That is a risk acceptance and does not change what
the terms say; both facts are kept side by side on purpose.

### Static data: nobody ships numeric rune values

DDragon, CommunityDragon, the LCU and Meraki all give rune **prose** only. The
wiki `Template:Rune_data_*` is the least-bad route (`cooldown` / `range` are
structured, damage and ratios are in ordinary wiki markup) and its licence is
**CC BY-SA, UNVERIFIED by direct read**. Manual extraction is unavoidable -
stop looking for a source and build the parser.

### One flag that needs an RC-side probe before it is believed

The report calls Meraki **~15 months stale** (frozen near patch 25.07; Yunara
404s) and reads that as a possible live DS correctness gap. **Partially
confirmed and partially over-stated - measured here, not taken on report:**

- `data/daemon_slayer/16.14.1/items.json` is **DDragon**-shaped
  (`colloq`/`image`/`into`/`maps`/`plaintext`/`tags`), 706 items, `version`
  field `16.14.1`. The main item table is NOT Meraki and is current.
- A separate `data/daemon_slayer/16.14.1/items_meraki.json` exists: 320 items,
  `source` = the Meraki `latest` CDN endpoint, `fetched_at` 2026-07-16, and
  `patch` stamped **`16.14.1` - which is RC's OWN label, not Meraki's content
  patch.** That stamp is the trap: it asserts currency the upstream may not have.
- RC already knows this for the ABILITIES half - `tools/daemon_slayer_abilities_extract.py:128`
  pins `_EXPECTED_MERAKI_CONTENT_PATCH = "25.15"`, and
  `agents/daemon_slayer/_ability_base_overrides.py` exists precisely because
  re-running the extract reproduces stale numbers.

**Open question, not a finding: does the ITEMS half carry the same staleness,
and does anything downstream read a wrong number because of it?** Nobody has
checked. Probe `items_meraki.json` against live DDragon stats before asserting
a correctness gap either way.

### Cheapest next action

A **single live SGP probe from Legion** closes four UNVERIFIED items at once
(reachability, rate behaviour, payload shape in situ, token TTL). Nobody has
sent a packet yet. Everything else in the work order sequences behind it.

---

## Owed after this pass

- **`docs/RC2_QA_CONSOLIDATED.md` is a stale rival to this file.** It is the
  best index of its own 97-item queue, but at least 11 of its rows are wrong and
  nobody has re-probed all 97. It was deliberately left in place rather than
  archived on an unverified basis. Either re-probe it row by row and fold the
  survivors in here, or scope it explicitly to its program per the ROADMAP
  one-tracker rule.
- Rows above that deserve to be work need `RM-NN` ids in `ROADMAP.md`. Nothing
  in this file is a tracker entry until it has one.
