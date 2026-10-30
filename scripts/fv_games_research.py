"""Player FV as an input to the game models and team rankings (Noah, Oct 30 2026: "figure out how we can use FV as an
input for game models to improve the game models and team rankings"). Each test adds a form not tried before
(fv-mean-games, fv-lowsample-priors, roster-proj-rankings, cfb/nfl roster priors), scored on each model's own split
and gate. Every grade is as of the draft / the season before, never after the game.
    python3 scripts/fv_games_research.py nhl      # young returning skaters: draft grade as a development offset in rv
    python3 scripts/fv_games_research.py qb247    # CFB: each QB in the ESPN play-by-play history -> 247 composite,
                                                  # then node scripts/cfb_qb_backup.mjs fv (backup QB valued by recruit grade)
Writes data/fv_games_research.json (one block per test).
"""
import gzip
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'fv_games_research.json')
r4 = lambda x: None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def save(key, block):
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d[key] = block
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1, allow_nan=False)


def wls(X, y, w, lam=1e-6):
    A = X.T @ (X * w[:, None]) + lam * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ (w * y))


def wt(e1, e0, w):
    """TOI-weighted paired t of squared errors (candidate minus base)"""
    d = w * (e1 - e0) / w.mean()
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))


# ---------------------------------------------------------------- NHL
def nhl_draft():
    """NHL id -> (draft year, pick, grade). Grade as fv_lowsample_research.nhl_grades: class-out board grade for
    2008-19 picks, else the draft model on the draft-year inputs (fit 2008-19)"""
    import fv_lowsample_research as L
    fv = L.nhl_grades()
    rows = json.load(gzip.open(os.path.join(HERE, 'data', 'hockey_rows.json.gz')))
    return {r['id']: (r['year'], r['pick'], fv[r['id']]) for r in rows if r['id'] and r['id'] in fv and not r['G']}


def nhl_players(K):
    """returning skaters (a line in season S-1): season S descriptive goals a 60 over average (go + gd) against the
    S-1 file's projected HPM, the rate rv prices them at. Young = drafted within K seasons"""
    D = nhl_draft()
    W = {}
    for S in range(2009, 2027):
        W[S] = {p['id']: p for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{S}.json')))['players']
                if p['grp'] in ('F', 'D')}
    R = []
    for S in range(2010, 2027):
        for i, p in W[S].items():
            q = W[S - 1].get(i)
            if not q or p['toi'] < 60:
                continue
            y = (p['go'] + p['gd']) / p['toi'] * 60
            d = D.get(i)
            k = S - d[0] if d else 99
            yg = 1.0 if 1 <= k <= K else 0.0
            R.append((S, y - q['hpm'], p['toi'], yg, yg * ((d[2] if d else 30) - 40), yg * -math.log(d[1] if d else 224),
                      yg * k, (q['age'] or 27), float(q['toi'] < 400), i))
    ids = [r[-1] for r in R]
    return np.array([r[:-1] for r in R], float), ids


