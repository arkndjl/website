# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
#!/usr/bin/env python3
"""FV sweep Nov 9 2026 (soccer): feeder profiles for the rebuild. Ids = players with a lineup age <= 23 in the pulled
Transfermarkt games who are not in the dump with a birth date and a height (the Oct 27 recipe). Checkpointed.

    python3 scripts/research/fv_nov09/soccer_profiles.py
"""
import concurrent.futures as cf
import gzip
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import soccer_prospect_data as SD   # noqa: E402
import soccer_prospects as SP       # noqa: E402

FN = os.path.join(SD.CACHE, 'players.json.gz')


def main():
    _, A = SP.tm_games(SD.FEED + SP.NEWC + SP.DUMPL + SD.EURO, range(SP.FIRST, SP.LAST + 1))
    young = set(A[A.age.notna() & (A.age <= 23)].player_id.unique())
    p = SP.rd('players', usecols=['player_id', 'date_of_birth', 'height_in_cm'])
    ok = set(p[p.date_of_birth.notna() & p.height_in_cm.notna() & (p.height_in_cm > 0)].player_id)
    have = json.load(gzip.open(FN, 'rt')) if os.path.exists(FN) else {}
    todo = [str(i) for i in sorted(young - ok) if str(i) not in have]
    print('young', len(young), 'todo', len(todo), 'have', len(have), flush=True)
    keep = ('name', 'lifeDates', 'attributes')

    def save():
        tmp = FN + '.tmp'
        with gzip.open(tmp, 'wt') as f:
            json.dump(have, f)
        os.replace(tmp, FN)
    miss = 0
    with cf.ThreadPoolExecutor(24) as ex:
        for n, (i, r) in enumerate(zip(todo, ex.map(lambda i: SD.get(f'/player/{i}'), todo))):
            if r and r.get('data'):
                have[i] = {k: r['data'].get(k) for k in keep}
            else:
                miss += 1
            if n % 5000 == 4999:
                save()
                print(n + 1, 'missing', miss, flush=True)
    save()
    print('profiles', len(have), 'missing', miss)


if __name__ == '__main__':
    main()
