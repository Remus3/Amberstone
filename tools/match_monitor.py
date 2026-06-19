"""
match_monitor.py - Background monitor for live match + champ-select observability.

Polls Legion's relay caches every 3s. Prints concise one-line state updates
whenever a meaningful field changes (phase, champion, queue, game_time rounds,
hp/mana drops, kda changes, OCR call rate). Keeps the diff feed focused so
any anomaly is visible immediately.

Not a persistent agent; intended to be run in the foreground from the
monitoring Claude's Bash tool for the duration of a test match.
"""
import json
import ssl
import time
import urllib.request

_NOVERIFY = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_NOVERIFY.check_hostname = False
_NOVERIFY.verify_mode = ssl.CERT_NONE

H = {"X-RC-Token": "8e8f131e212b329438218eca27372dde"}
BASE = "http://127.0.0.1:8889"
DASH = "https://127.0.0.1:8888"

prev: dict = {}


def fetch(url: str, headers: dict | None = None) -> dict | list | None:
    req = urllib.request.Request(url, headers=headers or {})
    ctx = _NOVERIFY if url.startswith("https:") else None
    try:
        with urllib.request.urlopen(req, timeout=2, context=ctx) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def snap() -> dict:
    out: dict = {"t": time.time()}
    f = fetch(f"{BASE}/latest-frame/meta", H)
    if f and "ts" in f: out["frame_age"] = round(time.time() - f["ts"], 1)
    l = fetch(f"{BASE}/latest-lcu", H)
    if l and "data" in l:
        d = l["data"]
        out["lcu_phase"] = d.get("phase")
        cs = d.get("champ_select") or {}
        out["cs_champ"] = cs.get("my_champion")
        out["cs_locked"] = cs.get("my_completed")
        out["cs_aram"] = cs.get("is_aram")
    lc = fetch(f"{BASE}/latest-liveclient", H)
    if lc and "data" in lc:
        d = lc["data"]
        gd = d.get("gameData") or {}
        ap = d.get("activePlayer") or {}
        cst = ap.get("championStats") or {}
        me = next((p for p in (d.get("allPlayers") or [])
                   if p.get("summonerName") == ap.get("summonerName")), None)
        out["ig_mode"]  = gd.get("gameMode")
        out["ig_time"]  = int(gd.get("gameTime", 0))
        out["ig_hp"]    = int(cst.get("currentHealth", 0))
        out["ig_hp_mx"] = int(cst.get("maxHealth", 0))
        out["ig_gold"]  = int(ap.get("currentGold", 0))
        out["ig_level"] = ap.get("level")
        if me:
            s = me.get("scores") or {}
            out["ig_kda"] = f'{s.get("kills",0)}/{s.get("deaths",0)}/{s.get("assists",0)}'
            out["ig_cs"]  = s.get("creepScore")
    return out


def diffs(a: dict, b: dict) -> list[str]:
    changes: list[str] = []
    watch = ("lcu_phase", "cs_champ", "cs_locked", "cs_aram",
             "ig_mode", "ig_level", "ig_kda", "ig_cs")
    for k in watch:
        if a.get(k) != b.get(k):
            changes.append(f"{k}: {a.get(k)} -> {b.get(k)}")
    # game time: print every 30s when in-game
    if b.get("ig_time") and (b.get("ig_time") // 30) != (a.get("ig_time", 0) // 30):
        changes.append(f"t={b['ig_time']}s hp={b.get('ig_hp')}/{b.get('ig_hp_mx')} "
                       f"gold={b.get('ig_gold')} cs={b.get('ig_cs')}")
    # stale relay
    if b.get("frame_age") is not None and b["frame_age"] > 4:
        changes.append(f"frame age {b['frame_age']}s (stale!)")
    return changes


def main() -> None:
    global prev
    print(f"[monitor] polling every 3s  base={BASE}")
    prev = snap()
    # Print initial state
    print(f"[init] {json.dumps({k:v for k,v in prev.items() if v is not None})}")
    while True:
        time.sleep(3.0)
        cur = snap()
        for line in diffs(prev, cur):
            ts = time.strftime("%H:%M:%S")
            print(f"[{ts}] {line}", flush=True)
        prev = cur


if __name__ == "__main__":
    main()
