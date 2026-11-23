#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lower-tier teams in ARK Ranking (Nov 23 2026): are the ratings good enough on bo3.gg tier B/C/D matches to rank
those teams, and does playing those matches through the player Elo (kx, shipped Nov 23 on Valve's series) also make
the ratings better on the lower-tier matches themselves?

    python3 scripts/cs2_ark_lowtier_research.py   # ~5 min -> data/cs2_ark_lowtier_research.json

Pre-registered before any held number was read:
  - scored rows: bo3.gg lower-tier matches (cs2_bo3.lowtier, tiers b/c/d, no Valve series), the pre-match gap of the
    five's player Elo (+ region offset). P = logistic(c x gap), c fit on tune (Aug 2024 - Jun 2025), held Jul 2025 on.
  - arms: shipped (kx .5: these matches update the players) vs base (kx ~0: same rows merged, players not updated).
  - A (rank them): ship deeper ARK coverage (lower-tier series count toward ARK's 15-series / 120-day rule) if the
    shipped arm's held log loss beats a coin flip (.6931) with t by month <= -2 on these matches.
  - B (kx helps them): reported; kx is already shipped on Valve's series (data/cs2_lowtier_research.json).
"""
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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "cs2_ark_lowtier_research.json"


def fitc(x, s):
    c = 1.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-c * x))
        g = np.sum((p - s) * x)
        h = np.sum(p * (1 - p) * x * x) + 1e-9
        c -= g / h
    return float(c)


def ll(p, s):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(s * np.log(p) + (1 - s) * np.log(1 - p))


def bymonth(dl, d):
    mo = defaultdict(list)
    for x, m in zip(dl, d):
        mo[m[:7]].append(x)
    m = np.array([np.mean(v) for _, v in sorted(mo.items())])
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))), int((m < 0).sum()), len(m)


def arm(series, H, raw, kx):
    p = dict(json.loads(M.FIT.read_text())["params"], kx=kx, xrows=True)
    _, st = M.replay(series, M.Vrs(H["vrs"]), p, bo3=cs2_bo3.Bo3(raw))
    return {(r["d"], r["a"], r["b"]): r for r in st["xrows"]}


if __name__ == "__main__":
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    A, B = arm(series, H, raw, 0.5), arm(series, H, raw, 1e-9)
    keys = sorted(set(A) & set(B))
    res = {"n": len(keys)}
    out = {}
    for nm, X in (("shipped", A), ("base", B)):
        tr = [X[k] for k in keys if M.TUNE[0] <= k[0] <= M.TUNE[1]]
        he = [X[k] for k in keys if k[0] >= M.HELD[0]]
        c = fitc(np.array([r["x"] for r in tr]), np.array([r["s"] for r in tr]))
        q = 1 / (1 + np.exp(-c * np.array([r["x"] for r in he])))
        s = np.array([r["s"] for r in he])
        out[nm] = (ll(q, s), he, c, q)
        res[nm] = {"c": round(c, 3), "held": float(ll(q, s).mean()), "nHeld": len(he), "acc": float(((q > .5) == (s == 1)).mean()),
                   "byTier": {t: float(ll(q, s)[[r["tier"] == t for r in he]].mean()) for t in ("b", "c", "d") if any(r["tier"] == t for r in he)}}
    l, he = out["shipped"][0], out["shipped"][1]
    t, neg, nm_ = bymonth(l - math.log(2), [r["d"] for r in he])
    res["A"] = {"vsCoin": float(l.mean() - math.log(2)), "tMonth": t, "monthsBetter": [neg, nm_], "pass": bool(l.mean() < math.log(2) and t <= -2)}
    dl = out["shipped"][0] - out["base"][0]
    t2, neg2, n2 = bymonth(dl, [r["d"] for r in he])
    res["B"] = {"d": float(dl.mean()), "tMonth": t2, "monthsBetter": [neg2, n2]}
    q = out["shipped"][3]
    s = np.array([r["s"] for r in he])
    bins = np.clip((q * 10).astype(int), 0, 9)
    res["calibration"] = [[round(float(q[bins == b].mean()), 3), round(float(s[bins == b].mean()), 3), int((bins == b).sum())] for b in range(10) if (bins == b).sum() >= 30]
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
