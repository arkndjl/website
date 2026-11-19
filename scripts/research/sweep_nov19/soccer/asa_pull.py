# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""American Soccer Analysis public API pull (MLS): season files for players (goals added, xG), goalkeepers, games,
game xG, salaries, plus the player and team lists. One call a second.

    python3 scripts/research/sweep_nov19/soccer/asa_pull.py <out dir> [first season] [last season]
"""
import json
import os
import sys
import time
import urllib.request

API = 'https://app.americansocceranalysis.com/api/v1/mls'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
SEASON = {'ga': 'players/goals-added?split_by_teams=true&minimum_minutes=0', 'xg': 'players/xgoals?split_by_teams=true',
          'gkx': 'goalkeepers/xgoals?split_by_teams=true', 'gkga': 'goalkeepers/goals-added?split_by_teams=true',
          'games': 'games?', 'gxg': 'games/xgoals?', 'sal': 'players/salaries?'}


def get(path):
    req = urllib.request.Request(f'{API}/{path}', headers={'User-Agent': UA})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:
            err = e
            time.sleep(3 + 3 * i)
    print('fail', path, repr(err), flush=True)
    return None


def main():
    out = sys.argv[1]
    s0, s1 = int(sys.argv[2]) if len(sys.argv) > 2 else 2013, int(sys.argv[3]) if len(sys.argv) > 3 else 2025
    os.makedirs(out, exist_ok=True)
    jobs = [(f'{k}_{S}', f'{p}&season_name={S}'.replace('?&', '?')) for S in range(s0, s1 + 1) for k, p in SEASON.items()]
    jobs += [('players', 'players'), ('teams', 'teams')]
    for name, path in jobs:
        fn = os.path.join(out, name + '.json')
        if os.path.exists(fn):
            continue
        d = get(path)
        if d is not None:
            json.dump(d, open(fn, 'w'))
            print(name, len(d), flush=True)
        time.sleep(1.1)


if __name__ == '__main__':
    main()
