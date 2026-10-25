#!/usr/bin/env python3
"""Hockey mock drafts (Noah, Oct 24 2026): the 2027 NHL draft, two rounds, three ways, like the basketball mocks.

    python3 scripts/hockey_mock.py      -> data/hockey_mock.json (after scripts/nhl_games.py and hockey_prospects.py)

Order       Projected standings from the NHL page's 10,000 simulated seasons (data/nhl_games.json: expected points),
            worst first, in both rounds; no lottery shuffle in the mock itself. Each lottery team's chance at the first
            pick is shown: its simulated finishing spot (1-16 among non-playoff teams) times the NHL's draw odds for
            that spot, where a team more than ten spots back that wins the draw moves up ten and the first pick goes to
            the last-place team. Traded picks follow Tankathon's draft order (owner of each team's pick); conditions on
            protected picks are not modelled.
Predictive  Where they go: the best player left on the consensus board (Tankathon's rank) at every pick.
Conviction  Our board: the best FV left (the mean NHL outcome, data/hockey.json), consensus rank breaking ties.
Blended     The geometric mean of a player's consensus rank and FV rank.
"""
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import nhl_data as D

OUT = os.path.join(ROOT, 'data', 'hockey_mock.json')
ORDER_URL = 'https://tankathon.com/nhl/draft-order'
ROUNDS = 2
# chance at the first pick by pre-lottery spot, 1-16 (NHL draft lottery odds)
ODDS1 = [.185, .135, .115, .095, .085, .075, .065, .06, .05, .035, .03, .025, .02, .015, .005, .005]


def owners():
    """{(round, original team): owner} from Tankathon's draft order"""
    try:
        html = urllib.request.urlopen(urllib.request.Request(ORDER_URL, headers={'User-Agent': D.UA}), timeout=60).read().decode('utf8', 'replace')
    except Exception as e:
        print('draft order:', e, file=sys.stderr)
        return {}
    out = {}
    for tr in re.findall(r'<tr>(.*?)</tr>', html, re.S):
        n = re.search(r'pick-number">(\d+)', tr)
        logos = re.findall(r'/nhl/([a-z]+)\.svg', tr)
        if not n or not logos:
            continue
        rd = 1 + (int(n.group(1)) - 1) // 32
        if rd > ROUNDS:
            continue
        own, orig = D.team(logos[0]), D.team(logos[-1])
        out[(rd, orig)] = own
    return out


def p_first(lot):
    """chance at the first pick from the distribution of pre-lottery spots (keys '1'..'16')"""
    p = 0.0
    for k, v in lot.items():
        s = int(k)
        if s <= 11:
            p += v * ODDS1[s - 1]
    if lot.get('1'):              # wins by teams 12th-16th fall to the last-place team
        p += lot['1'] * sum(ODDS1[11:])
    return p


def run_mock(order, board, key):
    left = list(board)
    picks = []
    for o in order:
        if not left:
            break
        best = min(left, key=key)
        left.remove(best)
        picks.append(dict(o, name=best['name'], pos=best['pos'], club=best['club'], league=best['league'], fv=best['fv'],
                          rk=best['rk'], frk=best['frk'], age=best['age']))
    return picks


def main():
    G = json.load(open(os.path.join(ROOT, 'data', 'nhl_games.json')))
    H = json.load(open(os.path.join(ROOT, 'data', 'hockey.json')))
    own = owners()
    power = sorted(G['power'], key=lambda r: (r['xpts'], r['rating']))
    lottery = []
    for i, r in enumerate(power, 1):
        p1 = p_first(r.get('lottery') or {})
        if i <= 16 or p1 >= 0.005:
            lottery.append({'t': r['t'], 'xpts': r['xpts'], 'playoff': r['playoff'], 'spot': i, 'p1': round(p1, 3),
                            'lot': round(sum((r.get('lottery') or {}).values()), 3)})
    order = []
    for rd in range(1, ROUNDS + 1):
        for i, r in enumerate(power, 1):
            t = r['t']
            order.append({'pick': (rd - 1) * 32 + i, 'round': rd, 'team': own.get((rd, t), t), 'orig': t})
    board = [dict(b) for b in H['board']]
    # provisional rows (not on Tankathon's board) rank after it on the consensus side, in FV order
    nb = sum(1 for b in board if not b.get('prov'))
    for i, b in enumerate(sorted((b for b in board if b.get('prov')), key=lambda b: -b['fvx']), 1):
        b['rk'] = nb + i
    for i, b in enumerate(sorted(board, key=lambda b: (-b['fvx'], b['rk'])), 1):
        b['frk'] = i
    pred = run_mock(order, board, lambda b: (b['rk'], -b['fvx']))
    conv = run_mock(order, board, lambda b: (-b['fvx'], b['rk']))
    blend = run_mock(order, board, lambda b: (math.sqrt(b['rk'] * b['frk']), b['rk']))
    out = {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'year': H.get('year'), 'season': G['season'],
           'traded': sum(1 for o in order if o['team'] != o['orig']), 'lottery': lottery, 'pred': pred, 'blend': blend, 'conv': conv}
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(pred), 'picks', out['traded'], 'traded')


if __name__ == '__main__':
    main()
