# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""One-time research pull: ESPN match summary team stats (shots, shots on target, possession, corners) for the
national-team history's ESPN events up to Jul 2026. One call a second, compact rows only.

    python3 scripts/research/sweep_nov19/soccer/intl_stats_pull.py <rows.pkl> <out.jsonl>
"""
import json
import os
import pickle
import sys
import time
import urllib.request

TIER_A = ('fifa.world', 'uefa.euro', 'conmebol.america', 'uefa.nations', 'uefa.euroq', 'fifa.worldq.uefa',
          'fifa.worldq.conmebol', 'concacaf.gold', 'caf.nations', 'afc.asian.cup', 'fifa.worldq.concacaf',
          'concacaf.nations.league')
KEEP = ('totalShots', 'shotsOnTarget', 'possessionPct', 'wonCorners', 'foulsCommitted', 'totalPasses', 'saves')


def one(lg, gid):
    u = f'https://site.api.espn.com/apis/site/v2/sports/soccer/{lg}/summary?event={gid}'
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'}), timeout=40))
    out = {}
    comp = ((d.get('header') or {}).get('competitions') or [{}])[0]
    ha = {str(c.get('id')): c.get('homeAway') for c in comp.get('competitors') or []}
    for t in (d.get('boxscore') or {}).get('teams') or []:
        tid = str((t.get('team') or {}).get('id'))
        st = {s['name']: s.get('displayValue') for s in t.get('statistics') or [] if s.get('name') in KEEP}
        out[ha.get(tid) or t.get('homeAway') or tid] = st
    return out


def main():
    rows = pickle.load(open(sys.argv[1], 'rb'))
    fn = sys.argv[2]
    done = set()
    if os.path.exists(fn):
        done = {json.loads(x)['id'] for x in open(fn)}
    ev = [r for r in rows if r.get('espn') and r['day'] >= '2010-01-01' and r['day'] <= '2026-07-31']
    ev.sort(key=lambda r: (r['lg'] not in TIER_A, r['day']))
    with open(fn, 'a') as fh:
        for r in ev:
            if str(r['espn']) in done:
                continue
            t0 = time.time()
            try:
                st = one(r['lg'], r['espn'])
            except Exception as e:
                st = {'err': repr(e)[:80]}
            fh.write(json.dumps({'id': str(r['espn']), 'lg': r['lg'], 'day': r['day'], 'h': r['h'], 'a': r['a'], 'st': st}) + '\n')
            fh.flush()
            time.sleep(max(0.0, 1.05 - (time.time() - t0)))


if __name__ == '__main__':
    main()
