#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Soccer GAR replacement line + functional positions (Nov 27 2026) -> data/soccer_repl_research_nov27.json.

    python3 scripts/soccer_repl_research_nov27.py <transfermarkt dump dir>

Questions (from a reader of the Process methodology):
  1 How stable is the replacement line (regulars on the bottom three sides by goal difference) across seasons?
  2 Does it carry institutional collapse (sides that give up mid-season, call up the academy)?
  3 How sensitive is it to positional granularity (GK/D/M/F vs GK/FB/CB/DM/CM/AM/W/ST), and how much of the spread
    of value inside D/M/F is functional role rather than quality?

Values: the shipped fit (data/soccer_war_fit.json) on the cached player rows, value a 90 on the one big-five scale
(soccer_players.gar_of). Functional role: each player-season's modal Understat starting position (soccer_players ROLE_US, --roles), next to
Transfermarkt's lineups (dcaribou/transfermarkt-datasets game_lineups) through the Understat->Transfermarkt link for
agreement. Collapse: Understat results, second-half points a match (soccer_players.collapse_of).

Pre-registered (before results):
  Lines (each a minutes-weighted value a 90 by position, regulars = 900+ minutes for the club):
    L0 shipped  bottom three sides by goal difference a match, every finished league-season pooled
    L1 skip1    the 2nd-4th worst sides (drops the single worst side of each league-season)
    L2 nocoll   bottom three, dropping collapsed sides (second-half points a match < .6 and below their first half)
    L3 safe     the 4th-6th worst sides (sides that stayed up)
    L4 pctl     the 15th percentile (minutes-weighted) of all regulars at the position, every league-season
    L5 median   the median of the bottom-three sides' own position lines (robust to one broken side)
  Held-out targets, season S (lines built on the other finished seasons only):
    T1 free arrivals: players in their first season at a big-five club who came on a free transfer, from the club's
       own academy / reserve side, or from outside the big five for a fee under 1m (Transfermarkt transfers), 450+
       minutes, minutes-weighted value a 90 by position
    T2 promoted sides' regulars in their first season up, by position
  Gate: a line replaces L0 only if its squared error to BOTH targets is lower in a majority of seasons with paired
  t <= -2 over seasons (Holm over L1-L5).
  Granularity:
    G1 share of the spread of value a 90 (regulars) inside D / M / F explained by functional role (eta squared),
       next to the same share for the raw inputs (npxG, xA, buildup a 90), and the year-to-year correlation of value
       a 90 inside each role (quality is what repeats)
    G2 the bottom-three line by functional role vs by D/M/F, and how many GAR ranks move
    G3 held out: next-season value a 90 (same player, 900+ both) predicted from this season's value shrunk toward
       the D/M/F mean vs toward the functional-role mean (shrink k picked on the other seasons); and the team
       goal-difference harness (last season's rates at this season's minutes, leave-one-season-out) with rates
       shrunk to the functional-role mean instead of the D/M/F mean. Same gate (paired t <= -2, majority).
