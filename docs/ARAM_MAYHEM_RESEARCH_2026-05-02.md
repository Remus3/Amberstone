# ARAM Mayhem Research — Patch 26.9 — 2026-05-02

> **Patch correction:** RC's CLAUDE.md cites "16.9.1" but live patch is **26.9**
> (released 2026-04-28). All public sources use 26.x; correcting downstream.
> ARAM Mayhem internal name in RC mode detection is `KIWI`.

> **Mode status:** ARAM Mayhem is **PERMANENT**, not rotating, since 2026.
> It launched 2025-10-22 with Trials of Twilight Act II and was extended
> indefinitely. It runs as a **separate queue** alongside standard ARAM —
> not a featured rotation.

---

## Active modifiers (current ruleset, patch 26.9)

ARAM Mayhem inherits **all standard ARAM rules** (Howling Abyss, no
recall, snowball summoner, no shop outside base, ARAM-specific incoming/outgoing
dmg + healing modifiers per champion) plus the following **Mayhem-only
overrides**:

### Stat / mechanical overrides
| Modifier | Value | Source |
|---|---|---|
| Attack speed cap | **5.0** (regular cap is 2.5) | Wiki ARAM: Mayhem |
| Crit overflow conversion | Each 1% crit > 100% → **0.45 bonus AD** OR **0.75 AP** (adaptive) | Wiki + V25.24 patch |
| Tenacity ramp ("Combo Breaker") | Each immobilization grants escalating tenacity for **3.25s**, refreshes on retrigger | Wiki |
| CC immunity cleanse | Immobilized **5 of last 7 seconds** → cleansed + **3s CC immunity** | Wiki |
| Default rune | All champions gain **Presence of Mind** automatically | Wiki |
| Nexus HP | **3000** (from 5500) — shorter games | V26.05 patch |
| Nexus turret HP | **3000** (from 1800) — harder lane push | V26.05 patch |
| Hail of Blades (ranged) bonus AS | **80%** (modified from standard) | Patch history |
| Press the Attack | **120–360 (lvl)** dmg + 15% amp | Patch history |

### Disabled / replaced systems
- **Runes are entirely disabled** (replaced by augment system)
- **Exhaust** summoner spell is disabled
- All other ARAM summoner rules apply (Mark/Dash + Flash, snowball)

### Base stat overrides (vs standard ARAM)
- Melee: 20–600 base HP scaling, **+15 armor & MR**
- Ranged: 20–400 base HP scaling, 2–25 armor/MR (currently bugged at 0 per Wiki)
- All: **+10% mana / energy regen**

---

## Modifier stacking + scope

- All listed stat modifiers above are **constant Mayhem field** — they apply
  to **both teams equally**, all game.
- **Augments are per-player and asymmetric** — each of the 10 players gets
  3 augment offerings (1 reroll allowed) at 4 selection windows: **start
  (~lvl 3), lvl 7, lvl 11, lvl 15**. Tier escalates through the windows
  (Silver → Gold → Prismatic).
- Augments can **only be selected while dead** — a strategic incentive to
  die at augment-window timing if you're alive at lvl 7/11/15.
- Champion-specific incoming-dmg and healing modifiers from regular ARAM
  still apply (e.g. Sett, Sion, Illaoi outgoing dmg adjustments per V26.06).

---

## Build implications vs regular ARAM

Mayhem's "stat field" is mostly **upward-shifted offense** plus a hard
cap on infinite CC chains. Item priority shifts vs regular ARAM:

| Category | Direction | Why | Items more / less valuable |
|---|---|---|---|
| **Crit (AD)** | UP | AS cap raised to 5.0 + crit overflow → AD/AP. Stacking past 100% crit is a real curve. | **IE, Phantom Dancer, Collector** more valuable; **Yun Tal/Navori** scale further |
| **Attack speed** | UP | 5.0 cap means on-hit / hyper-carry curves don't plateau. | **Wit's End, Kraken, Terminus, Nashor's** all scale longer |
| **Tenacity** | DOWN (slightly) | Combo Breaker auto-cleanses long CC chains. Solo tenacity items lose marginal value vs regular ARAM. | **Mercury's** still core; **Sterak's** somewhat redundant with mode tenacity ramp |
| **Healing** | NEUTRAL | Per-champion healing mods unchanged from ARAM. | No global shift |
| **Burst defense** | UP | Augments enable ridiculous burst (Blade Waltz, Dropkick). Single survival item more important. | **Maw, Zhonya's, GA, Edge of Night** all stronger |
| **Lucidity / Black Cleaver / Cosmic Drive (AH)** | DOWN-when-augmented | Bread/Butter/Cheese/Jam augments grant **+100 AH per ability** — if rolled, AH items become wasted stats | If you grab any "Bread" augment, drop 2nd AH item |
| **Mobility creep** | UP | Dashing (175 AH on dashes), Flashy (3-charge Flash) make mobility-cancelling items essential | **Stridebreaker, Dead Man's** less needed for chase; **Randuin's, Frozen Heart** for slow-stacking |
| **Penetration** | UP | Erosion silver augment stacks **30% resist shred** on enemy team. | **Void Staff / LDR** earlier if multiple enemies build resist |
| **Heal/Barrier sums** | UNCHANGED | Heal/Barrier untouched by Mayhem (Exhaust is the only disabled summ). | No change |

### Fast heuristics for the coach
- If mid-game player has AH-granting augment (Bread/Butter/Cheese/Jam,
  Dashing) → **suppress** any AH-prioritizing build path.
- If player has a crit augment (Deft, Blunt Force enabling AD scaling) →
  **prioritize** crit chain (Collector → IE → PD → LDR).
- If enemy team has 2+ knockup-augment users (Bounce of the Poro King,
  Growth Spurt) → tenacity items still recommended; Combo Breaker only
  cleanses *concurrent* chains.
- Penetration spike (Erosion) on either team → swap MR/armor item slot
  earlier than usual.

---

## Mayhem-only items

Confirmed exclusive items (Wiki ARAM: Mayhem):
- **Atma's Reckoning**
- **Rite of Ruin**
- **Sword of Blossoming Dawn** (Upgrade variant nerfed in 26.9 — lost
  basic-attack damage penalty removal effect)
- **Stat Bonus** (requires lvl 9; passive stat purchase)

These will not appear in `data/meta_build/aram_champion_builds.json` since
they don't exist in regular ARAM. Coach should **not** suggest these
unless mode is detected as Mayhem.

