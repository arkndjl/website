#!/usr/bin/env python3
"""Counter-Strike team RWA research, Nov 3 2026: does a team-level RWA add to the ARK Ranking's series model?

    python3 scripts/cs2_team_rwa_research.py   -> data/cs2_team_rwa_research.json (~10 min)

The live model already carries the five's MEAN player RWA (cs2_players.Live, PR #721). Three pre-registered team
versions, each scored the way cs2_players.game_test scores the shipped term (fit on series Jul 2024 - Jun 2025, held
Jul 2025 on, logistic by tier, ratings as of the first of the series' month, paired t on per-series log loss):
  unit   lineup RWA: what the roster wins as a unit beyond its players' RWA. Each map before the cutoff where 4+ of
         the series' five played together: round win % above 50 minus the five-vs-five RWA prediction, decayed
         (the ratings' half-life) and shrunk k rounds toward 0 (k picked on the fit window). A minus B, a 5th term.
  sum    roster sum of all five: a player without bo3.gg stats counts at the rating prior (0) instead of being dropped
         (the shipped term needs 3+ known per side and averages those). Replaces the shipped term.
  only   team RWA in place of player Elo: the shipped model without the player Elo term.
Ship rule: held all t below the Bonferroni cut for 3 tests (z(.025/3) = 2.39) and top-50 t < -2 (the Live gate).
"""
import gzip
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_players as P  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_team_rwa_research.json"
KS = (50, 200, 800)


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std() + 1e-12) * math.sqrt(len(d))), 2)


