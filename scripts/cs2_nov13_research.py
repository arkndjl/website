#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike model audit: new data (bo3.gg rounds, Valve's VRS factor tables) and eight series-model tests plus
two player-rating tests, pre-registered (research/cs2_nov13_prereg.md, committed before any held-out score was read).

    python3 scripts/cs2_nov13_research.py --tune    # grid picks on the tune window only -> data/cs2_nov13_tune.json
    python3 scripts/cs2_nov13_research.py --held    # one held-out pass at those picks -> data/cs2_nov13_research.json

Needs scripts/data/cs2_rounds (scripts/cs2_rounds.py --full), Valve's standings clone (scripts/.cache/cs/vrs) and
scikit-learn (the stack test only). Base = the live four-term series model (player Elo, VRS points, team map rating,
the five's player rating), weights by tier fit on Aug 2024 - Jun 2025, held Jul 2025 - Nov 10 2026 (Nov 11 on is the
2026-27 lockbox and is never read).
"""
import gzip
import html
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_model as CM  # noqa: E402
import cs2_players as P  # noqa: E402
import cs2_rounds  # noqa: E402
import names  # noqa: E402
from cs2_data import VRS, key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_nov13_research.json"
TUNEF = ROOT / "data" / "cs2_nov13_tune.json"
END = "2026-11-10"
ADJ = [{"mode": "side"}, {"mode": "econ"}, {"mode": "side", "wp": 1, "wm": .5}, {"mode": "side", "wp": 1, "wm": .25},
       {"mode": "side", "wp": .5, "wm": .5}, {"mode": "side", "wp": .5, "wm": 1}, {"mode": "side", "wp": 2, "wm": 1}]
FACT = ("Bounty Offered", "Bounty Collected", "Opponent Network", "LAN Wins")


def vrs_factors():
    """snapshot date -> {team key: [bounty offered, bounty collected, opponent network, LAN wins, H2H adj / 400]}"""
    out = {}
    for ydir in sorted((VRS / "live").iterdir()):
        det = ydir / "details"
        if not det.is_dir():
            continue
        for sdir in sorted(det.iterdir()):
            tab = {}
            for f in sdir.iterdir():
                txt = f.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"Team Name:\s*(.+?)<br", txt)
                if not m:
                    continue
                v = [re.search(nm + r":\s*([\d.]+)", txt) for nm in FACT]
                h = re.search(r"Head To Head Adjustments \((-?[\d.]+)\)", txt)
                if all(v) and h:
                    tab.setdefault(key(html.unescape(m.group(1).strip())),
                                   [float(q.group(1)) for q in v] + [float(h.group(1)) / 400])
            out[sdir.name.replace("_", "-")] = tab
    return out


class Lab:
    def __init__(self):
        H = json.load(gzip.open(CM.HIST))
        self.series = [r for r in H["series"] if r[6] == "vrs" and r[0] <= END]
        self.vrs = CM.Vrs(H["vrs"])
        self.p = json.loads(CM.FIT.read_text())["params"]
        self.bo3d = cs2_bo3.load()
        self.rd = cs2_rounds.load()
        self.fj = json.loads(P.FIT.read_text())
        self.M = P.Maps(self.bo3d)
        self.c = P.contributions(self.M, np.array([self.fj["beta"][k] for k in P.STATS]), np.array(self.fj["mline"]),
                                 self.fj["params"].get("pm", 0.0))
        self.snaps = {}
        self.fac = vrs_factors()
        self.fdates = sorted(self.fac)
        self._adj = {}

    def adj(self, cfg):
        k = json.dumps(cfg, sort_keys=True)
        if k not in self._adj:
            self._adj[k] = cs2_rounds.adjusted(self.bo3d, cfg, self.rd)
        return self._adj[k]

    def theta(self, mo, c=None, pp=None, tag=""):
        if (mo, tag) not in self.snaps:
            self.snaps[(mo, tag)] = P.ratings(self.M, self.c if c is None else c, P.ordd(mo + "-01"),
                                              pp or self.fj["params"])[0]
        return self.snaps[(mo, tag)]

    def rows(self, p=None, adj=None, elo=True, tm=None, rwa=None, valid=False):
        """Replay with settings p (default: live). adj: an adjusted-share config for the player Elo map updates (elo)
        and / or the team map rating (tm = its settings). rwa: (tag, contributions, params) for the player term."""
        bo3 = cs2_bo3.Bo3(self.bo3d)
        bo3.valid_only = valid
        if adj is not None:
            bo3.adj, bo3.adj_elo = self.adj(adj), elo
        p = dict(p or self.p)
        if tm:
            p["tm"] = tm
        rows, _ = CM.replay(self.series, self.vrs, p, bo3=bo3)
        if not hasattr(self, "nk"):
            self.nk, self.nkt = P.nick_index(self.M, bo3)
        for r in rows:
            th = self.theta(r["d"][:7], *(rwa[1:] if rwa else (None, None)), tag=rwa[0] if rwa else "")

            def mean(ros, k):
                ix = [self.nkt.get((names.key(q), k), self.nk.get(names.key(q))) for q in ros or []]
                v = [th[i] for i in ix if i is not None]
                return np.mean(v) if len(v) >= 3 else None
            a, b = mean(r["r"][4], r["a"]), mean(r["r"][5], r["b"])
            r["z"] = (a - b) / 10 if a is not None and b is not None else 0.0
            i = np.searchsorted(self.fdates, r["d"]) - 1
            tab = self.fac[self.fdates[i]] if i >= 0 else {}
            fa, fb = tab.get(r["a"], [0] * 5), tab.get(r["b"], [0] * 5)
            r["f"] = [x - y for x, y in zip(fa, fb)]
            del r["r"]
        return rows


BASE = lambda r: [r["x"], r["v"], r["t"], r["z"]]  # noqa: E731
tune = lambda rows: [r for r in rows if CM.TUNE[0] <= r["d"] <= CM.TUNE[1]]  # noqa: E731
held = lambda rows: [r for r in rows if r["d"] >= CM.HELD[0]]  # noqa: E731


def tiered(train, test, f=BASE):
    """-> (logits on test, weights) with the logistic fit by tier on train."""
    L, ws = np.zeros(len(test)), {}
    for tier in (True, False):
        tr = [r for r in train if r["top"] == tier]
        w = CM.fitlog(np.array([f(r) for r in tr]), np.array([r["s"] for r in tr]))
        ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
        idx = [i for i, r in enumerate(test) if r["top"] == tier]
        if idx:
            L[idx] = np.array([f(test[i]) for i in idx]) @ w
    return L, ws


def loss(L, rows):
    return CM.ll(1 / (1 + np.exp(-L)), np.array([r["s"] for r in rows]))


def tt(dl, rows):
    """Paired log-loss difference: mean, series t, and the t over months (Student t p, one-sided for 'better')."""
    from scipy import stats
    mo = np.array([r["d"][:7] for r in rows])
    ms = sorted(set(mo))
    a = np.array([dl[mo == m].mean() for m in ms])
    tm = float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a)))
    top = np.array([r["top"] for r in rows])
    return {"d": round(float(dl.mean()), 5), "t": round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2),
            "tMonth": round(tm, 2), "p": float(stats.t.cdf(tm, len(a) - 1)), "months": [int((a < 0).sum()), len(a)],
            "top50": round(float(dl[top].mean()), 5), "nTop": int(top.sum()), "n": len(dl)}


def second(rows, L, cols):
    """Second-stage design: the base logit and its products with extra columns (one coefficient each, both tiers)."""
    return np.column_stack([L] + [L * np.array([c(r) for r in rows]) for c in cols])


def stack_fit(tr, Ltr):
    """Boosted trees on the base terms and context (fixed settings, mirrored rows so the team order cannot matter)."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = stack_X(tr, Ltr)
    y = np.array([r["s"] for r in tr])
    g = HistGradientBoostingClassifier(max_depth=3, learning_rate=.05, max_iter=150, min_samples_leaf=200,
                                       l2_regularization=1.0, random_state=0)
    g.fit(np.vstack([X, mirror(X)]), np.concatenate([y, 1 - y]))
    return g


