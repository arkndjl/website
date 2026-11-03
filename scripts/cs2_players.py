#!/usr/bin/env python3
"""Counter-Strike players: ratings, prospects, transfer values and team tiers (data/cs2_players.json).

    python3 scripts/cs2_players.py --fit   # backtests -> data/cs2_players_fit.json (settings, scores, failed terms)
    python3 scripts/cs2_players.py         # build data/cs2_players.json and add tiers to data/cs2.json

Data: per-map player stats from bo3.gg (scripts/cs2_pstats.py, since Jan 2024), map results and event tiers
(scripts/cs2_bo3.py), bo3.gg's player directory (birthdays, photos).

Rating (RWA, round win % added per round, opponent-adjusted):
  1. Stat weights: a team's round share on a map regressed on the sum of its five players' per-round stats (kills,
     deaths, assists, damage, KAST, opening kills/deaths, trade kills, traded deaths, multi-kill rounds, clutches).
     A player's map line times the weights, minus the average line's, is his share of the team's round share: the five
     add up to the team's share above .5.
  2. Opponents: each map line is credited with the opposing five's mean rating (x w_opp), solved iteratively, so 0.5
     of round share against a top team counts for more than against a tier-3 side.
  3. Time decay (half-life h days) and shrinkage toward the prior (k rounds of the prior), both tuned on predicting
     the round share of later maps out of sample (walk forward, monthly cutoffs).
Prospects: players with fewer than T1_MAPS maps at S-tier events, graded by projected rating against tier-1 teams
(the rating above, plus a rise term only if it passes the backtest).
Transfer value (xTV): Elo the player adds to a team over a replacement-level player, priced with a curve anchored
on publicly reported buyouts (data/cs2_fees.json), with an age term from the data's own aging curve.
Tiers: an event-access cut on team Elo: Tier 1 = a team whose rating usually plays S-tier events (bo3.gg tiers), and so
on down, fit on the last 180 days.
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
from cs2_data import key  # noqa: E402
import cs2_pstats as PS  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIT = ROOT / "data" / "cs2_players_fit.json"
OUT = ROOT / "data" / "cs2_players.json"
FEES = ROOT / "data" / "cs2_fees.json"
STATS = ["k", "d", "a", "adr", "kast", "fk", "fd", "tk", "td", "mk", "cl", "hs"]  # hs added Nov 3 (held t -10.4)
TIER = {"s": 1, "a": 2, "b": 3, "c": 4, "d": 5}
T1_MAPS = 20


def ordd(s):
    return dt.date.fromisoformat(s[:10]).toordinal()


class Maps:
    """Every player-map row joined to its map (date, rounds, result, event tier)."""

    def __init__(self, bo3=None):
        bo3 = bo3 or cs2_bo3.load()
        mt = {m[0]: m for m in bo3["matches"]}
        gm = {g[0]: g for g in bo3["games"] if g[5] is not None and g[7] is not None}
        rows = []
        for f in sorted(PS.DIR.glob("*.json.gz")):
            with gzip.open(f, "rt") as fh:
                rows += json.load(fh)["rows"]
        by_g = defaultdict(list)
        for r in rows:
            if r[0] in gm and r[2] is not None:
                by_g[r[0]].append(r)
        G, P, S, X, D, TR, TM, NICK = [], [], [], [], [], [], [], {}
        games = []
        for g, rs in by_g.items():
            gg = gm[g]
            sides = defaultdict(list)
            for r in rs:
                sides[r[2]].append(r)
            if len(sides) != 2 or any(len(v) != 5 for v in sides.values()):
                continue
            w, lo, rw, rl = gg[5], gg[6], gg[7], gg[8]
            if {w, lo} != set(sides) or rw + rl < 13:
                continue
            m = mt.get(gg[1])
            tier = TIER.get(m[10], 5) if m else 5
            gi = len(games)
            games.append((g, gg[2][:10], w, lo, rw, rl, tier, gg[3]))
            for side, tid in enumerate((w, lo)):
                for r in sides[tid]:
                    R = rw + rl
                    G.append(gi), P.append(r[1]), S.append(side), D.append(ordd(gg[2]))
                    TM.append(tid)
                    X.append([r[3] / R, r[4] / R, r[5] / R, r[12] / 1000,
                              r[11] / 1000, r[7] / R, r[8] / R, r[9] / R, r[10] / R, r[15] / R, r[14] / R, r[6] / R])
                    TR.append(tier)
                    NICK[r[1]] = r[16]
        self.games = games
        self.g = np.array(G)
        self.p_raw = np.array(P)
        self.pids, self.p = np.unique(self.p_raw, return_inverse=True)
        self.side = np.array(S)
        self.X = np.array(X, dtype=float)
        self.d = np.array(D)
        self.tier = np.array(TR)
        self.team = np.array(TM)
        self.nick = NICK
        self.R = np.array([games[i][4] + games[i][5] for i in G], dtype=float)
        # round share of the player's own team
        self.y = np.array([(games[i][4] if s == 0 else games[i][5]) / (games[i][4] + games[i][5])
                           for i, s in zip(G, S)])
        # index: (game, side) -> the five row indices
        self.five = np.zeros((len(games), 2, 5), dtype=int)
        cnt = np.zeros((len(games), 2), dtype=int)
        for i, (gi, s) in enumerate(zip(G, S)):
            self.five[gi, s, cnt[gi, s]] = i
            cnt[gi, s] += 1
        self.gd = np.array([ordd(g[1]) for g in games])
        print(f"maps {len(games)}, player-maps {len(G)}, players {len(self.pids)}", file=sys.stderr)


def stat_weights(M, mask_games=None, l2=1e-4):
    """Team round share on the sum of its five per-round stat lines -> weights, intercept, mean line."""
    gi = np.arange(len(M.games)) if mask_games is None else np.where(mask_games)[0]
    Xt = M.X[M.five[gi, 0]].sum(1)  # winners' side 0 and losers' side 1 both used
    Xl = M.X[M.five[gi, 1]].sum(1)
    yt = M.y[M.five[gi, 0, 0]]
    yl = M.y[M.five[gi, 1, 0]]
    X = np.vstack([Xt, Xl])
    y = np.concatenate([yt, yl])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
    w = np.linalg.solve(Z.T @ Z + l2 * len(X) * np.diag([0] + [1] * (Z.shape[1] - 1)), Z.T @ y)
    beta = w[1:] / sd
    r2 = 1 - ((Z @ w - y) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return beta, mu / 5, float(r2)


def contributions(M, beta, mline, pm=0.0):
    """Each player-map's share of his team's round share above .5 (x100: round win % added). pm: share of the team's
    residual (round share its five box lines miss) credited to each of the five equally, x pm (box + plus-minus)."""
    c = (M.X - mline) @ beta * 100
    if pm:
        tot = np.zeros((len(M.games), 2))
        np.add.at(tot, (M.g, M.side), c)
        c = c + pm * (100 * (M.y - 0.5) - tot[M.g, M.side]) / 5
    return c


def ratings(M, c, T, p):
    """Ratings at day T (ordinal) from player-maps before T: decay half-life p['h'] days, shrink p['k'] rounds toward
    the prior, opponents' mean rating credited x p['opp'] (iterated). -> (theta per player, rounds weight)."""
    m = M.d < T
    w = M.R * np.exp(-(T - M.d) * math.log(2) / p["h"]) * m
    n = len(M.pids)
    theta = np.zeros(n)
    wsum = np.bincount(M.p, w, n)
    prior = p.get("prior", 0.0)
    # tier lift (Nov 3): + ssg x share of the last year's rounds at S/A-tier events. Low-tier pools connect to the top
    # through few maps, so opponent credit alone left their ratings high (S/A-exposed fives beat the rating prediction
    # by .037 round share per unit of share gap, t 13.7)
    lift = p.get("ssg", 0.0) * sa_share(M, T) if p.get("ssg") else 0.0
    for _ in range(6):
        th_row = (theta + lift)[M.p]
        opp = th_row[M.five[M.g, 1 - M.side]].mean(1)
        adj = c + p["opp"] * opp
        theta = (np.bincount(M.p, w * adj, n) + p["k"] * prior) / (wsum + p["k"])
    return theta + lift, wsum


