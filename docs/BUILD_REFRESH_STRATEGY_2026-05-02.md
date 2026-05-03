# Build Refresh Strategy — Patch 16.9 / 26.9

**Compiled:** 2026-05-02
**Live patch:** 16.9.1 (also written as 26.9; Season 16 Split 2)
**Goal:** refresh `data/meta_build/*_champion_builds.json` across SR, ARAM, Arena for the 172-champ DDragon roster without trying to research 516 mode-champ entries by hand.

> Existing state: SR file has only 18 entries (very stale; patch tag `16.8.1`). ARAM file has 166 entries (full coverage but stale; patch tag `26.8`). No arena_champion_builds.json exists — arena currently borrows ARAM data, which the just-shipped `ARENA_META_RESEARCH_2026-05-02.md` shows is structurally wrong (anvil RNG breaks the linear `full_build` semantic).

---

## Mode tier lists

### SR (Summoner's Rift) — top 30, aggregator A patch 16.9

Source: aggregator A `/lol/champions` ranked by WR, all roles, current patch. Role-segmented because SR builds bifurcate by lane.

| # | Champion | Role | WR | PR | BR |
|---|---|---|---|---|---|
| 1 | Naafiri | Mid | 53.98 | 2.62 | 28.37 |
| 2 | Seraphine | Sup | 53.54 | 9.44 | 3.31 |
| 3 | Warwick | Jng | 53.25 | 2.87 | 1.90 |
| 4 | Singed | Top | 53.01 | 2.94 | 1.06 |
| 5 | Ashe | ADC | 53.01 | 15.22 | 8.94 |
| 6 | Shyvana | Jng | 52.86 | 5.12 | 7.05 |
| 7 | Xerath | Mid | 52.82 | 5.60 | 8.16 |
| 8 | Smolder | ADC | 52.71 | 11.65 | 6.61 |
| 9 | Vladimir | Mid | 52.71 | 4.29 | 5.37 |
| 10 | Zed | Mid | 52.37 | 8.86 | 27.33 |
| 11 | Nocturne | Jng | 51.94 | 7.58 | 14.38 |
| 12 | Garen | Top | 51.68 | 7.60 | 7.89 |
| 13 | Nami | Sup | 51.55 | 14.24 | 3.95 |
| 14 | Malphite | Top | 51.52 | 6.21 | 19.56 |
| 15 | Ahri | Mid | 51.40 | 10.44 | 5.04 |
| 16 | Thresh | Sup | 51.37 | 12.61 | 7.75 |
| 17 | Katarina | Mid | 51.32 | 7.10 | 11.24 |
| 18 | Malzahar | Mid | 50.80 | 7.71 | 10.22 |
| 19 | Viktor | Mid | 50.79 | 8.43 | 4.63 |
| 20 | Lee Sin | Jng | 50.69 | 13.15 | 14.82 |
| 21 | Brand | ADC | 54.42 | 2.63 | 6.03 |
| 22 | Olaf | Top | 52.83 | 2.45 | 2.50 |
| 23 | Kayle | Top | 52.71 | 3.06 | 3.90 |
| 24 | Zilean | Sup | 52.56 | 2.78 | 1.49 |
| 25 | Vex | Mid | 52.50 | 2.55 | 3.37 |
| 26 | Rek'Sai | Jng | 52.50 | 2.34 | 1.80 |
| 27 | Annie | Mid | 52.47 | 3.07 | 0.79 |
| 28 | Rell | Sup | 52.34 | 3.48 | 1.02 |
| 29 | Jinx | ADC | 52.01 | 11.58 | 3.80 |
| 30 | Fizz | Mid | 52.00 | 4.14 | 5.42 |

Patch 26.9 buff list (from Riot notes — confirms emergence): Ezreal, Gragas, Kennen, **Shyvana**, Tahm Kench, Taliyah, Teemo, Udyr, **Warwick**, **Xin Zhao**, Zeri. Nerfs: Ambessa, Briar, Zoe. (Source: leagueoflegends.com patch 26.9 notes.)

