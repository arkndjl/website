"""Last week's designation, carried into a week whose report isn't out yet (nfl_games.CARRY).

Monday and Tuesday, ESPN's injury report still lists last week's questionable, doubtful and out players. This measures
what those designations are worth on the next week's game status report, 2021-25 (nflverse injuries and weekly rosters):
each player listed Q, D or O for week w, on a team that plays week w+1, by what the week w+1 report says. Cleared (off
the report, or on it with no designation) plays; questionable again plays at the questionable rate (.75 after playing,
.5 after missing: .70 for a player who was questionable, most of whom played, and .5 for one who was doubtful or out);
doubtful .02; out 0. Players moved to a reserve list or cut are left out (the roster
already has them), as are those absent from the report and inactive for the game (healthy scratches, not injuries).

  python3 scripts/nfl_inj_carry.py
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nfl_games as G

P_NEXT = {'cleared': 1.0, 'Questionable': 0.70, 'Doubtful': 0.02, 'Out': 0.0}


def main(first=2021, last=2025):
    res = defaultdict(Counter)
    for y in range(first, last + 1):
        ros = {(int(r['week']), r['gsis_id']): r['status']
               for r in G.rows(G.get(f'roster_weekly_{y}.csv', f'{G.REL}/weekly_rosters/roster_weekly_{y}.csv'))}
        rep = defaultdict(dict)
        for r in G.rows(G.get(f'injuries_{y}.csv', f'{G.REL}/injuries/injuries_{y}.csv')):
            if r.get('game_type', 'REG') == 'REG':
                rep[(r['team'], int(r['week']))][r['gsis_id']] = r['report_status']
        for (t, w), ps in rep.items():
            nxt = rep.get((t, w + 1))
            if nxt is None:
                continue
            for g, st in ps.items():
                if st not in ('Questionable', 'Doubtful', 'Out'):
                    continue
                rs = ros.get((w + 1, g))
                if g in nxt:
                    o = nxt[g] if nxt[g] in P_NEXT else 'cleared'
                elif rs == 'ACT':
                    o = 'cleared'
                else:
                    continue
                res[st][o] += 1
    for st in ('Questionable', 'Doubtful', 'Out'):
        c = res[st]; n = sum(c.values())
        q = {**P_NEXT, 'Questionable': P_NEXT['Questionable'] if st == 'Questionable' else 0.5}
        p = sum(q[k] * v for k, v in c.items()) / n
        print(f'{st:12} n {n:5}  plays {p:.2f}  ' + '  '.join(f'{k} {v / n:.0%}' for k, v in c.most_common()))


if __name__ == '__main__':
    main()
