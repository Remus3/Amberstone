import glob
import json
import os
import pathlib
import re
import time
import urllib.request
ROOT = pathlib.Path(__file__).resolve().parent
URL = "http://127.0.0.1:4000/v1/messages"

def grade(oracle: dict, code: str) -> bool:
    kind = oracle["kind"]
    if kind == "contains":
        return oracle["expect"] in code
    if kind == "py_exec":
        ns = {}
        try:
            exec(code, ns)                       # sandbox note: fixtures are trusted, local-only
            return str(eval(oracle["call"], ns)) == str(oracle["expect"])
        except Exception:  # noqa: BLE001 - untrusted LLM-generated code can raise anything
            return False
    if kind == "numeric":
        m = re.search(r"-?\d+\.?\d*", code)
        return m is not None and abs(float(m.group()) - float(oracle["expect"])) < float(oracle.get("eps", 1e-6))
    return False

def _extract_code(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text

def ask(model: str, prompt: str) -> tuple[str, float]:
    body = {"model": model, "max_tokens": 800, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST",
        headers={"content-type":"application/json","x-api-key":os.environ["LITELLM_MASTER_KEY"],
                 "anthropic-version":"2023-06-01"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        out = json.loads(r.read())
    txt = "".join(b.get("text","") for b in out.get("content", []) if b.get("type")=="text")
    return txt, time.time() - t0

def run(models=("rc-local","rc-background","rc-deepseek")):
    tasks = [json.loads(pathlib.Path(p).read_text()) for p in glob.glob(str(ROOT/"qual_tasks"/"*.json"))]
    card = {}
    for m in models:
        rows = []
        for t in tasks:
            try:
                txt, dt = ask(m, t["prompt"])
                ok = grade(t["oracle"], _extract_code(txt))
            except Exception:  # noqa: BLE001 - one bad model/task must not abort the scorecard run
                ok, dt = False, 0.0
            rows.append({"id": t["id"], "tier": t["tier"], "pass": ok, "secs": round(dt,1)})
        passed = sum(r["pass"] for r in rows)
        card[m] = {"passed": passed, "total": len(rows), "rows": rows}
    (ROOT/"qualification_scorecard.json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    return card

if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
