#!/usr/bin/env python
"""P3 ASCII-sweep census + scoper (DEEP-AUDIT phase P3).

Scans git-tracked AUTHORED files for non-ASCII codepoints, buckets the hits by
source tree, and flags the two real encoding-hazard classes:
  * BOM markers (UTF-8 BOM is PROTECTIVE on .ps1 - PS5.1 ANSI-decodes a no-BOM
    .ps1 and mojibakes any UTF-8 byte; it is clutter everywhere else).
  * .ps1 latent-mojibake risk = a no-BOM .ps1 that already holds a non-ASCII byte.

Upstream-data / generated / immutable trees are excluded (patch-refresh
regenerates them; sweeping is churn that the next extract undoes):
  data/, docs/_archive/, agent6 reports+proposals, *_phase3_html,
  *.log, generated csv.

This is the durable slicer for the remaining P3 encoding cycles - it mirrors the
cycle-16/17 partition harness. Run with no args for the full bucketed census.

Usage:
  python tools/p3_ascii_census.py            # full bucketed census
  python tools/p3_ascii_census.py --bom      # BOM + ps1-risk report only
"""
import collections
import os
import subprocess
import sys

ROOT = r"C:\Riot Commander"
AUTH_EXT = {'.py', '.js', '.css', '.md', '.ps1', '.txt', '.xml', '.bat', '.cmd'}
EXCL_PREFIX = ('docs/_archive/', 'data/',
               'agents/agent6_auditor/reports/', 'agents/agent6_auditor/proposals/')


def excluded(rel):
    fl = rel.lower()
    if fl.startswith(EXCL_PREFIX):
        return True
    if '/_phase3_html/' in fl or fl.endswith('.log') or '.log.' in fl:
        return True
    if fl.endswith('api_surface.csv'):
        return True
    return False


def tracked():
    out = subprocess.run(["git", "-C", ROOT, "ls-files"],
                         capture_output=True, text=True).stdout
    return out.splitlines()


def bucket_of(rel):
    fl = rel.lower()
    if fl.startswith('agents/daemon_slayer/') and '/tests/' not in fl:
        return 'ZZ_ds_engine(load-bearing-arrows)'
    if fl.startswith('agents/daemon_slayer/tests/') or fl.startswith('tests/'):
        return 'ZZ_tests(swept_c16_c17)'
    return fl.split('/')[0] if '/' in fl else 'ROOT'


def main():
    bom_only = '--bom' in sys.argv
    files = tracked()
    buckets = collections.defaultdict(list)
    bom8, utf16, ps1_bom, ps1_nonascii = [], [], {}, set()
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        if ext not in AUTH_EXT or excluded(rel):
            continue
        raw = open(os.path.join(ROOT, rel), 'rb').read()
        if raw[:3] == b'\xef\xbb\xbf':
            bom8.append(rel)
        elif raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
            utf16.append(rel)
        try:
            txt = raw.decode('utf-8')
        except UnicodeDecodeError:
            txt = raw.decode('utf-8', 'replace')
        cps = collections.Counter(f'U+{ord(c):04X}' for c in txt if ord(c) > 127)
        if ext == '.ps1':
            ps1_bom[rel] = raw[:3] == b'\xef\xbb\xbf'
            if cps:
                ps1_nonascii.add(rel)
        if cps:
            buckets[bucket_of(rel)].append((rel, sum(cps.values()), dict(cps)))

    print("=== BOM markers ===")
    print("UTF-8 BOM:", len(bom8))
    for f in bom8:
        tag = ' [.ps1 PROTECTIVE - keep]' if f.lower().endswith('.ps1') else ''
        print("  ", f, tag)
    print("UTF-16 (Task XML canonical - keep):", utf16)
    risk = sorted(f for f in ps1_nonascii if not ps1_bom.get(f))
    print("\n=== .ps1 LATENT MOJIBAKE RISK (no-BOM AND non-ASCII) ===")
    print("  ", risk if risk else "NONE")
    if bom_only:
        return
    for grp in sorted(buckets):
        tot = sum(n for _, n, _ in buckets[grp])
        print(f"\n### {grp}  ({len(buckets[grp])} files, {tot} non-ASCII)")
        if grp.startswith('ZZ_'):
            agg = collections.Counter()
            for _, _, cps in buckets[grp]:
                agg.update(cps)
            print("   codepoints:", dict(agg))
            continue
        for f, n, cps in sorted(buckets[grp], key=lambda x: -x[1]):
            print(f"   {n:4d} {f}  {cps}")


if __name__ == "__main__":
    main()
