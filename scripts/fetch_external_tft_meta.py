"""
scripts/fetch_external_tft_meta.py
Fetches Set 17 comp data from the configured external TFT meta source and
writes it to data/meta/tft_set17_external_raw.json for manual integration.

Every target is operator configuration, read from config/external_sources.json
(template: config/external_sources.example.json) at RUN time rather than at
import, so this module is import-safe on an install that has none. The two
header values are separate keys because the API checks them, so pointing the
endpoint elsewhere means pointing those elsewhere too.
"""
import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import external_sources  # noqa: E402

PROJECT = ROOT

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": external_sources.value("tft_meta_origin"),
        "Referer": external_sources.value("tft_meta_referer"),
    }


def _queries(graphql_url: str) -> list:
    """The two GraphQL shapes worth trying, both against the same endpoint."""
    return [
        # Tier-list comps.
        {
            "url": graphql_url,
            "body": json.dumps({
                "operationName": "TftCompsQuery",
                "variables": {"set": 17, "region": "global"},
                "query": "query TftCompsQuery($set: Int, $region: String) { tft { comps(set: $set, region: $region) { name tier winRate top4Rate units { name position } augments items { name unit } } } }"
            }).encode()
        },
        {
            "url": graphql_url,
            "body": json.dumps({
                "operationName": "GetTftTierList",
                "variables": {"filters": {"set": "set17"}},
                "query": "query GetTftTierList($filters: TftTierListFilters) { tft { tierList(filters: $filters) { comps { name tier placement champions { name position items { name } } } } } }"
            }).encode()
        },
    ]


def main() -> int:
    hdrs = _headers()
    graphql_url = external_sources.value("tft_meta_graphql")
    results = {}

    for q in _queries(graphql_url) if graphql_url else []:
        try:
            req = urllib.request.Request(q["url"], data=q["body"], headers=hdrs, method="POST")
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                data = json.loads(r.read().decode())
                print(f"SUCCESS {q['url']}: {str(data)[:500]}")
                results[q["url"]] = data
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {q['url']}: {e}")

    # The static data endpoints, swept in config order.
    for url in external_sources.values("tft_meta_data_urls"):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
                data = json.loads(r.read().decode())
                print(f"DATA SUCCESS {url}: {str(data)[:500]}")
                results[url] = data
        except Exception as e:  # noqa: BLE001
            print(f"DATA FAILED {url}: {e}")

    if results:
        out = PROJECT / "data" / "meta" / "tft_set17_external_raw.json"
        out.write_text(json.dumps(results, indent=2))
        print(f"\nWrote to {out}")
        return 0

    if not graphql_url and not external_sources.values("tft_meta_data_urls"):
        print("\nNo TFT meta source configured - see config/external_sources.example.json")
    else:
        print("\nNo data retrieved from the configured TFT meta source")
    return 1


if __name__ == "__main__":
    sys.exit(main())
