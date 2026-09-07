"""Parse external Arena stats-page tool-result files into compact summaries."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path


def parse(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        wrapper = json.loads(raw)
        content = wrapper.get("content", "")
        url = wrapper.get("url", "")
    except Exception:  # noqa: BLE001
        content = raw
        url = ""

    out: dict = {"url": url}

    m = re.search(r"/champion/([^/]+)/arena", url)
    out["champ_url_key"] = m.group(1) if m else None

    # Tier + WR - plain_text format: "Arena PerformanceF9.8%Win Rate (1st)22.7%Top 2 Rate"
    m = re.search(r"Arena Performance([SABCDF])([\d.]+)%Win Rate \(1st\)", content)
    if m:
        out["tier"] = m.group(1)
        out["wr_first"] = float(m.group(2))

    m = re.search(r"([\d.]+)%Top 2 Rate", content)
    out["top2"] = float(m.group(1)) if m else None
    m = re.search(r"([\d.]+)Avg Placement", content)
    out["avg_place"] = float(m.group(1)) if m else None
    m = re.search(r"([\d.]+)%Pick Rate(?:Combat|\n)", content)
    out["pickrate"] = float(m.group(1)) if m else None

    m = re.search(r"and a ([\d.]+)% top 4 rate", content)
    out["top4"] = float(m.group(1)) if m else None

    m = re.search(r"([\d.]+)Kills([\d.]+)Deaths([\d.]+)Assists", content)
    if m:
        out["kda"] = {"k": float(m.group(1)), "d": float(m.group(2)), "a": float(m.group(3))}

    # Best duo partners - short summary
    m = re.search(r"Best duo partners include ([^.]+)\.", content)
    if m:
        out["best_duos_summary"] = [s.strip() for s in m.group(1).split(",")]

    # Strongest single duo + WR
    m = re.search(r"strongest duo partner is ([\w' ]+?), achieving a ([\d.]+)% win rate", content)
    if m:
        out["best_duo_1"] = {"name": m.group(1).strip(), "wr": float(m.group(2))}
    m = re.search(r"Other high-synergy partners include ([\w' ]+) and ([\w' ]+),", content)
    if m:
        out["best_duo_2_3"] = [m.group(1).strip(), m.group(2).strip()]

    # Top 3 duo partners with stats - pattern: "1<Name><avg>Avg Place<+diff>Place Diff<wr>%Win Rate<top4>%Top 4"
    duos = []
    # The Top Arena Duo Partners section list: "1<Champ>X.YAvg Place..."
    # Better: pull from the table at end. In plain text the pattern is "[Name]TierWR%diff%top2%top4%avg%diff%matches"
    # Try the duo "1NameX.XAvg Place" pattern
    duo_section = re.search(r"Top Arena Duo Partners in Patch [\d.]+(.+?)(?:Best Arena Augments|Best Arena Builds)", content, re.S)
    if duo_section:
        seg = duo_section.group(1)
        # pattern: digit+ChampName + decimal + 'Avg Place'
        for m in re.finditer(r"(\d+)([A-Z][\w' ]+?)([\d.]+)Avg Place([+\-\d.]+)Place Diff([\d.]+)%Win Rate([\d.]+)%Top 4", seg):
            duos.append({
                "rank": int(m.group(1)),
                "name": m.group(2).strip(),
                "avg_place": float(m.group(3)),
                "place_diff": m.group(4),
                "wr": float(m.group(5)),
                "top4": float(m.group(6)),
            })
    out["top_duos"] = duos[:5]

    # Augments - pattern: "<TierLetter><pickrate>%Pick Rate<AugmentName>"
    augs = []
    aug_section = re.search(r"Best Arena Augments in Patch [\d.]+(.+?)Best Arena Duo Partners", content, re.S)
    if aug_section:
        seg = aug_section.group(1)
        # pattern: tier-letter + pickrate% + Pick Rate + name (until next [SABCDF]\d or end)
        for m in re.finditer(r"\b([SABCDF])([\d.]+)%Pick Rate([A-Z][\w':!\- ]+?)(?=(?:[SABCDF][\d.]+%Pick Rate|Best Arena Duo|$))", seg):
            name = m.group(3).strip()
            # Trim description that crept in (descriptions usually start with "Gain", "Your", "Every", lowercase, etc.)
            # Take first word group up to known terminators
            name = re.split(r"(?:Gain |Your |Every |Sacrifice |When |Become |Stars |After |Using |\(|\.)", name)[0].strip()
            # Clean up trailing words from description bleed-in
            # If it's "Gain a Prismatic Stat Anvil" (which IS the name), keep
            augs.append({
                "tier": m.group(1),
                "pickrate": float(m.group(2)),
                "name": name[:60],
            })
    out["augments"] = augs[:12]

    # Strongest augment choices summary - the most reliable augment names
    m = re.search(r"strongest augment choices include ([^.]+?), which provide", content)
    if m:
        out["strongest_augments"] = [s.strip() for s in m.group(1).split(",")]

    # Recommended augments
    m = re.search(r"prioritize ([\w'': !\-]+?) for maximum impact", content)
    if m:
        out["recommended_prismatic"] = m.group(1).strip()
    m = re.search(r"Gold augments like ([\w'': !\-]+?) (?:provide|synergize)", content)
    if m:
        out["recommended_gold"] = m.group(1).strip()

    # Top build summary
    m = re.search(r"top-performing build features\s*\*?\*?([^*.]+?)\*?\*?\s*as core items, achieving a ([\d.]+)% win rate", content)
    if m:
        out["top_build_summary"] = {
            "core": [s.strip() for s in m.group(1).split(",")],
            "wr": float(m.group(2)),
        }

    m = re.search(r"\*?\*?([\w'' ]+?)\*?\*?\s*is the recommended boots", content)
    if m:
        out["recommended_boots"] = m.group(1).strip()

    return out


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: parse_external_arena.py <file_or_dir>", file=sys.stderr)
        sys.exit(2)
    targets: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            targets.extend(sorted(p.glob("*.txt")))
        else:
            targets.append(p)
    results = []
    for f in targets:
        try:
            r = parse(f)
            r["_file"] = f.name
            results.append(r)
        except Exception as e:  # noqa: BLE001
            results.append({"_file": f.name, "_error": str(e)})
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
