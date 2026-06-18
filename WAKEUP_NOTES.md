# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-18 - Aggregator H R1 lift: win-rate-by-game-length Build Insights tab

Gemini DIRECTOR REFILL cycle (round-2 RF queue drained -> director synthesized R1: a
Section-7b heavyweight competitor deep-dive). Target = Aggregator H (not-yet-reviewed).
RC supersedes most of it; the one genuine gap shipped in-run.

- **SHIPPED F1 win-rate-by-game-length** (commit `e9f70e7d`): `core/duration_winrate.py`
  -> `/api/duration-winrate` -> Build Insights "Game Length" tab. Win % bucketed by match
  duration over the operator's OWN rewind corpus (no global / Riot / Claude dep, no DS
  schema change). Tier-1, no engine/DS/frozen. TDD +8; full RC suite 8349 passed exit 0;
  RC restarted pid 11712 (endpoint live; bogus mode -> 400).
- **VERIFY-GATE catch:** `matches.game_duration_s` has 4 ms-encoded/corrupt rows
  (MAX=1988073, clean 3600-100000s zero gap); MAX_DURATION_S=7200 + MIN_DURATION_S=300
  drop them. Live: ARAM n=2044 downward slope 56.2/51.1/49.4/48.2 (snowball tendency),
  SR n=683 peak 30-35m 60.2.
- **OWED (carry-forward):** live visual capture of the Game Length tab (Game-PC :8892 down +
  Claude_Preview cannot attach to RC-owned :8888 headless). Code-side 5-phase UI audit PASS,
  no MUST-FIX (1 SHOULD-FIX deferred: shared Min-buys control inert on the chart tab). Drive
  `?ui_mock=1#build-insights` -> Game Length tab when a visual path is available.
- Triage: F2 global win/pick/ban + F6 lobby-player-tags + F7 global objective/tier = FUTURE
  (new external dep; F6 already BACKLOG as Overlay App F 3.1); F3/F4/F5 CLOSED (RC at-parity or
  superior). Doc `docs/COMPETITOR_LIFT_2026-06-18.md`.

---

# 2026-06-17 - live-game-gated sync: ARAM Mayhem validation pass (operator playing live)

Operator played 6 ARAM Mayhem games while I ran the LIVE_GAME_GATED_SYNC checklist in sync. Docs-only
session (no code/engine touch); commit captures sync-doc ledger + WAKEUP. Champs: Olaf, Sivir,
Senna->Mundo, Lissandra, Vex->Quinn, Caitlyn. Tooling: a persistent champ-select catcher (Monitor
polling lcu.phase, emits on ChampSelect-enter - ARAM CS is too fast for a from-ReadyCheck poll) +
per-champ `ops/audit/ds_perm_swarm/live_flip_eyeball.py` OFF-vs-ON re-rank + dashboard screenshots.

- **DSP11 kit-axis = LIVE-VALIDATED, FLIP-READY** (Senna lethality +Black Cleaver; Quinn crit
  +IE/Collector/Statikk; Caitlyn non-tabled control = byte-identical). Seam correctly scoped. The
  actual flip (wire scorer + DS :8893 restart) is still operator-gated - do NOT flip blind.
- **Comp-verdict renders correctly** on SWAP + STAY branches; build-chooser/bench-swap/MAYHEM all
  render live. VARIANT branch still unobserved.
- **OPEN BUG - section A LCU push FAIL:** RuneWriter (`lcu/lcu_rune_writer.py`) pushes runes ONLY on
  the first champ-select per RC session, silent after. Memory `reference_runewriter_dies_after_game1`.
  Fix post-session (needs RC restart). NOT frozen.
- **Low-conf flag:** comp-verdict Vex(AP)->Garen(AD) reasoning reads inverted; check `core/aram_comp_verdict.py`.

NEXT: (1) fix RuneWriter re-arm bug. (2) tabled half still un-validated for RF1/RF2/RF3+RF6/DSP3 +
DSP11-manamune - needs one of those champs to roll (RF1 bruiser / Rakan / KSante|Rell / Cluster-A /
Ezreal|Corki). Full detail in `docs/LIVE_GAME_GATED_SYNC.md` LGS2 ledger entry.

---

# 2026-06-17 - verify + fix Antigravity repo-audit batch; ratify D5 frozen extraction (operator-directed)

Antigravity implemented the `repo-audit.md` D-items; operator asked to verify + fix + flip gated items. Commits `a13d7496` (38 files) + `d16200b3` (ci.yml, separate workflow-scope push). Both pushed, CI green, RC redeployed pid 9012.

- **CI-breaker FIXED:** Antigravity put `BLE001` in `ruff.toml` select with NO baseline -> `ruff check .` 1137 errors -> CI red. Reverted that line (ratchet deferred to a `--add-noqa` pass).
- **Hot-path FIXED:** D4 narrowed `snapshot_normalizer.py` catches to a 5-type tuple (dropped IndexError/ZeroDivisionError on live data). Back to `except Exception as exc:`, kept the new `_log.debug`.
- **D9 completed:** token header was on 2/4 guarded endpoints; added to dev.js (/api/loop-control) + screen_read.js (/api/command).
- **D12 reverted:** print->logger on interactive result CLIs (daemon_slayer/cli.py, config_validator.py, adaptation_hint_cli.py, aftergame_summary.py) hid stdout; restored result->print, kept status->logger.
- **D5 RATIFIED:** frozen `app/_game_lifecycle.py` map extracted to `core/coach_registry.py`. Verified-good as-shipped: D2 D3 D6 D8 D10 D13 D14. Deleted 7 scratch `scripts/fix_*/patch_*.py`; kept install_hooks.py.

NEXT (OPEN, do NOT re-pitch the reverted changes as bugs): **D1** Share de-dup NOT done (only a local pre-commit auto-sync hook; it re-stamps `Share/MANIFEST.md` every commit). **D4 ruff ratchet** + **D9 200/401 test** + **D11 assert->raise** deferred. Precompute scripts + vision_token.py kept print->logger (status, by choice). Memory [[feedback_verify_antigravity_audit_batch]].
