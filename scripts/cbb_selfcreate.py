#!/usr/bin/env python3
"""Self-created scoring from ESPN play-by-play (hoopR parquet, 2014-25 seasons), per college player-season.

    python3 scripts/cbb_selfcreate.py      # -> scripts/.cache/cbb/selfcreate.json  {"pid|year": counts}

Made field goals by zone (rim = layups, dunks, tips; mid = other twos; three), split assisted / unassisted, with
putbacks (a make right after the same player's offensive rebound) counted apart from unassisted. Players join to
Barttorvik careers through scripts/names.py inside the team-season (ESPN team id -> Barttorvik name from the games
history).
"""
import json, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import names as N

PBP = os.path.join(HERE, '.cache', 'cbb', 'pbp')
OUT = os.path.join(HERE, '.cache', 'cbb', 'selfcreate.json')
RIM = {'LayUpShot', 'DunkShot', 'TipShot'}
KEYS = ('rim_a', 'rim_u', 'rim_p', 'mid_a', 'mid_u', 'mid_p', 'tp_a', 'tp_u', 'fga')


def season(y, btname):
    import pyarrow.parquet as pq
    t = pq.read_table(os.path.join(PBP, f'{y}.parquet'), columns=['game_id', 'game_play_number', 'sequence_number', 'type_text', 'text', 'team_id',
                                                                   'athlete_id_1', 'athlete_id_2', 'athlete_name_1', 'shooting_play', 'scoring_play'])
    d = t.to_pydict()
    n = len(d['game_id'])
    order = sorted(range(n), key=lambda i: (d['game_id'][i], d['game_play_number'][i] if d['game_play_number'][i] is not None else 0))
    cnt = defaultdict(lambda: defaultdict(float))
    nm = {}
    prev = (None, None, None)          # game, type, athlete
    for i in order:
        g, tt, a1 = d['game_id'][i], d['type_text'][i], d['athlete_id_1'][i]
        tm = d['team_id'][i]
        if d['shooting_play'][i] and a1 is not None and tm is not None and tt not in ('MadeFreeThrow',) and 'Free Throw' not in (d['text'][i] or ''):
            b = btname.get(str(int(tm)))
            if b:
                k = (b, int(a1))
                nm[k] = d['athlete_name_1'][i]
                c = cnt[k]
                c['fga'] += 1
                if d['scoring_play'][i]:
                    z = 'rim' if tt in RIM else ('tp' if tt.startswith('Three') else 'mid')
                    put = prev[0] == g and prev[1] == 'Offensive Rebound' and prev[2] == a1
                    if 'Assisted' in (d['text'][i] or ''):
                        c[z + '_a'] += 1
                    elif put and z != 'tp':
                        c[z + '_p'] += 1
                    else:
                        c[z + '_u'] += 1
        prev = (g, tt, a1)
    return cnt, nm


def main():
    import gzip
    import cbb_games as C
    btname = C.bt_map(C.load_hist())
    careers = json.load(open(os.path.join(HERE, '.cache', 'cbb', 'careers.json')))
    pool = defaultdict(list)
    for c in careers:
        for s in c['seasons']:
            pool[(s['team'], s['year'])].append({'pid': c['pid'], 'name': c['name']})
    out, stats = {}, {}
    for y in range(2014, 2026):
        if not os.path.exists(os.path.join(PBP, f'{y}.parquet')):
            continue
        cnt, nm = season(y, btname)
        M = {}
        hit = miss = 0
        for (b, a), c in cnt.items():
            if c['fga'] < 20:
                continue
            if (b, y) not in M:
                M[(b, y)] = N.Matcher(pool.get((b, y), []), team=None, pos=None)
            r = M[(b, y)].find(nm[(b, a)])
            r = r[0] if isinstance(r, tuple) else r
            if not r:
                miss += 1
                continue
            hit += 1
            k = f"{r['pid']}|{y}"
            o = out.setdefault(k, {x: 0.0 for x in KEYS})
            for x in KEYS:
                o[x] += c.get(x, 0.0)
        stats[y] = {'matched': hit, 'missed': miss}
        print(y, stats[y], flush=True)
    json.dump({'stats': stats, 'rows': out}, open(OUT, 'w'))


if __name__ == '__main__':
    main()
