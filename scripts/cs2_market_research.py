#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike: do bookmaker closes (CS2Odds) improve the series model, the shown chance, or picks?
Pre-registered in research/cs2_market_prereg.md (five tests, Holm, t over days).

    python3 scripts/cs2_market_research.py            # -> data/cs2_market_research.json

Needs the CS2Odds page cache from scripts/cs2_cs2odds_research.py (day pages) and match pages in
scripts/.cache/cs2odds/m (opening prices, H5 only). Nothing dated Nov 11 2026 or later is read.
"""
import gzip
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_cs2odds_research as CO  # noqa: E402
import cs2_model as CM  # noqa: E402
from cs2_data import key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_market_research.json"
MCACHE = CO.CACHE / "m"
END, START, BURN = "2026-11-10", "2026-09-19", "2026-10-01"
HL, SHR, NEW = 30.0, 5.0, 30


def ordd(d):
    return date.fromisoformat(d).toordinal()


def lg(p):
    return CO.lg(p)


def consensus(q, lo=0.0, hi=CO.FRESH):
    v = [lg(x["p"]) for x in q.values() if lo <= x["age"] <= hi]
    return float(np.mean(v)) if v else None


def base_rows():
    """All Valve rows from Aug 2024 with base logits (tune-fit weights) and each team's prior series count."""
    import cs2_nov13_research as R
    R.vrs_factors = lambda: {}
    lab = R.Lab()
    base = [r for r in lab.rows() if r["d"] >= CM.TUNE[0]]
    L, _ = R.tiered(R.tune(base), base)
    cnt, out = {}, []
    for r, l in sorted(zip(base, L), key=lambda z: z[0]["d"]):
        out.append(dict(d=r["d"], a=r["a"], b=r["b"], s=float(r["s"]), top=bool(r["top"]), L=float(l),
                        na=cnt.get(r["a"], 0), nb=cnt.get(r["b"], 0)))
        cnt[r["a"]] = cnt.get(r["a"], 0) + 1
        cnt[r["b"]] = cnt.get(r["b"], 0) + 1
    return [r for r in out if r["d"] <= END]


def market_series():
    """Finished CS2Odds series up to END with a consensus close: (day, keyA, keyB, close logit A, stale logit A, tp?)"""
    out = []
    for m in CO.matches():
        res = m.get("result") or {}
        d = m["scheduledStartAt"][:10]
        if d > END or m["status"] not in ("completed", "completed_provisional") or \
                res.get("winnerSide") not in ("team_a", "team_b"):
            continue
        q = CO.closes(m)
        c = consensus(q)
        out.append(dict(d=d, a=key(m["teamA"]["name"]), b=key(m["teamB"]["name"]), c=c,
                        stale=consensus({b: v for b, v in q.items() if b != "thunderpick"}, CO.FRESH, 48.0),
                        tp="thunderpick" in q, y=float(res["winnerSide"] == "team_a"), slug=m["slug"], q=q))
    return out


def link(MS, BR):
    """Attach the base logit (from team A's side) to each market series found among the Valve rows (+-1 day)."""
    idx = {}
    for i, r in enumerate(BR):
        if r["d"] >= START:
            idx.setdefault(frozenset([r["a"], r["b"]]), []).append(i)
    used = set()
    for s in MS:
        best = None
        for i in idx.get(frozenset([s["a"], s["b"]]), []):
            dd = abs(ordd(BR[i]["d"]) - ordd(s["d"]))
            if dd <= 1 and i not in used and (best is None or dd < best[0]):
                best = (dd, i)
        if best:
            used.add(best[1])
            r = BR[best[1]]
            flip = r["a"] != s["a"]
            if (1 - r["s"] if flip else r["s"]) == s["y"]:
                s["L"], s["row"] = (-r["L"] if flip else r["L"]), best[1]


