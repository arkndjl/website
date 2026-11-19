# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S1 (descriptive): NHL season sim (playoffs, Cup) vs Polymarket (global) closed-market prices at the sim
backtest's own checkpoints, seasons 2024-25 and 2025-26, walk-forward settings.
    python3 s1_nhl_odds_vs_market.py <out.json>"""
import datetime as dt, json, math, os, sys
import numpy as np
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nhl_sim_backtest as B, nhl_games as G, poly_hist as PH
NICK = {'Ducks': 'ANA', 'Bruins': 'BOS', 'Sabres': 'BUF', 'Hurricanes': 'CAR', 'Blue Jackets': 'CBJ', 'Flames': 'CGY',
        'Blackhawks': 'CHI', 'Avalanche': 'COL', 'Stars': 'DAL', 'Red Wings': 'DET', 'Oilers': 'EDM', 'Panthers': 'FLA',
        'Kings': 'LAK', 'Wild': 'MIN', 'Canadiens': 'MTL', 'Devils': 'NJD', 'Predators': 'NSH', 'Islanders': 'NYI',
        'Rangers': 'NYR', 'Senators': 'OTT', 'Flyers': 'PHI', 'Penguins': 'PIT', 'Kraken': 'SEA', 'Sharks': 'SJS',
        'Blues': 'STL', 'Lightning': 'TBL', 'Maple Leafs': 'TOR', 'Mammoth': 'UTA', 'Hockey Club': 'UTA', 'Utah': 'UTA',
        'Canucks': 'VAN', 'Golden Knights': 'VGK', 'Jets': 'WPG', 'Capitals': 'WSH'}


def abbr(name):
    for k, v in NICK.items():
        if name.endswith(k): return v
    return None


def main(outfn):
    fit = json.load(open(G.FIT))
    P, feats, otc = fit['params'], fit['feats'], fit['ot']
    hist, rows, snaps = B.snapshots(P)
    coefs = B.bases(snaps, rows, feats)
    B.OTW.update(B.ot_fits(rows, coefs))
    chosen = json.load(open(B.OUT))['chosen']
    out, acc = [], {}
    for sn in snaps:
        S = sn['S']
        if S not in (2025, 2026): continue
        a, sd = chosen[str(S)]
        c = coefs[S]
        base = {t: sum(c[k] * v for k, v in sn['comp'][t].items() if k in c) for t in sn['comp']}
        reg = [g for g in hist if g['S'] == S and not g['po']]
        left_games = [g for g in reg if g['day'] >= sn['day']]
        left = len(left_games) / len(reg)
        teams, pm, pd_, pc, xp = B.sim(S, base, sn['pts'], left_games, c.get('home', 0.13), otc, a, sd, left,
                                       np.random.default_rng(1000 * S + sn['k']))
        pts, made, divw, cup = B.outcomes(hist, S)
        for kind, pmod, yes in (('playoffs', pm, made), ('title', pc, {cup})):
            ev = PH.load('nhl', kind, S)
            if not ev: continue
            px = PH.asof(ev, sn['day'])                       # the checkpoint day's games are not in the snapshot
            mk = {abbr(k): v for k, v in px.items() if abbr(k)}
            if len(mk) < 16 or not PH.liquid(px, 16 if kind == 'playoffs' else 1): continue
            if kind == 'title':
                t = sum(mk.values()); mk = {k: v / t for k, v in mk.items()}
            bm = bk = lm = lk = 0.0; n = 0
            for t_, p in zip(teams, pmod):
                if t_ not in mk: continue
                y = 1.0 if t_ in yes else 0.0
                q = mk[t_]
                bm += (p - y) ** 2; bk += (q - y) ** 2; n += 1
                cl = lambda v: min(max(v, 1e-3), 1 - 1e-3)
                lm += -math.log(cl(p) if y else 1 - cl(p)); lk += -math.log(cl(q) if y else 1 - cl(q))
            r = {'S': S, 'k': sn['k'], 'day': sn['day'], 'kind': kind, 'teams': n, 'brier_model': round(bm / n, 5),
                 'brier_market': round(bk / n, 5), 'll_model': round(lm / n, 4), 'll_market': round(lk / n, 4)}
            out.append(r); print(r, flush=True)
    for kind in ('playoffs', 'title'):
        R = [r for r in out if r['kind'] == kind]
        if R:
            acc[kind] = {'checkpoints': len(R), 'brier_model': round(sum(r['brier_model'] for r in R) / len(R), 5),
                         'brier_market': round(sum(r['brier_market'] for r in R) / len(R), 5),
                         'll_model': round(sum(r['ll_model'] for r in R) / len(R), 4),
                         'll_market': round(sum(r['ll_market'] for r in R) / len(R), 4)}
    print(acc)
    json.dump({'rows': out, 'summary': acc}, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1])
