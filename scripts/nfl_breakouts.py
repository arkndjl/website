#!/usr/bin/env python3
"""NFL breakouts tab (Noah, Nov 2 2026): each week's standout games by young players, against what we expected of them.

    python3 scripts/nfl_breakouts.py      # this season, every week played -> data/nfl_breakouts.json (stdlib; run by nfl.yml)

Young: a rookie, a player in his first three seasons (years_exp 0-2), or 24 or younger on Sept 1.

A week's WAR is the board's own (scripts/nfl_war.py board()): WAR through the week minus WAR before it, so it carries the
board's AV + XV blend and replacement accrues with the snaps he played that week.

Expected WAR for the week = his rate before the week x his snaps that week. The rate is the percentile projections' WAR rate
(scripts/player_pctl.py, data/pctl_fit_nfl.json): his last three seasons (Marcel 1 / .7 / .5) shrunk toward his group's rate,
then updated with the season before the week (normal-normal). A rookie with no NFL snaps starts at his group's newcomer rate.
SD = sqrt(noise a snap x snaps + rate variance x snaps^2), so z = (WAR - expected) / SD.

Ranked by WAR over expected (wins). z is shown beside it: a high z on few snaps is a small sample.
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'nfl_breakouts.json')
TOP = 40            # rows a week
MIN_SN = 10         # snaps in the week to be listed
AGE_MAX = 24
EXP_MAX = 2         # years_exp 0-2: seasons 1-3


def young(p):
    try:
        exp = int(p.get('exp'))
    except (TypeError, ValueError):
        exp = None
    return bool(p.get('rook')) or (exp is not None and exp <= EXP_MAX) or (p.get('age') is not None and p['age'] <= AGE_MAX)


def line(g, st):
    i = lambda k: int(round(st.get(k, 0)))
    if g == 'QB':
        s = f"{i('pass')} pass yds, {i('ptd')} TD, {i('pint')} INT"
        return s + (f", {i('rush')} rush yds" if st.get('rush', 0) >= 20 else '')
    if g == 'RB':
        return f"{i('car')} car, {i('rush')} rush yds, {i('recs')} rec, {i('rec')} rec yds" + (f", {i('rtd') + i('retd')} TD" if st.get('rtd', 0) + st.get('retd', 0) else '')
    if g in ('WR', 'TE'):
        return f"{i('recs')} rec, {i('rec')} yds" + (f", {i('retd')} TD" if st.get('retd', 0) else '')
    if g == 'OL':
        return ''
    parts = []
    if st.get('prss', 0): parts.append(f"{i('prss')} prss")
    if st.get('sack', 0): parts.append(f"{st['sack']:g} sk")
    parts.append(f"{i('tkl')} tkl")
    if st.get('tfl', 0): parts.append(f"{i('tfl')} TFL")
    if st.get('int', 0): parts.append(f"{i('int')} INT")
    if st.get('pd', 0): parts.append(f"{i('pd')} PD")
    if st.get('ff', 0): parts.append(f"{i('ff')} FF")
    return ', '.join(parts)


def build():
    import nfl_war as W
    import player_pctl as P
    games = list(W.rows(W.get('games.csv', W.GAMES)))
    reg = [g for g in games if g['game_type'] == 'REG']
    done = [g for g in reg if g['home_score'] not in ('', 'NA')]
    y = max(int(g['season']) for g in done)
    week = max(int(g['week']) for g in done if int(g['season']) == y)
    opp, tg_before = {}, {}
    for g in reg:
        if g['season'] != str(y):
            continue
        w = int(g['week'])
        opp[(g['home_team'], w)] = ('vs', g['away_team'])
        opp[(g['away_team'], w)] = ('at', g['home_team'])
    fit = json.load(open(P.FIT.format('nfl')))
    Rp = fit['rates']['war']
    R = P.Rate('value', Rp['K'], Rp['mu'], Rp['var'])
    H = P._load_hist('nfl')
    boards = {1: {}}
    for w in range(2, week + 2):
        out, _, _ = W.board(y, thru=w)
        boards[w] = {p['id']: p for p in out}
    tl = 17
    pw = []                  # (WAR over expected, snaps) for every player-week: the z spread
    weeks, best = {}, {}     # best: pid -> highest week WAR so far (season high note)
    for w in range(1, week + 1):
        before, after = boards[w], boards[w + 1]
        teams_before = {}
        for g in reg:
            if g['season'] == str(y) and int(g['week']) < w:
                for t in (g['home_team'], g['away_team']):
                    teams_before[t] = teams_before.get(t, 0) + 1
        allw, rows_w = [], []
        for pid, p in after.items():
            b = before.get(pid, {})
            sn = p['sn'] - b.get('sn', 0)
            if sn <= 0 or p['g'] <= b.get('g', 0):
                continue
            war = p.get('_war', p['war']) - b.get('_war', b.get('war', 0.0))
            allw.append((war, pid, sn, p, b))
        allw.sort(key=lambda r: -r[0])
        rank_all = {pid: i + 1 for i, (_, pid, _, _, _) in enumerate(allw)}
        for war, pid, sn, p, b in allw:
            prev_best = best.get(pid)
            best[pid] = war if prev_best is None else max(prev_best, war)
            grp = p['_g']
            m0, vet = R.prior(P.hist_of(H, y, pid, 'war'), grp)
            frac = max(0, tl - teams_before.get(p['t'], 0)) / tl
            loc, _ = P._cal(fit, 'war', frac)
            m1, _, _ = R.post(m0 + loc, grp, vet, b.get('_war', 0.0), b.get('sn', 0))
            x = m1 * sn
            pw.append((war - x, sn))
            if sn < MIN_SN or not young(p):
                continue
            st = {k: p['_st'].get(k, 0) - b.get('_st', {}).get(k, 0) for k in p['_st']}
            ha, op = opp.get((p['t'], w), ('', ''))
            notes = []
            if rank_all[pid] <= 50:
                notes.append(f"#{rank_all[pid]} in WAR, all players")
            if prev_best is not None and b.get('g', 0) >= 3 and war > prev_best:
                notes.append('season high')
            if w > 1 and b.get('g', 0) == 0:
                notes.append('first game this season')
            elif b.get('g', 0) and b['sn'] / b['g'] < 0.6 * sn:
                notes.append(f"snaps up from {b['sn'] / b['g']:.0f} a game")
            exp = str(p.get('exp', ''))
            rows_w.append({'n': p['n'], 'id': pid, 't': p['t'], 'ha': ha, 'op': op, 'pos': p['pos'], 'age': p.get('age'),
                           'yr': 'R' if p.get('rook') or exp == '0' else (int(exp) + 1 if exp.isdigit() else None),
                           'col': p.get('col', ''), 'sn': int(sn), 'war': round(war, 3), 'x': round(x, 3), 'ov': round(war - x, 3),
                           'rk': rank_all[pid], 'line': line(grp, st), 'note': '; '.join(notes), **({'ph': p['ph']} if p.get('ph') else {})})
        rows_w.sort(key=lambda r: -r['ov'])
        weeks[str(w)] = rows_w[:TOP]
    # z: the spread of WAR over expected in a game, fit on every player-week this season (all ages):
    # var = a x snaps + b x snaps^2 (least squares on the squared residuals, both terms >= 0)
    s11 = sum(sn * sn for _, sn in pw); s12 = sum(sn ** 3 for _, sn in pw); s22 = sum(sn ** 4 for _, sn in pw)
    t1 = sum(r * r * sn for r, sn in pw); t2 = sum(r * r * sn * sn for r, sn in pw)
    det = s11 * s22 - s12 * s12
    a, b2 = (s22 * t1 - s12 * t2) / det, (s11 * t2 - s12 * t1) / det
    if a < 0:
        a, b2 = 0.0, t2 / s22
    elif b2 < 0:
        a, b2 = t1 / s11, 0.0
    for rows_w in weeks.values():
        for r in rows_w:
            sd = math.sqrt(a * r['sn'] + b2 * r['sn'] ** 2)
            r['z'] = round(r['ov'] / sd, 1) if sd > 0 else None
    body = {'season': y, 'week': week, 'top': TOP, 'min': MIN_SN, 'age': AGE_MAX, 'sd': [round(a, 8), round(b2, 9)], 'n': len(pw), 'weeks': weeks}
    try:
        old = json.load(open(OUT))
        if {k: v for k, v in old.items() if k != 'asof'} == body:
            return print('nfl breakouts: no change')
    except (OSError, ValueError):
        pass
    body['asof'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(OUT, 'w') as f:
        json.dump(body, f, separators=(',', ':'))
    print(f'nfl breakouts: {y} weeks 1-{week}; week {week} top: ' +
          ', '.join(f"{r['n']} {r['ov']:+.2f}" for r in weeks[str(week)][:5]))


if __name__ == '__main__':
    build()
