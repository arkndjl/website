#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Hockey prospects: frame (height, weight, BMI) as FV drivers, Nov 3 2026 (Noah: "test height/weight/BMI/similar frame
measurements as FV drivers ... positionally adjusted and weighted correctly"; ht/wt from several sources combined by
reliability, official measurements weighted highest).

    python3 scripts/research/frame_nov03/hockey_frame.py --pull   # Central Scouting lists 2008-19 + CHL seasons (HockeyTech)
    python3 scripts/research/frame_nov03/hockey_frame.py          # tests -> <out dir>/hockey_frame.json

Sources per pick (all pre-draft except where checked):
  nhl   the NHL draft record's height / weight (scripts/data/hockey_rows.json.gz; NHL landing page where the record is blank)
  css   NHL Central Scouting's final list that spring (api-web.nhle.com draft/rankings/<y>/<cat>; combine-measured for invitees)
  chl   HockeyTech's CHL listing on the draft-year season line (OHL/WHL/QMJHL), checked for post-draft updates
Combined ("best"): a precision-weighted mean of the sources a pick has, each source's error variance from the triad
  covariance identity (three measures of one quantity: var(e_i) = var(x_i) - cov(x_i,x_j) cov(x_i,x_k) / cov(x_j,x_k)),
  shrunk to his position's mean with the position's true-score variance (empirical Bayes).
Position: the position he projects to, from the draft listing: F / D / G, and C / W / D / G. Each frame input is z-scored
  within that position (mean, sd over 2008-19 picks); BMI = 703 wt / ht^2.
Tests: on top of the live kept draft model (data/hockey_fit.json), the board's gate: class-out (12 classes) t >= 2 and
  8 of 12, top 64 picks out-of-class MSE not worse and Spearman not lower, forward (fit 2008-15, grade 2016-19) MSE,
  top-64 MSE and Spearman not worse (scripts/hockey_fv_drivers.checks). Stages 1-4 the same on the live stage models.
  One row per pick per model, so the class folds cluster by player. Every candidate counted for Holm.
"""
import gzip
import json
import math
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
UA = 'arkboard-research/1.0 (+https://arkndjl.net)'
import nhl_data as D  # noqa: E402
D.UA = UA
import hockey_prospects as H  # noqa: E402
import hockey_fv_drivers as HD  # noqa: E402
import names as NM  # noqa: E402
import harness as HS  # noqa: E402

CSSD = os.path.join(H.CACHE, 'css_full')
CHLD = HD.CHLD
OUTD = os.environ.get('FRAME_OUT') or '/mnt/project-files/fv/frame-nov03/hockey/'


def get(u):
    for _ in range(4):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=90).read())
        except Exception:
            pass
    return None


def pull():
    os.makedirs(CSSD, exist_ok=True); os.makedirs(CHLD, exist_ok=True)

    def one(yc):
        y, c = yc
        fn = os.path.join(CSSD, f'{y}_{c}.json')
        if not os.path.exists(fn):
            j = get(f'https://api-web.nhle.com/v1/draft/rankings/{y}/{c}') or {}
            json.dump(j.get('rankings') or [], open(fn, 'w'))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, [(y, c) for y in range(2008, 2027) for c in (1, 2, 3, 4)]))
    jobs = []
    for c, k in HD.HTKEY.items():
        for s in ((get(HD.HT % (k, c) + '&view=seasons') or {}).get('SiteKit') or {}).get('Seasons') or []:
            m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
            if m and 2006 <= int(m.group(1)) <= 2025:
                jobs.append((c, k, s['season_id'], int(m.group(1)) + 1))

    def season(j):
        c, k, sid, yr = j
        fn = os.path.join(CHLD, f'{c}_{yr}.json')
        if not os.path.exists(fn):
            d = get(HD.HT % (k, c) + f'&view=statviewtype&type=topscorers&season_id={sid}&first=0&limit=3000&stat=all&order_direction=')
            if d:
                json.dump(d['SiteKit'].get('Statviewtype'), open(fn, 'w'))
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(season, jobs))
    print('css', len(os.listdir(CSSD)), 'chl', len(os.listdir(CHLD)))


# -- measurements ------------------------------------------------------------------------------------------------
def ht_in(s):
    """HockeyTech heights: '6.02', 6'2, 6'02" (feet, inches)"""
    m = re.match(r'^(\d)[.\'](\d{1,2})"?$', str(s or '').strip())
    return int(m.group(1)) * 12 + int(m.group(2)) if m and int(m.group(2)) < 12 else None


