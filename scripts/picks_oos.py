#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Out-of-sample test of every live pick against the market, and the stake multiplier each sport earns. Stdlib only.

    python3 scripts/picks_oos.py          # data/picks_oos.json (Predictions, record group)
    python3 scripts/picks_oos.py --test   # self-check

Every pick the Predictions page flagged (live and paper rows alike, passes included as rule_monitor.judged counts them)
was made before its game with the line it was flagged at, so the live log is the one clean out-of-sample record. For
each rule (sport x market; props one rule; tennis moneylines one rule):
  - close value: clvRet, the return the pick was worth at the closing price, mean with a 95% interval clustered by game
    day (rule_monitor.clustered), one-sided p on G - 1 df;
  - results: flat ROI (1u a pick) and staked ROI with the same intervals;
  - calibration: the chance the stake sized on (pDU) against the close's no-vig chance at the pick's price (q, from
    clvRet) and the result, Brier of each, and the win rate against pDU;
  - realization: clvRet regressed on the staked edge evDU through the origin (1 = picks worth what they were staked on);
  - Holm: one-sided close-value p of every rule with 8+ game days adjusted together, and of every book together
    (family-wise .05; a book is the unit that bets live or paper).

The stake multiplier (Kelly x realization). A Kelly stake on edge e is right only if the pick is worth e; a pick worth
r e wants r x the stake (log growth is concave in the stake, so overbetting by 2x on a zero edge loses what full Kelly
gains). r per sport is estimated walk-forward: on each game day, from the sport's picks judged on earlier days only,
a normal update of r around the prior PRIOR (mean, sd) with the day-clustered se of the through-origin slope, then
clipped to [0, 1]. The test scores each day's picks at the close (their expected log growth at the close-implied chance,
at the stake actually posted x the multiplier) against the posted stakes (x 1): the multiplier ships only if it grows
the book more at the close on days it never saw. Paper books are scored too (what the stake would have been).
"""
import datetime
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import rule_monitor as RM  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'picks_oos.json')
BOOKS = ('nba', 'cbb', 'cfb', 'nfl', 'nflprops', 'tennis')
NAMES = {'nba': 'NBA', 'cbb': 'CBB', 'cfb': 'CFB', 'nfl': 'NFL', 'nflprops': 'NFL props', 'tennis': 'Tennis'}
PRIOR = (0.5, 0.25)          # realization prior (Nov 11 2026 peer review): the staked edge is worth about half, sd .25
MIN_DAYS = 8                 # game days before a rule enters the Holm family
ALPHA = 0.05


def dec(o):
    o = float(o)
    return 1 + (o / 100 if o > 0 else 100 / -o)


def push_of(e):
    """a push is worth 0 at the close too: picks on whole-number lines can push; treated as no push (the close value is
    already a return, so q below is the chance net of pushes)"""
    return 0.0


def close_q(e):
    """the close's chance the pick wins, from its close value at the pick's price: clvRet = q (d - 1) - (1 - q)"""
    d = dec(e['price'])
    return min(0.999, max(0.001, (e['clvRet'] + 1) / d))


def profit(e):
    """result per 1u staked at the pick's price (w / l / p)"""
    r = e.get('res')
    if r == 'w':
        return dec(e['price']) - 1
    if r == 'l':
        return -1.0
    return 0.0 if r in ('p', 'push') else None


def rule_key(book, e):
    if book in ('nflprops', 'tennis'):
        return book, 'all'
    return book, ('spread' if e['mk'] == 'ml' else e['mk'])


def picks(book):
    d = json.load(open(os.path.join(ROOT, 'data', f'games_picks_{book}.json')))
    out = []
    for e in (d.get('log') or []) + (d.get('withdrawnLog') or []):
        if not RM.judged(e) or e.get('clvRet') is None or e.get('price') is None or not e.get('kick'):
            continue
        out.append(e)
    return out, d


