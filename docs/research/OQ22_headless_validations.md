# OQ22 - Headless validations (moved OFF the gated checklist)

Date: 2026-07-02. Run: gemini-headless-upgrade loop, directive cycle (grounded HEAD
5d6e50ae, LEDGER-top 745). ENGINE-IMPACT: NONE (read-only validation; the single code
change is a Tier-1 presentation-string fix in a deterministic comp engine, no DS math /
ENGINE_VERSION / flag touched).

Four items from docs/LIVE_GAME_GATED_SYNC.md "Not actually live-gated (validate headless)"
were run as 4 disjoint parallel read-only analysis slices (orchestrator + sole-merger; each
slice verifier-gated against ground truth before its verdict was accepted). Summary:

| Slice | Verdict | Flip? | Action |
|-------|---------|-------|--------|
| S1 comp-verdict soundness | BUG-CONFIRMED | no (plain bug) | FIXED in-run (TDD, 3 regression tests) |
| S2 pickban-DB counter-quality | CORPUS-TOO-THIN | no | report-only; ROADMAP:55 flip stays operator-gated |
| S3 ability_hps v2 wiring | SUBSTRATE-SOUND-DEFERRED | no | report-only; base fold-in already live, heal-amp flip stays gated |
| S4 same-state Haiku-skip fidelity | PARTIAL-NEEDS-LIVE | no | report-only; debounce default-OFF stays operator-gated |

---

## S1 - Comp-verdict SOUNDNESS (Vex->Garen "all-AD comp" inverted) = BUG-CONFIRMED + FIXED

The LGS2 (2026-06-17) live-play flag was correct. On a mono-AP ARAM comp, the swap/variant
reason labelled the comp by the type it LACKS (the deficit) instead of the type it has (the
excess), producing the inverted "All-AD comp - swap to Garen to mix the damage type" for what
is actually an all-AP comp.

Root cause (independently traced by the orchestrator AND slice agent; identical conclusion):
- core/aram_comp_verdict.py `_damage_deficit` returns the MISSING primary damage type:
  `detail="ap"` means AP is absent (comp is mono-AD); `detail="ad"` means AD is absent (comp
  is mono-AP). The comp's excess (mono) type is the OPPOSITE of `detail`.
- core/aram_comp_verdict.py:333 (swap path, `_swap_reason`) interpolated `detail` directly:
  `f"All-{detail.upper()} comp - swap to {pick} to mix the damage type."` -> inverted label.
- core/aram_comp_verdict.py:304 (variant path) had the identical inversion in its "All-{X}"
  prefix (its "adds magic/physical" remedy clause was already correct).

The remedy logic was ALWAYS sound: `_bench_addresses` (line 223) requires
`_damage_lean(c) == detail`, so the swap/variant always adds the missing type. Only the
human-readable comp LABEL was backwards. This is a deterministic comp engine, not a DS
default-OFF live-flip seam, so it is a plain presentation bug - NOT an operator-gated flip.

Fix (this run): both sites now compute `excess = "AD" if detail == "ap" else "AP"` and label
the comp by its excess. TDD: 3 regression tests added to tests/test_aram_comp_verdict.py
(`test_mono_ad_swap_reason_labels_comp_as_ad`, `test_mono_ap_swap_reason_labels_comp_as_ap`,
`test_mono_ap_variant_reason_labels_comp_as_ap`) - RED-first (reproduced the exact
"All-AD comp - swap to Garen" string), GREEN after fix. 102 passed across comp_verdict + all
5 sibling test files (advisor / routes / bench_ui / champ_select_deterministic / p2w1_coach_a);
no existing test asserted the buggy string (the one advisor fixture at
tests/test_champ_select_advisor_deterministic.py:93 is a monkeypatched stub already carrying
the CORRECT non-inverted phrasing).

Secondary note (FUTURE, not this bug): Vex has DDragon-zeroed info.attack/info.magic (per
memory `reference_ddragon_info_zeroed_champs`), so `_damage_lean(Vex)` resolves "hybrid", not
"ap"; the mono-detection ignores hybrids by design (line 184-186). Deciding whether zeroed
champs should resolve their lean via `core.champion_info_overrides` is a distinct enhancement.

## S2 - champ_select pickban-DB counter-quality = CORPUS-TOO-THIN

The pickban targets DB (data/daemon_slayer/<patch>/pickban_targets.json, header confirmed:
level 9, mode sr, ranking `debiased_relative`, patch 16.13.1) is generated offline from a
single itemless level-9 1v1 `agents.daemon_slayer.matchup.compute_matchup` verdict per pair
(core/pickban_targets.py:14-30), de-biased so each champ's counter list is champ-specific.

