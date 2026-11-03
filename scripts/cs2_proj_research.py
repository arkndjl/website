#!/usr/bin/env python3
"""Research + fit (Nov 3 2026): a 6-month RWA projection for the Counter-Strike players board (scripts/cs2_players.py).

    python3 scripts/cs2_proj_research.py      # numpy; writes data/cs2_proj_fit.json (~2 min)

Rows: the board pool at the first of every month 2024-07 on (1,000+ rounds in the last year, a map in the last 120 days,
the board's own rule), each player's rating th at that day (cs2_players.ratings with the live fit settings, so a row
is exactly the RWA the board showed then, before the a / 2 scale) minus the pool mean that day.
Target: the same player's rating 182 days later minus that day's pool mean, players still in the pool (survivors).
Nothing after the cut enters a row; the target's ratings use only maps before T + 182.
Forms (4 tried):
    flat   the rating held flat
    rate   c0 + c1 x (regression to the mean)
    age    rate + (age - 24) + (age - 24) ** 2 (unknown age: 24 and a flag)
    proj   age + ln(maps last year) + S/A-tier round share last year
Split by time: fit on cuts whose target day falls before HELD (2025-07-01, the players fit's own held window), score
the cuts from HELD on. Paired t of squared error with PLAYERS as units (a player's held rows averaged), months won,
held calibration slope. Kept: the simplest form that beats flat with t <= -2, most months and slope .8-1.2; a richer
form replaces it only if it beats the simpler one the same way.
Results (Nov 3 2026; 23 cuts Jul 2024 - May 2026, 4,771 train rows, 9,685 held rows, 1,255 held players), held RMSE on
the board's RWA scale: flat .507, rate .496 (t -.06 vs flat), age .485 (t -2.41, 9/11 months, slope 1.02; vs rate t
-7.4, 11/11), proj .492 (vs age t +5.0, 0/11: maps and S/A share hurt, the ratings already carry the tier lift).
Kept: age. The live board's 6M column uses cLive (the age form refit on every row with a target). The monthly
cs2.yml refit reruns this with the same held start, so the gate keeps scoring new months.
"""
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_players as CP  # noqa: E402

OUT = CP.ROOT / "data" / "cs2_proj_fit.json"
H = 182
HELD = "2025-07-01"
FORMS = ("flat", "rate", "age", "proj")


def design(form, A):
    one = np.ones(len(A["x"]))
    a = A["age"] - 24
    c = {"rate": [A["x"]], "age": [A["x"], a, a * a, A["noage"]],
         "proj": [A["x"], a, a * a, A["noage"], np.log(np.maximum(A["m12"], 1)), A["ss"]]}[form]
    return np.column_stack([one] + c)


def pool(M, c, p, T):
    th, _ = CP.ratings(M, c, T, p)
    _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
    last = np.full(len(M.pids), -10 ** 9)
    np.maximum.at(last, M.p, np.where(M.d < T, M.d, -10 ** 9))
    act = (r12 >= 1000) & (last >= T - 120)
    return th, act


def paired(e1, e0, pid):
    g = defaultdict(list)
    for v, q in zip(e1 - e0, pid):
        g[q].append(v)
    d = np.array([np.mean(v) for v in g.values()])
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), len(d)


def main():
    fitj = json.loads(CP.FIT.read_text())
    p = fitj["params"]
    M = CP.Maps()
    beta = np.array([fitj["beta"][k] for k in CP.STATS])
    c = CP.contributions(M, beta, np.array(fitj["mline"]), p.get("pm", 0.0))
    pdir = CP.load_pdir()
    last = int(M.gd.max())
    cuts, d = [], dt.date(2024, 7, 1)
    while d.toordinal() + H <= last:
        cuts.append(d.toordinal())
        d = (d + dt.timedelta(days=32)).replace(day=1)
    cache = {}

    def at(T):
        if T not in cache:
            cache[T] = pool(M, c, p, T)
        return cache[T]
    rows = defaultdict(list)
    for T in cuts:
        th, act = at(T)
        thF, actF = at(T + H)
        mu, muF = th[act].mean(), thF[actF].mean()
        i = np.where(act & actF)[0]
        ag = CP.ages(M, pdir, T)[i]
        m12 = np.bincount(M.p, (M.d >= T - 365) & (M.d < T), len(M.pids))[i]
        ss = CP.sa_share(M, T)[i]
        for k, v in (("T", np.full(len(i), T)), ("pid", M.pids[i]), ("x", th[i] - mu), ("y", thF[i] - muF),
                     ("age", np.where(np.isnan(ag), 24.0, ag)), ("noage", np.isnan(ag).astype(float)), ("m12", m12),
                     ("ss", ss)):
            rows[k].append(v)
        print(dt.date.fromordinal(T), len(i), "of", int(act.sum()), file=sys.stderr)
    A = {k: np.concatenate(v) for k, v in rows.items()}
    held_T = CP.ordd(HELD)
    tr = A["T"] + H <= held_T
    te = A["T"] >= held_T
    y = A["y"]
    pr = {"flat": A["x"][te]}
    coef = {}
    for f in FORMS[1:]:
        X = design(f, A)
        b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]
        pr[f] = X[te] @ b
        coef[f] = [round(float(v), 5) for v in b]
    yt, pid, Tt = y[te], A["pid"][te], A["T"][te]
    e = {f: (pr[f] - yt) ** 2 for f in FORMS}
    a = p["a"] / 2                                  # board scale: RWA = a / 2 x rating
    res = {"h": H, "held": HELD, "cuts": [dt.date.fromordinal(cuts[0]).isoformat(), dt.date.fromordinal(cuts[-1]).isoformat()],
           "nTrain": int(tr.sum()), "nHeld": int(te.sum()), "playersHeld": int(len(set(pid))),
           "rmseRWA": {f: round(float(a * np.sqrt(e[f].mean())), 4) for f in FORMS},
           "slope": {f: round(float(np.polyfit(pr[f], yt, 1)[0]), 3) for f in FORMS}, "c": coef, "vs": {}}
    for f, g in (("rate", "flat"), ("age", "flat"), ("proj", "flat"), ("age", "rate"), ("proj", "age")):
        t, npl = paired(e[f], e[g], pid)
        mw = [int(e[f][Tt == T].mean() < e[g][Tt == T].mean()) for T in np.unique(Tt)]
        res["vs"][f"{f}-{g}"] = {"t": round(t, 2), "monthsWon": [sum(mw), len(mw)], "players": npl}
    ok = lambda k: res["vs"][k]["t"] <= -2 and 2 * res["vs"][k]["monthsWon"][0] > res["vs"][k]["monthsWon"][1]
    kept = None
    for f, step in (("rate", None), ("age", "age-rate"), ("proj", "proj-age")):
        if ok(f"{f}-flat") and 0.8 <= res["slope"][f] <= 1.2 and (kept is None or ok(step)):
            kept = f
    res["keep"] = kept
    # the final coefficients: every row with a target (train + held), for the live board
    if kept:
        X = design(kept, A)
        res["cLive"] = [round(float(v), 5) for v in np.linalg.lstsq(X, y, rcond=None)[0]]
    print(json.dumps(res, indent=1))
    OUT.write_text(json.dumps(res, indent=1, allow_nan=False))


if __name__ == "__main__":
    main()
