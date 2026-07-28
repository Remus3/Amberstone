# Research E - Build Data Sources at Scale, Stratified by Champion x Role x Region x Rank

Scope: how to obtain items / runes / skill order / summoner spells at scale, stratified.
Date of research: 2026-07-28. All claims tagged VERIFIED (primary source read this session),
PARTIAL (source read but claim only partly supported), or UNVERIFIED.

Settled going in and NOT re-researched: Match-V5 `perks` gives runes directly; the gap is REACH.

---

## 0. The stratification axis nobody supplies for free

VERIFIED (Riot Match-V5 reference, ParticipantDto field list read in full this session):
**Match-V5 `ParticipantDto` carries NO rank/tier field.** Not on the participant, not on
`InfoDto`, not on `MetadataDto`. The full field list contains `championId`, `championName`,
`teamPosition`, `individualPosition`, `item0..item6`, `summoner1Id`, `summoner2Id`, `perks`,
`puuid`, `platformId` (on InfoDto) - and nothing rank-shaped.

Consequences, and they drive the whole ranking below:

- **champion** - free, in every per-match source.
- **role** - free-ish, `teamPosition` (Riot recommends `teamPosition` over `individualPosition`).
- **region** - free, `InfoDto.platformId` / the match id prefix (`NA1_`, `EUW1_`).
- **rank tier** - NOT free. Must be JOINED, per puuid, at ingest time, from LEAGUE-V4 (or the
  SGP ledge equivalent), and it is a snapshot at join time, not the rank the player held during
  the match. Any per-match pipeline that wants rank stratification pays a second request per
  distinct puuid plus a rank-drift caveat.

The only sources where rank stratification is FREE are the pre-aggregated ones (aggregator D,
aggregator B, aggregator A tier lists) - and those cannot answer per-match questions. That is the central
trade in this whole document.

---

## 1. RANKED SOURCE TABLE (coverage per unit effort)

Effort scale: XS (hours) / S (1 session) / M (2-4 sessions) / L (weeks) / XL (open-ended).

TABLE PENDING FINAL MERGE - see section 1 final below.

---

## 2. Reach problem 1 - SGP, the client's own match-history backend

### 2.1 What SGP is

SGP = the "Service Gateway Proxy" family of Riot backend hosts that the League client itself
talks to for match history, ranked stats, spectator and summoner lookups. It is NOT the
`*.api.riotgames.com` developer API and it is NOT the local LCU. It is a real Riot production
service, authenticated with a token Riot's own client already holds.

### 2.2 Regional endpoint hostnames - VERIFIED

Primary source: `LeagueAkari/LeagueAkari`, `src/main/shards/akari-api/builtin.ts`,
`BUILTIN_SGP_LEAGUE_SERVERS_CONFIG`, `updatedAt: '2026-07-18T04:00:00.000Z'` - read in full
this session. Each server has TWO base URLs with DIFFERENT roles:

- `matchHistory` -> a **`pp.sgp.pvp.net`** super-region host (player-platform). This is where
  `/match-history-query/**` lives.
- `common` -> a **`<region>-red.lol.sgp.pvp.net`** per-region host. This is where the
  "ledge" services live (ranked stats, summoner, spectator).

Riot-operated (non-Tencent) map, verbatim from that file:

| sgpServerId | matchHistory (pp host) | common (lol host) |
|---|---|---|
| NA1 | https://usw2-red.pp.sgp.pvp.net | https://na-red.lol.sgp.pvp.net |
| BR1 | https://usw2-red.pp.sgp.pvp.net | https://br-red.lol.sgp.pvp.net |
| LA1 | https://usw2-red.pp.sgp.pvp.net | https://lan-red.lol.sgp.pvp.net |
| LA2 | https://usw2-red.pp.sgp.pvp.net | https://las-red.lol.sgp.pvp.net |
| PBE | https://usw2-red.pp.sgp.pvp.net | https://pbe-red.lol.sgp.pvp.net (regionPathParam PBE1) |
| EUW | https://euc1-red.pp.sgp.pvp.net | https://euw-red.lol.sgp.pvp.net (regionPathParam EUW1) |
| TR1 | https://euc1-red.pp.sgp.pvp.net | https://tr-red.lol.sgp.pvp.net |
| RU  | https://euc1-red.pp.sgp.pvp.net | https://ru-red.lol.sgp.pvp.net |
| KR  | https://apne1-red.pp.sgp.pvp.net | https://kr-red.lol.sgp.pvp.net |
| JP  | https://apne1-red.pp.sgp.pvp.net | https://jp-red.lol.sgp.pvp.net (regionPathParam JP1) |
| OC1 | https://apse1-red.pp.sgp.pvp.net | https://oce-red.lol.sgp.pvp.net |
| SG2 | https://apse1-red.pp.sgp.pvp.net | https://sg2-red.lol.sgp.pvp.net |
| TW2 | https://apse1-red.pp.sgp.pvp.net | https://tw2-red.lol.sgp.pvp.net |
| PH2 | https://apse1-red.pp.sgp.pvp.net | https://ph2-red.lol.sgp.pvp.net |
| VN2 | https://apse1-red.pp.sgp.pvp.net | https://vn2-red.lol.sgp.pvp.net |
| TH2 | https://apse1-red.pp.sgp.pvp.net | https://th2-red.lol.sgp.pvp.net |

Tencent (China) servers are a SEPARATE scheme: `https://<shard>-sgp.lol.qq.com:21019`, e.g.
`hn1-k8s-sgp.lol.qq.com:21019`, `tj100-sgp.lol.qq.com:21019`, `pbe-sgp.lol.qq.com:21019`.

**CORRECTION for the RC BACKLOG row.** RC's own `BACKLOG.md` currently records the SGP recipe as
"regional SGP host `:21019`". That is WRONG for a NA/EUW/KR operator - `:21019` is the **Tencent**
port only. Riot's own SGP hosts are plain HTTPS on 443 with no explicit port. On NA the two hosts
are `https://usw2-red.pp.sgp.pvp.net` (match history) and `https://na-red.lol.sgp.pvp.net`
(ledge). Fixing that row is a one-line edit and prevents a wasted probe.

Corroborating independent source, VERIFIED: `aPinat/riot-documentation` README documents the
public edge proxies `https://{apne|apse|euc|usw}.pp.riotgames.com` which "proxy to their
respective `https://{ROUTE}-green.pp.sgp.pvp.net`" for exactly the routes `/login-queue/v2`,
`/match-history-query/v1`, `/session-external/v1`. So `match-history-query` is a first-class
Riot player-platform service with a public-facing edge, not an internal-only hack. Note the
`-green` vs `-red` suffix difference (two deployment colours); UNVERIFIED which is canonical
for a live client at any given moment.

### 2.3 Auth model - VERIFIED

Primary source: `LeagueAkari` `src/main/shards/sgp/http-client-controller.ts` and
`token-state-controller.ts`, read in full. Two distinct token types, and they are NOT
interchangeable:

| Token type | Source (LCU/RC endpoint) | Field used | Sent as | Used against |
|---|---|---|---|---|
| `entitlements` | LCU `GET /entitlements/v1/token` | `.accessToken` | `Authorization: Bearer <t>` | the `matchHistory` (pp.sgp.pvp.net) host |
| `league-session` | LCU `GET /lol-league-session/v1/league-session-token` | the raw token string | `Authorization: Bearer <t>` | the `common` (lol.sgp.pvp.net) host |

The controller literally branches:
`const baseUrl = requiredTokenType === 'entitlements' ? serverConfig.matchHistory : serverConfig.common`.
Using the wrong token against the wrong host fails.

Both tokens come from the **local League client over the LCU lockfile**, which RC already has
plumbing for (`lcu/lcu_client.py`). No injection, no credential handling, no reverse engineering
of the binary - it is an authenticated read of the client's own auth state.

**Lifetime: the TTL number is UNVERIFIED, but the correct handling is VERIFIED.** Both are
RSO-issued JWTs with an `exp`. No source read this session states the numeric TTL. But
`Coordi777/Sona-Mayhem` `src/lib/lcu.ts` documents the mechanism explicitly: "LCU will
proactively push a new token via the WS event when the token is about to expire - you do not
need to compute the expiry yourself." LeagueAkari implements the identical pattern (a mobx
reaction on `leagueClient.data.entitlements.token`). **So: subscribe to the LCU websocket on
`/entitlements/v1/token` and `/lol-league-session/v1/league-session-token`, cache the pushed
value, never compute an expiry.** LeagueAkari's CHANGELOG records a fixed intermittent "JWT
Token not set" race where SGP was called before the token arrived - gate on token-readiness.

