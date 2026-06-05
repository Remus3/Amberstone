# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-05 - DS ally-amp Phase D: peel-target live consumer (item 307)

Wired the item-304 ally-amplification axis into its FIRST live consumer. Commit `7066e0c0`. Non-DS / non-engine / non-frozen; RC NOT restarted (route loads on the next between-games restart). Operator: "continue next -> phase D : am playing games ranked SR"; one AskUserQuestion -> **peel-target (live)**.

- **NEW `GET /api/peel-priority`** (`dashboard/routes_peel_priority.py`, additive, single-sided): pairs the live/supplied ally roster vs `compute_allyamp` -> `ranked` + `protect_target` (top buff-throughput ally) + `hard_saves` (PROTECT/`saves_ally` champs) + `verdict`. ABSENT `ally` -> live auto-read; empty -> `no_champions`; no game -> `no_live_roster`. Registered in `_dispatch.py`. + `_liveclient.ally_team` (symmetric to `enemy_team`).
- **Bug caught + fixed in-slice:** Live Client emits DISPLAY names ("Tahm Kench"); DS registries key canonical ids ("TahmKench") -> silent 0.0 miss; **TahmKench is a PROTECT hard-save**. NEW `core/archetype_picks.canonical_champion_id` (data-driven, ddragon_champions.json) bridges it; `_live_ally_roster` canonicalizes. Memory `reference_liveclient_name_vs_ddragon_id`.
- **Live re-rank** (in-process, real SR game): Caitlyn + Nautilus/MasterYi/Katarina/Seraphine -> "Peel for Seraphine (SHIELD)"; weights SANE, no tuning.
- +24 peel tests; ruff + hygiene 12 + 134-slice regression green.
- **NEXT:** restart RC between games (`echo restart > restart_trigger.txt`) to serve the route; peel chip BLOCKED (Game-PC MCP down -> fixture ritual unavailable); remaining item-304 Phase D variants (team-balance chip, teamfight/draft).

---

# 2026-06-05 - lolmath Discord chat digest (DS robustness check; docs-only, no engine change)

Digested a lolmath community chat against RC's Daemon Slayer via a 3-agent fan-out. Commit `a1bb672f` (BACKLOG.md only, CI green). RC NOT touched. Operator was mid-game (SR InProgress) at wrap.

- **2 of 3 lolmath behaviors are STRUCTURALLY ABSENT in RC (do NOT re-investigate):** (1) "marksman preset on a no-autos mage" (Fiddlesticks -> pure-AP degeneration) cannot occur - RC routes mages to `ds.ability` via the DDragon-tag archetype dispatcher (`core/archetype_picks.py`); the carry/dps DPS=0 path is unreachable in prod (only a forced `archetype="carry"` on a mage hits it). (2) "1 R bundles 2 empowered autos" double-count cannot occur - `burst.py:803` sums ability-blocks + AA separately; the AA-empower (`apply_ability_amps`) + on-hit (`apply_passive_damage`) seams are default-off, AA-only, on disjoint champ sets; Udyr in neither.
- **3rd behavior (target HP% for %HP item procs) is a documented modeling CHOICE, not a bug.** RC models the 3 genuinely-%CURRENT-HP procs - BotRK 3153 (`_effects_data.py:546`), Hellfire Hatchet 4017 (`:2055`), Fulmination 443055 (`:2312`) - at full max-HP (each comment self-documents the `current~=max` steady-state). `CallContext` carries `target_max_hp` but no `target_current_hp_pct`, so the current-HP knob (honored by ability_dps/burst) is half-wired for item procs. Live coach passes a real max_hp (`archetype_dispatch.py:222`) so the over-credit is live but bounded (the /dps + /rank routes default `target_max_hp=0.0` -> procs zeroed unless an HP is supplied).
- **Logged to BACKLOG** (operator-gated tuning, NOT shipped): thread `target_current_hp_pct` (default 1.0 = byte-identical) into `CallContext` + the 3 current-HP procs; the FLIP (lolmath's 50% fight-average) is the product decision, re-ranks, owes an ENGINE bump. **CRITICAL for the implementer:** do NOT touch Eclipse 6692 / Titanic 3748 / Hullbreaker / Reaper's Toll 443090 - they are genuinely %MAX-HP (an investigating subagent made exactly this Eclipse error; the BACKLOG entry has the full classification).
- **NEXT:** none required; the BACKLOG entry is the spec if the operator wants the tuning.

---

# 2026-06-04 - pickban routes refactor (item 305) + Gemini read-only auditor sub-project (item 306)

Two non-DS slices, both shipped + pushed + CI green; RC NOT restarted (no engine/frozen touch). Full records = items 305 + 306 in `docs/LEDGER.md`.

- **dashboard/routes_pickban.py cleanup (item 305; branch refactor/pickban-routes ff-merged main `6b8cbd7f`).** 8 atomic commits C1-C8. C1+C2 (TDD, xfail-strict): `_serve_personal_record` now 400s on a malformed `?queue=` (parity with pickban-recs - was silently defaulting to the SR queue set). C3-C8 behavior-preserving: `_exclude_clause(col=)` removed `.replace` SQL surgery x4; merged 3 query twins (-> `_query_performance_band` / `_query_co_participant` / `_query_loss_matchups`); `_pct()` + named consts; shared handler scaffold flattened both HTTP handlers C901 12/9 -> <8. 1209->1172 LOC, 53->54 tests, verifier subagent CONFIRMED. Residual C901 (`_compose_cleanse_advisory` 15, `_load_champ_name_to_id` 9) deliberately deferred.
- **Gemini auditor (item 306, PROVISIONAL; commits `eaa1f0a1` `f3c54906` `14f95e06`).** gemini-cli 0.45.1 / gemini-3-pro-preview (paid) as a headless READ-ONLY critic. `tools/gemini_audit.ps1` (nightly RC-GeminiAudit 03:00 -> `docs/EXTERNAL_REVIEW_<date>.md`, gitignored), `gemini_ask.ps1` (in-session Q/A -> `gemini_io/`), `claude_send.ahk` (AHK v2 self-clear, dry-run default, NOT auto-wired), `GEMINI.md`, `.geminiignore`, `docs/GEMINI_AUDIT_CONFIG.md` + `GEMINI_REVIEW_CONSUMPTION.md`. Read-only via `--approval-mode plan`; Gemini never writes source (the runner captures its stdout). First review verified genuine. Memory: `project_gemini_auditor.md`.
- **Don't-redo:** pickban is DONE + merged - do NOT re-refactor. Gemini key is a PAID User-scope key (prefix AQ.A); model id is gemini-3-pro-preview (NOT "gemini-3-pro" - 404s); read it via registry not `$env`; free quota is shared with Antigravity. Gemini is PROVISIONAL. D2/D3 copy-paste blocks + AHK "go" wiring are operator-side.
- **NEXT:** triage the first nightly EXTERNAL_REVIEW (verify-before-trust + TDD-first); optional deferred 2 C901 fns; tune Gemini cadence/scope after a few reviews.
