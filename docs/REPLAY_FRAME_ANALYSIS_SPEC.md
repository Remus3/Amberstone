# Frame-level replay analysis - feasibility spec and verdict

Authored 2026-07-26. Every number below is MEASURED on this machine against real
bytes or a live API response. Projections are labelled PROJECTED. Things I could
not measure are labelled UNMEASURED rather than estimated.

**Question asked:** can RC analyse `.rofl` frames rather than stat dumps -
second-by-second lane trading, wave pressure as measured not theorized,
objective and tank rotation as actually executed - over a population that
includes arbitrary known high-ELO players, role by role, and older matches?

**Verdict: SPLIT. Three of the four premises survive measurement; one is dead.**

| # | Premise | Verdict |
|---|---|---|
| V1 | A large high-ELO corpus is acquirable today | **BUILD** - measured 1131 files / 14.46 GB from one ladder |
| V2 | Role-by-role coverage | **BUILD** - free; a `.rofl` is a whole-game file, all 10 roles per file |
| V3 | Second-by-second behaviour from Layer-1 | **REFUTED** - Layer-1 floor is 29.6 s per chunk in PvP |
| V4 | Older matches | **REFUTED** - retention cutoff plus a recency-only window, two independent kills |
| V5 | Second-by-second from Layer-2 | **CONDITIONAL** - no crypto barrier at all, but an undocumented numeric protocol with sub-patch churn. Spike with a kill criterion, do not open-endedly commit |

---

## 1. Measured population

`GET /lol/match/v5/matches/by-puuid/{puuid}/replays` works for ANY puuid, not
just the operator's. This is the finding that makes the whole idea viable and it
was not previously on record.

- **271 of 302** NA challenger accounts returned 200, every one `total=5`. The
  other 31 were self-inflicted 429s from bursting, not refusals.
- Independently spot-checked on a fresh random sample of 6 challenger accounts:
  **6/6 served 5 slots, 30/30 distinct ids, 6/6 pre-signed URLs answered HTTP
  206.**
- Independently confirmed on two operator-named accounts before any ladder work:
  `SamplePlayer2#NA1` 5 listed / 5 alive / 3 ranked, `blaberfish2#NA1` 5 listed /
  5 alive / 5 ranked.

**THE SINGLE MEASURED NUMBER: 1131 distinct `.rofl` files, 14.46 GB,
downloadable today from the NA challenger ladder alone.** 1355 account-slots
minus 16.5 pct cross-account overlap (challenger players share games), and
1131 of 1131 pre-signed URLs answered 206.

Per-account measured yield is 5 slots -> **4.17 unique matches**. A
chall-plus-GM figure of ~4260 files is PROJECTED, not measured.

Account discovery is free and entitled: league-v4 challenger/GM and league-exp
master all 200 with the product key, and return puuids already encrypted under
our key (so no per-account Riot ID resolve). Measured supply: na1 302 chall /
720 GM / 205 master-p1; euw1 304, kr 300, eun1 201, br1 202, jp1 50. Non-americas
routing for `/replays` itself is UNMEASURED.

**Role coverage is free (V2).** A `.rofl` is the whole game, so every file
carries all 10 players. Role histogram over a 24-match sample:
TOP/JUNGLE/MIDDLE/BOTTOM/UTILITY = 32 each. Roles come per FILE, never per
account, so no per-role acquisition strategy is needed.

## 2. Why "older matches" is dead (V4)

Two independent kills, either one sufficient:

1. **Retention cutoff.** Measured cleanly by id: every id `>= NA1_5588704275`
   alive, every id `<= NA1_5587877643` dead. Dated dead anchors: 2026-06-21
   (16.12), 2026-05-26 (16.10), 2025-12-16 (15.24). The exact cutoff DATE is
   UNMEASURED; the id boundary is not.
2. **The window is recency-only.** All 19 dated sample matches are patch 16.14
   (2026-07-18 to 2026-07-26). `/replays` serves an active player's 5 most
   recent RETAINED games, so a currently-laddering account structurally cannot
   list an old one.

**There is no route to a chosen match.** `/matches/{matchId}/replays` -> 403.
`matchId`, `count`, `start`, `startTime` query params all return the identical
default 5 ids. `core/riot_api.get_replay_urls` (`riot_api.py:394`) takes only
puuid + region; no matchId helper exists because no such route exists.