def predict_score(M, c, p, months):
    """Walk forward: ratings at each month start predict that month's map round shares. -> (mse, mse of flat .5, n)."""
    err, base, nn = 0.0, 0.0, 0
    for mo in months:
        T = ordd(mo + "-01")
        T2 = ordd((dt.date.fromordinal(T) + dt.timedelta(days=32)).replace(day=1).isoformat())
        theta, _ = ratings(M, c, T, p)
        gi = np.where((M.gd >= T) & (M.gd < T2))[0]
        if not len(gi):
            continue
        ta = theta[M.p[M.five[gi, 0]]].sum(1)
        tb = theta[M.p[M.five[gi, 1]]].sum(1)
        y = M.y[M.five[gi, 0, 0]]
        pred = 0.5 + p.get("a", 1.0) * (ta - tb) / 200
        err += ((pred - y) ** 2).sum()
        base += ((0.5 - y) ** 2).sum()
        nn += len(gi)
    return err / nn, base / nn, nn


def logfit(x, y, l2=1e-6):
    X = np.column_stack([np.ones(len(x)), x])
    w = np.zeros(2)
    for _ in range(60):
        q = 1 / (1 + np.exp(-X @ w))
        H = (X * (q * (1 - q))[:, None]).T @ X + l2 * np.eye(2)
        w -= np.linalg.solve(H, X.T @ (q - y))
    return w


def tiers(teams, bo3, days=180):
    """Event-access tiers for the ranked teams (list of cs2.json team dicts, edited in place: tier, ev).
    Over the last `days`, every series a ranked team played is one row: its Elo and the event's bo3.gg tier. A logistic
    of 'S-tier event' on Elo gives the Elo where a team plays mostly S-tier events: the Tier 1 cut. 'S or A' gives
    Tier 2, 'S, A or B' Tier 3; below that, Tier 4. -> {"cuts": [t1, t2, t3], "n": rows, "days": days}"""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    tid = {t["k"]: bo3.team_of(t["k"]) for t in teams}
    by = defaultdict(list)
    for r in bo3.mt.values():
        if (r[1] or "") >= since:
            for x in (r[2], r[3]):
                by[x].append(TIER.get(r[10], 5))
    E, Y = [], []
    for t in teams:
        ev = by.get(tid[t["k"]], []) if tid[t["k"]] else []
        t["ev"] = [round(sum(1 for v in ev if v == j) / len(ev), 2) for j in (1, 2, 3)] if ev else None
        E += [t["elo"]] * len(ev)
        Y += ev
    E, Y = (np.array(E, float) - 1400) / 100, np.array(Y)
    cuts = []
    for j in (1, 2, 3):
        w = logfit(E, (Y <= j).astype(float))
        cuts.append(round(1400 - 100 * w[0] / w[1]) if w[1] > 0 else None)
    for t in teams:
        t["tier"] = next((i + 1 for i, c in enumerate(cuts) if c is not None and t["elo"] >= c), 4)
    return {"cuts": cuts, "n": int(len(Y)), "days": days}


