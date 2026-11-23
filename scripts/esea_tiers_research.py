#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESEA divisions on the pro scale (Nov 23 2026): play every region's ESEA Advanced / Main / Intermediate league
matches (research/esea_regions.json.gz, scripts/esea_regions_fetch.mjs) through the pro player Elo
(scripts/cs2_model.replay) with the pros, bridged by players who appear in both (FACEIT in-game name or nickname
= a Valve / bo3.gg nick, names.key, 4+ characters), then read where each region's divisions sit against Valve's VRS
ranks and bo3.gg's event tiers, and where 1NT ranks.

    python3 scripts/esea_tiers_research.py   # ~15-25 min -> data/esea_tiers_research.json

Pre-registered before any held number was read:
  - Predictive test: ESEA rows update players at K x kxe, kxe in {.25, .5, 1} picked on tune (Aug 2024 - Jun 2025,
    first 70% fit / last 30% scored); scored on the same Valve series as cs2_model.fit (3-term blend). SHIP the
    ESEA rows into the live model only if held log loss improves with t by month <= -2 and top 50 not worse (> +.0005).
  - Descriptive (reported whatever the test says): per season x region x division, the teams' median five-rating
    in the season's second half, the VRS rank whose teams' median rating matches it (same window), and the bo3.gg
    event tier whose teams match it. 1NT: its latest five against today's VRS-ranked teams.
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
import cs2_bo3  # noqa: E402
import cs2_model as M  # noqa: E402
import names  # noqa: E402
from cs2_data import key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "research" / "esea_regions.json.gz"
OUT = ROOT / "data" / "esea_tiers_research.json"
REG = {"NA": "Americas", "SA": "Americas", "EU": "Europe", "MENA": "Europe", "OCE": "Asia", "AS": "Asia"}
ME = "a6e9c61b-de50-47d4-9fc8-3f03a13c4d4a"  # 1NT's FACEIT team id (data/esea.json team.id)


class Vrs2(M.Vrs):
    """Valve's regions, plus each ESEA team's league region."""

    def __init__(self, vrs, ereg):
        super().__init__(vrs)
        self.ereg = ereg

    def region(self, k, date):
        if k in self.ereg:
            return self.ereg[k]
        return super().region(k, date)


def pro_nicks(series):
    out = {}
    for r in series:
        for q in (r[4] or []) + (r[5] or []):
            out.setdefault(names.key(q), q)
    for g in cs2_bo3.map_rosters().values():
        for ros in g.values():
            for q in ros:
                out.setdefault(names.key(q), q)
    return out


def esea_rows(E, pro):
    rows, meta, ereg, bridged = [], {}, {}, defaultdict(lambda: [0, 0])
    for m in E["matches"]:
        if not m.get("at") or m.get("winner") not in ("faction1", "faction2"):
            continue
        side = []
        for f in ("f1", "f2"):
            t = m[f]
            if not t.get("id") or t["id"] == "bye":
                break
            nm = f"esea {m['region']} {t['id'][:13]}"
            k = key(nm)
            meta[k] = {"id": t["id"], "name": t["name"], "region": m["region"]}
            ereg[k] = REG.get(m["region"], "Europe")
            ros = []
            for pid, nick, gname, lvl in t["roster"]:
                hit = next((pro[names.key(c)] for c in (gname, nick) if c and len(names.key(c)) >= 4
                            and names.key(c) in pro), None)
                ros.append(hit or "fc:" + pid)
                b = bridged[(m["season"], m["region"], m["div"])]
                b[0] += 1
                b[1] += hit is not None
            side.append((nm, ros))
        if len(side) < 2 or len(side[0][1]) < 4 or len(side[1][1]) < 4:
            continue
        d = dt.datetime.utcfromtimestamp(m["at"]).date().isoformat()
        rows.append([d, side[0][0], side[1][0], 0 if m["winner"] == "faction1" else 1, side[0][1], side[1][1], "esea",
                     {"season": m["season"], "region": m["region"], "div": m["div"]}])
    return rows, meta, ereg, bridged


