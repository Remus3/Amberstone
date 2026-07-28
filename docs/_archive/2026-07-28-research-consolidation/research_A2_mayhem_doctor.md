# Research A2 - ReformedDoge/Mayhem-Doctor

Read date: 2026-07-28. Source read: raw.githubusercontent.com, branch `main` (default branch
confirmed `"default_branch":"main"` from the repo API). All 20 `.js` source blobs downloaded and
read; nothing below is inferred from a filename.

---

## WHAT IT IS

A **Pengu Loader plugin** - client-side JavaScript that runs INSIDE the League client's CEF
process. It is an **out-of-game post-match history analyser**, not a live coach. Entry point
`Mayhem-Doctor/index.js` registers a Pengu `CommandBar.addAction`, an `Alt+X` keydown handler, a
button injected into the client's Match History page, and an "Investigator" tab injected into
profile pages.

Repo facts (from `GET /repos/ReformedDoge/Mayhem-Doctor`):
- created 2026-02-22, pushed 2026-07-24, size 234 KB, 2 stars, 0 forks, language JavaScript.
- Version string in `index.js` header: `@version 1.2.0`, author `SnoozeFest - github@ReformedDoge`.

File tree (`git/trees/main?recursive=1`) - 21 blobs total:

```
Mayhem-Doctor/index.js                4605
Mayhem-Doctor/src/analysis.js        25950
Mayhem-Doctor/src/assets/aram.svg   126578
Mayhem-Doctor/src/assets/styles.js   47139
Mayhem-Doctor/src/cache.js           10852
Mayhem-Doctor/src/config.js           3964
Mayhem-Doctor/src/fileCache.js        4248
Mayhem-Doctor/src/generalUtils.js    54464
Mayhem-Doctor/src/globalCache.js     19648
Mayhem-Doctor/src/lcu.js              3845
Mayhem-Doctor/src/resolver.js         1304
Mayhem-Doctor/src/store.js            4976
Mayhem-Doctor/src/ui/{augments,crawler,investigator,items,matchView,modal,patchFilter,settings,table,tabs}.js
README.md                             5077
```

README drift worth noting: the README's install tree lists `src/assets/base.css`,
`champions.css`, `investigator.css`, `matchView.css`. **None of those files exist** in the repo -
CSS is inlined in `src/assets/styles.js`. Read the source, not the README.

---

## LICENCE

**No licence. Confirmed two ways.**

1. Repo API: `"license": null`.
2. Full recursive tree contains **no** `LICENSE`, `LICENCE`, `COPYING`, or `NOTICE` blob at any
   path. README has a "Disclaimer" section (not-affiliated-with-Riot boilerplate) and a
   "Privacy" section, but no grant of rights.

Consequence: **all rights reserved by default. This code CANNOT be vendored, copied, or adapted
into Riot Commander.** Reference-reading only. Nothing below is a recommendation to copy code.

---

## DATA SOURCES (with quoted code)

Three sources, all out-of-game. There is **no** Live Client `:2999` read anywhere - a repo-wide
grep for `2999`, `liveclient`, `activePlayer`, `gameflow`, `champ-select` returns **zero** hits in
any `.js` file.

### 1. LCU static asset routes (in-client, same-origin fetch)

`src/lcu.js:24-52`:

```js
export async function loadStaticData() {
    try {
        const items = await LCU_API.get('/lol-game-data/assets/v1/items.json');
        ...
        const augs = await LCU_API.get('/lol-game-data/assets/v1/cherry-augments.json');
        augs.forEach(a => { if (a.id && a.id > 0) AUGMENT_DATA[a.id] = { name: a.nameTRA || `Augment ${a.id}`, icon: a.augmentSmallIconPath || a.augmentIconPath, rarity: a.rarity || 'kSilver' }; });

        const champs = await LCU_API.get('/lol-game-data/assets/v1/champion-summary.json');
        ...
        const spells = await LCU_API.get('/lol-game-data/assets/v1/summoner-spells.json');
```

Plus `/lol-game-data/assets/v1/perks.json`, `perkstyles.json`, `/lol-game-queues/v1/queues`
(`generalUtils.js:932-937`) and `/lol-summoner/v1/summoners?name=<riotId>` for PUUID resolution
(`lcu.js:86`). These are **name/icon/rarity lookup tables only**. No stats.

Because the plugin runs inside the client, its "LCU call" is a plain relative `fetch` with no
lockfile auth:

`generalUtils.js:565` - `const r = await fetch(url.startsWith('/') ? url : '/' + url);`

### 2. SGP match-history backend (the real data source)

`generalUtils.js:1100-1112`:

```js
async function getSgpMatchHistory(puuid, startIndex = 0, count = 20, tag = '', overrideRegion = null) {
    if (!LCU) return null;
    try {
        const { accessToken, sgpBase } = await getSgpContext(overrideRegion);

        let url = `${sgpBase}/match-history-query/v1/products/lol/player/${puuid}/SUMMARY?startIndex=${startIndex}&count=${count}`;
        if (tag) url += `&tag=${tag}`;

        const resp = await fetch(url, { headers: { 'Authorization': `Bearer ${accessToken}`, 'User-Agent': 'LeagueOfLegendsClient' } });
```

Token source, `lcu.js:66-70` (comment) - LCU `/entitlements/v1/token` or
`/lol-rso-auth/v1/authorization/access-token`. Region routing is a hardcoded host map
(`generalUtils.js:1036-1053`), split into a `matchHistory` host and a `common` host, e.g.

```js
NA1:  { matchHistory: 'https://usw2-red.pp.sgp.pvp.net', common: 'https://na-red.lol.sgp.pvp.net' },
EUW:  { matchHistory: 'https://euc1-red.pp.sgp.pvp.net', common: 'https://euw-red.lol.sgp.pvp.net' },
KR:   { matchHistory: 'https://apne1-red.pp.sgp.pvp.net', common: 'https://kr-red.lol.sgp.pvp.net' },
```

with a Tencent branch (`generalUtils.js:1068-1072`) for `https://<tCode>-sgp.lol.qq.com:21019` /
`<tCode>-k8s-sgp.lol.qq.com:21019`, region derived by regexing the entitlement token issuer
(`line 1019`), default fallback EUC1.

### 3. Local persistence

`src/store.js` / `src/cache.js` - Pengu `DataStore`, packed to short keys
(`cache.js:20,33`: `dm=dmg it=items[] ob=orderedBuild[] au=augments[] lb=legendaryItemUsed[]`).
Caps in `config.js:80-82`: 10 PUUIDs, 6 MB each, 60 MB total.

`src/fileCache.js` moves the big global blob out of DataStore to a plugin-served JSON file
(`./data/md-global-stats.json`) because "Pengu's DataStore.set() always calls commit(), which
JSON.stringify's the entire store, XOR's it, and writes it to disk" - a 50-70 MB blob made
unrelated writes lag.

`src/ui/settings.js:9` polls `https://api.github.com/repos/ReformedDoge/Mayhem-Doctor/releases/latest`
for updates. **No other outbound host.** The README's "never sends your data anywhere" claim is
consistent with what the code does.

### What it computes

- `analysis.js:29-31` - Laplace-smoothed win rate, `LAPLACE_K = 3`:
  `((wins + 3) / (games + 6)) * 100`.
- `analysis.js:34-46` `deriveOrderedBuild` - reconstructs build ORDER from the final 7 item slots
  by putting `challenges.legendaryItemUsed` (which is order-preserving) first, then the remainder.
  This is a genuinely neat trick: it recovers a pseudo build order from a SUMMARY match record
  that has no purchase timeline.
- `analysis.js:687-797` `analyzeChampBuildPath` - conditional path analysis: rank slot-1 items by
  `freqScore * (1 - w) + max(0, (wr - 40) * 4) * w` with `w = SETTINGS.synergyWeight = 0.3`
  (`config.js:11-13`), then for each of the top-3 anchors re-derive followers **within the subset
  of games that actually opened with that item**, sorted by mean slot index. Boots handled
  separately.
- `ui/augments.js:26-50, 52-79` - augment tier board by rarity with priority
  `wr + log(games) * 5`, and pairwise co-occurrence ("Best Seen Aug Pairs") over the 6
  `playerAugment` slots, same priority formula.
- `ui/crawler.js` - a BFS "global crawl": from your own games, expand to every participant PUUID,
  fetch their SUMMARY batches over SGP, dedupe by `gameCreation`, accumulate per-champion stats.
  Tuning in `config.js:85-92`: target 10,000 unique games, max 600 players, batch 20, max 2
  concurrent, 75 ms delay. This is how it manufactures a "global" (non-personal) win-rate corpus
  without any Riot dev key.

---

## THE AUGMENT QUESTION

**RC's fence is CONFIRMED. This plugin has no live in-game augment state, and does not claim to.**

Every augment value in the plugin comes from **post-game match records** - the
`playerAugment1..6` participant fields on a finished SGP match. Three independent read sites,
quoted:

`analysis.js:129-134` (parse of a completed game):

