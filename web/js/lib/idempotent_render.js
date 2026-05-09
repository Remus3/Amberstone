// Formalize the sig-on-container render-dedup pattern used throughout the dashboard.
//
// Usage:
//   if (idempotentRender(container, sig)) return;  // skip — content unchanged
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
