"""P(wins the starting job) for the college depth charts (team builders, CFB and CBB).

The model is fit and tested in scripts/research/start_odds_nov28/test.py (prereg.md there) and read from
data/start_odds_fit.json: a logistic regression on the next season's starters (CFB: the top N on PFN's impact rankings at
the spot; CBB: the top 5 in minute share) with the value as a z within the room plus the drivers that passed held out
(CFB: class, incumbent, transfer-in; CBB: last season's minute share, incumbent, class). score() returns P(start | on the
roster), scaled within each room so the expected starters, P(here) x P(start | here), add up to the room's N."""
import json, math, os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFB_ROOM = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'OG': 'OL', 'IOL': 'OL', 'G': 'OL', 'C': 'OL',
            'EDGE': 'DL', 'DE': 'DL', 'DL': 'DL', 'DT': 'DL', 'NT': 'DL', 'LB': 'LB', 'CB': 'DB', 'S': 'DB', 'DB': 'DB'}


def load():
    p = os.path.join(ROOT, 'data', 'start_odds_fit.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def _z(L, k):
    a = [o[k] for o in L]; m = sum(a) / len(a); s = math.sqrt(sum((x - m) ** 2 for x in a) / len(a)) or 1.0
    return [(x - m) / s for x in a]


def _row(o, coef, room_list):
    x = coef['const'] + coef.get('room:' + o['room'], 0.0) * (o['room'] != room_list[0])
    x += coef.get('zv', 0) * o['zv'] + coef.get('zsc', 0) * o['zsc'] + coef.get('lst', 0) * o['lst']
    c = o['c']; x += coef.get('So', 0) * (c == 2) + coef.get('Jr', 0) * (c == 3) + coef.get('Sr', 0) * (c >= 4)
    x += coef.get('inc', 0) * o['inc'] + coef.get('tr', 0) * o['tr'] + coef.get('sh', 0) * o['sh']
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


def score(F, sp, P):
    """P: [{room, team-room key 'g', p (P here), c, v, sc, lst, inc, tr, sh}] for one season -> sets o['ps'] (P start | here)"""
    f = F.get(sp)
    if not f: return
    coef, rooms, N = f['model']['coef'], f['rooms'], f['N']
    g = defaultdict(list)
    for o in P: g[o['g']].append(o)
    for L in g.values():
        L = [o for o in L if o['room'] in N]
        if not L: continue
        for o, a, b in zip(L, _z(L, 'v'), _z(L, 'sc')): o['zv'], o['zsc'] = a, b
        for o in L: o['ps'] = _row(o, coef, rooms)
        # the room's starters: expected count = N (seats by room for CFB, 5 for the team in CBB)
        n = N[L[0]['room']] if sp == 'cfb' else 5
        for _ in range(30):
            e = sum(o['p'] * o['ps'] for o in L)
            if e <= 0 or abs(e - n) < 1e-3: break
            k = n / e; ch = False
            for o in L:
                q = min(0.99, o['ps'] * k)
                if abs(q - o['ps']) > 1e-6: ch = True
                o['ps'] = q
            if not ch: break


def expect(F, sp, key, ps):
    """seasons 2 and 3: last season's terms are not known yet, so each is its mean among that season's starters and
    non-starters in the fit sample, mixed by P(start) the season before"""
    m = F[sp]['means'][key]; return ps * m[1] + (1 - ps) * m[0]
