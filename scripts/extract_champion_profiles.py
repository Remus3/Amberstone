"""
One-shot extractor: champion_profiles.py -> data/champion_profiles/<Name>.json
Run once, then champion_profiles.py becomes the thin loader.

That migration is done and this file stays as its record (repo review
2026-10-09, B27-02). champion_profiles.py now LOADS these files, so a re-run
reads every profile and writes the same bytes back (no diff). RM-1176:
importing this module runs nothing; `python scripts/extract_champion_profiles.py`
runs main(), and every write is atomic (core.polled_json.atomic_write_bytes)
because the loader reads these files at import.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.polled_json import atomic_write_bytes  # noqa: E402

OUT_DIR = ROOT / "data" / "champion_profiles"


def render(data: dict) -> bytes:
    """One profile's file bytes: indent 2, raw UTF-8, LF, no trailing newline."""
    return json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")


def main(out_dir: Path | None = None,
         champions: dict[str, dict] | None = None) -> int:
    """Write one <Name>.json per profile into ``out_dir`` (default OUT_DIR)."""
    if champions is None:
        from champion_profiles import CHAMPIONS
        champions = CHAMPIONS
    target = OUT_DIR if out_dir is None else Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for name, data in champions.items():
        atomic_write_bytes(target / f"{name}.json", render(data))
    print(f"Wrote {len(champions)} champion files to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
