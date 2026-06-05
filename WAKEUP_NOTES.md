# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-05 - DS anti-tank %HP/shred scorer - 16th axis (item 308) [headless-upgrade autonomous run]

Operator fired `/headless-upgrade` via the new desktop launcher (no explicit task); the autonomous run shipped the next DS axis. Commits `56fcb3d3` (axis) + `7901712a` (launcher). ENGINE 1.116.0 -> 1.117.0; DS :8893 restarted taskkill pid 18796 -> 1.117.0 live-verified. Full record = item 308 in `docs/LEDGER.md`.

- **NEW `agents/daemon_slayer/antitank.py` + `/anti-tank` route (POST+GET).** Per-(champ,source,kind) registry; `antitank_score` = sum(kind_weight [MAX_HP 1.0 / SHRED 0.85 / CURRENT_HP 0.75 / PERCENT_PEN 0.65] * cadence_mult [SUSTAINED 1.0 / PERIODIC 0.8 / BURST 0.65] * magnitude), 0.5 conditional midpoint; `top_kind` + `shreds_resist` flag (any SHRED/PERCENT_PEN). PURELY ADDITIVE (byte-identical to every existing route). SELECTIVE (flat-damage champs 0.0). **%-missing-HP executes EXCLUDED as finishers** (weakest vs a full tank). **Dual-kind-per-slot** (Trundle R = %max-HP + resist steal; Vi W / Yorick E / Sion E = %HP + shred).
- **Fan-out:** 171-champ Workflow (8 classify + 4 critics, 1.09M tok / 192 tool uses / 457s) -> 102 entries / 78 champs / 38 conditional. Live: Rumble 1.42 / KSante 1.24 / Sion 1.21 / Trundle 0.99 / Vayne 0.95 / KogMaw 0.93 top; MasterYi/Annie/Talon/Lux/Soraka 0.0. + `tools/ds_antitank_build.py` ((champ,source,kind) dedup) + notes sidecar (Share-excluded).
- +32 tests `test_antitank_item308.py`; DS suite 6579 passed; ruff clean; 61 ENGINE pin syncs; Share re-sync 311 files --check 0; CHANGELOG +1.117.0; ROADMAP relocated item 303 -> `docs/ROADMAP_HISTORY.md` (80KB budget).
- **ALSO shipped (commit `7901712a`):** idempotent one-click headless-upgrade desktop launcher (`tools/rc_headless_launcher.ps1` + `install_headless_launcher_shortcut.ps1` -> Desktop `RC Headless.lnk`). Per click: runs RC-GeminiAudit (schtasks /Run) + AHK-sends `/headless-upgrade` into the Claude desktop window, lock-guarded against double-injection (self-heals when claude.exe absent / lock stale). Operator config: Claude via AHK desktop-send, Gemini always-run-now.
- **Don't-redo:** %-missing-HP executes are excluded by design (do NOT re-add Garen R / Akali R as anti-tank); regenerate the registry via `tools/ds_antitank_build.py` (marker-spliced, do not hand-edit); dual-kind-per-slot is intentional. The anti-tank axis is EXHAUSTED across the roster.
- **NEXT (Phase D, live-gated):** an auto-pairing consumer crediting anti-tank into a live draft / teamfight / itemization verdict (buy %HP/shred vs an enemy tank line); tune the kind weights + cadence mults after a live re-rank.

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