TUNE = ("2024-07-01", "2025-06-30")
HELD = ("2025-07-01", "2099-12-31")
DEF = {"h": 180, "k": 300, "opp": 1.0, "prior": 0.0, "a": 1.0}


def months(a, b, last):
    out, d = [], dt.date.fromisoformat(a[:8] + "01")
    end = min(dt.date.fromisoformat(b), last)
    while d <= end:
        out.append(d.isoformat()[:7])
        d = (d + dt.timedelta(days=32)).replace(day=1)
    return out


def fit_scale(M, c, p, mos):
    """Least-squares a for pred = .5 + a (sum theta A - sum theta B) / 200 over the walk-forward months."""
    num = den = 0.0
    for mo in mos:
        T = ordd(mo + "-01")
        T2 = ordd((dt.date.fromordinal(T) + dt.timedelta(days=32)).replace(day=1).isoformat())
        theta, _ = ratings(M, c, T, p)
        gi = np.where((M.gd >= T) & (M.gd < T2))[0]
        x = (theta[M.p[M.five[gi, 0]]].sum(1) - theta[M.p[M.five[gi, 1]]].sum(1)) / 200
        y = M.y[M.five[gi, 0, 0]] - 0.5
        num += (x * y).sum()
        den += (x * x).sum()
    return num / den if den else 1.0


def map_sq(M, c, p, months):
    """Per-map squared errors of the walk-forward round-share prediction (as predict_score)."""
    out = []
    for mo in months:
        T = ordd(mo + "-01")
        T2 = ordd((dt.date.fromordinal(T) + dt.timedelta(days=32)).replace(day=1).isoformat())
        theta, _ = ratings(M, c, T, p)
        gi = np.where((M.gd >= T) & (M.gd < T2))[0]
        x = (theta[M.p[M.five[gi, 0]]].sum(1) - theta[M.p[M.five[gi, 1]]].sum(1)) / 200
        out.append((M.y[M.five[gi, 0, 0]] - 0.5 - p.get("a", 1.0) * x) ** 2)
    return np.concatenate(out)


def fit():
    M = Maps()
    last = dt.date.fromordinal(int(M.gd.max()))
    tune_g = (M.gd < ordd(TUNE[1]))
    beta, ml, r2 = stat_weights(M, tune_g)
    cs = {pm: contributions(M, beta, ml, pm) for pm in (0.0, 0.25, 0.5, 1.0)}
    tm, hm = months(*TUNE, last), months(*HELD, last)
    # scoring months are thinned to every second month in the grid (speed); held months are all scored.
    # opp > 1 over-credits (fed back through the iteration; top-50 game test worse at 2), 0.5 lost on Nov 2: kept 1.0
    grid = []
    for h in (120, 180, 365):
        for k in (25, 50, 100):
            for pm, cc in cs.items():
                p = dict(DEF, h=h, k=k, opp=1.0, pm=pm)
                p["a"] = fit_scale(M, cc, p, tm[::2])
                e, b0, n = predict_score(M, cc, p, tm[1::2])
                grid.append((e, p))
                print(f"h {h} k {k} pm {pm} a {p['a']:.2f} mse {e:.5f} flat {b0:.5f}", file=sys.stderr)
    grid.sort(key=lambda x: x[0])
    best = grid[0][1]
    c = cs[best["pm"]]
    # tier lift, tuned on the same tune months after the grid
    lifts = []
    for g in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        q = dict(best, ssg=g)
        q["a"] = fit_scale(M, c, q, tm[::2])
        lifts.append((predict_score(M, c, q, tm[1::2])[0], g, q))
        print(f"lift {g} mse {lifts[-1][0]:.6f}", file=sys.stderr)
    best = min(lifts, key=lambda x: x[0])[2]
    out = {"beta": dict(zip(STATS, [round(float(b), 4) for b in beta])), "mline": [round(float(x), 5) for x in ml],
           "r2": round(r2, 3), "params": best, "tune": list(TUNE), "held": [HELD[0], last.isoformat()]}
    # held out: ours vs alternatives (each with its own a fit on tune), paired t on per-map squared error
    j11 = [STATS.index(x) for x in STATS if x != "hs"]
    X0 = M.X
    M.X = X0[:, j11]
    b11, m11, _ = stat_weights(M, tune_g)
    c_old = contributions(M, b11, m11)
    M.X = X0
    alts = {"ARK player rating": (c, best),
            "Nov 2 rating (no headshots, no plus-minus)": (c_old, dict(DEF, h=180, k=50, opp=1.0)),
            "no plus-minus": (cs[0.0], dict(best, pm=0.0)),
            "no tier lift": (c, dict(best, ssg=0.0)),
            "no opponent credit": (c, dict(best, opp=0.0)),
            "kills minus deaths per round": ((M.X[:, 0] - M.X[:, 1]) * 100 / 2, best)}
    score, e_ours = [], None
    for nm, (cc, pp) in alts.items():
        pp = dict(pp)
        pp["a"] = fit_scale(M, cc, pp, tm[::2])
        e = map_sq(M, cc, pp, hm)
        b0 = map_sq(M, cc, dict(pp, a=0.0), hm).mean()
        if e_ours is None:
            e_ours = e
        dl = e - e_ours
        score.append({"name": nm, "mse": round(float(e.mean()), 6), "flat": round(float(b0), 6), "n": len(e),
                      "r2": round(float(1 - e.mean() / b0), 4),
                      "t": round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)})
        print(nm, score[-1], file=sys.stderr)
    out["score"] = score
    pdir = load_pdir()
    out["prospects"] = prospect_fit(M, c, best, pdir)
    print("prospects", json.dumps(out["prospects"], default=str)[:1500], file=sys.stderr)
    out["aging"] = ag = aging_fit(M, c, best, pdir)
    print("aging", ag, file=sys.stderr)
    out["value"] = fee_fit(M, c, best, pdir, ag, best["a"], cs2_bo3.Bo3())
    print("value", out["value"], file=sys.stderr)
    out["game"] = game_test(M, c, best)
    print("game", out["game"], file=sys.stderr)
    FIT.write_text(json.dumps(out, indent=1))
    return out


