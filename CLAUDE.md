# Amberstone - Agent Context

Live League / TFT coaching dashboard. Reads Riot Live Client API, calls Claude Haiku for coaching and Sonnet for vision, writes JSON to `data/`, serves `:8888` HTTPS dashboard locally on Legion (1-PC since 2026-05-29; ADR-011). RC is tkinter-free (scheduler is asyncio AppLoop; 3 residual .after() files, all frozen app-core); Daemon Slayer (`:8860`) computes real DPS math per champion.

> **Living docs (read at session start):** `docs/ARCHITECTURE.md` - `docs/OPERATIONS.md` - `ROADMAP.md` - `docs/API.md`
> **Deep references:** `docs/DAEMON_SLAYER.md` (DS engine - 706 items / 173 champs - ENGINE_VERSION 1.281.0 (patch 16.18.1) - Arena mirrors credit their OWN DDragon stat line, not the SR twin's (R161 doctrine B) - but MEASURED 2026-09-01 (RM-323): DDragon carries NO proc MAGNITUDE for the burst mirrors, SR twins included (the <stats> block is base stats only), so for those the row's own `note` is the authority and doctrine B is NOT a licence to zero a mirror out - rune offense registry carries an attack-speed column (Legend: Alacrity 9104) plus a distinct-item-stat census (Jack Of All Trades 8316, dps.py apply_rune_offense_grants, parsed by /dps + /hybrid + /rank-bruiser, DEFAULT-OFF, zero for AS-locked champions) - all 7 archetype scorers wired (Slice B on-hit AP ds.onhit) + Term A ally-granted EHP (ehp.py score_by=team_blended, parsed by /rank-tank only, DEFAULT-OFF) + canonical cast-rate keys (ult_rates.py apply_canonical_cast_rate_keys, DEFAULT-OFF and NO HTTP route parses it - RM-333) + RM-39/RM-43 AD-axis ability term (hybrid.py apply_ad_axis_ability_damage, parsed by /rank + /rank-bruiser, NOT /hybrid, DEFAULT-OFF; L2 1.223.0 credits PHYSICAL+TRUE, MIXED held, MAGIC permanently excluded) + per-spell CC consumer + cc_blended_ehp ecosystem COMPLETE 4 consumers + per-spell CC wave 9 108/89 + cc_conditional ecosystem COMPLETE 5 consumers wave 6 36/32 + survivability axes heal/shield/DR/resist-grant COMPLETE across both EHP scorers incl flat + rank-scaled-block + percent-of-resist + unlabeled-multi-stat-block + form-occupancy + per-stack-unbounded modes + revive/second-life EHP-numerator multiplier Anivia/Zac) - `docs/AGENTS.md` (Phase 3 framework) - `BACKLOG.md` (aspirational)
> **Architectural decisions:** [`docs/adr/README.md`](docs/adr/README.md) (indexed, 12 live ADRs + ADR-001 retired + ADR-004 superseded by ADR-012) - before re-litigating a past choice, check here first.
> **Dated artifacts** in `docs/_archive/` (excluded from ripgrep searches).

## Topology

| Machine | Tailnet / IP | LAN IP | Role |
|---|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | `192.168.8.230` | 1-PC (2026-05-29, ADR-011): runs League + Vanguard + RC + supervisor + vision server + dashboard + OBS. Relocated agents run local as ONLOGON tasks: RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener. Tailscale node `legion-rc` / `100.70.22.55` is the ONLY canonical name for this box. **The Windows computer name is deliberately NOT recorded here - it is re-rolled from time to time, so any value written down goes stale** (this table has already carried two dead ones). Probe it live with `$env:COMPUTERNAME` on the rare occasion you need it, and never reconcile MagicDNS to it. Note `hostname` returns `LEGION-RC` (the DNS name, set separately), so it will NOT match the computer name and that is expected |
| **Peer** | `peer-host` / `<peer-tailnet-ip>` | - | A separate machine running a separate private project. The RC<->Peer cross-Claude bridge was decommissioned 2026-06-24 (ADR-012), so this row is history, not topology |

**Cross-repo channel with the sibling projects.** Their names and local paths are per-host CONFIG, not repo content: they live in gitignored `ops/moon_sync_repos.json` (see `ops/moon_sync_repos.example.json`; `RC_MOON_SYNC_REPOS` overrides), and `tools/moon_sync_poller.py` plus `tests/test_loop_concurrency.py` both read them from there. **Two spelling traps survive the move and are worth keeping in mind:** a sibling checkout path may contain a REAL SPACE while its GitHub repo name uses a hyphen (a repo name cannot hold a space), so the two spellings differ ON PURPOSE and neither is a typo; and any such path MUST be quoted, because an unquoted `-File C:\Some Sibling\tools\x.ps1` reads as `-File C:\Some` plus a stray positional and fails silently. The channel itself: gitignored `moon_sync_inbox/` in EACH repo root - you WRITE into the sibling's, you READ your own. Both sessions independently invented a different channel on 2026-07-26 before finding this one; do not invent a third. `ops/loop/slots.py` + `ops/loop/winmutex.py` are BYTE-IDENTICAL-BY-CONTRACT across the participating repos, pinned by `SHARED_SHA256` in `tests/test_loop_concurrency.py`. Re-pinning is a JOINT act: never regenerate the digests from local disk - both trees hashing equal IS the acceptance, not a note claiming it. Copy the sibling's file with a BYTE-level copy, never `write_text` (it turns LF into CRLF on Windows and the pin is on bytes). **Participants since 2026-09-06: RC plus two sibling checkouts (Sibling-A and Sibling-B); a third, Sibling-C, is archived and its working copy deleted, so it will never re-sync and its digest must not be chased.** The newest participant vendors last - it has no pin to break until it has one. `docs/CHANNEL.md` is the third BYTE-IDENTICAL-BY-CONTRACT artifact, pinned on LF-NORMALISED bytes by `CHANNEL_PIN` in `tests/test_channel_doc_pin.py`; re-pin is a five-way act.

