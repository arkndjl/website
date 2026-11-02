"""Shared helpers for the soccer research studies (StatsBomb open data, compact.jsonl)."""
import json, math, random
from collections import defaultdict

INTL = ("FIFA World Cup", "UEFA Euro", "Copa America", "African Cup of Nations", "Women's World Cup", "UEFA Women's Euro")
BANDS = [(0, 15), (15, 30), (30, 45), (45, 60), (60, 75), (75, 200)]
BAND_LABELS = ["0-15", "15-30", "30-45+", "45-60", "60-75", "75-90+"]

def load(path):
    return [json.loads(l) for l in open(path)]

def clock(p, m, s):
    """Nominal game clock in minutes. First-half stoppage stays inside the first half (capped 44.99)."""
    t = m + s / 60
    if p == 1: return min(t, 44.99)
    return max(t, 45.0)

def goals(rec):
    """Regulation goals as list of (p, clock, scoring_team)."""
    out = []
    for s in rec["shots"]:
        if s["goal"] and s["p"] in (1, 2): out.append((s["p"], s["m"] + s["s"] / 60, s["team"]))
    for o in rec["og"]:
        if o["p"] in (1, 2):
            other = rec["away"] if o["team"] == rec["home"] else rec["home"]
            out.append((o["p"], o["m"] + o["s"] / 60, other))
    out.sort()
    return out

def elapsed(rec, p, t):
    """Real elapsed playing minutes at (period, raw minute)."""
    he1 = rec["half_end"].get("1", 45.0)
    if p == 1: return t
    return he1 + (t - 45)

def match_len(rec):
    he1 = rec["half_end"].get("1", 45.0); he2 = rec["half_end"].get("2", 90.0)
    return he1 + (he2 - 45)

def first_red(rec):
    """Elapsed time of first red card in regulation (any team), or None."""
    ts = [elapsed(rec, c["p"], c["m"] + c["s"] / 60) for c in rec["cards"] if c["p"] in (1, 2)]
    return min(ts) if ts else None

def regulation_ok(rec):
    """Sanity: regulation goals match the final score for matches that did not go to extra time."""
    g = goals(rec)
    went_et = any(s["p"] >= 3 for s in rec["shots"]) or "3" in rec["half_end"]
    if went_et: return True
    h = sum(1 for x in g if x[2] == rec["home"]); a = len(g) - h
    return (h, a) == (rec["hs"], rec["as"])

def ratings(recs):
    """Leave-one-out xG for/against per match for each team within competition-season.
    Returns dict (match_id, team) -> (xgf, xga) expected for that match from other matches."""
    tot = defaultdict(lambda: [0.0, 0.0, 0])
    per = {}
    for r in recs:
        key = (r["comp"], r["season"])
        xg = defaultdict(float)
        for s in r["shots"]:
            if s["p"] in (1, 2): xg[s["team"]] += s["xg"]
        for t, o in ((r["home"], r["away"]), (r["away"], r["home"])):
            per[(r["id"], t)] = (xg[t], xg[o])
            a = tot[(key, t)]; a[0] += xg[t]; a[1] += xg[o]; a[2] += 1
    comp_avg = defaultdict(lambda: [0.0, 0])
    for (key, t), a in tot.items():
        comp_avg[key][0] += a[0]; comp_avg[key][1] += a[2]
    hx = defaultdict(lambda: [0.0, 0.0])
    for r in recs:
        if r["comp"] in INTL: continue
        f, g = per[(r["id"], r["home"])]; hx[(r["comp"], r["season"])][0] += f; hx[(r["comp"], r["season"])][1] += g
    out = {}
    for r in recs:
        key = (r["comp"], r["season"]); avg = comp_avg[key][0] / comp_avg[key][1]
        def loo(t):
            a = tot[(key, t)]; f, g = per[(r["id"], t)]
            n = a[2] - 1
            if n < 2: return avg, avg
            k = 2.0  # shrink toward competition mean with 2 pseudo-matches
            return (a[0] - f + k * avg) / (n + k), (a[1] - g + k * avg) / (n + k)
        hf, ha = loo(r["home"]); af, aa = loo(r["away"])
        hr = 1.0 if r["comp"] in INTL else hx[key][0] / hx[key][1]
        exp_h = math.sqrt(max(hf, 0.05) * max(aa, 0.05)) * math.sqrt(hr)
        exp_a = math.sqrt(max(af, 0.05) * max(ha, 0.05)) / math.sqrt(hr)
        out[(r["id"], r["home"])] = (exp_h, exp_a)
        out[(r["id"], r["away"])] = (exp_a, exp_h)
    return out

