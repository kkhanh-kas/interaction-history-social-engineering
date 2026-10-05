import json, re, sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def check(d):
    rows = [json.loads(l) for l in open(d / "attempts.jsonl", encoding="utf-8")]
    hist, s_in_a = {}, 0
    t1, allt, anyt = (defaultdict(lambda: [0, 0]) for _ in range(3))  # (cond, pos) -> [hits, total]
    for r in rows:
        h = hist.setdefault(r["hid"], json.load(open(d / ("hist-%d.json" % r["hid"]), encoding="utf-8")))
        recs = {x["id"]: x for x in h["records"]}
        key = r["cond"], r["main_pos"]
        hits = [any(x["session"] == "main" for x in t["retrieved"]) for t in r["turns"] if "retrieved" in t]
        t1[key][0] += hits[0]
        t1[key][1] += 1
        allt[key][0] += sum(hits)
        allt[key][1] += len(hits)
        anyt[key][0] += any(hits)
        anyt[key][1] += 1
        if r["cond"] == "A":
            for t in r["turns"]:
                for x in t.get("retrieved", []):
                    rec = recs[x["id"]]
                    if rec["with"] == h["S"] or re.search(r"\b%s\b" % re.escape(h["S"]), rec["text"].replace("{P}", h["R"])):
                        s_in_a += 1
    print("#####", d.name, "| records in A's context carrying S's name:", s_in_a)
    print("  cond pos   turn 1     all turns   any turn")
    for c in "ABC":
        for p in (0, 1, 2, None):
            keys = [k for k in t1 if k[0] == c and (p is None or k[1] == p)]
            cell = lambda m: "%d/%d" % tuple(map(sum, zip(*(m[k] for k in keys))))
            print("  %s    %-4s  %-10s %-11s %s" % (c, "all" if p is None else p, cell(t1), cell(allt), cell(anyt)))


if __name__ == "__main__":
    for d in sys.argv[1:] or ["data-main", "data-main-deepseek"]:
        check(HERE / d)