def window_stats(M, c, theta, T0, T1, p):
    """Rounds-weighted mean of opponent-credited contributions over maps in [T0, T1) (no shrink, no decay), with the
    opponents' ratings theta. -> (mean per player, rounds per player)."""
    m = (M.d >= T0) & (M.d < T1)
    opp = theta[M.p][M.five[M.g, 1 - M.side]].mean(1)
    adj = c + p["opp"] * opp
    n = len(M.pids)
    w = M.R * m
    r = np.bincount(M.p, w, n)
    return np.bincount(M.p, w * adj, n) / np.maximum(r, 1), r


def s_maps(M, T):
    """Maps each player has played at S-tier events before day T."""
    return np.bincount(M.p, (M.tier == 1) & (M.d < T), len(M.pids))


def ages(M, pdir, T):
    out = np.full(len(M.pids), np.nan)
    for i, pid in enumerate(M.pids):
        b = (pdir.get(str(pid)) or [None] * 3)[2]
        if b:
            try:
                out[i] = (T - ordd(b)) / 365.25
            except ValueError:
                pass
    return out


def prospect_rows(M, c, p, T, pdir, min_r=600):
    """Prospect pool at day T: under T1_MAPS S-tier maps, min_r+ rounds in the last year. -> dict of arrays."""
    th, _ = ratings(M, c, T, p)
    th6, _ = ratings(M, c, T - 182, p)
    _, r12 = window_stats(M, c, th, T - 365, T, p)
    sm = s_maps(M, T)
    ok = (sm < T1_MAPS) & (r12 >= min_r)
    return {"i": np.where(ok)[0], "th": th, "rise": th - th6, "r12": r12, "age": ages(M, pdir, T), "sm": sm,
            "ss": sa_share(M, T)}


def sa_share(M, T):
    """Share of each player's rounds over the last year played at S- or A-tier events (bo3.gg tiers)."""
    m = (M.d >= T - 365) & (M.d < T)
    n = len(M.pids)
    return np.bincount(M.p, M.R * m * (M.tier <= 2), n) / np.maximum(np.bincount(M.p, M.R * m, n), 1)


def ols(X, y, w=None):
    w = np.ones(len(y)) if w is None else w
    Xw = X * w[:, None]
    return np.linalg.lstsq(Xw.T @ X + 1e-6 * np.eye(X.shape[1]), Xw.T @ y, rcond=None)[0]


