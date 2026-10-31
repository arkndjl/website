"""NFL injury term with questionable players priced by their last practice (Nov 1 2026 sweep), in the game model's
walk-forward. P(plays) for a questionable non-QB by (last practice, played the team's last game), measured on
2016-20 only (data/sweep_nov01/nfl_practice.json); everything else as nfl_games.injury_history. Scored: margin MAE
2017-20 (tune) and 2021-25 (held), paired by game, clustered by week; and vs the close (does the change move the
model's residual off the line toward the result)."""
import csv, json, os, sys
from collections import defaultdict
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import nfl_games as N
import harness as H
ROOT = os.path.dirname(HERE)
T = json.load(open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nfl_practice.json')))

def prac(s):
    s = (s or '').lower()
    return 'full' if s.startswith('full') else 'limited' if s.startswith('limited') else 'dnp' if s.startswith('did not') else None

def pq(practice, recent):
    k = f'tune|{practice}|{recent}'
    if practice and k in T and T[k]['n'] >= 100:
        return T[k]['played']
    return 0.75 if recent else 0.5

def inj_hist(games, years, practice_on):
    import nfl_war as W
    cp = os.path.join(N.CACHE, f'inj_hist_prac{int(practice_on)}.json')
    try:
        return json.load(open(cp))
    except (OSError, ValueError):
        pass
    out = {}
    for y in years:
        maps = W.gsis_map(y)
        prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
        top = max([int(g['week']) for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')] + [1])
        led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, min(top + 1, 19) + 1)}
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status'], prac(r['practice_status'])))
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        last_wk = {}
        for g in sg:
            w = int(g['week']); row = []
            for side in ('home', 'away'):
                t = N.team(g[f'{side}_team']); pw = last_wk.get(t); fresh = cont = 0.0
                for gsis, stt, pr in rep.get((t, w), []):
                    L = led[min(w, 19, top + 1)]
                    v = N.player_value(prev.get(gsis, (0.0, 0)), L.get(gsis, (0.0, 0)))
                    played = True if (pw is None or pw >= 18 or w > 18) else led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    p = pq(pr, played) if (practice_on and stt == 'Questionable') else N.play_prob(stt, played)
                    c = (1 - p) * max(v, 0.0) * N.PTS_PER_WIN
                    if played: fresh += c
                    else: cont += c
                row += [fresh, cont]
                last_wk[t] = w
            out[g['game_id']] = row
        print('inj', y, practice_on, flush=True)
    json.dump(out, open(cp, 'w'))
    return out

if __name__ == '__main__':
    last = 2025
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    P = json.load(open(N.FIT))['params']
    _, data = N.walk(games, box, qbs, P)
    res = {}
    preds = {}
    for on in (0, 1):
        inj = inj_hist(games, range(N.INJ_FIRST, last + 1), on)
        D = []
        for g, x, _ in data:
            if g['home_score'] in ('', 'NA') or int(g['season']) < 2016:
                continue
            r = inj.get(g['game_id'])
            x = dict(x); x['inj'] = ((r[2] + r[3]) - (r[0] + r[1])) if r else 0.0
            D.append((g, x))
        X = np.array([[x[f] for f in N.FEATS] for _, x in D]); y = np.array([N.num(g['result']) for g, _ in D])
        S = np.array([int(g['season']) for g, _ in D]); line = np.array([N.num(g['spread_line'], np.nan) for g, _ in D])
        wk = np.array([f"{g['season']}-{g['week']}" for g, _ in D])
        pred = np.full(len(y), np.nan)
        for s in range(2017, last + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], y[tr], rcond=None)[0]; pred[te] = X[te] @ b
        preds[on] = pred
        res[f'coef_inj_{on}'] = round(float(b[N.FEATS.index('inj')]), 3)
    ok = ~np.isnan(line) & ~np.isnan(preds[0])
    for lab, k in (('tune 2017-20', (S <= 2020) & ok), ('held 2021-25', (S >= 2021) & ok)):
        a = np.abs(preds[1][k] - y[k]); b0 = np.abs(preds[0][k] - y[k])
        r = H.paired(a, b0, cluster=wk[k])
        # vs close: regress result - line on (model - line); does the new model's gap carry more?
        e1 = preds[1][k] - line[k]; e0 = preds[0][k] - line[k]; rr = y[k] - line[k]
        res[lab] = {'n': int(k.sum()), 'mae_new': round(float(a.mean()), 4), 'mae_old': round(float(b0.mean()), 4),
                    't': round(r['t'], 2), 'line': round(float(np.abs(line[k] - y[k]).mean()), 4),
                    'slope_new': round(float(np.polyfit(e1, rr, 1)[0]), 3), 'slope_old': round(float(np.polyfit(e0, rr, 1)[0]), 3),
                    'gapdiff_vs_res_t': None}
        # does the change itself (new - old) predict result - line?
        dlt = preds[1][k] - preds[0][k]
        bb = (dlt @ rr) / (dlt @ dlt); se = np.sqrt(np.sum((rr - bb * dlt) ** 2) / (len(rr) - 1) / (dlt @ dlt))
        res[lab]['delta_vs_close_b'] = round(float(bb), 3); res[lab]['delta_vs_close_t'] = round(float(bb / se), 2)
        print(lab, res[lab], flush=True)
    print(res)
    json.dump(res, open(os.path.join(ROOT, 'data', 'sweep_nov01', 'nfl_practice_games.json'), 'w'), indent=1)
