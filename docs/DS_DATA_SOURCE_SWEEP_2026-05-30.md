# DS / RC missing-data source sweep - exhaustive (2026-05-30)

Question: beyond the wiki + CommunityDragon already tapped (items 221/224), what
OTHER sites/sources can supply the data DS/RC lacks? Investigate each deeply,
trace to upstream, exhaust all paths.

Method: 5 parallel investigation agents, each on a distinct lens, every claim
grounded in a verbatim live fetch this session (Legion host). Spot-verified the
two highest-value net-new claims by hand before writing.

VERDICT up front: **the source space is EXHAUSTED.** The LoL data ecosystem has
exactly FOUR upstream layers - DDragon (base stats), CommunityDragon RAW (the
game's own WAD bins, the deepest published layer), Meraki lolstaticdata (item
passives + ability ratios, parsed from the bins), and the LoL wiki (community-
curated structured params + ChampionData). EVERY other site is downstream: a
closed-source re-implementation of those four (the theorycraft calculators) or a
Riot Match-V5 win-rate aggregator (everyone else). ZERO net-new structured
ability/CC/mode math exists downstream. The genuinely-new extractable data all
lives in the wiki + CDragon (sources RC already reaches); the perennial CC-
duration-in-seconds gap is a TRUE CEILING - structured nowhere, free-text on
Meraki/wiki only.

---

## 1. The 4-layer upstream map (and why it bottoms out)

```
Riot game install (.wad.client archives)        <- the actual game data
        |  CDTB / ritobin unpack + convert (XXH64-hashed paths)
        v
CommunityDragon RAW (raw.communitydragon.org)    <- DEEPEST published layer
   - game/data/characters/<slug>/<slug>.bin.json  (spell bins)
   - plugins/.../v1/champions/<id>.json           (pre-parsed champ JSON)
   - game/items.cdtb.bin.json                     (item bins, 14.7MB)
   - game/data/maps/shipping/map30/map30.bin.json (Arena, hash-obscured)
        |
        +-- Meraki lolstaticdata (parses the bins -> item passives + ratios)
        +-- DDragon (Riot official base stats; Meraki parses this too)
        +-- LoL wiki ChampionData + Template:Data (human editors, some bin-derived)
        |
        v
DOWNSTREAM (calc.gg, lolsolved, aggregator B, aggregator A, aggregator D, aggregator C, overlay app E,
overlay app F, aggregator P, esports stats site Z3, esports stats site Z2, pro-build site Z4, aggregator H)
   - re-serve the 4 above, OR aggregate Match-V5 win-rates. NET-NEW: nothing.
```

Exhaustion proof: a local install parsed via CDTB/ritobin yields byte-equivalent
`.bin` content to what CDragon already publishes (confirmed: CDragon's own docs
say RAW is "directly scraped from the game client and the LCU"). The ONE layer
deeper that holds CC durations - the compiled buff SCRIPTS - is NOT exposed
(probed `.../scripts/<spell>.bin.json` + `.../<champ>.bin.lua` -> both HTTP 404).
So nothing below CDragon is queryable. The ceiling is real.

---

## 2. Per-bucket verdict (the 8 gaps from LOLMATH_WIKI_SOURCE_2026-05-30.md)