Both in tailnet `tailc150de.ts.net` (Game-PC retired from the pipeline 2026-05-29, ADR-011). Prefer tailnet hostnames. Vision runs in-process at `127.0.0.1:8889`. The game host is config not code: `core/game_host.py` `RC_GAME_HOST` (default `127.0.0.1`) is where every live reader finds Live Client `:2999` + LCU.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **Always `py_compile` before restart.** Syntax errors crash silently under `pythonw.exe`.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Overlays poll mid-write.
- **Never `Stop-Process`.** Hangs MCP pipe. Use `taskkill /F /PID`.
- **Commit messages with special chars:** use `git commit -F <tmpfile>` (Write the file, ASCII-only) or a single-quoted here-string - never a double-quoted here-string or a piped string (BOM + ANSI-mangle risk, same root cause as the no-em-dash rule below). `tools/precommit_gate.py` (PreToolUse hook on `git commit` + PowerShell) is the backstop: it blocks banned glyphs + net-new ruff on staged lines.
- **Never add a `Co-Authored-By: Claude` trailer, and never file its absence as a defect.** `.githooks/commit-msg:23-29` STRIPS it per operator policy 2026-06-03 (deletion, not rejection, which is why it reads as an authoring omission; evidence: `docs/history_notes.md` 2026-09-16). Audit it with an ANCHORED predicate and read the message TAIL: a bare `grep -ci 'Co-Authored-By'` matches prose ABOUT the trailer.
- **Git hooks are the AUTHORITATIVE gate, and a fresh clone has NONE.** `core.hooksPath` is LOCAL config and is not cloned, so a new clone of this repo runs zero hooks until someone sets it - which defeats the tracked `.githooks/` dir entirely. **First action in any fresh clone: `python scripts/install_hooks.py`.** Claude PreToolUse hooks are defense in depth, NOT a substitute - but they do fire: **RE-MEASURED 2026-08-01 on CLI 2.1.220, SessionStart AND PreToolUse both fire under a headless `claude -p --permission-mode bypassPermissions`** (Bash provably run, both hooks recorded to a sentinel). This SUPERSEDES the 2026-07-26 "they do NOT survive headless" finding, which was confounded twice: it ran on CLI **2.1.205**, and its probe dir carries `hasTrustDialogAccepted: false` to this day. Hook findings are VERSION-SPECIFIC and expire - re-measure, never inherit. **Two confounds to eliminate before ever concluding a hook did not fire:** (1) a `settings.json` containing single-backslash Windows paths is INVALID JSON, so it never parses, no hook is registered, and nothing warns you - assert it parses before trusting a negative; (2) an untrusted workspace makes headless silently DISCARD `permissions.allow`, which presents almost identically to hooks not loading. The trust key in `~/.claude.json` is per path-STRING, so `C:\X`, `C:/X` and `C:/x` are three separate entries and headless reads the forward-slash one - each worktree path is its own key. Never treat a hook's PRESENCE as proof it fires; the only valid test is end-to-end (stage a banned glyph, attempt a real commit, assert HEAD unchanged). See memory `reference_git_hooks_authoritative_and_traps` for the ways a hook can be present and silently do nothing.
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts within ~5s).
- **`SCRIPT_DIR` in `app/__init__.py` MUST be `Path(__file__).parent.parent`** (package layout).
- **State assumptions explicitly before coding.**
- **No em-dashes or en-dashes - ever (7-bit ASCII authored content).** Hard rule across Legion / Peer, in *all* authored text: code, comments, docstrings, `.md`, writeups, commit messages, WAKEUP/ROADMAP/CLAUDE, chat output. Use ` - ` (spaced hyphen) for a clause break, `-` otherwise. Also avoid smart quotes (U+201C U+201D U+2018 U+2019) and en/em dashes (U+2013 U+2014); stay ASCII. **Why:** Windows PowerShell 5.1 `ParseFile` ANSI-decodes a no-BOM `.ps1`, turning a UTF-8 em-dash inside a double-quoted string into a U+201D smart-quote that the tokenizer treats as a string terminator -> cascading parse failure (2026-05-18 boot-script incident); also a standing operator style rule. **Retroactive purge done** (2026-05-18, `tools/strip_em_dashes.py` - reusable for drift checks): em+en dashes stripped repo-wide incl. the functional `"-"` no-data sentinel in code/JSON (operator-approved behavior change - empty dashboard cells render `-`). **NOT swept** (immutable history / non-source): `*.log` + rotated `*.log.N`, `docs/_archive/**` + dated artifacts, `.jsonl` ledgers, binaries, `.pyc`/`.git`. Smart quotes are rule-banned going forward but not yet retroactively swept (separate operator-gated pass).
- **Frozen files** (do not modify without explicit user approval):
  `main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
  `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/diagnose.md`, `tools/caveman.md`.

## Restart workflow

```
echo restart > restart_trigger.txt
```
Verify: read `ops/runtime/health.json`, confirm new `pid`, `alive=true`, `last_reload_ok=true`.
Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`.

## Third-party lift: license gate

Before lifting ANYTHING from an external repo, check the license and say what
it is. Two traps, both hit on 2026-07-28:

- **A repo can contradict itself.** One reviewed plugin ships an MIT `LICENSE`
  file while its `package.json` says `"license": "UNLICENSED", "private": true`.
  Another ships GPL-3 in `LICENSE` and `"ISC"` in `package.json`. A single
  glance at either source alone gives the wrong answer.
- **The person who cleared it may not own it.** A repo crediting prior authors
  ("first version by X", a per-file "BY @Y" header) has multiple copyright
  holders, so its current maintainer cannot unilaterally relicense it.
  Operator clearance from ONE party is not clearance for the work.
- **A LICENSE file can name NOBODY.** Measured 2026-08-01 (RM-127 Phase 3): one
  reviewed repo ships an MIT `LICENSE` that is an unrendered template, reading
  literally `Copyright (c) {{ year }} {{ organization }}`. It is a grant with no
  grantor. This is not the contradiction case above - both files "agree on MIT"
  and a grep for the SPDX id passes. **Read the copyright LINE, not just the
  license name.** Same pass found a truncated MIT (warranty clause cut, which is
  why the host reported NOASSERTION), a manifest with its license declaration
  COMMENTED OUT while `LICENSE` looked clean, and a repo with a valid MIT whose
  `NOTICE` named three adapted upstreams - clean license, still not vendor-safe.
  **Also note BUSL-1.1**: source-available, not copyleft, DO-NOT-VENDOR anyway,
  though its Additional Use Grant may permit running it internally.
- **The WRAPPER does not clear the PAYLOAD.** (Evidence: `docs/history_notes.md` 2026-09-16.)
  A top-level SPDX id describes the WRAPPER, not the embedded assets: before
  recording ANY verdict, enumerate the third-party notices for MARKS, ICONS,
  FONTS, SAMPLE DATA and COMMITTED BINARIES, each of which can carry its OWN
  terms. RC is Apache-2.0 and PUBLIC, so what bites RC is publishing
  NON-COMMERCIAL bytes under a permissive label - NC and SA assets cannot be
  absorbed. **The trap is licence-family INDEPENDENT**, which is the part most
  often missed: it bites a copyleft-outbound tree as a compatibility conflict
  and a permissive-outbound tree as a mislabelling problem, so a tree reasoning
  only about its OWN outbound licence checks for the wrong thing.
