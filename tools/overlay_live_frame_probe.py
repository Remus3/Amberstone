"""Live-frame probe for the w-nextbuy overlay widget + the OQ16 90s/10s gauge cadence.

Ground-truth read of the RUNNING rc-shell overlay via CDP (the technique in
memory reference_overlay_live_verify_technique) cross-checked against live
/api/state. Screenshots cannot prove these - the widget rows are text and the
alert tier is a data-attribute, so the DOM is the authority.

Prereqs:
  1. rc-shell relaunched with --remote-debugging-port=9222 --remote-allow-origins=*
     (a NEW overlay JS module is NOT hot-reloaded; a full relaunch is required).
  2. A live SR game in progress. ARAM/Arena do not exercise BARON or the
     trinket row, so SR is the only mode that covers every acceptance line.

Usage:
  python tools/overlay_live_frame_probe.py            # one sample
  python tools/overlay_live_frame_probe.py --watch 20 # sample every 5s, 20 times
"""

from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.request

import websocket

CDP_LIST = "http://127.0.0.1:9222/json/list"
API_STATE = "https://127.0.0.1:8888/api/state"

# Reads the three NEXT BUY rows, the objective-gauge alert tiers, and the mount
# geometry (a changed height between samples IS a reflow).
PAGE_EXPR = r"""
(() => {
  const out = {shell: document.body ? document.body.dataset.shell || null : null};
  const nb = document.getElementById('am-next-buy');
  out.nextbuy = {present: !!nb, hidden: nb ? nb.hidden : null};
  if (nb) {
    const r = nb.getBoundingClientRect();
    out.nextbuy.rect = {x: r.x, y: r.y, w: r.width, h: r.height};
    out.nextbuy.rows = [...nb.querySelectorAll('[data-nb-row]')].map(el => ({
      key: el.dataset.nbRow,
      state: el.dataset.nbState || '',
      label: (el.querySelector('.nb-k') || {}).textContent || '',
      value: (el.querySelector('.nb-v') || {}).textContent || '',
    }));
  }
  const og = document.getElementById('am-obj-gauges');
  out.gauges = og ? [...og.querySelectorAll('[data-obj]')].map(el => ({
    dial: el.dataset.obj,
    state: el.dataset.ogState || '',
    alert: el.dataset.ogAlert || '',
    eta: (el.querySelector('.og-eta') || {}).textContent || '',
  })) : null;
  return JSON.stringify(out);
})()
"""


def _cdp_eval(ws, expr, msg_id):
    ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True, "awaitPromise": True},
    }))
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == msg_id:
            res = msg.get("result", {}).get("result", {})
            return json.loads(res.get("value") or "{}")


def _api_state():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(API_STATE, context=ctx, timeout=5) as fh:
        return json.load(fh)


def sample(ws, msg_id):
    page = _cdp_eval(ws, PAGE_EXPR, msg_id)
    st = _api_state()
    lc = st.get("liveclient") or {}
    # /api/state.liveclient is the FLATTENED block built by
    # dashboard/_liveclient.py:114 liveclient_summary() (attached at
    # dashboard/_state_builder.py:687), NOT the raw Live Client :2999 payload.
    # Gold lands at out["gold"] (_liveclient.py:148) and the clock at
    # out["game_time_s"] (_liveclient.py:144). The raw activePlayer.currentGold
    # / gameData.gameTime paths this probe used to read never exist here and
    # always read null - that is the widget-vs-probe null the 2026-07-23
    # WAKEUP flagged as unconfirmed.
    return {
        "mode_key": st.get("mode_key"),
        "game_time_s": lc.get("game_time_s"),
        "current_gold": lc.get("gold"),
        "page": page,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=1, help="number of samples")
    ap.add_argument("--every", type=float, default=5.0, help="seconds between samples")
    args = ap.parse_args()

    targets = json.load(urllib.request.urlopen(CDP_LIST))
    if not targets:
        raise SystemExit("no CDP target - is rc-shell running with --remote-debugging-port=9222?")
    ws = websocket.create_connection(targets[0]["webSocketDebuggerUrl"],
                                     origin="http://127.0.0.1:9222")
    heights = set()
    try:
        for i in range(args.watch):
            row = sample(ws, i + 1)
            h = ((row["page"].get("nextbuy") or {}).get("rect") or {}).get("h")
            if h:
                heights.add(round(h, 1))
            print(json.dumps(row, indent=2))
            if i + 1 < args.watch:
                time.sleep(args.every)
    finally:
        ws.close()
    if len(heights) > 1:
        print(f"REFLOW: #am-next-buy height changed across samples: {sorted(heights)}")
    elif heights:
        print(f"NO REFLOW: #am-next-buy height stable at {heights.pop()}px")


if __name__ == "__main__":
    main()
