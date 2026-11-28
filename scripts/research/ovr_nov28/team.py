# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Team OVR research (Nov 28 2026): how to weight a roster's player OVR inputs (z, the rate OVR is read from) into a team
rating, scored leave one season out on the team's realised result next season.

  NBA  target: next season's team rating, sum(rXPM x MP) / sum(MP) x 5 (it tracks net rating at r2 .999)
  NHL  target: next season's team WAR (it sums to goal differential at r2 .978)
Players on next season's roster carry this season's z (a newcomer: the mean next-season rate of newcomers in the training
seasons). Weightings:
  mins    next season's minutes / TOI (what the live board has in season: minutes played so far)
  prior   this season's minutes (newcomers: the median newcomer's)
  depth   z sorted into depth slots (NBA top 10; NHL 12 F, 6 D, 1 G), slot weights fit on the training seasons
  equal   the top 8 (NBA) or top 12 F + 6 D + G (NHL), equal weights
python3 scripts/research/ovr_nov28/team.py -> research/ovr_research.json 'team'"""
import json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from engine import wls, pearson, paired_t
import ovr as O

RES = os.path.join(ROOT, 'research', 'ovr_research.json')
FIT = json.load(open(os.path.join(ROOT, 'data', 'ovr_fit.json')))


def last_tm(t): return str(t or '').split('/')[-1]


def nba_seasons():
    F = O.nba_files(); par = FIT['par']['nba']; out = []
    for s in sorted(F):
        if s + 1 not in F or s + 1 >= max(F) or s < 2011: continue
        cur = {r['id']: r for r in O.nba_rows(s, F)}
        for r in cur.values(): r['z'] = r['P'] if RAW else O.zof(par, r)
        nxt = [p for p in json.load(open(F[s + 1]))['players'] if p.get('xpm') is not None and not p.get('pr')]
        teams = {}
        for p in nxt:
            q = cur.get(p['id'])
            teams.setdefault(last_tm(p['tm']), []).append({'z': q['z'] if q else None, 'w1': p['mp'], 'w0': q['n'] if q else None,
                                                           'grp': 'all', 'y': p.get('txpm', p['xpm']) * p['mp']})
        out.append((s, teams))
    return out


def nhl_seasons():
    F = O.nhl_files(); pars = FIT['par']['nhl']; out = []
    for s in sorted(F):
        if s + 1 not in F or s + 1 >= max(F) or s < 2010: continue
        if json.load(open(F[s + 1])).get('games', 82) < 82: continue
        cur = {r['id']: r for r in O.nhl_rows(s, F)}
        for r in cur.values(): r['z'] = r['P'] if RAW else O.zof(pars[r['grp']], r)          # WAR a 60
        nxt = [p for p in json.load(open(F[s + 1]))['players'] if p.get('toi') and p.get('grp') in ('F', 'D', 'G')]
        teams = {}
        for p in nxt:
            q = cur.get(p['id'])
            teams.setdefault(p['tm'], []).append({'z': q['z'] if q else None, 'w1': p['toi'], 'w0': q['n'] if q else None,
                                                  'grp': p['grp'], 'y': p.get('war') or 0.0})
        out.append((s, teams))
    return out


RAW = False
LAST = {}
SLOTS = {'nba': {'all': 10}, 'nhl': {'F': 12, 'D': 6, 'G': 1}}


def run(sport):
    S = nba_seasons() if sport == 'nba' else nhl_seasons()
    nba = sport == 'nba'
    def target(pl):
        return sum(x['y'] for x in pl) / sum(x['w1'] for x in pl) * 5 if nba else sum(x['y'] for x in pl)
    res = {k: [] for k in ('mins', 'prior', 'depth', 'equal')}
    for s, teams in S:
        tr = [(s2, t2) for s2, t2 in S if s2 != s]
        # newcomer z and minutes from the training seasons
        nz = {}; nw = {}
        for _, tt in tr:
            for pl in tt.values():
                for x in pl:
                    if x['z'] is None:
                        nz.setdefault(x['grp'], []).append((x['y'] / x['w1'] * (1 if not nba else 1)) if x['w1'] else 0)
                        nw.setdefault(x['grp'], []).append(x['w1'])
        # newcomer value: mean next-season rate (NBA rXPM; NHL WAR a 60 = y / toi x 60)
        nzv = {g: (st.mean(v) if nba else st.mean(v) * 60) for g, v in nz.items()}
        nwv = {g: st.median(v) for g, v in nw.items()}
        def zz(x): return x['z'] if x['z'] is not None else nzv.get(x['grp'], 0.0)
        def feats(pl, how):
            if how == 'mins':
                return [sum(zz(x) * x['w1'] for x in pl) / sum(x['w1'] for x in pl) * 5] if nba else [sum(zz(x) * x['w1'] / 60 for x in pl)]
            if how == 'prior':
                w = [x['w0'] if x['w0'] is not None else nwv.get(x['grp'], 0) for x in pl]
                if nba: return [sum(zz(x) * wi for x, wi in zip(pl, w)) / sum(w) * 5]
                tot = sum(x['w1'] for x in pl); return [sum(zz(x) * wi / 60 for x, wi in zip(pl, w)) * (sum(w) and tot / sum(w))]
            f = []
            for g, k in SLOTS[sport].items():
                zs = sorted((zz(x) for x in pl if x['grp'] == g or g == 'all'), reverse=True)[:k]
                zs += [nzv.get(g, 0.0)] * (k - len(zs))
                f += zs if how == 'depth' else [sum(zs) / k]
            return f
        for how in res:
            X = [[1.0] + feats(pl, how) for _, tt in tr for pl in tt.values()]
            y = [target(pl) for _, tt in tr for pl in tt.values()]
            b = wls(X, y, [1.0] * len(y), ridge=1e-3)
            p = [sum(bi * v for bi, v in zip(b, [1.0] + feats(pl, how))) for pl in teams.values()]
            res[how].append(pearson(p, [target(pl) for pl in teams.values()]) ** 2)
    LAST.clear(); LAST.update(res)
    out = {k: {'r2': round(st.mean(v), 3)} for k, v in res.items()}
    for k in ('prior', 'depth', 'equal'):
        out[k]['vsMins'] = {'t': paired_t(res[k], res['mins']), 'wins': sum(1 for a, b in zip(res[k], res['mins']) if a > b), 'of': len(res[k])}
    out['depth']['vsPrior'] = {'t': paired_t(res['depth'], res['prior']), 'wins': sum(1 for a, b in zip(res['depth'], res['prior']) if a > b)}
    out['seasons'] = [S[0][0], S[-1][0]]
    return out


def input_test(sport):
    """OVR's rate (with its held-out extra terms) against the plain projection rate, both minutes-weighted with the
    same newcomer fill, per-season R2 on next season's team result"""
    global RAW
    RAW = True; run(sport); raw = list(LAST['mins'])
    RAW = False; run(sport); ovr = list(LAST['mins'])
    return {'raw': round(st.mean(raw), 4), 'ovr': round(st.mean(ovr), 4), 't': paired_t(ovr, raw),
            'wins': sum(1 for a, b in zip(ovr, raw) if a > b), 'of': len(raw)}


if __name__ == '__main__' and sys.argv[1:2] == ['--input']:
    R = json.load(open(RES)); R.setdefault('inputs', {})
    for sp in ('nba', 'nhl'):
        R['inputs']['team_' + sp] = input_test(sp); print(sp, R['inputs']['team_' + sp])
    json.dump(R, open(RES, 'w'), indent=1); sys.exit()

if __name__ == '__main__':
    R = json.load(open(RES)); R.setdefault('team', {})
    for sp in sys.argv[1:] or ['nba', 'nhl']:
        R['team'][sp] = run(sp); print(sp, json.dumps(R['team'][sp]))
    json.dump(R, open(RES, 'w'), indent=1)
