#!/usr/bin/env python3
"""Big-time throws (BTT) for quarterbacks: a free proxy, tested as a QB talent signal and as a game-model term
(thread "Test big time throws for QBs", Nov 1 2026; Noah: "Can we measure big time throws for QBs and see if this
helps as an FV driver / in the game model?"). Research only. Results in data/qb_btt_research.json.

PFF's big-time throw is a charted grade (ball placement and timing, mostly downfield, into tight windows) and is
paywalled; no free per-throw or per-season source exists. Proxies, fixed before any outcome was looked at:
  NFL (nflverse play-by-play, 2014-26; cp is nflverse's completion probability from air yards, depth, location,
  pressure and separation-free context):
    btt    completions thrown 10+ air yards with completion probability <= .45, a dropback. League rate 4.0%, about
           PFF's league BTT rate. 2024 leaders Darnold 34, Burrow 31, Allen 29, Wilson 29, Jackson 28, Love 27
           (PFF: Allen 37, Tagovailoa 35, Love 33 -- same names near the top, a proxy not a copy)
    dcoe   downfield completions over expected: sum of (complete - cp) on 10+ air-yard attempts, a dropback
  CFB (ESPN play text, 2015-26; air yards are spotted only from 2026, so depth is yards gained):
    btt    completions gaining 25+ yards, a dropback (attempts + sacks)
Talent test (the FV-driver question):
  NFL  QB season t -> t+1 (250+ dropbacks both, regular season 2014-25): next-season EPA a dropback on this season's
       EPA a dropback, CPOE, sack rate and INT rate (the XV QB parts the play-by-play has), plus the proxy. One season
       out; pass = coefficient t >= 2 (+), held-out squared error below the base at paired t <= -1.5, most seasons won.
  CFB  the proxy as a candidate FV driver in the wide FV harness (scripts/cfb_fv_refit.mjs --wide --stage=cand
       --gates, cand key bttQ|QB, from scripts/.cache/fvrefit/btt.json written here with --cfb-fv).
Game-model test (as scripts/penalty_research.py: season-to-date team rate, shrunk to a prior worth n0 games, z within
season; residual vs the close, tune/held split, BH over the family):
    btt_net  margin  (offense btt - btt allowed)(home) - (same)(away)          +
    btt_off  margin  offense btt(home) - offense btt(away)                      +
    btt_T    totals  sum of both offenses' btt and both defenses' btt allowed   +
    dcoe_net margin  (NFL) as btt_net on dcoe                                   +
    python3 scripts/qb_btt_research.py              # NFL + CFB -> data/qb_btt_research.json
    python3 scripts/qb_btt_research.py --cfb-fv     # QB-season proxy for the FV harness
Result (Nov 1 2026): nothing passes, nothing shipped.
  NFL talent: btt beyond the base t -3.21 (wrong way), one-season-out t -0.8; dcoe t -0.35. Other thresholds
  (15/.55, 20/.45, 10/.35) also negative. BTT tracks same-season EPA (r .48) but adds nothing to next season.
  NFL games: btt_net/btt_off/btt_T/dcoe_net all null or the wrong way vs the close (best held SE t +0.4 to -1.2).
  CFB games: btt_off held -1.11 (wrong sign), btt_T held -3.59 but held SE t +3.6; none pass.
  CFB FV (cfb_fv_refit.mjs --wide): bttQ|QB fold t -2.45 (1/10), bttV|QB t -1.88 (0/10); top 32 and forward flat.
  Pre-register a true air-yard CFB BTT from 2026 ESPN spots (as cfb_adot_prereg) and re-score after 2026-27.
Caches (not committed): scripts/.cache/nfl/play_by_play_Y.csv.gz (nflverse), scripts/.cache/btt/nfl_db.json.gz (slim
dropbacks), scripts/.cache/cfb/espn_pbp (python3 scripts/cfb_espn_pbp.py 2015 2026).
"""
import collections
import csv
import datetime
import glob
import gzip
import json
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402
import style_research as SR  # noqa: E402
import penalty_research as PR  # noqa: E402

CB = os.path.join(HERE, '.cache', 'btt')
OUT = os.path.join(ROOT, 'data', 'qb_btt_research.json')
AIR, CPMAX, CFB_YDS = 10, 0.45, 25
FR = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'JAC': 'JAX', 'LAR': 'LA'}
tm = lambda t: FR.get(t, t)


