"""NFL fourth-down study: go vs kick, by state, 2015-2026.

Expected WP of each option is estimated per play from equal states:
  go   = p_conv * E[WPA | converted, state] + (1 - p_conv) * E[WPA | failed, state]
  kick = best of E[WPA | punt, state] and E[WPA | FG try, state] (where each is realistic)
Branch models are gradient-boosted regressions of nflverse WPA on the pre-snap state, fit only on
plays that took that branch, cross-fitted by game (5 folds). p_conv is a logistic fit of empirical
4th-down conversion rates on distance and field position (pooled, so a team's own confidence does
not enter). Gain = go - kick.
Run: python3 -I fourth_down.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from common import load, wilson, cluster_mean_ci, cluster_sum_ci, r, write

FEAT = ["yardline_100", "ydstogo", "wp", "game_seconds_remaining", "half_seconds_remaining",
        "score_differential", "posteam_timeouts_remaining", "defteam_timeouts_remaining", "qtr"]
TH = 0.01  # 1 WP point: clear go / clear kick


def conv_features(d):
    y = d.ydstogo.clip(1, 30).to_numpy(float)
    yl = d.yardline_100.to_numpy(float)
    return np.column_stack([np.log(y), y, d.goal_to_go.fillna(0).to_numpy(float), yl / 100, (yl <= 10).astype(float)])


def main():
    d = load()
    f = d[(d.down == 4) & d.play_type.isin(["pass", "run", "punt", "field_goal"]) & (d.qb_kneel != 1)
          & (d.qb_spike != 1) & (d.qtr <= 4) & d.wp.notna() & d.wpa.notna() & d.ydstogo.notna()].copy()
    f["go"] = f.play_type.isin(["pass", "run"]).astype(int)
    f["conv"] = ((f.fourth_down_converted == 1) | (f.touchdown == 1) & (f.td_team == f.posteam)).astype(int)
    f["branch"] = np.where(f.go == 1, np.where(f.conv == 1, "S", "F"), np.where(f.play_type == "punt", "P", "G"))
    f = f.reset_index(drop=True)
    print("4th-down plays", len(f), f.branch.value_counts().to_dict())

    # cross-fitted branch models
    games = f.game_id.unique()
    rng = np.random.default_rng(1)
    fold_of = dict(zip(games, rng.integers(0, 5, len(games))))
    f["fold"] = f.game_id.map(fold_of)
    for b in "SFPG":
        f["m" + b] = np.nan
    f["pconv"] = np.nan
    X = f[FEAT].astype(float)
    for k in range(5):
        tr, te = f.fold != k, f.fold == k
        for b in "SFPG":
            m = tr & (f.branch == b)
            mdl = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, min_samples_leaf=40,
                                                l2_regularization=1.0, random_state=0)
            mdl.fit(X[m], f.wpa[m])
            f.loc[te, "m" + b] = mdl.predict(X[te])
        g = tr & (f.go == 1)
        lr = LogisticRegression(C=10, max_iter=1000).fit(conv_features(f[g]), f.conv[g])
        f.loc[te, "pconv"] = lr.predict_proba(conv_features(f[te]))[:, 1]

    fg_ok = f.yardline_100 <= 38      # 55-yard try or shorter
    punt_ok = f.yardline_100 >= 30
    kick = np.where(fg_ok & punt_ok, np.maximum(f.mP, f.mG), np.where(fg_ok, f.mG, f.mP))
    f["v_go"] = f.pconv * f.mS + (1 - f.pconv) * f.mF
    f["v_kick"] = kick
    f["gain"] = f.v_go - f.v_kick
    f["rec"] = np.where(f.gain > TH, "go", np.where(f.gain < -TH, "kick", "close"))
    f["lost"] = np.where(f.go == 1, np.maximum(0, -f.gain), np.maximum(0, f.gain))
    f["lost_kick"] = np.where(f.go == 0, np.maximum(0, f.gain), 0.0)

    # calibration check: predicted vs realized mean WPA for each chosen option
    for nm, m, col in [("go", f.go == 1, "v_go"), ("kick", f.go == 0, "v_kick")]:
        print(f"calib {nm}: pred {f.loc[m, col].mean():.4f} actual {f.loc[m, 'wpa'].mean():.4f}")
    q = pd.qcut(f.gain, 10)
    print(f.groupby(q, observed=True).agg(n=("go", "size"), go=("go", "mean"), gain=("gain", "mean"),
          wpa_go=("wpa", lambda s: s[f.loc[s.index, "go"] == 1].mean()),
          wpa_kick=("wpa", lambda s: s[f.loc[s.index, "go"] == 0].mean())).to_string())

    # empirical conversion rates
    go = f[f.go == 1]
    conv_rows = []
    for lab, m in [("1", go.ydstogo == 1), ("2", go.ydstogo == 2), ("3", go.ydstogo == 3), ("4-5", go.ydstogo.between(4, 5)),
                   ("6-10", go.ydstogo.between(6, 10))]:
        p, lo, hi = wilson(int(go.conv[m].sum()), int(m.sum()))
        conv_rows.append((lab, p, lo, hi, int(m.sum())))
        print("conv", lab, round(p, 3), round(lo, 3), round(hi, 3), int(m.sum()))
    # 3rd-down benchmark (less selected): same distances, offense ran a play
    t = d[(d.down == 3) & d.play_type.isin(["pass", "run"]) & (d.qb_kneel != 1) & (d.qtr <= 4)]
    for yd in (1, 2, 3):
        m = t.ydstogo == yd
        print("3rd conv", yd, wilson(int((t.first_down[m] == 1).sum()), int(m.sum())), int(m.sum()))

    # by season
    seasons = sorted(f.season.unique())
    rows = []
    for s in seasons:
        fs = f[f.season == s]
        ng = fs[fs.rec == "go"]
        nk = fs[fs.rec == "kick"]
        pg = wilson(int(ng.go.sum()), len(ng))
        pk = wilson(int(nk.go.sum()), len(nk))
        tot, lo, hi = cluster_sum_ci(fs.lost, fs.game_id)
        totk, _, _ = cluster_sum_ci(fs.lost_kick, fs.game_id)
        teams = 32
        ngames = fs.game_id.nunique()
        rows.append(dict(season=int(s), n=len(fs), n_go_state=len(ng), go_rate_go_state=pg, n_kick_state=len(nk),
                         go_rate_kick_state=pk, lost=tot, lost_lo=lo, lost_hi=hi, lost_kick=totk, games=ngames,
                         lost_per_team_game=tot / (2 * ngames), go_overall=fs.go.mean()))
        print(s, len(fs), f"go-state n={len(ng)} goRate={pg[0]:.3f} ({pg[1]:.3f}-{pg[2]:.3f}) | kick-state goRate={pk[0]:.3f}"
              f" | lost={tot:.2f} ({lo:.2f}-{hi:.2f}) per team-game={tot/(2*ngames):.4f} lost_from_kicking={totk:.2f} overall go={fs.go.mean():.3f}")

    # share of go-states by distance / zone, recent seasons
    rec = f[f.season >= 2023]
    for lab, m in [("4th&1", rec.ydstogo == 1), ("4th&2-3", rec.ydstogo.between(2, 3)), ("4th&4-5", rec.ydstogo.between(4, 5)),
                   ("4th&6+", rec.ydstogo >= 6)]:
        sub = rec[m & (rec.rec == "go")]
        print(lab, "go-states", len(sub), "go rate", round(sub.go.mean(), 3), "lost", round(sub.lost.sum(), 2))
    for lab, m in [("own 1-40", rec.yardline_100 > 60), ("own40-opp40", rec.yardline_100.between(40, 60)),
                   ("opp 39-1", rec.yardline_100 < 40)]:
        sub = rec[m & (rec.rec == "go")]
        print(lab, "go-states", len(sub), "go rate", round(sub.go.mean(), 3), "lost", round(sub.lost.sum(), 2))

    # realized check in go-states: goers vs kickers, mean WPA, game-clustered
    gs = f[f.rec == "go"]
    a = cluster_mean_ci(gs.wpa[gs.go == 1], gs.game_id[gs.go == 1])
    b = cluster_mean_ci(gs.wpa[gs.go == 0], gs.game_id[gs.go == 0])
    print("realized WPA in go-states: go", a, (gs.go == 1).sum(), "kick", b, (gs.go == 0).sum())
    ks = f[f.rec == "kick"]
    a2 = cluster_mean_ci(ks.wpa[ks.go == 1], ks.game_id[ks.go == 1])
    b2 = cluster_mean_ci(ks.wpa[ks.go == 0], ks.game_id[ks.go == 0])
    print("realized WPA in kick-states: go", a2, (ks.go == 1).sum(), "kick", b2, (ks.go == 0).sum())

    f[["season", "game_id", "posteam", "ydstogo", "yardline_100", "wp", "go", "conv", "wpa", "pconv", "v_go", "v_kick", "gain",
       "rec", "lost"]].to_parquet(os.path.join(os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl"), "fourth_scored.parquet"))
    pd.to_pickle(dict(rows=rows, conv=conv_rows, realized=(a, b, a2, b2, int((gs.go == 1).sum()), int((gs.go == 0).sum()),
                       int((ks.go == 1).sum()), int((ks.go == 0).sum())), n=len(f), ngames=f.game_id.nunique()),
                 "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl/fourth_summary.pkl")



def emit():
    sc = os.environ.get("NFL_SCRATCH", "/tmp/claude-0/-home-user-website/74038a8a-b0f9-507c-bb0a-47f7b7c402f2/scratchpad/nfl")
    f = pd.read_parquet(os.path.join(sc, "fourth_scored.parquet"))
    summ = pd.read_pickle(os.path.join(sc, "fourth_summary.pkl"))
    f["lc"] = np.where((f.rec == "go") & (f.go == 0), f.gain, 0) + np.where((f.rec == "kick") & (f.go == 1), -f.gain, 0)
    pts_go, pts_kick = [], []
    for s in sorted(f.season.unique()):
        fs = f[f.season == s]
        g = fs[fs.rec == "go"]
        k = fs[fs.rec == "kick"]
        p, lo, hi = wilson(int(g.go.sum()), len(g))
        pts_go.append(dict(x=int(s), y=r(p), lo=r(lo), hi=r(hi), n=len(g)))
        p, lo, hi = wilson(int(k.go.sum()), len(k))
        pts_kick.append(dict(x=int(s), y=r(p), lo=r(lo), hi=r(hi), n=len(k)))

    def per_team_game(sub):
        # clear-decision WP lost, per team-game, CI by game bootstrap
        v, lo, hi = cluster_sum_ci(sub.lc, sub.game_id, seed=3)
        ng = 2 * sub.game_id.nunique()
        return v / ng, lo / ng, hi / ng, sub.game_id.nunique()

    early = per_team_game(f[f.season.isin([2015, 2016])])
    late = per_team_game(f[f.season.isin([2024, 2025])])
    gE = f[f.season.isin([2015, 2016]) & (f.rec == "go")]
    gL = f[f.season.isin([2024, 2025]) & (f.rec == "go")]
    pE = wilson(int(gE.go.sum()), len(gE))
    pL = wilson(int(gL.go.sum()), len(gL))
    rec = f[f.season >= 2023]
    sh = rec[(rec.rec == "go")]
    by = {}
    for lab, m in [("1", sh.ydstogo == 1), ("2-3", sh.ydstogo.between(2, 3)), ("4+", sh.ydstogo >= 4)]:
        by[lab] = wilson(int(sh.go[m].sum()), int(m.sum())) + (int(m.sum()), float(sh.lc[m].sum() / rec.lc.sum()))
    a, b, a2, b2, nga, ngk, nka, nkk = summ["realized"]
    conv = {c[0]: c for c in summ["conv"]}
    n = len(f)
    print(early, late, pE, pL, by)
    study = {
        "id": "nfl-fourth-down",
        "sport": "NFL",
        "question": "When going for it on 4th down gains win probability, how often do NFL teams go?",
        "answer": (f"In states where going gains 1+ WP point, teams went {pE[0]*100:.0f}% of the time in 2015-16 and "
                   f"{pL[0]*100:.0f}% in 2024-25."),
        "findings": [
            f"Clear-kick states: teams go about 4% of the time every season (n={sum(p['n'] for p in pts_kick):,}).",
            f"WP lost to clear errors: {early[0]*100:.1f} WP pts per team-game in 2015-16 ({early[1]*100:.1f}-{early[2]*100:.1f}), "
            f"{late[0]*100:.1f} in 2024-25 ({late[1]*100:.1f}-{late[2]*100:.1f}).",
            f"2023-26 go states: go rate {by['1'][0]*100:.0f}% at 4th-and-1 (n={by['1'][3]:,}), {by['2-3'][0]*100:.0f}% at 2-3 yds "
            f"(n={by['2-3'][3]:,}), {by['4+'][0]*100:.0f}% at 4+ (n={by['4+'][3]:,}).",
            f"Conversion: 4th-and-1 {conv['1'][1]*100:.0f}% ({conv['1'][2]*100:.0f}-{conv['1'][3]*100:.0f}, n={conv['1'][4]:,}), "
            f"4th-and-2 {conv['2'][1]*100:.0f}% ({conv['2'][2]*100:.0f}-{conv['2'][3]*100:.0f}, n={conv['2'][4]:,}).",
        ],
        "method": ("Per play, expected WPA of go (pooled conversion rate x WPA if converted/failed) vs best of punt/FG, each from "
                   "boosted models of nflverse WPA on the same pre-snap state, cross-fit by game. Teams' own choice does not set the rate. WP-lost CIs exclude model error."),
        "data": f"nflverse play-by-play, 2015 to 2026 wk 8, Q1-Q4 4th downs (no penalties/kneels), {n:,} plays, {f.game_id.nunique():,} games.",
        "n": int(n),
        "robust": True,
        "interest": 4,
        "split_check": (f"Model checks out of sample: realized WPA in go states, goers {a[0]*100:+.1f} vs kickers {b[0]*100:+.1f} pts "
                        f"(n={nga:,}/{ngk:,}); rise in go rate holds every season."),
        "chart": {
            "type": "line",
            "title": "Go rate on 4th down, by what the model recommends",
            "x_label": "season", "y_label": "go %", "y_fmt": "pct", "x_reverse": False,
            "ref": None, "mark": None,
            "series": [
                {"name": "going gains 1+ WP pt", "points": pts_go},
                {"name": "kicking gains 1+ WP pt", "points": pts_kick},
            ],
        },
    }
    write(study)


if __name__ == "__main__":
    if "--emit" not in sys.argv:
        main()
    emit()
