#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""AP All-Pro teams and Pro Bowl rosters from Wikipedia's raw pages -> {season: {'ap1': [...], 'ap2': [...], 'pb': [...]}}
of [gsis id, name, team, position], plus the same lists by name for the players that did not join.

    python3 honours_parse.py <dir of raw pages> <out json>

Pages: <S>_All-Pro_Team.txt and <S+1>_Pro_Bowl.txt / <S+1>_Pro_Bowl_Games.txt for season S."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
import names as NM      # noqa: E402
import nfl_games as N   # noqa: E402

LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]'*\s*,\s*\[\[(\d{4} )?([^\]|]+?)( season)?(?:\|[^\]]*)?\]\]([^\n]*?)(?=<br|\n|$)", re.I)
MASCOT = dict(N.BY_MASCOT, redskins='WAS', team='WAS', commanders='WAS')


def players(text):
    for m in LINK.finditer(text):
        name = (m.group(2) or m.group(1)).strip()
        name = re.sub(r'\s*\(.*?\)$', '', name)
        t = MASCOT.get(m.group(4).split()[-1].lower())
        yield name, t, m.group(6)


def main():
    src, dst = sys.argv[1], sys.argv[2]
    out, miss = {}, {}
    for s in range(2016, 2026):
        ros = [{'name': r['full_name'], 'team': N.team(r['team']), 'pos': r['position'], 'id': r['gsis_id']}
               for r in N.rows(N.get(f'roster_{s}.csv', f'{N.REL}/rosters/roster_{s}.csv')) if r.get('gsis_id')]
        M = NM.Matcher(ros)
        res = {'ap1': set(), 'ap2': set(), 'pb': set()}
        miss[s] = []

        def add(k, name, team):
            r, _ = M.find(name, team=team)
            if r:
                res[k].add((r['id'], r['name'], r['team'], r['pos']))
            else:
                miss[s].append([k, name, team])
        p = os.path.join(src, f'{s}_All-Pro_Team.txt')
        if os.path.exists(p):
            for name, t, tail in players(open(p, encoding='utf-8').read()):
                tags = re.findall(r'AP(?:-2t?)?', ' '.join(re.findall(r'\(([^)]*)\)', tail)))
                if 'AP' in tags:
                    add('ap1', name, t)
                elif tags:
                    add('ap2', name, t)
        for nm in (f'{s + 1}_Pro_Bowl.txt', f'{s + 1}_Pro_Bowl_Games.txt'):
            p = os.path.join(src, nm)
            if os.path.exists(p):
                text = open(p, encoding='utf-8').read()
                m = re.search(r'^==[^=\n]*[Rr]oster', text, re.M)
                a = m.start() if m else -1
                m = re.search(r'^==\s*Number of selections', text, re.M)
                b = m.start() if m else -1
                for name, t, _ in players(text[a:b if b > 0 else None] if a >= 0 else ''):
                    add('pb', name, t)
        out[str(s)] = {k: sorted(v) for k, v in res.items()}
        print(s, {k: len(v) for k, v in res.items()}, 'unmatched', len(miss[s]), miss[s][:4], flush=True)
    json.dump({'honours': out, 'unmatched': miss}, open(dst, 'w'))


if __name__ == '__main__':
    main()
