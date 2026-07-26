# Replay parse criteria - per role, per tier, for live coaching and PGR

Authored 2026-07-26. Every field named here was enumerated from a real payload
on this machine. Anything not verified is marked UNMEASURED and must be probed
before it is built on. Nothing in this document is inferred from documentation.

Companion: `docs/REPLAY_FRAME_ANALYSIS_SPEC.md` (acquisition + Layer-1/Layer-2).

---

## 1. The measured substrate

Four producers, different fidelity and different cost. A criterion is only as
good as the tier it can actually be computed from, so every criterion below
names its tier.

| tier | source | resolution | scale | client needed |
|---|---|---|---|---|
| **T0** | `.rofl` Layer-1 tail JSON | end of game only | whole corpus | no |
| **T1** | Match-V5 timeline FRAMES | 60 s | whole ladder | no |
| **T2** | Match-V5 timeline EVENTS | sub-second, with map coords | whole ladder | no |
| **T3** | `:2999` seek + camera back-projection | any instant, ~19 map units | one game at a time | YES, interactive |

**T2 is the workhorse and was underestimated.** Events are not merely
timestamps: `CHAMPION_KILL` carries a per-instance damage breakdown naming the
spell. T3 is only needed for continuous position between events.

### T1 frame fields (per player, every 60 s) - VERIFIED

```
position{x,y}  currentGold  totalGold  goldPerSecond  xp  level
minionsKilled  jungleMinionsKilled  timeEnemySpentControlled
championStats{ abilityHaste abilityPower armor armorPen armorPenPercent
  attackDamage attackSpeed bonusArmorPenPercent bonusMagicPenPercent
  ccReduction cooldownReduction health healthMax healthRegen lifesteal
  magicPen magicPenPercent magicResist movementSpeed omnivamp physicalVamp
  power powerMax powerRegen spellVamp }
damageStats{ magic/physical/true x DamageDone, DoneToChampions, Taken,
  plus totalDamageDone / totalDamageDoneToChampions / totalDamageTaken }
```

### T2 event types - VERIFIED (counts from one 25-min game)

```
ITEM_PURCHASED 211  WARD_PLACED 237  SKILL_LEVEL_UP 136  LEVEL_UP 126
ITEM_DESTROYED 190  CHAMPION_KILL 58  TURRET_PLATE_DESTROYED 48
WARD_KILL 41  BUILDING_KILL 11  ELITE_MONSTER_KILL 9  CHAMPION_SPECIAL_KILL 6
ITEM_UNDO 4  DRAGON_SOUL_GIVEN 2  ITEM_SOLD 1  OBJECTIVE_BOUNTY_PRESTART 1
PAUSE_END 1  GAME_END 1
```

Per-event payloads, verified:

- `CHAMPION_KILL`: `killerId victimId assistingParticipantIds position bounty
  shutdownBounty killStreakLength victimDamageDealt victimDamageReceived
  victimTeamfightDamageDealt victimTeamfightDamageReceived`
  Each damage entry: `{participantId, name, spellName, spellSlot, basic,
  physicalDamage, magicDamage, trueDamage, type}`.
- `ELITE_MONSTER_KILL`: `killerId killerTeamId monsterType monsterSubType
  position bounty assistingParticipantIds`
- `TURRET_PLATE_DESTROYED`: `killerId teamId laneType position`
- `BUILDING_KILL`: `killerId teamId laneType towerType buildingType position
  bounty assistingParticipantIds`
- `SKILL_LEVEL_UP`: `participantId skillSlot levelUpType`
- `WARD_PLACED`: `creatorId wardType` - **NO POSITION**
- `OBJECTIVE_BOUNTY_PRESTART`: `teamId actualStartTime`

### NOT MEASURABLE - do not design a criterion that needs these

| want | status |
|---|---|
| minion / wave state | **BLOCKED.** No minion entities in any tier. cs RATE and plate timings are PROXIES, never a wave measurement. Layer-2 only. |
| ward POSITIONS | **BLOCKED at T1/T2** - `WARD_PLACED` has no position field. Vision COUNT and TIMING are available; vision COVERAGE is not. |
| ability cooldown state | **BLOCKED.** `activeplayerabilities` returns HTTP 400 in a replay (spectator context). Casts are only visible where they appear in a kill's damage breakdown. |
| non-lethal trade damage | **PARTIAL.** Damage breakdowns exist only inside `CHAMPION_KILL`. A trade nobody died in is invisible except as a 60 s `damageStats` delta. |
| recall / base timing | **DERIVED, not direct.** Infer from a gold drop plus `ITEM_PURCHASED`; no explicit event. |
| champion positions between frames | **T3 only** (~19 units, interactive). T1's 60 s sampling carries ~2000 units of error - see the retraction in `core/replay_analysis.py`. |

