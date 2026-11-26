# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""CFB class-score panel: one row per FBS program and class, each commit's history points, season ratings.
Reads scripts/.cache/classscore/sched (cfbfastR schedules 2005-26), scripts/data/cfb_recruits_cfbd.json.gz,
static/data/cfb-recruits.json (the live points map). Writes scripts/.cache/classscore/cfb_panel.json."""
import csv, gzip, json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import names as N  # noqa: E402
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'classscore'); SCHED = os.path.join(CACHE, 'sched')
P5 = {'SEC', 'Big Ten', 'ACC', 'Big 12', 'Pac-12', 'Pac-10', 'Big East'}
CAP = 28.0


def seasons():
    out = {}
    for y in range(2005, 2027):
        rows = [r for r in csv.DictReader(open(os.path.join(SCHED, f's{y}.csv'))) if r['home_points'] not in ('', 'NA') and r['away_points'] not in ('', 'NA')]
        fbs, name, conf, elo = set(), {}, {}, {}
        for r in sorted(rows, key=lambda r: (r['season_type'] == 'postseason', int(r['week'] or 0))):
            for sd in ('home', 'away'):
                t = r[sd + '_id']; name[t] = r[sd + '_team']
                if r[sd + '_division'] == 'fbs': fbs.add(t); conf[t] = r[sd + '_conference']
                if r[sd + '_postgame_elo'] not in ('', 'NA'): elo[t] = float(r[sd + '_postgame_elo'])
        ids = sorted(fbs); ix = {t: i for i, t in enumerate(ids)}; k = len(ids)
        A, b, w, g = [], [], {t: 0 for t in ids}, {t: 0 for t in ids}
        for r in rows:
            h, a = r['home_id'], r['away_id']
            if h not in ix and a not in ix: continue
            m = float(r['home_points']) - float(r['away_points'])
            row = np.zeros(k + 2)
            row[ix[h] if h in ix else k] += 1; row[ix[a] if a in ix else k] -= 1
            row[k + 1] = 0 if r['neutral_site'] == 'TRUE' else 1
            A.append(row); b.append(max(-CAP, min(CAP, m)))
            for t, won in ((h, m > 0), (a, m < 0)):
                if t in ix: g[t] += 1; w[t] += won
        A, b = np.array(A), np.array(b)
        beta = np.linalg.solve(A.T @ A + np.eye(k + 2) * 1.0, A.T @ b)
        r = beta[:k]; z = (r - r.mean()) / r.std()
        ev = np.array([elo.get(t, np.nan) for t in ids]); ez = (ev - np.nanmean(ev)) / np.nanstd(ev)
        out[y] = {t: {'team': name[t], 'conf': conf[t], 'p4': conf[t] in P5 or name[t] == 'Notre Dame', 'pts': round(float(r[i]), 2), 'z': round(float(z[i]), 4),
                      'wp': round(w[t] / max(1, g[t]), 4), 'g': g[t], 'elo': None if np.isnan(ez[i]) else round(float(ez[i]), 4)} for t, i in ix.items()}
    return out


def points_map():
    """live points (xFV - floor) by composite rating and level: bin means, interpolated"""
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-recruits.json'))); fl = d['floor']
    rows = [x for x in d['class'] + [y for f in d['future'] for y in f['list']] if x.get('comp') and x.get('tid') and x.get('level') in ('P4', 'G5')]
    out = {}
    for lv in ('P4', 'G5'):
        c = np.array([x['comp'] for x in rows if x['level'] == lv]); p = np.array([x['xfv'] - fl for x in rows if x['level'] == lv])
        o = np.argsort(c); c, p = c[o], p[o]
        nb = 24 if lv == 'P4' else 8
        edges = np.unique(np.concatenate([np.quantile(c, np.linspace(0, .9, nb)), np.quantile(c, [.93, .96, .98, .99, 1.0])])) if lv == 'P4' else np.quantile(c, np.linspace(0, 1, nb + 1))
        xs, ys = [], []
        for a, b in zip(edges[:-1], edges[1:]):
            m = (c >= a) & (c <= b)
            if m.sum() >= 5: xs.append(float(c[m].mean())); ys.append(float(p[m].mean()))
        out[lv] = (xs, ys)
    return out, rows, fl


def main():
    S = seasons()
    pm, live, fl = points_map()
    f = lambda c, lv: float(np.interp(c, *pm[lv]))
    # the map at the class level on the live class
    by = {}
    for x in live: by.setdefault((x['tid'], x.get('cls')), []).append(x)
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-recruits.json')))
    a, b = [], []
    for t in d['teams']:
        mine = [x for x in d['class'] if x.get('tid') == t['tid'] and x.get('comp') and x.get('level') in ('P4', 'G5')]
        if len(mine) >= 5: a.append(sum(x['xfv'] - fl for x in mine)); b.append(sum(f(x['comp'], x['level']) for x in mine))
    chk = {'teams': len(a), 'r': round(float(np.corrcoef(a, b)[0, 1]), 4), 'slope': round(float(np.polyfit(b, a, 1)[0]), 3)}
    pl = [(x['xfv'] - fl, f(x['comp'], x['level'])) for x in live]
    chk['player_r'] = round(float(np.corrcoef(*zip(*pl))[0, 1]), 4)
    print('map check', chk)
    H = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'cfb_recruits_cfbd.json.gz')))
    classes, miss = {}, {}
    for y, rows in H.items():
        y = int(y); ref = S.get(y) or S[max(S)]
        tk = {N.team_key(v['team']): t for t in S[min(max(S), y)] for v in [S[min(max(S), y)][t]]}
        for yy in (y - 1, y + 1, y + 2):
            for t, v in (S.get(yy) or {}).items(): tk.setdefault(N.team_key(v['team']), t)
        cl = {}
        for r in rows:
            nm, rating, school = r[0], r[1], r[4]
            if not school or rating is None: continue
            t = tk.get(N.team_key(school))
            if t is None: miss[school] = miss.get(school, 0) + 1; continue
            lv = 'P4' if (S[min(max(S), y)].get(t) or {'p4': False})['p4'] else 'G5'
            cl.setdefault(t, []).append([nm, rating, round(f(rating, lv), 3)])
        classes[y] = cl
    print('unmatched schools (top)', sorted(miss.items(), key=lambda kv: -kv[1])[:25])
    json.dump({'check': chk, 'seasons': S, 'classes': classes}, open(os.path.join(CACHE, 'cfb_panel.json'), 'w'))
    for y in (2012, 2020): print(y, len(classes[y]), sorted(((sum(p[2] for p in v), (S[y].get(t) or {'team': t})['team'], len(v)) for t, v in classes[y].items()), reverse=True)[:6])


if __name__ == '__main__': main()
