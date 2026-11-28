#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Recruit position projection, CFB and CBB: where a high school recruit plays in college, from his listed position,
height, weight and grade (CFB) or rank (CBB). Shown on the recruit boards and cards (Pos cell, odds in its hover).

    python3 scripts/recruit_pos.py          # apply the fit on file to the live classes -> data/recruit_pos.json
                                            # ("<class>|<name>": [label, hover, 1 when the label is his listed position])
    python3 scripts/recruit_pos.py --fit    # refit + held-out tests -> data/recruit_pos_fit.json (needs the caches below)
    python3 scripts/recruit_pos.py --test   # label rules

Truth: CFB = the position group on college rosters in years 2-4 (cfbfastR rosters by ESPN athlete id, share of seasons;
scripts/.cache/cfb_rosters/r<season>.csv, pulled when missing). CBB = Barttorvik's role, minutes-weighted over the first
two college seasons, on five spots (Combo G half PG half SG, PF/C half PF half C; scripts/.cache/cbb/bt).
Model: multinomial logit, L2 1, size terms within the listed position's family. Tests held out by class and walk forward
(scripts/research/recruit_pos_nov28/). A second spot is named when its chance is at least DUAL (by sport).
The projection is not an FV input: it failed as one in both sports (cfb_fv_test.py, cbb_fv_test.py, Nov 28)."""
import json, math, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RES = os.path.join(HERE, 'research', 'recruit_pos_nov28')
sys.path.insert(0, RES); sys.path.insert(0, HERE)
FIT = os.path.join(ROOT, 'data', 'recruit_pos_fit.json')
OUT = os.path.join(ROOT, 'data', 'recruit_pos.json')
DUAL = {'cfb': 0.30, 'cbb': 0.35}   # a second spot is named at this chance (CBB higher: a combo guard is half PG, half SG by truth)
# CBB: two spots side by side read as one hybrid label
CBB_PAIR = {('PG', 'SG'): 'G', ('SG', 'SF'): 'G/F', ('SF', 'PF'): 'F', ('PF', 'C'): 'PF/C'}
CFB_FAM = {'QB': 'QB', 'RB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'DL': 'DL', 'LB': 'LB', 'DB': 'DB', 'ST': 'ST'}
CFB_NAME = {'ST': 'K/P'}
# ESPN code -> roster group, for keeping the more exact high school code when the projection agrees with it
CFB_CODE_G = {'QB-DT': 'QB', 'QB-PP': 'QB', 'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE-Y': 'TE', 'TE-H': 'TE', 'TE': 'TE',
              'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'IOL': 'OL', 'DT': 'DL', 'DL': 'DL', 'DE': 'DL', 'EDGE': 'DL', 'OLB': 'LB',
              'ILB': 'LB', 'LB': 'LB', 'CB': 'DB', 'S': 'DB', 'K': 'ST', 'P': 'ST', 'LS': 'ST'}
CFB_SHORT = {'QB-DT': 'QB', 'QB-PP': 'QB', 'TE-Y': 'TE', 'TE-H': 'TE', 'DL': 'DT', 'OC': 'C'}


def pct(p): return f'{round(p * 100)}%'


def hover(code, probs):
    top = [f'{k} {pct(p)}' for k, p in probs if p >= .05][:3]
    return f'HS {code} · ' + ' · '.join(top)


def cfb_label(code, P, G):
    """P = chances over G. One group, or two when the second is at least DUAL. The high school code stands in for its
    own group (CB, S, DE, OT ...); ATH and a move to another group show the college group."""
    o = sorted(zip(G, P), key=lambda x: -x[1])
    nm = lambda g: CFB_SHORT.get(code, code) if CFB_CODE_G.get(code) == g else CFB_NAME.get(g, g)
    lab = nm(o[0][0]) + ('/' + nm(o[1][0]) if o[1][1] >= DUAL['cfb'] else '')
    return lab, hover(code, [(CFB_NAME.get(g, g), p) for g, p in o])


def cbb_label(code, P, S5):
    o = sorted(zip(S5, P), key=lambda x: -x[1])
    a, b = o[0][0], o[1][0]
    pair = tuple(sorted((a, b), key=S5.index))
    if o[1][1] >= DUAL['cbb'] and pair in CBB_PAIR: lab = CBB_PAIR[pair]
    else: lab = code if code == a else a
    return lab, hover(code, o)


def apply():
    import cfb_pos as F, cbb_pos as B
    fit = json.load(open(FIT)); out = {'asof': None, 'cfb': {}, 'cbb': {}}
    f = fit['cfb']; F.SZ.update(f['sz']); Bc = np.array(f['B'])
    d = json.load(open(os.path.join(ROOT, 'data', 'cfb_recruits.json'))); out['asof'] = d.get('asof')
    lists = [(d['next'], d['class'])] + [(x['year'], x['list']) for x in d.get('future', [])]
    for yr, L in lists:
        for r in L:
            code = r.get('pos')
            if code not in F.FAM: continue
            P = F.mnl.predict(np.array([F.feats(code, r.get('ht'), r.get('wt'), r.get('grade'))]), Bc)[0]
            lab, hv = cfb_label(code, P, f['G'])
            out['cfb'][f'{yr}|{r["name"]}'] = [lab, hv] + ([1] if lab == CFB_SHORT.get(code, code) else [])
    f = fit['cbb']; B.SZ.update(f['sz']); Bb = np.array(f['B'])
    d = json.load(open(os.path.join(ROOT, 'data', 'cbb_recruits.json')))
    for c in d['classes']:
        for r in c['list']:
            code = r.get('pos')
            if code not in B.FAM: continue
            ht = r.get('ht'); ht = B.D.inches(ht) if isinstance(ht, str) else ht
            P = B.mnl.predict(np.array([B.feats(code, ht, r.get('wt'), r.get('rk'))]), Bb)[0]
            lab, hv = cbb_label(code, P, f['S5'])
            out['cbb'][f'{c["year"]}|{r["name"]}'] = [lab, hv] + ([1] if lab == code else [])
    json.dump(out, open(OUT, 'w'), separators=(',', ':'), ensure_ascii=False)
    for s in ('cfb', 'cbb'):
        ch = sum(1 for v in out[s].values() if '/' in v[0] or v[0] in ('G', 'F'))
        print(s, len(out[s]), 'rows,', ch, 'hybrid')


def oof_check(P, Y, T):
    """held-out share of rows that get a second spot, and how often the truth is in the label"""
    two = np.sort(P, 1)[:, -2] >= T
    top = P.argmax(1); tru = Y.argmax(1); sec = np.argsort(P, 1)[:, -2]
    hit1 = float((top == tru)[~two].mean()); hit2 = float(((top == tru) | (sec == tru))[two].mean())
    return {'dualShare': round(float(two.mean()), 3), 'single': round(hit1, 3), 'dual': round(hit2, 3)}


def refit():
    import cfb_pos as F, cbb_pos as B, mnl
    os.makedirs(F.ROS, exist_ok=True)
    for y in range(2014, 2026):
        p = os.path.join(F.ROS, f'r{y}.csv')
        if not os.path.exists(p):
            os.system(f'curl -s -m 120 -o {p} https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_{y}.csv')
    res = {}
    t = lambda v: round(float(np.mean(v) / (np.std(v, ddof=1) / math.sqrt(len(v)))), 2)
    # CFB
    rows = [r for r in F.load() if 2014 <= r['c'] <= 2025]
    hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]; gs = [r['grade'] for r in rows if r['grade']]
    F.SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)), gr=float(np.mean(gs)), gs=float(np.std(gs)))
    ev = [r for r in rows if r['c'] <= 2024]
    c = np.array([r['c'] for r in ev]); Y = np.array([r['y'] for r in ev]); ath = np.array([r['code'] == 'ATH' for r in ev])
    o = {}
    for nm, mk in (('listed', lambda r: F.feats(r['code'], r['ht'], r['wt'], r['grade'], size=False, gr=False)),
                   ('model', lambda r: F.feats(r['code'], r['ht'], r['wt'], r['grade']))):
        o[nm] = F.run(ev, mk, 1.0)
    ll0, ll1, P1 = o['listed'][0], o['model'][0], o['model'][1]
    ks = sorted(set(c)); d = [ll0[c == k].mean() - ll1[c == k].mean() for k in ks]; da = [ll0[(c == k) & ath].mean() - ll1[(c == k) & ath].mean() for k in ks]
    P0 = o['listed'][1]
    res['cfb'] = {'n': len(ev), 'ath': int(ath.sum()), 'classes': [int(ks[0]), int(ks[-1])], 'll': [round(float(ll0.mean()), 4), round(float(ll1.mean()), 4)], 't': t(d), 'wins': int(sum(x > 0 for x in d)),
                  'acc': [round(float((P0.argmax(1) == Y.argmax(1)).mean()), 3), round(float((P1.argmax(1) == Y.argmax(1)).mean()), 3)],
                  'athLl': [round(float(ll0[ath].mean()), 4), round(float(ll1[ath].mean()), 4)], 'athT': t(da), 'athWins': int(sum(x > 0 for x in da)),
                  'athAcc': [round(float((P0.argmax(1) == Y.argmax(1))[ath].mean()), 3), round(float((P1.argmax(1) == Y.argmax(1))[ath].mean()), 3)],
                  'label': oof_check(P1, Y, DUAL['cfb'])}
    X = np.array([F.feats(r['code'], r['ht'], r['wt'], r['grade']) for r in rows])
    res['cfb'].update(G=F.G, sz=dict(F.SZ), B=np.round(mnl.fit(X, np.array([r['y'] for r in rows]), 1.0), 5).tolist())
    # CBB
    rows = B.load()
    hs = [r['ht'] for r in rows if r['ht']]; ws = [r['wt'] for r in rows if r['wt']]
    B.SZ.update(ht=float(np.mean(hs)), hs=float(np.std(hs)), wt=float(np.mean(ws)), ws=float(np.std(ws)), lr=float(np.mean([math.log(r['rk']) for r in rows if r['rk']])))
    c = np.array([r['c'] for r in rows]); Y = np.array([r['y'] for r in rows]); ks = sorted(set(c)); o = {}
    for nm, mk in (('listed', lambda r: B.feats(r['code'], r['ht'], r['wt'], r['rk'], False, False)), ('model', lambda r: B.feats(r['code'], r['ht'], r['wt'], r['rk']))):
        Xm = np.array([mk(r) for r in rows]); P = np.zeros_like(Y)
        for k in ks: P[c == k] = mnl.predict(Xm[c == k], mnl.fit(Xm[c != k], Y[c != k], 1.0))
        o[nm] = (mnl.logloss(P, Y), P)
    ll0, ll1, P1 = o['listed'][0], o['model'][0], o['model'][1]; d = [ll0[c == k].mean() - ll1[c == k].mean() for k in ks]
    res['cbb'] = {'n': len(rows), 'classes': [int(ks[0]), int(ks[-1])], 'll': [round(float(ll0.mean()), 4), round(float(ll1.mean()), 4)], 't': t(d), 'wins': int(sum(x > 0 for x in d)),
                  'acc': [round(float((o['listed'][1].argmax(1) == Y.argmax(1)).mean()), 3), round(float((P1.argmax(1) == Y.argmax(1)).mean()), 3)],
                  'label': oof_check(P1, Y, DUAL['cbb'])}
    X = np.array([B.feats(r['code'], r['ht'], r['wt'], r['rk']) for r in rows])
    res['cbb'].update(S5=B.S5, sz=dict(B.SZ), B=np.round(mnl.fit(X, Y, 1.0), 5).tolist())
    for s in ('cfb', 'cbb'):
        p = os.path.join(RES, f'{s}_fv_test.json')
        if os.path.exists(p): res[s]['fvTest'] = json.load(open(p))
    res['dual'] = DUAL
    json.dump(res, open(FIT, 'w'), indent=1)
    print(json.dumps({s: {k: v for k, v in res[s].items() if k not in ('B', 'sz')} for s in ('cfb', 'cbb')}, indent=1))


def test():
    G = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'DB', 'ST']
    p = lambda **k: [k.get(g, 0) for g in G]
    assert cfb_label('ATH', p(DB=.62, WR=.3, RB=.08), G)[0] == 'DB/WR'
    assert cfb_label('ATH', p(DB=.8, WR=.15, RB=.05), G)[0] == 'DB'
    assert cfb_label('CB', p(DB=.9, WR=.1), G)[0] == 'CB'
    assert cfb_label('S', p(DB=.6, LB=.4), G)[0] == 'S/LB'
    assert cfb_label('QB-DT', p(QB=.9, WR=.1), G)[0] == 'QB'
    assert cfb_label('DE', p(LB=.55, DL=.45), G)[0] == 'LB/DE'
    S5 = ['PG', 'SG', 'SF', 'PF', 'C']
    assert cbb_label('PF', [0, 0, .1, .5, .4], S5)[0] == 'PF/C'
    assert cbb_label('SG', [.05, .5, .4, .05, 0], S5)[0] == 'G/F'
    assert cbb_label('CG', [.48, .47, .05, 0, 0], S5)[0] == 'G'
    assert cbb_label('SF', [0, .1, .8, .1, 0], S5)[0] == 'SF'
    assert cbb_label('PG', [.35, .05, .6, 0, 0], S5)[0] == 'SF'
    assert hover('ATH', [('DB', .62), ('WR', .3), ('RB', .03)]) == 'HS ATH · DB 62% · WR 30%'
    print('ok')


if __name__ == '__main__':
    if '--test' in sys.argv: test()
    elif '--fit' in sys.argv: refit(); apply()
    else: apply()