**Entitlements token response shape - VERIFIED** (documented in Sona-Mayhem's `getEntitlementsToken`):
`{ accessToken (JWT - this is the one you Bearer to SGP), token (a different entitlements JWT),
issuer (URL), subject (the player PUUID), entitlements (usually []) }`.

**Region discovery without hardcoding - VERIFIED.** Do not hardcode the host suffix. The
`issuer` field encodes the region and the deployment colour, e.g.
`https://na-red.lol.sgp.pvp.net`, `https://euw-red.lol.sgp.pvp.net`. Sona parses it with
`/https?:\/\/([a-z0-9]+)-[a-z0-9]+\.lol\.sgp\.pvp\.net/`. This matters because the colour
suffix is NOT stable: `aPinat/riot-documentation` lists `-blue` hosts (`euw-blue.lol.sgp.pvp.net`)
and `-green` pp hosts, while LeagueAkari's 2026-07-18 map uses `-red` throughout. Derive the
host from the live token, fall back to the static map. Sona's own note records the platformId
mismatch trap too: `EUW1 -> EUW`, `RU1 -> RU`, `NA -> NA1`, `OCE -> OC1`.

**HARD CONSTRAINT (VERIFIED):** SGP requires the League client to be RUNNING AND LOGGED IN.
`src/main/shards/sgp/state.ts` derives `sgpServerId` from
`getSgpServerId(auth.region, auth.rsoPlatformId)` and returns an empty/unsupported availability
when `leagueClient.state.auth` is null. There is no offline / headless SGP. This alone caps SGP
as a bulk-harvest channel: it is a live-session channel.

### 2.4 Endpoints and what they return - VERIFIED

From `src/shared/http-api-axios-helper/sgp/match-history-query.ts` (entitlements token, pp host):

- `GET /match-history-query/v1/products/lol/player/{puuid}/SUMMARY`
  query: `startIndex`, `count`, `tag`, `tagsQueryType` (`AND` | `OR`)
- `GET /match-history-query/v1/products/lol/{SUBID}_{gameId}/SUMMARY`
- `GET /match-history-query/v1/products/lol/{SUBID}_{gameId}/DETAILS`
- `GET /match-history-query/v3/product/lol/matchId/{SUBID}_{gameId}/infoType/replay` (stream)

`{SUBID}` is the sgpServerId (or `regionPathParam` when set, e.g. `EUW1`, `JP1`, `PBE1`; for
Tencent it is the `rsoPlatformId` half of `TENCENT_xxx`).

From `src/shared/http-api-axios-helper/sgp/leagues-ledge.ts` (league-session token, lol host):

- `GET /leagues-ledge/v2/rankedStats/puuid/{puuid}` -> ranked tier/division per queue.
  The LeagueAkari source carries an inline Chinese comment on this method translating to
  **"this API cannot cross regions"**. VERIFIED as the author's own annotation; region-locked
  by design. (Original comment text omitted here - this document is 7-bit ASCII.)

Other ledge routes documented by third parties (PARTIAL - seen in `lzskyline/LeeSin` TECH.md and
several Rust/Python ports, not read from a Riot source):
- `GET /summoner-ledge/v1/regions/{region}/summoners/puuid/{puuid}`
- `GET /gsm/v1/ledge/spectator/region/{region}/puuid/{puuid}` (live game / spectator)

**Payload shape - VERIFIED** from `src/shared/types/sgp/match-history.ts`, read in full. The
`SUMMARY` response is `{ games: [{ metadata, json }] }` where `json` is Match-V5-shaped:
`gameId`, `gameMode`, `gameVersion`, `mapId`, `queueId`, `platformId`, `teams`, and
`participants[]` carrying `championId`, `championName`, `teamPosition`, `individualPosition`,
`item0..item6`, `puuid`, `riotIdGameName`/`riotIdTagline`, `playerAugment1..6` (Arena),
`challenges`, and critically:

```
perks: { statPerks: { defense, flex, offense },
         styles: [ { description, style, selections: [ { perk, var1, var2, var3 } ] } ] }
```

That is byte-for-byte the Match-V5 `PerksDto` / `PerkStatsDto` / `PerkStyleDto` /
`PerkStyleSelectionDto` shape. **Runes come out of SGP in exactly the format RC already parses.**

Summoner spells: the SGP participant type lists `spell1Id`, `spell2Id`, `summoner1Casts`,
`summoner2Casts` - i.e. the summoner-spell ids are present but under the older
`spell1Id`/`spell2Id` names rather than Match-V5's `summoner1Id`/`summoner2Id`. PARTIAL: field
names taken from the LeagueAkari TypeScript type, not from a live response. Budget a small
normalizer and confirm on first live probe.

**Skill order and item order: VERIFIED available.** The `DETAILS` endpoint returns
`GameDetailsJson` with `frames[].events[]` typed to include `SKILL_LEVEL_UP`
(`participantId`, `skillSlot`, `levelUpType: 'NORMAL' | 'EVOLVE'`), `ITEM_PURCHASED`,
`ITEM_SOLD`, `ITEM_DESTROYED`, `ITEM_UNDO`, plus full `participantFrames` with `championStats`
and `damageStats`. This is the Match-V5 TIMELINE, served by SGP. So SGP alone covers all four
build dimensions the question asks for: items, runes, skill order, summoner spells.

### 2.5 Event-mode coverage - the actual reason to build this

VERIFIED: `BUILTIN_SUPPORTED_QUEUES` in the same `builtin.ts` (dated 2026-07-18) lists
`420, 440, 430, 450, 480, 1700, 1750, 490, 1900, 900, 2300, **2400**, 4210, 4220, 4240, 4250, 4260`.
Queue **2400** - ARAM Mayhem, the exact queue Match-V5 403s on - is a first-class supported queue
in a shipping SGP client. Also `BUILTIN_AUTO_SELECT_GROUPS` has an explicit `gameMode: 'KIWI'`
entry alongside `ARAM`. This is the strongest available confirmation short of a live probe that
SGP returns event-mode games that Match-V5 will not.

### 2.6 Rate behaviour - UNVERIFIED, and do not guess

No primary source found. Riot publishes nothing for SGP; there is no `X-App-Rate-Limit` contract
to read. What IS observable in the code:

- LeagueAkari wraps the SGP axios instance with `axios-retry` and counts connection
  successes/failures into state (`connectionSuccessesCounted` / `connectionFailuresCounted`) -
  i.e. it treats SGP as flaky-but-not-quota'd, and has no token-bucket limiter.
- No open-source consumer read this session implements an SGP rate limiter. That is weak
  evidence that casual per-lobby use (tens of requests per game) does not trip a limit. It is
  NOT evidence that ladder-scale harvesting (thousands of puuids/hour) is safe.

**Recommendation: treat SGP rate limits as unknown-and-hostile.** Probe with a conservative
fixed rate, log every non-2xx, and back off hard on the first 429/403. A ban here costs the
operator's own League account, not an API key.

### 2.7 Stability across patches - PARTIAL

- The host map is versioned data in LeagueAkari (`updatedAt` field, refreshed remotely) which
  itself implies the map DOES drift and must be re-pulled, not hardcoded once.
- The path shapes (`/match-history-query/v1/products/lol/player/{puuid}/SUMMARY`) appear
  identically across ~15 independent projects in C#, Rust, Go, Python, TypeScript, some dating
  back years. That is strong evidence of path stability.
- `zhouyi207/YssLeague` annotates its rankedStats response type with the design note that every
  field is `#[serde(default)]` because "Riot Ledge's schema adds/removes fields between regions
  and versions". Treat SGP response schemas as additive-and-drifting: parse defensively, never
  assert on field presence.
- UNVERIFIED: whether Riot has ever broken SGP for third parties deliberately.

### 2.8 What SGP CAN and CANNOT answer

CAN:
- Per-match runes, items, summoner spells, skill order, augments - for ANY puuid, including
  event modes (queue 2400 / gameMode KIWI) and Arena, in Match-V5 shape.
- Ranked tier for a puuid (via `leagues-ledge` on the `common` host), which is the rank-join
  Match-V5 cannot give you.
- Replay file download by gameId (v3 `infoType/replay`).

CANNOT:
- Run without a logged-in League client. No headless, no cron-at-3am unless the client is up.
- Cross regions. `rankedStats` is annotated region-locked; the `common` host is per-region; the
  entitlements token's issuer encodes the region. UNVERIFIED whether the shared `pp` super-region
  host (e.g. `usw2-red` for NA+BR+LAN+LAS) accepts a NA token for a BR puuid. That is a cheap
  one-request probe and worth doing before assuming either way.
- Enumerate a ladder. SGP is puuid-in, matches-out. It has no "give me all Diamond players"
  route. You still need LEAGUE-EXP-V4 (official API) to SEED the puuid list. SGP replaces the
  fetch step, not the discovery step.
- Give you a licence to redistribute. See section 6.

### 2.9 The other undocumented-but-sanctioned routes

**LOL-RSO-MATCH-V1 - fully documented and sanctioned, wider coverage than Match-V5.**
`GET /lol/rso-match/v1/matches/ids` takes a player ACCESS TOKEN (RSO) rather than a product key,
supports `count` / `start` / `queue` / `type` (ranked, normal, tourney, tutorial), and
**includes custom matches**, which Match-V5 will not return. Riot Dev Rel announced this
explicitly (2024) with an attached policy: third-party sites may not publicly display a player's
custom-queue match history unless the player opts in. Cost: you need an approved RSO client
(OAuth registration + Riot approval), which is a real product-application gate, not a form fill.
UNVERIFIED: whether rso-match covers event modes / queue 2400. Known open bug: issue #1061 in
`RiotGames/developer-relations` reports 404s from this endpoint for custom matches.

**LCU local match history** - `GET /lol-match-history/v1/products/lol/{puuid}/matches?begIndex&endIndex`
on the local client. Zero new infrastructure (RC already has the lockfile client). Third-party
observation (`Skayles/nightfury-gg` source comment): "the LCU serves ~20 games per request, and
only keeps a limited recent window - a few hundred at most". PARTIAL - that is a developer's
comment, not Riot documentation. This is the cheapest possible probe and covers event modes, but
the window is shallow and it is primarily a self/lobby-scope route.

**Riot Client `GET /player-account/aliases/v1/lookup?gameName=&tagLine=`** -> returns puuid.
VERIFIED present in LeagueAkari (`riot-client/player-account.ts`) and in KebsCS's Riot-Client
route catalog. NOTE: this is on the **Riot Client** lockfile/port, not the LCU port - a separate
auth handle RC would need to add. Solves riotId -> puuid without spending ACCOUNT-V1 budget.

---

## 4. Reach problem 3 - games with no obtainable match id (VODs, clips, replay channels)

### 4.1 HEADLINE: the premise behind approach A is FALSE

The task framed this as "replay-upload channels show every player's FULL RUNE PAGE on screen in
the first seconds before the game starts, at a fixed HUD position". **That is not what the
League client renders.** VERIFIED against Riot's own communications and the League Wiki:

- **Loading screen:** per player, shows champion/skin, name, rank border, summoner spells, and
  the **keystone icon plus the secondary path icon - and nothing else**. Riot's Runes Reforged
  announcement: in the loading screen "you'll be able to see the path / keystone of each player
  in your game", and "you'll also be able to see the keystone of all players in the game
  scoreboard". A later loading-screen rework added the ability to **hover** opponents' spells
  and runes for detail - and a hover does not happen in a recorded VOD.
- **TAB scoreboard in-game:** keystone icon only, with a hover tooltip. There is no runes tab
  that lists a full page for all ten players.
- **Stat shards:** UNVERIFIED that they are rendered for OTHER players anywhere in the client at
  any time. Multi-year player requests for full rune / shard visibility remain unfulfilled.
  Treat shards as **not recoverable by CV at all**.

So the ceiling of approach A is: keystone + secondary path + summoner spells. That is roughly
30 percent of a rune page, zero minor runes, zero shards. It cannot reach parity with a match id
no matter how good the vision model is.

### 4.2 HUD geometry is not stable either (secondary kill)

- HUD Scale is a **user setting** (pros commonly run 35-50 percent). It is not a function of
  resolution. Riot additionally states it "set slightly smaller sizes for the scoreboard for
  lower resolutions while preventing it from ballooning at ultra high resolutions" - so the
  mapping from pixels to elements is resolution-dependent AND user-dependent.
- The reference open-source scraper `floh22/LeagueOCR` hard-requires "16:9 Resolution (Native
  1080p)" and "Max UI Scale (100)" - and it only extracts dragon/baron state and team gold.
  No items, no runes, no per-player stats. That is the realistic ceiling of a calibrated scraper.
- Broadcast HUD moves wholesale between seasons: Riot shipped an entirely re-laid-out esports
  HUD at First Stand 2025 (scoreboard to a vertical top-left block, timers to top-right). Any
  pro-VOD calibration predating that is dead.

### 4.3 Detection state of the art (tertiary kill)

There is **no open-source project that identifies runes from League video**. What exists:
`Oleffa/LeagueAI` (YOLOv3; towers/minions/one champion, its own TODO admits the mAP calculation
needs rework), `Maknee/LeagueMinimapDetectionOpenCV` and DeepLeague (minimap only),
`Dan-Shields/League-OCR-HUD` (which **supplements the Live Client API** with Cloud Vision OCR -
it does not replace it). **No published accuracy number for rune or item identification from
video exists.**

OCR is the wrong tool regardless: the HUD renders rune **icons**, not names. The only viable
approach is template / perceptual-hash / embedding match against DDragon or CommunityDragon icon
art. YouTube serves less-popular 1080p in H.264 with visible macroblocking on motion, and
small high-frequency icon detail is exactly what that codec discards first.

Cost of A: compute is cheap (single-digit CPU-minutes per 30-minute VOD with frame sampling).
The cost is **engineering** - region calibration per resolution x HUD-scale x aspect ratio, an
icon-template corpus regenerated on every patch that adds or reworks a rune, and full
re-calibration on every HUD move. Unbounded and recurring, for a 30-percent-complete answer.

### 4.4 Approach B - resolve the match id from video metadata. This works.