# ---------------------------------------------------------------- NFL dropbacks
def nfl_slim():
    p = os.path.join(CB, 'nfl_db.json.gz')
    if os.path.exists(p):
        return json.load(gzip.open(p))
    out = []
    for y in range(2014, 2027):
        rd = csv.reader(gzip.open(os.path.join(HERE, '.cache', 'nfl', f'play_by_play_{y}.csv.gz'), 'rt'))
        h = next(rd)
        I = {k: i for i, k in enumerate(h)}
        for r in rd:
            if r[I['qb_dropback']] != '1' or r[I['two_point_attempt']] == '1':
                continue
            f = lambda k: float(r[I[k]]) if r[I[k]] not in ('', 'NA') else None
            out.append([y, r[I['season_type']], r[I['game_id']], r[I['posteam']], r[I['defteam']],
                        r[I['passer_player_id']] or r[I['passer_id']], r[I['passer_player_name']] or r[I['passer']],
                        int(r[I['pass_attempt']] == '1'), int(r[I['complete_pass']] == '1'), f('air_yards'), f('cp'), f('epa'),
                        int(r[I['interception']] == '1'), int(r[I['sack']] == '1'), int(r[I['qb_scramble']] == '1'), f('cpoe'),
                        f('wp'), int(r[I['qb_hit']] == '1')])
    os.makedirs(CB, exist_ok=True)
    json.dump(out, gzip.open(p, 'wt'))
    return out


def is_btt(d):
    return d[8] and d[9] is not None and d[9] >= AIR and d[10] is not None and d[10] <= CPMAX


def dco(d):
    return (d[8] - d[10]) if d[7] and d[9] is not None and d[9] >= AIR and d[10] is not None else 0.0


# ---------------------------------------------------------------- NFL talent test
def nfl_talent(D):
    Q = collections.defaultdict(lambda: collections.defaultdict(float))
    for d in D:
        if d[1] != 'REG' or not d[5] or d[5] == 'NA':
            continue
        q = Q[(d[5], d[0])]
        q['name'] = d[6]
        q['db'] += 1
        q['epa'] += d[11] or 0
        q['sk'] += d[13]
        q['int'] += d[12]
        q['att'] += d[7]
        if d[15] is not None and d[7]:
            q['cpoe'] += d[15]
            q['ncp'] += 1
        q['btt'] += 1 if is_btt(d) else 0
        q['dcoe'] += dco(d)
    feat = lambda q: [q['epa'] / q['db'], q['cpoe'] / max(q['ncp'], 1), q['sk'] / q['db'], q['int'] / max(q['att'], 1),
                      q['btt'] / q['db'], q['dcoe'] / q['db']]
    rows = []
    for (pid, y), q in Q.items():
        n = Q.get((pid, y + 1))
        if y + 1 <= 2025 and n and q['db'] >= 250 and n['db'] >= 250:
            rows.append(dict(pid=pid, y=y, name=q['name'], x=feat(q), yv=n['epa'] / n['db'], w=n['db'],
                             btt1=n['btt'] / n['db'], db=q['db']))
    X = np.array([r['x'] for r in rows])
    y = np.array([r['yv'] for r in rows])
    w = np.array([r['w'] for r in rows], float)
    Y = np.array([r['y'] for r in rows])
    pid = np.array([r['pid'] for r in rows])
    Z = (X - X.mean(0)) / X.std(0)
    out = {'n': len(rows), 'seasons': [int(Y.min()), int(Y.max()) + 1],
           'yoy_r': {'btt': round(float(np.corrcoef(X[:, 4], [r['btt1'] for r in rows])[0, 1]), 3),
                     'epa': round(float(np.corrcoef(X[:, 0], y)[0, 1]), 3)},
           'r_btt_epa_same_season': round(float(np.corrcoef(X[:, 4], X[:, 0])[0, 1]), 3),
           'r_btt_next_epa': round(float(np.corrcoef(X[:, 4], y)[0, 1]), 3)}
    base = [0, 1, 2, 3]
    for name, cols in (('btt', base + [4]), ('dcoe', base + [5]), ('btt_alone', [4]), ('epa_alone', [0])):
        if name.endswith('_alone'):
            b0 = []
        else:
            b0 = base
        A = np.c_[np.ones(len(y)), Z[:, cols]]
        B = np.c_[np.ones(len(y)), Z[:, b0]] if b0 else np.ones((len(y), 1))
        sw = np.sqrt(w)
        b, s = SR.ols_cl(A * sw[:, None], y * sw, pid)
        e_new, e_old = np.zeros(len(y)), np.zeros(len(y))
        won = 0
        for yr in sorted(set(Y)):
            tr, te = Y != yr, Y == yr
            bn = np.linalg.lstsq(A[tr] * sw[tr, None], y[tr] * sw[tr], rcond=None)[0]
            bo = np.linalg.lstsq(B[tr] * sw[tr, None], y[tr] * sw[tr], rcond=None)[0]
            e_new[te] = (A[te] @ bn - y[te]) ** 2
            e_old[te] = (B[te] @ bo - y[te]) ** 2
            won += int((w[te] * e_new[te]).sum() < (w[te] * e_old[te]).sum())
        pr = H.paired(e_new * w / w.mean(), e_old * w / w.mean(), cluster=pid)
        k = len(cols)    # the test term is the last column
        o = {'coef_per_sd': round(float(b[k]), 4), 't': round(float(b[k] / s[k]), 2), 'loso_dSE': round(float(pr['d']), 6),
             'loso_t': round(pr['t'], 2), 'seasons_won': [won, len(set(Y))]}
        o['pass'] = bool(name in ('btt', 'dcoe') and o['t'] >= 2 and o['loso_t'] <= -1.5 and won > len(set(Y)) / 2)
        out[name] = o
    return out, rows


