#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Drivers for provisional (ESEA-only) CS2 prospects: pre-registered test (scripts/research/cs2_prov_nov23/PREREG.md).

    python3 scripts/cs2_prov_research.py      # -> data/cs2_prov_research.json

Rows: an ESEA league player (any region, Intermediate/Main/Advanced) at the end of season s with under 300 bo3.gg rounds
in the year before, linked to a bo3.gg player, who plays 600+ bo3.gg rounds in the year after. Target = the pro
prospect target (opponent-credited rating over that year). Nested specs S1 (division, region) .. S4 (FACEIT level) and
S5 (NA box K-D percentile in the division), tune seasons <= 52, held 53-54, player-clustered t, Holm over 5.
"""
import datetime as dt
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_players as CP  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_prov_research.json"
LV = {"Intermediate": -1, "Main": 0, "Advanced": 1}
HELD = (53, 54)
SPECS = {
    "S1": ["lv", "eu", "lv_eu"],
    "S2": ["lv", "eu", "lv_eu", "rs", "po", "pw", "top3"],
    "S3": ["lv", "eu", "lv_eu", "rs", "po", "pw", "top3", "up", "down", "exp"],
    "S4": ["lv", "eu", "lv_eu", "rs", "po", "pw", "top3", "up", "down", "exp", "sk", "dsk"],
}


def load(name):
    p = ROOT / "research" / name
    try:
        return json.load(gzip.open(p))
    except (OSError, ValueError):
        return None


def regions():
    ms = []
    for f in ("esea_regions_early.json.gz", "esea_regions.json.gz"):
        d = load(f)
        if d:
            ms += d["matches"]
    seen, out = set(), []
    for m in ms:
        if m["id"] not in seen and m.get("at") and m.get("div") in LV:
            seen.add(m["id"])
            out.append(m)
    return out


def boxes():
    ms = []
    for f in ("esea_matches_early.json.gz", "esea_matches.json.gz"):
        d = load(f)
        if d:
            ms += d["matches"]
    seen, out = set(), []
    for m in ms:
        if m["id"] not in seen and m.get("at"):
            seen.add(m["id"])
            out.append(m)
    return out


def link(M, ms):
    """FACEIT id -> bo3.gg player index (cs2_prospects_lowtier_research.esea_ids, over every season's matches)."""
    import cs2_bo3
    nick, teams, mates = defaultdict(set), defaultdict(set), defaultdict(set)
    for m in ms:
        for f in ("f1", "f2"):
            ros = [q for q in m[f]["roster"] if len(q) > 2]
            for q in ros:
                nick[q[0]].update(names.key(x) for x in q[1:3] if x)
                teams[q[0]].add(names.key(m[f]["name"]))
                mates[q[0]].update(r[0] for r in ros if r[0] != q[0])
    try:
        for k, v in json.load(open(ROOT / "data" / "esea_rwa.json"))["names"].items():
            nick[k].add(names.key(v))
    except (OSError, ValueError, KeyError):
        pass
    bo3 = cs2_bo3.Bo3()
    tn = {}
    for r in bo3.mt.values():
        tn[r[2]], tn[r[3]] = names.key(r[4] or ""), names.key(r[5] or "")
    bt = defaultdict(set)
    for pi, tid in set(zip(M.p.tolist(), M.team.tolist())):
        bt[names.key(M.nick.get(M.pids[pi]) or "")].add((pi, tid))
    out = {}
    for fid, ks in nick.items():
        cand = {(pi, tid) for k in ks if k for pi, tid in bt.get(k, ())}
        ok = set()
        for pi, tid in cand:
            hit = 0
            for o in mates[fid]:
                if any((pj, tid) in bt.get(k, ()) for k in nick.get(o, ()) if k for pj, _ in bt.get(k, ())):
                    hit += 1
                    if hit >= 2:
                        break
            if hit >= 2 or tn.get(tid) in teams[fid]:
                ok.add(pi)
        if len(ok) == 1:
            out[fid] = ok.pop()
    return out


def features(ms, bx):
    """(fid, season) -> feature dict, season end days, NA box percentile per (fid, season)."""
    day = lambda m: m["at"]  # noqa: E731  (seconds: exit order inside a bracket)
    end = defaultdict(int)
    for m in ms:
        end[m["season"]] = max(end[m["season"]], dt.date.fromtimestamp(m["at"]).toordinal())
    pl = defaultdict(lambda: defaultdict(lambda: {"n": 0, "lv": -9, "rg": Counter(), "tm": Counter(), "sk": []}))
    team_rs = defaultdict(lambda: [0, 0])          # (season, team id) -> [rounds for, rounds total] regular season
    po = defaultdict(lambda: defaultdict(int))     # (season, region, div, stage) -> team -> playoff wins
    po_last = {}
    for m in ms:
        s, f1, f2 = m["season"], m["f1"], m["f2"]
        if "bye" in (f1["id"], f2["id"]):
            continue
        sc = m.get("score") or {}
        a, b = sc.get("faction1") or 0, sc.get("faction2") or 0
        playoff = "playoff" in (m.get("stage") or "").lower()
        if not playoff and m.get("bo", 1) == 1 and a + b >= 13:
            for f, x in (("f1", a), ("f2", b)):
                team_rs[(s, m[f]["id"])][0] += x
                team_rs[(s, m[f]["id"])][1] += a + b
        if playoff:
            k = (s, m.get("region"), m["div"], m["stage"])
            for f in ("f1", "f2"):
                po[k][m[f]["id"]] += 0
                po_last[(k, m[f]["id"])] = max(po_last.get((k, m[f]["id"]), 0), day(m))
            w = {"faction1": "f1", "faction2": "f2"}.get(m.get("winner"))
            if w:
                po[k][m[w]["id"]] += 1
        for f in ("f1", "f2"):
            for q in m[f]["roster"]:
                r = pl[q[0]][s]
                r["n"] += 1
                r["lv"] = max(r["lv"], LV[m["div"]])
                r["rg"][m.get("region")] += 1
                r["tm"][(m[f]["id"], m["div"])] += 1
                lvl = q[3] if len(q) > 3 else q[-1]
                if isinstance(lvl, (int, float)) and lvl > 0:
                    r["sk"].append(lvl)
    # playoff results per team: made, wins, top 3 (the last three teams standing in its bracket). A
    # bracket = teams joined by playoff matches inside (season, region, division, stage): conferences split apart.
    par = {}

    def root(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for m in ms:
        if "playoff" in (m.get("stage") or "").lower() and "bye" not in (m["f1"]["id"], m["f2"]["id"]):
            k = (m["season"], m.get("region"), m["div"], m["stage"])
            par[root((k, m["f1"]["id"]))] = root((k, m["f2"]["id"]))
    br = defaultdict(dict)
    for k, tw in po.items():
        for t, v in tw.items():
            br[root((k, t))][t] = v
    pres = {}
    for rt, tw in br.items():
        k = rt[0]
        rk = sorted(tw, key=lambda t: (-po_last[(k, t)], -tw[t]))   # last three standing: latest exit first
        for j, t in enumerate(rk):
            o = pres.setdefault((k[0], t), {"po": 1, "pw": 0, "top3": 0})
            o["pw"] = max(o["pw"], tw[t])
            o["top3"] = max(o["top3"], int(j < 3))
    # NA box K-D per round percentile within (season, division), players with 100+ rounds
    kd = defaultdict(lambda: [0.0, 0])
    for m in bx:
        for mp in m.get("maps") or []:
            rr = (mp.get("s1") or 0) + (mp.get("s2") or 0)
            if rr < 13:
                continue
            for side in ("p1", "p2"):
                for q in mp.get(side) or []:
                    x = kd[(q[0], m["season"], m["div"])]
                    x[0] += (q[1] or 0) - (q[2] or 0)
                    x[1] += rr
    pct = {}
    grp = defaultdict(list)
    for (fid, s, dv), (v, r) in kd.items():
        if r >= 100 and dv in LV:
            grp[(s, dv)].append((v / r, fid))
    for (s, dv), xs in grp.items():
        xs.sort()
        for j, (_, fid) in enumerate(xs):
            pct[(fid, s)] = max(pct.get((fid, s), 0), (j + 0.5) / len(xs))
    F = {}
    for fid, ss in pl.items():
        for s, r in ss.items():
            if r["n"] < 3:
                continue
            (tid, _), _ = max(r["tm"].items(), key=lambda kv: (LV[kv[0][1]], kv[1]))
            rf, rt = team_rs.get((s, tid), (0, 0))
            p = pres.get((s, tid), {"po": 0, "pw": 0, "top3": 0})
            prev = ss.get(s - 1)
            sk = float(np.mean(r["sk"])) if r["sk"] else None
            psk = float(np.mean(prev["sk"])) if prev and prev["sk"] else None
            eu = int(r["rg"].most_common(1)[0][0] == "EU")
            F[(fid, s)] = {"lv": r["lv"], "eu": eu, "lv_eu": r["lv"] * eu, "rs": (rf / rt - 0.5) if rt else 0.0,
                           "po": p["po"], "pw": math.log1p(p["pw"]), "top3": p["top3"],
                           "up": int(bool(prev) and r["lv"] > prev["lv"]), "down": int(bool(prev) and r["lv"] < prev["lv"]),
                           "exp": sum(1 for t in range(s - 3, s) if t in ss and ss[t]["n"] >= 3),
                           "sk": sk, "dsk": (sk - psk) if sk is not None and psk is not None else 0.0,
                           "na": int(r["rg"].most_common(1)[0][0] == "NA"), "kdp": pct.get((fid, s))}
    return F, end


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std(ddof=1) + 1e-12) * math.sqrt(len(d))), 2) if len(d) > 2 else None