**B-tier band (rank 31–60):** to be pulled in Phase 2 from aggregator A `/lol/champions?page=2`. Expect Aurelion Sol, Yorick, Twitch, Heimerdinger, Pantheon, Maokai, Nautilus, Karma, Lulu, Trundle, Jhin, Sivir, Cassiopeia, Kindred, Renekton, Diana, Wukong, Sett, Veigar, Cho'Gath, Yone, etc. (these are typical 49–52% WR pool members across recent patches).

### ARAM — top 30, aggregator K patch 16.9

Source: aggregator K `/tierlist` ranked by WR. Pure WR (no role split — ARAM is one mode). PR is implicit from the per-champ `Games` count (not exposed as %).

| # | Champion | WR | Games | Tier |
|---|---|---|---|---|
| 1 | Mordekaiser | 55.5 | 9211 | S+ |
| 2 | Sion | 55.5 | 6386 | S+ |
| 3 | Lux | 54.3 | 15865 | S |
| 4 | Rell | 54.1 | 3754 | S |
| 5 | Seraphine | 54.1 | 13350 | S |
| 6 | Vel'Koz | 54.0 | 13678 | S |
| 7 | Ashe | 53.9 | 15268 | S |
| 8 | Yorick | 53.8 | 3171 | S |
| 9 | Heimerdinger | 53.8 | 10414 | S |
| 10 | Brand | 53.6 | 13818 | S |
| 11 | Kalista | 53.4 | 6488 | A |
| 12 | Sett | 53.3 | 5444 | A |
| 13 | Zyra | 53.3 | 8251 | A |
| 14 | Ziggs | 53.1 | 13626 | A |
| 15 | Leona | 53.0 | 6269 | A |
| 16 | Zaahen | 52.9 | 3788 | A |
| 17 | Bel'Veth | 52.9 | 1541 | A |
| 18 | Galio | 52.8 | 8009 | A |
| 19 | Illaoi | 52.7 | 4118 | A |
| 20 | Xin Zhao | 52.7 | 4067 | A |
| 21 | Olaf | 52.7 | 3506 | A |
| 22 | Rek'Sai | 52.6 | 1545 | A |
| 23 | Jax | 52.6 | 5590 | A |
| 24 | Dr. Mundo | 52.6 | 6079 | A |
| 25 | Jinx | 52.5 | 14012 | A |
| 26 | Sona | 52.4 | 7375 | A |
| 27 | Fiddlesticks | 52.4 | 9122 | A |
| 28 | Hwei | 52.4 | 5649 | A |
| 29 | Yasuo | 52.4 | 8198 | A |
| 30 | Kled | 52.4 | 1621 | A |

Patch 26.9 ARAM-specific changes: Hubris-rune nerf; Mayhem buffs to Bard / Ornn (Mayhem-only); Health Relic AOE 16→22%. Standard ARAM has no champ-targeted balance this patch — tier list is mostly drift from SR buffs.

**B-tier band (rank 31–60):** to be pulled in Phase 2. Aggregator K lists ~150 champs total; ranks 31–60 typically sit in the 51.0–52.3% WR range.

### Arena (CHERRY) — top 15, aggregator J + aggregator C patch 26.9

Source: pre-shipped `docs/ARENA_META_RESEARCH_2026-05-02.md` (sample size ~140k matches across aggregator C + aggregator J + aggregator B). Arena tier = 1st-place WR (not standard WR — placement matters more than win/loss).