| # | Gap | Verdict | Source (lowest-effort) | Effort | Proof |
|---|---|---|---|---|---|
| A | CC durations (stun/root/snare seconds) | **CLOSED - true ceiling** | none structured; Meraki/wiki free-text only | n/a | CDragon BuffData = loc-string only (Leona Q `mBuff.mDescription="game_buff_tooltip_LeonaShieldOfDaybreak"`, no number); buff scripts 404; wiki Ashe R duration only in `{{tip|stun}}...{{pp|...}}` prose; CDragon v1 only when desc names the placeholder (Leona Q works `Effect1Amount=[1.0..]`, Nautilus Q "briefly" fails) |
| B | Mode mults URF/OFA/USB/NB | **NOW** | wiki `Module:ChampionData/data` raw, `stats.<mode>` | LOW (same raw-scan RC uses for cast time) | raw module 379274 B carries 102 urf / 82 ofa / 45 usb / 32 nb blocks (verified in-hand); Aatrox `stats.urf={dmg_dealt 1.15, dmg_taken 0.7}`, Brand `nb={dmg_dealt 0.9, dmg_taken 1.08}` |
| B' | Mode mults Arena (CHERRY) + Swiftplay | **CLOSED (champ dmg) / FUTURE (item-side)** | no champ dmg-mult anywhere; item-side = CDragon `items.cdtb.bin.json` `DataValuesModeOverride` (hashed keys) | HIGH (item-side, unhash) | wiki `ar` 45 blocks, 0 carry dmg_dealt/taken (only base-stat overrides: `Ziggs ar={hp_lvl 17}`); `swift` 13 blocks, 0 dmg mult; map30 bin hash-obscured (`mPerChampionModifiers`=0 clear-text) |
| C | Static-cooldown flag (ignores Haste) | **NOW** | wiki `Template:Data <Champ>/<Ability>` `static` param | MEDIUM (per-ability wikitext + regex) | `Template:Data Anivia/Glacial Storm` -> `\|static = 1` verbatim |
| D | Charge / ammo model | **NOW - clean win** | CDragon v1 `champions/<id>.json` `ammo:{maxAmmo,ammoRechargeTime}` | LOW (no hash traversal) | verified in-hand: Ashe E `maxAmmo=[2,2,2,2,2,2]`, `ammoRechargeTime=[90,80,70,60,50,50]`; Corki R raw bin `mMaxAmmo=[4,4,4,4,4,4,4]` |
| E | AA timing for the 110 unmeasured champs | **CLOSED - true ceiling** | none (render-default only) | n/a | confirmed item 224 + this sweep: stored only on override; the 110 carry no explicit value in wiki OR CDragon |
| F | Typed CC-class flags | **NOW** | wiki `Template:Data` knockdown/silence/grounded/spellshield/parry (rich) + CDragon `mSpellTags` (coarse) | LOW-MED | wiki Corki Valkyrie `\|grounded=True \|knockdown=True`; CDragon Leona Q `mSpellTags=[...,"Trait_ImmobilizingCCSpell"]` |
| G | Per-ability missile speed (skillshot travel) | **NOW** | CDragon raw bin `mSpell.missileSpeed` / `mMissileSpec` | LOW-MED (pick missile sub-record) | Morgana Q 1200, Ashe R 1600, Leona E missile sub-record 2000 (cast record shows 0) |
| H | AoE geometry (radius/width/angle) | **PARTIAL / FUTURE** | CDragon `castConeDistance`/`castConeAngle` (clean) + `castRadius` (conflated) + wiki `effect radius` (markup) | MED + hand-validate | Nautilus W cone `dist=1400 angle=20.0` clean; `castRadius` defaults to boilerplate 210 on many spells - not safe to bulk-trust |

---

## 3. Downstream site sweep - ALL CLOSED (the literal "what other sites" answer)

| Site | Reachable | Public data | Upstream traced | Verdict |
|---|---|---|---|---|
| calc.gg | yes | per-entity REST | **Meraki lolstaticdata** (cited in its own HTML) + DDragon; ability math is server-side Python, never shipped | CLOSED |
| lolsolved.gg | yes | none client-side | closed server-side model (DDragon/Meraki-class behind backend) | CLOSED |
| lolmath (.lol/.com) | **DEAD** | n/a | `.lol` dead DNS; `.com` parked/for-sale | CLOSED (defunct) |
| aggregator P | yes (GitHub) | aggregate SQLite | **"All data is sourced from Aggregator B"** (its README) | CLOSED |
| aggregator B | yes | GraphQL + stats2 CDN | Riot Match-V5 aggregated + DDragon; schema is all win-rate (`fetchPerformanceScore`...) | CLOSED |
| aggregator A | yes | REST + official MCP | Match-V5 aggregated + DDragon; MCP docs say "not granular mechanical data" | CLOSED |
| aggregator D / overlay app E / overlay app F / aggregator C | partial (some Cloudflare-block) | win-rate JSON | Match-V5 aggregated + DDragon | CLOSED |
| esports stats site Z3 / esports stats site Z2 / pro-build site Z4 / aggregator H | yes/partial | esports/pro tables | pro Match data | CLOSED |

Synthesis: the theorycraft calculators (the only tier that COULD have carried
net-new math) hand-code it server-side and ship none as data - calc.gg even tags
item passives "NOT IMPLEMENTED", the same one-by-one model as DS itself. Every
other site is a Match-V5 win-rate aggregator. The downstream tier is worth
NOTHING for DS math beyond the 4 upstreams.

---

## 4. Net-new actionable for DS, ranked (all from wiki + CDragon - already reached)

