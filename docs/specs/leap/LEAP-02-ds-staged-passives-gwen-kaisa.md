# LEAP-02 - DS staged passive-damage entries: Gwen P + Kai'Sa P

Status: SPEC (pre-implementation). Author pass: 2026-07-16.
Target model: claude-opus-4-8, effort MAX (Tier-2 engine slice).
Estimated sessions: 1.

---

## GOAL

front-load the thinking into specs; execution sessions are typing, not deciding.

Close the loop on the two "STAGED own-slice" champion passive-damage entries the
DAEMON_SLAYER.md:71 changelog line names (Gwen P bilinear AP-on-HP + Kai'Sa P
per-Plasma-stack). This deepens the just-shipped 7th archetype scorer `ds.onhit`
(ENGINE 1.216.0, LEDGER 911, Slice B, on-hit AP combined-DPS for
Gwen/Kayle/Kog'Maw).

CRITICAL HEADLINE (read EVIDENCE before writing a line of code): the two
"decisions" the task title implies are still open are ALREADY SHIPPED. Both
entries are seeded with concrete, live decisions. Gwen P is additionally routed
end-to-end and live. The genuine remaining work is narrow:

  1. Route the ONE unrouted entry (Kai'Sa P) into the AA on-hit cadence seam so
     its Caustic Wounds per-stack magic becomes route-reachable (byte-identical
     by default, live flip stays operator-gated) - the real ENGINE delta.
  2. Refresh two STALE "STAGED" markers that outlived their seeding (append-only
     changelog line + an inline comment).
  3. TDD RED-first per-champion regression pins that LOCK the shipped Gwen
     bilinear evaluation and the shipped Kai'Sa per-stack evaluation, plus the
     new Kai'Sa route-reachability + default byte-identity.

Do NOT re-derive the bilinear term shape or the stack count - they exist; the
job is to confirm, route the missing consumer, tell the truth in docs, and pin.

---

## EVIDENCE (ground-truth, every claim cited file:line)

Current state, all verified live against the tree on 2026-07-16:

- ENGINE_VERSION = `1.216.0` at `agents/daemon_slayer/__init__.py:18`. Live patch
  `16.14.1` at `data/daemon_slayer/current.txt`.

- **Gwen P is SEEDED (bilinear), NOT staged.** `_passive_damage_overrides.py:599-607`:
  `("Gwen","P",0)` = `PassiveDamageEntry(target_max_hp_pct=1.0,
  bilinear_terms=(_per_100(0.55, "ap", "target_max_hp"),), damage_type="MAGIC",
  cadence="on_hit", ...)`. Seeded by item 248 = ENGINE 1.80.0 (bilinear AP-on-HP
  schema lift), `agents/daemon_slayer/CHANGELOG.md:4064`. The bilinear evaluator
  term the changelog said Gwen "needs" was BUILT and Gwen was the canonical case
  it was built for (`_passive_damage_overrides.py:596-598`).

- **Gwen P is ROUTED live end-to-end.** `("Gwen","P",0)` is in
  `_AA_ROUTED_ON_HIT_KEYS` at `_passive_damage_overrides.py:1107` (added by
  Slice B, LEDGER 911, ENGINE 1.216.0). The consumer reads it at
  `agents/daemon_slayer/dps.py:1177` (import) + `:1183`
  (`aa_routed_on_hit_entry(resolved.champion_id)`). Gwen is on the on-hit AP
  roster with coherence 1.0 (`core/ds_onhit_ap_roster.json`). Gwen P is DONE -
  zero work this slice; it is a regression-pin target only.

- **Kai'Sa P is SEEDED (per-stack), NOT staged; its stack-count decision is made.**
  `_passive_damage_overrides.py:677-686`: `("Kaisa","P",0)` =
  `PassiveDamageEntry(base=_lerp_per_level(4.0,24.0), ap_pct=12.0,
  per_stack=PerStackTerm(base=_lerp_per_level(1.0,6.0), ap_pct=3.0),
  assumed_stacks=2.0, damage_type="MAGIC", cadence="on_hit", ...)`. Seeded by
  item 249 = ENGINE 1.81.0 (per-stack passive-damage schema lift),
  `CHANGELOG.md:4027` and `:4044` ("the canonical case STAGED through item 248").
  The `assumed_stacks=2.0` note (line 684) documents the rationale verbatim:
  "cap 5/consume-at-5; assumed_stacks 2.0 = ramp-cycle-average, operator-tunable".

- **Kai'Sa P is NOT routed into any consumer.** `_AA_ROUTED_ON_HIT_KEYS`
  (`_passive_damage_overrides.py:1103-1111`) holds exactly Warwick P, Orianna P,
  Gwen P, Kayle E, Kog'Maw W. No Kai'Sa. Kai'Sa is NOT on the on-hit AP roster
  (`core/ds_onhit_ap_roster.json` = Gwen/Kayle/KogMaw only). So Kai'Sa P is
  seeded-but-inert: it injects only under `apply_passive_damage=True`, which no
  live scorer enables for her. THIS is the one genuine open item.

- **Two STALE "STAGED" markers survive their own seeding:**
  - `docs/DAEMON_SLAYER.md:71` (the immutable ENGINE 1.78.0 / item 247 line):
    "STAGED own-slice: Gwen P (bilinear AP-on-HP needs a core evaluator term) +
    Kai'Sa P (per-Plasma-stack ramp needs a stack-count decision)." This line is
    append-only-immutable by the changelog rule ("never append to a prior
    version's line", `docs/DAEMON_SLAYER.md:75`), so it is not edited in place -
    it is superseded by a NEW top line.
  - `_passive_damage_overrides.py:499-502`: an item-247 inline comment claiming
    Gwen and Kai'Sa "remain STAGED in the docstring" - stale; the seeded entries
    sit directly below it at lines 599 and 677. This comment IS editable and
    should be corrected in place.

- **Allowlist test is assertIn-based, not exact-set.**
  `agents/daemon_slayer/tests/test_passive_damage_aa_cadence.py:124-126` asserts
  `assertIn(("Warwick","P",0))`, `assertIn(("Orianna","P",0))`,
  `assertNotIn(("Ziggs","P",0))`. No full-set equality, and (2-probe scan) no
  `assertNotIn(("Kaisa",...))`. Adding Kai'Sa will NOT break it. NOTE a stale
  COMMENT at `tests/test_onhit_dps.py:65` ("Gwen's Thousand Cuts was excluded
  from `_AA_ROUTED_ON_HIT_KEYS`") is pre-Slice-B and now false - not an
  assertion, harmless, may be tidied opportunistically.

- **Bilinear evaluator math (for the Gwen pin), from the docstring worked
  example** `_passive_damage_overrides.py:256-258`:
  `_per_100(0.55, "ap", "target_max_hp")` -> factor 0.000055; at AP=200,
  target_max_hp=2500 -> 0.000055 * 200 * 2500 = 27.5 (the AP part = 1.1% of 2500).

- **Kai'Sa fold math (for the Kai'Sa pin), from the design-framework spec**
  `docs/specs/2026-07-16-ds-onhit-ap-combined-dps-scorer-design.md:102-107`:
  `to_damage_block` folds `field + per_stack.field * assumed_stacks`
  element-wise. So the Kai'Sa synthetic block carries base
  `lerp(4,24)@L + lerp(1,6)@L * 2.0` and `ap_pct = 12.0 + 3.0 * 2.0 = 18.0`.

- **Design framework to reuse:** the Slice B design spec
  `docs/specs/2026-07-16-ds-onhit-ap-combined-dps-scorer-design.md` (added by
  commit 571c59ba) - its section 5.2 (lines 93-109) is the exact AA-routing
  precedent (Gwen added to `_AA_ROUTED_ON_HIT_KEYS`; `aa_routed_on_hit_entry`
  routes the P-slot on-hit onto the AA cadence, "byte-identical mechanism to
  Warwick/Orianna").

---

## SCOPE

1. **Route Kai'Sa P (the ENGINE delta).** Add `("Kaisa","P",0)` to
   `_AA_ROUTED_ON_HIT_KEYS` (`_passive_damage_overrides.py:1103-1111`) with an
   inline comment mirroring the Gwen line at :1107. This makes Kai'Sa P Caustic
   Wounds route-reachable on the AA cadence via the existing
   `aa_routed_on_hit_entry` -> `dps.py:1183` consumer. NO new schema field, NO
   dataclass change, NO evaluator change - the block and the consumer both
   already exist.

2. **ENGINE bump** 1.216.0 -> 1.217.0 (quoted-literal replace only,
   `agents/daemon_slayer/__init__.py:18`) + prepend ONE new changelog line to
   `docs/DAEMON_SLAYER.md` (newest-first) recording: 248/1.80.0 seeded Gwen
   bilinear + 249/1.81.0 seeded Kai'Sa per-stack, Slice B/1.216.0 routed Gwen,
   this bump routes Kai'Sa (route-reachable, default byte-identical, flip
   operator-gated). This new line is what "refreshes" the DS.md:71 marker (the
   old line stays immutable, per the changelog rule).

3. **Refresh the editable stale marker** at `_passive_damage_overrides.py:499-502`
   to state Gwen + Kai'Sa are SEEDED (items 248/249) and Gwen is routed (Slice B)
   / Kai'Sa is now routed (this slice), NOT "STAGED".

4. **TDD RED-first tests** (per-champion, not generic shapes) - see ACCEPTANCE.

## NON-SCOPE (do NOT do; each is a deliberate deferral or a shipped fact)

- **Do NOT re-derive or change the Gwen P bilinear term.** It is shipped and
  correct (`_per_100(0.55, "ap", "target_max_hp")`, line 602). Pin it, do not
  touch it.
- **Do NOT re-derive or change Kai'Sa's `assumed_stacks=2.0`.** It is shipped and
  correct (line 681). Pin it, do not re-tune it in this slice.
- **Do NOT flip the Kai'Sa live default to ON.** Enabling
  `apply_passive_damage=True` for Kai'Sa in a live scorer re-ranks her build and
  requires a live in-game re-rank check (the item-278 stack-consume-cadence
  discipline). Kai'Sa Caustic Wounds is a stack-build-then-consume mechanic, the
  same class item 278 deliberately kept out of v1 auto-routing. The flip is
  Phase-D / operator + live-gated, tracked to `docs/LIVE_GAME_GATED_SYNC.md`.
  This slice makes it route-REACHABLE only, byte-identical for every live path.
- **Do NOT add Kai'Sa to `core/ds_onhit_ap_roster.json`.** She is an AD marksman,
  not an AP on-hit champ; the on-hit AP scorer is the wrong home. Routing !=
  roster membership.
- **Do NOT model the Kai'Sa 5th-stack-consume missing-HP sub-term** (15% + 6% per
  100 AP of MISSING health). It is a documented reject
  (`_passive_damage_overrides.py:670-676`): the single-entry-per-(champ,key,form)
  registry cannot carry a per-TERM conditional gate without wrongly gating the
  unconditional ramp too; it needs per-term gating or a multi-entry lift (a
  separate future slice), and it is inert at the full-HP default context anyway.
- No new scorer, no roster expansion, no coach/dispatcher wiring beyond the
  allowlist entry.

---

## DESIGN DECISIONS PRE-ANSWERED

### D1 - Gwen P bilinear term shape: ALREADY SHIPPED (confirm + pin, do not build)

The concrete "AP x target-max-HP interaction" term the task asks to propose is
already in the tree and correct:

```
("Gwen","P",0): PassiveDamageEntry(
    base=(0.0,),
    target_max_hp_pct=1.0,                                  # 1% max HP flat
    bilinear_terms=(_per_100(0.55, "ap", "target_max_hp"),),# + 0.55% per 100 AP
    damage_type="MAGIC", cadence="on_hit", ...)
```

A `_per_100(pct, per_attr, of_attr)` bilinear term evaluates as
`(pct/10000) * ctx[per_attr] * ctx[of_attr]` (docstring
`_passive_damage_overrides.py:249-258`). Verbatim ability: A Thousand Cuts on-hit
"1% (+ 0.55% per 100 AP) of the target's maximum health" bonus magic.

Pre-computed regression anchor (execution session recomputes from the shipped
coefficients, not from this text - self-checking): at AP=200,
target_max_hp=2500, the pre-mitigation per-hit magic = 1% * 2500 + (0.000055 *
200 * 2500) = 25.0 + 27.5 = **52.5**.

DECISION: keep as-is; add a per-champion characterization test that pins the
evaluated value through the canonical `to_damage_block` + `_evaluate_block` +
`AbilityContext` path (see AC-1). Rationale: this locks the shipped decision so a
future bilinear refactor cannot silently drift Gwen.

### D2 - Kai'Sa P stack-count default: ALREADY SHIPPED = 2.0 (confirm + pin)

The recommended stack count is `assumed_stacks = 2.0`, already shipped
(`_passive_damage_overrides.py:681`). Rationale, grounded in the verbatim
mechanic documented at lines 662-670 (Riot Data Dragon / Meraki 16.14.1, no
external probe needed - the ability text is in-repo):

- Caustic Wounds caps at 5 Plasma stacks; the 5th application CONSUMES them all,
  so stacks present "before application" cycle through 0, 1, 2, 3, 4.
- The steady-state cycle-average over that 0..4 ramp = mean(0,1,2,3,4) = **2.0**.
- The per-stack coefficients themselves are EXACT from the ability text
  (`+ 1:6 per level + 3% AP per stack`); only the multiplier is the steady-state
  assumption, and 2.0 is the mathematically-correct ramp-average, not a guess.

The value is carried as a named, operator-tunable entry field (`assumed_stacks`),
NOT a magic literal buried in the evaluator - a future live consumer can feed the
real observed count. DECISION: keep 2.0; do not re-tune. Add a per-champion pin
(AC-2) asserting the folded block matches `12% + 3%*2 = 18%` AP and the
`base + per_stack*2` fold, so any future re-tune is a deliberate, test-visible
change.

### D3 - the genuine open decision: how to route Kai'Sa P live

Route Kai'Sa P via the SAME seam Gwen uses: add `("Kaisa","P",0)` to
`_AA_ROUTED_ON_HIT_KEYS`. Consequences, all verified:

- BYTE-IDENTICAL for every live path: `apply_passive_damage` defaults False on
  `compute_dps`; only the on-hit scorer sets it True, and only for on-hit-roster
  champs (Gwen/Kayle/KogMaw) - Kai'Sa is not on the roster, so no live scorer
  enables it for her. The marksman/sustained scorer that DOES rank Kai'Sa keeps
  `apply_passive_damage=False`.
- ROUTE-REACHABLE: an explicit `compute_dps(champion="Kaisa",
  apply_passive_damage=True)` (or a `/dps` body param) now injects the
  cycle-averaged Caustic Wounds per hit, evaluated through the canonical block
  path - previously it injected nothing (no allowlist entry).
- The default-ON flip stays operator/live-gated (D-tier), exactly mirroring the
  item-247/288 "wired + route-reachable + byte-identical; flip stays gated"
  precedent. This respects the item-278 rule that a stack-consume cadence needs a
  live re-rank check before it fires by default.

DECISION: add the allowlist entry (1 line + comment). Do not enable it live.
Primary value of this slice is truth-in-docs + regression-locking the shipped
D1/D2 decisions; the Kai'Sa route-reachability is the modest ENGINE delta that
carries the bump.

---

## TESTABLE ACCEPTANCE CRITERIA (TDD RED-first)

Write these tests FIRST and watch them fail (RED) before touching production
code, per the TDD-first project rule. Per-champion assertions, not generic
shapes. New file `agents/daemon_slayer/tests/test_passive_damage_staged_route_leap02.py`
for AC-1/AC-2/AC-4; extend `tests/test_passive_damage_aa_cadence.py` for AC-3.

- **AC-1 (Gwen bilinear pin, per-champion).**
  `test_gwen_p_bilinear_evaluates_max_hp_plus_ap`: build the `("Gwen","P",0)`
  entry's `to_damage_block`, evaluate through `_evaluate_block` with an
  `AbilityContext` at AP=200 and target_max_hp=2500; assert the pre-mitigation
  magic == 52.5 (= 25.0 flat + 27.5 AP-on-HP). RED today only if the term were
  removed/changed; GREEN confirms the shipped bilinear is locked. This test is
  behavior-locking (Gwen needs no code change).

- **AC-2 (Kai'Sa per-stack fold pin, per-champion).**
  `test_kaisa_p_per_stack_folds_assumed_two_stacks`: evaluate the
  `("Kaisa","P",0)` block at level 18, AP=200; assert the folded `ap_pct == 18.0`
  (12 + 3*2) AND the folded flat base == `24 + 6*2 = 36`, giving pre-mitigation
  magic 36 + 0.18*200 = 72.0. Assert a level-1 point too (base 4 + 1*2 = 6,
  ap_pct 18) to pin the per-level fold. Pins `assumed_stacks=2.0` and the exact
  coefficients.

- **AC-3 (Kai'Sa route-reachability + default byte-identity).** In
  `tests/test_passive_damage_aa_cadence.py`:
  `test_kaisa_p_now_aa_routed`: `assertIn(("Kaisa","P",0),
  _AA_ROUTED_ON_HIT_KEYS)` and `aa_routed_on_hit_entry("Kaisa")` returns the
  `(key, entry)` (cadence == "on_hit"). RED today (Kai'Sa absent), GREEN after
  the allowlist add.
  `test_kaisa_default_dps_byte_identical`: `compute_dps(champion="Kaisa", ...)`
  with default args == the same call captured BEFORE the change (default
  `apply_passive_damage=False` injects nothing). Proves the live path is
  untouched.
  `test_kaisa_apply_passive_damage_injects`: the SAME call with
  `apply_passive_damage=True` now has strictly higher `per_attack_on_hit_damage`
  / steady DPS than the default (the Caustic Wounds per hit is credited).

- **AC-4 (no live re-rank regression).** A guard test that the marksman/sustained
  scorer's Kai'Sa item ranking (the live path, default flags) is unchanged vs a
  pre-change capture - the allowlist add must not perturb any default ranking.

- **AC-5 (suite parity).** Full DS-dir suite + full `tests/` suite green save the
  3 KNOWN-pre-existing unrelated fails documented in LEDGER 910/911
  (`test_coach_poll_offload_hot03` thread-timing x2 + `test_doc_size_budget`
  ROADMAP-over-budget). Report exact observed pass/fail counts from THIS run;
  never carry a prior or subagent count forward.

- **AC-6 (live proof).** After the DS `:8893` restart, a live probe shows the
  route is reachable and default-safe: a `/rank-onhit` or `/dps` call proves Gwen
  unchanged (control) and a Kai'Sa `apply_passive_damage=true` call injects while
  the default Kai'Sa call does not. `/health` reports ENGINE 1.217.0.

---

## R5 TIER = Tier-2

Schema-adjacent engine registry edit (`agents/daemon_slayer/*.py`) + ENGINE
bump. Full ritual required:

1. **`py_compile`** every edited `.py` before any restart (hard rule; silent
   crash under `pythonw.exe` otherwise).
2. **Full dual suite** run ONCE after ALL edits are finished (no mid-suite DS
   bounce): the DS-dir suite (`agents/daemon_slayer/tests/`) AND the top-level
   `tests/`. Trust the exit code + result file; re-run only if edited-since or the
   pipe glitched.
3. **ENGINE bump** `agents/daemon_slayer/__init__.py:18` 1.216.0 -> 1.217.0,
   quoted-literal replace ONLY (replace the `"1.216.0"` string; touch no other
   line). Prepend the new changelog line to `docs/DAEMON_SLAYER.md`.
4. **Deploy gate** regenerates the DS anchor pins as part of the bump (per the
   LEDGER 911 precedent: the Slice B bump wrote 136 anchor pins / 115 files
   byte-exact). Run the DS deploy/anchor-regen step the repo uses for a bump; do
   not hand-edit pins.
5. **Share mirror staged in the SAME commit.** The DS commit triggers the Share
   mirror sync (pre-commit hook / `ds_share_sync`); LEDGER 900/911 precedent:
   the hook writes ~456-460 files. Confirm `ds_share_sync --check` is green
   before push (mirror in-sync is a CI gate). [UNVERIFIED-SKIP: the literal Share
   mirror directory path did not resolve in 2 probes (`Share/daemon_slayer` and
   `Share/*/daemon_slayer/__init__.py` both empty) - rely on the repo's
   `ds_share_sync` tool + the commit hook rather than a hardcoded path; confirm
   the tool exists via `grep -rl ds_share_sync tools/` at execution start.]
6. **DS `:8893` restart** after the bump: confirm port 8893 is FREE first (a
   detached child can hold the port so the first `/Run` silently skips a
   port-bind), then `schtasks /End` + `/Run` `RC-DaemonSlayer` (it is NOT
   supervisor-watched). Then verify `/health` shows ENGINE 1.217.0 (AC-6).
7. **RC reload** is only needed if a live scorer routing changed; this slice does
   NOT change any live routing (Kai'Sa flip stays gated), so an RC restart is not
   required for behavior - but do confirm `/health` post-DS-restart.

---

## FILES TOUCHED (grep-verified)

Production:
- `agents/daemon_slayer/_passive_damage_overrides.py` - add `("Kaisa","P",0)` to
  `_AA_ROUTED_ON_HIT_KEYS` (line ~1107 block) + fix the stale inline comment
  (lines 499-502). NO dataclass / evaluator change.
- `agents/daemon_slayer/__init__.py` - ENGINE_VERSION literal bump (line 18).
- `docs/DAEMON_SLAYER.md` - prepend ONE new changelog line (newest-first; do NOT
  edit the immutable line 71).

Tests:
- `agents/daemon_slayer/tests/test_passive_damage_staged_route_leap02.py` - NEW
  (AC-1, AC-2, AC-4).
- `agents/daemon_slayer/tests/test_passive_damage_aa_cadence.py` - EXTEND (AC-3).

Auto-generated by the deploy gate (do not hand-edit): DS anchor-pin files + the
Share mirror tree (`ds_share_sync` output). Optional tidy:
`agents/daemon_slayer/tests/test_onhit_dps.py:65` stale comment.

Consumer confirmed to need NO edit: `agents/daemon_slayer/dps.py:1177,1183`
already reads `_AA_ROUTED_ON_HIT_KEYS` via `aa_routed_on_hit_entry` at any slot.

---

## DONE RITUAL

1. Full dual suite green (AC-5), exact observed counts reported from this run.
2. `ds_share_sync --check` green; mirror staged in the feature commit.
3. Commit (use `git commit -F <tmpfile>`, ASCII-only, no banned glyphs; the
   precommit gate blocks banned glyphs + net-new ruff). Push.
4. DS `:8893` restarted; `/health` = ENGINE 1.217.0; live probe (AC-6) captured.
5. Append the per-item completion entry to `docs/LEDGER.md` (NEWEST-first, next
   integer id; NEVER to CLAUDE.md). Record: both entries were already seeded
   (248/1.80.0 Gwen bilinear, 249/1.81.0 Kai'Sa per-stack), Gwen already routed
   (911), this slice routed Kai'Sa route-reachable + refreshed the stale markers
   + pinned both. Note the Kai'Sa live-flip is operator/live-gated ->
   `docs/LIVE_GAME_GATED_SYNC.md`.
6. Update `docs/LIVE_GAME_GATED_SYNC.md` with the Kai'Sa live-flip re-rank-check
   item.

---

## GHOST LIST (do NOT touch / do NOT re-litigate)

- **Lux / Ziggs / Akali / Kha'Zix inert on-hit rows are NOT this slice**
  (`docs/DAEMON_SLAYER.md:65`, item 278 / ENGINE 1.100.0): mark-consume (Lux),
  internal-CD (Ziggs), empowered-first-hit (Akali/Kha'Zix) stay UNROUTED - their
  cadence is not every-AA and needs structured-cadence + a live re-rank. Leave
  them inert; they are a separate future slice.
- **AurelionSol W cross-spell seam stays STAGED** (`docs/DAEMON_SLAYER.md:72`,
  item 246 / ENGINE 1.77.0): deferred cross-spell amp, out of scope here.
- **Do NOT re-credit Navori 6675 Bring-It-Down** - it is guard-locked; do not add
  or re-enable any Navori damage credit.
- **NEVER `--force` a Meraki re-extract** - the `latest` endpoint is mutable;
  a forced re-extract corrupts the frozen content snapshot (CLAUDE.md Settled +
  ENGINE 1.108.0 content-freshness guard).
- **Dataclass fields append-at-END-with-default.** This slice adds NO dataclass
  field; if you find yourself editing `PassiveDamageEntry` / `PerStackTerm`, STOP
  - the schema already carries everything needed. If a field ever is added,
  append it at the end with a default (a mid-class required field broke 41
  constructions in item 216).
- **No mid-suite DS bounce.** Finish ALL edits (allowlist + version + comment +
  tests), THEN run the suite once. A DS `:8893` bounce mid-suite produces false
  anchor-mismatch / live-integration failures that cost a re-run.
- **No em-dashes or en-dashes, ever. 7-bit ASCII only** in all authored content
  (code, comments, `.md`, commit message, LEDGER entry). Use ` - ` for a clause
  break. Smart quotes banned too.