| # | Champion | Tier | 1st WR | Notes |
|---|---|---|---|---|
| 1 | Cho'Gath | S | 17.7 | 30% top-2; 39.5% banrate |
| 2 | Zaahen | S | top overall | 63.7% top-4 / 76% banrate |
| 3 | Shyvana | S | (50% on optimal core) | 2.3 avg place |
| 4 | Vi | S | 16.9 | 31.6% top-2 |
| 5 | Sett | S | 16.9 | 22.3% PR — highest pickrate top-tier; 52.9% banrate |
| 6 | Olaf | A | 15.4 | 57.9% top-4 |
| 7 | Pantheon | A | 14.7 | 27.3% top-2 |
| 8 | Ambessa | A | 15.4 | 53.5% top-4; 25.8% banrate |
| 9 | Amumu | A | 15.1 | 50.9% top-4; Aurelion Sol duo 73.3% WR |
| 10 | Briar | S | 16.3 | 57.2% top-4 |
| 11 | Xin Zhao | S | 19.6 | highest single-champ 1st-rate non-Zaahen |
| 12 | Tryndamere | C | 12.8 | high pickrate but mediocre solo |
| 13 | Ahri | C | 13.5 | 11% PR despite C tier |
| 14 | Brand | A | 15.5 | 30.4% top-2; 24.5% banrate |
| 15 | Malphite | B | 13.7 | honourable mention |

Arena is **partner-paired** — `best_duos` field is load-bearing (e.g., Amumu+Aurelion Sol 73.3% together). Phase 1 must capture top-3 duos per S/A champ.

**B-tier band (Arena ranks 16–45):** to be pulled in Phase 2. Aggregator C' arena list shows ~50 champs at meaningful pickrate; rest are tail.

---

## Source reliability table

Probed 2026-05-02 from Legion. Fetcher = WebFetch (the same allowlist behaviour the data_pipeline uses).

| Source | SR | ARAM | Arena | Notes |
|---|---|---|---|---|
| **aggregator A** `/lol/champions`, `/lol/modes/aram` | OK (full top-30 table) | partial (Lux only — needs URL with `?tier=all` or per-rank pagination) | n/a | Best SR source. WebFetch returns full tables for the all-roles index. |
| **aggregator K** `/tierlist` | n/a | OK (full top-30 with games count) | n/a | Cleanest ARAM source. No rate-limit hit. |
| **aggregator C** `/lol/tier-list`, `/lol/tier-list/aram` | partial (5 expert picks per role only — no stats table) | 404 on `/lol/aram/tier-list` (must use `/lol/tier-list/aram`) | OK (used in arena doc) | Good for arena duos and curated picks; weak for raw stats. |
| **aggregator J** `/en/league/champion/{C}/arena` | n/a | n/a | OK for all 19 champs probed | Per-champion arena page. Slow but works. |
| **aggregator B** `/lol/tier-list`, `/lol/aram-tier-list` | blocked (truncated header only) | blocked | partial header | Public pages obfuscate data behind JS. **Stats API** `aggregator B stats host/.../overview.json` returns 403 from server-side fetchers (used to work; data_pipeline.py treats it as non-fatal). |
| **aggregator D** `/lol/tierlist/`, `/lol/tierlist/aram/` | 403 | 403 | 403 | Hard-blocked across the board for automated fetches. |
| **aggregator N** `/lol/aram/tier-list`, `/lol/arena/tier-list` | n/a | 402 (paywalled fetch) | 402 | Paywalled at fetcher layer. |
| **overlay app E** `/lol/tierlists/...` | 403 | 403 | 403 | Cloudflare blocks. |
| **aggregator H** `/champions/stats/aram` | 403 | 403 | n/a | Documented in MEMORY as 403-on-automated. Don't propose. |
| **leagueoflegends.com** patch notes | OK (champ buffs/nerfs list) | OK (ARAM section) | OK (Arena section) | Authoritative for *what changed*, not *current WR*. Use to detect tier-list drift. |
| **wiki.leagueoflegends.com** | OK | OK | OK (used in arena doc) | Authoritative for items, augments, mode rules. Not a tier source. |

**Outcome:** SR is aggregator A-primary, ARAM is aggregator K-primary, Arena is aggregator J+aggregator C-primary. No single source covers all three. Backups are weak — if a primary breaks we fall back to leagueoflegends.com patch notes for direction-of-change and hand-curate.

---

## Comparison strategy proposal

Multi-source comparison only matters for **top 30 / S+A tier** champs in Phase 1. For B-tier (single source) and tail (label-only) the "compare" question doesn't arise.

### Per-mode resolution rule when sources disagree

