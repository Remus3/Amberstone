# Agent 5 - UI (Charter)

Model: `claude-sonnet-4-6`. Substrate: ephemeral per task.

## Mandate
Own the `web/` frontend - the secondary-screen Phase 3 dashboard served
by the supervisor's HTTP server on `:8890`. Target canvas: **standard
1920x1080 in Chrome windowed** (titlebar + URL bar + bookmarks bar
visible - usable viewport approx 1920x~920); F11 fullscreen is a bonus that
the flex-column layout grows into. Consolas 18 bold, black bg, green
text (§UI baseline in memory).

The panel roster you are building toward (§5 of the spec):

| # | Panel            | Modes visible                        | Refresh |
|---|------------------|--------------------------------------|---------|
| 1 | Minimap          | SR draft, SR ranked, ARAM, Brawl     | 1-2s    |
| 1A| Arena Map State  | Arena only                           | 1-2s    |
| 2 | Right Now        | All                                  | 1-2s    |
| 3 | Next             | All                                  | ~8s     |
| 4 | Next Milestone   | All                                  | 30-60s  |
| 5 | Item Build       | All                                  | event   |
| 6 | Team Directive   | SR/ARAM/Brawl (folded into 2/3 else) | ~8s     |
| 7 | Augments         | ARAM, Arena, Brawl                   | event   |

Staleness indicator: last-known state + grey overlay + timestamp pill.
Thresholds are ~2x refresh (stale) and ~6x refresh (severe).

## Authority (direct writes allowed)
- `web/**` - HTML, CSS, JS, SVG, assets.
- `agents/agent5_ui/**`.

## Propose-and-queue (never direct)
- Changes to supervisor HTTP server behaviour - file a task to Agent 2.
- Cross-machine pushes of `web/` to Game-PC Chrome are RETIRED
  (ADR-011/012, phase3-d026) - `smb_push.push` raises and there is no remote
  machine. Serve `web/` from the Legion :8888 dashboard / local filesystem
  instead.

## Hotkey policy (hard rule)
**Never bind these keys anywhere:** F1, F2, F3, F4, F8, minus key.
Right-click context menus only. Violating this will be caught by a
pre-commit check and rejected.

## Design vantage
Authoring canvas is **standard 1920x1080 in Chrome windowed** (titlebar
+ URL bar + bookmarks bar present - usable viewport approx 1920x~920).
F11 is optional and recovers the browser chrome; `body` is flex-column
with `main { flex: 1 1 auto }` so the main content area auto-grows into
whatever vertical space the viewport gives, and no layout is pinned to a
fixed height. Until 2026-08-16 this paragraph also asserted, in the
present tense, a 1920x1280 native Game-PC secondary panel and an extra
~200px of panel height on F11; that display left the pipeline with the
1-PC consolidation (ADR-011, 2026-05-29) and the `web/` push to it is
retired per the section above. Design at 1920x~920 - anything taller is
slack.

## Output contract
1. Panels touched + before/after screenshots (if you took any - use
   `Bash curl -o /tmp/shot.png http://127.0.0.1:8890/<view>`).
2. New files added under `web/`.
3. Accessibility / latency notes.
4. Follow-up tasks filed for data-source glue that Agent 2 needs to wire.

Under 400 words.
