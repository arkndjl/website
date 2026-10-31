#!/usr/bin/env python3
"""Which schools develop talent? Recruit outcome over what his recruiting rating predicted, by school (research, Oct 31 2026).

    python3 scripts/school_dev.py cbb     # scripts/data/cbb_recruit_hist.json.gz (On3 classes) -> scripts/data/school_dev/cbb.json
    python3 scripts/school_dev.py cfb     # scripts/.cache/dev/cfb_recruits.json (cfb_recruit_retarget.dataset) -> scripts/data/school_dev/cfb.json
    python3 scripts/school_dev.py cbb-coach   # the CBB run grouped by head coach (Sports Reference, 2014 on)
    python3 scripts/school_dev.py site    # data/school_dev.json for the Development tabs (after the three runs)

Delta = realized outcome - E[outcome | recruiting rating, class, position]. E is fit leaving the recruit's own school
out, so a school's recruits never set their own baseline (Kentucky and Duke would otherwise define what a top-10
recruit is worth). Recruits count for the school they signed with, whatever happened next (intent to treat): a
transfer out still counts for the school that signed him, and playing time is not conditioned on, because both are
outcomes of the school's development as much as causes of it. Transfers in are not in the sample (they were not HS
recruits of that school).

School effect = empirical Bayes: u = sum(delta) / (n + s2 / tau2), with tau2 the between-school variance left after
sampling noise (method of moments on the training classes).

Out-of-sample tests (does a school's past delta predict its future recruits' deltas?):
  rolling: for each class t, effects from classes < t only, scored on class t
  split:   effects from the first half of the classes, scored on the second half
  halves:  split-half reliability (odd vs even classes)
Scored as the slope of the held-out delta on the prior effect (t clustered by school; a calibrated effect has slope 1),
the held-out MSE change with the effect used as is (slope fixed at 1, nothing fit on the test rows), and classes won.
Run raw and net of program strength at signing (is it development, or just being a good program?).

Outcomes:
  cbb  fv   realized NBA FV tier (scripts/cbb_link.py TIERS; 20 = never reached the NBA), classes 2009-2020
  cbb  col  peak college value in his first four seasons, any school: minutes share x (BPM + 3)+, classes 2009-2023
  cfb  fv   NFL outcome on the FV scale (mean of AV a season and draft capital, as cfb_recruit_retarget), classes 2011-19
"""
import gzip
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, 'scripts', 'data', 'school_dev')   # research output (Hugo does not load it)
FIXK = None   # a fixed shrinkage (prior weight in recruits) for the sensitivity runs; None = empirical Bayes
KNOTS_RK = [math.log(k) for k in (3, 8, 20, 50, 120, 250)]


def clean(o):
    """NaN -> null (a bare NaN breaks JSON readers)"""
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list): return [clean(v) for v in o]
    if isinstance(o, float) and o != o: return None
    return o


def hinge(x, knots):
    return [x] + [max(0.0, x - k) for k in knots]


# ---- data -------------------------------------------------------------------------------------------------------
def cbb_coaches():
    """(season, Barttorvik team) -> head coach (Sports Reference id), seasons 2014 on, as cbb_coach_prior.py"""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    import cbb_games as C
    import cbb_roster as RO
    raw = RO.coach_feats(RO.load_coaches(), json.load(open(C.TPRIOR)), raw=True)
    return {(s, t): v['coach'] for s, d in raw.items() for t, v in d.items()}


