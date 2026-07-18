# Agent 6 - Fourth Audit (Phase 3 repo pass)

- **Date:** 2026-04-28
- **Auditor:** Agent 6 (Opus 4.7, ephemeral session under task `t-db28173acbb2`)
- **Scope:** Phase 3 subtree - `agents/`, `lib/`, `web/` - cross-referenced
  against `agents/state/resolved_decisions.json@phase3-1.1`.
- **Follows:** `20260422-134400-third-audit-phase3.md`. All 10 third-audit
  proposals verified landed in code:
  - H-01 fanout parallel (ws_server.py:93-126), H-02 heartbeat guard
    (ws_server.py:181-193), H-03 decisions version check (supervisor.py:79,
    258-282, called at 1489).
  - M-01 charter-fail-loud (supervisor.py:1333-1347), M-02 ddragon
    JSONDecodeError guard (lib/ddragon/fetch.py:88-89), M-04 queue-load
    error log (scheduler.py:243-244, 466-467, 580-581).
  - L-01 ws_client backoff with jitter (web/js/ws_client.js:30-42).
- **Method:** Two parallel Explore subagents (`agents/` + `lib`/`web/`),
  then claim-by-claim verification by me before inclusion. Five subagent
  claims rejected as false-positives or overstated; see "Disputed" below.

## New findings

### MEDIUM

**M-01 - Icon downloader concatenates DDragon-supplied filename without basename guard**
- **File:line:** `lib/icons/downloader.py:69-70` (champions),
  `:83-84` (spells), `:97-98` (items). Runes path is fine - `Path(icon).name`
  on lines 111 and 120 strips directory components.
- **What's wrong:** `img = (meta.get("image") or {}).get("full")` and then
  `_download(url, out / img, force)`. If a DDragon response (or a MITM with
  TLS bypass; or a future Riot CDN bug) returned `"full": "../../../etc/x.png"`
  or `"full": "abs\\path"`, `Path("data/icons/champion") / img` would resolve
  outside `data/icons/`. The breaker/blocklist won't catch this - it's a
  filesystem write at the consumer.
- **Why:** Defense-in-depth. The icon root is the only place external
  data crosses into a path operation without a `.name` reduction or
  allowlist. Runes already handle this correctly; champions/spells/items
  don't.
- **Fix:**
  ```python
  bn = os.path.basename(img.replace("\\", "/"))
  if bn != img or "/" in img or "\\" in img or img.startswith("."):
      logger.warning("rejecting suspicious icon name %r for %s", img, key)
      continue
  target = out / bn
  ```
- **Action:** Proposal `P-audit4-m01-icon-basename-guard` filed for Agent 2.

**M-02 - `SUPPORTED_MODES` duplicated in 4 places; no enforcement against `resolved_decisions.json`**
- **File:line:** `agents/agent4_coach_mentor/analyzer.py:40`,
  `agents/agent2_backend/pipeline/orchestrator.py:66`,
  `coaches/adaptation_hint.py` (re-exported and consumed by
  `agent4_coach_mentor/cold_streak_detector.py:28`,
  `agent4_coach_mentor/insight_detector.py:24`,
  `agents/supervisor.py:905`),
  `agents/agent3_testing/suite/test_supervisor.py:21` (`MODE_DBS`).
- **What's wrong:** Each file independently hardcodes
  `("sr_draft","sr_ranked","aram","arena","brawl")`. The decisions file
  (`db.files`) is the source of truth for the mode set, and Agent 6's
  mandate calls drift from that file a finding. There is no startup
  cross-check.
- **Why:** Adding a sixth mode (e.g. URF, an event mode) would require
  hand-edits to ≥4 files, none of them caught by tests. Conversely,
  removing one would not be caught - orphan code paths persist silently.
- **Fix:** Introduce a single `lib.modes.PHASE3_MODES` constant that
  `lib/modes/__init__.py` reads from the decisions file at import. Then
  `assert PHASE3_MODES == decisions["db"]["files"]` at supervisor start.
  Replace each hardcoded tuple with an import.
- **Action:** Proposal `P-audit4-m02-modes-single-source` filed for Agent 2.

**M-03 - Per-task log dumps full claude stdout/stderr without secret redaction**
- **File:line:** `agents/supervisor.py:1411-1423`.
- **What's wrong:** The per-task log writes
  `f"--- stdout ---\n{proc.stdout}\n\n--- stderr ---\n{proc.stderr}\n"`
  verbatim. Two leak vectors:
  1. The ephemeral agent's transcript may echo a fragment of its system
     prompt, which currently includes the contents of `CLAUDE.md` and the
     charter. Neither references the API key today, but the supervisor
     also injects `ANTHROPIC_API_KEY` into the env - and any traceback or
     error message that surfaces `os.environ` (Python's default repr on
     `KeyError` etc.) would put it in stdout/stderr.
  2. A misbehaving agent that runs `env`-equivalent introspection writes
     its output to stdout, which lands in the per-task log under
     `logs/agents/task-*.log` in cleartext. Anyone with read access on
     Legion (admins, Duet host's screen-share, future remote-access
     scenarios) can read it.
