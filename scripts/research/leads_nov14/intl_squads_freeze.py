# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The pulled Transfermarkt matchday squads (intl_squads_pull.py's cache) -> scripts/data/soccer_intl_squads.json.gz,
the file scripts/soccer_intl.py reads and keeps current.

    python3 scripts/research/leads_nov14/intl_squads_freeze.py
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
import soccer_intl as I
import s1_intl as S


def main():
    rows, _, _ = I.load()
    clubs, games = S.tm_data()
    mp = S.name_map(clubs, games, rows)
    C = {'tm': mp, 'sq': {}}
    n = 0
    for p in glob.glob(os.path.join(S.TMC, 'g', '*.json')):
        g = json.load(open(p))
        if not g or not g.get('d') or g['h'].get('id') not in mp or g['a'].get('id') not in mp:
            continue
        for s, o in (('h', 'a'), ('a', 'h')):
            pl = [x for x in (g[s].get('xi') or []) + (g[s].get('sub') or []) if x[0]]
            sq = [v for x in pl for v in (int(x[0]), int(round((x[1] or 0) / 1000)))] if len(pl) >= 11 else []
            C['sq'].setdefault(mp[g[s]['id']], []).append([g['d'], str(g['id']), mp[g[o]['id']], sq])
        n += 1
    I.save_callups(C)
    print(n, 'matches,', len(C['sq']), 'nations,', os.path.getsize(I.CUF), 'bytes')


if __name__ == '__main__':
    main()
