#!/usr/bin/env python3
"""CBB FV driver test of the production-tab metrics (Nov 3 2026, research only; Noah: "test all of the new stuff we're
creating for FV drivers"). Every number the new CBB tabs show (scripts/cbb_tabs.py: stats, WAR leaders, breakouts,
top performers, portal, returning, team talent) is built here for each returner's past board season, from seasons
before it only, and added on its own to the shipped returner driver set (data/cbb_fit.json).

    python3 scripts/cbb_careers_kit.py      # once: scripts/.cache/cbb/careers.json
    python3 scripts/cbb_fv_sweep2.py --pull # once: game logs 2010-25 into scripts/.cache/cbb/advgames
    python3 scripts/cbb_fv_sweep3.py [cand,...]   # -> scripts/data/cbb_fv_sweep3.json
    python3 scripts/cbb_fv_sweep3.py --xbpm [cand,...]   # breakout predictor: the same candidates in the xBPM ridge

Candidates (last season = the season before the board)
  WAR tab     war (wins over replacement: (BPM + 2) x minutes / 40 x .68 x .0124), waa (BPM x the same), war_car (every
              prior season summed), war3 (5/4/3 weighted)
  stats tab   splus (Stat+: BPM against his position's mean / sd, G F C from Barttorvik role, 10%+ minute seasons)
  breakouts   war_gain (WAR last season minus the season before), min_gain (minutes share gain), usg_gain (usage
              gain), lowmin (BPM x (1 - minutes share): efficiency in a small role, the "next breakout" read)
  top perf.   gs_pg (Game Score a game), gs40 (Game Score a 40 minutes, shrunk to the mean by 300), gs_max (best game),
              big_games (log 1 + games with Game Score 20+); Barttorvik game logs, seasons 2010 on
  returning   opp (minutes share his coming team lost from last season: the opportunity), mates_war (returning
              teammates' WAR last season on his coming team: the competition for minutes)
  talent      tal_team (mean recruiting -ln rank of the coming team's eight best-ranked players)
  portal      tr_up (transfer from a non-power to a power conference), tr_down (the reverse)
Gate (cbb_fv_sweep2's): (1) 2009-16 boards out of fold under three fold rules (whole college classes, two player
splits): gain in each, >= 4/5 folds, player-clustered t >= 2; (2) fit 2009-16, held 2017-19 boards on the horizon
outcome: deviance gain and the top 10 / 25 / 50 not worse; (3) forward 2020-23 boards the same. Pass = all three."""
import gzip, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F
import cbb_fv_sweep2 as S2

OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_fv_sweep3.json')
ADV = os.path.join(D.CACHE, 'advgames')
POSMAP = {'Pure PG': 'G', 'Scoring PG': 'G', 'Combo G': 'G', 'Wing G': 'G', 'Wing F': 'F', 'Stretch 4': 'F', 'PF/C': 'C', 'C': 'C'}
POWER = {'ACC', 'B10', 'B12', 'SEC', 'BE', 'P12'}
WPP = 0.01243        # wins a point, cbb_tabs.py fit on 2025-26 team-seasons
CANDS = ['war', 'waa', 'war_car', 'war3', 'splus', 'war_gain', 'min_gain', 'usg_gain', 'lowmin', 'gs_pg', 'gs40', 'gs_max',
         'big_games', 'opp', 'mates_war', 'tal_team', 'tr_up', 'tr_down']
CTX = {}
NEWC = '--new' in sys.argv     # --xbpm --new: newcomers' xBPM (team context candidates only)


def mins(s):
    return (s['mp'] or 0) * (s['gp'] or 0)


def war_of(s, repl=-2.0):
    return ((s['bpm'] or 0) - repl) * mins(s) / 40 * 0.68 * WPP if s['bpm'] is not None else 0.0


