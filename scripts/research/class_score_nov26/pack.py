# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Pack the class-score tests for Process: data/class_score_research.json (the 'Class score' glossary term) and the
Research card research/studies/cfb/class-top-end-depth.json. Run after cfb_build.py, cbb_build.py, tests.py (both
sports, both rounds), sens.py, stock.py, concave.py and round4.py."""
import json, math, os
import numpy as np
import tests as T

out = {'asof': '2026-11-26'}
sens = json.load(open(os.path.join(T.HERE, 'sens.json')))
for sp in ('cfb', 'cbb'):
    cfg = T.CFG[sp]; P, S, C = T.load(sp)
    r1 = json.load(open(os.path.join(T.HERE, f'{sp}_tests.json'))); r2 = json.load(open(os.path.join(T.HERE, f'{sp}_tests_r2.json')))
    rows = T.rows_of(sp, S, C, r2=True)
    none = T.compare(rows, {'plain': ([T.f_plain], ['-'])}, base=lambda r: [])
    y = np.array([r['y'] for r in rows]); b = T.ols(T.X_of(rows, T.f_plain), y)
    tot = np.array([sum(r['pts']) for r in rows])
    w = r2['weights'][str(cfg['live_k'])]
    slim = lambda res: {k: {'t': v['t'], 'd': v['d'], 'up': v['classes_up'], 'pass': v['pass'], 'rmse': v['rmse']} for k, v in res['forms'].items()}
    o = {'classes': [min(cfg['classes']), max(cfg['classes'])], 'n': r2['primary']['n'], 'nClasses': r2['primary']['classes'], 'map': r2['map'], 'k': cfg['live_k'],
         'base': r2['primary']['base_rmse'], 'plain': {'perPoint': round(float(b[-1]), 5), 't': none['forms']['plain']['t'], 'up': none['forms']['plain']['classes_up'], 'noneRmse': none['base_rmse'],
                                                       'p10': round(float(np.percentile(tot, 10)), 1), 'p90': round(float(np.percentile(tot, 90)), 1), 'top': round(float(np.percentile(tot, 99)), 1)},
         'forms': slim(r2['primary']), 'forward': {k: v for k, v in r2['forward'].items() if k != 'n'}, 'weights': w,
         'round1': {'n': r1['primary']['n'], 'base': r1['primary']['base_rmse'], 'forms': slim(r1['primary']), 'weights': r1['weights'][str(cfg['live_k'])]},
         'secondary': {k: {'n': v['n'], 'top': v['weights']['top'], 'depth': v['weights']['depth'], 't_diff': v['weights']['t_diff'],
                           'best': max(((f['t'], n) for n, f in v.get('forms', {}).items()), default=None)} for k, v in r2['secondary'].items()},
         'roster': {k.split(' ', 1)[1]: {'n': v['n'], 'classes': [v['classes'][0], v['classes'][-1]], 'top': v['weights']['top'], 'depth': v['weights']['depth'], 't_diff': v['weights']['t_diff'],
                                         'forms': v.get('forms')} for k, v in sens.items() if k.startswith(sp + ' ')}}
    if sp == 'cfb':
        o['position'] = {'match': sens['pos_match'], 't': sens['cfb_position']['t'], 'up': sens['cfb_position']['classes_up']}
        sd = float(np.std([v['pts'] for y_ in range(2012, 2026) for v in S[y_].values()])); o['ratingSd'] = round(sd, 2)
    else:
        r1rows = T.rows_of(sp, S, C)
        a = T.compare(r1rows, {'any': ([lambda r: [float(len(r['pts']) > 0)]], ['-'])})
        o['round1']['anyFlag'] = {'rmse': a['forms']['any']['rmse'], 't': a['forms']['any']['t']}
    out[sp] = o
stock = json.load(open(os.path.join(T.HERE, 'stock.json'))); conc = json.load(open(os.path.join(T.HERE, 'concave.json')))
import stock as K
for sp in ('cfb', 'cbb'):
    st = stock[sp]; k = str(T.CFG[sp]['live_k']); P, S, C = T.load(sp); rr = K.rows_of(sp, S, C)
    tot = np.array([sum(sum(c) for c in r['cl']) for r in rr])
    out[sp]['roster4'] = {'n': st['n'], 'seasons': [min(K.CFG[sp]['seasons']), max(K.CFG[sp]['seasons'])], 'nSeasons': st['seasons'], 'base': st['base'], 'plain': st['plain'],
                          'p10': round(float(np.percentile(tot, 10)), 1), 'p90': round(float(np.percentile(tot, 90)), 1),
                          'forms': {n: {'t': v['t'], 'up': v['classes_up'], 'pass': v['pass'], 'rmse': v['rmse'], 'fwd': st['forward'][n]['t']} for n, v in st['forms'].items()},
                          'weights': st['weights'][k], 'wins': st['wins']['weights'], 'nil': st['nil'], 'pre': st['pre']}
    out[sp]['bend'] = {d: {'t': conc[f'{sp} {d}']['bent_vs_plain']['t'], 'up': conc[f'{sp} {d}']['bent_vs_plain']['up'], 'forms': conc[f'{sp} {d}']['forms'], 'weights': conc[f'{sp} {d}']['weights']} for d in ('class', 'roster')}
r4 = json.load(open(os.path.join(T.HERE, 'round4.json')))
for sp in ('cfb', 'cbb'): out[sp]['round4'] = r4[sp]
out['cbb']['bend']['first'] = {k.split(', ')[1]: v for k, v in conc.items() if k.startswith('cbb first season')}
json.dump(out, open(os.path.join(T.ROOT, 'data', 'class_score_research.json'), 'w'), indent=1)

# ---- the Research card ----------------------------------------------------------------------------------------------
f, b = out['cfb']['roster4'], out['cbb']['roster']['all']
pt = lambda w, nm: {'x': nm, 'y': round(10 * w[0], 4), 'lo': round(10 * (w[0] - 1.96 * w[1]), 4), 'hi': round(10 * (w[0] + 1.96 * w[1]), 4)}
card = {'id': 'cfb-class-top-end-depth', 'sport': 'CFB', 'date': '2026-11-26', 'question': "Does a recruiting class's top end win more than its depth?",
        'answer': f"No. Point for point they are worth the same: CFB t = {f['weights']['t_diff']:.2f}, CBB t = {b['t_diff']:.2f}. The plain sum is not beaten.",
        'findings': [f"CFB, four classes on a roster: top 5 {10 * f['weights']['top'][0]:.3f} rating SD per 10 points, depth {10 * f['weights']['depth'][0]:.3f} (n={f['n']:,}).",
                     f"CFB class sum over no class score: t = {f['plain']['t']:.2f}, {f['plain']['up']}/{f['nSeasons']} seasons. No reweighting passes (best t = {max(v['t'] for v in f['forms'].values()):.2f}).",
                     f"CBB, returning and transfer value held fixed: top 2 {10 * b['top'][0]:.3f}, depth {10 * b['depth'][0]:.3f} per 10 points (n={b['n']:,}).",
                     f"CBB without the roster held fixed, depth reads {10 * out['cbb']['weights']['depth'][0]:+.3f}: a deep class follows a thin returning roster."],
        'method': "Program rating z (opponent-adjusted margin in CFB, net rating in CBB) on the class's top-end and depth FV points, with the ratings before signing, a three-season baseline and program level as controls. Forms that reweight the class (split, decay, cap, star premium, power x decay) were pre-registered and scored held out by class or season, t clustered by program.",
        'data': f"CFBD composite classes 2009-25 and cfbfastR results 2005-25; consensus-ranked CBB classes 2009-25 and program net ratings 2008-26. {f['n']:,} CFB program-seasons, {b['n']:,} CBB classes.",
        'n': int(f['n'] + b['n']), 'robust': True, 'interest': 4,
        'split_check': f"CFB NIL-era seasons: top 5 {10 * f['nil']['weights']['top'][0]:.3f}, depth {10 * f['nil']['weights']['depth'][0]:.3f}, t = {f['nil']['weights']['t_diff']:.2f} (n={f['nil']['n']}). Not distinguishable yet.",
        'auto': 'scripts/research/class_score_nov26/pack.py',
        'chart': {'type': 'bar', 'title': 'Rating SD per 10 class points', 'x_label': 'part of the class', 'y_label': 'rating SD per 10 points', 'y_fmt': 'num', 'ref': None, 'mark': None,
                  'series': [{'name': 'per 10 points', 'points': [pt(f['weights']['top'], 'CFB top 5'), pt(f['weights']['depth'], 'CFB depth'), pt(b['top'], 'CBB top 2'), pt(b['depth'], 'CBB depth')]}]}}
os.makedirs(os.path.join(T.ROOT, 'research', 'studies', 'cfb'), exist_ok=True)
json.dump(card, open(os.path.join(T.ROOT, 'research', 'studies', 'cfb', 'cfb-class-top-end-depth.json'), 'w'), indent=1, ensure_ascii=False)
for k in ('answer', 'findings', 'split_check'): print(card[k])
for sp in ('cfb', 'cbb'):
    o = out[sp]; print(sp, o['n'], 'plain', o['plain'], '\n  weights', o['weights']['top'], o['weights']['depth'], o['weights']['t_diff'], '\n  forms', {k: (v['t'], v['up'], v['pass']) for k, v in o['forms'].items()}, '\n  roster', {k: (v['n'], v['top'], v['depth'], v['t_diff']) for k, v in o['roster'].items()})
print(out['cfb']['position'], out['cfb']['ratingSd'], out['cbb']['round1']['anyFlag'])
