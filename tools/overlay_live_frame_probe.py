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


# Stage + trinket mirrors of web/js/lib/next_buy_model.js (NB_STAGE:39-44,
# NB_TRINKETS:55-58, NB_TRINKET_FROM:50). Recorded per sample so the TRINKET
# acceptance line is adjudicable from the capture alone: without owned_items
# and the stage they imply, a "-" row is indistinguishable from a gate miss
# and a correctly-gated quiet row (the 2026-07-23 session lost criterion 2 to
# exactly this gap - 260 samples, no way to tell which).
_EARLY_CLOCK_S = 600
_LATE_CLOCK_S = 1320
_MID_OWNED = 2
_LATE_OWNED = 4
_STAGE_ORDER = {"early": 0, "mid": 1, "late": 2}
_TRINKETS = {"farsight alteration", "stealth ward", "oracle lens",
             "scrying orb", "warding totem"}
_TRINKET_FROM = {"stealth ward", "warding totem"}


def _stage_for(clock_s, owned_count):
    """stageFor(next_buy_model.js:67-75): the FURTHER along of clock and count."""
    by_clock = ("early" if not isinstance(clock_s, (int, float))
                or clock_s < _EARLY_CLOCK_S
                else "mid" if clock_s < _LATE_CLOCK_S else "late")
    by_owned = ("early" if owned_count < _MID_OWNED
                else "mid" if owned_count < _LATE_OWNED else "late")
    return by_clock if _STAGE_ORDER[by_clock] >= _STAGE_ORDER[by_owned] else by_owned


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
    owned = [x for x in (lc.get("owned_items") or []) if x]
    completed = [x for x in owned if str(x).strip().lower() not in _TRINKETS]
    clock = lc.get("game_time_s")
    stage = _stage_for(clock, len(completed))
    sr_items = lc.get("sr_items") or []
    return {
        "mode_key": st.get("mode_key"),
        "game_time_s": clock,
        "current_gold": lc.get("gold"),
        # Every input the TRINKET + GOLD acceptance lines are judged against.
        "owned_items": owned,
        "completed_count": len(completed),
        "stage": stage,
        "holds_upgradable_trinket": any(
            str(x).strip().lower() in _TRINKET_FROM for x in owned),
        # The GOLD row targets the first sr_items row with next===true
        # (next_buy_model.js:12-16). No such row means the widget CANNOT
        # render a countdown, which is an upstream feed fact, not a widget bug.
        "next_item": next((r.get("name") for r in sr_items if r.get("next")), None),
        "sr_items_len": len(sr_items),
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
            # flush per sample: a redirected stdout is block-buffered, so a
            # `> file.json` capture lags reality by minutes. The 2026-07-23
            # session read a 7-minute-stale baron ETA off exactly that lag.
            print(json.dumps(row, indent=2), flush=True)
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
