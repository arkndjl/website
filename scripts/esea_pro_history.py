#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESEA -> pro-scale history and the standing retest for ESEA-only CS2 prospects (Noah, Nov 23 2026).

    python3 scripts/esea_pro_history.py          # snapshot (weekly) + retest -> data/esea_pro_test.json
    python3 scripts/esea_pro_history.py --test   # retest only

Snapshot (scripts/data/esea_pro_history/YYYY-MM-DD.json.gz, one a week): every ESEA league player as of that day,
point in time: RWA and rounds (data/esea_rwa.json, NA box lines), latest region / division / season / team
(research/esea_regions.json.gz, every region), nickname, and the bo3.gg player id the nickname + teammates link to
(cs2_prospects_lowtier_research.esea_ids) with his bo3.gg rounds in the last year.

Retest (set up front, Nov 23 2026; the Nov 23 run had 0 tune rows, 28 ESEA-only held rows):
  rows   an ESEA player at a cutoff with 300+ ESEA rounds in the year before, under 300 bo3.gg rounds in that year
         (ESEA-only), and 600+ bo3.gg rounds in the year after (the prospect target: opponent-credited rating).
         Two sources: monthly cutoffs rebuilt from the FACEIT box archive (features: ESEA K-D per round, division
         level) and the weekly snapshots once a year old (features: ESEA RWA, division level).
  split  by cutoff date: the earliest two thirds tune (OLS), the last third held.
  gate   a spec is tested only with 120+ tune rows and 60+ distinct held players; it passes with held t < -2 against
         the tune mean, |bias t| < 2 and a slope above .5 (outcome on grade). The first passing spec grades ESEA-only
         players on the newest snapshot (data/esea_pro_test.json "grades"), which scripts/cs2_players.py adds to
         the prospects tab. Until then status "waiting" (too few rows) or "fail".
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
import cs2_prospects_lowtier_research as LT  # noqa: E402
import esea_rwa_research as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "scripts" / "data" / "esea_pro_history"
OUT = ROOT / "data" / "esea_pro_test.json"
DIV = {"Open9-10": -2, "Open1-8": -1.5, "Open": -1.75, "Intermediate": -1, "Main": 0, "Advanced": 1}
MIN_TUNE, MIN_HELD = 120, 60


def load_maps():
    fitj = json.loads(CP.FIT.read_text())
    p = fitj["params"]
    M = CP.Maps()
    c = CP.contributions(M, np.array([fitj["beta"][k] for k in CP.STATS]), np.array(fitj["mline"]), p.get("pm", 0.0))
    return M, c, p


def snapshot(M, c, p, ids):
    today = dt.date.today()
    if any(dt.date.fromisoformat(f.name[:10]) > today - dt.timedelta(days=6) for f in HIST.glob("*.json.gz")):
        return None
    rw = json.load(open(ROOT / "data" / "esea_rwa.json"))
    e = json.load(gzip.open(ROOT / "research" / "esea_regions.json.gz"))
    last = {}
    for m in sorted(e["matches"], key=lambda m: m.get("at") or 0):
        for f in ("f1", "f2"):
            for q in m[f]["roster"]:
                if len(q) > 2:
                    last[q[0]] = [m.get("region"), m.get("div"), m.get("season"), m[f]["name"], q[1]]
    T = today.toordinal() + 1
    th, _ = CP.ratings(M, c, T, p)
    _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
    pl = {}
    for fid in set(last) | set(rw["p"]):
        x = rw["p"].get(fid)
        reg, dv, se, tm, nk = last.get(fid) or [None] * 5
        b = ids.get(fid)
        pl[fid] = [x[0] if x else None, x[1] if x else 0, reg, dv, se, tm, nk or rw["names"].get(fid),
                   int(M.pids[b]) if b is not None else None, int(r12[b]) if b is not None else 0]
    HIST.mkdir(parents=True, exist_ok=True)
    out = {"asof": today.isoformat(), "cols": ["rwa", "rounds", "region", "div", "season", "team", "nick", "bo3", "bo3r12"],
           "p": pl}
    with gzip.open(HIST / f"{today.isoformat()}.json.gz", "wt") as fh:
        json.dump(out, fh, separators=(",", ":"))
    return len(pl)


