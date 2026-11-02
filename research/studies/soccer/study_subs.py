"""Study: first-substitution timing by score state, and whether an early first sub changes the rest of the match."""
import json, sys
from collections import defaultdict
from common import *

SCR = sys.argv[1]
recs = [r for r in load(SCR + "/compact.jsonl") if regulation_ok(r)]
R = ratings(recs)

def nominal(s): return clock(s["p"], s["m"], s["s"])

def state_at(r, team, T_el):
    ev = timeline(r)
    f = sum(1 for e in ev if e[4] and e[0] <= T_el and e[2] == team)
    a = sum(1 for e in ev if e[4] and e[0] <= T_el and e[2] != team)
    return f - a

def el_nom(r, m):  # elapsed time at nominal second-half minute m
    return r["half_end"].get("1", 45.0) + (m - 45)

# ---------- A: hazard of first tactical sub in the second half by current state ----------
haz = defaultdict(lambda: [0, 0])   # (state, minute) -> [at risk, subbed]
first_min = defaultdict(list)       # state at sub time -> minutes
fh_sub = 0; teams = 0
for r in recs:
    red = first_red(r)
    ev = timeline(r)
    gl = [(e[0], e[2]) for e in ev if e[4]]
    for team in (r["home"], r["away"]):
        tac = sorted(nominal(s) for s in r["subs"] if s["team"] == team and s["why"] == "Tactical" and s["p"] in (1, 2))
        teams += 1
        ft = tac[0] if tac else None
        if ft is not None and ft < 45: fh_sub += 1; continue
        for m in range(45, 90):
            T = el_nom(r, m)
            if red is not None and red <= T: break
            if ft is not None and ft < m: break
            st = sum(1 if tm == team else -1 for t, tm in gl if t <= T)
            st = max(-1, min(1, st))
            h = haz[(st, m)]; h[0] += 1
            if ft is not None and m <= ft < m + 1: h[1] += 1
        if ft is not None and (red is None or red > el_nom(r, ft)):
            st = sum(1 if tm == team else -1 for t, tm in gl if t <= el_nom(r, ft))
            first_min[max(-1, min(1, st))].append(ft)

