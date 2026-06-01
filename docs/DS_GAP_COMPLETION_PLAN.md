# Daemon Slayer - Gap1/Gap2 completion + refactor plan (next session, LIVE)

Authored 2026-05-31. Decisions captured via operator Q/A. Frame this purely by
technical substance. Next session is LIVE: the operator is present and plays
games, so per-flag default-on flips can be validated ("saner, not just
different") in a real game.

Source of the work items: `Share/docs/04_GAPS_AND_ROADMAP.md` +
`Share/docs/05_AUDIT_AND_REFACTOR.md` + CLAUDE item 239.

## Ground rules

- Refactors land BEFORE the amp/passive feature work (features must target the
  new structure, not the old).
- TDD: failing test first, then implement, full DS suite green before each
  commit, ENGINE_VERSION bump + test-pin sync + DS :8893 restart per the ritual
  (`reference_ds_server_not_supervisor_watched`), `/health` confirms the version.
- Every default-on flip needs live proof, per champ / mode / passive. What is
  not validated stays default-OFF + documented - that is a CORRECT handoff
  state, not an incomplete one.
- `Share/src` is a deterministic mirror (`tools/ds_share_sync.py`). Committing a
  `Share/` change auto-pushes the review gist via `.git/hooks/post-commit` ->
  `tools/gist_share_sync.py` (deterministic zip, no spurious pushes).

## Phase A - Refactors (structure first; green between each)

A1. `agents/daemon_slayer/__init__.py` changelog relocation -> a CHANGELOG file.
    Low-risk, isolated. Declutters the first module a reviewer opens.
A2. `ability_dps.py` 3-way split (doc 05 rec). This is the amp-seam home, so it
    MUST land before Phase C. Preserve public API; tests green.
A3. `cc_conditional.py` registry -> external data file (doc 05 rec). cc_pressure
    counts then derive from the data file (feeds B1).

## Phase B - Stale-doc + dead-code cleanup (on refactored structure)

B1. Fix the 4 stale docstrings:
    - `ability_hps.py:30` "nothing consumes it yet" -> it does (correct it).
    - `fight_report.py` "5 substrate modules" -> 7.
    - `cc_pressure.py` stale registry counts -> derive from the A3 data file.
    - any sibling stale count doc 05 lists.
B2. Delete dead `cli.py:204` `_cmd_not_implemented`.
B3. Rewrite `Share/docs/05_AUDIT_AND_REFACTOR.md` entries from "rec" -> "fixed"
    for everything landed in A + B.

## Phase C - Amp/passive feature work (default-OFF, byte-identical, on split ability_dps)

C1. Staged amps - block-index routing ONLY: Sion Q + Hwei Q f2. Reconcile the
    amp vs each form's own "Maximum ..." damage block (do not double-model);
    Hwei Q f2 also needs a missing-HP coefficient. AurelionSol W cross-spell
    seam is DEFERRED (its own session).
C2. AA-empowerment amp seam in `compute_dps`: Caitlyn W, Fiora E, Jayce W f1,
    Sivir W, Nidalee Q (base="aa", currently inert). Build the seam default-OFF.
C3. Gap2 exotic passive registry - author all 8 default-OFF (no re-rank): Aatrox
    P, JarvanIV P, Zed P, Gwen P, Caitlyn P Headshot, Kaisa P, Ekko P,
    Gangplank P. Bespoke per-passive modeling (%HP / crit-chance / per-stack /
    conditional / dot).
    Each: default-OFF byte-identical pins, ENGINE bump, green, DS restart.

## Phase D - Live validation + flag-flips (opportunistic; operator plays)

D1. Wire Gap2 cadence: on_hit passive damage -> the AUTO-ATTACK cadence (the
    default-on enabler for `apply_passive_damage`).
D2. As each champ/mode is played, validate "saner not just different" and flip
    the relevant flag default-on PER champ/mode/passive:
    - `apply_ability_amps` (Mordekaiser Q / Illaoi Q + C1 block-index entries)
    - `apply_passive_damage` (the 10 P-slot + C3 exotic, per-passive, after D1)
    - `apply_build_tenacity` + `score_by=cc_blended` (tank/bruiser EHP)
    - `apply_mode_modifiers` (validate IN that mode: URF / Arena / etc.)
    - `gate_ammo` (22 ammo champs)
    - `aoe_targets_hit`
    - C2 AA-empowerment amps (the 5 champs)
    Flip ONLY what is validated live; leave the rest default-OFF + documented.

## Phase E - Share re-sync + handoff polish

E1. Add a neutral README/doc line flagging the `lolmath` data-schema key
    (`champion["lolmath"]`, `scenarios_by_lolmath`) as an internal name for the
    rotation/ARAM scenario sub-object (decision: leave the key structural).
    Home: `Share/docs/03_DATA_AND_SOURCES.md` (+ optionally `Share/README.md`).
E2. `tools/ds_share_sync.py` regenerates `Share/src` + MANIFEST at the new
    ENGINE version. `tools/ds_share_sync.py --check` (CI drift guard) clean.
E3. Commit the `Share/` change -> `.git/hooks/post-commit` auto-pushes the gist.
    Verify the gist is current (`gh api gists/<id>` / open the link).
E4. CI green, /done.

## Completability

- Phases A, B, C, E are deterministic + headless-completable = the guaranteed
  spine of the session.
- Phase D is opportunistic (depends on which champs/modes get played). Flip what
  is validated; the rest stays honestly default-OFF.

## Out of scope (deferred)

- AurelionSol W cross-spell amp seam (its own session).
- Abstracting the `lolmath` data key (kept structural per decision).
- Sending the gist link (operator-gated; the agent does not send it).
