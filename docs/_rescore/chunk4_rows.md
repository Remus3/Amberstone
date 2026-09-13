# RC re-score, chunk 4 - LEDGER entries 1397 to 1406

## Method (not a tally - totals are deliberately left to the caller)

- **`fix_chain` DIRECTION APPLIED: FORWARD, per pin section 6.** Section 6 was read
  twice. The event is scored as the DEFECT, and `fix_chain` counts how many times
  THE REMEDY FOR THAT EVENT was itself subsequently refuted. `0` means the first
  remedy stood. No event here is scored as a fix-of-a-fix merely because it is
  somebody's second attempt - that is the backward reading the pin forbids.
- **Event definition applied:** a point where a CLAIM made in the course of the work
  was contradicted, corrected, retracted or found wrong. A pre-existing code bug with
  no stated antecedent claim is NOT scored as an event here. See the `pin_gap` on
  chunk4-25: pin section 6 says "score the event as the DEFECT", which arguably
  widens this, and the two readings give different counts.
- **Entry 1405 yields ZERO rows.** Its content is the verification of a sibling
  carrier's relayed finding. The headline and claims 1 and 2 are external-origin
  claims this tree never adopted (exclusion 2) and the headline additionally fits
  exclusion 5 exactly - this tree's own correct action (RM-406, already an ancestor of
  HEAD) is what made the other tree's record false. Claim 3 was CONFIRMED, not
  refuted. The remaining candidates inside it (the `ROOT` literal ruled LATENT, the
  `core/hot_reload.py:18` docstring non-member) are hypotheses opened by the probe
  that cleared them, exclusion 4.
- Other exclusions applied: exclusion 1 (recitals) removed entry 1403's cycle-12
  citation and entry 1399's RM-406 pin-move recital; exclusion 4 removed entry 1397's
  rejected re-pointing candidate and entry 1401's five checked-and-excluded route
  sites.

---

## chunk4-01

- `id`: chunk4-01
- `entry`: 1397
- `claim`: The `tests/` tree was too slow to run inside a loop cycle, so cycle 7 shipped without running it.
- `quote`: `cycle 7 shipped without running the suite, because a prior serial run had been measured at roughly four hours`
- `refuter`: This cycle's own full `tests/` run under `-n 8`, finishing in 307 seconds.
- `prevention`: CONTRACT
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-02

- `id`: chunk4-02
- `entry`: 1397
- `claim`: Cycle 7's work was green when it shipped.
- `quote`: `A GUARD WAS ALREADY RED WHEN THIS CYCLE STARTED`
- `refuter`: Cycle 74's full `tests/` tree run.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the survival guard was already present and already failing at `7ff5fc853`, but the suite was not run at cycle 7.
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-03

- `id`: chunk4-03
- `entry`: 1397
- `claim`: The existing survival guard protects the newest session row in the director context window.
- `quote`: `the survival guard only reds AFTER the row has already fallen out`
- `refuter`: The slice's own analysis while building the replacement headroom arm.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - it grades the right property but only after the row has already been cut, so it cannot prevent the loss it detects.
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-04

- `id`: chunk4-04
- `entry`: 1397
- `claim`: The audit doc's citation to `ORCHESTRATION_PLAN.md:916-919` resolved to the sentence it quoted.
- `quote`: `the citation was ALREADY content-stale before this change`
- `refuter`: The baselining check run this cycle, resolving the range at 948 lines.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: NO - baselined historical rather than re-pointed, deliberately.
- `fix_chain`: 0

## chunk4-05

- `id`: chunk4-05
- `entry`: 1398
- `claim`: The lane-8 directive claimed `dashboard/_state_builder.py` pays a duplicate `/activeplayerrunes` fetch tax.
- `quote`: ``"duplicate `/activeplayerrunes` tax" REFUTED``
- `refuter`: The slice's own triage pass before any code was written.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-06