def game_scores():
    """(pid, year) -> (games, Game Score sum, minutes, best, games at 20+)"""
    out = {}
    if not os.path.isdir(ADV): return out
    for fn in sorted(os.listdir(ADV)):
        if not fn.endswith('.json.gz'): continue
        acc = defaultdict(lambda: [0, 0.0, 0.0, -99.0, 0])
        for g in json.load(gzip.open(os.path.join(ADV, fn))):
            try:
                fgm, fga = g[23] + g[25], g[24] + g[26]
                gs = g[33] + .4 * fgm - .7 * fga - .4 * (g[28] - g[27]) + .7 * g[34] + .3 * g[35] + g[38] + .7 * g[36] + .7 * g[39] - .4 * g[42] - g[37]
            except TypeError:
                continue
            a = acc[(str(g[51]), int(g[52]))]
            a[0] += 1; a[1] += gs; a[2] += g[8] or 0; a[3] = max(a[3], gs); a[4] += gs >= 20
        out.update(acc)
    return out


def team_maps(careers):
    """(team, year) -> {pid: minutes}, BPM, rg_lrk; and the Stat+ norms"""
    roster = defaultdict(dict); war = {}; rec = {}
    acc = defaultdict(list)
    for c in careers:
        g = c.get('rec') or {}
        lr = [-math.log(min(x, 500)) for x in (g.get('on3rk'), g.get('rk247')) if x]
        rl = float(np.mean(lr)) if lr else -math.log(600)
        for s in c['seasons']:
            k = (s['team'], s['year'])
            roster[k][c['pid']] = mins(s)
            war[(c['pid'], s['year'])] = war_of(s)
            rec[(c['pid'], s['year'])] = rl
            if s['bpm'] is not None and (s['min_per'] or 0) >= 10 and s['year'] <= 2016:
                acc[POSMAP.get(s['role'], 'F')].append((s['bpm'], mins(s)))
    norms = {}
    for p, xs in acc.items():
        b = np.array(xs); w = b[:, 1]; mu = (b[:, 0] * w).sum() / w.sum()
        norms[p] = (mu, math.sqrt(((b[:, 0] - mu) ** 2 * w).sum() / w.sum()))
    return roster, war, rec, norms


def team_ctx(c, i, f):
    """the coming team's context (history rosters list the players who played that season)"""
    s = c['seasons'][i]; Y = s['year']; pid = c['pid']
    R, W, RC = CTX['roster'], CTX['war'], CTX['rec']
    last = R.get((s['team'], Y - 1), {})
    now = R.get((s['team'], Y), {})
    tot = sum(last.values())
    f['opp'] = (sum(m for q, m in last.items() if q not in now) / tot) if tot else None
    f['mates_war'] = sum(W.get((q, Y - 1), 0.0) for q in now if q != pid and q in last)
    rl = sorted((RC.get((q, Y), -math.log(600)) for q in now if q != pid), reverse=True)[:8]
    f['tal_team'] = float(np.mean(rl)) if rl else None
    return f


def extra(c, i, f):
    if i == 0:
        return team_ctx(c, i, f)
    s = c['seasons'][i]; prev = c['seasons'][:i]; p = prev[-1]; Y = s['year']; pid = c['pid']
    R, W, RC, N, GS = CTX['roster'], CTX['war'], CTX['rec'], CTX['norms'], CTX['gs']
    f['war'] = war_of(p)
    f['waa'] = war_of(p, 0.0)
    f['war_car'] = sum(war_of(r) for r in prev)
    ws = [5, 4, 3]
    f['war3'] = sum(w * war_of(r) for w, r in zip(ws, reversed(prev[-3:]))) / sum(ws[:len(prev[-3:])])
    mu, sd = N.get(POSMAP.get(p['role'], 'F'), N['F'])
    f['splus'] = 100 + 25 * ((p['bpm'] or 0) - mu) / sd
    if len(prev) >= 2:
        q = prev[-2]
        f['war_gain'] = f['war'] - war_of(q)
        f['min_gain'] = (p['min_per'] or 0) - (q['min_per'] or 0)
        f['usg_gain'] = (p['usg'] or 0) - (q['usg'] or 0)
    else:
        f['war_gain'] = f['min_gain'] = f['usg_gain'] = 0.0
    f['lowmin'] = (p['bpm'] or 0) * (1 - (p['min_per'] or 0) / 100)
    g = GS.get((str(pid), p['year']))
    if g and g[0] >= 5:
        f['gs_pg'] = g[1] / g[0]
        f['gs40'] = F.shrink(g[1] / max(g[2], 1) * 40, g[2], 8.0, 300)
        f['gs_max'] = g[3]
        f['big_games'] = math.log1p(g[4])
    elif p['year'] >= 2010:
        f['gs_pg'] = f['gs40'] = f['gs_max'] = f['big_games'] = None
    else:
        f['gs_pg'] = f['gs40'] = f['gs_max'] = f['big_games'] = None
    team_ctx(c, i, f)
    moved = p['team'] != s['team']
    pc, nc = p['conf'] in POWER, s['conf'] in POWER
    f['tr_up'] = 1.0 if moved and nc and not pc else 0.0
    f['tr_down'] = 1.0 if moved and pc and not nc else 0.0
    return f


