"""
scripts/fetch_external_tft_meta.py
Fetches Set 17 comp data from Aggregator C GraphQL API and writes to
data/meta/tft_set17_external_raw.json for manual integration.
"""
import json
import ssl
import urllib.request
import sys
from pathlib import Path

PROJECT = Path(__file__).parent.parent

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://aggregator-c.invalid",
    "Referer": "https://aggregator-c.invalid/tft/tier-list",
}

# Try multiple Aggregator C API patterns
QUERIES = [
    # GraphQL query for tier list comps
    {
        "url": "https://aggregator-c.invalid/api/tft/graphql",
        "body": json.dumps({
            "operationName": "TftCompsQuery",
            "variables": {"set": 17, "region": "global"},
            "query": "query TftCompsQuery($set: Int, $region: String) { tft { comps(set: $set, region: $region) { name tier winRate top4Rate units { name position } augments items { name unit } } } }"
        }).encode()
    },
    {
        "url": "https://aggregator-c.invalid/api/tft/graphql",
        "body": json.dumps({
            "operationName": "GetTftTierList",
            "variables": {"filters": {"set": "set17"}},
            "query": "query GetTftTierList($filters: TftTierListFilters) { tft { tierList(filters: $filters) { comps { name tier placement champions { name position items { name } } } } } }"
        }).encode()
    },
]

results = {}
for q in QUERIES:
    try:
        req = urllib.request.Request(q["url"], data=q["body"], headers=HDRS, method="POST")
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            body = r.read().decode()
            data = json.loads(body)
            print(f"SUCCESS {q['url']}: {str(data)[:500]}")
            results[q["url"]] = data
    except Exception as e:
        print(f"FAILED {q['url']}: {e}")

# Also try the static CDN data
cdn_urls = [
    "https://aggregator-c-cdn.invalid/assets/tft/data/set17/tier-list.json",
    "https://aggregator-c-cdn.invalid/assets/tft/data/en_US/set17/comps.json",
    "https://aggregator-c.invalid/api/tft/v1/meta/comps?set=17",
    "https://aggregator-c.invalid/api/tft/v1/tier-list?set=17&patch=latest",
]

for url in cdn_urls:
    try:
        req = urllib.request.Request(url, headers=HDRS)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            body = r.read().decode()
            data = json.loads(body)
            print(f"CDN SUCCESS {url}: {str(data)[:500]}")
            results[url] = data
    except Exception as e:
        print(f"CDN FAILED {url}: {e}")

if results:
    out = PROJECT / "data" / "meta" / "tft_set17_external_raw.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote to {out}")
else:
    print("\nNo data retrieved from Aggregator C")