- **Why:** Local file leak of a credential the project explicitly
  treats as secret (`API-Key-Claude.txt` is gitignored). The current
  log-on-disk is the easiest exfil path.
- **Fix:** Add a redactor:
  ```python
  _SECRET_PATTERNS = [
      re.compile(r"sk-ant-[A-Za-z0-9_\-]{40,}"),
      re.compile(r"ANTHROPIC_API_KEY\s*=\s*\S+"),
      re.compile(r"(?i)api[\-_]?key[\"'\s:=]+[A-Za-z0-9_\-]{20,}"),
  ]
  def _redact(s: str) -> str:
      for p in _SECRET_PATTERNS:
          s = p.sub("[REDACTED-SECRET]", s)
      return s
  ```
  Wrap stdout/stderr with `_redact(...)` before write_text.
- **Action:** Proposal `P-audit4-m03-task-log-redact` filed for Agent 2.

**M-04 - `web/js/dashboard.js` injects activity-feed timestamps via `innerHTML` template**
- **File:line:** `web/js/dashboard.js:113-118`.
- **What's wrong:** `span.innerHTML = '<span class="ev-glyph">${glyph}</span><span class="ev-ts">${ts}</span>...'`.
  `glyph` is hardcoded by `_opGlyph()` - safe. `ts = (e.ts || "").slice(11, 19)`
  - pulled from `/api/activity` events, which are populated from
  `task_queue.jsonl` records. Today the timestamps are server-generated
  ISO strings, but the `slice(11, 19)` doesn't validate format - a future
  agent payload that overrides `ts` (or a corrupted line that survives the
  audit3 M-04 logging guard) could land HTML in there. The two
  `textContent` assignments on lines 119-120 do this correctly; the
  template should follow the same pattern.
- **Why:** Defense-in-depth XSS hardening for the kiosk. The dashboard
  is on a LAN-only origin today, but the kiosk runs unsandboxed Edge
  in fullscreen - any script execution there can keylog the user, hit
  the supervisor's `/api/*` from same-origin, etc.
- **Fix:** Build the structure with `createElement` and
  `textContent`:
  ```js
  const g = document.createElement("span"); g.className = "ev-glyph"; g.textContent = glyph;
  const t = document.createElement("span"); t.className = "ev-ts";    t.textContent = ts;
  const o = document.createElement("span"); o.className = "ev-op";    o.textContent = op;
  const k = document.createElement("span"); k.className = "ev-kind";  k.textContent = e.event || "";
  span.append(g, t, o, k);
  ```
- **Action:** Proposal `P-audit4-m04-activity-feed-no-innerhtml` filed for Agent 5.

### LOW / INFO

**L-01 - `lib/ddragon/fetch.py` does not deduplicate concurrent pulls of the same bundle**
- **File:line:** `lib/ddragon/fetch.py` `_pull` / cache-read pair.
- **What's wrong:** Two Agent 4 / Agent 5 spawns racing on a cold cache
  both miss, both hit DDragon, both write `tmp → replace`. The replace is
  atomic so the file is never corrupt, but each spawn pays one extra HTTP
  RTT and one redundant network roundtrip. Phase 3 supervisor is
  single-process today, but ephemeral spawns are subprocesses so the
  in-process `threading.Lock` proposed in subagent feedback wouldn't help
  cross-process anyway. A file-lock (`portalocker` or `msvcrt.locking`)
  on `<bundle>.json.lock` is the right fix if we want this.
- **Why:** Cosmetic perf only. Not a correctness problem. Filing as
  INFO so it doesn't get re-flagged in future audits - the cross-process
  nature is the real gating constraint.
- **Action:** No proposal. Logged here as a known quantity.

