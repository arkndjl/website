# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NBA payroll panel (see PANEL.md): salary = Basketball-Reference team salary tables (scripts/data/nba_salary_hist.json,
largest figure when he was on several), value = VORX (static/data/nba-xpm/<end year>.json), wins = regular-season games in
scripts/nba_games_hist.json.gz. A traded player (team 'OKC/CHO') goes to the team he finished with, pay and value both."""
import gzip, json, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from xaav import NBA_CAP  # noqa: E402

ESPN = {'BKN': 'BRK', 'CHA': 'CHO', 'GS': 'GSW', 'NO': 'NOP', 'NY': 'NYK', 'PHX': 'PHO', 'SA': 'SAS', 'UTAH': 'UTA', 'WSH': 'WAS'}
# NBA minimum salary (rookie minimum), $M, by end year
NBA_MIN = {2013: .49, 2014: .49, 2015: .51, 2016: .53, 2017: .54, 2018: .82, 2019: .84, 2020: .90, 2021: .90, 2022: .93,
           2023: .95, 2024: 1.12, 2025: 1.16, 2026: 1.27}


def main():
    sal = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'nba_salary_hist.json')))
    g = json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nba_games_hist.json.gz')))['games']
    W, GP = defaultdict(int), defaultdict(int)
    for x in g:
        if x['t'] != 2 or not x.get('fin'):
            continue
        h, a = ESPN.get(x['h'], x['h']), ESPN.get(x['a'], x['a'])
        GP[(x['S'], h)] += 1; GP[(x['S'], a)] += 1
        W[(x['S'], h if x['hs'] > x['as'] else a)] += 1
    rows, seasons = [], {}
    for s in range(2013, 2027):
        d = json.load(open(os.path.join(ROOT, 'static', 'data', 'nba-xpm', f'{s}.json')))
        S = sal.get(str(s), {})
        T = defaultdict(list)
        seen = set()
        for p in d['players']:
            tm = p['tm'].split('/')[-1]
            pay = S.get(p['id'])
            T[tm].append({'id': p['id'], 'n': p['n'], 'pay': round(pay / 1e6, 3) if pay else None, 'v': p.get('vorx')})
            seen.add(p['id'])
        # salaried players with no value row (did not play): team unknown in this file, so they are left out (reported)
        miss = sum(v for k, v in S.items() if k not in seen) / 1e6
        tot = sum(S.values()) / 1e6
        seasons[str(s)] = {'cap': NBA_CAP[s], 'min': NBA_MIN[s], 'gp': 82, 'payNoValueShare': round(miss / tot, 3)}
        for tm, pl in T.items():
            rows.append({'s': s, 'tm': tm, 'w': W[(s, tm)], 'gp': GP[(s, tm)], 'pts': None, 'pl': pl})
        paid = [q for pl in T.values() for q in pl if q['pay']]
        vv = sum(q['v'] or 0 for pl in T.values() for q in pl if (q['v'] or 0) > 0)
        vj = sum(q['v'] or 0 for pl in T.values() for q in pl if (q['v'] or 0) > 0 and q['pay'])
        print(s, len(T), 'teams', f'pay $ with no value row {miss / tot:.1%}', f'VORX+ with pay {vj / vv:.1%}', len(paid))
    out = {'lg': 'nba', 'unit': 'wins', 'src': __doc__.strip(), 'seasons': seasons, 'rows': rows}
    with gzip.open(os.path.join(HERE, 'panel_nba.json.gz'), 'wt') as f:
        json.dump(out, f, separators=(',', ':'))


if __name__ == '__main__':
    main()
