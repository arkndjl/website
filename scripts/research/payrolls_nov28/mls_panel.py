#!/usr/bin/env python3
"""MLS payroll panel (PANEL.md): ASA goals added above replacement + MLSPA guaranteed compensation by team-season.

python3 scripts/research/payrolls_nov28/mls_panel.py   (raw API responses cached in scripts/.cache/payrolls/mls/)
"""
import gzip, json, os, statistics, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'payrolls', 'mls')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'panel_mls.json.gz')
ASA = 'https://app.americansocceranalysis.com/api/v1/mls'
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
RS = 'Regular Season'
SEASONS = list(range(2013, 2027))
# MLS salary budget per club ($M), as announced by the league each year.
CAP = {2013: 2.95, 2014: 3.1, 2015: 3.49, 2016: 3.66, 2017: 3.845, 2018: 4.035, 2019: 4.24, 2020: 4.9, 2021: 4.9,
       2022: 4.88, 2023: 5.21, 2024: 5.47, 2025: 5.95, 2026: 6.425}
NEAR = 1.25          # "freely available" = guaranteed comp <= 1.25 x senior minimum
MINMIN = 500         # minutes for a replacement-pool player
POOL = {'CB': 'D', 'FB': 'D', 'DM': 'M', 'CM': 'M', 'AM': 'M', 'W': 'F', 'ST': 'F', 'GK': 'G'}
_last = [0.0]


def get(path, **q):
    q = {k: v for k, v in q.items() if v is not None}
    key = path.replace('/', '_') + ('_' + '_'.join(f'{k}-{v}' for k, v in sorted(q.items())) if q else '')
    fn = os.path.join(CACHE, key.replace(' ', '') + '.json')
    if os.path.exists(fn):
        with open(fn) as f:
            return json.load(f)
    url = f'{ASA}/{path}' + ('?' + urllib.parse.urlencode(q) if q else '')
    for i in range(4):
        time.sleep(max(0, 1.2 - (time.time() - _last[0])))
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=90) as r:
                d = json.load(r)
            break
        except Exception as e:  # noqa: BLE001
            print('retry', url, e, file=sys.stderr)
            time.sleep(5 * (i + 1))
    else:
        raise SystemExit(f'failed {url}')
    os.makedirs(CACHE, exist_ok=True)
    with open(fn, 'w') as f:
        json.dump(d, f)
    return d


def tid(v):
    return v if isinstance(v, str) else (v[-1] if v else None)


