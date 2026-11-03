#!/usr/bin/env python3
"""CS2 RWA staple audit (Nov 3 2026) -> data/cs2_rwa_research_nov03.json.

Pre-registered (before results):
  leak  : which settings touch HELD (Jul 2025+): stat weights, a scale, grid h/k/pm, tier lift.
  C1    : joint tune of half-life h, shrink k rounds and plus-minus share pm (tier lift fixed .5) on the TUNE months
          (a on even months, scored on odd), best one scored once on HELD vs shipped.
Gate: held paired t on per-map squared error < -2 (one CS2 test, Holm = plain cut), a majority of held months better.
"""
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_players as P  # noqa: E402

OUT = P.ROOT / "data" / "cs2_rwa_research_nov03.json"


def per_month(M, c, p, mos):
    return [P.map_sq(M, c, p, [mo]) for mo in mos]


def main():
    t0 = time.time()
    M = P.Maps()
    fj = json.loads(P.FIT.read_text())
    base = dict(fj["params"])
    last = dt.date.fromordinal(int(M.gd.max()))
    tune_g = M.gd < P.ordd(P.TUNE[1])
    beta, ml, _ = P.stat_weights(M, tune_g)
    tm, hm = P.months(*P.TUNE, last), P.months(*P.HELD, last)
    cs = {}

    def cc(pm):
        if pm not in cs:
            cs[pm] = P.contributions(M, beta, ml, pm)
        return cs[pm]
    res = {"base": base, "tuneMonths": tm, "heldMonths": hm}
    res["leak"] = {"statWeightsGamesBefore": P.TUNE[1], "aScaleMonths": tm[::2], "gridScoredMonths": tm[1::2],
                   "heldFrom": P.HELD[0], "heldTouched": False}
    grid = []
    for h in (90, 120, 180, 270):
        for k in (10, 15, 25, 40):
            for pm in (0.35, 0.5, 0.65, 0.8):
                p = dict(base, h=h, k=k, pm=pm)
                p["a"] = P.fit_scale(M, cc(pm), p, tm[::2])
                e, b0, n = P.predict_score(M, cc(pm), p, tm[1::2])
                grid.append((e, h, k, pm, p["a"]))
                print(f"h {h} k {k} pm {pm} a {p['a']:.3f} tune {e:.6f} ({time.time()-t0:.0f}s)", file=sys.stderr,
                      flush=True)
    grid.sort()
    e_b = next(g[0] for g in grid if g[1] == base["h"] and g[2] == base["k"] and g[3] == base["pm"])
    res["tuneGrid"] = [[round(g[0], 7), g[1], g[2], g[3], round(g[4], 3)] for g in grid[:8]]
    res["tuneShipped"] = round(e_b, 7)
    _, h, k, pm, a = grid[0]
    new = dict(base, h=h, k=k, pm=pm, a=a)
    bp = dict(base)
    bp["a"] = P.fit_scale(M, cc(base["pm"]), bp, tm[::2])
    e0m = per_month(M, cc(base["pm"]), bp, hm)
    e1m = per_month(M, cc(pm), new, hm)
    e0, e1 = np.concatenate(e0m), np.concatenate(e1m)
    flat = np.concatenate(per_month(M, cc(base["pm"]), dict(bp, a=0.0), hm)).mean()
    d = e1 - e0
    t = float(d.mean() / (d.std() + 1e-12) * math.sqrt(len(d)))
    better = sum(1 for x, y in zip(e0m, e1m) if len(x) and y.mean() < x.mean())
    same = (h, k, pm) == (base["h"], base["k"], base["pm"])
    res["C1"] = {"pick": {"h": h, "k": k, "pm": pm}, "r2Base": round(float(1 - e0.mean() / flat), 4),
                 "r2New": round(float(1 - e1.mean() / flat), 4), "t": round(t, 2) if not same else 0.0,
                 "n": int(len(d)), "monthsBetter": better, "months": len(hm), "same": same}
    res["C1"]["pass"] = bool(t < -2 and better > len(hm) / 2 and not same)
    print(json.dumps(res["C1"]), file=sys.stderr)
    OUT.write_text(json.dumps(res, indent=1, allow_nan=False))


if __name__ == "__main__":
    main()