def wmean(x, w):
    return float((x * w).sum() / w.sum())


def design(R, cols, fill):
    return np.column_stack([np.ones(len(R))] + [np.array([fill[k] if r[k] is None else r[k] for r in R], float)
                                                 for k in cols])


def compare(tune, held, ca, cb):
    """Spec cb against spec ca (ca=None = tune mean): held loss diff clustered by player."""
    fill = {"sk": float(np.mean([r["sk"] for r in tune if r["sk"] is not None] or [10])), "kdp": 0.5}
    y, w = np.array([r["y"] for r in tune]), np.array([r["w"] for r in tune])
    yh, wh = np.array([r["y"] for r in held]), np.array([r["w"] for r in held])

    def pred(cols):
        if cols is None:
            return np.full(len(held), wmean(y, w)), None
        b = CP.ols(design(tune, cols, fill), y, w)
        return design(held, cols, fill) @ b, b
    pa, _ = pred(ca)
    pb, b = pred(cb)
    ea, eb = yh - pa, yh - pb
    dl = wh * (eb * eb - ea * ea) / wh.mean()
    cl = defaultdict(float)
    for r, v in zip(held, dl):
        cl[r["fid"]] += v
    t = tstat(list(cl.values()))
    slope = float(np.polyfit(pb, yh, 1, w=np.sqrt(wh))[0]) if np.std(pb) > 1e-9 else None
    return {"n": len(held), "players": len(cl), "mseA": round(wmean(ea * ea, wh), 4), "mseB": round(wmean(eb * eb, wh), 4),
            "t": t, "tBias": tstat(wh * eb / wh.mean()), "slope": None if slope is None else round(slope, 3),
            "b": None if b is None else [round(float(v), 4) for v in b], "fill": fill}


