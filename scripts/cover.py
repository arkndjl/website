"""The chance a game's model side covers the line, or its total goes over, as the games tables show it.

The tables used to price a gap of e points as Phi(e / sd): the model margin as the truth, sd the result's spread around
the model. Against the market that overstates a lot. Each sport's walk-forward rows say how much of a gap to the
closing line the result actually keeps: NBA about none in 2024-26, so a 4-point gap showed 64% cover against a real
48% ATS (Oct 21 2026 model audit). Here the result's margin over the line is regressed on the model's gap, last
SEASONS seasons of walk-forward rows: cover = Phi(b * e / s), b the slope (held in [0, 1]), s the residual sd.

    python3 scripts/cover.py --fit     # rewrite data/cover_fit.json from scripts/data/games_wf
"""
import gzip
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.join(HERE, 'data', 'games_wf')
FIT = os.path.join(HERE, '..', 'data', 'cover_fit.json')
SEASONS = 3
SPORTS = ('nba', 'nfl', 'cbb', 'cfb')
_F = {}


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _slope(pairs):
    n = len(pairs)
    if n < 50:
        return None
    mx = sum(e for e, _ in pairs) / n
    my = sum(y for _, y in pairs) / n
    sxx = sum((e - mx) ** 2 for e, _ in pairs)
    b = sum((e - mx) * (y - my) for e, y in pairs) / sxx if sxx > 0 else 0.0
    b = min(1.0, max(0.0, b))
    s = math.sqrt(sum((y - my - b * (e - mx)) ** 2 for e, y in pairs) / (n - 2))
    return {'b': round(b, 4), 'sd': round(s, 3), 'n': n}


def fit():
    out = {'note': 'cover = Phi(b * gap / sd): the result over the closing line regressed on the model gap to it, '
                   f'last {SEASONS} seasons of walk-forward rows (scripts/cover.py)', 'sports': {}}
    for sp in SPORTS:
        fn = os.path.join(WF, sp + '.json.gz')
        if not os.path.exists(fn):
            continue
        rows = [r for r in json.load(gzip.open(fn)) if r.get('res') is not None]
        S = sorted({r['S'] for r in rows})[-SEASONS:]
        rows = [r for r in rows if r['S'] in S]
        sp_ = _slope([(r['m'] - r['L'], r['res'] - r['L']) for r in rows if r.get('m') is not None and r.get('L') is not None])
        to_ = _slope([(r['tm'] - r['T'], r['tot'] - r['T']) for r in rows if r.get('tm') is not None and r.get('T') and r.get('tot') is not None])
        out['sports'][sp] = {'seasons': S, 'spread': sp_, 'total': to_}
        print(sp, S, 'spread', sp_, 'total', to_)
    with open(FIT, 'w') as f:
        json.dump(out, f, indent=1)
    _F.clear()


def params(sport, mk):
    if not _F:
        try:
            _F.update(json.load(open(FIT))['sports'])
        except (OSError, ValueError, KeyError):
            pass
    return (_F.get(sport) or {}).get(mk)


def chance(sport, mk, gap):
    """the chance the side the model leans to wins against the line (mk 'spread': covers; 'total': gap is model minus
    total, the chance of the over); None with no fit"""
    p = params(sport, mk)
    if not p or not p.get('sd'):
        return None
    z = p['b'] * gap / p['sd']
    return phi(abs(z)) if mk == 'spread' else phi(z)


if __name__ == '__main__':
    if sys.argv[1:2] == ['--fit']:
        fit()
    else:
        print(__doc__)
