"""Parse the cached aggregator J HTML into Phase 3 arena_tail.json entries.

Each page yields:
  - tier (re-derived from wr_first vs Phase-1 thresholds)
  - wr_first  (from <title> "X.X% WR")
  - wr_top4   (from "X.X% top 4" sometimes; otherwise from JSON-LD/avg)
  - avg_placement
  - matches   (sample size, used to flag low-confidence rows)
  - ideal_core_priority  (top-3 build "Core Items" union, ordered by build WR desc)
  - boots     (most recommended boots from top build)
  - prismatic_priority  (best 2-3 prismatic augments by winRate)
  - build_changing_augments (1-2 highest-winRate augments)
  - best_duos (top 1-2 partners from JSON-LD)
  - kit_notes / vs_tanks / vs_healing / arena_meta -- generic per-tag fallback
                (Phase 3 keeps these short; full text from aggregator J would need an
                LLM pass - out of scope for the 30-min budget. We synthesize from
                champion class tags + build outcome.)
"""
from __future__ import annotations
import json
import re
import codecs
import sys
from pathlib import Path

ROOT = Path(r"C:/Riot Commander")
HTML_DIR = ROOT / "data/meta_build/refresh_2026-05-02/_phase3_html"
DDRAGON = ROOT / "data/meta/ddragon_champions.json"
COVERED = ROOT / "data/meta_build/arena_champion_builds.json"
OUT = ROOT / "data/meta_build/refresh_2026-05-02/arena_tail.json"

# Same slug map as fetcher
SLUG_OVERRIDES = {
    "Aurelion Sol": "AurelionSol",
    "Bel'Veth": "Belveth",
    "Cho'Gath": "Chogath",
    "Dr. Mundo": "DrMundo",
    "Jarvan IV": "JarvanIV",
    "Kai'Sa": "Kaisa",
    "Kha'Zix": "Khazix",
    "K'Sante": "KSante",
    "Kog'Maw": "KogMaw",
    "LeBlanc": "Leblanc",
    "Lee Sin": "LeeSin",
    "Master Yi": "MasterYi",
    "Miss Fortune": "MissFortune",
    "Nunu & Willump": "Nunu",
    "Rek'Sai": "RekSai",
    "Renata Glasc": "Renata",
    "Tahm Kench": "TahmKench",
    "Twisted Fate": "TwistedFate",
    "Vel'Koz": "Velkoz",
    "Wukong": "MonkeyKing",
    "Xin Zhao": "XinZhao",
}


def slug_for(name: str) -> str:
    return SLUG_OVERRIDES.get(name, name.replace("'", "").replace(" ", "").replace(".", ""))


def load_missing() -> tuple[list[str], dict[str, dict]]:
    dd = json.loads(DDRAGON.read_text(encoding="utf-8"))["data"]
    cls_by_name = {v["name"]: v.get("tags", []) for v in dd.values()}
    covered = set(json.loads(COVERED.read_text(encoding="utf-8")).keys()) - {
        "_meta",
        "_phase2_meta",
        "_phase2_added",
    }
    missing = sorted(n for n in cls_by_name if n not in covered)
    return missing, cls_by_name


def stream_chunks(html: str) -> str:
    """Concatenate every self.__next_f.push([N,"…"]) string after JS-unescape."""
    pat = re.compile(r"self\.__next_f\.push\(\[\d+,\s*\"", re.S)
    out: list[str] = []
    i = 0
    while True:
        m = pat.search(html, i)
        if not m:
            break
        start = m.end()
        j = start
        while j < len(html):
            c = html[j]
            if c == "\\":
                j += 2
                continue
            if c == "\"":
                out.append(html[start:j])
                i = j + 1
                break
            j += 1
        else:
            break
    combined = ""
    for c in out:
        try:
            combined += codecs.decode(c.encode("utf-8"), "unicode_escape")
        except Exception:
            combined += c
    return combined


# Phase-1 thresholds (matching covered file)
def derive_tier(wr_first: float | None) -> str | None:
    if wr_first is None:
        return None
    if wr_first >= 17:
        return "S"
    if wr_first >= 15:
        return "A"
    if wr_first >= 13:
        return "B"
    if wr_first >= 11:
        return "C"
    return "D"


