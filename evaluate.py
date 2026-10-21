"""
Reproducible evaluation:  python evaluate.py [--report docs/evaluation_report.md]

Builds a fresh in-memory-style KB from data/seed_faqs.json, runs data/eval_set.json (queries NOT present in the KB's
alternative questions) and reports retrieval quality, abstention quality, calibration, threshold trade-offs and latency.
"""
import argparse
import json
import os
import statistics
import sys
import tempfile
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["FAQ_DB"] = os.path.join(tempfile.mkdtemp(), "eval.db")

import db  # noqa: E402
from engine import Engine  # noqa: E402


def build(answer_th=None):
    db.init_db()
    db.seed_if_empty(os.path.join(HERE, "data", "seed_faqs.json"))
    seed = json.load(open(os.path.join(HERE, "data", "seed_faqs.json"), encoding="utf-8"))
    faqs = db.list_faqs(True)
    key2id = {s["key"]: f["id"] for s, f in zip(seed, faqs)}  # seeded in file order
    st = db.get_settings()
    if answer_th is not None:
        st["answer_threshold"] = str(answer_th)
    return Engine(faqs, st), key2id


def run(engine, cases, key2id):
    out = []
    for c in cases:
        ctx = {"last_faq_id": key2id[c["last"]]} if c.get("last") else None
        r = engine.answer(c["query"], ctx)
        exp = key2id.get(c["expected"]) if c["expected"] not in (None, "AMBIG") else None
        ids = [e["faq_id"] for e in r.get("evidence", [])]
        out.append({**c, "res": r, "exp_id": exp, "ids": ids})
    return out


def metrics(rows):
    ans = [r for r in rows if r["exp_id"] is not None]
    neg = [r for r in rows if r["expected"] is None]
    amb = [r for r in rows if r["expected"] == "AMBIG"]
    top1 = sum(1 for r in ans if r["ids"][:1] == [r["exp_id"]]) / len(ans)
    top3 = sum(1 for r in ans if r["exp_id"] in r["ids"][:3]) / len(ans)
    mrr = sum((1 / (r["ids"].index(r["exp_id"]) + 1)) if r["exp_id"] in r["ids"] else 0 for r in ans) / len(ans)
    correct = sum(1 for r in ans if r["res"]["status"] == "answered" and r["res"]["faq_id"] == r["exp_id"])
    wrong = sum(1 for r in ans if r["res"]["status"] == "answered" and r["res"]["faq_id"] != r["exp_id"])
    abst = len(ans) - correct - wrong
    # abstention detection: positive = "should not answer" (unknown + unrelated)
    tp = sum(1 for r in neg if r["res"]["status"] != "answered")
    fn = len(neg) - tp
    fp = sum(1 for r in ans if r["res"]["status"] != "answered")
    prec = tp / (tp + fp) if tp + fp else 0
    rec = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
    clar = sum(1 for r in ans if r["res"]["status"] in ("clarify", "ambiguous")
               and r["exp_id"] in [s["faq_id"] for s in r["res"].get("suggestions", [])])
    answered = [r for r in rows if r["res"]["status"] == "answered"]
    sel_acc = (sum(1 for r in answered if r["res"]["faq_id"] == r["exp_id"]) / len(answered)) if answered else 0
    lat = sorted(r["res"]["latency_ms"] for r in rows)
    return {
        "n_answerable": len(ans), "n_negative": len(neg), "n_ambiguous": len(amb),
        "top1": top1, "top3": top3, "mrr": mrr,
        "answered_correct": correct / len(ans), "clarified_with_correct_option": clar / len(ans),
        "safe_success": (correct + clar) / len(ans), "answered_wrong": wrong / len(ans), "abstained_on_answerable": abst / len(ans),
        "unknown_precision": prec, "unknown_recall": rec, "unknown_f1": f1,
        "false_answer_rate_negatives": sum(1 for r in neg if r["res"]["status"] == "answered") / len(neg),
        "ambiguous_not_answered": (sum(1 for r in amb if r["res"]["status"] != "answered") / len(amb)) if amb else None,
        "selective_accuracy": sel_acc, "p50_ms": statistics.median(lat), "p95_ms": lat[int(0.95 * (len(lat) - 1))],
    }


def per_category(rows):
    g = defaultdict(list)
    for r in rows:
        g[r["category"]].append(r)
    out = []
    for cat, rs in g.items():
        if rs[0]["expected"] is None or rs[0]["expected"] == "AMBIG":
            ok = sum(1 for r in rs if r["res"]["status"] != "answered")
            out.append((cat, len(rs), ok / len(rs), None, "correctly did not answer"))
        else:
            top1 = sum(1 for r in rs if r["ids"][:1] == [r["exp_id"]]) / len(rs)
            ok = sum(1 for r in rs if r["res"]["status"] == "answered" and r["res"]["faq_id"] == r["exp_id"]) / len(rs)
            out.append((cat, len(rs), ok, top1, "answered correctly"))
    return out


