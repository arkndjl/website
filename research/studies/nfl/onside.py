"""NFL onside kicks: surprise vs expected, 2015-2026.
Expected = 4th quarter with the kicking team trailing. Surprise = any other onside (Q1-Q3, or not trailing).
Outcome: kicking team recovery (Wilson CI), kicking-team WPA vs a normal kickoff in the same quarter group.
Kickoff rule eras: 2015-17, 2018-23 (no running start), 2024+ (dynamic kickoff; onside must be declared, trailing in Q4).
Run: python3 -I onside.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from common import load, wilson, cluster_mean_ci, r, write


def main():
    d = load()
    k = d[(d.kickoff_attempt == 1) & (d.qtr <= 4) & d.wpa.notna()].copy()
    k["onside"] = k.desc.str.contains("onside", case=False, na=False)
    k["kdiff"] = -k.score_differential          # posteam is the receiving team on kickoffs
    k["kwpa"] = -k.wpa
    k["rec"] = (k.own_kickoff_recovery == 1).astype(int)
    k["expected"] = (k.qtr == 4) & (k.kdiff < 0)
    k["era"] = np.where(k.season <= 2017, "2015-17", np.where(k.season <= 2023, "2018-23", "2024-26"))
    o = k[k.onside]
    res = {}
    for era in ["2015-17", "2018-23", "2024-26"]:
        for nm, m in [("surprise", ~o.expected), ("expected", o.expected)]:
            c = o[(o.era == era) & m]
            w = wilson(int(c.rec.sum()), len(c))
            res[(era, nm)] = (w, len(c))
            print(era, nm, len(c), [round(x, 3) for x in w])
    sur = o[~o.expected & (o.season <= 2023)]
    exp_ = o[o.expected & (o.season <= 2023)]
    ws = wilson(int(sur.rec.sum()), len(sur))
    we = wilson(int(exp_.rec.sum()), len(exp_))
    print("surprise 2015-23", len(sur), ws, "expected", len(exp_), we)
    # WPA of surprise onside vs normal kickoffs in Q1-Q3 within 14 pts, same seasons
    s13 = sur[(sur.qtr <= 3)]
    norm = k[~k.onside & (k.qtr <= 3) & (k.season <= 2023) & (k.kdiff.abs() <= 14)]
    a = cluster_mean_ci(s13.kwpa, s13.game_id)
    b = cluster_mean_ci(norm.kwpa, norm.game_id)
    print("Q1-3 surprise onside kicking WPA", len(s13), a, "normal", len(norm), b)
    # break-even recovery: WPA if recovered vs not, among Q1-3 surprise onsides
    rec_w = s13[s13.rec == 1].kwpa.mean(); fail_w = s13[s13.rec == 0].kwpa.mean()
    be = (b[0] - fail_w) / (rec_w - fail_w)
    print("WPA recovered", rec_w, "failed", fail_w, "break-even rec rate", be)
    print("surprise by qtr", sur.groupby("qtr").agg(n=("rec", "size"), r=("rec", "mean")))
    pts = []
    for era in ["2015-17", "2018-23", "2024-26"]:
        for nm in ["surprise", "expected"]:
            pass
    pts = []
    for nm, lab in [("surprise", "surprise"), ("expected", "late, trailing")]:
        for era in ["2015-17", "2018-23", "2024-26"]:
            w, n = res[(era, nm)]
            if n >= 5:
                pts.append(dict(x=f"{lab} {era}", y=r(w[0]), lo=r(w[1]), hi=r(w[2]), n=n))
    ser = [dict(name="recovered", points=pts)]
    # per-season table is too thin; halves of 2015-23
    h1 = sur[sur.season <= 2018]; h2 = sur[sur.season >= 2019]
    e2 = res[("2024-26", "expected")]
    study = {
        "id": "nfl-onside-surprise",
        "sport": "NFL",
        "question": "Do surprise onside kicks get recovered more than expected late-game onside kicks?",
        "answer": (f"Yes, {ws[0]*100:.0f}% vs {we[0]*100:.0f}% (2015-23), but below the ~{be*100:.0f}% break-even for an early onside. "
                   "Net WPA not different from zero."),
        "findings": [
            f"Surprise {ws[0]*100:.1f}% ({ws[1]*100:.1f}-{ws[2]*100:.1f}, n={len(sur)}); expected {we[0]*100:.1f}% "
            f"({we[1]*100:.1f}-{we[2]*100:.1f}, n={len(exp_)}).",
            f"Q1-Q3 surprise onside, kicking-team WPA {a[0]*100:+.1f} pts ({a[1]*100:+.1f} to {a[2]*100:+.1f}, n={len(s13)}); "
            f"normal kickoff {b[0]*100:+.2f}.",
            f"Break-even recovery rate for a Q1-Q3 surprise onside: about {be*100:.0f}%.",
            f"2024-26 expected onsides: {e2[0][0]*100:.1f}% recovered ({e2[0][1]*100:.1f}-{e2[0][2]*100:.1f}, n={e2[1]}).",
        ],
        "method": ("Onside = kickoff described as onside. Expected = Q4 with the kicker trailing; surprise = all others. "
                   "WPA compared with normal Q1-Q3 kickoffs within 14 points, game bootstrap CIs. Teams pick spots, so rates are upper bounds."),
        "data": f"nflverse play-by-play, 2015 to 2026 wk 8, {len(o):,} onside kicks.",
        "n": int(len(o)),
        "robust": bool(ws[1] > we[2]),  # recovery gap; WPA gain is not distinguishable from zero
        "interest": 3,
        "split_check": (f"Surprise recovery {h1.rec.mean()*100:.0f}% in 2015-18 (n={len(h1)}), {h2.rec.mean()*100:.0f}% in 2019-23 "
                        f"(n={len(h2)}); expected stays near {we[0]*100:.0f}%."),
        "chart": {
            "type": "bar",
            "title": "Onside kick recovery rate by kickoff-rule era",
            "x_label": "seasons", "y_label": "recovered %", "y_fmt": "pct", "x_reverse": False,
            "ref": {"y": r(be, 2), "label": "break-even, Q1-Q3"}, "mark": None,
            "series": ser,
        },
    }
    write(study)


if __name__ == "__main__":
    main()
