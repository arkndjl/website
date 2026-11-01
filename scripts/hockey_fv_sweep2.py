#!/usr/bin/env python3
"""Hockey prospects FV driver sweep, Nov 1 2026 (research only; Noah: "any more stat/qualitative proxies?").
Rebuilds the live draft and stage models from the frozen rows (scripts/data/hockey_rows.json.gz; stages with nany,
comps and the preseason share as data/hockey_fit.json has them) and offers each new constructed proxy on top:

  club   junior/college/European club development: the club's earlier picks' outcome (as known at the grading date:
         WAR seasons up to then) over the draft model's out-of-class grade, weighted by how much of their window is
         in, shrunk. Rolling: only classes drafted before the graded class (stage k: as of season draft + k).
  org    the same for the drafting NHL organisation, offered in the stages (the draft-model version failed Oct 31).
  dur    durability: games played (all club lines) over the main league's schedule that season; dmin the lowest
         share in seasons 1..k; dlow any season under half.
  sPP / sPPg / sESg  CHL usage in a stage season: power-play share of points, its change since the draft year,
         even-strength NHLe change since the draft year (HockeyTech; QMJHL names fixed since the Oct 24 run).
  lvl / proY  competition step-up: ln(stage league factor / draft league factor); pro games before 21.
  esAge  draft-year CHL even-strength points a game over the league-season norm for his age (all CHL players).

Gate (each candidate on top of the stage's live kept set): class-out t >= 2 and 8/12 wins, top-64 picks MSE and
Spearman not worse, forward (fit 2008-15, grade 2016-19) MSE, top-64 MSE and top-64 Spearman not worse.

    python3 scripts/hockey_fv_drivers.py --pull     # landing pages + CHL seasons -> scripts/.cache/hockey
    python3 scripts/hockey_fv_sweep2.py             # -> scripts/.cache/hockey/sweep2.json
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hockey_prospects as H
import hockey_fv_drivers as HD
import names as NM
import nhl_data as D

OUT = os.path.join(H.CACHE, 'sweep2.json')
SHRINK = 8.0          # club / org shrink, weighted picks (fixed before testing)


def tval(d):
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0


def evalc(F, y, cls, picks, base, c):
    s0, _ = H.score(F, y, cls, base)
    s1, _ = H.score(F, y, cls, base + [c])
    d = s0 - s1
    c0 = HD.checks(F, y, cls, picks, base); c1 = HD.checks(F, y, cls, picks, base + [c])
    X = np.array([[f[k] for k in base + [c]] for f in F]); b = H.ols(X, y)
    o = {'gain': round(float(d.mean()), 3), 't': round(tval(d), 2), 'wins': int((d > 0).sum()), 'of': len(d),
         'coef': round(float(b[-1]), 3), 'nz': int(sum(1 for f in F if f[c] != 0)), 'mse0': round(float(s0.mean()), 2),
         'dTopMse': round(c1['topMse'] - c0['topMse'], 3), 'dTopRho': round(c1['topRho'] - c0['topRho'], 4),
         'dFwdMse': round(c1['fwdMse'] - c0['fwdMse'], 3), 'dFwdTopMse': round(c1['fwdTopMse'] - c0['fwdTopMse'], 3),
         'dFwdTopRho': round(c1['fwdTopRho'] - c0['fwdTopRho'], 4)}
    o['pass'] = bool(o['t'] >= 2 and o['wins'] >= 8 and o['dTopMse'] <= 0 and o['dTopRho'] >= 0 and o['dFwdMse'] <= 0
                     and o['dFwdTopMse'] <= 0 and o['dFwdTopRho'] >= 0)
    return o


# -- truncated outcomes (what was known at a date) --------------------------------------------------------------
def trunc_fv(r, W, sc, asof):
    """outcome FV from WAR seasons year+1 .. min(year+7, asof) (season end years): what was known by June of asof"""
    wins, gps, gsx = [], 0, []
    for S in range(r['year'] + 1, min(r['year'] + H.WINDOW, asof) + 1):
        q = W.get(S, {}).get(r.get('id'))
        if q:
            wins.append(q.get('war') or 0.0); gps += q.get('gp') or 0; gsx.append(q.get('gsax') or 0.0)
    t = {'G': r['G'], 'nhl_gp': gps, 'peak': sum((sorted(wins, reverse=True) + [0, 0, 0])[:3]) / 3,
         'gpeak': sum((sorted(gsx, reverse=True) + [0, 0, 0])[:3]) / 3}
    return H.fv_of(t, sc)


def club_key(r):
    lg, cl = (r.get('league') or '').upper(), r.get('club') or ''
    if 'U-18' in cl or 'NTDP' in lg or 'U18' in cl:
        return ('NTDP', 'USA U-18')
    return (lg, cl) if cl else None


def dev_table(rows, W, sc, fv0, keyf):
    """{asof: {key: (sum w*res, sum w)}}: for each date, earlier classes' truncated outcomes over the draft grade
    (expectation refit for each elapsed n on that class alone, so nothing later leaks in)"""
    by = {}
    for r in rows:
        by.setdefault(r['year'], []).append(r)
    cache = {}
    out = {}
    for asof in range(H.FIRST, 2027):
        acc = {}
        for e in range(H.FIRST, asof):
            n = asof - e
            rs = [r for r in by.get(e, []) if id(r) in fv0]
            if len(rs) < 30:
                continue
            yt = np.array([trunc_fv(r, W, sc, asof) for r in rs]); x = np.array([fv0[id(r)] for r in rs])
            A = np.column_stack([np.ones(len(x)), x]); b = np.linalg.lstsq(A, yt, rcond=None)[0]
            res = yt - A @ b
            w = min(n, H.WINDOW) / H.WINDOW
            for r, v in zip(rs, res):
                k = keyf(r)
                if k is None:
                    continue
                a = acc.setdefault(k, [0.0, 0.0]); a[0] += w * v; a[1] += w
        out[asof] = acc
    return out


def dev_of(T, key, asof):
    a = T.get(asof, {}).get(key)
    return 0.0 if not a else a[0] / (a[1] + SHRINK)


def oracle_table(rows, sc, fv0, keyf):
    """diagnostic only (leaks later classes): club mean residual of full outcomes, own class left out"""
    acc = {}
    for r in rows:
        if id(r) in fv0 and r['year'] <= H.LAST_FIT and keyf(r):
            acc.setdefault(keyf(r), []).append((r['year'], H.fv_of(r, sc) - fv0[id(r)]))
    return acc


def oracle_of(A, key, own):
    v = [x for c, x in A.get(key, []) if c != own]
    return sum(v) / (len(v) + SHRINK) if v else 0.0


# -- CHL league-age norms --------------------------------------------------------------------------------------
def age_norms(T):
    """{(lg, yr, age floor at Sep 15 of yr-1): mean even-strength points a game}, players with 20+ GP"""
    N = {}
    for (lg, yr), t in T.items():
        for p in t['players']:
            if p['gp'] < 20 or not p['birth']:
                continue
            a = H.age_at(p['birth'], yr - 1)
            if a is None:
                continue
            N.setdefault((lg, yr, int(a)), []).append((p['pts'] - p['ppp'] - p['shp']) / p['gp'])
    return {k: float(np.mean(v)) for k, v in N.items() if len(v) >= 10}


def chl_ids():
    """{(league, end year, birth): [(name, player id)]} from the cached topscorer tables"""
    import datetime as dt
    M = {}
    for fn in os.listdir(HD.CHLD):
        c, yr = fn[:-5].split('_')
        for p in json.load(open(os.path.join(HD.CHLD, fn))) or []:
            try:
                bd = dt.datetime.strptime(p.get('birthdate') or '', '%b %d, %Y').date().isoformat()
            except ValueError:
                continue
            nm = p['name']
            if ', ' in nm:
                a, _, b = nm.partition(', '); nm = f'{b} {a}'
            M.setdefault((HD.HTLG[c], int(yr), bd), []).append((nm, str(p.get('player_id'))))
    return M


GBG = os.path.join(H.CACHE, 'gbg')
HTC = {'OHL': 'ohl', 'WHL': 'whl', 'QMJHL': 'lhjmq'}


def gbg_pull(rows):
    """HockeyTech game-by-game logs of every CHL pick in his draft year and the season after (one request a
    player-season) plus each league-season's schedule -> scripts/.cache/hockey/gbg"""
    import re
    from concurrent.futures import ThreadPoolExecutor
    os.makedirs(GBG, exist_ok=True)
    B = HD.HT
    sid = {}
    for c, k in HD.HTKEY.items():
        for s in (HD._get(B % (k, c) + '&view=seasons') or {}).get('SiteKit', {}).get('Seasons') or []:
            m = re.match(r'(\d{4}) ?- ?(\d{2,4}) \|? ?Regular Season$', s['season_name'].strip())
            if m:
                sid[(HD.HTLG[c], int(m.group(1)) + 1)] = s['season_id']
    IDS = chl_ids()
    jobs = set()
    for r in rows:
        if r['G'] or not r.get('birth'):
            continue
        for j, q in ((0, r.get('d0')), (1, (r.get('post') or {}).get(1))):
            if q and q['lg'] in H.CHL and (q['lg'], r['year'] + j) in sid:
                c = [i for nm, i in IDS.get((q['lg'], r['year'] + j, r['birth']), []) if NM.same(nm, r['name'])]
                if len(c) == 1:
                    jobs.add((q['lg'], c[0], sid[(q['lg'], r['year'] + j)]))
    def one(j):
        lg, pid, s = j
        fn = os.path.join(GBG, f'{HTC[lg]}_{pid}_{s}.json')
        if not os.path.exists(fn):
            d = HD._get(B % (HD.HTKEY[HTC[lg]], HTC[lg]) + f'&view=player&category=gamebygame&player_id={pid}&season_id={s}')
            g = ((d or {}).get('SiteKit', {}).get('Player') or {}).get('games')
            if g is not None:
                json.dump([[x.get('date_played'), x.get('player_team'), int(x.get('goals') or 0), int(x.get('assists') or 0),
                            int(x.get('power_play_goals') or 0)] for x in g], open(fn, 'w'), separators=(',', ':'))
    def sched(k):
        lg, s = k
        fn = os.path.join(GBG, f'{HTC[lg]}_sched_{s}.json')
        if not os.path.exists(fn):
            d = HD._get(B % (HD.HTKEY[HTC[lg]], HTC[lg]) + f'&view=schedule&season_id={s}')
            g = (d or {}).get('SiteKit', {}).get('Schedule')
            if g is not None:
                json.dump([[x.get('date_played'), x.get('home_team'), x.get('visiting_team')] for x in g], open(fn, 'w'), separators=(',', ':'))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(sched, sorted({(lg, s) for lg, _, s in jobs})))
        list(ex.map(one, sorted(jobs)))
    print(len(jobs), 'player-seasons;', len(os.listdir(GBG)), 'files')
    return sid, IDS