def wilson(k, n, z=1.96):
    if n == 0: return (float("nan"),) * 2
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h

def boot(groups, stat, B=1000, seed=1):
    """Cluster bootstrap. groups: list of per-cluster items; stat(list)->float."""
    rng = random.Random(seed); n = len(groups); vals = []
    for _ in range(B):
        vals.append(stat([groups[rng.randrange(n)] for _ in range(n)]))
    vals.sort()
    return vals[int(0.025 * B)], vals[int(0.975 * B) - 1]

def timeline(rec):
    """Events in elapsed time: ('shot', e, team, xg, goal) and ('og', e, scoring_team). Regulation only."""
    ev = []
    for s in rec["shots"]:
        if s["p"] in (1, 2): ev.append((elapsed(rec, s["p"], s["m"] + s["s"] / 60), 0, s["team"], s["xg"], s["goal"]))
    for o in rec["og"]:
        if o["p"] in (1, 2):
            other = rec["away"] if o["team"] == rec["home"] else rec["home"]
            ev.append((elapsed(rec, o["p"], o["m"] + o["s"] / 60), 1, other, 0.0, True))
    ev.sort(key=lambda x: (x[0], x[1]))
    return ev

def slices(rec):
    """Split the match into pieces of constant (band, score diff, red state).
    Yields dicts from the home POV: band, diff (home-away), red (bool), dur, xg_h, xg_a, g_h, g_a, t0."""
    he1 = rec["half_end"].get("1", 45.0); L = match_len(rec)
    bounds = [0, 15, 30, he1, he1 + 15, he1 + 30, max(L, he1 + 30.01)]
    red = first_red(rec)
    cuts = sorted(set(bounds + ([red] if red is not None else [])))
    ev = timeline(rec)
    gl = [(e[0], e[2]) for e in ev if e[4]]
    cuts = sorted(set(cuts + [g[0] for g in gl]))
    out = []
    for a, b in zip(cuts, cuts[1:]):
        if b <= a: continue
        # state at start of piece: goals strictly before or at a
        out.append({"t0": a, "t1": b, "dur": b - a, "xg_h": 0.0, "xg_a": 0.0, "g_h": 0, "g_a": 0})
    # assign state and events
    gi = 0; h = a_ = 0
    for pc in out:
        while gi < len(gl) and gl[gi][0] <= pc["t0"]:
            if gl[gi][1] == rec["home"]: h += 1
            else: a_ += 1
            gi += 1
        pc["diff"] = h - a_
        pc["red"] = red is not None and pc["t0"] >= red
        pc["band"] = max(i for i in range(6) if bounds[i] <= pc["t0"] + 1e-9)
    for t, kind, tm, xg, goal in ev:
        # goal events sit exactly on a cut; they belong to the piece that ends there
        for pc in out:
            if (pc["t0"] < t <= pc["t1"]) or (t == 0 and pc["t0"] == 0):
                side = "h" if tm == rec["home"] else "a"
                pc["xg_" + side] += xg
                if goal: pc["g_" + side] += 1
                break
    return out

def ols_cluster(X, y, groups):
    """OLS with cluster-robust (CR1) standard errors. X: list of rows (include intercept). Returns beta, se."""
    import numpy as np
    X = np.asarray(X, float); y = np.asarray(y, float)
    XtX_inv = np.linalg.pinv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    meat = np.zeros((X.shape[1], X.shape[1]))
    idx = {}
    for i, g in enumerate(groups): idx.setdefault(g, []).append(i)
    for g, ii in idx.items():
        s = X[ii].T @ e[ii]
        meat += np.outer(s, s)
    G = len(idx); n, k = X.shape
    c = G / (G - 1) * (n - 1) / (n - k)
    V = c * XtX_inv @ meat @ XtX_inv
    return b, np.sqrt(np.diag(V))
