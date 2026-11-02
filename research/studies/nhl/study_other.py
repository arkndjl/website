"""Secondary NHL studies: power-play pull (6v4 vs 5v4), pull on offensive-zone faceoff, score effects.
usage: python3 -I study_other.py <scratch_dir>"""
import json, math, os, pickle, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pullmodel import solve

S = sys.argv[1]
T = pickle.load(open(os.path.join(S, "tables.pkl"), "rb"))
G = len(T["games"]); seasons = np.array([s for _, s in T["games"]])
KEYS = sorted({k for _, acc in T["expo"] for k in acc})
E = {k: np.zeros((G, 3)) for k in KEYS}
for gi, acc in T["expo"]:
    for k, v in acc.items(): E[k][gi] = v
rng = np.random.default_rng(3)
q = lambda a: (float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5)))
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h

def rates(w):
    tot = {k: (w[:, None] * E[k]).sum(0) for k in KEYS}
    r = lambda ks, i: sum(tot[k][i] for k in ks) / sum(tot[k][0] for k in ks) * 3600
    t = tot["tied"]
    R = dict(r0=(t[1] + t[2]) / 2 / t[0] * 3600,
             a5={1: r(["5v5_d1"], 1), 2: r(["5v5_d2"], 1)}, b5={1: r(["5v5_d1"], 2), 2: r(["5v5_d2"], 2)},
             a6={1: r(["6v5_d1"], 1), 2: r(["6v5_d2"], 1)}, b6={1: r(["6v5_d1"], 2), 2: r(["6v5_d2"], 2)})
    pp = dict(a54=r(["5v4_d1", "5v4_d2", "5v4_d3"], 1), b54=r(["5v4_d1", "5v4_d2", "5v4_d3"], 2),
              a64=r(["6v4_d1", "6v4_d2", "6v4_d3"], 1), b64=r(["6v4_d1", "6v4_d2", "6v4_d3"], 2))
    return R, pp

def pp_value(R, pp, s, pull, d=1, plen=120):
    """P(level at 60:00): down d, s seconds left, a 2:00 minor starts now. pull: 6v4 during PP, else 5v4.
    After the PP (or a PP goal) play continues under the optimal even-strength policy."""
    V, _ = solve(R, s)
    a, b = (pp["a64"], pp["b64"]) if pull else (pp["a54"], pp["b54"])
    a, b = a / 3600, b / 3600
    L = min(plen, s)
    # W[j][dd]: value with j PP seconds elapsed, deficit dd; iterate backwards over PP time
    W = {dd: V[s - L, dd] for dd in range(0, 5)}
    for j in range(L - 1, -1, -1):
        rem = s - j - 1     # seconds left after this second
        Wn = {}
        for dd in range(0, 5):
            if dd == 0:
                Wn[0] = V[s - j, 0]; continue
            win = V[rem, dd - 1]          # PP goal ends the minor
            lose = W[min(dd + 1, 4)]
            Wn[dd] = a * win + b * lose + (1 - a - b) * W[dd]
        W = Wn
    return W[d]

# ---------------- study A: power-play pull
w1 = np.ones(G)
R0, PP0 = rates(w1)
starts = [60, 120, 180, 240, 300, 360]
def ppcurves(R, pp):
    return [pp_value(R, pp, s, True) for s in starts], [pp_value(R, pp, s, False) for s in starts]
c6, c5 = ppcurves(R0, PP0)
b6, b5, bpp = [], [], []
for b in range(200):
    w = rng.poisson(1.0, G).astype(float); Rb, ppb = rates(w)
    x6, x5 = ppcurves(Rb, ppb); b6.append(x6); b5.append(x5); bpp.append([ppb[k] for k in ("a54", "b54", "a64", "b64")])
b6, b5, bpp = np.array(b6), np.array(b5), np.array(bpp)
diff = b6 - b5
ppres = dict(rates=PP0, rates_ci={k: q(bpp[:, i]) for i, k in enumerate(("a54", "b54", "a64", "b64"))},
             expo={k: [float(E[k][:, 0].sum() / 60), int(E[k][:, 1].sum()), int(E[k][:, 2].sum())] for k in KEYS if k.startswith(("5v4", "6v4"))},
             starts=starts, pull=c6, nopull=c5, pull_ci=[q(b6[:, i]) for i in range(len(starts))],
             nopull_ci=[q(b5[:, i]) for i in range(len(starts))], diff=[float(x) for x in np.array(c6) - np.array(c5)],
             diff_ci=[q(diff[:, i]) for i in range(len(starts))])
for nm, m in (("early", seasons <= 20222023), ("late", seasons >= 20232024)):
    Rs, pps = rates(m.astype(float)); x6, x5 = ppcurves(Rs, pps)
    ppres["split_" + nm] = dict(rates=pps, diff=[a - b for a, b in zip(x6, x5)])

# ---------------- study B: pull on an offensive-zone faceoff vs other pulls (down 1, even strength, first pull)
P = [p for p in T["pulls"] if "s0" in p]
first = {}
for p in sorted(P, key=lambda p: p["s0"]):
    if p["dpe"] or not p["shifts"]: continue
    k = (p["gi"], p["home"], p["d"])
    if k not in first: first[k] = p
