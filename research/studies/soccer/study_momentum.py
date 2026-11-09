# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Study: scoring rates in the minutes after a goal (team that conceded / team that scored), against a
baseline matched on minute band, score state and pre-match strength."""
import json, sys, math
from collections import defaultdict
from common import *

SCR = sys.argv[1]
recs = [r for r in load(SCR + "/compact.jsonl") if regulation_ok(r)]
R = ratings(recs)
mean_ef = sum(v[0] for v in R.values()) / len(R)
BK = [(0, 3), (3, 6), (6, 10), (10, 15), (15, 20)]
BX = [1.5, 4.5, 8, 12.5, 17.5]

rows = []  # per team-minute: (match_id, band, state, strength, xg, goals, since, kind)
for r in recs:
    he1 = r["half_end"].get("1", 45.0); L = match_len(r); red = first_red(r)
    ev = timeline(r)
    bounds = [0, 15, 30, he1, he1 + 15, he1 + 30, 1e9]
    for team in (r["home"], r["away"]):
        st_f = R[(r["id"], team)][0] / mean_ef
        xg_m = defaultdict(float); g_m = defaultdict(int)
        for e in ev:
            if e[2] == team:
                k = int(e[0]); xg_m[k] += e[3]; g_m[k] += int(e[4])
        gl = [(e[0], e[2]) for e in ev if e[4]]
        for k in range(int(L)):
            if red is not None and k + 1 > red: break
            if k < he1 <= k + 1 and False: pass
            prev = [g for g in gl if g[0] <= k]
            st = sum(1 if tm == team else -1 for t, tm in prev)
            band = max(i for i in range(6) if bounds[i] <= k)
            since, kind = None, None
            if prev:
                since = k - prev[-1][0]; kind = "scored" if prev[-1][1] == team else "conceded"
                # skip minutes straddling halftime break effect: count elapsed time only
            rows.append((r["id"], band, max(-2, min(2, st)), st_f, xg_m.get(k, 0.0), g_m.get(k, 0), since, kind, r["season"]))

base = defaultdict(lambda: [0.0, 0.0, 0])
for q in rows:
    b = base[(q[1], q[2])]; b[0] += q[4]; b[1] += q[5]; b[2] += q[3]
def bucket(s):
    for i, (a, b) in enumerate(BK):
        if a <= s < b: return i
    return None

# group per match for bootstrap: match -> {(kind, bucket): [O_xg, O_g, E_xg, E_g]}
pm = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0.0, 0.0]))
for q in rows:
    if q[6] is None: continue
    bi = bucket(q[6])
    if bi is None: continue
    b = base[(q[1], q[2])]
    exg = b[0] / b[2] * q[3]; eg = b[1] / b[2] * q[3]
    a = pm[q[0]][(q[7], bi)]; a[0] += q[4]; a[1] += q[5]; a[2] += exg; a[3] += eg
groups = list(pm.values())
seasons = {}
for r in recs: seasons[r["id"]] = r["season"]
ids = list(pm.keys())

def ratio(gs, key, o, e):
    O = sum(g[key][o] for g in gs if key in g); E = sum(g[key][e] for g in gs if key in g)
    return O / E if E else float("nan")

out = {}
for kind in ("conceded", "scored"):
    pts = []
    for bi in range(len(BK)):
        key = (kind, bi)
        rx = ratio(groups, key, 0, 2); rg = ratio(groups, key, 1, 3)
        lo, hi = boot(groups, lambda gs: ratio(gs, key, 0, 2), B=400)
        glo, ghi = boot(groups, lambda gs: ratio(gs, key, 1, 3), B=400)
        mins = sum(1 for q in rows if q[7] == kind and q[6] is not None and bucket(q[6]) == bi)
        G = sum(g[key][1] for g in groups if key in g)
        pts.append({"x": BX[bi], "y": rx, "lo": lo, "hi": hi, "n": mins, "goal_ratio": rg, "g_lo": glo, "g_hi": ghi, "goals": G})
        print(kind, BK[bi], round(rx, 3), (round(lo, 3), round(hi, 3)), "goals O/E", round(rg, 3), (round(glo, 3), round(ghi, 3)), "team-min", mins, "goals", G)
    out[kind] = pts
# 0-10 pooled + split
for kind in ("conceded", "scored"):
    for nm, sel in (("all", lambda i: True), ("2015/16", lambda i: seasons[i] == "2015/2016"), ("other", lambda i: seasons[i] != "2015/2016")):
        gs = [pm[i] for i in ids if sel(i)]
        def r10(gs, o, e):
            O = sum(g[(kind, b)][o] for g in gs for b in (0, 1, 2) if (kind, b) in g)
            E = sum(g[(kind, b)][e] for g in gs for b in (0, 1, 2) if (kind, b) in g)
            return O / E
        v = r10(gs, 0, 2); lo, hi = boot(gs, lambda x: r10(x, 0, 2), B=400)
        vg = r10(gs, 1, 3); glo, ghi = boot(gs, lambda x: r10(x, 1, 3), B=400)
        out[f"{kind}_0_10_{nm}"] = {"xg": (v, lo, hi), "g": (vg, glo, ghi), "matches": len(gs)}
        print(kind, nm, "0-10 xG O/E", round(v, 3), (round(lo, 3), round(hi, 3)), "goals", round(vg, 3), (round(glo, 3), round(ghi, 3)))
out["team_minutes"] = len(rows); out["matches"] = len(recs)
json.dump(out, open(SCR + "/momentum_results.json", "w"), indent=1)
