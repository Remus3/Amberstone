"""
scripts/download_aram_icons.py
Downloads all ARAM-available item icons from Riot Data Dragon CDN.
Run once to populate data/icons/aram_items/ for the item build panel.
"""
import urllib.request
import json
import re
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).parent.parent
OUT_DIR = ROOT / "data" / "icons" / "aram_items"
OUT_DIR.mkdir(parents=True, exist_ok=True)

print("Fetching Riot DDragon version list...")
try:
    versions = json.loads(
        urllib.request.urlopen(
            "https://ddragon.leagueoflegends.com/api/versions.json",
            timeout=10
        ).read()
    )
    VERSION = versions[0]
    print(f"Using version: {VERSION}")
except Exception as e:  # noqa: BLE001
    print(f"ERROR fetching versions: {e}")
    sys.exit(1)

print("Fetching item data...")
try:
    items_raw = json.loads(
        urllib.request.urlopen(
            f"https://ddragon.leagueoflegends.com/cdn/{VERSION}/data/en_US/item.json",
            timeout=15
        ).read()
    )
except Exception as e:  # noqa: BLE001
    print(f"ERROR fetching item data: {e}")
    sys.exit(1)


def slugify(name: str) -> str:
    """Convert item name to filesystem-safe slug matching _ItemBuildCanvas._load_icon."""
    s = re.sub(r"'s?|'", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# Filter: items available on Howling Abyss (map ID 12)
ARAM_MAP_ID = "12"
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

print(f"Found {len(aram_items)} ARAM-available items")

# Download icons
downloaded = 0
skipped = 0
failed = 0

for item_id, info in sorted(aram_items.items()):
    name = info["name"]
    img_file = info["img"]
    slug = slugify(name)
    out_path = OUT_DIR / f"{slug}.png"

    if out_path.exists():
        skipped += 1
        continue

    url = f"https://ddragon.leagueoflegends.com/cdn/{VERSION}/img/item/{img_file}"
    try:
        data = urllib.request.urlopen(url, timeout=15).read()
        out_path.write_bytes(data)
        downloaded += 1
        if downloaded % 25 == 0:
            print(f"  Downloaded {downloaded} items so far... ({name})")
        time.sleep(0.05)  # be nice to the CDN
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL [{item_id}] {name}: {e}")
        failed += 1

print("\nDone.")
print(f"  New downloads:  {downloaded}")
print(f"  Already cached: {skipped}")
print(f"  Failed:         {failed}")
print(f"  Output dir:     {OUT_DIR}")

# Print a slug-mapping for common ARAM items not matching expected names
print("\nSlug mapping for common items:")
common = [
    "Blade of The Ruined King", "Infinity Edge", "Kraken Slayer",
    "Guinsoo's Rageblade", "Phantom Dancer", "Runaan's Hurricane",
    "Berserker's Greaves", "Mortal Reminder", "Lord Dominik's Regards",
    "Immortal Shieldbow", "Wit's End", "Quicksilver Sash",
]
for name in common:
    slug = slugify(name)
    path = OUT_DIR / f"{slug}.png"
    status = "✓" if path.exists() else "✗ MISSING"
    print(f"  {name!s:35} -> {slug}.png  {status}")