def gbg_feats(r, j, sid, IDS):
    """(trajectory, longest run of his team's games missed, games missed share) for his CHL season draft year + j"""
    q = r.get('d0') if j == 0 else (r.get('post') or {}).get(1)
    if r['G'] or not q or q['lg'] not in H.CHL or (q['lg'], r['year'] + j) not in sid:
        return None
    s = sid[(q['lg'], r['year'] + j)]
    c = [i for nm, i in IDS.get((q['lg'], r['year'] + j, r.get('birth')), []) if NM.same(nm, r['name'])]
    fn = os.path.join(GBG, f'{HTC[q["lg"]]}_{c[0]}_{s}.json') if len(c) == 1 else None
    sf = os.path.join(GBG, f'{HTC[q["lg"]]}_sched_{s}.json')
    if not fn or not os.path.exists(fn) or not os.path.exists(sf):
        return None
    g = json.load(open(fn)); S = json.load(open(sf))
    if len(g) < 20:
        return None
    # his games by team stint; the team's schedule dates between his first and last game there
    played = {}
    for d, t, gl, a, ppg in g:
        played.setdefault(t, set()).add(d)
    run, miss, tot = 0, 0, 0
    for t, ds in played.items():
        td = sorted(x[0] for x in S if t in (x[1], x[2]) and x[0])
        if not td:
            continue
        lo, hi = min(ds), max(ds)
        cur = 0
        for d in td:
            if d < lo or d > hi:
                continue
            tot += 1
            if d in ds:
                cur = 0
            else:
                cur += 1; miss += 1; run = max(run, cur)
    # trajectory: points a game in the second half of his team's schedule over the first half (by date)
    allt = sorted({x[0] for x in S if x[0] and any(t in (x[1], x[2]) for t in played)})
    mid = allt[len(allt) // 2] if allt else None
    h1 = [gl + a for d, t, gl, a, _ in g if d < mid]; h2 = [gl + a for d, t, gl, a, _ in g if d >= mid]
    traj = (np.mean(h2) - np.mean(h1)) / 2 if len(h1) >= 10 and len(h2) >= 10 else None
    return {'traj': None if traj is None else 82 * H.nhle_of(q['lg']) * traj / 10, 'run': run, 'miss': miss / max(tot, 1)}


def main():
    W = H.war_tables()
    rows = HD.build_rows()          # frozen rows + landing-page and CHL detail (r['x'])
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr]); picks = np.array([r['pick'] for r in tr])
    fit = json.load(open(H.FIT))
    F = [H.feats(r) for r in tr]
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    kept = fit['kept']
    s_all, p0 = H.score(F, y, cls, kept)
    print('draft model', kept, 'mse', round(s_all.mean(), 2), '(fit json', fit['mse'], ')', flush=True)
    fv0 = {id(r): float(p) for r, p in zip(tr, p0)}
    # out-of-class grades for 2020-26 classes too (a fit on 2008-19), for the rolling tables' later dates
    X = np.array([[f[c] for c in kept] for f in F]); bfull = H.ols(X, y)
    for r in rows:
        if r['year'] > H.LAST_FIT:
            f = H.feats(r); f['cs'] = 0.0
            fv0[id(r)] = float(np.clip(H.pred(bfull, [[f[c] for c in kept]])[0], 20, 80))

    # schedules (most games any pick had in a league-season), for durability
    sched = {}
    for r in rows:
        for s in (HD.full(r['id']) or {}).get('seasons') or []:
            if s.get('gameTypeId') == 2 and not H.TOURN.match(s.get('leagueAbbrev') or ''):
                k = (s['leagueAbbrev'], s['season']); sched[k] = max(sched.get(k, 0), s.get('gamesPlayed') or 0)
    schedF = {}          # the same from the frozen main lines only (what the daily build has)
    for r in rows:
        for j, q in list(r['post'].items()) + [(0, r.get('d0'))]:
            if q:
                kk_ = (q['lg'], r['year'] + int(j)); schedF[kk_] = max(schedF.get(kk_, 0), q['gp'])
    T = HD.chl_tables(); NORM = age_norms(T)
    print('CHL tables', len(T), 'norms', len(NORM), flush=True)

    CT = dev_table(rows, W, sc, fv0, club_key)
    OT = dev_table(rows, W, sc, fv0, lambda r: r.get('team'))
    OA = oracle_table(rows, sc, fv0, club_key)
    res = {'draft': {}, 'stages': {}}

    # -- draft model candidates
    for f, r in zip(F, tr):
        k = club_key(r)
        f['club'] = dev_of(CT, k, r['year']) if k else 0.0
        f['clubO'] = oracle_of(OA, k, r['year']) if k else 0.0
        c0 = r['x'].get('chl0'); d0 = r.get('d0') or {}
        f['esAge'] = 0.0
        if c0 and not r['G'] and r.get('birth'):
            a = H.age_at(r['birth'], r['year'] - 1)
            nm = NORM.get((d0['lg'], r['year'], int(a))) if a is not None else None
            if nm is not None:
                f['esAge'] = 82 * H.nhle_of(d0['lg']) * (c0['esppg'] - nm) / 10
    SID, IDS = gbg_pull(rows)
    GF = {(id(r), j): gbg_feats(r, j, SID, IDS) for r in tr for j in (0, 1)}
    print('game logs', sum(1 for v in GF.values() if v), flush=True)
    for f, r in zip(F, tr):
        g = GF[(id(r), 0)]
        f['traj'] = g['traj'] if g and g['traj'] is not None else 0.0
        f['run'] = min(g['run'], 20) / 10 if g else 0.0          # longest absence, 10-game units
        f['miss'] = g['miss'] - .08 if g else 0.0
    for c in ['club', 'clubO', 'esAge', 'traj', 'run', 'miss']:
        res['draft'][c] = evalc(F, y, cls, picks, kept, c); print('draft', c, res['draft'][c], flush=True)

    # -- stages: rebuild the live stage rows (onboard population, comps, pnS) and offer each candidate
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
        Fk = [H.stage_feats(r, k, fv0[id(r)]) for r in sub]
        yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
        st = fit['stages'][str(k)]
        kk = list(st['kept']); kplain = list(kk)
        if 'comp' in kk:
            base_nc = kk[:kk.index('comp')]
            pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, base_nc), 20, 80), [H.comp_grp(r) for r in sub], ck)
            for f, r, c in zip(Fk, sub, ck):
                f['comp'] = H.comp_of(pool, f, H.comp_grp(r), own=c)
        if 'pre' in st:
            H.pre_fill(Fk, sub, k); kk = list(st['pre']['kept'])
        s0, _ = H.score(Fk, yk, ck, kk)
        print(f'stage {k} base', kk, 'mse', round(s0.mean(), 2), '(fit json', st.get('pre', st)['mse'], ')', flush=True)
        for f, r in zip(Fk, sub):
            x = r['x']['post']; sk = not r['G']
            ck_ = club_key(r)
            f['club'] = dev_of(CT, ck_, r['year'] + k) if ck_ else 0.0
            f['org'] = dev_of(OT, r.get('team'), r['year'] + k)
            # durability: games over the schedule, each stage season with a line
            sh = []
            for j in range(1, k + 1):
                q = r['post'].get(j); sf = (x.get(j) or {}).get('sf') or {}
                n = sched.get((q['lg'], (r['year'] + j - 1) * 10000 + r['year'] + j)) if q else None
                sh.append(min(sf.get('gp', 0) / n, 1.0) if q and n and n >= 20 else None)
            f['durL'] = sh[-1] - .85 if sk and sh[-1] is not None else 0.0
            v = [s for s in sh if s is not None]
            f['dmin'] = min(v) - .75 if sk and v else 0.0
            f['dlow'] = int(sk and any(s < .5 for s in v))
            q = r['post'].get(k); n = schedF.get((q['lg'], r['year'] + k)) if q else None
            ngp = r['gp_k'].get(k, 0) - r['gp_k'].get(k - 1, 0)
            f['durF'] = min((q['gp'] + (ngp if q['lg'] != 'NHL' else 0)) / n, 1.0) - .85 if sk and q and n and n >= 20 else 0.0
            # CHL usage
            cS, c0 = (x.get(k) or {}).get('chl'), r['x'].get('chl0')
            q = r['post'].get(k); d0 = r.get('d0') or {}
            f['sPP'] = cS['ppsh'] - .3 if sk and cS and cS['ppg'] > 0 else 0.0
            f['sPPg'] = cS['ppsh'] - c0['ppsh'] if sk and cS and c0 else 0.0
            f['sESg'] = (82 * H.nhle_of(q['lg']) * cS['esppg'] - 82 * H.nhle_of(d0['lg']) * c0['esppg']) / 10 if sk and cS and c0 else 0.0
            # step-up
            f['lvl'] = math.log(H.nhle_of(q['lg']) / H.nhle_of(d0['lg'])) if sk and q and d0.get('lg') and H.nhle_of(d0['lg']) > 0 else 0.0
            age_k = (r['age'] or 18.5) + k
            f['proY'] = f['pro'] * max(0.0, 21 - age_k) if sk else 0.0
            g = GF.get((id(r), 1)) if k == 1 else None
            f['strj'] = g['traj'] if g and g['traj'] is not None else 0.0
            f['srun'] = min(g['run'], 20) / 10 if g else 0.0
            f['smiss'] = g['miss'] - .08 if g else 0.0
            f['sESx'] = f['sESg'] - f['nhgrow'] if f['sESg'] else 0.0       # the even-strength part beyond total growth
            f['sESnp'] = f['sESg'] if not f['pro'] else 0.0                 # junior-only, as nhgrow is
        out = {'base': kk, 'mse': round(float(s0.mean()), 2), 'n': len(sub)}
        for c in ['club', 'org', 'durL', 'durF', 'dmin', 'dlow', 'sPP', 'sPPg', 'sESg', 'lvl', 'proY'] + (['strj', 'srun', 'smiss'] if k == 1 else []):
            out[c] = evalc(Fk, yk, ck, pk, kk, c); print(f'  k{k} {c:5s}', out[c], flush=True)
        # robustness for the ones that pass: the plain stage model (used August to the end of the preseason), the
        # ES variants, and on top of total NHLe growth where the stage does not keep it
        for c in ['durL', 'durF', 'dmin', 'sESg']:
            if kplain != kk:
                out[c + '|plain'] = evalc(Fk, yk, ck, pk, kplain, c); print(f'  k{k} {c}|plain', out[c + '|plain'], flush=True)
        for c in ['nhgrow', 'sESx', 'sESnp']:
            out[c] = evalc(Fk, yk, ck, pk, kk, c); print(f'  k{k} {c:5s}', out[c], flush=True)
        if 'nhgrow' not in kk:
            out['sESg|+nhgrow'] = evalc(Fk, yk, ck, pk, kk + ['nhgrow'], 'sESg'); print(f'  k{k} sESg|+nhgrow', out['sESg|+nhgrow'], flush=True)
        res['stages'][k] = out
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


