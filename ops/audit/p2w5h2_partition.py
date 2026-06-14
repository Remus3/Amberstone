"""P2 W5 cycle 17: LPT partition of agents/daemon_slayer/tests into 6 disjoint
slices + non-ASCII census (the W5 lighter lens scope probe)."""
import json
import os

ROOT = "agents/daemon_slayer/tests"
BANNED = {0x2013, 0x2014, 0x201C, 0x201D, 0x2018, 0x2019}  # em/en dash + smart quotes

files = []
census = {}
banned_hits = {}
for root, _, fs in os.walk(ROOT):
    if "__pycache__" in root:
        continue
    for f in fs:
        if not f.endswith(".py"):
            continue
        p = os.path.join(root, f).replace(os.sep, "/")
        text = open(p, encoding="utf-8", errors="replace").read()
        loc = text.count("\n") + 1
        files.append((loc, p))
        non = sorted({hex(ord(c)) for c in text if ord(c) > 127})
        if non:
            census[p] = non
        bh = sorted({hex(ord(c)) for c in text if ord(c) in BANNED})
        if bh:
            banned_hits[p] = bh

files.sort(reverse=True)
bins = [[] for _ in range(6)]
load = [0] * 6
for loc, p in files:
    i = load.index(min(load))
    bins[i].append(p)
    load[i] += loc

for i, b in enumerate(bins):
    print(f"SLICE {chr(65 + i)}: {len(b)} files / {load[i]} LOC")
print("total", len(files), "files /", sum(load), "LOC")
print("non-ascii files:", len(census), "| BANNED-glyph files:", len(banned_hits))
if banned_hits:
    print("BANNED:", json.dumps(banned_hits, indent=1))

json.dump(
    {chr(65 + i): bins[i] for i in range(6)},
    open("ops/audit/p2w5h2_slices.json", "w", encoding="utf-8"),
    indent=1,
)
json.dump(census, open("ops/audit/p2w5h2_nonascii_census.json", "w", encoding="utf-8"), indent=1)
print("-> ops/audit/p2w5h2_slices.json + p2w5h2_nonascii_census.json")
