#!/usr/bin/env python3
"""Nov 23 2026 (Trevin Jirak): does the CBB in-season blend underrate returners whose role grew this season?
Builds the cbb_live_backtest.py checkpoint rows (2010-26, nine dates) plus what the variants need:
last season's minutes and mpg, minutes to date, and a 'role run' now-grade (only the trailing run of games in his
current role when the earlier games were a smaller role). Writes rows.pkl.gz next to this file for test.py."""
import gzip, json, os, pickle, sys
import numpy as np
from multiprocessing import Pool
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import cbb_data as D
import cbb_fit as F
import cbb_live as L
import cbb_live_backtest as B

FIT = json.load(open(F.OUT))
LF = json.load(open(L.LIVE_FIT))
RECON = LF['recon']
careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
F.horizon_fv(careers); F.set_context(careers)
BY = {str(c['pid']): c for c in careers}


def role_run(sub):
    """the trailing run of games at 50%+ of his last-5 mean minutes; returned only when the games before it were a
    smaller role (mpg under 70% of the run's) and the run has 2+ games"""
    mins = [r[L.C['min']] or 0 for r in sub]
    ref = np.mean(mins[-5:])
    j = len(sub)
    while j > 0 and mins[j - 1] >= 0.5 * ref: j -= 1
    if j == 0 or len(sub) - j < 2: return None
    pre = [m for m in mins[:j] if m > 0]
    run = mins[j:]
    if pre and np.mean(pre) >= 0.7 * np.mean(run): return None
    return sub[j:]


def season(y):
    by_p, tg = B.load_season(y)
    full_games = np.median([len(v) for v in tg.values() if len(v) >= 10])
    cuts = [f'{y - 1 if m >= 11 else y}{m:02d}{d:02d}' for m, d in B.CHECK]
    out = []
    for pid, rs in by_p.items():
        c = BY.get(pid)
        if not c: continue
        i = next((j for j, s in enumerate(c['seasons']) if s['year'] == y), None)
        if i is None: continue
        meta = c['seasons'][i]
        srow = {k: meta.get(k) for k in ('year', 'team', 'conf', 'yr', 'hti', 'role', 'rec')}
        pre_cc = dict(c, seasons=c['seasons'][:i] + [srow])
        f_pre = F.features(pre_cc, i)
        team_n = len(tg.get(rs[-1][L.C['team']], [])) or 1
        full = L.line(L.summed(rs, team_n), RECON, meta)
        prev = c['seasons'][i - 1] if i > 0 else None
        prev_n = (prev['mp'] or 0) * (prev['gp'] or 0) if prev else 0.0
        car_n = sum((s['mp'] or 0) * (s['gp'] or 0) for s in c['seasons'][:i])
        row = {'y': y, 'pid': pid, 'new': f_pre['newcomer'], 'out': c['nba']['fvh'], 'f_pre': f_pre,
               'f_full': F.features(L.next_career(pre_cc, full), i + 1), 'prev_n': prev_n, 'prev_mp': (prev['mp'] or 0) if prev else 0.0,
               'prev_minper': (prev.get('min_per') or 0) if prev else 0.0, 'car_n': car_n, 'full_mp': full['mp'], 'dates': []}
        for cut in cuts:
            sub, tgd = B.to_date(rs, tg, cut)
            if not sub: row['dates'].append(None); continue
            a = L.summed(sub, max(1, tgd))
            ln = L.line(a, RECON, meta)
            n = a['mp'] * a['gp']
            gp_full = a['gp'] * full_games / max(1, tgd) if tgd < full_games else None
            d = {'n': n, 'mp': a['mp'], 'gp': a['gp'], 'f_proj': F.features(L.next_career(pre_cc, ln, gp_full), i + 1)}
            rr = role_run(sub)
            if rr:
                ar = L.summed(rr, max(1, len(rr)))
                lr = L.line(ar, RECON, meta)
                # the role run read as his season: games projected to a full season at the run's rate
                d['f_role'] = F.features(L.next_career(pre_cc, lr, full_games), i + 1)
                d['n_role'] = ar['mp'] * ar['gp']; d['mp_role'] = ar['mp']
            row['dates'].append(d)
        out.append(row)
    print(y, len(out), flush=True)
    return out


if __name__ == '__main__':
    with Pool(int(os.environ.get('NP', '8'))) as p:
        rows = sum(p.map(season, list(B.SEASONS)), [])
    # score here (cheap), keep only arrays
    sc = lambda fs: L.score_many(fs, FIT, ladder=True)
    e_pre, _, Lpre = sc([r['f_pre'] for r in rows]); e_full, _, _ = sc([r['f_full'] for r in rows])
    pts, fp, frl = [], [], []
    for i, r in enumerate(rows):
        for j, d in enumerate(r['dates']):
            if d:
                pts.append((i, j, d['n'], d['mp'], d['gp'], d.get('n_role', np.nan), d.get('mp_role', np.nan)))
                fp.append(d['f_proj']); frl.append(d.get('f_role') or d['f_proj'])
    e_proj, _, Lproj = sc(fp); e_role, _, Lrole = sc(frl)
    P = np.array(pts, float)
    I = P[:, 0].astype(int)
    meta = {k: np.array([r[k] if r[k] is not None else np.nan for r in rows], float) for k in ('y', 'new', 'out', 'prev_n', 'prev_mp', 'prev_minper', 'car_n', 'full_mp')}
    pickle.dump({'I': I, 'J': P[:, 1].astype(int), 'N': P[:, 2], 'MP': P[:, 3], 'GP': P[:, 4], 'NR': P[:, 5], 'MPR': P[:, 6],
                 'e_pre': e_pre, 'e_full': e_full, 'e_proj': e_proj, 'e_role': e_role, 'Lpre': Lpre, 'Lproj': Lproj, 'Lrole': Lrole,
                 'meta': meta, 'pid': np.array([r['pid'] for r in rows])}, gzip.open(os.path.join(HERE, 'rows.pkl.gz'), 'wb'))
    print('rows', len(rows), 'checkpoints', len(pts))
