# LoL Wiki as a DS supplementary data source - feasibility probe (2026-05-30)

Item 216 carry (a). Question: does wiki.leagueoflegends.com (the post-Fandom
wiki.gg-hosted MediaWiki instance) expose structured champion ability data that
RC's Meraki dump LACKS, and could it feed a Daemon Slayer schema lift?

All probes below are LIVE HTTP against the wiki MediaWiki API on 2026-05-30 -
verbatim response snippets included as proof (not from training data; the wiki
migrated off Fandom + dropped Cargo for a custom "Bucket" extension, so prior
knowledge is stale).

VERDICT up front: **GO (conditional)** - the wiki carries several combat-relevant
fields the Meraki dump does not, queryable via a public read-only API. But it is
a SUPPLEMENT, not a replacement: the per-ability CC durations + ratios still live
in free-form `leveling`/`description` text (same parse problem RC already solved
against Meraki), so the high-value net-new wins are the STRUCTURED scalar fields
(cast/windup timing, missile speed, Arena/URF/NB mode multipliers, charge/recharge),
not a magic CC-duration table.

> MERGER CORRECTION (2026-05-30, verified vs live code before commit): the agent's
> original "mode multipliers are the biggest win / fix the ARAM gap" claim is
> OVERSTATED and is the known false-claim pattern (feedback_verify_generated_reports).
> ARAM mode mults are NOT a DS gap - Meraki `aram_modifiers` already carries the
> full ARAM set (dealt/taken/healing/shielding/tenacity/AH/AS) and DS already
> applies aramDamageDealt (dps.py:583) + aramDamageTaken (ehp.py:11) + aramTenacity
> (ENGINE 1.25.0). The wiki mode-mult win is net-new ONLY for the modes Meraki
> omits: Arena (CHERRY), URF, Nexus Blitz, One-for-All. The honest top net-new
> wins are AA-timing + static-CD flags + charge model; Arena-mode mults are a
> narrower (Arena-coaching-lane-only) win. Findings below corrected inline.

---

## 1. Probe results (live, verbatim)

### 1a. Cargo is GONE - Bucket replaced it

`GET /en-us/api.php?action=cargoquery&tables=ChampionAbilities&...&format=json`

    {"error":{"code":"badvalue","info":"Unrecognized value for parameter
    \"action\": cargoquery.", ...},"servedby":"mediawiki-697868d8d9-hhfsg"}

Cargo extension is NOT installed. The task brief assumed Cargo; that assumption
is stale. (The OLD Fandom wiki had Cargo; wiki.gg migration dropped it.)

### 1b. Installed extensions (siteinfo)

`GET /en-us/api.php?action=query&meta=siteinfo&siprop=extensions&format=json`

Returned 74 extensions. Relevant ones present: **Bucket**, **Scribunto**
(Lua modules), **VariablesLua**, **ParserFunctions**, **TemplateData**,
**Parsoid**, **CirrusSearch/Elastica**. Explicitly ABSENT: **Cargo**,
**SemanticMediaWiki**. So the structured-data layer is Bucket + Scribunto Lua,
not Cargo/SMW.

### 1c. Available API actions

`GET /en-us/api.php?action=help&modules=main&format=json`

