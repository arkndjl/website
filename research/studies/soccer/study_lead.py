"""Study: protecting a 1-goal lead. xG share by minute band for teams leading by 1 vs their pre-match expected share,
and the points cost of the late shift."""
import json, math, sys, random
from collections import defaultdict
from common import *

SCR = sys.argv[1]
recs = [r for r in load(SCR + "/compact.jsonl") if regulation_ok(r)]
R = ratings(recs)
L_avg = sum(match_len(r) for r in recs) / len(recs)
MID = [7.5, 22.5, 37.5, 52.5, 67.5, 85]

# per match, per band, per state: [dur, xgf, xga, expf*dur, expa*dur, gf, ga]
per_match = []
for r in recs:
    acc = defaultdict(lambda: [0.0] * 7)
    for pc in slices(r):
        if pc["red"]: continue
        for team, sgn, xf, xa, gf, ga in ((r["home"], 1, pc["xg_h"], pc["xg_a"], pc["g_h"], pc["g_a"]),
                                          (r["away"], -1, pc["xg_a"], pc["xg_h"], pc["g_a"], pc["g_h"])):
            d = sgn * pc["diff"]
            if d not in (-1, 0, 1): continue
            ef, ea = R[(r["id"], team)]
            a = acc[(pc["band"], d)]
            a[0] += pc["dur"]; a[1] += xf; a[2] += xa; a[3] += ef / L_avg * pc["dur"]; a[4] += ea / L_avg * pc["dur"]
            a[5] += gf; a[6] += ga
    per_match.append((r, dict(acc)))

def agg(ms, band, d):
    t = [0.0] * 7
    for _, acc in ms:
        a = acc.get((band, d))
        if a:
            for i in range(7): t[i] += a[i]
    return t

def share(t): return t[1] / (t[1] + t[2]) if t[1] + t[2] > 0 else float("nan")
def eshare(t): return t[3] / (t[3] + t[4]) if t[3] + t[4] > 0 else float("nan")

# league-wide xG volume by band (all 11v11 states), relative to the match average
vol = [[0.0, 0.0] for _ in range(6)]
for r in recs:
    for pc in slices(r):
        if pc["red"]: continue
        vol[pc["band"]][0] += pc["dur"]; vol[pc["band"]][1] += pc["xg_h"] + pc["xg_a"]
tot_rate = sum(v[1] for v in vol) / sum(v[0] for v in vol)
MULT = [v[1] / v[0] / tot_rate for v in vol]
print("band volume multipliers", [round(x, 3) for x in MULT])

def mult_integral(r, T, L):
    he1 = r["half_end"].get("1", 45.0)
    bounds = [0, 15, 30, he1, he1 + 15, he1 + 30, 1e9]
    tot = 0.0
    for b in range(6):
        lo, hi = max(T, bounds[b]), min(L, bounds[b + 1])
        if hi > lo: tot += (hi - lo) * MULT[b]
    return tot

res = {"bands": [], "mult": MULT}
lead_pts, exp_pts = [], []
for b in range(6):
    t1 = agg(per_match, b, 1); t0 = agg(per_match, b, 0)
    n_m = sum(1 for _, acc in per_match if (b, 1) in acc)
    lo, hi = boot(per_match, lambda ms: share(agg(ms, b, 1)), B=400)
    dlo, dhi = boot(per_match, lambda ms: (lambda t: share(t) - eshare(t))(agg(ms, b, 1)), B=400)
    row = {"band": BAND_LABELS[b], "x": MID[b], "lead_share": share(t1), "lo": lo, "hi": hi, "exp_share": eshare(t1),
           "excess": share(t1) - eshare(t1), "excess_lo": dlo, "excess_hi": dhi,
           "lead_xgf90": t1[1] / t1[0] * 90, "lead_xga90": t1[2] / t1[0] * 90,
           "lead_expf90": t1[3] / t1[0] * 90, "lead_expa90": t1[4] / t1[0] * 90,
           "level_xg90_total": (t0[1] + t0[2]) / t0[0] * 90 / 2, "lead_total90": (t1[1] + t1[2]) / t1[0] * 90 / 2,
           "lead_minutes": t1[0], "n_matches": n_m}
    res["bands"].append(row)
    print(row)