def prospect_fit(M, c, p, pdir):
    """Walk forward over quarterly cutoffs: a prospect's rating over the next 12 months (opponent-credited, 600+
    rounds) from his rating now, his 6-month rise and age. Tune cutoffs before HELD, scored on the rest."""
    last = int(M.gd.max())
    cuts = []
    d = dt.date(2024, 10, 1)
    while d.toordinal() + 365 <= last:
        cuts.append(d.toordinal())
        d = (d + dt.timedelta(days=92)).replace(day=1)
    data = []
    for T in cuts:
        pr = prospect_rows(M, c, p, T, pdir)
        thF, _ = ratings(M, c, T + 365, p)
        fut, rf = window_stats(M, c, thF, T, T + 365, p)
        i = pr["i"][rf[pr["i"]] >= 600]
        # reached T1: 20+ S-tier maps within the next year
        reach = (s_maps(M, T + 365) - pr["sm"])[pr["i"]] >= T1_MAPS
        data.append({"T": T, "i": i, "th": pr["th"][i], "rise": pr["rise"][i], "age": pr["age"][i], "y": fut[i],
                     "ss": pr["ss"][i], "w": np.minimum(rf[i], 3000), "reach_all": reach, "th_all": pr["th"][pr["i"]],
                     "rise_all": pr["rise"][pr["i"]], "ss_all": pr["ss"][pr["i"]]})
    tune = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() < HELD[0]]
    held = [x for x in data if dt.date.fromordinal(x["T"]).isoformat() >= HELD[0]]
    if not tune or not held:
        return None

    def stack(xs, cols):
        X = np.concatenate([np.column_stack([np.ones(len(x["y"]))] + [np.nan_to_num(x[k] - (22 if k == "age" else 0))
                                                                      for k in cols]) for x in xs])
        return X, np.concatenate([x["y"] for x in xs]), np.concatenate([x["w"] for x in xs])
    res = {}
    for nm, cols in (("rating now", ["th"]), ("rating + rise", ["th", "rise"]), ("rating + age", ["th", "age"]),
                     ("rating + rise + age", ["th", "rise", "age"]),
                     # Nov 3: share of last year's rounds at S/A-tier events (scripts/cs2_nov03_research.py, t -5.9)
                     ("rating + age + S/A share", ["th", "age", "ss"])):
        X, y, w = stack(tune, cols)
        b = ols(X, y, w)
        Xh, yh, wh = stack(held, cols)
        e = yh - Xh @ b
        res[nm] = {"cols": cols, "b": [round(float(v), 4) for v in b], "mse": float((wh * e * e).sum() / wh.sum()),
                   "n": int(len(yh)), "e": e, "w": wh}
    be, bmse = res["rating now"]["e"], res["rating now"]["mse"]
    for nm, r in res.items():
        dlt = r["w"] * (r["e"] ** 2 - be ** 2)
        r["t"] = round(float(dlt.mean() / (dlt.std() + 1e-12) * math.sqrt(len(dlt))), 2)
        r["dmse"] = round(r["mse"] - bmse, 4)
        r["mse"] = round(r["mse"], 4)
    # the S/A share term on its own: against rating + age
    ra_, rs_ = res["rating + age"], res["rating + age + S/A share"]
    dl = rs_["w"] * (rs_["e"] ** 2 - ra_["e"] ** 2)
    rs_["tTerm"] = round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)
    for r in res.values():
        del r["e"], r["w"]
    # reach model: logistic of reaching T1 within a year on rating and rise (all prospects, not only 600+ later)
    def reach_fit(cols):
        Xr = np.concatenate([np.column_stack([np.ones(len(x["th_all"]))] + [x[k] for k in cols]) for x in tune])
        yr = np.concatenate([x["reach_all"] for x in tune]).astype(float)
        wr = np.zeros(Xr.shape[1])
        for _ in range(50):
            q = 1 / (1 + np.exp(-Xr @ wr))
            wr -= np.linalg.solve((Xr * (q * (1 - q))[:, None]).T @ Xr + 1e-6 * np.eye(len(wr)), Xr.T @ (q - yr))
        Xrh = np.concatenate([np.column_stack([np.ones(len(x["th_all"]))] + [x[k] for k in cols]) for x in held])
        yrh = np.concatenate([x["reach_all"] for x in held]).astype(float)
        qh = np.clip(1 / (1 + np.exp(-Xrh @ wr)), 1e-6, 1 - 1e-6)
        return wr, -(yrh * np.log(qh) + (1 - yrh) * np.log(1 - qh)), yr, yrh
    wr, lh, yr, yrh = reach_fit(["th_all", "rise_all"])
    wr2, lh2, _, _ = reach_fit(["th_all", "rise_all", "ss_all"])
    dl = lh2 - lh
    t_ss = round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)
    if t_ss < -3.3:  # Bonferroni cut of the Nov 3 test batch
        wr, lh = wr2, lh2
    llh = float(lh.mean())
    pb = yr.mean()
    llb = float(-(yrh * np.log(pb) + (1 - yrh) * np.log(1 - pb)).mean())
    # passing terms (held t < -2 and lower mse) are kept
    keep = "rating now"
    rs_ = res["rating + age + S/A share"]
    if rs_["t"] < -2 and res["rating + age"]["t"] < -2 and rs_["tTerm"] < -3.3:  # term clears the Bonferroni cut
        keep = "rating + age + S/A share"
    for nm in ("rating + rise + age", "rating + rise", "rating + age") if keep == "rating now" else ():
        r = res[nm]
        if r["t"] < -2 and all(res[x]["t"] < -2 for x in (["rating + " + c for c in ("rise", "age") if c in r["cols"]]
                                                          if nm.count("+") == 2 else [nm])):
            keep = nm
            break
    return {"models": res, "keep": keep, "cuts": [dt.date.fromordinal(x["T"]).isoformat() for x in data],
            "nTune": int(sum(len(x["y"]) for x in tune)),
            "reach": {"w": [round(float(v), 4) for v in wr], "tShare": t_ss, "ll": round(llh, 4), "llBase": round(llb, 4),
                      "rate": round(float(yrh.mean()), 3), "n": int(len(yrh))}}


