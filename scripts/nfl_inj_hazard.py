#!/usr/bin/env python3
"""How long an injured NFL player stays out (Oct 25 2026, audit W2-H): the season sims' later weeks (nfl_games.season_views)
carried no non-QB injuries, and a QB listed out came back the next week unless he was on IR. This fits a discrete hazard
for games missed by this week's status and body part, and tests carrying it into the later weeks.

    python3 scripts/nfl_inj_hazard.py          # data/nfl_inj_hazard.json (the table nfl_games reads, and the tests)

  episodes   every player listed questionable, doubtful or out on the league's game status report (nflverse injuries,
             regular season 2016-25), and every player moved to a reserve list (IR, PUP, NFI: weekly rosters RES/PUP
             after being active), followed through the team's next MAXK games: missed (inactive or on a reserve list
             that week) or played (active). Cut, traded or retired ends the episode (censored).
  table      P(misses the team's j-th next game | status, body part group), j = 1..MAXK, each part's rate shrunk to the
             status's with M_PART pseudo-episodes; parts that fail the held-out test fold into 'any'.
  playerTest log loss of miss_j on 2021-25 with the table fit on 2016-20: status only vs status + body part.
  gameTest   margin MAE of each regular-season game at week w+k (k 1-4) forecast before week w: walk-forward team
             ratings as of week w (no hindsight), the coefficients fit on earlier seasons (nfl_season_backtest.coefs),
             with the week-w injury report carried by the table (non-QBs: P(miss) x WAR a game x 36, the game model's
             inj term; QBs: QB1 at his chance to be back, the week-w starter otherwise) against the old rule (non-QB
             injuries dropped after week w, a QB back the next week unless on a reserve list). Tables fit leave one
             season out on 2016-20 and on 2016-20 for 2021-25; paired t over games.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as N  # noqa: E402

OUT = os.path.join(N.ROOT, 'data', 'nfl_inj_hazard.json')
SEASONS = range(2016, 2026)
MAXK = 12
M_PART = 40.0
KS = (1, 2, 3, 4)
STATUSES = ('Questionable', 'Doubtful', 'Out', 'Reserve')
PARTS = {'knee': 'knee', 'acl': 'knee', 'mcl': 'knee', 'ankle': 'ankle', 'hamstring': 'hamstring',
         'concussion': 'concussion', 'head': 'concussion', 'shoulder': 'shoulder', 'foot': 'foot', 'toe': 'foot',
         'heel': 'foot', 'achilles': 'achilles', 'calf': 'calf', 'groin': 'groin/hip', 'hip': 'groin/hip',
         'quadricep': 'groin/hip', 'thigh': 'groin/hip', 'back': 'back', 'neck': 'back', 'illness': 'illness',
         'personal': 'non-injury', 'resting': 'non-injury', 'not injury': 'non-injury', 'hand': 'hand/arm',
         'thumb': 'hand/arm', 'finger': 'hand/arm', 'wrist': 'hand/arm', 'elbow': 'hand/arm', 'forearm': 'hand/arm',
         'ribs': 'torso', 'chest': 'torso', 'pectoral': 'torso', 'oblique': 'torso', 'abdomen': 'torso'}


def part_of(text):
    t = (text or '').lower()
    for k, v in PARTS.items():
        if k in t:
            return v
    return 'other' if t else 'none'


def schedule(games, y):
    """team -> sorted regular-season weeks it plays"""
    wk = defaultdict(set)
    for g in games:
        if int(g['season']) == y and g['game_type'] == 'REG':
            wk[N.team(g['home_team'])].add(int(g['week'])); wk[N.team(g['away_team'])].add(int(g['week']))
    return {t: sorted(v) for t, v in wk.items()}


def episodes(games, y):
    """[(team, week, gsis, pos, status, part, [1 missed / 0 played for the next games, until censored])]"""
    sch = schedule(games, y)
    ros = {}
    for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv')):
        if r.get('game_type', 'REG') == 'REG' and r['gsis_id']:
            ros[(int(r['week']), r['gsis_id'])] = (N.team(r['team']), r['status'])
    rep = {}
    for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
        if r.get('game_type', 'REG') == 'REG' and r['report_status'] in ('Questionable', 'Doubtful', 'Out'):
            rep[(N.team(r['team']), int(r['week']), r['gsis_id'])] = (r['position'], r['report_status'], part_of(r['report_primary_injury']))
    out = []

    def follow(t, w, gsis):
        ws = [x for x in sch.get(t, []) if x > w][:MAXK]
        o = []
        for x in ws:
            tt, st = ros.get((x, gsis), (None, None))
            if tt != t or st not in ('ACT', 'INA', 'RES', 'PUP'):
                break
            o.append(0 if st == 'ACT' else 1)
        return o
    for (t, w, gsis), (pos, st, pt) in rep.items():
        o = follow(t, w, gsis)
        if o:
            out.append((t, w, gsis, pos, st, pt, o))
    # moved to a reserve list: active (or inactive) the week before, on it this week
    prev = {}
    for (w, gsis), (t, st) in sorted(ros.items()):
        p = prev.get(gsis)
        if st in ('RES', 'PUP') and p and p[0] == w - 1 and p[1] == t and p[2] in ('ACT', 'INA') and w in sch.get(t, []):
            pt = rep.get((t, w - 1, gsis), (None, None, 'none'))[2]
            o = follow(t, w, gsis)
            if o:
                out.append((t, w, gsis, '', 'Reserve', pt, o))
        prev[gsis] = (w, t, st)
    return out


def fit_table(eps, parts=True):
    """{status: {part: [P(miss game j)]}} with 'any' per status"""
    c = defaultdict(lambda: np.zeros((2, MAXK)))
    for e in eps:
        o = e[6]
        for key in ((e[4], 'any'), (e[4], e[5])):
            c[key][0, :len(o)] += o; c[key][1, :len(o)] += 1
    tab = {}
    for st in STATUSES:
        a = c[(st, 'any')]
        base = (a[0] + 0.5) / (a[1] + 1)
        tab[st] = {'any': base}
        if parts:
            for (s2, pt), v in c.items():
                if s2 == st and pt != 'any':
                    tab[st][pt] = (v[0] + M_PART * base) / (v[1] + M_PART)
    return tab


def p_miss(tab, st, pt, j):
    t = tab.get(st)
    if not t or j < 1:
        return 0.0
    v = t.get(pt, t['any'])
    return float(v[min(j, MAXK) - 1])


def player_test(E):
    tune = [e for y in range(2016, 2021) for e in E[y]]
    held = [e for y in range(2021, 2026) for e in E[y]]
    res = {}
    for name, parts in (('status', False), ('statusPart', True)):
        tab = fit_table(tune, parts)
        ll = []
        for e in held:
            for j, m in enumerate(e[6][:4], 1):
                p = min(max(p_miss(tab, e[4], e[5], j), 1e-3), 1 - 1e-3)
                ll.append(-(m * math.log(p) + (1 - m) * math.log(1 - p)))
        res[name] = np.array(ll)
    d = res['statusPart'] - res['status']
    return {'held': '2021-25 (games 1-4 after the report)', 'n': int(len(d)), 'llStatus': round(float(res['status'].mean()), 4),
            'llStatusPart': round(float(res['statusPart'].mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)}


def values(games, y):
    """(team, week) -> [(gsis, WAR a game)] for the players on that week's report, on the ledger before the week
    (nfl_games.injury_history's values)."""
    import nfl_war as W
    maps = W.gsis_map(y)
    prev = W.war_ledger(y - 1, maps=W.gsis_map(y - 1))
    led = {w: W.war_ledger(y, thru=w, maps=maps) for w in range(1, 19)}
    out = {}
    for r in N.rows(N.get(f'injuries_{y}.csv', f'{N.REL}/injuries/injuries_{y}.csv')):
        if r.get('game_type', 'REG') == 'REG' and r['report_status'] in ('Questionable', 'Doubtful', 'Out'):
            w = int(r['week'])
            L = led[min(w, 18)]
            out[(N.team(r['team']), w, r['gsis_id'])] = max(N.player_value(prev.get(r['gsis_id'], (0.0, 0)), L.get(r['gsis_id'], (0.0, 0))), 0.0)
    return out


def walk_snaps(G, box, qbs, params):
    """Before each regular-season week of 2016-25: each team's elo/mkt parts, its QB rate, and every QB's value."""
    m = N.Model(**params)
    snaps = {}
    for g in G:
        s, wk = int(g['season']), int(g['week'])
        m.feats(g)
        if s in SEASONS and g['game_type'] == 'REG' and (s, wk) not in snaps:
            snaps[(s, wk)] = {'elo': {t: (m.elo[t] - 1505) / 25 for t in N.DIV_OF}, 'mkt': {t: m.mkt[t] for t in N.DIV_OF},
                              'qbt': {t: m.rate(m.qbt, t, m.repl) for t in N.DIV_OF},
                              'qv': {q: m.qbval(q) for q in list(m.qb)}, 'repl': m.repl}
        m.update(g, box, qbs)
    return snaps


def main():
    import nfl_season_backtest as SB
    games = list(N.rows(N.get('games.csv', N.GAMES)))
    E = {y: episodes(games, y) for y in SEASONS}
    print('episodes', {y: len(v) for y, v in E.items()})
    pt = player_test(E)
    print('player test', pt)
    use_parts = pt['t'] < -2
    F = json.load(open(N.FIT))
    G, box, qbs = N.load(2025)
    N.index_qbs(qbs, G); N.load_qb_teams(2025)
    inj = N.injury_history(G, range(N.INJ_FIRST, 2026))
    data, _ = SB.walk(G, box, qbs, F['params'], inj, ())
    B = SB.coefs(data)[0]
    snaps = walk_snaps(G, box, qbs, F['params'])
    vals = {}
    vc = os.path.join(N.CACHE, 'inj_hazard_vals_v1.json')
    try:
        vals = {int(k): v for k, v in json.load(open(vc)).items()}
    except (OSError, ValueError):
        pass
    for y in SEASONS:
        if y not in vals:
            vals[y] = {f'{t}|{w}|{g}': v for (t, w, g), v in values(G, y).items()}
            json.dump(vals, open(vc, 'w'))
    rest = lambda x: max(-7, min(7, N.num(x, 7) - 7))
    rows = []          # (season, k, err old, err new, err old qb, err new qb)
    for y in SEASONS:
        tab = fit_table([e for yy in range(2016, 2021) if yy != y for e in E[yy]], use_parts)
        sch = schedule(G, y)
        sg = [g for g in G if int(g['season']) == y and g['game_type'] == 'REG' and g['home_score'] not in ('', 'NA')]
        # each team's week-w report: non-QBs and QBs, and its reserve moves (QBs)
        rep = defaultdict(list)
        for e in E[y]:
            rep[(e[0], e[1])].append(e)
        starts = defaultdict(list)
        for g in sg:
            for side in ('home', 'away'):
                starts[N.team(g[f'{side}_team'])].append((int(g['week']), g[f'{side}_qb_id']))
        rst = {(int(r['week']), r['gsis_id']): r['status'] for r in N.rows(N.get(f'roster_weekly_{y}.csv', f'{N.REL}/weekly_rosters/roster_weekly_{y}.csv'))
               if r.get('game_type', 'REG') == 'REG'}
        b = B[y]
        for w in range(1, 18):
            snap = snaps.get((y, w))
            if not snap:
                continue

            def qa(t, q):
                return (snap['qv'].get(q, snap['repl']) - snap['qbt'][t]) * 38 if q else 0.0

            def team_view(t, j):
                """(old non-QB cost, new non-QB cost, old QB part, new QB part) for t's j-th game after week w"""
                new = 0.0
                for e in rep.get((t, w), []):
                    if e[4] == 'Reserve' or e[3] == 'QB':
                        continue
                    v = vals[y].get(f'{t}|{w}|{e[2]}', 0.0)
                    new += p_miss(tab, e[4], e[5], j) * v * N.PTS_PER_WIN
                ss = [(wk, q) for wk, q in starts[t] if wk < w]
                cnt = defaultdict(int)
                for _, q in ss:
                    cnt[q] += 1
                qb1 = max(cnt, key=lambda q: (cnt[q], max(wk for wk, qq in ss if qq == q))) if cnt else ''
                now = next((q for wk, q in starts[t] if wk == w), qb1)
                # the old rule: QB1 back for the later games unless he is on a reserve list (then this week's starter)
                gone = rst.get((w, qb1)) in ('RES', 'PUP')
                old_q = qa(t, now if gone else qb1)
                e1 = next((e for e in rep.get((t, w), []) if e[2] == qb1 and e[4] != 'Reserve'), None)
                if e1 and not gone and now != qb1:
                    p = p_miss(tab, e1[4], e1[5], j)
                    new_q = p * qa(t, now) + (1 - p) * qa(t, qb1)
                else:
                    new_q = old_q
                return new, new_q, old_q
            for g in sg:
                k = int(g['week']) - w
                if k not in KS:
                    continue
                h, a = N.team(g['home_team']), N.team(g['away_team'])
                jh = sum(1 for x in sch[h] if w <= x < int(g['week'])); ja = sum(1 for x in sch[a] if w <= x < int(g['week']))
                base = (b['elo'] * (snap['elo'][h] - snap['elo'][a]) + b['mkt'] * (snap['mkt'][h] - snap['mkt'][a])
                        + b['home'] * (0 if g['location'] == 'Neutral' else 1) + b['rest'] * (rest(g['home_rest']) - rest(g['away_rest'])))
                nh, qh_new, qh_old = team_view(h, jh)
                na, qa_new, qa_old = team_view(a, ja)
                y_ = N.num(g['result'])
                old = base + b['qb'] * (qh_old - qa_old)
                rows.append((y, k, abs(y_ - old), abs(y_ - (old + b['inj'] * (na - nh))),
                             abs(y_ - (base + b['qb'] * (qh_new - qa_new))), int(qh_new != qh_old or qa_new != qa_old)))
    R = np.array(rows, float)
    gt = {}
    for lab, lo, hi in (('2016-20', 2016, 2020), ('2021-25', 2021, 2025)):
        sel = (R[:, 0] >= lo) & (R[:, 0] <= hi)
        d = R[sel, 3] - R[sel, 2]; dq = R[sel, 4] - R[sel, 2]
        touched = sel & (R[:, 5] == 1)
        dqt = R[touched, 4] - R[touched, 2]
        tt = lambda x: round(float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))), 2) if len(x) > 2 and x.std() > 0 else None
        gt[lab] = {'n': int(sel.sum()), 'maeOld': round(float(R[sel, 2].mean()), 4),
                   'maeNonQb': round(float(R[sel, 3].mean()), 4), 'tNonQb': tt(d),
                   'maeQb': round(float(R[sel, 4].mean()), 4), 'tQb': tt(dq),
                   'qbGames': int(touched.sum()), 'qbGamesMaeOld': round(float(R[touched, 2].mean()), 3) if touched.any() else None,
                   'qbGamesMaeNew': round(float(R[touched, 4].mean()), 3) if touched.any() else None, 'tQbGames': tt(dqt),
                   'byK': {str(k): {'old': round(float(R[sel & (R[:, 1] == k), 2].mean()), 3),
                                    'nonQb': round(float(R[sel & (R[:, 1] == k), 3].mean()), 3),
                                    'qb': round(float(R[sel & (R[:, 1] == k), 4].mean()), 3)} for k in KS}}
    print(json.dumps(gt, indent=1))
    full = fit_table([e for y in SEASONS for e in E[y]], use_parts)
    out = {'asof': '2026-10-25', 'maxk': MAXK, 'parts': use_parts, 'playerTest': pt, 'gameTest': gt,
           'table': {st: {p: [round(float(x), 3) for x in v] for p, v in d.items()} for st, d in full.items()},
           'n': {st: sum(1 for y in SEASONS for e in E[y] if e[4] == st) for st in STATUSES}}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=1)


if __name__ == '__main__':
    main()