def main():
    teams = {t['team_id']: t['team_abbreviation'] for t in get('teams')}
    names = {p['player_id']: p.get('player_name') for p in get('players')}
    seasons, rows, rep = {}, [], []
    for s in SEASONS:
        txg = get('teams/xgoals', season_name=s, stage_name=RS)
        if not txg:
            continue
        if s == SEASONS[-1] and len(set(t['count_games'] for t in txg)) != 1:
            print(f'{s}: regular season not complete, skipped')
            continue
        ga = get('players/goals-added', season_name=s, minimum_minutes=0, split_by_teams='true', stage_name=RS)
        gk = get('goalkeepers/goals-added', season_name=s, minimum_minutes=0, split_by_teams='true', stage_name=RS)
        sal = get('players/salaries', season_name=s) or []
        # pay: last MLSPA release in the season for each (player, team)
        pay = {}
        for r in sorted(sal, key=lambda r: r.get('mlspa_release') or ''):
            if r.get('guaranteed_compensation') is not None and r.get('team_id'):
                pay[(r['player_id'], tid(r['team_id']))] = r
        base = [r['base_salary'] for r in pay.values() if r.get('base_salary')]
        # senior minimum: the modal base salary among the lowest third that is above the reserve minimum.
        # The two most common low values are the reserve and senior minimums; take the larger.
        low = sorted(base)[:len(base) // 3]
        top2 = [v for v, _ in Counter(low).most_common(2)]
        mn = max(top2) / 1e6 if top2 else None
        p5 = sorted(base)[len(base) // 20] / 1e6
        # value rows
        val = {}
        for x in ga:
            val[(x['player_id'], tid(x['team_id']))] = (x['general_position'], x['minutes_played'] or 0,
                                                       sum(d['goals_added_above_avg'] or 0 for d in x['data']))
        for x in gk:
            val[(x['player_id'], tid(x['team_id']))] = ('GK', x['minutes_played'] or 0,
                                                       sum(d['goals_added_above_avg'] or 0 for d in x['data']))
        # replacement rate: minutes-weighted mean g+/96 of 500+ minute players paid <= NEAR x senior minimum, by position
        # group (D: CB FB, M: DM CM AM, F: W ST, G: GK). Keepers pooled over all seasons (few minimum-paid starters).
        grp = defaultdict(lambda: [0.0, 0.0, 0])
        for k, (pos, m, g) in val.items():
            p = pay.get(k)
            if m >= MINMIN and p and p['guaranteed_compensation'] <= NEAR * mn * 1e6:
                a = grp[POOL[pos]]
                a[0] += g; a[1] += m; a[2] += 1
        rep.append((s, val, pay, grp, mn, p5, txg))
    gkp = [sum(r[3]['G'][i] for r in rep) for i in range(3)]
    for s, val, pay, grp, mn, p5, txg in rep:
        rr = {g: (a[0] / a[1] * 96, a[2]) for g, a in grp.items() if g != 'G'}
        rr['G'] = (gkp[0] / gkp[1] * 96, gkp[2])
        seasons[str(s)] = {'cap': CAP.get(s), 'min': round(mn, 4), 'min_p5': round(p5, 4), 'gp': txg[0]['count_games'],
                           'repl96': {g: round(v[0], 4) for g, v in sorted(rr.items())},
                           'repl_n': {g: v[1] for g, v in sorted(rr.items())}}
        byt = defaultdict(dict)
        for k in set(val) | set(pay):
            pid, t = k
            if t not in teams:
                continue
            v = None
            if k in val:
                pos, m, g = val[k]
                v = round(g - rr[POOL[pos]][0] * m / 96, 3)
            p = pay.get(k)
            byt[t][pid] = {'id': pid, 'n': names.get(pid) or (p or {}).get('player_name') or pid,
                           'pay': round(p['guaranteed_compensation'] / 1e6, 4) if p else None, 'v': v}
        for t in txg:
            rows.append({'s': s, 'tm': teams[t['team_id']], 'w': t['points'], 'gp': t['count_games'], 'pts': t['points'],
                         'pl': sorted(byt[t['team_id']].values(), key=lambda r: -(r['pay'] or 0))})
    out = {'lg': 'mls', 'unit': 'goals added', 'src': (
        "American Soccer Analysis API, regular season only (stage_name=Regular Season), split_by_teams=true so a player moved "
        "mid-season has one row per club. v = ASA goals added above average (sum of goals_added_above_avg over action types; "
        "keepers from goalkeepers/goals-added) minus a replacement rate x minutes/96. Replacement rate = minutes-weighted mean "
        "g+/96 of players with 500+ regular-season minutes paid at most 1.25 x the senior minimum (guaranteed comp), per season "
        "and position group (D = CB FB, M = DM CM AM, F = W ST); keepers' rate pooled over all seasons. Pay = guaranteed "
        "compensation from the last MLSPA release of the season for that player and club (ASA players/salaries), $M; "
        "guaranteed comp includes signing and marketing bonuses annualised, and DP pay is far above the cap charge. "
        "min = senior minimum read from the data: the larger of the two modal base salaries in the lowest third of the season's "
        "salaries (reserve and senior minimums); min_p5 = 5th percentile of base salary. cap = announced salary budget. "
        "w = pts = league points, gp = matches. No buyout or dead-money rows (not in the source)."),
        'seasons': seasons, 'rows': rows}
    with gzip.open(OUT, 'wt') as f:
        json.dump(out, f, separators=(',', ':'))
    # join report
    print('season  teams  min    p5     repl D/M/F/G (n)                 pay$joined  v_joined(|v| of rows w/ minutes)  r(v,pts)')
    for s in sorted({r['s'] for r in rows}):
        R = [r for r in rows if r['s'] == s]
        P = [p for r in R for p in r['pl']]
        pt = sum(p['pay'] or 0 for p in P)
        pj = sum(p['pay'] for p in P if p['pay'] and p['v'] is not None)
        vt = sum(abs(p['v']) for p in P if p['v'] is not None)
        vj = sum(abs(p['v']) for p in P if p['v'] is not None and p['pay'] is not None)
        nv = sum(p['v'] is not None for p in P)
        nvj = sum(p['v'] is not None and p['pay'] is not None for p in P)
        V = [sum(p['v'] or 0 for p in r['pl']) for r in R]
        W = [r['w'] for r in R]
        c = statistics.correlation(V, W)
        S = seasons[str(s)]
        rp = ' '.join(f"{S['repl96'][g]:+.3f}({S['repl_n'][g]})" for g in 'DMFG')
        print(f"{s}  {len(R):5d}  {S['min']:.4f} {S['min_p5']:.4f} {rp}  {pj / pt:6.1%}   "
              f"{vj / vt:6.1%} |v|, {nvj / nv:6.1%} rows   {c:.2f}")
    allv = [sum(p['v'] or 0 for p in r['pl']) for r in rows]
    print('pooled r(team v, points) =', round(statistics.correlation(allv, [r['w'] for r in rows]), 3),
          '| team-seasons', len(rows))


if __name__ == '__main__':
    main()
