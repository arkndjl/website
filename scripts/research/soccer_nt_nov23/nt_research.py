#!/usr/bin/env python3
"""Soccer prospect FV: opponent- and nation-strength-adjusted national team play (prereg.md, Nov 23 2026).
Harness = scripts/soccer_trust_research.py (core rows, test gate). Outputs results.json here."""
import json, math, os, pickle, re, sys
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR); sys.path.insert(0, HERE)
import soccer_prospects as SP            # noqa
import soccer_prospect_data as SD        # noqa
import soccer_trust_research as TR       # noqa
import soccer_intl as SI                 # noqa
import nation_strength as NS             # noqa

CACHE = os.path.join(SP.CACHE, 'nt')
NTC = TR.NTC
FRIENDLY = ['FS']
SEASONS = range(2010, 2027)


def q(s):
    return np.clip(np.asarray(s, float) + 3, 0, 6) / 3


def team_names(ids):
    fn = os.path.join(CACHE, 'club_names.json')
    have = json.load(open(fn)) if os.path.exists(fn) else {}
    todo = [str(int(c)) for c in ids if str(int(c)) not in have]
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(10) as ex:
        for i, r in zip(todo, ex.map(lambda i: SD.get(f'/club/{i}', tries=3), todo)):
            have[i] = ((r or {}).get('data') or {}).get('name')
    os.makedirs(CACHE, exist_ok=True)
    json.dump(have, open(fn, 'w'))
    return {int(k): v for k, v in have.items()}


def nation_of(name, known):
    if not name:
        return None
    base = re.sub(r'\s*(U\s?\d\d|Olymp\w*|B)$', '', name).strip()
    n = SI.tm_to_mj(base)
    return n if n in known else None


def apps():
    fn = os.path.join(CACHE, 'apps.pkl')
    if os.path.exists(fn):
        return pd.read_pickle(fn)
    S = NS.series()
    cu = SI.callups()['tm']
    out = []
    for kind, comps in (('sen', NTC), ('yth', list(SD.YOUTH_INTL))):
        G, A = SP.tm_games(comps, SEASONS)
        A = A.merge(G[['game_id', 'comp', 'date', 'home', 'away']], on='game_id')
        ids = set(A.club.dropna().astype(int)) | set(G.home.dropna().astype(int)) | set(G.away.dropna().astype(int))
        nm = team_names([i for i in ids if str(i) not in cu])
        def nat(i):
            if pd.isna(i):
                return None
            i = int(i)
            if str(i) in cu and kind == 'sen':
                return cu[str(i)]
            return nation_of(nm.get(i), S)
        nmap = {i: nat(i) for i in ids}
        if kind == 'sen':     # only senior sides (no U-teams under a senior code)
            ok = {i for i in ids if (str(i) in cu) or (nm.get(i) and not re.search(r'U\s?\d\d|Olymp|B$|Youth|Amateur', nm[i]))}
            A = A[A.club.isin(ok)]
            A['cap'] = 99
        else:
            A['cap'] = A.comp.map(lambda c: SD.YOUTH_INTL[c][0])
        A['own'] = A.club.map(nmap)
        opp = np.where(A.club.values == A.home.values, A.away.values, A.home.values)
        A['opp'] = pd.Series(opp, index=A.index).map(nmap)
        d = A.date.dt.strftime('%Y-%m-%d')
        A['s_own'] = [NS.at(S, t, x) if t else None for t, x in zip(A.own, d)]
        A['s_opp'] = [NS.at(S, t, x) if t else None for t, x in zip(A.opp, d)]
        A['kind'] = kind
        print(kind, len(A), 'own mapped', A.own.notna().mean().round(3), 'opp', A.opp.notna().mean().round(3), flush=True)
        out.append(A)
    A = pd.concat(out, ignore_index=True)
    for c in ('s_own', 's_opp'):
        A[c] = pd.to_numeric(A[c])
    A.to_pickle(fn)
    return A


