#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T1 (prereg.md): the CS2 series model's player term, month-start ratings (fit form) vs series-day ratings (serve form).

    python3 scripts/research/ctx_nov27/tcs/t1_live_form.py     # ~8 min -> t1.json

Lockbox: rows after 2026-11-10 dropped."""
import gzip
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
import cs2_bo3  # noqa: E402
import cs2_model as CM  # noqa: E402
import cs2_players as CP  # noqa: E402
import names  # noqa: E402

LOCK = "2026-11-10"


def main():
    fj = json.loads(CP.FIT.read_text())
    p = fj["params"]
    M = CP.Maps()
    c = CP.contributions(M, np.array([fj["beta"][k] for k in CP.STATS]), np.array(fj["mline"]), p.get("pm", 0.0))
    H = json.load(gzip.open(CM.HIST))
    series = [r for r in H["series"] if r[6] == "vrs"]
    vrs = CM.Vrs(H["vrs"])
    bo3 = cs2_bo3.Bo3()
    rows, _ = CM.replay(series, vrs, json.loads(CM.FIT.read_text())["params"], bo3=bo3)
    rows = [r for r in rows if "2024-07-01" <= r["d"][:10] <= LOCK]
    nk, nkt = CP.nick_index(M, bo3)
    snaps = {}

    def th_at(T):
        if T not in snaps:
            snaps[T] = CP.ratings(M, c, T, p)[0]
        return snaps[T]

    def z_of(r, T):
        th = th_at(T)

        def mean(ros, k):
            ix = [nkt.get((names.key(q), k), nk.get(names.key(q))) for q in ros or []]
            v = [th[i] for i in ix if i is not None]
            return np.mean(v) if len(v) >= 3 else None
        a, b = mean(r["r"][4], r["a"]), mean(r["r"][5], r["b"])
        return (a - b) / 10 if a is not None and b is not None else 0.0

    for n, r in enumerate(rows):
        d = r["d"][:10]
        r["zm"] = z_of(r, CP.ordd(d[:7] + "-01"))
        r["zd"] = z_of(r, CP.ordd(d))
        if n % 3000 == 0:
            print(n, len(rows), len(snaps), file=sys.stderr)
    tr = [r for r in rows if CM.TUNE[0] <= r["d"] <= CM.TUNE[1]]
    he = [r for r in rows if r["d"] >= CM.HELD[0]]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])
    mo = np.array([r["d"][:7] for r in he])

    def run(fit_key, score_key):
        q = np.zeros(len(he))
        ws = {}
        for tier in (True, False):
            t_ = [r for r in tr if r["top"] == tier]
            idx = [i for i, r in enumerate(he) if r["top"] == tier]
            w = CM.fitlog(np.array([[r["x"], r["v"], r["t"], r[fit_key]] for r in t_]), np.array([r["s"] for r in t_]))
            ws["top" if tier else "rest"] = [round(float(z), 4) for z in w]
            q[idx] = 1 / (1 + np.exp(-np.array([[he[i]["x"], he[i]["v"], he[i]["t"], he[i][score_key]] for i in idx]) @ w))
        return CM.ll(q, s), ws

    def bymonth(dl, m):
        months = sorted(set(mo[m]))
        v = np.array([dl[m & (mo == x)].mean() for x in months])
        t = float(v.mean() / (v.std(ddof=1) + 1e-12) * math.sqrt(len(v)))
        return {"d": round(float(dl[m].mean()), 5), "t_month": round(t, 2), "months": f"{int((v < 0).sum())}/{len(v)}",
                "t_row": round(float(dl[m].mean() / (dl[m].std() + 1e-12) * math.sqrt(m.sum())), 2)}

    lB, wB = run("zm", "zm")
    lC, _ = run("zm", "zd")
    lA, wA = run("zd", "zd")
    allm = np.ones(len(he), bool)
    out = {"lock": LOCK, "nTune": len(tr), "nHeld": len(he), "nTop50": int(top.sum()), "snapshots": len(snaps),
           "ll": {"B month fit, month score": round(float(lB.mean()), 5), "C month fit, day score (live)": round(float(lC.mean()), 5),
                  "A day fit, day score": round(float(lA.mean()), 5)},
           "llTop50": {"B": round(float(lB[top].mean()), 5), "C": round(float(lC[top].mean()), 5), "A": round(float(lA[top].mean()), 5)},
           "w": {"B": wB, "A": wA},
           "A_vs_C": {"all": bymonth(lA - lC, allm), "top50": bymonth(lA - lC, top)},
           "A_vs_B": {"all": bymonth(lA - lB, allm), "top50": bymonth(lA - lB, top)},
           "C_vs_B": {"all": bymonth(lC - lB, allm), "top50": bymonth(lC - lB, top)},
           "zCorr": round(float(np.corrcoef([r["zm"] for r in he], [r["zd"] for r in he])[0, 1]), 4)}
    (HERE / "t1.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
