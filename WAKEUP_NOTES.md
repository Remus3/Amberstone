# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-19h

**Session: the sanctioned Match-V5 replay pull, BUILT and LIVE-PROVEN, plus the
key-scoped account-cache fix it depended on.** No ENGINE bump.

## What shipped

1. **The cache defect is fixed.** `core/riot_api.py` account cache keys now carry
   `_key_fingerprint()` - a truncated sha256 of the ACTIVE key. PUUIDs are a
   per-API-key encryption, so a key-agnostic key over an IMMUTABLE row poisoned
   the entry permanently on rotation. Regression test:
   `test_key_rotation_invalidates_the_account_cache`. The sibling keys were left
   alone on purpose - `league:v4:{region}:{puuid}` and the mastery keys embed the
   PUUID, so a new key yields a new cache key for free.
2. **The pull.** `core/riot_api.get_replay_urls` (uncached - the URLs die in an
   hour) + `core/rofl_archive.download_replays` + `_api_pull` in
   `tools/rofl_archiver.py`, wired under the SAME `--pull` the RC-RoflArchive
   task already passes, so the 15-minute cadence picked it up with NO task edit.
   `--no-api-pull` / `--no-lcu-pull` split the two halves.

## MEASURED on the live runs - four things no amount of reading would have given

- **The bodies are GZIP-framed** and urllib does not decompress. The first live
  pull discarded 5 of 5 as "not a replay". The is-this-actually-a-replay guard
  is what caught it instead of writing 5 gzip blobs under `.rofl` names.
- **SamplePlayer#Vayne: all five URLs 404.** Riot LISTS the match and no longer
  retains the file. Permanent and expected, so it is counted `gone`, NOT
  `failed` - otherwise the scheduled task reports LastTaskResult=1 forever and
  buries any real fault. Trist's five downloaded clean.
- **The two sources spell one match differently** (`NA1-x.rofl` from the client,
  `NA1_x.rofl` from the API), so a filename-keyed skip re-downloaded 10 MB. The
  live archive has one such duplicate pair (`NA1_5595187452`), harmless, left in
  place. Skip is now match-id-keyed across both spellings.
- **Idempotency is proven live:** run 2 downloaded 5, run 3 skipped 5.

## THE OPEN QUESTION - now instrumented, do NOT guess at it

Does the 5-per-account window ROTATE as games are played? If yes, cadence alone
converts a rolling window into a permanent archive and no bulk trick is needed.

Every pull now appends what it saw to `<archive>/pull_log.jsonl`, and `--pull`
prints a rotation verdict. **Four observations exist, all with NO games played
in between, so the printed `rotated=False` means nothing yet.**
`pull_rotation_report` returns `rotated=None` on a single observation rather
than fabricating a negative - do not read a False from same-window pulls as an
answer. **PLAY GAMES, then run `--pull` and read the rotation line.**

## The API-served .rofl are NOT degraded - measured, do not re-investigate

They extract at **201 fields** per player where client-saved replays from the
SAME era give 367, which looks alarming and is not. Diffed: all 166 extra fields
are mission / event / battle-pass counters (`Missions_*`, `HoL_*`, `Event_*`,
`WeeklyMission_*`, `DemonsHand_*`) - account progression, not match data. ZERO
fields are API-only, and every core stat (ITEM0-6, GOLD_EARNED,
CHAMPIONS_KILLED, NUM_DEATHS, ASSISTS, LEVEL, MINIONS_KILLED,
TOTAL_DAMAGE_DEALT_TO_CHAMPIONS, TIME_PLAYED, WIN) is present in both. The
sidecar backfill plan loses nothing by sourcing from the API pull.

## Live state at wrap

Archive holds 13 `.rofl` (12 unique matches) + 12 stat sidecars at
`Documents\RC_ROFL_Archive`. Two sidecars briefly failed with WinError 32
against a concurrent scheduled run; a re-run wrote them (known Windows
concurrency shape, not a defect in this code).

