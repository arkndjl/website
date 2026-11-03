#!/usr/bin/env python3
"""Counter-Strike research, Nov 3 2026: rating metric, prospect FV drivers + badges, series-model terms.

    python3 scripts/cs2_nov03_research.py [rating|prospects|game ...]   -> data/cs2_nov03_research.json

Every test is out of sample: tuned or fit on maps/series before Jul 2025 (scripts/cs2_players.py TUNE), scored on
Jul 2025 on (HELD), paired t on the per-row loss difference. All tests across the three parts are counted together
and judged against a Bonferroni cut (|t| > z(.025 / n)); a term ships only if it clears that cut held out.

rating (target: the round share of later maps, walk forward, monthly cutoffs, per-map squared error):
  grid      half-life / shrink grid extended below the shipped h 180, k 50 (both were at the grid's edge)
  hs        headshot rate added to the stat lines
  pm        team residual (round share the five's box lines miss) shared equally, x lam (box + plus-minus)
  mates     teammates' mean rating subtracted, x m (stats inflated on strong teams)
  tierw     maps at higher-tier events weighted up, weight f^(tier-1)
prospects (target: rating over the next 12 months, prospects = under 20 S-tier maps, quarterly cutoffs):
  each stat line over the last year (per round), mean event tier, teammates' rating, log rounds, and each badge
  (top 25% of the active pool on its stat) added one at a time to the shipped rating + age model.
game (target: series result; the live model = player Elo + VRS + team map term + the five's mean rating):
  daily     the five's rating as of the series day instead of the first of the month
  star      best player minus the five's mean, A minus B
  rest      days since each team's last series (capped 14), A minus B; back-to-back flag
"""
import datetime as dt
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_players as P  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_nov03_research.json"
RES = json.loads(OUT.read_text()) if OUT.exists() else {}


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std() + 1e-12) * math.sqrt(len(d))), 2)


def mon_bounds(mo):
    T = P.ordd(mo + "-01")
    T2 = P.ordd((dt.date.fromordinal(T) + dt.timedelta(days=32)).replace(day=1).isoformat())
    return T, T2


def ratings_x(M, c, T, p, w_row=None, mates=0.0):
    """cs2_players.ratings with optional row weights and a teammate term."""
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) * math.log(2) / p["h"]) * m
    if w_row is not None:
        w = w * w_row
    n = len(M.pids)
    theta = np.zeros(n)
    wsum = np.bincount(M.p, w, n)
    for _ in range(6):
        th_row = theta[M.p]
        opp = th_row[M.five[M.g, 1 - M.side]].mean(1)
        adj = c + p["opp"] * opp
        if mates:
            own = th_row[M.five[M.g, M.side]].sum(1)
            adj = adj - mates * (own - th_row) / 4
        theta = np.bincount(M.p, w * adj, n) / (wsum + p["k"])
    return theta


def map_err(M, c, p, mos, **kw):
    """Per-map squared error of .5 + a (sum A - sum B) / 200 over the months (a fit on the same rows' tune twin)."""
    xs, ys = [], []
    for mo in mos:
        T, T2 = mon_bounds(mo)
        th = ratings_x(M, c, T, p, **kw)
        gi = np.where((M.gd >= T) & (M.gd < T2))[0]
        xs.append((th[M.p[M.five[gi, 0]]].sum(1) - th[M.p[M.five[gi, 1]]].sum(1)) / 200)
        ys.append(M.y[M.five[gi, 0, 0]] - 0.5)
    return np.concatenate(xs), np.concatenate(ys)


def score(M, c, p, tm, hm, **kw):
    x, y = map_err(M, c, p, tm[::2], **kw)
    a = float((x * y).sum() / (x * x).sum())
    xh, yh = map_err(M, c, p, hm, **kw)
    return a, (yh - a * xh) ** 2, yh ** 2