- **A LICENCE audit and a BEHAVIOUR audit are DIFFERENT audits, and enumerating
  EVERY TOP-LEVEL DIRECTORY is a precondition for both.** Same review: an audit
  of one package walked its source directory of 117 files and passed, while a
  wired-in network egress path sat in a separate top-level hooks directory of 98
  files and was missed by two independent reviewers. An empty grep is a claim
  about your PATTERN, not about the codebase. A tarball-vs-repository divergence
  was real but NOT the cause - the missed file is byte-identical in both
  (evidence: `docs/history_notes.md` 2026-09-16). Do NOT write "audit the tarball, not the repo" - that lesson is REFUTED.

GPL/copyleft stays DO-NOT-VENDOR regardless of verbal clearance - vendoring it
would relicense RC itself. The always-legal path is the one RC already uses:
re-implement the mechanic in RC's own code from the observed behaviour.
Techniques and protocol facts are not copyrightable; source is.

## Memory recall (Perseus Vault)

Local semantic-recall store over RC's own institutional knowledge. Exists because
the recurring failure is not ignorance, it is REDISCOVERY: redoing closed work,
re-pitching a refuted idea, acting on a stale doc, or writing a finding into the
wrong `.md`. Grep plus judgment does not catch those; paraphrase-tolerant recall does.

- **Local, no cloud, no API key.** One binary + one SQLite file at
  `~/.perseus-vault/`. Wired as MCP server `perseus-vault` in `.mcp.json`, so the
  `mcp__perseus-vault__*` tools are available in-session.
- **A fresh clone has NO wiring** - same trap as the git hooks. `.mcp.json`, the
  `.claude/settings.json` hooks, and the vault itself are all LOCAL and gitignored;
  only `tools/perseus_sync.py` is tracked. Re-wire with
  `perseus-vault connect --client claude-code --hooks`, then run the sync.
- **BEFORE starting any non-trivial item, recall first.** Use
  `python tools/perseus_recall.py "<the task in your own words>"`. If a `settled`
  or `ledger` hit says the work is CLOSED, REFUTED, or already shipped, stop and
  report that instead of building. This is the whole point of the store.
- **Recall through that tool, not the raw MCP call.** Raw
  `perseus_vault_recall` returns each hit's full body TWICE; the projection
  measured ~98 percent smaller for the same answer (evidence:
  `docs/history_notes.md` 2026-09-16). A mandatory step
  that costs 13k tokens is a step that gets skipped, which defeats the store.
  Take a `key` from the listing and fetch that ONE entity when you need a body.
- **It is a MIRROR, never the source of truth.** Source of truth stays CLAUDE.md,
  the `memory/*.md` files, `docs/LEDGER.md`, `ROADMAP.md`, `BACKLOG.md`. Never
  "fix" a fact only in the vault.
- **Re-sync after changing any of those:** `python tools/perseus_sync.py`
  (idempotent - category+key updates in place, never duplicates). Coverage check
  only: `python tools/perseus_sync.py --verify`.
- **`status: healthy` is NOT proof recall works.** Perseus reports
  `semantic_recall: available` with zero warnings even when most rows have no
  embedding, and recall then silently degrades to keyword. Only
  `embedded == active` proves coverage - that is exactly what `--verify` asserts.
  MEASURED 2026-07-28: a fresh ingest of 1197 entities left 91 embedded and still
  reported healthy.

## Session workflow

Scoped sessions - each focused task is one session.
- **End:** commit + update `WAKEUP_NOTES.md` (keep last 2-3 sessions at full fidelity; archive older to `docs/history_notes.md`) + push.
- **Start:** `/clear`, bootstrap from CLAUDE.md + MEMORY.md + git log + WAKEUP_NOTES + `docs/ARCHITECTURE.md` + `ROADMAP.md`.
- `/clear` between Tier items, between coding/reviewing modes, between focus-area switches.

## Session-End Ritual

When user says 'wrap', '/done', or 'end session': run tests, commit with descriptive message, push, sync living docs (append the per-item ledger entry to `docs/LEDGER.md`, NOT CLAUDE.md), **write the next-session continuation prompt to `RC-NEXT-SESSION.txt` in the REPO ROOT**, and confirm CI green before declaring done.

**`RC-NEXT-SESSION.txt` is the ONE hand-off file and the write is UNCONDITIONAL.** Repo root, TRACKED, OVERWRITTEN every `/done` - never appended, never dated-suffixed, never a second copy anywhere. `Desktop\RC-NEXT-SESSION.lnk` is only a shortcut to it; do NOT write to the Desktop (it moved off 2026-09-06). Printing the prompt into chat is not the hand-off - chat dies at `/clear`. This matches the convention every sibling uses (`<CODE>-NEXT-SESSION.txt` plus a Desktop `.lnk`). The old second file `NEXT_SESSION_PROMPT.md` is RETIRED to `docs/_archive/2026-09-07-NEXT_SESSION_PROMPT.md` (2026-09-20) - do not recreate it, and do not file its absence as a defect.

## Output Constraints

Keep individual responses under 500 output tokens to avoid API errors. Break long work into multiple turns or use file writes for verbose output.

## Style Rules

- No em-dashes anywhere (repo-wide hard rule, enforced).
- Watch for em-dashes in PowerShell double-quoted strings - they cause mojibake parse failures.

## Execution Efficiency & Tooling Rules

Operator-agreed 2026-06-13 to cut per-edit + audit wall-clock. Default to fast, direct, text-based tools; scale verification to blast radius. SCOPES "Testing Discipline" + "Verification Discipline" below (those apply at Tier-2). Memory: `feedback_execution_efficiency_rules`.

> **PRECEDENCE (operator 2026-07-30):** these rules govern HOW a step is executed - which tool, how much verification. They do NOT govern the SHAPE of the work. Shape is set by "Session Default" below, and where the two disagree, Session Default wins. R7 and R9 were rewritten on 2026-07-30 to remove exactly that conflict; do not restore the old wording.

Text-first (R1-R4) - never default to visual / computer-use for text, code, or state:
- **R1** Files = Read / Edit / Write / Grep / Glob ONLY. NEVER computer-use / Windows-MCP to read or change a file. **This bans Bash-mediated WRITES to repo files too** - `python - <<'EOF'` heredocs, `sed -i`, `>` redirection - and not only for tidiness: `tools/stop_claim_gate.py` corroborates every file claim from the Edit/Write tool-call record, so a file changed through Bash reads to it as an UNBACKED CLAIM even when the change is real and committed. (Measured 2026-09-04; evidence: `docs/history_notes.md` 2026-09-16.) Bash stays correct for READING (`grep`, `git show`) and for scratchpad files; for a tracked file, use Edit/Write. If you already used Bash, back the claim with `git show <sha> -- <path>` rather than retracting something true - and never fabricate an Edit call to satisfy the gate.
- **R2** Runtime / dashboard state via `curl -k https://127.0.0.1:8888/api/...` or Read `ops/runtime/health.json`. NEVER screenshot to read a number, version, or STATE.
- **R3** Visual tools (screenshot / computer-use / Windows-MCP / preview / capture_monitor) ONLY for rendered-pixel / CSS / layout checks with no text equivalent, and live-game capture. The UI-audit ritual + game-monitor are the sanctioned visual uses (`feedback_screenshot_after_ui_changes`).
- **R4** Prefer built-in tools over Bash / PowerShell. When shell is needed: absolute paths (no `cd`), one compound command over many round-trips.

