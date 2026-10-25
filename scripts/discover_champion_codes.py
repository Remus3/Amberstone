"""
scripts/discover_champion_codes.py
Writes data/meta/tft_set<N>_champion_codes.json: TFT team-planner display
name -> team_planner_code, read from the local League client.

DEFAULT (passive, GET only - safe while the operator is in a lobby or game):
  GET /lol-tft-team-planner/v1/previous-context   -> the planner's "setId"
  GET /lol-game-data/assets/v1/tftchampions-teamplanner.json
      -> {"TFTSet17": [...], "TFTSet18": [...]}, each row carrying
         display_name + team_planner_code
  Options: --set TFTSet18 (override the planner's setId), --root <repo>,
  --dry-run (print, write nothing).

  Measured 2026-10-25 (session 134, live Set 18 lobby): the game-data rows
  agree with the legacy probe's measured Set 17 file on 63 of its 64 units
  (its "Nunu" is "Nunu & Willump" = 57 there); the one mismatch is Morgana
  (file 0, game data 88). Set 18: 65 units, codes 1001-1085, every name in
  the CommunityDragon Set 18 roster, every planner tier equal to its cost.

--legacy-mutating-probe: the original Set 17 method. It POSTs and DELETEs on
  the team planner (clears the planner team, adds each champion, POSTs for a
  team code and decodes code[2:5]). It DESTROYS the operator's planner team
  and is hard-wired to TFT17_ character ids, so it is never run during a
  lobby or game; kept only for reproducing the Set 17 measurement.
"""
from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
META_REL = Path("data") / "meta"

LOCKFILES = (
    Path(r"C:\Riot Games\League of Legends (PBE)\lockfile"),
    Path(r"C:\Riot Games\League of Legends\lockfile"),
)
PLANNER_CONTEXT = "/lol-tft-team-planner/v1/previous-context"
PLANNER_GAME_DATA = "/lol-game-data/assets/v1/tftchampions-teamplanner.json"


class Lcu:
    """Minimal LCU client; the passive path only ever calls get()."""

    def __init__(self, lockfile: Path):
        parts = lockfile.read_text().strip().split(":")
        port, pw = parts[2], parts[3]
        auth = base64.b64encode(f"riot:{pw}".encode()).decode()
        self.base = f"https://127.0.0.1:{port}"  # game host is local (ADR-011)
        self.hdrs = {"Authorization": f"Basic {auth}",
                     "Accept": "application/json",
                     "Content-Type": "application/json"}
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def request(self, method: str, ep: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}{ep}", data=data,
                                     headers=self.hdrs, method=method)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=10) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:200]
        except Exception as e:  # noqa: BLE001
            return 0, str(e)

    def get(self, ep: str):
        return self.request("GET", ep)


def set_number(set_id: str) -> int:
    digits = "".join(ch for ch in set_id if ch.isdigit())
    if not digits:
        raise ValueError(f"no set number in {set_id!r}")
    return int(digits)


def codes_path(set_id: str, root: Path = PROJECT) -> Path:
    return Path(root) / META_REL / f"tft_set{set_number(set_id)}_champion_codes.json"


def codes_from_game_data(game_data: dict, set_id: str) -> dict:
    """display_name -> team_planner_code for one set of the game-data table.

    Raises ValueError when the set is absent or empty, a row lacks an int code,
    or one display name maps to two codes (the flat map cannot hold both)."""
    rows = game_data.get(set_id) if isinstance(game_data, dict) else None
    if not isinstance(rows, list) or not rows:
        have = sorted(game_data) if isinstance(game_data, dict) else []
        raise ValueError(f"set {set_id!r} not in game data (have {have})")
    out: dict = {}
    for row in rows:
        name = row.get("display_name")
        code = row.get("team_planner_code")
        if not isinstance(name, str) or not name or type(code) is not int:
            raise ValueError(f"bad planner row: {row!r:.200}")
        if name in out and out[name] != code:
            raise ValueError(f"{name!r} has two codes: {out[name]} and {code}")
        out[name] = code
    return out


def encode(codes: dict) -> bytes:
    """Byte format of the committed Set 17 file: indent 2, sorted, LF."""
    return json.dumps(codes, indent=2, sort_keys=True).encode("utf-8")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def passive(lcu: Lcu, set_override: str | None, root: Path, dry_run: bool) -> int:
    s, b = lcu.get(PLANNER_CONTEXT)
    if s != 200:
        print(f"Cannot get previous-context: HTTP {s}")
        return 1
    set_id = set_override or json.loads(b).get("setId") or ""
    if not set_id:
        print("previous-context carries no setId; pass --set")
        return 1
    s, b = lcu.get(PLANNER_GAME_DATA)
    if s != 200:
        print(f"Cannot get {PLANNER_GAME_DATA}: HTTP {s}")
        return 1
    codes = codes_from_game_data(json.loads(b), set_id)
    out = codes_path(set_id, root)
    print(f"set={set_id} units={len(codes)} -> {out}")
    if not dry_run:
        atomic_write_bytes(out, encode(codes))
        print(f"Wrote {len(codes)} codes to {out}")
    return 0


