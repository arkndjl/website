#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Port pass Nov 23 (prereg.md C1, C2): CS2 letdown spot in the series model; series-model player Elo as a prospect FV
input. Lockbox: nothing after 2026-11-10 is read.
    python3 scripts/research/port_nov23/tennis_cs/cs2_port.py  -> cs2_results.json beside this file"""
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

OUTD = Path(__file__).resolve().parent
sys.path.insert(0, str(OUTD.parent.parent.parent))
import cs2_nov13_research as R  # noqa: E402
import cs2_model as CM  # noqa: E402
import cs2_players as P  # noqa: E402
import cs2_bo3  # noqa: E402
import names  # noqa: E402

END = "2026-11-10"
R.vrs_factors = lambda: {}  # the VRS factor tables are not used here (no Valve clone needed)


def ld_flags(rows):
    """C1: team won its previous series as an underdog (Elo chance < .35) and plays again within 4 days"""
    last = {}
    out = []
    for r in rows:
        f = {}
        for side, k in (("a", r["a"]), ("b", r["b"])):
            q = last.get(k)
            gap = (dt.date.fromisoformat(r["d"][:10]) - dt.date.fromisoformat(q[0][:10])).days if q else 99
            f[side] = 1.0 if q and q[1] and q[2] < .35 and gap <= 4 else 0.0
        out.append(f["a"] - f["b"])
        pa = 1 / (1 + 10 ** (-r["x"]))
        last[r["a"]] = (r["d"], r["s"] == 1, pa)
        last[r["b"]] = (r["d"], r["s"] == 0, 1 - pa)
    return out


def cv_tune(tr, f):
    """leave-one-month-out log loss on the tune window"""
    mo = np.array([r["d"][:7] for r in tr])
    L = np.zeros(len(tr))
    for m in sorted(set(mo)):
        a = [r for r, x in zip(tr, mo) if x != m]
        b = [r for r, x in zip(tr, mo) if x == m]
        idx = np.where(mo == m)[0]
        L[idx] = R.tiered(a, b, f)[0]
    return L


def c1(lab):
    rows = lab.rows()
    rows = [r for r in rows if r["d"] <= END]
    for r, v in zip(rows, ld_flags(rows)):
        r["ld"] = v
    tr, he = R.tune(rows), [r for r in R.held(rows) if r["d"] <= END]
    fb, fc = R.BASE, (lambda r: R.BASE(r) + [r["ld"]])
    lt = R.loss(cv_tune(tr, fc), tr) - R.loss(cv_tune(tr, fb), tr)
    Lb, wb = R.tiered(tr, he, fb)
    Lc, wc = R.tiered(tr, he, fc)
    dl = R.loss(Lc, he) - R.loss(Lb, he)
    return {"flagged": int(sum(1 for r in rows if r["ld"] != 0)), "tune": R.tt(lt, tr), "held": R.tt(dl, he),
            "w": wc, "llBase": round(float(R.loss(Lb, he).mean()), 5)}


def c2(lab):
    M, c, p = lab.M, lab.c, lab.fj["params"]
    pdir = P.load_pdir()
    lim = P.ordd(END)
    cuts, d = [], dt.date(2024, 10, 1)
    while d.toordinal() + 365 <= lim:
        cuts.append(d.toordinal())
        d = (d + dt.timedelta(days=92)).replace(day=1)
    iso = [dt.date.fromordinal(T).isoformat() for T in cuts]
    bo3 = cs2_bo3.Bo3(lab.bo3d)
    _, st = CM.replay(lab.series, lab.vrs, dict(lab.p), bo3=bo3, snaps=iso)
    nk, _ = P.nick_index(M, bo3)
    data = []
    for T, s in zip(cuts, iso):
        pl = st["snaps"][s]["pl"]
        elo = np.full(len(M.pids), np.nan)
        for nick, v in pl.items():
            i = nk.get(names.key(nick))
            if i is not None:
                elo[i] = v
        pr = P.prospect_rows(M, c, p, T, pdir)
        thF, _ = P.ratings(M, c, T + 365, p)
        fut, rf = P.window_stats(M, c, thF, T, T + 365, p)
        i = pr["i"][rf[pr["i"]] >= 600]
        e = elo[i]
        data.append({"T": s, "th": pr["th"][i], "age": np.nan_to_num(pr["age"][i] - 22), "ss": pr["ss"][i],
                     "pe": np.nan_to_num(e / 400), "pm": np.isnan(e).astype(float), "y": fut[i],
                     "w": np.minimum(rf[i], 3000)})
    tune = [x for x in data if x["T"] < P.HELD[0]]
    held = [x for x in data if x["T"] >= P.HELD[0]]

    def stack(xs, cols):
        X = np.concatenate([np.column_stack([np.ones(len(x["y"]))] + [x[k] for k in cols]) for x in xs])
        return X, np.concatenate([x["y"] for x in xs]), np.concatenate([x["w"] for x in xs])
    out = {"cuts": iso, "nTune": int(sum(len(x["y"]) for x in tune)), "nHeld": int(sum(len(x["y"]) for x in held)),
           "eloCover": round(float(1 - np.concatenate([x["pm"] for x in data]).mean()), 3)}
    E = {}
    for nm, cols in (("base", ["th", "age", "ss"]), ("pelo", ["th", "age", "ss", "pe", "pm"])):
        X, y, w = stack(tune, cols)
        b = P.ols(X, y, w)
        Xh, yh, wh = stack(held, cols)
        E[nm] = (yh - Xh @ b, wh)
        out[nm] = {"b": [round(float(v), 4) for v in b], "mse": round(float((wh * E[nm][0] ** 2).sum() / wh.sum()), 4)}
    (eb, w), (ec, _) = E["base"], E["pelo"]
    dl = w * (ec ** 2 - eb ** 2)
    out["t"] = round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)
    from scipy import stats
    out["p"] = float(stats.norm.cdf(out["t"]))
    return out


def main():
    lab = R.Lab()
    res = {"C1_LD": c1(lab)}
    print("C1", json.dumps(res["C1_LD"]))
    res["C2_PELO"] = c2(lab)
    print("C2", json.dumps(res["C2_PELO"]))
    (OUTD / "cs2_results.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