fp = [p for p in first.values() if p["Tsk"] == 6 and p["Osk"] == 5 and p["d"] in (1, 2)]
pred_cache = {}
def pred(t, d):
    if (t, d) not in pred_cache:
        pred_cache[(t, d)] = solve(R0, t, tau={1: 10**6, 2: 10**6, 3: 10**6, 4: 10**6})[0][t, d]
    return pred_cache[(t, d)]
fz = {}
for d in (1, 2):
    for grp, f in (("OZ faceoff", lambda p: p["fz"] == "O"), ("NZ/DZ faceoff", lambda p: p["fz"] in ("N", "D")),
                   ("on the fly", lambda p: p["fz"] is None)):
        ps = [p for p in fp if p["d"] == d and f(p)]
        if not ps: continue
        obs = np.array([p["level"] for p in ps], float); pr = np.array([pred(p["tl"], d) for p in ps])
        gf = np.array([p["gf"] for p in ps], float); ga = np.array([p["ga"] for p in ps], float)
        res = obs - pr
        bs = [res[rng.integers(0, len(ps), len(ps))].mean() for _ in range(2000)]
        fz[f"{d}|{grp}"] = dict(n=len(ps), obs=wilson(int(obs.sum()), len(ps)), pred=float(pr.mean()),
                                resid=float(res.mean()), resid_ci=q(bs), gf_spell=wilson(int(gf.sum()), len(ps)),
                                ga_spell=wilson(int(ga.sum()), len(ps)), med_tl=float(np.median([p["tl"] for p in ps])),
                                early=float(np.mean([obs[i] - pr[i] for i, p in enumerate(ps) if p["season"] <= 20222023])),
                                late=float(np.mean([obs[i] - pr[i] for i, p in enumerate(ps) if p["season"] >= 20232024])))
# OZ vs on-the-fly difference in residual, down 1 and down 1+2 pooled
def grp_res(d, f):
    ps = [p for p in fp if p["d"] in d and f(p)]
    return np.array([p["level"] - pred(p["tl"], p["d"]) for p in ps], float)
for nm, d in (("d1", (1,)), ("d12", (1, 2))):
    a = grp_res(d, lambda p: p["fz"] == "O"); b = grp_res(d, lambda p: p["fz"] != "O")
    bs = [a[rng.integers(0, len(a), len(a))].mean() - b[rng.integers(0, len(b), len(b))].mean() for _ in range(2000)]
    fz["diff_" + nm] = dict(diff=float(a.mean() - b.mean()), ci=q(bs), n_oz=len(a), n_other=len(b))

# ---------------- study C: score effects (5v5 unblocked attempts and goals, periods 1-3)
F = np.array(T["fen"])  # gi, period, home_is_shooter, diff_home_before, goal
gi = F[:, 0].astype(int); per = F[:, 1]; hsh = F[:, 2]; dh = F[:, 3]; gl = F[:, 4]
# perspective of the team that is trailing (or the home team when tied)
states = [-3, -2, -1, 0, 1, 2, 3]
def share_tables(w):
    out = {}
    ww = w[gi]
    for st in states:
        # attempts by a team when its score diff = st: home shooter with dh=st, away shooter with -dh=st
        if st >= 3: mf = (hsh == 1) & (dh >= 3) | (hsh == 0) & (-dh >= 3); ma = (hsh == 0) & (dh >= 3) | (hsh == 1) & (-dh >= 3)
        elif st <= -3: mf = (hsh == 1) & (dh <= -3) | (hsh == 0) & (-dh <= -3); ma = (hsh == 0) & (dh <= -3) | (hsh == 1) & (-dh <= -3)
        else: mf = (hsh == 1) & (dh == st) | (hsh == 0) & (-dh == st); ma = (hsh == 0) & (dh == st) | (hsh == 1) & (-dh == st)
        f, a = (ww * mf).sum(), (ww * ma).sum()
        gf, ga = (ww * mf * gl).sum(), (ww * ma * gl).sum()
        out[st] = (f / (f + a), gf / (gf + ga), gf / f, ga / a, f, a, gf, ga)
    return out
base = share_tables(np.ones(G))
bt = [share_tables(rng.poisson(1.0, G).astype(float)) for _ in range(300)]
se = {st: dict(fen_share=base[st][0], fen_ci=q([b[st][0] for b in bt]), goal_share=base[st][1], goal_ci=q([b[st][1] for b in bt]),
               sh_for=base[st][2], sh_for_ci=q([b[st][2] for b in bt]), sh_against=base[st][3],
               n_att=int(base[st][4] + base[st][5]), n_goals=int(base[st][6] + base[st][7])) for st in states}
for nm, m in (("early", seasons <= 20222023), ("late", seasons >= 20232024)):
    t = share_tables(m.astype(float)); se["split_" + nm] = {st: (t[st][0], t[st][1]) for st in states}
json.dump(dict(pp=ppres, fz=fz, se=se, n_fen=len(F)), open(os.path.join(S, "other_results.json"), "w"), indent=1, default=float)
print(json.dumps(dict(pp=ppres, fz=fz, se=se), indent=1, default=float))
