// Overlay change-pulse hook (HZ-D1, docs/ELECTRON_OVERLAY.md sec 4B + 7).
//
// The in-game overlay is a passive HUD - the operator plays, they do not
// stare at it. When a mounted overlay panel's rendered content changes
// (new coach call, DS build rebuild landing, a callout firing), its
// container gets the .ov-pulse class for ~1.2s so the one-shot edge-glow
// keyframe in web/css/overlay.css draws peripheral vision. This is the
// "didn't notice mid-game" fix from the overlay plan.
//
// Discipline:
//   - active ONLY when body[data-shell="overlay"]; initOverlayPulse() is
//     a no-op otherwise (and main.js only calls it on the overlay route);
//   - per-container throttle: a render burst (initial fixture landing,
//     SSE reconnect replay) pulses at most once per THROTTLE_MS window;
//   - observers watch childList + characterData only - NO attribute
//     observation, so toggling the pulse class itself can never feed
//     back into the observer;
//   - GPU-light: the glow is a one-shot box-shadow animation, no loop.

const PULSE_CLASS = "ov-pulse";
const PULSE_MS = 1200;     // matches the 1.2s ov-pulse-edge keyframe
const THROTTLE_MS = 1500;  // min gap between pulses per container

// Observed mount -> the container the glow lands on. container=null
// means the mount element glows itself (the rn-* strip mounts carry
// their own card chrome in overlay mode).
const TARGETS = [
  { mount: "am-call-body",  container: ".am-pane-call" },
  { mount: "am-build-body", container: ".am-pane-build" },
  { mount: "rn-lead",       container: null },
  { mount: "rn-choices",    container: null },
  { mount: "rn-callouts",   container: null },
];

function _wire(mountEl, containerEl) {
  const slot = { last: 0, timer: null };
  const obs = new MutationObserver(() => {
    const now = Date.now();
    if (now - slot.last < THROTTLE_MS) return;
    slot.last = now;
    containerEl.classList.remove(PULSE_CLASS);
    void containerEl.offsetWidth; // restart the keyframe cleanly
    containerEl.classList.add(PULSE_CLASS);
    if (slot.timer) clearTimeout(slot.timer);
    slot.timer = setTimeout(
      () => containerEl.classList.remove(PULSE_CLASS), PULSE_MS);
  });
  obs.observe(mountEl, {
    childList: true, subtree: true, characterData: true,
  });
  return obs;
}

// Wire observers on the overlay panel mounts. Returns the number of
// mounts wired (0 when not in overlay mode or no mounts exist - both
// fail-soft, never throws).
export function initOverlayPulse() {
  if (!document.body || document.body.dataset.shell !== "overlay") return 0;
  let wired = 0;
  for (const t of TARGETS) {
    const mount = document.getElementById(t.mount);
    if (!mount) continue;
    const container = t.container
      ? (mount.closest(t.container) || document.querySelector(t.container))
      : mount;
    if (!container) continue;
    _wire(mount, container);
    wired += 1;
  }
  return wired;
}