def xbpm_test(careers, cands):
    """breakout predictor: each candidate added to the xBPM ridge (cbb_fit.xbpm_fit: RET_CANDS, lambda 50, rows weighted
    by minutes to 600) for the board season's college BPM. 5-fold player CV on 2010-19, then fit 2010-19 and score
    2020-26 forward; weighted squared error, player-clustered t."""
    rows = []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2010 <= s['year'] <= 2026) or (i == 0) != NEWC or s['bpm'] is None: continue
            mpt = mins(s)
            if mpt < 100: continue
            rows.append({'pid': c['pid'], 'year': s['year'], 'y': s['bpm'], 'w': min(600, mpt) / 600, 'f': extra(c, i, F.features(c, i))})
    def fit_pred(tr, te, cols):
        X = F.matrix(tr, cols); std = F.Std(X); Z = std(X)
        A = np.hstack([np.ones((len(Z), 1)), Z]); P = np.eye(A.shape[1]) * 50; P[0, 0] = 0
        w = np.array([r['w'] for r in tr]); y = np.array([r['y'] for r in tr])
        b = np.linalg.solve((A * w[:, None]).T @ A + P, (A * w[:, None]).T @ y)
        Zt = std(F.matrix(te, cols)); return np.hstack([np.ones((len(Zt), 1)), Zt]) @ b
    tune = [r for r in rows if r['year'] <= 2019]; fwd = [r for r in rows if r['year'] >= 2020]
    fo = np.array([F.fold_of(r['pid']) for r in tune])
    def cv(cols):
        e = np.zeros(len(tune))
        for k in range(F.FOLDS):
            tr = [r for r, f in zip(tune, fo) if f != k]; te = np.where(fo == k)[0]
            e[te] = fit_pred(tr, [tune[j] for j in te], cols) - np.array([tune[j]['y'] for j in te])
        return e
    def score(e0, e1, rs, groups):
        w = np.array([r['w'] for r in rs]); d = w * (e0 ** 2 - e1 ** 2)
        return {'gain': round(float(d.sum() / w.sum()), 4), 't': round(S2.ctstat(d, [r['pid'] for r in rs]), 2),
                'groups': f"{sum(d[groups == g].sum() > 0 for g in np.unique(groups))}/{len(np.unique(groups))}",
                'rmse': round(float(np.sqrt((w * e1 ** 2).sum() / w.sum())), 4)}
    base = list(F.NEW_CANDS if NEWC else F.RET_CANDS)
    e0 = cv(base); f0 = fit_pred(tune, fwd, base) - np.array([r['y'] for r in fwd])
    yrs = np.array([r['year'] for r in fwd])
    w = np.array([r['w'] for r in tune]); wf = np.array([r['w'] for r in fwd])
    out = {'rows': [len(tune), len(fwd)], 'base_rmse': [round(float(np.sqrt((w * e0 ** 2).sum() / w.sum())), 4), round(float(np.sqrt((wf * f0 ** 2).sum() / wf.sum())), 4)], 'cands': {}}
    print('xBPM base RMSE (cv 2010-19, fwd 2020-26):', out['base_rmse'], 'rows', out['rows'])
    for cnd in cands:
        cols = base + cnd.split('+')
        a = score(e0, cv(cols), tune, fo)
        b = score(f0, fit_pred(tune, fwd, cols) - np.array([r['y'] for r in fwd]), fwd, yrs)
        ok = a['gain'] > 0 and a['t'] >= 2 and int(a['groups'].split('/')[0]) >= 4 and b['gain'] > 0 and b['t'] >= 2
        out['cands'][cnd] = {'cv': a, 'fwd': b, 'pass': ok}
        print(f"  {cnd:10s} {'PASS' if ok else 'fail'} cv {a} | fwd {b}"); sys.stdout.flush()
    return out


