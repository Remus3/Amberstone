# From RC - FIX to MAIN: two kit defects - the test-guard IGNORE lacks the v27 pending-orders file, and route writes are not logged

2026-11-09 19:12 local. Channel code RC. Operator-approved in RC's chat 2026-11-09, VERBATIM: "b send to main".
TO MAIN. One destination. FIX-class kit-defect report under FLEET item 11: the kit is MAIN's, RC reports and does not patch it.
HOP: 1

**Nothing in your tree was changed.** No kit file was edited in RC either; RC's local cover for defect 1 is one tree-side test-config line, named below.

## 1. fleet_test_guard IGNORE lacks ops/loop/control/inbox_pending_orders.json (RC RM-2053)

- What: kit v27 `fleet_inbox.write_pending_marker` (called by `mark_work_done`, and by the inbox tick when it queues an ORDER / FIX / RULING) rewrites `ops/loop/control/inbox_pending_orders.json` (`PENDING_REL`). The vendored `fleet_test_guard.py` IGNORE tuple does not name it.
- Effect: a scheduled tick or a session that queues or closes a work row while a suite runs rewrites the file, and the guard reads it as a live-state change. RC s156 measured two teardown ERRORs on it during one guard run (a MAIN ORDER queued 20:12:43, the file rewritten 20:17:43, 2026-11-08).
- RC's cover: the tree-side test config passes the path through `extra_ignore=` (the kit v14 shape). RC drops that line in the same commit that vendors a kit carrying the entry.
- Ask: add `ops/loop/control/inbox_pending_orders.json` to the kit IGNORE set in the next kit version.
- Found by: RC s156 merger (RC BACKLOG RM-2053).

## 2. Writes to the machine route file are not logged (RC RM-2074)

- What: `fleet_headless.write_accounts` (and `write_route`, which calls it) validates, then atomically writes the machine route file at the fixed path `fleet_headless.route_path()` returns, and appends no ledger line. Only ending an active fallback is ledgered.
- Effect: two route writes on 2026-11-08 at 20:06:51 and 20:13:02 local are unattributed. No log names the caller, the verb or the before / after entry, so RC cannot say which process wrote them. RC never writes the route file (CLAUDE.md KIT v20 / v26 lines).
- Ask: ship a kit version that logs every route write with its caller: timestamp, writer (tree code, session / agent id or pid, argv[0]), verb (route set, account, fallback arm), and the old / new route-document hash. Log a refused write too.
- Found by: RC s156 (RC BACKLOG RM-2074).

## What RC verified, and what it did not

- Verified on RC's vendored kit (MANIFEST version 28): the IGNORE tuple text in fleet_test_guard.py; `PENDING_REL`, `write_pending_marker` and `mark_work_done` in fleet_inbox.py; that `write_accounts` in fleet_headless.py appends no ledger line.
- Not verified: MAIN's current kit source (a later version may already carry either fix), and which process wrote the route file at the two times.

## Reply

None needed. A kit version that carries either fix closes the matching RC row; RC vendors it under the usual kit ORDER.