VERIFIED from indexed video metadata on the "Challenger Replays" family of channels: title
format is `<Champion> <Role> vs <Enemy> - <Region> Challenger Patch <X.Y>` (e.g. "Rumble Top vs
Viego - KR Challenger Patch 25.16"), and the description body carries the **Riot ID plus tagline
and LP** (e.g. "Yousil@zypp, KR Challenger 1371 LP"). So each video yields Riot ID + region +
patch + upload date. **No match id appears** - but the identity does.

PARTIAL: the sub-agent could not render youtube.com watch pages directly (WebFetch returns only
the SPA shell), so the exact description layout, and whether aggregator A / Aggregator G links are commonly
pasted, is confirmed only from search-index snippets rather than a primary page read.

Resolution chain, all VERIFIED against Riot docs:
riot ID from description -> ACCOUNT-V1 `by-riot-id` -> puuid -> MATCH-V5
`by-puuid/{puuid}/ids` with `startTime`/`endTime` set to a +/- 1 day window around the upload
date -> filter by champion and role from the title. With champion + region + date this is
near-unique; ties resolve on the enemy champion, which is also in the title. Note
`startTime`/`endTime` only apply from 2021-06-16 onward.

Once resolved you get the **exact `perks` object Riot recorded**, including `statPerks`
(offense/flex/defense - the shards CV can never see), `item0..item6`, and
`summoner1Id`/`summoner2Id`. Ground truth, not an estimate.

### 4.5 RETENTION - a hard limit that constrains the whole programme

**VERIFIED, Riot DevRel primary source (match-history-retention-Change):** Riot reduced Match
History retention "from three years to two years on a rolling cadence", effective 2019-08-07,
and **timeline data has a SEPARATE one-year retention**.

This is load-bearing well beyond the VOD question:
- runes, items, summoner spells (from the match doc): **2 years**
- **skill order requires the TIMELINE (`SKILL_LEVEL_UP` events) and is therefore only available
  for 1 year.**

Any skill-order corpus older than 12 months cannot be rebuilt from Riot. If RC wants skill-order
depth, the timeline must be harvested continuously, not retroactively. This alone justifies a
standing ingest job over any one-off backfill.

### 4.6 YouTube Data API quota - VERIFIED, and the naive design fails

Current Google docs (determine_quota_cost): projects have "a default quota allocation of 100
`search.list` calls, 100 `videos.insert` calls, and 10,000 units per day combined for all other
endpoints". **`search.list` is capped at 100 CALLS per day** irrespective of the unit budget.

The design that works avoids `search.list` entirely: one `channels.list` -> the uploads playlist
id -> `playlistItems.list` paging (1 unit per 50 videos) -> `videos.list` with `part=snippet` for
descriptions. That yields on the order of 250k video descriptions/day within quota with ZERO
search.list usage. Description text arrives in `snippet.description`.
UNVERIFIED: the current YouTube API Services ToS text (which imposes metadata
storage/refresh obligations) was not read this session.

### 4.7 PRO games - do not go near a video. The data is already published.

- **Unofficial lolesports livestats** (`vickz84259/lolesports-api-docs` OpenAPI spec, VERIFIED):
  `/livestats/v1/details/{gameId}` returns `extendedParticipantStats` with **`items` (max 7),
  `perkMetadata` {styleId, subStyleId, perks}, and `abilities` (ability level-ups = skill
  order)**. Notably it does **not** carry summoner spells. `/window` is much thinner
  (level, K/D/A, CS, gold, HP).
- **Leaguepedia (lol.fandom.com) Cargo API:** the `ScoreboardPlayers` table declares a **`Runes`**
  column (`Module:CargoDeclare/ScoreboardPlayers`). Licence **CC BY-SA 3.0** (attribution +
  share-alike). Unauthenticated `cargoquery` is rate-limited to roughly 1 request/minute.
  UNVERIFIED: lol.fandom.com returned HTTP 402 to every fetch this session, so the exact `Runes`
  string format - specifically whether it includes shards - is unconfirmed.
- **esports stats site Z2** publishes per-game build pages at `esports stats site Z2/game/stats/{id}/page-builds/` covering pro
  games through Worlds 2025. UNVERIFIED: the table did not render through WebFetch, so
  shard-level detail there is unconfirmed.
- **Oracle's Elixir:** columns are gameid, datacompleteness, url, league, year, split, playoffs,
  date, game, patch, participantid, side, position, playername, playerid, teamname, teamid,
  champion, ban1-5, gamelength, result, K/D/A, damagetochampions, totalgold and similar
  aggregates. **NO runes, NO skill order, NO item build order.** Free for analysts/commentators/
  fans; some content is courtesy of Leaguepedia under CC BY-SA 3.0. PARTIAL - the column list is
  from indexed CSV headers; esports stats site Z3.com 403'd WebFetch.
- Commercial/live pro data is gated behind **GRID** via the Riot/Bayes LoL Data Portal.

### 4.8 VERDICT on reach problem 3

**Cheaper: B, by a wide margin.** B is a metadata pull (about 1 quota unit per 50 videos) plus
two Riot API calls per video. No calibration, no per-patch maintenance.

**More reliable: B, decisively.** B returns the exact perks Riot recorded including shards. A's
ceiling is keystone + secondary path from an icon match against a compression-degraded frame,
with no shards and no minor runes, at an accuracy no published project has ever measured.

**Is A worth building at all? NO.** Three independent kills, any one sufficient:
1. The information A is meant to harvest **is not on screen**. Full rune pages are never
   rendered passively; shards are never rendered at all.
2. A does not remove B's dependency - to attribute a build to a player you still need the
   identity from the description, which IS B.
3. For pro games the per-game runes + items + skill order are already published as structured
   data (lolesports livestats `details`, Leaguepedia Cargo, esports stats site Z2). Scraping pixels to rebuild
   a dataset that exists as JSON is strictly worse.

Build B. Use CV only for the one thing B genuinely cannot give: **in-video timing** (when an
item completed relative to a fight) - and even there, prefer the Live Client API on RC's own
games over frame scraping.

Two compliance flags: Riot's General Policies bar products that "identify or analyze players who
are deliberately hidden by the game" (relevant if a video subject uses streamer mode); and the
YouTube API Services ToS imposes metadata storage/refresh obligations that were not read here.

### 2.10 The four load-bearing SGP questions, answered plainly

**(a) Is the host pattern and path independently confirmed?**

CONFIRMED, from four mutually independent sources read this session:
1. `LeagueAkari/LeagueAkari` `builtin.ts` (2026-07-18) - the 26-server map incl. `NA1 ->
   usw2-red.pp.sgp.pvp.net`.
2. `aPinat/riot-documentation` README - Riot's PUBLIC edge proxies `{apne|apse|euc|usw}.pp.riotgames.com`
   documented as proxying to `{ROUTE}-green.pp.sgp.pvp.net` for exactly `/match-history-query/v1`.
   This is the strongest single piece of evidence: it shows `match-history-query` is a named Riot
   player-platform service with a public edge, not a private hack.
3. `Coordi777/Sona-Mayhem` `src/lib/lcu.ts` - the issuer-regex host derivation and the working
   request with `Bearer accessToken`.
4. Independent reimplementations of the identical path in C#, Rust, Go, Python and TypeScript
   across ~15 repos (Seraphine, show-me, rank-analysis, LeagueJax, YssLeague, lol-stats,
   Orianna, SadeRift, rank55, ImperialAstronomer, LeagueHistory, Snooze-Manager, Mayhem-Doctor).

The coordinator's `ReformedDoge/Mayhem-Doctor` lead independently corroborates: it surfaced in my
own GitHub code search (`modules/generalUtils.js` / `src/generalUtils.js`) with
`matchHistoryBase = 'https://euc1-red.pp.sgp.pvp.net'` and
`commonBase = 'https://euw-red.lol.sgp.pvp.net'` as its defaults, and the same
`/match-history-query/v1/products/lol/player/{puuid}/SUMMARY?startIndex&count[&tag]` call with
`Authorization: Bearer ${accessToken}`. That matches my LeagueAkari-derived map exactly, from a
different codebase, different author, different language. I am treating the host map and path as
VERIFIED-BY-CONVERGENCE.

STILL UNVERIFIED: (i) the `-red` vs `-green` vs `-blue` colour suffix - three different sources
show three different colours, so **derive it from the token issuer, do not hardcode**; (ii) any
live reachability from Legion - nobody has sent a packet yet; (iii) SGP rate limits.

**(b) AUTH - can an external Python process get the token? YES. This is the decisive answer.**

The token is NOT process-internal. `GET /entitlements/v1/token` is an ordinary **LCU HTTP
endpoint** served on the lockfile port with HTTP Basic `riot:<lockfile password>` - the exact
transport RC already implements in `lcu/lcu_client.py:71`. Evidence that an external process
works, not just an in-client plugin:

- **LeagueAkari is a standalone Electron desktop app**, not a client plugin. Its main process
  reads the token over the lockfile and issues SGP requests from Node. If it worked only from
  inside the client CEF, LeagueAkari could not exist.
- `Tian-Yuanxin/lol-match-stats-local` `backend/sgp_client.py` + `backend/lcu_client.py` is a
  **Python** backend doing exactly this: read the LCU token, Bearer it at the SGP host.
- Mayhem-Doctor is a Pengu Loader plugin and therefore uses relative `fetch` - that is a
  consequence of running inside CEF, not a requirement of the protocol.

So the coordinator's concern ("a route with an unobtainable token is not reach") resolves in
RC's favour: the token IS obtainable from an external process, over plumbing RC already owns.

The real constraint is different and I want it stated sharply: **the League client must be
running and logged in.** The LCU only exists while the client is up; `state.ts` returns
unsupported availability when `leagueClient.state.auth` is null. There is no headless mint. A
theoretical headless path exists via `entitlements.auth.riotgames.com/api/token/v1` behind an RSO
login, but that requires handling the operator's account credentials - out of scope, ToS-hostile,
and not recommended. UNVERIFIED and deliberately not pursued.

Refresh: do not compute an expiry. Subscribe to the LCU websocket on `/entitlements/v1/token`
and `/lol-league-session/v1/league-session-token`; the client pushes a replacement before expiry.
Numeric TTL remains UNVERIFIED.

**(c) ToS status: the terms are SILENT, which is NOT permission.**

Stating this plainly because the coordinator is right that a working third-party plugin is not
permission:

- Riot's **API Terms and Conditions** govern "the Riot Games API" - the developer API at
  `*.api.riotgames.com` behind an `X-Riot-Token`. SGP is not that. The API Terms therefore do not
  grant SGP access, and equally do not name it as prohibited. **Silent.**
- The API Terms DO prohibit "attempting to reverse engineer, decompile, disassemble or otherwise
  attempt to discover or directly access the source code of the Riot Games API, Game, and/or any
  component thereof". Reading a documented-by-community HTTP endpoint the client itself exposes
  is not decompilation - but "directly access ... any component thereof" is broad enough that a
  hostile reading reaches it. I am not going to call that settled either way.
- The API Terms also prohibit "using the Riot Games API in a manner that disrupts, circumvents,
  or interferes with any part of the Game". Ladder-scale harvesting through SGP is a plausible
  "circumvents" (it routes around the developer key's rate limits, which is precisely the appeal).
- Because SGP falls outside the API Terms, the governing document defaults to the **game's own
  Terms of Service** and its third-party-software clause. Enforcement there is against the
  **operator's League ACCOUNT**, not an API key. That is a materially worse blast radius than a
  key suspension.
- Riot has been asked about the adjacent issue and did not answer: `RiotGames/developer-relations`
  issue #959 reported that custom-game info is reachable "through the internal API, bypassing
  RSO"; it was closed **not planned** with no staff reply, and the reporter states a parallel
  security-channel report was ignored. So there is no Riot statement to cite in either direction.

**Factual verdict on the terms: ToS-GRAY, SILENT-not-permissive, account-level risk.** That is
what the documents say, and this document does not soften it.

**OPERATOR RULING: sanctioned 2026-07-28, NON-BLOCKING.** The operator has explicitly accepted
this risk and cleared SGP to proceed. Recorded here as a **risk acceptance**, not as a claim that
the terms say something different - the factual paragraph above stands unchanged and remains the
accurate description of Riot's position. The two statements are not in conflict: the terms are
silent, and the operator has decided that silence is acceptable to them.

Consequences of the ruling for this document: SGP is no longer gated on a terms decision, and no
recommendation below waits on one. What it does NOT change: every UNVERIFIED marking on SGP
stands exactly as written. Permission changes what is allowed, not what is known. The remaining
blocker is purely technical - see 2.10(b) and the token deep-dive at 2.11.

One operational note that survives the ruling because it is engineering, not compliance: the
enforcement surface here is the operator's League ACCOUNT rather than an API key, so the failure
mode of an over-aggressive harvester is losing the account that mints the token - which would
also destroy the channel itself. Rate-limit conservatively for self-preservation, not for
compliance.

**(d) Per-match or pre-aggregated? PER-MATCH. Unambiguously.**

The endpoint name `SUMMARY` is misleading and worth calling out explicitly, because it reads like
a rollup and is not one. VERIFIED from the response type
(`src/shared/types/sgp/match-history.ts`): `SgpMatchHistoryLol` is
`{ games: SgpGameSummaryLol[] }`, and each element is `{ metadata, json }` where `json` is a
complete per-match document with a `gameId`, a `queueId`, and a ten-element `participants[]`
array each carrying `perks`, `item0..item6`, `championId` and `teamPosition`.

`SUMMARY` vs `DETAILS` is the **match doc vs the timeline** distinction, exactly mirroring
Match-V5's `/matches/{id}` vs `/matches/{id}/timeline`. Not summary-vs-raw. There is no
pre-aggregated product anywhere in the SGP match-history surface.

Corroborating: Mayhem-Doctor reads `playerAugment1..6` per participant off FINISHED matches -
a per-participant field only present on a per-match record.

**One more VERIFIED capability from the cross-feed and my own reading - queue filtering.**
`Coordi777/Sona-Mayhem` documents the `tag` parameter format concretely: **`tag=q_<queueId>`**,
e.g. `q_450` for ARAM, combined with `tagsQueryType` = `AND` | `OR`. That means SGP can filter
server-side by queue, including `q_2400`. Mayhem-Doctor's `VALID_QUEUE_IDS = [2400]` is a
production ARAM-Mayhem analyser built on exactly this - independent evidence that queue 2400
comes back from SGP in practice, which is the whole reach gap.

Sona also states SGP "breaks through the LCU 100-game cap" and defaults `count` to 100 - so SGP
paginates deeper than the local LCU route. PARTIAL: author's claim, no stated hard maximum.

### 2.11 THE ENTITLEMENTS TOKEN - deep dive (now the only remaining blocker)

With the terms gate lifted by operator ruling, the sole question that decides whether SGP is
real reach for RC is: **can an external Python process obtain this token?** Answer: **YES,
VERIFIED**, and RC already owns every piece of the plumbing.

**Where it originates.** `GET /entitlements/v1/token` is an **LCU route** - served by the League
client itself, not the Riot Client, and not only from inside the client's CEF context. Confirmed
three ways: (i) LeagueAkari stores it as `leagueClient.data.entitlements.token` and subscribes to
the **LCU** websocket event `/entitlements/v1/token`; (ii) `Neinndall/AssetsManager` catalogs it
in its LCU endpoint map beside `/lol-league-session/v1/league-session-token`; (iii) an
independent LCU reference doc annotates it verbatim as "entitlements token (**for external Riot
services**)" - i.e. its documented purpose is exactly what SGP uses it for.

The token itself is minted upstream by RSO (Riot Sign-On); the League client obtains it during
login and exposes it on the LCU for its own subsystems. The LCU is the retrieval point, not the
issuer.

**Obtainable outside the client process? YES.** The LCU is a normal local HTTPS server. Auth is
HTTP **Basic** with username `riot` and the per-launch password, discovered either from the
`lockfile` in the League install directory (`LeagueClient.exe` dir; colon-delimited
`name:pid:port:password:protocol`) or from the `LeagueClientUx.exe` process command line
(`--app-port=<n>` and `--remoting-auth-token=<pw>`). Both discovery routes are in active use in
open source. The certificate is Riot's self-signed cert, so either pin Riot's CA or skip
verification for `127.0.0.1`.

Proof by existence, from two independent codebases that are NOT client plugins:
- **LeagueAkari** is a standalone **Electron desktop application**. Its Node main process reads
  the token over the lockfile and issues SGP requests itself. If in-CEF execution were required,
  LeagueAkari could not work at all.
- **`Tian-Yuanxin/lol-match-stats-local`** is a **Python backend** (`backend/lcu_client.py` +
  `backend/sgp_client.py`) doing precisely this: discover the LCU, read the token, Bearer it at
  the SGP host. Its own (Chinese) comment translates to: "for the Bearer, prefer the LCU
  GET /lol-league-session/v1/league-session-token; you may also try the entitlement accessToken"
  - i.e. a working Python precedent for both token types.

Mayhem-Doctor's use of relative `fetch` is a consequence of being a Pengu Loader plugin running
inside the client CEF - a property of that host, not a requirement of the protocol.

**RC-specific:** `lcu/lcu_client.py:71` already implements lockfile + Basic auth. The new work is
a `core/sgp_client.py` that reuses that handle, reads `/entitlements/v1/token`, and issues
`Bearer`-authenticated requests to the pp host. No new auth mechanism, no credential handling,
no injection.

**Response shape (VERIFIED):** `{ accessToken, token, issuer, subject, entitlements }`.
- `accessToken` - the JWT you put in `Authorization: Bearer`. **This is the one SGP wants.**
- `token` - a different entitlements JWT. Not the one for match-history-query.
- `issuer` - e.g. `https://na-red.lol.sgp.pvp.net`; parse it to derive the SGP server and the
  live host colour instead of hardcoding.
- `subject` - the player's own PUUID.
- `entitlements` - usually `[]`.

**Lifetime: numeric TTL UNVERIFIED.** No source read this session states it. It is an RSO-issued
JWT and therefore carries an `exp` claim - a local implementation can simply decode the JWT
payload and read `exp` directly rather than guessing, which is the pragmatic resolution of this
unknown. I am NOT asserting a number.

**What refreshing requires: nothing active - VERIFIED mechanism.** The League client pushes a
replacement over the **LCU websocket** before the old one expires.
`Coordi777/Sona-Mayhem` documents it explicitly: "LCU will proactively push a new token via the
WS event when the token is about to expire - you do not need to compute the expiry yourself."
LeagueAkari implements the same pattern as a reaction on the token field. So the correct client
is: connect the LCU websocket, subscribe to `/entitlements/v1/token` and
`/lol-league-session/v1/league-session-token`, seed the cache with one initial GET of each, and
overwrite on every push. Do not poll, do not schedule a refresh, do not compute an expiry.

Known race to guard: LeagueAkari's CHANGELOG records an intermittent "JWT Token not set" fault
where SGP was called before the token had arrived. Gate every SGP call on a token-ready flag
covering **both** tokens (LeagueAkari's `isTokenReady` requires both to be set).

**The genuine hard constraint, restated:** the League client must be RUNNING and LOGGED IN. The
LCU does not exist otherwise, so there is no token, so there is no SGP. This makes SGP a
**live-session channel**, not a headless cron channel. Any RC design must either piggyback on
sessions where the operator is already playing, or accept that the harvester only runs while the
client is open. A headless RSO mint against `entitlements.auth.riotgames.com/api/token/v1` is
theoretically possible but requires handling the operator's account credentials - out of scope,
not researched further, UNVERIFIED, and not recommended.

---

## 3. Reach problem 2 - cross-region breadth

### 3.1 Routing values - VERIFIED

**Platform routing (15 live):** `br1, eun1, euw1, jp1, kr, la1, la2, me1, na1, oc1, ru, sg2,
tr1, tw2, vn2` (+ `pbe1`). `ph2` and `th2` were **deprecated and folded into `sg2` on
2025-01-08**. `me1` (MENA) is current and is missing from several community routing tables - do
not copy an old list.

**Regional routing (4 for LoL):** `americas, asia, europe, sea` (+ `esports`/`esportseu` for
ACCOUNT-V1 only; `apac` deprecated).

| Platform group | Regional host |
|---|---|
| NA1, BR1, LA1, LA2 | americas |
| KR, JP1 | asia |
| EUN1, EUW1, ME1, TR1, RU | europe |
| OC1, SG2, TW2, VN2 | sea |

**Which routing per API - VERIFIED:**

| API | Routing | Host example |
|---|---|---|
| LEAGUE-V4 (challenger/gm/master leagues, entries) | **Platform** | `euw1.api.riotgames.com` |
| LEAGUE-EXP-V4 `/entries/{queue}/{tier}/{division}` | **Platform** | `kr.api.riotgames.com` |
| SUMMONER-V4 | **Platform** | `na1.api.riotgames.com` |
| MATCH-V5 (ids, match, timeline) | **Regional** | `europe.api.riotgames.com` |
| ACCOUNT-V1 (by-puuid, by-riot-id) | **Regional** | `americas.api.riotgames.com` |

ACCOUNT-V1 does NOT offer `sea`; use `asia` for SEA platforms.

### 3.2 Where the quota binds - VERIFIED, and it is the single most useful number here

| Key type | Limits | Sustained ceiling |
|---|---|---|
| Development | 20 req / 1 s AND 100 req / 2 min | 0.833 req/s |
| Personal | 20 req / 1 s AND 100 req / 2 min | 0.833 req/s |
| Production | 500 req / 10 s AND 30,000 req / 10 min | 50 req/s |

For dev/personal the **2-minute window binds**, not the 20/s burst. Effective rate is
100/120 = **0.833 req/s**, not 20/s. Any plan sized off "20 per second" is wrong by 24x.

**PER REGION, not global - VERIFIED, quoted from Riot's own docs:**
- Portal, personal key section: "Note that rate limits are enforced per region."
- Portal, production key section: "Remember that this rate limit is enforced per region."
- Riot's rate-limiting doc: "Every call made to any Riot Games API endpoint in a given region
  counts against the app rate limit for that key in that region", and the same sentence for
  method limits. The doc carries worked examples showing a 429 on `na1` while `la1` still 200s.

**Consequence, and this is the asymmetry that shapes the whole design:** one key gives you
**15 independent platform buckets** for ladder work but only **4 independent regional buckets**
for match work. Ladder throughput scales 15x; MATCH-V5 throughput scales only 4x. A production
key yields roughly 750 req/s aggregate on ladder endpoints but only ~200 req/s aggregate on
match-v5. **Match-V5 is the bottleneck, permanently, and no amount of region fan-out fixes it.**

UNVERIFIED: Riot's doc says "region" and its examples use PLATFORM hosts. I could not find a
sentence explicitly confirming the four REGIONAL hosts each get a separate app bucket. It is
strongly implied (distinct hosts; match-v5 only lives there) but **measure it on day 1** by
bursting and reading `X-App-Rate-Limit-Count` on `americas` vs `europe`.

**Per-method limits: UNVERIFIED and unpublishable.** Riot's reference pages for LEAGUE-EXP-V4
`/entries`, LEAGUE-V4 `challengerleagues`, MATCH-V5 `by-puuid/ids`, `matches/{id}` and `timeline`
carry **no rate-limit section at all**. The community numbers ("500/10s for match endpoints",
"2000/1min for summoner") are illustrative examples in Riot's rate-limiting write-up, are
per-key, and could not be tied to a current primary source. **Read `X-Method-Rate-Limit` off a
live response with your own key. Do not hardcode.**

**Header semantics - VERIFIED:**
- `X-App-Rate-Limit` / `X-Method-Rate-Limit`: `limit:window_seconds`, comma-separated for
  multiple windows, e.g. `20:1,100:120`.
- `X-App-Rate-Limit-Count` / `X-Method-Rate-Limit-Count`: `count:window`, same shape.
- `X-Rate-Limit-Type`: on 429 only. Values `application` | `method` | `service`.
- `Retry-After`: "the remaining number of seconds before the rate limit resets".

Two 429 flavours: infrastructure-enforced (has `X-Rate-Limit-Type` + `Retry-After` - sleep
exactly `Retry-After`), and service-enforced (**no** `X-Rate-Limit-Type`, **no** `Retry-After` -
Riot's guidance is back off "a reasonable amount of time (e.g., 1 second)"). A third class,
**service rate limits, is shared across ALL applications** hitting that service - so a
well-behaved single key can be 429'd by other people's traffic. Backoff must handle a 429 you
did not cause.

Contractual note: developer.riotgames.com/terms says "A Development Key shall not be permitted to
make more than ten (10) network calls every ten (10) seconds" = 1 req/s, contradicting the
portal's 20/s + 100/2min. The portal number is what the infrastructure enforces and reports in
headers. Treat the Terms clause as a contractual floor and the portal as observed behaviour;
UNVERIFIED and unreconciled by any source found.

### 3.3 Ladder enumeration - what it actually takes

**LEAGUE-EXP-V4** `GET /lol/league-exp/v4/entries/{queue}/{tier}/{division}`
- `queue`: `RANKED_SOLO_5x5, RANKED_TFT, RANKED_FLEX_SR, RANKED_FLEX_TT`
- `tier`: **`CHALLENGER, GRANDMASTER, MASTER, DIAMOND, EMERALD, PLATINUM, GOLD, SILVER, BRONZE,
  IRON`** - apex tiers ARE supported here. That is why league-exp-v4 exists.
- `division`: `I, II, III, IV` (use `I` for apex).
- `page` query param, defaults to 1.

**LEAGUE-V4** `/lol/league/v4/entries/{queue}/{tier}/{division}` supports **only** `DIAMOND,
EMERALD, PLATINUM, GOLD, SILVER, BRONZE, IRON` - no apex. Apex comes from the three dedicated
endpoints `/lol/league/v4/{challengerleagues|grandmasterleagues|masterleagues}/by-queue/{queue}`,
one call each, whole league inline.

**Pagination - VERIFIED, with a trap:**
- Page size is **~205 entries, not 200** (developer-relations issue #1115, filed 2025-11-13).
- Exhaustion signal is an **empty array**. No total count, no cursor.
- **HARD 10,000-ENTRY CAP on apex tiers.** Issue #1115: both `masterleagues/by-queue` and
  `league-exp-v4 .../MASTER/I?page=N` stop at 10,000 (48 x 205 + 160). "After page 49, the
  endpoint returns an empty list." **This truncates MASTER on EUW1 and KR**, where the real
  Master population exceeds 10k. Open, no Riot response. **Plan for Master being incomplete on
  high-population regions** - it silently biases any Master-tier stratum.
- UNVERIFIED: whether the 10k cap also applies below Master (IRON IV / SILVER on KR could
  approach it). Probe.

**summonerId -> puuid hop: NOT needed. VERIFIED.** `LeagueEntryDTO` returns `puuid` directly
("Player's encrypted puuid"). In the generated-from-Riot-reference Riven schema,
`league_exp_v4::LeagueEntry.puuid` is **required/non-optional** while `summoner_id` is optional;
`league_v4::LeagueItem.summoner_id` is documented "deprecated and will be removed. Use `puuid`
instead." Riot removed accountId/summonerId-keyed endpoints effective **2025-06-20**, including
`/lol/league/v4/entries/by-summoner/{encryptedSummonerId}`. The crawl is
league-exp-v4 -> puuid -> match-v5. Community guides (hextechdocs' crawling article included)
that still describe a summoner-v4 hop are **stale**. **Key everything on puuid.**

**Wall-clock, computed.** Per region per queue: 7 non-apex tiers x 4 divisions = 28 paginated
buckets + 3 apex calls. Requests ~= `R/205 + 31`, R = ranked players in that region/queue.

R itself is **UNVERIFIED - Riot publishes no ranked-population figure.** Worked on a stated
placeholder of R = 2,000,000 (EUW-scale), to be replaced by the first measured run:

| Job | Requests | Personal (0.833/s) | Production (50/s) |
|---|---|---|---|
| One region full ladder | ~9,787 | ~3.3 hours | ~3.3 minutes |
| Match-id pull, 2M players (regional bucket) | 2,000,000 | ~27.8 days | ~11.1 hours |
| Match detail, ~4M unique matches | 4,000,000 | ~55 days | ~22.2 hours |
| + timelines | +4,000,000 | ~110 days | ~44.4 hours |

**The ladder is cheap; the match pull is the whole cost.** A personal key is fine for ladder
snapshots (hours) and hopeless for match backfill (months). A production key turns a
single-region stratified corpus into a 1-3 day job.

### 3.4 PUUID scope - VERIFIED, and it has a nasty operational edge

- **Same across regions for one key: YES.** Riot's PUUID announcement: on a region transfer "a
  new account ID and Summoner ID are created in the new region but the PUUID remains the same in
  both regions." A puuid harvested on `kr` is valid on the `asia` match host with the same key.
- **Stable across keys: NO.** "All encrypted values are unique per API Key holder."
- Documented length: exactly 78 characters.

**Operational consequence: any puuid corpus is KEY-LOCKED.** Rotating or regenerating the API key
invalidates every stored puuid, and you can never join your puuid-keyed data against anyone
else's. This is the same root cause as RC's known stale-PUUID 400 failure mode. Budget a full
re-resolution pass if the key ever changes, and store the riotId alongside every puuid so
re-resolution is possible at all.

### 3.5 Production key - the approval bar is "public and reviewable", not "technically good"

- **Personal keys can NEVER be raised.** Portal: personal applications "won't be approved for
  rate limit increases".
- Production requirements, VERIFIED from the portal FAQ:
  - "Production keys are reserved for fully functioning applications" - working, hosted prototype.
  - "We cannot grant production keys to applications without a verified website."
  - "We are unable to accept Github repositories and source code in lieu of a functioning
    application/site."
  - The site must display a **Terms of Service and a Privacy Policy**.
  - Turnaround: reviewed weekly, "sometimes ... up to three weeks".
- Grants 500/10s + 30,000/10min per region, plus Tournament API.
- **Read for RC:** RC is a localhost-only single-user dashboard. It has no verified public
  website, so it **fails the gate as currently shaped**. A personal key covers it legally
  ("private bots, personal stat tracking, and personal research" are named acceptable uses) but
  caps at 0.833 req/s per region, which rules out bulk ingestion. Getting production means
  standing up a real hosted site with ToS + privacy policy and a walkable user flow - a product
  decision, not an engineering one. UNVERIFIED: approval rate for hobby-scale coaching tools.
- FAQ rule worth noting: "You may NOT have multiple applications to bypass rate limits."

### 3.6 Terms - storage, redistribution, attribution

- **Caching / storage:** there is **no explicit clause** in the Developer Policies or the API
  Terms setting a cache TTL, retention limit, or storage prohibition. Permitted by omission. The
  only storage-adjacent clause is on termination: "Upon termination ... You shall immediately
  cease using the Materials, including without limitation any Game Information in Your
  possession, as well as delete all of the Game Information in Your possession."
- **Redistribution: effectively NO.** Prohibited: "Distributing, selling, transferring,
  encumbering, sublicensing, renting, loaning, lending or leasing the Riot Games API ... to any
  third party" and "using the Riot Games API to use, distribute or transmit the Game Information
  in any manner not authorized under these API Terms". The Developer API Policy adds that a
  product may not act as a "data broker between our API and another third-party company".
  Reselling or charging for access requires "Riot's prior written approval".
- **Attribution: REQUIRED, fixed text.** "[Your Product Name] is not endorsed by Riot Games and
  does not reflect the views or opinions of Riot Games or anyone officially involved in producing
  or managing Riot Games properties. Riot Games and all associated properties are trademarks or
  registered trademarks of Riot Games, Inc."

Read for a coaching tool: harvesting a stratified corpus for RC's own models is fine. Publishing
the corpus, exposing it as a feed, or handing it to another company is not.

---

## 6. Static data - which source carries NUMERIC rune and item values

All JSON below was **actually fetched live on 2026-07-28**, field lists are real.

### 6.1 The bottom line first

**No source ships structured numeric rune values. Not one.** DDragon, CommunityDragon, the LCU
asset tree, Meraki - every route delivers keystone numbers as a **prose string**. Manual
extraction is **unavoidable** for runes. If the operator was hoping one of these would supply
Electrocute-damage-by-level as a number, the answer is no, and that is now settled.

### 6.2 DDragon

- `versions.json` -> 582 entries, newest **`16.14.1`**. **Numbering note: DDragon `16.x` IS the
  publicly-announced `26.x` patch.** A "16 vs 26" mismatch is NOT lag - do not chase it.
- **`runesReforged.json`** - style keys `id, key, icon, name, slots`; rune keys, COMPLETE:
  **`id, key, icon, name, shortDesc, longDesc`**. **Zero numeric fields.** Electrocute's numbers
  exist only inside prose: `"longDesc": "...Damage: 70 - 240 (+0.1 bonus AD, +0.05 AP) damage.<br>Cooldown: 20s..."`.
  Legend: Alacrity: "Gain 3% attack speed plus an additional 1.5% for every Legend stack (max 10
  stacks)". Conqueror: "gaining 1.8-4 ... Adaptive Force per stack".
- **`item.json`** - `stats` holds ONLY base stat mods (`FlatHPPoolMod`, `FlatArmorMod`,
  `FlatPhysicalDamageMod`, `PercentAttackSpeedMod`, `FlatCritChanceMod`, ...). Passive/active
  numbers are NOT in `stats` - they live in the HTML `description` string (`<passive>`,
  `<active>`, `<magicDamage>` tags) and sometimes as unlabeled
  `effect.Effect1Amount..EffectNAmount` raw datavalues with no semantic key.
- **Patch lag - Riot's own words:** "Updating Data Dragon after each League of Legends patch is a
  manual process, so it is not always updated immediately after a patch." Community reports of
  up to two days; historical incidents include realms stuck on 8.23.1 after 8.24.1 shipped.
- **Licence:** no explicit licence. Covered by Legal Jibber Jabber / Developer API policies plus
  the standard "not endorsed by Riot Games" disclaimer. UNVERIFIED: no formal written
  redistribution grant exists.

### 6.3 CommunityDragon - the currency winner

- **Freshness is excellent and MEASURED:** `status.live.txt` returned
  **`2026-07-28T06:00:02Z done`** - re-scraped hours before this research. A `/pbe/` lane exists
  at the same path shape, giving pre-patch warning.
- **`v1/perks.json`** field list, identical on every entry: **`id, name,
  majorChangePatchVersion, tooltip, shortDesc, longDesc, recommendationDescriptor, iconPath,
  endOfGameStatDescs, recommendationDescriptorAttributes`**. **Still no numeric value fields.**
  `tooltip` contains UNRESOLVED placeholders (`@TotalDamage@`, `@f1@`, `@GraceWindow.2@`,
  `{{ Item_Melee_Ranged_Split }}`) needing the game's runtime variable table. `longDesc` has
  numbers substituted but only as prose. The one numeric-ish extra is
  `recommendationDescriptorAttributes` (Legend: Alacrity -> `{"kDamagePerSecond": 10}`) which is
  a UI hint weight, NOT the rune's value. Do not mistake it for one.
- **`v1/perkstyles.json`** - `schemaVersion, styles`; style keys `id, name, tooltip, iconPath,
  assetMap, isAdvanced, allowedSubStyles, subStyleBonus, slots, defaultPageName, defaultSubStyle,
  defaultPerks, defaultPerksWhenSplashed, defaultStatModsPerSubStyle`. Pure topology, no values -
  but this IS the authoritative tree/slot structure.
- **`v1/items.json` is WORSE than DDragon for stats.** Keys: `id, name, description, active,
  inStore, from, to, categories, maxStacks, requiredChampion, requiredAlly,
  requiredBuffCurrencyName, requiredBuffCurrencyCost, specialRecipe, isEnchantment, price,
  priceTotal, displayInItemSets, iconPath`. **There is no `stats` object at all** - even base
  stats are HTML inside `description` (`<stats><attention> 25</attention> Move Speed</stats>`).
  Use DDragon for item stats, CDragon for rune ids/topology/icons.
- Raw bin data under `/latest/game/data/` has no perks directory; CDragon's own docs say bin
  files have "no unified format nor an easy way to interpret it". Not a practical rune-value route.
- **Licence:** "CommunityDragon was created under Riot Games' 'Legal Jibber Jabber' policy using
  assets owned by Riot Games. Riot Games does not endorse or sponsor this project."
  Community-run, Patreon-funded, **no formal data licence, no SLA**.

### 6.4 Meraki Analytics - MEASURED as ~15 months stale. Direct RC impact.

- **Runes: there is no runes file. None.** `/riot/lol/resources/latest/en-US/runes.json` returns
  **HTTP 404**. Their README says it outright: "Data other than that for champions and items
  should be covered by the data that Riot provides, or by the CDragon project."
- **Items: the best parsed base stats of any source.** `items/3153.json` has a `stats` object
  with 24 stat categories, each nested `{flat, percent, perLevel, percentPerLevel, percentBase,
  percentBonus}`. But passives remain prose - and in *wiki markup*, e.g. Mist's Edge:
  `"Basic attacks deal {{as|'''bonus''' physical damage}} [[on-hit]] equal to {{as|{{rd|8%|5%}} of the target's '''current''' health}}"`.
- **Staleness is measured, not anecdotal:**
  - `champions/Yunara.json` -> **404**, while DDragon 16.14.1 has Yunara (key 804). Yunara
    shipped in 2025.
  - Highest `patchLastChanged` observed anywhere: Aurora `25.07`, Ambessa `25.05`, Aatrox `25.04`.
    Nothing in 25.1x or 26.x.
  - Open issues #112 (Mel missing, 2025-02-26), #119 (update frequency, 2025-08-30), #120
    (2025-09-09).
  - Repo last commit **2025-11-12** (`df17d37`), sporadic bugfixes from 3 outside contributors,
    not Meraki staff.
  - **Conclusion: `latest` is effectively frozen around patch 25.07 (~April 2025), roughly 15
    months stale.** Life support, not dead.
- **Licence: MIT.** `MIT License / Copyright (c) 2020 Meraki Analytics, LLC`, standard body. Plus
  a README request: "If you use this data for your apps, cache it on your own servers/apps to
  reduce the load on our services." **This is the only source in this entire document with a
  clean, permissive, redistributable licence.**

**ACTION FOR RC, and it is not hypothetical.** CLAUDE.md records Daemon Slayer at
ENGINE_VERSION 1.262.0 / patch 16.14.1 / 706 items / 173 champs, and the memory index lists
`reference_meraki_items_bulk` as a DS data feed. If DS item stats are sourced from
`cdn.merakianalytics.com/.../latest/`, then **any item added or restatted after ~April 2025 is
missing or wrong in DS**, while DS advertises patch 16.14.1. That is a live correctness gap
between the claimed patch and the underlying data. Recommend probing `data/daemon_slayer/` item
coverage against DDragon 16.14.1 before the next ENGINE bump. Flagged, not actioned - out of
scope for this research task.

### 6.5 The alternatives - and the actual answer for numeric runes

- **League Wiki.** IMPORTANT CORRECTION: the wiki **moved off Fandom**.
  `leagueoflegends.fandom.com` returns HTTP 402 to fetchers. The live wiki is
  **`wiki.leagueoflegends.com`**, and **it does NOT have Cargo** - `action=cargoquery` returns
  `{"error":{"code":"badvalue","info":"Unrecognized value for parameter \"action\": cargoquery."}}`.
  Data lives in Lua modules and templates: `Module:ChampionData/data`, `Module:ItemData/data`,
  `Template:Item_data_<name>`, and for runes **`Template:Rune_data_<name>`** with params
  `1, disp_name, released, path, shard slots, slot, description, description2..4, cooldown,
  range, removed, wr`. So **`cooldown` and `range` ARE structured**; damage/ratios/per-stack are
  still in `description`, but in wiki template markup (`{{as|...}}`, `{{rd|8%|5%}}`) which is far
  more regular and machine-parseable than Riot's HTML. `Module:RuneData/data` does not exist -
  runes are template-based.
  - **The wiki is more current than DDragon prose.** Measured discrepancy today: wiki Electrocute
    = `70 - 260 (based on level) (+ 10% bonus AD) (+ 5% AP)`; DDragon/CDragon longDesc =
    `70 - 240 (+0.1 bonus AD, +0.05 AP)`. UNVERIFIED which is correct for 16.14.1 - but they
    disagree, and Riot's longDesc strings are hand-maintained and known to drift. **If RC's rune
    registry was seeded from DDragon longDesc, some values may be stale.**
  - **Licence: UNVERIFIED by direct fetch** (402 on Fandom; no licence page read on the new
    domain). Fandom-era content was CC BY-SA 3.0 and the migrated wiki is widely understood to
    carry CC BY-SA. **Treat as CC BY-SA, attribution + share-alike required, until confirmed.**
- **LCU `/lol-game-data/assets/v1/perks.json`** - byte-identical in shape to the CDragon file;
  CDragon's path IS the mirror of the LCU asset tree (the `iconPath` values literally read
  `/lol-game-data/assets/v1/perk-images/...`). Same 10 fields, same prose-only numbers. **Zero
  extra numeric structure.** Its only advantage: live on the installed patch with no mirror lag.
- **lolstaticdata forks / successors:** GitHub repo search returned **0 maintained forks or
  successors**. None exists. UNVERIFIED: private forks.

### 6.6 Recommended static-data combination

1. **Rune NUMERIC values:** parse `wiki.leagueoflegends.com` `Template:Rune_data_<name>`
   `description` fields as PRIMARY (most current, regular markup, `cooldown`/`range` already
   structured). Cross-check against CDragon `longDesc`. Regex level-ranges and ratios into RC's
   own registry, pin the extraction with tests, re-run on patch day. **Manual extraction is
   unavoidable - budget for it, do not keep looking for a source that has it.**
2. **Rune ids / trees / slots / icons:** CDragon `v1/perks.json` + `v1/perkstyles.json`.
   Refreshed within hours of live, plus a `/pbe/` pre-warning lane. Strictly better than DDragon.
3. **Item BASE stats:** DDragon `item.json` `stats` for currency. Use Meraki's richer
   `{flat, percent, perLevel, percentBase, percentBonus}` shape as the SCHEMA MODEL, but do NOT
   trust Meraki's CONTENT as current.
4. **Item PASSIVE numbers:** manual, from wiki `Template:Item_data_<name>`. Same unavoidable
   extraction as runes.

---

## 5. Reach problem 4 - community aggregators

### 5.1 THE STRUCTURAL ANSWER, before any endpoint detail

Every one of aggregator A / aggregator B / aggregator D / Overlay App F / Overlay App E / AGGREGATOR N / Aggregator C is
**PRE-AGGREGATED** for the build-data use case. What they expose is win rate, pick rate, ban
rate, and a modal build, already rolled up over a sample you cannot see, filtered by rank tier
and role on their side.

**Pre-aggregated sources cannot answer per-match questions.** Concretely, for RC they CANNOT
answer:
- "in games where this champion built X before Y, what happened to gold-at-15" - needs per-match.
- "what did THIS opponent build in their last 20 games" - needs per-match (aggregator A/Overlay App F DO
  render a per-player match list, but that is their re-presentation of Match-V5, which RC can get
  directly and legally).
- anything requiring a join between build choice and timeline events.
- any Laplace/shrink treatment of small samples, because you do not get the sample count in a
  form you can trust or recompute.

What they CAN answer, cheaply and well: "what is the current consensus build for champion C in
role R at rank tier T on patch P" - i.e. a **prior**, not evidence. That is a legitimate and
useful thing for a coaching engine to have. It is just not a substitute for a corpus.

So the honest ranking is: aggregators are a **fast, low-effort source of PRIORS**, they are a
**licence and anti-bot minefield**, and they are **structurally incapable** of being the corpus.

### 5.2 What I verified myself, first-hand, this session

I read the robots.txt of the three most relevant sites directly. These are primary sources and
they are unambiguous.

**aggregator D robots.txt - VERIFIED verbatim.** Carries the Cloudflare Managed content-signal
block:
```
User-agent: *
Content-Signal: search=yes,ai-train=no,use=reference
Allow: /
...
User-agent: ClaudeBot
Disallow: /
User-agent: CCBot
Disallow: /
User-agent: GPTBot
Disallow: /
User-agent: Google-Extended
Disallow: /
```
plus the preamble: "**ANY RESTRICTIONS EXPRESSED VIA CONTENT SIGNALS ARE EXPRESS RESERVATIONS OF
RIGHTS UNDER ARTICLE 4 OF THE EUROPEAN UNION DIRECTIVE 2019/790**" and "As a condition of
accessing this website, you agree to abide by the following content signals."

This matters more than a normal robots.txt. EU DSM Article 4 is the text-and-data-mining
exception, and Article 4(3) lets a rightsholder **expressly reserve** TDM rights - which
disapplies the exception. aggregator D has done exactly that: `ai-train=no`, `use=reference`.
So scraping aggregator D to build a training or derived dataset is not merely
against-the-robots-file; it is against an express reservation the site conditions access on.

**aggregator B robots.txt - VERIFIED verbatim.** Identical Cloudflare content-signal block (same
`ai-train=no,use=reference`, same ClaudeBot/CCBot/GPTBot/Google-Extended disallows), PLUS a
global rule that matters operationally:
```
User-agent: *
Disallow: /*?*
Allow: /wow/*?*
```
**`Disallow: /*?*` blocks every URL carrying a query string** for all agents - which is exactly
the shape a JSON/XHR data endpoint takes. Sitemaps are served from `static.bigbrain.gg`
(aggregator B is a BigBrain property).

**aggregator A robots.txt - VERIFIED verbatim.** Markedly more permissive: `User-Agent: *` / `Allow: /`,
with `Disallow: /*?*` scoped only to Googlebot and Bingbot, and a single named block on
`carbon-umbrella-bot`. **No Cloudflare content-signal block, no ClaudeBot disallow, no EU DSM
reservation.** On the robots.txt axis alone, aggregator A is the least hostile of the three.

**Process note, stated for the record:** because aggregator D and aggregator B explicitly `Disallow: /` for
ClaudeBot, I did **not** fetch their content pages, ToS pages, or any data endpoint. Everything
attributed to those two sites here comes from their robots.txt (which is always fetchable) or
from third-party descriptions. That is a deliberate limit on this research, not an oversight -
and it is itself a finding: an automated pipeline running under an identifiable agent UA is
already out of bounds on two of the three.

### 5.3 THE STANDOUT FINDING - aggregator A ships an OFFICIAL, MIT-licensed MCP server

This is the one genuinely sanctioned programmatic surface in the whole aggregator space and it
changes the recommendation completely.

**`https://aggregator-a.invalid/mcp`** (Streamable HTTP), source at `aggregator-a/mcp-server`, **MIT licence**,
no auth found. It exposes `lol_get_champion_analysis`, documented as returning "optimal builds
(items, runes, skills, spells)". First-party, published by Aggregator A themselves, under a permissive
licence - which sidesteps the scraping question entirely because it is not scraping.

Note the internal contradiction in aggregator A's own documents, worth recording because it is why the
MCP path matters:
- aggregator A **Help Center** states aggregator A "does not prohibit data crawling or web scraping", subject
  to citing the source and not making excessive requests.
- aggregator A **Terms of Use** (`aggregator A terms of service`) prohibits "scraping or data mining while
  using the Sites or Services" and using "automated scripts to collect information", and bars
  reproduction/distribution/derivative works "without our express written consent".

Those two cannot both govern a scraper. The MCP server is unaffected by the tension - it is an
interface aggregator A published for programmatic consumption.

aggregator A's internal REST, for completeness (VERIFIED shape from open source, not probed here):
`https://aggregator-a.invalid/api/champion/{region}/champions/{mode}/{championId}/{position}?tier={tier}`
with modes `ranked` / `aram` / `urf`, plus a tier-list route and
`/api/global/champions/ranked/versions`. Payload (~19KB) carries `rune_pages` **including stat
shards**, `summoner_spells`, `starter_items`, `boots`, `core_items`, `last_items`, `skills` +
`skill_masteries`, `counters`. Tiers: `all|gold_plus|platinum_plus|emerald_plus|diamond_plus|master_plus`.
Anti-bot: CloudFront; plain fetches 403, a browser UA passes, headless-Chrome fingerprints 403.
UNVERIFIED: no RapidAPI listing found (absence, not proof).

### 5.4 Per source

| Source | API surface | PER-MATCH or PRE-AGG | Stratified? | Licence / redistribution | Anti-bot |
|---|---|---|---|---|---|
| **aggregator A MCP** | **OFFICIAL** `mcp-api.aggregator A/mcp`, `aggregator-a/mcp-server`, no auth | **PRE-AGG** | tier + role + region | **MIT (client)**. Help Center permits crawling w/ citation; ToS forbids scraping - MCP avoids the conflict | n/a |
| **aggregator A internal REST** | `lol-api-champion.aggregator A/api/...` | **PRE-AGG** | region path, `position`, 6 tier brackets | ToS forbids scraping + derivative works w/o written consent | CloudFront; UA-sensitive |
| **aggregator B `stats2` CDN** | `aggregator-b-stats.invalid/lol/{statsVer}/overview/{patch}/{queue}/{champId}/{ovVer}.json`; versions from `static.bigbrain.gg/.../ugg-api-versions.json`. (A GraphQL at `aggregator B GraphQL API` exists but serves summoner/rank, **not builds**) | **PRE-AGG** (`matches`/`wins` counters) | **BEST IN CLASS** - one ~460KB file holds `overview[region][rank][role]`, 18 regions x 17 rank brackets x 5 roles; queues incl. `ranked_solo_5x5`, `normal_aram`, `arena`, `pick_urf`, `one_for_all`, `nexus_blitz` | ToS (2018-05-25) has **NO scraping/redistribution clause at all**. BUT robots: `ai-train=no`, EU DSM Art.4 reservation, **ClaudeBot `Disallow: /`**, `Disallow: /*?*` | Cloudflare |
| **aggregator D** | `a1.aggregator D/mega/?ep={rune\|build-itemset\|build-earlyset\|build-team\|tier\|counter}&patch=&c={slug}&lane=&tier=&queue=&region=` | **PRE-AGG** (`[id, picks, wins]`) | tier, lane, region, queue, patch (`region=all` pools) | **NO ToS document exists** - only a privacy policy. No data licence. Silence, not permission. robots: `ai-train=no`, Art.4, **ClaudeBot `Disallow: /`** | Cloudflare; needs browser UA + `Referer: https://aggregator-d.invalid/`; 40-entry counter cap |
| **Overlay App E** | `league-champion-aggregate.iesdev.com/graphql`, `data.v2.iesdev.com`, `datalake-server.iesdev.com/graphql` | **PRE-AGG** (`builds { games, wins, runes{...}, summonerSpells }`) | tier, role, region, queue, **plus `opponentChampionId` matchup-scoped** | ToS **unfetchable (403)**. **RC ALREADY HAS A STANDING POSITION - see 5.6** | Cloudflare on overlay app E; iesdev hosts unauthenticated |
| **aggregator G** | `aggregator G build API/champion/build?platform_id=&champion_id=&game_version=&tier=` - **the only one live-readable anonymously** | **PRE-AGG** | tier + platform + lane + patch | robots **fully permissive** (`Allow: /`, no AI exclusions). **No ToS document exists anywhere on the site** | none |
| **Aggregator C** | `app.aggregator C/api/lol/graphql/v1/query`. Richest build payload: Starter/Early/Core/Situational/FullBuild + `skillOrder` + `skillMaxOrder` | **PRE-AGG** | rank, role, queue, region, patch - **richest filters** | ToS **explicitly bars** automated access: prohibits accessing "through the use of any engine, software, tool, agent, device or mechanism (including spiders, robots, crawlers, data mining tools or the like)" and any commercial use | robots permissive for `/api/lol/`, ToS is not |
| **Overlay App F / Aggregator H** (Wargraphs, same operator) | **No public API and no JSON endpoint found in any open-source consumer** - HTML pages only | Overlay App F is live-game/player-scoped; LoG champion pages **PRE-AGG** | LoG UI has rank+role; API params UNVERIFIED | ToS **unfetchable** (robots.txt 403, ToS behind a Cloudflare challenge). Snippet-only paraphrase suggests the most restrictive terms in the set | Cloudflare challenge - hardest target |
| **AGGREGATOR N** | Only `aggregator N/api/lol/arena/v1/champion/statistics` found - **no build endpoint at all** | **PRE-AGG** | UI yes; API UNVERIFIED | ToS 403s; robots blocks ClaudeBot/GPTBot, `ai-train=no` | 403 |
| **aggregator Z1** | `aggregator Z1/v1/tierlist?...`; **no champion-build endpoint found** despite build pages existing | **PRE-AGG** | tier + patch | ToS at `/tos` is itself robots-disallowed and 403s | Cloudflare (consumers use cloudscraper/Playwright) |

**MEASURED CAVEAT on aggregator G**, the only source live-probed: every non-KR `platform_id` tried
(NA1, NA) returned an **empty `build_by_lane`**. Two independent open-source consumers hardcode
`platform_id=KR`. So aggregator G's apparent openness does not buy cross-region stratification.

**aggregator D sample size, as the site itself states it:** "We are the only League of Legends
stats site to analyse every champion from every ranked game"; patch 16.14 Emerald+ =
**25,611,637 champions** analysed. It claims to include 100 percent of champions played in the
selected bracket. That is the largest claimed sample of the group. UNVERIFIED conflict: one
implementer reports runes/skills/spells return no data via `mega` (served only in
server-rendered HTML), while another repo uses `ep=rune` successfully.

### 5.5 The Riot-terms overlay that applies to ALL of them

Riot's Developer Policies state verbatim: **"Products should use supported services from Riot
Games for data ingestion"** and "All products must be registered in, and audited by Riot Games
through the Developer Portal". The API Terms prohibit "using the Riot Games API to collect any
additional information about the Game or Game users that is not provided Game Information or
permitted by the Riot Games API", and bar acting as a "data broker between our API and another
third-party company".

Read together: there is **no clause forbidding scraping other websites in those words** - the
operative constraint is the affirmative "use supported Riot services" mandate, plus each
aggregator's own terms. That is a meaningful distinction and I am not going to overstate it.

The Legal Jibber Jabber grant (VERIFIED) is a "personal, non-exclusive, non-sublicenseable,
non-transferable, **revocable**, limited license" for noncommercial fan projects, with a
commercial carve-out only for projects that "comply with our API Terms and Policies" using a
valid API key. Aggregator data is Riot data re-presented; ingesting it does not launder it into
something RC may redistribute.

**Approved-third-party status:** aggregator A and aggregator B both implement **Riot Sign On**, which Riot grants
only to registered Developer Portal products - strong evidence both are registered/approved
products. aggregator B has been an official Riot broadcast partner; aggregator A has partnered with Riot on LCK
sponsorship. But **no aggregator surveyed explicitly permits reuse or redistribution of its
data.** The "not endorsed by Riot Games" boilerplate they all carry is a disclaimer, not an
approval, and it says nothing about your right to their data.

### 5.6 RC ALREADY HAS A PRECEDENT ON OVERLAY APP E - honour it

`Share/lolmath_ingest/README.md` in this repo records that Daemon Slayer reads the Overlay App E
`data.v2.iesdev.com` ARAM-Mayhem augment aggregate as a **runtime feed**, and explicitly
**excludes it from the shipped bundle** "rather than redistributed", because "Overlay App E's own
terms govern it".

That is exactly the right pattern and it is already RC's house style: **fetch live at runtime,
never vendor into the repo, never redistribute.** Any new aggregator use should follow it
verbatim. It also means Overlay App E is a known quantity here rather than a new decision.

### 5.7 Verdict on aggregators - ranked for a consumer that must not redistribute

1. **aggregator A via the OFFICIAL MCP server** - the only knowingly-supported programmatic surface,
   MIT-licensed client, first-party. Best legal footing by a wide margin. **Start here.**
2. **aggregator B `stats2` CDN** - objectively the best data (every region x rank x role in one file,
   all queues including ARAM and Arena) and a ToS with no scraping or redistribution clause.
   Blocked by robots for agent UAs and by `Disallow: /*?*`; format is undocumented positional
   arrays that break silently. Legally the cleanest ToS, operationally the most fragile, and
   robots-hostile.
3. **aggregator G** - technically open, clean named JSON, permissive robots, but **KR-only in practice
   (measured)** and zero ToS. Limited value for a region-stratified need.
4. **Overlay App E** - clean GraphQL with matchup-scoped builds, already governed by RC's existing
   runtime-feed-not-redistributed precedent.
5. **aggregator D** - the best sample-size claim in the space, but Cloudflare-fronted, no ToS at
   all, no licence, ClaudeBot-disallowed, and runes/skills may be HTML-only.
6. **Aggregator C / AGGREGATOR N / aggregator Z1 / Overlay App F-LoG - avoid.** Explicit anti-automation ToS
   and/or hard Cloudflare gates. Aggregator C' prohibition is verbatim and unambiguous.

And the point that outranks all six: **none of them substitutes for a per-match corpus.** They
are priors. Fetch once per patch, at human cadence, apply `core/smoothed_rates` shrink, keep a
kill switch, never vendor the payload - the item-277 pattern RC already proved with 101.qq.com
and already applies to Overlay App E.

---

## 1-FINAL. THE RANKED SOURCE TABLE

Ranked by coverage added per unit of effort. Effort: XS (hours) / S (one session) /
M (2-4 sessions) / L (weeks) / XL (open-ended).

| # | Source | Coverage it ADDS | Per-match or Pre-agg | Licence + redistribution | Observed rate limits | Effort | Verified? |
|---|---|---|---|---|---|---|---|
| 1 | **MATCH-V5 + LEAGUE-EXP-V4 (personal key), harder** | Nothing new in KIND - but it is the only sanctioned way to ENUMERATE a ladder and thus the only route to true rank stratification. Runes+items+spells 2yr, skill order 1yr. | **PER-MATCH** | Riot API Terms. Cache OK by omission; **redistribution NO**; fixed attribution text required | **0.833 req/s per region** (100/2min binds, not 20/s). 15 platform buckets, only **4** regional buckets for match-v5 | S (RC already has ingestion) | VERIFIED |
| 2 | **CommunityDragon `v1/perks.json` + `perkstyles.json`** | Authoritative rune ids, tree/slot topology, icons, `/pbe/` pre-patch lane | Static | Legal Jibber Jabber, no formal licence, no SLA | none observed; be polite | XS | VERIFIED (fetched today, `status.live.txt` = `2026-07-28T06:00:02Z`) |
| 3 | **DDragon `item.json` / `versions.json`** | Item BASE stats (`stats` object), canonical patch list | Static | No explicit licence; Riot disclaimer required | none | XS | VERIFIED (16.14.1 fetched) |
| 4 | **SGP `match-history-query` (LCU entitlements token)** | **The event-mode gap**: queue 2400 / gameMode KIWI / Arena, in Match-V5 shape, for arbitrary puuids, with no dev-key quota. Plus DETAILS = full timeline (skill order) and replay download. | **PER-MATCH** (`SUMMARY` is the match doc, NOT a rollup) | **FACTUAL: no licence. Riot terms are SILENT, not permissive; enforcement surface is the operator's ACCOUNT, not a key.** `OPERATOR-SANCTIONED 2026-07-28, NON-BLOCKING` (risk acceptance, does not change the terms) | **UNVERIFIED - unknown; rate-limit conservatively for self-preservation** | M (+ live probe) | Host map + path + auth + payload VERIFIED; reachability and limits UNVERIFIED |
| 5 | **wiki.leagueoflegends.com `Template:Rune_data_*`** | **The ONLY route to numeric rune values.** `cooldown`/`range` structured; damage/ratios in regular wiki markup. More current than DDragon prose (measured Electrocute disagreement) | Static | **CC BY-SA (attribution + share-alike) - UNVERIFIED by direct read**, 402 on Fandom | ~unmetered; be polite | M (parser + per-patch tests) | Field list VERIFIED; licence UNVERIFIED |
| 6 | **YouTube Data API -> riotId -> ACCOUNT-V1 -> MATCH-V5** | Named high-elo VOD games that have no pasted match id | **PER-MATCH** (resolves to real Match-V5) | YouTube ToS (storage/refresh obligations, UNVERIFIED) + Riot terms downstream | **`search.list` capped at 100 CALLS/day**; other endpoints 10,000 units/day. Avoid search.list; use channels->playlistItems->videos | S | VERIFIED (quota doc); description format PARTIAL |
| 7 | **Leaguepedia Cargo (`ScoreboardPlayers.Runes`)** | Pro-game runes per player, historical | **PER-MATCH** (per pro game) | **CC BY-SA 3.0 - redistribution PERMITTED with attribution + share-alike** | ~1 request/minute unauthenticated | S | Column existence VERIFIED; `Runes` string format UNVERIFIED (402) |
| 8 | **lolesports `livestats/v1/details/{gameId}`** | Pro-game `items`, `perkMetadata`, **`abilities` (skill order)**. No summoner spells | **PER-MATCH** | Unofficial/undocumented. UNVERIFIED | UNVERIFIED | S | Spec VERIFIED (OpenAPI) |
| 9 | **Meraki `items.json`** | Best PARSED item base-stat SHAPE (`{flat, percent, perLevel, percentBase, percentBonus}`) | Static | **MIT - the only cleanly redistributable source here** | none; README asks you to cache | XS | VERIFIED - and **~15 months STALE (frozen ~patch 25.07; Yunara 404s)** |
| 10 | **LCU `/lol-match-history/v1/products/lol/{puuid}/matches`** | Cheapest possible event-mode probe; zero new infra (RC owns the lockfile client) | **PER-MATCH** | Same silence as SGP | ~20/request, **~100-game cap** (third-party observed) | XS | Path VERIFIED; caps PARTIAL |
| 11 | **LOL-RSO-MATCH-V1** | Sanctioned wider coverage: **custom games**, which Match-V5 refuses | **PER-MATCH** | Sanctioned, but display of custom history requires player opt-in | Riot key limits | L (needs an APPROVED RSO client) | Endpoint VERIFIED; event-mode coverage UNVERIFIED; open 404 bug #1061 |
| 12 | **aggregator A OFFICIAL MCP server** (`mcp-api.aggregator A/mcp`) | Consensus build prior (items, runes, skills, spells) per champ x role x tier - **from a first-party supported interface, not a scrape** | **PRE-AGGREGATED** | **MIT** (`aggregator-a/mcp-server` client). Help Center permits crawling w/ citation; ToS forbids scraping - the MCP path avoids that conflict. No redistribution right to aggregator A's data | none published | XS | VERIFIED (repo + endpoint published) |
| 13 | **Oracle's Elixir** | Pro macro/aggregate stats | Per-game rows | Free for analysts/fans; partly CC BY-SA 3.0 via Leaguepedia | n/a (CSV) | XS | **NO runes, NO skill order, NO item order** - does not answer this brief |
| 14 | **aggregator B `stats2` CDN** | Objectively the richest stratification anywhere: `overview[region][rank][role]`, 18 regions x 17 rank brackets x 5 roles, all queues incl. ARAM + Arena, in ONE file | **PRE-AGGREGATED** | ToS (2018) has **no scraping or redistribution clause**, BUT robots sets `ai-train=no` + express EU DSM Art.4 reservation + **ClaudeBot `Disallow: /`** + `Disallow: /*?*` | Cloudflare | S | robots.txt + ToS VERIFIED; endpoint shape from open source, **deliberately not probed** |
| 15 | **aggregator D / Aggregator C / AGGREGATOR N / aggregator Z1 / Overlay App F-LoG** | Priors only, nothing rows 12-14 do not already give | **PRE-AGGREGATED** | aggregator D: **no ToS exists at all** + ClaudeBot disallow. **Aggregator C ToS verbatim bars "spiders, robots, crawlers, data mining tools or the like"** and all commercial use. AGGREGATOR N/aggregator Z1 ToS unfetchable (403). Overlay App F/LoG ToS behind a Cloudflare challenge | Hard Cloudflare gates throughout | - | **AVOID** - VERIFIED where fetchable, UNVERIFIED where 403 |
| 16 | **CV on VOD frames (approach A)** | **Keystone + secondary path only.** No minor runes, no shards | n/a | n/a | n/a | XL, recurring | **DO NOT BUILD** - the data is not on screen (VERIFIED) |

### Reading of the table

- **Rows 1-3 are the spine.** Sanctioned, cheap, already mostly built in RC.
- **Row 4 (SGP) is the single highest-payoff row.** It is the only thing that closes the
  event-mode gap, and it is now operator-sanctioned. Auth is solved, the payload is confirmed
  Match-V5-shaped, and the token is confirmed reachable from an external Python process. The one
  thing left is a live probe.
- **Row 5 is unavoidable work.** No one ships numeric rune values. Stop looking; build the parser.
- **Rows 6-8 are the pro/VOD answer** and they are cheap. Row 7 (Leaguepedia, CC BY-SA) and
  row 9 (Meraki, MIT) are the ONLY two rows in the entire table with an affirmative
  redistribution licence.
- **Row 12 is the surprise.** aggregator A publishing a first-party MIT-licensed MCP server makes the
  cheapest prior also the cleanest one. It displaces the whole "should we scrape an aggregator"
  question for most purposes.
- **Rows 15-16 are explicit DO-NOT-BUILDs**, each killed by a primary source read this session.
- **Everything from row 12 down is PRE-AGGREGATED** and therefore structurally incapable of
  answering a per-match question, no matter how good the stratification looks.

---

## 8. EXPLICIT UNVERIFIED LIST

Everything below is a real gap. None of it should be treated as fact.

**SGP**
1. Live reachability of any SGP host from Legion. Nobody has sent a packet. This is the one
   cheap probe that unblocks the whole row.
2. SGP rate limits, quotas, and ban behaviour. **Completely unknown. Treat as hostile.**
3. The `-red` / `-green` / `-blue` host colour suffix - three sources show three different
   values. Derive from the token `issuer`, never hardcode.
4. Numeric TTL of the entitlements and league-session tokens (the refresh MECHANISM is verified).
5. Whether a NA-issued entitlements token is accepted by the shared `usw2-red` pp host for a BR /
   LAN / LAS puuid (same super-region). One request settles it.
6. Whether SGP has a hard `count` maximum above 100.
7. Exact `tag` vocabulary beyond the confirmed `q_<queueId>` form, and `tagsQueryType` semantics.
8. Whether Riot has ever deliberately broken SGP for third parties.
9. SGP participant summoner-spell field naming (`spell1Id`/`spell2Id` per the TS type vs
   Match-V5's `summoner1Id`/`summoner2Id`) - from a type definition, not a live response.

**Riot public API**
10. Per-method rate limits for LEAGUE-EXP-V4 `/entries`, LEAGUE-V4 `challengerleagues`, MATCH-V5
    `by-puuid/ids`, `matches/{id}`, `timeline`. Riot's reference pages carry **no rate-limit
    section**. Read `X-Method-Rate-Limit` live.
11. Whether the 4 REGIONAL hosts each get an independent app-limit bucket (doc says "per region"
    but every example uses PLATFORM hosts). Measure with `X-App-Rate-Limit-Count`.
12. Ranked population per region (the `R` in every wall-clock estimate). No primary source exists;
    all timings above are placeholders on R = 2,000,000.
13. Whether the 10,000-entry apex cap also applies below Master.
14. Whether `summonerId` is still populated on league entries in 2026, and the removal date for
    the deprecated `SummonerDTO.id`.
15. Any documented maximum cache TTL / retention window in Riot's terms. **None found.**
16. Production-key approval rate for hobby/coaching-scale tools.
17. The dev-key discrepancy: API Terms say 10 calls / 10 s; the portal says 20/s + 100/2min.
    Unreconciled by any source found.
18. Whether LOL-RSO-MATCH-V1 covers event modes / queue 2400.

**Static data**
19. Licence of the migrated `wiki.leagueoflegends.com` (Fandom returned 402). Assumed CC BY-SA.
20. Which Electrocute value is correct for 16.14.1 - wiki says `70-260 (+10% bAD)(+5% AP)`,
    DDragon/CDragon longDesc says `70-240 (+0.1 bAD, +0.05 AP)`. They disagree.
21. Whether any private maintained fork of lolstaticdata exists (public search: zero).
22. Any formal written Riot grant to redistribute DDragon data (none found).

**VOD / pro**
23. Exact YouTube description layouts on replay channels - confirmed only via search-index
    snippets; watch pages return the SPA shell to WebFetch.
24. Whether Leaguepedia's `ScoreboardPlayers.Runes` string includes stat shards (402 on fetch).
25. Whether esports stats site Z2 build pages carry shard-level rune detail (table did not render).
26. Current YouTube API Services ToS text on metadata storage/refresh obligations.
27. Whether stat shards are rendered for OTHER players anywhere in the client at any time.
    Best evidence says no; not positively disproven.

**Aggregators**
28. **Aggregator H / Overlay App F ToS verbatim** - robots.txt 403s and the ToS page returns a
    Cloudflare challenge. The paraphrase (personal non-commercial only, express anti-crawler
    clause) is SEARCH-SNIPPET ONLY and must not be treated as quoted.
29. **Overlay App E ToS verbatim** - `/robots.txt` and `/legal/terms-of-service` both 403.
30. **AGGREGATOR N and aggregator Z1 ToS verbatim** - both 403. aggregator Z1's `/tos` is itself robots-disallowed.
31. aggregator B `stats2` and aggregator D `mega` endpoints were **deliberately NOT probed** - both sites
    `Disallow: /` for ClaudeBot. All endpoint shapes come from open-source code and robots.txt.
32. Whether Overlay App F/Aggregator H expose ANY JSON endpoint (none found in any open-source
    consumer; HTML pages only).
33. Whether aggregator D `ep=rune` reliably returns runes - two open-source consumers disagree, one
    reporting runes/skills/spells are HTML-only.
34. Whether AGGREGATOR N has a build endpoint at all (only an Arena statistics route was found).
35. **Published rate limits for any aggregator - NONE found anywhere.** Not one of them documents
    a limit.
36. Whether the historical RapidAPI "Aggregator A API" listing is official or current (none found).
37. Whether Overlay App E was ever a formally Riot-approved/partnered overlay.
38. Live anti-bot / Cloudflare challenge behaviour under a non-agent UA - not tested.

---

## 9. RECOMMENDED ORDER OF WORK

1. **XS, today:** probe the LCU route `/lol-match-history/v1/products/lol/{puuid}/matches` for a
   queue-2400 game. Zero new infra, confirms the event-mode data exists locally.
2. **XS, next - the single highest-value action in this document.** One SGP probe from Legion,
   now unblocked (operator-sanctioned 2026-07-28). With the League client logged in:
   LCU `GET /entitlements/v1/token` -> take `.accessToken`, parse `.issuer` for the live host ->
   `GET {issuerHost-derived pp host}/match-history-query/v1/products/lol/player/{own_puuid}/SUMMARY?startIndex=0&count=1&tag=q_2400`
   with `Authorization: Bearer <accessToken>`. For NA the static fallback host is
   `https://usw2-red.pp.sgp.pvp.net`, but prefer the issuer-derived value. **One request resolves
   UNVERIFIED items 1, 3, 6 and most of 7, and confirms the entire event-mode reach claim.**
   Decode the JWT `exp` in the same pass to close item 4.
3. **XS:** fix the `BACKLOG.md` SGP row - `:21019` is Tencent-only and wrong for a NA operator.
   The Riot hosts are plain 443. This is a one-line edit that prevents a wasted probe.
4. **S:** stand up `core/sgp_client.py` on the existing `lcu/lcu_client.py:71` handle - LCU
   websocket subscription for both tokens, token-ready gate, conservative fixed rate, hard
   backoff on any non-2xx.
5. **S:** probe DS item coverage against DDragon 16.14.1 to size the Meraki staleness gap
   (Meraki `latest` is frozen ~patch 25.07 while DS advertises 16.14.1).
6. **XS:** wire the aggregator A MCP server as the once-per-patch build prior. Cheapest and cleanest
   licensed option in the aggregator space.
7. **M:** the wiki rune-value parser. Unavoidable - nothing else unblocks numeric rune values.
8. **S:** the YouTube -> riotId -> ACCOUNT-V1 -> MATCH-V5 resolver, if VOD coverage is wanted.
   Note the 1-year timeline retention: skill order must be harvested continuously, never
   retroactively.
9. **Never:** CV rune extraction from VOD frames.