The rewind corpus CANNOT validate it at pair granularity. Ground-truth verified:
rewind_history.db = 2954 matches, but 2073 are ARAM (queue 450) and only 660 are SR-classic
(queues 400/420/430/440/490 = 139+516+3+2+0), which is the relevant slice for an SR duel
proxy. Over a 10-champ role-spread sample (50 champ->counter pairs, 38 with any opposing-team
game): pooled suggested-counter win rate = 49.5% (a coin flip), per-pair n median 2.5, max 7,
ZERO pairs reached n>=10. The single most-frequent opposing pair in all 660 SR games is
Jinx/Vladimir at 24 games (role-agnostic) - still far below the ~100+ games needed to detect
a modest counter edge at 95% CI. The 49.5% is noise; it neither validates nor inverts the
table.

Recommendation: the ROADMAP:55 pickban-DB flip STAYS operator-gated. A real validation needs
a much larger lane-labeled SR corpus (10k+, `team_position`-restricted, per-pair Wilson CI),
or live-game observation over many games. Do NOT flip on this evidence.

## S3 - ability_hps v2 wiring = SUBSTRATE-SOUND-DEFERRED (ROADMAP:72 prose is stale)

Ground-truth verified: the BASE ability-HPS fold-in is ALREADY live-wired, contrary to the
ROADMAP:72 "substrate now ready / deferred" framing. `compute_ability_hps` is imported and
called on every enchanter build at agents/daemon_slayer/hps.py:620-636, and folded into the
ranked total at hps.py:640 (`total = direct + buff_credit + ability_hps_total`), so it already
influences the `/rank-enchanter` + `/hps` ranking. What is STILL deferred/operator-gated is
the `assume_missing_hp_heal_amp` FLAG (hps.py:499 + ranker hps.py:828, default False) - the
R5 missing-HP heal-amp seam already tracked in docs/LIVE_GAME_GATED_SYNC.md. That is the
correct expected state (scoring-math change; do not flip blind).

Corpus agreement: 789 winning enchanter builds across 8 champs (65-121 wins each). The 9-item
enchanter registry (Redemption / Knight's Vow / Locket / Mikael / Ardent / Imperial Mandate /
Staff of Flowing Water / Moonstone / Echoes of Helia) captures the corpus core
(Moonstone/Ardent/Redemption/Imperial Mandate/Staff/Mikael/Echoes all present). GAP (FUTURE,
corpus-derived, not re-verified per-item this run): 5 corpus-proven winners are NOT in the
registry - Dream Maker (3870), Dawncore (6621), Shurelya (2065), Seraph's Embrace (3040),
Luden's (6655); since `enchanter_only=True` restricts the candidate pool to the registry,
`/rank-enchanter` cannot surface them. This is a coverage gap independent of the ability-HPS
math.

Recommendation: keep the heal-amp flip operator-gated. Two follow-ups flagged FUTURE:
(1) ROADMAP:72 prose is stale (base fold-in already live; only the flag remains); (2) enchanter
registry omits 5 corpus-proven winners - registry expansion + a live SR-support game would be
needed before any default-on decision.

## S4 - Same-state Haiku-skip fidelity = PARTIAL-NEEDS-LIVE

Mechanism (ground-truth verified): `_coach_state_signature` at coaches/aram_coach.py:66 (fields
at :104-121) with the skip-gate at aram_coach.py:859-864, sibling in coaches/arena_coach.py:73.
Both default OFF (`RC_ARAM_STATE_DEBOUNCE` / `RC_ARENA_STATE_DEBOUNCE` = "0", aram_coach.py:57 /
arena_coach.py:64), with a hard `_STATE_DEBOUNCE_MAX_STALE_S = 45.0` ceiling forcing a re-call
regardless of signature. Brawl has no debounce. Discrete busters (level / item / HP-band-cross /
round / next-opponent) are covered by tests/test_aram_state_debounce.py +
tests/test_arena_state_debounce.py (both present).

Replay proof (partial): reconstructed signatures from data/coach_trace.jsonl (200-cap ring; 126
ARAM fired-call rows from one ~33-min match). Only 2 of 125 consecutive pairs collapsed to the
same recoverable signature; BOTH were correct skips (dead/respawn-wait and game-start-hold, same
coaching action), ZERO false-skips. But this is insufficient for a full headless proof: it is
one match, fired-calls-only (the dense poll stream the debounce actually gates is not logged),
three vision-only signature fields (tower HP / augments / hp_packs) are unrecoverable from the
trace, and there are zero Arena rows.

Recommendation: do NOT flip. The default-ON flip still needs the C14/D5 live rows - a live ARAM
+ a live Arena game with the flag ON in shadow (or a poll-stream capture logging every tick's
signature) to measure the true skip rate and confirm no tower-HP / augment / threshold-crossing
false-skip. Both flags stay operator-gated.

---

## Net outcome

- 1 real bug found and FIXED in-run (S1, TDD, no flip): comp-verdict inverted damage-type label.
- 3 validations confirm the corresponding flips must STAY operator-gated (S2 corpus-too-thin,
  S3 heal-amp scoring-math change, S4 fidelity partial). No flip was flipped.
- 2 FUTURE follow-ups surfaced (not built): ROADMAP:72 stale prose + enchanter registry
  coverage gap (S3); pickban validation needs a larger lane-labeled corpus (S2).