def num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def css_lists():
    out = {}
    for fn in os.listdir(CSSD):
        y = int(fn.split('_')[0])
        for x in json.load(open(os.path.join(CSSD, fn))):
            out.setdefault(y, []).append({'name': f"{x.get('firstName', '')} {x.get('lastName', '')}".strip(),
                                          'birth': x.get('birthDate'), 'ht': num(x.get('heightInInches')),
                                          'wt': num(x.get('weightInPounds'))})
    return out


def chl_lists():
    import datetime as dt
    out = {}
    for fn in os.listdir(CHLD):
        c, yr = fn[:-5].split('_')
        for p in json.load(open(os.path.join(CHLD, fn))) or []:
            try:
                b = dt.datetime.strptime(p.get('birthdate') or '', '%b %d, %Y').date().isoformat()
            except ValueError:
                continue
            nm = p.get('name') or ''
            if ', ' in nm:
                a, _, bb = nm.partition(', '); nm = f'{bb} {a}'
            out.setdefault((int(yr), b), []).append({'name': nm, 'ht': ht_in(p.get('height')), 'wt': num(p.get('weight'))})
    return out


def attach(rows):
    CS, CH = css_lists(), chl_lists()
    for r in rows:
        r['m'] = {'nhl': {'ht': num(r.get('ht')), 'wt': num(r.get('wt'))}}
        c = [x for x in CS.get(r['year'], []) if NM.same(x['name'], r['name']) and (not r.get('birth') or not x['birth'] or x['birth'] == r['birth'])]
        if c:
            r['m']['css'] = {'ht': c[0]['ht'], 'wt': c[0]['wt']}
        if r.get('birth'):
            q = [x for x in CH.get((r['year'], r['birth']), []) if NM.same(x['name'], r['name'])]
            if q:
                r['m']['chl'] = {'ht': q[0]['ht'], 'wt': q[0]['wt']}


def triad(rows, k, srcs=('nhl', 'css', 'chl')):
    """error variance of each source's measure k (in, lb) from rows with all three"""
    X = np.array([[r['m'][s][k] for s in srcs] for r in rows if all(r['m'].get(s, {}).get(k) for s in srcs)], float)
    C = np.cov(X.T)
    ev = {}
    for i, s in enumerate(srcs):
        j, l = [a for a in range(3) if a != i]
        ev[s] = max(float(C[i, i] - C[i, j] * C[i, l] / C[j, l]), 1e-3)
    return ev, len(X), {f'{a}-{b}': round(float(np.mean(X[:, i] - X[:, j])), 2) for (i, a) in enumerate(srcs) for (j, b) in enumerate(srcs) if i < j}


POS_FD = lambda r: 'G' if r['G'] else 'D' if r['D'] else 'F'
POS_CW = lambda r: 'G' if r['G'] else 'D' if r['D'] else 'C' if (r.get('pos') or '').startswith('C') else 'W'


def best(rows, k, ev, posf, srcs):
    """precision-weighted combination of the sources, shrunk to the position mean (true-score var tau2)"""
    out = {}
    for g in set(map(posf, rows)):
        R = [r for r in rows if posf(r) == g]
        vals = [r['m']['nhl'][k] for r in R if r['m']['nhl'][k]]
        mu = float(np.mean(vals)); tau2 = max(float(np.var(vals)) - ev['nhl'], 1e-3)
        for r in R:
            w0, s0 = 1 / tau2, mu / tau2
            for s in srcs:
                v = r['m'].get(s, {}).get(k)
                if v:
                    w0 += 1 / ev[s]; s0 += v / ev[s]
            out[id(r)] = s0 / w0
    return out


def zcol(rows, val, posf, name, fit_rows):
    """z within position (mean / sd from the 2008-19 picks); missing -> 0"""
    st = {}
    for g in set(map(posf, fit_rows)):
        v = [val(r) for r in fit_rows if posf(r) == g and val(r) is not None]
        st[g] = (float(np.mean(v)), float(np.std(v)) or 1.0)
    for r in rows:
        v = val(r)
        m, s = st[posf(r)]
        r.setdefault('fz', {})[name] = 0.0 if v is None else (v - m) / s
    return st


