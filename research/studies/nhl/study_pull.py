"""Goalie-pull study: rates with CIs, Markov optimum with game-cluster bootstrap, actual pull times, validation.
usage: python3 -I study_pull.py <scratch_dir> <out_dir>"""
import json, math, os, pickle, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pullmodel import solve

S, OUT = sys.argv[1], sys.argv[2]
T = pickle.load(open(os.path.join(S, "tables.pkl"), "rb"))
G = len(T["games"])
seasons = np.array([s for _, s in T["games"]])
KEYS = sorted({k for _, acc in T["expo"] for k in acc})
E = {k: np.zeros((G, 3)) for k in KEYS}
for gi, acc in T["expo"]:
    for k, v in acc.items(): E[k][gi] = v

def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"),) * 3
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h

def rates(w=None, mask=None):
    """per-60 rates from game weights"""
    w = np.ones(G) if w is None else w
    if mask is not None: w = w * mask
    tot = {k: (w[:, None] * E[k]).sum(0) for k in KEYS}
    r = lambda k, i: tot[k][i] / tot[k][0] * 3600 if tot[k][0] > 0 else 0
    t = tot["tied"]
    return dict(r0=(t[1] + t[2]) / 2 / t[0] * 3600,
                a5={1: r("5v5_d1", 1), 2: r("5v5_d2", 1)}, b5={1: r("5v5_d1", 2), 2: r("5v5_d2", 2)},
                a6={1: r("6v5_d1", 1), 2: r("6v5_d2", 1)}, b6={1: r("6v5_d1", 2), 2: r("6v5_d2", 2)},
                a54={1: r("5v4_d1", 1), 2: r("5v4_d2", 1)}, b54={1: r("5v4_d1", 2), 2: r("5v4_d2", 2)}), tot

def rate_ci(k, i):
    """rate per 60 with game-cluster bootstrap CI (computed later); return point, goals, minutes"""
    tot = E[k].sum(0)
    return tot[i] / tot[0] * 3600, int(tot[i]), tot[0] / 60

START = 600
GRID = [x * 30 for x in range(0, 15)]   # 0:00 .. 7:00
def curves(R):
    V1 = [solve(R, START, tau={1: t})[0][START, 1] for t in GRID]
    V2 = [solve(R, START, tau={2: t})[0][START, 2] for t in GRID]
    _, best = solve(R, START)
    return np.array(V1), np.array(V2), best[1], best[2]

R0, tot0 = rates()
c1, c2, o1, o2 = curves(R0)
rng = np.random.default_rng(7)
B = 400
boot = dict(c1=[], c2=[], o1=[], o2=[], r={})
for b in range(B):
    w = rng.poisson(1.0, G).astype(float)
    Rb, _ = rates(w)
    x1, x2, b1, b2 = curves(Rb)
    boot["c1"].append(x1); boot["c2"].append(x2); boot["o1"].append(b1); boot["o2"].append(b2)
    for nm in ("a5", "b5", "a6", "b6"):
        for d in (1, 2): boot["r"].setdefault(f"{nm}{d}", []).append(Rb[nm][d])
    boot["r"].setdefault("r0", []).append(Rb["r0"])
q = lambda a: (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))

# split check: season halves (2021-22+2022-23 vs 2023-24+2024-25)
splits = {}
for nm, m in (("early", seasons <= 20222023), ("late", seasons >= 20232024)):
    Rs, _ = rates(mask=m.astype(float)); _, _, s1, s2 = curves(Rs); splits[nm] = (s1, s2)

# ---- actual pull times (first non-delayed-penalty spell while trailing at even strength, last 10 min)
P = [p for p in T["pulls"] if "s0" in p]
C = [p for p in T["pulls"] if "checkpoint" in p]
first = {}
for p in sorted(P, key=lambda p: p["s0"]):
    if p["dpe"] or not p["shifts"]: continue
    k = (p["gi"], p["home"], p["d"])
    if k not in first: first[k] = p
fp = list(first.values())
def pulltimes(d, season=None):
    xs = [p["tl"] for p in fp if p["d"] == d and p["Tsk"] == 6 and p["Osk"] == 5 and (season is None or p["season"] == season)]
    return np.array(xs)