Tiered verification (R5-R7) - Tier-0/1 do NOT pay the Tier-2 tax (operator-accepted tradeoff):
- **Tier-0** cosmetic (doc / comment / string / non-runtime constant): Edit + `py_compile` if .py. No suite, no restart.
- **Tier-1** local logic (one module): `py_compile` + that module's tests only.
- **Tier-2** schema / engine / scorer / item-effect / `ENGINE_VERSION`: full dual suite (DS dir + `tests/`) + DS `:8860` restart + Share mirror.
- **R5** Classify every change into a tier; run only that tier's verification.
- **R6** Run the relevant suite ONCE; trust exit code + result file. Re-run only if I edited since, or the pipe demonstrably glitched - not prophylactically.
- **R7** Adversarial verification is the DEFAULT, not the exception (operator 2026-07-30). Every substantive claim gets an independent `verifier` / refutation pass before it is called done - including my own single-thread edits. The old "verifier ONLY for parallel-slice or stale-pipe" carve-out is REVOKED: it made self-checking opt-in, and the standing failure class is exactly a confident unbacked claim. Tier-0 cosmetic edits remain exempt.

Overhead (R8-R11):
- **R8** Never re-Read a file I just Edited to confirm (Edit fails loudly).
- **R9** Orchestrated multi-agent is the DEFAULT shape for substantive work (operator 2026-07-30) - see "Session Default" below, which governs. Inline solo is the EXCEPTION, reserved for truly trivial edits (a one-line cosmetic change, a doc typo, a single string). The former "no subagents under ~3 files" file-count threshold is REVOKED as the deciding test: substance decides, not file count. A 1-file engine change is substantive; a 5-file rename is not.
- **R10** Batch independent reads / greps in one message.
- **R11** Skip the screenshot ritual for backend / version / doc changes (scoped to web/* visual changes).

Enforcement (hooks in `.claude/settings.json`): PostToolUse `tools/pytest_guard.py` is py_compile-only by default (no auto full-suite per edit); `RC_FULL_SUITE=1` restores auto-suite for a Tier-2 batch. PreToolUse `tools/text_first_guard.py` denies pure screen-text/state readers (Windows-MCP Scrape, computer-use read_clipboard) with a text-path pointer; escape hatch `ops/runtime/allow_visual.flag`.

## Web dashboard

`web_dashboard.py` at `:8888` HTTPS. Key endpoints: `/`, `/api/state`, `/api/health/all`, `/api/input`, `/api/command`, `/api/ds-preview`, `/metrics`. Viewed in Chrome on Legion at `https://legion-rc:8888/` - design baseline is **standard 1920x1080 with Chrome chrome present** (titlebar + URL bar + bookmarks bar visible, usable viewport approx 1920x~920). F11 fullscreen is optional and recovers the chrome chrome - `main` flex-grows into the extra height (no layout pinned to 1280). Cert via `tools/regen_rc_cert.ps1`. Each machine has its own Anthropic API key, named per host on the Anthropic console. Those console names are deliberately NOT recited here (they name other machines), and they are NOT renamed by the product rename - editing a doc does not rename a key.

## Scheduled tasks (Legion)

Key: `RC-Supervisor` (logon, Administrator, HIGHEST). Vision has NO scheduled task (removed 2026-06-11, deep-audit P2): `dashboard/server.py` self-heals `:8889` in-process. Full list: `docs/OPERATIONS.md`.

## Vision pipeline

The `screen_agent.py` agent (Legion-local) POSTs frames every 2s to `:8889/upload-frame`. Coaches call `modes.shared_vision._capture_screen()` -> GET `:8889/latest-frame`. **`_run_vision()` gates on `_fetch_game_data() is not None`** - vision never fires during lobby/idle. Tiered: OCR first, Sonnet escalation for misses. Calibrate `data/vision_regions.json` to expand OCR coverage. The sibling Live Client relay (`:8889/upload-liveclient` <- RC-LiveClientRelay agent; `/latest-liveclient` -> poller + `core/liveclient_cache`) self-heals: `vision_server/_relay.get_latest_liveclient()` reads `:2999` in-process when the relayed snapshot is stale + `GAME_HOST` is local, so the relay agent is non-integral to DS/RC (1-PC, ADR-011 update 2026-06-02).

## Mode detection

`game_reader.py._process_game()` -> `core/game_snapshot.py` -> mode strings. ARAM Mayhem (`KIWI`) -> `MODE_ARAM`.

## Where to find current state

- Live PID + mode + health: `ops/runtime/health.json`
- Current game state: `data/{aram,arena,brawl,tft}_coaching_data.json`
- Recent activity: `logs/YYYY-MM-DD.log`
- Architecture / module map: `docs/ARCHITECTURE.md`
- Ops commands + restart: `docs/OPERATIONS.md`
- Open work: `ROADMAP.md` - Aspirational: `BACKLOG.md` - History: `docs/history_notes.md`

## Useful commands

Full reference: `docs/OPERATIONS.md`. Quick-start:
```
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"
echo restart > restart_trigger.txt
curl -k https://127.0.0.1:8888/api/health/all
```


## TDD First

All feature work and bug fixes follow TDD: write failing characterization/regression test first, then implement, then verify full suite (`pytest agents/daemon_slayer` + `pytest tests`, both from the repo root - never `pytest .`) before committing. **Do not restate a suite count here.** The DS count lives in the `docs/DAEMON_SLAYER.md` status banner, but **that count is NOT guarded and a doc is not a source of truth** - `tests/test_docs_daemon_slayer_drift.py` pins only `ENGINE_VERSION` + `patch` + the route list in that banner and says in its own docstring that it deliberately does NOT pin the `def test_` counts. Measure the DS count with `pytest agents/daemon_slayer --collect-only -q`. The RC `tests/` count likewise has no guard, so measure it with `pytest tests --collect-only -q` rather than quoting a doc. Counts recited here have gone stale twice (evidence: `docs/history_notes.md` 2026-09-16).

## Subagent Code Quality

When spawning subagents to generate files (especially tests), require them to run ruff/lint before reporting done. Subagent-generated test files have broken CI in the past.

## Session Default (was: Subagent-First Protocol)

**Standing operator directive (2026-07-30). The default shape of EVERY session is orchestrated + multi-agent + self-adjudicating + self-adversarial.** This is the baseline, not an escalation reserved for big items - choosing it needs no justification; departing from it does. It GOVERNS the Execution Efficiency rules above wherever the two disagree.

**RESTATED 2026-09-09 with the REASON, which is now part of the rule: "sub-agent first to keep main session quiet and clear, always."** The main window is the OPERATOR'S surface. Work happens in subagents; the main thread holds the plan, the merge, the gate and the report - not the doing. "Always" is the operator's word. The trivial-edit carve-out below stands but is narrow, and "it is faster inline" is NOT a reason to spend the main window.

**HEADLESS-LOOPING PROGRAM (standing, operator 2026-09-09): the five-way responder work - its tests and its fixes - runs on a HEADLESS LOOP, not as attended per-row sessions.** **The RUNNER ITSELF IS ALREADY BUILT** - RM-384 shipped it 2026-09-08 (LEDGER 1364) and RM-385 + RM-386 shipped both tails the same day; `docs/RESPONDER_RUNNER_SPEC.md` is the spec it was built FROM, not open work. So the loop's scope is tests, fixes and hardening on a shipped runner. A first draft of this rule called the runner unstarted, which was one day stale. The loop does not ask permission per cycle. **THE BOUNDARY (operator-adopted 2026-09-09, SUPERSEDING the ARMING-only reading): halt before any byte leaves the tree.** The loop halts and PINGS THE OPERATOR before any write, delete or lock acquisition outside the repository root, before any PUSH WHOSE DIFF CAN LEAK (the diff gate below - the destination rule that used to sit here is SUPERSEDED), and before any edit to a cross-repository byte-pinned or grammar-pinned artifact - not merely before arming a task. Arming REMAINS a halt point; it is simply no longer the only one and no longer the earliest. **SCOPE, decided by the operator in the same breath: this binds EVERY RC session, ATTENDED ONES INCLUDED.** Every byte-leaves-tree act halts in an attended session too. Do not read "headless loop" in this heading as the limit of the rule. **ONE STANDING CARVE-OUT, operator-granted 2026-09-20, and it is NARROW: delivering a channel REPLY into a sibling's `moon_sync_inbox/` is PRE-AUTHORISED and does NOT halt.** The operator's words were "yes always deliver a reply". **Its scope is the agreed inbox surface and nothing else** - it does not authorise writing, deleting or locking anything else outside the root, it does not authorise reading a sibling's tree beyond what a reply needs, and it does not touch the PUSH half or the byte-pinned-artifact half, both of which still halt. **Deliver, then RE-HASH every destination and publish the reached-count** (a discipline adopted from a sibling: an outbound note sitting in your own outbox is not delivery, and only the recipient's copy proves it). **THE PUSH HALF IS GATED ON DIFF CONTENT, NOT ON DESTINATION (operator-adopted 2026-09-09, SUPERSEDING the one-day-old carve-out that pre-authorised a push to RC's OWN origin; that sentence is deleted, not softened, and both readings must never sit in this file at once).** A push HALTS and pings when its DIFF touches a cross-repository byte-pinned artifact (`ops/loop/slots.py`, `ops/loop/winmutex.py`, pinned by `SHARED_SHA256` at `tests/test_loop_concurrency.py:480`, parametrised at `:548`; `docs/CHANNEL.md`, pinned by `CHANNEL_PIN` in `tests/test_channel_doc_pin.py`), or when it trips the sibling-name sweep. It does NOT halt on an ordinary push that passes the suites and the sweep. A DESTINATION rule is wrong in BOTH settings (evidence: `docs/history_notes.md` 2026-09-16). A content rule halts on neither ordinary case and halts on precisely the pushes that can leak. **THE SWEEP EXISTS AND IS ARMED (RM-399 SHIPPED 2026-09-10): `tools/sibling_name_sweep.py`, guarded by `tests/test_sibling_name_sweep.py`, wired into `.githooks/pre-push` AHEAD of the preserved `git lfs pre-push "$@"`.** The 2026-09-09 gap sentence that sat here - asserting in capitals that RC had no such sweep, that no such test file existed, and that pre-push was LFS ONLY - was true when written and is now false in all three halves; it is deleted, not softened, and must not be restored. **But the honest claim is "the sweep half is ARMED WITH A MEASURED ESCAPE RATE ABOVE ZERO", never "sibling names cannot leak", and that phrasing must not be softened.** Specifying it found **FIVE REAL ESCAPES in RC's own tree**, all live in HEAD and **ALL ALREADY PUBLISHED to the public remote**. Four were remediated at HEAD (`f6cf005bb`); **remediating HEAD does NOT undo publication, and no history rewrite was performed.** **The fifth was CLOSED UNILATERALLY 2026-09-12; the fence that called it joint was wrong on its premise** (`SHARED_SHA256` pins only `slots.py` and `winmutex.py`; evidence: `docs/history_notes.md` 2026-09-16). `KNOWN_EXCEPTIONS` in the tool is now `{}` - there is no declared exception left, and this sentence must not be restored to claim one. **Named blind spots:** A BARE CHANNEL CODE IS NEVER DETECTED - measured 2026-09-20 off `tools/sibling_name_sweep.py:904`, whose own comment reads "Never matches a code on its own": the code arm only escalates `SEV_NAME` to `SEV_RESOLUTION` near an existing NAME match (`:936-941`), so it is a severity MODIFIER and never a detector. The sweep reported `ops/loop/winmutex.py` CLEAN while its line 118 named a carrier, and reports clean for every other counterparty code too. **That INSTANCE was repaired 2026-09-20 by ROUND B (`3ca8be8ce`; bytes 6190 -> 6184, `df0a7a40`, pin moved in the same commit), so do not go looking for it - but the BLIND SPOT is unchanged and the example must not be read as closing it.** A repaired instance is not a repaired detector. RC's earlier channel wording, "matches project names not channel codes", UNDERSTATED this - the codes are not a weaker arm, they are not an arm at all. LFS OBJECT CONTENT is never scanned by `--pre-push` (the pointer is, and scans clean truthfully) - **but that is FALSE of `--tree` on a smudged checkout, measured 2026-09-20 (RM-477): the tree arm reads the WORKING TREE, so it scans the full smudged payload, 633,521,375 bytes over 4911 files. That is MORE coverage than this line used to claim, not less, and the general trap is that a fact about the OBJECT STORE is not a fact about the CHECKOUT;** `--no-verify` bypasses the whole hook and nothing can prevent it; `RC_SIBLING_SWEEP_BYPASS=1` proceeds but prints the full would-have-halted report and appends it to a gitignored log. **It is NOT contiguity-only:** its positive-control arm is seeded from RC's OWN five escapes and includes a SPLIT-FORM control catching a name broken across a comment-continuation line wrap, which no whole-token search can see. **And there is NO TIMEOUT: RC halts and WAITS.** It never proceeds after a delay, because a bilateral rule that auto-proceeds is a unilateral rule with extra steps. `RC-InboxResponder` stays DISARMED until an expiring agreement record arms it, and an unattended loop must never arm another repo. **RSC REFUTED the older ARMING-only reading** with seven seams that reach another repo with NOTHING armed: the shared `slots.py` root, `reap()` unlink, `Global\` mutexes, the byte-pinned pair, responder filename grammar, push, and unconfined subagent writes (full text: `docs/history_notes.md` 2026-09-16).

The four properties, each load-bearing:
- **Orchestrated** - one merger holds the plan and the merge; work is decomposed into disjoint slices before any of it starts.
- **Multi-agent** - slices run in parallel on non-overlapping files, worktree-isolated where they write.
- **Self-adjudicating** - a distinct agent decides between competing outputs against stated criteria. The agent that produced a thing never grades it.
- **Self-adversarial** - findings and "done" claims get an independent pass that is trying to REFUTE them, defaulting to refuted when uncertain. Agreement between two agents is not evidence (`feedback_row_agreement_is_not_evidence`).

**The only exception is genuinely trivial work:** a one-line cosmetic edit, a doc typo, a single string, a conversational answer. Substance decides, not file count.

The 2026-06-20 wording this replaced is SUPERSEDED (text: `docs/history_notes.md` 2026-09-16).
- **Spec first, then act:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it against ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
- **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building. The loop is single-vendor since 2026-08-01 - director, executor and auditor are all Claude, and there is no second vendor to be 'down'.
- **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
- Every `.claude/commands/*.md` carries the SUBAGENT-FIRST block (local, gitignored). See memory `feedback_subagent_first_protocol` + `feedback_parallel_batch_agents`.

## Testing Discipline

**A test that enumerates the REPO ROOT uses `tests/_repo_walk` - never a fresh `rglob` plus a hand-rolled skip set (ADR-015).** The universe is the git index first, `EXCLUDED_DIRS` as backstop; a guard keeps only its OWN scope skips on top. Ask first whether an EMPTY enumeration would PASS your assertion, and anchor it if so - that is how a conversion turns a machine-local red into a silent always-green. A subdirectory walk is not a root walk and needs none of this.

Before any mutation or fault-injection round, snapshot the digest of every durable store it could reach (seen stores, watermarks, ledgers, hook logs), compare after the round, and attribute any change to a named writer before grading a single arm - an unattributed change voids the round.

Always run the full test suite after schema changes, engine version bumps, or item-effect additions. Avoid data-fragile cross-item comparison assertions; prefer assertions on computed quantities. When stubbing methods accessed via class, wrap with `@staticmethod` correctly. Before writing any probe or test, grep the codebase to confirm every method, field, and data shape it will use actually exists - cite file:line for each; never scaffold against an assumed API surface (past misses: heal/shield assumed in raw_modifiers, wrong file shapes). **Tier scope (R5):** "full suite" = Tier-2 (schema / engine / ENGINE_VERSION / item-effect); Tier-0 cosmetic + Tier-1 local-logic edits are exempt - see "Execution Efficiency & Tooling Rules".

## Error Handling

Never surface raw API error strings (credit/balance exhaustion, 400, rate-limit, thinking-block) in the coach UI or any user-facing dashboard panel. Catch and render a friendly degraded-mode message (e.g. "coaching paused - retrying") and log the raw error to `logs/`. Applies to all coaches + dashboard panels.

## Verification

Before asserting external state - API key validity, account IDs, process/PID metrics, "X is dead/missing/broken" - verify it live against the source of truth; never rely on a stale doc or another agent's unverified output. Re-probe first, then assert. See memories `feedback_verify_generated_reports` / `feedback_verify_before_declare_broken` / `feedback_audit_proposals_are_intent`.

## Verification Discipline

Re-verify against ground truth before claiming any task green; the tool pipe can replay stale or out-of-order results (item 238 hit severe stale-tool-result replay - fabricated "1 failed", a non-existent dtype=None, a pre-bump /health, invented filenames). Ground truth when the pipe wedges = `git status` + Edit success/fail + pytest written to a file + a DONE-exit sentinel, NOT raw stdout. Before reporting complete: re-run the relevant suite fresh, confirm every cited test file actually exists on disk (`ls` it), and report the exact pass/fail counts you observed THIS run - never carry a prior or subagent-reported count forward. NEVER trust a subagent's claim about test counts, green CI, or file existence without an independent probe; subagents have cited non-existent test files and used broken commands (wmic, pre-restart cumulative measurements). The `verifier` subagent (`.claude/agents/verifier.md`) exists for exactly this re-check. See `feedback_verify_generated_reports` / `feedback_verify_before_declare_broken`. **Tier scope (R6-R7):** this re-verify-fresh + verifier mandate applies at Tier-2; Tier-0/1 follow tiered verification (run once, trust exit code unless edited-since or the pipe glitched) - see "Execution Efficiency & Tooling Rules".

## UI Fixture Ritual

Any UI page change runs the visual-hierarchy / fixture audit subagent BEFORE the commit + push, not after. Do not commit a page until the 5-phase audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) completes and every MUST-FIX is resolved in the same slice. Shipping a page ahead of its audit (page #8) was a process miss the operator called out explicitly. See `feedback_phase3_fixture_ritual` + headless-upgrade section 3b.

## Python Conventions

When adding a required field to a dataclass, append it at the END with a default; do not insert mid-class. A mid-class required field breaks every existing positional construction + test (item 216 inserted an AbilityContext field mid-class and broke 41 manual constructions; the fix was to default it at the end).

## Data Fixes

A data-corruption or pollution fix is not done until already-corrupted rows are backfilled + recovered, not just future occurrences prevented. A race-condition guard that only stops future races leaves the existing bad rows wrong (item 211 needed two extra backfill + Match-V5 recovery rounds AFTER the guard landed). Plan the recovery pass in the SAME fix and verify the historical rows are corrected live.

## Engine / Build Conventions

Champion-specific build / scorer fixes are validated per-champion, not with one generic ADC-crit shape; expect to patch multiple champions. A narrow first fix (item 208 marksman pollution) missed Golden Spatula + duplicate-path pollution and forced a second comprehensive cleanup (item 213). Before shipping a build/scorer fix: grep for sibling cases (other champions, other modes, duplicate build paths) and add a test covering each, root-cause-first (see the `root-cause-fix` skill). When narrowing a proc/effect fold (burn / kill-state / item-DoT credit): start with the tightest matching item/effect set and add a test asserting unrelated proc types (physical / tank / spellblade) are excluded BEFORE widening; widen only on test evidence (the DSV1 burn-proc fold over-counted on its first pass and took two narrowing iterations).

## Windows Environment Notes

Claude Desktop on Windows may be installed via the Microsoft Store (check `%LOCALAPPDATA%\Packages`) in addition to standard install paths. Use `pythonw.exe` (not `python.exe`) for background daemons to avoid flashing console windows. Every console-subsystem CHILD of a windowless parent (pythonw, or a hook under the desktop harness) needs `creationflags=CREATE_NO_WINDOW` or it flashes - the interpreter token removes no flash, and a windowless interpreter still keeps stdin/stdout/stderr/exit when the parent redirects them. AppData is MSIX-virtualised and repo roots are NOT, so a packaged process writing under `%LOCALAPPDATA%` shadows every later read from outside the package - keep runtime records under the repo root.

## Daemon Slayer Batch Workflow

When continuing Daemon Slayer work: pick the next batch from ROADMAP, implement schema/engine changes, add tests (target green before commit), bump engine version, commit + push, verify live, update hand-off notes.

Before launching a background RC or test suite right after a DS change, wait for the Share mirror sync + DS `:8860` restart to settle; a mid-suite DS bounce produces false anchor-mismatch / live-integration failures that then cost a re-run to confirm they were transient.

## Session Wrap-up

When invoked with `/done` or asked to wrap a session: (1) audit pending changes, (2) commit and push, (3) update ROADMAP/README + append the per-item completion entry to `docs/LEDGER.md` (NEVER to CLAUDE.md; it is CI size-budgeted < 60KB - touch CLAUDE.md only for rule/frozen-list/Settled changes), (4) process lessons/WAKEUP_NOTES, (5) OVERWRITE `RC-NEXT-SESSION.txt` in the repo root with the continuation prompt and commit it with the session's work (see "Session-End Ritual"), (6) print final banner. Run independent steps in parallel. (Deprecated 2026-06-21 per operator: the Peer cross-Claude bridge probe / `/loop /process-bridge-tasks` re-run is NO LONGER part of the /done ritual - do not probe the bridge or flag a dead Peer loop at wrap.)

## Active priorities

Per-item completion ledger relocated to `docs/LEDGER.md` (append-only, newest-first) on 2026-06-02 to keep CLAUDE.md out of the per-turn auto-load budget. CLAUDE.md is CI size-budgeted (< 60KB) - NEVER append item-ledger entries here; append them to `docs/LEDGER.md`.

- Open work + NEXT: `ROADMAP.md` + `BACKLOG.md`
- Recent session fidelity (last 2-3): `WAKEUP_NOTES.md`
- Per-item completion ledger (item 325 and newer): `docs/LEDGER.md`
- Deep archive (items 1-324 + pruned wakeups): `docs/history_notes.md`

### Settled - do not re-litigate (items 1-149 relocated verbatim to `docs/history_notes.md` (1-93 on 2026-05-19, 94-149 on 2026-05-23); read that archive for full context before re-opening any line below)

- **Phases 1-7, 2.1-2.4, 3, 4-6, FU01/FU02/FU04 all shipped; the 6-scorer archetype-expansion plan (carry/tank/bruiser/mage/assassin/enchanter) is fully wired and the dispatcher has no fallbacks.** FU03 was superseded by FU04. Do not re-plan these or re-pitch a scorer.
- **DS conditional-target-state arc is operator-CLOSED (s232).** Part-2 live target-state plumbing is shelved permanently; an s232 saturation guard exists. Do NOT re-pitch Part-2 or re-scan for conditional candidates.
- **DS block_index/form_index/max_priority/combo_sequence pure-data registries were swept s223-s232 and are provably saturated** (machine-guarded). Further growth needs a schema lift, not uncovered-champion scans. The reusable pre-filters (`tools/ds_*_prefilter.py`, `ds_block_scanner.py`) are durable for patch re-extracts. Never `--force` a Meraki re-extract (the `latest` endpoint is mutable).
- **CARVE-OUT to the "source of truth is the Meraki bulk" DS audit rule: Meraki is NOT the source for item PEN / LETHALITY / resist-reduction MAGNITUDES - those live ONLY in the DDragon `<stats>` description block.** Measured at 16.15.1 (2026-08-08, independently verified): `items_meraki.json` carries **320 items against DDragon's 706**, **ZERO rows carry a `stats` key at all** (row keys are id/name/rank/tier/shop/passives/active/simpleDescription/noEffects/removed), and item **228005 is absent from Meraki entirely**. Auditing a magnitude against Meraki therefore produces phantom mismatches - it cost one slice 7 of them this run before it was caught. **Meraki REMAINS correct and preferred for item PASSIVE FORMULAS** - but NOT for `aram_modifiers`, and that half of this carve-out was WRONG until 2026-09-04. `aram_modifiers` is LOLMATH-sourced, not Meraki: `tools/daemon_slayer_extract.py:503` declares it on the `LolmathExtract` dataclass under "Sourced from the data chunk", `:970` assigns `lolmath.aram_modifiers.get(champ_id)`, every consumer reads `champ_rec["lolmath"]["aram_modifiers"]` (8 sites incl. `dps.py:930`, `ehp.py:936`), and `ehp.py:930` says so in prose - "extracted by `tools/daemon_slayer_extract.py` from lolmath's data chunk". Found by an adversarial pass during RM-291B (LEDGER 1332) - this is a narrow carve-out, not "Meraki is wrong".
- **AUTONOMOUS_AUDIT s5 menu is fully exhausted** (the effects.py facade split shipped s246). Do NOT re-pitch an effects.py re-merge, an `__all__`, or a FastMCP/SDK rewrite of the stdlib MCP servers.
- **Keystone fixed + live-proven (item 87): ARAM Mayhem reports queueId 2400** (not 920). The phase-driven view-router was proven correct - do NOT re-pitch a router change. The `cs.is_aram` rendering path is item-87-preserved.
- **The augment LCU/:2999 API is a confirmed dead-end** (no capture-free augment API mid-game). Augment-OCR into the coach is the proven path. Do NOT re-pitch an LCU augment API.
- **`core/build_order.py` no-double-unique rule is engine-authoritative** - do NOT add a family map (a guard test fails on any family literal); the engine has 6 unique-passive families, not 3.
- **Research-list triage CLOSED negatives (do NOT re-research):** every LCU client/codegen repo is inferior to RC's lockfile client; the LCU/Riot-Client endpoint catalog is reference-only, and its use was operator-cleared VERBALLY on 2026-07-28 (the upstream repo still ships NO LICENSE file, so the clearance is not in writing - do not treat absence of a LICENSE as permission for any OTHER repo); the corpus has ZERO Arena/Cherry/Mayhem lobby-create payloads (a bespoke payload must come from live LCU capture); `.rofl` full packet-parse stays out of scope as a shipping feature (per-patch Layer-2 obfuscation re-RE cost; a patch-stable Layer-1 header/chunk spike is logged in BACKLOG - the old "subset of Match-V5" reason was corrected 2026-06-03 since the format does carry per-cast/windup telemetry); ML win-predictors / CV-minimap / voice / `riot-offline-mode` are all CLOSED; Pengu `league-client-mcp` = NO (thinner than RC's client).
- **`core/smoothed_rates.py` is the shared Laplace/shrink primitive**; the s220 PGR 0-100 score is deferred to ROADMAP-S3 - do NOT pre-build it.
- **Brawl mode is retired from champ-select** (s214). **CORRECTED 2026-08-06: the second half of this entry - "legacy brawl backend is left as deadcode for a separate cleanup pass" - was FALSE, and was false on the day it was written.** `coaches/brawl_coach.py` is LIVE-REACHABLE: `core/game_snapshot.py` routes URF / ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ to `MODE_BRAWL`, `core/coach_registry.py` maps that to the module, `app/_game_lifecycle.py` importlib-loads it on game start, `config/feature_flags.json` has `brawl.live_coaching: "allow"` (verified live), and `coaches/brawl_coach.py:492` issues a **live Haiku call** - construction alone suffices, because `_base_coach.__init__` spawns the poll loop. Routing provenance: `docs/history_notes.md` 2026-09-16. **A cleanup pass acting on the old wording would delete the coach for five other modes.** Two fences: `brawl_coach.py:199 GAME_MODES` omits URF/ARURF/ONEFORALL but is NEVER READ (documentation, not a gate - do not "fix" it into one), and this is CODE REACHABILITY only - whether Riot currently rotates those modes is unmeasured, so the honest phrase is "unexercised, not unreachable". LEDGER 1222.
- **The Riot Personal key is valid and in-scope.** Match-V5 403/empty on event modes (ARAM Mayhem `gameMode=KIWI`, queue 2400) is EXPECTED, not a key fault; event-mode Match-V5 timeline placeholders are correct and permanent. **But Match-V5 is not the only route (MEASURED 2026-07-19, RM-106):** SGP, the client's own LCU-session-authenticated match-history backend, DOES return KIWI / queue-2400 games in Match-V5 shape. The statement above still stands; its CONSEQUENCE - that event-mode match data is unobtainable - does not.
- **`web/js/dashboard.js` is GONE** (quarantined `90c54ef5`; only `/js/main.js` loads). It was dead code - no `<script>` reference - and the `dashboard.js:5055` `_replayQueueLabel` 920 bug died with it. Nothing to leave alone; this line is a closed fence, kept only so the 920 bug is not re-reported against a file that no longer exists.
- **ADR-008 unified asset-hash:** editing `web/{js,css}/panels/*` auto-reloads via `compute_asset_hash` - no RC restart for asset-only changes.
- **No-em-dash retroactive purge is done** (s244 `tools/strip_em_dashes.py`, reusable for drift checks); the functional `"-"` no-data sentinel is operator-approved. The smart-quote retro-sweep is NOT yet done (separate operator-gated pass).
- **The all-173 alphabetical DS_SWEEP is CLOSED (2026-07-18, batch32): 173/173 - GAP 135, REFUTE 35, FENCED 3, Remaining 0.** Do NOT re-open the roster or re-scan for uncovered champions; further growth needs a schema lift, not another pass. Next free spec = RM-98. Two probe traps make a re-run produce plausible-but-WRONG output: `POST /rank` is the CARRY scorer and silently ignores `enemy_ad_share`/`enemy_ap_share` (use `/rank-<archetype>`), and probing at `item_ids=[]` under-ranks amp/complementary items - that artifact manufactured the two headline RM-92 instances (Soraka Moonstone reads #10 of 10 empty, #2 at depth, and the shipped build order already buys it). See memories `reference_ds_probe_rank_vs_archetype_route` + `reference_ds_probe_empty_build_artifact`.
- **The live-gated set is NOT synthetically drainable - measured, do not re-pitch.** A 14-agent triage-then-adversarial-refutation pass over all 124 rows (2026-07-18) closed **6**. Dominant kill was SUBSTITUTION: gate rows ask whether something RENDERS / SENDS / UPDATES, and the compute half is always available headless and always the wrong question. `docs/LIVE_GAME_GATED_SYNC.md` carries the full note.
- **Ledger commit citations before 2026-07 are ~50% unresolvable and that is EXPECTED** (387 of 1148). Not a history rewrite - worktree-agent slice SHAs that never survived cherry-pick. The work landed; verify by merge hash / file / test, never by a slice hash. Self-corrected: 0 of 537 July citations are dead. See the preamble in `docs/LEDGER.md`.
- **Live DS truth = `data/daemon_slayer/current.txt` + `agents/daemon_slayer/__init__.py` + `/health`** (do not trust ledger recollection of patch/ENGINE). DS coverage %/match-row prose is a DS-batch docs-sync job, never recomputed in a general sync (nested registry schema; a flat count mis-parses) - memory `feedback_ds_coverage_prose_recompute`.
- **A DS route seam has THREE gates, and the ownership prose lies in BOTH directions.** Measure owners with `inspect.signature` over a package-wide sweep, never inherit a docstring (one was measured wrong in BOTH directions in one run; evidence: `docs/history_notes.md` 2026-09-16). Then check the TRANSPORT, not just the flag: `/dps` carried no `rune_ids` and `/ehp` no `targets_in_rotation`, and non-prefixed transports are invisible to both reachability guards, so flag-only wiring ships a seam that is settable, guard-green and arithmetically INERT. Memory `reference_ds_route_seam_transport_vs_flag`.
- **Ability-haste is measured INERT however authored - do not spec it a fourth time.** RM-39/RM-43 was deferred, operator-reopened 2026-07-29, and re-closed the same day by the gating experiment. Three specs, one answer.
- **Biggest pending non-engine item: the s220 aggregator-G-style Post Game Review reframe** (UI; operator-decided scope - single-match richer layout, the 0-100 score is an RC heuristic over enriched stats with NO Claude/Riot dependency; staged S2-S5, each its own session plus the per-page UI-audit ritual). Legion 1-PC consolidation is DONE (ADR-011) - only deferred tails remain (OBS launch-test live-gated; Phase 11 vision relay full-collapse partly done items 267/276). 101.qq.com duo-synergy is DONE + LIVE-WIRED (item 277): captured + characterized, then operator chose the LIVE dependency - NEW `core/synergy_external_source.fetch_rows` feeds the EXISTING item-199 `core/smoothed_rates_101qq` lane (live-first, static May-25 seed fallback, `RC_DUO_SYNERGY_LIVE=0` kill switch); `/api/duo-synergy` route + bot/sup grid unchanged. **The "raw payload gitignored (redistributable)" clause that sat here until 2026-09-07 was FALSE in both halves.** The capture is TRACKED, so nothing protects it (evidence: `docs/history_notes.md` 2026-09-16). It is third-party data governed by that operator's terms, so it is recorded in `NOTICE` rather than assumed safe. Live open work is tracked in `ROADMAP.md` / `BACKLOG.md`.

Full open work + future: `ROADMAP.md` + `BACKLOG.md`. Per-item ledger (325 and newer): `docs/LEDGER.md`. Deep archive (items 1-324 + pruned wakeups): `docs/history_notes.md`.