- `id`: chunk4-06
- `entry`: 1398
- `claim`: The directive claimed `PolledJsonFile` should be moved onto `NamedMutex`.
- `quote`: ``"`PolledJsonFile` onto `NamedMutex`" REFUTED``
- `refuter`: The slice's triage - `core/polled_json.py:204` records zero production instantiations and `ops/loop/winmutex.py` has no such class.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-07

- `id`: chunk4-07
- `entry`: 1398
- `claim`: The directive claimed orphan-tree wiring was outstanding work.
- `quote`: `orphan-tree wiring = RM-407 and split-form sibling scanner = RM-399, ALREADY SHIPPED`
- `refuter`: The slice's triage against shipped ledger state.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-08

- `id`: chunk4-08
- `entry`: 1398
- `claim`: The directive claimed a split-form sibling scanner was outstanding work.
- `quote`: `orphan-tree wiring = RM-407 and split-form sibling scanner = RM-399, ALREADY SHIPPED`
- `refuter`: The slice's triage against shipped ledger state.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-09

- `id`: chunk4-09
- `entry`: 1398
- `claim`: The directive implied the `SHARED_SHA256` pins had drifted from the live bytes.
- `quote`: ``pins MATCH live bytes``
- `refuter`: The slice re-running the byte pin.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - `tests/test_loop_concurrency.py` pins exactly this and would have answered the claim before it entered a directive.
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-10

- `id`: chunk4-10
- `entry`: 1398
- `claim`: BACKLOG RM-234 and LEDGER 1117 claimed there is no production consumer of `my_runes`.
- `quote`: ``BACKLOG RM-234 + LEDGER 1117 claimed "no production consumer of `my_runes`" - FALSE``
- `refuter`: The slice's consumer census - `coaches/aram_coach.py:430` templates it and `:1031` feeds Haiku.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `uncertain`: BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-11

- `id`: chunk4-11
- `entry`: 1398
- `claim`: Directive hypothesis H2 against `item_advisor.py` was a real defect.
- `quote`: `H2 REFUTED`
- `refuter`: Slice E's probe.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: exclusion 4 turns on WHO opened the hypothesis. The entry names H1/H2/H3 without saying whether they were filed in the directive or raised by the probe that cleared them. Scored as an event on the reading that the directive opened them, consistent with the five triage rows above.

## chunk4-12

- `id`: chunk4-12
- `entry`: 1398
- `claim`: The new `RC_ATOMIC_WRITE_GATE` could run in block mode over net-new staged runtime lines.
- `quote`: `BLOCK MODE NOT VIABLE YET - that is the finding`
- `refuter`: The slice's own back-test - strict 4 hits / 2 files, lenient 11 / 9, with named false negatives and false positives.
- `prevention`: GATE-ABSENT
- `uncertain`: PROXY-MEASURE
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: NO - shipped warn-by-default instead.
- `fix_chain`: 0

## chunk4-13

- `id`: chunk4-13
- `entry`: 1398
- `claim`: A mis-typed `win_pct` input crashes the frozen state authority.
- `quote`: ``already caught the crash; effect: STALE `win_pct` ``
- `refuter`: The slice's call-path read of `app/_game_lifecycle.py:465-467`.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: the entry records the corrected effect without restating the antecedent claim in full, so event-hood rests on the word "already". The pin gives no rule for a correction whose antecedent is implied rather than quoted.

## chunk4-14

- `id`: chunk4-14
- `entry`: 1399
- `claim`: The builder reported the RM-412 slice all green.
- `quote`: `AN INDEPENDENT VERIFIER REFUTED THE BUILDER'S "ALL GREEN" and found a hard red the builder never reported`
- `refuter`: An independent read-only verifier.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the `docs/OPERATIONS.md` test-scope guard is present and self-declared authoritative, and the builder did not run it.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - fixed in the same commit.
- `fix_chain`: 0

## chunk4-15

