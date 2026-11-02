#!/usr/bin/env python3
"""ARKBOARD Research, CS2 studies on bo3.gg round data (see fetch_rounds.py and research/studies/BRIEF.md).

    python3 research/studies/cs2/cs2_studies.py

Reads $CS2_RAW/rounds.jsonl (scratchpad) and scripts/data/cs2_bo3.json.gz (map results for a team Elo), writes one
JSON per study next to this file.

Economy levels are bo3.gg's per-team buy class from equipment value at round start:
-1 eco (median ~$4k), 0 half-buy (~$9k), 1 force / light buy (~$18k), 2 full buy (~$27k).
Strength control: map Elo on bo3 team ids from every bo3 map since 2020 (K=24), pre-map.
CIs: Wilson for one-row-per-map proportions; cluster-robust (by map) SEs for round-level rates and regressions.
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = Path(os.environ.get("CS2_RAW",
                          "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/cs2/raw"))
Z = 1.96
# team keys in rounds.jsonl
NAME, SIDE, WIN, EQ, LVL, SPENT, SAVE, LBONUS, LSTREAK, WSTREAK, PISTOL, KILLS, DEATHS = range(13)
LVLNAME = {-1: "eco", 0: "half", 1: "force", 2: "full"}


# ---------- stats helpers ----------
def wilson(k, n):
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return (p, c - h, c + h)


def cluster_rate(rows):
    """rows: [(cluster, y)] -> (mean, lo, hi, n) with cluster-robust SE."""
    n = len(rows)
    if n == 0:
        return (None, None, None, 0)
    p = sum(y for _, y in rows) / n
    acc = defaultdict(float)
    for c, y in rows:
        acc[c] += y - p
    g = len(acc)
    var = sum(v * v for v in acc.values()) / (n * n) * (g / max(g - 1, 1))
    se = math.sqrt(var)
    return (p, p - Z * se, p + Z * se, n)


def logit_fit(X, y, cl, iters=30):
    """Logistic regression (Newton) -> beta, cluster-robust covariance."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (y - p))
        b += step
        if np.abs(step).max() < 1e-8:
            break
    p = 1 / (1 + np.exp(-X @ b))
    Hinv = np.linalg.pinv(X.T @ (X * (p * (1 - p))[:, None]))
    s = X * (y - p)[:, None]
    cl = np.asarray(cl)
    order = np.argsort(cl, kind="stable")
    cs, idx = np.unique(cl[order], return_index=True)
    S = np.add.reduceat(s[order], idx, axis=0)
    g = len(cs)
    meat = S.T @ S * (g / max(g - 1, 1))
    return b, Hinv @ meat @ Hinv


def marginal_effect(X, b, V, col, draws=400, seed=1):
    """Average predicted P with X[:,col]=1 minus =0, with a CI from coefficient draws."""
    X = np.asarray(X, float)
    X1, X0 = X.copy(), X.copy()
    X1[:, col], X0[:, col] = 1, 0

    def me(bb):
        return float(np.mean(1 / (1 + np.exp(-X1 @ bb)) - 1 / (1 + np.exp(-X0 @ bb))))
    rng = np.random.default_rng(seed)
    sims = [me(bb) for bb in rng.multivariate_normal(b, V, draws)]
    return me(b), float(np.percentile(sims, 2.5)), float(np.percentile(sims, 97.5))


def r3(x):
    return None if x is None else round(float(x), 4)


def pt(x, est, n):
    return {"x": x, "y": r3(est[0]), "lo": r3(est[1]), "hi": r3(est[2]), "n": int(n)}


def pct(x, d=1):
    return f"{100 * x:.{d}f}%"


def pp(x):
    return f"{100 * x:+.1f} pp"


# ---------- data ----------
def elo_table():
    """-> {bo3 game id: P(winner beats loser) pre-map}, map Elo on all bo3 maps (K=24)."""
    d = json.load(gzip.open(ROOT / "scripts/data/cs2_bo3.json.gz", "rt"))
    games = sorted((g for g in d["games"] if g[5] is not None and g[6] is not None and g[2]), key=lambda g: g[2])
    r = defaultdict(lambda: 1500.0)
    out = {}
    for g in games:
        a, b = g[5], g[6]
        p = 1 / (1 + 10 ** ((r[b] - r[a]) / 400))
        out[g[0]] = p
        r[a] += 24 * (1 - p)
        r[b] -= 24 * (1 - p)
    return out


