"""Does FV at the mean outcome (the headline since Oct 21 2026, PR #335) do better than the grade as an input to the game
models? Each sport's FV-based team or rookie input is rebuilt twice, once on the grade and once at the mean of its
outcome odds (scripts/fv_dist.py), and scored held out on the shared harness (clustered paired t, scripts/harness.py).
  OMP_NUM_THREADS=1 python3 scripts/fv_mean_games.py cbb      # college basketball preseason prior (fvtop and friends)
  OMP_NUM_THREADS=1 python3 scripts/fv_mean_games.py cfb      # CFB roster prior: returning FV from the rebuilt boards
Writes data/fv_mean_games.json (one block per sport).
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
from fv_dist import at_mean, cbb_z  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'fv_mean_games.json')
r4 = lambda x: None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def save(key, block):
    d = json.load(open(OUT)) if os.path.exists(OUT) else {}
    d[key] = block
    with open(OUT, 'w') as f:
        json.dump(d, f, indent=1, allow_nan=False)


def summ(p):
    return {k: r4(p[k]) if isinstance(p[k], float) else p[k] for k in ('d', 't', 'p', 'n', 'G')}


# ---------------------------------------------------------------- college basketball
def cbb_team_fv(mean):
    """cbb_games.team_fv's terms with each E[FV] at the grade (mean False) or at its outcome mean (fv_dist, the board's
    restatement: class this season, newcomer to D-I, role family)"""
    import csv
    import cbb_games as C
    by = defaultdict(dict)
    for r in csv.DictReader(open('/mnt/project-files/cbb/backtest/research_seasons.csv')):
        by[int(r['year'])][r['pid']] = r
    pos = lambda r: 'G' if r.get('guard') == '1.0' else 'C' if r.get('big') == '1.0' else 'F'
    tx = (lambda e, cls, r: at_mean('cbb', e, cbb_z(cls, False, pos(r), e), scale='rarity')) if mean else (lambda e, cls, r: e)
    out = {}
    for y in range(C.FIRST, C.LAST + 1):
        T = defaultdict(lambda: {'fvw': 0.0, 'fvfr': 0.0, 'es': []})
        for pid, r in by[y].items():
            f = T[r['team']]
            p = by[y - 1].get(pid)
            if p and p['min_per']:
                share = float(p['min_per']) / 100
                e = tx(C.player_fv(C.research_feats(p, r['team']), 'returner'), r['yr'], r)
                f['fvw'] += (e - 20) * share
                f['es'].append(e)
            elif r['yr'] == 'Fr':
                lr = [-math.log(min(float(v), 500)) for v in (r.get('on3rk'), r.get('rk247')) if v not in (None, '', 'nan') and float(v) > 0]
                l = sum(lr) / len(lr) if lr else -math.log(600)
                e = tx(C.player_fv({'rg_lrk': l, 'top': max(0.0, l + math.log(25)), 'top5': max(0.0, l + math.log(5)), 'yr': 1.0}, 'newcomer'), 'Fr', r)
                f['fvfr'] += e - 20
                f['es'].append(e)
        out[str(y)] = {}
        for t, f in T.items():
            es = sorted(f['es'], reverse=True)
            top = lambda k: sum(es[:k]) / len(es[:k]) - 20 if es else 0.0
            out[str(y)][t] = {'fvw': f['fvw'], 'fvfr': f['fvfr'], 'fvtop': top(5), 'fvtop3': top(3), 'fvtop8': top(8),
                              'fvsum': sum(max(0.0, e - 30) for e in es[:10])}
    return out


_CB = {}


def _cbb_walk(pf):
    import cbb_games as C
    C.PRIOR_F = pf
    games, btname, d1s, tprior, avs, P, feats = _CB['args']
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    return C.walk_pred(Xm, y, S, d1)


def cbb(stage=1):
    import multiprocessing as mp
    import cbb_games as C
    F = json.load(open(os.path.join(ROOT, 'data', 'cbb_games_fit.json')))
    P, feats = F['params'], list(F['feats'])
    games, btname, d1s, tprior, avs = C.load_all()
    G0, G1 = cbb_team_fv(False), cbb_team_fv(True)
    # check: the grade rebuild reproduces the shipped fvtop
    diffs = [abs(G0[y][t]['fvtop'] - v['fvtop']) for y in tprior for t, v in tprior[y].items() if t in G0.get(y, {}) and 'fvtop' in v]
    for y in tprior:
        for t, v in tprior[y].items():
            for tag, G in (('G', G0), ('M', G1)):
                g = G.get(y, {}).get(t)
                for k in ('fvw', 'fvfr', 'fvtop', 'fvtop3', 'fvtop8', 'fvsum'):
                    v[k + tag] = round(g[k], 3) if g else 0.0
    base = list(C.PRIOR_F)
    swap = lambda a, b: [b if k == a else k for k in base]
    trials = {
        'base': base,
        'fvtop at mean (for the grade)': swap('fvtop', 'fvtopM'),
        'top 3 at mean': swap('fvtop', 'fvtop3M'), 'top 3 grade': swap('fvtop', 'fvtop3G'),
        'top 8 at mean': swap('fvtop', 'fvtop8M'), 'top 8 grade': swap('fvtop', 'fvtop8G'),
        'top-10 sum over 30 at mean': swap('fvtop', 'fvsumM'), 'top-10 sum over 30 grade': swap('fvtop', 'fvsumG'),
        '+ minutes-weighted FV at mean': base + ['fvwM'], '+ minutes-weighted FV grade': base + ['fvwG'],
        '+ freshmen FV at mean': base + ['fvfrM'], '+ freshmen FV grade': base + ['fvfrG'],
        'fvtop at mean + minutes-weighted at mean': swap('fvtop', 'fvtopM') + ['fvwM'],
    }
    if stage == 2:
        # second pass: freshmen FV at the mean kept (tune t -3.4, held out not worse), the rest on top of it
        b2 = base + ['fvfrM']
        trials = {'base': base, '+ freshmen FV at mean': b2, '+ freshmen FV at mean + minutes-weighted grade': b2 + ['fvwG'],
                  '+ freshmen FV at mean + minutes-weighted at mean': b2 + ['fvwM'], '+ freshmen FV grade + minutes-weighted grade': base + ['fvfrG', 'fvwG'],
                  'freshmen at mean, fvtop at mean': [k if k != 'fvtop' else 'fvtopM' for k in b2]}
    _CB['args'] = (games, btname, d1s, tprior, avs, P, feats)
    names = list(trials)
    with mp.get_context('fork').Pool(4) as pool:
        preds = pool.map(_cbb_walk, [trials[k] for k in names])
    W, rows = C.run_walk(P, games, tprior, btname, d1s, avs)
    D, Xm, y, TX, ty, S, line, tline, d1 = C.matrices(rows, feats)
    pb = preds[0]
    ok = ~np.isnan(pb) & d1
    tune, held = H.season_masks(S, (C.SCORE0, C.TUNE_END), C.TUNE_END + 1, ok)
    day = np.array([g['date'][:10] for g, _, _ in D])
    team = np.array([f"{g['home']}|{g['season']}" for g, _, _ in D])
    cl = [day, team]
    lb = H.ae(pb, y)
    res = {'note': 'preseason prior terms, walk rebuilt; d = candidate minus shipped abs margin error (negative is better), clustered by game day x home team-season',
           'split': f'tune {C.SCORE0}-{C.TUNE_END}, held {C.TUNE_END + 1}-{C.LAST}', 'checkFvtopRebuild': r4(max(diffs) if diffs else None),
           'baseMae': {'tune': r4(lb[tune].mean()), 'held': r4(lb[held].mean())}, 'trials': {}}
    for k, p in zip(names[1:], preds[1:]):
        lc = H.ae(p, y)
        res['trials'][k] = {'prior': trials[k], 'tune': summ(H.paired(lc[tune], lb[tune], [c[tune] for c in cl])),
                            'held': summ(H.paired(lc[held], lb[held], [c[held] for c in cl])),
                            'mae': {'tune': r4(np.nanmean(lc[tune])), 'held': r4(np.nanmean(lc[held]))}}
        print(k, res['trials'][k]['tune'], res['trials'][k]['held'], flush=True)
    save('cbb' if stage == 1 else 'cbb2', res)


# ---------------------------------------------------------------- college football
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'fvmean')
ROS = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ros')


def cfb_rows():
    """every graded board row 2014-25 (node scripts/cfb_fv_refit.mjs --teamfv=..., --wide for 2014-18 on box lines,
    --past for 2019-25 on PFN lines), the board as it stood at the end of each season, at the grade and the mean"""
    w = json.load(open(os.path.join(CACHE, 'wide.json')))
    p = json.load(open(os.path.join(CACHE, 'past.json')))
    g7 = {'QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB'}         # OL, CB and S have PFN lines from 2024 only
    return [r for r in w if r['s'] <= 2018 and r['g'] in g7] + [r for r in p if r['s'] >= 2019 and r['g'] in g7], w


def cfb_rosters():
    """cfbfastR (ESPN) rosters by season: {S: {athlete id: ESPN team id}}, {S: {(name key, team key): athlete id}}"""
    import csv
    import names as NM
    tid, byid, byname = {}, {}, {}
    for y in range(2012, 2027):
        sp = os.path.join(ROS, f's{y}.csv')
        if os.path.exists(sp):
            for r in csv.DictReader(open(sp, encoding='utf-8')):
                for side in ('home', 'away'):
                    if r.get(side + '_id') and r.get(side + '_team'):
                        tid[NM.team_key(r[side + '_team'])] = r[side + '_id']
    for y in range(2012, 2027):
        p = os.path.join(ROS, f'r{y}.csv')
        if not os.path.exists(p):
            continue
        byid[y], byname[y] = {}, {}
        for r in csv.DictReader(open(p, encoding='utf-8')):
            t = tid.get(NM.team_key(r['team']))
            if not t or not r['athlete_id']:
                continue
            byid[y][r['athlete_id']] = t
            k = (NM.key(f"{r['first_name']} {r['last_name']}"), t)
            byname[y][k] = None if k in byname[y] and byname[y][k] != r['athlete_id'] else r['athlete_id']
    return tid, byid, byname


def cfb_team_terms(rows, G):
    """per (S, ESPN team id): the season S-1 board's FV of the players on the team's season S roster (returners and
    transfers in), as team talent. Each term at the grade (G) and the mean (M):
      av    expected NFL AV a season (avOf, the board's value curve) summed over the team's top 22
      top   mean FV of the top 10
      snap  last season's snaps x expected AV, summed (/1000): who played, weighted by the value of what they showed
      ret   av over returners only (no transfers)"""
    import names as NM
    tid, byid, byname = cfb_rosters()
    # PFN school names to ESPN ids: by key, else the majority team of rows whose athlete id the roster resolves
    vote = defaultdict(lambda: defaultdict(int))
    for r in rows:
        if r.get('espn') and r['s'] in byid and str(r['espn']) in byid[r['s']]:
            vote[r['team']][byid[r['s']][str(r['espn'])]] += 1
    team_of = {}
    for r in rows:
        if r['team'] in team_of:
            continue
        t = tid.get(NM.team_key(r['team']))
        if not t and vote[r['team']]:
            t = max(vote[r['team']].items(), key=lambda kv: kv[1])[0]
        team_of[r['team']] = t
    stats = defaultdict(int)
    T = defaultdict(list)                       # (S, team id) -> [(row, returner)]
    for r in rows:
        t0 = team_of.get(r['team'])
        y = r['s']
        if not t0 or y + 1 not in byid:
            stats['noTeam'] += 1
            continue
        aid = str(r['espn']) if r.get('espn') else byname.get(y, {}).get((NM.key(r['name']), t0))
        if not aid:
            stats['noId'] += 1
            # no roster id: back if the same name is on the same school's next roster
            nxt = byname[y + 1].get((NM.key(r['name']), t0))
            if nxt:
                T[(y + 1, t0)].append((r, True))
                stats['backByName'] += 1
            continue
        t1 = byid[y + 1].get(aid)
        if t1:
            T[(y + 1, t1)].append((r, t1 == t0))
            stats['back' if t1 == t0 else 'transfer'] += 1
        else:
            stats['gone'] += 1
    out = {}
    for (S, t), L in T.items():
        if S not in G or t not in G[S]['fbs']:
            continue
        f = {}
        for tag, fk, ak in (('G', 'fvg', 'avg'), ('M', 'fvm', 'avm')):
            srt = sorted(L, key=lambda x: -x[0][fk])
            f['av' + tag] = sum(x[0][ak] for x in srt[:22])
            f['top' + tag] = float(np.mean([x[0][fk] for x in srt[:10]])) if srt else 30.0
            f['snap' + tag] = sum((x[0]['snaps'] or 0) * x[0][ak] for x in srt) / 1000
            f['ret' + tag] = sum(x[0][ak] for x in srt[:22] if x[1])
        out[(S, t)] = f
    return out, dict(stats)


def cfb():
    import cfb_roster_prior as P
    P.coaches = lambda G: {}                    # hcNew failed in the prior's test and isn't used
    G = P.load_games()
    F = P.finals(G)
    B, onT = P.boxes(G)
    RET = P.returning(G, B, onT)
    TAL, _ = P.talent(G)
    X = P.features(G, F, RET, TAL, {})
    rows, wide = cfb_rows()
    TF, stats = cfb_team_terms(rows, G)
    keys = sorted({k for v in TF.values() for k in v})
    cover = {}
    for S in G:
        ids = [(S, t) for t in G[S]['fbs'] if (S, t) in X]
        cover[str(S)] = sum(1 for i in ids if i in TF)
        for k in keys:
            v = np.array([TF.get(i, {}).get(k, np.nan) for i in ids])
            lo = np.nanmin(v) if np.isfinite(v).any() else 0.0
            v = np.where(np.isnan(v), lo, v)             # no graded player back: the season's floor
            z = (v - v.mean()) / (v.std() or 1)
            for i, zz in zip(ids, z):
                X[i][k] = float(zz)
    hy = json.load(open(os.path.join(ROOT, 'data', 'cfb_roster_prior.json')))['hyper']
    run = P.Run(G, F, X, hy['lam'], hy['hfa'], hy['sigma'])
    TUNE, HOLD = P.TUNE, P.HOLD
    ship = ['last', 'tal', 'offRet', 'qbRet', 'offIn']

    def ev(ks):
        # tuning seasons: prior fit leave-one-season-out within them; held out: fit on the tuning seasons
        ae_t, pr_t = [], []
        for S in TUNE:
            a, _, _, pr = run.metrics(ks, [s for s in TUNE if s != S], [S])
            ae_t.append(a); pr_t += pr
        a_h, _, w, pr_h = run.metrics(ks, TUNE, HOLD)
        return np.concatenate(ae_t), a_h, w, pr_t, pr_h

    b = ev(ship)
    cl = lambda pr: [np.array([r['date'][:10] for r, _ in pr]), np.array([f"{r['h']}|{r['S']}" for r, _ in pr])]
    clt, clh = cl(b[3]), cl(b[4])
    # early weeks too: the prior matters most before the games pile up
    wk_t = np.array([r['w'] <= 4 for r, _ in b[3]]); wk_h = np.array([r['w'] <= 4 for r, _ in b[4]])
    res = {'note': 'CFB preseason prior (scripts/cfb_roster_prior.py walk); d = candidate minus shipped abs margin error, clustered by game day x home team-season',
           'split': 'tune 2016-20 (prior fit leave one season out), held 2021-26', 'rowSeasons': 'board rows 2014-18 box-score stand-ins (--wide), 2019-25 PFN (--past)',
           'link': stats, 'teamsWithFv': cover, 'baseMae': {'tune': r4(b[0].mean()), 'held': r4(b[1].mean())}, 'trials': {}}
    trials = {}
    for k in ('av', 'top', 'snap', 'ret'):
        for tag in ('G', 'M'):
            trials[f'+ {k}{tag}'] = ship + [k + tag]
            trials[f'{k}{tag} for tal'] = [x if x != 'tal' else k + tag for x in ship]
    for name, ks in trials.items():
        e = ev(ks)
        res['trials'][name] = {'prior': ks, 'w': r4(e[2][-1] if '+' in name else e[2][ks.index(next(x for x in ks if x not in ship)) + 1]),
                               'tune': summ(H.paired(e[0], b[0], clt)), 'held': summ(H.paired(e[1], b[1], clh)),
                               'tuneWk1to4': summ(H.paired(e[0][wk_t], b[0][wk_t], [c[wk_t] for c in clt])),
                               'heldWk1to4': summ(H.paired(e[1][wk_h], b[1][wk_h], [c[wk_h] for c in clh])),
                               'mae': {'tune': r4(e[0].mean()), 'held': r4(e[1].mean())}}
        print(name, res['trials'][name]['w'], res['trials'][name]['tune'], res['trials'][name]['held'], flush=True)
    # head to head, mean against grade, inside the full prior
    for k in ('av', 'top', 'snap', 'ret'):
        g, m = ev(ship + [k + 'G']), ev(ship + [k + 'M'])
        res['trials'][f'{k}: mean vs grade'] = {'tune': summ(H.paired(m[0], g[0], clt)), 'held': summ(H.paired(m[1], g[1], clh))}
    save('cfb', res)
    return res


# ---------------------------------------------------------------- NFL rookies
def nfl_rookie_fv():
    """{gsis: (FV at mean, grade)} for each drafted player's final college season on the CFB board (the board at the
    end of the season before his draft: QB, RB, WR, TE, EDGE, DL, LB), matched to nflverse's draft by name and school"""
    import csv
    import names as NM
    rows, _ = cfb_rows()
    by = defaultdict(list)
    for r in rows:
        by[(r['s'], NM.key(r['name']))].append(r)
    out, n = {}, Counter()
    for p in csv.DictReader(open(os.path.join(ROOT, 'scripts', '.cache', 'statplus', 'draft_picks.csv'), encoding='utf-8')):
        D = int(p['season'])
        if D < 2015 or not p.get('gsis_id'):
            continue
        c = by.get((D - 1, NM.key(p['pfr_player_name'])), [])
        c2 = [r for r in c if NM.same_team(r['team'], p['college'])] or (c if len(c) == 1 else [])
        if len(c2) > 1:
            c2 = [max(c2, key=lambda r: r['snaps'] or 0)]
        n['drafted'] += 1
        if c2:
            out[p['gsis_id']] = (c2[0]['fvm'], c2[0]['fvg'], D)
            n['matched'] += 1
    return out, dict(n)


