# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Down 14, first TD: go for 2 at down 8 or kick? NFL (nflverse) and CFB (cfbfastR, FBS against FBS).

The tree (o = overtime win chance, p = 2-pt rate, x = XP rate), given two TDs and no other score:
  go for 2 first   p * (x + (1-x) o) + (1-p) * p o            good: kick to win next time; failed: 2 again to tie
  kick first       x * x o + (1-x) * p o                      good: kick to tie, then OT; missed: 2 to tie
  kick first, best x * max(x o, p) + (1-x) * p o              good: go for 2 to win when p > x o
Breakeven p solves go for 2 first = kick first. Inputs come from the play-by-play:
  p, x     every try in regulation (NFL 2015 on, when the XP moved to the 15; CFB 2016 on, FBS against FBS)
  o        the team that tied the game in the last 5 minutes, its win rate in overtime
  path     after a Q4 PAT at down 8, the share where the same team scored the next TD with nothing scored between
           (the share of games where the choice decides anything); edge in the game = path x the tree's gain
  coaches  Q4 PATs at down 8 (was down 14 before the TD), share going for 2, by season
Run:  python3 -I down14.py nfl_raw_dir cfb_raw_dir      (play_by_play_<year>.parquet from nflverse-data and
      sportsdataverse-data cfbfastR_cfb_pbp releases), then it writes nfl-down-14-go-for-two.json and
      ../cfb/cfb-down-14-go-for-two.json.