- `id`: chunk4-15
- `entry`: 1399
- `claim`: 317 passed across 16 repo-root-enumerating guards proved the new package tree clean.
- `quote`: `the builder ran 16 repo-root-enumerating guards and got **317 passed**, proving NOTHING`
- `refuter`: A `git add -N` re-run, which surfaced 2 real failures.
- `prevention`: GATE-EXISTING
- `prevention_why`: VACUOUS - the guards enumerate the git index per ADR-015 and the new files were untracked, so every one of them passed while measuring nothing.
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-16

- `id`: chunk4-16
- `entry`: 1399
- `claim`: The package was swept clean of sibling names across 31 banned identifiers in three variants.
- `quote`: ``THE ONE REAL SIBLING-NAME LEAK WAS IN `__pycache__`, NOT SOURCE.``
- `refuter`: The slice's own publish-shape check, which found `.pyc` files embedding the absolute repo path.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - the sibling-name sweep reads tracked source, and the leak sat in untracked bytecode invisible to a git publish but shipped by a tar or cp -r publish.
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES, with the entry stating the residual is transient because any pytest run repopulates `__pycache__`.
- `fix_chain`: 0

## chunk4-17

- `id`: chunk4-17
- `entry`: 1399
- `claim`: The new package could declare itself all-rights-reserved and not yet distributable.
- `quote`: `the package declared itself all-rights-reserved and "not yet distributable" while sitting in a PUBLIC repo`
- `refuter`: The slice's own license-gate pass before the package mattered.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - byte-identical Apache-2.0 copy plus three guards.
- `fix_chain`: 0

## chunk4-18

- `id`: chunk4-18
- `entry`: 1399
- `claim`: The package README claimed exactly one degraded input is swallowed silently.
- `quote`: `the README claimed ONE degraded input was silent when **TWO** are`
- `refuter`: The slice re-reading the `OSError` branch against the prose.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0
- `pin_gap`: the pin fixes no granularity rule. The three README corrections in this entry share one artifact, one author and one pass, and are equally defensible as one event or three. Scored as three (chunk4-18, -19, -20) because each is a distinct false proposition.

## chunk4-19

- `id`: chunk4-19
- `entry`: 1399
- `claim`: The package README claimed the replace retry simply never fires on POSIX.
- `quote`: ``it claimed the retry "simply never fires" on POSIX when a bare `PermissionError` catch means **`EACCES` DOES fire it**``
- `refuter`: A measured ACL-denial run - 4 attempts, roughly 275 ms.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-20

- `id`: chunk4-20
- `entry`: 1399
- `claim`: The package README claimed a scratch file is never left behind.
- `quote`: ``"never left behind" is true for raised exceptions and **FALSE** for `SIGKILL` / `taskkill /F` / power loss``
- `refuter`: The slice re-deriving the guarantee from the code paths.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-21

- `id`: chunk4-21
- `entry`: 1399
- `claim`: The repo's root `.gitattributes` covered the new package, so a local green meant a green fresh clone.
- `quote`: ``the root `.gitattributes` pins only `*.py` / `*.md`, so the new `.gitignore` would have checked out CRLF in a fresh clone``
- `refuter`: The slice's own clone-shape reasoning against `core.autocrlf=true`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - package-local `.gitattributes` pinning `eol=lf`.
- `fix_chain`: 0

## chunk4-22

- `id`: chunk4-22
- `entry`: 1400
- `claim`: The shipped test pins the non-WAL warning check the way RM-233's acceptance asked.
- `quote`: ``the non-`wal` WARN branch is UNFALSIFIABLE ON THIS HOST``
- `refuter`: The slice's own caveat, corroborated by the independent verifier.
- `prevention`: PROXY-MEASURE
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: NO - the test pins the pragma READ; the emit half has never been observed firing.
- `fix_chain`: 0

## chunk4-23

- `id`: chunk4-23
- `entry`: 1401
- `claim`: RM-296d's filed row claimed that mapping the string "false" to False invents a JSON convention the rest of the API does not use.
- `quote`: `"invents a JSON convention the rest of the API does not use". It does not invent one`
- `refuter`: The slice's precedent search, which found the convention already in `dashboard/routes_diag.py:347-350`.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-24

