"""Aggregate per-champion verdicts into the D1 deliverable.

Reads ops/audit/ds_cross_eval/verdicts/*.json -> writes REPORT.md (coverage,
per-scorer severity rollup, MISMATCH roster, grouped nominations) anchored to
SYSTEMIC_FINDINGS.md. Robust to partial roster. Read-only over verdicts. ASCII.

Usage: python tools/ds_cross_eval/aggregate.py
"""
from __future__ import annotations

import glob
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:/Riot Commander")
BASE = ROOT / "ops" / "audit" / "ds_cross_eval"
ROSTER = 172


def load() -> list:
    out = []
    for f in sorted(glob.glob(str(BASE / "verdicts" / "*.json"))):
        try:
            out.append(json.loads(Path(f).read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            out.append({"champion": Path(f).stem, "scorer": "?",
                        "severity": "PARSE_ERR", "headline": str(exc),
                        "nominated_retune": ""})
    return out


def main() -> int:
    v = load()
    n = len(v)
    sev = Counter(x.get("severity") for x in v)
    by_scorer = defaultdict(Counter)
    for x in v:
        by_scorer[x.get("scorer", "?")][x.get("severity")] += 1

    mism = [x for x in v if x.get("severity") == "MISMATCH"]
    minor = [x for x in v if x.get("severity") == "MINOR"]
    noms = [x for x in v if (x.get("nominated_retune") or "").strip()]

    lines = []
    lines.append("# DS comprehensive per-champion cross-eval - D1 REPORT")
    lines.append("")
    lines.append(f"Coverage: {n}/{ROSTER} champions judged "
                 f"({100.0 * n / ROSTER:.1f}%).")
    lines.append(f"Severity: {dict(sev)}")
    lines.append("")
    lines.append("Gate: report-first (Gemini-locked). Anchor: rewind WIN "
                 "outcomes, mode-segregated (owned n>=8 else all-player else "
                 "synthetic). Self-rune scope only. Root causes: "
                 "SYSTEMIC_FINDINGS.md.")
    lines.append("")
    lines.append("## Per-scorer severity rollup")
    lines.append("")
    lines.append("| scorer | OK | MINOR | MISMATCH |")
    lines.append("|---|---|---|---|")
    for sc in sorted(by_scorer):
        c = by_scorer[sc]
        lines.append(f"| {sc} | {c.get('OK',0)} | {c.get('MINOR',0)} | "
                     f"{c.get('MISMATCH',0)} |")
    lines.append("")
    lines.append(f"## MISMATCH roster ({len(mism)})")
    lines.append("")
    for x in sorted(mism, key=lambda z: (z.get("scorer", ""), z.get("champion", ""))):
        lines.append(f"- **{x.get('champion')}** ({x.get('scorer')}, "
                     f"{x.get('evidence_tier_aram','?')}): {x.get('headline')}")
    lines.append("")
    lines.append(f"## MINOR roster ({len(minor)})")
    lines.append("")
    for x in sorted(minor, key=lambda z: (z.get("scorer", ""), z.get("champion", ""))):
        lines.append(f"- {x.get('champion')} ({x.get('scorer')}): "
                     f"{x.get('headline')}")
    lines.append("")
    lines.append(f"## Nominated retunes ({len(noms)}) - validate per-champion "
                 "vs rewind WIN outcomes before any Tier-2 code")
    lines.append("")
    for x in sorted(noms, key=lambda z: z.get("champion", "")):
        lines.append(f"- {x.get('champion')} ({x.get('scorer')}): "
                     f"{x.get('nominated_retune')}")
    lines.append("")

    (BASE / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"COVERAGE {n}/{ROSTER}  SEV {dict(sev)}")
    print(f"MISMATCH {len(mism)}  MINOR {len(minor)}  NOMS {len(noms)}")
    print("BY_SCORER", {k: dict(c) for k, c in by_scorer.items()})
    print(f"wrote {BASE / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