Demonstrated live, not theorised: of three requested `blaberfish2#NA1` matches,
Vi and Lee Sin were still in the window and **Sylas (`NA1_5606819138`) had
already rotated out and is permanently unobtainable.**

**Consequence: forward-harvest is measured-sound; back-fill of a named player's
older game is measured-dead.** Corpus depth must come from CADENCE.

## 3. The Layer-1 / Layer-2 boundary, against real bytes

**The public roflxd / Replay Tool Z16 layout that every third-party tool cites is
REFUTED for this container.** All 16 archived files are `RIOT\x02\x00`. There is
no 256-byte front signature and no length table - no `fileLength`,
`metadataOffset`, `payloadOffset`, `payloadHeaderOffset`. That layout describes
the older `RIOT\x00\x00` v1 container. Do not inherit it.

Confirmed v2 layout, verified by exact byte accounting on **16 of 16 files**
(`29 + SUM(17 + payload) + 256 + json_len + trailing == filesize`):

| element | measured |
|---|---|
| header | `struct.Struct("<4sH8sB")`, 15 bytes: magic, version=2, 8-byte per-patch constant, version-string length |
| version string | ASCII, immediately after; payload starts at offset **29** on 16/16 |
| block chain | `struct.Struct("<IIBII")`, 17 bytes inline before each payload: `id`, `next_chunk_id`, `type`, `declen`, `complen` (0 = stored) |
| block types | 1=chunk, 2=keyframe, 3=metadata, 4=stored |
| tail | a 256-byte high-entropy block, then the JSON blob: `raw.find(b'{"gameLength"') == chain_end + 256` on 16/16 |

**Fields the public layout promises that DO NOT EXIST here:** `gameId`,
`encryptionKey`, `encryptionKeyLength`, `keyframeInterval`, `chunkCount`,
`keyframeCount`, `endStartupChunkId`, `startGameChunkId`. `gameId` is absent in
every integer width and as ASCII; there are zero base64-shaped runs anywhere.
Counts come from walking the chain (which matches `lastGameChunkId - 2` /
`lastKeyFrameId` on 16/16).

**THE BOUNDARY ANSWER: there is no encryption. No Blowfish, no key, no gameId
XOR, no zlib, no gzip.** Payloads are plain zstd frames (`28 b5 2f fd`),
decompressible with Python 3.14 stdlib `compression.zstd` and no third-party
code. Proof they were never ciphertext: zstd achieves 1.81x-6.46x on them
(ciphertext is incompressible), and decompressed entropy is 5.37-7.27 vs
7.96-7.99 compressed.

Independently re-verified by the author on `NA1_5607594617` (a file pulled this
session, which the measuring agent never touched): header `<4sH8sB` /
`16.14.794.9266`, payload_off 29, chain of 41 chunks + 21 keyframes + 1 metadata
+ 1 stored, `chain_end + 256 == json offset` exactly, and stdlib zstd
decompressed block 1 from 5406 -> 15166 bytes **with no key**.

**LAYER-1** (defeated, in full, by this pass): magic, version, patch constant,
block chain walk, zstd decompression, tail signature boundary, tail JSON stats,
block counts and cadence. Identical across 3 patches and 4 builds, on files from
118 KB to 19.5 MB, with zero special cases.

**LAYER-2** (untouched): packet framing inside a chunk, the opcode table,
per-message field layout, entity-id to champion binding, position quantization,
cast encoding.

**So what an analyser must defeat is SEMANTICS, not crypto and not
compression.** This materially changes - but does not automatically overturn -
the CLAUDE.md Settled fence, whose stated justification is "per-patch Layer-2
obfuscation re-RE cost". The crypto half of that rationale is measurably absent.
The churn half stands and got worse: **two builds shipped inside patch 16.14
alone** (`.5912` and `.9266`, both in our corpus). Re-opening the fence is an
operator decision and is NOT taken here.

## 4. Why Layer-1 cannot answer the actual question (V3)

The finest temporal unit Layer-1 exposes is one chunk:

| mode | chunk cadence | keyframe cadence |
|---|---|---|
| PvP | **29.16 - 30.00 s** | 56.7 - 60.0 s |
| co-op vs AI | 2.69 - 3.00 s | 56.7 - 60.0 s |

Re-verified: 41 chunks over a 1215 s game = **29.6 s**. Why bot games chunk at
3 s is UNMEASURED.

At ~30 s granularity, "second-by-second lane trading" and "wave pressure as
measured" are not measurements - they are interpolation across a window longer
than most trades. **Any Layer-1 second-by-second claim is off by 1 to 1.5 orders
of magnitude for PvP.** This is the hard cap and no amount of Layer-1 work moves
it.

**But the fine-grained data is in there.** Decompressed chunk volume is
20.1-24.0 kB/s in PvP (34.9 MB for a 27.9-minute game; re-verified 21.2 MB for a
20.3-minute game), arranged as periodic full keyframes plus dense deltas - the
shape of a per-tick state stream. Sub-second telemetry plausibly exists and is
unencrypted. Extracting it is strictly a Layer-2 deliverable.

The obstacle is that the decompressed stream carries **zero plaintext
identifiers**: 0 hits for all 10 champion names across all 86 blocks of one
file. Every reference is numeric.

## 5. Named blockers

| id | blocker | evidence |
|---|---|---|
| B1 | No fetch-by-match-id route | `/matches/{id}/replays` 403; all query params return the same default 5 |
| B2 | 5 slots per account, recency-only | `total=5` on 271/271 successful probes |
| B3 | Retention cutoff | id `>= NA1_5588704275` alive, `<= NA1_5587877643` dead |
| B4 | A game not pulled during residency is lost forever | `NA1_5606819138` rotated out between the operator's request and the pull |
| B5 | Layer-1 temporal floor 29.6 s | chunk cadence, 16/16 files |
| B6 | Riot 429 at burst | 31 of 302 accounts on an unthrottled sweep |
| B7 | RC's own limiter, 100 per 120 s | `riot_api.py:211`; 360 s for 311 calls |
| B8 | Stored db puuids are key-scoped and 400 | "Exception decrypting"; resolve fresh by Riot ID |
| B9 | Sidecar `NAME` is empty; 5/24 matches 404 on Match-V5 | event queues; attribution needs the Match-V5 participant join |
| B10 | Layer-2 has zero plaintext identifiers | 0/10 champion-name hits across 86 blocks |
| B11 | Sub-patch build churn | `.5912` and `.9266` both inside 16.14 |
| B12 | The RM-106b playback alternative needs a patch-matched client and is interactive-only | `ROADMAP.md:29` |
| B13 | Riot acceptable-use for bulk third-party replay harvesting | UNMEASURED - clear this before any ladder-scale sweep |

## 6. Recommended sequencing

1. **Now, cheap, already half-built:** scale the roster corpus
   (`tools/replay_roster_pull.py`, shipped `aa5a143c`) from 2 tracked accounts to
   ladder-scale forward-harvest on a schedule. Layer-1 stats + 30 s chunk
   cadence + the tail JSON are free and permanent. Clear B13 first.
2. **Then, before any Layer-2 commitment:** a bounded spike on ONE chunk stream
   with an explicit kill criterion - can entity ids be bound to champions across
   two builds without re-RE? If no, stop; the fence holds on churn grounds even
   though its crypto rationale is void.
3. **Do not** plan any historical backfill of named players. It is measured-dead.

## 7. UNMEASURED

Non-americas `/replays` routing; the exact retention cutoff date; deeper
league-exp pages; the identity of the 8-byte patch constant; what the 256-byte
tail block is; why bot games chunk at 3 s; Layer-1 extraction on a non-operator
file (no full body was downloaded during population measurement - though the 8
roster files pulled since do extract cleanly); Riot acceptable-use policy for
bulk harvesting.

## 8. Correction to prior art

The claim that API-served replays extract at **201** fields versus 367 for
client-saved does NOT hold as a source discriminator: `set(201) - set(367)` is
empty, the 166 extra keys are per-account mission trackers
(`2026_S1A1_Skins_*`, `ActMission_*`), and two `match_v5_replays` files in this
corpus carry the full 367. Field count is not a source or mode discriminator.
