#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Walk-forward retune of each sport's rating settings (Nov 23 2026; the cross-sport port of scripts/cs2_ark_loop.py).

Question: does re-picking a rating's settings before every season, on the seasons before it, beat keeping the
shipped settings? Pre-registered (Nov 23 2026, before any number was read), the same for every sport:
  - candidates: the shipped settings (each sport's fit file) and one-step moves on every setting its own tune() searches,
    to the neighbouring grid value either side (one step past the grid's end when the shipped value sits on it).
  - each candidate's chances are the sport's own walk-forward chances (blend weights fit on seasons before the game's,
    inputs as shipped), so every row is already out of sample.
  - procedure: for season y, the candidate with the lowest log loss on every scored season before y is picked; season y
    is scored once with it. Compared with the shipped settings on the sport's held-out seasons only (its tuning seasons
    picked the shipped settings in sample, which would favour them).
  - pass: mean log-loss gap < 0, t by month <= -2.0, calibration slope .7-1.3. A pass ships the pick on all
    pre-lockbox seasons to the fit file and reruns the sport's refit at those settings (2026-27 lockbox: never read).
    -> data/wf_retune.json, research/studies/cs2/wf-retune-sports.json (Process card)

    python3 scripts/wf_retune.py nhl nba ...   # one or more sports; results merge into the file
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
OUT = ROOT / "data" / "wf_retune.json"
CARD = ROOT / "research" / "studies" / "cs2" / "wf-retune-sports.json"


def neighbours(grid, cur):
    """the grid values either side of cur (one step past an end)"""
    vals = sorted(set(grid) | {cur})
    i = vals.index(cur)
    out = []
    if i > 0:
        out.append(vals[i - 1])
    elif len(vals) > 1:
        lo = vals[0] - (vals[1] - vals[0]) if vals[0] <= 0 or vals[1] / max(vals[0], 1e-9) < 1.5 else vals[0] * vals[0] / vals[1]
        out.append(round(lo, 6))
    if i < len(vals) - 1:
        out.append(vals[i + 1])
    elif len(vals) > 1:
        hi = vals[-1] + (vals[-1] - vals[-2]) if vals[-2] <= 0 or vals[-1] / max(vals[-2], 1e-9) < 1.5 else vals[-1] * vals[-1] / vals[-2]
        out.append(round(hi, 6))
    return out


def candidates(P, grid, keep=None):
    out = [("shipped", dict(P))]
    for k, g in grid.items():
        for v in neighbours(g, P[k]):
            if keep and not keep(k, v):
                continue
            out.append((f"{k} {v:g}", dict(P, **{k: v})))
    return out


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def slope(p, y):
    z = np.log(np.clip(p, 1e-6, 1 - 1e-6) / np.clip(1 - p, 1e-6, 1))
    b = 1.0
    for _ in range(50):
        pr = 1 / (1 + np.exp(-b * z))
        b -= np.sum((pr - y) * z) / (np.sum(pr * (1 - pr) * z * z) + 1e-9)
    return float(b)


def walk(C, first, held_from):
    """C: name -> dict(S season, m month 'YYYY-MM', p chance, y outcome) over the same rows (NaN p = unscored)."""
    names = list(C)
    base = C["shipped"]
    ok = np.ones(len(base["y"]), bool)
    for n in names:
        ok &= ~np.isnan(C[n]["p"])
    S, M, y = base["S"], base["m"], base["y"]
    L = {n: (C[n]["l"] if "l" in C[n] else ll(np.where(ok, C[n]["p"], .5), y)) for n in names}
    rec, P, Y, mon, DD = [], [], [], defaultdict(list), []
    for s in sorted(set(S[ok & (S >= held_from)].tolist())):
        tr = ok & (S >= first) & (S < s)
        pick = min(names, key=lambda n: (float(L[n][tr].mean()), n != "shipped"))
        te = ok & (S == s)
        d = L[pick][te] - L["shipped"][te]
        DD.append(d)
        for mo, x in zip(M[te], d):
            mon[mo].append(x)
        P.append(C[pick]["p"][te])
        Y.append(y[te])
        rec.append({"season": int(s), "pick": pick, "n": int(te.sum()), "ll": round(float(L[pick][te].mean()), 5),
                    "llShipped": round(float(L["shipped"][te].mean()), 5), "d": round(float(d.mean()), 5)})
    mm = np.array([np.mean(v) for _, v in sorted(mon.items())])
    t = float(mm.mean() / (mm.std(ddof=1) / math.sqrt(len(mm)) + 1e-12)) if len(mm) > 1 else 0.0
    p, yy = np.concatenate(P), np.concatenate(Y)
    dall = float(np.concatenate(DD).mean())
    b = slope(p, yy)
    allm = ok & (S >= first)
    nxt = min(names, key=lambda n: (float(L[n][allm].mean()), n != "shipped"))
    return {"next": nxt, "seasons": rec, "n": int(len(yy)), "d": round(dall, 5), "tMonth": round(t, 2),
            "monthsBetter": [int((mm < 0).sum()), int(len(mm))], "slope": round(b, 3),
            "pass": bool(dall < 0 and t <= -2.0 and .7 <= b <= 1.3)}


# ---------------------------------------------------------------- adapters: name -> (candidates, rows, first, held, ship)
def nhl():
    import nhl_games as G
    hist = G.load_hist()
    F = json.load(open(G.FIT))
    P, feats = F["params"], F["feats"]
    grid = {'K': [4, 6, 9], 'reg': [0.2, 0.35, 0.5], 'hl': [30, 60, 120], 'car': [0.3, 0.5, 0.7],
            'ghl': [30, 60, 120], 'gcar': [0.3, 0.5, 0.7], 'mhl': [20, 40, 80], 'mcar': [0.2, 0.4, 0.7],
            'gk_car': [0.4, 0.6, 0.8], 'gk_k': [10, 25, 50], 'gk_0': [-0.25, -0.1, 0.0], 'pen': [1.0, 4.0, 12.0]}
    mv = G.hist_moves(hist)
    keep = lambda k, v: not (k.endswith("car") and v > 1) and not (k in ("reg",) and v <= 0)  # noqa: E731

    def run(Q):
        _, rows, _ = G.walk(hist, Q, moves=mv)
        S, y, mg, tot, pc, tc, day = G.arrays(rows)
        trn = ~np.isnan(pc) if "mkt" in feats else np.ones(len(y), bool)
        p = G.walk_logit(G.design(rows, feats), y, S, G.SCORE_FROM + 1, trn)
        return {"S": S, "m": np.array([d[:7] for d in day]), "p": p, "y": y.astype(float)}
    return candidates(P, grid, keep), run, G.SCORE_FROM + 1, G.HOLD_FROM


def nba():
    """margin model: home win chance = phi(walk-forward margin / the season's walk-forward sd, as shipped)"""
    import nba_games as N
    import nba_games_fit as NF
    games, names = N.load_hist()
    inj = NF.load_inj()
    F = json.load(open(N.FIT))
    P, feats = dict(F["params"]), F["feats"]
    _, _, PT = NF.measure_P(games, names, inj, P)
    sd = {int(k): v for k, v in F["sdBySeason"].items()}
    grid = {"hl": [12, 20, 30], "carry": [0.3, 0.5, 0.7], "mk": [0.05, 0.1, 0.15, 0.25], "mrev": [0.3, 0.5, 0.7],
            "rhl": [5.0, 10.0, 20.0], "elo_k": [15.0, 20.0, 25.0], "n0": [300.0, 600.0, 1200.0], "rook": [-3.0, -2.0, -1.0]}
    keep = lambda k, v: k == "rook" or (v > 0 and not (k == "carry" and v > 1))  # noqa: E731

    def run(Q):
        D, X, TX, y, ty, S, line, tline = NF.design(games, names, PT, Q, inj, feats)
        pr = NF.wf(NF.mat(X, feats), y, S)
        s = np.array([sd.get(int(v), F["sd"]) for v in S])
        p = np.array([N.phi(m / q) if not np.isnan(m) else np.nan for m, q in zip(pr, s)])
        keepy = y != 0
        p[~keepy] = np.nan
        return {"S": S, "m": np.array([g["tip"][:7] for g, _, _ in D]), "p": p, "y": (y > 0).astype(float)}
    return candidates(P, grid, keep), run, N.SCORE_FROM, N.HOLD_FROM


def nfl():
    """nfl_games.fit()'s walk (ratings, injuries, seasonal OLS from 2015); home win chance = phi(margin / shipped sd)"""
    import nfl_games as G
    last = 2025
    games, box, qbs = G.load(last)
    G.index_qbs(qbs, games)
    G.load_qb_teams(last)
    inj = G.injury_history(games, range(G.INJ_FIRST, last + 1))
    F = json.load(open(ROOT / "data" / "nfl_games_fit.json"))
    P, sd = dict(F["params"]), F["sd"]
    grid = {"hl": [4, 6, 8, 12], "carry": [0.3, 0.5, 0.7], "qb_n0": [50.0, 100.0, 200.0], "mk": [0.1, 0.2, 0.3],
            "mrev": [0.2, 0.4, 0.6]}
    keep = lambda k, v: v > 0 and not (k in ("carry", "mrev") and v > 1)  # noqa: E731

    def run(Q):
        _, data = G.walk(games, box, qbs, Q)
        for g, x, _ in data:
            r = inj.get(g["game_id"])
            if r:
                x["inj"] = (r[2] + r[3]) - (r[0] + r[1])
                x["ir"] = r[5] - r[4]
        D = [(g, x) for g, x, _ in data if g["home_score"] not in ("", "NA") and int(g["season"]) >= 2012]
        X = np.array([[x[f] for f in G.FEATS] for _, x in D])
        y = np.array([G.num(g["result"]) for g, _ in D])
        S = np.array([int(g["season"]) for g, _ in D])
        pred = np.full(len(y), np.nan)
        for s in range(2015, last + 1):
            tr, te = S < s, S == s
            pred[te] = X[te] @ np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        p = np.array([0.5 * (1 + math.erf(m / sd / math.sqrt(2))) if not np.isnan(m) else np.nan for m in pred])
        p[y == 0] = np.nan
        return {"S": S, "m": np.array([g["gameday"][:7] for g, _ in D]), "p": p, "y": (y > 0).astype(float)}
    return candidates(P, grid, keep), run, 2015, 2021


def cbb():
    """cbb_games.fit()'s walk: D-I games, home win chance = phi(walk-forward margin / the season's shipped sd)"""
    import cbb_games as G
    games, btname, d1s, tprior, avs = G.load_all()
    games = [g for g in games if g["season"] <= 2026]          # 2026-27 is the lockbox
    F = json.load(open(G.FIT))
    P, feats = dict(F["params"]), F["feats"]
    sd = {int(k): v for k, v in F["sdBySeason"].items()}
    grid = {'hl': [0.0, 30.0, 45.0, 70.0], 'lam': [2.0, 4.0, 8.0], 'K': [15.0, 25.0, 40.0], 'ecarry': [0.4, 0.6, 0.8],
            'mk': [0.08, 0.15, 0.25], 'mrev': [0.0, 0.3], 'split': [0.3, 0.5, 0.7]}
    keep = lambda k, v: v >= 0 and not (k in ("ecarry", "split", "mrev") and v > 1)  # noqa: E731

    def run(Q):
        W, rows = G.run_walk(Q, games, tprior, btname, d1s, avs)
        D, Xm, y, TX, ty, S, line, tline, d1 = G.matrices(rows, feats)
        pred = G.walk_pred(Xm, y, S, d1)
        s = np.array([sd.get(int(v), F["sd"]) for v in S])
        p = 0.5 * (1 + np.array([math.erf(z) for z in pred / s / math.sqrt(2)]))
        p[~d1 | (y == 0)] = np.nan
        return {"S": S, "m": np.array([str(g.get("date") or g.get("d"))[:7] for g, _, _ in D]), "p": p,
                "y": (y > 0).astype(float)}
    return candidates(P, grid, keep), run, G.SCORE0, G.TUNE_END + 1


def soccer():
    """soccer_games.walk(): every scored match's 1X2 chances straight from the ratings; loss = 3-way log loss
    (slope on the home-win chance)"""
    import soccer_games as G
    rows = G.add_inj(G.add_mv(G.add_market(G.D.load(G.HIST))))
    P = G.params()
    keys = ['wm', 'km', 'wx', 'kx', 'k', 'kl', 'kh', 'rho', 'boost', 'nb', 'cup', 'mv', 'av']
    cands = [("shipped", dict(P))]
    for k in keys:   # tune()'s own steps: +-.04 (rho), +-.5 (boost), x.7 / x1.4 (the rest; weights capped at 1)
        for f in ((-0.04, 0.04) if k == 'rho' else (-0.5, 0.5) if k == 'boost' else (0.7, 1.4)):
            v = P[k] + f if k in ('rho', 'boost') else P[k] * f
            if k.startswith('w'):
                v = min(v, 1.0)
            if v != P[k]:
                cands.append((f"{k} {v:.4g}", dict(P, **{k: v})))

    def run(Q):
        wf = [o for o in G.walk(rows, Q) if o['S'] <= 2026]
        pr = np.array([o['p'] for o in wf], float)
        r = np.array([0 if o['hs'] > o['as'] else 1 if o['hs'] == o['as'] else 2 for o in wf])
        l = -np.log(np.clip(pr[np.arange(len(r)), r], 1e-6, 1))
        return {"S": np.array([o['S'] for o in wf]), "m": np.array([o['day'][:7] for o in wf]), "p": pr[:, 0],
                "y": (r == 0).astype(float), "l": l}
    return cands, run, G.SCORE_FROM, G.HOLD_FROM


def tennis():
    """tennis_model's walk-forward blend chances (weights fit on the WIN seasons before each), tour-level main draws"""
    import tennis_data as T
    import tennis_model as M
    rows, _, _ = T.load()
    rows = [r for r in rows if r[0] <= 20261110]                 # Nov 11 2026 on is the lockbox
    P = dict(M.DEFAULT, **json.load(open(M.FIT))["params"])
    grid = {"KC": [200, 250, 300, 350], "KO": [5, 10, 20, 40], "KS": [0.35, 0.4, 0.45, 0.5], "SW": [0.2, 0.3, 0.4, 0.5],
            "RET": [0.5, 1.0, 1.5], "PHI": [0.35, 0.5, 0.7, 0.9], "V0": [0.03, 0.05, 0.1, 0.2],
            "Q": [0.0001, 0.0003, 0.001], "KG": [1.0, 1.5, 2.0, 3.0, 4.0], "GSW": [0.0, 0.3, 0.5]}
    keep = lambda k, v: v >= 0 and not (k in ("SW", "GSW", "PHI") and v > 1)  # noqa: E731

    def run(Q):
        _, rec = M.run(rows, Q, score=lambda r: M.scored(r, 2012 - M.WIN, 2100), cm_lag=M.CM_LAG)
        pw = np.array(M.wf_probs(rec, Q), float)
        d = np.array([x[0][0] for x in rec])
        k = d >= 20120000
        flip = np.arange(int(k.sum())) % 2 == 1     # rows are winner-first: alternate sides so y is not all 1
        p = np.where(flip, 1 - pw[k], pw[k])
        return {"S": d[k] // 10000, "m": np.array([f"{v // 10000}-{v // 100 % 100:02d}" for v in d[k]]), "p": p,
                "y": (~flip).astype(float)}
    return candidates(P, grid, keep), run, 2012, 2023


ADAPT = {"tennis": tennis, "nhl": nhl, "nba": nba, "nfl": nfl, "cbb": cbb, "soccer": soccer}


_RUN = None


def _call(Q):
    return _RUN(Q)


def main():
    global _RUN
    import os
    for sp in sys.argv[1:]:
        cands, run, first, held = ADAPT[sp]()
        C = {}
        procs = int(os.environ.get("WF_PROCS", "1"))
        if procs > 1:   # fork: the children share the loaded data
            import multiprocessing as mp
            _RUN = run
            with mp.get_context("fork").Pool(procs) as pool:
                outs = pool.map(_call, [Q for _, Q in cands])
            C = {n: o for (n, _), o in zip(cands, outs)}
        else:
            for n, Q in cands:
                C[n] = run(Q)
                print(sp, n, round(float(np.nanmean(ll(C[n]["p"], C[n]["y"]))), 5), flush=True)
        r = walk(C, first, held)
        r["candidates"] = [n for n, _ in cands]
        print(sp, {k: v for k, v in r.items() if k not in ("candidates",)}, flush=True)
        res = json.loads(OUT.read_text()) if OUT.exists() else {}   # other sports may have written meanwhile
        res[sp] = r
        OUT.write_text(json.dumps(res, indent=1))
    card(res)


NAMES = {"tennis": "Tennis", "nhl": "NHL", "nba": "NBA", "nfl": "NFL", "cbb": "CBB", "soccer": "Soccer"}


def card(res):
    """Process > Research card from data/wf_retune.json (and the CS2 loop's record), never hand-edited"""
    rows = [(NAMES[k], v) for k, v in res.items() if k in NAMES]
    try:
        cs = json.loads((ROOT / "data" / "cs2_ark_loop.json").read_text())["record"]
        rows.append(("CS2", {"tMonth": cs["t"], "d": cs["d"], "pass": cs["d"] < 0 and cs["t"] <= -2,
                             "monthsBetter": cs["won"], "n": cs["n"]}))
    except (OSError, ValueError, KeyError):
        pass
    rows.sort(key=lambda z: z[1]["tMonth"])
    ok = [n for n, v in rows if v["pass"]]
    out = {
        "id": "wf-retune-sports", "sport": "CS2",
        "question": "Does re-picking a rating's settings each season beat keeping them fixed?",
        "answer": (f"Passes in {', '.join(ok) if ok else 'no sport'}; fails in "
                   f"{', '.join(n for n, v in rows if not v['pass']) or 'none'}."),
        "findings": [f"{n}: {v['d'] * 1000:+.2f} log loss x1000, t by month {v['tMonth']:+.2f}, "
                     f"{v['monthsBetter'][0]}/{v['monthsBetter'][1]} months." for n, v in rows][:4],
        "method": ("Each season (CS2: month), the settings with the lowest walk-forward log loss on every earlier "
                   "season are picked from the shipped set and one-step moves on each tuned setting, then scored once "
                   "on that season against the shipped settings. Held-out seasons only; pass at t by month <= -2."),
        "data": "Each sport's game-model history, held-out seasons before the 2026-27 lockbox; CS2 Jul 2025 to its last sealed month.",
        "n": int(sum(v.get("n", 0) for _, v in rows)), "robust": bool(ok), "interest": 3,
        "split_check": f"{len(ok)} of {len(rows)} sports pass.",
        "chart": {"type": "bar", "title": "t by month, re-picked minus fixed settings", "x_label": "sport",
                  "y_label": "t by month", "y_fmt": "num", "ref": {"y": -2, "label": "pass"}, "mark": None,
                  "series": [{"name": "t", "points": [{"x": n, "y": v["tMonth"], "n": v.get("n")} for n, v in rows]}]},
        "auto": "scripts/wf_retune.py"}
    CARD.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