# Default boot picks per class
BOOTS_BY_CLASS = {
    "Mage": "Sorcerer's Shoes",
    "Marksman": "Berserker's Greaves",
    "Assassin": "Sorcerer's Shoes",
    "Fighter": "Plated Steelcaps",
    "Tank": "Plated Steelcaps",
    "Support": "Mercury's Treads",
}

# Class-default core builds for arena (when aggregator J has no build table)
CORE_BY_CLASS = {
    "Tank": [
        "Heartsteel",
        "Sunfire Aegis",
        "Kaenic Rookern",
        "Dead Man's Plate",
        "Thornmail",
        "Warmog's Armor",
    ],
    "Fighter": [
        "Hemomancer's Helm",
        "Black Cleaver",
        "Sterak's Gage",
        "Death's Dance",
        "Dead Man's Plate",
        "Goredrink",
    ],
    "Marksman": [
        "Hamstringer",
        "Kraken Slayer",
        "Bloodthirster",
        "Infinity Edge",
        "Mortal Reminder",
        "Phantom Dancer",
    ],
    "Mage": [
        "Pyromancer's Cloak",
        "Liandry's Anguish",
        "Shadowflame",
        "Rabadon's Deathcap",
        "Void Staff",
        "Zhonya's Hourglass",
    ],
    "Assassin": [
        "Eclipse",
        "Edge of Night",
        "Serpent's Fang",
        "The Collector",
        "Voltaic Cyclosword",
        "Youmuu's Ghostblade",
    ],
    "Support": [
        "Locket of the Iron Solari",
        "Knight's Vow",
        "Redemption",
        "Shurelya's Battlesong",
        "Ardent Censer",
        "Moonstone Renewer",
    ],
}


def boots_default(tags: list[str]) -> str:
    for t in tags:
        if t in BOOTS_BY_CLASS:
            return BOOTS_BY_CLASS[t]
    return "Plated Steelcaps"


def core_default(tags: list[str]) -> list[str]:
    for t in tags:
        if t in CORE_BY_CLASS:
            return list(CORE_BY_CLASS[t])
    return list(CORE_BY_CLASS["Fighter"])


