// Formalize the sig-on-container render-dedup pattern used throughout the dashboard.
//
// Usage:
//   if (idempotentRender(container, sig)) return;  // skip - content unchanged
//   // ... rebuild container.innerHTML ...
//
// Returns true when the sig matches (caller should return early).
// Returns false when the sig differs, having already stamped the new sig on the container.
//
// The "direct sig on element" variant (dataset.sig) is used when callers manage
// their own rendering loop; this helper handles the guard + stamp in one call.
export function idempotentRender(container, sig) {
  if (!container) return true;
  if (container.dataset.sig === String(sig)) return true;
  container.dataset.sig = String(sig);
  return false;
}

// Compute a stable content signature from any set of values.
// Lightweight alternative to JSON.stringify for arrays of primitives.
export function makeSig(...parts) {
  return parts.map(p => (p == null ? "" : String(p))).join("|");
}

// Stream-level render gate (RC2 6.3). The per-container idempotentRender
// dedups one element; makeStreamGate dedups a whole push STREAM where the
// entire payload is the unit of change. The SSE intake (main.js) re-runs the
// full render pipeline on every event - including the 15s forced heartbeat
// (byte-identical data) and, at the L4 0.5s tick, near-duplicates. The gate
// holds the last signature so the caller can skip a redundant re-render while
// still updating liveness (state.lastSseTs) on every event.
//
// Usage:
//   const gate = makeStreamGate();
//   es.onmessage = (ev) => {
//     state.lastSseTs = Date.now();      // liveness ALWAYS
//     if (!gate.changed(ev.data)) return; // identical -> skip the pipeline
//     ... render ...
//   };
//
// changed(sig) returns true (and stamps) when sig differs from the last seen,
// false when identical. null/undefined coerce to a stable string (never throw).
export function makeStreamGate() {
  let last = null;
  return {
    changed(sig) {
      const s = sig == null ? "" : String(sig);
      if (s === last) return false;
      last = s;
      return true;
    },
    reset() { last = null; },
  };
}
