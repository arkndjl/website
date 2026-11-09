# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Study: NBA 2-for-1.

Sample: quarters 1-3, the first possession of each quarter that starts with 25-40 s left (team A).
Decision: seconds A uses before its first shot / turnover / trip to the line (quick <= 10 s, full > 10 s).
Outcome: A's points minus opponent's points from possession start to the end of the quarter.
Selection: transition shots are quick by nature, so the main comparison uses possessions that start
from a dead ball after an opponent score (inbound), stratified by start-time bin. CIs: bootstrap.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bball_common as bc
from poss import possession_after

QUICK = 10.0


def episodes():
    ev = bc.load("nba")
    games = bc.game_table(ev, "nba")
    sub = ev[(ev.period <= 3) & (ev.sec <= 60) & ev.game_id.isin(games.index)]
    rows = []
    for (gid, per), g in sub.groupby(["game_id", "period"], sort=False):
        kinds = g["kind"].astype(str).tolist()
        if "endp" not in kinds:
            continue
        teams = g["team"].tolist(); made = g["made"].tolist(); subs = g["sub"].astype(str).tolist()
        secs = g["sec"].tolist(); hs = g["hs"].tolist(); as_ = g["as_"].tolist()
        home, away = int(g.home.iloc[0]), int(g.away.iloc[0])
        pos, lastft = possession_after(kinds, teams, made, subs, home, away)
        e = kinds.index("endp")
        fh, fa = hs[e], as_[e]
        for i in range(e):
            A = pos[i]
            if A is None or (i > 0 and pos[i - 1] == A) or not (25 <= secs[i] <= 40):
                continue
            k = kinds[i]
            start = ("dead" if (k in ("shot", "ft") and teams[i] != A) else
                     "dreb" if k in ("dreb", "dbreb") else
                     "tov" if k in ("tov", "steal") else "other")
            t_end = None
            for j in range(i + 1, e + 1):
                if kinds[j] in ("shot", "tov", "ft") and teams[j] == A:
                    t_end = secs[j]
                    break
                if kinds[j] == "endp":
                    break
            if t_end is None:
                break
            sign = 1 if A == home else -1
            net = sign * ((fh - fa) - (hs[i] - as_[i]))
            ptsA = (fh - hs[i]) if A == home else (fa - as_[i])
            ptsB = (fa - as_[i]) if A == home else (fh - hs[i])
            # possessions after: count A shots/tov/ft-trips vs B to see who got the last one
            rows.append(dict(game_id=gid, season=int(g.season.iloc[0]), period=per, t0=float(secs[i]),
                             used=float(secs[i] - t_end), t_end=float(t_end), start=start,
                             net=net, ptsA=ptsA, ptsB=ptsB))
            break
    return pd.DataFrame(rows)


def strat(df, B=2000, seed=5):
    """Quick minus full, within t0 bins (5 s), weighted by quick counts; game-cluster bootstrap (vectorized)."""
    df = df.copy()
    df["tb"] = pd.cut(df.t0, [24.9, 30, 35, 40.1], labels=False)
    df["cell"] = df.tb * 2 + df.quick.astype(int)
    gids, gidx = np.unique(df.game_id.to_numpy(), return_inverse=True)
    G = len(gids)
    S = np.zeros((G, 6)); C = np.zeros((G, 6))
    np.add.at(S, (gidx, df.cell.to_numpy()), df.net.to_numpy())
    np.add.at(C, (gidx, df.cell.to_numpy()), 1)
    def est(Ss, Cs):
        tot, w = 0.0, 0.0
        for b in range(3):
            nq, nf = Cs[2 * b + 1], Cs[2 * b]
            if nq > 0 and nf > 0:
                tot += nq * (Ss[2 * b + 1] / nq - Ss[2 * b] / nf); w += nq
        return tot / w
    point = est(S.sum(0), C.sum(0))
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(B):
        wts = np.bincount(rng.integers(0, G, G), minlength=G)
        bs.append(est(wts @ S, wts @ C))
    return float(point), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