# ---- points cost: leading by exactly 1 at nominal 75', 11v11 at that moment ----
def conv(xgs):
    dist = [1.0]
    for p in xgs:
        p = min(max(p, 0.0), 0.99)
        nd = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nd[k] += v * (1 - p); nd[k + 1] += v * p
        dist = nd
    return dist

def pois(lam, kmax=12):
    return [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(kmax)]

def xpts(df, da, lead):
    w = d = 0.0
    for i, pf in enumerate(df):
        for j, pa in enumerate(da):
            g = lead + i - j
            if g > 0: w += pf * pa
            elif g == 0: d += pf * pa
    return 3 * w + d

def points_at(T_nom, lead=1):
    rows = []
    for r in recs:
        he1 = r["half_end"].get("1", 45.0); T = he1 + (T_nom - 45); L = match_len(r)
        if L <= T: continue
        red = first_red(r)
        if red is not None and red <= T: continue
        ev = timeline(r)
        h = sum(1 for e in ev if e[4] and e[0] <= T and e[2] == r["home"]); a = sum(1 for e in ev if e[4] and e[0] <= T and e[2] != r["home"])
        if abs(h - a) != lead: continue
        ld = r["home"] if h > a else r["away"]
        fh = sum(1 for e in ev if e[4] and e[2] == r["home"]); fa = sum(1 for e in ev if e[4] and e[2] != r["home"])
        fd = (fh - fa) * (1 if ld == r["home"] else -1)
        pts = 3 if fd > 0 else (1 if fd == 0 else 0)
        xf = [e[3] for e in ev if e[0] > T and e[1] == 0 and e[2] == ld]
        xa = [e[3] for e in ev if e[0] > T and e[1] == 0 and e[2] != ld]
        ef, ea = R[(r["id"], ld)]; rem = L - T
        rem = mult_integral(r, T, L)
        x_real = xpts(pois(sum(xf)), pois(sum(xa)), lead)
        x_exp = xpts(pois(ef / L_avg * rem), pois(ea / L_avg * rem), lead)
        rows.append({"id": r["id"], "pts": pts, "x_real": x_real, "x_exp": x_exp, "xgf": sum(xf), "xga": sum(xa),
                     "expf": ef / L_avg * rem, "expa": ea / L_avg * rem, "season": r["season"], "comp": r["comp"]})
    return rows

pc = {}
for Tn in (60, 70, 75, 80, 85):
    rows = points_at(Tn)
    m = lambda rs, k: sum(x[k] for x in rs) / len(rs)
    d_lo, d_hi = boot(rows, lambda rs: m(rs, "x_real") - m(rs, "x_exp"), B=1000)
    a_lo, a_hi = boot(rows, lambda rs: m(rs, "pts") - m(rs, "x_exp"), B=1000)
    p_lo, p_hi = boot(rows, lambda rs: m(rs, "pts"), B=1000)
    pc[Tn] = {"n": len(rows), "pts": m(rows, "pts"), "pts_lo": p_lo, "pts_hi": p_hi, "x_real": m(rows, "x_real"),
              "x_exp": m(rows, "x_exp"), "cost": m(rows, "x_real") - m(rows, "x_exp"), "cost_lo": d_lo, "cost_hi": d_hi,
              "act_minus_exp": m(rows, "pts") - m(rows, "x_exp"), "ame_lo": a_lo, "ame_hi": a_hi,
              "xgf": m(rows, "xgf"), "xga": m(rows, "xga"), "expf": m(rows, "expf"), "expa": m(rows, "expa")}
    print(Tn, pc[Tn])
    if Tn == 75:
        # split check: men's club 2015/16 vs rest
        for nm, f in (("2015/16 men's leagues", lambda x: x["season"] == "2015/2016"), ("other", lambda x: x["season"] != "2015/2016")):
            rs = [x for x in rows if f(x)]
            lo, hi = boot(rs, lambda q: m(q, "x_real") - m(q, "x_exp"), B=600)
            pc["split_" + nm] = {"n": len(rs), "cost": m(rs, "x_real") - m(rs, "x_exp"), "lo": lo, "hi": hi}
            print(nm, pc["split_" + nm])
res["points"] = pc
res["n_matches"] = len(recs)
json.dump(res, open(SCR + "/lead_results.json", "w"), indent=1)