def nick_index(M, bo3):
    """(nick key, team key) -> player id index and nick key -> the index with the most maps (Valve rosters are nicks)."""
    by = defaultdict(lambda: defaultdict(int))
    byt = {}
    for i, (pi, tid) in enumerate(zip(M.p, M.team)):
        nk = names.key(M.nick.get(M.pids[pi]) or "")
        by[nk][pi] += 1
        byt[(nk, bo3.k(int(tid)))] = pi
    return {k: max(v, key=v.get) for k, v in by.items()}, byt


def game_test(M, c, p):
    """Does the five's mean player rating add to the live series model (player Elo + VRS + team map rating)?
    Ratings from each month's first day only; same tune / held windows and tiered logistic as cs2_model --fit."""
    import cs2_model as CM
    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = CM.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, vrs, json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    nk, nkt = nick_index(M, bo3)
    snaps = {}
    for r in rows:
        mo = r["d"][:7]
        if mo not in snaps:
            snaps[mo] = ratings(M, c, ordd(mo + "-01"), p)[0]
        th = snaps[mo]

        def mean(ros, k):
            v = [th[nkt.get((names.key(q), k), nk.get(names.key(q)))] for q in ros or []
                 if nkt.get((names.key(q), k), nk.get(names.key(q))) is not None]
            return np.mean(v) if len(v) >= 3 else None
        a, b = mean(r["r"][4], r["a"]), mean(r["r"][5], r["b"])
        r["z"] = (a - b) / 10 if a is not None and b is not None else 0.0
        r["zok"] = a is not None and b is not None
    tr = [r for r in rows if CM.TUNE[0] <= r["d"] <= CM.TUNE[1] and r["d"] >= "2024-07-01"]
    he = [r for r in rows if r["d"] >= CM.HELD[0]]
    s = np.array([r["s"] for r in he])
    out = {}
    for nm, f in (("live model", lambda r: [r["x"], r["v"], r["t"]]),
                  ("live model + player ratings", lambda r: [r["x"], r["v"], r["t"], r["z"]])):
        q = np.zeros(len(he))
        ws = {}
        for tier in (True, False):
            t_ = [r for r in tr if r["top"] == tier]
            idx = [i for i, r in enumerate(he) if r["top"] == tier]
            w = CM.fitlog(np.array([f(r) for r in t_]), np.array([r["s"] for r in t_]))
            ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
            q[idx] = 1 / (1 + np.exp(-np.array([f(he[i]) for i in idx]) @ w))
        out[nm] = {"q": q, "w": ws}
    l0, l1 = CM.ll(out["live model"]["q"], s), CM.ll(out["live model + player ratings"]["q"], s)
    top = np.array([r["top"] for r in he])
    res = {"n": len(he), "coverage": round(float(np.mean([r["zok"] for r in he])), 3),
           "w": out["live model + player ratings"]["w"]}
    for nm, m in (("all", np.ones(len(he), bool)), ("top50", top)):
        dl = (l1 - l0)[m]
        res[nm] = {"n": int(m.sum()), "ll0": round(float(l0[m].mean()), 4), "ll1": round(float(l1[m].mean()), 4),
                   "t": round(float(dl.mean() / (dl.std() + 1e-12) * math.sqrt(len(dl))), 2)}
    return res


class Live:
    """Player-rating term for the live series model (scripts/cs2_model.py): the five's mean rating, A minus B, / 10,
    from ratings as of the first of the series' month (as in game_test). Off (w None) unless game_test passed."""

    def __init__(self, bo3):
        fj = json.loads(FIT.read_text()) if FIT.exists() else {}
        g = fj.get("game") or {}
        self.w = g.get("w") if g.get("all", {}).get("t", 0) < -2 and g.get("top50", {}).get("t", 0) < -2 else None
        if not self.w:
            return
        self.p = fj["params"]
        self.M = Maps()
        self.c = contributions(self.M, np.array([fj["beta"][k] for k in STATS]), np.array(fj["mline"]),
                               self.p.get("pm", 0.0))
        self.nk, self.nkt = nick_index(self.M, bo3)
        self.snaps = {}

    def mean(self, ros, k, d):
        mo = d[:7]  # "now": today's ratings, for upcoming series
        if mo not in self.snaps:
            T = dt.date.today().toordinal() + 1 if d == "now" else ordd(mo + "-01")
            self.snaps[mo] = ratings(self.M, self.c, T, self.p)[0]
        th = self.snaps[mo]
        ix = [self.nkt.get((names.key(q), k), self.nk.get(names.key(q))) for q in ros or []]
        v = [th[i] for i in ix if i is not None]
        return float(np.mean(v)) if len(v) >= 3 else None

    def z(self, ra, ka, rb, kb, d):
        a, b = self.mean(ra, ka, d), self.mean(rb, kb, d)
        return (a - b) / 10 if a is not None and b is not None else 0.0


def load_pdir():
    try:
        with gzip.open(PS.PDIR, "rt") as fh:
            return json.load(fh)
    except (FileNotFoundError, OSError, ValueError):
        return {}


