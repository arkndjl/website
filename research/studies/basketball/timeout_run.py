"""Study: NBA timeout after an opponent run.

Trigger: the score that brings an unanswered opponent run to 8+ points (first time per run), Q1-Q4,
>= 150 s left in the period, margin within 20. The team that was run on (A) inbounds.
TO = A calls a timeout in that dead ball. No TO = A calls no timeout in the next 60 s of clock.
Outcome: A's net points over the next 120 s of game clock (same period). Both groups follow the same
run, so regression to the mean is shared; we also stratify by run size and period. CIs: game bootstrap.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bball_common as bc

LIVE = {"shot", "tov", "ft", "dreb", "steal", "oreb"}
HORIZON = 120.0


def episodes():
    ev = bc.load("nba")
    games = bc.game_table(ev, "nba")
    ev = ev[ev.game_id.isin(games.index) & (ev.period <= 4)]
    rows = []
    for (gid, per), g in ev.groupby(["game_id", "period"], sort=False):
        kinds = g.kind.astype(str).tolist(); teams = g.team.tolist(); secs = g.sec.tolist()
        hs = g.hs.tolist(); as_ = g.as_.tolist(); made = g.made.tolist()
        home, away = int(g.home.iloc[0]), int(g.away.iloc[0])
        n = len(kinds)
        run_team, run_pts, fired = None, 0, False
        ph, pa = (hs[0], as_[0])
        for i in range(n):
            dh, da = hs[i] - ph, as_[i] - pa
            ph, pa = hs[i], as_[i]
            if dh <= 0 and da <= 0:
                continue
            scorer = home if dh > 0 else away
            pts = dh if dh > 0 else da
            if scorer == run_team:
                run_pts += pts
            else:
                run_team, run_pts, fired = scorer, pts, False
            if fired or run_pts < 8:
                continue
            # wait until the score sequence is done (no more FTs by the scorer at this second)
            j = i + 1
            while j < n and secs[j] == secs[i] and kinds[j] in ("foul", "other", "timeout"):
                j += 1
            if j < n and kinds[j] == "ft" and secs[j] == secs[i] and teams[j] == scorer:
                continue  # and-one / more FTs pending: evaluate after them
            fired = True
            t0 = secs[i]
            if t0 < 150:
                continue
            A = away if scorer == home else home
            marg = (hs[i] - as_[i]) * (1 if A == home else -1)
            if abs(marg) > 20:
                continue
            to_now = to_b = False
            j = i + 1
            while j < n and kinds[j] not in LIVE:
                if kinds[j] == "timeout":
                    if teams[j] == A:
                        to_now = True
                    elif teams[j] == scorer:
                        to_b = True
                j += 1
            if to_b:
                continue
            to_later = False
            if not to_now:
                for q in range(j, n):
                    if secs[q] < t0 - 60:
                        break
                    if kinds[q] == "timeout" and teams[q] == A:
                        to_later = True
                        break
                if to_later:
                    continue
            # score at horizon
            hh, ha = hs[i], as_[i]
            for q in range(i + 1, n):
                if secs[q] < t0 - HORIZON:
                    break
                hh, ha = hs[q], as_[q]
            net = ((hh - ha) - (hs[i] - as_[i])) * (1 if A == home else -1)
            rows.append(dict(game_id=gid, season=int(g.season.iloc[0]), period=per, t0=t0, run=run_pts,
                             marg=marg, to=to_now, net=net, a_home=(A == home)))
    return pd.DataFrame(rows)


def strat_diff(df, B=2000, seed=9):
    """TO minus no-TO net points, within run-size x period cells, weighted by TO counts; game bootstrap."""
    df = df.copy()
    df["rb"] = np.select([df.run <= 9, df.run <= 11], [0, 1], 2)
    df["cell"] = (df.rb * 4 + (df.period - 1)) * 2 + df.to.astype(int)
    gids, gidx = np.unique(df.game_id.to_numpy(), return_inverse=True)
    G, K = len(gids), 24
    S = np.zeros((G, K)); C = np.zeros((G, K))
    np.add.at(S, (gidx, df.cell.to_numpy()), df.net.to_numpy())
    np.add.at(C, (gidx, df.cell.to_numpy()), 1)
    def est(Ss, Cs):
        tot = w = 0.0
        for c in range(12):
            nt, nn = Cs[2 * c + 1], Cs[2 * c]
            if nt > 0 and nn > 0:
                tot += nt * (Ss[2 * c + 1] / nt - Ss[2 * c] / nn); w += nt
        return tot / w
    point = est(S.sum(0), C.sum(0))
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(B):
        wts = np.bincount(rng.integers(0, G, G), minlength=G)
        bs.append(est(wts @ S, wts @ C))
    return float(point), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


if __name__ == "__main__":
    path = os.path.join(bc.SCRATCH, "timeout_run.csv")
    df = pd.read_csv(path) if os.path.exists(path) and "--fresh" not in sys.argv else episodes()
    df.to_csv(path, index=False)
    print(len(df), df.to.mean())
    print(df.groupby(["run", "to"]).net.agg(["size", "mean"]).head(20))
    T, N = df[df.to], df[~df.to]
    tm, nm = bc.boot_mean(T.net, T.game_id), bc.boot_mean(N.net, N.game_id)
    sd = strat_diff(df)
    early = df.season <= 2019
    sde, sdl = strat_diff(df[early], B=800), strat_diff(df[~early], B=800)
    print(tm, nm, sd, sde, sdl)
    series = []
    for flag, name in ((True, "timeout"), (False, "no timeout")):
        pts = []
        for q in (1, 2, 3, 4):
            sub = df[(df.to == flag) & (df.period == q)]
            m, lo, hi = bc.boot_mean(sub.net.to_numpy(), sub.game_id.to_numpy())
            pts.append(dict(x=f"Q{q}", y=bc.r3(m), lo=bc.r3(lo), hi=bc.r3(hi), n=int(len(sub))))
        series.append(dict(name=name, points=pts))
    q4 = df[df.period == 4]
    d4 = bc.boot_diff(q4[q4.to].net, q4[~q4.to].net, q4[q4.to].game_id, q4[~q4.to].game_id)
    robust = (sd[1] > 0 or sd[2] < 0) and ((sde[0] > 0) == (sdl[0] > 0))
    out = {
        "id": "nba-timeout-after-run",
        "sport": "NBA",
        "question": "Does a timeout stop an opponent run?",
        "answer": (f"{'Yes' if robust and sd[0] > 0 else 'No'}: after an 8+ pt run, a timeout nets {sd[0]:+.2f} pts "
                   f"over the next 2:00 vs playing on (CI {sd[1]:+.2f} to {sd[2]:+.2f})."),
        "findings": [
            f"Timeout: next 2:00 net {tm[0]:+.2f} pts (CI {tm[1]:+.2f} to {tm[2]:+.2f}), n={len(T)}.",
            f"No timeout: next 2:00 net {nm[0]:+.2f} pts (CI {nm[1]:+.2f} to {nm[2]:+.2f}), n={len(N)}.",
            f"Both groups outscore the opponent after the run (mean reversion plus the ball); same-state gap {sd[0]:+.2f}.",
            f"Q4 only: timeout minus none {d4[0]:+.2f} pts (CI {d4[1]:+.2f} to {d4[2]:+.2f}), n={len(q4)}.",
        ],
        "method": ("Trigger = score making an unanswered run 8+ pts, >= 2:30 left in quarter, margin within 20. "
                   "Timeout in that dead ball vs no timeout in next 60 s; net points next 120 s; matched on run size and quarter."),
        "data": f"ESPN play-by-play via sportsdataverse, NBA 2011-12 to 2025-26, {df.game_id.nunique():,} games, {len(df):,} runs.",
        "n": int(len(df)),
        "robust": bool(robust),
        "interest": 4,
        "split_check": f"Timeout minus none: {sde[0]:+.2f} pts in 2012-19 (CI {sde[1]:+.2f} to {sde[2]:+.2f}), {sdl[0]:+.2f} in 2020-26 (CI {sdl[1]:+.2f} to {sdl[2]:+.2f}).",
        "chart": {
            "type": "bar",
            "title": "Net points in next 2:00 after an opponent 8+ pt run, by quarter",
            "x_label": "quarter", "y_label": "net points, next 2:00",
            "y_fmt": "signed", "x_reverse": False, "ref": {"y": 0, "label": "even"}, "mark": None,
            "series": series,
        },
    }
    print(out["answer"]); print("\n".join(out["findings"])); print(out["split_check"])
    bc.write_json(out, out["id"])
