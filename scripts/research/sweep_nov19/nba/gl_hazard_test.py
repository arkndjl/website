# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Lead 6b (PREREG.md): a 30-day call-up hazard from G League game logs.

    python3 gl_hazard_test.py GL_DIR      # -> impl/nba/gl_hazard.json

Snapshots on the 1st and 15th of Dec-Mar, seasons 2020-2025: players with 3+ G League games in the 30 days before and
no NBA game yet that season; label = first NBA game within 30 days (NBA dates: scripts/nba_pbox_hist.json.gz).
Baseline: age, games, minutes a game and Game Score per 36 to date. Candidate adds last-10-game minutes, Game Score
per 36 and points per 36, each minus the to-date value. Walk-forward by season; held 2023-25."""
import datetime as dt, gzip, json, os, sys
import numpy as np
import common as C
import gleague_callup as GC
import nba_games as N


def gs(r):
    return (r['PTS'] + .4 * r['FGM'] - .7 * r['FGA'] - .4 * (r['FTA'] - r['FTM']) + .7 * r['OREB'] + .3 * r['DREB'] + r['STL']
            + .7 * r['AST'] + .7 * r['BLK'] - .4 * r['PF'] - r['TOV'])


def logs(folder, y):
    out = {}
    for tag in ('log', 'logsc'):
        fn = os.path.join(folder, f'{tag}_{y}.json')
        if not os.path.exists(fn): continue
        d = json.load(open(fn))['resultSets'][0]
        for x in d['rowSet']:
            r = dict(zip(d['headers'], x))
            if not r['MIN']: continue
            for k in ('PTS', 'FGM', 'FGA', 'FTA', 'FTM', 'OREB', 'DREB', 'STL', 'AST', 'BLK', 'PF', 'TOV'): r[k] = r[k] or 0
            out.setdefault(r['PLAYER_ID'], []).append((dt.date.fromisoformat(r['GAME_DATE'][:10]), float(r['MIN']), gs(r), float(r['PTS']), r['PLAYER_NAME']))
    for v in out.values(): v.sort()
    return out


def main():
    G, names = N.load_hist()
    box = json.load(gzip.open(os.path.join(C.SCRIPTS, 'nba_pbox_hist.json.gz'), 'rt'))
    first = {}                                             # season -> espn id -> first NBA game date (regular season)
    for g in G:
        b = box.get(g['id'])
        if not b or g.get('t') != 2: continue
        d = N.gday(N.tipdt(g))
        for t in b:
            for r in b[t]:
                if r[4] and r[4] > 0:
                    f = first.setdefault(g['S'], {})
                    if r[0] not in f or d < f[r[0]]: f[r[0]] = d
    rows = []
    for y in range(2020, 2026):
        L = logs(sys.argv[1], y)
        age = {p: o['age'] for p, o in GC.gl_season(y).items()}
        find = C.matcher([(pid, names[pid]) for pid in first.get(y, {}) if pid in names])
        nba = {p: first[y].get(find(v[0][4])) for p, v in L.items()}
        for mth, yr in ((12, y - 1), (1, y), (2, y), (3, y)):
            for dd in (1, 15):
                d = dt.date(yr, mth, dd)
                for p, v in L.items():
                    past = [g for g in v if g[0] < d]
                    rec = [g for g in past if (d - g[0]).days <= 30]
                    if len(rec) < 3: continue
                    f = nba.get(p)
                    if f and f < d: continue
                    mn = sum(g[1] for g in past); l10 = past[-10:]; m10 = sum(g[1] for g in l10)
                    if mn <= 0 or m10 <= 0: continue
                    a = age.get(p) or 24.0
                    base = [a, (a - 24) ** 2, len(past), mn / len(past), 36 * sum(g[2] for g in past) / mn]
                    new = [m10 / len(l10) - base[3], 36 * sum(g[2] for g in l10) / m10 - base[4],
                           36 * sum(g[3] for g in l10) / m10 - 36 * sum(g[3] for g in past) / mn]
                    rows.append((y, str(d), base, new, 1.0 if f and 0 <= (f - d).days < 30 else 0.0))
    S = np.array([r[0] for r in rows]); D = np.array([r[1] for r in rows]); Y = np.array([r[4] for r in rows])
    XB = np.array([r[2] for r in rows]); XN = np.array([r[2] + r[3] for r in rows])
    print('rows', len(rows), 'rate', round(float(Y.mean()), 4), {int(s): (int((S == s).sum()), round(float(Y[S == s].mean()), 3)) for s in sorted(set(S))}, flush=True)
    ll = {}
    for nm, X in (('base', XB), ('new', XN)):
        l = np.full(len(Y), np.nan)
        for s in range(2021, 2026):
            tr, te = S < s, S == s
            if not te.any() or tr.sum() < 300: continue
            mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
            b = GC.logit_fit((X[tr] - mu) / sd, Y[tr])
            p = np.clip(GC.sig(GC.lin(b, (X[te] - mu) / sd)), 1e-4, 1 - 1e-4)
            l[te] = -(Y[te] * np.log(p) + (1 - Y[te]) * np.log(1 - p))
        ll[nm] = l
    d = ll['new'] - ll['base']
    res = {'n': len(rows), 'rate': round(float(Y.mean()), 4)}
    for nm, k in (('tune', np.isin(S, (2021, 2022))), ('held', S >= 2023)):
        k = k & ~np.isnan(d)
        p = C.paired(d[k], D[k]); ss = sorted(set(S[k]))
        res[nm] = {'n': int(k.sum()), 'll0': round(float(ll['base'][k].mean()), 5), 'll1': round(float(ll['new'][k].mean()), 5), 'd': round(p['d'], 5), 't': round(p['t'], 2),
                   'clusters': p['k'], 'seasonsLower': int(sum(d[k & (S == s)].mean() < 0 for s in ss)), 'seasons': len(ss)}
    res['p'] = C.p2(res['held']['t']) if res['held']['t'] < 0 else 1.0
    res['pass_pre_holm'] = bool(res['held']['t'] <= -2 and res['tune']['d'] < 0 and res['held']['seasonsLower'] * 2 > res['held']['seasons'])
    print(json.dumps(res, indent=1))
    json.dump(res, open(os.path.join(C.IMPL, 'gl_hazard.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