def aging_fit(M, c, p, pdir):
    """Next year's rating from this year's (shrunk) rating and age: fut = b0 + b1 th + b2 (age-24) + b3 (age-24)^2,
    quarterly cutoffs, players with 1000+ rounds in both years."""
    last = int(M.gd.max())
    X, y, w = [], [], []
    d = dt.date(2024, 7, 1)
    while d.toordinal() + 365 <= last:
        T = d.toordinal()
        th, _ = ratings(M, c, T, p)
        _, r0 = window_stats(M, c, th, T - 365, T, p)
        thF, _ = ratings(M, c, T + 365, p)
        fut, r1 = window_stats(M, c, thF, T, T + 365, p)
        ag = ages(M, pdir, T)
        ok = (r0 >= 1000) & (r1 >= 1000) & ~np.isnan(ag) & (ag > 15) & (ag < 40)
        a = ag[ok] - 24
        X += list(np.column_stack([np.ones(ok.sum()), th[ok], a, a * a]))
        y += list(fut[ok])
        w += list(np.minimum(r1[ok], 3000))
        d = (d + dt.timedelta(days=92)).replace(day=1)
    X, y, w = np.array(X), np.array(y), np.array(w)
    b = ols(X, y, w)
    return {"b": [round(float(v), 5) for v in b], "n": int(len(y)),
            "peak": (round(24 - b[2] / (2 * b[3]), 1) if b[3] < 0 and 16 < 24 - b[2] / (2 * b[3]) < 40 else None)}


def project(th, age, ag, years=2):
    """Ratings for the next `years` seasons through the aging fit (age unknown: 24)."""
    b = ag["b"]
    out, x, a = [], th, (age if age == age and age else 24.0)
    for _ in range(years):
        x = b[0] + b[1] * x + b[2] * (a - 24) + b[3] * (a - 24) ** 2
        out.append(x)
        a += 1
    return out


def value(th, age, repl, ag, v, scale_a):
    """Transfer value (USD): sum over the next two seasons (15% a year discount) of A (exp(b E) - 1), E = round win %
    the player adds over a replacement-level player (scale_a x (rating - replacement) / 2)."""
    tot = 0.0
    for y, x in enumerate(project(th, age, ag)):
        e = max(0.0, scale_a * (x - repl) / 2)
        tot += 0.85 ** y * (math.exp(v["b"] * e) - 1)
    return v["A"] * tot


def fee_fit(M, c, p, pdir, ag, scale_a, bo3):
    """Fit A and b of value() on the reported fees: rating and age at the player's first map for the buying team."""
    fees = json.loads(FEES.read_text())["fees"] if FEES.exists() else []
    pts = []
    nk, _ = nick_index(M, bo3)
    for f in fees:
        pi = nk.get(names.key(f["nick"]))
        if pi is None:
            continue
        rows = np.where(M.p == pi)[0]
        to = key(f["to"])
        new = [i for i in rows if bo3.k(int(M.team[i])) == to]
        if not new:
            continue
        T = int(min(M.d[i] for i in new))
        th, _ = ratings(M, c, T, p)
        rr = window_stats(M, c, th, T - 365, T, p)[1]
        act = rr >= 1000
        if rr[pi] < 1000:  # no year of maps before the move (sh1ro moved before the stats start)
            continue
        repl = float(np.median(th[act]))
        age = ages(M, pdir, T)[pi]
        pts.append({"nick": f["nick"], "usd": f["usd"], "date": dt.date.fromordinal(T).isoformat(),
                    "th": round(float(th[pi]), 3), "age": None if age != age else round(float(age), 1),
                    "repl": round(repl, 3), "rounds": int(rr[pi])})
    best = None
    for b in np.arange(0.01, 3.01, 0.01):
        g = [sum(0.85 ** y * (math.exp(b * max(0, scale_a * (x - q["repl"]) / 2)) - 1)
                 for y, x in enumerate(project(q["th"], q["age"] or 24, ag))) for q in pts]
        if min(g) <= 0:
            continue
        la = np.mean([math.log(q["usd"]) - math.log(x) for q, x in zip(pts, g)])
        err = np.mean([(math.log(q["usd"]) - la - math.log(x)) ** 2 for q, x in zip(pts, g)])
        if best is None or err < best[0]:
            best = (err, float(b), float(math.exp(la)))
    if best is None:
        return None
    v = {"A": round(best[2]), "b": round(best[1], 2), "rmseLog": round(math.sqrt(best[0]), 3), "n": len(pts),
         "fx": round(math.exp(math.sqrt(best[0])), 2)}
    for q in pts:
        q["xtv"] = round(value(q["th"], q["age"] or 24, q["repl"], ag, v, scale_a))
    v["pts"] = pts
    return v


def fv_of(x, mu, sd):
    return int(min(80, max(20, round(50 + 10 * (x - mu) / sd))))


