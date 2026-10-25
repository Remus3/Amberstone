# m01 - champion_fallback reads a queue log that does not exist (medium)

Filed by Agent 6 full audit pass t-02760f99d1a0 (2026-10-25). Owner: Agent 2.

## Defect
agents/agent5_ui/champion_fallback.py:34 sets
_QUEUE_LOG_PATH = _PROJECT_ROOT / "data" / "task_queue.jsonl".
The queue lives at agents/state/task_queue.jsonl (scheduler.py:88
QUEUE_LOG = STATE_DIR / "task_queue.jsonl"). data/task_queue.jsonl does
not exist (ls 2026-10-25), so _try_recent_user_note() (:133) always
returns None at :136 and the "user typed 'playing Jinx'" tier of
current_champion() is dead. Live-reachable: agents/_supervisor_http.py
imports current_champion.

## Fix
```diff
-_QUEUE_LOG_PATH = _PROJECT_ROOT / "data" / "task_queue.jsonl"
+from agents.agent1_lead.scheduler import QUEUE_LOG as _QUEUE_LOG_PATH
```
(or `_PROJECT_ROOT / "agents" / "state" / "task_queue.jsonl"` if the
import cycle bites). Note the reader does a full readlines() of the
queue; tail-read the last ~64 KiB instead since the file grows until
compaction.

## Test
Point _QUEUE_LOG_PATH at the scheduler constant and assert equality; a
tmp queue with a user_text "playing Jinx" record returns "Jinx".