1. **Charge/ammo (D)** - CDragon v1 `champions/<id>.json`, clean per-rank arrays,
   low effort, real DPS-cadence impact (Corki/Teemo/Graves/Heimer/Mundo ammo).
2. **URF/OFA/USB/NB mode mults (B)** - wiki ChampionData `stats.<mode>` raw-scan,
   same one-request path as cast time; ~96/69/35/28 champs. Arena lane: stat
   overrides only (no dmg mult), apply at the stat layer not as an ARAM-style mult.
3. **Per-ability missile speed (G)** - CDragon raw bin, skillshot fight-window math.
4. **Static-CD flag (C)** - wiki `Template:Data` `static`; fixes Haste over-credit
   on static-CD spells.
5. **Typed CC-class flags (F)** - enrichment; coarse from CDragon `mSpellTags`,
   richer from wiki `Template:Data` booleans.
6. **AoE geometry (H)** - partial; opt-in per-spell with hand-validation.

A single extension to the existing CDragon walk (`daemon_slayer_wiki_stats_extract.py`
+ `daemon_slayer_abilities_extract.py`) + a thin wiki `Template:Data` fetcher
covers items 1-5. CC durations (A) + the 110 AA-timing champs (E) get NOTHING new.

---

## 5. CLOSED negatives - do NOT re-research

- **CC durations in seconds**: structured on NO source. CDragon buff records hold
  only loc-string keys; the buff scripts that hold the numbers are not published
  (404). Wiki + Meraki carry them only as `leveling`/`description` prose. This is
  a true data ceiling - stays the hand-curated / text-parse path RC already uses.
- **AA timing for the 110 unmeasured champs**: render-default only; not stored in
  any source. Ceiling confirmed twice (item 224 + this sweep).
- **Arena (CHERRY) champion damage multiplier**: does not exist as a mult; Riot
  tunes Arena via per-level base-stat scaling + augments/economy. Wiki `ar` = stat
  overrides only.
- **All downstream sites** (calc.gg, lolsolved, lolmath, aggregator B, aggregator A, aggregator D,
  aggregator C, overlay app E, overlay app F, aggregator P, esports stats site Z3, esports stats site Z2,
  pro-build site Z4, aggregator H): re-serve the 4 upstreams or aggregate Match-V5.
- **Anything below CDragon** (local WAD via CDTB/ritobin): byte-equivalent to
  CDragon's published bins; no gain. No community project publishes pre-decoded
  spell-effect JSON (bins have "no unified format", per CDragon's own docs).

---

## 6. Access + extraction notes (corrections to prior docs)

- **wiki alias UA correction** (refines `reference_lol_wiki_access` + item 224):
  `wiki.leagueoflegends.com` is reachable, BUT a browser-like UA (`Mozilla/5.0`)
  trips a Cloudflare challenge -> HTTP 403; a NON-browser UA (e.g.
  `RiotCommander-DaemonSlayer/1.0`) passes -> 200. The extractor's UA already
  works; do NOT switch it to a browser UA.
- **wiki mode blocks are nested under `["stats"]`**, not top-level; and the
  `{{#invoke:ChampionData|get|...}}` expandtemplates getter returns empty for
  these (and even for the `stats.attack_cast_time` control) - use the action=raw
  brace-scan keyed by `apiname` (RC already does this), NOT the getter.
- **CDragon patch-pin URL is 2-segment**: `/16.11/` works, `/16.11.1/` 404s. Map
  `current.txt` `MAJOR.MINOR.x` -> `MAJOR.MINOR` for reproducible snapshots.
- **CDragon v1 vs raw bin**: v1 `champions/<id>.json` gives cooldown/cost/ammo
  with NO hash traversal (cleaner); missile speed / geometry / typed-CC need the
  raw bin (extend the existing AA-cast-time walk). Items stay on Meraki (CDragon
  `items.cdtb.bin.json` is what Meraki already parses - no gain re-doing it).

---

## 7. Provenance

Every row above is from a live fetch this session (verbatim snippets in the
investigation transcripts). Hand-verified by the orchestrator: CDragon v1 Ashe
ammo/cooldown arrays; wiki raw module mode-block counts (102/82/45/32/45/13).
Trusted from the brace-scan agents (correct parser, cross-checked Brand/Yuumi/
Sona/Corki/Teemo/Leona/Morgana/Nautilus/Ashe): the per-champ mult values + the
CDragon spell-bin field paths. Not committed; review artifact.