def tci(m, se, G):
    """95% interval on G - 1 df (normal past 30)"""
    if m is None or se is None:
        return None
    df = max(1, G - 1)
    z = 1.96 if df >= 30 else {1: 12.71, 2: 4.30, 3: 3.18, 4: 2.78, 5: 2.57, 6: 2.45, 7: 2.36, 8: 2.31, 9: 2.26, 10: 2.23,
                               12: 2.18, 15: 2.13, 20: 2.09, 25: 2.06}.get(df) or (2.23 if df < 12 else 2.13 if df < 20 else 2.06)
    return [round(m - z * se, 4), round(m + z * se, 4)]


def summarize(es):
    days = [RM.day(e['kick']) for e in es]
    clv = [e['clvRet'] for e in es]
    m, se, t, G = RM.clustered(clv, days)
    p = RM.t_cdf(t, G - 1) if t is not None and G >= 2 else None
    graded = [(e, profit(e)) for e in es if profit(e) is not None]
    gd = [RM.day(e['kick']) for e, _ in graded]
    roi, rse, _, rG = RM.clustered([x for _, x in graded], gd)
    st = [(e, x) for e, x in graded if (e.get('units') or 0) > 0]
    sroi, sse, _, sG = RM.clustered([x for _, x in st], [RM.day(e['kick']) for e, _ in st], [e['units'] for e, _ in st]) if st else (None, None, None, 0)
    # calibration: chance staked on vs the close's chance vs the result (decided picks only)
    dec_ = [(e, x) for e, x in graded if x != 0]
    cal = None
    if dec_:
        pw = [e.get('pDU') or e.get('p') for e, _ in dec_]
        qs = [close_q(e) for e, _ in dec_]
        ys = [1.0 if x > 0 else 0.0 for _, x in dec_]
        bm = sum((a - y) ** 2 for a, y in zip(pw, ys)) / len(ys)
        bq = sum((a - y) ** 2 for a, y in zip(qs, ys)) / len(ys)
        dd = [RM.day(e['kick']) for e, _ in dec_]
        gap, gse, _, gG = RM.clustered([y - a for a, y in zip(pw, ys)], dd)
        over, ose, _, oG = RM.clustered([a - q for a, q in zip(pw, qs)], dd)
        cal = {'n': len(ys), 'pDU': round(sum(pw) / len(pw), 4), 'qClose': round(sum(qs) / len(qs), 4),
               'win': round(sum(ys) / len(ys), 4), 'winMinusP': round(gap, 4), 'winMinusPci': tci(gap, gse, gG),
               'pOverClose': round(over, 4), 'pOverCloseCi': tci(over, ose, oG),
               'brierModel': round(bm, 4), 'brierClose': round(bq, 4), 'skill': round(1 - bm / bq, 4) if bq else None}
    ev = [e.get('evDU') or 0.0 for e in es]
    sxx = sum(x * x for x in ev)
    real = rse_ = None
    if sxx > 0:
        real = sum(x * r for x, r in zip(ev, clv)) / sxx
        acc = {}
        for x, r, dd in zip(ev, clv, days):
            acc[dd] = acc.get(dd, 0.0) + x * (r - real * x)
        Gd = len(acc)
        rse_ = math.sqrt(sum(v * v for v in acc.values()) * Gd / max(1, Gd - 1)) / sxx if Gd > 1 else None
    return {'n': len(es), 'days': G, 'clvRet': None if m is None else round(m, 4), 'clvCi': tci(m, se, G),
            't': None if t is None else round(t, 2), 'p': None if p is None else round(1 - p, 4),
            'beat': round(sum(1 for e in es if e['clvRet'] > 0) / len(es), 3) if es else None,
            'graded': len(graded), 'roi': None if roi is None else round(roi, 4), 'roiCi': tci(roi, rse, rG),
            'roiStaked': None if sroi is None else round(sroi, 4), 'roiStakedCi': tci(sroi, sse, sG),
            'evDU': round(sum(ev) / len(ev), 4) if ev else None,
            'real': None if real is None else round(real, 3), 'realSe': None if rse_ is None else round(rse_, 3),
            'cal': cal}


def holm(ps, alpha=ALPHA):
    """{key: (adjusted p, reject)} by Holm's step-down"""
    order = sorted(ps, key=lambda k: ps[k])
    m, out, run = len(order), {}, 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[k]))
        out[k] = run
    rej, stop = {}, False
    for k in order:
        stop = stop or out[k] > alpha
        rej[k] = not stop
    return {k: (round(out[k], 4), rej[k]) for k in order}