def stack_X(rows, L):
    return np.column_stack([L, [r["x"] for r in rows], [r["v"] for r in rows], [r["t"] for r in rows],
                            [r["z"] for r in rows], [r["top"] for r in rows], [r["bo"] for r in rows],
                            [r["u"] for r in rows], [r["t"] != 0 for r in rows]]).astype(float)


def mirror(X):
    Xm = X.copy()
    Xm[:, :5] *= -1
    return Xm


def stack_logit(g, rows, L):
    X = stack_X(rows, L)
    q = (g.predict_proba(X)[:, 1] + 1 - g.predict_proba(mirror(X))[:, 1]) / 2
    q = np.clip(q, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


def sc(kw):
    t_ = tune(LAB.rows(**kw))
    return float(loss(tiered(t_, t_)[0], t_).mean())


def tune_phase():
    lab = Lab()
    base = lab.rows()
    tr = tune(base)
    L0, w0 = tiered(tr, tr)
    l0 = loss(L0, tr).mean()
    out = {"base": {"ll": round(float(l0), 5), "w": w0, "n": len(tr)}}
    print("base tune", l0, len(tr), "rounds for", len(lab.rd), "maps", flush=True)

    global LAB
    LAB = lab
    for cfg in ADJ:
        lab.adj(cfg)
    import multiprocessing as mp
    pool = mp.get_context("fork").Pool(4)
    for nm, kw in (("A_elo", lambda cfg, sp: dict(p=dict(lab.p, span=sp), adj=cfg, elo=True)),
                   ("A_tm", lambda cfg, sp: dict(adj=cfg, elo=False, tm=dict(cs2_bo3.TM, adj=True, span=sp)))):
        jobs = [(cfg, sp) for cfg in ADJ for sp in ((.4, .3) if nm == "A_elo" else (.3, .225))]
        grid = [(v, cfg, sp) for v, (cfg, sp) in zip(pool.map(sc, [kw(*j) for j in jobs]), jobs)]
        grid.sort(key=lambda g: g[0])
        print(nm, grid, flush=True)
        out[nm] = {"pick": {"cfg": grid[0][1], "span": grid[0][2]}, "ll": round(grid[0][0], 5),
                   "grid": [[round(g[0], 5), g[1], g[2]] for g in grid]}
    for nm, k, vals in (("C_tprior", "tprior", (.25, .5, .75, 1.0)), ("D_ktier", "ktier", (.75, 1.25, 1.5, 2.0))):
        grid = sorted(zip(pool.map(sc, [dict(p=dict(lab.p, **{k: v})) for v in vals]), vals))
        print(nm, grid, flush=True)
        out[nm] = {"pick": grid[0][1], "ll": round(grid[0][0], 5), "grid": [[round(a, 5), b] for a, b in grid]}
    out["G_valid"] = {"ll": round(sc(dict(valid=True)), 5)}
    pool.close()
    # player rating (RWA): walk-forward round-share MSE on the tune months not used for the scale
    M, fp = lab.M, lab.fj["params"]
    last = P.dt.date.fromordinal(int(M.gd.max()))
    tmo = P.months(*P.TUNE, last)

    def rsc(c, pp):
        pp = dict(pp)
        pp["a"] = P.fit_scale(M, c, pp, tmo[::2])
        return P.predict_score(M, c, pp, tmo[1::2])[0]
    out["rwa_base"] = rsc(lab.c, fp)
    grid = sorted((rsc(lab.c, dict(fp, tp=v)), v) for v in (.25, .5, .75, 1.0))
    print("P1_tp", out["rwa_base"], grid, flush=True)
    out["P1_tp"] = {"pick": grid[0][1], "mse": grid[0][0], "grid": grid}
    grid = []
    beta, ml = np.array([lab.fj["beta"][k] for k in P.STATS]), np.array(lab.fj["mline"])
    for cfg in ADJ:
        grid.append((rsc(P.contributions(M, beta, ml, fp.get("pm", 0.0), y=yadj(lab, cfg)), fp), cfg))
    grid.sort(key=lambda g: g[0])
    print("P2_adj", grid, flush=True)
    out["P2_adj"] = {"pick": grid[0][1], "mse": grid[0][0], "grid": grid}
    TUNEF.write_text(json.dumps(out, indent=1))


def yadj(lab, cfg):
    """Each player-map row's own-team adjusted round share (plain share where the map has no rounds)."""
    M, a = lab.M, lab.adj(cfg)
    y = M.y.copy()
    for gi, g in enumerate(M.games):
        v = a.get(g[0])
        if v is not None:
            y[M.five[gi, 0]] = v
            y[M.five[gi, 1]] = 1 - v
    return y


def held_phase():
    from scipy import stats
    T = json.loads(TUNEF.read_text())
    lab = Lab()
    base = lab.rows()
    tr, he = tune(base), held(base)
    L0, w0 = tiered(tr, he)
    Ltr, _ = tiered(tr, tr)
    l0 = loss(L0, he)
    res = {}

    def variant(nm, rows, f=BASE):
        t_, h_ = tune(rows), held(rows)
        L, w = tiered(t_, h_, f)
        res[nm] = dict(tt(loss(L, h_) - l0, he), w=w)
    a = T["A_elo"]["pick"]
    variant("A_elo", lab.rows(p=dict(lab.p, span=a["span"]), adj=a["cfg"], elo=True))
    a2 = T["A_tm"]["pick"]
    variant("A_tm", lab.rows(adj=a2["cfg"], elo=False, tm=dict(cs2_bo3.TM, adj=True, span=a2["span"])))
    variant("B_vrs_factors", base, lambda r: BASE(r) + r["f"])
    variant("G_valid", lab.rows(valid=True))
    gv = res.pop("G_valid")
    variant("C_tprior", lab.rows(p=dict(lab.p, tprior=T["C_tprior"]["pick"])))
    variant("D_ktier", lab.rows(p=dict(lab.p, ktier=T["D_ktier"]["pick"])))
    for nm, cols in (("E_format", [lambda r: r["bo"] == 1, lambda r: r["bo"] == 5]), ("F_experience", [lambda r: r["u"]])):
        w = CM.fitlog(second(tr, Ltr, cols), np.array([r["s"] for r in tr]))
        res[nm] = dict(tt(loss(second(he, L0, cols) @ w, he) - l0, he), w=[round(float(z), 4) for z in w])
    g = stack_fit(tr, Ltr)
    res["S_stack"] = tt(loss(stack_logit(g, he, L0), he) - l0, he)
    holm(res, stats)
    for nm in ("A_elo", "A_tm", "C_tprior", "D_ktier"):
        res[nm]["tuneBetter"] = T[nm]["ll"] < T["base"]["ll"]
        res[nm]["pass"] = bool(res[nm]["pass"] and res[nm]["tuneBetter"])
    out = {"held": [CM.HELD[0], END], "n": len(he), "base": {"ll": round(float(l0.mean()), 5), "w": w0,
           "top50": round(float(l0[[r["top"] for r in he]].mean()), 5)}, "series": res,
           "fix": {"G_valid": dict(gv, tuneLl=T["G_valid"]["ll"], ship=bool(gv["d"] <= 0 or gv["tMonth"] < 1))}}
    # player rating: held months, per-map squared error against the shipped rating; then its series check
    M, fp = lab.M, lab.fj["params"]
    last = P.dt.date.fromordinal(int(M.gd.max()))
    tmo = P.months(*P.TUNE, last)
    hmo = [m for m in P.months(*P.HELD, last) if m <= END[:7]]
    beta, ml = np.array([lab.fj["beta"][k] for k in P.STATS]), np.array(lab.fj["mline"])
    e0 = P.map_sq(M, lab.c, fp, hmo)
    gm = np.concatenate([np.full(int(((M.gd >= P.ordd(m + "-01")) & (M.gd < P.ordd(nxt(m)))).sum()), i)
                         for i, m in enumerate(hmo)])
    pr = {}
    for nm, c, pp in (("P1_tp", lab.c, dict(fp, tp=T["P1_tp"]["pick"])),
                      ("P2_adj", P.contributions(M, beta, ml, fp.get("pm", 0.0), y=yadj(lab, T["P2_adj"]["pick"])), fp)):
        pp = dict(pp)
        pp["a"] = P.fit_scale(M, c, pp, tmo[::2])
        dl = P.map_sq(M, c, pp, hmo) - e0
        a = np.array([dl[gm == i].mean() for i in range(len(hmo))])
        tm = float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a)))
        rows = lab.rows(rwa=(nm, c, pp))
        L, w = tiered(tune(rows), held(rows))
        pr[nm] = {"d": float(dl.mean()), "tMonth": round(tm, 2), "p": float(stats.t.cdf(tm, len(a) - 1)),
                  "months": [int((a < 0).sum()), len(a)], "tuneBetter": T[nm]["mse"] < T["rwa_base"],
                  "series": tt(loss(L, he) - l0, he), "a": pp["a"]}
    holm(pr, stats, top=False)
    for nm in pr:
        pr[nm]["pass"] = bool(pr[nm]["pass"] and pr[nm]["tuneBetter"] and pr[nm]["series"]["d"] <= 0)
    out["players"] = pr
    out["market"] = market_phase()
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


