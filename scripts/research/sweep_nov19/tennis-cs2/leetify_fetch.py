#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Leetify public match endpoint for ESEA league maps (research pull, newest first, 1 request a second).

    python3 leetify_fetch.py <ids.txt> <out.jsonl>     # one FACEIT match id a line; resumes; a miss is stored too
"""
import json, os, subprocess, sys, time
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
URL = 'https://api-public.cs-prod.leetify.com/v2/matches/faceit/'
KEEP = ('steam64_id', 'name', 'initial_team_number', 'total_kills', 'total_deaths', 'total_assists', 'total_damage',
        'leetify_rating', 'ct_leetify_rating', 't_leetify_rating', 'rounds_count', 'rounds_won', 'rounds_survived',
        'trade_kill_opportunities', 'trade_kill_attempts', 'trade_kills_succeed', 'traded_death_opportunities',
        'traded_deaths_succeed', 'flashbang_hit_foe', 'flashbang_leading_to_kill', 'flash_assist', 'flashbang_thrown',
        'he_foes_damage_avg', 'utility_on_death_avg', 'accuracy_enemy_spotted', 'reaction_time',
        'counter_strafing_shots_good_ratio', 'multi1k', 'multi2k', 'multi3k', 'multi4k', 'multi5k', 'total_hs_kills')
ids = open(sys.argv[1]).read().split()
out = sys.argv[2]
have = set()
if os.path.exists(out):
    for line in open(out): have.add(json.loads(line)['id'])
stop = os.path.join(os.path.dirname(out), 'stop_leetify')
n = 0
with open(out, 'a') as f:
    for i in ids:
        if i in have: continue
        if os.path.exists(stop): break
        t = time.time()
        try:
            r = subprocess.run(['curl', '-sS', '--compressed', '-m', '30', '-A', UA, '-w', '\n%{http_code}', URL + i],
                               capture_output=True, text=True, timeout=40)
            body, code = r.stdout.rsplit('\n', 1)
        except Exception:
            time.sleep(5); continue
        row = {'id': i, 'code': int(code or 0)}
        if code == '200':
            try:
                d = json.loads(body)
                row.update(map=d.get('map_name'), fin=d.get('finished_at'), ts=d.get('team_scores'),
                           st=[{k: p.get(k) for k in KEEP} for p in d.get('stats', [])])
            except ValueError:
                row['code'] = -1
        elif code == '429':
            time.sleep(60); continue
        f.write(json.dumps(row) + '\n'); f.flush()
        n += 1
        if n % 200 == 0: print(time.strftime('%H:%M:%S'), n, flush=True)
        time.sleep(max(0, 1.05 - (time.time() - t)))