- `id`: chunk4-24
- `entry`: 1402
- `claim`: RM-313's fence claimed that coercing `championId` risks breaking JS consumers that currently strict-compare strings.
- `quote`: `That census was run, and it inverted the expected risk.`
- `refuter`: The slice's census over the `web/js` consumers - zero unsafe-on-int, two unsafe-on-string.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-25

- `id`: chunk4-25
- `entry`: 1402
- `claim`: The string-`championId` consumer exposure was hypothetical.
- `quote`: `a string id silently badged the **WRONG ARENA PLAYER AS ME** - a live rendering defect, not a hypothetical`
- `refuter`: The same consumer census, reading `web/js/panels/champ_select.js:3516`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES, partially
- `fix_chain`: 1
- `chain_kind`: SIBLING-SURFACE
- `pin_gap`: two gaps meet here. (a) The remedy was found incomplete in the SAME session that shipped it - `arena_teams()` at `:195` is read first and stays uncoerced - and the pin does not say whether a same-session limitation counts as the remedy being "subsequently refuted". Scored as 1 on the reading that it does. (b) Pin section 6 says "score the event as the DEFECT", which would admit bare code defects with no antecedent claim as events; the task's definition would not. This row is scored under the task's definition because the entry explicitly contradicts the filed "hypothetical" framing.

## chunk4-26

- `id`: chunk4-26
- `entry`: 1402
- `claim`: RM-313's acceptance claimed `championId` and its sibling fields could be coerced in one pass.
- `quote`: `THE ROW'S ONE-PASS ACCEPTANCE IS DELIBERATELY NOT MET`
- `refuter`: The per-field census result, which found two live consumer defects on one field and did not generalise.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / OVER-GENERALISED
- `correct`: YES
- `defect_corrected`: NO - siblings filed as RM-417 rather than shipped.
- `fix_chain`: 0

## chunk4-27

- `id`: chunk4-27
- `entry`: 1403
- `claim`: RM-318's acceptance scope - the six detectors - covered the severe case.
- `quote`: `THE SEAM REACHES ONE SITE THE FILED ROW DID NOT ASK FOR, AND THAT SITE IS THE SEVERE ONE.`
- `refuter`: The slice reading `DecisionLoop._loop`, whose `gameTime` read sits outside the per-detector try/except and kills the whole tick.
- `prevention`: CONTRACT
- `uncertain`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES - the shipped coercion covers that read too.
- `fix_chain`: 0

## chunk4-28

- `id`: chunk4-28
- `entry`: 1404
- `claim`: RM-295a's premise claimed the only signal on a frozen duo-synergy snapshot is a log.warning.
- `quote`: ``the row's own premise that "the only signal is a `log.warning`" was itself optimistic on one of the three paths``
- `refuter`: The slice's three-freeze-path audit - the `_refresh` except handler logged nothing at all.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 1
- `chain_kind`: SELF
- Note on the chain: the remedy, `health()`, was found in the same entry to have no consumer at all, filed as RM-416, and the entry names that as a repeat of RM-295b's own mistake.

## chunk4-29

- `id`: chunk4-29
- `entry`: 1404
- `claim`: RM-295a's parenthetical defined `stale_for_s` as now minus `_LOADED_AT`.
- `quote`: `THE FILED SPEC WAS WRONG AND IS CORRECTED RATHER THAN FOLLOWED`
- `refuter`: The slice, finding `_LOADED_AT` is the RETRY stamp, so the literal spec reads 0 during the exact outage it exists to report.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - measured from `_LAST_GOOD_AT` while keeping the row's key names.
- `fix_chain`: 0

## chunk4-30