def cbb_rows(by_coach=False):
    CO = cbb_coaches() if by_coach else {}
    D = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cbb_recruit_hist.json.gz')))
    T = D['teams']
    rows = []
    for r in D['recruits']:
        c = r.get('college')
        if not c or not r.get('rk'):
            continue
        y1 = c['y1']
        col = r.get('col') or {}
        peak = 0.0; bw = bs = 0.0
        for k, (g, mn, bpm) in col.items():
            if y1 <= int(k) <= y1 + 3:
                peak = max(peak, mn / 100 * max(0.0, bpm + 3))
                w = g * mn / 100; bw += w; bs += w * bpm
        prog = T.get(str(y1 - 1), {}).get(c['team'])
        y = {}
        if r['cls'] <= 2020: y['fv'] = float(r['rfv'])
        if y1 + 3 <= 2026: y['col'] = peak
        # rate only (takes playing-time opportunity out): minutes-weighted BPM over his first four seasons, 100+
        # game-minutes-share units (about 5 full games) to count
        if y1 + 3 <= 2026 and bw >= 5: y['bpm'] = bs / bw
        if by_coach:
            co = CO.get((y1, c['team']))
            if not co: continue
        rows.append({'school': CO[(y1, c['team'])] if by_coach else c['team'], 'team': c['team'], 'cls': r['cls'], 'grp': 'all', 'b': hinge(math.log(r['rk']), KNOTS_RK),
                     'prog': prog, 'y': y, 'name': r['name'], 'rk': r['rk']})
    return rows


def cfb_rows():
    data = json.load(open(os.path.join(ROOT, 'scripts', '.cache', 'dev', 'cfb_recruits.json')))
    rows = []
    for r in data:
        gr = r.get('grade') or 0
        comp = r.get('comp') or 0
        # rating: the 247 composite where it has one, else ESPN's grade on the composite's scale (fit below)
        rows.append({'school': r['team'], 'cls': r['cls'] if r.get('cls') else r.get('year'), 'grp': r['g'], 'gr': gr, 'comp': comp,
                     'prog': r.get('eloZ'), 'level': r.get('level'), 'y': {'fv': float(r['rfv']), 'dr': 1.0 if r['drafted'] else 0.0}, 'name': r['name'], 'tid': r.get('tid')})
    # ESPN grade -> composite scale on rows with both (linear), unranked (grade < 60) at the floor
    both = [(r['gr'], r['comp']) for r in rows if r['gr'] >= 60 and r['comp'] > 0]
    a, b = np.polyfit([x for x, _ in both], [y for _, y in both], 1)
    for r in rows:
        x = r['comp'] if r['comp'] > 0 else (a * r['gr'] + b if r['gr'] >= 60 else None)
        r['rating'] = x
    floor = min(r['rating'] for r in rows if r['rating'] is not None) - 0.01
    qs = np.quantile([r['rating'] for r in rows if r['rating'] is not None], [.5, .75, .9, .96, .99, .997])
    for r in rows:
        x = r['rating'] if r['rating'] is not None else floor
        r['b'] = hinge(x, list(qs)) + [1.0 if r['rating'] is None else 0.0]
    return rows


# ---- expectation, leave one school out ---------------------------------------------------------------------------
def design(rows):
    cls = sorted({r['cls'] for r in rows}); grp = sorted({r['grp'] for r in rows})
    X = []
    for r in rows:
        v = [1.0] + list(r['b']) + [1.0 if r['cls'] == c else 0.0 for c in cls[1:]] + [1.0 if r['grp'] == g else 0.0 for g in grp[1:]]
        # position x rating slope (NFL value by position differs in steepness)
        if len(grp) > 1: v += [r['b'][0] * (1.0 if r['grp'] == g else 0.0) for g in grp[1:]]
        X.append(v)
    return np.array(X)


def loso_expect(rows, key, lam=1e-3):
    ix = [i for i, r in enumerate(rows) if key in r['y']]
    X = design([rows[i] for i in ix]); y = np.array([rows[i]['y'][key] for i in ix])
    XtX = X.T @ X + lam * np.eye(X.shape[1]); Xty = X.T @ y
    bys = defaultdict(list)
    for j, i in enumerate(ix): bys[rows[i]['school']].append(j)
    E = np.zeros(len(ix))
    for s, js in bys.items():
        Xs = X[js]; w = np.linalg.solve(XtX - Xs.T @ Xs, Xty - Xs.T @ y[js]); E[js] = Xs @ w
    # variance of the delta by rating: squared deltas on the rating basis (class and position terms left out)
    nb = 1 + len(rows[ix[0]]['b'])
    Xb = X[:, :nb]; d2 = (y - E) ** 2
    wv = np.linalg.lstsq(Xb, d2, rcond=None)[0]; v = np.maximum(Xb @ wv, 0.05 * d2.mean())
    for j, i in enumerate(ix):
        rows[i].setdefault('E', {})[key] = float(E[j]); rows[i].setdefault('d', {})[key] = float(y[j] - E[j])
        rows[i].setdefault('v', {})[key] = float(v[j])
    return ix