## Do NOT redo

- SGP (Cloudflare 1010; getting past it is bot-detection evasion).
- Old-client installs are game-files-only, no LCU, so no `/lol-replays/` there.
- Backoff for the 20000/10s limit. It cannot bind; the binding limits are the
  5-per-account window and the 1-hour URL expiry, and retrying helps neither.


# 2026-07-19g

**Session: replay forward-capture pipeline + silent-except batch program + three of my own claims retracted.**
Commits `b54e315d`..`d750c8be` (+ this docs sync). LEDGER 969. No ENGINE bump.

## START HERE NEXT SESSION - build the sanctioned replay pull

`GET https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/replays`
returns **200** `{"total": 5, "matchFileURLs": [...]}` - pre-signed S3 URLs on
`lol-prod-us-west-2-match-history-replay` with
`response-content-disposition=attachment; filename="NA1_xxxx.rofl"`. Ordinary API
key, no third party, no `.bat`, no bearer-token scraping. **This supersedes both
the third-party route and SGP.**

Bounds MEASURED, do not re-derive: `X-Amz-Expires=3600` (ONE hour) and exactly
**5 per account**. A refreshing recency window, NOT an archive - so it PAIRS with
`tools/rofl_archiver.py` (pull 5 -> archive permanently -> extract) rather than
replacing it. Vayne's 5 are 15.x-era ids and Trist's are 16.14-era, so it is
"last 5 with a replay retained" PER ACCOUNT, not a global recency cut.

**TWO TRAPS THAT WILL COST AN HOUR IF RE-INHERITED:**

1. **PUUIDs ARE ENCRYPTED PER API KEY.** Cycling the key 400s every stored one
   with `"Bad Request - Exception decrypting <puuid>"`. All three of ours did.
2. **`core/riot_api.get_account_by_riot_id` CANNOT re-resolve them** - it checks
   `get_cache().get_immutable()` BEFORE any network call (`riot_api.py:346`), so
   a "re-resolve" silently returns the OLD key's cached PUUID and the 400
   persists. Bypass the cache (call Account-V1 through `_http_get` directly) and
   the fresh puuid 200s immediately. Verified both accounts.

**THE PRECISE DEFECT AND THE PRECISE FIX** (sharpened after the operator pointed
out it is about WHICH KEY RESOLVED THE PUUID, not which key sends it):

```python
core/riot_api.py:351
cache_key = f"account:v1:{region}:{name}#{tag}".lower()   # key-AGNOSTIC key ...
                                                          # ... for a key-SCOPED value
```

