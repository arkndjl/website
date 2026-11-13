#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL game-model tests (PREREG.md beside this file: A1 ir, A2 qbr, A3 contract-valued
injuries, B1 tqb, B2 tinj).

    python3 scripts/research/nfl_nov13/ledgers.py 2016 ... 2025     # once: weekly point-in-time WAR ledgers
    python3 scripts/research/nfl_nov13/games_test.py                # writes data/nfl_audit_nov13.json ('games')

Each candidate joins the live model's walk-forward (scripts/nfl_games.py params, refit on every season before);
absolute error paired per game, t clustered by season-week. Settings are picked on 2015-20; the held-out 2021-25 p at
that setting is the test's p.
"""
import csv
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import harness as H      # noqa: E402
import nfl_games as N    # noqa: E402
import ledgers as L      # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_audit_nov13.json')
LAST = 2025
YEARS = range(N.INJ_FIRST, LAST + 1)
RESERVE = {'RES', 'PUP', 'SUS', 'NWT', 'RSN', 'EXE'}
OFF_POS = {'RB', 'FB', 'WR', 'TE', 'T', 'G', 'C', 'OL', 'OT', 'OG'}
DEF_POS = {'DE', 'DT', 'NT', 'DL', 'LB', 'OLB', 'ILB', 'MLB', 'CB', 'S', 'SS', 'FS', 'DB'}
GROUP = {'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL',
         'DE': 'DL', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL', 'LB': 'LB', 'OLB': 'LB', 'ILB': 'LB', 'MLB': 'LB',
         'CB': 'DB', 'S': 'DB', 'SS': 'DB', 'FS': 'DB', 'DB': 'DB'}
NICK = {t: full.split()[-1] for t, full in N.TEAMS.items()}
NICK.update({'LA': 'Rams', 'LV': 'Raiders', 'LAC': 'Chargers', 'WAS': 'Commanders'})
OLD_NICK = {'Redskins': 'Commanders', 'Football Team': 'Commanders', 'Washington': 'Commanders'}


def cache(name):
    return os.path.join(N.CACHE, name)


from nfl_market import cap_of   # noqa: E402


def contracts():
    import nfl_market as MK
    return MK.contracts(cache('players.csv'), cache('historical_contracts.csv.gz'))


def roster_info(y):
    """gsis -> (coarse position, club nickname) from the season roster"""
    out = {}
    for r in N.rows(N.get(f'roster_{y}.csv', f'{N.REL}/rosters/roster_{y}.csv')):
        if r['gsis_id']:
            out[r['gsis_id']] = (r['position'], NICK.get(N.team(r['team']), ''))
    return out


# ---------------------------------------------------------------- injuries, player by player
def detail(games):
    """game_id -> {'rep': [(side 0 home / 1 away, gsis, report position, P(miss), value, played last)],
                   'res': [(side, gsis, value, n games since his last, played this season)]}"""
    out = {}
    for y in YEARS:
        prev, led = L.load(y)
        sg = [g for g in games if int(g['season']) == y and g['home_score'] not in ('', 'NA')]
        top = max([int(g['week']) for g in sg] + [1])
        rep = defaultdict(list)
        for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
            if r['report_status'] and r['position'] != 'QB':
                rep[(N.team(r['team']), int(r['week']))].append((r['gsis_id'], r['report_status'], N.practice_of(r['practice_status']), r['position']))
        res = defaultdict(list)
        for r in N.rows(cache(f'roster_weekly_{y}.csv')):
            if r['status'] in RESERVE and r['position'] != 'QB' and r['gsis_id'] and r['week'] not in ('', 'NA'):
                res[(N.team(r['team']), int(r['week']))].append(r['gsis_id'])
        weeks_of = defaultdict(list)
        for g in sg:
            for side in ('home', 'away'):
                weeks_of[N.team(g[f'{side}_team'])].append(int(g['week']))
        gp = lambda gsis, w: led[min(w, 19)].get(gsis, (0, 0))[1]
        last_wk = {}
        for g in sg:
            w = int(g['week'])
            Lw = led[min(w, 19, top + 1)]
            d = {'rep': [], 'res': []}
            for si, side in enumerate(('home', 'away')):
                t = N.team(g[f'{side}_team'])
                pw = last_wk.get(t)
                for gsis, stt, prac, pos in rep.get((t, w), []):
                    v = N.player_value(prev.get(gsis, (0.0, 0)), Lw.get(gsis, (0.0, 0)))
                    if pw is None or pw >= 18 or w > 18:
                        played = True
                    else:
                        played = led[pw + 1].get(gsis, (0, 0))[1] > led[pw].get(gsis, (0, 0))[1]
                    d['rep'].append((si, gsis, pos, 1 - N.play_prob(stt, played, prac), v, played))
                tw = [x for x in weeks_of[t] if x < w]
                listed = {x[0] for x in rep.get((t, w), [])} if os.environ.get('IR_CLEAN') else set()
                for gsis in set(res.get((t, w), [])) - listed:
                    v = N.player_value(prev.get(gsis, (0.0, 0)), Lw.get(gsis, (0.0, 0)))
                    if v <= 0:
                        continue
                    lastp = None
                    for x in tw:
                        if x <= 18 and gp(gsis, x + 1) > gp(gsis, x):
                            lastp = x
                    n = len([x for x in tw if lastp is None or x > lastp])
                    d['res'].append((si, gsis, v, n, lastp is not None))
                last_wk[t] = w
            out[g['game_id']] = d
        print('detail', y, len(sg), flush=True)
    return out


# ---------------------------------------------------------------- ESPN QBR
def qbr_lines(games):
    """(nflverse game id, club) -> [(gsis, QBR EPA, plays)], and the 2006-14 play-weighted mean EPA a play"""
    esp = {}
    for p in csv.DictReader(open(cache('players.csv'), newline='', encoding='utf-8')):
        if p['espn_id'] and p['gsis_id']:
            esp[p['espn_id']] = p['gsis_id']
    gid = {g['espn']: g['game_id'] for g in games if g.get('espn')}
    ab = {'WSH': 'WAS', 'LAR': 'LA'}
    out = defaultdict(list)
    s0 = [0.0, 0.0]
    miss = 0
    for r in csv.DictReader(open(cache('qbr_week_level.csv'), newline='', encoding='utf-8')):
        try:
            e, n = float(r['epa_total']), float(r['qb_plays'])
        except ValueError:
            continue
        if 2006 <= int(r['season']) <= 2014:
            s0[0] += e; s0[1] += n
        g, q = gid.get(r['game_id']), esp.get(r['player_id'])
        if not g or not q:
            miss += 1
            continue
        out[(g, N.team(ab.get(r['team_abb'], r['team_abb'])))].append((q, e, n))
    print('qbr rows', sum(len(v) for v in out.values()), 'unjoined', miss, 'mean 2006-14', round(s0[0] / s0[1], 4))
    return out, s0[0] / s0[1]


def main():
    F = json.load(open(N.FIT))
    params = F['params']
    games, box, qbs = N.load(LAST)
    N.index_qbs(qbs, games); N.load_qb_teams(LAST)
    inj = N.injury_history(games, YEARS)
    det = detail(games)
    cons = contracts()
    ql, qmean = qbr_lines(games)
    repl2 = qmean - 0.16

    # last season's club and coarse position, and k_g = WAR a game per cap % in the group, from last season only
    info = {y: roster_info(y) for y in range(N.INJ_FIRST - 1, LAST + 1)}
    kg = {}
    for y in YEARS:
        prev, _ = L.load(y)
        num, den = defaultdict(float), defaultdict(float)
        for gsis, (w, gms) in prev.items():
            pos, club = info[y - 1].get(gsis, (None, None))
            g_ = GROUP.get(pos)
            if not g_ or gms < 8:
                continue
            last2 = info.get(y - 2, {}).get(gsis, (None, None))[1]
            c = cap_of(cons, gsis, y - 1, last2)
            if c:
                num[g_] += w / gms; den[g_] += c
        kg[y] = {g_: num[g_] / den[g_] for g_ in num if den[g_] > 0}
    print('k_g 2025', {k: round(v, 4) for k, v in kg[LAST].items()})

    # the walk: the live model's features, plus the QB parts by side and the QBR twin
    m = N.Model(**params)
    a_ = m.a
    q2 = defaultdict(lambda: [0.0, 0.0]); qt2 = defaultdict(lambda: [0.0, 0.0])
    D = []
    season = None
    for g in games:
        x, tx = m.feats(g)
        s = int(g['season'])
        if s != season:
            for q in q2.values():
                q[0] *= 0.7; q[1] *= 0.7
            for t in qt2:
                qt2[t][0] *= m.carry; qt2[t][1] *= m.carry
            season = s
        h, a = N.team(g['home_team']), N.team(g['away_team'])
        qadj = lambda t, q: (m.qbval(q) - m.rate(m.qbt, t, m.repl)) if q else 0.0
        v2 = lambda q: (q2[q][0] + repl2 * m.n0) / (q2[q][1] + m.n0)
        qadj2 = lambda t, q: (v2(q) - m.rate(qt2, t, repl2)) if q else 0.0
        x = dict(x); tx = dict(tx)
        tx['tqb'] = (qadj(h, g['home_qb_id']) + qadj(a, g['away_qb_id'])) * 38
        x['qbr'] = (qadj2(h, g['home_qb_id']) - qadj2(a, g['away_qb_id'])) * 38
        D.append((g, x, tx))
        m.update(g, box, qbs)
        if g['home_score'] not in ('', 'NA'):
            for t in (h, a):
                tq = [0.0, 0.0]
                for q, e, n in ql.get((g['game_id'], t), ()):
                    q2[q][0] += e; q2[q][1] += n
                    tq[0] += e; tq[1] += n
                if tq[1] > 10:
                    qt2[t][0] = qt2[t][0] * a_ + tq[0] / tq[1]; qt2[t][1] = qt2[t][1] * a_ + 1
    D = [(g, x, tx) for g, x, tx in D if g['home_score'] not in ('', 'NA') and int(g['season']) >= 2012]

    HL = (2, 4, 8, None)
    LAM = (0.25, 0.5, 1.0)
    chk = []
    for g, x, tx in D:
        r = inj.get(g['game_id'])
        if r:
            x['inj'] = (r[2] + r[3]) - (r[0] + r[1])
        d = det.get(g['game_id'])
        y = int(g['season'])
        for sc in ('in', 'all'):
            for hl in HL:
                x[f'ir_{sc}_{hl}'] = 0.0
        for lam in LAM:
            x[f'injm_{lam}'] = 0.0
        tx['tinj'] = 0.0
        if not d:
            continue
        sgn = lambda si: 1.0 if si == 1 else -1.0       # away minus home
        own = 0.0
        for si, gsis, pos, pm, v, played in d['rep']:
            c = pm * max(v, 0.0) * N.PTS_PER_WIN
            own += sgn(si) * c
            if pos in OFF_POS:
                tx['tinj'] += c
            elif pos in DEF_POS:
                tx['tinj'] -= c
            g_ = GROUP.get(pos)
            cap = cap_of(cons, gsis, y, info[y - 1].get(gsis, (None, None))[1])
            k = kg[y].get(g_)
            for lam in LAM:
                v2_ = (1 - lam) * v + lam * k * cap if (cap and k) else v
                x[f'injm_{lam}'] += sgn(si) * pm * max(v2_, 0.0) * N.PTS_PER_WIN
        chk.append(abs(own - x['inj']) if r else 0.0)
        for si, gsis, v, n, inseason in d['res']:
            for hl in HL:
                c = v * N.PTS_PER_WIN * (0.5 ** (n / hl) if hl else 1.0)
                x[f'ir_all_{hl}'] += sgn(si) * c
                if inseason:
                    x[f'ir_in_{hl}'] += sgn(si) * c
    print('injury rebuild vs cache: max gap', round(max(chk), 3), 'mean', round(float(np.mean(chk)), 4))

    S = np.array([int(g['season']) for g, _, _ in D])
    WK = np.array([f"{g['season']}-{g['week']}" for g, _, _ in D])
    y = np.array([N.num(g['result']) for g, _, _ in D]); ty = np.array([N.num(g['total']) for g, _, _ in D])
    line = np.array([N.num(g['spread_line'], np.nan) for g, _, _ in D])
    tline = np.array([N.num(g['total_line'], np.nan) for g, _, _ in D])
    ok = ~np.isnan(line)
    A = (S >= 2015) & (S <= 2020) & ok; B = (S >= 2021) & ok

    def wf(feats, tot=False):
        X = np.array([[(tx if tot else x)[f] for f in feats] for _, x, tx in D]); yy = ty if tot else y
        pred = np.full(len(yy), np.nan)
        for s in range(2015, LAST + 1):
            tr, te = S < s, S == s
            b = np.linalg.lstsq(X[tr], yy[tr], rcond=None)[0]; pred[te] = X[te] @ b
        b = np.linalg.lstsq(X, yy, rcond=None)[0]
        return np.abs(pred - yy), pred, dict(zip(feats, b))

    def cmp(e1, e0, k):
        r = H.paired(e1[k], e0[k], cluster=WK[k])
        return {'d': round(r['d'], 4), 't': round(r['t'], 2), 'p': round(r['p'], 4), 'n': r['n']}

    def close(pred, k, ln):
        """does the candidate's move predict result minus the close? slope and t"""
        return None

    base, tbase = list(N.FEATS), list(N.TFEATS)
    e0, p0, _ = wf(base); t0, tp0, _ = wf(tbase, True)
    res = {'prereg': 'scripts/research/nfl_nov13/PREREG.md', 'base': {
        'mae1520': round(float(e0[A].mean()), 3), 'mae2125': round(float(e0[B].mean()), 3),
        'line1520': round(float(np.abs(line[A] - y[A]).mean()), 3), 'line2125': round(float(np.abs(line[B] - y[B]).mean()), 3),
        'total1520': round(float(t0[A].mean()), 3), 'total2125': round(float(t0[B].mean()), 3)}}
    print(res['base'])

    def run(name, cells, tot=False):
        """cells: {label: feature list}; picks the best 2015-20 cell, reports every cell"""
        eb = t0 if tot else e0
        rows = {}
        for lab, feats in cells.items():
            e1, p1, b = wf(feats, tot)
            new = [f for f in feats if f not in (tbase if tot else base)]
            pb = tp0 if tot else p0
            yy, ln = (ty, tline) if tot else (y, line)
            mv = p1 - pb
            k = B & ~np.isnan(ln) & (np.abs(mv) > 1e-9)
            sl = None
            if k.sum() > 50:      # result minus the close on the candidate's move (held out): does the close miss it?
                bb = float((mv[k] @ (yy[k] - ln[k])) / (mv[k] @ mv[k]))
                r_ = (yy[k] - ln[k]) - bb * mv[k]
                sl = [round(bb, 2), round(bb / math.sqrt(float(r_ @ r_) / (k.sum() - 1) / float(mv[k] @ mv[k])), 2)]
            rows[lab] = {'tune': cmp(e1, eb, A), 'held': cmp(e1, eb, B), 'coef': {f: round(float(b[f]), 3) for f in new} or
                         {'inj': round(float(b.get('inj', 0)), 3)}, 'vsCloseHeld': sl}
            print(name, lab, rows[lab], flush=True)
        pick = min(rows, key=lambda k_: rows[k_]['tune']['d'])
        res[name] = {'cells': rows, 'pick': pick, 'tuneT': rows[pick]['tune']['t'], 'heldT': rows[pick]['held']['t'],
                     'heldP': rows[pick]['held']['p']}

    if os.environ.get('DIAG'):       # post hoc, descriptive: by season, and the reserve cost inside the injury term
        for _, x, _ in D:
            for hl in HL:
                x[f'injir_{hl}'] = x['inj'] + x[f'ir_all_{hl}']
        cells = {'ir_all_None': base + ['ir_all_None'], 'ir_all_8': base + ['ir_all_8'], 'ir_in_None': base + ['ir_in_None']}
        cells.update({f'join_{hl}': [f if f != 'inj' else f'injir_{hl}' for f in base] for hl in HL})
        diag = {}
        for lab, feats in cells.items():
            e1, p1, b = wf(feats)
            by = {int(s_): round(float((e1 - e0)[(S == s_) & ok].mean()), 3) for s_ in range(2016, LAST + 1)}
            sdx = {int(s_): round(float(np.std([x[feats[-1] if lab[0] == 'i' else f'injir_{lab[5:]}' if lab != 'join_None' else 'injir_None'] for (g, x, _), ss in zip(D, S) if ss == s_])), 2) for s_ in (2017, 2019, 2021, 2023, 2025)}
            diag[lab] = {'tune': cmp(e1, e0, A), 'held': cmp(e1, e0, B), 'tune1720': cmp(e1, e0, A & (S >= 2017)), 'bySeason': by, 'sd': sdx,
                         'coef': round(float(b[feats[-1]] if lab[0] == 'i' else b[[f for f in feats if f.startswith('injir')][0]]), 3)}
            print('DIAG', lab, diag[lab], flush=True)
        old = json.load(open(OUT)); old['games']['A1_diag_posthoc'] = diag
        json.dump(old, open(OUT, 'w'), indent=1)
        return
    run('A1_ir' + ('_offReport' if os.environ.get('IR_CLEAN') else ''), {f'{sc}_{hl}': base + [f'ir_{sc}_{hl}'] for sc in ('in', 'all') for hl in HL})
    if os.environ.get('IR_CLEAN'):      # the diagnostic rerun writes only its own block
        old = json.load(open(OUT)); old['games'].update({k: v for k, v in res.items() if k.startswith('A1_ir_')})
        json.dump(old, open(OUT, 'w'), indent=1)
        return
    run('A2_qbr', {'replace': [f if f != 'qb' else 'qbr' for f in base], 'add': base + ['qbr']})
    # A3 swaps the injury term's values: same input name, so swap the column
    cells = {}
    for lam in LAM:
        for _, x, _ in D:
            x[f'inj@{lam}'] = x[f'injm_{lam}']
        cells[f'L{lam}'] = [f if f != 'inj' else f'inj@{lam}' for f in base]
    run('A3_injContract', cells)
    run('B1_tqb', {'tqb': tbase + ['tqb']}, tot=True)
    run('B2_tinj', {'tinj': tbase + ['tinj']}, tot=True)

    try:
        old = json.load(open(OUT))
    except (OSError, ValueError):
        old = {}
    old['games'] = res
    json.dump(old, open(OUT, 'w'), indent=1)
    print(json.dumps({k: {kk: v[kk] for kk in ('pick', 'tuneT', 'heldT', 'heldP')} for k, v in res.items() if k[0] in 'AB'}, indent=1))


if __name__ == '__main__':
    main()