# ---- empirical Bayes school effects --------------------------------------------------------------------------------
def eb(rows, key, dkey='d'):
    """precision-weighted school means (the delta's variance grows with the rating: a top-10 recruit's outcome is far
    noisier than a No. 200's), DerSimonian-Laird tau2, shrunk toward 0: u = m x tau2 / (tau2 + V)"""
    by = defaultdict(lambda: [0.0, 0.0, 0])
    for r in rows:
        w = 1 / r['v'][key]; g = by[r['school']]; g[0] += w * r[dkey][key]; g[1] += w; g[2] += 1
    S = list(by); W = np.array([by[s][1] for s in S]); m = np.array([by[s][0] / by[s][1] for s in S])
    mu = float(W @ m / W.sum())
    Q = float(W @ (m - mu) ** 2)
    tau2raw = (Q - (len(S) - 1)) / (W.sum() - (W ** 2).sum() / W.sum())
    vbar = float(np.mean([r['v'][key] for r in rows]))
    tau2 = vbar / FIXK if FIXK else max(1e-9, tau2raw)
    eff = {s: {'u': float(m[i] * tau2 / (tau2 + 1 / W[i])), 'n': by[s][2], 'raw': float(m[i]), 'se': float(math.sqrt(1 / (W[i] + 1 / tau2)))}
           for i, s in enumerate(S)}
    return eff, {'sd': math.sqrt(vbar), 'tau2': tau2, 'tau': math.sqrt(tau2), 'tau2raw': float(tau2raw), 'k': vbar / tau2, 'Q': Q, 'df': len(S) - 1}


def score(test, eff, key, dkey='d'):
    """held-out delta on the prior effect: slope (t by school cluster), MSE change at slope 1, rows"""
    e = np.array([r[dkey][key] for r in test]); u = np.array([eff.get(r['school'], {'u': 0.0})['u'] for r in test])
    sch = [r['school'] for r in test]
    ec = e - e.mean()
    b = float(u @ ec / (u @ u)) if u @ u > 0 else 0.0
    res = ec - b * u
    g = defaultdict(lambda: [0.0, 0.0])
    for ui, ri, s in zip(u, res, sch): g[s][0] += ui * ri
    meat = sum(v[0] ** 2 for v in g.values())
    se = math.sqrt(meat) / (u @ u) if u @ u > 0 else float('inf')
    mse0 = float(np.mean(ec ** 2)); mse1 = float(np.mean((ec - u) ** 2))
    return {'n': len(test), 'slope': round(b, 3), 't': round(b / se, 2) if se > 0 else 0.0,
            'mseGainPct': round(100 * (mse0 - mse1) / mse0, 3) if mse0 > 0 else 0.0, 'r': round(float(np.corrcoef(u, e)[0, 1]), 4) if u.std() > 0 else 0.0}


def net_of_program(rows, key):
    """delta net of program strength at signing (linear + square, fit on all rows: a nuisance control)"""
    R = [r for r in rows if key in r.get('d', {})]
    p = np.array([r['prog'] if r['prog'] is not None else 0.0 for r in R]); miss = np.array([r['prog'] is None for r in R], float)
    X = np.column_stack([np.ones(len(R)), p, p ** 2, miss]); y = np.array([r['d'][key] for r in R])
    w = np.linalg.lstsq(X, y, rcond=None)[0]
    for r, v in zip(R, y - X @ w): r.setdefault('dn', {})[key] = float(v)
    return [round(float(x), 4) for x in w]