def nfl():
    """rookies' projected WAR (scripts/nfl_roster.py: draft slot) plus their final college FV (at the mean, or the
    grade) as (FV - 45) / 10 with an on-board flag, player level (rookie-season WAR) and in the game model's offseason
    moves term at the shipped share (.25, half-life 8), the same walk as scripts/nfl_offseason_research.py"""
    import nfl_games as N
    from nfl_roster import team_ledger, rosters, pfeat, age, pick, RPOS, team_moves, ROSTER
    FVR, link = nfl_rookie_fv()
    last = 2025
    L = {y: team_ledger(y) for y in range(2013, last + 1)}
    R = {y: rosters(y) for y in range(2013, last + 1)}
    pw = {y: defaultdict(float) for y in L}
    pos = {}
    for y, led in L.items():
        for (g, t), v in led.items():
            pw[y][g] += v[0]; pos[g] = v[2]

    def rowsfor(y, mode):
        X, ids, Y, rk_ = [], [], [], []
        for t, ros in R[y].items():
            for g, r in ros.items():
                ry = int(r['rookie_year']) if r.get('rookie_year', '').isdigit() else (int(r['entry_year']) if r.get('entry_year', '').isdigit() else y)
                rk = 1.0 if ry >= y else 0.0
                grp = pos.get(g) or RPOS.get(r['position'], 'DB')
                x = pfeat(pw.get(y - 1, {}).get(g, 0.0), pw.get(y - 2, {}).get(g, 0.0), 1.0 if (y - 2) in pw else 0.0, age(r, y), rk, y - ry, pick(r), grp, ROSTER['aging'])
                if mode:
                    f = FVR.get(g) if rk and FVR.get(g, (0, 0, 0))[2] == y else None
                    x += [rk * ((f[0 if mode == 'M' else 1] - 45) / 10 if f else 0.0), rk * (1.0 if f else 0.0)]
                X.append(x); ids.append(g); Y.append(pw[y].get(g, 0.0)); rk_.append(rk)
        return np.array(X), ids, np.array(Y), np.array(rk_)

    def project(mode):
        PR = {y: rowsfor(y, mode) for y in range(2014, last + 1)}
        proj, err = {}, {}
        for y in PR:
            tr = [PR[k] for k in PR if k < y]
            X, ids, Y, rk = PR[y]
            if not tr:
                b = np.zeros(X.shape[1]); b[1] = 0.5
            else:
                Xt = np.vstack([t[0] for t in tr]); Yt = np.concatenate([t[2] for t in tr])
                lam = np.eye(Xt.shape[1]) * 5.0; lam[0, 0] = 0
                b = np.linalg.solve(Xt.T @ Xt + lam, Xt.T @ Yt)
            p = X @ b
            proj[y] = dict(zip(ids, p))
            err[y] = ((p - Y) ** 2, rk.astype(bool), b)
        return proj, err

    V = {m: project(m) for m in ('', 'M', 'G')}
    res = {'link': link, 'player': {}, 'game': {}, 'note': 'player: rookie-season WAR squared error vs the slot-only projection (iid paired t; rookies only); game: abs margin error, moves term at the shipped share, clustered by week x home team-season'}
    for m in ('M', 'G'):
        for lab, ys in (('2015_20', range(2015, 2021)), ('2021_25', range(2021, last + 1))):
            e1 = np.concatenate([V[m][1][y][0][V[m][1][y][1]] for y in ys]); e0 = np.concatenate([V[''][1][y][0][V[''][1][y][1]] for y in ys])
            p_ = H.paired(e1, e0)
            res['player'][f'{m}/{lab}'] = {'n': int(len(e1)), 'rmse': r4(np.sqrt(e1.mean())), 'rmseSlot': r4(np.sqrt(e0.mean())), 't': r4(p_['t'])}
        res['player'][f'{m}/coef2025'] = [r4(v) for v in V[m][1][last][2][-2:]]
        print('nfl player', m, {k: v for k, v in res['player'].items() if k.startswith(m)}, flush=True)
    # game level: the live walk, the shipped moves term from each projection
    F = json.load(open(N.FIT)); params = F['params']
    games, box, qbs = N.load(last)
    N.index_qbs(qbs, games); N.load_qb_teams(last)
    inj = N.injury_history(games, range(N.INJ_FIRST, last + 1))
    _, data = N.walk(games, box, qbs, params)
    gp = defaultdict(int)
    D = []
    for g, x, _ in data:
        s = int(g['season']); h, a = N.team(g['home_team']), N.team(g['away_team'])
        before = (gp[(s, h)], gp[(s, a)])
        if g['home_score'] not in ('', 'NA'):
            gp[(s, h)] += 1; gp[(s, a)] += 1
        if g['home_score'] in ('', 'NA') or s < 2012:
            continue
        x = dict(x)
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        D.append((g, x, before))
    S = np.array([int(g['season']) for g, _, _ in D]); WK = np.array([int(g['week']) for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D])
    XB = np.array([[x[f] for f in N.FEATS] for _, x, _ in D])
    p0 = np.full(len(y), np.nan)
    for s in range(2015, last + 1):
        tr, te = S < s, S == s
        p0[te] = XB[te] @ np.linalg.lstsq(XB[tr], y[tr], rcond=None)[0]

    def feat(proj):
        TQ = {yy: team_moves(yy, L.get(yy - 1, {}), R[yy], proj[yy], pw.get(yy - 1, {}), pos) for yy in range(2015, last + 1)}
        v = np.zeros(len(D))
        for i, (g, x, (nh, na)) in enumerate(D):
            T = TQ.get(int(g['season']))
            if not T:
                continue
            hl = ROSTER['hl']
            fh, fa = (0.5 ** (nh / hl), 0.5 ** (na / hl)) if g['game_type'] == 'REG' else (0.5 ** (17 / hl),) * 2
            v[i] = (fh * T.get(N.team(g['home_team']), {}).get('moves', 0.0) - fa * T.get(N.team(g['away_team']), {}).get('moves', 0.0)) * N.PTS_PER_WIN / 17
        return v

    e_ship = np.abs(p0 + ROSTER['c'] * feat(V[''][0]) - y)
    cl = [WK.astype(str), np.array([f"{N.team(g['home_team'])}|{g['season']}" for g, _, _ in D])]
    clus = lambda k: [np.char.add(S[k].astype(str), c[k]) if j == 0 else c[k] for j, c in enumerate(cl)]
    for m in ('M', 'G'):
        e1 = np.abs(p0 + ROSTER['c'] * feat(V[m][0]) - y)
        for lab, k in (('2015_20', (S >= 2015) & (S <= 2020)), ('2021_25', S >= 2021)):
            for wl, kk in (('all', k), ('wk1_4', k & (WK <= 4))):
                kk = kk & ~np.isnan(e1)
                res['game'][f'{m}/{lab}/{wl}'] = summ(H.paired(e1[kk], e_ship[kk], clus(kk)))
        print('nfl game', m, {k_: v for k_, v in res['game'].items() if k_.startswith(m)}, flush=True)
    save('nfl', res)