# ---------------------------------------------------------------- the stake multiplier

def realization(es, prior=PRIOR):
    """posterior mean (clipped to [0, 1]) of r, the share of the staked edge the picks realize at the close"""
    ev = [e.get('evDU') or 0.0 for e in es]
    sxx = sum(x * x for x in ev)
    if sxx <= 0:
        return prior[0], None, None
    clv = [e['clvRet'] for e in es]
    r = sum(x * c for x, c in zip(ev, clv)) / sxx
    acc = {}
    for e, x, c in zip(es, ev, clv):
        d = RM.day(e['kick'])
        acc[d] = acc.get(d, 0.0) + x * (c - r * x)
    G = len(acc)
    if G < 2:
        return prior[0], r, None
    se = math.sqrt(sum(v * v for v in acc.values()) * G / (G - 1)) / sxx
    # never trust a clustered se below the iid one on few days
    sd = math.sqrt(sum((c - r * x) ** 2 for x, c in zip(ev, clv)) / max(1, len(ev) - 1))
    se = max(se, sd / math.sqrt(sxx), 1e-6)
    w0, w1 = 1 / prior[1] ** 2, 1 / se ** 2
    post = (w0 * prior[0] + w1 * r) / (w0 + w1)
    return min(1.0, max(0.0, post)), r, se


_MULT = {}


def mult(book):
    """the stake multiplier a book's picks earn now: realization() on every judged pick in its log (1 = picks worth
    what they are staked on). Cached per run; the prior's mean when the log can't be read"""
    if book not in _MULT:
        try:
            _MULT[book] = realization(picks(book)[0])[0]
        except (OSError, ValueError):
            _MULT[book] = PRIOR[0]
    return _MULT[book]


def scaled(u, book):
    """a Kelly stake (% of bankroll) times the book's multiplier: quarter units, at least .25 when there is a stake"""
    return u if not u else max(0.25, round(u * mult(book) * 4) / 4)


def close_growth(e, f):
    """expected log growth of staking f (fraction of bankroll) on e at the close-implied chance"""
    if f <= 0:
        return 0.0
    q = close_q(e)
    b = dec(e['price']) - 1
    f = min(f, 0.99)
    return q * math.log(1 + f * b) + (1 - q) * math.log(1 - f)


def stake_of(e):
    """the Kelly stake the pick was posted at, % of bankroll before the night cap (paper rows carry what it would be)"""
    return e.get('unitsRaw') or e.get('units') or 0.0


def walk(es, prior=PRIOR):
    """walk-forward by game day: (multiplier used each day, close growth at posted stakes, at multiplied stakes)"""
    days = {}
    for e in es:
        days.setdefault(RM.day(e['kick']), []).append(e)
    seen, rows = [], []
    for d in sorted(days):
        m, _, _ = realization(seen, prior) if seen else (prior[0], None, None)
        g1 = sum(close_growth(e, stake_of(e) / 100) for e in days[d])
        gm = sum(close_growth(e, m * stake_of(e) / 100) for e in days[d])
        rows.append((d, round(m, 3), g1, gm, len(days[d])))
        seen += days[d]
    return rows


def best_mult(es):
    """in-sample multiplier that maximizes close growth (a record, never used to stake)"""
    best = (0.0, 0.0)
    for i in range(0, 41):
        m = i / 20
        g = sum(close_growth(e, m * stake_of(e) / 100) for e in es)
        if g > best[1] + 1e-12:
            best = (m, g)
    return best[0]


