#!/usr/bin/env python3
"""CS2: round-share rating used as a map-win chance (math audit Nov 2 2026, OPEN item "CS2 map round-share vs map-win
scale"). Research script; results in data/cs2_scale_research.json.

cs2_bo3.TeamMaps learns R (team) and Mo (team x map) so that sig(R_a + Mo_a - R_b - Mo_b) tracks the map's stretched
round share (.5 + (share - .5) / span x .5, span .3), then TeamMaps.chance feeds the same sig(...) into the veto and
series_from_maps as each map's WIN chance. A 58% round share wins far more than 58% of maps, so the per-map chances
are too close to .5 and the Bo3 / Bo5 combination (p^2 (3 - 2p)) bends them on the wrong scale; the blend's weight on
the series logit is linear, so it cannot undo the bend.

Fix tested: map win chance = sig(c x z), z the round-share logit, c a one-parameter logistic fit (no intercept, each
map from a random side) on maps played before the month of the match (refit each month, walk-forward), the same in
the veto. Scored with cs2_model's own harness: player Elo replay + tiered blend fit on Aug 2024 - Jun 2025, held out
Jul 2025 on; paired log loss (per series), t, months won; also series that join a bo3 match only.
Pass: held log loss lower at t <= -2 (all series) and no worse on the top 50.

    python3 scripts/cs2_scale_research.py      # needs scripts/.cache/cs/vrs (cs2_data.py clones it)
"""
import gzip
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cs2_bo3 as B  # noqa: E402
import cs2_model as M  # noqa: E402

OUT = M.ROOT / "data" / "cs2_scale_research.json"
ORIG = B.TeamMaps


def fit_c(z, y, c=1.0):
    z, y = np.asarray(z), np.asarray(y)
    for _ in range(30):
        q = 1 / (1 + np.exp(-c * z))
        g = float(z @ (q - y)); h = float((z * z) @ (q * (1 - q))) + 1e-9
        c -= g / h
    return c


class Calibrated(ORIG):
    """TeamMaps with each map's win chance on the map-win scale: sig(c x round-share logit), c refit monthly."""
    log = None

    def __init__(self, bo3, p=B.TM):
        super().__init__(bo3, p)
        self.c, self.zs, self.ys, self.mo = 1.0, [], [], None
        self.rnd = random.Random(7)
        Calibrated.log = self

    def chance(self, a, b, bo, d):
        x = self.R.get(a, 0.0) - self.R.get(b, 0.0)
        pool = self.pool(d)
        c = self.c
        if not pool:
            return B.logit(B.series_from_maps([B.sig(c * x)], bo))
        da = {mp: self.Mo[(a, mp)] - self.Mo[(b, mp)] for mp in pool}
        pv = [B.series_from_maps([B.sig(c * (x + da.get(q, 0))) for q in played] or [B.sig(c * x)], bo)
              for played in B.veto(da, pool, bo)]
        return B.logit(sum(pv) / len(pv))

    def play(self, upto=None, ask=None):
        out = {}
        p = self.p
        for m in sorted(self.b.mt.values(), key=lambda r: r[1]):
            if upto and m[1] >= upto:
                break
            mo = m[1][:7]
            if mo != self.mo:
                if len(self.zs) > 500:
                    self.c = fit_c(self.zs, self.ys, self.c)
                self.mo = mo
            a, b = m[2], m[3]
            for t in (a, b):
                if t not in self.R:
                    self.R[t] = p["new"].get(m[10], 0.0)
            if ask and m[0] in ask:
                v = self.chance(a, b, m[9] or 3, m[1])
                for i in ask[m[0]]:
                    out[i] = (v, a)
            for g in self.b.maps.get(m[0], []):
                w, lo, mp = g[5], g[6], g[3]
                if {w, lo} != {a, b}:
                    continue
                self.recent.append((m[1][:10], mp))
                z = self.R[w] + self.Mo[(w, mp)] - self.R[lo] - self.Mo[(lo, mp)]
                sd = 1 if self.rnd.random() < .5 else -1
                self.zs.append(sd * z); self.ys.append(1.0 if sd == 1 else 0.0)
                e = B.sig(z)
                s = B.round_share(g[7], g[8], p["span"])
                for t, sg in ((w, 1), (lo, -1)):
                    self.R[t] += sg * p["K"] * (1 + p["Kn"] * math.exp(-self.n[t] / 30)) * (s - e)
                    self.n[t] += 1
                    self.Mo[(t, mp)] += sg * p["Km"] / (1 + self.nm[(t, mp)] / p["nm0"]) * (s - e)
                    self.nm[(t, mp)] += 1
            if len(self.recent) > 20000:
                self.recent = self.recent[-12000:]
        return out


def run(cls):
    B.TeamMaps = cls
    try:
        H = json.load(gzip.open(M.HIST))
        series = [r for r in H["series"] if r[6] == "vrs"]
        vrs = M.Vrs(H["vrs"])
        bo3 = B.Bo3()
        rows, _ = M.replay(series, vrs, dict(M.DEF), bo3=bo3)
    finally:
        B.TeamMaps = ORIG
    win = lambda w: [r for r in rows if w[0] <= r["d"] <= w[1]]  # noqa: E731
    tr, he = win(M.TUNE), win(M.HELD)
    q, w = M.tiered(tr, he, "blend")
    return he, q, w, bo3


def main():
    he0, q0, w0, bo3 = run(ORIG)
    he1, q1, w1, _ = run(Calibrated)
    assert [r["i"] for r in he0] == [r["i"] for r in he1]
    s = np.array([r["s"] for r in he0])
    l0, l1 = M.ll(q0, s), M.ll(q1, s)
    lg = Calibrated.log
    zs, ys = np.array(lg.zs), np.array(lg.ys)
    rep = {"cFinal": round(lg.c, 3), "cAllMaps": round(fit_c(zs, ys), 3), "nMaps": int(len(zs)),
           "llMapWinAtC1": round(float(M.ll(1 / (1 + np.exp(-zs)), ys).mean()), 4),
           "llMapWinAtC": round(float(M.ll(1 / (1 + np.exp(-fit_c(zs, ys) * zs)), ys).mean()), 4),
           "weightsTune": {"base": w0, "calibrated": w1}}
    subs = {"all": np.ones(len(s), bool), "joined": np.array([r["t"] != 0 for r in he1]),
            "top50": np.array([r["top"] for r in he0])}
    months = sorted({r["d"][:7] for r in he0})
    md = np.array([r["d"][:7] for r in he0])
    for nm, m in subs.items():
        d = (l1 - l0)[m]
        won = sum(1 for mo in months if (m & (md == mo)).any() and (l1 - l0)[m & (md == mo)].mean() < 0)
        rep[nm] = {"n": int(m.sum()), "base": round(float(l0[m].mean()), 4), "calibrated": round(float(l1[m].mean()), 4),
                   "d": round(float(d.mean()), 5), "t": round(M.tstat(d), 2), "monthsWon": f"{won}/{len(months)}"}
    rep["verdict"] = "PASS" if rep["all"]["t"] <= -2 and rep["top50"]["d"] <= 0 else "FAIL"
    print(json.dumps(rep, indent=1))
    OUT.write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
