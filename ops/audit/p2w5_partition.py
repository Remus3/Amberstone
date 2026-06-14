"""P2 W5 cycle 16: balanced LPT partition of tests/ into 6 disjoint slices."""
import json
import os

files = []
for root, _, fs in os.walk("tests"):
    if "__pycache__" in root:
        continue
    for f in fs:
        if f.endswith(".py"):
            p = os.path.join(root, f).replace(os.sep, "/")
            try:
                loc = sum(1 for _ in open(p, encoding="utf-8", errors="replace"))
            except OSError:
                loc = 0
            files.append((loc, p))

files.sort(reverse=True)
bins = [[] for _ in range(6)]
load = [0] * 6
for loc, p in files:
    i = load.index(min(load))
    bins[i].append(p)
    load[i] += loc

for i, b in enumerate(bins):
    print(f"SLICE {chr(65 + i)}: {len(b)} files / {load[i]} LOC")

json.dump(
    {chr(65 + i): bins[i] for i in range(6)},
    open("ops/audit/p2w5_slices.json", "w", encoding="utf-8"),
    indent=1,
)
print("total", len(files), "files /", sum(load), "LOC -> ops/audit/p2w5_slices.json")
