#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Counter-Strike: does the player Elo term deserve less weight right after a roster change?

    python3 scripts/cs2_roster_elo_research.py   -> data/cs2_roster_elo_research.json (~2 min)

scripts/cs2_calib_research.py found the player Elo term loses about a third of its weight in the months after breaks
and transfer windows, and that days since a player's last series (its "stale" term) passes on all series but not on
the top 50. Player Elo credits a player for his old team's results, so the cause may be the roster, not the idle time.
One pre-registered form: a fifth term, player Elo x fresh, fresh = mean over the two teams of exp(-days since the
team's listed five last changed / 60). Same rows, tune and held windows and gate as cs2_calib_research.py (held t by
month under the Holm cut for a sixth test on that record, and top-50 t by month < -2). The hypothesis came from that
script's weak-month weights, which include held months, so a pass here would still need the live months to confirm.
"""
import gzip
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_calib_research as R  # noqa: E402
import cs2_model as CM  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "cs2_roster_elo_research.json"
TAU = 60.0


def main():
    rows, W = R.build_rows()
    series = [r for r in json.load(gzip.open(CM.HIST))["series"] if r[6] == "vrs"]
    assert len(series) == len(rows)
    last, changed = {}, {}
    for r, S in zip(rows, series):
        d = R.od(S[0])
        f = []
        for team, ros in ((r["a"], S[4]), (r["b"], S[5])):
            if ros:
                five = frozenset(ros)
                if team in last and five != last[team]:
                    changed[team] = d
                last[team] = five
            f.append(math.exp(-(d - changed[team]) / TAU) if team in changed else 0.0)
        r["fresh"] = sum(f) / 2
        w = W["top"] if r["top"] else W["rest"]
        r["L"] = w[0] * r["x"] + w[1] * r["v"] + w[2] * r["t"] + w[3] * r["z"]
    tr = [r for r in rows if "2024-08-07" <= r["d"] <= "2025-06-30"]
    he = [r for r in rows if "2025-07-01" <= r["d"] < R.END]
    s = np.array([r["s"] for r in he])
    top = np.array([r["top"] for r in he])
    mo = np.array([r["d"][:7] for r in he])

    def tiered(F):
        q, ws = np.zeros(len(he)), {}
        for tier in (True, False):
            T = [r for r in tr if r["top"] == tier]
            w = CM.fitlog(np.array([F(r) for r in T]), np.array([r["s"] for r in T]))
            ws["top" if tier else "rest"] = [round(float(x), 3) for x in w]
            idx = np.where(top == tier)[0]
            q[idx] = 1 / (1 + np.exp(-np.array([F(he[i]) for i in idx]) @ w))
        return CM.ll(q, s), ws
    F4 = lambda r: [r["x"], r["v"], r["t"], r["z"]]  # noqa: E731
    b4, _ = tiered(F4)
    b5, ws = tiered(lambda r: F4(r) + [r["x"] * r["fresh"]])
    dl = b5 - b4
    cut = -NormalDist().inv_cdf(1 - .025 / 6)
    res = {"all": R.tt(dl, mo), "top50": R.tt(dl[top], mo[top]), "weights": ws, "holmCut": round(cut, 2),
           "freshMean": round(float(np.mean([r["fresh"] for r in he])), 3),
           "weakMonths": {m: round(float(dl[mo == m].mean()), 4) for m in R.WEAK if (mo == m).any()}}
    res["pass"] = bool(res["all"]["tMonth"] < cut and res["top50"]["tMonth"] < -2)
    out = {"held": ["2025-07-01", R.END], "tau": TAU, "n": len(he), "fresh_x_playerElo": res,
           "shipped": ["fresh_x_playerElo"] if res["pass"] else []}
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
