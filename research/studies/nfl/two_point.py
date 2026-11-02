"""NFL two-point vs extra point, 2015-2026 (XP moved to the 15 in 2015).

1) Success rates by season (Wilson CIs), expected points per try.
2) Situational value: expected WPA of each option per PAT, from pooled success rates and boosted models of nflverse WPA
   on the PAT state for each outcome branch (2pt good / 2pt failed / XP good / XP missed), cross-fit by game.
3) Down 14 late, after the first TD (down 8 at the PAT): closed-form win chance given two TDs and no other scoring.
Run: python3 -I two_point.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from common import load, wilson, cluster_mean_ci, r, write

FEAT = ["score_differential", "game_seconds_remaining", "wp", "posteam_timeouts_remaining", "defteam_timeouts_remaining"]


def main():
    d = load()
    p = d[((d.two_point_attempt == 1) | (d.extra_point_attempt == 1)) & d.wp.notna() & d.wpa.notna()].copy()
    p = p[p.qtr <= 4].reset_index(drop=True)
    p["two"] = (p.two_point_attempt == 1).astype(int)
    p["ok"] = np.where(p.two == 1, p.two_point_conv_result == "success", p.extra_point_result == "good").astype(int)
    p["branch"] = np.where(p.two == 1, np.where(p.ok == 1, "S", "F"), np.where(p.ok == 1, "G", "M"))
    print(p.branch.value_counts().to_dict())

    # 1) by season
    rows = []
    for s in sorted(p.season.unique()):
        ps = p[p.season == s]
        t = ps[ps.two == 1]
        x = ps[ps.two == 0]
        w2 = wilson(int(t.ok.sum()), len(t))
        w1 = wilson(int(x.ok.sum()), len(x))
        rows.append((int(s), w2, len(t), w1, len(x)))
        print(s, f"2pt {w2[0]:.3f} ({w2[1]:.3f}-{w2[2]:.3f}) n={len(t)} | XP {w1[0]:.3f} ({w1[1]:.3f}-{w1[2]:.3f}) n={len(x)}"
                 f" | EP 2pt {2*w2[0]:.3f} XP {w1[0]:.3f} | 2pt share {len(t)/len(ps):.3f}")
    t, x = p[p.two == 1], p[p.two == 0]
    W2, W1 = wilson(int(t.ok.sum()), len(t)), wilson(int(x.ok.sum()), len(x))
    print("pooled 2pt", W2, len(t), "XP", W1, len(x))
    # pass vs run on 2pt
    for nm, m in [("pass", t.play_type == "pass"), ("run", t.play_type == "run")]:
        print("2pt", nm, wilson(int(t.ok[m].sum()), int(m.sum())), int(m.sum()))
    # EP difference with CI (independent binomials, normal approx)
    se = np.sqrt(4 * W2[0] * (1 - W2[0]) / len(t) + W1[0] * (1 - W1[0]) / len(x))
    epd = 2 * W2[0] - W1[0]
    print("EP diff", epd, epd - 1.96 * se, epd + 1.96 * se)
    # halves
    for nm, m in [("2015-20", p.season <= 2020), ("2021-26", p.season >= 2021)]:
        tt, xx = p[m & (p.two == 1)], p[m & (p.two == 0)]
        print(nm, "2pt", wilson(int(tt.ok.sum()), len(tt)), len(tt), "XP", wilson(int(xx.ok.sum()), len(xx)), len(xx))

    # 2) branch models, cross-fit
    games = p.game_id.unique()
    rng = np.random.default_rng(2)
    fold = p.game_id.map(dict(zip(games, rng.integers(0, 5, len(games)))))
    X = p[FEAT].astype(float)
    for b in "SFGM":
        p["m" + b] = np.nan
    for k in range(5):
        tr, te = fold != k, fold == k
        for b in "SFGM":
            m = tr & (p.branch == b)
            mdl = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, min_samples_leaf=20,
                                                l2_regularization=1.0, random_state=0).fit(X[m], p.wpa[m])
            p.loc[te, "m" + b] = mdl.predict(X[te])
    p2, p1 = W2[0], W1[0]
    p["gain"] = (p2 * p.mS + (1 - p2) * p.mF) - (p1 * p.mG + (1 - p1) * p.mM)
    for nm, m, a, b in [("2pt", p.two == 1, "mS", "mF"), ("XP", p.two == 0, "mG", "mM")]:
        pr = np.where(p.ok[m] == 1, p.loc[m, a], p.loc[m, b])
        print("calib", nm, pr.mean(), p.wpa[m].mean())

    late = p[(p.qtr == 4) & (p.game_seconds_remaining <= 600)]
    sit = []
    for diff in [-15, -14, -12, -11, -10, -9, -8, -7, -5, -4, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11]:
        c = late[late.score_differential == diff]
        if len(c) < 15:
            continue
        g = cluster_mean_ci(c.gain, c.game_id, B=500)
        gr = wilson(int(c.two.sum()), len(c))
        sit.append((diff, g, gr, len(c)))
        print(f"last10 diff {diff:+d} n={len(c)} gain {g[0]*100:+.2f} ({g[1]*100:+.2f},{g[2]*100:+.2f}) go2 {gr[0]:.2f} ({gr[1]:.2f}-{gr[2]:.2f})")

    # 3) down 8 at the PAT (was down 14), Q4: share going for 2 by season group
    d8 = p[(p.score_differential == -8) & (p.qtr == 4)]
    d8_rows = []
    for s in sorted(d8.season.unique()):
        c = d8[d8.season == s]
        w = wilson(int(c.two.sum()), len(c))
        d8_rows.append((int(s), w, len(c)))
        print("down8 Q4", s, len(c), round(w[0], 3))
    # closed form with Beta draws for p2, p1; OT = 0.5
    rng = np.random.default_rng(5)
    a2 = rng.beta(t.ok.sum() + 1, len(t) - t.ok.sum() + 1, 20000)
    a1 = rng.beta(x.ok.sum() + 1, len(x) - x.ok.sum() + 1, 20000)
    ot = 0.5
    aggressive = a2 * (a1 + (1 - a1) * ot) + (1 - a2) * a2 * ot   # 2 first; if good kick to win, if not 2 again to tie
    conventional = a1 * (a1 * ot + (1 - a1) * a2 * ot) + (1 - a1) * a2 * ot  # kick first; then kick (or 2 after a miss) to tie
    diff = aggressive - conventional
    print("down14 two-TD win: aggressive", aggressive.mean(), "conventional", conventional.mean(), "diff", diff.mean(),
          np.percentile(diff, [2.5, 97.5]))

    pd.to_pickle(dict(rows=rows, W2=W2, n2=len(t), W1=W1, n1=len(x), epd=(epd, epd - 1.96 * se, epd + 1.96 * se), sit=sit,
                      d8=d8_rows, agg=float(aggressive.mean()), conv=float(conventional.mean()),
                      dd=(float(diff.mean()), *np.percentile(diff, [2.5, 97.5]).tolist()), n=len(p), games=p.game_id.nunique(),
                      d8_all=(int(d8.two.sum()), len(d8))),
                 os.path.join(os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl"), "two_summary.pkl"))



def two_td(p2, p1, ot=0.5):
    agg = p2 * (p1 + (1 - p1) * ot) + (1 - p2) * p2 * ot
    con = p1 * (p1 * ot + (1 - p1) * p2 * ot) + (1 - p1) * p2 * ot
    return agg, con


def emit():
    sc = os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl")
    S = pd.read_pickle(os.path.join(sc, "two_summary.pkl"))
    rows = S["rows"]
    # EP per try by season: 2 x 2pt rate vs XP rate
    s2 = [dict(x=s, y=r(2 * w2[0]), lo=r(2 * w2[1]), hi=r(2 * w2[2]), n=n2) for s, w2, n2, w1, n1 in rows]
    s1 = [dict(x=s, y=r(w1[0]), lo=r(w1[1]), hi=r(w1[2]), n=n1) for s, w2, n2, w1, n1 in rows]
    W2, W1 = S["W2"], S["W1"]
    epd = S["epd"]
    xp_early = [w1 for s, w2, n2, w1, n1 in rows if s <= 2022]
    first = rows[0]
    last3 = [x for x in rows if x[0] in (2023, 2024, 2025)]
    k = sum(x[3][0] * x[4] for x in last3); n = sum(x[4] for x in last3)
    w_xp_recent = wilson(round(k), n)
    k = sum(x[3][0] * x[4] for x in rows if x[0] <= 2017); n0 = sum(x[4] for x in rows if x[0] <= 2017)
    w_xp_old = wilson(round(k), n0)
    two_rates = [x[1][0] for x in rows if x[0] <= 2025]
    study = {
        "id": "nfl-two-point",
        "sport": "NFL",
        "question": "Is a two-point try worth more than an extra point on average?",
        "answer": (f"No clear edge. 2-pt tries score {2*W2[0]:.2f} points per try, XPs {W1[0]:.2f}; "
                   f"difference {epd[0]:+.2f} ({epd[1]:+.2f} to {epd[2]:+.2f})."),
        "findings": [
            f"2-pt success {W2[0]*100:.1f}% ({W2[1]*100:.1f}-{W2[2]*100:.1f}, n={S['n2']:,}); break-even vs XP is {W1[0]*50:.1f}%.",
            f"XP rate {w_xp_old[0]*100:.1f}% in 2015-17 (n={n0:,}), {w_xp_recent[0]*100:.1f}% in 2023-25 (n={n:,}).",
            f"2-pt rate by season ranges {min(two_rates)*100:.0f}% to {max(two_rates)*100:.0f}%; every season CI includes 48%.",
            "2-pt runs 55% (50-60, n=388), passes 45% (42-48, n=1,041).",
        ],
        "method": ("Wilson 95% CIs on success rates; expected points = 2 x 2-pt rate vs XP rate. Tries in Q1-Q4, "
                   "all game states; selection is small since 2-pt tries are mostly score-driven."),
        "data": f"nflverse play-by-play, 2015 to 2026 wk 8, {S['n2']:,} two-point tries and {S['n1']:,} extra points.",
        "n": int(S["n2"] + S["n1"]),
        "robust": False,
        "interest": 2,
        "split_check": "2-pt rate 47.6% in 2015-20 (n=706), 48.5% in 2021-26 (n=752); XP edge within noise in both.",
        "chart": {
            "type": "line",
            "title": "Expected points per try",
            "x_label": "season", "y_label": "points per try", "y_fmt": "num", "x_reverse": False,
            "ref": None, "mark": None,
            "series": [{"name": "two-point try", "points": s2}, {"name": "extra point", "points": s1}],
        },
    }
    write(study)

    # down 14 -> TD -> down 8 at the PAT
    groups = [(2015, 2016), (2017, 2018), (2019, 2020), (2021, 2022), (2023, 2024), (2025, 2026)]
    d8 = {s: (w, n) for s, w, n in S["d8"]}
    pts = []
    for g in groups:
        k = sum(round(d8[s][0][0] * d8[s][1]) for s in g if s in d8)
        n = sum(d8[s][1] for s in g if s in d8)
        p, lo, hi = wilson(k, n)
        pts.append(dict(x=f"{g[0]}-{str(g[1])[2:]}", y=r(p), lo=r(lo), hi=r(hi), n=n))
    print(pts)
    e_agg, e_con = two_td(0.4759, 0.9384)
    l_agg, l_con = two_td(0.4854, 0.9499)
    dd = S["dd"]
    k_all, n_all = S["d8_all"]
    early = [x for x in pts[:2]]
    study = {
        "id": "nfl-down-14-go-for-two",
        "sport": "NFL",
        "question": "Down 14 in the 4th, should a team go for two after the first touchdown?",
        "answer": (f"Yes. With two TDs and a stop, going for 2 first wins {S['agg']*100:.0f}% vs {S['conv']*100:.0f}% kicking. "
                   f"Teams went for 2 {pts[-1]['y']*100:.0f}% of the time in 2025-26."),
        "findings": [
            f"Win chance gain given two TDs: {dd[0]*100:+.1f} pts ({dd[1]*100:+.1f} to {dd[2]*100:+.1f}).",
            f"Down 8 at a Q4 PAT: went for 2 in {round(early[0]['y']*early[0]['n'] + early[1]['y']*early[1]['n'])} of "
            f"{early[0]['n'] + early[1]['n']} in 2015-18, {round(pts[-1]['y']*pts[-1]['n'])} of {pts[-1]['n']} in 2025-26.",
            f"Inputs: 2-pt {S['W2'][0]*100:.1f}% (n={S['n2']:,}), XP {S['W1'][0]*100:.1f}% (n={S['n1']:,}), overtime 50/50.",
            "The early 2-pt result also tells the team whether it needs a TD or a TD and 2 on the next drive.",
        ],
        "method": ("Closed-form win chance given two TDs and no opponent score, with pooled 2-pt and XP rates; "
                   "CI from Beta draws of both rates. Go-for-2 share counts Q4 tries at down 8, Wilson CIs."),
        "data": f"nflverse play-by-play, 2015 to 2026 wk 8; {k_all + (n_all - k_all)} Q4 PATs at down 8; {S['n2']:,} 2-pt tries.",
        "n": int(n_all),
        "robust": True,
        "interest": 4,
        "split_check": (f"Gain holds with 2015-20 rates ({(e_agg-e_con)*100:+.1f} pts) and 2021-26 rates "
                        f"({(l_agg-l_con)*100:+.1f} pts)."),
        "chart": {
            "type": "bar",
            "title": "Share going for 2 when down 8 at a 4th-quarter PAT",
            "x_label": "seasons", "y_label": "go-for-2 %", "y_fmt": "pct", "x_reverse": False,
            "ref": None, "mark": None,
            "series": [{"name": "went for 2", "points": pts}],
        },
    }
    write(study)


if __name__ == "__main__":
    if "--emit" not in sys.argv:
        main()
    emit()