def rating(M):
    last = dt.date.fromordinal(int(M.gd.max()))
    fj = json.loads(P.FIT.read_text())
    base_p = fj["params"]
    tune_g = M.gd < P.ordd(P.TUNE[1])
    beta, ml, _ = P.stat_weights(M, tune_g)
    c = P.contributions(M, beta, ml)
    tm, hm = P.months(*P.TUNE, last), P.months(*P.HELD, last)
    out = {}
    _, e0, flat = score(M, c, base_p, tm, hm)
    out["shipped"] = {"params": base_p, "r2": round(1 - e0.mean() / flat.mean(), 4), "n": len(e0)}
    print("shipped", out["shipped"], file=sys.stderr)

    def cmp(nm, e, extra=None):
        d = e - e0
        r = {"r2": round(1 - e.mean() / flat.mean(), 4), "dr2": round(float((e0.mean() - e.mean()) / flat.mean()), 4),
             "t": tstat(d)}
        r.update(extra or {})
        out[nm] = r
        print(nm, r, file=sys.stderr)
    # grid: tuned on the tune months (odd months scored), best then held
    grid = []
    for h in (60, 90, 120, 180):
        for k in (10, 25, 50):
            p = dict(base_p, h=h, k=k)
            x, y = map_err(M, c, p, tm[::2])
            p["a"] = float((x * y).sum() / (x * x).sum())
            xt, yt = map_err(M, c, p, tm[1::2])
            grid.append((float(((yt - p["a"] * xt) ** 2).mean()), h, k))
    grid.sort()
    _, h, k = grid[0]
    _, e, _ = score(M, c, dict(base_p, h=h, k=k), tm, hm)
    cmp("grid", e, {"h": h, "k": k, "tuneTop": grid[:4]})
    # hs: headshots per round added to the stat lines
    rows_hs = hs_col(M)
    X0 = M.X
    M.X = np.column_stack([X0, rows_hs])
    b2, m2, _ = P.stat_weights(M, tune_g)
    c2 = P.contributions(M, b2, m2)
    M.X = X0
    _, e, _ = score(M, c2, base_p, tm, hm)
    cmp("hs", e, {"beta_hs": round(float(b2[-1]), 4)})
    # pm: box + share of the team residual
    tot = np.zeros((len(M.games), 2))
    np.add.at(tot, (M.g, M.side), c)
    resid = 100 * (M.y - 0.5) - tot[M.g, M.side]
    best = None
    for lam in (0.25, 0.5, 1.0):
        x, y = map_err(M, c + lam * resid / 5, base_p, tm[1::2])
        a = float((x * y).sum() / (x * x).sum())
        e_ = float(((y - a * x) ** 2).mean())
        if best is None or e_ < best[0]:
            best = (e_, lam)
    _, e, _ = score(M, c + best[1] * resid / 5, base_p, tm, hm)
    cmp("pm", e, {"lam": best[1]})
    # mates
    best = None
    for mt in (0.25, 0.5):
        x, y = map_err(M, c, base_p, tm[1::2], mates=mt)
        a = float((x * y).sum() / (x * x).sum())
        e_ = float(((y - a * x) ** 2).mean())
        if best is None or e_ < best[0]:
            best = (e_, mt)
    _, e, _ = score(M, c, base_p, tm, hm, mates=best[1])
    cmp("mates", e, {"m": best[1]})
    # tier weights
    best = None
    for f in (0.7, 0.85):
        wr = f ** (M.tier - 1.0)
        x, y = map_err(M, c, base_p, tm[1::2], w_row=wr)
        a = float((x * y).sum() / (x * x).sum())
        e_ = float(((y - a * x) ** 2).mean())
        if best is None or e_ < best[0]:
            best = (e_, f)
    _, e, _ = score(M, c, base_p, tm, hm, w_row=best[1] ** (M.tier - 1.0))
    cmp("tierw", e, {"f": best[1]})
    RES["rating"] = out


def hs_col(M):
    """Headshots per round for every player-map row of M (same order as M.X)."""
    hs = {}
    for f in sorted(P.PS.DIR.glob("*.json.gz")):
        with gzip.open(f, "rt") as fh:
            for r in json.load(fh)["rows"]:
                hs[(r[0], r[1])] = r[6]
    gids = np.array([g[0] for g in M.games])[M.g]
    return np.array([hs.get((int(g), int(p)), 0) for g, p in zip(gids, M.p_raw)], float) / M.R


BADGES = [  # name, column, sign (+ = high is good)
    ("Entry", "fk", 1), ("Opener", "okd", 1), ("Clutch", "cl", 1), ("Trader", "tk", 1), ("Support", "a", 1),
    ("Survivor", "d", -1), ("Multi-Kill", "mk", 1), ("Damage", "adr", 1), ("Consistent", "kast", 1),
    ("Headshot", "hsk", 1), ("Big Stage", "s_share", 1)]


