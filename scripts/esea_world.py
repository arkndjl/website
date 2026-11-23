#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT's worldwide rank and the ESEA division levels (CS2 Tiers 5 and 6), from every region's ESEA results.

    python3 scripts/esea_world.py   # ~8 min -> data/esea_world.json

Reads research/esea_regions.json.gz (scripts/esea_regions_fetch.mjs; esea-research.yml refreshes the current season
weekly) and plays it on the pro scale (scripts/esea_tiers_research.py anchored(): bridged players with 30+ pro series
are fixed at their pro player Elo, everyone else carries an ESEA rating that starts at his division's level).
  - levels: each region's Advanced / Main median team rating in the latest season, on the pro scale (pl + Valve's
    region offset, the same scale as data/cs2.json teams[].pl). cs2_players.tiers(): a ranked team below the Tier 3 cut
    is Tier 5 under its region's ESEA Advanced median, Tier 6 under ESEA Main's.
  - 1NT weekly: its latest five's rating, the VRS rank it would hold (1 + VRS-ranked teams rated above it, the
    standings snapshot before the week), its rank among NA ESEA teams of the season, and its tier.
Rough by construction (Nov 23 2026 study): anchored ratings predict ESEA results worse than ESEA-only ratings, and the
EU / NA gap rides on Valve's region offsets.
"""
import datetime as dt
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_model as M  # noqa: E402
import esea_tiers_research as R  # noqa: E402
import names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "esea_world.json"
ME = R.ME
REGV = {"NA": "Americas", "EU": "Europe"}


def ts(m):
    return dt.datetime.fromtimestamp(m["at"], dt.timezone.utc).date().isoformat()


def main():
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    E = json.load(gzip.open(R.SRC))
    E["matches"] = [m for m in E["matches"] if m.get("at")]
    pro = R.pro_nicks(series)
    p = dict(json.loads(M.FIT.read_text())["params"])
    today = dt.date.today()
    months = [f"{y}-{m:02d}-01" for y in range(2024, today.year + 1) for m in range(1, 13)]
    months = [x for x in months if "2024-02-01" <= x <= today.isoformat()]
    _, st = M.replay(series, M.Vrs(H["vrs"]), p, bo3=cs2_bo3.Bo3(raw), snaps=months)
    snaps = st["snaps"]
    P = {"anchor": 30, "K": 128, "Kmin": 26, "n0": 50, "span": .5}
    mine = sorted((m for m in E["matches"] if any(m[f].get("id") == ME for f in ("f1", "f2"))), key=lambda m: m["at"])
    d0 = dt.date.fromisoformat(ts(mine[0])) if mine else today
    weeks = []
    w = d0 + dt.timedelta(days=(7 - d0.weekday()) % 7 or 7)  # Mondays after 1NT's first league match
    while w <= today:
        weeks.append(w.isoformat())
        w += dt.timedelta(days=7)
    dstart = {}
    for it in range(3):
        keep = {}
        out, rt = R.anchored(E, pro, snaps, months, dstart, P, weeks=list(weeks) if it == 2 else None, keep=keep)
        lv = defaultdict(list)
        for o in out:
            lv[(o["region"], o["div"])] += [o["sa"], o["sb"]]
        if it < 2:
            dstart = {k: float(np.median(v)) for k, v in lv.items()}
    vrs = M.Vrs(H["vrs"])

    def snap_at(d):
        return snaps[max([x for x in months if x <= d] or [months[0]])]

    def pval(pid, nick, gname, rts, sn, rg, dv):
        hit = next((pro[names.key(c)] for c in (gname, nick) if c and len(names.key(c)) >= 4 and names.key(c) in pro), None)
        if hit and sn["pn"].get(hit, 0) >= P["anchor"]:
            return sn["pl"][hit]
        return rts.get(pid, dstart.get((rg, dv), 0.0))

    def five(roster, rts, sn, rg, dv):
        return float(np.mean([pval(*x[:3], rts, sn, rg, dv) for x in roster])) + sn["roff"].get(REGV.get(rg, "Asia"), 0.0)

    def ladder(d, sn):
        vd = vrs.before(d)
        lad = []
        for vk, (rk, pts, nm, _) in vrs.tab[vd].items():
            r5 = sn["lastros"].get(vk)
            if r5:
                lad.append(float(np.mean([sn["pl"].get(x, -100) for x in r5])) + sn["roff"].get(vrs.region(vk, d), 0))
        return lad

    # levels: latest season's median team rating per region x division, second half of the season
    last = max(m["season"] for m in E["matches"])
    levels = {}
    for (rg, dv) in {(o["region"], o["div"]) for o in out}:
        os_ = [o for o in out if o["season"] == last and (o["region"], o["div"]) == (rg, dv)]
        if len(os_) < 30:
            os_ = [o for o in out if o["season"] == last - 1 and (o["region"], o["div"]) == (rg, dv)]
        if len(os_) < 30:
            continue
        ds = sorted(o["d"] for o in os_)
        by = defaultdict(list)
        for o in os_:
            if o["d"] >= ds[len(ds) // 2]:
                by[o["a"]].append(o["sa"])
                by[o["b"]].append(o["sb"])
        med = [float(np.median(v)) for v in by.values() if len(v) >= 3]
        sn = snap_at(ds[-1])
        levels.setdefault(rg, {})[dv] = round(float(np.median(med)) + sn["roff"].get(REGV.get(rg, "Asia"), 0.0), 1)

    def tier(s, rg="NA"):
        lv = levels.get(rg) or levels.get("NA") or {}
        if "Advanced" in lv and s >= lv["Advanced"]:
            return 4
        return 5 if "Main" in lv and s >= lv["Main"] else 6

    def point(d, rts):
        sn = snap_at(d)
        before = [m for m in mine if ts(m) < d]
        if not before:
            return None
        m = before[-1]
        f = "f1" if m["f1"]["id"] == ME else "f2"
        s1 = five(m[f]["roster"], rts, sn, "NA", m["div"])
        lad = ladder(d, sn)
        sea = m["season"]
        latest = {}
        for x in E["matches"]:
            if x["season"] == sea and x["region"] == "NA" and ts(x) < d:
                for g in ("f1", "f2"):
                    if x[g].get("id") and x[g]["id"] != "bye" and len(x[g]["roster"]) >= 4:
                        latest[x[g]["id"]] = (x["div"], x[g]["roster"])
        na = {tid: five(ros, rts, sn, "NA", dv) for tid, (dv, ros) in latest.items()}
        na[ME] = s1
        return {"d": d, "s": round(s1, 1), "vrs": 1 + sum(v > s1 for v in lad), "of": len(lad),
                "na": 1 + sum(v > s1 for k, v in na.items() if k != ME), "naOf": len(na), "season": sea, "div": m["div"],
                "tier": tier(s1)}

    # every team of the latest season (any region): today's world rank (VRS-equivalent) and tier, by FACEIT team id
    d1 = (today + dt.timedelta(days=1)).isoformat()
    sn1, lad1 = snap_at(d1), ladder(d1, snap_at(d1))
    latest = {}
    for x in sorted(E["matches"], key=lambda m: m["at"]):
        if x["season"] >= last - 1:
            for g in ("f1", "f2"):
                if x[g].get("id") and x[g]["id"] != "bye" and len(x[g]["roster"]) >= 4:
                    latest[x[g]["id"]] = (x["region"], x["div"], x[g]["roster"])
    teams = {}
    for tid, (rg, dv, ros) in latest.items():
        s = five(ros, rt, sn1, rg, dv)
        teams[tid] = {"w": 1 + sum(v > s for v in lad1), "t": tier(s, rg), "s": round(s, 1)}
    pts = [x for x in (point(w, keep[w]) for w in weeks) if x]
    now = point((today + dt.timedelta(days=1)).isoformat(), rt)
    res = {"asof": today.isoformat(), "data": E.get("asof"), "levels": levels, "now": now, "weekly": pts,
           "seasons": [min(m["season"] for m in E["matches"]), last], "nMatches": len(E["matches"]), "teams": teams}
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k not in ("weekly", "teams")}, indent=1, default=float), len(pts), "weeks")


if __name__ == "__main__":
    main()
