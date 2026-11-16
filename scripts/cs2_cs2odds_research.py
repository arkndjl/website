#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike series model against bookmaker closing prices from CS2Odds (https://cs2odds.com/results).

    python3 scripts/cs2_cs2odds_research.py           # fetch (cached), join, score -> data/cs2_cs2odds_research.json

CS2Odds' results-by-day pages carry each finished series' last pre-start price per bookmaker (1xBet, 22Bet,
Thunderpick, Cloudbet, BC.Game, Stake ...), with the time it was seen and the result. History starts 19 Sep 2026.
robots.txt allows all; one page per UTC day, fetched at a slow rate and cached in scripts/.cache/cs2odds.

Checks: (1) Thunderpick closes against our own forward Thunderpick archive (scripts/data/odds_tp); (2) results
against Valve's series; (3) the live four-term series model, weights by tier fit on the tune window only (as in
scripts/cs2_nov13_research.py), against the de-vigged consensus close: log loss, and whether the model adds to the
close (logistic on both logits, leave-one-day-out, t over days). Valve rows run to the latest VRS snapshot (~Nov 1),
so the 2026-27 lockbox (Nov 11 on) is never read.
"""
import gzip
import json
import math
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_model as CM  # noqa: E402
from cs2_data import key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / ".cache" / "cs2odds"
OUT = ROOT / "data" / "cs2_cs2odds_research.json"
SITE = "https://cs2odds.com"
UA = "Mozilla/5.0 (compatible; arkndjl-research)"
FRESH = 2.0  # hours: a book's close counts only if seen this close to the scheduled start


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def days():
    xml = get(SITE + "/results/sitemap.xml")
    return re.findall(r"<loc>https://cs2odds\.com/results/(\d{4}-\d\d-\d\d)</loc>", xml)


def fetch():
    CACHE.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    for d in days():
        f = CACHE / f"{d}.html.gz"
        if f.exists() and d < today:
            continue
        f.write_bytes(gzip.compress(get(f"{SITE}/results/{d}").encode()))
        time.sleep(1.5)


def matches():
    """Every series on the cached day pages (the page's own data, read from the Next.js payload)."""
    dec, out = json.JSONDecoder(), {}
    for f in sorted(CACHE.glob("*.html.gz")):
        s = gzip.decompress(f.read_bytes()).decode()
        raw = "".join(json.loads('"' + c + '"') for c in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', s, re.S))
        for m in re.finditer(r'\{"match":\{"id"', raw):
            try:
                o, _ = dec.raw_decode(raw, m.start() + 9)
            except ValueError:
                continue
            out[o["id"]] = o
    return list(out.values())


def ts(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def lg(p):
    p = min(max(p, .005), .995)
    return math.log(p / (1 - p))


def closes(m):
    """book -> {p: de-vigged chance team A, over: overround, age: hours before start}"""
    c = m.get("closing") or {}
    qa, qb = ({q["bookmakerSlug"]: q for q in (c.get(s) or {}).get("quotes", []) if q.get("closeStatus") == "captured"}
              for s in ("teamA", "teamB"))
    st = ts(m["scheduledStartAt"])
    out = {}
    for bk in set(qa) & set(qb):
        a, b = 1 / qa[bk]["decimalOdds"], 1 / qb[bk]["decimalOdds"]
        out[bk] = {"p": a / (a + b), "over": a + b, "age": (st - ts(qa[bk]["observedAt"])).total_seconds() / 3600}
    return out


def tp_check(M):
    """CS2Odds' Thunderpick close vs the last pre-start price in our own Thunderpick archive, same series."""
    tp = {}
    for f in (ROOT / "scripts" / "data" / "odds_tp").glob("cs2-*.jsonl"):
        for ln in f.read_text().splitlines():
            r = json.loads(ln)
            if ts(r["t"]) < ts(r["start"]) and (r["id"] not in tp or r["t"] > tp[r["id"]]["t"]):
                tp[r["id"]] = r
    idx = {}
    for r in tp.values():
        idx.setdefault(frozenset([key(r["n1"]), key(r["n2"])]), []).append(r)
    same, dp = 0, []
    for m in M:
        q = closes(m).get("thunderpick")
        if not q:
            continue
        a = key(m["teamA"]["name"])
        for r in idx.get(frozenset([a, key(m["teamB"]["name"])]), []):
            if abs((ts(r["start"]) - ts(m["scheduledStartAt"])).total_seconds()) < 6 * 3600:
                o1, o2 = (r["o1"], r["o2"]) if key(r["n1"]) == a else (r["o2"], r["o1"])
                p = (1 / o1) / (1 / o1 + 1 / o2)
                dp.append(abs(q["p"] - p))
                same += abs(q["p"] - p) < 1e-3
                break
    dp = np.array(dp)
    return {"n": len(dp), "same": int(same), "medianAbsDp": round(float(np.median(dp)), 4),
            "meanAbsDp": round(float(dp.mean()), 4), "over5pp": int((dp > .05).sum())}


def model_rows():
    """Held-out logits of the live four-term model (tune-window weights) for Valve series from Sep 2026."""
    import cs2_nov13_research as R
    R.vrs_factors = lambda: {}  # the factor tables are not part of the base model
    lab = R.Lab()
    base = lab.rows()
    he = R.held(base)
    L0, w = R.tiered(R.tune(base), he)
    return [dict(d=r["d"], a=r["a"], b=r["b"], s=r["s"], top=bool(r["top"]), L=float(lg_)) for r, lg_ in zip(he, L0)
            if r["d"] >= "2026-09-01"], w


def join(M, MR):
    idx = {}
    for i, r in enumerate(MR):
        idx.setdefault(frozenset([r["a"], r["b"]]), []).append(i)
    used, out, agree = set(), [], 0
    for m in M:
        res = m.get("result") or {}
        if m["status"] not in ("completed", "completed_provisional") or res.get("winnerSide") not in ("team_a", "team_b"):
            continue
        q = closes(m)
        if not q:
            continue
        st, A = ts(m["scheduledStartAt"]), key(m["teamA"]["name"])
        best = None
        for i in idx.get(frozenset([A, key(m["teamB"]["name"])]), []):
            dd = abs((datetime.fromisoformat(MR[i]["d"]).date() - st.date()).days)
            if dd <= 1 and i not in used and (best is None or dd < best[0]):
                best = (dd, i)
        row = {"day": m["scheduledStartAt"][:10], "y": float(res["winnerSide"] == "team_a"), "q": q, "bo": m.get("bestOf")}
        if best:
            used.add(best[1])
            r = MR[best[1]]
            flip = r["a"] != A
            row.update(L=-r["L"] if flip else r["L"], top=r["top"], ok=(1 - r["s"] if flip else r["s"]) == row["y"])
            agree += row["ok"]
        out.append(row)
    return out, agree


def score(rows):
    y = np.array([r["y"] for r in rows])
    Lm, Lk = np.array([r["L"] for r in rows]), np.array([r["mk"] for r in rows])
    days_ = np.array([r["day"] for r in rows])
    ud = sorted(set(days_))
    X = np.column_stack([Lm, Lk])
    Lb, Lc = np.zeros(len(rows)), np.zeros(len(rows))
    for d in ud:
        te = days_ == d
        Lb[te] = X[te] @ CM.fitlog(X[~te], y[~te], l2=1e-2)
        Lc[te] = Lk[te, None] @ CM.fitlog(Lk[~te, None], y[~te], l2=1e-2)
    llm, llk = CM.ll(1 / (1 + np.exp(-Lm)), y), CM.ll(1 / (1 + np.exp(-Lk)), y)
    llb, llc = CM.ll(1 / (1 + np.exp(-Lb)), y), CM.ll(1 / (1 + np.exp(-Lc)), y)

    def tday(dl):
        a = np.array([dl[days_ == d].mean() for d in ud])
        return round(float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a))), 2)
    rng, ws = np.random.default_rng(0), []
    for _ in range(300):
        ix = np.concatenate([np.where(days_ == d)[0] for d in rng.choice(ud, len(ud))])
        ws.append(CM.fitlog(X[ix], y[ix], l2=1e-2)[0])
    w = CM.fitlog(X, y, l2=1e-2)
    return {"n": len(rows), "days": len(ud), "llModel": round(float(llm.mean()), 4), "llClose": round(float(llk.mean()), 4),
            "tModelVsClose": tday(llm - llk), "blendD": round(float((llb - llc).mean()), 4), "tBlend": tday(llb - llc),
            "wModel": round(float(w[0]), 3), "wModelSe": round(float(np.std(ws)), 3), "wClose": round(float(w[1]), 3),
            "accModel": round(float(np.mean((Lm > 0) == y)), 3), "accClose": round(float(np.mean((Lk > 0) == y)), 3)}


