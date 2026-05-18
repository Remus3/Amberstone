"""Inspect the streamed RSC data in aggregator J pages to learn parse strategy."""
from pathlib import Path
import re
import json
import codecs

p = Path(r"C:/Riot Commander/data/meta_build/refresh_2026-05-02/_phase3_html/Akali.html")
b = p.read_text(encoding="utf-8", errors="replace")

# Pull every self.__next_f.push([N,"..."])  - the inner string is JS-string-escaped
# Use a non-greedy capture between the two outer quotes after [1, (or similar idx)
pat = re.compile(r'self\.__next_f\.push\(\[\d+,\s*"', re.S)
chunks: list[str] = []
i = 0
while True:
    m = pat.search(b, i)
    if not m:
        break
    start = m.end()
    # walk forward, respecting backslash escapes, until the matching closing "
    j = start
    while j < len(b):
        c = b[j]
        if c == "\\":
            j += 2
            continue
        if c == '"':
            chunks.append(b[start:j])
            i = j + 1
            break
        j += 1
    else:
        break

print("chunks:", len(chunks))
combined = ""
for c in chunks:
    try:
        # decode JS-string escapes
        combined += codecs.decode(c.encode("utf-8"), "unicode_escape")
    except Exception:
        combined += c

out = Path(r"C:/Riot Commander/data/meta_build/refresh_2026-05-02/_phase3_html/_akali_combined.txt")
out.write_text(combined, encoding="utf-8")
print("combined len:", len(combined))

# look for keywords
for kw in [
    "ideal_core",
    "core_items",
    "prismatic",
    "augment",
    "winRate",
    "win_rate",
    "place",
    "duo",
    "Hemomancer",
    "Reverberation",
    "Moonflair",
    "external_tier",
    "tier",
    '"build"',
    "boots",
    "matches",
    "Akali",
]:
    idx = combined.find(kw)
    print(f"{kw}: {idx}", combined[max(0, idx-30):idx+80].replace("\n", " ") if idx > 0 else "")
