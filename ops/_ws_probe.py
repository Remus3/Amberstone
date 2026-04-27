"""Quick WS probe — connects to Phase 3 /push for 7s, dumps frame summary."""
import asyncio, json, sys
import websockets

async def go():
    frames = []
    async with websockets.connect("ws://127.0.0.1:8891/push") as ws:
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=7.0)
                frames.append(json.loads(msg))
        except asyncio.TimeoutError:
            pass
    print(f"collected {len(frames)} frames", flush=True)
    seen = {}
    for f in frames:
        seen[f.get("type", "?")] = seen.get(f.get("type", "?"), 0) + 1
    print("types:", seen, flush=True)
    for f in frames[:12]:
        t = f.get("type")
        if t == "heartbeat":
            print(f"  heartbeat  t={f.get('t')}", flush=True)
        elif t == "health":
            p = f.get("payload", {})
            print(f"  health     mode={p.get('mode')} aram={p.get('aram_mode')} alive={p.get('alive')}", flush=True)
        elif t == "state":
            p = f.get("payload", {})
            print(f"  state      src={f.get('source')} mode={f.get('mode')} action={str(p.get('action'))[:50]!r}", flush=True)

asyncio.run(go())
