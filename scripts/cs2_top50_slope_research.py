#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike: one fixed slope on top-50 series, fit on the tune window only.

    python3 scripts/cs2_top50_slope_research.py   -> data/cs2_top50_slope_research.json (~2 min)

Top-50 series run sharp across the held window (slope .83). The walk-forward recalibrations in
scripts/cs2_calib_research.py failed; a constant has not been tried. One pre-registered form: the top-50 logit times
the slope its own tune-window rows give (Aug 2024 - Jun 2025, shrunk toward 1 with 1,000 rows as that script's
temperature is). Gate as there: held t by month under the Holm cut for a seventh test, top-50 t by month < -2.
"""
import json
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_calib_research as R  # noqa: E402
import cs2_model as CM  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "cs2_top50_slope_research.json"


def main():
    rows, W = R.build_rows()
    for r in rows:
        w = W["top"] if r["top"] else W["rest"]
        r["L"] = w[0] * r["x"] + w[1] * r["v"] + w[2] * r["t"] + w[3] * r["z"]
    tr = [r for r in rows if "2024-08-07" <= r["d"] <= "2025-06-30" and r["top"]]
    he = [r for r in rows if "2025-07-01" <= r["d"] < R.END]
    b = float(CM.fitlog(np.array([[r["L"]] for r in tr]), np.array([r["s"] for r in tr]))[0])
    k = (len(tr) * b + 1000) / (len(tr) + 1000)
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])
    mo = np.array([r["d"][:7] for r in he])
    L = np.array([r["L"] for r in he])
    z = np.where(top, k * L, L)
    dl = CM.ll(1 / (1 + np.exp(-z)), s) - CM.ll(1 / (1 + np.exp(-L)), s)
    cut = -NormalDist().inv_cdf(1 - .025 / 7)
    res = {"tuneSlope": round(b, 3), "tuneRows": len(tr), "applied": round(k, 3), "all": R.tt(dl, mo),
           "top50": R.tt(dl[top], mo[top]), "holmCut": round(cut, 2)}
    res["pass"] = bool(res["all"]["tMonth"] < cut and res["top50"]["tMonth"] < -2)
    out = {"held": ["2025-07-01", R.END], "fixed_top50_slope": res, "shipped": ["fixed_top50_slope"] if res["pass"] else []}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
