#!/usr/bin/env python3
"""Run the golden question sets against a deployed Agis RAG and fail if the
score drops below the threshold. Meant for CI (see .github/workflows/golden-eval.yml).

Environment:
  AGIS_API_URL      e.g. https://your-backend.example.com/api/v1
  AGIS_EMAIL / AGIS_PASSWORD   account that owns the knowledge bases (or AGIS_TOKEN)
  AGIS_KB_IDS       comma-separated KB ids; empty = every KB that has golden questions
  GOLDEN_THRESHOLD  0-1, default 0.7
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("AGIS_API_URL", "").rstrip("/")
THRESHOLD = float(os.environ.get("GOLDEN_THRESHOLD", "0.7"))


def call(path, method="GET", body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")


def main():
    if not API:
        print("AGIS_API_URL not set; nothing to evaluate.")
        return 0
    token = os.environ.get("AGIS_TOKEN")
    if not token:
        token = call("/auth/login", "POST", {"email": os.environ["AGIS_EMAIL"], "password": os.environ["AGIS_PASSWORD"]})["access_token"]
    kb_ids = [k for k in os.environ.get("AGIS_KB_IDS", "").split(",") if k.strip()]
    if not kb_ids:
        kb_ids = [kb["id"] for kb in call("/knowledge-bases", token=token)]

    failed = False
    ran = 0
    for kb_id in kb_ids:
        questions = call(f"/evaluation/golden/{kb_id}", token=token)
        if not questions:
            continue
        ran += 1
        res = call("/evaluation/golden/run", "POST", {"kb_id": kb_id, "threshold": THRESHOLD}, token=token)
        status = "PASS" if res["pass"] else "FAIL"
        print(f"[{status}] KB {kb_id}: score {res['overall_score']:.3f} (threshold {THRESHOLD}), "
              f"{res['passed']}/{res['total']} questions passed, judged by {res['method']}")
        for r in res["results"]:
            mark = "ok " if r["passed"] else "LOW"
            print(f"   {mark} {r['score']:.2f}  {r['question'][:90]}")
        failed |= not res["pass"]
    if ran == 0:
        print("No knowledge base has golden questions; add some on the Evaluation page.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