def holm(ps, alpha=0.05):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    ok = [False] * len(ps)
    for j, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - j):
            ok[i] = True
        else:
            break
    return ok


def main():
    fitj = json.loads(CP.FIT.read_text())
    p = fitj["params"]
    M = CP.Maps()
    c = CP.contributions(M, np.array([fitj["beta"][k] for k in CP.STATS]), np.array(fitj["mline"]), p.get("pm", 0.0))
    ms, bx = regions(), boxes()
    ids = link(M, ms)
    F, end = features(ms, bx)
    last = int(M.gd.max())
    out = {"asof": dt.date.today().isoformat(), "seasons": sorted(end), "matches": len(ms), "boxMatches": len(bx),
           "linked": len(ids)}
    rows, rows6 = [], []
    cache = {}
    for s in sorted(end):
        T = end[s] + 1
        if T + 182 > last:
            continue
        th, _ = CP.ratings(M, c, T, p)
        _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
        for H, need, dst in ((365, 600, rows), (182, 300, rows6)):
            if T + H > last:
                continue
            thF, _ = CP.ratings(M, c, T + H, p)
            fut, rf = CP.window_stats(M, c, thF, T, T + H, p)
            for (fid, s2), x in F.items():
                if s2 != s or fid not in ids:
                    continue
                pi = ids[fid]
                if r12[pi] >= 300 or rf[pi] < need:
                    continue
                dst.append(dict(x, fid=fid, s=s, y=float(fut[pi]), w=float(min(rf[pi], 3000))))
        cache[s] = T
    out["rows"] = {"12m": len(rows), "6m": len(rows6),
                   "bySeason": dict(Counter(r["s"] for r in rows)), "byCell": {f"{'EU' if k[0] else 'NA/other'} {k[1]}": v
                   for k, v in Counter((r["eu"], r["lv"]) for r in rows).items()}}
    early = [r for r in rows if r["s"] < HELD[0]]
    if len(early) >= 60:
        tune, held, split = early, [r for r in rows if r["s"] in HELD], "tune S<=52, held S53-54"
    else:
        tune, held, split = [r for r in rows if r["s"] == 53], [r for r in rows if r["s"] == 54], "fallback: tune S53, held S54"
    out["split"], out["nTune"], out["nHeld"] = split, len(tune), len(held)
    res, prev = {}, None
    for nm, cols in SPECS.items():
        res[nm] = compare(tune, held, prev, cols)
        res[nm]["vs"] = "tune mean" if prev is None else [k for k, v in SPECS.items() if v == prev][0]
        prev = cols
    # S5 NA only: S1 + K-D percentile, both fit on NA tune rows with box lines
    nt = [r for r in tune if r["na"] and r["kdp"] is not None]
    nh = [r for r in held if r["na"] and r["kdp"] is not None]
    res["S5"] = compare(nt, nh, ["lv"], ["lv", "kdp"]) if len(nt) >= 15 and len(nh) >= 10 else {"n": len(nh), "nTune": len(nt), "t": None}
    res["S5"]["vs"] = "S1 (NA rows)"
    ps = [0.5 * math.erfc(-(r["t"]) / math.sqrt(2)) if r.get("t") is not None else 1.0 for r in res.values()]
    for (nm, r), ok, pv in zip(res.items(), holm(ps), ps):
        r["p"] = round(pv, 4)
        r["pass"] = bool(ok and r["t"] is not None and r["t"] < -2 and r.get("tBias") is not None and abs(r["tBias"]) < 2
                         and r.get("slope") is not None and 0.5 <= r["slope"] <= 1.5)
    out["specs"] = res
    keep = None
    for nm in ("S1", "S2", "S3", "S4"):
        if res[nm]["pass"]:
            keep = nm
        else:
            break
    out["keep"] = keep
    # robustness: kept (or S1) spec on the 6-month target, same split rule
    sp = keep or "S1"
    t6 = [r for r in rows6 if r["s"] < HELD[0]] if len(early) >= 60 else [r for r in rows6 if r["s"] <= 53]
    h6 = [r for r in rows6 if r["s"] >= HELD[0]] if len(early) >= 60 else [r for r in rows6 if r["s"] > 53]
    if len(t6) >= 30 and len(h6) >= 10:
        out["robust6m"] = {"spec": sp, **{k: v for k, v in compare(t6, h6, None, SPECS[sp]).items() if k != "fill"}}
    # live grades: newest finished season's features, coefficients refit on every row (tune + held) of the kept spec
    th, _ = CP.ratings(M, c, last + 1, p)
    _, r12 = CP.window_stats(M, c, th, last + 1 - 365, last + 1, p)
    t1 = []
    try:
        idx = {int(x): i for i, x in enumerate(M.pids)}
        t1 = [idx[r["id"]] for r in json.load(open(ROOT / "data" / "cs2_players.json"))["board"] if r["tier"] == 1 and r["id"] in idx]
    except (OSError, ValueError, KeyError):
        pass
    mu1, sd1 = (float(th[t1].mean()), float(th[t1].std())) if t1 else (0.0, 1.0)
    fin = max(s for s in end if end[s] + 1 <= dt.date.today().toordinal() - 7 and any(
        "playoff" in (m.get("stage") or "").lower() for m in ms if m["season"] == s))
    out["liveSeason"] = fin
    lf = "laursen"
    try:
        lid = json.load(open(ROOT / "data" / "cs.json")).get("laursenFaceit")
    except (OSError, ValueError):
        lid = None
    if keep:
        allr = tune + held
        cols = SPECS[keep]
        fill = compare(tune, held, None, cols)["fill"]
        b = CP.ols(design(allr, cols, fill), np.array([r["y"] for r in allr]), np.array([r["w"] for r in allr]))
        out["live"] = {"spec": keep, "b": [round(float(v), 4) for v in b], "fill": fill, "mu1": mu1, "sd1": sd1}
        g = []
        a = p["a"]
        for (fid, s), x in F.items():
            if s != fin or (fid in ids and r12[ids[fid]] >= 300):
                continue
            pr = float(design([x], cols, fill) @ b)
            g.append({"fid": fid, "proj": round(a / 2 * (pr - mu1), 2), "fv": CP.fv_of(pr, mu1, sd1)})
        out["grades"] = sorted(g, key=lambda r: -r["proj"])
    # floor share by cell (FV of linked reachers on the pro scale), all rows
    cells = defaultdict(list)
    for r in rows:
        cells[f"{'EU' if r['eu'] else 'NA/other'} {[k for k, v in LV.items() if v == r['lv']][0]}"].append(
            50 + 10 * (r["y"] - mu1) / sd1)
    out["fvByCell"] = {k: {"n": len(v), "p50": round(float(np.median(v)), 1), "p90": round(float(np.percentile(v, 90)), 1),
                           "atFloor": round(float(np.mean(np.array(v) <= 20)), 2)} for k, v in sorted(cells.items())}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "grades"}, indent=1))


if __name__ == "__main__":
    main()