def main():
    import cs2_model as CM
    M = P.Maps()
    fj = json.loads(P.FIT.read_text())
    p = fj["params"]
    a = p["a"]
    c = P.contributions(M, np.array([fj["beta"][k] for k in P.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = CM.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, vrs, json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    rows = [r for r in rows if r["d"] >= "2024-07-01"]
    nk, nkt = P.nick_index(M, bo3)
    # each player's (game*2 + side) rows, for finding the maps a lineup played together
    gs_all = M.g * 2 + M.side
    by_p = {}
    order = np.argsort(M.p, kind="stable")
    bounds = np.searchsorted(M.p[order], np.arange(len(M.pids) + 1))
    for i in range(len(M.pids)):
        ix = order[bounds[i]:bounds[i + 1]]
        by_p[i] = (gs_all[ix], M.d[ix])
    Rg = np.array([g[4] + g[5] for g in M.games], float)
    snaps = {}

    def snap(T):
        if T not in snaps:
            th = P.ratings(M, c, T, p)[0]
            sA = th[M.p[M.five[:, 0]]].sum(1)
            sB = th[M.p[M.five[:, 1]]].sum(1)
            y0 = M.y[M.five[:, 0, 0]]
            r0 = 100 * (y0 - 0.5) - a * (sA - sB) / 2
            res = np.column_stack([r0, -r0]).ravel()  # index game*2 + side
            w = np.repeat(Rg * np.exp(-(T - M.gd) * math.log(2) / p["h"]) * (M.gd < T), 2)
            snaps[T] = (th, res, w)
        return snaps[T]

    def idx(ros, k):
        return [nkt.get((names.key(q), k), nk.get(names.key(q))) for q in ros or []]

    cov = {"unit": 0, "sum": 0}
    for r in rows:
        T = P.ordd(r["d"][:7] + "-01")
        th, res, w = snap(T)
        ia, ib = idx(r["r"][4], r["a"]), idx(r["r"][5], r["b"])
        ka, kb = [i for i in ia if i is not None], [i for i in ib if i is not None]
        ok = len(ka) >= 3 and len(kb) >= 3
        r["zm"] = (np.mean(th[ka]) - np.mean(th[kb])) / 10 if ok else 0.0
        # sum of the five, unknown players at the prior 0 (scaled per five so a short roster list is not penalised)
        okS = len(ka) >= 1 and len(kb) >= 1
        nA, nB = max(len(ia), 1), max(len(ib), 1)
        r["zs"] = (th[ka].sum() * 5 / nA - th[kb].sum() * 5 / nB) / 50 if okS else 0.0
        cov["sum"] += okS
        # lineup residual
        u = {}
        for side, kk in (("a", ka), ("b", kb)):
            if len(kk) < 4:
                u[side] = None
                continue
            g = np.concatenate([by_p[i][0][(by_p[i][1] < T) & (by_p[i][1] >= T - 365)] for i in kk])
            if not len(g):
                u[side] = (0.0, 0.0)
                continue
            vals, cnt = np.unique(g, return_counts=True)
            sel = vals[cnt >= 4]
            u[side] = (float((w[sel] * res[sel]).sum()), float(w[sel].sum()))
        r["u"] = u if u["a"] is not None and u["b"] is not None else None
        cov["unit"] += r["u"] is not None
    print("snaps", len(snaps), file=sys.stderr)
    tr = [r for r in rows if r["d"] <= CM.TUNE[1]]
    he = [r for r in rows if r["d"] >= CM.HELD[0]]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])

    def run(f, rs_tr=tr, rs_he=he):
        q = np.zeros(len(rs_he))
        ws = {}
        for tier in (True, False):
            t_ = [r for r in rs_tr if r["top"] == tier]
            ix = [i for i, r in enumerate(rs_he) if r["top"] == tier]
            wt = CM.fitlog(np.array([f(r) for r in t_]), np.array([r["s"] for r in t_]))
            ws["top" if tier else "rest"] = [round(float(z), 4) for z in wt]
            q[ix] = 1 / (1 + np.exp(-np.array([f(rs_he[i]) for i in ix]) @ wt))
        return CM.ll(q, np.array([r["s"] for r in rs_he])), ws

    def uz(r, k):
        if r["u"] is None:
            return 0.0
        (na, wa), (nb, wb) = r["u"]["a"], r["u"]["b"]
        return (na / (wa + k) - nb / (wb + k)) / 10

    base = lambda r: [r["x"], r["v"], r["t"], r["zm"]]  # noqa: E731
    l0, w0 = run(base)
    out = {"n": len(he), "coverage": {k: round(v / len(rows), 3) for k, v in cov.items()},
           "shipped": {"ll": round(float(l0.mean()), 4), "top50": round(float(l0[top].mean()), 4), "w": w0}}
    # k for the lineup term: fit window split in two (first half fits, second half scores)
    half = [r for r in tr if r["d"] < "2025-02-01"], [r for r in tr if r["d"] >= "2025-02-01"]
    kt = {}
    for k in KS:
        lt, _ = run(lambda r, k=k: base(r) + [uz(r, k)], half[0], half[1])
        lb, _ = run(base, half[0], half[1])
        kt[k] = round(float((lt - lb).mean()), 5)
    kbest = min(kt, key=kt.get)
    print("unit k on fit window", kt, "->", kbest, file=sys.stderr)
    tests = {"unit": lambda r: base(r) + [uz(r, kbest)],
             "sum": lambda r: [r["x"], r["v"], r["t"], r["zs"]],
             "only": lambda r: [r["v"], r["t"], r["zm"]]}
    for nm, f in tests.items():
        l1, ws = run(f)
        out[nm] = {"ll": round(float(l1.mean()), 4), "d": round(float((l1 - l0).mean()), 5), "t": tstat(l1 - l0),
                   "top50": {"ll": round(float(l1[top].mean()), 4), "t": tstat((l1 - l0)[top])}, "w": ws}
        print(nm, out[nm], file=sys.stderr)
    out["unit"]["k"] = kbest
    out["unit"]["kTune"] = kt
    cut = NormalDist().inv_cdf(1 - 0.025 / len(tests))
    out["cut"] = round(cut, 2)
    out["pass"] = [nm for nm in tests if out[nm]["t"] < -cut and out[nm]["top50"]["t"] < -2]
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print("pass", out["pass"], file=sys.stderr)


if __name__ == "__main__":
    main()