---

## 2. The two coaching modes are NOT the same problem

This distinction governs every criterion below and is the most common way a
replay-analysis pipeline goes wrong.

**PGR / after-game** may use the whole match, including the future. "This death
at 14:20 is what lost you the drake at 15:05" is legitimate: the outcome is
known.

**LIVE** has no future. A live criterion may only read state at or before now.
Any criterion whose definition contains an outcome that has not happened is
PGR-only. The live equivalent must be re-cast as a **precondition**: not "this
cost you the game" but "you are now in a state that preceded that loss in N
comparable games".

Practically: every PGR criterion below can be converted to a live one ONLY by
precomputing its precondition distribution over the corpus, which is exactly
the haiku-zero table. **PGR is what generates the live rules.** Build PGR
first; a live rule with no corpus behind it is an assumption.

---

## 3. Magnitude: making "how much did it cost" measurable

Every criterion emits a magnitude so findings can be ranked instead of listed.
Use measured currency, never a made-up severity score.

| magnitude | source | tier |
|---|---|---|
| gold swing | `bounty` + `shutdownBounty` on kills, `bounty` on buildings and elite monsters | T2 |
| gold delta over a window | `totalGold` difference across frames | T1 |
| xp / level swing | `xp`, `level` across frames | T1 |
| tempo cost | seconds dead: death timestamp to next observed action | T2 |
| stat swing | `championStats` before vs after a purchase | T1 |
| damage attribution | per-spell entries in a kill's breakdown | T2 |

**Timeline of magnitude, start to end.** Every match reduces to one ordered
series per team: cumulative gold difference sampled at 60 s, with T2 events
overlaid as step changes. Each event's magnitude is its bounty plus the
downstream gold swing over the following 60 s. That series IS the "what
happened to this game" backbone, and both the winning-side and losing-side
readings are views over it.

---

## 4. Win-side and loss-side are different questions

Do NOT compute the same criteria for both and flip the sign.

**WINNING SIDE - revealed-correct decisions.** The outcome validates the
choice, so mine for the DECISION PATTERN: what did they do before each positive
step change. Filter to decisions that recur across many winning games - a
one-off does not generalise. These become candidate coaching rules.

**LOSING SIDE - cost attribution.** Rank negative step changes by magnitude and
attribute each to the nearest preceding decision. The deliverable is an ordered
list of what cost the most, not a list of everything that went wrong.

**The trap, and it is the reason this section exists:** a winning player's
action is not automatically correct. Winners make mistakes they got away with,
and the corpus will happily teach those. Any rule mined from the winning side
must be checked against the losing side too - if losers do it at a similar
rate, it is noise, not a lesson. Require a measured rate difference before
promoting anything to a coaching rule.

---

## 5. Criteria by role

Each row: **what** | **tier** | **fields** | **LIVE / PGR**.
Status is MEASURABLE unless stated.

### 5.1 Universal (all roles)

| criterion | tier | fields | mode |
|---|---|---|---|
| Death cost ranking | T2 | `CHAMPION_KILL.bounty + shutdownBounty`, timestamp, `position` | PGR |
| Killer-side damage composition | T2 | `victimDamageReceived[].spellName/basic/physical/magic/true` | PGR |
| Died-while-ahead (shutdown given) | T2 | `shutdownBounty > 0` | BOTH |
| Gold-per-minute curve vs role cohort | T1 | `totalGold`, frame ts | BOTH |
| Item spike timing vs cohort | T2 | `ITEM_PURCHASED` ts per completed item | BOTH |
| Stat state at each death | T1+T2 | `championStats` at nearest frame, kill ts | PGR |
| Skill order | T2 | `SKILL_LEVEL_UP.skillSlot` ordered | BOTH |
| Time dead (tempo loss) | T2 | death ts, level-based respawn | PGR |
| CC applied to enemies | T1 | `timeEnemySpentControlled` | BOTH |
| Damage taken vs dealt ratio by phase | T1 | `damageStats` deltas | BOTH |

### 5.2 TOP

| criterion | tier | fields | mode |
|---|---|---|---|
| Plate share and timing | T2 | `TURRET_PLATE_DESTROYED` where `laneType=TOP_LANE` | BOTH |
| Isolation deaths (died with 0 assists near own lane) | T2 | `CHAMPION_KILL` with empty `assistingParticipantIds` + `position` | PGR |
| Teleport-window impact | UNMEASURED | summoner-spell casts are NOT in any tier; only the loadout is | - |
| Split-push pressure | T3 | continuous position vs lane axis while team is elsewhere | PGR |
| Trade wins pre-6 | T2 | kill damage breakdowns before first `LEVEL_UP` to 6 | PGR |

