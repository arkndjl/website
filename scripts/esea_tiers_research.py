#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESEA divisions on the pro scale (Nov 23 2026): play every region's ESEA Advanced / Main / Intermediate league
matches (research/esea_regions.json.gz, scripts/esea_regions_fetch.mjs) through the pro player Elo
(scripts/cs2_model.replay) with the pros, bridged by players who appear in both (FACEIT in-game name or nickname
= a Valve / bo3.gg nick, names.key, 4+ characters), then read where each region's divisions sit against Valve's VRS
ranks and bo3.gg's event tiers, and where 1NT ranks.

    python3 scripts/esea_tiers_research.py              # test + placement, ~25 min -> data/esea_tiers_research.json
    python3 scripts/esea_tiers_research.py --describe   # placement only (keeps the test numbers), ~8 min
    python3 scripts/esea_tiers_research.py --profile    # bo3.gg event tiers of each division's pro-record players

RESULTS (Nov 23 2026, S53-S59, 33,156 ESEA matches NA + EU): ESEA rows in the pro model FAIL (held -.0008, t by
month -1.97, 12/17; not shipped). Placement through anchors is rough: anchored ESEA ratings predict S58-59 ESEA
results worse than ESEA-only ratings (.678 vs .658), nick bridges are noisy below Advanced. Robust part (--profile,
players with 20+ bo3.gg maps): EU Advanced 32-50% of players, maps ~80% tier C / 20% B; NA Advanced ~20%, ~half B /
half C; Main and Intermediate <= 2% (the few hits are mostly nick collisions).

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
REG = {"NA": "Americas", "SA": "Americas", "EU": "Europe", "MENA": "Europe", "OCE": "Asia", "AS": "Asia", "SEA": "Asia"}
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


def anchored(E, pro, st_snaps, months, dstart, P, weeks=None, keep=None):
    """ESEA ratings on the pro scale: a bridged player with ANCHOR+ pro series is fixed at his pro rating (the snapshot
    before the match's month); everyone else carries an ESEA rating that starts at his first division's level
    (dstart) and moves on each match (series result; a Bo1 on round share). -> (per-match rows, final ratings)."""
    rt, n, out = {}, defaultdict(int), []
    last = {}  # team id -> its latest 4+ roster: a forfeit's no-show side is played as that five (Noah Nov 23: forfeit
    #            wins count as wins), the result a plain series win
    for m in sorted(E["matches"], key=lambda m: m.get("at") or 0):
        if not m.get("at") or m.get("winner") not in ("faction1", "faction2"):
            continue
        if any(not m[f].get("id") or m[f]["id"] == "bye" for f in ("f1", "f2")):
            continue
        ros = {}
        for f in ("f1", "f2"):
            if len(m[f]["roster"]) >= 4:
                ros[f] = last[m[f]["id"]] = m[f]["roster"]
            elif m[f]["id"] in last:
                ros[f] = last[m[f]["id"]]
        if len(ros) < 2:
            continue
        m = dict(m, f1=dict(m["f1"], roster=ros["f1"]), f2=dict(m["f2"], roster=ros["f2"]))
        d = dt.datetime.fromtimestamp(m["at"], dt.timezone.utc).date().isoformat()
        while weeks and d >= weeks[0]:  # ESEA ratings as of each week's start (scripts/esea_world.py)
            keep[weeks.pop(0)] = dict(rt)
        sn = st_snaps[max([x for x in months if x <= d] or [months[0]])]
        side = []
        for f in ("f1", "f2"):
            vals, free = [], []
            for pid, nick, gname, lvl in m[f]["roster"]:
                hit = next((pro[names.key(c)] for c in (gname, nick) if c and len(names.key(c)) >= 4
                            and names.key(c) in pro), None)
                if hit and sn["pn"].get(hit, 0) >= P["anchor"]:
                    vals.append(sn["pl"][hit])
                else:
                    if pid not in rt:
                        rt[pid] = dstart.get((m["region"], m["div"]), 0.0)
                    vals.append(rt[pid])
                    free.append(pid)
            side.append((float(np.mean(vals)), free, m[f]["id"]))
        e = 1 / (1 + 10 ** (-(side[0][0] - side[1][0]) / 400))
        y = 1.0 if m["winner"] == "faction1" else 0.0
        sc = m.get("score") or {}
        s1, s2 = sc.get("faction1"), sc.get("faction2")
        if m.get("bo", 1) == 1 and s1 is not None and s2 is not None and s1 + s2 >= 13:
            sh = s1 / (s1 + s2)
            y = min(1.0, max(0.0, .5 + (sh - .5) / P["span"] / 2))
        out.append({"d": d, "season": m["season"], "region": m["region"], "div": m["div"], "e": e,
                    "w": 1.0 if m["winner"] == "faction1" else 0.0, "a": side[0][2], "b": side[1][2],
                    "sa": side[0][0], "sb": side[1][0]})
        for (sv, free, _), sg in ((side[0], 1), (side[1], -1)):
            for pid in free:
                k = P["Kmin"] + (P["K"] - P["Kmin"]) * math.exp(-n[pid] / P["n0"])
                rt[pid] += sg * k * (y - e)
                n[pid] += 1
    for w in weeks or []:
        keep[w] = dict(rt)
    return out, rt