if __name__ == "__main__":
    path = os.path.join(bc.SCRATCH, "two_for_one.csv")
    df = pd.read_csv(path) if os.path.exists(path) and "--fresh" not in sys.argv else episodes()
    df.to_csv(path, index=False)
    df["quick"] = df.used <= QUICK
    print(len(df), df.start.value_counts().to_dict())
    print(df.groupby(["start", "quick"]).agg(n=("net", "size"), net=("net", "mean"), A=("ptsA", "mean"), B=("ptsB", "mean")))
    dead = df[df.start == "dead"]
    # chart: net by seconds used, dead-ball starts
    bins = [0, 4, 6, 8, 10, 12, 14, 16, 18, 20, 40]
    dead = dead.assign(ub=pd.cut(dead.used, bins, right=True, include_lowest=True))
    pts = []
    for b, s in dead.groupby("ub", observed=True):
        m, lo, hi = bc.boot_mean(s.net.to_numpy())
        pts.append(dict(x=float(round((b.left + min(b.right, 24)) / 2, 1)), y=bc.r3(m), lo=bc.r3(lo), hi=bc.r3(hi), n=int(len(s))))
        print(b, len(s), round(m, 3), round(lo, 3), round(hi, 3), round(s.ptsA.mean(), 2), round(s.ptsB.mean(), 2))
    q, f = dead[dead.quick], dead[~dead.quick]
    qm = bc.boot_mean(q.net, q.game_id); fm = bc.boot_mean(f.net, f.game_id)
    qa = bc.boot_mean(q.ptsA, q.game_id); fa = bc.boot_mean(f.ptsA, f.game_id)
    qb = bc.boot_mean(q.ptsB, q.game_id); fb = bc.boot_mean(f.ptsB, f.game_id)
    sd = strat(dead)
    sd_all = strat(df)
    early = dead.season <= 2019
    sde, sdl = strat(dead[early], B=800), strat(dead[~early], B=800)
    print("quick", qm, qa, qb, "full", fm, fa, fb, "strat", sd, "all starts", sd_all, "split", sde, sdl)
    robust = (sd[1] > 0 or sd[2] < 0) and ((sde[0] > 0) == (sdl[0] > 0))
    out = {
        "id": "nba-two-for-one",
        "sport": "NBA",
        "question": "With 25-40 seconds left in a quarter, does a quick shot for a 2-for-1 pay?",
        "answer": (f"{'Yes' if sd[0] > 0 and robust else 'Small edge'}: quick shot nets {sd[0]:+.2f} pts per quarter-end vs a full possession "
                   f"(CI {sd[1]:+.2f} to {sd[2]:+.2f})."),
        "findings": [
            f"Quick (<=10 s): net {qm[0]:+.2f} pts to quarter end (CI {qm[1]:+.2f} to {qm[2]:+.2f}), n={len(q)}.",
            f"Full (>10 s): net {fm[0]:+.2f} pts (CI {fm[1]:+.2f} to {fm[2]:+.2f}), n={len(f)}.",
            f"Points for/against: quick {qa[0]:.2f}/{qb[0]:.2f}, full {fa[0]:.2f}/{fb[0]:.2f}.",
            f"All start types (incl. transition): quick minus full {sd_all[0]:+.2f} pts (CI {sd_all[1]:+.2f} to {sd_all[2]:+.2f}), n={len(df)}.",
        ],
        "method": ("Q1-Q3, first possession starting 25-40 s left. Outcome = own minus opponent points to quarter end. "
                   "Main sample = inbound after opponent score (no transition); quick vs full compared within 5 s start-time bins, game-clustered bootstrap."),
        "data": f"ESPN play-by-play via sportsdataverse, NBA 2011-12 to 2025-26, {df.game_id.nunique():,} games, {len(dead):,} inbound possessions.",
        "n": int(len(dead)),
        "robust": bool(robust),
        "interest": 3,
        "split_check": f"Quick minus full: {sde[0]:+.2f} pts in 2012-19 (CI {sde[1]:+.2f} to {sde[2]:+.2f}), {sdl[0]:+.2f} in 2020-26 (CI {sdl[1]:+.2f} to {sdl[2]:+.2f}).",
        "chart": {
            "type": "line",
            "title": "Net points to quarter end by seconds used, inbound possessions 25-40 s left",
            "x_label": "seconds used before first shot", "y_label": "net points (own minus opponent)",
            "y_fmt": "signed", "x_reverse": False,
            "ref": {"y": 0, "label": "even"}, "mark": {"x": QUICK, "label": "10 s"},
            "series": [{"name": "inbound after opponent score", "points": pts}],
        },
    }
    print(out["answer"]); print("\n".join(out["findings"])); print(out["split_check"])
    bc.write_json(out, out["id"])
