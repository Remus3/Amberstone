"""
scripts/download_aram_icons.py
Downloads all ARAM-available item icons from Riot Data Dragon CDN.
Run once to populate data/icons/aram_items/ for the item build panel.

dashboard/routes_static.py serves that directory at /icons/items/<slug>.png,
and web/legacy_index.html `itemSlug` builds the slug from the item NAME, so
`slugify` below must stay the same rule (RM-1173). Nothing runs at import:
the download is `main()` (RM-1173). Each icon is written through
core.polled_json.atomic_write_bytes, because the dashboard serves the
directory while it fills.
"""
import json
import re
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.polled_json import atomic_write_bytes  # noqa: E402

OUT_DIR = ROOT / "data" / "icons" / "aram_items"
DDRAGON = "https://ddragon.leagueoflegends.com"

# Filter: items available on Howling Abyss (map ID 12)
ARAM_MAP_ID = "12"

# Common ARAM items whose slug is printed after a run, as a spot check.
COMMON = [
    "Blade of The Ruined King", "Infinity Edge", "Kraken Slayer",
    "Guinsoo's Rageblade", "Phantom Dancer", "Runaan's Hurricane",
    "Berserker's Greaves", "Mortal Reminder", "Lord Dominik's Regards",
    "Immortal Shieldbow", "Wit's End", "Quicksilver Sash",
]


def fetch_json(url: str, timeout: float):
    return json.loads(urllib.request.urlopen(url, timeout=timeout).read())


def slugify(name: str) -> str:
    """Item name to its icon slug: the web/legacy_index.html itemSlug rule.

    Strips "'s" only at a word end, then any other apostrophe, so
    "Jak'Sho, The Protean" is jaksho-the-protean (the old "'s?" rule made it
    jakho-the-protean, which the dashboard never requests).
    """
    s = re.sub(r"'s\b|'", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def aram_items_from(items_raw: dict) -> dict:
    """item id -> {"name", "img"} for every purchasable final ARAM item."""
    aram_items = {}
    for item_id, item in items_raw.get("data", {}).items():
        maps = item.get("maps", {})
        gold = item.get("gold", {})
        name = item.get("name", "")
        # Must be: available on ARAM map, purchasable, have a name and image
        item_depth = item.get("depth", 1)
        # Skip components (depth 1 = basic, depth 2 = mid-tier components)
        # depth 3 = fully completed items we want to show
        # Exception: some ARAM-unique items have depth 1 but no recipe
        is_final = item_depth >= 3 or (item_depth >= 1 and not item.get("from"))
        if (maps.get(ARAM_MAP_ID)
                and gold.get("purchasable", False)
                and name
                and item.get("image", {}).get("full")
                and is_final):
            aram_items[item_id] = {
                "name": name,
                "img":  item["image"]["full"],
            }
    return aram_items


def download_icons(aram_items: dict, version: str,
                   out_dir: pathlib.Path) -> tuple[int, int, int]:
    """Fetch each missing icon; returns (downloaded, skipped, failed)."""
    downloaded = 0
    skipped = 0
    failed = 0
    for item_id, info in sorted(aram_items.items()):
        name = info["name"]
        img_file = info["img"]
        slug = slugify(name)
        out_path = out_dir / f"{slug}.png"

        if out_path.exists():
            skipped += 1
            continue

        url = f"{DDRAGON}/cdn/{version}/img/item/{img_file}"
        try:
            data = urllib.request.urlopen(url, timeout=15).read()
            atomic_write_bytes(out_path, data)
            downloaded += 1
            if downloaded % 25 == 0:
                print(f"  Downloaded {downloaded} items so far... ({name})")
            time.sleep(0.05)  # be nice to the CDN
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL [{item_id}] {name}: {e}")
            failed += 1
    return downloaded, skipped, failed


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching Riot DDragon version list...")
    try:
        versions = fetch_json(f"{DDRAGON}/api/versions.json", timeout=10)
        version = versions[0]
        print(f"Using version: {version}")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR fetching versions: {e}")
        return 1

    print("Fetching item data...")
    try:
        items_raw = fetch_json(
            f"{DDRAGON}/cdn/{version}/data/en_US/item.json", timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR fetching item data: {e}")
        return 1

    aram_items = aram_items_from(items_raw)
    print(f"Found {len(aram_items)} ARAM-available items")

    downloaded, skipped, failed = download_icons(aram_items, version, OUT_DIR)

    print("\nDone.")
    print(f"  New downloads:  {downloaded}")
    print(f"  Already cached: {skipped}")
    print(f"  Failed:         {failed}")
    print(f"  Output dir:     {OUT_DIR}")

    # Print a slug-mapping for common ARAM items not matching expected names
    print("\nSlug mapping for common items:")
    for name in COMMON:
        slug = slugify(name)
        path = OUT_DIR / f"{slug}.png"
        status = "ok" if path.exists() else "MISSING"
        print(f"  {name!s:35} -> {slug}.png  {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