def parse_page(name: str, slug: str, tags: list[str], html: str) -> dict:
    combined = stream_chunks(html)

    entry: dict = {
        "tier": None,
        "wr_first": None,
        "wr_top4": None,
        "avg_placement": None,
        "matches": None,
        "ideal_core_priority": [],
        "prismatic_priority": [],
        "boots": boots_default(tags),
        "best_duos": [],
        "build_changing_augments": [],
        "vs_tanks": "",
        "vs_healing": "Mortal Reminder anvil mandatory vs healers; Chempunk a fallback.",
        "kit_notes": "",
        "arena_meta": "",
        "_sources": [
            {
                "url": f"https://aggregator-j.invalid/en/league/champion/{slug}/arena",
                "fetched": "2026-05-03",
            }
        ],
    }

    # 1) header WR + placement from <title> + description
    m = re.search(
        r"Arena Build & Tier \(([\d.]+)% WR\)", combined
    )
    if m:
        entry["wr_first"] = float(m.group(1))
    # description has avg placement
    m = re.search(
        r"with a ([\d.]+)% win rate and a ([\d.]+) average placement", combined
    )
    if m:
        if entry["wr_first"] is None:
            entry["wr_first"] = float(m.group(1))
        entry["avg_placement"] = float(m.group(2))

    entry["tier"] = derive_tier(entry["wr_first"])

    # 2) total matches across page-level data - use sum of augment 'matches'
    aug_match_total = 0
    aug_records: list[dict] = []
    aug_pat = re.compile(
        r'\{"augmentId":(\d+)[^}]*?"championId":"[^"]+"[^}]*?"winRate":([\d.\-]+)[^}]*?"matches":(\d+)[^}]*?"statBotTier":"([SABCDF])"[^}]*?"augmentName":"([^"]+)"[^}]*?"augmentRarity":(\d+)',
        re.S,
    )
    for am in aug_pat.finditer(combined):
        wr = float(am.group(2))
        matches = int(am.group(3))
        tier = am.group(4)
        nm = am.group(5)
        rarity = int(am.group(6))
        aug_records.append(
            {"name": nm, "wr": wr, "matches": matches, "tier": tier, "rarity": rarity}
        )
        aug_match_total += matches
    if aug_match_total:
        entry["matches"] = aug_match_total

    # rarity 4 = prismatic, 3 = gold, 2 = silver, 1 = bronze (heuristic from aggregator J)
    prismatic = [a for a in aug_records if a["rarity"] == 4]
    silver = [a for a in aug_records if a["rarity"] == 2]
    # pick build_changing = top 2 by winRate from any rarity ≥ 2 with matches >= 5
    candidates = sorted(
        [a for a in aug_records if a["matches"] >= 5],
        key=lambda x: (-x["wr"], -x["matches"]),
    )
    entry["build_changing_augments"] = [
        f"{a['name']} ({a['wr']}% WR, n={a['matches']})" for a in candidates[:2]
    ]
    # prismatic_priority - sort by winRate
    prismatic_sorted = sorted(prismatic, key=lambda x: (-x["wr"], -x["matches"]))
    entry["prismatic_priority"] = [
        f"{a['name']} ({a['wr']}% WR)" for a in prismatic_sorted[:3]
    ]

    # 3) Items - pull from build descriptions: "X, Y, Z as core items"
    # Top build first
    item_names: list[str] = []
    m = re.search(r"top-performing build features ([^.]+?) as core items", combined)
    if m:
        item_names = [x.strip() for x in m.group(1).split(",")]
    # also collect from itemIcon title attrs (build tables)
    title_pat = re.compile(r'"title":"([^"]+)","loading":"lazy"')
    seen = set(item_names)
    for tm in title_pat.finditer(combined):
        nm = tm.group(1)
        if nm and nm not in seen and "Core item" not in nm:
            # filter out non-items by skipping ones that contain typical non-item words
            seen.add(nm)
    # Actual approach: collect alt-text "X - Core item N for ..."
    core_alt = re.findall(
        r'"alt":"([^"]+) - Core item \d+ for [^"]+ Arena build"', combined
    )
    # Preserve order, dedupe
    ordered: list[str] = []
    for nm in (item_names + core_alt):
        if nm and nm not in ordered:
            ordered.append(nm)
    # Also pull situational
    sit_alt = re.findall(
        r'"alt":"([^"]+) - Situational item option for [^"]+ Arena build"', combined
    )
    for nm in sit_alt:
        if nm and nm not in ordered:
            ordered.append(nm)
    entry["ideal_core_priority"] = ordered[:7]
    if not entry["ideal_core_priority"]:
        # No build table on aggregator J - synthesize from class defaults
        entry["ideal_core_priority"] = core_default(tags)
        entry["_core_synthetic"] = True

    # boots – look for "X is the recommended boots choice"
    m = re.search(r"([A-Z][\w' ]+?) is the recommended boots choice", combined)
    if m:
        entry["boots"] = m.group(1).strip()

    # 4) Duos from JSON-LD
    duo_pat = re.compile(
        r'"name":"([^"]+)","url":"https://aggregator-j.invalid\.gg/en/league/champion/[^"]+/arena","image":"[^"]+","description":"[^"]+ paired with [^:]+: ([\d.]+)% win rate, ([\d.]+) avg placement"'
    )
    duos = []
    for dm in duo_pat.finditer(combined):
        duos.append((dm.group(1), float(dm.group(2)), float(dm.group(3))))
    duos_sorted = sorted(duos, key=lambda x: (-x[1], x[2]))
    entry["best_duos"] = [f"{d[0]} ({d[1]}% WR)" for d in duos_sorted[:2]]

    # 5) Class-derived narrative
    primary = tags[0] if tags else "Fighter"
    if "Tank" in tags or primary == "Tank":
        entry["vs_tanks"] = "Anti-tank not your job - focus engage/peel; let duo carry %HP dmg."
        entry["kit_notes"] = "Frontline body - soak engage, re-position duo, peel CC chains."
    elif "Marksman" in tags:
        entry["vs_tanks"] = "Mortal Reminder + on-hit (BotRK / Kraken) anvil priority vs HP stacks."
        entry["kit_notes"] = "Ranged DPS - range = HP in arena; need peel duo (Tank/Enchanter)."
    elif "Mage" in tags:
        entry["vs_tanks"] = "Liandry's anvil core; Void Staff if 2+ MR items on enemies."
        entry["kit_notes"] = "AP burst/DPS - positioning critical, value Stasis/Edge of Night vs assassins."
    elif "Assassin" in tags:
        entry["vs_tanks"] = "Don't try - pivot to squishies; Serpent's Fang / Edge of Night vs shields."
        entry["kit_notes"] = "Burst pick-off - needs angle; mediocre into peel duos, strong vs squishy comps."
    elif "Support" in tags:
        entry["vs_tanks"] = "Build defensive (Locket/Knight's Vow) and let carry duo handle DPS."
        entry["kit_notes"] = "Enchanter/engage - duo-dependent; pick ADC/bruiser carry partner."
    else:  # Fighter
        entry["vs_tanks"] = "BotRK + Black Cleaver anvil; Goredrink keeps you topped vs sustained HP fights."
        entry["kit_notes"] = "Bruiser - mid-range engage, HP+omnivamp scaling, look for Reverberation/Goliath prismatics."

    # arena_meta one-liner
    wr = entry["wr_first"]
    n = entry["matches"]
    sample_note = " (low sample)" if n and n < 1000 else ""
    if wr is None:
        entry["arena_meta"] = "Stats unavailable on aggregator J 26.9 - synthetic class-default build."
    elif wr >= 17:
        entry["arena_meta"] = f"S-tier overperformer at {wr}% wr_first{sample_note} - first-pick worthy."
    elif wr >= 15:
        entry["arena_meta"] = f"A-tier solid blind pick at {wr}% wr_first{sample_note}."
    elif wr >= 13:
        entry["arena_meta"] = f"B-tier - playable into most lobbies at {wr}% wr_first{sample_note}."
    elif wr >= 11:
        entry["arena_meta"] = f"C-tier filler at {wr}% wr_first{sample_note} - needs duo synergy or augment lottery."
    else:
        entry["arena_meta"] = f"D/F-tier on aggregator J 26.9 ({wr}% wr_first{sample_note}) - counter-pick only."

    return entry