# ---------------------------------------------------------------- NFL game events
def nfl_events(D):
    G = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, 0.0]))   # game -> team -> [db, btt, dcoe]
    for d in D:
        a = G[d[2]][tm(d[3])]
        a[0] += 1
        a[1] += 1 if is_btt(d) else 0
        a[2] += dco(d)
    sched = {r['id']: r for r in json.load(gzip.open(SR.WF.format('nfl')))}
    ev = []
    for gid, T in G.items():
        y, wk, aw, hm = gid.split('_')
        aw, hm = tm(aw), tm(hm)
        if hm not in T or aw not in T:
            continue
        r0 = sched.get(gid)
        dt = SR.when(r0['date']) if r0 else datetime.datetime(int(y), 9, 1) + datetime.timedelta(days=7 * int(wk))
        sd = lambda me, op: {'b': (me[1], me[0]), 'ba': (op[1], op[0]), 'd': (me[2], me[0]), 'da': (op[2], op[0])}
        ev.append(dict(t=dt, S=int(y), h=hm, a=aw, gid=gid, sh=sd(T[hm], T[aw]), sa=sd(T[aw], T[hm])))
    return ev


# ---------------------------------------------------------------- CFB (ESPN play text)
PASS_T = {'Pass Reception', 'Passing Touchdown', 'Pass Incompletion', 'Pass Interception Return', 'Interception Return Touchdown',
          'Sack', 'Pass Interception', 'Pass', 'Pass Completion'}
COMP_T = {'Pass Reception', 'Passing Touchdown', 'Pass Completion'}
RX_PASSER = re.compile(r"^([A-Z][\w.'\- ]+?) (?:pass|sacked)", re.I)


def cfb_games():
    """ESPN id -> {'ha': {'home': team id, ...}, 'S', 'date', 'sides': {team id: [db, btt]}, 'qb': {(team id, name): [db, btt, comp, att, yds]}}"""
    p = os.path.join(CB, 'cfb_games.json.gz')
    if os.path.exists(p):
        return json.load(gzip.open(p))
    out = {}
    for f in glob.glob(os.path.join(HERE, '.cache', 'cfb', 'espn_pbp', '*.json.gz')):
        try:
            g = json.load(gzip.open(f))
        except (OSError, ValueError):
            continue
        ha = {t['ha']: t['id'] for t in g.get('teams') or []}
        if 'home' not in ha or 'away' not in ha:
            continue
        sides = {ha['home']: [0, 0], ha['away']: [0, 0]}
        qb = {}
        for dr in g.get('drives') or []:
            for pl in dr.get('plays') or []:
                t = pl.get('t')
                if t not in PASS_T or pl.get('pen') and 'no play' in (pl.get('x') or '').lower():
                    continue
                team = pl.get('st')
                if team not in sides:
                    continue
                y = pl.get('y') or 0
                big = int(t in COMP_T and y >= CFB_YDS)
                sides[team][0] += 1
                sides[team][1] += big
                m = RX_PASSER.match(pl.get('x') or '')
                if m:
                    k = team + '|' + m.group(1).strip()
                    q = qb.setdefault(k, [0, 0, 0, 0, 0])
                    q[0] += 1
                    q[1] += big
                    if t != 'Sack':
                        q[3] += 1
                        if t in COMP_T:
                            q[2] += 1
                            q[4] += y
        out[os.path.basename(f).split('.')[0]] = {'ha': ha, 'date': g.get('date'), 'sides': sides, 'qb': qb}
    json.dump(out, gzip.open(p, 'wt'))
    return out


def cfb_events(CG):
    wf = json.load(gzip.open(SR.WF.format('cfb')))
    ev = []
    for r in wf:
        g = CG.get(str(r['id']))
        if not g:
            continue
        h, a = g['sides'][g['ha']['home']], g['sides'][g['ha']['away']]
        if h[0] < 10 or a[0] < 10:
            continue
        sd = lambda me, op: {'b': (me[1], me[0]), 'ba': (op[1], op[0])}
        ev.append(dict(t=SR.when(r['date']), S=r['S'], h=r['home'], a=r['away'], gid=str(r['id']), sh=sd(h, a), sa=sd(a, h)))
    return ev