def gate(old_fit):
    """the board's own selection: the old fit's stage models against the refit's (data/hockey_fit.json), same rows"""
    W = H.war_tables()
    rows = H.read_rows(W); H.nhl_so_far(rows, W)
    sc = H.outcome_scale(rows)
    tr = [r for r in rows if H.FIRST <= r['year'] <= H.LAST_FIT]
    y = np.array([H.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    new, old = json.load(open(H.FIT)), json.load(open(old_fit))
    F = [H.feats(r) for r in tr]
    babs = H.ols(np.array([[f[c] for c in H.ABS] for f in F]), y)
    S = H.class_strength(F, cls, babs); H.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    _, p0 = H.score(F, y, cls, new['kept'])
    fv0 = {id(r): float(p) for r, p in zip(tr, p0)}
    out = {}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season() and H.onboard(r, k)]
        yk = np.array([H.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub]); pk = np.array([r['pick'] for r in sub])
        for tag in ('plain', 'pre'):
            res = {}
            for nm, fd in (('old', old), ('new', new)):
                st = fd['stages'][str(k)]
                if tag == 'pre' and 'pre' not in st:
                    continue
                kk = st['pre']['kept'] if tag == 'pre' else st['kept']
                Fk = [H.stage_feats(r, k, fv0[id(r)]) for r in sub]
                if 'comp' in kk:
                    # the pool's residual is from the model as it stood when comps were offered
                    bc = st['kept'][:st['kept'].index('comp')]
                    pool = H.comp_pool(Fk, yk - np.clip(H.loco(Fk, yk, ck, bc), 20, 80), [H.comp_grp(r) for r in sub], ck)
                    for f, r, c in zip(Fk, sub, ck):
                        f['comp'] = H.comp_of(pool, f, H.comp_grp(r), own=c)
                if 'pnS' in kk:
                    H.pre_fill(Fk, sub, k)
                s, _ = H.score(Fk, yk, ck, kk)
                res[nm] = (s, HD.checks(Fk, yk, ck, pk, kk), kk)
            if len(res) < 2:
                continue
            d = res['old'][0] - res['new'][0]
            o = {'old': res['old'][2], 'new': res['new'][2],
                 'mse': [round(float(res['old'][0].mean()), 2), round(float(res['new'][0].mean()), 2)],
                 't': round(tval(d), 2), 'wins': int((d > 0).sum()),
                 **{'d' + a: round(res['new'][1][a] - res['old'][1][a], 4) for a in res['new'][1]}}
            out[f'{k}{tag}'] = o; print(k, tag, o, flush=True)
    return out


if __name__ == '__main__':
    if '--gate' in sys.argv:
        g = gate(sys.argv[sys.argv.index('--gate') + 1])
        json.dump(g, open(os.path.join(H.CACHE, 'sweep2_gate.json'), 'w'), indent=1)
    else:
        main()
