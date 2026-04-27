// Phase 3 WS stub — subscribes to /push and paints the last frame.
// Real UI is Agent 5's deliverable.
(function () {
  const WS_HOST = location.hostname || "legion-pc.local";
  const WS_PORT = 8891;
  const WS_URL = `ws://${WS_HOST}:${WS_PORT}/push`;

  const pill = document.getElementById("status-pill");
  const ep = document.getElementById("ws-endpoint");
  const state = document.getElementById("ws-state");
  const lastHb = document.getElementById("ws-last-hb");
  const counter = document.getElementById("ws-frame-count");
  const lastFrame = document.getElementById("last-frame");
  ep.textContent = WS_URL;

  let frameCount = 0;
  let lastHbTs = 0;
  let staleTimer = null;

  function setPill(label, cls) {
    pill.textContent = label;
    pill.className = `pill ${cls}`;
  }

  function markStale() {
    setPill("stale", "stale");
    state.textContent = "stale";
  }

  // Audit P-audit3-l01 (2026-04-22): exponential backoff with jitter so
  // a server restart doesn't trigger a reconnect storm from multiple
  // kiosks / tabs. Sequence: 1.5 → 3 → 6 → 12 → 30s ceiling, each with
  // +/- 25% jitter. Reset to the base delay on any successful open.
  const BACKOFF_MS = [1500, 3000, 6000, 12000, 30000];
  let backoffIdx = 0;
  function nextBackoff() {
    const base = BACKOFF_MS[Math.min(backoffIdx, BACKOFF_MS.length - 1)];
    backoffIdx = Math.min(backoffIdx + 1, BACKOFF_MS.length - 1);
    // ±25% jitter
    const jitter = (Math.random() - 0.5) * 0.5 * base;
    return Math.max(500, Math.round(base + jitter));
  }

  function connect() {
    setPill("connecting", "pending");
    state.textContent = "connecting";
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      setPill("connected", "connected");
      state.textContent = "open";
      backoffIdx = 0;     // reset on success
    };
    ws.onclose = () => {
      setPill("closed", "stale");
      state.textContent = "closed";
      setTimeout(connect, nextBackoff());
    };
    ws.onerror = () => {
      setPill("error", "stale");
    };
    ws.onmessage = (evt) => {
      let msg;
      try { msg = JSON.parse(evt.data); } catch { msg = { type: "raw", body: evt.data }; }
      if (msg.type === "heartbeat") {
        lastHbTs = msg.t || Date.now() / 1000;
        lastHb.textContent = new Date(lastHbTs * 1000).toLocaleTimeString();
        if (staleTimer) clearTimeout(staleTimer);
        staleTimer = setTimeout(markStale, 12000);
        return;
      }
      frameCount += 1;
      counter.textContent = String(frameCount);
      lastFrame.textContent = JSON.stringify(msg, null, 2);
    };
  }

  connect();
})();