# -- tests ----------------------------------------------------------------------------------------------------------
def tval(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0


def evalc(F, y, cls, picks, base, cand):
    s0, _ = H.score(F, y, cls, base)
    s1, _ = H.score(F, y, cls, base + cand)
    d = s0 - s1
    c0 = HD.checks(F, y, cls, picks, base); c1 = HD.checks(F, y, cls, picks, base + cand)
    X = np.array([[f[c] for c in base + cand] for f in F]); b = H.ols(X, y)
    o = {'gain': round(float(d.mean()), 3), 't': round(tval(d), 2), 'wins': int((d > 0).sum()), 'of': len(d),
         'coef': [round(float(v), 3) for v in b[-len(cand):]], 'mse0': round(float(s0.mean()), 2),
         'dTopMse': round(c1['topMse'] - c0['topMse'], 3), 'dTopRho': round(c1['topRho'] - c0['topRho'], 4),
         'dFwdMse': round(c1['fwdMse'] - c0['fwdMse'], 3), 'dFwdTopMse': round(c1['fwdTopMse'] - c0['fwdTopMse'], 3),
         'dFwdTopRho': round(c1['fwdTopRho'] - c0['fwdTopRho'], 4)}
    o['p1'] = round(float(1 - HS.t_cdf(o['t'], o['of'] - 1)), 4)                # one-sided, Student t on the folds
    o['cv'] = bool(o['t'] >= 2 and o['wins'] >= 8)
    o['pass'] = bool(o['cv'] and o['dTopMse'] <= 0 and o['dTopRho'] >= 0 and o['dFwdMse'] <= 0
                     and o['dFwdTopMse'] <= 0 and o['dFwdTopRho'] >= 0)
    return o


def holm(res):
    ks = sorted(res, key=lambda k: res[k]['p1'])
    m = len(ks)
    for i, k in enumerate(ks):
        res[k]['holm'] = bool(all(res[j]['p1'] <= .05 / (m - n) for n, j in enumerate(ks[:i + 1])))
    return res


def main():
    W = H.war_tables()
    rows = H.read_rows(W); H.nhl_so_far(rows, W)
    attach(rows)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); picks = np.array([r['pick'] for r in tr])
    fit = json.load(open(H.FIT))
    rep = {'n': len(tr)}
    # coverage + agreement
    cov = {s: {k: round(float(np.mean([bool(r['m'].get(s, {}).get(k)) for r in tr])), 3) for k in ('ht', 'wt')} for s in ('nhl', 'css', 'chl')}
    rep['coverage'] = cov
    ev, rep['triad'] = {}, {}
    for k in ('ht', 'wt'):
        e, n, md = triad(tr, k)
        ev[k] = e
        rep['triad'][k] = {'errVar': {s: round(v, 3) for s, v in e.items()}, 'n': n, 'meanDiff': md}
    print(json.dumps(rep), flush=True)
    # which sources are pre-draft: the CHL listing's mean gap to the draft record on the draft-year line
    srcs_ok = ('nhl', 'css') + (('chl',) if abs(rep['triad']['wt']['meanDiff'].get('nhl-chl', 0)) < 2 else ())
    rep['srcs'] = list(srcs_ok)
    for k in ('ht', 'wt'):
        B = best(tr, k, ev[k], POS_FD, srcs_ok)
        for r in tr:
            r['b_' + k] = B[id(r)]
    for r in tr:
        h, w = r['m']['nhl']['ht'], r['m']['nhl']['wt']
        r['bmi'] = 703 * w / h ** 2 if h and w else None
        r['b_bmi'] = 703 * r['b_wt'] / r['b_ht'] ** 2
        c = r['m'].get('css') or {}
        r['c_ht'] = c.get('ht') or h; r['c_wt'] = c.get('wt') or w
    zs = {}
    for posn, pf in (('FD', POS_FD), ('CW', POS_CW)):
        for nm, val in (('ht', lambda r: r['m']['nhl']['ht']), ('wt', lambda r: r['m']['nhl']['wt']), ('bmi', lambda r: r['bmi']),
                        ('htB', lambda r: r['b_ht']), ('wtB', lambda r: r['b_wt']), ('bmiB', lambda r: r['b_bmi']),
                        ('htC', lambda r: r['c_ht']), ('wtC', lambda r: r['c_wt'])):
            zs[f'{nm}_{posn}'] = zcol(tr, val, pf, f'{nm}_{posn}', tr)
    rep['posStats'] = {k: {g: [round(a, 2), round(b, 2)] for g, (a, b) in v.items()} for k, v in zs.items() if k in ('ht_FD', 'wt_FD', 'bmi_FD', 'ht_CW', 'wt_CW')}
    F = [H.feats(r) for r in tr]
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    for f, r in zip(F, tr):
        f.update(r['fz'])
        sk = 1 - r['G']
        for nm in ('ht', 'wt', 'bmi'):
            f[f'{nm}_F'] = r['fz'][f'{nm}_FD'] * (sk and not r['D']); f[f'{nm}_D'] = r['fz'][f'{nm}_FD'] * r['D']
            f[f'{nm}_Gk'] = r['fz'][f'{nm}_FD'] * r['G']
    kept = fit['kept']
    s0, p0 = H.score(F, y, cls, kept)
    rep['draft'] = {'kept': kept, 'mse': round(float(s0.mean()), 2), 'fitMse': fit['mse'], 'cands': {}}
    print('draft base', kept, round(s0.mean(), 2), fit['mse'], flush=True)
    DC = {'ht_FD': ['ht_FD'], 'wt_FD': ['wt_FD'], 'bmi_FD': ['bmi_FD'], 'ht+wt_FD': ['ht_FD', 'wt_FD'],
          'ht_CW': ['ht_CW'], 'wt_CW': ['wt_CW'], 'bmi_CW': ['bmi_CW'],
          'htB_FD': ['htB_FD'], 'wtB_FD': ['wtB_FD'], 'bmiB_FD': ['bmiB_FD'], 'htC_FD': ['htC_FD'], 'wtC_FD': ['wtC_FD'],
          'ht by F/D/G': ['ht_F', 'ht_D', 'ht_Gk'], 'wt by F/D/G': ['wt_F', 'wt_D', 'wt_Gk'], 'bmi by F/D/G': ['bmi_F', 'bmi_D', 'bmi_Gk']}
    for nm, cols in DC.items():
        rep['draft']['cands'][nm] = o = evalc(F, y, cls, picks, kept, cols)
        print('draft', nm, o, flush=True)
    # stages
    fv0 = {id(r): float(p) for r, p in zip(tr, p0)}
    rep['stages'] = {}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
        yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
        st = fit['stages'][str(k)]
        kk = st['pre']['kept'] if 'pre' in st else st['kept']
        Fk = [H.stage_feats(r, k, fv0[id(r)]) for r in sub]
        if 'comp' in kk:
            bc = st['kept'][:st['kept'].index('comp')]
            pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, bc), 20, 80), [H.comp_grp(r) for r in sub], ck)
            for f, r, c in zip(Fk, sub, ck):
                f['comp'] = H.comp_of(pool, f, H.comp_grp(r), own=c)
        if 'pnS' in kk:
            H.pre_fill(Fk, sub, k)
        for f, r in zip(Fk, sub):
            f.update(r['fz'])
        sb, _ = H.score(Fk, yk, ck, kk)
        out = {'kept': kk, 'mse': round(float(sb.mean()), 2), 'n': len(sub), 'cands': {}}
        for nm in ('htB_FD', 'wtB_FD', 'bmiB_FD'):
            out['cands'][nm] = o = evalc(Fk, yk, ck, pk, kk, [nm])
            print(f'stage {k}', nm, o, flush=True)
        rep['stages'][k] = out
    allc = {f'draft {k}': v for k, v in rep['draft']['cands'].items()}
    allc.update({f'k{k} {c}': v for k, s in rep['stages'].items() for c, v in s['cands'].items()})
    holm(allc)
    rep['nTests'] = len(allc)
    rep['passed'] = [k for k, v in allc.items() if v['pass'] and v['holm']]
    rep['passedNoHolm'] = [k for k, v in allc.items() if v['pass']]
    os.makedirs(OUTD, exist_ok=True)
    json.dump(rep, open(os.path.join(OUTD, 'hockey_frame.json'), 'w'), indent=1)
    print('tests', rep['nTests'], 'pass', rep['passed'], 'pass w/o Holm', rep['passedNoHolm'])