def lines(M, T, extra):
    """Per-round stat lines over [T-365, T) for every player, plus derived columns."""
    n = len(M.pids)
    w = M.R * ((M.d >= T - 365) & (M.d < T))
    r = np.bincount(M.p, w, n)
    out = {k: np.bincount(M.p, w * M.X[:, j], n) / np.maximum(r, 1) for j, k in enumerate(P.STATS)}
    out["hs"] = np.bincount(M.p, w * extra["hs"], n) / np.maximum(r, 1)
    out["hsk"] = out["hs"] / np.maximum(out["k"], 1e-6)
    out["okd"] = out["fk"] - out["fd"]
    out["s_share"] = np.bincount(M.p, w * (M.tier <= 2), n) / np.maximum(r, 1)
    out["tier"] = np.bincount(M.p, w * M.tier, n) / np.maximum(r, 1)
    out["r"] = r
    return out


def prospects(M):
    fj = json.loads(P.FIT.read_text())
    p = fj["params"]
    c = P.contributions(M, np.array([fj["beta"][k] for k in P.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    pdir = P.load_pdir()
    extra = {"hs": hs_col(M)}
    last = int(M.gd.max())
    cuts, d = [], dt.date(2024, 10, 1)
    while d.toordinal() + 365 <= last:
        cuts.append(d.toordinal())
        d = (d + dt.timedelta(days=92)).replace(day=1)
    data = []
    for T in cuts:
        pr = P.prospect_rows(M, c, p, T, pdir)
        thF = P.ratings(M, c, T + 365, p)[0]
        fut, rf = P.window_stats(M, c, thF, T, T + 365, p)
        i = pr["i"][rf[pr["i"]] >= 600]
        L = lines(M, T, extra)
        th = pr["th"]
        # teammates: mean rating of the four others on his last-year maps
        m = (M.d >= T - 365) & (M.d < T)
        own = th[M.p][M.five[M.g, M.side]].sum(1)
        mt = np.bincount(M.p, M.R * m * (own - th[M.p]) / 4, len(M.pids)) / np.maximum(L["r"], 1)
        # badge pool: every player with 1000+ rounds in the year before T
        pool = L["r"] >= 1000
        row = {"T": T, "y": fut[i], "w": np.minimum(rf[i], 3000), "th": th[i],
               "age": np.nan_to_num(pr["age"][i] - 22), "mates": mt[i], "logr": np.log(L["r"][i])}
        for k in P.STATS + ["hsk", "okd", "s_share", "tier"]:
            v = L[k]
            mu, sd = v[pool].mean(), v[pool].std() + 1e-9
            row["z_" + k] = (v[i] - mu) / sd
        for nm, k, sg in BADGES:
            cut = np.quantile(sg * L[k][pool], 0.75)
            row["b_" + nm] = (sg * L[k][i] >= cut).astype(float)
        data.append(row)
    tune = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() < P.HELD[0]]
    held = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() >= P.HELD[0]]

    def stack(xs, cols):
        X = np.concatenate([np.column_stack([np.ones(len(x["y"]))] + [x[k] for k in cols]) for x in xs])
        return X, np.concatenate([x["y"] for x in xs]), np.concatenate([x["w"] for x in xs])

    def run(cols):
        X, y, w = stack(tune, cols)
        b = P.ols(X, y, w)
        Xh, yh, wh = stack(held, cols)
        e = yh - Xh @ b
        return b, e, wh
    base_cols = ["th", "age"]
    _, e0, wh = run(base_cols)
    out = {"base": {"cols": base_cols, "mse": round(float((wh * e0 ** 2).sum() / wh.sum()), 4), "n": int(len(e0)),
                    "nTune": int(sum(len(x["y"]) for x in tune))}}
    keys = ["z_" + k for k in P.STATS + ["hsk", "okd", "s_share", "tier"]] + ["mates", "logr"] + \
        ["b_" + b[0] for b in BADGES]
    for k in keys:
        b, e, _ = run(base_cols + [k])
        dlt = wh * (e ** 2 - e0 ** 2)
        out[k] = {"coef": round(float(b[-1]), 4), "dmse": round(float(dlt.sum() / wh.sum()), 4), "t": tstat(dlt),
                  "tuneN": out["base"]["nTune"]}
        print(k, out[k], file=sys.stderr)
    # joint: forward selection on the tune cutoffs (leave-one-cutoff-out), scored once held out
    sel, cur = [], None

    def cv(cols):
        tot = 0.0
        for j in range(len(tune)):
            tr = [x for q, x in enumerate(tune) if q != j]
            X, y, w = stack(tr, cols)
            b = P.ols(X, y, w)
            Xv, yv, wv = stack([tune[j]], cols)
            tot += float((wv * (yv - Xv @ b) ** 2).sum())
        return tot
    cur = cv(base_cols)
    pool_k = list(keys)
    while pool_k:
        sc = sorted((cv(base_cols + sel + [k]), k) for k in pool_k)
        if sc[0][0] >= cur * 0.999:
            break
        cur = sc[0][0]
        sel.append(sc[0][1])
        pool_k.remove(sc[0][1])
    b, e, _ = run(base_cols + sel)
    dlt = wh * (e ** 2 - e0 ** 2)
    out["joint"] = {"cols": sel, "b": [round(float(v), 4) for v in b], "dmse": round(float(dlt.sum() / wh.sum()), 4),
                    "t": tstat(dlt)}
    print("joint", out["joint"], file=sys.stderr)
    RES["prospects"] = out


def badges(M):
    """Badges on the main board: every player with 1000+ rounds in the year before a quarterly cutoff (and 1000+ in
    the year after); next year's rating from rating + age, plus one badge (top 25% of the pool) at a time."""
    fj = json.loads(P.FIT.read_text())
    p = fj["params"]
    c = P.contributions(M, np.array([fj["beta"][k] for k in P.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    pdir = P.load_pdir()
    extra = {"hs": hs_col(M)}
    last = int(M.gd.max())
    data, d = [], dt.date(2024, 7, 1)
    while d.toordinal() + 365 <= last:
        T = d.toordinal()
        th = P.ratings(M, c, T, p)[0]
        thF = P.ratings(M, c, T + 365, p)[0]
        fut, rf = P.window_stats(M, c, thF, T, T + 365, p)
        L = lines(M, T, extra)
        ag = P.ages(M, pdir, T)
        pool = L["r"] >= 1000
        i = np.where(pool & (rf >= 1000))[0]
        row = {"T": T, "y": fut[i], "w": np.minimum(rf[i], 3000), "th": th[i], "age": np.nan_to_num(ag[i] - 24)}
        for nm, k, sg in BADGES:
            cut = np.quantile(sg * L[k][pool], 0.75)
            row["b_" + nm] = (sg * L[k][i] >= cut).astype(float)
        data.append(row)
        d = (d + dt.timedelta(days=92)).replace(day=1)
    tune = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() < P.HELD[0]]
    held = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() >= P.HELD[0]]

    def stack(xs, cols):
        X = np.concatenate([np.column_stack([np.ones(len(x["y"]))] + [x[k] for k in cols]) for x in xs])
        return X, np.concatenate([x["y"] for x in xs]), np.concatenate([x["w"] for x in xs])

    def run(cols):
        X, y, w = stack(tune, cols)
        b = P.ols(X, y, w)
        Xh, yh, wh = stack(held, cols)
        return b, yh - Xh @ b, wh
    _, e0, wh = run(["th", "age"])
    out = {"base": {"n": int(len(e0)), "nTune": int(sum(len(x["y"]) for x in tune))}}
    for nm, _, _ in BADGES:
        b, e, _ = run(["th", "age", "b_" + nm])
        dlt = wh * (e ** 2 - e0 ** 2)
        out["b_" + nm] = {"coef": round(float(b[-1]), 4), "dmse": round(float(dlt.sum() / wh.sum()), 4),
                          "t": tstat(dlt)}
        print(nm, out["b_" + nm], file=sys.stderr)
    RES["badges"] = out


def game(M):
    import cs2_model as CM
    fj = json.loads(P.FIT.read_text())
    p = fj["params"]
    c = P.contributions(M, np.array([fj["beta"][k] for k in P.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = CM.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, vrs, json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    nk, nkt = P.nick_index(M, bo3)
    rows = [r for r in rows if r["d"] >= "2024-07-01"]
    snaps = {}

    def th_at(T):
        if T not in snaps:
            snaps[T] = P.ratings(M, c, T, p)[0]
        return snaps[T]

    def five(ros, k, th):
        v = [th[ix] for q in ros or [] if (ix := nkt.get((names.key(q), k), nk.get(names.key(q)))) is not None]
        return v if len(v) >= 3 else None
    lastd = {}
    for r in rows:
        Tm = P.ordd(r["d"][:7] + "-01")
        Td = P.ordd(r["d"])
        for nm, T in (("m", Tm), ("d", Td)):
            th = th_at(T)
            a, b = five(r["r"][4], r["a"], th), five(r["r"][5], r["b"], th)
            ok = a is not None and b is not None
            r["z" + nm] = (np.mean(a) - np.mean(b)) / 10 if ok else 0.0
            if nm == "d":
                r["star"] = ((max(a) - np.mean(a)) - (max(b) - np.mean(b))) / 10 if ok else 0.0
        da = min(14, Td - lastd.get(r["a"], Td - 14))
        db = min(14, Td - lastd.get(r["b"], Td - 14))
        r["rest"] = (da - db) / 7
        r["b2b"] = float(da <= 1) - float(db <= 1)
        lastd[r["a"]] = lastd[r["b"]] = Td
    print("snaps", len(snaps), file=sys.stderr)
    tr = [r for r in rows if r["d"] <= CM.TUNE[1]]
    he = [r for r in rows if r["d"] >= CM.HELD[0]]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])

    def run(f):
        q = np.zeros(len(he))
        ws = {}
        for tier in (True, False):
            t_ = [r for r in tr if r["top"] == tier]
            idx = [i for i, r in enumerate(he) if r["top"] == tier]
            w = CM.fitlog(np.array([f(r) for r in t_]), np.array([r["s"] for r in t_]))
            ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
            q[idx] = 1 / (1 + np.exp(-np.array([f(he[i]) for i in idx]) @ w))
        return CM.ll(q, s), ws
    base = lambda r: [r["x"], r["v"], r["t"], r["zm"]]  # noqa: E731
    l0, _ = run(base)
    out = {"shipped": {"n": len(he), "ll": round(float(l0.mean()), 4), "top50": round(float(l0[top].mean()), 4)}}
    tests = {"daily": lambda r: [r["x"], r["v"], r["t"], r["zd"]],
             "star": lambda r: [r["x"], r["v"], r["t"], r["zd"], r["star"]],
             "rest": lambda r: [r["x"], r["v"], r["t"], r["zd"], r["rest"], r["b2b"]]}
    ref = {"daily": l0}
    for nm, f in tests.items():
        l1, ws = run(f)
        r0 = ref.get(nm, ref.get("dailyLL", l0))
        out[nm] = {"ll": round(float(l1.mean()), 4), "d": round(float((l1 - r0).mean()), 5), "t": tstat(l1 - r0),
                   "top50": {"ll": round(float(l1[top].mean()), 4), "t": tstat((l1 - r0)[top])}, "w": ws}
        if nm == "daily":
            ref["dailyLL"] = l1
        print(nm, out[nm], file=sys.stderr)
    RES["game"] = out


LABEL = {"k": "kills", "d": "deaths", "a": "assists", "adr": "damage", "kast": "KAST", "fk": "opening kills",
         "fd": "opening deaths", "tk": "trade kills", "td": "traded deaths", "mk": "multi-kill rounds",
         "cl": "clutches", "hsk": "headshot %", "okd": "opening kills - deaths", "s_share": "S/A-tier share",
         "tier": "mean event tier", "mates": "teammates' rating", "logr": "rounds played", "joint": "forward-selected set",
         "grid": "half-life / shrink grid", "hs": "headshots", "pm": "plus-minus", "tierw": "event-tier weights",
         "daily": "rating as of the series day", "star": "best player - mean", "rest": "days of rest", "all three": "utility $ + damage taken + accuracy"}


def label(k):
    part, _, nm = k.partition(" ")
    if nm.startswith("badge "):
        nm = nm[6:]
    pre = {"rating": "rating: ", "prospects": "prospect FV: ", "board": "board: ", "game": "series model: "}.get(part)
    if pre is None:
        return k
    if nm.startswith("b_"):
        return pre + nm[2:] + " badge"
    return pre + LABEL.get(nm.removeprefix("z_"), nm.removeprefix("z_"))


def utility(M):
    """Utility and other bo3.gg fields not in the stat lines (pulled to scripts/.cache/cs2_util.json.gz): utility $
    bought per round, damage taken per round, accuracy (hits / shots). Each added to the stat lines on its own and all
    three together; shipped rating settings; held-out paired t on per-map squared error."""
    U = json.load(gzip.open(ROOT / "scripts" / ".cache" / "cs2_util.json.gz", "rt"))
    look = {}
    for g, rows in U.items():
        for r in rows:
            if r[0] is not None:
                look[(int(g), int(r[0]))] = r[1:]
    gids = np.array([g[0] for g in M.games])[M.g]
    V = np.array([look.get((int(g), int(p)), [None] * 6) for g, p in zip(gids, M.p_raw)], dtype=object)
    have = np.array([v[0] is not None for v in V])
    f = lambda j: np.array([float(v[j] or 0) for v in V])  # noqa: E731
    cols = {"utility $ per round": f(0) / 1000 / M.R, "damage taken per round": f(1) / 100 / M.R,
            "accuracy": f(2) / np.maximum(f(3), 1)}
    print("utility coverage", round(float(have.mean()), 3), file=sys.stderr)
    fj = json.loads(P.FIT.read_text())
    p = fj["params"]
    last = dt.date.fromordinal(int(M.gd.max()))
    tm, hm = P.months(*P.TUNE, last), P.months(*P.HELD, last)
    tune_g = M.gd < P.ordd(P.TUNE[1])
    X0 = M.X

    def run(extra):
        M.X = np.column_stack([X0] + extra) if extra else X0
        b, ml, _ = P.stat_weights(M, tune_g)
        c = P.contributions(M, b, ml, p["pm"])
        q = dict(p)
        q["a"] = P.fit_scale(M, c, q, tm[::2])
        e = P.map_sq(M, c, q, hm)
        M.X = X0
        return e, [round(float(x), 4) for x in b[len(P.STATS):]]
    e0, _ = run([])
    out = {"coverage": round(float(have.mean()), 3)}
    for nm, v in list(cols.items()) + [("all three", None)]:
        e, b = run(list(cols.values()) if v is None else [v])
        out[nm] = {"t": tstat(e - e0), "beta": b, "dr2": round(float((e0.mean() - e.mean()) / (e0.mean() + 1e-12)), 4)}
        print(nm, out[nm], file=sys.stderr)
    RES["utility"] = out


def bonferroni():
    tests = []
    for nm, v in (RES.get("rating") or {}).items():
        if nm != "shipped":
            tests.append(("rating " + nm, v["t"]))
    for nm, v in (RES.get("prospects") or {}).items():
        if nm != "base":
            tests.append(("prospects " + nm, v["t"]))
    for nm, v in (RES.get("badges") or {}).items():
        if nm != "base":
            tests.append(("board badge " + nm, v["t"]))
    for nm, v in (RES.get("utility") or {}).items():
        if nm != "coverage":
            tests.append(("rating " + nm, v["t"]))
    for nm, v in (RES.get("confirm") or {}).items():
        tests.append((nm, v))
    for nm, v in (RES.get("game") or {}).items():
        if nm != "shipped":
            tests.append(("game " + nm, v["t"]))
    n = len(tests)
    from statistics import NormalDist
    cut = NormalDist().inv_cdf(1 - 0.025 / max(n, 1))
    RES["multiple"] = {"n": n, "cut": round(cut, 2), "pass": [k for k, t in tests if t < -cut],
                       "tests": sorted(([label(k), t] for k, t in tests),
                                       key=lambda x: x[1])}
    print("bonferroni", RES["multiple"], file=sys.stderr)


if __name__ == "__main__":
    parts = sys.argv[1:] or ["rating", "prospects", "game"]
    M = P.Maps()
    for part in parts:
        globals()[part](M)
        cur = json.loads(OUT.read_text()) if OUT.exists() else {}
        cur[part] = RES[part]
        OUT.write_text(json.dumps(cur, indent=1, default=float))
    RES = json.loads(OUT.read_text())
    # the shipped versions, re-scored by scripts/cs2_players.py --fit (data/cs2_players_fit.json)
    fj = json.loads(P.FIT.read_text())
    RES.setdefault("confirm", {}).update({"rating: headshots + plus-minus vs Nov 2": -next(x["t"] for x in fj["score"] if x["name"].startswith("Nov 2")),
                      "prospects: S/A share on the new rating": fj["prospects"]["models"]["rating + age + S/A share"]["tTerm"],
                      "T1%: S/A share": fj["prospects"]["reach"]["tShare"]})
    bonferroni()
    OUT.write_text(json.dumps(RES, indent=1, default=float))
