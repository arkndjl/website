#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike over-confidence research: why the live series model's favourites won less than priced in some months
(Sep 2025, Jan 2026, Sep-Oct 2026; the model monitor's alarm), and whether a fix passes out of sample.

    python3 scripts/cs2_calib_research.py   -> data/cs2_calib_research.json (~2 min; the vintage check needs Valve's
                                               standings clone in scripts/.cache/cs/vrs, as cs2_data.py makes)

Rows are the live four-term model (player Elo, VRS points, team map rating, five's player rating), replayed the way
cs2_players.game_test scores it: weights by tier fit on Aug 2024 - Jun 2025, held Jul 2025 - Oct 2026.
Checks (no model change unless one passes):
  vintage    Is the weak latest month a data artefact? Valve lists a series only in snapshots after it, so older
             months gain series that later snapshots add; the latest month has none of those yet. Score each month on
             series a snapshot listed within 45 days (what the live model had) vs later additions.
  weak       term weights refit on the weak months vs the rest (which term loses power).
Pre-registered fixes (pass: held t by month, as the Nov 9 audit registered for this alarm, below the Holm cut for
the five tests, and top-50 t by month < -2, the Live gate; calibration drift is a month-level effect, so a series-level
t overstates it):
  stale      the logit x players' mean days since their last series (cap 90, /30) as a fifth term: rating uncertainty
             after breaks, the time the weak months follow.
  temp       walk-forward temperature by tier: logit slope on the 90 (or 180) days of rows ending 35 days before each
             month (Valve's lag), shrunk toward 1 with 1,000 rows.
  temp_top   the same on top-50 series only (the audit's top-50 Bo3 slope .79).
  expanding  weights refit each month on every row up to 35 days before it (vs the fixed tune fit).
"""
import datetime as dt
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_model as CM  # noqa: E402
import cs2_players as P  # noqa: E402
import names  # noqa: E402
from cs2_data import key  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "cs2_calib_research.json"
WEAK = ("2024-10", "2025-01", "2025-09", "2026-01", "2026-09", "2026-10")
END = "2026-11-01"
od = lambda d: dt.date.fromisoformat(d).toordinal()  # noqa: E731


def build_rows():
    fj = json.loads(P.FIT.read_text())
    M = P.Maps()
    p = fj["params"]
    c = P.contributions(M, np.array([fj["beta"][k] for k in P.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, CM.Vrs(H["vrs"]), json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    nk, nkt = P.nick_index(M, bo3)
    snaps, lastP, lastros = {}, {}, {}
    for r, S in zip(rows, series):
        mo = r["d"][:7]
        if mo not in snaps:
            snaps[mo] = P.ratings(M, c, P.ordd(mo + "-01"), p)[0]
        th = snaps[mo]

        def mean(ros, k):
            ix = [nkt.get((names.key(q), k), nk.get(names.key(q))) for q in ros or []]
            v = [th[i] for i in ix if i is not None]
            return np.mean(v) if len(v) >= 3 else None
        a, b = mean(S[4], r["a"]), mean(S[5], r["b"])
        r["z"] = (a - b) / 10 if a is not None and b is not None else 0.0
        d = od(S[0])
        ra, rb = S[4] or lastros.get(r["a"]), S[5] or lastros.get(r["b"])
        for k, ro in ((r["a"], S[4]), (r["b"], S[5])):
            if ro:
                lastros[k] = ro
        gp = [min(d - lastP.get(q, d - 90), 90) for ro in (ra, rb) for q in (ro or [])]
        r["gP"] = (np.mean(gp) if gp else 90) / 30
        for ro in (ra, rb):
            for q in ro or []:
                lastP[q] = d
        win = S[1] if S[3] == 0 else S[2]
        r["vk"] = (S[0],) + tuple(sorted((S[1], S[2]))) + (win,)
        del r["r"]
    return rows, fj["game"]["w"]


def lstats(R):
    if len(R) < 50:
        return {"n": len(R)}
    L = np.array([r["L"] for r in R])
    s = np.array([r["s"] for r in R])
    return {"n": len(R), "slope": round(float(CM.fitlog(L[:, None], s)[0]), 3),
            "ll": round(float(CM.ll(1 / (1 + np.exp(-L)), s).mean()), 4)}


def tt(dl, mo):
    ms = sorted(set(mo))
    a = np.array([dl[mo == m].mean() for m in ms])
    return {"d": round(float(dl.mean()), 5), "t": round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2),
            "tMonth": round(float(a.mean() / (a.std() + 1e-12) * math.sqrt(len(a))), 2),
            "monthsBetter": [int((a < 0).sum()), len(a)]}


def main():
    rows, W = build_rows()
    for r in rows:
        w = W["top"] if r["top"] else W["rest"]
        r["L"] = w[0] * r["x"] + w[1] * r["v"] + w[2] * r["t"] + w[3] * r["z"]
    out = {"held": ["2025-07-01", END], "weak": WEAK}
    # vintage
    vdir = CM.VRS / "live"
    if vdir.exists():
        import cs2_data
        sn, _ = cs2_data.parse_snapshots()
        first = {}
        for d in sorted(sn):
            for rs in sn[d].values():
                team, opp, wl, date, _ = rs[0]
                first.setdefault((date,) + tuple(sorted((team, opp))) + (team if wl == "W" else opp,), d)
        by = defaultdict(lambda: ([], []))
        for r in rows:
            f = first.get(r["vk"])
            lag = od(f) - od(r["d"]) if f else 999
            by[r["d"][:7]][0 if lag <= 45 else 1].append(r)
        out["vintage"] = {m: {"early": lstats(e), "late": lstats(l)} for m, (e, l) in sorted(by.items())
                          if "2024-09" <= m < END[:7]}
        he = [r for m, v in by.items() if "2025-07" <= m < END[:7] for r in v[0]]
        hl = [r for m, v in by.items() if "2025-07" <= m < END[:7] for r in v[1]]
        out["vintageHeld"] = {"early": lstats(he), "late": lstats(hl)}
    # term weights, weak months vs the rest
    out["weakWeights"] = {}
    for tier in (True, False):
        for nm, f in (("weak", lambda r: r["d"][:7] in WEAK), ("other", lambda r: r["d"][:7] not in WEAK)):
            R = [r for r in rows if "2024-08-07" <= r["d"] < END and r["top"] == tier and f(r)]
            X = np.array([[r["x"], r["v"], r["t"], r["z"]] for r in R])
            s = np.array([r["s"] for r in R])
            w = CM.fitlog(X, s)
            q = 1 / (1 + np.exp(-X @ w))
            se = np.sqrt(np.diag(np.linalg.inv((X * (q * (1 - q))[:, None]).T @ X)))
            out["weakWeights"][("top" if tier else "rest") + "_" + nm] = {
                "n": len(R), "w": [round(float(x), 3) for x in w], "se": [round(float(x), 3) for x in se]}
    # fixes
    tr = [r for r in rows if "2024-08-07" <= r["d"] <= "2025-06-30"]
    he = [r for r in rows if "2025-07-01" <= r["d"] < END]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])
    mo = np.array([r["d"][:7] for r in he])
    L = np.array([r["L"] for r in he])
    base = CM.ll(1 / (1 + np.exp(-L)), s)

    def tiered(F, trainf=None):
        q = np.zeros(len(he))
        for m in sorted(set(mo)) if trainf else [None]:
            for tier in (True, False):
                R = [r for r in (rows if trainf else tr) if r["top"] == tier and (trainf is None or trainf(r, od(m + "-01")))]
                w = CM.fitlog(np.array([F(r) for r in R]), np.array([r["s"] for r in R]))
                idx = np.where((top == tier) & ((mo == m) if m else True))[0]
                q[idx] = 1 / (1 + np.exp(-np.array([F(he[i]) for i in idx]) @ w))
        return CM.ll(q, s)

    def temp(days, tiers):
        z = L.copy()
        for m in sorted(set(mo)):
            T0 = od(m + "-01") - 35
            for tier in tiers:
                R = [r for r in rows if T0 - days <= od(r["d"]) < T0 and r["top"] == tier and r["d"] >= "2024-08-07"]
                b = CM.fitlog(np.array([[r["L"]] for r in R]), np.array([r["s"] for r in R]))[0]
                idx = (mo == m) & (top == tier)
                z[idx] = (len(R) * b + 1000) / (len(R) + 1000) * L[idx]
        return CM.ll(1 / (1 + np.exp(-z)), s)
    F4 = lambda r: [r["x"], r["v"], r["t"], r["z"]]  # noqa: E731
    base4 = tiered(F4)
    cands = {
        "stale": tiered(lambda r: F4(r) + [r["L"] * r["gP"]]) - base4 + base,
        "temp 90d": temp(90, (True, False)),
        "temp 180d": temp(180, (True, False)),
        "temp_top 90d": temp(90, (True,)),
        "expanding": tiered(F4, lambda r, T0: r["d"] >= "2024-08-07" and od(r["d"]) < T0 - 35),
    }
    res = {}
    for nm, l in cands.items():
        dl = l - base
        res[nm] = {"all": tt(dl, mo), "top50": tt(dl[top], mo[top]),
                   "weakMonths": {m: round(float(dl[mo == m].mean()), 4) for m in WEAK if (mo == m).any()}}
    # Holm over the five tests on the all-series t; the Live gate also needs top-50 t < -2
    order = sorted(res, key=lambda k: res[k]["all"]["tMonth"])
    going = True
    for i, nm in enumerate(order):
        cut = NormalDist().inv_cdf(1 - .025 / (len(order) - i))
        going = going and res[nm]["all"]["tMonth"] < -cut
        res[nm]["holmCut"] = round(-cut, 2)
        res[nm]["pass"] = bool(going and res[nm]["top50"]["tMonth"] < -2)
    out["base"] = {"n": len(he), "ll": round(float(base.mean()), 5), "slopeTop50": lstats([r for r in he if r["top"]]),
                   "slopeRest": lstats([r for r in he if not r["top"]])}
    out["fixes"] = res
    out["shipped"] = [k for k, v in res.items() if v["pass"]]
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("base", "fixes", "shipped")}, indent=1))


if __name__ == "__main__":
    main()