def nhl_offsets(K, form):
    """walk forward: residual (season S rate - projected HPM) on young / young x grade (or slot), TOI-weighted, fit on
    seasons before S. Returns the player test and S -> {id: offset} for every graded player drafted within K"""
    A, ids = nhl_players(K)
    S, res, w, yg, gfv, gsl, gk, age, low = (A[:, j] for j in range(9))
    one = np.ones(len(S))
    X0 = np.column_stack([one])
    X1 = {'young': np.column_stack([one, yg]),
          'fv': np.column_stack([one, yg, gfv]),
          'slot': np.column_stack([one, yg, gsl]),
          'fvk': np.column_stack([one, yg, gfv, yg * gk]),
          'age': np.column_stack([one, np.clip(age, 18, 36) - 27]),
          'agefv': np.column_stack([one, np.clip(age, 18, 36) - 27, yg, gfv]),
          'age2': np.column_stack([one, np.clip(age, 18, 36) - 27, (np.clip(age, 18, 36) - 27) ** 2])}[form]
    p0, p1 = np.full(len(S), np.nan), np.full(len(S), np.nan)
    coefs = {}
    for s in range(2013, 2027):
        tr, te = S < s, S == s
        b0, b1 = wls(X0[tr], res[tr], w[tr]), wls(X1[tr], res[tr], w[tr])
        p0[te], p1[te] = X0[te] @ b0, X1[te] @ b1
        coefs[s] = (b0, b1)
    coefs[2027] = (wls(X0, res, w), wls(X1, res, w))
    out = {}
    for nm, k in (('2013_20', (S >= 2013) & (S < 2021)), ('2021_26', S >= 2021), ('young2013_26', (S >= 2013) & (yg == 1))):
        e1, e0 = (p1[k] - res[k]) ** 2, (p0[k] - res[k]) ** 2
        out[nm] = {'n': int(k.sum()), 't': round(wt(e1, e0, w[k]), 2), 'dmse': r4(float(np.average(e1 - e0, weights=w[k])))}
    out['coef_all'] = [r4(c) for c in coefs[2027][1]]
    D = nhl_draft()
    ages = {}
    for s in range(2013, 2028):
        try:
            for p in json.load(open(os.path.join(ROOT, 'static', 'data', 'nhl-war', f'{s - 1}.json')))['players']:
                ages[(s, p['id'])] = p['age'] or 27
        except OSError:
            pass
    off = {}
    for s in range(2013, 2028):
        b0, b1 = coefs[s]
        o = {}
        for i, (yr, pk, g) in D.items():
            k = s - yr
            if form.startswith('age'):
                continue
            if 1 <= k <= K:
                x = {'young': [1, 1], 'fv': [1, 1, g - 40], 'slot': [1, 1, -math.log(pk)], 'fvk': [1, 1, g - 40, k]}[form]
                o[i] = float(np.dot(b1, x) - b0[0])
        if form.startswith('age'):
            for (ss, i), a in ages.items():
                if ss != s:
                    continue
                x = min(max(a, 18), 36) - 27
                d = D.get(i)
                k = s - d[0] if d else 99
                yg = 1.0 if 1 <= k <= K else 0.0
                v = [1, x] + ([yg, yg * (d[2] - 40) if d else 0.0] if form == 'agefv' else [x * x] if form == 'age2' else [])
                o[i] = float(np.dot(b1, v) - b0[0])
        off[s] = o
    return out, off


def nhl_games_test(off, label):
    """rv with each returning young skater's projected HPM moved by his offset; LL on nhl_games' walk, gate as
    nhl_games.passes (tune t >= 1.5, held > -1, lined and all games)"""
    import nhl_games as G
    F = json.load(open(G.FIT))
    P, feats = F['params'], F['feats']
    hist = G.load_hist()
    G._LV.clear()
    _, rows0, _ = G.walk(hist, P)
    W0 = G._war

    def war(S):
        w = W0(S)
        if w is None or S not in off:
            return w
        ps, repl, avg = w
        ps2 = {}
        for i, p in ps.items():
            if i in off[S]:
                p = dict(p, hpm=p['hpm'] + off[S][i])
            ps2[i] = p
        return ps2, repl, avg
    G._war = war
    _, rows1, _ = G.walk(hist, P)
    G._war = W0
    assert [g['id'] for g, _ in rows0] == [g['id'] for g, _ in rows1]
    for (g, f0), (_, f1) in zip(rows0, rows1):
        f0['rvy'] = f1['rv']
    alt = [x if x != 'rv' else 'rvy' for x in feats]
    Sx, yy, m, tot, pc, tc, day = G.arrays(rows0)
    out = {}
    for lab, lined, first, tune_s in (('lined', True, G.FIRST_TEST, G.TUNE), ('all', False, G.SCORE_FROM + 1, (G.SCORE_FROM + 1, G.TUNE[1]))):
        ok = ~np.isnan(pc) if lined else np.ones(len(yy), bool)
        l0 = H.logloss(G.walk_logit(G.design(rows0, feats), yy, Sx, first, ok), yy)
        l1 = H.logloss(G.walk_logit(G.design(rows0, alt), yy, Sx, first, ok), yy)
        r = {}
        for nm, k in (('tune', (Sx >= tune_s[0]) & (Sx <= tune_s[1]) & ok), ('held', (Sx >= G.HOLD_FROM) & ok)):
            k = k & ~np.isnan(l0) & ~np.isnan(l1)
            pr = H.paired(l0[k], l1[k], day[k])
            r[nm] = {'n': int(k.sum()), 'dLL1000': round(float((l1[k] - l0[k]).mean()) * 1000, 3), 'tHelps': round(pr['t'], 2)}
        seas = {}
        for s in sorted(set(Sx[ok & ~np.isnan(l0) & ~np.isnan(l1)].astype(int))):
            k = ok & (Sx == s) & ~np.isnan(l0) & ~np.isnan(l1)
            seas[str(s)] = round(float((l1[k] - l0[k]).mean()) * 1000, 3)
        r['bySeason'] = seas
        out[lab] = r
    print(label, json.dumps({k: {kk: v[kk] for kk in ('tune', 'held')} for k, v in out.items()}), flush=True)
    return out