def prov():
    """the provisional model (off-board CHL draft-eligibles, scripts/hockey_provisional.py): frame z within F / D on top
    of its kept drivers, its own class-out rule; the only measure there is HockeyTech's profile (one listing a player)"""
    import hockey_provisional as HP
    W = H.war_tables()
    rows = H.read_rows(W); H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    pop = HP.population(rows, W, sc, range(H.FIRST, H.LAST_FIT + 1))
    y = np.array([p['fv'] for p in pop]); cls = np.array([p['year'] for p in pop])
    F = [HP.feats(p) for p in pop]
    P = json.load(open(HP.FIT))
    kept = P['kept']
    for p in pop:
        p['bmi'] = 703 * p['wt'] / p['ht'] ** 2 if p.get('ht') and p.get('wt') else None
    pf = lambda p: p['pos']
    for nm in ('ht', 'wt', 'bmi'):
        zcol(pop, lambda p, nm=nm: p.get(nm) or None, pf, nm + 'z', pop)
    for f, p in zip(F, pop):
        f.update(p['fz'])
        f['wtzD'] = p['fz']['wtz'] * f['D']; f['wtzF'] = p['fz']['wtz'] * (1 - f['D'])
    s0, _ = H.score(F, y, cls, kept)
    rep = {'n': len(pop), 'kept': kept, 'mse': round(float(s0.mean()), 3), 'fitMse': P['mse'],
           'coverage': {k: round(float(np.mean([bool(p.get(k)) for p in pop])), 3) for k in ('ht', 'wt')}, 'cands': {}}
    nh = np.array([p['fv'] > 20 for p in pop])
    for nm, cols in (('htz', ['htz']), ('wtz', ['wtz']), ('bmiz', ['bmiz']), ('wtz by F/D', ['wtzF', 'wtzD'])):
        s1, p1 = H.score(F, y, cls, kept + cols)
        d = s0 - s1
        X = np.array([[f[c] for c in kept + cols] for f in F]); b = H.ols(X, y)
        tr, te = cls <= 2015, cls >= 2016
        def fwd(cs):
            Xc = np.array([[f[c] for c in cs] for f in F])
            q = np.clip(H.pred(H.ols(Xc[tr], y[tr]), Xc[te]), 20, 80)
            top = np.argsort(-q)[:int(te.sum() * .05)]
            return float(np.mean((q - y[te]) ** 2)), float(np.mean(nh[te][top]))
        f0, f1 = fwd(kept), fwd(kept + cols)
        _, p0 = H.score(F, y, cls, kept)
        top0, top1 = np.argsort(-p0)[:int(len(y) * .05)], np.argsort(-p1)[:int(len(y) * .05)]
        o = {'gain': round(float(d.mean()), 4), 't': round(tval(d), 2), 'wins': int((d > 0).sum()), 'of': len(d),
             'coef': [round(float(v), 3) for v in b[-len(cols):]],
             'top5pctNhl': [round(float(nh[top0].mean()), 3), round(float(nh[top1].mean()), 3)],
             'fwdMse': round(f1[0] - f0[0], 4), 'fwdTop5Nhl': round(f1[1] - f0[1], 3)}
        o['p1'] = round(float(1 - HS.t_cdf(o['t'], o['of'] - 1)), 4)
        o['pass'] = bool(o['t'] >= 2 and o['wins'] >= 8 and o['top5pctNhl'][1] >= o['top5pctNhl'][0] and o['fwdMse'] <= 0
                         and o['fwdTop5Nhl'] >= 0)
        rep['cands'][nm] = o
        print('prov', nm, o, flush=True)
    os.makedirs(OUTD, exist_ok=True)
    json.dump(rep, open(os.path.join(OUTD, 'hockey_prov_frame.json'), 'w'), indent=1)


if __name__ == '__main__':
    if '--pull' in sys.argv:
        pull()
    elif '--prov' in sys.argv:
        prov()
    else:
        main()