def residual_feature(MS, BR):
    """H1: per row, resA - resB from earlier days' (close - base) gaps, decayed and shrunk."""
    ev = sorted((s for s in MS if "L" in s and s["c"] is not None), key=lambda s: s["d"])
    f = np.zeros(len(BR))
    for i, r in enumerate(BR):
        if r["d"] < BURN:
            continue
        t = ordd(r["d"])

        def res(team):
            num = den = 0.0
            for s in ev:
                if s["d"] >= r["d"]:
                    break
                if team in (s["a"], s["b"]):
                    g = (s["c"] - s["L"]) * (1 if s["a"] == team else -1)
                    w = 0.5 ** ((t - ordd(s["d"])) / HL)
                    num, den = num + w * g, den + w
            return num / (den + SHR) if den else 0.0
        f[i] = res(r["a"]) - res(r["b"])
    return f


def rating_feature(MS, BR):
    """H2: ridge Bradley-Terry on earlier days' consensus closes (decayed), refit per day; term = rA - rB."""
    ev = [s for s in MS if s["c"] is not None]
    f = np.zeros(len(BR))
    for d in sorted({r["d"] for r in BR if r["d"] >= BURN}):
        past = [s for s in ev if s["d"] < d]
        teams = sorted({s["a"] for s in past} | {s["b"] for s in past})
        ix = {k: j for j, k in enumerate(teams)}
        X = np.zeros((len(past), len(teams)))
        for j, s in enumerate(past):
            X[j, ix[s["a"]]], X[j, ix[s["b"]]] = 1, -1
        y = np.array([s["c"] for s in past])
        w = 0.5 ** ((ordd(d) - np.array([ordd(s["d"]) for s in past])) / HL)
        A = X.T @ (X * w[:, None]) + np.eye(len(teams))
        rt = np.linalg.solve(A, X.T @ (w * y))
        for i, r in enumerate(BR):
            if r["d"] == d and r["a"] in ix and r["b"] in ix:
                f[i] = rt[ix[r["a"]]] - rt[ix[r["b"]]]
    return f


def tday(dl, days):
    ud = sorted(set(days))
    a = np.array([dl[days == d].mean() for d in ud])
    return float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a))), len(ud)


def term_test(BR, f):
    rows = [i for i, r in enumerate(BR) if BURN <= r["d"] <= END]
    y = np.array([BR[i]["s"] for i in rows])
    L = np.array([BR[i]["L"] for i in rows])
    x = f[rows]
    days = np.array([BR[i]["d"] for i in rows])
    top = np.array([BR[i]["top"] for i in rows])
    X = np.column_stack([L, x])
    Lb = np.zeros(len(rows))
    for d in sorted(set(days)):
        te = days == d
        Lb[te] = X[te] @ CM.fitlog(X[~te], y[~te], l2=1e-2)
    l0 = CM.ll(1 / (1 + np.exp(-L)), y)
    dl = CM.ll(1 / (1 + np.exp(-Lb)), y) - l0
    t, nd = tday(dl, days)
    w = CM.fitlog(X, y, l2=1e-2)
    return {"n": len(rows), "nonzero": int((x != 0).sum()), "days": nd, "llBase": round(float(l0.mean()), 4),
            "d": round(float(dl.mean()), 5), "t": round(t, 2), "top50": round(float(dl[top].mean()), 5),
            "w": [round(float(z), 3) for z in w]}


def h4(MS):
    rows = [s for s in MS if "L" in s and not s["tp"] and s["stale"] is not None]
    y = np.array([s["y"] for s in rows])
    L = np.array([s["L"] for s in rows])
    X = np.column_stack([L, [s["stale"] for s in rows]])
    days = np.array([s["d"] for s in rows])
    Lb = np.zeros(len(rows))
    for d in sorted(set(days)):
        te = days == d
        Lb[te] = X[te] @ CM.fitlog(X[~te], y[~te], l2=1e-2)
    l0 = CM.ll(1 / (1 + np.exp(-L)), y)
    dl = CM.ll(1 / (1 + np.exp(-Lb)), y) - l0
    t, nd = tday(dl, days)
    w = CM.fitlog(X, y, l2=1e-2)
    return {"n": len(rows), "days": nd, "llBase": round(float(l0.mean()), 4),
            "llBlend": round(float((l0 + dl).mean()), 4), "d": round(float(dl.mean()), 5), "t": round(t, 2),
            "w": [round(float(z), 3) for z in w]}