curves = {}
for st in (-1, 0, 1):
    S = 1.0; pts = []
    for m in range(45, 90):
        n, k = haz[(st, m)]
        if n: S *= 1 - k / n
        if (m + 1) % 5 == 0 or m == 45:
            pts.append({"x": m + 1, "y": 1 - S, "n": n})
    curves[st] = pts
    med = next((p["x"] for p in pts if p["y"] >= 0.5), None)
    ms = sorted(first_min[st]); 
    print("state", st, "curve", [(p["x"], round(p["y"], 3)) for p in pts], "median-from-curve", med,
          "observed median first-sub minute", ms[len(ms) // 2] if ms else None, "n", len(ms))
# HT sub rate by HT state
ht = defaultdict(lambda: [0, 0])
for r in recs:
    red = first_red(r)
    if red is not None and red <= r["half_end"].get("1", 45): continue
    for team in (r["home"], r["away"]):
        tac = [s for s in r["subs"] if s["team"] == team and s["why"] == "Tactical"]
        if any(s["p"] == 1 for s in tac): continue
        st = max(-1, min(1, state_at(r, team, r["half_end"].get("1", 45))))
        ht[st][0] += 1; ht[st][1] += any(s["p"] == 2 and s["m"] == 45 and s["s"] < 30 or (s["p"] == 2 and s["m"] == 45) for s in tac)
print("HT sub rate by state", {k: (v[1], v[0], round(v[1] / v[0], 3), wilson(v[1], v[0])) for k, v in ht.items()})

# ---------- B: effect of an early first sub (landmarks at 45 [HT subs] and 60) ----------
def landmark(Tn, early_lo):
    rows = []
    for r in recs:
        red = first_red(r)
        T = el_nom(r, Tn) if Tn > 45 else r["half_end"].get("1", 45.0) + 0.6  # HT subs happen at 45:00 of 2nd half
        L = match_len(r)
        if red is not None and red <= T: continue
        ev = timeline(r)
        sides = []
        for team in (r["home"], r["away"]):
            subs = [s for s in r["subs"] if s["team"] == team and s["p"] in (1, 2)]
            if any(s["why"] != "Tactical" and nominal(s) < Tn + (0.6 if Tn == 45 else 0) for s in subs): sides.append(None); continue
            tac = sorted(nominal(s) for s in subs if s["why"] == "Tactical")
            if tac and tac[0] < early_lo: sides.append(None); continue
            cut = Tn + (0.6 if Tn == 45 else 0)
            sides.append(1 if (tac and tac[0] < cut) else 0)
        for i, team in enumerate((r["home"], r["away"])):
            if sides[i] is None: continue
            opp_early = sides[1 - i] if sides[1 - i] is not None else 0
            st = state_at(r, team, T)
            xf_pre = sum(e[3] for e in ev if e[0] <= T and e[1] == 0 and e[2] == team)
            xa_pre = sum(e[3] for e in ev if e[0] <= T and e[1] == 0 and e[2] != team)
            # performance in the 15 minutes before the landmark (the trigger window)
            xf_w = sum(e[3] for e in ev if T - 15 < e[0] <= T and e[1] == 0 and e[2] == team)
            xa_w = sum(e[3] for e in ev if T - 15 < e[0] <= T and e[1] == 0 and e[2] != team)
            xf = sum(e[3] for e in ev if e[0] > T and e[1] == 0 and e[2] == team)
            xa = sum(e[3] for e in ev if e[0] > T and e[1] == 0 and e[2] != team)
            gf = sum(1 for e in ev if e[0] > T and e[4] and e[2] == team)
            ga = sum(1 for e in ev if e[0] > T and e[4] and e[2] != team)
            ef, ea = R[(r["id"], team)]
            rows.append({"id": r["id"], "early": sides[i], "opp_early": opp_early, "st": st, "str": ef - ea,
                         "pre": xf_pre - xa_pre, "win": xf_w - xa_w, "home": int(team == r["home"] and r["comp"] not in INTL),
                         "xgd": xf - xa, "gd": gf - ga, "season": r["season"], "rem": L - T})
    return rows

def fit(rows, y):
    X = []
    for q in rows:
        stv = [int(q["st"] <= -2), int(q["st"] == -1), int(q["st"] == 1), int(q["st"] >= 2)]
        X.append([1, q["early"], q["opp_early"], q["str"], q["pre"], q["win"], q["home"]] + stv)
    keep = [j for j in range(len(X[0])) if j < 2 or len(set(x[j] for x in X)) > 1]
    X = [[x[j] for j in keep] for x in X]
    b, se = ols_cluster(X, [q[y] for q in rows], [q["id"] for q in rows])
    return b[1], se[1]

out = {"curves": curves, "ht": {k: v for k, v in ht.items()}}
for Tn, lo in ((45, 0), (60, 0)):
    rows = landmark(Tn, lo)
    e = [q for q in rows if q["early"]]; l = [q for q in rows if not q["early"]]
    raw = (sum(q["xgd"] for q in e) / len(e), sum(q["xgd"] for q in l) / len(l))
    res = {"n": len(rows), "n_early": len(e), "raw_xgd_early": raw[0], "raw_xgd_late": raw[1],
           "matches": len(set(q["id"] for q in rows))}
    for y in ("xgd", "gd"):
        b, se = fit(rows, y); res[y] = (b, b - 1.96 * se, b + 1.96 * se)
    # by state at landmark
    for stn, f in (("trailing", lambda q: q["st"] < 0), ("level", lambda q: q["st"] == 0), ("leading", lambda q: q["st"] > 0)):
        rs = [q for q in rows if f(q)]
        b, se = fit(rs, "xgd")
        res["xgd_" + stn] = (b, b - 1.96 * se, b + 1.96 * se, len(rs), sum(q["early"] for q in rs))
    for sn, f in (("2015/16", lambda q: q["season"] == "2015/2016"), ("other", lambda q: q["season"] != "2015/2016")):
        rs = [q for q in rows if f(q)]
        b, se = fit(rs, "xgd")
        res["split_" + sn] = (b, b - 1.96 * se, b + 1.96 * se, len(rs))
    out["landmark_%d" % Tn] = res
    print(Tn, json.dumps(res, default=float))
json.dump(out, open(SCR + "/subs_results.json", "w"), default=float, indent=1)