- `id`: chunk4-30
- `entry`: 1404
- `claim`: RM-295a's fence claimed `dashboard/routes_duo_synergy.py` and the UI badge both read `source()`.
- `quote`: `BOTH HALVES ARE FALSE AT HEAD`
- `refuter`: The merger's independent re-probe - zero `source()` calls there and no non-test caller repo-wide.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNKNOWN
- `uncertain`: DECAYED
- `correct`: YES
- `defect_corrected`: YES - the reason was replaced and the fence deliberately kept on other ground.
- `fix_chain`: 0

## chunk4-31

- `id`: chunk4-31
- `entry`: 1404
- `claim`: A `stale:live` / `stale:static` prefix on `source()` was the right way to surface staleness; it shipped in slice `95c5fa2fa`.
- `quote`: `THE PREFIX EXPERIMENT WAS BUILT, MEASURED AND DELIBERATELY REFUSED AT MERGE`
- `refuter`: The merge-time adjudication, on the ground that shipping it required widening the lock test that exists to forbid it.
- `prevention`: GATE-FIRED-IGNORED
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - reverted in `b51b05092`, lock test byte-identical across both slice commits, plus an inverted test asserting the prefix is absent.
- `fix_chain`: 0

## chunk4-32

- `id`: chunk4-32
- `entry`: 1404
- `claim`: The merger's verifier prompt claimed the revert restored `source()` byte-for-byte.
- `quote`: ``the verifier prompt claimed the revert restored `source()` "byte-for-byte", and that was REFUTED as worded``
- `refuter`: The independent verifier - the function text grew from 162 to 1573 chars.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - restated as AST-identical body with an unchanged return domain.
- `fix_chain`: 0

## chunk4-33

- `id`: chunk4-33
- `entry`: 1406
- `claim`: BACKLOG RM-217 stood OPEN, prescribing a `RETRACTED:` marker the stop-claim scanner honours.
- `quote`: `THE FIRST FINDING IS THAT THE ROW WAS ALREADY DEAD.`
- `refuter`: This slice's row-age check against RM-396 (REFUTED, 2026-09-09) and RM-398 in the same file.
- `prevention`: GATE-ABSENT
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES - RM-217 closed.
- `fix_chain`: 0

## chunk4-34

- `id`: chunk4-34
- `entry`: 1406
- `claim`: The filed rows recited the transcript corpus size as 90 / 91 / 92 / 93.
- `quote`: `the rows above recite 90 / 91 / 92 / 93 and every one of them is now stale`
- `refuter`: This run's re-derivation - 123 frozen transcripts, 0 parse errors.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / DECAYED
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-35

- `id`: chunk4-35
- `entry`: 1406
- `claim`: A loose retraction rule - a retraction verb anywhere in a sentence naming the number - would clear genuine retractions.
- `quote`: `4 of the 5 cleared are OFF-TARGET`
- `refuter`: Corpus scoring over 123 frozen transcripts, including three pure collisions where nothing was retracted and RM ids parsing as numbers.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `uncertain`: FRESH
- `correct`: YES
- `defect_corrected`: YES - variant A refused.
- `fix_chain`: 0

## chunk4-36

- `id`: chunk4-36
- `entry`: 1406
- `claim`: Tightening the retraction rule to the 40-char `_negated` window makes it both safe and useful.
- `quote`: `Precision 0 of 1, recall 0 of 1 on the target class.`
- `refuter`: The same corpus scoring - the one finding it clears is a true positive and not a retraction.
- `prevention`: GATE-ABSENT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - variant B refused.
- `fix_chain`: 0

## chunk4-37

- `id`: chunk4-37
- `entry`: 1406
- `claim`: A retraction always self-flags by re-spelling the figure.
- `quote`: `The first draft asserted that a retraction always self-flags by re-spelling the figure; it was RED against the real gate`
- `refuter`: The real gate - `CLAIM_COUNT` wants `passed`, so only a retraction that QUOTES the figure self-flags.
- `prevention`: GATE-FIRED-CAUGHT
- `discovery`: RUN
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES
- `fix_chain`: 0

## chunk4-38

