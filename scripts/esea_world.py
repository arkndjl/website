#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""1NT's worldwide rank and the ESEA division levels (CS2 Tiers 5 and 6), from every region's ESEA results.

    python3 scripts/esea_world.py   # ~8 min -> data/esea_world.json

Reads research/esea_regions.json.gz (scripts/esea_regions_fetch.mjs; esea-research.yml refreshes the current season
weekly) and plays it on the pro scale (scripts/esea_tiers_research.py anchored(): bridged players with 30+ pro series
are fixed at their pro player Elo, everyone else carries an ESEA rating that starts at his division's level).
  - levels: each region's Advanced / Main median team rating in the latest season, on the pro scale (pl + Valve's
    region offset, the same scale as data/cs2.json teams[].pl). cs2_players.tiers(): a ranked team below the Tier 3 cut
    is Tier 5 under NA's ESEA Advanced median, Tier 6 under NA ESEA Main's (EU's divisions rate above both).
  - world rank = ARK Ranking equivalent (Noah Nov 23): 1 + teams in ARK's pool (ark_pool) above the five on ARK's sort
    key. 1NT weekly: its share of the NA ESEA field that week placed on today's pool (so weeks compare), its NA ESEA rank
    and tier; "raw" keeps the rank against that week's own VRS ladder.
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


def ark_pool(rows, st, vrs, p, raw, today):
    """ARK Ranking's pool and sort key, as cs2_model.build() has it: every team with 15+ series and one in the last 120
    days (Valve series and lower-tier bo3.gg matches), ordered on W_top . (five's player Elo + region offset, VRS points or the 400 floor) / 400. The top 150 are
    re-sorted on the Bo3 chance against the top 20 (team map and RWA terms too), so a rank beyond ~150 is this order."""
    global W0, W1
    try:   # the pool cs2_model.build() ranked (rebrands merged, same weights): data/cs2.json arkPool
        ap = json.loads((ROOT / "data" / "cs2.json").read_text())["arkPool"]
        W0, W1 = ap["w"]
        return ap["z"]
    except (OSError, ValueError, KeyError):
        pass
    fitj = json.loads(M.FIT.read_text())
    w = fitj["weights"]["top"]
    try:
        import cs2_players
        live = cs2_players.Live(cs2_bo3.Bo3(raw))
        if live.w:
            w = live.w["top"]
    except Exception as ex:  # noqa: BLE001
        print("RWA weights skipped:", ex)
    W0, W1 = float(w[0]), float(w[1])
    vt = vrs.tab[vrs.dates[-1]]
    cut = (today - dt.timedelta(days=120)).isoformat()
    lastd, n = {}, defaultdict(int)
    for r in list(rows) + list(st.get("xrows") or []):   # lower-tier bo3.gg matches count, as in cs2_model.build()
        for k in (r["a"], r["b"]):
            lastd[k] = max(lastd.get(k, ""), r["d"])
            n[k] += 1
    out = []
    for k in lastd:
        ros = st["lastros"].get(k)
        if lastd[k] >= cut and n[k] >= 15 and ros:
            x = sum(st["pl"].get(q, p["mu_new"]) for q in ros) / len(ros) + st["roff"].get(vrs.region(k, today.isoformat()), 0)
            v = vt.get(k)
            out.append(W0 * x / 400 + W1 * (v[1] if v else 400) / 400)
    return out


W0, W1 = 1.0, 0.0


def main():
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    E = json.load(gzip.open(R.SRC))
    # a forfeit FACEIT never started has no time: it takes its stage's median match time (it still counts as a win)
    st_at = defaultdict(list)
    for m in E["matches"]:
        if m.get("at"):
            st_at[(m["season"], m["region"], m["div"], m["stage"])].append(m["at"])
    for m in E["matches"]:
        if not m.get("at") and st_at.get((m["season"], m["region"], m["div"], m["stage"])):
            m["at"] = int(np.median(st_at[(m["season"], m["region"], m["div"], m["stage"])]))
    E["matches"] = [m for m in E["matches"] if m.get("at")]
    pro = R.pro_nicks(series)
    p = dict(json.loads(M.FIT.read_text())["params"])
    today = dt.date.today()
    months = [f"{y}-{m:02d}-01" for y in range(2024, today.year + 1) for m in range(1, 13)]
    months = [x for x in months if "2024-02-01" <= x <= today.isoformat()]
    prow, st = M.replay(series, M.Vrs(H["vrs"]), dict(p, xrows=True), bo3=cs2_bo3.Bo3(raw), snaps=months)
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

    def arkz(s):   # an ESEA five on ARK's sort key: no VRS points = the same 400-point floor every unlisted team gets
        return W0 * s / 400 + W1 * 1.0

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

    def tier(s, rg="NA"):   # one ladder (NA's levels) for every region, as cs2_players.tiers()
        lv = levels.get("NA") or {}
        if "Advanced" in lv and s >= lv["Advanced"]:
            return 4
        return 5 if "Main" in lv and s >= lv["Main"] else 6

    def point(d, rts):
        sn = snap_at(d)
        before = [m for m in mine if ts(m) < d and len(m["f1" if m["f1"]["id"] == ME else "f2"]["roster"]) >= 4]
        if not before:
            return None
        m = before[-1]
        f = "f1" if m["f1"]["id"] == ME else "f2"
        s1 = five(m[f]["roster"], rts, sn, "NA", m["div"])
        lad = ladder(d, sn)
        sea = m["season"]
        latest = {}
        for x in sorted(E["matches"], key=lambda m: (m["season"], m["at"])):   # this season's teams over last season's
            if x["season"] in (sea - 1, sea) and x["region"] == "NA" and ts(x) < d:
                for g in ("f1", "f2"):
                    if x[g].get("id") and x[g]["id"] != "bye" and len(x[g]["roster"]) >= 4:
                        latest[x[g]["id"]] = (x["div"], x[g]["roster"])
        na = {tid: five(ros, rts, sn, "NA", dv) for tid, (dv, ros) in latest.items()}
        na[ME] = s1
        return {"d": d, "s": round(s1, 1), "ros": [x[1] for x in m[f]["roster"]], "vrs": 1 + sum(v > s1 for v in lad), "of": len(lad), "q": sum(v > s1 for k, v in na.items() if k != ME) / max(1, len(na) - 1), "field": sorted(na.values()),
                "na": 1 + sum(v > s1 for k, v in na.items() if k != ME), "naOf": len(na), "season": sea, "div": m["div"],
                "tier": tier(s1)}

    # every team of the latest season (any region): today's world rank (ARK Ranking equivalent) and tier, by FACEIT id
    d1 = (today + dt.timedelta(days=1)).isoformat()
    sn1, lad1 = snap_at(d1), ark_pool(prow, st, vrs, p, raw, today)
    latest = {}
    for x in sorted(E["matches"], key=lambda m: m["at"]):
        if x["season"] >= last - 1:
            for g in ("f1", "f2"):
                if x[g].get("id") and x[g]["id"] != "bye" and len(x[g]["roster"]) >= 4:
                    latest[x[g]["id"]] = (x["region"], x["div"], x[g]["roster"])
    teams = {}
    for tid, (rg, dv, ros) in latest.items():
        s = five(ros, rt, sn1, rg, dv)
        teams[tid] = {"w": 1 + sum(v > arkz(s) for v in lad1), "t": tier(s, rg), "s": round(s, 1)}
    pts = [x for x in (point(w, keep[w]) for w in weeks) if x]
    now = point((today + dt.timedelta(days=1)).isoformat(), rt)
    # the weekly world rank on today's ladder: the raw rank against each week's own VRS ladder is not comparable over time
    # (Valve's ranked field grew from ~225 to ~350 teams, mostly near ESEA's level, and the pro scale drifts against the
    # ESEA ratings). Each week keeps only 1NT's place in that week's NA ESEA field (share of teams rated above it, all
    # divisions, opponent-adjusted, point in time); that share is read off today's NA field and placed on today's ladder.
    field = now["field"]

    def on_today(q):
        if not field:
            return None
        i = min(len(field) - 1, max(0, int(round((1 - q) * (len(field) - 1)))))
        return 1 + sum(v > arkz(field[i]) for v in lad1)
    for x in pts:
        x["raw"] = x["vrs"]
        x["vrs"] = on_today(x["q"])
        x["of"] = len(lad1)
    now["raw"], now["vrs"], now["of"] = now["vrs"], 1 + sum(v > arkz(now["s"]) for v in lad1), len(lad1)
    for x in pts + [now]:
        x["q"] = round(x["q"], 3)
        x.pop("field", None)
        if x is not now:
            x.pop("ros", None)
    res = {"asof": today.isoformat(), "data": E.get("asof"), "levels": levels, "now": now, "weekly": pts,
           "seasons": [min(m["season"] for m in E["matches"]), last], "nMatches": len(E["matches"]), "teams": teams}
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in res.items() if k not in ("weekly", "teams")}, indent=1, default=float), len(pts), "weeks")


if __name__ == "__main__":
    main()
