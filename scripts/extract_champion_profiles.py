"""
One-shot extractor: champion_profiles.py → data/champion_profiles/<Name>.json
Run once, then champion_profiles.py becomes the thin loader.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from champion_profiles import CHAMPIONS

out_dir = ROOT / "data" / "champion_profiles"
out_dir.mkdir(parents=True, exist_ok=True)

for name, data in CHAMPIONS.items():
    (out_dir / f"{name}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

print(f"Wrote {len(CHAMPIONS)} champion files to {out_dir}")