def archive_rows(M, c, p, ids):
    ms = json.load(gzip.open(ROOT / "research" / "esea_matches.json.gz"))
    lines = defaultdict(list)
    for m in ms["matches"]:
        if not m.get("at"):
            continue
        day = dt.date.fromtimestamp(m["at"]).toordinal()
        for mp in m.get("maps") or []:
            rr = (mp.get("s1") or 0) + (mp.get("s2") or 0)
            for side in ("p1", "p2"):
                for q in mp.get(side) or [] if rr else []:
                    if q[0] in ids:
                        x = R.line(q)
                        if x:
                            lines[q[0]].append((day, rr, DIV.get(m["div"], 0), x[0] - x[1]))
    last = int(M.gd.max())
    first = min((x[0] for L in lines.values() for x in L), default=last)
    rows, d = [], dt.date.fromordinal(first + 182).replace(day=1)
    while d.toordinal() + 365 <= last:
        T = d.toordinal()
        thF, _ = CP.ratings(M, c, T + 365, p)
        fut, rf = CP.window_stats(M, c, thF, T, T + 365, p)
        th, _ = CP.ratings(M, c, T, p)
        _, r12 = CP.window_stats(M, c, th, T - 365, T, p)
        for fid, L in lines.items():
            pi = ids[fid]
            L0 = [x for x in L if T - 365 <= x[0] < T]
            rnd = sum(x[1] for x in L0)
            if rnd < 300 or r12[pi] >= 300 or rf[pi] < 600:
                continue
            rows.append({"T": T, "fid": fid, "x": [sum(x[3] for x in L0) / rnd, sum(x[1] * x[2] for x in L0) / rnd],
                         "y": float(fut[pi]), "w": float(min(rf[pi], 3000))})
        d = (d + dt.timedelta(days=32)).replace(day=1)
    return rows


def snapshot_rows(M, c, p):
    last = int(M.gd.max())
    rows = []
    for f in sorted(HIST.glob("*.json.gz")):
        T = dt.date.fromisoformat(f.name[:10]).toordinal()
        if T + 365 > last:
            continue
        s = json.load(gzip.open(f))
        thF, _ = CP.ratings(M, c, T + 365, p)
        fut, rf = CP.window_stats(M, c, thF, T, T + 365, p)
        idx = {int(x): i for i, x in enumerate(M.pids)}
        for fid, r in s["p"].items():
            if r[0] is None or r[1] < 300 or r[7] is None or r[8] >= 300 or r[7] not in idx:
                continue
            pi = idx[r[7]]
            if rf[pi] >= 600:
                rows.append({"T": T, "fid": fid, "x": [r[0], DIV.get(r[3], 0)], "y": float(fut[pi]),
                             "w": float(min(rf[pi], 3000))})
    return rows


def gate(rows):
    res = {"rows": len(rows)}
    if not rows:
        return res
    days = sorted({r["T"] for r in rows})
    cut = days[int(len(days) * 2 / 3)] if len(days) >= 3 else days[-1] + 1
    tune, held = [r for r in rows if r["T"] < cut], [r for r in rows if r["T"] >= cut]
    res.update({"tune": len(tune), "held": len(held), "heldPlayers": len({r["fid"] for r in held}),
                "heldFrom": dt.date.fromordinal(cut).isoformat()})
    if len(tune) < MIN_TUNE or res["heldPlayers"] < MIN_HELD:
        res["status"] = "waiting"
        return res

    def XY(rs):
        return (np.array([[1] + r["x"] for r in rs]), np.array([r["y"] for r in rs]), np.array([r["w"] for r in rs]))
    X, y, w = XY(tune)
    b = CP.ols(X, y, w)
    Xh, yh, wh = XY(held)
    e, e0 = yh - Xh @ b, yh - float((y * w).sum() / w.sum())
    pred = Xh @ b
    res.update({"b": [round(float(v), 4) for v in b], "t": LT.tstat(wh * (e * e - e0 * e0)), "tBias": LT.tstat(wh * e),
                "slope": round(float(np.polyfit(pred, yh, 1, w=np.sqrt(wh))[0]), 3)})
    res["status"] = "pass" if res["t"] < -2 and abs(res["tBias"]) < 2 and res["slope"] > 0.5 else "fail"
    return res


def grades(M, c, p, b):
    """Pro-scale projection for every ESEA-only player on the newest snapshot (RWA spec)."""
    f = max(HIST.glob("*.json.gz"), default=None)
    if not f:
        return []
    s = json.load(gzip.open(f))
    out = []
    for fid, r in s["p"].items():
        if r[0] is None or r[1] < 300 or r[8] >= 300:
            continue
        out.append({"fid": fid, "n": r[6], "tm": r[5], "rg": r[2], "div": r[3], "rwa": r[0], "r": r[1],
                    "proj": round(float(b[0] + b[1] * r[0] + b[2] * DIV.get(r[3], 0)), 4)})
    return out


def main():
    M, c, p = load_maps()
    ids_ix = LT.esea_ids(M)
    out = {"asof": dt.date.today().isoformat(), "minTune": MIN_TUNE, "minHeld": MIN_HELD,
           "linked": len(ids_ix), "snapshots": 0}
    if "--test" not in sys.argv:
        out["snapNew"] = snapshot(M, c, p, ids_ix)
    out["snapshots"] = len(list(HIST.glob("*.json.gz")))
    out["archive"] = gate(archive_rows(M, c, p, ids_ix))
    out["snapshot"] = gate(snapshot_rows(M, c, p))
    out["status"] = ("pass" if out["snapshot"].get("status") == "pass" else
                     "fail" if "fail" in (out["archive"].get("status"), out["snapshot"].get("status")) else "waiting")
    # only the snapshot (RWA) spec grades: its inputs are what a new snapshot holds
    if out["snapshot"].get("status") == "pass":
        out["grades"] = grades(M, c, p, out["snapshot"]["b"])
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "grades"}))


if __name__ == "__main__":
    main()
