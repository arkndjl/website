"""Study: foul up 3 (NBA + CBB).

State: final regulation period, leader up exactly 3, trailer in possession and the possession still live
with <= 12 s left (no shot / turnover / foul yet). Decision = the leader's first act on that possession:
a non-shooting foul that sends the trailer to the line ("foul") vs anything else ("defend").
Fouls with no free throws (NBA foul to give) do not end the possession; we keep reading.
Outcome: leader wins the game (OT included). One episode per game (the first).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bball_common as bc
from poss import possession_after

W = 12.0
NBA_INTENT = {"Personal Foul", "Personal Take Foul", "Transition Take Foul", "Away from Play Foul",
              "Flagrant Foul Type 1", "Flagrant Foul Type 2", "Clear Path Foul"}


def episodes(league):
    ev = bc.load(league)
    games = bc.game_table(ev, league)
    reg = bc.REG_PERIODS[league]
    sub = ev[(ev.period == reg) & (ev.sec <= 45) & ev.game_id.isin(games.index)]
    rows = []
    for gid, g in sub.groupby("game_id", sort=False):
        gm = games.loc[gid]
        kinds = g["kind"].astype(str).tolist()
        teams = g["team"].tolist()
        made = g["made"].tolist()
        subs = g["sub"].astype(str).tolist()
        secs = g["sec"].tolist()
        hs = g["hs"].tolist()
        as_ = g["as_"].tolist()
        three = g["three"].tolist()
        home, away = int(gm.home), int(gm.away)
        pos, lastft = possession_after(kinds, teams, made, subs, home, away)
        n = len(kinds)
        i = 0
        found = None
        while i < n and found is None:
            T = pos[i]
            if T is None or (i > 0 and pos[i - 1] == T):
                i += 1
                continue
            # possession for T begins at event i
            lead_T = (hs[i] - as_[i]) if T == home else (as_[i] - hs[i])
            if lead_T != -3:
                i += 1
                continue
            L = away if T == home else home
            t0 = secs[i]
            # scan the possession
            j = i + 1
            gave = 0
            decision = None
            tdec = None
            while j < n:
                k, tm = kinds[j], teams[j]
                if k == "foul" and tm == L and subs[j] != "Technical Foul":
                    shooting = False
                    if league == "nba":
                        shooting = subs[j] not in NBA_INTENT
                    else:
                        # shooting foul if T has an FGA at the same second next to it, or 3 FTs follow
                        for q in range(max(i + 1, j - 2), min(n, j + 3)):
                            if kinds[q] == "shot" and teams[q] == T and secs[q] == secs[j]:
                                shooting = True
                        fts = [q for q in range(j + 1, min(n, j + 6)) if kinds[q] == "ft" and teams[q] == T and secs[q] == secs[j]]
                        if len(fts) >= 3:
                            shooting = True
                    has_ft = any(kinds[q] == "ft" and teams[q] == T and secs[q] == secs[j]
                                 for q in range(j + 1, min(n, j + 6)))
                    if shooting:
                        decision, tdec = "defend", secs[j]
                        break
                    if not has_ft:
                        gave += 1  # foul to give: possession continues
                        j += 1
                        continue
                    decision, tdec = "foul", secs[j]
                    break
                if (k in ("shot", "tov") and tm == T) or k in ("endp", "endg") or (k == "foul" and tm == T) \
                        or (k == "steal" and tm == L):
                    decision, tdec = "defend", secs[j]
                    break
                j += 1
            if decision is None:
                break
            if tdec > W:  # possession ended before the window: not the state we study
                i = j
                continue
            # leader win
            lead_final = (gm.fh - gm.fa) if L == home else (gm.fa - gm.fh)
            # regulation result: score at end of regulation period
            endreg = g[g.kind.astype(str) == "endp"]
            found = dict(game_id=gid, league=league, season=int(gm.season), stype=int(gm.stype), t0=float(t0),
                         tdec=float(tdec), decision=decision, gave=gave, win=bool(lead_final > 0),
                         ot=bool(gm.ot), leader_home=(L == home))
        if found:
            rows.append(found)
    return pd.DataFrame(rows)


def summarize(df, league):
    res = {}
    for d in ("foul", "defend"):
        s = df[df.decision == d]
        res[d] = dict(n=len(s), win=bc.wilson(int(s.win.sum()), len(s)), ot=bc.wilson(int(s.ot.sum()), len(s)),
                      win_in_ot=bc.wilson(int((s.win & s.ot).sum()), int(s.ot.sum())))
    return res


BINS = [(-0.1, 4, "0-4"), (4, 8, "4-8"), (8, 12, "8-12"), (12, 99, "12+")]
XMID = {"0-4": 2, "4-8": 6, "8-12": 10, "12+": 14}


def strat_diff(df, labels, B=4000, seed=3):
    """Foul minus defend win rate, averaged over bins with weights = bin size (bootstrap within bins)."""
    rng = np.random.default_rng(seed)
    parts = [df[df.bin == b] for b in labels]
    w = np.array([len(p) for p in parts], float)
    w /= w.sum()
    def est(ps):
        return sum(wi * (p[p.decision == "foul"].win.mean() - p[p.decision == "defend"].win.mean()) for wi, p in zip(w, ps))
    point = est(parts)
    bs = []
    for _ in range(B):
        ps = []
        for p in parts:
            f = p[p.decision == "foul"].win.to_numpy(); d = p[p.decision == "defend"].win.to_numpy()
            ps.append((f[rng.integers(0, len(f), len(f))].mean(), d[rng.integers(0, len(d), len(d))].mean()))
        bs.append(sum(wi * (a - b) for wi, (a, b) in zip(w, ps)))
    return float(point), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def build(lg):
    path = os.path.join(bc.SCRATCH, f"foul3_{lg}.csv")
    df = pd.read_csv(path) if os.path.exists(path) and "--fresh" not in sys.argv else episodes(lg)
    df.to_csv(path, index=False)
    df = df[df.decision.isin(["foul", "defend"])]
    df["bin"] = pd.cut(df.t0, [b[0] for b in BINS] + [99], labels=[b[2] for b in BINS])
    df["regloss"] = (~df.win) & (~df.ot)
    stats = {}
    for d in ("foul", "defend"):
        s = df[df.decision == d]
        stats[d] = dict(n=len(s), win=bc.wilson(int(s.win.sum()), len(s)), ot=bc.wilson(int(s.ot.sum()), len(s)),
                        regloss=bc.wilson(int(s.regloss.sum()), len(s)),
                        otwin=bc.wilson(int((s.win & s.ot).sum()), int(s.ot.sum())))
    live = ["4-8", "8-12", "12+"]
    sd = strat_diff(df, live)
    early = df.season <= 2019
    sd_e = strat_diff(df[early], live)
    sd_l = strat_diff(df[~early], live)
    series = []
    for d, name in (("foul", "foul"), ("defend", "defend")):
        pts = []
        for b in [x[2] for x in BINS]:
            s = df[(df.decision == d) & (df.bin == b)]
            if len(s) >= 10:
                p, lo, hi = bc.wilson(int(s.win.sum()), len(s))
                pts.append(dict(x=XMID[b], y=bc.r3(p), lo=bc.r3(lo), hi=bc.r3(hi), n=int(len(s))))
        series.append(dict(name=name, points=pts))
    tab = df.groupby(["bin", "decision"], observed=True).agg(n=("win", "size"), win=("win", "mean"), ot=("ot", "mean"), regloss=("regloss", "mean"))
    print(lg, stats, "\nstrat diff", sd, "early", sd_e, "late", sd_l)
    print(tab)
    print("foul time median", df[df.decision == "foul"].tdec.median(), "share fouling (live bins)", (df[df.bin.isin(live)].decision == "foul").mean())
    return df, stats, sd, sd_e, sd_l, series


def pct(x):
    return f"{100 * x:.1f}%"


if __name__ == "__main__":
    for lg in ("cbb", "nba"):
        df, st, sd, sde, sdl, series = build(lg)
        F, Dd = st["foul"], st["defend"]
        L = lg.upper()
        seas = "2011-12 to 2025-26"
        robust = sd[1] > 0 or sd[2] < 0
        same_sign = (sde[0] > 0) == (sdl[0] > 0)
        out = {
            "id": f"{lg}-foul-up-3",
            "sport": L,
            "question": "Up 3 in the last 12 seconds, should the leader foul or defend?",
            "answer": (f"{'Foul' if robust and sd[0] > 0 else 'No clear edge'}: leader wins {pct(F['win'][0])} fouling, {pct(Dd['win'][0])} defending; "
                       f"{100*sd[0]:+.1f} pp at equal time (CI {100*sd[1]:+.1f} to {100*sd[2]:+.1f})."),
            "findings": [
                f"Leader win: foul {pct(F['win'][0])} (CI {pct(F['win'][1])}-{pct(F['win'][2])}, n={F['n']}), defend {pct(Dd['win'][0])} (CI {pct(Dd['win'][1])}-{pct(Dd['win'][2])}, n={Dd['n']}).",
                f"Same-time difference (foul minus defend): {100*sd[0]:+.1f} pp (95% CI {100*sd[1]:+.1f} to {100*sd[2]:+.1f}).",
                f"Reached OT: foul {pct(F['ot'][0])}, defend {pct(Dd['ot'][0])}. Lost in regulation: foul {pct(F['regloss'][0])}, defend {pct(Dd['regloss'][0])}.",
                f"Leader win rate once in OT: foul {pct(F['otwin'][0])} (n={int(round(F['ot'][0]*F['n']))}), defend {pct(Dd['otwin'][0])} (n={int(round(Dd['ot'][0]*Dd['n']))}).",
            ],
            "method": ("First trailer possession per game that is live with 12 s or less, final regulation period, down 3. "
                       "Foul = leader's non-shooting foul sending trailer to the line before any shot. "
                       "Compared within possession-start bins (4-8, 8-12, 12+ s); outcome = game win incl. OT."),
            "data": f"ESPN play-by-play via sportsdataverse, {L}, {seas}, {len(df):,} games.",
            "n": int(len(df)),
            "robust": bool(robust and same_sign),
            "interest": 4,
            "split_check": f"Foul minus defend: {100*sde[0]:+.1f} pp in 2012-19 (CI {100*sde[1]:+.1f} to {100*sde[2]:+.1f}), {100*sdl[0]:+.1f} in 2020-26 (CI {100*sdl[1]:+.1f} to {100*sdl[2]:+.1f}).",
            "chart": {
                "type": "line",
                "title": f"{L}: leader win % up 3, by seconds left at trailer possession start",
                "x_label": "seconds left at possession start (bin middle; 14 = started earlier, live at 12)",
                "y_label": "leader win %",
                "y_fmt": "pct", "x_reverse": True, "ref": None, "mark": None,
                "series": series,
            },
        }
        import json
        print(out["answer"]); print("\n".join(out["findings"])); print(out["split_check"])
        bc.write_json(out, out["id"])
