#!/usr/bin/env python3
"""Novig alt-line test (Noah, Oct 28 2026: "Any way we can tailor our picks specifically based on Novig to improve them?"
then "Yes" to building the ladder test). Research harness: nothing live reads it.

    python3 scripts/novig_ladder_test.py      # data/novig_ladder_test.json + a table

Novig lists every rung of a spread or total (-3.5 at -125, -2.5 at +105, ...), each its own two-sided market. A pick is
bet today on the main rung (nearest 50/50). The question: would the rung with the most expected Kelly growth, priced
by the same calibrated chance the stake uses (scripts/units.py at that rung's gap and ask), have grown the bankroll
faster? For every graded live pick (data/games_picks_<sport>.json log) with a ladder snapshot from before it was flagged
(scripts/data/odds_novig_ladder, novig.snap_ladder, from Oct 28 2026), it scores the main rung and the best rung by:
  close  log growth if the close is the truth (each rung's chance at the pick's closing line; low noise)
  real   log growth on the result
paired per pick, t by pick. Pre-registered gate to ship (rule_options picking the best rung): 300+ graded pairs in a
sport, close growth better with t >= 2, and real growth not worse by more than 2 SE. Off-centre rungs hold 6-15% against
~1% at the centre, so the gate can easily fail: then the main rung stays.
"""
import datetime
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv as C  # noqa: E402
import games_picks as GP  # noqa: E402
import novig  # noqa: E402
import units as DU  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'novig_ladder_test.json')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
GATE_N, GATE_T = 300, 2.0
STALE_H = 2.0                   # a ladder snapshot older than this before the flag is not the price the pick saw


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def ladders(sport):
    """{espn id: [(t, ladder)]} in time order"""
    out = {}
    for fn in sorted(glob.glob(os.path.join(novig.LADDER, f'{sport}-*.jsonl'))):
        for x in open(fn):
            if x.strip():
                r = json.loads(x)
                if r.get('id'):
                    out.setdefault(str(r['id']), []).append((r['t'], r['lad']))
    return out


def k_of(R, mk, seg):
    """the line move per point of edge the pick was priced on: its segment's, else its market's"""
    for z in R.get('segments') or []:
        if z['mk'] == mk and f"{z['fam']}: {z['val']}" == seg and z.get('k'):
            return z['k']
    return (R['markets'].get(mk) or {}).get('k')


def growth(f, B, c):
    w, _, l = c
    return w * math.log(1 + f * B) + l * math.log(1 - f)


def rung(sport, mk, side, M, x, ask, k, p):
    """(stake fraction, expected growth on the calibrated chance, decimal payout) at rung x and ask, or None"""
    sgn = 1 if side in ('home', 'over') else -1
    gap = sgn * (M - x)
    if gap <= 0 or not 0 < ask < 1:
        return None
    c = GP.calib(sport, mk, side, x, gap, k)
    if c is None:
        return None
    o = novig.american(ask)
    f = min(DU.BOOK_CAP, p['lam'] * DU.kelly_pct(p, c, o, gap)) / 100
    if f <= 0:
        return None
    w, _, _ = DU.priced(p, c, o, gap)
    B = 1 / ask - 1
    return f, growth(f, B, (w, c[1], 1 - c[1] - w)), B


def result(mk, side, x, score):
    a, h = score
    v = (h - a) if mk == 'spread' else (h + a)
    d = (v - x) if side in ('home', 'over') else (x - v)
    return 1 if d > 0 else 0 if d == 0 else -1


def run():
    RJ = json.load(open(GP.RULES))
    out = {'asof': datetime.date.today().isoformat(), 'gate': {'n': GATE_N, 't': GATE_T}, 'sports': {}}
    for sport in SPORTS:
        R = RJ['sports'].get(sport) or {}
        try:
            log = json.load(open(GP.OUT.format(sport))).get('log', [])
        except (OSError, ValueError):
            log = []
        L = ladders(sport)
        pairs = []
        for e in log:
            mk = e.get('mk')
            if mk not in ('spread', 'total') or e.get('res') is None or e.get('close') is None or not e.get('score'):
                continue
            snaps = [s for s in L.get(str(e['id']), []) if s[0] <= e['flagged'] and
                     (iso(e['flagged']) - iso(s[0])).total_seconds() <= STALE_H * 3600]
            k = k_of(R, mk, e.get('seg'))
            if not snaps or not k:
                continue
            lad = snaps[-1][1].get('L' if mk == 'spread' else 'T') or []
            side = e['side']
            M = e['line'] + (e['edge'] if side in ('home', 'over') else -e['edge'])
            p = DU.params(sport, mk)
            opts = []
            for x, a_h, a_a in lad:
                ask = a_h if side in ('home', 'over') else a_a
                r = rung(sport, mk, side, M, x, ask, k, p)
                if r:
                    opts.append((x, ask) + r)
            if not opts:
                continue
            main = min(opts, key=lambda o: abs(o[0] - e['line']))
            best = max(opts, key=lambda o: o[3])

            def score(o):
                x, ask, f, _, B = o
                c = C.chances(sport, mk, side, x, e['close'])
                r = result(mk, side, x, e['score'])
                return growth(f, B, c), math.log(1 + f * (B if r > 0 else -1 if r < 0 else 0))
            gm, rm = score(main)
            gb, rb = score(best)
            pairs.append({'id': e['id'], 'mk': mk, 'main': main[0], 'best': best[0], 'dClose': gb - gm, 'dReal': rb - rm})
        out['sports'][sport] = summarize(pairs)
        print(sport, out['sports'][sport]['verdict'], {k: v for k, v in out['sports'][sport].items() if k not in ('verdict', 'pairs')})
    json.dump(out, open(OUT, 'w'), indent=1)
    return out


def summarize(pairs):
    def mt(xs):
        n = len(xs)
        if n < 2:
            return None, None, None
        m = sum(xs) / n
        s = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
        return m, s / math.sqrt(n), (m / (s / math.sqrt(n)) if s else None)
    dc, sc, tc = mt([q['dClose'] for q in pairs])
    dr, sr, tr = mt([q['dReal'] for q in pairs])
    moved = sum(1 for q in pairs if q['best'] != q['main'])
    ok = (len(pairs) >= GATE_N and tc is not None and tc >= GATE_T and dc > 0 and (dr is None or dr >= -2 * (sr or 0)))
    verdict = ('pass: bet the best rung' if ok else
               f'waiting ({len(pairs)} of {GATE_N} graded picks with a ladder)' if len(pairs) < GATE_N else 'fail: main rung stays')
    r = lambda v, d=5: None if v is None else round(v, d)
    return {'n': len(pairs), 'moved': moved, 'dClose': r(dc), 'tClose': r(tc, 2), 'dReal': r(dr), 'seReal': r(sr),
            'verdict': verdict, 'pairs': pairs[-50:]}


if __name__ == '__main__':
    run()