def load():
    elo = elo_table()
    maps = []
    bad = defaultdict(int)
    seen = set()
    for line in (RAW / "rounds.jsonl").open():
        try:
            d = json.loads(line)
        except ValueError:
            bad["json"] += 1
            continue
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        R = d["rounds"]
        n = len(R)
        if not d["ws"] or n != d["ws"] + d["ls"] or n < 13 or d["ws"] < 13:
            bad["rounds"] += 1
            continue
        if any(r[0] != i + 1 or len(r[4]) != 2 for i, r in enumerate(R)):
            bad["shape"] += 1
            continue
        names = sorted({t[NAME] for t in R[0][4]})
        if len(names) != 2 or d["winner"] not in names:
            bad["names"] += 1
            continue
        A = R[0][4][0][NAME]
        rows = []  # per round: {team: dict}, winner name
        ok = True
        first_side = {t[NAME]: t[SIDE] for t in R[0][4]}
        for i, r in enumerate(R):
            tm = {t[NAME]: t for t in r[4]}
            if set(tm) != set(names) or any(t[LVL] is None or t[EQ] is None for t in r[4]):
                ok = False
                break
            # sides: rounds 1-12 as started, 13-24 swapped (overtime not checked)
            rn = i + 1
            if rn <= 24:
                exp = first_side[A] if rn <= 12 else ("T" if first_side[A] == "CT" else "CT")
                if tm[A][SIDE] != exp:
                    ok = False
                    break
            w = [t[NAME] for t in r[4] if t[WIN] == 1]
            if len(w) != 1:
                ok = False
                break
            rows.append((tm, w[0]))
        if not ok:
            bad["sides/econ"] += 1
            continue
        p = elo.get(d["id"])
        pw = {d["winner"]: p, d["loser"]: (1 - p) if p is not None else None} if p is not None else {}
        maps.append({"id": d["id"], "map": d["map"], "begin": d["begin"], "tier": d["tier"], "winner": d["winner"],
                     "names": names, "first": first_side, "rounds": rows, "elo": pw})
    print(f"maps kept {len(maps)}, dropped {dict(bad)}", file=sys.stderr)
    return maps


def elo_logit(m, team):
    p = m["elo"].get(team)
    if p is None:
        return 0.0
    p = min(max(p, 0.02), 0.98)
    return math.log(p / (1 - p))


def other(m, team):
    return m["names"][0] if m["names"][1] == team else m["names"][1]