### Augment system summary
- ~40+ Mayhem-original augments + selected Arena augment imports
- Tiers: **Silver** (60 AS, +20% AD type), **Gold** (100 AH per ability,
  Flash-charges), **Prismatic** (Blade Waltz, Bounce of the Poro King,
  Can't Touch This — game-warping)
- Riot deliberately avoided always-on augments for teamfight readability;
  most are auto-cast on cooldown
- Notable Prismatics:
  - **Blade Waltz** — blinks to up to 6 enemies w/ on-hit
  - **Dashing** — +175 AH to dashes/blinks
  - **Flashy** — 3 Flash charges, 2s between
  - **Can't Touch This** — 2s invuln on ult, 8s CD
  - **Bounce of the Poro King** — Poro King transform w/ knockback bounces
  - **Growth Spurt** — knock up enemies in 400u for 1s
  - **Executioner** — basic-ability CD reset on takedown
  - **Donation** — +1750 gold instant

---

## Top 10 picks in Mayhem (patch 26.9)

**Source caveat:** Two sources give different orderings (AGGREGATOR N winrate
list vs arammayhem.com curated tier list). AGGREGATOR N's site requires JS
(403'd direct fetch). Numbers below are aggregated from search snippets
+ arammayhem.com tier article. **Treat as soft signal, not authoritative.**

| # | Champion | Tier / WR | Key augment synergy |
|---|---|---|---|
| 1 | **Kassadin** | S+ (highest WR) | Slaughter Time, Silver Moon, Eureka Final Form |
| 2 | **Vayne** | S+ (~54.5% WR) | Dual Blade — % true dmg shreds tanks |
| 3 | **Brand** | S+ (~55.9% WR) | Infernal Conduit — zero-CD spam |
| 4 | **Lillia** | S (~57–59% WR) | Infernal Conduit + Leg Day (DoT + MS) |
| 5 | **Naafiri** | S | Executioner — basic-ability resets on takedowns |
| 6 | **Galio** | S | Flexible — full damage with innate tankiness |
| 7 | **Maokai** | S | AOE CC after ARAM debuff lift |
| 8 | **Aurora** | S | Snowball Upgrade — broad augment flex |
| 9 | **Ekko** | S | Dual Blade + ARAM-specific buffs |
| 10 | **Ryze** | S | Single-combo deletion; low pickrate edge |

**Aggregator C's WR-only top 10** (separate methodology, snippet-only):
Brand 55.88%, Vayne 54.45%, Yasuo 55.30%, Lillia 59.21%, Morgana 54.30%,
Graves 53.32%, Jinx 53.12%, Aurelion Sol 52.74%, Sett 52.07%, Mundo 51.58%.

**Mayhem-segmented tier data DOES exist** at:
- AGGREGATOR N `/lol/mayhem/tier-list` and `/lol/mayhem/stats` (hourly refresh, separate from regular ARAM)
- Overlay App E `/lol/tierlist/aram-mayhem`
- arammayhem.com (dedicated site, includes augment-pairing winrates)
- Aggregator C has Mayhem patch notes but their main ARAM tier list lumps both

This means RC **could** scrape Mayhem-specific WR for the coach if
desired (none of these has a public API — would need HTML scrape).

---

## Rotation cadence

- **Permanent**, not rotating. Confirmed by Riot 2026-01 and reaffirmed
  multiple times since.
- Released 2025-10-22 with Trials of Twilight Act II.
- "Extended for 2026" announcements explicitly said it stays available
  alongside standard ARAM as a separate queue.
- Riot has stated "more content coming" — expect new augments / map
  modifiers per patch but the queue itself is stable.
- Per-patch tuning happens (26.9 example: Bard/Ornn buffs, Sword of
  Blossoming Dawn nerf, Health Relic buff, Prom Queen nerf).

> **RC implication:** since Mayhem is permanent + has a separate queue,
> mode detection should distinguish `KIWI` from regular ARAM and route
> to a Mayhem-aware coach path. Currently RC maps Mayhem → MODE_ARAM,
> which means the coach is missing: (a) augment context, (b) Mayhem-only
> item awareness, (c) the AS-cap-5.0 / crit-overflow build math.

---

## Sources fetched (URL + timestamp + notes)

All fetches: 2026-05-02.

| URL | Notes |
|---|---|
| https://wiki.leagueoflegends.com/en-us/ARAM:_Mayhem | Primary — global stat overrides, augment system, Mayhem-only items |
| https://wiki.leagueoflegends.com/en-us/ARAM:_Mayhem/Augments | Augment list by tier; representative top-impact entries |
| https://wiki.leagueoflegends.com/en-us/ARAM:_Mayhem/Patch_history | Patch history through V26.06; **does NOT have 26.9 yet at fetch time** |
| https://arammayhem.com/patch-notes | Patch 26.9 (2026-04-28) changes — Bard, Ornn, Health Relic, augment nerfs |
| https://arammayhem.com/articles/aram-mayhem-tier-list-patch-26/ | Curated S+/S tier list — Kassadin, Vayne, Brand top |
| https://www.leagueoflegends.com/en-us/news/dev/dev-bringing-mayhem-to-aram/ | Riot dev blog — design intent, augment philosophy, separate queue |
| https://aggregator-c.invalid/lol/guides/aram-mayhem-patch-notes | 26.9 confirmation; no Mayhem-segmented WR table on this page |
| WebSearch (multiple) | Top-WR snippets from Aggregator C-style aggregator (Brand 55.88%, Lillia 59.21%, etc.) |
| https://overlay-app-e.invalid/lol/tierlist/aram-mayhem | **403** on direct fetch (bot wall); known to exist as Mayhem-only tier list |
| https://aggregator-n.invalid/lol/mayhem/tier-list | **402** on direct fetch (paywall/JS); known to host Mayhem-only WR data |
| https://support-leagueoflegends.riotgames.com/hc/en-us/articles/45460878435987 | **403** on direct fetch; official Riot support page exists |

### Source-confidence notes
- **High confidence (Riot patch notes / Wiki):** Stat modifier table,
  augment selection mechanics, disabled features (runes/Exhaust),
  Mayhem-only item names, permanent-queue status.
- **Medium confidence (3rd-party aggregator):** patch 26.9 detailed
  changes, exact augment numbers (e.g. Bard +6%–7.5% per 100 AP).
- **Soft signal (search snippets only):** specific top-10 winrates.
  arammayhem.com tier list and Aggregator C WR list disagree on ordering;
  both look credible. Use only as directional weight.
