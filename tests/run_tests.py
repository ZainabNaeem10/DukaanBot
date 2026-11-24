"""
Runs tests/test_messages.json against the AI service and prints a report.
No extra packages needed (Python 3.8+).

Usage (from the project folder):
    python tests\run_tests.py                     (BATIK real catalog, tests/test_messages_batik.json)
    python tests\run_tests.py --store store_001   (fictional store, tests/test_messages.json)
    python tests\run_tests.py --url http://localhost:8000 --out tests\results.json

Experiments (for the report; run each and compare the summaries):
    python tests\run_tests.py --out tests\results_full.json
    python tests\run_tests.py --no-rag --no-grounding --out tests\results_baseline.json
    python tests\run_tests.py --no-grounding --out tests\results_no_grounding.json

Checks per message:
  - intent matches expected_intent
  - escalate matches expected_escalate
  - reply contains at least one string from must_include_any (if given; case-insensitive)
  - an order object is returned when expected_order is true
Whether the reply states the right facts (see "facts") still needs a human read; use results.json for that.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles
except AttributeError:
    pass

HERE = Path(__file__).parent


def call(url, payload, query=""):
    req = urllib.request.Request(
        url.rstrip("/") + "/respond" + query,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--store", default="store_002", help="store_002 = BATIK (real), store_001 = Noor (fictional)")
    ap.add_argument("--tests", default=None, help="test file (default: the one for the chosen store)")
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds to wait between messages (free LLM plans limit requests per minute)")
    ap.add_argument("--no-rag", action="store_true", help="baseline: plain LLM, no catalog retrieval")
    ap.add_argument("--no-grounding", action="store_true", help="skip the grounding check")
    args = ap.parse_args()
    params = []
    if args.no_rag:
        params.append("rag=false")
    if args.no_grounding:
        params.append("grounding=false")
    query = ("?" + "&".join(params)) if params else ""

    if args.tests is None:
        name = "test_messages_batik.json" if args.store == "store_002" else "test_messages.json"
        args.tests = str(HERE / name)
    tests = json.loads(Path(args.tests).read_text(encoding="utf-8"))
    results = []
    counts = {"intent": 0, "escalate": 0, "include": 0, "include_total": 0,
              "order": 0, "order_total": 0, "grounded": 0, "errors": 0}

    for i, t in enumerate(tests):
        if i and args.delay:
            time.sleep(args.delay)
        payload = {
            "store_id": args.store,
            "conversation_id": "test-%s" % t["id"],
            "message": t["message"],
            "history": t.get("history", []),
        }
        row = {"id": t["id"], "message": t["message"], "facts": t["facts"], "problems": []}
        try:
            r = call(args.url, payload, query)
        except (urllib.error.URLError, ValueError, OSError) as e:
            counts["errors"] += 1
            row.update(reply=None, problems=["request failed: %s" % e])
            results.append(row)
            print("[ERR ] %2d  %s" % (t["id"], e))
            continue

        row["reply"] = r.get("reply")
        row["intent"] = r.get("intent")
        row["escalate"] = r.get("escalate")
        row["escalate_reason"] = r.get("escalate_reason")
        row["grounded"] = r.get("grounded")

        if r.get("intent") == t["expected_intent"]:
            counts["intent"] += 1
        else:
            row["problems"].append("intent %r, expected %r" % (r.get("intent"), t["expected_intent"]))
        if bool(r.get("escalate")) == t["expected_escalate"]:
            counts["escalate"] += 1
        else:
            row["problems"].append("escalate %r, expected %r" % (r.get("escalate"), t["expected_escalate"]))
        if t.get("must_include_any"):
            counts["include_total"] += 1
            reply = (r.get("reply") or "").lower()
            if any(s.lower() in reply for s in t["must_include_any"]):
                counts["include"] += 1
            else:
                row["problems"].append("reply has none of %s" % t["must_include_any"])
        if t.get("expected_order"):
            counts["order_total"] += 1
            if r.get("order"):
                counts["order"] += 1
            else:
                row["problems"].append("no order returned")
        if r.get("grounded"):
            counts["grounded"] += 1

        results.append(row)
        status = "PASS" if not row["problems"] else "FAIL"
        print("[%s] %2d  %s" % (status, t["id"], t["message"]))
        for p in row["problems"]:
            print("          - " + p)
        if row["problems"] and row.get("reply") is not None:
            print("          bot said: %s" % row["reply"])
            if row.get("escalate_reason"):
                print("          handover reason: %s" % row["escalate_reason"])

    n = len(tests)
    print("\n" + "=" * 50)
    print("Messages run            : %d (errors: %d)" % (n, counts["errors"]))
    print("Intent correct          : %d/%d (%.0f%%)" % (counts["intent"], n, 100.0 * counts["intent"] / n))
    print("Escalation correct      : %d/%d (%.0f%%)" % (counts["escalate"], n, 100.0 * counts["escalate"] / n))
    if counts["include_total"]:
        print("Price/fact strings found: %d/%d" % (counts["include"], counts["include_total"]))
    if counts["order_total"]:
        print("Order extracted         : %d/%d" % (counts["order"], counts["order_total"]))
    print("Marked grounded         : %d/%d" % (counts["grounded"], n))
    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Full results written to %s" % args.out)
    print("Facts still need a human read: compare each reply with the 'facts' column in test_messages.json")


if __name__ == "__main__":
    main()