# ---------------------------------------------------------------- NBA rookies
def nba():
    """the college basketball board's preseason grade for the draft season (static/data/cbb-past.json, out of fold
    before 2017), at the mean (fvx) and as the grade (fvg), on top of the shipped rookie prior (a + b ln(pick) +
    final college BPM, college draftees; scripts/nba_prior_research.py). With ln(pick) in the fit, the FV term is FV's
    residual to slot. Walk-forward by rookie class, scored on rookie-season XPM weighted by minutes."""
    import nba_games as N
    import nba_prior_research as R
    rows = [r for r in R.rookie_rows() if not r['intl']]
    brd = R.board()
    for r in rows:
        bd = brd.get((N.norm(r['n']), r['S'] - 1))
        r['fvg'] = bd['fvg'] if bd else None
    X = R.rfeats(rows)
    g = np.array([r['fvg'] if r['fvg'] is not None else np.nan for r in rows], float)
    X['fvg'] = np.where(np.isnan(g), 28.0, g)
    # residual of FV to slot, fit on all classes would leak; ln(pick) sits in every fit, so the coefficient is the residual's
    res = {'n': len(rows), 'onBoard': int((~np.isnan(g)).sum()), 'note': 'college draftees; d = rmse change vs lp + cbpm, t paired on weighted squared error'}
    for target in ('xpm', 'mpg'):
        base = ['lp', 'cbpm']
        _, ref = R.score_rookie(rows, X, base, target)
        res[target] = {}
        for nm, add in (('fv at mean', ['fvx', 'nofv']), ('fv grade', ['fvg', 'nofv']), ('fv at mean, no flag', ['fvx']), ('fv grade, no flag', ['fvg']),
                        ('P(NBA)', ['nbaP'])):
            s, _ = R.score_rookie(rows, X, base + add, target, ref)
            res[target][nm] = {k: s[k] for k in ('2015_21', '2022_26')}
            print('nba', target, nm, s['2015_21'], s['2022_26'], flush=True)
    save('nba', res)


if __name__ == '__main__':
    {'cbb': cbb, 'cbb2': lambda: cbb(2), 'nba': nba, 'cfb': cfb, 'nfl': nfl}[sys.argv[1]]()