def run(series, extra, p, raw, ereg):
    comb = sorted(series + extra, key=lambda r: r[0])
    rows, st = M.replay(comb, Vrs2(H["vrs"], ereg), p, bo3=cs2_bo3.Bo3(raw))
    return rows, st


def score(rows):
    rows = [r for r in rows if r["r"][6] == "vrs"]
    tr = [r for r in rows if M.TUNE[0] <= r["d"] <= M.TUNE[1]]
    he = [r for r in rows if r["d"] >= M.HELD[0]]
    q, _ = M.tiered(tr, he, "blend")
    cut = tr[int(len(tr) * .7)]["d"]
    a, b = [r for r in tr if r["d"] < cut], [r for r in tr if r["d"] >= cut]
    qt, _ = M.tiered(a, b, "blend")
    return M.ll(q, np.array([r["s"] for r in he])), he, float(M.ll(qt, np.array([r["s"] for r in b])).mean())


def bymonth(dl, he):
    mo = defaultdict(list)
    for x, r in zip(dl, he):
        mo[r["d"][:7]].append(x)
    m = np.array([np.mean(v) for _, v in sorted(mo.items())])
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))), int((m < 0).sum()), len(m)


def ladder(rows, vrs, lo, hi):
    """Pro teams in [lo, hi]: median rating per team, with VRS rank (at the window's end) and modal bo3.gg tier."""
    by, tiers = defaultdict(list), defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r["r"][6] != "vrs" or not lo <= r["d"] <= hi:
            continue
        for k, s in ((r["a"], r["sa"]), (r["b"], r["sb"])):
            by[k].append(s)
            if r["tier"]:
                tiers[k][r["tier"]] += 1
    out = []
    for k, v in by.items():
        if len(v) < 3:
            continue
        g = vrs.get(k, hi)
        out.append({"k": k, "s": float(np.median(v)), "vrk": g[0] if g else None,
                    "tier": max(tiers[k], key=tiers[k].get) if tiers[k] else None})
    return out


def equiv(s, lad):
    """A rating -> the VRS rank whose neighbours' median rating matches it (ranked teams only, 15-rank window)."""
    rk = sorted((t["vrk"], t["s"]) for t in lad if t["vrk"])
    if not rk:
        return None
    med = [(r, float(np.median([x for rr, x in rk if abs(rr - r) <= 7]))) for r, _ in rk]
    above = [r for r, m in med if m >= s]
    return max(above) if above else 1