```js
        playerAugment1: part.playerAugment1,
        playerAugment2: part.playerAugment2,
        playerAugment3: part.playerAugment3,
        playerAugment4: part.playerAugment4,
        playerAugment5: part.playerAugment5,
        playerAugment6: part.playerAugment6,
```

`cache.js:64-65` (persisting a completed game):

```js
        au:  [p.playerAugment1,p.playerAugment2,p.playerAugment3,
              p.playerAugment4,p.playerAugment5,p.playerAugment6].filter(x => x),
```

`globalCache.js:77-78` (crawl record packing):

```js
    // [0]=win [1]=items [2]=augments [3]=orderedBuild [4]=gameCreation (optional, absent in legacy records)
    const rec = [g.win ? 1 : 0, g.items, g.augments, g.orderedBuild];
```

The only augment route it touches is `/lol-game-data/assets/v1/cherry-augments.json`
(`lcu.js:42`), which is the **static catalogue** - id, `nameTRA`, icon path, rarity. No stats, no
live state. It is exactly the same catalogue RC already resolves augment ids against.

Ruling out the three hypotheses in the task:

1. *In-client CEF/plugin surface RC cannot reach* - **no.** The plugin does have CEF privilege
   (it even installs a `window.fetch` interception hook, `generalUtils.js:1118+`, and DOM-observes
   client elements), but it never points that privilege at any in-game or champ-select augment
   surface. There is no `/lol-champ-select`, no `/lol-gameflow`, no `:2999`, no arena/cherry
   session route anywhere in the codebase. The privilege exists and is unused for augments.
2. *Bundled static augment table* - **no.** No augment stats ship in the repo; the only bundled
   asset is `aram.svg`. Augment win rates are computed at runtime from the user's own (or crawled)
   completed matches, cold-start empty.
3. *No live augment state* - **yes, this is the case.** The plugin is entirely retrospective.
   Its own UI copy says as much: `ui/augments.js:99` renders
   `'Not enough data - need >=2 games with the same pair.'`

So: the ONLY on-domain repo in that account, written by someone with full in-client CEF
execution, still gets augments exclusively from post-game records. That is independent
corroboration that there is no capture-free mid-game augment API - not even from inside the
client process. RC's Settled line stands, and RC's augment-OCR path remains the only route to
live augment state.

Sharper still: the plugin's problem shape is *weaker* than RC's. RC needs augments **during** the
game to coach; Mayhem-Doctor only needs them **after**, where the data is trivially available.
It never faced RC's question.

---

## WHAT RC ALREADY HAS

| Mayhem-Doctor capability | RC equivalent | Verdict |
|---|---|---|
| Queue 2400 = Mayhem, `VALID_QUEUE_IDS = [2400]` (`config.js:9`) | Settled item 87 - "ARAM Mayhem reports queueId 2400 (not 920)", live-proven | RC already knows, and knows the 920 trap MD does not mention |
| Laplace smoothing k=3 (`analysis.js:25`) | `core/smoothed_rates.py` - the shared Laplace/shrink primitive | RC has it as a shared primitive |
| Per-augment win-rate prior | `core/augment_external_source.py` - Overlay App E/iesdev `aram_mayhem_augments` feed with per-augment `win_rate`, `pick_rate`, `tier` AND `augment_stage_stats` (per-round), blended toward own history by `w = n_own/(n_own+K)`; plus `core/augment_recommender.py`, `core/augment_shadow.py` | **RC is strictly ahead** - MD has only own/crawled history, no external prior, no per-round stage stats, no blend |
| Build-order reconstruction from final items | `core/build_order.py` (engine-authoritative, 6 unique-passive families, no-double-unique rule) + Daemon Slayer `:8893` real DPS math over 706 items / 173 champs | **RC is a different class** - MD is frequency/win-rate only, zero item mechanics |
| Item win rates, boots ranking | DS scorers (7 archetypes), `core/aram_item_interaction.py`, `core/aram_tenacity_context.py` | RC ahead |
| ARAM boot/alias id knowledge (`config.js:56-77`: 3013, 3168, 3170-3176, 1111, 2422, 223xxx mirrors) | Verified present in RC: `core/build_order.py:109,137,152` (3170 Swiftmarch, 3168/3013/3176 tier-3 boots), `agents/daemon_slayer/tests/test_magic_pen_flat_catalog_r153.py` (1111 Jarvan I's in `ITEM_EFFECTS`), 2422 in `data/daemon_slayer/16.10.1/items.json`, 223xxx alias pattern in memory `reference_items_index_alias_ids` | **No new ids.** RC covers all of them |
| SGP match history for event modes | Memory RM-106: RC MEASURED that SGP returns KIWI / queue-2400 games in Match-V5 shape. Implementation is `BACKLOG.md:54` as **FUTURE, ToS-HIGHEST, live-probe-gated**; `grep -rln "sgp" --include=*.py core/ tools/ agents/` returns **nothing** | **The one place MD is materially ahead of RC's shipped code** - see verdict |
| ARAM balance-modifier table (per-champion Mayhem damage-dealt/taken tuning) | RC has `core/aram_balance_context.py`, `core/aram_comp_verdict.py`, `core/aram_archetype_override.json` | **MD has NONE.** Repo-wide grep for `balance`, `modifier`, `damageDealt` multipliers finds nothing. It has no concept of ARAM balance tuning at all |
| Live coaching, vision, DPS math, deterministic coach | RC's entire `modes/`, `agents/daemon_slayer/`, vision pipeline | MD has none - it is out-of-game only |

---

## VERDICT

**REFERENCE-ONLY.**

Not ADOPT: unlicensed, so nothing can be vendored, and every analytic it ships is thinner than
RC's equivalent (frequency + Laplace win rate vs RC's DS combat simulation and blended external
augment prior).