**SR:** Pick the **highest-PR variant** when WR is within 1.0% of the best. Reason: highest-PR build is the one that's been pressure-tested across the largest sample; a 0.5% WR edge on a 1k-game sample is noise. If there are two distinct *archetypes* (e.g., crit vs lethality on Vayne) and both have >5% PR, **list both** in the new schema's `variants` array and let the coach pick by game state (vs-tank → crit, vs-squishy → lethality).

**ARAM:** Pick the **highest-WR variant** outright. ARAM has no matchup selection — you can't avoid the comp — so the build that won most over the largest sample is canonically right. Variants only matter for fundamentally bimodal champs (e.g., Sett tank vs Sett bruiser).

**Arena:** Pick the **highest-1st-place-WR core** (placement matters more than W/L). But: arena builds are anvil-RNG, so the "core" is aspirational — the schema must store an **item priority list** (rank-ordered "if offered, take X over Y") rather than a fixed `full_build`. Per-augment overrides take precedence (e.g., Dual Wield → swap to Kraken/BotRK regardless of base core).

### When to surface multiple variants vs collapse

- 1 variant: WR delta to second-best > 2% OR PR ratio > 3:1. Single canonical build.
- 2 variants: WR within 1.5% AND both >5% PR AND identifiable trigger (vs-tank, vs-squishy, vs-burst). Add `variants: [{trigger, build}, ...]`.
- Never 3+: cognitive load on coach prompt is not worth the added precision; collapse the lowest-PR third into the trigger note of the closest sibling.

### Citation field

Every champ entry gets `_sources: [{name, url, fetched_at, wr, pr}]` so we can audit drift between refreshes. The pipeline emits this per-row, not as a global header.

---

## Schema proposal

### Current ARAM schema (per-champ)

```jsonc
{
  "aram_tier": "A",
  "build_note": "long coaching paragraph",
  "core_items": ["Titanic Hydra", "Sterak's Gage", "Black Cleaver"],
  "vs_tanks": "Thornmail",
  "vs_healing": "Thornmail in core",
  "vs_burst": "Immortal Shieldbow replaces Sterak's vs poke burst",
  "full_build": ["Plated Steelcaps", "Sunfire Aegis", "Sterak's Gage", "Death's Dance", "Thornmail", "Gargoyle Stoneplate"]
}
```

### Current SR schema (per-champ)

```jsonc
{
  "start": "Doran's Blade",
  "first_back": "Recurve Bow (800g) or Long Sword if <800g",
  "full_build": [...],
  "vs_tanks": "...", "vs_healing": "...", "vs_burst": "...",
  "build_note": "...",
  "recall_timing": "..."
}
```

### Proposed unified schema (one shape, mode-specific extension blocks)

```jsonc
{
  // shared across all 3 modes
  "tier": "S",                          // S+/S/A/B/C/D
  "wr": 53.6, "pr": 11.7, "br": 6.0,    // raw stats from primary source
  "build_note": "one-line coaching gist",
  "kit_notes": "win-condition / passive identity",
  "variants": [                          // 1–2 per champ; see comparison rules above
    {"trigger": "default",   "build": [...], "boots": "Mercury's Treads"},
    {"trigger": "vs_tanks",  "build": [...], "boots": "Plated Steelcaps"}
  ],
  "anti_picks": {                        // replaces vs_tanks/vs_healing/vs_burst trio
    "vs_tanks":   "BotRK 3rd",
    "vs_healing": "Mortal Reminder 5th",
    "vs_burst":   "Maw of Malmortius if 3+ AP"
  },
  "_sources": [{"name": "aggregator A", "url": "...", "fetched_at": "2026-05-02"}],

  // SR-only block (null on ARAM/Arena entries)
  "sr": {
    "role": "Mid",
    "start": "Doran's Blade",
    "first_back": "Sheen + boots",
    "recall_timing": "1100g threshold",
    "runes_primary": "Conqueror",
    "runes_secondary": "Resolve"
  },

  // ARAM-only block
  "aram": {
    "rune_shard_priority": ["Adaptive", "Adaptive", "Armor"],
    "energized_synergy": false
  },

  // Arena-only block (anvil-aware)
  "arena": {
    "wr_first": 17.7,                   // 1st-place WR (the arena-canonical metric)
    "wr_top4": 50.9,
    "ideal_core_priority": ["Hemomancer's Helm", "Death's Dance", "BotRK"],  // ranked
    "prismatic_priority":  ["Reverberation", "Moonflair Spellblade", "Goliath"],
    "best_duos": [{"champ": "Aurelion Sol", "wr": 73.3, "avg_place": 1.7}],
    "build_changing_augments": ["Dual Wield", "Mystic Punch", "ADAPt"]
  }
}
```