def tau_ci(rows, key, dkey='d', B=300, seed=7):
    """bootstrap over schools: 5/50/95th percentile of tau (SD of true school effects; sqrt of the untruncated
    moment estimate, negative variance read as 0)"""
    by = defaultdict(list)
    for r in rows:
        if key in r.get(dkey, {}): by[r['school']].append(r)
    S = list(by); rng = np.random.default_rng(seed); taus = []
    for _ in range(B):
        pick = rng.integers(0, len(S), len(S)); R = []
        for j, i in enumerate(pick): R += [{'school': f'{S[i]}#{j}', dkey: r[dkey], 'v': r['v']} for r in by[S[i]]]
        taus.append(eb(R, key, dkey)[1]['tau2raw'])
    return [round(math.sqrt(max(0.0, float(x))), 3) for x in np.percentile(taus, [5, 50, 95])]


def tests(rows, key, dkey, classes):
    R = [r for r in rows if key in r.get(dkey, {})]
    out = {}
    # rolling origin: effects from classes < t, scored on class t (from the 4th class on)
    roll, wins, pooled_e, pooled_u, pooled_s = [], 0, [], [], []
    per = []
    for t in classes[3:]:
        tr = [r for r in R if r['cls'] < t]; te = [r for r in R if r['cls'] == t]
        if not te: continue
        eff, _ = eb(tr, key, dkey)
        sc = score(te, eff, key, dkey); per.append({'cls': t, **sc}); wins += sc['mseGainPct'] > 0
        for r in te: pooled_e.append(r[dkey][key]); pooled_u.append(eff.get(r['school'], {'u': 0.0})['u']); pooled_s.append(r['school'])
    # pooled score: each row carries its own prior effect, so score by hand
    e = np.array(pooled_e); u = np.array(pooled_u); ec = e - e.mean()
    b = float(u @ ec / (u @ u)); res = ec - b * u
    g = defaultdict(float)
    for ui, ri, s in zip(u, res, pooled_s): g[s] += ui * ri
    se = math.sqrt(sum(v ** 2 for v in g.values())) / (u @ u)
    out['rolling'] = {'n': len(e), 'slope': round(b, 3), 't': round(b / se, 2), 'mseGainPct': round(100 * (np.mean(ec ** 2) - np.mean((ec - u) ** 2)) / np.mean(ec ** 2), 3),
                      'r': round(float(np.corrcoef(u, e)[0, 1]), 4), 'classesWon': f'{wins}/{len(per)}', 'byClass': per}
    half = classes[len(classes) // 2]
    eff, hp = eb([r for r in R if r['cls'] < half], key, dkey)
    out['split'] = {'train': f'{classes[0]}-{half - 1}', 'test': f'{half}-{classes[-1]}', **score([r for r in R if r['cls'] >= half], eff, key, dkey), 'hyper': hp}
    # split-half reliability, odd vs even classes, schools with 15+ recruits on each side
    eo, _ = eb([r for r in R if r['cls'] % 2], key, dkey); ee, _ = eb([r for r in R if not r['cls'] % 2], key, dkey)
    both = [s for s in eo if s in ee and eo[s]['n'] >= 15 and ee[s]['n'] >= 15]
    a = np.array([eo[s]['raw'] for s in both]); c = np.array([ee[s]['raw'] for s in both])
    rr = float(np.corrcoef(a, c)[0, 1]) if len(both) > 3 else float('nan')
    se_r = (1 - rr ** 2) / math.sqrt(max(1, len(both) - 2)) if len(both) > 3 else float('nan')
    out['halves'] = {'schools': len(both), 'r': round(rr, 3), 't': round(rr / se_r, 2) if se_r == se_r else None, 'spearmanBrown': round(2 * rr / (1 + rr), 3) if rr == rr else None}
    return out


def main():
    sport = sys.argv[1] if len(sys.argv) > 1 else 'cbb'
    rows = cbb_rows(sport == 'cbb-coach') if sport.startswith('cbb') else cfb_rows()
    keys = ['fv', 'col', 'bpm'] if sport.startswith('cbb') else ['fv', 'dr']
    res = {'asof': __import__('datetime').date.today().isoformat(), 'sport': sport, 'outcomes': {}}
    for key in keys:
        loso_expect(rows, key)
        R = [r for r in rows if key in r['y']]
        classes = sorted({r['cls'] for r in R})
        pw = net_of_program(rows, key)
        out = {'n': len(R), 'classes': [classes[0], classes[-1]], 'schools': len({r['school'] for r in R}), 'programCoef': pw}
        global FIXK
        for dkey in ('d', 'dn'):
            nm = 'raw' if dkey == 'd' else 'netProgram'
            FIXK = None; out[nm] = tests(rows, key, dkey, classes)
            out[nm]['tauCI'] = tau_ci(rows, key, dkey)
            for kf in (25, 75):
                FIXK = kf; t2 = tests(rows, key, dkey, classes)
                out[nm][f'k{kf}'] = {'rolling': {a: b for a, b in t2['rolling'].items() if a != 'byClass'}, 'split': {a: b for a, b in t2['split'].items() if a != 'hyper'}}
        FIXK = None
        eff, hp = eb(R, key)
        effn, hpn = eb(R, key, 'dn')
        top = sorted(((v['u'], s, v['n'], v['se'], effn[s]['u']) for s, v in eff.items() if v['n'] >= 8), reverse=True)
        out['hyper'] = hp; out['hyperNet'] = hpn
        sy, se_, tids = defaultdict(float), defaultdict(float), defaultdict(lambda: defaultdict(int))
        for r in R:
            sy[r['school']] += r['y'][key]; se_[r['school']] += r['E'][key]; tids[r['school']][r.get('tid') or r.get('team')] += 1
        out['schoolsAll'] = [{'school': s, 'u': round(u, 3), 'n': n, 'se': round(se, 3), 'uNet': round(un, 3), 'sumY': round(sy[s], 2), 'sumE': round(se_[s], 2),
                              'id': max(tids[s], key=tids[s].get)} for u, s, n, se, un in top]
        res['outcomes'][key] = out
        o = {k: v for k, v in out.items() if k not in ('schoolsAll',)}
        for dk in ('raw', 'netProgram'):
            o[dk] = {k: ({kk: vv for kk, vv in v.items() if kk != 'byClass'} if isinstance(v, dict) else v) for k, v in out[dk].items()}
        print(key, json.dumps(o, indent=1))
        print('top', [(x['school'], x['u'], x['n']) for x in out['schoolsAll'][:12]])
        print('bottom', [(x['school'], x['u'], x['n']) for x in out['schoolsAll'][-8:]])
    json.dump(clean(res), open(os.path.join(RES, f'{sport}.json'), 'w'), indent=1)




# ---- site table -----------------------------------------------------------------------------------------------------
def coach_name(slug):
    w = slug.rsplit('-', 1)[0].split('-')
    fix = lambda x: x.upper() if len(x) == 2 and not set(x) & set('aeiouy') else ('Mc' + x[2:].capitalize()) if x.startswith('mc') and len(x) > 3 else x.capitalize()
    return ' '.join(fix(x) for x in w)


def site():
    """data/school_dev.json for the Development tabs: CFB on the NFL FV delta, CBB on the college BPM delta (the NBA FV
    delta failed), with the CBB head coach's own BPM delta (any school, 2014 on)."""
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    out = {'asof': __import__('datetime').date.today().isoformat()}
    cf = json.load(open(os.path.join(RES, 'cfb.json')))['outcomes']
    T = {t['tid']: t for t in json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']}
    dr = {x['school']: x for x in cf['dr']['schoolsAll']}
    rows = []
    for x in cf['fv']['schoolsAll']:
        t = T.get(str(x['id']))
        if not t: continue   # FBS teams on the board only
        d = dr.get(x['school'], {})
        rows.append({'id': str(x['id']), 't': t['team'], 'logo': t.get('logo'), 'conf': t.get('conf'), 'dev': round(x['u'], 2), 'se': round(x['se'], 2),
                     'net': round(x['uNet'], 2), 'raw': round((x['sumY'] - x['sumE']) / x['n'], 2), 'n': x['n'],
                     'dr': int(round(d.get('sumY', 0))), 'xdr': round(d.get('sumE', 0), 1)})
    rows.sort(key=lambda r: -r['dev'])
    for i, r in enumerate(rows): r['rk'] = i + 1
    t = cf['fv']
    out['cfb'] = {'classes': t['classes'], 'n': t['n'], 'tau': round(t['hyper']['tau'], 2), 'k': round(t['hyper']['k']),
                  'test': {'rolling': {k: t['raw']['rolling'][k] for k in ('t', 'slope', 'classesWon')}, 'split': {k: t['raw']['split'][k] for k in ('t', 'slope')},
                           'halves': t['raw']['halves']['r'], 'netRolling': t['netProgram']['rolling']['t']}, 'rows': rows}
    cb = json.load(open(os.path.join(RES, 'cbb.json')))['outcomes']
    cc = json.load(open(os.path.join(RES, 'cbb-coach.json')))['outcomes']['bpm']
    ce = {x['school']: x for x in cc['schoolsAll']}
    import cbb_games as C
    bt = C.bt_map(C.load_hist())
    idof = {}
    for i, n in bt.items(): idof.setdefault(n, i)
    P = {p['id']: p for p in json.load(open(os.path.join(ROOT, 'data', 'cbb_games.json')))['power']}
    CO = cbb_coaches(); last = max(s for s, _ in CO)
    rows = []
    for x in cb['bpm']['schoolsAll']:
        i = idof.get(x['school']); p = P.get(i)
        if not p: continue
        co = CO.get((last, x['school'])); c = ce.get(co, {}) if co else {}
        rows.append({'id': i, 't': p['t'], 'logo': p.get('logo'), 'conf': p.get('conf'), 'dev': round(x['u'], 2), 'se': round(x['se'], 2),
                     'net': round(x['uNet'], 2), 'raw': round((x['sumY'] - x['sumE']) / x['n'], 2), 'n': x['n'],
                     'coach': coach_name(co) if co else None, 'cdev': round(c['u'], 2) if c else None, 'cse': round(c['se'], 2) if c else None, 'cn': c.get('n')})
    rows.sort(key=lambda r: -r['dev'])
    for i, r in enumerate(rows): r['rk'] = i + 1
    t = cb['bpm']
    out['cbb'] = {'classes': t['classes'], 'n': t['n'], 'tau': round(t['hyper']['tau'], 2), 'k': round(t['hyper']['k']), 'coachTau': round(cc['hyper']['tau'], 2),
                  'test': {'rolling': {k: t['raw']['rolling'][k] for k in ('t', 'slope', 'classesWon')}, 'split': {k: t['raw']['split'][k] for k in ('t', 'slope')},
                           'coachSplit': {k: cc['raw']['split'][k] for k in ('t', 'slope')}, 'coachNetSplit': cc['netProgram']['split']['t']},
                  'nbaFail': {'Q': round(cb['fv']['hyper']['Q'], 1), 'df': cb['fv']['hyper']['df'], 'tauHi': cb['fv']['raw']['tauCI'][2]}, 'rows': rows}
    json.dump(out, open(os.path.join(ROOT, 'data', 'school_dev.json'), 'w'), separators=(',', ':'))
    print('cfb', len(out['cfb']['rows']), 'cbb', len(out['cbb']['rows']))


if __name__ == '__main__':
    site() if sys.argv[1:2] == ['site'] else main()