def main():
    careers = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(careers)
    for c in careers: c['nba']['fvx'] = F.xpm_fv(c, thr)
    F.horizon_fv(careers)
    roster, war, rec, norms = team_maps(careers)
    CTX.update(roster=roster, war=war, rec=rec, norms=norms, gs=game_scores())
    print('Stat+ norms', {k: tuple(round(x, 2) for x in v) for k, v in norms.items()}, 'game-score seasons', len(CTX['gs']))
    if '--xbpm' in sys.argv:
        pick = [a for a in sys.argv[1:] if not a.startswith('-')]
        res = xbpm_test(careers, pick[0].split(',') if pick else CANDS)
        prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
        prev['xbpm_new' if NEWC else 'xbpm'] = res
        json.dump(prev, open(OUT, 'w'), indent=1)
        return
    fitj = json.load(open(os.path.join(D.ROOT, 'data', 'cbb_fit.json')))
    M = fitj['models']['returner']; F.TOP_MEAN = M['topMean']
    rows, hr = [], []
    for c in careers:
        for i, s in enumerate(c['seasons']):
            if not (2009 <= s['year'] <= 2023) or i == 0: continue
            f = extra(c, i, F.features(c, i))
            r = {'pid': c['pid'], 'name': c['name'], 'year': s['year'], 'y': c['nba']['fvx'], 'yh': c['nba']['fvh'], 'last': c['last'],
                 'cls': (c['last'] - 2009) % F.FOLDS, 'f': f}
            if s['year'] in F.TRAIN and c['last'] <= 2020: rows.append(r)
            elif s['year'] >= 2017 and c['nba']['fvh'] is not None: hr.append(r)
    seen = {r['pid'] for r in rows}
    hr = [r for r in hr if r['pid'] not in seen]
    print(f'returner rows: train {len(rows)}, held 2017-19 {sum(r["year"] <= 2019 for r in hr)}, fwd 2020-23 {sum(r["year"] >= 2020 for r in hr)}')
    pick = sys.argv[1].split(',') if len(sys.argv) > 1 and not sys.argv[1].startswith('-') else CANDS
    nba = np.array([r['y'] >= 30 for r in rows])
    for cnd in pick:
        v = np.array([r['f'].get(cnd) if r['f'].get(cnd) is not None else np.nan for r in rows], dtype=float)
        bp = np.array([r['f']['bpm'] for r in rows]); ok = ~np.isnan(v)
        print(f'  {cnd}: sd {np.nanstd(v):.3f}, mean NBA {np.nanmean(v[nba]):+.3f} vs non {np.nanmean(v[~nba]):+.3f}, '
              f'r with BPM {np.corrcoef(v[ok], bp[ok])[0, 1]:+.2f}, missing {int((~ok).sum())}')
    res = {}; cvc = {}; hc = {}
    prev = json.load(open(OUT)) if os.path.exists(OUT) else {}
    res.update(prev.get('results', {}))
    for cnd in pick:
        a = S2.cv(rows, M['kept'], M['lam'], cnd, cvc)
        b = S2.held(rows, hr, M['kept'], M['lam'], cnd, hc)
        cv_ok = all(x['gain'] > 0 and x['folds'] >= 4 and x['t'] >= 2 for x in a.values())
        top_ok = lambda h: h['gain'] > 0 and all(h[k][1] >= h[k][0] for k in ('top10', 'top25', 'top50'))
        res[cnd] = {'cv': a, **b, 'pass': bool(cv_ok and top_ok(b['held']) and top_ok(b['fwd']))}
        print(cnd, 'PASS' if res[cnd]['pass'] else 'fail', json.dumps(res[cnd]))
        sys.stdout.flush()
    prev.update({'asof': __import__('datetime').date.today().isoformat(), 'kept': M['kept'], 'results': res})
    json.dump(prev, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