def main():
    if "--no-fetch" not in sys.argv:
        fetch()
    M = matches()
    MR, w = model_rows()
    J, agree = join(M, MR)
    ok = [r for r in J if r.get("ok")]
    age = np.array([min(v["age"] for v in r["q"].values()) for r in J])
    out = {"source": SITE + "/results", "window": [min(r["day"] for r in J), max(r["day"] for r in J)],
           "series": len(M), "withClose": len(J), "fresh": FRESH,
           "freshestBookAgeH": [round(float(x), 2) for x in np.percentile(age, [10, 50, 90])],
           "overroundMedian": round(float(np.median([np.median([v["over"] for v in r["q"].values()]) for r in J])), 3),
           "booksMean": round(float(np.mean([len(r["q"]) for r in J])), 2),
           "thunderpickVsArchive": tp_check(M), "joined": sum("L" in r for r in J), "resultsAgree": agree,
           "modelWeights": w, "tests": {}}
    for tag, flt, book, fresh in (("all", lambda r: True, None, FRESH), ("anyAge", lambda r: True, None, None),
                                  ("top50", lambda r: r["top"], None, FRESH), ("rest", lambda r: not r["top"], None, FRESH),
                                  ("bo3", lambda r: r["bo"] == 3, None, FRESH),
                                  ("thunderpick", lambda r: True, "thunderpick", None)):
        rows = []
        for r in ok:
            qs = [v for b, v in r["q"].items() if (book is None or b == book) and (fresh is None or v["age"] <= fresh)]
            if flt(r) and qs:
                rows.append(dict(r, mk=float(np.mean([lg(v["p"]) for v in qs]))))
        out["tests"][tag] = score(rows)
    t = out["tests"]["all"]
    out["pass"] = bool(t["blendD"] < 0 and t["tBlend"] <= -2)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