Not NO VALUE either, for exactly two reasons:

1. **The augment answer is a real, useful negative.** A developer with full in-client CEF
   execution - who installs a `window.fetch` hook and DOM-observes the client - still reads
   augments only from finished matches. That is the strongest available third-party corroboration
   that RC's "no capture-free mid-game augment API" fence is correct, and it closes off "maybe a
   Pengu plugin can see augments live" as a future re-pitch. Log it against the Settled line.

2. **It is a working, readable specimen of the SGP recipe RC has only de-risked on paper.**
   `BACKLOG.md:54` describes exactly this flow and calls the region host-map a de-risked-but-
   unbuilt recipe with "ONE remaining live unknown = a Legion NA-region host reachability probe".
   MD ships the full 17-entry host map including `NA1 -> https://usw2-red.pp.sgp.pvp.net`, the
   exact URL template, and the exact headers (`Authorization: Bearer`, `User-Agent:
   LeagueOfLegendsClient`). Reading that as documentation costs nothing and does not change the
   ToS posture one bit - `BACKLOG.md` already rates this ToS-HIGHEST / do-not-ship-blind, and
   that rating is unchanged by someone else having done it. **Do not treat MD's existence as
   permission.** The operator gate on SGP stands.

The one idea worth noting without copying: `deriveOrderedBuild` (`analysis.js:34-46`) recovers a
plausible build ORDER from a match record that has no purchase timeline, by leaning on
`challenges.legendaryItemUsed` being order-preserving. If RC ever wants build-order signal out of
SUMMARY-shaped history rather than a timeline, that is the trick - reimplemented from the
described idea, not from the code. Low priority: RC's build orders come from DS simulation, not
from observed history.

---

## EVIDENCE

- `GET https://api.github.com/repos/ReformedDoge/Mayhem-Doctor` - `"license": null`,
  `"default_branch": "main"`, `"pushed_at": "2026-07-24T19:58:19Z"`, `"size": 234`,
  `"stargazers_count": 2`, `"forks_count": 0`.
- `GET https://api.github.com/repos/ReformedDoge/Mayhem-Doctor/git/trees/main?recursive=1` - 21
  blobs, no LICENSE at any path.
- All 20 `.js` blobs downloaded from `raw.githubusercontent.com/.../main/Mayhem-Doctor/...` to
  `<scratchpad>/md_src/` and read. Byte sizes matched the tree listing for every file.
- Repo-wide grep across the downloaded sources for
  `2999|liveclient|LiveClient|gameflow|/lol-champ-select|activePlayer|balance|modifier` -
  **zero** hits in any file (only `MAYHEM` string-literal hits in `modal.js`/`tabs.js` easter-egg
  text and `queueId` hits listed above).
- Augment reads quoted from `analysis.js:129-134`, `cache.js:64-65`, `globalCache.js:77-78`;
  augment catalogue from `lcu.js:42`.
- SGP call quoted from `generalUtils.js:1100-1112`; host map `generalUtils.js:1036-1053`.
- RC-side cross-checks run live this session: `ls C:/Riot Commander/core/` (13 `aram_*` /
  `augment_*` modules present), `head -30 core/augment_external_source.py`,
  `grep -rln "sgp" --include=*.py core/ tools/ agents/` (no hits),
  `grep -n "SGP" BACKLOG.md` (line 54, FUTURE/ToS-HIGHEST),
  `grep -rn "2422|1111|3170" ...` (all present in RC item data / build_order / DS tests).
