#!/usr/bin/env python3
"""Nov 3 2026 game-model check: does each Nov 3 player-rating change (damage taken in STATS, tier lift, plus-minus,
headshots) help the SERIES model, not only the per-map rating fit? Same replay, tune / held windows and tiered
logistic as cs2_players.game_test; per-series log loss of the live model + each rating variant, paired against the
shipped rating.

    python3 scripts/cs2_gd_series_research.py     # -> data/cs2_gd_series_research.json
"""
import gzip, json, math, sys
import numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_players as CP
import cs2_model as CM
import cs2_bo3
import names

OUT = CP.ROOT / "data" / "cs2_gd_series_research.json"


def main():
    M = CP.Maps()
    fj = json.loads(CP.FIT.read_text())
    best = fj["params"]
    tune_g = M.gd < CP.ordd(CP.TUNE[1])
    X0 = M.X
    beta, ml, _ = CP.stat_weights(M, tune_g)
    var = {"shipped": (CP.contributions(M, beta, ml, best["pm"]), best)}
    M.X = X0[:, [CP.STATS.index(x) for x in CP.STATS if x != "gd"]]
    b, m, _ = CP.stat_weights(M, tune_g)
    var["no damage taken"] = (CP.contributions(M, b, m, best["pm"]), best)
    M.X = X0[:, [CP.STATS.index(x) for x in CP.STATS if x != "hs"]]
    b, m, _ = CP.stat_weights(M, tune_g)
    var["no headshots"] = (CP.contributions(M, b, m, best["pm"]), best)
    M.X = X0
    var["no tier lift"] = (var["shipped"][0], dict(best, ssg=0.0))
    var["no plus-minus"] = (CP.contributions(M, beta, ml, 0.0), dict(best, pm=0.0))

    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = CM.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, vrs, json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    nk, nkt = CP.nick_index(M, bo3)
    tr = [r for r in rows if CM.TUNE[0] <= r["d"] <= CM.TUNE[1] and r["d"] >= "2024-07-01"]
    he = [r for r in rows if r["d"] >= CM.HELD[0]]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])
    L = {}
    for nm, (c, p) in var.items():
        snaps = {}
        for r in rows:
            mo = r["d"][:7]
            if mo not in snaps:
                snaps[mo] = CP.ratings(M, c, CP.ordd(mo + "-01"), p)[0]
            th = snaps[mo]

            def mean(ros, k):
                v = [th[nkt.get((names.key(q), k), nk.get(names.key(q)))] for q in ros or []
                     if nkt.get((names.key(q), k), nk.get(names.key(q))) is not None]
                return np.mean(v) if len(v) >= 3 else None
            a, bb = mean(r["r"][4], r["a"]), mean(r["r"][5], r["b"])
            r["z"] = (a - bb) / 10 if a is not None and bb is not None else 0.0
        q = np.zeros(len(he))
        for tier in (True, False):
            t_ = [r for r in tr if r["top"] == tier]
            idx = [i for i, r in enumerate(he) if r["top"] == tier]
            w = CM.fitlog(np.array([[r["x"], r["v"], r["t"], r["z"]] for r in t_]), np.array([r["s"] for r in t_]))
            q[idx] = 1 / (1 + np.exp(-np.array([[he[i]["x"], he[i]["v"], he[i]["t"], he[i]["z"]] for i in idx]) @ w))
        L[nm] = CM.ll(q, s)
        print(nm, round(float(L[nm].mean()), 5), flush=True)
    out = {"n": len(he), "nTop50": int(top.sum()), "variants": {}}
    for nm, l in L.items():
        r = {"ll": round(float(l.mean()), 5), "top50": round(float(l[top].mean()), 5)}
        if nm != "shipped":
            for k, msk in (("t", np.ones(len(l), bool)), ("tTop50", top)):
                d = (L["shipped"] - l)[msk]   # negative = the shipped rating is better
                r[k] = round(float(d.mean() / (d.std() + 1e-12) * math.sqrt(len(d))), 2)
        out["variants"][nm] = r
    print(json.dumps(out, indent=1))
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
