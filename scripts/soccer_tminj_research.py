#!/usr/bin/env python3
"""Dated injury lists in the soccer game model (Oct 2026): Transfermarkt injury and absence spells
(scripts/soccer_tm_injuries.py) on match day, priced at each missing player's prior-season GAR a 90 x his usual
league minutes (Understat line-ups). Big five, walk-forward log loss, tune 2013-22 vs held out 2023+.

    python3 scripts/soccer_tminj_research.py      # -> data/soccer_tminj_research.json

Out on match day D: a spell that started before D and ends after D (or is still open). The end date is known only
afterwards, so this stands for pre-match team news (the close sees it too), not for what is known days ahead.
Usual minutes: mean over the club's last 10 league matches he was not out for (3+ such matches).
Terms: 'level' every missing player; 'fresh' spells that began in the last 21 days; 'change' missing now minus
missing at the club's previous league match (the part the market ratings from earlier closes haven't seen)."""
import bisect
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soccer_data as D
import soccer_games as G
import soccer_avail_research as A
import soccer_tm_injuries as T

OUT = os.path.join(G.ROOT, 'data', 'soccer_tminj_research.json')


TMC = {'eng.1': 'GB1', 'esp.1': 'ES1', 'ger.1': 'L1', 'ita.1': 'IT1', 'fra.1': 'FR1', 'uefa.champions': 'CL',
       'uefa.europa': 'EL', 'uefa.europa.conf': 'UCOL'}


def out_on(sp, day, kinds, comp=None):
    """spells covering day; a suspension counts only in its own competition (comp: the match's Transfermarkt id)"""
    return [s for s in sp if s[2] in kinds and s[0] < day and (s[1] is None or s[1] > day)
            and (s[2] == 'inj' or not s[5] or comp is None or s[5] == comp)]


def add_tm(rows, mode='level', kinds=('inj', 'abs'), fresh_days=21):
    link = D.load(T.LINK)['p']
    sp = {}
    for us, tm in link.items():
        p = os.path.join(T.CDIR, f'{tm}.json.gz')
        if os.path.exists(p):
            sp[us] = D.load(p) or []
    gv = {}

    def v(S, p):
        if S not in gv:
            try:
                gv[S] = {x['p']: x['gar90'] for x in json.load(open(os.path.join(A.WARD, f'{S}.json')))['players']}
            except (OSError, KeyError, ValueError):
                gv[S] = {}
        return gv[S].get(p, A.AV_V0)
    seq = defaultdict(list)
    for r in sorted((r for r in rows if r.get('us') and r.get('hs') is not None), key=lambda r: r['day']):
        m = D.us_match(r['us'])
        for s, t in (('h', r['h']), ('a', r['a'])):
            seq[t].append((r['day'], {str(x['player_id']): int(x['time'] or 0) for x in m['ro'][s]}, TMC[r['lg']]))
    days = {t: [x[0] for x in L] for t, L in seq.items()}
    import datetime as dt

    def missing(t, day, i, comp):
        """goals of value out on day, given the club's match index i (its last league match before day)"""
        L = seq[t]
        S = D.season_of(day)
        cut = (dt.date.fromisoformat(day) - dt.timedelta(days=fresh_days)).isoformat()
        tot = 0.0
        for p in set().union(*[x[1] for x in L[max(0, i - 9):i + 1]]):
            if p not in sp:
                continue
            o = out_on(sp[p], day, kinds, comp)
            if not o:
                continue
            if mode == 'fresh' and not any(s[0] >= cut for s in o):
                continue
            ms = [x[1].get(p, 0) for x in L[max(0, i - 9):i + 1] if not out_on(sp[p], x[0], kinds, x[2])]
            if len(ms) < 3:
                continue
            tot += v(S - 1, p) * (sum(ms) / len(ms)) / 90
        return tot

    def deficit(t, day, comp):
        L = seq.get(t)
        if not L:
            return 0.0
        i = bisect.bisect_left(days[t], day) - 1
        if i < 3 or (dt.date.fromisoformat(day) - dt.date.fromisoformat(L[i][0])).days > A.AV_DAYS:
            return 0.0
        x = missing(t, day, i, comp)
        if mode == 'change':
            x -= missing(t, L[i][0], i - 1, L[i][2])
        return x
    n = 0
    for r in rows:
        if r['lg'] in G.SCORED or r.get('us'):
            c = TMC.get(r['lg'])
            r['avz'] = round((deficit(r['a'], r['day'], c) - deficit(r['h'], r['day'], c)) / 2, 4)
            n += r['avz'] != 0
    print(mode, kinds, 'rows with a gap', n, flush=True)
    return rows


def main():
    rows = G.add_mv(G.add_market(D.load(G.HIST)))
    P = G.params()
    base = A.scores(rows, P)
    res = {'tests': []}
    for mode, kinds, avs in (('level', ('inj', 'abs'), (0.25, 0.5, 1.0)),
                             ('fresh', ('inj', 'abs'), (0.25, 0.5, 1.0)),
                             ('change', ('inj', 'abs'), (0.25, 0.5, 1.0)),
                             ('level', ('inj',), (0.5,)),
                             ('level', ('abs',), (0.5,))):
        add_tm(rows, mode, kinds)
        for av in avs:
            s = A.scores(rows, P, av)
            t = {'mode': mode, 'kinds': list(kinds), 'av': av,
                 'tune': A.compare(base, s, *G.TUNE), 'hold': A.compare(base, s, G.HOLD_FROM, 2100),
                 'holdBig5': A.compare(base, s, G.HOLD_FROM, 2100, lambda lg, z: lg in D.BIG5),
                 'bySeason': {S: A.compare(base, s, S, S)['dLL'] for S in range(2016, 2028)}}
            res['tests'].append(t)
            print(json.dumps(t), flush=True)
    json.dump(res, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