# --- legacy Set 17 probe (MUTATES the team planner; see module docstring) ---

LEGACY_CHAMPIONS = [
    "Aatrox", "Caitlyn", "Talon", "Twisted Fate", "Poppy", "Veigar",
    "Chogath", "Lissandra", "Leona", "Teemo", "Nasus",
    "Akali", "Jax", "Gnar", "Meepsie", "Mordekaiser", "Shen", "Ezreal", "Diana",
    "Maokai", "Lulu", "Fizz", "Illaoi", "KaiSa", "MissFortune", "Ornn",
    "Urgot", "Nami", "Viktor", "Rhaast",
    "Kindred", "Nunu", "Xayah", "Corki", "Rammus", "Karma", "Riven",
    "AurelionSol", "TheMightyMech", "Pantheon", "Sona", "TahmKench",
    "Samira", "Morgana", "LeBlanc",
    "Bard", "Jhin", "Fiora", "Graves", "Blitzcrank", "MasterYi", "Pyke", "Aurora",
    "BelVeth", "Briar", "Jinx", "Gragas", "Gwen", "Ekko", "RekSai",
    "TwistedFate", "Meepsie",
]
LEGACY_DISPLAY = {
    "Chogath": "Cho'Gath", "KaiSa": "Kai'Sa", "MissFortune": "Miss Fortune",
    "AurelionSol": "Aurelion Sol", "TheMightyMech": "The Mighty Mech",
    "TahmKench": "Tahm Kench", "MasterYi": "Master Yi",
    "BelVeth": "Bel'Veth", "RekSai": "Rek'Sai", "TwistedFate": "Twisted Fate",
}


def legacy_probe(lcu: Lcu, root: Path) -> int:
    s, b = lcu.get(PLANNER_CONTEXT)
    if s != 200:
        print(f"Cannot get previous-context: HTTP {s}")
        return 1
    prev = json.loads(b)
    team_id = prev.get("optionalTeamId", "")
    set_id = prev.get("setId", "TFTSet17")
    print(f"Using team_id={team_id}  set={set_id}")

    def get_code():
        s, b = lcu.request("POST", f"/lol-tft-team-planner/v1/sets/{set_id}/team-code/{team_id}")
        return b.strip().strip('"') if s == 200 else None

    def clear_team():
        lcu.request("DELETE", f"/lol-tft-team-planner/v1/sets/{set_id}/teams/{team_id}/champions")
        time.sleep(0.2)

    clear_team()
    baseline = get_code()
    if not baseline:
        print("ERROR: Cannot get baseline code - is the client in a game?")
        return 1
    print(f"Baseline: {baseline}")

    out = Path(root) / META_REL / "tft_set17_champion_codes.json"
    results = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    print(f"Loaded {len(results)} existing codes\n")
    seen = set()
    for clean in LEGACY_CHAMPIONS:
        if clean in seen:
            continue
        seen.add(clean)
        display = LEGACY_DISPLAY.get(clean, clean)
        if display in results:
            continue  # already known
        clear_team()
        found = False
        for fmt in (f"TFT17_{clean}", f"TFT17_{clean.replace('The', '')}", clean):
            s, _ = lcu.request(
                "POST", f"/lol-tft-team-planner/v1/sets/{set_id}/teams/{team_id}/champions/{fmt}")
            if s in (200, 201, 204):
                time.sleep(0.15)
                code = get_code()
                if code and len(code) > 5:
                    prefix = code[2:5]
                    if prefix != "000":
                        results[display] = int(prefix, 16)
                        print(f"  {display}: {results[display]} (0x{prefix})")
                        found = True
                        break
            time.sleep(0.06)
        if not found:
            print(f"  {display}: NOT FOUND")
    atomic_write_bytes(out, encode(results))
    print(f"\nWrote {len(results)} codes to {out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[2])
    ap.add_argument("--set", dest="set_id", default=None,
                    help="planner set id, e.g. TFTSet18 (default: the planner's setId)")
    ap.add_argument("--root", type=Path, default=PROJECT)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--legacy-mutating-probe", action="store_true",
                    help="original Set 17 method; POST/DELETE on the team planner")
    args = ap.parse_args(argv)
    lf = next((p for p in LOCKFILES if p.exists()), None)
    if not lf:
        print("NO_LOCKFILE - launch League client first")
        return 1
    lcu = Lcu(lf)
    if args.legacy_mutating_probe:
        return legacy_probe(lcu, args.root)
    return passive(lcu, args.set_id, args.root, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