# ---------------------------------------------------------------- game terms
def edge(o, d):
    return lambda z: z[o] - z[d] if z.get(o) is not None and z.get(d) is not None else None


def gterms(rows, nfl_):
    stats = ['b', 'ba', 'd', 'da'] if nfl_ else ['b', 'ba']
    SR.zs(rows, stats)
    t = {'btt_net': (PR.mterm(rows, edge('b', 'ba')), False), 'btt_off': (PR.mterm(rows, lambda z: z['b']), False),
         'btt_T': (PR.tterm(rows, lambda z: z['b'] + z['ba'] if z.get('b') is not None and z.get('ba') is not None else None), True)}
    if nfl_:
        t['dcoe_net'] = (PR.mterm(rows, edge('d', 'da')), False)
    return t


def games(sp, ev):
    ev.sort(key=lambda e: e['t'])
    stats = ['b', 'ba', 'd', 'da'] if sp == 'nfl' else ['b', 'ba']
    rel = PR.reliability(ev, stats)
    n0 = max(PR.N0_FLOOR[sp], min(round(max(rel[s]['n50'] for s in ('b', 'ba'))), 40))
    rel['n0'] = n0
    print(sp, 'events', len(ev), 'reliability', rel, flush=True)
    pre = SR.run_roll(ev, n0, stats)
    rows = PR.rows_from_wf(sp, pre)
    res = {}
    for k, (x, tot) in gterms(rows, sp == 'nfl').items():
        o = SR.score(rows, x, tot, SR.TUNE[sp], 1)
        res[k] = o
        print(f"{sp:5}{k:9} n {o['n']}  tune {o['tune']} held {o['held']} held SE {o['seHeld']}  z {o['z']}  model {o.get('model')}", flush=True)
    return res, rel


# ---------------------------------------------------------------- CFB FV candidate file
def cfb_fv(CG):
    """scripts/.cache/fvrefit/btt.json: {"<season>|<name key>|<school key>": {db, btt, rate}} from ESPN play text, one
    row per QB-season (the season label is the fall year). Team names from the games_wf rows."""
    import cfb_game_splits as GS
    wf = {str(r['id']): r for r in json.load(gzip.open(SR.WF.format('cfb')))}
    names = {}
    for gid, r in wf.items():
        g = CG.get(gid)
        if g:
            names[g['ha']['home']] = r['home']
            names[g['ha']['away']] = r['away']
    acc = collections.defaultdict(lambda: [0, 0, 0, 0, 0])
    for gid, g in CG.items():
        if not g.get('date'):
            continue
        d = g['date'][:10]
        S = int(d[:4]) - (1 if int(d[5:7]) < 7 else 0)
        for k, v in g['qb'].items():
            tid, nmx = k.split('|', 1)
            if tid not in names:
                continue
            a = acc[(S, nmx, names[tid])]
            for i in range(5):
                a[i] += v[i]
    out = {}
    for (S, nmx, team), a in acc.items():
        if a[0] < 50:
            continue
        key = f'{S}|{GS.nm(nmx)}|{GS.school(team)}'
        out[key] = {'db': a[0], 'btt': a[1], 'rate': round(a[1] / a[0], 4), 'name': nmx, 'team': team}
    p = os.path.join(HERE, '.cache', 'fvrefit', 'btt.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, 'w'))
    print('cfb QB seasons', len(out), '->', p)


def main():
    if '--cfb-fv' in sys.argv:
        cfb_fv(cfb_games())
        return
    D = nfl_slim()
    res = {'asof': datetime.date.today().isoformat(), 'def': {'nfl_btt': f'complete, air >= {AIR}, cp <= {CPMAX}, per dropback',
                                                              'cfb_btt': f'completion gaining {CFB_YDS}+ yards, per dropback'}}
    tal, _ = nfl_talent(D)
    res['nfl_talent'] = tal
    print('nfl talent', json.dumps(tal), flush=True)
    res['games'], res['reliability'] = {}, {}
    res['games']['nfl'], res['reliability']['nfl'] = games('nfl', nfl_events(D))
    if '--nfl' not in sys.argv:
        res['games']['cfb'], res['reliability']['cfb'] = games('cfb', cfb_events(cfb_games()))
    tests = [(sp, k) for sp in res['games'] for k in res['games'][sp]]
    p = [2 * (1 - 0.5 * (1 + math.erf(abs(res['games'][sp][k]['z']) / math.sqrt(2)))) for sp, k in tests]
    for (sp, k), pi, q in zip(tests, p, H.bh(p)):
        o = res['games'][sp][k]
        o['p'], o['q'] = round(pi, 5), round(float(q), 4)
        o['pass'] = bool(o['pass_split'] and q <= .10)
        print(f"{sp:5}{k:9} z {o['z']:6} q {o['q']}  {'PASS' if o['pass'] else ''}")
    if '--nfl' not in sys.argv:
        json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
