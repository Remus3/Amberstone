# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-17 - DSP5 summoner-spell seam: NEW summoners.py (headless gemini-loop cycle 7)

- Executor cycle 7 of the DS permutation swarm (`ops/loop`, gemini director). Directive = DSP5 (summoner-spell seam, NEW `agents/daemon_slayer/summoners.py`). Commits `790b0236` (code + ENGINE bump + Share + CHANGELOGs + LIVE_GAME_GATED) + `f9929bbf` (living docs) + `9845586f` (ROADMAP <80KB trim) pushed.
- ROOT: RC had ZERO summoner-spell layer (the `summoner combat set` permutation bucket was unmodeled).
- FIX (Tier-2, ENGINE 1.130.0 -> 1.131.0): NEW `summoners.py` - a self-contained `SUMMONER_SPELLS` registry (the rune_procs-at-birth precedent), one pure level-scaled closure per spell, modeled on its scoring axis: Ignite 14 antiheal_true (70-525 true DoT + 0.40 Grievous Wounds), Exhaust 3 incoming_dr (0.35), Heal 7 ehp_heal (80-346 + 0.30 MS), Barrier 21 ehp_shield (100-502.35), Cleanse 1 cc_discount (0.75 tenacity; QSS analog), Ghost 6 move_speed (0.24-0.5082). Public surface fail-soft (unknown id / bad level -> 0.0).
- MAGNITUDES: DDragon + CDragon 16.12.1 ZERO summoner magnitudes (prose-only, like stripped item passives - verified by fetching both); every coefficient is LoL-wiki-cited (`reference_lol_wiki_access`) per spell in the `formula` string. The wiki is the live patch (post-16.12.1) so the flip re-anchors at flip; DEFAULT-OFF means zero live impact this revision.
- DEFAULT-OFF: `SUMMONER_SEAM_IDS` marks the 6 ids but NO live scorer consumes the module -> `/rank` byte-identical. Live flip (wire a fight_report/matchup/coach consumer) EXCLUDED -> `LIVE_GAME_GATED_SYNC.md` section B.
- DS :8893 bounced (taskkill 6560 + schtasks) -> 1.131.0; Share re-synced (347, --check green); DS+Share CHANGELOG prepended + Share/docs/02 function-ref subsection; 78 ENGINE pins / 70 .py bumped (quoted-literal-only). TDD +24 red->green. DS-dir 7206 / RC 8281 / 3 hygiene gates 12 green; ruff/py_compile/ASCII clean. INLINE (R9), verifier SKIPPED per R7 (fresh in-thread dual re-verify + live :8893 + Share --check). External wiki fetch = S7b data-anchor (not S4 budget).
- POST-PUSH FIX: the swarm-progress prepend tipped ROADMAP to 82309 > 81920 (`test_doc_size_budget` ROADMAP_MAX) -> trimmed DSP1-3 detail to a LEDGER pointer (`9845586f`), now 81724. Lesson: run `tests/test_doc_size_budget.py` before committing a swarm-progress prepend.
- NEXT: DSP6 (enemy-rune threat seam, NEW; default-OFF). Tracker `docs/ORCHESTRATION_PLAN.md`.

---

# 2026-06-17 - DSP4 REGRESS directive: 1 real fix + 1 false positive (headless gemini-loop cycle 6)