action= accepts (relevant subset, verbatim): `bucket` ("Query bucket through
Lua."), `query`, `parse`, `expandtemplates`, `scribunto-console`. NO `cargo`.

### 1d. action=bucket is externally callable

`GET /en-us/api.php?action=help&modules=bucket&format=json`

    "Query bucket through Lua." - required param: `query` (a Bucket Lua
    statement). Requires READ rights only. No edit/login needed.

This is the structured-query path: a caller passes a Bucket Lua SELECT-like
statement and gets rows back. (Bucket = weirdgloop's SQL-like-over-Lua store,
the wiki.gg replacement for Cargo; github.com/weirdgloop/mediawiki-extensions-Bucket.)

### 1e. Champion DATA module - stats + ability-slot names, NOT per-ability detail

`Module:ChampionData/data` exists (pageid 1401029). Its doc
(`Module:ChampionData/data/doc`) enumerates the per-champion schema:

  - identity: `id`, `apiname`, `title`, archaic ratings `attack/defense/magic`
  - `resource`, `rangetype`, `role`, `adaptivetype`
  - `stats{}`: hp_base/hp_lvl/hp5_base/hp5_lvl, mp_*, arm_*, mr_*, dam_base/dam_lvl,
    as_base/as_ratio/as_lvl, crit_base/crit_mod, **missile_speed,
    attack_cast_time, attack_total_time, attack_delay_offset, windup_modifier**,
    range, ms, gameplay_radius, acquisition_radius, selection_radius,
    pathing_radius
  - mode-balance overrides: **`aram`, `urf`, `nb`, `ofa`, `usb`, `ar`, `swift`**
    (per-mode damage-dealt/taken/healing multipliers)
  - `skill_i/q/w/e/r` (ability ICON names only) + `skills` (slot ordering)

So `/data` is champion-LEVEL stats + ability slot names. It does NOT hold
per-ability cooldown/ratio/CC.

### 1f. Per-ability detail lives in `Template:Ability data`

`Template:Ability data` is the standardized per-ability parameter schema.
Documented params (verbatim, relevant subset):

  - timing/cd: **`cast time`, `static`, `cooldown`, `cdstart`, `ontargetcd`,
    `ontargetcdstatic`, `recharge`, `queue time`**
  - cost: `cost`, `costtype`
  - range/move: `range`, `target range`, `attack range`, `speed`
  - geometry: `collision radius`, `effect radius`, `width`, `angle`,
    `inner radius`, `tether radius`
  - mechanics: `projectile`, `targeting`, `affects`, `damagetype`, `spelleffects`,
    **`knockdown`, `silence`, `grounded`, `callforhelp`, `parry`, `spellshield`**
  - text: `description`..`description6`, `leveling`..`leveling6`, `icon`..`icon6`

CRITICAL: there are NO dedicated CC-DURATION params (no stun/snare/root/knockup
seconds field). CC magnitudes are embedded in the free-form `leveling` /
`description` strings - the exact same parse surface RC already mines from
Meraki `effects[].description` (the ENGINE 1.46.0 `effects_descriptions` lift).

### 1g. Live module serve PROVEN

`GET /en-us/api.php?action=expandtemplates&text={{#invoke:ChampionData|get|Aatrox|attack_cast_time}}&prop=wikitext&format=json`

    "0.30000001192093||"

Real live float (Aatrox attack windup cast time 0.3s). The compound call's
2nd+3rd subfields (missile_speed, aram) returned empty - `get` needs the
`stats.` sub-path for nested fields, a minor query-shape detail. The point is
PROVEN: the module API returns live structured champion data to an
unauthenticated read caller.

### 1h. robots.txt / ToS

`GET /robots.txt`:
  - `Disallow: /*api.php`  (also `/en-us/Special:`, `/en-us/Bucket:`)
  - NO `Crawl-delay` directive.

api.php is disallowed for CRAWLERS. Read-only API use for a handful of
per-patch pulls is standard MediaWiki practice and not a bulk crawl, but the
honest read is: respect it - do a small, infrequent (per-patch, ~1/2 weeks)
batch with a descriptive User-Agent, OR use `Special:Export` (XML dump of the
data module, the crawler-blessed bulk path) instead of hammering api.php.
wiki.gg content is CC-BY-SA; attribution required if any text is surfaced
verbatim (RC surfaces computed numbers, not prose, so low risk).

---

## 2. Field comparison - wiki vs Meraki/RC

RC sample = `data/daemon_slayer/16.11.1/champion_abilities.json` Aatrox Q form 0.
RC already has: cooldown[], cost[], damage_type, targeting, affects, resource,
parent_resource, is_aoe, cast_time, notes, damage_blocks[] (typed ratios via
_UNIT_TO_FIELD), effects_descriptions[].

| Wiki field | Meraki/RC has it? | DS could use it for | Notes |
|---|---|---|---|
| `cast time` (per ability) | YES (`cast_time`) | cast-gated CC, DPS windup | redundant - RC ENGINE 1.51.0 lift covers it |
| `cooldown` / `static` (static CD) | PARTIAL - RC has cooldown[], NOT the static-CD flag | haste-immune CD math, true rotation DPS | **NET-NEW: `static`/`ontargetcdstatic`** = which CDs ignore Haste |
| `recharge` + charges/ammo | NO | ammo-stacking DPS (Corki/Teemo/Graves/Riven-passive) | **NET-NEW** - Meraki dump has no charge model |
| `speed` (missile speed) per ability | NO (RC only has champ-level via none) | skillshot travel-time, effective-range DPS | **NET-NEW** at ability granularity |
| `attack_cast_time`/`attack_total_time`/`windup_modifier`/`attack_delay_offset` | NO | AUTO-ATTACK DPS windup precision, on-hit cadence | **NET-NEW + high value** - RC AA DPS uses simpler AS model |
| `missile_speed` (champ AA) | NO | kited-DPS, projectile AA travel | **NET-NEW** |
| mode multipliers `aram`/`urf`/`nb`/`ar` | ARAM YES (Meraki) / Arena+URF+NB NO | Arena/URF/NB-correct EHP+DPS | **NET-NEW for Arena/URF/NB ONLY.** ARAM is NOT a gap: Meraki `aram_modifiers` already carries dealt/taken/healing/shielding/tenacity/AH/AS and DS already applies dealt (dps.py:583) + taken (ehp.py:11) + tenacity (ENGINE 1.25.0). Meraki has NO cherry/arena mults -> wiki is the source there. |
| `knockdown`/`silence`/`grounded`/`parry`/`spellshield` (bool flags) | PARTIAL via text only | typed CC class without text-parse | **NET-NEW structured CC TYPE flags** (not durations) |
| `collision/effect/inner/tether radius`, `width`, `angle` | NO (RC has only is_aoe bool) | AoE-hit-count modeling, tether mechanics | NET-NEW geometry; lower DS priority |
| `costtype` | YES (resource/parent_resource) | resource gating | redundant |
| CC DURATION (stun/root/snare seconds) | NO (text only, both sources) | the cc_conditional registry | **NOT structured on wiki either** - same `leveling`/`description` parse as Meraki. NO win here. |
| ratios/scaling (AD%/AP%/HP%) | YES (typed `damage_blocks` via _UNIT_TO_FIELD) | DPS math | RC's typed map is RICHER than wiki's raw `leveling` text |

---

## 3. GO / NO-GO

**GO (conditional / supplement).** The wiki is a viable supplementary source.
It is NOT a replacement and does NOT solve the CC-duration parse problem (CC
seconds are free-text on BOTH sources). But it carries STRUCTURED scalar fields
Meraki lacks, each unblocking a distinct DS math lane:

Top net-new fields worth extracting (ranked by DS value):

1. **Arena / URF / NB mode-balance multipliers** (`ar`, `urf`, `nb`, `ofa`) -
   champ-level damage / healing / tenacity deltas for the NON-ARAM modes. MERGER
   CORRECTION: ARAM is NOT a gap - Meraki `aram_modifiers` already carries the
   full ARAM set and DS already applies aramDamageDealt (dps.py:583), aramDamageTaken
   (ehp.py:11), and aramTenacity (ENGINE 1.25.0). The net-new win is ONLY the modes
   Meraki omits: Arena (CHERRY), URF, Nexus Blitz, One-for-All. Real but narrower
   than first stated - relevant to the Arena coaching lane only.
2. **Auto-attack timing** (`attack_cast_time`, `attack_total_time`,
   `windup_modifier`, `attack_delay_offset`, champ `missile_speed`) - precise
   AA windup + projectile travel. Unblocks accurate sustained-AA DPS + kited-DPS
   (marksman fight-window math). RC's current AA model is coarser.
3. **Static-cooldown flags** (`static`, `ontargetcdstatic`) - which ability CDs
   ignore Ability Haste. Unblocks correct rotation-DPS under Haste items
   (currently DS may over-credit Haste on static-CD spells).
4. **Charge/ammo model** (`recharge` + charge count) - ammo-stacking champs
   (Corki, Teemo, Graves, Kindred-passive-adjacent). Meraki dump has zero charge
   data. Unblocks per-cast frequency for charge-based abilities.
5. **Typed CC-class flags** (`knockdown`, `silence`, `grounded`, `parry`,
   `spellshield`) - structured booleans for CC TYPE (not duration). Lets the
   cc_conditional registry classify a spell's CC kind without text-parsing,
   even though duration still needs the text.

NO-GO sub-claim: do NOT expect a structured CC-duration table. Both wiki and
Meraki bury stun/root/knockup seconds in `leveling`/`description` prose. The
wiki's `leveling` text is arguably PARSE-EQUIVALENT to Meraki's, and RC's typed
`damage_blocks` map is already richer than the wiki's raw text. So the wiki adds
NOTHING to the ratio/CC-duration lanes.

---

## 4. Integration plan IF go

**Reusability of the existing normalizer:** PARTIAL. The operator's instinct
("unit-map + form-stitching is the reusable part") is HALF right:

  - REUSABLE: the form-stitching mental model (P/Q/W/E/R, multi-form per key)
    and the typed-scaling philosophy carry over conceptually.
  - NOT directly reusable: `tools/daemon_slayer_abilities_extract.py` is shaped
    around Meraki's JSON `modifiers[].values[]`/`units[]` schema. The wiki serves
    either (a) Lua-table source (parse a `return {...}` table) or (b) Bucket-API
    JSON rows or (c) `expandtemplates` wikitext. None match Meraki's JSON shape,
    so `_normalize_modifiers` / `_normalize_cooldown_or_cost` / `_build_damage_block`
    do NOT apply 1:1. The `_UNIT_TO_FIELD` map would only be reused IF we also
    text-parse the wiki `leveling` strings (not recommended - Meraki already
    wins that lane).

**Recommended architecture:** a SEPARATE thin extractor,
`tools/daemon_slayer_wiki_stats_extract.py`, that pulls ONLY the structured
scalar fields above (mode mults + AA timing + static-CD + charges + CC-type
flags) and writes a SIDECAR file `data/daemon_slayer/<patch>/champion_wiki_stats.json`
keyed by the same DDragon champion name anchor RC already uses. DS engine then
MERGES the sidecar onto the Meraki-derived ability records by champ name. Keep
Meraki as the ratio/CC-duration source-of-truth; layer the wiki sidecar for the
5 net-new lanes. This avoids any re-parse of overlapping data.

**Extraction path (3 options, pick one):**
  - BEST: `action=bucket` with a Lua SELECT over the ability-data Bucket table
    (if abilities are bucketed) + `Module:ChampionData|get` for champ stats.
    Clean JSON rows, no Lua-table parse.
  - FALLBACK: `Special:Export` XML dump of `Module:ChampionData/data` (one
    request, crawler-blessed) + a Lua-table -> dict parser (the `/data` module is
    a literal `return {...}`; lupa or a small regex/AST-lite parser handles it).
  - LAST RESORT: `expandtemplates` per-field (proven live in 1g, but chatty).

**Effort estimate:** ~1-1.5 sessions. MERGER CORRECTION to ROI ranking: since ARAM
mults are already covered by Meraki, the highest-ROI net-new lane is AA-timing
(item 2, materially improves marksman/AA DPS) + static-CD flags (item 3, fixes
Haste over-credit), with Arena/URF mode-mults (item 1) as a narrower Arena-only
win. AA-timing + static-CD + charges are each a small additive field set on top
of the same sidecar.

**Risk:**
  - ToS / rate: api.php robots-disallowed (1h). Mitigate: low-frequency per-patch
    pull + descriptive UA, or `Special:Export`. CC-BY-SA attribution if any prose
    surfaced (RC surfaces numbers, low risk).
  - Freshness: wiki is community-edited; lags Riot patches by hours-to-days and
    can carry transient errors. Meraki (data-dragon-derived) is more authoritative
    for ratios. Use wiki ONLY for the fields Meraki lacks; never let it override a
    Meraki ratio. Pin the wiki pull to the same patch label RC already tracks
    (`data/daemon_slayer/current.txt`) and accept it may trail by a few days.
  - Lua-table parse complexity: moderate if using `Special:Export` (the `/data`
    module is large but flat-ish); avoidable entirely via `action=bucket` JSON.
  - Mutable-source rule: same discipline as Meraki `latest` - snapshot per patch,
    never trust a live re-query mid-engine.

---

## 5. Bottom line

Single most important finding: the LoL wiki's net-new value is the STRUCTURED
SCALAR fields Meraki omits - **auto-attack timing (windup/missile speed),
static-cooldown flags, charge/ammo model, and the NON-ARAM mode multipliers
(Arena/URF/NB)** - NOT a CC-duration table (CC seconds are free-text on both
sources, and RC's typed ratio map already beats the wiki on the overlap), and
NOT ARAM mode mults (already covered by Meraki `aram_modifiers` + applied by DS).
GO as a sidecar supplement via `action=bucket`; build a thin new wiki-stats
extractor rather than retrofitting the Meraki normalizer; keep Meraki
authoritative for ratios/CC + ARAM mults.