def half_split(maps):
    ds = sorted(m["begin"] for m in maps)
    return ds[len(ds) // 2]


def date_range(maps):
    ds = sorted(m["begin"][:10] for m in maps)
    return ds[0], ds[-1]


def save(obj):
    det = obj.pop("_detail", None)
    if det is not None:
        (RAW.parent / f"{obj['id']}.detail.json").write_text(json.dumps(det, indent=1) + "\n")
    p = HERE / f"{obj['id']}.json"
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
    print("wrote", p.name, file=sys.stderr)


def data_line(maps, extra=""):
    a, b = date_range(maps)
    tiers = "S/A/B-tier" if any(m["tier"] == "b" for m in maps) else "S/A-tier"
    return f"bo3.gg round data, {tiers} pro maps, {a} to {b}, {len(maps):,} maps{extra}"


# ---------- study 1: pistol loser, save vs buy on the next round ----------
def study_pistol_loser(maps):
    recs = []  # one per (map, half)
    for m in maps:
        R = m["rounds"]
        for h, p in ((1, 0), (2, 12)):
            if len(R) < p + 3:
                continue
            L = other(m, R[p][1])
            W = R[p][1]
            nxt, nxt2 = R[p + 1][0], R[p + 2][0]
            lv = nxt[L][LVL]
            half = R[p:p + 12]
            won_half = sum(1 for _, w in half if w == L)
            recs.append({
                "map": m["id"], "half": h, "side": R[p][0][L][SIDE], "lvl": lv, "buy": 1 if lv >= 0 else 0,
                "w2": int(R[p + 1][1] == L), "w3": int(R[p + 2][1] == L), "half_rounds": won_half,
                "half_full": len(half) == 12, "map_win": int(m["winner"] == L), "elo": elo_logit(m, L),
                "opp_eq": nxt[W][EQ] / 10000, "k1": R[p][0][L][KILLS] or 0, "begin": m["begin"],
                "lvl3": R[p + 2][0][L][LVL]})
    out = {}
    # raw rates by side x decision
    for side in ("CT", "T"):
        for buy in (0, 1):
            sub = [r for r in recs if r["side"] == side and r["buy"] == buy]
            out[(side, buy)] = {
                "n": len(sub),
                "w2": cluster_rate([(r["map"], r["w2"]) for r in sub]),
                "w3": cluster_rate([(r["map"], r["w3"]) for r in sub]),
                "half": cluster_rate([(r["map"], r["half_rounds"] / 12) for r in sub if r["half"] == 1]),
                "map": cluster_rate([(r["map"], r["map_win"]) for r in sub]),
            }

    # adjusted effects: logit(outcome) ~ buy + CT + elo + opp R2 equipment + loser pistol kills + half2
    def adj(rs, key, cont=False):
        X = np.asarray([[1, r["buy"], r["side"] == "CT", r["elo"], r["opp_eq"], r["k1"], r["half"] == 2]
                        for r in rs], float)
        keep = [0, 1] + [j for j in range(2, X.shape[1]) if X[:, j].std() > 0]
        X = X[:, keep]
        if cont:  # linear probability for share outcomes -> OLS with cluster SE
            Xa, y = np.asarray(X, float), np.asarray([r[key] for r in rs], float)
            b = np.linalg.lstsq(Xa, y, rcond=None)[0]
            e = y - Xa @ b
            XtXi = np.linalg.inv(Xa.T @ Xa)
            cl = np.asarray([r["map"] for r in rs])
            order = np.argsort(cl, kind="stable")
            cs, idx = np.unique(cl[order], return_index=True)
            S = np.add.reduceat((Xa * e[:, None])[order], idx, axis=0)
            V = XtXi @ (S.T @ S) @ XtXi
            se = math.sqrt(V[1, 1])
            return (b[1], b[1] - Z * se, b[1] + Z * se)
        b, V = logit_fit(X, [r[key] for r in rs], [r["map"] for r in rs])
        return marginal_effect(X, b, V, 1)

    res = {}
    for side in ("CT", "T", "all"):
        rs = [r for r in recs if side == "all" or r["side"] == side]
        res[side] = {"w2": adj(rs, "w2"), "w3": adj(rs, "w3"), "map": adj(rs, "map_win"),
                     "half": adj([dict(r, hr=r["half_rounds"]) for r in rs if r["half"] == 1], "hr", cont=True)}
    # split check: first vs second half of the date range, CT side, round-3 and map effect
    mid = half_split(maps)
    split = {}
    for nm, rs in (("early", [r for r in recs if r["begin"] < mid]), ("late", [r for r in recs if r["begin"] >= mid])):
        split[nm] = {s: adj([r for r in rs if r["side"] == s], "map_win") for s in ("CT", "T")}

    def shown(side, buy, k):
        return out[(side, buy)][k]
    series = []
    for buy, nm in ((0, "save round 2"), (1, "buy round 2")):
        pts = []
        for side in ("CT", "T"):
            for k, lab in (("w2", "R2"), ("w3", "R3"), ("map", "map")):
                e = shown(side, buy, k)
                pts.append(pt(f"{side} {lab}", e, e[3]))
        series.append({"name": nm, "points": pts})
    sh = {s: sum(1 for r in recs if r["side"] == s and r["buy"] == 0) / max(1, sum(1 for r in recs if r["side"] == s))
          for s in ("CT", "T")}
    ct, t = res["CT"], res["T"]

    def eff(e):
        return f"{pp(e[0])} ({pp(e[1])[:-3]} to {pp(e[2])})"
    n = len(recs)
    nct = sum(1 for r in recs if r["side"] == "CT")
    a = res["all"]
    zero = a["map"][1] < 0 < a["map"][2]
    ans = (f"Buying on round 2: {pp(a['w2'][0])} in round 2, {pp(a['w3'][0])} in round 3, map win {pp(a['map'][0])}"
           + (" (not different from 0)." if zero else "."))
    obj = {
        "id": "cs2-pistol-loser-buy", "sport": "CS2",
        "question": "After losing the pistol round, should the team save or buy on round 2?",
        "answer": ans,
        "findings": [
            f"CT buy vs save, adjusted: R2 {eff(ct['w2'])}, R3 {eff(ct['w3'])}. {pct(1 - sh['CT'], 0)} of CT losers buy.",
            f"T buy vs save, adjusted: R2 {eff(t['w2'])}, R3 {eff(t['w3'])}. {pct(1 - sh['T'], 0)} of T losers buy.",
            f"Map win, buy vs save: CT {eff(ct['map'])}, T {eff(t['map'])}.",
            f"First-half rounds won (of 12), buy vs save: CT {ct['half'][0]:+.2f} ({ct['half'][1]:+.2f} to {ct['half'][2]:+.2f}), "
            f"T {t['half'][0]:+.2f} ({t['half'][1]:+.2f} to {t['half'][2]:+.2f}).",
        ],
        "method": ("Pistol loser's round-2 buy class from bo3.gg equipment value (save = eco, buy = half/force). Logistic "
                   "models adjust for side, team Elo, winner's round-2 equipment, loser's pistol kills and half; "
                   "cluster-robust CIs by map."),
        "data": data_line(maps, f", {n:,} pistol-loss halves ({nct:,} CT)"),
        "n": n,
        "robust": None, "interest": 4,
        "split_check": (f"Map effect early/late: CT {pp(split['early']['CT'][0])} / {pp(split['late']['CT'][0])}, "
                        f"T {pp(split['early']['T'][0])} / {pp(split['late']['T'][0])}."),
        "chart": {"type": "bar", "title": "Pistol loser win %, save vs buy on round 2",
                  "x_label": "side and outcome", "y_label": "win %", "y_fmt": "pct", "x_reverse": False,
                  "ref": None, "mark": None, "series": series},
    }
    obj["_detail"] = {"raw": {f"{s}-{'buy' if b else 'save'}": {k: [r3(x) for x in v[:3]] + [v[3]] if k != "n" else v
                                                                for k, v in d.items()} for (s, b), d in out.items()},
                      "adjusted": {s: {k: [r3(x) for x in v] for k, v in d.items()} for s, d in res.items()},
                      "split": {k: {s: [r3(x) for x in v] for s, v in d.items()} for k, d in split.items()}}
    return obj, recs, res, split


# ---------- study 2: round win % by equipment difference and side ----------
def study_equipment(maps):
    by_bin = defaultdict(list)
    match = defaultdict(list)
    B = 4000
    for m in maps:
        for i, (tm, w) in enumerate(m["rounds"]):
            rn = i + 1
            if rn in (1, 13) or rn > 24:
                continue
            ct = next(t for t in tm.values() if t[SIDE] == "CT")
            tt = next(t for t in tm.values() if t[SIDE] == "T")
            y = int(w == ct[NAME])
            d = ct[EQ] - tt[EQ]
            b = max(-6, min(6, int(round(d / B))))
            by_bin[b].append((m["id"], y))
            match[(ct[LVL], tt[LVL])].append((m["id"], y))
    series = []
    for side in ("CT", "T"):
        pts = []
        for b in range(-6, 7):
            rows = by_bin[b if side == "CT" else -b]
            if len(rows) < 100:
                continue
            if side == "T":
                rows = [(c, 1 - y) for c, y in rows]
            e = cluster_rate(rows)
            pts.append(pt(b * B / 1000, e, e[3]))
        series.append({"name": side, "points": pts})
    eq0 = {s["name"]: next(p for p in s["points"] if p["x"] == 0) for s in series}
    mt = {k: cluster_rate(v) for k, v in match.items()}
    n_rounds = sum(len(v) for v in by_bin.values())
    ecoall = cluster_rate(match[(-1, 2)] + [(c, 1 - y) for c, y in match[(2, -1)]])

    def mm(c, t):
        e = mt[(c, t)]
        return f"{pct(e[0])} ({pct(e[1])}-{pct(e[2])}, n={e[3]:,})"
    # crossover: equipment gap where CT win% = 50%
    pts = series[0]["points"]
    cross = None
    for a, b in zip(pts, pts[1:]):
        if a["y"] < 0.5 <= b["y"]:
            cross = a["x"] + (0.5 - a["y"]) / (b["y"] - a["y"]) * (b["x"] - a["x"])
    mid = half_split(maps)
    sp = []
    for part in ([m for m in maps if m["begin"] < mid], [m for m in maps if m["begin"] >= mid]):
        rows = []
        for m in part:
            for i, (tm, w) in enumerate(m["rounds"]):
                if i + 1 in (1, 13) or i + 1 > 24:
                    continue
                ct = next(t for t in tm.values() if t[SIDE] == "CT")
                tt = next(t for t in tm.values() if t[SIDE] == "T")
                if ct[LVL] == 2 and tt[LVL] == 2:
                    rows.append((m["id"], int(w == ct[NAME])))
        sp.append(cluster_rate(rows))
    obj = {
        "id": "cs2-equipment-gap", "sport": "CS2",
        "question": "How much does an equipment gap change round win chances on CT and T?",
        "answer": (f"Full buy vs full buy: CT wins {pct(mt[(2, 2)][0])}. At equal dollar value CT wins "
                   f"{pct(eq0['CT']['y'])}; an eco beats a full buy {pct(ecoall[0])}."),
        "findings": [
            f"Full buy vs full buy: CT wins {mm(2, 2)}.",
            f"Force vs full: CT forcing wins {mm(1, 2)}; T forcing wins {pct(1 - mt[(2, 1)][0])} (n={mt[(2, 1)][3]:,}).",
            f"Eco vs full: CT eco wins {mm(-1, 2)}; T eco wins {pct(1 - mt[(2, -1)][0])} (n={mt[(2, -1)][3]:,}).",
            f"CT needs about ${cross:.1f}k more equipment value than T for a 50% round (CT rifles and kits cost more).",
        ],
        "method": ("Non-pistol regulation rounds; equipment value at round start per team from bo3.gg, binned by "
                   "CT minus T in $4k steps (ends capped at $24k). Round win rate with map-clustered CIs."),
        "data": data_line(maps, f", {n_rounds:,} rounds"),
        "n": n_rounds, "robust": True, "interest": 3,
        "split_check": (f"Full vs full CT win %: early {pct(sp[0][0])} (n={sp[0][3]:,}), late {pct(sp[1][0])} "
                        f"(n={sp[1][3]:,})."),
        "chart": {"type": "line", "title": "Round win % by equipment gap", "x_label": "own minus opponent equipment ($k)",
                  "y_label": "round win %", "y_fmt": "pct", "x_reverse": False,
                  "ref": {"y": 0.5, "label": "even"}, "mark": None, "series": series},
    }
    obj["_detail"] = {"matchups_ct_win": {f"CT {LVLNAME[c]} v T {LVLNAME[t]}": [r3(x) for x in e[:3]] + [e[3]]
                                          for (c, t), e in sorted(mt.items()) if e[3] >= 50},
                      "crossover_k": r3(cross)}
    return obj


# ---------- study 3: pistol round value ----------
def study_pistol_value(maps):
    recs = []
    for m in maps:
        R = m["rounds"]
        p1, p2 = R[0][1], R[12][1]
        for team in m["names"]:
            recs.append({"map": m["id"], "side1": R[0][0][team][SIDE], "p1": int(p1 == team), "p2": int(p2 == team),
                         "win": int(m["winner"] == team), "elo": m["elo"].get(team), "begin": m["begin"]})
    # one row per map: use the first-pistol winner
    cats = []
    rows1 = [r for r in recs if r["p1"] == 1]

    def wl(rs):
        k = sum(r["win"] for r in rs)
        e = wilson(k, len(rs))
        exp = [r["elo"] for r in rs if r["elo"] is not None]
        excess = (sum(r["win"] for r in rs if r["elo"] is not None) - sum(exp)) / max(1, len(exp))
        return e, len(rs), excess
    groups = [
        ("P1 won on CT", [r for r in rows1 if r["side1"] == "CT"]),
        ("P1 won on T", [r for r in rows1 if r["side1"] == "T"]),
        ("P2 won on CT", [r for r in recs if r["p2"] == 1 and r["side1"] == "T"]),
        ("P2 won on T", [r for r in recs if r["p2"] == 1 and r["side1"] == "CT"]),
        ("both pistols", [r for r in recs if r["p1"] == 1 and r["p2"] == 1]),
        ("split, won P1", [r for r in rows1 if r["p2"] == 0]),
    ]
    pts, res = [], {}
    for lab, rs in groups:
        e, n, ex = wl(rs)
        res[lab] = (e, n, ex)
        pts.append({"x": lab, "y": r3(e[0]), "lo": r3(e[1]), "hi": r3(e[2]), "n": n})
    # Elo-adjusted logistic: map win ~ p1 + p2 + elo logit, one row per team-map (cluster by map)
    X = [[1, r["p1"], r["p2"], math.log(min(max(r["elo"], .02), .98) / (1 - min(max(r["elo"], .02), .98)))]
         for r in recs if r["elo"] is not None]
    y = [r["win"] for r in recs if r["elo"] is not None]
    cl = [r["map"] for r in recs if r["elo"] is not None]
    b, V = logit_fit(X, y, cl)
    me1 = marginal_effect(X, b, V, 1)
    me2 = marginal_effect(X, b, V, 2)
    mid = half_split(maps)
    sp = [wl([r for r in rows1 if (r["begin"] < mid) == early]) for early in (True, False)]
    n = len(maps)
    a, bb = res["P1 won on CT"], res["P1 won on T"]
    obj = {
        "id": "cs2-pistol-value", "sport": "CS2",
        "question": "How much is the first pistol round worth, and does the side matter?",
        "answer": (f"First pistol winner takes the map {pct(wl(rows1)[0][0])}: {pct(a[0][0])} on CT, {pct(bb[0][0])} "
                   f"on T."),
        "findings": [
            f"Pistol 1 won on CT: map win {pct(a[0][0])} ({pct(a[0][1])}-{pct(a[0][2])}, n={a[1]:,}).",
            f"Pistol 1 won on T: map win {pct(bb[0][0])} ({pct(bb[0][1])}-{pct(bb[0][2])}, n={bb[1]:,}).",
            f"Both pistols: {pct(res['both pistols'][0][0])} map win (n={res['both pistols'][1]:,}). "
            f"Split pistols, P1 winner: {pct(res['split, won P1'][0][0])}.",
            f"Above Elo expectation: P1 on T {pp(bb[2])}, on CT {pp(a[2])}. Win vs lose P1, Elo-adjusted: {pp(me1[0])} "
            f"({pp(me1[1])[:-3]} to {pp(me1[2])}).",
        ],
        "method": ("Map win % for pistol round winners (rounds 1 and 13), Wilson CIs. Team strength: logistic model "
                   "with pre-map Elo; pistol effects as average marginal change, map-clustered CIs."),
        "data": data_line(maps),
        "n": n, "robust": bool(me1[1] > 0), "interest": 4,
        "split_check": (f"P1 winner map win: early {pct(sp[0][0][0])} (n={sp[0][1]:,}), late {pct(sp[1][0][0])} "
                        f"(n={sp[1][1]:,})."),
        "chart": {"type": "bar", "title": "Map win % after winning a pistol round", "x_label": "pistol result",
                  "y_label": "map win %", "y_fmt": "pct", "x_reverse": False, "ref": {"y": 0.5, "label": "50%"},
                  "mark": None, "series": [{"name": "pistol winner", "points": pts}]},
    }
    obj["_detail"] = {"elo_excess": {k: r3(v[2]) for k, v in res.items()}, "me_p1": [r3(x) for x in me1],
                      "me_p2": [r3(x) for x in me2], "coef": [r3(x) for x in b]}
    return obj


# ---------- study 3b: CT-first vs T-first per map (shown from the T-first team) ----------
def study_side_first(maps):
    bym = defaultdict(list)
    for m in maps:
        R = m["rounds"]
        ctf = next(t for t, s in m["first"].items() if s == "CT")
        p = m["elo"].get(ctf)
        bym[m["map"]].append((int(m["winner"] != ctf), None if p is None else 1 - p, m["begin"]))
    pts, rows = [], []
    allr = [r for v in bym.values() for r in v]
    for mp, rs in sorted(bym.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < 300:
            continue
        k = sum(r[0] for r in rs)
        e = wilson(k, len(rs))
        el = [r for r in rs if r[1] is not None]
        ex = (sum(r[0] for r in el) - sum(r[1] for r in el)) / max(1, len(el))
        rows.append((mp, e, len(rs), ex))
    rows.sort(key=lambda r: -r[1][0])
    for mp, e, n, ex in rows:
        pts.append({"x": mp.replace("de_", ""), "y": r3(e[0]), "lo": r3(e[1]), "hi": r3(e[2]), "n": n})
    k = sum(r[0] for r in allr)
    eall = wilson(k, len(allr))
    sig = [r for r in rows if r[1][1] > 0.5 or r[1][2] < 0.5]
    mid = half_split(maps)
    sp = []
    for early in (True, False):
        rs = [r for r in allr if (r[2] < mid) == early]
        sp.append((wilson(sum(r[0] for r in rs), len(rs)), len(rs)))
    best, worst = rows[0], rows[-1]
    obj = {
        "id": "cs2-side-first", "sport": "CS2",
        "question": "Which side should a team start on, map by map?",
        "answer": (f"Start T. T-first teams win {pct(eall[0])} of maps; {pct(best[1][0])} on {best[0][3:]}, "
                   f"{pct(worst[1][0])} on {worst[0][3:]}."),
        "findings": [
            f"All maps: T-first team wins {pct(eall[0])} ({pct(eall[1])}-{pct(eall[2])}, n={len(allr):,}).",
            f"{best[0][3:]}: T-first {pct(best[1][0])} ({pct(best[1][1])}-{pct(best[1][2])}, n={best[2]:,}).",
            f"{worst[0][3:]}: T-first {pct(worst[1][0])} ({pct(worst[1][1])}-{pct(worst[1][2])}, n={worst[2]:,}).",
            f"CI excludes 50% on {', '.join(r[0][3:] for r in sig) or 'none'}. Elo-adjusted T-first: "
            f"{pp(sum(r[3] * r[2] for r in rows) / sum(r[2] for r in rows))}.",
        ],
        "method": ("Map win % of the team that started T, Wilson CIs. Side choice is not random (pick/veto), so "
                   "Elo-expected wins are subtracted as a check on team strength."),
        "data": data_line(maps),
        "n": len(allr), "robust": bool(sig), "interest": 3,
        "split_check": (f"T-first win %: early {pct(sp[0][0][0])} (n={sp[0][1]:,}), late {pct(sp[1][0][0])} "
                        f"(n={sp[1][1]:,})."),
        "chart": {"type": "bar", "title": "Map win % for the team starting T", "x_label": "map",
                  "y_label": "map win %", "y_fmt": "pct", "x_reverse": False, "ref": {"y": 0.5, "label": "50%"},
                  "mark": None, "series": [{"name": "T first", "points": pts}]},
    }
    obj["_detail"] = {"elo_excess": {r[0]: r3(r[3]) for r in rows}}
    return obj


# ---------- study 4: losing streaks beyond economy ----------
def study_streak(maps):
    """Does a team on a losing streak win the next round less than the economy predicts? (bo3.gg has no timeout
    data, so this is the no-timeout baseline the timeout question needs.)"""
    rows = []
    for m in maps:
        R = m["rounds"]
        streak = {t: 0 for t in m["names"]}
        for i, (tm, w) in enumerate(R):
            rn = i + 1
            if rn > 24:
                break
            if rn in (1, 13):
                streak = {t: 0 for t in m["names"]}
            else:
                for team in m["names"]:
                    if tm[team][SIDE] != "CT":
                        continue  # one row per round, from the CT team's view, plus T view below
                    for me in m["names"]:
                        op = other(m, me)
                        sc_me = sum(1 for _, ww in R[:i] if ww == me)
                        sc_op = i - sc_me
                        rows.append({"map": m["id"], "y": int(w == me), "k": min(streak[me], 6),
                                     "ct": int(tm[me][SIDE] == "CT"), "eq": tm[me][EQ] / 10000,
                                     "oeq": tm[op][EQ] / 10000, "lv": tm[me][LVL], "olv": tm[op][LVL],
                                     "diff": sc_me - sc_op, "elo": elo_logit(m, me), "begin": m["begin"],
                                     "rn": rn})
            for team in m["names"]:
                streak[team] = 0 if w == team else streak[team] + 1
    # baseline model without streak: side x buy-class matchup dummies, equipment, score diff, Elo, round in half
    keys = sorted({(r["ct"], r["lv"], r["olv"]) for r in rows if r["ct"] == 1})
    kidx = {k: i for i, k in enumerate(keys[1:])}

    def feats(r):
        f = [1.0, r["eq"], r["oeq"], r["diff"] / 5, r["elo"], ((r["rn"] - 1) % 12) / 12]
        d = [0.0] * len(kidx)
        k = (r["ct"], r["lv"], r["olv"])
        if k in kidx:
            d[kidx[k]] = 1.0
        return f + d
    X = np.asarray([feats(r) for r in rows])
    y = np.asarray([r["y"] for r in rows], float)
    # each round appears twice (both teams); fit on CT-view rows only for the baseline, predict for both
    ctm = np.asarray([r["ct"] == 1 for r in rows])
    b, _ = logit_fit(X[ctm], y[ctm], [r["map"] for r, c in zip(rows, ctm) if c])
    # symmetric T-view prediction: 1 - P(CT wins) for the same round
    pred = 1 / (1 + np.exp(-X @ b))
    # for T rows, recompute from the CT row of the same round (rows are appended in pairs)
    for i in range(0, len(rows), 2):
        a, c = i, i + 1
        if rows[a]["ct"] == 1:
            pred[c] = 1 - pred[a]
        else:
            pred[a] = 1 - pred[c]
    res = {}
    for k in range(0, 7):
        idx = [i for i, r in enumerate(rows) if r["k"] == k]
        resid = [(rows[i]["map"], rows[i]["y"] - pred[i]) for i in idx]
        e = cluster_rate(resid)
        act = sum(rows[i]["y"] for i in idx) / len(idx)
        res[k] = (e, len(idx), act, float(np.mean(pred[idx])))
    pts = [pt(k, res[k][0], res[k][1]) for k in range(1, 7)]
    mid = half_split(maps)
    sp = []
    for early in (True, False):
        idx = [i for i, r in enumerate(rows) if r["k"] >= 3 and (r["begin"] < mid) == early]
        sp.append((cluster_rate([(rows[i]["map"], rows[i]["y"] - pred[i]) for i in idx]), len(idx)))
    k3 = [i for i, r in enumerate(rows) if r["k"] >= 3]
    e3 = cluster_rate([(rows[i]["map"], rows[i]["y"] - pred[i]) for i in k3])
    n = len(rows) // 2

    def f(k):
        e, nn, act, pr = res[k]
        return (f"After {k} loss{'es' if k > 1 else ''} in a row: wins {pct(act)}, model {pct(pr)}, gap {pp(e[0])} "
                f"({pp(e[1])[:-3]} to {pp(e[2])}, n={nn:,}).")
    obj = {
        "id": "cs2-loss-streak", "sport": "CS2",
        "question": "Does a losing streak hurt the next round beyond economy (the no-timeout baseline)?",
        "answer": (("No tilt. " if e3[0] > -0.005 else "")
                   + f"After 3+ straight losses a team wins {100 * e3[0]:+.1f} pp vs an economy and score model."),
        "findings": [f(1), f(3), f(5),
                     "bo3.gg round data has no timeout calls, so the timeout effect itself is not measured."],
        "method": ("Logistic baseline on buy-class matchup by side, equipment values, score gap, Elo and round in half; "
                   "actual minus predicted win rate by current losing streak in the half, map-clustered CIs."),
        "data": data_line(maps, f", {n:,} rounds"),
        "n": n, "robust": None, "interest": 3,
        "split_check": (f"3+ streak gap: early {pp(sp[0][0][0])} (n={sp[0][1]:,}), late {pp(sp[1][0][0])} "
                        f"(n={sp[1][1]:,})."),
        "chart": {"type": "line", "title": "Next-round win vs economy model, by losing streak",
                  "x_label": "rounds lost in a row", "y_label": "actual minus expected", "y_fmt": "signed",
                  "x_reverse": False, "ref": {"y": 0, "label": "model"}, "mark": None,
                  "series": [{"name": "losing team", "points": pts}]},
    }
    obj["robust"] = bool(e3[1] > 0 or e3[2] < 0) and all(
        (s[0][1] > 0 or s[0][2] < 0) and math.copysign(1, s[0][0]) == math.copysign(1, e3[0]) for s in sp)
    obj["_detail"] = {str(k): {"gap": [r3(x) for x in v[0][:3]], "n": v[1], "actual": r3(v[2]), "pred": r3(v[3])}
                      for k, v in res.items()}
    return obj


def main():
    maps = load()
    only = set(sys.argv[1:])
    if not only or "1" in only:
        o, recs, res, split = study_pistol_loser(maps)
        ct, t = res["CT"], res["T"]
        o["robust"] = bool((ct["map"][1] > 0 or ct["map"][2] < 0) and all(
            math.copysign(1, split[k]["CT"][0]) == math.copysign(1, ct["map"][0]) for k in split))
        save(o)
    if not only or "2" in only:
        save(study_equipment(maps))
    if not only or "3" in only:
        save(study_pistol_value(maps))
        save(study_side_first(maps))
    if not only or "4" in only:
        save(study_streak(maps))


if __name__ == "__main__":
    main()
