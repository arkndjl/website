#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CS2 prospects from lower tiers (Nov 23 2026): can the prospect grade (scripts/cs2_players.py prospect_fit) take
players the live list leaves out, point in time and held out?

    python3 scripts/cs2_prospects_lowtier_research.py     # -> data/cs2_prospects_lowtier_research.json (~3 min)

A. bo3.gg lower tiers. The live prospect pool needs 1,000+ rounds in the last year (about 45 maps). Bands tested:
   300-599 and 600-999 rounds, and by where a player's rounds came from (mostly C/D-tier events vs not).
   For each band, the kept prospect model (rating + age + S/A share), fit on the tune cutoffs of the live pool, grades
   the band's held rows; scored against the band's own tune mean (a constant), with the bias and the slope of the
   outcome on the grade. A band passes when the grade beats the constant (held t < -2) and its bias is not
   significant (|t| < 2); otherwise a band-term refit is tried (fit on tune, scored on held, must not hurt the
   live pool's rows).
B. ESEA (NA, FACEIT box lines). ESEA players found on bo3.gg (nickname key + 2 of the same five on one bo3.gg team,
   or the team name) with 600+ bo3.gg rounds in the year after a cutoff: their ESEA RWA and division at the cutoff
   (scripts/esea_rwa_research.py ratings) against that later pro-scale rating. Scored against the band constant
   (ESEA-only players' mean later rating) on the held cutoffs. Too few rows (<60 held) = not gradable.
Outcome target and cutoffs as prospect_fit: rating over the next 12 months, opponent-credited, 600+ rounds.
"""
import datetime as dt
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_players as CP  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_prospects_lowtier_research.json"
BANDS = [("1000+ (live pool)", 1000, 1e9), ("600-999", 600, 1000), ("300-599", 300, 600)]


def tstat(d):
    d = np.asarray(d, float)
    return round(float(d.mean() / (d.std() + 1e-12) * math.sqrt(len(d))), 2) if len(d) > 1 else None


def wmean(x, w):
    return float((x * w).sum() / w.sum())


def cutoffs(M):
    last = int(M.gd.max())
    cuts, d = [], dt.date(2024, 10, 1)
    while d.toordinal() + 365 <= last:
        cuts.append(d.toordinal())
        d = (d + dt.timedelta(days=92)).replace(day=1)
    return cuts


def rows_at(M, c, p, T, pdir):
    """Every player under T1_MAPS S-tier maps with 300+ rounds in the last year and a map in the last 120 days."""
    th, _ = CP.ratings(M, c, T, p)
    _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
    sm = CP.s_maps(M, T)
    lastd = np.zeros(len(M.pids))
    m = M.d < T
    np.maximum.at(lastd, M.p[m], M.d[m])
    ok = (sm < CP.T1_MAPS) & (r12 >= 300) & (lastd >= T - 120)
    i = np.where(ok)[0]
    my = (M.d >= T - 365) & m
    cd = np.bincount(M.p, M.R * my * (M.tier >= 4), len(M.pids)) / np.maximum(r12, 1)
    thF, _ = CP.ratings(M, c, T + 365, p)
    fut, rf = CP.window_stats(M, c, thF, T, T + 365, p)
    age = CP.ages(M, pdir, T)
    ss = CP.sa_share(M, T)
    j = i[rf[i] >= 600]
    return {"T": T, "i": j, "th": th[j], "age": np.nan_to_num(age[j] - 22), "ss": ss[j], "r12": r12[j], "cd": cd[j],
            "y": fut[j], "w": np.minimum(rf[j], 3000)}


def design(R, cols):
    return np.column_stack([np.ones(len(R["y"]))] + [R[k] for k in cols])


def cat(xs):
    return {k: np.concatenate([x[k] for x in xs]) for k in xs[0] if k != "T"}


def sub(R, m):
    return {k: v[m] for k, v in R.items()}


def score(R, pred, const):
    e, e0, w = R["y"] - pred, R["y"] - const, R["w"]
    dl = w * (e * e - e0 * e0)
    bias = w * e
    sl = np.polyfit(pred, R["y"], 1, w=np.sqrt(w))[0] if len(pred) > 2 else None
    return {"n": int(len(e)), "mse": round(wmean(e * e, w), 4), "mseConst": round(wmean(e0 * e0, w), 4), "t": tstat(dl),
            "bias": round(wmean(e, w), 3), "tBias": tstat(bias), "slope": None if sl is None else round(float(sl), 3)}


def part_a(M, c, p, pdir, cols):
    data = [rows_at(M, c, p, T, pdir) for T in cutoffs(M)]
    tune = cat([x for x in data if dt.date.fromordinal(x["T"]).isoformat() < CP.HELD[0]])
    held = cat([x for x in data if dt.date.fromordinal(x["T"]).isoformat() >= CP.HELD[0]])
    live = tune["r12"] >= 1000
    b = CP.ols(design(sub(tune, live), cols), tune["y"][live], tune["w"][live])
    out = {"cols": cols, "b": [round(float(v), 4) for v in b], "cuts": [dt.date.fromordinal(x["T"]).isoformat() for x in data],
           "bands": {}, "tiers": {}}
    for nm, lo, hi in BANDS:
        mt, mh = (tune["r12"] >= lo) & (tune["r12"] < hi), (held["r12"] >= lo) & (held["r12"] < hi)
        H = sub(held, mh)
        const = wmean(tune["y"][mt], tune["w"][mt])
        out["bands"][nm] = score(H, design(H, cols) @ b, const)
    for nm, f in (("mostly C/D-tier rounds", lambda R: R["cd"] >= 0.5), ("mostly B-tier or higher", lambda R: R["cd"] < 0.5)):
        for bn, lo, hi in BANDS[:2] + [("300-999", 300, 1000)]:
            mt = f(tune) & (tune["r12"] >= lo) & (tune["r12"] < hi)
            mh = f(held) & (held["r12"] >= lo) & (held["r12"] < hi)
            if mh.sum() < 10 or mt.sum() < 10:
                continue
            H = sub(held, mh)
            out["tiers"][f"{nm}, {bn}"] = score(H, design(H, cols) @ b, wmean(tune["y"][mt], tune["w"][mt]))
    # band vs live pool: the held period runs above every grade (level drift); a band is only off if its residual
    # differs from the live pool's (Welch t on the weighted residuals)
    ph = held["r12"] >= 1000
    e_all = held["y"] - design(held, cols) @ b
    for nm, lo, hi in BANDS[1:] + [("300-999", 300, 1000)]:
        mh = (held["r12"] >= lo) & (held["r12"] < hi)
        a1, a2 = e_all[mh], e_all[ph]
        w1, w2 = held["w"][mh], held["w"][ph]
        m1, m2 = wmean(a1, w1), wmean(a2, w2)
        v1, v2 = wmean((a1 - m1) ** 2, w1) / len(a1), wmean((a2 - m2) ** 2, w2) / len(a2)
        out["bands"].setdefault(nm, {})["dBiasVsLive"] = round(m1 - m2, 3)
        out["bands"][nm]["tDBias"] = round((m1 - m2) / math.sqrt(v1 + v2), 2)
    # spread correction for thin samples: pred = kept + g x lr x (th - the band's tune mean th), g fit on tune
    # 300-999 rows, scored on held 300-999 rows against the kept grade
    for R in (tune, held):
        R["lr"] = np.log(1000 / np.minimum(R["r12"], 1000))
    mt, mh = tune["r12"] < 1000, held["r12"] < 1000
    thm = wmean(tune["th"][mt], tune["w"][mt])
    T_, H_ = sub(tune, mt), sub(held, mh)
    zt = T_["lr"] * (T_["th"] - thm)
    rt = T_["y"] - design(T_, cols) @ b
    g = float((T_["w"] * zt * rt).sum() / (T_["w"] * zt * zt).sum())
    zh = H_["lr"] * (H_["th"] - thm)
    e1 = H_["y"] - design(H_, cols) @ b
    e2 = e1 - g * zh
    out["spread"] = {"g": round(g, 4), "thMean": round(thm, 4), "n": int(mh.sum()), "mseKept": round(wmean(e1 * e1, H_["w"]), 4),
                     "mseSpread": round(wmean(e2 * e2, H_["w"]), 4), "t": tstat(H_["w"] * (e2 * e2 - e1 * e1)),
                     "slopeAfter": round(float(np.polyfit(H_["y"] - e2, H_["y"], 1, w=np.sqrt(H_["w"]))[0]), 3)}
    # refit on the 300+ pool with a low-rounds term: log(1000 / rounds) above 0 below 1,000 rounds
    b2 = CP.ols(design(tune, cols + ["lr"]), tune["y"], tune["w"])
    out["refit"] = {"cols": cols + ["lr"], "b": [round(float(v), 4) for v in b2]}
    for nm, m in (("all 300+", np.ones(len(held["y"]), bool)), ("live pool", held["r12"] >= 1000),
                  ("300-999", held["r12"] < 1000)):
        H = sub(held, m)
        e1, e2 = H["y"] - design(H, cols) @ b, H["y"] - design(H, cols + ["lr"]) @ b2
        out["refit"][nm] = {"n": int(m.sum()), "mseKept": round(wmean(e1 * e1, H["w"]), 4),
                            "mseRefit": round(wmean(e2 * e2, H["w"]), 4), "t": tstat(H["w"] * (e2 * e2 - e1 * e1)),
                            "biasRefit": round(wmean(e2, H["w"]), 3), "tBias": tstat(H["w"] * e2)}
    return out


def esea_ids(M):
    """FACEIT player id -> bo3.gg player index: same nickname key, confirmed by 2+ ESEA teammates on one bo3.gg team
    (same key, same team id) or a team-name key match."""
    import esea_rwa_research as R  # noqa: F401
    e = json.load(gzip.open(ROOT / "research" / "esea_regions.json.gz"))
    nick, teams, mates = defaultdict(set), defaultdict(set), defaultdict(set)
    for m in e["matches"]:
        if m.get("region") != "NA":
            continue
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
    bt = defaultdict(set)           # (nick key) -> {(player index, team id)}
    tn = {}
    import cs2_bo3
    bo3 = cs2_bo3.Bo3()
    for r in bo3.mt.values():
        tn[r[2]], tn[r[3]] = names.key(r[4] or ""), names.key(r[5] or "")
    for pi, tid in set(zip(M.p.tolist(), M.team.tolist())):
        bt[names.key(M.nick.get(M.pids[pi]) or "")].add((pi, tid))
    out = {}
    for fid, ks in nick.items():
        cand = {(pi, tid) for k in ks if k for pi, tid in bt.get(k, ())}
        if not cand:
            continue
        ok = set()
        for pi, tid in cand:
            mate_hit = sum(1 for o in mates[fid] if any((x, tid) in bt.get(k, ()) for k in nick.get(o, ()) if k
                                                         for x in [y for y, t2 in bt.get(k, ()) if t2 == tid]))
            if mate_hit >= 2 or tn.get(tid) in teams[fid]:
                ok.add(pi)
        if len(ok) == 1:
            out[fid] = ok.pop()
    return out


def part_b(M, c, p, pdir):
    import esea_rwa_research as R
    ids = esea_ids(M)
    res = {"matched": len(ids)}
    ms = json.load(gzip.open(R.SR.ARCHIVE if hasattr(R.SR, "ARCHIVE") else ROOT / "research" / "esea_matches.json.gz"))
    # ESEA rating at each cutoff: rounds-weighted mean of the player's FACEIT RWA lines over the prior year
    # (fit's stat weights), plus his rounds-weighted division level (Open -2 .. Advanced +1)
    fitp = json.load(open(ROOT / "data" / "esea_rwa_fit.json"))
    beta = fitp.get("beta") or fitp.get("weights")
    DIV = {"Open9-10": -2, "Open1-8": -1.5, "Intermediate": -1, "Main": 0, "Advanced": 1}
    lines = defaultdict(list)       # fid -> [(day ordinal, rounds, division level, stat line per round)]
    for m in ms["matches"]:
        if not m.get("at"):
            continue
        day = dt.date.fromtimestamp(m["at"]).toordinal()
        for mp in m.get("maps") or []:
            rr = (mp.get("s1") or 0) + (mp.get("s2") or 0)
            if not rr:
                continue
            for side in ("p1", "p2"):
                for q in mp.get(side) or []:
                    if q[0] in ids:
                        x = R.line(q)
                        if x:
                            lines[q[0]].append((day, rr, DIV.get(m["div"], 0), x))
    res["withBox"] = len(lines)
    rows = []
    for T in cutoffs(M):
        thF, _ = CP.ratings(M, c, T + 365, p)
        fut, rf = CP.window_stats(M, c, thF, T, T + 365, p)
        th, _ = CP.ratings(M, c, T, p)
        _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
        for fid, L in lines.items():
            pi = ids[fid]
            L0 = [x for x in L if T - 365 <= x[0] < T]
            rnd = sum(x[1] for x in L0)
            if rnd < 300 or rf[pi] < 600:
                continue
            tot = np.sum([np.array(x[3], float) for x in L0], 0)
            kd = (tot[0] - tot[1]) / rnd
            dv = sum(x[1] * x[2] for x in L0) / rnd
            rows.append({"T": T, "fid": fid, "kd": kd, "dv": dv, "pro": r12[pi], "th": th[pi], "y": fut[pi],
                         "w": min(rf[pi], 3000)})
    res["rows"] = len(rows)
    held = [r for r in rows if dt.date.fromordinal(r["T"]).isoformat() >= CP.HELD[0]]
    tune = [r for r in rows if dt.date.fromordinal(r["T"]).isoformat() < CP.HELD[0]]
    res["nTune"], res["nHeld"] = len(tune), len(held)
    res["esea_only_held"] = sum(1 for r in held if r["pro"] < 300)
    if len(tune) >= 30 and len(held) >= 10:
        def XY(rs):
            return (np.array([[1, r["kd"], r["dv"]] for r in rs]), np.array([r["y"] for r in rs]),
                    np.array([r["w"] for r in rs], float))
        X, y, w = XY(tune)
        b = CP.ols(X, y, w)
        Xh, yh, wh = XY(held)
        e, e0 = yh - Xh @ b, yh - wmean(y, w)
        res["fit"] = {"b": [round(float(v), 4) for v in b], "mse": round(wmean(e * e, wh), 4),
                      "mseConst": round(wmean(e0 * e0, wh), 4), "t": tstat(wh * (e * e - e0 * e0))}
    # floor check: matched ESEA players' FV on their next-year bo3.gg rating (600+ rounds), by best ESEA division,
    # at the last held cutoff. FV scale = today's Tier-1 starters (data/cs2_players.json board, tier 1)
    best = defaultdict(lambda: -9)
    for m in ms["matches"]:
        for mp in m.get("maps") or []:
            for side in ("p1", "p2"):
                for q in mp.get(side) or []:
                    if q[0] in ids:
                        best[q[0]] = max(best[q[0]], DIV.get(m["div"], 0))
    T = ordt = max(t for t in cutoffs(M))
    thN, _ = CP.ratings(M, c, dt.date.today().toordinal() + 1, p)
    idx = {int(x): i for i, x in enumerate(M.pids)}
    t1 = [idx[r["id"]] for r in json.load(open(ROOT / "data" / "cs2_players.json"))["board"] if r["tier"] == 1 and r["id"] in idx]
    mu1, sd1 = float(thN[t1].mean()), float(thN[t1].std())
    thF, _ = CP.ratings(M, c, T + 365, p)
    fut, rf = CP.window_stats(M, c, thF, T, T + 365, p)
    res["floor"] = {"cut": dt.date.fromordinal(ordt).isoformat()}
    inv = {v: k for k, v in DIV.items()}
    for lv in sorted({best[f] for f in ids if f in best}):
        fv = np.array([50 + 10 * (fut[pi] - mu1) / sd1 for f, pi in ids.items() if best.get(f) == lv and rf[pi] >= 600])
        if len(fv):
            res["floor"][inv.get(lv, "none")] = {"n": int(len(fv)), "p50": round(float(np.median(fv)), 1),
                                                 "p90": round(float(np.percentile(fv, 90)), 1),
                                                 "atFloor": round(float((fv <= 20).mean()), 2)}
    res["gradable"] = bool(res.get("fit") and res["nHeld"] >= 60 and res["fit"]["t"] is not None and res["fit"]["t"] < -2)
    del rows
    return res


def main():
    fitj = json.loads(CP.FIT.read_text())
    p = fitj["params"]
    M = CP.Maps()
    beta = np.array([fitj["beta"][k] for k in CP.STATS])
    c = CP.contributions(M, beta, np.array(fitj["mline"]), p.get("pm", 0.0))
    pdir = CP.load_pdir()
    keep = fitj["prospects"]["models"][fitj["prospects"]["keep"]]["cols"]
    out = {"asof": dt.date.today().isoformat(), "A": part_a(M, c, p, pdir, keep)}
    print(json.dumps(out["A"], indent=1), file=sys.stderr)
    try:
        out["B"] = part_b(M, c, p, pdir)
    except Exception as ex:  # noqa: BLE001
        out["B"] = {"error": repr(ex)[:300]}
    print(json.dumps(out["B"], indent=1), file=sys.stderr)
    # LAURSEN_111 (NA ESEA, no bo3.gg maps): ESEA can't be graded on the pro scale, so a provisional floor grade
    out["laursen"] = {"fv": 20, "prov": True, "why": "ESEA is not gradable on the pro scale (held rows %s, no tune rows); "
                      "%d%% of NA ESEA Advanced players who went on to 600+ bo3.gg rounds graded at the 20 floor the next year"
                      % (out["B"].get("nHeld"), round(100 * ((out["B"].get("floor") or {}).get("Advanced") or {}).get("atFloor", 0)))}
    OUT.write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