def describe(out, res, H, st_snaps, months):
    vrs = M.Vrs(H["vrs"])
    REGV = {"NA": "Americas", "EU": "Europe", "SEA": "Asia"}
    table = []
    for (sn, rg, dv) in sorted({(o["season"], o["region"], o["div"]) for o in out}):
        os_ = [o for o in out if (o["season"], o["region"], o["div"]) == (sn, rg, dv)]
        ds = sorted(o["d"] for o in os_)
        lo, hi = ds[len(ds) // 2], ds[-1]
        by = defaultdict(list)
        for o in os_:
            if o["d"] >= lo:
                by[o["a"]].append(o["sa"])
                by[o["b"]].append(o["sb"])
        med = [float(np.median(v)) for v in by.values() if len(v) >= 3]
        if len(med) < 6:
            continue
        snap = st_snaps[max([x for x in months if x <= hi])]
        roff = snap["roff"].get(REGV.get(rg, "Europe"), 0.0)
        q = np.percentile(med, [10, 50, 90]) + roff
        vd = vrs.before(hi)
        lad = []
        for vk, (rk, pts, nm, _) in vrs.tab[vd].items():
            r5 = snap["lastros"].get(vk)
            if r5:
                lad.append((rk, float(np.mean([snap["pl"].get(x, -100) for x in r5])) + snap["roff"].get(vrs.region(vk, hi), 0)))
        lad.sort()
        eq = lambda x: 1 + sum(v > x for _, v in lad)  # noqa: E731
        bands = {b: round(float(np.median([v for r, v in lad if lo_ <= r <= hi_])), 1)
                 for b, (lo_, hi_) in {"1-20": (1, 20), "21-50": (21, 50), "51-100": (51, 100), "101-200": (101, 200),
                                       "201+": (201, 9999)}.items() if any(lo_ <= r <= hi_ for r, _ in lad)}
        table.append({"season": sn, "region": rg, "div": dv, "teams": len(med), "p10": round(q[0], 1), "med": round(q[1], 1),
                      "p90": round(q[2], 1), "vrsEqMed": eq(q[1]), "vrsEqP90": eq(q[2]), "vrsEqP10": eq(q[0]),
                      "vrsTeams": len(lad), "vrsBands": bands})
    return table


if __name__ == "__main__" and "--profile" not in sys.argv:
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    E = json.load(gzip.open(SRC))
    pro = pro_nicks(series)
    p = dict(json.loads(M.FIT.read_text())["params"])
    if "--describe" not in sys.argv:
        ext, meta, ereg, bridged = esea_rows(E, pro)
        print("esea rows", len(ext), flush=True)
        base, _ = run(series, [], p, raw, ereg)
        lb, he, tb = score(base)
        grid = []
        for kxe in (.25, .5, 1.0):
            rows, st = run(series, ext, dict(p, kxe=kxe), raw, ereg)
            l, _, t = score(rows)
            grid.append({"kxe": kxe, "tune": t, "dTune": t - tb, "_l": l})
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
        OUT.write_text(json.dumps(res, indent=1, default=float))
        print(json.dumps(res, indent=1), flush=True)
    res = json.loads(OUT.read_text())
    # ---- descriptive: ESEA on the pro scale through fixed anchors (the live pro model, ESEA never feeds it)
    months = sorted({f"{y}-{m:02d}-01" for y in range(2024, 2027) for m in range(1, 13)})
    months = [x for x in months if "2024-02-01" <= x <= dt.date.today().isoformat()]
    _, st = M.replay(series, M.Vrs(H["vrs"]), p, bo3=cs2_bo3.Bo3(raw), snaps=months)
    snaps = st["snaps"]
    P = {"anchor": 30, "K": 128, "Kmin": 26, "n0": 50, "span": .5}  # ESEA player Elo settings (esea-standin, Nov 3)
    dstart = {}
    for it in range(3):  # each division's start level = its teams' median rating on the previous pass
        out, rt = anchored(E, pro, snaps, months, dstart, P)
        lv = defaultdict(list)
        for o in out:
            lv[(o["region"], o["div"])] += [o["sa"], o["sb"]]
        dstart = {k: float(np.median(v)) for k, v in lv.items()}
        print("pass", it, {f"{k[0]} {k[1]}": round(v) for k, v in sorted(dstart.items())}, flush=True)
    # sanity: anchored ESEA ratings vs the same Elo with no anchors, on ESEA S58-59 results (log loss)
    held = [o for o in out if o["season"] >= 58]
    res["eseaLL"] = {"anchored": float(np.mean(M.ll(np.array([o["e"] for o in held]), np.array([o["w"] for o in held])))),
                     "n": len(held)}
    out0, _ = anchored(E, {}, snaps, months, dstart, P)
    h0 = [o for o in out0 if o["season"] >= 58]
    res["eseaLL"]["noAnchors"] = float(np.mean(M.ll(np.array([o["e"] for o in h0]), np.array([o["w"] for o in h0]))))
    br = defaultdict(lambda: [0, 0])
    for m in E["matches"]:
        for f in ("f1", "f2"):
            for pid, nick, gname, lvl in m[f].get("roster") or []:
                b = br[(m["region"], m["div"])]
                b[0] += 1
                b[1] += any(c and len(names.key(c)) >= 4 and names.key(c) in pro for c in (gname, nick))
    res["bridged"] = {f"{k[0]} {k[1]}": round(v[1] / max(v[0], 1), 3) for k, v in sorted(br.items())}
    res["divisions"] = describe(out, res, H, snaps, months)
    # 1NT now
    last = max((m for m in E["matches"] if any(m[f].get("id") == ME for f in ("f1", "f2")) and m.get("at")),
               key=lambda m: m["at"], default=None)
    if last:
        f = "f1" if last["f1"]["id"] == ME else "f2"
        snap = snaps[months[-1]]
        vals = []
        for pid, nick, gname, lvl in last[f]["roster"]:
            hit = next((pro[names.key(c)] for c in (gname, nick) if c and len(names.key(c)) >= 4 and names.key(c) in pro), None)
            vals.append(snap["pl"][hit] if hit and snap["pn"].get(hit, 0) >= P["anchor"] else rt.get(pid, dstart.get(("NA", last["div"]), 0)))
        s1 = float(np.mean(vals)) + snap["roff"].get("Americas", 0)
        vrs = M.Vrs(H["vrs"])
        lad = []
        for vk, (rk, pts, nm, _) in vrs.tab[vrs.dates[-1]].items():
            r5 = st["lastros"].get(vk)
            if r5:
                lad.append((rk, nm, float(np.mean([st["pl"].get(x, -100) for x in r5])) + st["roff"].get(vrs.region(vk, "9999"), 0)))
        lad.sort(key=lambda z: -z[2])
        eq = 1 + sum(v > s1 for _, _, v in lad)
        # ESEA teams this season, latest five each, same scale
        lastm = {}
        for m in sorted(E["matches"], key=lambda m: m.get("at") or 0):
            if m["season"] == max(x["season"] for x in E["matches"]):
                for g in ("f1", "f2"):
                    if m[g].get("id") and m[g]["id"] != "bye" and len(m[g]["roster"]) >= 4:
                        lastm[m[g]["id"]] = (m["region"], m["div"], m[g]["roster"], m[g]["name"])
        tv = {}
        for tid, (rg, dv, ros, nm) in lastm.items():
            v = []
            for pid, nick, gname, lvl in ros:
                hit = next((pro[names.key(c)] for c in (gname, nick) if c and len(names.key(c)) >= 4 and names.key(c) in pro), None)
                v.append(snap["pl"][hit] if hit and snap["pn"].get(hit, 0) >= P["anchor"] else rt.get(pid, dstart.get((rg, dv), 0)))
            tv[tid] = (rg, dv, nm, float(np.mean(v)) + snap["roff"].get({"NA": "Americas", "EU": "Europe"}.get(rg, "Asia"), 0))
        na = sorted([x for x in tv.values() if x[0] == "NA"], key=lambda z: -z[3])
        dvr = sorted([x for x in tv.values() if x[0] == "NA" and x[1] == last["div"]], key=lambda z: -z[3])
        res["oneNT"] = {"asof": dt.datetime.fromtimestamp(last["at"], dt.timezone.utc).date().isoformat(),
                        "div": last["div"], "rating": round(s1, 1), "vrsEquiv": eq, "vrsTeams": len(lad),
                        "vrsNeighbours": [(rk, nm, round(v, 1)) for rk, nm, v in lad[max(0, eq - 3):eq + 2]],
                        "naRank": [1 + sum(x[3] > s1 for x in na), len(na)],
                        "divRank": [1 + sum(x[3] > s1 for x in dvr), len(dvr)],
                        "allRank": [1 + sum(x[3] > s1 for x in tv.values()), len(tv)]}
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k != "divisions"}, indent=1, default=float))
    for r in res["divisions"]:
        print(r)


