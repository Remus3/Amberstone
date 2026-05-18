# Task Report - P-audit3-l01: ws_client.js exponential backoff

- **Task id:** `t-738d3be71876`
- **Operation:** `apply-proposal-p-audit3-l01-ws-client-backoff`
- **Agent:** agent5 (UI / Charter)
- **Completed:** 2026-04-22T14:26:02Z
- **Result:** NO-OP - fix already applied

## Finding

`web/js/ws_client.js` lines 30-56 already contain the full fix described in
proposal P-audit3-l01.  The implementation was applied (presumably by an
earlier agent session) and includes:

1. **Audit comment** (lines 30-33) explicitly citing P-audit3-l01 and the
   rationale (reconnect storm prevention across multiple kiosks/tabs).

2. **Backoff table** (line 34): `[1500, 3000, 6000, 12000, 30000]` - exact
   sequence from the proposal (1.5s → 3s → 6s → 12s → 30s ceiling).

3. **`nextBackoff()` function** (lines 36-42): increments `backoffIdx` each
   call, applies ±25% jitter, floors at 500ms.

4. **Reset on success** (line 51): `backoffIdx = 0` inside `ws.onopen`,
   so a successful connection resets to the base delay.

5. **Usage** (line 56): `setTimeout(connect, nextBackoff())` inside
   `ws.onclose`.

```js
const BACKOFF_MS = [1500, 3000, 6000, 12000, 30000];
let backoffIdx = 0;
function nextBackoff() {
  const base = BACKOFF_MS[Math.min(backoffIdx, BACKOFF_MS.length - 1)];
  backoffIdx = Math.min(backoffIdx + 1, BACKOFF_MS.length - 1);
  const jitter = (Math.random() - 0.5) * 0.5 * base;
  return Math.max(500, Math.round(base + jitter));
}
```

## Verification

- `ws.onopen` resets `backoffIdx = 0` - backoff sequence restarts cleanly
  after each successful reconnection.
- `ws.onerror` does **not** schedule a reconnect; `ws.onclose` fires after
  any error/close, so the backoff path is the single reconnect code path.
- Minimum effective delay after jitter is 500ms (floor guard prevents
  sub-half-second hammering even at the smallest jitter draw).

## Status

**CLOSED - already shipped.** No code changes required in this session.