### Rationale for unified schema (vs three separate schemas)

- **Coach prompt builders already key off champ-name → entry**; one file lookup with mode-block selection is simpler than three files with conditional reads.
- **Anti-pick fields are universal** across modes (Mortal Reminder vs Soraka is Mortal Reminder vs Soraka in any mode), so factoring them out of mode-specific blocks reduces duplication.
- **Mode-specific blocks are nullable** — Anivia's `arena` block can simply be absent if she's untracked there, and the coach gracefully degrades.
- The `variants` array is the **single biggest schema change** — it replaces the `full_build` + `vs_*` quartet with structured triggers, which both match arena's reality (anvil priority) and let SR/ARAM expose multi-archetype champs cleanly.

### Migration cost

The existing JSON is ~4500 lines combined. Migration script can re-shape mechanically:
- old `full_build` → `variants[0].build` with `trigger: "default"`
- old `vs_*` strings → `anti_picks` object (1:1 field rename)
- old `aram_tier` → `tier`
- new `wr`, `pr`, `br`, `_sources` filled by the multi-source fetcher
- new mode blocks default to `null`

---

## Scope estimate

### Per-mode fetch counts

| Phase | Coverage | Per-champ fetches | Champs | Total fetches |
|---|---|---|---|---|
| **Phase 1** (multi-source S/A) | top 30 each | 3 sources | 30 × 3 modes = 90 | **270** |
| **Phase 2** (single-source B) | rank 31–60 each | 1 source | 30 × 3 = 90 | **90** |
| **Phase 3** (tier-only tail) | 61–172 | tier label only (1 batch fetch per mode) | 1 batch × 3 = 3 | **3** |
| Plus: tier-list bootstrap fetches | per-mode list | 1 per mode | 3 | **3** |
| | | | | **Total: ~366 fetches** |

### Token / time budget

- **Tier-list bootstrap (3 fetches):** done in this doc. Cost: free.
- **Phase 1:** 270 WebFetch calls. Each ~3–8k input tokens after summarization → ~1.5M tokens total. At ~2 fetches/min through current rate-limit posture, ~2–3 hours of agent time. Coach-prompt generation pass on top: ~30 min.
- **Phase 2:** 90 fetches, single source, ~30 min agent time.
- **Phase 3:** 3 batch fetches (top-N WR list per mode), 5 min.
- **Schema migration script:** 1 hour to write + verify.

**Total: ~366 fetches over ~4–5 hours of focused agent time** (split across 3+ sessions per CLAUDE.md `/clear` discipline).

---

## Pipeline integration sketch