def market_phase():
    """M_tp: does Thunderpick's opening price add to the model's chance on the forward archive?"""
    win = {m[0]: m[6] for m in cs2_bo3.load()["matches"]}
    R = []
    for mid, (o, c) in cs2_bo3.closes().items():
        if o.get("m") is None or win.get(mid) is None or o["start"][:10] > END:
            continue
        R.append((o["start"][:10], CM.cs2_bo3.logit(o["m"]), cs2_bo3.logit(o["p"]), cs2_bo3.logit(c["p"]),
                  float(win[mid] == o["t1"])))
    days = sorted({r[0] for r in R})
    A = np.array([r[1:] for r in R])
    dd = np.array([r[0] for r in R])
    out = {"n": len(R), "days": len(days)}
    lm = CM.ll(1 / (1 + np.exp(-A[:, 0])), A[:, 3])
    for nm, j in (("open", 1), ("close", 2)):
        L = np.zeros(len(R))
        for d in days:
            te = dd == d
            w = CM.fitlog(A[~te][:, [0, j]], A[~te, 3], l2=1e-2)
            L[te] = A[te][:, [0, j]] @ w
        dl = CM.ll(1 / (1 + np.exp(-L)), A[:, 3]) - lm
        a = np.array([dl[dd == d].sum() for d in days]) / len(R) * len(days)
        w = CM.fitlog(A[:, [0, j]], A[:, 3], l2=1e-2)
        out[nm] = {"llModel": round(float(lm.mean()), 4), "llPrice": round(float(CM.ll(1 / (1 + np.exp(-A[:, j])), A[:, 3]).mean()), 4),
                   "llBlend": round(float((lm + dl).mean()), 4), "d": round(float(dl.mean()), 4),
                   "tDay": round(float(a.mean() / (a.std(ddof=1) + 1e-12) * math.sqrt(len(a))), 2),
                   "w": [round(float(z), 3) for z in w]}
    out["pass"] = bool(out["open"]["d"] < 0 and out["open"]["tDay"] <= -2)
    return out


def nxt(mo):
    return (P.dt.date.fromisoformat(mo + "-01") + P.dt.timedelta(days=32)).replace(day=1).isoformat()


def holm(res, stats, top=True):
    """Holm over the family on the held by-month p (one-sided .025); a pass also needs the top 50 no worse."""
    order = sorted(res, key=lambda k: res[k]["p"])
    going = True
    for i, nm in enumerate(order):
        cut = .025 / (len(order) - i)
        going = going and res[nm]["p"] < cut
        res[nm]["holmP"] = cut
        res[nm]["pass"] = bool(going and (not top or res[nm]["top50"] <= 0))


if __name__ == "__main__":
    held_phase() if "--held" in sys.argv else tune_phase()
