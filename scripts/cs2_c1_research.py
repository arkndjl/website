#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pre-registered test: staleness-scaled rating uncertainty in the Counter-Strike event sims.

    python3 scripts/cs2_c1_research.py --prep   # pre-stage logits, staleness, changed five -> scripts/.cache/cs2_c1.pkl
    python3 scripts/cs2_c1_research.py --tune   # the grid on tune stages; picks (a, b)
    python3 scripts/cs2_c1_research.py --held   # scores the pick once on held stages -> data/cs2_c1_research.json

Per team sd = SD0 x (1 + a x stale) + b x changed, against the flat SD0 the live sims use. stale = days since the
team's last series / 30, capped 3; changed = the five listed for the stage differs from the five of its last series.
Score: Brier summed over a stage's teams (Swiss advancement, bracket title), summed per event, t over events.
"""
import datetime as dt
import gzip
import json
import math
import pickle
import random
import sys
import time
from collections import defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_events as E  # noqa: E402
from cs2_data import key  # noqa: E402
from cs2_swiss import bracket, swiss  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PKL = ROOT / "scripts" / ".cache" / "cs2_c1.pkl"
OUT = ROOT / "data" / "cs2_c1_research.json"
SD0 = 0.60
A_GRID, B_GRID = (0.0, 0.25, 0.5, 1.0), (0.0, 0.15, 0.3)
SPLIT, LOCK, FIRST = "2025-07-01", "2026-11-10", "2024-10-01"
N_TUNE, N_HELD = 4000, 10000


def prep():
    import cs2_model as M
    import cs2_players
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[0] <= LOCK]
    vrs = M.Vrs(H["vrs"])
    p = json.loads(M.FIT.read_text())["params"]
    bo3 = cs2_bo3.Bo3()
    ss = [s for s in E.stages() if FIRST <= s["date"] <= LOCK]
    dates = sorted({s["date"] for s in ss})
    t0 = time.time()
    rows, st = M.replay(series, vrs, p, bo3=bo3, snaps=dates)
    tm = cs2_bo3.TeamMaps(bo3)
    tm.play(snaps=dates)
    live = cs2_players.Live(bo3)
    rows = [r for r in rows if r["d"] >= "2024-08-07"]
    for r in rows:
        r["z"] = live.z(r["r"][4], r["a"], r["r"][5], r["b"], r["d"]) if live.w else 0.0
    by_team = defaultdict(list)                     # team key -> [(date, five or None)] in date order
    for r in series:
        by_team[key(r[1])].append((r[0], r[4]))
        by_team[key(r[2])].append((r[0], r[5]))
    print(f"replay {time.time() - t0:.0f}s, {len(ss)} stages")
    cols = (0, 1, 2, 3)
    out = []
    for s in ss:
        d = s["date"]
        tr = [r for r in rows if r["d"] < d]
        w = {}
        for tier in (True, False):
            rr = [r for r in tr if r["top"] == tier]
            X = np.array([[(r["x"], r["v"], r["t"], r["z"])[c] for c in cols] for r in rr])
            w["top" if tier else "rest"] = list(M.fitlog(X, np.array([r["s"] for r in rr])))
        mdl = E.Model(M, p, st["snaps"][d], vrs, tm.snaps[d], live, bo3, w, d, cols)
        mdl.names = s["names"]
        ks = {t: bo3.k(t) or key(s["names"][t]) for t in s["teams"]}
        seeds = sorted(s["teams"], key=lambda t: (v[0] if (v := vrs.get(ks[t], d)) else 999))
        bos = (1, 3, 5)
        lg = {(a, b, bo): mdl.logit(a, b, bo) for a in s["teams"] for b in s["teams"] if a != b for bo in bos}
        d0 = dt.date.fromisoformat(d)
        stale, chg, days = {}, {}, {}
        for t in s["teams"]:
            hist = by_team.get(ks[t], [])
            before = [x for x in hist if x[0] < d]
            days[t] = (d0 - dt.date.fromisoformat(before[-1][0])).days if before else None
            stale[t] = min(days[t] / 30, 3.0) if before else 3.0
            lastros = st["snaps"][d]["lastros"].get(ks[t])
            nxt = next((x[1] for x in hist if x[0] >= d and x[1]
                        and (dt.date.fromisoformat(x[0]) - d0).days <= 21), None)
            chg[t] = int(bool(lastros and nxt and set(lastros) != set(nxt)))
        out.append({"event": s["event"], "tid": s["tid"], "kind": s["kind"], "date": d, "teams": s["teams"],
                    "seeds": seeds, "r1": s.get("r1"), "allbo3": s.get("allbo3"), "adv": s.get("adv"),
                    "tree": s.get("tree"), "champ": s.get("champ"), "logit": lg, "stale": stale, "chg": chg, "days": days})
    PKL.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump(out, PKL.open("wb"))
    al = [v for s in out for v in s["stale"].values()]
    print("stages", len(out), "mean stale", round(float(np.mean(al)), 3), "p90", round(float(np.quantile(al, .9)), 3),
          "changed share", round(float(np.mean([v for s in out for v in s["chg"].values()])), 3),
          "no history", sum(v is None for s in out for v in s["days"].values()))


def run(args):
    """One stage, one (a, b): -> (Brier sum, log loss)."""
    s, a, b, n, seed = args
    rng = random.Random(seed)
    lg = s["logit"]
    sd = {t: SD0 * (1 + a * s["stale"][t]) + b * s["chg"][t] for t in s["teams"]}
    cnt = defaultdict(int)
    order = s["seeds"]

    def draw():
        e = {t: rng.gauss(0, sd[t]) for t in order}
        return lambda x, y, bo: 1 / (1 + math.exp(-(lg[(x, y, bo)] + e[x] - e[y])))
    if s["kind"] == "swiss":
        known = [[(x, y, None) for x, y in s["r1"]]]
        for _ in range(n):
            W, _, _ = swiss(order, draw(), rng, known, s["allbo3"])
            for t in order:
                cnt[t] += W[t] == 3
        P = {t: cnt[t] / n for t in order}
        ys = {t: int(t in s["adv"]) for t in order}
        return sum((P[t] - ys[t]) ** 2 for t in order), sum(E.ll(P[t], ys[t]) for t in order)
    for _ in range(n):
        cnt[bracket(s["tree"], draw(), rng)[0]] += 1
    P = {t: cnt[t] / n for t in s["teams"]}
    return sum((P[t] - (t == s["champ"])) ** 2 for t in P), -math.log(max(P[s["champ"]], 1e-4))


def by_event(ss, vals, kind=None):
    ev = defaultdict(float)
    for s, v in zip(ss, vals):
        if kind is None or s["kind"] == kind:
            ev[s["tid"]] += v
    return ev


def paired(ss, cand, base, kind=None, j=0):
    c, b0 = by_event(ss, [x[j] for x in cand], kind), by_event(ss, [x[j] for x in base], kind)
    d = np.array([c[k] - b0[k] for k in sorted(b0)])
    t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 1 and d.std() > 0 else None
    return {"n": len(d), "d": round(float(d.mean()), 5), "t": None if t is None else round(t, 2),
            "won": int((d < 0).sum()), "cand": round(float(np.mean(list(c.values()))), 4),
            "live": round(float(np.mean(list(b0.values()))), 4)}


def score(ss, cells, n, seed0):
    jobs = [(s, a, b, n, seed0 + i) for a, b in cells for i, s in enumerate(ss)]
    with Pool(4) as pool:
        res = pool.map(run, jobs, chunksize=4)
    return {c: res[i * len(ss):(i + 1) * len(ss)] for i, c in enumerate(cells)}


def main():
    if "--prep" in sys.argv:
        return prep()
    ss = pickle.load(PKL.open("rb"))
    assert all(FIRST <= s["date"] <= LOCK for s in ss)
    tune = [s for s in ss if s["date"] < SPLIT]
    held = [s for s in ss if s["date"] >= SPLIT]
    out = json.loads(OUT.read_text()) if OUT.exists() else {}
    if "--tune" in sys.argv:
        cells = [(a, b) for a in A_GRID for b in B_GRID]
        t0 = time.time()
        r = score(tune, cells, N_TUNE, 1000)
        grid = {f"{a} {b}": round(sum(x[0] for x in r[(a, b)]), 4) for a, b in cells}
        best = min(cells, key=lambda c: sum(x[0] for x in r[c]))
        out = {"sd0": SD0, "split": SPLIT, "lock": LOCK, "nTune": N_TUNE, "nHeld": N_HELD,
               "stages": {"tune": len(tune), "held": len(held)}, "grid": grid, "pick": {"a": best[0], "b": best[1]},
               "tune": {"all": paired(tune, r[best], r[(0.0, 0.0)]), "swiss": paired(tune, r[best], r[(0.0, 0.0)], "swiss"),
                        "se": paired(tune, r[best], r[(0.0, 0.0)], "se"),
                        "ll": paired(tune, r[best], r[(0.0, 0.0)], None, 1)}}
        print(f"tune {time.time() - t0:.0f}s", json.dumps(out, indent=1))
        OUT.write_text(json.dumps(out, indent=1) + "\n")
    elif "--held" in sys.argv:
        best = (out["pick"]["a"], out["pick"]["b"])
        if best == (0.0, 0.0):
            out["pass"] = False
            out["verdict"] = "FAIL: the tune grid picked the flat sd"
        else:
            r = score(held, [(0.0, 0.0), best], N_HELD, 5000)
            out["held"] = {"all": paired(held, r[best], r[(0.0, 0.0)]), "swiss": paired(held, r[best], r[(0.0, 0.0)], "swiss"),
                           "se": paired(held, r[best], r[(0.0, 0.0)], "se"),
                           "ll": paired(held, r[best], r[(0.0, 0.0)], None, 1)}
            th, tt = out["held"]["all"]["t"], out["tune"]["all"]["t"]
            out["pass"] = bool(th is not None and tt is not None and th <= -1.645 and tt < 0)
            out["verdict"] = "PASS" if out["pass"] else "FAIL"
        print(json.dumps(out, indent=1))
        OUT.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