"""
import json, math, os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import wilson   # noqa: E402

O_BASE = 0.5


def tree(p, x, o=O_BASE):
    go = p * (x + (1 - x) * o) + (1 - p) * p * o
    kick = x * x * o + (1 - x) * p * o
    best = x * np.maximum(x * o, p) + (1 - x) * p * o
    return go, kick, best


def breakeven(x, o=O_BASE):
    lo, hi = 0.0, 1.0
    for _ in range(60):
        m = (lo + hi) / 2
        g, k, _ = tree(m, x, o)
        lo, hi = (lo, m) if g > k else (m, hi)
    return (lo + hi) / 2


def r(v, d=4):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), d)


# ---------------------------------------------------------------- NFL
def nfl(raw):
    cols = ["game_id", "play_id", "season", "season_type", "qtr", "game_seconds_remaining", "posteam", "defteam",
            "home_team", "away_team", "score_differential", "two_point_attempt", "two_point_conv_result",
            "extra_point_attempt", "extra_point_result", "touchdown", "td_team", "field_goal_result", "safety",
            "total_home_score", "total_away_score", "result"]
    fr = []
    for y in range(2015, 2027):
        f = f"{raw}/play_by_play_{y}.parquet"
        if os.path.exists(f):
            fr.append(pd.read_parquet(f, columns=cols))
    d = pd.concat(fr, ignore_index=True).sort_values(["game_id", "play_id"]).reset_index(drop=True)
    last_season = int(d.season.max())
    last_week = None
    tries = d[((d.two_point_attempt == 1) | (d.extra_point_attempt == 1)) & (d.qtr <= 4)].copy()
    tries["two"] = (tries.two_point_attempt == 1).astype(int)
    tries["ok"] = np.where(tries.two == 1, tries.two_point_conv_result == "success",
                           tries.extra_point_result == "good").astype(int)
    tries["team"] = tries.posteam
    tries["diff"] = tries.score_differential          # before the try: TD already counted
    tries["secs"] = tries.game_seconds_remaining
    # every score change, in order, for the path and the overtime rate
    d["hs"], d["as_"] = d.total_home_score.ffill().fillna(0), d.total_away_score.ffill().fillna(0)
    ev = scores_from_totals(d, "game_id", "home_team", "away_team", "hs", "as_", "qtr", "game_seconds_remaining")
    fin = d.groupby("game_id").agg(home=("home_team", "first"), away=("away_team", "first"),
                                   hs=("hs", "last"), as_=("as_", "last"), season=("season", "first"))
    return dict(league="NFL", tries=tries, ev=ev, fin=fin, last_season=last_season)


# ---------------------------------------------------------------- CFB
def cfb(raw):
    cols = ["game_id", "id_play", "season", "season_type", "period", "TimeSecsRem", "pos_team", "def_pos_team", "home", "away",
            "play_type", "play_text", "pos_score_diff_start", "score_pts", "pos_team_score", "def_pos_team_score",
            "home_team_division", "away_team_division"]
    fr = []
    for y in range(2016, 2027):
        f = f"{raw}/play_by_play_{y}.parquet"
        if os.path.exists(f):
            fr.append(pd.read_parquet(f, columns=cols))
    d = pd.concat(fr, ignore_index=True)
    # FBS against FBS; the current season's file can leave the division blank, so use the teams listed as FBS in any season
    fbs = set(d.home[d.home_team_division == "fbs"]) | set(d.away[d.away_team_division == "fbs"])
    d = d[d.home.isin(fbs) & d.away.isin(fbs)]
    d = d.sort_values(["game_id", "id_play"]).reset_index(drop=True)
    last_season = int(d.season.max())
    # the PAT is written in the TD row. Older rows end with (Name KICK), (Name PAT MISSED/BLOCKED), (... for two-point
    # conversion) or (Two-Point ... Failed); rows from 2025 on read "TOUCHDOWN, ... #N Name kick attempt good/failed" or
    # "... rush/pass attempt Successful/failed" (a retry after a penalty: the last attempt counts)
    td = d[d.play_type.isin(["Rushing Touchdown", "Passing Touchdown"]) & (d.period <= 4)].copy()
    txt = td.play_text.fillna("").str.lower()
    tail = txt.str.extract(r"\(([^()]*)\)\s*$")[0].fillna("")
    new = txt.str.findall(r"\b(kick|rush|pass) attempt (good|successful|failed|no good)").map(lambda m: m[-1] if m else None)
    has_new = new.notna()
    n_kind = new.map(lambda m: m[0] if m else "")
    n_ok = new.map(lambda m: m[1] in ("good", "successful") if m else False)
    is2_old = tail.str.contains("two-point|2pt|two point|conversion")
    two_ok_old = is2_old & ~tail.str.contains("fail|no good|incomplete|intercept")
    kick_old = tail.str.contains(r"\bkick\b|\bpat\b|extra point") & ~is2_old
    kick_ok_old = kick_old & ~tail.str.contains("miss|block|no good|fail")
    is2 = np.where(has_new, n_kind.isin(["rush", "pass"]), is2_old)
    kick = np.where(has_new, n_kind == "kick", kick_old)
    two_ok = np.where(has_new, n_kind.isin(["rush", "pass"]) & n_ok, two_ok_old)
    kick_ok = np.where(has_new, (n_kind == "kick") & n_ok, kick_ok_old)
    is2, kick, two_ok, kick_ok = (pd.Series(v, index=td.index).astype(bool) for v in (is2, kick, two_ok, kick_ok))
    td = td[is2 | kick].copy()
    td["two"] = is2[td.index].astype(int)
    td["ok"] = np.where(td.two == 1, two_ok[td.index], kick_ok[td.index]).astype(int)
    # check against the points the row carries: 8 = TD + 2, 7 = TD + kick, 6 = TD only
    pts = td.score_pts
    good = ((td.two == 1) & (td.ok == 1) & (pts == 8)) | ((td.two == 0) & (td.ok == 1) & (pts == 7)) | ((td.ok == 0) & (pts == 6))
    print("CFB PAT rows", len(td), "agree with points", round(good.mean(), 4), file=sys.stderr)
    td = td[good].copy()
    td["team"] = td.pos_team
    td["diff"] = td.pos_score_diff_start + 6
    td["qtr"] = td.period
    td["secs"] = td.TimeSecsRem.where(td.period == 4)   # seconds left in the 4th (half clock in the 4th = game clock)
    # running score by team
    d["hscore"] = np.where(d.pos_team == d.home, d.pos_team_score, d.def_pos_team_score)
    d["ascore"] = np.where(d.pos_team == d.home, d.def_pos_team_score, d.pos_team_score)
    d["hscore"] = d.groupby("game_id").hscore.cummax()
    d["ascore"] = d.groupby("game_id").ascore.cummax()
    d["gsr"] = np.where(d.period <= 4, (4 - d.period) * 900 + d.TimeSecsRem.clip(upper=900), 0)
    ev = scores_from_totals(d, "game_id", "home", "away", "hscore", "ascore", "period", "gsr")
    fin = d.groupby("game_id").agg(home=("home", "first"), away=("away", "first"),
                                   hs=("hscore", "last"), as_=("ascore", "last"), season=("season", "first"))
    return dict(league="CFB", tries=td, ev=ev, fin=fin, last_season=last_season)


def scores_from_totals(d, gid, home, away, hs, as_, qtr, secs):
    """One row per score change: game, team that scored, points, qtr, seconds left, score after."""
    g = d[[gid, home, away, hs, as_, qtr, secs]].copy()
    g.columns = ["game_id", "home", "away", "hs", "as_", "qtr", "secs"]
    dh = g.groupby("game_id").hs.diff().fillna(g.hs)
    da = g.groupby("game_id").as_.diff().fillna(g.as_)
    rows = []
    for (i, h, a) in zip(g.index, dh, da):
        if h > 0:
            rows.append((i, "H", h))
        if a > 0:
            rows.append((i, "A", a))
    ev = pd.DataFrame(rows, columns=["i", "side", "pts"])
    ev = ev.join(g, on="i")
    ev["team"] = np.where(ev.side == "H", ev.home, ev.away)
    return ev.reset_index(drop=True)


# ---------------------------------------------------------------- analysis
def analyse(L):
    t, ev, fin = L["tries"], L["ev"], L["fin"]
    two, xp = t[t.two == 1], t[t.two == 0]
    P = wilson(int(two.ok.sum()), len(two))
    X = wilson(int(xp.ok.sum()), len(xp))
    q4two = two[two.qtr == 4]
    P4 = wilson(int(q4two.ok.sum()), len(q4two))

    # overtime: games that went past regulation, the team that tied it inside the last 5 minutes
    reg = ev[ev.qtr <= 4]
    ot_games = set(ev[ev.qtr >= 5].game_id) | set(fin.index[(fin.hs == fin.as_)])
    last = reg.groupby("game_id").tail(1).set_index("game_id")
    tie_rows = []
    for gid in ot_games:
        if gid not in last.index:
            continue
        e = last.loc[gid]
        if e.hs != e.as_ or e.secs > 300:
            continue
        f = fin.loc[gid]
        if f.hs == f.as_:
            continue   # NFL tie after OT: left out
        won = (f.hs > f.as_) if e.team == f.home else (f.as_ > f.hs)
        tie_rows.append(int(won))
    O = wilson(sum(tie_rows), len(tie_rows))

    # Q4 PATs at down 8 (was down 14 before the TD)
    d8 = t[(t.qtr == 4) & (t["diff"] == -8)].copy()
    # path: next score after the try is the same team's TD (6+ points), before the end of regulation
    path, won, nxt = [], [], []
    evg = {g: e for g, e in ev.groupby("game_id")}
    for idx, row in d8.iterrows():
        e = evg.get(row.game_id)
        f = fin.loc[row.game_id]
        later = e[(e.i > idx) & (e.qtr <= 4)] if e is not None else None
        if later is not None and len(later):
            # the try itself can land on the row after (NFL: PAT is its own play); skip points scored on the try
            later = later[~((later.i == idx) | ((later.team == row.team) & (later.pts <= 2) & (later.i <= idx + 2)))]
        first = later.iloc[0] if later is not None and len(later) else None
        path.append(int(first is not None and first.team == row.team and first.pts >= 6))
        nxt.append("none" if first is None else ("own TD" if (first.team == row.team and first.pts >= 6) else
                   ("own FG" if first.team == row.team else "opp")))
        won.append(int((f.hs > f.as_) if row.team == f.home else (f.as_ > f.hs)))
    d8["path"], d8["won"], d8["next"] = path, won, nxt

    p, x, o = P[0], X[0], 0.5
    go, kick, best = tree(p, x, o)
    be = breakeven(x, o)
    # CI on the gain: Beta draws of p and x
    rng = np.random.default_rng(7)
    a2 = rng.beta(two.ok.sum() + 1, len(two) - two.ok.sum() + 1, 20000)
    a1 = rng.beta(xp.ok.sum() + 1, len(xp) - xp.ok.sum() + 1, 20000)
    gk = np.array(tree(a2, a1, o)[:2])
    gain_draw = gk[0] - gk[1]
    gain_ci = np.percentile(gain_draw, [2.5, 97.5])
    PATH = wilson(int(d8.path.sum()), len(d8))
    # game-level edge: path share x gain (draws of both)
    pd_ = rng.beta(d8.path.sum() + 1, len(d8) - d8.path.sum() + 1, 20000)
    edge = pd_ * gain_draw
    edge_ci = np.percentile(edge, [2.5, 97.5])
    # empirical OT rate instead of .5
    go_o, kick_o, _ = tree(p, x, O[0])
    # sensitivity: gain against the 2-pt rate
    sens = []
    for pp in np.arange(0.30, 0.6001, 0.02):
        g, k, b = tree(pp, x, o)
        sens.append(dict(x=r(pp * 100, 1), y=r(g - k)))
    # coaches by season
    by = []
    for s, c in d8.groupby(d8.season if "season" in d8 else d8.game_id.str[:4].astype(int)):
        w = wilson(int(c.two.sum()), len(c))
        by.append((int(s), int(c.two.sum()), len(c), w))
    # realised: win rate by choice (selection: the strong chase more often late, small n)
    real = {}
    for k_, c in d8.groupby("two"):
        real[int(k_)] = (int(c.won.sum()), len(c))
    # rates in each half for the split check
    halves = []
    seasons = sorted(t.season.unique())
    mid = seasons[len(seasons) // 2]
    for nm, m in [(f"{seasons[0]}-{str(mid - 1)[2:]}", t.season < mid), (f"{mid}-{str(seasons[-1])[2:]}", t.season >= mid)]:
        tt, xx = t[m & (t.two == 1)], t[m & (t.two == 0)]
        pp, xx_ = tt.ok.mean(), xx.ok.mean()
        g, k, _ = tree(pp, xx_, o)
        halves.append((nm, pp, len(tt), xx_, len(xx), g - k))
    out = dict(league=L["league"], P=P, n2=len(two), P4=P4, n24=len(q4two), X=X, n1=len(xp), O=O, nO=len(tie_rows),
               go=go, kick=kick, best=best, gain=go - kick, gain_ci=gain_ci.tolist(), be=be,
               go_o=go_o, kick_o=kick_o, path=PATH, n8=len(d8), edge=float(np.mean(edge)), edge_ci=edge_ci.tolist(),
               sens=sens, by=by, real=real, halves=halves, next=d8.next.value_counts().to_dict(),
               branches=dict(two_good=x + (1 - x) * o, two_fail=p * o, xp_good=x * o, xp_good_best=max(x * o, p), xp_miss=p * o),
               first=int(t.season.min()), last=L["last_season"])
    return out


def pct(v, d=0):
    return f"{v * 100:.{d}f}%"


def pts(v, d=1):
    return f"{v * 100:+.{d}f}"


def study(S, sid, sport, data_line, rq_extra):
    groups = []
    by = S["by"]
    # season groups of two (NFL) or by season (CFB)
    yrs = [x[0] for x in by]
    spans = [(a, min(a + 1, yrs[-1])) for a in range(yrs[0], yrs[-1] + 1, 2)]
    for a, b in spans:
        k = sum(x[1] for x in by if a <= x[0] <= b)
        n = sum(x[2] for x in by if a <= x[0] <= b)
        if n:
            w = wilson(k, n)
            groups.append(dict(x=f"{a}-{str(b)[2:]}" if b > a else str(a), k=k, n=n, y=r(w[0]), lo=r(w[1]), hi=r(w[2])))
    early, late = groups[0], groups[-1]
    br = S["branches"]
    real2, realk = S["real"].get(1, (0, 0)), S["real"].get(0, (0, 0))
    h = S["halves"]
    res = {
        "id": sid,
        "sport": sport,
        "question": "Down 14, a team scores a touchdown. Should it go for two right away or kick?",
        "answer": (f"Go for 2. Given two TDs and a stop it wins {pct(S['go'])} of the time against {pct(S['kick'])} for kicking, "
                   f"worth {pts(S['edge'])} points of win chance overall."),
        "date": "2026-11-28",
        "findings": [
            f"The gain given two TDs is {pts(S['gain'])} points ({pts(S['gain_ci'][0])} to {pts(S['gain_ci'][1])}), "
            f"and going for 2 first wins as long as the 2-pt rate is above {pct(S['be'], 1)}.",
            f"After a Q4 PAT at down 8 the same team scored the next TD with nothing between in {pct(S['path'][0])} "
            f"(n={S['n8']:,}); in the rest the choice decides almost nothing.",
            f"Inputs: 2-pt {pct(S['P'][0], 1)} (n={S['n2']:,}), XP {pct(S['X'][0], 1)} (n={S['n1']:,}), and teams that tied "
            f"late won {pct(S['O'][0])} in overtime (n={S['nO']:,}).",
            f"Teams went for 2 at down 8 in the 4th in {early['k']} of {early['n']} in {early['x']} and {late['k']} of "
            f"{late['n']} in {late['x']}.",
            f"Raw results are noisy: teams that went for 2 won {real2[0]} of {real2[1]} and teams that kicked won {realk[0]} of "
            f"{realk[1]}, and the teams that chose each differ.",
        ],
        "method": ("A closed-form tree given two TDs and no opponent score: after 2 is good, kick to win; after 2 fails, 2 again to "
                   "tie; after an XP, kick to tie; overtime at 50%. The CI comes from Beta draws of the 2-pt and XP rates. "
                   "The game-level edge is the share of down-8 spots that reach a second TD first, times the gain."),
        "data": data_line,
        "n": int(S["n8"]),
        "robust": bool(S["gain_ci"][0] > 0),
        "interest": 4,
        "split_check": (f"The gain is {pts(h[0][5])} points with the {h[0][0]} rates (2-pt {pct(h[0][1], 1)}) and "
                        f"{pts(h[1][5])} with the {h[1][0]} rates (2-pt {pct(h[1][1], 1)}); with the measured overtime rate "
                        f"it is {pts(S['go_o'] - S['kick_o'])}."),
        "tree": {
            "p": r(S["P"][0]), "x": r(S["X"][0]), "o": 0.5,
            "go": r(S["go"]), "kick": r(S["kick"]), "be": r(S["be"]),
            "rows": [
                ["go for 2", "good", r(S["P"][0]), "TD + kick wins", r(br["two_good"])],
                ["go for 2", "no good", r(1 - S["P"][0]), "TD + 2 ties", r(br["two_fail"])],
                ["kick", "good", r(S["X"][0]), "TD + kick ties", r(br["xp_good"])],
                ["kick", "no good", r(1 - S["X"][0]), "TD + 2 ties", r(br["xp_miss"])],
            ],
        },
        "chart": {
            "type": "line",
            "title": "Win chance gain from going for 2 first, given two TDs",
            "x_label": "2-pt rate %", "y_label": "gain, WP", "y_fmt": "pct", "x_reverse": False,
            "ref": {"y": 0, "label": "even"},
            "mark": {"x": r(S["P"][0] * 100, 1), "label": f"{sport} {pct(S['P'][0], 1)}"},
            "series": [{"name": "go for 2 first minus kick", "points": S["sens"]}],
        },
        "chart2": {
            "type": "bar",
            "title": "Share going for 2 at down 8 in the 4th",
            "x_label": "seasons", "y_label": "go-for-2 %", "y_fmt": "pct", "x_reverse": False, "ref": None, "mark": None,
            "series": [{"name": "went for 2", "points": [{k: v for k, v in g.items() if k != "k"} for g in groups]}],
        },
        "rq": rq_extra,
    }
    return res


def main():
    nraw, craw = sys.argv[1], sys.argv[2]
    out = {}
    for name, fn, raw in [("NFL", nfl, nraw), ("CFB", cfb, craw)]:
        L = fn(raw)
        S = analyse(L)
        out[name] = S
        print(name, json.dumps({k: v for k, v in S.items() if k not in ("sens",)}, default=str, indent=None), file=sys.stderr)
    N, C = out["NFL"], out["CFB"]
    nfl_line = (f"nflverse play-by-play, {N['first']} to {N['last']}; {N['n2']:,} 2-pt tries, {N['n1']:,} XPs, "
                f"{N['n8']:,} Q4 PATs at down 8.")
    cfb_line = (f"cfbfastR play-by-play, FBS against FBS, {C['first']} to {C['last']}; {C['n2']:,} 2-pt tries, {C['n1']:,} XPs, "
                f"{C['n8']:,} Q4 PATs at down 8.")
    s1 = study(N, "nfl-down-14-go-for-two", "NFL", nfl_line, None)
    s2 = study(C, "cfb-down-14-go-for-two", "CFB", cfb_line, None)
    for s, path in [(s1, os.path.join(HERE, "nfl-down-14-go-for-two.json")),
                    (s2, os.path.join(HERE, "..", "cfb", "cfb-down-14-go-for-two.json"))]:
        s.pop("rq", None)
        with open(path, "w") as f:
            json.dump(s, f, indent=2)
            f.write("\n")
        print("wrote", os.path.normpath(path), file=sys.stderr)


if __name__ == "__main__":
    main()
