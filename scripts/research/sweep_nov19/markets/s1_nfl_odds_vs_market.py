# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""S1 (descriptive): NFL season sim P(playoffs) vs Polymarket (global) make-the-playoffs prices before weeks 1, 5, 9,
13, 15 and 17 of 2024 and 2025 (walk-forward ratings, the shipped rating sd 5 x sqrt(share left)).
    python3 s1_nfl_odds_vs_market.py <out.json>"""
import json, math, os, random, sys
import numpy as np
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import nfl_season_backtest as B, nfl_games as N, poly_hist as PH
NICK = {'Cardinals': 'ARI', 'Falcons': 'ATL', 'Ravens': 'BAL', 'Bills': 'BUF', 'Panthers': 'CAR', 'Bears': 'CHI', 'Bengals': 'CIN',
        'Browns': 'CLE', 'Cowboys': 'DAL', 'Broncos': 'DEN', 'Lions': 'DET', 'Packers': 'GB', 'Texans': 'HOU', 'Colts': 'IND',
        'Jaguars': 'JAX', 'Chiefs': 'KC', 'Rams': 'LA', 'Chargers': 'LAC', 'Raiders': 'LV', 'Dolphins': 'MIA', 'Vikings': 'MIN',
        'Patriots': 'NE', 'Saints': 'NO', 'Giants': 'NYG', 'Jets': 'NYJ', 'Eagles': 'PHI', 'Steelers': 'PIT', 'Seahawks': 'SEA',
        '49ers': 'SF', 'Buccaneers': 'TB', 'Titans': 'TEN', 'Commanders': 'WAS'}


def abbr(name):
    for k, v in NICK.items():
        if name.endswith(k): return v
    return None


def main(outfn):
    F = json.load(open(N.FIT))
    G, box, qbs = N.load(2025)
    N.index_qbs(qbs, G); N.load_qb_teams(2025)
    inj = N.injury_history(G, range(N.INJ_FIRST, 2026))
    data, snaps = B.walk(G, box, qbs, F['params'], inj, B.WEEKS)
    Bc = B.coefs(data)[0]
    out = []
    for s in (2024, 2025):
        ev = PH.load('nfl', 'playoffs', s)
        sg, res_all = N.season_results(G, s)
        sched = [(g['home_team'], g['away_team']) for g in sg]
        lg = N.League(sched, 3)
        field, _ = lg.seeds(res_all, random.Random(1))
        made = {t for c in field.values() for t in c}
        b = dict(Bc[s]); b['sd'] = F['sd']
        rest = lambda x: max(-7, min(7, N.num(x, 7) - 7))
        for wk in B.WEEKS:
            snap = snaps[(s, wk)]
            R = {t: sum(b.get(f, 0.0) * v[f] for f in ('elo', 'epa', 'qb', 'mkt')) for t, v in snap.items()}
            res0 = [r if int(g['week']) < wk else None for g, r in zip(sg, res_all)]
            mus = {k: R[N.team(g['home_team'])] - R[N.team(g['away_team'])] + (b['home'] if g['location'] != 'Neutral' else 0)
                   + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest'])) for k, g in enumerate(sg) if res0[k] is None}
            left = sum(1 for r in res0 if r is None) / len(sg)
            rsd = B.snap_sd(5 * math.sqrt(left))
            B.SDS = [rsd]
            _, _, o = B.sim_checkpoint((s, wk, R, b, sched, res0, mus, 'full'))
            po = o[rsd][0]
            day = min(g['gameday'] for g in sg if int(g['week']) == wk)
            px = PH.asof(ev, day)
            mk = {abbr(k): v for k, v in px.items() if abbr(k)}
            alive = sum(1 for t in lg.T if N.team(t) in mk or t in mk)
            if len(mk) < 8 or not PH.liquid(px, sum(1 for k in px if abbr(k) in {N.team(t) for t in made} | made)):
                out.append({'S': s, 'wk': wk, 'day': day, 'skip': 'no market or illiquid', 'listed': len(mk), 'sum': round(sum(px.values()), 2)})
                print(out[-1], flush=True); continue
            bm = bk = lm = lk = 0.0; n = 0
            cl = lambda v: min(max(v, 1e-3), 1 - 1e-3)
            for i, t in enumerate(lg.T):
                q = mk.get(t, mk.get(N.team(t)))
                if q is None: continue
                y = 1.0 if t in made else 0.0
                p = float(po[i])
                bm += (p - y) ** 2; bk += (q - y) ** 2; n += 1
                lm += -math.log(cl(p) if y else 1 - cl(p)); lk += -math.log(cl(q) if y else 1 - cl(q))
            out.append({'S': s, 'wk': wk, 'day': day, 'teams': n, 'brier_model': round(bm / n, 5), 'brier_market': round(bk / n, 5),
                        'll_model': round(lm / n, 4), 'll_market': round(lk / n, 4)})
            print(out[-1], flush=True)
    ok = [r for r in out if 'teams' in r]
    if ok:
        s = {k: round(sum(r[k] for r in ok) / len(ok), 5) for k in ('brier_model', 'brier_market', 'll_model', 'll_market')}
        s['checkpoints'] = len(ok); print(s)
        out.append({'summary': s})
    json.dump(out, open(outfn, 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1])