def build():
    fitj = json.loads(FIT.read_text())
    p = fitj["params"]
    M = Maps()
    beta = np.array([fitj["beta"][k] for k in STATS])
    c = contributions(M, beta, np.array(fitj["mline"]), p.get("pm", 0.0))
    today = dt.date.today()
    T = today.toordinal() + 1
    th, _ = ratings(M, c, T, p)
    th90, _ = ratings(M, c, T - 90, p)
    th6, _ = ratings(M, c, T - 182, p)
    _, r12 = window_stats(M, c, th, T - 365, T, p)
    m12 = np.bincount(M.p, M.d >= T - 365, len(M.pids))
    sm = s_maps(M, T)
    pdir = load_pdir()
    age = ages(M, pdir, T)
    bo3 = cs2_bo3.Bo3()
    cs = json.loads((ROOT / "data" / "cs2.json").read_text())
    tinfo = {t["k"]: t for t in cs["teams"]}
    tname = {}
    for r in sorted(bo3.mt.values(), key=lambda r: r[1]):
        tname[r[2]], tname[r[3]] = r[4], r[5]
    # latest map per player: team, date
    order = np.argsort(M.d, kind="stable")
    lastrow = {}
    for i in order:
        lastrow[M.p[i]] = i
    # per-round stat lines over the last year
    w12 = M.R * (M.d >= T - 365)
    agg = {k: np.bincount(M.p, w12 * M.X[:, j], len(M.pids)) / np.maximum(r12, 1) for j, k in enumerate(STATS)}
    act = (r12 >= 1000) & np.array([M.d[lastrow[i]] >= T - 120 if i in lastrow else False for i in range(len(M.pids))])
    repl = float(np.median(th[act]))
    a = p["a"]
    ag = fitj["aging"]
    v = fitj.get("value")
    t1 = [i for i in np.where(act)[0] if tinfo.get(bo3.k(int(M.team[lastrow[i]])), {}).get("tier") == 1]
    mu1, sd1 = float(np.mean(th[t1])), float(np.std(th[t1]) or 1)

    def row(i):
        pid = int(M.pids[i])
        d = pdir.get(str(pid)) or [None] * 6
        tid = int(M.team[lastrow[i]])
        tk = bo3.k(tid)
        ti = tinfo.get(tk, {})
        return {"id": pid, "n": M.nick.get(pid) or d[1], "slug": d[0], "nat": (d[3] or "").lower() or None,
                "ph": d[5], "age": None if age[i] != age[i] else round(float(age[i]), 1),
                "tm": ti.get("n") or tname.get(tid) or "", "tk": tk if ti else None, "trk": ti.get("rk"),
                "tier": ti.get("tier", 4), "logo": bool(ti.get("logo")),
                "rwa": round(float(a / 2 * (th[i] - mu1)), 2), "d90": round(float(a / 2 * (th[i] - th90[i])), 2),
                "rar": round(float(r12[i] * a * (th[i] - repl) / 200), 1), "maps": int(m12[i]), "sm": int(sm[i]),
                "kpr": round(float(agg["k"][i]), 3), "dpr": round(float(agg["d"][i]), 3),
                "adr": round(float(agg["adr"][i] * 100), 1), "kast": round(float(agg["kast"][i] * 100), 1),
                "ok": round(float((agg["fk"][i] - agg["fd"][i]) * 100), 1),
                "xtv": int(round(value(float(th[i]), age[i], repl, ag, v, a), -3)) if v else None,
                "last": dt.date.fromordinal(int(M.d[lastrow[i]])).isoformat()}
    pool = sorted(np.where(act)[0], key=lambda i: -th[i])
    board = [row(i) for i in pool[:400]]
    for k, r in enumerate(board):
        r["rk"] = k + 1
    # prospects: fewer than T1_MAPS S-tier maps; graded on the projected rating over the next year
    pf = fitj.get("prospects") or {}
    keep = (pf.get("models") or {}).get(pf.get("keep"), {"cols": ["th"], "b": [0, 1]})
    rw = (pf.get("reach") or {}).get("w")
    pros = []
    ss = sa_share(M, T)
    for i in pool:
        if sm[i] >= T1_MAPS:
            continue
        x = {"th": th[i], "rise": th[i] - th6[i], "age": (age[i] - 22) if age[i] == age[i] else 0.0, "ss": ss[i]}
        proj = keep["b"][0] + sum(b * x[k] for b, k in zip(keep["b"][1:], keep["cols"]))
        r = row(i)
        r["proj"] = round(float(a / 2 * (proj - mu1)), 2)
        r["fv"] = fv_of(proj, mu1, sd1)
        r["rise"] = round(float(a / 2 * (th[i] - th6[i])), 2)
        r["ss"] = round(float(ss[i]), 2)
        if rw:
            z = rw[0] + rw[1] * th[i] + rw[2] * (th[i] - th6[i]) + (rw[3] * ss[i] if len(rw) > 3 else 0.0)
            r["t1p"] = round(float(1 / (1 + math.exp(-z))), 3)
        pros.append(r)
    pros.sort(key=lambda r: (-r["proj"], -r.get("t1p", 0)))
    pros = pros[:200]
    for k, r in enumerate(pros):
        r["rk"] = k + 1
    out = {"asof": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "first": dt.date.fromordinal(int(M.gd.min())).isoformat(), "nMaps": len(M.games), "nPool": int(act.sum()),
           "repl": round(a / 2 * (repl - mu1), 2), "t1sd": round(a / 2 * sd1, 2), "board": board, "prospects": pros,
           "fit": {k: fitj.get(k) for k in ("beta", "r2", "params", "score", "tune", "held", "aging", "game")}}
    out["fit"]["prospects"] = {k: pf.get(k) for k in ("models", "keep", "reach", "cuts", "nTune")}
    out["fit"]["value"] = v
    OUT.write_text(json.dumps(out, separators=(",", ":"), allow_nan=False))
    print(f"players: {len(board)} board, {len(pros)} prospects; #1 {board[0]['n']}")


if __name__ == "__main__":
    if "--fit" in sys.argv:
        fit()
    else:
        build()