if __name__ == "__main__":
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    E = json.load(gzip.open(SRC))
    pro = pro_nicks(series)
    ext, meta, ereg, bridged = esea_rows(E, pro)
    print("esea rows", len(ext), flush=True)
    p = dict(json.loads(M.FIT.read_text())["params"])
    base, _ = run(series, [], p, raw, ereg)
    lb, he, tb = score(base)
    grid = []
    for kxe in (.25, .5, 1.0):
        rows, st = run(series, ext, dict(p, kxe=kxe), raw, ereg)
        l, _, t = score(rows)
        grid.append({"kxe": kxe, "tune": t, "dTune": t - tb, "_l": l, "_rows": rows, "_st": st})
        print(kxe, "tune", round(t - tb, 5), flush=True)
    best = min(grid, key=lambda g: g["tune"])
    dl = best["_l"] - lb
    top = np.array([r["top"] for r in he])
    t, neg, nm = bymonth(dl, he)
    res = {"nEsea": len(ext), "base": {"held": float(lb.mean()), "tune": tb},
           "grid": [{k: v for k, v in g.items() if not k.startswith("_")} for g in grid], "pick": best["kxe"],
           "held": {"n": len(he), "d": float(dl.mean()), "tMonth": t, "monthsBetter": [neg, nm],
                    "top50": {"d": float(dl[top].mean())}}}
    res["ship"] = bool(dl.mean() < 0 and t <= -2 and dl[top].mean() <= .0005)
    print(json.dumps(res, indent=1), flush=True)

    # ---- descriptive, on the picked setting
    rows, st = best["_rows"], best["_st"]
    vrs = M.Vrs(H["vrs"])
    seasons = defaultdict(list)
    for r in rows:
        if r["r"][6] == "esea":
            seasons[r["r"][7]["season"]].append(r["d"])
    table = []
    for sn, ds in sorted(seasons.items()):
        lo, hi = sorted(ds)[len(ds) // 2], max(ds)  # the season's second half
        lad = ladder(rows, vrs, lo, hi)
        tierm = defaultdict(list)
        for x in lad:
            if x["tier"]:
                tierm[x["tier"]].append(x["s"])
        tmed = {k: round(float(np.median(v)), 1) for k, v in tierm.items() if len(v) >= 5}
        teams = defaultdict(lambda: defaultdict(list))
        for r in rows:
            if r["r"][6] == "esea" and r["r"][7]["season"] == sn and lo <= r["d"] <= hi:
                g = (r["r"][7]["region"], r["r"][7]["div"])
                teams[g][r["a"]].append(r["sa"])
                teams[g][r["b"]].append(r["sb"])
        for (rg, dv), tt in sorted(teams.items()):
            med = [float(np.median(v)) for v in tt.values() if len(v) >= 3]
            if len(med) < 6:
                continue
            q = np.percentile(med, [25, 50, 75, 90])
            b = bridged[(sn, rg, dv)]
            near = min(tmed, key=lambda k: abs(tmed[k] - q[1])) if tmed else None
            table.append({"season": sn, "region": rg, "div": dv, "teams": len(med), "bridged": round(b[1] / max(b[0], 1), 3),
                          "p25": round(q[0], 1), "med": round(q[1], 1), "p75": round(q[2], 1), "p90": round(q[3], 1),
                          "vrsMed": equiv(q[1], lad), "vrsP90": equiv(q[3], lad), "tierNear": near, "tierMed": tmed})
    res["divisions"] = table
    # 1NT now: the last five to play, today's ratings, against today's VRS-ranked teams
    last = max((m for m in E["matches"] if any(m[f].get("id") == ME for f in ("f1", "f2")) and m.get("at")),
               key=lambda m: m["at"], default=None)
    if last:
        f = "f1" if last["f1"]["id"] == ME else "f2"
        k = key(f"esea {last['region']} {ME[:13]}")
        ros = st["lastros"].get(k) or []
        rg = ereg.get(k)
        s1 = float(np.mean([st["pl"].get(q, p["mu_new"]) for q in ros])) + st["roff"].get(rg, 0) if ros else None
        vt = vrs.tab[vrs.dates[-1]]
        lad = []
        for vk, (rk, pts, nm, _) in vt.items():
            r5 = st["lastros"].get(vk)
            if r5:
                lad.append({"k": vk, "vrk": rk, "s": float(np.mean([st["pl"].get(q, p["mu_new"]) for q in r5]))
                            + st["roff"].get(vrs.region(vk, "9999"), 0)})
        esea_now = defaultdict(list)
        lastseason = max(seasons)
        for ek in {r["a"] for r in rows if r["r"][6] == "esea" and r["r"][7]["season"] == lastseason} | \
                {r["b"] for r in rows if r["r"][6] == "esea" and r["r"][7]["season"] == lastseason}:
            r5 = st["lastros"].get(ek)
            if r5:
                esea_now[meta[ek]["region"]].append(float(np.mean([st["pl"].get(q, p["mu_new"]) for q in r5]))
                                                  + st["roff"].get(ereg[ek], 0))
        res["oneNT"] = {"asof": dt.datetime.utcfromtimestamp(last["at"]).date().isoformat(), "region": last["region"],
                        "div": last["div"], "rating": round(s1, 1) if s1 is not None else None,
                        "five": ros, "vrsEquiv": equiv(s1, lad) if s1 is not None else None,
                        "vrsTeamsAbove": sum(x["s"] > s1 for x in lad) if s1 is not None else None, "vrsTeams": len(lad),
                        "eseaRankBy": {r: [1 + sum(x > s1 for x in v), len(v)] for r, v in esea_now.items()},
                        "eseaRankAll": [1 + sum(x > s1 for v in esea_now.values() for x in v),
                                        sum(len(v) for v in esea_now.values())]}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "divisions"}, indent=1))
    for r in table:
        print(r)