act = {}
for d in (1, 2):
    xs = pulltimes(d)
    bm = [np.median(rng.choice(xs, len(xs))) for _ in range(1000)]
    act[d] = dict(median=float(np.median(xs)), n=len(xs), ci=q(bm), q25=float(np.percentile(xs, 25)), q75=float(np.percentile(xs, 75)),
                  by_season={int(s): float(np.median(pulltimes(d, s))) for s in sorted(set(seasons))})
    act[d]["share_at_or_before_opt"] = float(np.mean(xs >= (o1 if d == 1 else o2)))

# value of optimum vs actual median policy (from START, down d)
def val(R, d, t):
    return solve(R, START, tau={d: t})[0][START, d]
gain = {}
for d, o in ((1, o1), (2, o2)):
    am = int(round(act[d]["median"]))
    g0 = val(R0, d, o) - val(R0, d, am)
    gb = []
    rng2 = np.random.default_rng(11)
    for b in range(200):
        w = rng2.poisson(1.0, G).astype(float); Rb, _ = rates(w)
        _, bb = solve(Rb, START)
        gb.append(val(Rb, d, bb[d]) - val(Rb, d, am))
    gain[d] = (g0, q(gb), am)

# ---- validation 1: teams down d at 6:00 left at 5v5 with both goalies in: observed P(level at 60:00) vs model with actual median pull times
val_rows = []
for d in (1, 2):
    cs = [c for c in C if c["checkpoint"] == 360 and c["d"] == d and c["Tg"] and c["Og"] and c["Tsk"] == 5 and c["Osk"] == 5]
    k = sum(c["level"] for c in cs)
    tau = {1: int(round(act[1]["median"])), 2: int(round(act[2]["median"]))}
    pred = solve(R0, 360, tau=tau)[0][360, d]
    val_rows.append((d, k, len(cs), wilson(k, len(cs)), pred))
# ---- validation 2: actual first pulls down 1 at even strength, by pull-time bin: observed vs model (pulled from then on)
bins = [(0, 60), (60, 90), (90, 120), (120, 150), (150, 600)]
vb = []
for lo, hi in bins:
    ps = [p for p in fp if p["d"] == 1 and p["Tsk"] == 6 and p["Osk"] == 5 and lo <= p["tl"] < hi]
    if not ps: continue
    k = sum(p["level"] for p in ps)
    pred = np.mean([solve(R0, p["tl"], tau={1: 10**6, 2: 10**6, 3: 10**6, 4: 10**6})[0][p["tl"], 1] for p in ps[:1]] )
    # exact: average model value over each pull's own time
    preds = {}
    for p in ps:
        t = p["tl"]
        if t not in preds: preds[t] = solve(R0, t, tau={1: 10**6, 2: 10**6, 3: 10**6, 4: 10**6})[0][t, 1]
    pred = float(np.mean([preds[p["tl"]] for p in ps]))
    vb.append(dict(bin=f"{lo//60}:{lo%60:02d}-{hi//60}:{hi%60:02d}", n=len(ps), obs=wilson(k, len(ps)), pred=pred))

res = dict(rates=R0, rate_ci={k: q(v) for k, v in boot["r"].items()},
           expo={k: dict(min=float(tot0[k][0] / 60), gf=int(tot0[k][1]), ga=int(tot0[k][2])) for k in KEYS},
           opt1=o1, opt1_ci=q(boot["o1"]), opt2=o2, opt2_ci=q(boot["o2"]), splits=splits,
           curve1=c1.tolist(), curve2=c2.tolist(),
           curve1_ci=[q(np.array(boot["c1"])[:, i]) for i in range(len(GRID))],
           curve2_ci=[q(np.array(boot["c2"])[:, i]) for i in range(len(GRID))],
           actual=act, gain=gain, val_checkpoint=val_rows, val_bins=vb, n_games=G, n_shift=T["n_shift"])
json.dump(res, open(os.path.join(S, "pull_results.json"), "w"), indent=1, default=float)
print(json.dumps(res, indent=1, default=float)[:6000])
