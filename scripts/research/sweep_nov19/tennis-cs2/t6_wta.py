#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""T6: WTA official API (api.wtatennis.com) parity against the history and a count of top-400 players whose last
match date it moves. Tournament weeks that start after Nov 2 2026 are not read (lockbox)."""
import subprocess, time, datetime as dt
from tcommon import *
API = 'https://api.wtatennis.com/tennis/'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
WC = '/home/user/scratch-tennis-cs2/wta'
os.makedirs(WC, exist_ok=True)
_t = [0.0]


def get(path, name):
    p = os.path.join(WC, name + '.json')
    if os.path.exists(p): return json.load(open(p))
    w = 1.05 - (time.time() - _t[0])
    if w > 0: time.sleep(w)
    _t[0] = time.time()
    r = subprocess.run(['curl', '-sS', '--compressed', '-m', '40', '-A', UA, API + path], capture_output=True, text=True, timeout=60)
    try: d = json.loads(r.stdout)
    except ValueError: return None
    json.dump(d, open(p, 'w'))
    return d


rows, players, tn = load_rows()
R = Resolver(players, [r for r in rows if r[1] == 'wta'], 20230101)
out = {}
# parity: tour-level main-draw singles of 2026 events that started before May 25
T = get('tournaments/?page=0&pageSize=100&excludeLevels=ITF&from=2026-01-01&to=2026-05-24', 'tourn_2026a')['content']
T = [t for t in T if t['level'] in ('Grand Slam', 'WTA 1000', 'WTA 500', 'WTA 250') and t['startDate'] < '2026-05-25' and 'UNITED CUP' not in t['tournamentGroup']['name']]
api = []
for t in T:
    d = get(f"tournaments/{t['tournamentGroup']['id']}/2026/matches", f"m_{t['tournamentGroup']['id']}_2026")
    for m in (d or {}).get('matches', []):
        if m['DrawLevelType'] != 'M' or m['DrawMatchType'] != 'S' or m['MatchState'] != 'F' or m['Winner'] not in ('2', '3', '4', '5'): continue      # 2 / 3 A / B won, 4 / 5 by retirement; 6 / 7 walkovers
        a = R.pid(m['PlayerNameFirstA'] + ' ' + m['PlayerNameLastA'], 'wta'); b = R.pid(m['PlayerNameFirstB'] + ' ' + m['PlayerNameLastB'], 'wta')
        w, l = (a, b) if m['Winner'] in ('2', '4') else (b, a)
        api.append((t['startDate'], t['tournamentGroup']['name'], w, l))
d0, d1 = 20251225, 20260531
from tennis_data import is_qual
H = [r for r in rows if r[1] == 'wta' and d0 <= r[0] <= d1 and r[2] in ('G', 'M', 'A') and not is_qual(r[4]) and (r[9] or '').strip() not in ('W/O', '') and 'United Cup' not in (tn.get(r[6]) or '')]
hs = {}
for r in H: hs.setdefault((r[7], r[8]), []).append(r[0])
found = unres = wrongw = 0
used = set()
for sd, nm, w, l in api:
    if not w or not l: unres += 1; continue
    o = dord(int(sd.replace('-', '')))
    if any(abs(dord(x) - o) <= 10 for x in hs.get((w, l), [])): found += 1; used.add((w, l))
    elif any(abs(dord(x) - o) <= 10 for x in hs.get((l, w), [])): wrongw += 1
hin = sum(1 for r in H if (r[7], r[8]) in used)
out['parity'] = {'events': len(T), 'api_matches': len(api), 'found_same_winner': found, 'name_unresolved': unres, 'winner_differs': wrongw,
                 'share_api_found': round(found / max(1, len(api)), 4), 'history_rows': len(H), 'history_found_in_api': hin,
                 'share_history_found': round(hin / max(1, len(H)), 4)}
print(out['parity'], flush=True)
# coverage: last match date per top-400 player, tournament weeks starting on or before Nov 2 2026
rk = []
for pg in range(4):
    rk += get(f'players/ranked?page={pg}&pageSize=100&type=rankSingles&sort=asc&name=&metric=SINGLES&at=2026-11-02&nationality=', f'rank_20261102_{pg}') or []
last = {}
for r in rows:
    if r[1] == 'wta' and r[0] <= 20261102:
        last[r[7]] = max(last.get(r[7], 0), r[0]); last[r[8]] = max(last.get(r[8], 0), r[0])
moved = same = nores = 0; gaps = []; lv = {}
for x in rk:
    p = x['player']
    d = get(f"players/{p['id']}/matches/?page=0&pageSize=40&sort=desc", f"p_{p['id']}")
    ms = [m for m in (d or {}).get('matches', []) if m.get('s_d_flag') == 'S' and (m.get('StartDate') or '')[:10] <= '2026-11-02']
    if not ms: continue
    api_last = int(max(m['StartDate'][:10] for m in ms).replace('-', ''))
    pid = R.pid(p['fullName'], 'wta')
    if not pid: nores += 1; continue
    ours = last.get(pid, 0)
    if dord(api_last) - dord(ours) > 14:        # past any start-date convention gap (a Slam week is filed up to 14 days apart)
        moved += 1; gaps.append(dord(api_last) - dord(ours))
        top = max(ms, key=lambda m: m['StartDate']); lv[top['TournamentLevel']] = lv.get(top['TournamentLevel'], 0) + 1
    else: same += 1
out['coverage'] = {'players': len(rk), 'moved_later': moved, 'not_moved': same, 'name_unresolved': nores,
                   'median_days_gained': float(np.median(gaps)) if gaps else 0, 'level_of_newest': lv}
out['pass'] = bool(out['parity']['share_api_found'] >= .98 and out['parity']['share_history_found'] >= .98 and moved >= 20)
print(json.dumps(out, indent=1)); save('t6_results', out)