def build():
    out = {'asof': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'prior': list(PRIOR),
           'rules': [], 'books': [], 'holm': {}, 'walk': {}}
    allp, ps = [], {}
    for book in BOOKS:
        try:
            es, d = picks(book)
        except FileNotFoundError:
            continue
        if not es:
            continue
        ps_state = d.get('paperState') or {}
        paper = bool(ps_state.get('paper')) if ps_state else bool(d.get('paper'))
        groups = {}
        for e in es:
            groups.setdefault(rule_key(book, e), []).append(e)
        for (b, mk), g in sorted(groups.items()):
            s = summarize(g)
            row = {'book': b, 'name': NAMES[b], 'mk': mk, **s}
            out['rules'].append(row)
            if s['days'] >= MIN_DAYS and s['p'] is not None:
                ps[f'{b}|{mk}'] = s['p']
        s = summarize(es)
        post, raw, se = realization(es)
        wk = walk(es)
        g1, gm = sum(r[2] for r in wk), sum(r[3] for r in wk)
        out['books'].append({'book': book, 'name': NAMES[book], 'paper': paper, **s, 'mult': round(post, 3),
                             'mInSample': best_mult(es),
                             'growthPosted': round(100 * g1, 3), 'growthMult': round(100 * gm, 3)})
        out['walk'][book] = [{'day': r[0], 'm': r[1], 'g1': round(100 * r[2], 4), 'gm': round(100 * r[3], 4), 'n': r[4]} for r in wk]
        allp += es
    out['all'] = summarize(allp)
    h = holm(ps)
    out['holm'] = {k: {'pAdj': v[0], 'pass': v[1]} for k, v in h.items()}
    for r in out['rules']:
        k = f"{r['book']}|{r['mk']}"
        r['holm'] = out['holm'].get(k)
    # the books are the unit that goes live or paper: Holm across all of them, whatever their days
    hb = holm({b['book']: b['p'] for b in out['books'] if b['p'] is not None})
    for b in out['books']:
        v = hb.get(b['book'])
        b['holm'] = {'pAdj': v[0], 'pass': v[1]} if v else None
    G1 = sum(b['growthPosted'] for b in out['books'])
    GM = sum(b['growthMult'] for b in out['books'])
    out['multTest'] = {'growthPosted': round(G1, 3), 'growthMult': round(GM, 3), 'pass': GM > G1}
    return out


def test():
    assert abs(dec(-110) - 1.9091) < 1e-3 and abs(dec(150) - 2.5) < 1e-9
    h = holm({'a': 0.01, 'b': 0.04, 'c': 0.03})
    assert h['a'] == (0.03, True) and h['c'] == (0.06, False) and h['b'][1] is False
    e = {'price': -110, 'clvRet': 0.0, 'kick': '2026-11-01T00:00:00Z'}
    assert abs(close_q(e) - 1 / dec(-110)) < 1e-9
    assert close_growth({**e, 'clvRet': 0.0}, 0.05) < 0            # zero edge: any stake loses at the close
    assert close_growth({**e, 'clvRet': 0.05}, 0.02) > 0
    es = [{'price': -103, 'clvRet': 0.01 * (-1) ** d, 'evDU': 0.03, 'kick': f'2026-11-{d:02d}T23:00:00Z'} for d in range(1, 21)]
    m, r, _ = realization(es)
    assert abs(r) < 0.1 and 0 <= m < PRIOR[0]
    print('picks_oos: ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
        sys.exit()
    o = build()
    with open(OUT, 'w') as f:
        json.dump(o, f, separators=(',', ':'))
    for b in o['books']:
        print(f"{b['name']:10} n {b['n']:4} days {b['days']:3} clv {b['clvRet']:+.4f} {b['clvCi']} t {b['t']} roi {b['roi']} "
              f"real {b['real']}±{b['realSe']} mult {b['mult']} mIS {b['mInSample']} G {b['growthPosted']:+.3f} -> {b['growthMult']:+.3f} paper {b['paper']}")
    for r in o['rules']:
        c = r['cal'] or {}
        print(f"  {r['book']:8} {r['mk']:7} n {r['n']:4} d {r['days']:3} clv {r['clvRet']:+.4f} {r['clvCi']} p {r['p']} holm {r['holm']} "
              f"roi {r['roi']} cal win-p {c.get('winMinusP')} p-q {c.get('pOverClose')} skill {c.get('skill')}")
    print('all', {k: o['all'][k] for k in ('n', 'days', 'clvRet', 'clvCi', 't', 'roi', 'roiCi', 'real', 'realSe')})
    print('mult test', o['multTest'])
