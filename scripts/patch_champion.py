"""
scripts/patch_champion.py - Modular champion data patcher for aram_champion_builds.json

Usage:
    python patch_champion.py --list                          # show all champions + tiers
    python patch_champion.py --show Lucian                   # show one champion's data
    python patch_champion.py --apply patches/lucian.json     # apply a champion patch file
    python patch_champion.py --validate                      # check all builds for issues
    python patch_champion.py --apply-all patches/            # apply all patch files in dir

Patch file format (patches/lucian.json):
{
  "champion": "Lucian",
  "aram_tier": "A",
  "build_note": "...",
  "core_items": ["Trinity Force", "Galeforce", "Navori Flickerblades"],
  "full_build":  ["Berserker's Greaves", "Trinity Force", ...],
  "vs_tanks":   "...",
  "vs_healing": "...",
  "vs_burst":   "..."
}
"""
import json
import sys
import argparse
import logging
from pathlib import Path

ROOT = Path(__file__).parent.parent
BUILDS_FILE = ROOT / "data" / "meta_build" / "aram_champion_builds.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("patch_champion")

# Items that must never appear in full_build (components)
BANNED_COMPONENTS = {
    "Dagger", "Long Sword", "Pickaxe", "B.F. Sword", "Amp Tome",
    "Brawler's Gloves", "Cloak of Agility", "Blasting Wand",
    "Null-Magic Mantle", "Chain Vest", "Cloth Armor", "Ruby Crystal",
    "Sapphire Crystal", "Needlessly Large Rod", "Fiendish Codex",
    "Vampiric Scepter", "Aether Wisp", "Recurve Bow", "Noonquiver",
    "Caulfield's Warhammer",
}

# Items that are mutually exclusive
MUTEX_PAIRS = [
    ("Lord Dominik's Regards", "Mortal Reminder"),
    ("Kraken Slayer", "Lord Dominik's Regards"),  # soft conflict - both anti-tank
]

# Crit items (Season 16)
CRIT_ITEMS = {
    "Infinity Edge": 25, "Rapid Firecannon": 25, "The Collector": 25,
    "Immortal Shieldbow": 25, "Galeforce": 20, "Hexoptics C44": 25,
    "Navori Flickerblades": 25, "Navori Quickblades": 20,
    "Phantom Dancer": 25, "Stormrazor": 25, "Essence Reaver": 25,
    "Yun Tal Wildarrows": 0,  # Season 16: now AS-focused, 0% crit
}

IE_ACTIVATION_THRESHOLD = 60  # IE passive needs 60%+ crit (excluding IE itself)


def load_builds() -> dict:
    return json.loads(BUILDS_FILE.read_text(encoding="utf-8"))


def save_builds(builds: dict) -> None:
    tmp = BUILDS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(builds, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(BUILDS_FILE)


def validate_build(champion: str, data: dict) -> list[str]:
    """Return list of issues found in a champion's build data."""
    issues = []
    fb = data.get("full_build", [])

    # Check for components
    for item in fb:
        if item in BANNED_COMPONENTS:
            issues.append(f"Component in full_build: {item!r}")

    # Check mutex pairs
    for a, b in MUTEX_PAIRS:
        if any(a in i for i in fb) and any(b in i for i in fb):
            issues.append(f"Mutex conflict: {a!r} and {b!r} both in full_build")

    # Check IE crit threshold
    if any("Infinity Edge" in i for i in fb):
        crit_without_ie = sum(
            CRIT_ITEMS.get(i, 0) for i in fb if "Infinity Edge" not in i
        )
        if crit_without_ie < IE_ACTIVATION_THRESHOLD:
            issues.append(
                f"IE without sufficient crit: only {crit_without_ie}% "
                f"(need {IE_ACTIVATION_THRESHOLD}% excluding IE)"
            )

    # Warn about empty full_build
    if not fb:
        issues.append("full_build is empty")

    return issues


def cmd_list(args) -> None:
    builds = load_builds()
    tiers = {}
    for k, v in builds.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        t = v.get("aram_tier", "?")
        tiers.setdefault(t, []).append(k)
    for tier in ("S", "A", "B", "C", "D", "?"):
        champs = sorted(tiers.get(tier, []))
        if champs:
            log.info("%s: %s", tier, ", ".join(champs))


def cmd_show(args) -> None:
    builds = load_builds()
    champ = args.champion
    data = builds.get(champ)
    if not data:
        log.error("Champion %r not found", champ)
        sys.exit(1)
    log.info(json.dumps({champ: data}, indent=2, ensure_ascii=False))
    issues = validate_build(champ, data)
    if issues:
        log.warning("Issues found:")
        for issue in issues:
            log.warning("  - %s", issue)


def cmd_validate(args) -> None:
    builds = load_builds()
    total_issues = 0
    for champ, data in builds.items():
        if champ.startswith("_") or not isinstance(data, dict):
            continue
        issues = validate_build(champ, data)
        if issues:
            log.warning("%s:", champ)
            for issue in issues:
                log.warning("  - %s", issue)
            total_issues += len(issues)
    if total_issues == 0:
        log.info("All builds validated - no issues found")
    else:
        log.warning("Total issues: %d", total_issues)


def cmd_apply(args) -> None:
    patch_file = Path(args.file)
    if not patch_file.exists():
        log.error("Patch file not found: %s", patch_file)
        sys.exit(1)

    patch = json.loads(patch_file.read_text(encoding="utf-8"))
    champ = patch.get("champion")
    if not champ:
        log.error("Patch file must have a 'champion' field")
        sys.exit(1)

    # Validate before applying
    issues = validate_build(champ, patch)
    if issues and not getattr(args, "force", False):
        log.error("Validation failed for %s - use --force to override:", champ)
        for issue in issues:
            log.error("  - %s", issue)
        sys.exit(1)

    builds = load_builds()
    existing = builds.get(champ, {})

    # Merge patch into existing (patch fields override)
    patch_data = {k: v for k, v in patch.items() if k != "champion"}
    existing.update(patch_data)
    builds[champ] = existing

    save_builds(builds)
    log.info("Applied patch for %s", champ)
    if issues:
        log.warning("Applied with warnings:")
        for issue in issues:
            log.warning("  - %s", issue)


def cmd_apply_all(args) -> None:
    patch_dir = Path(args.directory)
    if not patch_dir.is_dir():
        log.error("Not a directory: %s", patch_dir)
        sys.exit(1)

    patch_files = sorted(patch_dir.glob("*.json"))
    if not patch_files:
        log.warning("No .json files found in %s", patch_dir)
        return

    for pf in patch_files:
        try:
            args.file = str(pf)
            cmd_apply(args)
        except SystemExit:
            log.error("Skipped %s due to errors", pf.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Champion build patcher")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List all champions by tier")

    p_show = sub.add_parser("show", help="Show one champion's data")
    p_show.add_argument("champion")

    sub.add_parser("validate", help="Validate all builds")

    p_apply = sub.add_parser("apply", help="Apply a champion patch file")
    p_apply.add_argument("file")
    p_apply.add_argument("--force", action="store_true")

    p_all = sub.add_parser("apply-all", help="Apply all patches in a directory")
    p_all.add_argument("directory")
    p_all.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.cmd == "list":        cmd_list(args)
    elif args.cmd == "show":      cmd_show(args)
    elif args.cmd == "validate":  cmd_validate(args)
    elif args.cmd == "apply":     cmd_apply(args)
    elif args.cmd == "apply-all": cmd_apply_all(args)
    else:
        parser.print_help()
