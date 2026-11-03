#!/usr/bin/env python3
"""FV test of position-adjusted frame for CBB returners (Nov 3 2026, research). Each board row's projected NBA position
comes from nbapos.py's model refit without the player's own draft class (his last college season), applied to his last
college season before the board. Candidates swap into / add to the shipped returner set (data/cbb_fit.json):

  ht_np    height minus the projected position's NBA height (Barttorvik listing of NBA players at each position,
           mixed over the position probabilities)          swap:ht_np replaces ht_g (height vs his college role)
  ht_npz   the same over the pooled within-position sd     swap:ht_npz
  epos     expected NBA position (1 PG - 5 C)               add
  splus_np Stat+ against the projected position's BPM mean / sd (swap:splus_np replaces splus, G/F/C by college role)

Gate (scripts/cbb_fv_sweep2.py): 2009-16 boards out of fold under three fold rules (gain in each, >= 4/5 folds,
player-clustered t >= 2), then fit 2009-16 and grade held 2017-19 and forward 2020-23 boards on the horizon outcome
(deviance gain, top 10 / 25 / 50 not worse). Pass = all three.

    python3 scripts/research/nbapos/nbapos_fv.py <bbref_pos.json> [cand,...]"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, '..', '..'))
import nbapos as M
import cbb_fit as F
import cbb_data as D
import cbb_fv_sweep2 as S2

SPEC = ['ht', 'skill']
if os.environ.get('LEAN') == '1':   # the shipped display model's inputs (scripts/cbb_nbapos.py)
    M.SKILL = ['ast', 'usg', 'tp_sh', 'orb', 'drb', 'blk', 'stl', 'rim_sh', 'dunk40', 'ft']
LAM = 0.3
G3 = {'PG': 'G', 'SG': 'G', 'SF': 'F', 'PF': 'F', 'C': 'C'}


def class_models(players):
    """one fit per held-out draft class, plus 'all'"""
    out = {}
    for k in sorted({p['cls'] for p in players}) + ['all']:
        R, Y, W = [], [], []
        for p in players:
            if p['cls'] == k: continue
            for s, f in p['rows']:
                R.append(f); Y.append(p['y']); W.append(1.0 / len(p['rows']))
        X = M.design(R, SPEC)
        mu, sd = X.mean(0), X.std(0) + 1e-9
        out[k] = (M.fit((X - mu) / sd, np.array(Y), np.array(W), LAM), mu, sd)
    return out


def norms(players, key='ht'):
    """each NBA position's mean and sd of a college measure (players' final college season), weighted by minutes share"""
    v = np.array([p['rows'][-1][1][key] for p in players]); Y = np.array([p['y'] for p in players])
    m = (Y * v[:, None]).sum(0) / Y.sum(0)
    s = np.sqrt((Y * (v[:, None] - m) ** 2).sum(0) / Y.sum(0))
    pooled = float(np.sqrt((Y * (v[:, None] - m) ** 2).sum() / Y.sum()))
    return m, s, pooled


def project(models, cls, f):
    B, mu, sd = models.get(cls, models['all'])
    return M.predict(B, (M.design([f], SPEC) - mu) / sd)[0]


POOL = os.environ.get('POOL') == '1'


def pooled(seasons):
    """the college line pooled over every season so far, weighted by minutes (height and class from the latest)"""
    L = [(M.col_feats(x), max(1.0, (x['mp'] or 0) * (x['gp'] or 0))) for x in seasons if x['hti']] or [(M.col_feats(seasons[-1]), 1.0)]
    w = sum(m for _, m in L)
    f = dict(L[-1][0])
    for k in M.SKILL: f[k] = sum(x[k] * m for x, m in L) / w
    return f


def main():
    careers, players = M.load(sys.argv[1])
    models = class_models(players)
    hm, hs, hp = norms(players)
    print('NBA position height (Barttorvik listing):', {M.POS[k]: (round(hm[k], 1), round(hs[k], 1)) for k in range(5)}, 'pooled sd', round(hp, 2))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    Mr = fitj['models']['returner']; F.TOP_MEAN = Mr['topMean']
    rows, hr = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = F.features(c, i)
            prev = c['seasons'][i - 1]
            p = project(models, c['last'], pooled(c['seasons'][:i]) if POOL else M.col_feats(prev))
            f['epos'] = float(p @ np.arange(1, 6))
            f['ht_np'] = f['ht'] - float(p @ hm)
            f['ht_npz'] = f['ht_np'] / hp
            f['ht_np_lo'] = min(0.0, f['ht_np']); f['ht_np_hi'] = max(0.0, f['ht_np'])
            f['ht_mix'] = (f['ht_np'] + f['ht_g']) / 2
            mu = sum(p[k] * F.SPLUS[G3[M.POS[k]]][0] for k in range(5)); sd = sum(p[k] * F.SPLUS[G3[M.POS[k]]][1] for k in range(5))
            f['splus_np'] = 100 + 25 * ((prev['bpm'] or 0) - mu) / sd
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held 2017-19 {sum(r["year"] <= 2019 for r in hr)}, fwd 2020-23 {sum(r["year"] >= 2020 for r in hr)}')
    a = np.array([[r['f']['ht_g'], r['f']['ht_np'], r['f']['epos']] for r in rows])
    print('corr ht_g / ht_np / epos', np.round(np.corrcoef(a.T), 2).tolist())
    kept = Mr['kept']
    SW = {'swap:ht_mix': ('ht_g', 'ht_mix'), 'swap:ht_np': ('ht_g', 'ht_np'), 'swap:ht_npz': ('ht_g', 'ht_npz'), 'swap:splus_np': ('splus', 'splus_np')}
    orig = S2.colset
    def colset(kp, cand):
        if cand in SW: return [SW[cand][1] if k == SW[cand][0] else k for k in kp]
        if cand == 'swap:ht_lohi': return [k for k in kp if k != 'ht_g'] + ['ht_np_lo', 'ht_np_hi']
        if cand == 'ht_lo': return kp + ['ht_np_lo']
        return orig(kp, cand)
    S2.colset = colset
    cands = sys.argv[2].split(',') if len(sys.argv) > 2 else ['swap:ht_np', 'swap:ht_npz', 'ht_np', 'epos', 'swap:splus_np']
    res = {}; cvc = {}; hc = {}
    for cnd in cands:
        a = S2.cv(rows, kept, Mr['lam'], cnd, cvc)
        b = S2.held(rows, hr, kept, Mr['lam'], cnd, hc)
        cv_ok = all(x['gain'] > 0 and x['folds'] >= 4 and x['t'] >= 2 for x in a.values())
        top_ok = lambda h: h['gain'] > 0 and all(h[k][1] >= h[k][0] for k in ('top10', 'top25', 'top50'))
        res[cnd] = {'cv': a, **b, 'pass': bool(cv_ok and top_ok(b['held']) and top_ok(b['fwd']))}
        print(cnd, 'PASS' if res[cnd]['pass'] else 'fail', json.dumps(res[cnd])); sys.stdout.flush()
    out = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_nbapos_fv%s%s.json' % ('_pool' if POOL else '', '_lean' if os.environ.get('LEAN') == '1' else ''))
    json.dump({'asof': __import__('datetime').date.today().isoformat(), 'kept': kept,
               'ht_norms': {M.POS[k]: [round(hm[k], 2), round(hs[k], 2)] for k in range(5)}, 'results': res}, open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
