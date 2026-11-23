#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lower-tier matches in the CS2 player Elo (Nov 23 2026): does playing bo3.gg matches that never join a Valve series
(mostly tier C/D, 2024 on) through the player ratings improve the series model on Valve's series, out of sample?

    python3 scripts/cs2_lowtier_research.py   # ~10-20 min -> data/cs2_lowtier_research.json

Why bo3.gg and not Liquipedia: Liquipedia's robots.txt bars every agent from /counterstrike/api.php (and ClaudeBot from
the site), its API terms keep the MediaWiki API for editing, and LiquipediaDB is Enterprise-only (Nov 2026).
Pre-registered here before any held number was read:
  - extra rows (cs2_bo3.lowtier) = bo3.gg matches with 1+ finished map (cs2_bo3.real_map), not joined to a Valve series, since
    2024-01-01, both sides with 4+ players in scripts/data/cs2_pstats (top 5 by maps in the match). Nicks map to Valve's
    spelling through names.key. Extra rows update player Elo, team Elo, region offsets; they are never scored.
  - knobs (tune Aug 2024 - Jun 2025 only): kx (K multiplier on extra rows) in {.25, .5, 1}, tiers {b,c,d} or {c,d}.
  - scored: the same Valve series rows as cs2_model.fit, blend fit on tune, held Jul 2025 on.
  - SHIP if held all-series log loss improves with t by month <= -2 and top-50 mean not worse (> +.0005 fails).
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
OUT = ROOT / "data" / "cs2_lowtier_research.json"


def run(series, ext, p, bo3):
    """ext: the tier string (cs2_model.replay builds the rows through cs2_bo3.lowtier), or None for the base."""
    b = cs2_bo3.Bo3(bo3.raw)
    rows, _ = M.replay(series, M.Vrs(H["vrs"]), dict(p, kx=p.get("kx", 0) if ext else 0, xt=ext or ""), bo3=b)
    return rows, len(getattr(b, "joined_all", b.joined))


def score(rows):
    win = lambda w: [r for r in rows if w[0] <= r["d"] <= w[1]]  # noqa: E731
    tr, he = win(M.TUNE), win(M.HELD)
    q, _ = M.tiered(tr, he, "blend")
    s = np.array([r["s"] for r in he])
    # tune score: fit on the first 70% of tune, score the rest (no held rows)
    cut = tr[int(len(tr) * .7)]["d"]
    a, bb = [r for r in tr if r["d"] < cut], [r for r in tr if r["d"] >= cut]
    qt, _ = M.tiered(a, bb, "blend")
    return M.ll(q, s), he, float(M.ll(qt, np.array([r["s"] for r in bb])).mean())


def bymonth(dl, he):
    mo = defaultdict(list)
    for x, r in zip(dl, he):
        mo[r["d"][:7]].append(x)
    m = np.array([np.mean(v) for _, v in sorted(mo.items())])
    return float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))), int((m < 0).sum()), len(m)


def with_rwa(rows_by, live):
    """Add the shipped fourth term (the five's RWA, cs2_players.Live) and score base vs pick on 4 terms."""
    for rows in rows_by.values():
        for r in rows:
            r["z"] = live.z(r["r"][4], r["a"], r["r"][5], r["b"], r["d"])
    out = {}
    for nm, rows in rows_by.items():
        tr = [r for r in rows if M.TUNE[0] <= r["d"] <= M.TUNE[1]]
        he = [r for r in rows if r["d"] >= M.HELD[0]]
        q = np.zeros(len(he))
        for tier in (True, False):
            t_ = [r for r in tr if r["top"] == tier]
            idx = [i for i, r in enumerate(he) if r["top"] == tier]
            f = lambda r: [r["x"], r["v"], r["t"], r["z"]]  # noqa: E731
            w = M.fitlog(np.array([f(r) for r in t_]), np.array([r["s"] for r in t_]))
            q[idx] = 1 / (1 + np.exp(-np.array([f(he[i]) for i in idx]) @ w))
        out[nm] = (M.ll(q, np.array([r["s"] for r in he])), he)
    return out


if __name__ == "__main__" and "--rwa" in sys.argv:
    import cs2_players
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    bo3 = cs2_bo3.Bo3(raw)
    bo3.raw = raw
    res = json.loads(OUT.read_text())
    p = dict(M.DEF)
    bo3.join(series)
    ext = res["pick"]["tiers"]
    rb, _ = run(series, None, p, bo3)
    rx, _ = run(series, ext, dict(p, kx=res["pick"]["kx"]), bo3)
    live = cs2_players.Live(cs2_bo3.Bo3(raw))
    assert live.w, "RWA term off"
    o = with_rwa({"base": rb, "pick": rx}, live)
    dl = o["pick"][0] - o["base"][0]
    he = o["base"][1]
    top = np.array([r["top"] for r in he])
    t, neg, nm = bymonth(dl, he)
    res["heldWithRwa"] = {"base": float(o["base"][0].mean()), "pick": float(o["pick"][0].mean()), "d": float(dl.mean()),
                          "tMonth": t, "monthsBetter": [neg, nm], "top50": {"d": float(dl[top].mean()),
                          "tMonth": bymonth(dl[top], [r for r, k in zip(he, top) if k])[0]}}
    res["ship"] = bool(res["ship"] and dl.mean() < 0 and t <= -2 and dl[top].mean() <= .0005)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res["heldWithRwa"], indent=1), res["ship"])
elif __name__ == "__main__":
    H = json.load(gzip.open(M.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    raw = cs2_bo3.load()
    bo3 = cs2_bo3.Bo3(raw)
    bo3.raw = raw
    p = dict(M.DEF)
    bo3.join(series)
    base_rows, nj = run(series, None, p, bo3)
    lb, he, tb = score(base_rows)
    print("base joined", nj, "held", lb.mean(), "tune", tb, flush=True)
    grid = []
    nx = {t: len(cs2_bo3.lowtier(bo3, series, set(t))) for t in ("bcd", "cd")}
    for tiers in ("bcd", "cd"):
        ext = tiers
        for kx in (.25, .5, 1.0):
            rows, nj2 = run(series, ext, dict(p, kx=kx), bo3)
            assert len(rows) == len(base_rows)
            l, he2, t = score(rows)
            grid.append({"tiers": tiers, "kx": kx, "n": nx[tiers], "joined": nj2, "tune": t, "_l": l})
            print(tiers, kx, len(ext), nj2, "tune", round(t - tb, 5), flush=True)
    best = min(grid, key=lambda g: g["tune"])
    dl = best["_l"] - lb
    top = np.array([r["top"] for r in he])
    t, neg, nm = bymonth(dl, he)
    res = {"base": {"held": float(lb.mean()), "tune": tb, "joined": nj}, "grid": [{k: v for k, v in g.items() if k != "_l"}
           | {"dTune": g["tune"] - tb} for g in grid], "pick": {"tiers": best["tiers"], "kx": best["kx"]},
           "held": {"n": len(he), "d": float(dl.mean()), "tMonth": t, "monthsBetter": [neg, nm],
                    "top50": {"n": int(top.sum()), "d": float(dl[top].mean()), "tMonth": bymonth(dl[top], [r for r, k in zip(he, top) if k])[0]},
                    "rest": {"d": float(dl[~top].mean())}}}
    res["ship"] = bool(res["held"]["d"] < 0 and t <= -2 and res["held"]["top50"]["d"] <= .0005)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