"""
import csv
import gzip
import json
import math
import os
import sys
from collections import defaultdict, Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import soccer_data as D  # noqa: E402
import soccer_players as SP  # noqa: E402

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'data', 'soccer_repl_research_nov27.json')
TMC = {'GB1': 'eng.1', 'ES1': 'esp.1', 'IT1': 'ita.1', 'L1': 'ger.1', 'FR1': 'fra.1'}
ROLE = {'Goalkeeper': 'GK', 'Centre-Back': 'CB', 'Sweeper': 'CB', 'Left-Back': 'FB', 'Right-Back': 'FB',
        'Defensive Midfield': 'DM', 'Central Midfield': 'CM', 'Attacking Midfield': 'AM', 'Left Midfield': 'W',
        'Right Midfield': 'W', 'Left Winger': 'W', 'Right Winger': 'W', 'Centre-Forward': 'ST', 'Second Striker': 'ST'}
ROLES = ['GK', 'FB', 'CB', 'DM', 'CM', 'AM', 'W', 'ST']
POSS = ('GK', 'D', 'M', 'F')


def rd(dump, name):
    with gzip.open(os.path.join(dump, name + '.csv.gz'), 'rt') as fh:
        yield from csv.DictReader(fh)


def wmean(g, key='v'):
    m = sum(r['min'] for r in g)
    return sum(r[key] * r['min'] for r in g) / m if m else float('nan')


def wpct(g, q):
    g = sorted(g, key=lambda r: r['v'])
    tot = sum(r['min'] for r in g); c = 0
    for r in g:
        c += r['min']
        if c >= q * tot:
            return r['v']
    return float('nan')


def tstat(d):
    d = np.array(d, float)
    return float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if len(d) > 2 and d.std() > 0 else 0.0


def main(dump):
    F = json.load(open(SP.FIT))
    rows = D.load(SP.ROWS)
    SP.prep(rows, F['shrink'])
    LS = SP.league_strength()
    cur = D.current_season()
    for r in rows:
        r['v'] = SP.value(r, F) + SP.lg_adj(r, F, LS)
    done = [r for r in rows if r['S'] < cur]
    seasons = sorted({r['S'] for r in done})

    # ---------------- Transfermarkt: games, lineups, transfers
    link = D.load(SP.MV_LINK)['p']
    tm2us = defaultdict(list)
    for u, t in link.items():
        tm2us[str(t)].append(u)
    games = {}
    for g in rd(dump, 'games'):
        if g['competition_id'] in TMC and g['home_club_goals'] != '':
            games[g['game_id']] = (TMC[g['competition_id']], int(g['season']) + 1, g['date'], g['home_club_id'],
                                   g['away_club_id'], int(g['home_club_goals']), int(g['away_club_goals']))
    print('games', len(games), flush=True)
    rolec = defaultdict(Counter)                      # (us id, S, lg) -> Counter(role) over starts
    clubof = defaultdict(Counter)                     # (us id, S, lg) -> TM club ids
    for l in rd(dump, 'game_lineups'):
        g = games.get(l['game_id'])
        if not g or l['player_id'] not in tm2us:
            continue
        for u in tm2us[l['player_id']]:
            k = (u, g[1], g[0])
            clubof[k][l['club_id']] += 1
            if l['type'] == 'starting_lineup' and l['position'] in ROLE:
                rolec[k][ROLE[l['position']]] += 1
    for r in rows:                                    # role = Understat's (the rows, soccer_players --roles); tmrole beside it
        c = rolec.get((r['p'], r['S'], r['lg']))
        r['tmrole'] = c.most_common(1)[0][0] if c else None
    # Understat team -> TM club (majority of its players)
    tclub = defaultdict(Counter)
    for r in rows:
        c = clubof.get((r['p'], r['S'], r['lg']))
        if c:
            tclub[(r['lg'], r['S'], r['tid'])][c.most_common(1)[0][0]] += r['min']
    tclub = {k: v.most_common(1)[0][0] for k, v in tclub.items()}
    # results by club-season: first and second half points a match
    res = defaultdict(list)
    for gid, (lg, S, day, h, a, hg, ag) in games.items():
        res[(lg, S, h)].append((day, 3 if hg > ag else 1 if hg == ag else 0))
        res[(lg, S, a)].append((day, 3 if ag > hg else 1 if hg == ag else 0))
    half = {}
    for k, v in res.items():
        v.sort(); n = len(v) // 2
        half[k] = (sum(p for _, p in v[:n]) / max(n, 1), sum(p for _, p in v[n:]) / max(len(v) - n, 1))
    # transfers: first big-five club season and how he arrived
    arrive = {}                                       # (tm id, to club, S) -> (fee, from name)
    for t in rd(dump, 'transfers'):
        try:
            y = int(t['transfer_season'][:2]) + 2001
        except ValueError:
            continue
        arrive[(t['player_id'], t['to_club_id'], y)] = (float(t['transfer_fee'] or -1), t['from_club_name'], t['from_club_id'])
    print('roles on', sum(1 for r in done if r['role']), 'of', len(done), 'player-seasons', flush=True)

    # ---------------- team-seasons, ranks
    team = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        t = team[(r['lg'], r['S'], r['tid'])]; t[0] += r['gf'] - r['ga']; t[1] += r['min']
    by = defaultdict(list)
    for (lg, S, tid), (gd, mn) in team.items():
        if mn > 0 and S < cur:
            by[(lg, S)].append((gd / 11 / (mn / 990), tid))
    rank = {}
    for (lg, S), v in by.items():
        for i, (_, tid) in enumerate(sorted(v), 1):
            rank[(lg, S, tid)] = i
    CS = SP.collapsed(cur)                            # Understat's results (soccer_players.collapse_of)
    coll = {k: k in CS for k in rank}
    tmc = 0
    for k, rk in rank.items():                        # the same rule on Transfermarkt's results, for agreement
        c = tclub.get(k)
        h = half.get((k[0], k[1], c)) if c else None
        tmc += bool(h and h[1] < 0.6 and h[1] < h[0]) == coll[k]
    collapsed = sorted([k for k, rk in rank.items() if rk <= 3 and coll[k]])

    def reg(r):
        return r['min'] >= 900

    def line(rs, kind, key='pos', keys=POSS):
        out = {}
        for pos in keys:
            g = [r for r in rs if r[key] == pos and reg(r)]
            rk = lambda r: rank.get((r['lg'], r['S'], r['tid']), 99)
            if kind == 'L0':
                s = [r for r in g if rk(r) <= 3]
            elif kind == 'L1':
                s = [r for r in g if 2 <= rk(r) <= 4]
            elif kind == 'L2':
                s = [r for r in g if rk(r) <= 3 and not coll.get((r['lg'], r['S'], r['tid']))]
            elif kind == 'L3':
                s = [r for r in g if 4 <= rk(r) <= 6]
            elif kind == 'L4':
                out[pos] = wpct(g, 0.15); continue
            elif kind == 'L5':
                tl = defaultdict(list)
                for r in g:
                    if rk(r) <= 3:
                        tl[(r['lg'], r['S'], r['tid'])].append(r)
                out[pos] = float(np.median([wmean(x) for x in tl.values()])) if tl else float('nan'); continue
            out[pos] = wmean(s)
        return out

    R = {'note': 'values from the shipped fit on the cached rows; roles = modal Understat starting position (tmrole: Transfermarkt)',
         'collapseAgreeTM': round(tmc / len(rank), 3),
         'roleAgreeTM': round(float(np.mean([r['role'] == r['tmrole'] for r in done if r['min'] >= 900 and r['role'] and r['tmrole']])), 3),
         'seasons': seasons, 'rolesMatched': round(sum(1 for r in done if r['role'] and reg(r)) / sum(1 for r in done if reg(r)), 3)}

    # ---------------- 1 stability
    st = {}
    for pos in POSS:
        per = []
        boot = []
        for (lg, S) in sorted(by):
            g = [r for r in done if r['lg'] == lg and r['S'] == S and r['pos'] == pos and reg(r) and rank.get((lg, S, r['tid']), 99) <= 3]
            if len(g) < 2:
                continue
            per.append((lg, S, wmean(g)))
            rng = np.random.default_rng(1)
            bs = []
            for _ in range(200):
                s = [g[i] for i in rng.integers(0, len(g), len(g))]
                bs.append(wmean(s))
            boot.append(np.var(bs))
        vals = np.array([x[2] for x in per])
        seas = {S: wmean([r for r in done if r['S'] == S and r['pos'] == pos and reg(r) and rank.get((r['lg'], S, r['tid']), 99) <= 3]) for S in seasons}
        lgs = {lg: wmean([r for r in done if r['lg'] == lg and r['pos'] == pos and reg(r) and rank.get((lg, r['S'], r['tid']), 99) <= 3]) for lg in TMC.values()}
        loso = [line([r for r in done if r['S'] != S], 'L0')[pos] for S in seasons]
        sd_obs = float(vals.std(ddof=1)); sd_noise = float(math.sqrt(np.mean(boot)))
        st[pos] = {'pooled': round(F['repl'][pos], 4), 'sdLeagueSeason': round(sd_obs, 4), 'sdSamplingNoise': round(sd_noise, 4),
                   'sdTrue': round(math.sqrt(max(0, sd_obs ** 2 - sd_noise ** 2)), 4),
                   'bySeason': {S: round(v, 4) for S, v in seas.items()}, 'sdSeasonPooled': round(float(np.std(list(seas.values()), ddof=1)), 4),
                   'byLeague': {k: round(v, 4) for k, v in lgs.items()},
                   'losoRange': [round(min(loso), 4), round(max(loso), 4)],
                   'garSwing30': round(float(np.std(list(seas.values()), ddof=1)) * 30, 2)}
    R['stability'] = st
    # how big a GAR swing a season-specific line would make for a 30-match regular, vs the spread of GAR
    gr = [r for r in done if reg(r)]
    R['garSdRegulars'] = round(float(np.std([(r['v'] - F['repl'][r['pos']]) * r['min'] / 90 for r in gr])), 2)

    # ---------------- 2 collapse
    R['collapse'] = {'bottom3': sum(1 for k, v in rank.items() if v <= 3), 'collapsed': len(collapsed),
                     'sides': [f'{lg} {S - 1}-{S % 100:02d} {next((r["team"] for r in done if (r["lg"], r["S"], r["tid"]) == (lg, S, t)), t)}'
                               for lg, S, t in collapsed]}
    # do collapsed sides' regulars rate lower than other bottom-three regulars (same position)?
    cmp = {}
    for pos in POSS:
        a = [r for r in done if r['pos'] == pos and reg(r) and rank.get((r['lg'], r['S'], r['tid']), 99) <= 3]
        c = [r for r in a if coll.get((r['lg'], r['S'], r['tid']))]
        o = [r for r in a if not coll.get((r['lg'], r['S'], r['tid']))]
        cmp[pos] = {'collapsed': round(wmean(c), 4) if c else None, 'other': round(wmean(o), 4), 'nColl': len(c)}
    R['collapse']['valueByPos'] = cmp

    # ---------------- targets
    big5_clubs = defaultdict(set)                     # tm id -> set of (S) seasons at a big-five club before
    first = {}
    for r in sorted(done, key=lambda r: r['S']):
        t = link.get(r['p'])
        if t is None:
            continue
        first.setdefault(str(t), r['S'])
    youth = (' U19', ' U21', ' U23', ' U18', ' U17', ' II', ' B', ' Youth', ' Reserves', ' Jgd.', ' Primavera', ' Juvenil')
    tset = defaultdict(list)
    for r in done:
        if r['min'] < 450:
            continue
        t = link.get(r['p'])
        if t is None or first.get(str(t)) != r['S'] or r['S'] == seasons[0]:
            continue
        c = tclub.get((r['lg'], r['S'], r['tid']))
        a = arrive.get((str(t), c, r['S']))
        if not a:
            continue
        fee, frm, fid = a
        free = fee == 0 and 'loan' not in frm.lower()
        acad = any(frm.endswith(y) or (y + ' ') in frm for y in youth)
        cheap = 0 <= fee < 1e6
        if free or acad or cheap:
            tset[(r['S'], r['pos'])].append(r)
    prom = defaultdict(list)
    tids = defaultdict(set)
    for (lg, S, tid) in rank:
        tids[(lg, S)].add(tid)
    for r in done:
        if reg(r) and r['S'] > seasons[0] and r['tid'] not in tids.get((r['lg'], r['S'] - 1), {r['tid']}):
            prom[(r['S'], r['pos'])].append(r)
    T = {'T1': {k: (wmean(v), sum(x['min'] for x in v)) for k, v in tset.items()},
         'T2': {k: (wmean(v), sum(x['min'] for x in v)) for k, v in prom.items()}}
    R['targets'] = {n: {pos: round(wmean([r for (S, p), v in src.items() if p == pos for r in v]), 4) for pos in POSS}
                    for n, src in (('T1', tset), ('T2', prom))}
    R['targets']['n'] = {'T1': sum(len(v) for v in tset.values()), 'T2': sum(len(v) for v in prom.values())}
    kinds = ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']
    err = {k: {'T1': {}, 'T2': {}} for k in kinds}
    for S in seasons[1:]:
        trn = [r for r in done if r['S'] != S]
        for k in kinds:
            Lk = line(trn, k)
            for tn in ('T1', 'T2'):
                e = []; w = []
                for pos in POSS:
                    if (S, pos) in T[tn]:
                        m, mn = T[tn][(S, pos)]
                        e.append((Lk[pos] - m) ** 2 * mn); w.append(mn)
                err[k][tn][S] = sum(e) / sum(w)
    lines = {k: {p: round(v, 4) for p, v in line(done, k).items()} for k in kinds}
    gate = {}
    for k in kinds[1:]:
        g = {}
        for tn in ('T1', 'T2'):
            d = [err[k][tn][S] - err['L0'][tn][S] for S in err[k][tn]]
            g[tn] = {'mse': round(float(np.mean(list(err[k][tn].values()))), 5), 'mse0': round(float(np.mean(list(err['L0'][tn].values()))), 5),
                     't': round(tstat(d), 2), 'better': f'{sum(x < 0 for x in d)}/{len(d)}'}
        g['pass'] = all(g[tn]['t'] <= -2 and int(g[tn]['better'].split('/')[0]) * 2 > int(g[tn]['better'].split('/')[1]) for tn in ('T1', 'T2'))
        gate[k] = g
    # mean signed gap of the shipped line to the targets (line - target): which way it leans
    R['lines'] = lines
    R['lineGate'] = gate
    R['bias0'] = {tn: round(float(np.mean([(lines['L0'][p] - T[tn][(S, p)][0]) for (S, p) in T[tn]])), 4) for tn in ('T1', 'T2')}
    # rank stability of GAR under each line
    def gar_rank(L):
        v = [(r['v'] - L[r['pos']]) * r['min'] / 90 for r in gr]
        return np.argsort(np.argsort(-np.array(v)))
    r0 = gar_rank(lines['L0'])
    R['rankCorr'] = {k: round(float(np.corrcoef(r0, gar_rank(lines[k]))[0, 1]), 4) for k in kinds[1:]}

    # ---------------- 3 granularity
    gm = [r for r in done if reg(r) and r['role'] and r['pos'] != 'GK']
    G1 = {}
    m90 = lambda r: r['min'] / 90
    feats = {'value': lambda r: r['v'], 'npxg90': lambda r: (r['x'] - r['pen']) / m90(r), 'xa90': lambda r: r['xA'] / m90(r),
             'bup90': lambda r: r['bu'] / m90(r)}
    for pos in ('D', 'M', 'F'):
        g = [r for r in gm if r['pos'] == pos]
        out = {'n': len(g), 'roles': dict(Counter(r['role'] for r in g).most_common())}
        for fn, fx in feats.items():
            x = np.array([fx(r) for r in g]); w = np.array([r['min'] for r in g], float)
            mu = np.average(x, weights=w)
            tot = np.average((x - mu) ** 2, weights=w)
            between = 0.0
            for ro in set(r['role'] for r in g):
                ix = np.array([r['role'] == ro for r in g])
                between += w[ix].sum() / w.sum() * (np.average(x[ix], weights=w[ix]) - mu) ** 2
            out['eta2_' + fn] = round(float(between / tot), 3)
        G1[pos] = out
    # quality: year-to-year correlation of value a 90 within role (900+ both seasons, same coarse position)
    prev = {(r['p'], r['S']): r for r in done if reg(r)}
    yy = defaultdict(list)
    for r in gm:
        q = prev.get((r['p'], r['S'] - 1))
        if q and q['pos'] == r['pos']:
            yy[r['role']].append((q['v'], r['v'], q.get('role') == r['role']))
    G1['yearToYear'] = {ro: {'r': round(float(np.corrcoef([a for a, _, _ in v], [b for _, b, _ in v])[0, 1]), 3), 'n': len(v),
                             'sameRole': round(float(np.mean([s for _, _, s in v])), 3)} for ro, v in sorted(yy.items())}
    G1['roleStability'] = round(float(np.mean([s for v in yy.values() for _, _, s in v])), 3)
    R['G1'] = G1
    # G2 lines by role
    roleline = {}
    for ro in ROLES:
        g = [r for r in done if r['role'] == ro and reg(r) and rank.get((r['lg'], r['S'], r['tid']), 99) <= 3]
        a = [r for r in done if r['role'] == ro and reg(r)]
        roleline[ro] = {'repl': round(wmean(g), 4), 'avg': round(wmean(a), 4), 'n': len(g),
                        'coarse': Counter(r['pos'] for r in a).most_common(1)[0][0]}
    R['G2'] = {'roleLine': roleline}
    rl = {ro: v['repl'] for ro, v in roleline.items()}
    gx = [r for r in gr if r['role']]
    a0 = np.array([(r['v'] - lines['L0'][r['pos']]) * r['min'] / 90 for r in gx])
    a1 = np.array([(r['v'] - rl[r['role']]) * r['min'] / 90 for r in gx])
    rk0 = np.argsort(np.argsort(-a0)); rk1 = np.argsort(np.argsort(-a1))
    R['G2']['rankCorr'] = round(float(np.corrcoef(rk0, rk1)[0, 1]), 4)
    R['G2']['medianRankMove'] = int(np.median(np.abs(rk0 - rk1)))
    R['G2']['garMoveByRole'] = {ro: round(float(np.mean([a1[i] - a0[i] for i, r in enumerate(gx) if r['role'] == ro])), 2) for ro in ROLES}
    # top-50 overlap per season
    ov = []
    for S in seasons:
        ix = [i for i, r in enumerate(gx) if r['S'] == S]
        t0 = set(sorted(ix, key=lambda i: -a0[i])[:50]); t1 = set(sorted(ix, key=lambda i: -a1[i])[:50])
        ov.append(len(t0 & t1) / 50)
    R['G2']['top50Overlap'] = round(float(np.mean(ov)), 3)

    # G4 held out: replacement by functional role vs by D/M/F, scored on the targets grouped by role
    def role_line(rs, kind):
        out = {}
        for ro in ROLES:
            g = [r for r in rs if r['role'] == ro and reg(r) and rank.get((r['lg'], r['S'], r['tid']), 99) <= 3
                 and (kind == 'L0' or not coll.get((r['lg'], r['S'], r['tid'])))]
            out[ro] = wmean(g)
        return out
    TR = {}
    for tn, src in (('T1', tset), ('T2', prom)):
        acc = defaultdict(list)
        for (S, p), v in src.items():
            for r in v:
                if r['role'] and r['pos'] != 'GK':
                    acc[(S, r['role'])].append(r)
        TR[tn] = {k: (wmean(v), sum(x['min'] for x in v), Counter(x['pos'] for x in v)) for k, v in acc.items()}
    g4 = {}
    for kind in ('L0', 'L2'):
        e = {'coarse': {'T1': {}, 'T2': {}}, 'role': {'T1': {}, 'T2': {}}}
        for S in seasons[1:]:
            trn = [r for r in done if r['S'] != S]
            Lc = line(trn, kind); Lr = role_line(trn, kind)
            for tn in ('T1', 'T2'):
                ec = er = w = 0.0
                for (S2, ro), (m, mn, pc) in TR[tn].items():
                    if S2 != S:
                        continue
                    c = sum(Lc[p] * n for p, n in pc.items()) / sum(pc.values())     # the coarse line its players carry
                    ec += (c - m) ** 2 * mn; er += (Lr[ro] - m) ** 2 * mn; w += mn
                e['coarse'][tn][S] = ec / w; e['role'][tn][S] = er / w
        g = {}
        for tn in ('T1', 'T2'):
            d = [e['role'][tn][S] - e['coarse'][tn][S] for S in e['role'][tn]]
            g[tn] = {'mseCoarse': round(float(np.mean(list(e['coarse'][tn].values()))), 5),
                     'mseRole': round(float(np.mean(list(e['role'][tn].values()))), 5), 't': round(tstat(d), 2),
                     'better': f'{sum(x < 0 for x in d)}/{len(d)}'}
        g4[kind] = g
    R['G4'] = g4
    R['targetsByRole'] = {tn: {ro: round(wmean([r for (S, p), v in src.items() for r in v if r['role'] == ro]), 4) for ro in ROLES}
                          for tn, src in (('T1', tset), ('T2', prom))}
    R['G2']['roleLineNoColl'] = {k: round(v, 4) for k, v in role_line(done, 'L2').items()}

    # G3a next-season value: shrink this season's value toward coarse vs role mean (k picked on other seasons)
    pairs = []
    for r in done:
        if not r['role'] or r['pos'] == 'GK' or r['min'] < 450:
            continue
        q = next_ = None
    nxt = {}
    for r in done:
        if r['min'] >= 900:
            nxt.setdefault((r['p'], r['S']), r)
    for r in done:
        if r['role'] and r['pos'] != 'GK' and r['min'] >= 450:
            n_ = nxt.get((r['p'], r['S'] + 1))
            if n_:
                pairs.append((r, n_))
    mu_pos = defaultdict(list); mu_role = defaultdict(list)

    def means(trn):
        a = defaultdict(lambda: [0.0, 0.0]); b = defaultdict(lambda: [0.0, 0.0])
        for r in trn:
            if r['role'] and r['pos'] != 'GK':
                a[r['pos']][0] += r['v'] * r['min']; a[r['pos']][1] += r['min']
                b[r['role']][0] += r['v'] * r['min']; b[r['role']][1] += r['min']
        return {k: s / m for k, (s, m) in a.items()}, {k: s / m for k, (s, m) in b.items()}

    def pred(r, mu, k, key):
        w = r['min'] / (r['min'] + k)
        return w * r['v'] + (1 - w) * mu[r[key]]
    KS = (0, 300, 900, 2000, 5000)
    e3 = {'pos': {}, 'role': {}}
    for S in sorted({r['S'] for r, _ in pairs}):
        trn = [r for r in done if r['S'] not in (S, S + 1)]
        mp, mr = means(trn)
        tp = [(r, n_) for r, n_ in pairs if r['S'] != S]
        te = [(r, n_) for r, n_ in pairs if r['S'] == S]
        for key, mu in (('pos', mp), ('role', mr)):
            best = min(KS, key=lambda k: np.mean([(pred(r, mu, k, key) - n_['v']) ** 2 for r, n_ in tp if r[key] in mu]))
            e3[key][S] = (float(np.mean([(pred(r, mu, best, key) - n_['v']) ** 2 for r, n_ in te])), best)
    d = [e3['role'][S][0] - e3['pos'][S][0] for S in e3['pos']]
    R['G3a'] = {'msePos': round(float(np.mean([v[0] for v in e3['pos'].values()])), 6),
                'mseRole': round(float(np.mean([v[0] for v in e3['role'].values()])), 6),
                'kPos': Counter(v[1] for v in e3['pos'].values()).most_common(1)[0][0],
                'kRole': Counter(v[1] for v in e3['role'].values()).most_common(1)[0][0],
                't': round(tstat(d), 2), 'better': f'{sum(x < 0 for x in d)}/{len(d)}', 'pairs': len(pairs)}

    # G3b team harness: rates shrunk toward the role mean instead of the D/M/F mean
    R['G3b'] = team_harness(F, rows, cur)
    json.dump(R, open(OUT, 'w'), indent=1, allow_nan=False, default=str)
    print(json.dumps({k: R[k] for k in R if k not in ('stability',)}, indent=1, default=str)[:6000])
    print(json.dumps(R['stability'], indent=1)[:3000])


def team_harness(F, rows, cur):
    """the GAR fit's own held-out test with the shrink target swapped (pos -> role, D/M/F where no role)"""
    import copy
    tsd = {}
    team = defaultdict(lambda: [0.0, 0.0])
    for r in rows:
        t = team[(r['lg'], r['S'], r['tid'])]; t[0] += r['gf'] - r['ga']; t[1] += r['min']
    for k, (gd, mn) in team.items():
        mp = mn / 990
        tsd[k] = {'gd': gd / 11, 'mp': mp, 'pts': 0}
    done = [r for r in rows if r['S'] < cur]
    res = {}
    for mode in ('pos', 'role'):
        rs = copy.deepcopy(done)
        SP.prep(rs, F['shrink'])
        if mode == 'role':                             # re-shrink every rate toward the role mean (D/M/F where none)
            sh = F['shrink']
            by = defaultdict(list)
            for r in rs:
                by[(r['lg'], r['S'])].append(r)
            for g_ in by.values():
                tot = sum(r['min'] for r in g_) or 1
                mu_rel = sum(r['_relpre'] * r['min'] for r in g_) / tot
                grp = defaultdict(list)
                for r in g_:
                    grp[r['role'] if r.get('role') and r['pos'] != 'GK' else r['pos']].append(r)
                for ps in grp.values():
                    pm = sum(r['min'] for r in ps) or 1
                    for k in [x for x in SP.FEATS if x not in SP.RAPM]:
                        mu = sum(r['_' + k] * r['min'] for r in ps) / pm
                        for r in ps:
                            w = r['min'] / (r['min'] + sh)
                            r[k] = w * r['_' + k] + (1 - w) * mu
                    pmu = sum((r['_relpre'] - mu_rel) * r['min'] for r in ps) / pm
                    for r in ps:
                        w = r['min'] / (r['min'] + 2 * sh)
                        r['rel'] = w * (r['_relpre'] - mu_rel) + (1 - w) * pmu
        ks, X, y = SP.design(rs, tsd, F['feats'], prior=True, priors=('lgm', 'new'), LS=SP.league_strength(), TMV={})
        S_arr = np.array([k[1] for k in ks])
        pred = np.zeros(len(y))
        for S in sorted(set(S_arr)):
            tr = S_arr != S
            b = SP.ridge(X[tr], y[tr], F['lambda'])
            pred[~tr] = X[~tr] @ b
        res[mode] = {int(S): float(np.mean((y[S_arr == S] - pred[S_arr == S]) ** 2)) for S in sorted(set(S_arr))}
    d = [res['role'][S] - res['pos'][S] for S in res['pos']]
    var = None
    return {'msePos': round(float(np.mean(list(res['pos'].values()))), 6), 'mseRole': round(float(np.mean(list(res['role'].values()))), 6),
            't': round(tstat(d), 2), 'better': f'{sum(x < 0 for x in d)}/{len(d)}'}


if __name__ == '__main__':
    main(sys.argv[1])