`scripts/data_pipeline.py` currently has `cmd_aram_builds()` which only patches `aram_tier` from the aggregator B stats API (currently 403'd — non-fatal). Three new commands, one migration script, one schema validator:

```python
# scripts/data_pipeline.py — additions

def cmd_full_refresh(mode: str = "all", phase: int = 0) -> bool:
    """
    Multi-source build refresh. mode in {sr, aram, arena, all}; phase in {0,1,2,3}.
    phase=0 = bootstrap tier-list fetch (cheap, gates the rest)
    phase=1 = top-30 multi-source build research (expensive, 3 sources/champ)
    phase=2 = rank 31-60 single-source refresh
    phase=3 = tier-label-only tail update (batch list fetch, no per-champ research)
    """

def cmd_migrate_schema() -> bool:
    """
    One-shot: rewrite aram_champion_builds.json + sr_champion_builds.json
    into the new unified schema. Backs up originals to data/meta_build/_legacy/.
    Creates arena_champion_builds.json from the arena research doc + roster.
    """

def cmd_validate_builds() -> bool:
    """
    Schema-validate all 3 build files against unified shape.
    Warn on: missing tier, build with <3 items, _sources older than 14d,
    variants[].trigger duplicates, arena entry missing arena.* block.
    """

# Wire into existing top-level dispatcher (around line 454):
def cmd_all():
    ok = True
    ok &= cmd_ddragon()
    ok &= cmd_items_index()
    ok &= cmd_runes()
    ok &= cmd_icons()
    ok &= cmd_full_refresh(mode="all", phase=0)   # tier bootstrap only
    ok &= cmd_validate_builds()
    return ok
```

### Hook points
- **Patch-day cron** (`RC-PatchRefresh` scheduled task): runs `cmd_full_refresh(phase=0)` to refresh tiers + re-tag `_note` patch field. Phase 1/2/3 stay manual (cost + token-spend).
- **Coach load path** (`coaches/_base_coach.py` build lookup): swap from `champ.get("full_build", [])` to `champ.get("variants", [{}])[0].get("build", [])` with fallback to legacy field. Migration is non-breaking if `cmd_migrate_schema()` keeps both fields for one patch cycle.
- **Dashboard** (`web_dashboard.py /api/state`): expose `tier`, `wr`, `_sources[0].fetched_at` so the dashboard can show staleness badges.
- **Validator in CI** (`scripts/precommit_pycompile.py` or new pre-commit hook): block commits that bump a build entry without bumping its `_sources[].fetched_at` — prevents stale data masquerading as fresh.

---

## Sources fetched

| Source | URL | Status | Used for |
|---|---|---|---|
| aggregator A champions index | https://aggregator-a.invalid/lol/champions | OK | SR top-30 table |
| aggregator A ARAM landing | https://aggregator-a.invalid/lol/modes/aram | partial | ARAM patch confirmation |
| aggregator K tier list | https://aggregator-k.invalid/tierlist | OK | ARAM top-30 table |
| Riot patch notes 26.9 | https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-9-notes/ | OK | SR buff/nerf list, ARAM Health Relic + Mayhem changes |
| WebSearch — ARAM tier list 16.9 | (Google) | OK | confirmed 5 source domains live |
| WebSearch — patch 26.9 ARAM changes | (Google) | OK | confirmed Health Relic + Hubris changes |
| ARAM aggregator Z14 | https://aram-aggregator-z14.invalid/ | OK (about page only) | confirmed alive as future ARAM source |
| aggregator B stats2 API | https://aggregator-b-stats.invalid/lol/1.5/table/aram/.../overview.json | 403 | (failed; data_pipeline.py treats as non-fatal) |
| aggregator B ARAM tier list page | https://aggregator-b.invalid/lol/aram-tier-list | blocked (header only) | (failed) |
| aggregator D SR | https://aggregator-d.invalid/lol/tierlist/ | 403 | (failed) |
| aggregator D ARAM | https://aggregator-d.invalid/lol/tierlist/aram/ | 403 | (failed) |
| aggregator C SR | https://aggregator-c.invalid/lol/tier-list | partial (5 picks only) | confirms aggregator-B-style stats not exposed without JS render |
| aggregator C ARAM | https://aggregator-c.invalid/lol/aram/tier-list | 404 | wrong URL (real path is `/lol/tier-list/aram`) |
| aggregator N ARAM | https://aggregator-n.invalid/lol/aram | 402 | (failed; paywalled fetcher) |
| overlay app E ARAM | https://overlay-app-e.invalid/lol/tierlists/champions/aram | 403 | (failed) |
| Aggregator H ARAM | https://aggregator-h.invalid/champions/stats/aram | 403 | (failed; expected per MEMORY) |
| Pre-shipped arena doc | `docs/ARENA_META_RESEARCH_2026-05-02.md` | local | Arena top-15 + augment mapping + items reference |