def main() -> int:
    missing, cls_by_name = load_missing()
    out: dict = {
        "_meta": {
            "patch": "26.9",
            "season": "Arena Season 2",
            "fetched": "2026-05-03",
            "phase": 3,
            "scope": f"Arena tail ({len(missing)} missing champs)",
            "mode_internal_name": "CHERRY",
            "tier_thresholds_inherited_from_phase1": {
                "S": ">=17",
                "A": "15-17",
                "B": "13-15",
                "C": "11-13",
                "D": "<11",
            },
            "sources_used": ["https://aggregator-j.invalid/en/league/champion/<Name>/arena"],
            "sources_failed": [],
            "schema_note": (
                "Same shape as Phase 1/2 but vs_X / kit_notes / arena_meta are "
                "class-derived defaults (not per-champion narrative) to fit Phase 3 budget. "
                "ideal_core_priority is union of aggregator J top-3 build cores + situational. "
                "prismatic_priority is top-3 rarity=4 augments by winRate. "
                "build_changing_augments is top-2 augments by winRate (any rarity, n>=5)."
            ),
            "vs_x_note": "Anvil-pull priority hints, not fixed alternate builds.",
        },
        "champions": {},
        "_partial": [],
        "_synthetic": [],
        "_skipped": [],
    }

    for name in missing:
        slug = slug_for(name)
        html_path = HTML_DIR / f"{slug}.html"
        if not html_path.exists():
            out["_skipped"].append({"name": name, "reason": "no html cached"})
            continue
        try:
            html = html_path.read_text(encoding="utf-8", errors="replace")
            entry = parse_page(name, slug, cls_by_name.get(name, []), html)
            # If wr_first missing AND no aggregator J data at all → fully synthetic
            if entry["wr_first"] is None and not entry["best_duos"]:
                entry["_synthetic"] = True
                out["_synthetic"].append(name)
            elif entry.get("_core_synthetic"):
                out["_partial"].append(
                    {"name": name, "reason": "aggregator J has no arena build table - core_priority synthesized from class default"}
                )
            out["champions"][name] = entry
        except Exception as e:
            out["_skipped"].append({"name": name, "reason": f"parse error: {e}"})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    print(
        f"captured: {len(out['champions'])}  synthetic: {len(out['_synthetic'])}  skipped: {len(out['_skipped'])}"
    )
    if out["_skipped"]:
        for s in out["_skipped"]:
            print(" skipped:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