def calibration(rows):
    bins = [(0, .3), (.3, .55), (.55, .75), (.75, 1.01)]
    out = []
    for lo, hi in bins:
        rs = [r for r in rows if lo <= r["res"]["confidence"] < hi and r["expected"] not in ("AMBIG",)]
        if rs:
            acc = sum(1 for r in rs if (r["res"]["faq_id"] == r["exp_id"] if r["exp_id"] else False)
                      or (r["exp_id"] is None and r["res"]["status"] != "answered")) / len(rs)
            out.append((f"{lo:.2f}-{min(hi, 1):.2f}", len(rs), acc))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report")
    a = ap.parse_args()
    cases = json.load(open(os.path.join(HERE, "data", "eval_set.json"), encoding="utf-8"))
    eng, key2id = build()
    rows = run(eng, cases, key2id)
    m = metrics(rows)
    L = ["# TrustFAQ evaluation report", "",
         f"Test set: {len(cases)} queries ({m['n_answerable']} answerable, {m['n_negative']} unknown/unrelated, "
         f"{m['n_ambiguous']} ambiguous). Knowledge base: {len(eng.faqs)} FAQs. "
         f"Thresholds: answer>={eng.answer_th}, clarify>={eng.clarify_th}. Dense embeddings: {'on' if eng.dense else 'off'}.", "",
         "## Headline metrics", "", "| Metric | Value |", "|---|---|"]
    for k in ("top1", "top3", "mrr", "answered_correct", "clarified_with_correct_option", "safe_success", "answered_wrong", "abstained_on_answerable", "selective_accuracy",
              "unknown_precision", "unknown_recall", "unknown_f1", "false_answer_rate_negatives", "ambiguous_not_answered"):
        v = m[k]
        L.append(f"| {k} | {'n/a' if v is None else f'{v:.3f}'} |")
    L += [f"| latency p50 / p95 (ms) | {m['p50_ms']:.1f} / {m['p95_ms']:.1f} |", "", "## By category", "",
          "| Category | n | Success | Top-1 retrieval | Success means |", "|---|---|---|---|---|"]
    for cat, n, ok, t1, what in per_category(rows):
        L.append(f"| {cat} | {n} | {ok:.2f} | {'-' if t1 is None else f'{t1:.2f}'} | {what} |")
    L += ["", "## Calibration (confidence bin -> fraction of cases handled correctly)", "", "| Confidence | n | Correct |", "|---|---|---|"]
    for b, n, acc in calibration(rows):
        L.append(f"| {b} | {n} | {acc:.2f} |")
    L += ["", "## Threshold sweep (answer threshold)", "",
          "| Threshold | Answered correctly | Answered wrongly | False answers on unknown/unrelated | Abstained on answerable |", "|---|---|---|---|---|"]
    for th in (0.35, 0.45, 0.55, 0.65, 0.75):
        e2, k2 = build(th)
        mm = metrics(run(e2, cases, k2))
        L.append(f"| {th} | {mm['answered_correct']:.3f} | {mm['answered_wrong']:.3f} | {mm['false_answer_rate_negatives']:.3f} | {mm['abstained_on_answerable']:.3f} |")
    L += ["", "## Failures (for error analysis)", "", "| Category | Query | Expected | Got (status, FAQ) | Conf |", "|---|---|---|---|---|"]
    id2q = {f["id"]: f["question"] for f in eng.faqs}
    for r in rows:
        res = r["res"]
        good = (res["status"] == "answered" and res["faq_id"] == r["exp_id"]) if r["exp_id"] else res["status"] != "answered"
        if not good:
            L.append(f"| {r['category']} | {r['query'][:60]} | {id2q.get(r['exp_id'], r['expected'])} | {res['status']}, {id2q.get(res['faq_id'], '-')} | {res['confidence']:.2f} |")
    L += ["", "> Limits: small hand-written test set from one author, one sample KB. Numbers show the pipeline behaves sensibly "
          "on this data, not that it will reach the same accuracy on another institute's FAQs. Re-run on your own KB before quoting figures."]
    text = "\n".join(L)
    print(text)
    if a.report:
        os.makedirs(os.path.dirname(os.path.abspath(a.report)), exist_ok=True)
        open(a.report, "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