def nt_feats(N, ids, snap):
    snap = pd.Timestamp(snap)
    E = pd.DataFrame(index=ids)
    w = N[N.player_id.isin(ids) & (N.date < snap)]
    p = w[w.mins > 0].copy()
    p['n90'] = p.mins / 90
    p['qo'] = q(p.s_opp.fillna(-1.0))     # unrated opponent: a weak side
    p['qw'] = q(p.s_own.fillna(-1.0))
    s = p[p.kind.eq('sen')]
    y = p[p.kind.eq('yth')]
    g = lambda x, col: x.groupby('player_id')[col].sum().reindex(ids).fillna(0)
    s = s.assign(oq=s.n90 * s.qo, wq=s.n90 * s.qw, gq=(s.gl + s.ast) * s.qo)
    E['snt_opp'] = g(s, 'oq') / 10
    E['snt_own'] = g(s, 'wq') / 10
    E['snt_ga'] = g(s, 'gq') / (g(s, 'n90') + 5)
    sc = s[~s.comp.isin(FRIENDLY)]
    E['snt_comp'] = g(sc, 'oq') / 10
    # share of own nation's senior minutes in the 365 days before the snapshot x q(own)
    r = s[s.date >= snap - pd.Timedelta(days=365)]
    allsen = N[(N.kind == 'sen') & (N.date < snap) & (N.date >= snap - pd.Timedelta(days=365))]
    tm = allsen.groupby('own').game_id.nunique() * 90
    pm = r.groupby(['player_id', 'own']).agg(m=('mins', 'sum'), qw=('qw', 'mean')).reset_index()
    pm['sh'] = (pm.m / pm.own.map(tm)).clip(0, 1) * pm.qw
    E['snt_sh12'] = pm.groupby('player_id').sh.max().reindex(ids).fillna(0)
    y = y.assign(oq=y.n90 * y.qo * y.cap / 21, gq=(y.gl + y.ast) * y.qo)
    E['yi_opp'] = g(y, 'oq') / 10
    E['yi_ga'] = g(y, 'gq') / (g(y, 'n90') + 5)
    E['nt_all'] = E.snt_opp + E.yi_opp
    return E


CANDS = [['snt_opp'], ['snt_own'], ['snt_ga'], ['snt_comp'], ['snt_sh12'], ['yi_opp'], ['yi_ga'], ['nt_all']]


def rows():
    fn = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    G, A, P, V, R, O, TG = TR.core()
    N = apps()
    AB = A[A._cup.isna()].drop(columns='_cup')
    done = O[O.s22 <= SP.COHORTS[1]]
    fitj = json.load(open(SP.FIT))
    out = {}
    for md in TR.SNAPS:
        xs = []
        for t in range(SP.ROWS[0], SP.ROWS[1] + 1):
            snap = SP.snapdate(t, md)
            X = SP.features(AB, P, V, R, TG, t, snap)
            X['mvlvl'] = SP.mv_level(X.mv)
            X = X[X.index.isin(done.index) & X.old]
            X['mvd'] = X.mv * np.exp(fitj['mvRef']['%02d-%02d' % md] - X.mvlvl)
            F = SP.design(X)
            E = nt_feats(N, X.index, snap)
            Z = pd.concat([F, E], axis=1)
            Z['fv_out'] = done.fv.reindex(X.index)
            Z['s22'] = done.s22.reindex(X.index)
            Z['t'] = t
            Z['pid'] = X.index
            xs.append(Z.reset_index(drop=True))
            print('rows', md, t, len(Z), flush=True)
        out[md] = pd.concat(xs, ignore_index=True)
    pickle.dump(out, open(fn, 'wb'))
    return out


def holm(ts):
    from math import erf, sqrt
    ps = {k: .5 * (1 - erf(v / sqrt(2))) for k, v in ts.items()}
    m, ok = len(ps), {}
    for i, (k, p) in enumerate(sorted(ps.items(), key=lambda kv: kv[1])):
        ok[k] = p <= .05 / (m - i)
        if not ok[k]:
            for k2, _ in sorted(ps.items(), key=lambda kv: kv[1])[i:]:
                ok[k2] = False
            break
    return ps, ok


def main():
    Rw = rows()
    kept = json.load(open(SP.FIT))['kept']
    out = {'prereg': '4fe0f733', 'kept': kept, 'snap': {}}
    for md, Z in Rw.items():
        key = '%02d-%02d' % md
        y, co = Z.fv_out.values, Z.s22.values
        e, p = SP.loso(Z, y, co, kept)
        res = {'n': int(len(Z)), 'mse': round(float((e ** 2).mean()), 2),
               'cover': {c: int((Z[c] != 0).sum()) for c in sorted({c for cs in CANDS for c in cs})}, 'cands': {}}
        for cols in CANDS:
            r = TR.test(Z, kept, cols)
            res['cands']['+'.join(cols)] = r
            print(key, '+'.join(cols), r, flush=True)
        out['snap'][key] = res
    k0 = '%02d-%02d' % TR.SNAPS[0]
    ps, ok = holm({c: v['t'] for c, v in out['snap'][k0]['cands'].items()})
    for c, v in out['snap'][k0]['cands'].items():
        v['p'] = round(ps[c], 4); v['holm'] = bool(ok[c])
        other = [s for s in out['snap'] if s != k0]
        v['final'] = bool(v['pass'] and ok[c] and all(out['snap'][s]['cands'][c]['t'] > -2 for s in other))
    json.dump(out, open(os.path.join(HERE, 'results.json'), 'w'), indent=1, allow_nan=False)


if __name__ == '__main__':
    main()