- `id`: chunk4-38
- `entry`: 1406
- `claim`: The brief's "six consecutive Stops" figure, written into a tracked source comment.
- `quote`: `the brief's "six consecutive Stops" figure was written into a tracked source comment before being checked`
- `refuter`: The slice checking `ops/runtime/stop_claim_history.jsonl`, whose rows carry counts and check names but not the quotes.
- `prevention`: CONTRACT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / UNDER-PROVEN
- `uncertain`: UNKNOWN
- `correct`: YES
- `defect_corrected`: YES - attributed to the brief rather than asserted, with the measured figures in the comment.
- `fix_chain`: 0

## chunk4-39

- `id`: chunk4-39
- `entry`: 1406
- `claim`: The gate's armed emit told sessions to retract, a remedy the file implements.
- `quote`: ``the armed emit read "Fix or retract, then finish" - half of it naming a remedy `audit()` does not implement and never did``
- `refuter`: This slice reading `audit()`.
- `prevention`: GATE-ABSENT
- `discovery`: CODE-READ
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - one-string correction, `audit()` untouched and frozen-corpus figures identical on both sides.
- `fix_chain`: 0

## chunk4-40

- `id`: chunk4-40
- `entry`: 1406
- `claim`: The verifier claimed the mid-run modified-file movement came from another session.
- `quote`: `it reported the tree going 3 -> 6 modified files mid-run and attributed it to another session. It was this one.`
- `refuter`: The merger, recording the process caveat rather than smoothing it over.
- `prevention`: CONTRACT
- `discovery`: SELF-AUDIT
- `origin_time`: FRESH
- `correct`: YES
- `defect_corrected`: YES - every measurement re-run against the current bytes, with the entry stating the second pass is what is relied on.
- `fix_chain`: 0

## chunk4-41

- `id`: chunk4-41
- `entry`: 1406
- `claim`: RM-396 left an evidence-bearing retraction defensible as an escape hatch.
- `quote`: `ITS ADVERSARIAL PASS CLOSED THE ONE ESCAPE HATCH RM-396 HAD LEFT OPEN.`
- `refuter`: The adversarial verifier - the attack transcript already contains a real green run, so any evidence-keyed rule silences the fabrication too.
- `prevention`: ADVERSARY
- `discovery`: SELF-AUDIT
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: YES - the space collapses to an external human.
- `fix_chain`: 0

## chunk4-42

- `id`: chunk4-42
- `entry`: 1406
- `claim`: Entry 1405's own "pin advanced" parenthetical, naming the next-free id, was clean.
- `quote`: ``was ALREADY RED at `9b4bb834d`, on exactly this shape, from entry 1405's own "pin advanced" parenthetical``
- `refuter`: `tests/test_rm_id_registry_drift.py::test_the_pinned_next_free_id_is_not_allocated_anywhere`.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong time - the guard was present and would have failed at 1405's own commit, but was not observed until this run.
- `uncertain`: GATE-FIRED-IGNORED
- `discovery`: RUN
- `origin_time`: INHERITED / BORN-WRONG
- `correct`: YES
- `defect_corrected`: YES - cleared by advancing the pin past the now genuinely allocated id.
- `fix_chain`: 0

## chunk4-43

- `id`: chunk4-43
- `entry`: 1406
- `claim`: The stop-claim gate covers a fabricated count.
- `quote`: ``records an edit's `file_path` and NEVER its content, so a fabricated count written into a tracked file draws zero findings``
- `refuter`: The slice's own three-case control - chat-only 1 finding, file-only 0, both 1.
- `prevention`: GATE-EXISTING
- `prevention_why`: wrong scope - `collect_evidence` reaches chat text and edit paths but never edit content, so the laundering route is unmeasured.
- `discovery`: RUN
- `origin_time`: INHERITED / UNDER-PROVEN
- `correct`: YES
- `defect_corrected`: NO - spun off as RM-421, explicitly do not fold back.
- `fix_chain`: 0