PUUIDs are a per-API-key encryption of the same account - the value changes the
instant the KEY changes, NOT on any time schedule (the old "Riot slowly rotates
PUUIDs" model is retracted; memory `reference_riot_puuid_rotation` is corrected).
The Riot ID is the durable identity; the PUUID is a key-scoped handle. Because
the account cache key omits key identity and the value lands in the IMMUTABLE
cache, one rotation poisons it permanently.

**Fix: include a fingerprint of the active API key in the account cache key.**
The other cache keys need no change - `league:v4:{region}:{puuid}` and the
mastery keys embed the PUUID itself, so a new key naturally yields a new cache
key. Add a test that a key change invalidates the account entry; it is the
regression that would otherwise silently return.

**OPEN AND UNFIXED, fix BEFORE any bulk pull:** all 2961 PUUIDs in
`rewind_history.db` are stale against the API (still fine as an internal join
key, useless as a request parameter), and NOTHING invalidates the immutable cache
on key rotation. That cache invalidation is the first piece of work.

Build: fetch URLs -> download -> archive -> extract, into `core/rofl_archive.py`
+ `tools/rofl_archiver.py`, wired into the existing `RC-RoflArchive` task, with
the cache fix. Same TDD treatment as the rest of the module (RED first; the
1-hour URL expiry and the 5-cap both want explicit tests).

**OPERATOR HYPOTHESIS TO TEST (worth real effort):** the third-party service
served matches across the last ~3 patches, which is far more than 5 per account.
If it polls this same endpoint per user over time and ACCUMULATES, then the
"faster way" is simply to run our pull on a cadence and let the archive grow -
converting a rolling 5-match window into a permanent archive. Test by pulling
twice with games played in between and confirming the 5 rotate. If they rotate,
cadence beats any bulk trick and the current 15-minute task already does it.

## Second task, if the first lands early

`--extract` writes JSON sidecars only; it deliberately does NOT touch
`data/rewind_history.db` (1.8 GB of production data, and merging is a
schema-aware job with dedupe questions). Backfilling the event-mode hole from
sidecars is the natural follow-up. `.rofl` stats have NO patch gate, so this
works for every archived replay forever.

## Live state at wrap

RC pid was 8148 mode=game (it restarted mid-session; 10624 was the earlier pid).
DS `:8893` engine 1.228.0 patch 16.14.1, 173 champs / 706 items. `RC-RoflArchive`
Ready, LastTaskResult=0, 15-min interval. Archive holds **7 replays + 1 clip + 8
stat sidecars** at `Documents\RC_ROFL_Archive`. League client was CLOSED at wrap
(lockfile absent) - that is now a reported SKIP, not a failure.

## Do NOT redo / do NOT re-inherit

- **Three claims of mine were RETRACTED this session, all by measurement.** Do not
  re-inherit any of them: "RM-106b is closed / playback does not serve `:2999`"
  (that probe ran with `EnableReplayApi` ABSENT - it measured the flag-OFF state);
  "there is no third-party source for personal replays" (one HOSTS them); and
  "forward-capture only, CANNOT backfill" (conditionally false once an old
  `.rofl` + a matching old client exist). ROADMAP + history carry the corrected
  versions.
- **SGP is DEAD as a route.** Cloudflare `error code 1010`; getting past it means
  forging a User-Agent to defeat bot detection, which was deliberately NOT done
  and should not be revisited. Narrative relocated to `ROADMAP_HISTORY`.
- **Riot's own LCU download is patch-locked to the RUNNING client** - a match ONE
  patch back reports `incompatible`. Use `/download/graceful`, never `/download`.
- **Old-client installs are game-files-only** (30 GB, `Game/` + the exe, NO
  `LeagueClient.exe`), so they have NO LCU. Do not plan anything around calling
  an old client's `/lol-replays/` API. The Replay API is served by the GAME
  process, so `:2999` seek-and-sample DOES work there - but `EnableReplayApi=1`
  must be set in THAT install's own `game.cfg`.
- **Playback needs Vanguard stopped (=> reboot to play live again); STAT
  EXTRACTION DOES NOT.** Extraction is pure file reading and runs alongside a live
  Vanguard - the 15-min task does it now. Only per-timestamp work pays the reboot.
- The spec at `docs/specs/2026-07-19-silent-except-triage.md` has RELIABLE
  file:line citations but **UNRELIABLE exception-type lists** - section 2c was
  refuted independently 4 times. Re-derive every type set from the call chain.
- `lcu_client._request` swallow contract is deliberately UNCHANGED (report-only)
  and pinned by a passing test. Changing it alters error semantics on every LCU
  path repo-wide - its own session.
- ~680 silent handlers remain untriaged; the TFT cluster (~39) is the obvious
  next tranche. 48 frozen-file handlers ARE now triaged (grant was given).

## Traps re-confirmed this session

- **The background-task notification lied about the exit code on ALL THREE suite
  runs** - it reported 0 while the captured file read `MAIN_EXIT=1`. Capture by
  redirect and READ THE FILE. Never trust the notification.
- The RF5 `assert_prod_artifacts_unchanged` teardown ERROR is the LIVE RC process
  writing `data/` mid-run, not a regression (LEDGER 861/860/755/659). It fires
  even on a 0.5-second run, which no test could cause.
- A **vacuous test** slipped past me AND past a build agent in the same session -
  mine had a broad `except` swallowing a signature `TypeError`; the agent's
  sampled its expected key out of the poisoned map. Both "passed" before the fix.
  Confirm RED for the RIGHT REASON, not just RED.

## Next session prompt

> Build the sanctioned Match-V5 replay pull into `core/rofl_archive.py` +
> `tools/rofl_archiver.py`: fetch `matchFileURLs` for each account, download,
> archive, extract, wired into `RC-RoflArchive`. FIRST fix the immutable-cache
> invalidation on API-key rotation (`riot_api.py:346`) - without it every stored
> PUUID stays stale and every pull 400s. Read the RM-106 block in ROADMAP.md and
> the two traps in WAKEUP before writing code; both are measured, not guessed.
> TDD, RED first, pytest exit captured BY REDIRECT and read from the file.

---


# 2026-07-19m (RM-104: the filing named one bug and the sweep found four; the three nobody filed were the live ones)

**The reported defect was real and exactly as described. It was also the least
important of the four, and the only one that could not reach production. The
sweep that found the other three took one script.**

Shipped: `1f13188b` ENGINE 1.228.0. DS 8866 passed / 1 skipped / 2518 subtests;
`tests/` 11993 passed / 23 skipped; `:8893` live at 1.228.0. Ledger 968.

**ALWAYS RUN THE SIBLING SWEEP BEFORE BELIEVING A FILING'S SCOPE.** RM-104 said
"Kaenic is the sole outlier whose mirror exists in the index but is uncredited."
False. Shieldbow `226673`, Sterak's `223053` and Maw `223156` had the identical
`shield=None` defect, are ALWAYS-ON, and had been crediting zero on every Arena
build. The filed one is default-OFF and reaches no route. A ~30-line script
resolving each mirror id to its longest base-id suffix proved the population is
exactly four, and that script is now a standing test - the defect was a CLASS
(mirror entries copied from an SR entry's prose with `shield=` dropped), so a
per-instance fix would have left the next one to rot silently.

**A SUBAGENT GAVE ME CORRECT EVIDENCE AND THE WRONG CONCLUSION.** The sourcing
agent found - accurately - that three of four mirrors are stat-retuned (350 vs
400 HP, 300 vs 400, 50 vs 60 AD) and concluded inheriting their shields is
"likely wrong, not merely unsourced." It conflated COEFFICIENT with OUTPUT. The
formulas scale off the champion's resolved `bonus_hp`/`bonus_ad`/`max_hp`, so
the retune already flows through: Sterak's credits 0.60 * 300 = 180.0, not 240.
Measured, not reasoned. Acting on that conclusion would have invented four
unsourced magnitudes to fix a non-problem. **Verify a subagent's INFERENCE
separately from its EVIDENCE - they fail independently.**

**I REGENERATED THE WRONG TABLE AND BRIEFLY REPORTED A FALSE RESULT.**
`tools/daemon_slayer_build_orders_generate.py` is NOT the artifact the stamp /
freshness tests read - those come from `core.build_order_precompute` and
`core.build_order_variants` at `--champions all`. The wrong tool returned
stamp-only, so I told the operator no recommendation had changed. The right
tools changed **68 of 173 ARENA** entries, all gaining `223053`, SR + ARAM
untouched. The acceptance criteria's "stamp-only" prediction was itself
inherited from the filing's latency claim and was wrong for the same reason.
Operator reviewed and shipped as-is.

**ORDERING: sync Share LAST.** I ran `ds_share_sync`, then edited 120 version-pin
test files, leaving the mirror stale behind me - one of 14 `tests/` failures,
none of which came from the fix. The bump ritual's regen/sync-THEN-suite order
exists for precisely this.

**THE NOTIFICATION LIED AND THE REDIRECT DID NOT.** The background-task
completion event reported `exit code 0`; the captured file read `MAIN_EXIT=1`
with 14 failures. Capture pytest by redirect and read the FILE - the
notification's exit code is not the suite's.

**NEXT: the silent-no-op bare excepts - and THE "~28" IS WRONG, MEASURED.** The
standing handoff has said "~28 silent-no-op bare excepts logging at DEBUG" for
three sessions. Re-sized by AST this session (grep is useless here - a naive
`except .*:` grep returns 232 and a run including vendored `python-embed/`
site-packages returns 1127). **First-party, excluding `tests/` + `Share/` +
`python-embed/`: 781 silent-no-op handlers - 166 debug-only and 615
pass/continue/`...`-only, of which 510 catch broad (bare / `Exception` /
`BaseException`).** So the debug-only class alone is ~6x the filed figure and
the total is ~28x. Do NOT scope the next session to 28.

Densest first-party files (debug-only): `game_reader/snapshot_normalizer.py` 23,
`lcu/lcu_rune_writer.py` 8, `agents/supervisor.py` 7, `coaches/arena_coach.py` 7,
`coaches/_base_coach.py` 7, `performance_tracker.py` 5. That population has now
produced FIVE silent failures across three sessions and is the highest-value
cleanup available - but it is a triage-and-batch job, not a one-session sweep.
Sizing script: scratchpad `size_silent_excepts.py` (AST, re-runnable).

---

# 2026-07-19l (three lanes shipped; every filing was wrong somewhere load-bearing, and I broke Share/src and fixed it)

**A ROADMAP number, a spec's prescribed fix, and a stated defect premise are all
just claims. Three of three were wrong this session in ways that would have
shipped defects, and all three were caught by reading files instead of prose.**

Shipped: `556662a7` RM-107 + the `begin/end` HTTP 400 sibling; `b9ac8de9`
CHANGELOG 1.224.0/1.225.0 backfill + prepend guard; `8bf21a77` Share/src
recovery; `ba676157` atomic Share sync; `a60d32e6` Lane 1 feed index + RM-108;
`37db1414` ENGINE 1.227.0 (RM-101/102/103/105). CI green. Ledger 965-967.

**THE INCIDENT, because it will recur otherwise.** Commit `6464532e` (mine)
emptied `Share/src` on main - 501 deletions, 596,900 lines, ZERO additions.
`ds_share_sync._write` was `rmtree` THEN rebuild, so the mirror spent the entire
~483-file rebuild deleted, and I committed while background agents were live.
Recovered within minutes; root-fixed in `ba676157` as stage-then-swap. **Do NOT
restore the rmtree shape.** Two rules earned: never commit while agents are
live, and verify a commit's CONTENTS, not its message.

**A SECOND silent trap in the same family:** `pathlib.write_text` on Windows
translates `\n` to `\r\n`, so my patcher scripts CRLF-ified 134 working-tree
files whose index form is LF. Only the Share byte-compare caught it. Any future
agent patching files with `write_text` reintroduces it - **use `write_bytes`.**

**Three filings corrected, do not re-inherit them.** (1) RM-107's prescribed
"narrow the except" is mechanically impossible - `_lcu_get` swallows the error
itself. (2) RM-101's ~154 HP is an UN-AMORTIZED upper bound, not a coefficient;
shipped at 0.25 = 38.38, and the "reorders a ranking" conclusion was then
MEASURED true anyway (+81.56 EHP, 9 of 138 positions, top-6 swap). (3) RM-108's
"a naive parser reads 0.0" is false - all 56,896 tokens land in display-prose
keys with zero runtime readers, so the detector serves registry AUTHORS.

**Two guards earned their keep.** The changelog guard I wrote this session
caught my OWN bump. The R134 signature guard rejected my OWN wiring (flags
inserted mid-signature). Both fired correctly on their author.

**NEXT: RM-104** (Kaenic mirror 222504) plus the three always-on lifeline
mirrors `226673` / `223053` / `223156` the verifier found carrying the identical
`shield=None` defect. Then the ~28 silent-no-op bare excepts the sweep sized but
did not fix - that population has now produced four silent failures in two
sessions.