def profile():
    """Where each ESEA division's players play pro: for players whose FACEIT name is a bo3.gg nick with 20+ maps in
    the 6 months around the season, the share of those maps by bo3.gg event tier (S, A, B, C, D)."""
    E = json.load(gzip.open(SRC))
    bo3 = cs2_bo3.Bo3()
    gm = {g[0]: g for gs in bo3.maps.values() for g in gs}
    maps = defaultdict(list)  # nick key -> [(date, tier)]
    for g, sides in cs2_bo3.map_rosters().items():
        gg = gm.get(g)
        m = bo3.mt.get(gg[1]) if gg else None
        if not m:
            continue
        for ros in sides.values():
            for q in ros:
                maps[names.key(q)].append((m[1][:10], m[10] or "d"))
    span = defaultdict(list)
    for m in E["matches"]:
        if m.get("at"):
            span[m["season"]].append(dt.datetime.fromtimestamp(m["at"], dt.timezone.utc).date())
    out = []
    for (sn, rg, dv) in sorted({(m["season"], m["region"], m["div"]) for m in E["matches"]}):
        if sn < 56:
            continue
        lo = (min(span[sn]) - dt.timedelta(days=90)).isoformat()
        hi = (max(span[sn]) + dt.timedelta(days=90)).isoformat()
        pl = set()
        for m in E["matches"]:
            if (m["season"], m["region"], m["div"]) == (sn, rg, dv):
                for f in ("f1", "f2"):
                    for pid, nick, gname, lvl in m[f].get("roster") or []:
                        pl.add((pid, next((names.key(c) for c in (gname, nick) if c and len(names.key(c)) >= 4
                                           and names.key(c) in maps), None)))
        tiers, nb = defaultdict(float), 0
        for pid, k in pl:
            v = [t for d, t in maps.get(k, []) if lo <= d <= hi] if k else []
            if len(v) >= 20:
                nb += 1
                for t in v:
                    tiers[t] += 1 / len(v)  # each player counts once
        tot = sum(tiers.values()) or 1
        out.append({"season": sn, "region": rg, "div": dv, "players": len(pl), "proPlayers": nb,
                    "share": round(nb / max(len(pl), 1), 3), "tiers": {t: round(tiers[t] / tot, 3) for t in "sabcd"}})
    return out


if __name__ == "__main__" and "--profile" in sys.argv:
    res = json.loads(OUT.read_text())
    res["profile"] = profile()
    OUT.write_text(json.dumps(res, indent=1, default=float))
    for r in res["profile"]:
        print(r)