### 5.3 JUNGLE

| criterion | tier | fields | mode |
|---|---|---|---|
| Objective presence | **T3** | position at objective ts. **T1 is NOT usable here - measured ~2000 unit error, 8 of 33 samples wrong by more than the decision threshold** | PGR |
| Camp throughput | T1 | `jungleMinionsKilled` slope | BOTH |
| First-clear efficiency | T1 | jungle cs and level at 3:30 frame | BOTH |
| Objective trade (took X while enemy took Y) | T2 | two `ELITE_MONSTER_KILL` within a window, opposite `killerTeamId` | PGR |
| Gank conversion | T2 | `CHAMPION_KILL` with jungler as killer or assist, by lane from `position` | PGR |
| Counter-jungle | T1 | `jungleMinionsKilled` rising while positioned in enemy half (needs T3 for the position half) | PGR |

### 5.4 MID

| criterion | tier | fields | mode |
|---|---|---|---|
| Roam profit | T2 | kills or plates outside mid within N s, minus mid cs lost across the frame | PGR |
| Wave-loss on roam | **BLOCKED** | needs wave state; cs delta is the PROXY and must be labelled as such | - |
| Priority before objective | T3 | position relative to objective at spawn minus 30 s | PGR |
| Burst combo composition | T2 | `victimDamageDealt` spell sequence in kills they secured | PGR |
| Solo-kill rate | T2 | kills with empty `assistingParticipantIds` | BOTH |

### 5.5 BOT

| criterion | tier | fields | mode |
|---|---|---|---|
| cs at 10 / 15 vs cohort | T1 | `minionsKilled` at frame 10, 15 | BOTH |
| 2v2 trade outcome | T2 | kill damage breakdowns where both bot pairs appear | PGR |
| Positioning in fights (damage taken share) | T1+T2 | `damageStats.totalDamageTaken` delta across fight window | PGR |
| Dive survivability | T2 | deaths where `victimDamageReceived` has 3+ distinct `participantId` | PGR |
| Item spike vs first grouped fight | T2 | `ITEM_PURCHASED` ts vs first multi-kill event | BOTH |

### 5.6 SUPPORT

| criterion | tier | fields | mode |
|---|---|---|---|
| Ward cadence | T2 | `WARD_PLACED` ts per `wardType` | BOTH |
| Ward coverage / map control | **BLOCKED** | `WARD_PLACED` has NO position; only counts and timing exist | - |
| Sweeper usage | T2 | `WARD_KILL` count and timing | BOTH |
| Engage conversion | T2 | kills within N s of their `timeEnemySpentControlled` rising | PGR |
| Peel effectiveness | T2 | carry deaths where support dealt damage in `victimTeamfightDamageReceived` | PGR |
| Roam / lane-leave cost | T1 | partner cs and gold slope while support is absent (position needs T3) | PGR |

---

## 6. Pipeline shape

```
acquire        tools/replay_roster_pull.py        -> .rofl corpus (T0)
               core/riot_api.get_match_timeline   -> T1 + T2, headless
normalise      core/replay_analysis.normalize_timeline -> Timeline
               (T3 producer: core/replay_seek + core/replay_camera)
derive         per-role criteria above -> Finding{t_ms, role, criterion,
                 magnitude_gold, tier, source, sample_age_s, confidence}
rank           order by magnitude; win-side and loss-side views
mine           aggregate Findings across corpus -> rate tables
                 (win-rate difference REQUIRED before a rule is promoted)
serve          PGR: render the ranked list for one match
               LIVE: look up the precomputed precondition table - no Haiku
```

**Every Finding must carry its tier and its sampling error.** A T1-derived
positional claim and a T3-derived one are not interchangeable, and the pipeline
that forgets which is which will produce confident nonsense - that already
happened once here, at ~2000 units of error.

## 7. Build order

1. **T1 + T2 derivations only.** Headless, whole ladder, no client. Covers most
   of the table above.
2. **Corpus mining** to get win-side vs loss-side RATE differences. This is what
   converts a finding into a rule and is the haiku-zero precompute input.
3. **T3 only for the criteria marked T3** - jungle objective presence, split
   push, priority. Interactive and hand-curated by necessity.
4. **Do not build** anything in the BLOCKED rows until Layer-2 is opened, and
   note that the fence's crypto rationale is void while its churn rationale
   stands.

## 8. Open, needs a live replay to close

- Full `:2999` event list during replay playback (only `GameStart`,
  `ChampionKill`, `Multikill` observed so far - the T2 list above is the
  Match-V5 one and is richer).
- Whether `activePlayer` populates in a replay (its abilities route 400s).
- Whether any minion or ward entity is exposed anywhere on `:2999`. If wards
  are, the SUPPORT coverage row unblocks at T3.