def openings(slug):
    """Match page -> {book: (open p A, close p A)} on the match-winner market (both sides opened and closed)."""
    f = MCACHE / f"{slug}.html.gz"
    if not f.exists():
        return None
    s = gzip.decompress(f.read_bytes()).decode("utf-8", "replace")
    raw = "".join(json.loads('"' + c + '"') for c in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', s, re.S))
    i = raw.find('"marketType":"match_winner"')
    if i < 0:
        return None
    j = raw.find('"marketType"', i + 30)
    seg = raw[i:j if j > 0 else len(raw)]
    sides = re.split(r'"outcomeKey":"team_', seg)[1:]
    q = {}
    for side in sides:
        sd = side[0]
        for m in re.finditer(r'"bookmakerName":"([^"]+)"[^{}]*?"decimalOdds":([\d.]+)[^{}]*?"openingOdds":([\d.]+|null)',
                             side):
            if m.group(3) != "null":
                q.setdefault(m.group(1), {})[sd] = (float(m.group(3)), float(m.group(2)))
    out = {}
    for b, v in q.items():
        if "a" in v and "b" in v:
            (oa, ca), (ob, cb) = v["a"], v["b"]
            out[b] = ((1 / oa) / (1 / oa + 1 / ob), (1 / ca) / (1 / ca + 1 / cb))
    return out


def h5(MS):
    rows = []
    for s in MS:
        if "L" not in s:
            continue
        q = openings(s["slug"])
        if not q:
            continue
        o = float(np.mean([lg(v[0]) for v in q.values()]))
        c = float(np.mean([lg(v[1]) for v in q.values()]))
        if abs(o - c) > 3:
            continue
        rows.append((s["d"], s["L"] - o, c - o))
    if len(rows) < 50:
        return {"n": len(rows), "note": "too few match pages"}
    days = np.array([r[0] for r in rows])
    g, mv = np.array([r[1] for r in rows]), np.array([r[2] for r in rows])
    k = float((g @ mv) / (g @ g))
    ud = sorted(set(days))
    ks = np.array([(g[days == d] @ mv[days == d]) / max(g[days == d] @ g[days == d], 1e-9) for d in ud])
    wd = np.array([g[days == d] @ g[days == d] for d in ud])
    kw = float((ks * wd).sum() / wd.sum())
    # t over days of each day's contribution to the pooled slope
    a = np.array([(g[days == d] @ mv[days == d]) for d in ud]) / (g @ g) * len(ud)
    t = float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a)))
    moved = float(np.mean(np.abs(mv) > 1e-6))
    return {"n": len(rows), "days": len(ud), "k": round(k, 4), "kDayW": round(kw, 4), "t": round(t, 2),
            "shareMoved": round(moved, 3), "gapSd": round(float(g.std()), 3)}


def holm(res):
    from scipy import stats
    ps = {k: float(stats.norm.cdf(v["t"] if k != "H5" else -v["t"])) for k, v in res.items() if "t" in v}
    order = sorted(ps, key=ps.get)
    ok = True
    for j, k in enumerate(order):
        ok = ok and ps[k] <= .025 / (len(order) - j)
        res[k]["p"] = round(ps[k], 5)
        res[k]["holm"] = bool(ok)
    for k, v in res.items():
        top_ok = v.get("top50", 0) <= 0
        v["pass"] = bool(v.get("holm") and top_ok and (v["d"] < 0 if "d" in v else v.get("k", 0) > 0))


def main():
    BR = base_rows()
    MS = market_series()
    link(MS, BR)
    newc = np.array([min(r["na"], r["nb"]) < NEW for r in BR])
    f1 = residual_feature(MS, BR)
    f2 = rating_feature(MS, BR)
    res = {"H1": term_test(BR, f1), "H2": term_test(BR, f2), "H3": term_test(BR, np.where(newc, f1, 0.0)),
           "H4": h4(MS), "H5": h5(MS)}
    holm(res)
    out = {"prereg": "research/cs2_market_prereg.md", "window": [START, END], "burn": BURN,
           "marketSeries": len(MS), "linked": sum("L" in s for s in MS), "tests": res}
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