def nhl(only=None):
    if only:
        res = json.load(open(OUT))['nhl']
        for form, lab in only:
            pl, off = nhl_offsets(5, form)
            res['players'][lab] = pl
            print(lab, pl, flush=True)
            res['games'][lab] = nhl_games_test(off, lab)
            save('nhl', res)
        return
    res = {'note': 'NHL rv (lineup value): returning skaters priced at the S-1 projected HPM, which has no age or '
                   'development term. Young = drafted within K seasons; offset = walk-forward fit of (season rate - '
                   'projected HPM) on young / young x draft grade (or -log pick). Player t: TOI-weighted paired squared '
                   'error vs intercept only (negative helps). Games: tHelps > 0 helps (nhl_games gate: tune >= 1.5, held > -1)',
           'players': {}, 'games': {}}
    for K in (3, 5):
        for form in ('young', 'fv', 'slot', 'fvk'):
            pl, off = nhl_offsets(K, form)
            res['players'][f'K{K} {form}'] = pl
            print(K, form, pl, flush=True)
            res['games'][f'K{K} {form}'] = nhl_games_test(off, f'K{K} {form}')
            save('nhl', res)
    for form, lab in (('age', 'age (all skaters)'), ('agefv', 'age + K5 young x grade'), ('age2', 'age quadratic')):
        pl, off = nhl_offsets(5, form)
        res['players'][lab] = pl
        print(lab, pl, flush=True)
        res['games'][lab] = nhl_games_test(off, lab)
        save('nhl', res)


# ---------------------------------------------------------------- CFB backup QBs
def qb247():
    """ESPN athlete id of every QB with a pass in scripts/.cache/cfb/qb_epa.json.gz -> 247 composite: the 247 QB
    (PRO, DUAL, QB, ATH) of the same name key in a class from S-6 to S of his first season, the school matching his ESPN
    team when two share the name. Writes scripts/.cache/cfb/qb247.json"""
    import names as NM
    C = os.path.join(HERE, '.cache', 'cfb')
    Q = json.load(gzip.open(os.path.join(C, 'qb_epa.json.gz')))
    tn = {}
    for S in range(2015, 2027):
        for g in json.load(open(os.path.join(C, 'espn_hist', f'games{S}.json'))):
            tn[g['h']], tn[g['a']] = g['hn'], g['an']
    seen = {}
    for g in Q['games'].values():
        for t, P in g['q'].items():
            for a in P:
                if a not in seen or g['S'] < seen[a][0]:
                    seen[a] = (g['S'], t)
    R = {}
    for y in range(2010, 2027):
        f = os.path.join(C, 'r247', f'{y}.json')
        if os.path.exists(f):
            for r in json.load(open(f)):
                if r['pos'] in ('PRO', 'DUAL', 'QB', 'ATH'):
                    R.setdefault(NM.key(r['name']), []).append((y, r))
    out, st = {}, {'qbs': len(seen), 'matched': 0, 'ambiguous': 0, 'none': 0}
    for a, (S, t) in seen.items():
        nm = Q['names'].get(a)
        c = [(y, r) for y, r in R.get(NM.key(nm or ''), []) if S - 6 <= y <= S]
        tk = NM.team_key(tn.get(t, ''))
        if len(c) > 1:
            c2 = [(y, r) for y, r in c if r['school'] and tk.startswith(NM.team_key(r['school']))]
            c = c2 if len(c2) == 1 else ([x for x in c if x[1]['pos'] != 'ATH'] if len([x for x in c if x[1]['pos'] != 'ATH']) == 1 else [])
            if not c:
                st['ambiguous'] += 1
                continue
        if c:
            out[a] = c[0][1]['comp']
            st['matched'] += 1
        else:
            st['none'] += 1
    json.dump(out, open(os.path.join(C, 'qb247.json'), 'w'))
    print(st)


if __name__ == '__main__':
    if sys.argv[1] == 'nhl-age':
        nhl([('agefv', 'age + K5 young x grade'), ('age2', 'age quadratic')])
    else:
        {'nhl': nhl, 'qb247': qb247}[sys.argv[1]]()
