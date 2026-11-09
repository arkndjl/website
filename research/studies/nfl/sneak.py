# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL short yardage: QB sneak vs other runs vs passes on 3rd/4th-and-1, 2015-2026.
QB = player with 20+ pass attempts that season. Sneak = designed QB run (not a scramble, no dropback) at the middle.
Outcome: conversion (first down or TD), EPA. Same down, distance and field zone compared; CIs Wilson / game bootstrap.
Run: python3 -I sneak.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from common import load, wilson, cluster_mean_ci, r, write


def main():
    d = load()
    qbs = (d[d.pass_attempt == 1].groupby(["season", "passer_player_id"]).size().rename("n").reset_index())
    qbs = set(map(tuple, qbs[qbs.n >= 20][["season", "passer_player_id"]].to_numpy()))
    s = d[(d.down.isin([3, 4])) & (d.ydstogo == 1) & d.play_type.isin(["run", "pass"]) & (d.qb_kneel != 1) & (d.qb_spike != 1)
          & (d.qtr <= 4) & d.epa.notna()].copy()
    # skip end-of-game garbage: keep wp 5-95%
    s = s[s.wp.between(0.05, 0.95)]
    isqb = np.array([(a, b) in qbs for a, b in zip(s.season, s.rusher_player_id)])
    s["kind"] = np.where(s.play_type == "pass", "pass",
                         np.where(isqb & (s.qb_scramble != 1) & (s.qb_dropback != 1),
                                  np.where(s.run_location.fillna("middle") == "middle", "sneak", "qb run outside"), "other run"))
    s["conv"] = ((s.first_down == 1) | ((s.touchdown == 1) & (s.td_team == s.posteam))).astype(int)
    s["zone"] = np.where(s.yardline_100 <= 1, "goal1", np.where(s.goal_to_go == 1, "g2g", "field"))
    print(pd.crosstab(s.kind, s.down))
    out = {}
    for k in ["sneak", "other run", "pass", "qb run outside"]:
        m = s.kind == k
        w = wilson(int(s.conv[m].sum()), int(m.sum()))
        e = cluster_mean_ci(s.epa[m], s.game_id[m], B=500)
        out[k] = (w, e, int(m.sum()))
        print(k, int(m.sum()), "conv", [round(x, 3) for x in w], "epa", [round(x, 3) for x in e])
    # same state: non-goal-line, by down
    for dn in (3, 4):
        for k in ["sneak", "other run", "pass"]:
            m = (s.kind == k) & (s.down == dn) & (s.zone == "field")
            print("down", dn, "field", k, int(m.sum()), [round(x, 3) for x in wilson(int(s.conv[m].sum()), int(m.sum()))])
    # reweight other-run and pass to the sneak's mix of down x zone (direct standardization)
    cells = s[s.kind == "sneak"].groupby(["down", "zone"]).size()
    wts = cells / cells.sum()
    std = {}
    for k in ["sneak", "other run", "pass"]:
        rate = s[s.kind == k].groupby(["down", "zone"]).conv.mean()
        std[k] = float((rate.reindex(wts.index) * wts).sum())
    print("standardized to sneak mix", std)
    # by season: sneak and other run conv
    seas = {}
    for k in ["sneak", "other run", "pass"]:
        pts = []
        for yr in sorted(s.season.unique()):
            m = (s.kind == k) & (s.season == yr)
            w = wilson(int(s.conv[m].sum()), int(m.sum()))
            pts.append(dict(x=int(yr), y=r(w[0]), lo=r(w[1]), hi=r(w[2]), n=int(m.sum())))
        seas[k] = pts
        print(k, [(p["x"], p["y"], p["n"]) for p in pts])
    # sneak share by season and PHI/BUF vs rest
    print("sneak share", s.groupby("season").apply(lambda x: (x.kind == "sneak").mean()).round(3).to_dict())
    for nm, m in [("PHI", s.posteam == "PHI"), ("BUF", s.posteam == "BUF"), ("rest", ~s.posteam.isin(["PHI", "BUF"]))]:
        mm = m & (s.kind == "sneak")
        print("sneak", nm, int(mm.sum()), [round(x, 3) for x in wilson(int(s.conv[mm].sum()), int(mm.sum()))])
    # split halves
    halves = {}
    for nm, m in [("2015-20", s.season <= 2020), ("2021-26", s.season >= 2021)]:
        a = s[m & (s.kind == "sneak")]
        b = s[m & (s.kind == "other run")]
        halves[nm] = (a.conv.mean(), len(a), b.conv.mean(), len(b))
        print(nm, halves[nm])
    rest = s[~s.posteam.isin(["PHI", "BUF"]) & (s.kind == "sneak")]
    w_rest = wilson(int(rest.conv.sum()), len(rest))
    # difference CI sneak - other run (game bootstrap on conversion)
    a = s[s.kind.isin(["sneak", "other run"])].copy()
    a["is"] = (a.kind == "sneak").astype(int)
    g = a.groupby(["game_id", "is"]).conv.agg(["sum", "count"]).unstack(fill_value=0)
    rng = np.random.default_rng(4)
    idx = rng.integers(0, len(g), (1000, len(g)))
    S1, C1 = g[("sum", 1)].to_numpy(), g[("count", 1)].to_numpy()
    S0, C0 = g[("sum", 0)].to_numpy(), g[("count", 0)].to_numpy()
    diffs = S1[idx].sum(1) / C1[idx].sum(1) - S0[idx].sum(1) / C0[idx].sum(1)
    dci = (S1.sum() / C1.sum() - S0.sum() / C0.sum(), *np.percentile(diffs, [2.5, 97.5]))
    print("sneak - other run", dci)

    sn, ot, ps = out["sneak"], out["other run"], out["pass"]
    study = {
        "id": "nfl-qb-sneak",
        "sport": "NFL",
        "question": "On 3rd or 4th and 1, does the QB sneak convert more often than other plays?",
        "answer": (f"Yes. Sneaks convert {sn[0][0]*100:.0f}%, other runs {ot[0][0]*100:.0f}%, passes {ps[0][0]*100:.0f}%. "
                   f"Sneak share of these plays was {s[s.season==2015].kind.eq('sneak').mean()*100:.0f}% in 2015, "
                   f"{s[s.season==2025].kind.eq('sneak').mean()*100:.0f}% in 2025."),
        "findings": [
            f"Sneak {sn[0][0]*100:.1f}% ({sn[0][1]*100:.1f}-{sn[0][2]*100:.1f}, n={sn[2]:,}); other run {ot[0][0]*100:.1f}% "
            f"({ot[0][1]*100:.1f}-{ot[0][2]*100:.1f}, n={ot[2]:,}).",
            f"Pass {ps[0][0]*100:.1f}% ({ps[0][1]*100:.1f}-{ps[0][2]*100:.1f}, n={ps[2]:,}). Gap sneak minus other run "
            f"{dci[0]*100:+.1f} pts ({dci[1]*100:+.1f} to {dci[2]*100:+.1f}).",
            f"EPA per play: sneak {sn[1][0]:+.2f} ({sn[1][1]:+.2f} to {sn[1][2]:+.2f}), other run {ot[1][0]:+.2f}, pass {ps[1][0]:+.2f}.",
            f"Without PHI and BUF, sneaks still convert {w_rest[0]*100:.1f}% ({w_rest[1]*100:.1f}-{w_rest[2]*100:.1f}, n={len(rest):,}).",
        ],
        "method": ("Conversion = first down or TD. Same down and distance; reweighted to the sneak's mix of down and goal-line "
                   f"state gives {std['sneak']*100:.0f}/{std['other run']*100:.0f}/{std['pass']*100:.0f}%. "
                   "Yards to go of 1 hides inches, so sneaks may get the shortest spots."),
        "data": f"nflverse play-by-play, 2015 to 2026 wk 8, 3rd/4th-and-1 runs and passes, WP 5-95%, {len(s):,} plays.",
        "n": int(len(s)),
        "robust": True,
        "interest": 3,
        "split_check": (f"2015-20: sneak {halves['2015-20'][0]*100:.0f}% (n={halves['2015-20'][1]:,}) vs other run "
                        f"{halves['2015-20'][2]*100:.0f}%; 2021-26: {halves['2021-26'][0]*100:.0f}% (n={halves['2021-26'][1]:,}) "
                        f"vs {halves['2021-26'][2]*100:.0f}%."),
        "chart": {
            "type": "line",
            "title": "Conversion rate on 3rd/4th-and-1 by play type",
            "x_label": "season", "y_label": "converted %", "y_fmt": "pct", "x_reverse": False,
            "ref": None, "mark": None,
            "series": [{"name": "QB sneak", "points": seas["sneak"]}, {"name": "other run", "points": seas["other run"]},
                       {"name": "pass", "points": seas["pass"]}],
        },
    }
    write(study)


if __name__ == "__main__":
    main()
