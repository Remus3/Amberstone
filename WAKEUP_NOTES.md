# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-26 (L4 Phase-D capability-gap synthesizer - item 631, `d52d6152`, CI green)

First bet from the item-626 research report after the objective-state pack. Operator picked L4,
then the multi-axis-synthesizer slice. Grounding found the report's "first slice = anti-tank, it
is unconsumed" was WRONG: `core.ds_antitank_hint.build_antitank_hint` already exists + is consumed
(A3 axis in build_order_variants), and `routes_ds_profile.py` already does a single-champion radar.
So slice 1 = the genuinely-unbuilt SYNTHESIS.

- NEW `core/ds_capability_gap.py` `build_capability_gap(my_champ, enemies, mode)` - detector-registry
  consumer that reads existing DS scorers vs a live enemy comp, emits the single highest-severity
  capability DEFICIT. v1 detectors: **anti_tank** (delegates to build_antitank_hint) + **poke** (keys
  on `ThreatRangeResult.is_artillery`). Ranks by enemy-demand count, tie-break anti_tank>poke. Adding
  an axis = append a detector.
- Pure read-only, never raises, **default-inert** (NOT yet wired into a served path - awaits a live
  coach surface + shadow-log per flip discipline). No ENGINE bump, no Share mirror. Tier-1.
- RED-first; fixtures grounded vs live scorer output. GREEN: 17/17 new tests, ruff clean, sibling
  ds_antitank_hint 13/13.

NEXT: more detectors (sustain/zone/objdamage) + wire into a live coach surface behind a shadow flag.
Other untouched report bets: L9/L10 live championStats + stat-shard ingestion, E1 TFT det twin.
STILL UNVERIFIED (carried): no live SR-game validation of EITHER the 627-630 objective rows OR this
consumer - all client mode. Do NOT re-derive anti-tank or the ds-profile radar (both already exist).

---

# 2026-06-26 (OBJECTIVE-STATE COACHING PACK shipped end-to-end - items 627-630)

Built the whole pack queued by item 626, one slice per turn, RED-first TDD, commit+push each.
All zero-LLM deterministic folds over the BaronKill/DragonKill `objective_events` stream
(`dashboard/_liveclient.py:215`); all render via the kind-agnostic `web/js/panels/callouts.js`
with NO JS edit; all Tier-1, no engine/ENGINE/Share/flip.

- L1 (627, `1e07d91a`): `epic_buff_callouts` - sided Baron(180s)/Elder(150s) buff-expiry
  countdowns. Elder via an additive `dragon_type` field on the dragon event (name stays
  "dragon" so macro_response is byte-identical). Used ACCURATE per-monster durations, NOT the
  research doc's merged 180s.
- L2 (628, `cc41f14a`): `dragon_soul_callout` - 3-stack "SOUL next drake - force/deny" advisory.
  Wired into the `_deterministic_coaching` advisory chain at `advisory = macro or soul or heal`.
- L3 (629, `528926d5`): dynamic respawn fix (the served-path slice). `_objective_callouts` now
  uses last_kill+respawn (drake 300s / baron 360s) once a kill exists; baron gains a real
  respawn ETA; soul-secured suppresses the drake row. Cadence constants reconciled to ONE source
  (event_callouts owns `SR_{DRAGON,BARON}_{FIRST,RESPAWN}_S`; decision_detector imports them).
  No-kill path byte-identical (characterization-guarded).
- L2 follow-on (630, `e37eb405`): soul cascade extended - secured(4+) locked-element row +
  soul-race delta row. Honest test churn: 3 L2 tests updated (2-drake now a race row).

NEXT: optional bigger bets from the report - L4 Phase-D capability-scorer consumer, L9/L10 live
championStats + stat-shard ingestion, E1 TFT deterministic twin. No live-game validation done
(client mode all session); the pack is pure + fully unit-tested. Pre-existing anomaly (not mine):
RC-LiveFlipWatcher task Disabled/result=1.

---

# 2026-06-26 (orchestrated lift/expansion/UI-UX research [626] + queued objective-state pack)

Operator asked for a non-superficial orchestrated research pass. Ran a 4-phase Workflow
(`wf_7b49d885-771`, 48 agents): exclusion-ledger grounding -> 9 web+code scouts -> adversarial
verify -> synthesis. The whole point on THIS repo is filtering against the huge shipped/CLOSED
surface; built an exclusion ledger first and killed any re-pitch. 9 vectors -> 35 candidates ->
24 verified-novel survivors. Report: `docs/research/LIFT_EXPANSION_UIUX_2026-06-26.md`.

- Through-line: RC already reads-and-discards the data for most of its highest-value gaps.
- QUEUED (ROADMAP NOW, top, RED) - OBJECTIVE-STATE COACHING PACK = L1 buff-expiry timer +
  L2 dragon soul tracker + L3 dynamic respawn fix. All S-effort zero-LLM folds over the
  BaronKill/DragonKill stream RC parses at `dashboard/_liveclient.py:215` and discards. Tier-1
  additive callouts via the existing callouts.js, no engine/flip. Director picks ONE per cycle.
- Recovery note: the first run's Verify+Synthesis was wiped by a TRANSIENT server rate-limit
  (35 concurrent verifiers). Fixed by batching verify (6 agents) + `resumeFromRunId` (Ground+
  Scout returned cached). The run-id-resume + batched-fanout pattern is the durable fix.
- Docs-only Tier-0: commit `510c000c`, no code/engine/ENGINE/Share. RC untouched (DS 1.151.0).

NEXT: the director should pick L1 first (smallest, unambiguous BaronKill EventName). Bigger
FUTURE bets in the report: L4 Phase-D capability-scorer consumer, L9/L10 live championStats +
stat-shard ingestion, E1 TFT deterministic twin (north-star advance), E2 spatial timeline metrics.