- Executor cycle 6 (`ops/loop`, gemini director). Gemini AUDITOR returned REGRESS on item-468 DSP4 with 2 items; BOTH verified vs ground truth FIRST (S7 + the item-466 auditor-false-positive precedent).
- (1) REAL - `burst.py` rune-procs note: gated on `if _scored_runes:` (post-filter), so `runes=[8401]` default-OFF swallowed the "rune procs +0.0 (0 known rune(s))" note; the pre-DSP4 engine fired it for any supplied rune set (8401 then unknown -> `_n=0`). Broke the burst.py docstring byte-identical contract. FIX: gate on `if runes:`, keep `_n` over `_scored_runes`. SCORING + totals unchanged; live `/rank` (runes=None) unaffected. NO ENGINE bump (notes-string only).
- (2) FALSE POSITIVE - `frozenset[int]` "import crash on Py<3.9": refuted (`from __future__ import annotations` line 42 = lazy string; Python 3.14; `import rune_procs` -> `IMPORT_OK [8401] frozenset 20`). No change made.
- Sibling sweep: `combo.py` gates its rune note on `if rune_proc > 0.0:` (damage value) -> already byte-identical, no change.
- TDD: +2 subtests (notes byte-identical for `runes=[8401]`; `runes=None` emits no note) red->green. DS 7182 passed / 1942 subtests; RC 8281 passed; 0 regressions. ruff/py_compile/ASCII clean. Share re-synced (`--check` green). Commit `d5868799`; this living-docs commit follows.
- NEXT: DSP5 summoner-spell seam (NEW `agents/daemon_slayer/summoners.py`, default-OFF).

---

# 2026-06-17 - DSP4 self-rune completion seam: Shield Bash 8401 (headless gemini-loop cycle 5)

- Executor cycle 5 of the DS permutation swarm (`ops/loop`, gemini director). Directive = DSP4 (self-rune completion). Commit `1f7dbe62` (code+Share+CHANGELOGs+LIVE_GAME_GATED) pushed; this living-docs commit follows.
- ROOT (catalog sweep): DDragon 16.12.1 `runesReforged.json` has 62 runes; 19 were modeled, 42 unmodeled. Exactly ONE LIVE, pickable, direct-champion-damage proc was still missing -> Shield Bash 8401 (Resolve).
- FIX (Tier-2, ENGINE 1.129.0 -> 1.130.0): add 8401 to `RUNE_PROCS` (on_proc_burst, shield_gated, cd 0): `compute = 5-30 by level + 0.025*bonus_hp + 0.15*shield_amount` (longDesc-verbatim; "adaptive" = damage TYPE, no AD/AP). NEW `shield_amount` kwarg. Registry 19 -> 20.
- SEAM (DEFAULT-OFF, byte-identical off): NEW `COMPLETION_RUNE_IDS={8401}` + `score_completion_runes` on `compute_burst_damage` + `compute_combo` (default False -> completion runes SKIPPED). Burst scores the shield-independent 5-30 + 2.5% bonus-HP floor (no live shield signal); `shield_amount` forward-compat. Live flip EXCLUDED -> `LIVE_GAME_GATED_SYNC.md` section B.
- `core/rune_wpa.py`: each WPA row gains `proc_modeled` (fail-soft RUNE_PROCS-keys import, additive; panel-DOM subset test stays green) - cross-links the empirical WPA lens with the mechanical proc model.
- COVERAGE: 42 other unmodeled runes are honest exclusions (stat-grants Waterwalking/Jack burst-neutral, ult-amp Axiom Arcanist, legacy Deathfire Touch, non-damage utility) - documented in-module + both CHANGELOGs.
- DS :8893 bounced (taskkill 8076 + schtasks) -> 1.130.0; Share re-synced (345, --check green); DS+Share CHANGELOG prepended; 2 new DS test mirrors staged. TDD +27 subtests; 2 registry-shape pins 19->20; 77 ENGINE pins bumped. DS-dir 7177 / RC 8281 green; ruff clean. INLINE (R9 - one coupled seam), verifier SKIPPED per R7 (fresh in-thread dual re-verify).
- DON'T REDO: DSP4 is DONE. The adaptive stat-grant runes (Waterwalking/Jack/Eyeball-class) are burst-neutral (proc_type adaptive is skipped by the burst consumer) -> modeling them is fight_report-cosmetic only, LOW value, do NOT bump ENGINE for them absent a surfacing need.
- NEXT: DSP5 (summoner-spell seam, NEW `agents/daemon_slayer/summoners.py`). Tracker `docs/ORCHESTRATION_PLAN.md`.
