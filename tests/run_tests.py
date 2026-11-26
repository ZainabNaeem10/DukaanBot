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
import csv
import io
import json
import re
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


REAL_CSV = HERE / "real_questions_batik.csv"
INTENTS = {"product_question", "policy", "order", "complaint", "discount", "bulk", "other"}


def _yes(v):
    s = (v or "").strip().lower()
    if s in ("yes", "y", "true", "1", "haan"):
        return True
    if s in ("no", "n", "false", "0", "nahi", ""):
        return False
    raise ValueError("expected_escalate must be yes or no, got %r" % v)


def load_real_questions(path):
    """Real customer questions copied by hand from public pages (see docs/real-questions-guide.md).
    One row per question. Rows whose message starts with # are ignored (the example row)."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
        print("WARNING: %s is not saved as UTF-8; Urdu text may be broken. In Excel use "
              "Save As > 'CSV UTF-8 (Comma delimited)'." % path.name)
    out = []
    for line_no, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        extra = row.pop(None, None)  # an unquoted comma makes extra columns: glue them back on
        if extra and row.get("must_include_any") is not None:
            row["must_include_any"] = ",".join([row["must_include_any"]] + list(extra))
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if isinstance(v, str) or v is None}
        msg = row.get("message", "")
        if not msg or msg.startswith("#"):
            continue
        intent = row.get("expected_intent", "").lower()
        try:
            if intent not in INTENTS:
                raise ValueError("expected_intent must be one of %s, got %r" % (", ".join(sorted(INTENTS)), intent))
            esc = _yes(row.get("expected_escalate"))
        except ValueError as e:
            print("SKIPPED %s line %d: %s" % (path.name, line_no, e))
            continue
        t = {"id": "R%d" % (len(out) + 1), "message": msg, "expected_intent": intent, "expected_escalate": esc,
             "facts": row.get("facts", ""), "source": "real",
             "found_on": row.get("found_on", ""), "date_found": row.get("date_found", "")}
        inc = [s.strip() for s in row.get("must_include_any", "").split("|") if s.strip()]
        if inc:
            t["must_include_any"] = inc
        out.append(t)
    return out


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
    ap.add_argument("--no-real", action="store_true", help="skip tests/real_questions_batik.csv")
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
    for t in tests:
        t.setdefault("source", "written")
    if args.store == "store_002" and not args.no_real and REAL_CSV.exists():
        real = load_real_questions(REAL_CSV)
        tests += real
        print("Loaded %d real customer questions from %s" % (len(real), REAL_CSV.name))
    results = []
    counts = {"intent": 0, "escalate": 0, "include": 0, "include_total": 0,
              "order": 0, "order_total": 0, "grounded": 0, "errors": 0}

    llm_errors = {}
    for i, t in enumerate(tests):
        if i and args.delay:
            time.sleep(args.delay)
        payload = {
            "store_id": args.store,
            "conversation_id": "test-%s" % t["id"],
            "message": t["message"],
            "history": t.get("history", []),
        }
        row = {"id": t["id"], "message": t["message"], "facts": t["facts"], "problems": [],
               "source": t.get("source", "written")}
        try:
            r = call(args.url, payload, query)
        except (urllib.error.URLError, ValueError, OSError) as e:
            counts["errors"] += 1
            row.update(reply=None, problems=["request failed: %s" % e])
            results.append(row)
            print("[ERR ] %3s  %s" % (t["id"], e))
            continue

        row["reply"] = r.get("reply")
        row["intent"] = r.get("intent")
        row["escalate"] = r.get("escalate")
        row["escalate_reason"] = r.get("escalate_reason")
        tr = r.get("trace") or {}
        row["trace"] = tr
        src = tr.get("source", "unknown")
        counts["src_" + src] = counts.get("src_" + src, 0) + 1
        if tr.get("llm_error"):
            llm_errors[tr["llm_error"]] = llm_errors.get(tr["llm_error"], 0) + 1
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
            # models sometimes write "7‑10" with a non-breaking hyphen or en dash
            reply = re.sub(r"[\u2010-\u2015\u2212]", "-", (r.get("reply") or "").lower())
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
        print("[%s] %3s  %s" % (status, t["id"], t["message"]))
        for p in row["problems"]:
            print("          - " + p)
        if row["problems"] and row.get("reply") is not None:
            print("          bot said: %s" % row["reply"])
            if row.get("escalate_reason"):
                print("          handover reason: %s" % row["escalate_reason"])
        if tr.get("first_problems"):
            print("          fact check rejected the first answer: %s" % "; ".join(tr["first_problems"]))
            if tr.get("retry_problems"):
                print("          ...and the retry: %s -> rule-based answer sent" % "; ".join(tr["retry_problems"]))
            else:
                print("          ...the retry passed")

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
    sources = sorted({r.get("source", "written") for r in results})
    if len(sources) > 1:
        print("By source (all checks passed):")
        for s in sources:
            rows = [r for r in results if r.get("source", "written") == s]
            ok = sum(1 for r in rows if r.get("reply") is not None and not r["problems"])
            print("  %-34s: %d/%d (%d%%)" % ("real customer questions" if s == "real" else "written by us",
                                            ok, len(rows), round(100.0 * ok / len(rows))))
    labels = [("llm", "LLM answer passed first time"), ("llm_retry", "rejected, fixed on retry"),
              ("rejected_then_rules", "rejected twice -> rules"), ("rules", "rule-based (no LLM call)"),
              ("llm_failed", "LLM call failed -> rules"),
              ("unknown", "fixed reply (greeting or handover rule)")]
    if any(k.startswith("src_") for k in counts):
        print("How answers were made:")
        for key, label in labels:
            if counts.get("src_" + key):
                print("  %-34s: %d" % (label, counts["src_" + key]))
    Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    if llm_errors:
        print("LLM ERRORS (these messages were answered by the rule-based backup):")
        for err, k in sorted(llm_errors.items(), key=lambda x: -x[1]):
            print("  %dx %s" % (k, err.replace("\n", " ")[:200]))
        if any("429" in e or "rate" in e.lower() for e in llm_errors):
            print("  -> Groq free-plan limit reached. Wait (limits reset over time) or see "
                  "https://console.groq.com/settings/limits. Re-run later for a fair result.")
    print("Full results written to %s" % args.out)
    print("Facts still need a human read: compare each reply with the 'facts' column in test_messages.json")


if __name__ == "__main__":
    main()
