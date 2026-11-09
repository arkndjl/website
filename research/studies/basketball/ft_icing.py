# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Study: free throw icing (NBA + CBB).

Sample: first free throw of a trip in the last 2:00 of the final regulation period or OT, margin within 3
before the trip. Iced = the defending team calls a timeout between the foul and the first free throw.
Outcome: first FT made. Control: shooter's FT% on all his other attempts in the data (leave-one-out),
compared as made minus expected; shooters with < 20 other attempts dropped. CIs: game-cluster bootstrap.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bball_common as bc

PREV = {"ft", "shot", "tov", "dreb", "steal", "endp"}


def trips(league):
    ev = bc.load(league)
    games = bc.game_table(ev, league)
    ev = ev[ev.game_id.isin(games.index)]
    ft = ev[(ev.kind == "ft") & (ev["sub"] != "special") & (ev.player > 0)]
    car = ft.groupby("player").made.agg(["sum", "count"])
    reg = bc.REG_PERIODS[league]
    late = ev[(ev.period >= reg) & (ev.sec <= 120)]
    rows = []
    for gid, g in late.groupby("game_id", sort=False):
        kinds = g.kind.astype(str).tolist(); teams = g.team.tolist(); secs = g.sec.tolist()
        made = g.made.tolist(); subs = g["sub"].astype(str).tolist(); per = g.period.tolist()
        hs = g.hs.tolist(); as_ = g.as_.tolist(); pl = g.player.tolist()
        home = int(g.home.iloc[0])
        last_rel = None
        for i, k in enumerate(kinds):
            if k == "ft" and subs[i] != "special" and pl[i] > 0:
                first = not (last_rel is not None and kinds[last_rel] == "ft" and teams[last_rel] == teams[i]
                             and secs[last_rel] == secs[i])
                if first:
                    T = teams[i]
                    # look back at the dead-ball window
                    iced = own = False
                    j = i - 1
                    while j >= 0 and secs[j] == secs[i] and kinds[j] not in PREV:
                        if kinds[j] == "foul":
                            break
                        if kinds[j] == "timeout":
                            if teams[j] == T:
                                own = True
                            elif teams[j] > 0:
                                iced = True
                        j -= 1
                    # margin before this FT (score after previous event)
                    pre_h, pre_a = (hs[i - 1], as_[i - 1]) if i > 0 else (hs[i] - made[i] * (T == home), as_[i] - made[i] * (T != home))
                    margin = (pre_h - pre_a) if T == home else (pre_a - pre_h)
                    if abs(margin) <= 3 and (per[i] > reg or secs[i] <= 120):
                        rows.append(dict(game_id=gid, season=int(g.season.iloc[0]), player=pl[i], made=bool(made[i]),
                                         iced=iced, own=own, sec=secs[i], margin=margin, ot=per[i] > reg))
            if k in PREV:
                last_rel = i
    df = pd.DataFrame(rows)
    c = car.reindex(df.player)
    df["oth_n"] = c["count"].to_numpy() - 1
    df["exp"] = (c["sum"].to_numpy() - df.made.astype(int)) / df.oth_n.clip(lower=1)
    return df[df.oth_n >= 20]


def build(lg):
    path = os.path.join(bc.SCRATCH, f"icing_{lg}.csv")
    df = pd.read_csv(path) if os.path.exists(path) and "--fresh" not in sys.argv else trips(lg)
    df.to_csv(path, index=False)
    df["resid"] = df.made.astype(float) - df.exp
    base = df[~df.own]  # drop trips where the shooting team itself called time
    I, N = base[base.iced], base[~base.iced]
    pi = bc.wilson(int(I.made.sum()), len(I)); pn = bc.wilson(int(N.made.sum()), len(N))
    d = bc.boot_diff(I.resid.to_numpy(), N.resid.to_numpy(), I.game_id.to_numpy(), N.game_id.to_numpy())
    early = base.season <= 2019
    de = bc.boot_diff(base[early & base.iced].resid, base[early & ~base.iced].resid, B=1000)
    dl = bc.boot_diff(base[~early & base.iced].resid, base[~early & ~base.iced].resid, B=1000)
    tiers = [(0, 0.65, "<65%"), (0.65, 0.75, "65-75%"), (0.75, 0.85, "75-85%"), (0.85, 1.01, "85%+")]
    series = []
    for flag, name in ((True, "iced"), (False, "not iced")):
        pts = []
        for lo, hi, lab in tiers:
            s = base[(base.iced == flag) & (base.exp >= lo) & (base.exp < hi)]
            p, l, h = bc.wilson(int(s.made.sum()), len(s))
            pts.append(dict(x=lab, y=bc.r3(p), lo=bc.r3(l), hi=bc.r3(h), n=int(len(s))))
        series.append(dict(name=name, points=pts))
    print(lg, len(base), "iced", len(I), pi, I.exp.mean(), "not", len(N), pn, N.exp.mean(), "diff", d, de, dl)
    L = lg.upper()
    robust = (d[1] > 0 or d[2] < 0) and ((de[0] > 0) == (dl[0] > 0))
    verdict = ("Icing works" if robust and d[0] < 0 else "Icing does not work" if robust else "No measurable effect")
    out = {
        "id": f"{lg}-ft-icing",
        "sport": L,
        "question": "Does a timeout before a late free throw make the shooter miss?",
        "answer": f"{verdict}: iced shooters {100*d[0]:+.1f} pp vs un-iced, relative to own FT% (CI {100*d[1]:+.1f} to {100*d[2]:+.1f}).",
        "findings": [
            f"Iced: {100*pi[0]:.1f}% made (CI {100*pi[1]:.1f}-{100*pi[2]:.1f}), shooters' usual {100*I.exp.mean():.1f}%, n={len(I)}.",
            f"Not iced: {100*pn[0]:.1f}% made (CI {100*pn[1]:.1f}-{100*pn[2]:.1f}), shooters' usual {100*N.exp.mean():.1f}%, n={len(N)}.",
            f"Iced minus not iced, vs own FT%: {100*d[0]:+.1f} pp (95% CI {100*d[1]:+.1f} to {100*d[2]:+.1f}).",
        ],
        "method": ("First FT of a trip, last 2:00 of regulation or OT, margin within 3. Iced = defense timeout between foul and FT. "
                   "Outcome = made minus shooter's leave-one-out FT% (min 20 other FTs); game-clustered bootstrap."),
        "data": f"ESPN play-by-play via sportsdataverse, {L}, 2011-12 to 2025-26, {len(base):,} first free throws.",
        "n": int(len(base)),
        "robust": bool(robust),
        "interest": 3,
        "split_check": f"Iced minus not iced: {100*de[0]:+.1f} pp in 2012-19 (CI {100*de[1]:+.1f} to {100*de[2]:+.1f}), {100*dl[0]:+.1f} in 2020-26 (CI {100*dl[1]:+.1f} to {100*dl[2]:+.1f}).",
        "chart": {
            "type": "bar",
            "title": f"{L}: first FT make % late and close, by shooter's usual FT%",
            "x_label": "shooter FT% (other attempts)", "y_label": "made %",
            "y_fmt": "pct", "x_reverse": False, "ref": None, "mark": None,
            "series": series,
        },
    }
    print(out["answer"]); print("\n".join(out["findings"])); print(out["split_check"])
    bc.write_json(out, out["id"])


if __name__ == "__main__":
    for lg in sys.argv[1:] or ("nba", "cbb"):
        build(lg)
