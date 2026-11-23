#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ESEA teams on the CS2 ARK Ranking board (Noah Nov 23 2026: "include teams from Intermediate and Open 9-10"): are the
ratings that place them (scripts/esea_world.py: anchored ESEA ratings on the pro scale, forfeits as wins) good enough
to rank them? Pre-registered before any held number was read:
  - scored: each ESEA match (research/esea_regions.json.gz), the pre-match chance from the two fives' anchored ratings
    (point in time; Elo logistic, 400 scale) against the series result. Held = Jul 2025 on (the CS2 model's split).
  - a region x division is placed on the board if its held log loss beats a coin (.6931) with t by month <= -2 AND its
    calibration slope (logit fit on held) is within .7 - 1.3 (a placement ordered right but on the wrong scale fails).
    -> data/esea_board_research.json
  - rerun as data accrues (Nov 23 2026, scripts/cs2_ark_loop.py's rolling monthly seal): held runs Jul 2025 to the last
    complete month; each new sealed month is a new look, and look k needs t by month <= Phi^-1(.0228 / k) (look 1 = -2.0).
    A division that passes is listed in "promoted" and scripts/esea_world.py puts its teams on the ARK Ranking board.

    python3 scripts/esea_board_research.py   # ~2 min; weekly in esea-research.yml (exits early with no new sealed month)
"""
import datetime as dt
import gzip
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3  # noqa: E402
import cs2_model as M  # noqa: E402
import esea_tiers_research as R  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "esea_board_research.json"


def main():
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev_meta = prev.get("_loop") or {"looks": 1 if prev else 0, "sealed": "2026-10" if prev else None}
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    E = json.load(gzip.open(R.SRC))
    st_at = defaultdict(list)
    for m in E["matches"]:
        if m.get("at"):
            st_at[(m["season"], m["region"], m["div"], m["stage"])].append(m["at"])
    for m in E["matches"]:
        if not m.get("at") and st_at.get((m["season"], m["region"], m["div"], m["stage"])):
            m["at"] = int(np.median(st_at[(m["season"], m["region"], m["div"], m["stage"])]))
    E["matches"] = [m for m in E["matches"] if m.get("at")]
    lastm = max(dt.datetime.utcfromtimestamp(m["at"]).strftime("%Y-%m") for m in E["matches"])
    sealed = (dt.date.fromisoformat(lastm + "-01") - dt.timedelta(days=1)).strftime("%Y-%m")
    if sealed == prev_meta.get("sealed") and "--force" not in sys.argv:
        print("no new sealed month since", sealed)
        return
    look = prev_meta["looks"] + (1 if sealed != prev_meta.get("sealed") else 0)
    crit = -2.0 if look <= 1 else statistics.NormalDist().inv_cdf(.0228 / look)
    pro = R.pro_nicks(series)
    p = dict(json.loads(M.FIT.read_text())["params"])
    today = dt.date.today()
    months = [f"{y}-{m:02d}-01" for y in range(2024, today.year + 1) for m in range(1, 13)]
    months = [x for x in months if "2024-02-01" <= x <= today.isoformat()]
    _, st = M.replay(series, M.Vrs(H["vrs"]), p, bo3=cs2_bo3.Bo3(raw), snaps=months)
    P = {"anchor": 30, "K": 128, "Kmin": 26, "n0": 50, "span": .5}
    dstart = {}
    for it in range(3):
        out, _ = R.anchored(E, pro, st["snaps"], months, dstart, P)
        lv = defaultdict(list)
        for o in out:
            lv[(o["region"], o["div"])] += [o["sa"], o["sb"]]
        if it < 2:
            dstart = {k: float(np.median(v)) for k, v in lv.items()}
    res = {}
    for key in sorted({(o["region"], o["div"]) for o in out}):
        he = [o for o in out if (o["region"], o["div"]) == key and M.HELD[0] <= o["d"] and o["d"][:7] <= sealed]
        if len(he) < 200:
            continue
        q = np.clip(np.array([o["e"] for o in he]), 1e-6, 1 - 1e-6)
        y = np.array([o["w"] for o in he])
        l = -(y * np.log(q) + (1 - y) * np.log(1 - q))
        mo = defaultdict(list)
        for x, o in zip(l - math.log(2), he):
            mo[o["d"][:7]].append(x)
        mm = np.array([np.mean(v) for _, v in sorted(mo.items())])
        t = float(mm.mean() / (mm.std(ddof=1) / math.sqrt(len(mm))))
        z = np.log(q / (1 - q))
        b = 1.0
        for _ in range(50):   # calibration slope: P(win) = logistic(b x logit(q))
            pr = 1 / (1 + np.exp(-b * z))
            b -= np.sum((pr - y) * z) / (np.sum(pr * (1 - pr) * z * z) + 1e-9)
        ok = bool(l.mean() < math.log(2) and t <= crit and .7 <= b <= 1.3)
        res[f"{key[0]} {key[1]}"] = {"n": len(he), "ll": round(float(l.mean()), 4), "coin": .6931, "tMonth": round(t, 2),
                                     "months": [int((mm < 0).sum()), len(mm)], "acc": round(float(((q > .5) == (y == 1)).mean()), 3),
                                     "slope": round(b, 3), "pass": ok}
    res["promoted"] = sorted(k for k, v in res.items() if isinstance(v, dict) and v.get("pass"))
    res["_loop"] = {"looks": look, "sealed": sealed, "crit": round(crit, 2)}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