**L-02 - `lib/scrapers/_base.py` `_load_robots` not lock-protected**
- **File:line:** `lib/scrapers/_base.py:45-60`.
- **What's wrong:** Same concurrent-pull pattern as L-01 - two callers
  on a cold robots state both fetch. `RobotFileParser` mutation is
  thread-naive. In a single-process scraper run (today's reality) this
  is a benign duplicate fetch; if the scraper is ever fanned out across
  threads or processes the duplicate goes from cosmetic to potentially
  rate-limit-tripping at the target.
- **Why:** Same as L-01 - Phase 3 single-process topology means this
  is latent, not active.
- **Action:** No proposal. Already noted in audit 3's "Deferred"
  section under the same multi-process caveat.

**L-03 - `lib/http/client.py` blocklist not auto-reloaded on file modification**
- **File:line:** `lib/http/client.py:96-120`.
- **What's wrong:** The blocklist is loaded once in `__init__` and only
  refreshed when `reload_blocklist()` is explicitly called. Agent 6's
  charter grants autonomous edits to the file, but a stale supervisor
  process between an Agent 6 edit and the next supervisor restart will
  not see the change.
- **Why:** Documented design - the comment on line 119 says "Agent 6
  calls this after editing blocklist.json." But there's no programmatic
  enforcement, and Agent 6 ephemeral sessions can't reach into the
  long-running supervisor's `HttpClient` instance.
- **Fix (option A - file mtime check):** In `request()`, stat the
  blocklist path and reload if mtime changed. Cheap (~1 syscall per
  outbound request).
- **Fix (option B - supervisor SIGHUP-equivalent):** Have the supervisor
  poll the blocklist mtime in `_dispatch_loop` and call
  `client.reload_blocklist()` itself.
- **Action:** Proposal `P-audit4-l03-blocklist-mtime-reload` filed for
  Agent 2 (option A - simpler, no new wiring).

**L-04 - `agents/agent5_ui/champion_fallback.py` SQLite connection not closed in error path**
- **File:line:** `agents/agent5_ui/champion_fallback.py:117-127`.
- **What's wrong:** `conn = sqlite3.connect(...); ... .fetchone()`; if
  any non-`sqlite3.Error` exception fires between the connect and the
  explicit `conn.close()` on line 124, conn leaks. In practice all
  exceptions from execute/fetchone are `sqlite3.Error` subclasses, so
  this is theoretical.
- **Fix:** `with sqlite3.connect(...) as conn:` - context manager
  closes regardless.
- **Action:** No proposal. Marked LOW because it's theoretical and the
  fix is trivial enough that it can ride the next pass through this
  file.

**L-05 - `agents/agent2_backend/smb_push._backup_existing` may leave empty backup dir on copy failure**
- **File:line:** `agents/agent2_backend/smb_push.py:98-107`.
- **What's wrong:** `backup_dir.mkdir(parents=True, exist_ok=True)` runs
  before `shutil.copy2`; if the SMB share vanishes between mkdir and
  copy2, the empty directory is left on the share. Cosmetic - the next
  push picks a new timestamp directory.
- **Action:** No proposal. INFO.

## Subagent claims rejected as false-positive

For the record so these don't reappear in future passes:

| claim | location | verdict |
|-------|----------|---------|
| `_handle_push` early `ConnectionClosed` leaves ws in `_push_clients` | `ws_server.py:153-170` | **False.** The `try/finally` on line 162-170 always runs `discard(ws)` regardless of whether the initial-frame send raised. |
| `Scheduler.next_ready` requeue race against `approve()`/`_agent0_review()` | `scheduler.py:490-523` | **False.** Entire loop body is held under `with self._lock:`. Any concurrent caller must wait. Requeue heappush is inside the same lock window. |
| DDragon missing `championFull.json` is a defect | `lib/ddragon/fetch.py` `pull_all` | **Feature request, not defect.** Coaches read the data they need; nothing in Phase 3 requests `championFull` and adding it would expand DDragon traffic without a consumer. |
| `web/index.html` hardcodes WS hostname unsafely | `web/js/ws_client.js:4` | **False.** `WS_HOST = location.hostname \|\| "legion-pc.local"` - runtime hostname is preferred and the literal is only a fallback for `file://` or empty hostname. |
| `_handle_file_task` redaction is missing | (subagent placed at supervisor.py:1414) | **Misattributed.** The line cited is the *per-task log writer for ephemeral spawns*, not file-task handling. Real concern recast as M-03. |

## Autonomous actions taken this pass

1. **`agents/agent6_auditor/safeguards/startup_checks.md`** - updated
   the invariant table to reflect:
   - Invariant 5 / 6 (port preflight) are now `Yes` - `_port_available`
     at supervisor.py:286, called at supervisor.py:1499-1501.
   - Invariant 7 (queue corruption) now `Partial - bad lines logged
     loudly` per audit3 M-04.
   - Invariant 8 (decisions version check) now `Yes` -
     `_verify_decisions_version` at supervisor.py:258-282, called at
     supervisor.py:1489.
2. No `source_quality.json` changes; the third-audit fan-out (5 sources)
   is still correct.
3. No `blocklist.json` changes; no scrapers triggered the auto-escalate
   thresholds since the third audit.

## Proposals filed this pass

| id | severity | owner | target |
|----|----------|-------|--------|
| P-audit4-m01-icon-basename-guard       | medium | 2 | `lib/icons/downloader.py:69, 83, 97` |
| P-audit4-m02-modes-single-source       | medium | 2 | `analyzer.py:40`, `orchestrator.py:66`, `coaches/adaptation_hint.py`, `test_supervisor.py:21` |
| P-audit4-m03-task-log-redact           | medium | 2 | `agents/supervisor.py:1411-1423` |
| P-audit4-m04-activity-feed-no-innerhtml | medium | 5 | `web/js/dashboard.js:113-118` |
| P-audit4-l03-blocklist-mtime-reload    | low    | 2 | `lib/http/client.py:96-120, 181-211` |

## Queue state

- Third audit: 10 proposals → all 10 verified landed in code this pass.
- This pass: 5 proposals filed (no high/critical findings - code base
  is in better shape than at audit 3), 1 audit task completing.
- No safeguard updates required follow-up tasks; all autonomous actions
  applied directly.
