#!/usr/bin/env python3
"""Pick rule + stake recalibration for Novig prices (Noah, Oct 27 2026: "recheck/recalibrate what should qualify as a
pick and how many units to use in order to make our picks as profitable as possible"). Research harness, nothing live
reads it.

    python3 scripts/pick_recal.py            # data/pick_recal.json + a table

Walk-forward on every season with opening lines: each test season's calibration is fit on the seasons before it only,
then scored on the test season. The score is the long-run profit a Kelly bettor cares about: log growth of the
bankroll, (a) expected at the close (each pick's chance if the close is the truth; low noise) and (b) realized on the
results. Stakes are compounding % of bankroll (DU), bets at the price we now get (Novig, about -103 a side on spreads
and totals; DraftKings was -110).

calibration: d(gap) = a + b x gap, the close-implied chance edge over a fair coin (win - loss, no vig) of the model's
side at the open, by gap (|model - open|, points), OLS on the fit seasons' picks (gap >= 1, no bad opens, inside the
3 sd cap). A pick's chance is w = (1 - push + d) / 2, its expected return at price o is e = w (dec(o) - 1) - l.

policies
  meanX   the rule since Oct 21: X = the cut with the best mean close value at the fit price (n >= 40, t >= 1)
  edge0   every pick whose calibrated return at the bet price is > 0 (the growth-optimal cut under Kelly)
  edgeSE  every pick whose calibrated return is > its standard error
stake: lam x u x Kelly on the calibrated return (u = e^2 / (e^2 + var e)), capped at cap % a bet, slate exposure <= 50%
timing: a live pick is bet at the line when it posts, after part of the open's move, so the scoring can take the true
live edge as TRUE x the backtest's, and the growth cut can be fit on a calibration scaled by s.

Result (Oct 27 2026, bet at -103, 1x Kelly, cap 5): the Oct 21 rule 93% total log growth (realized 146%); the growth cut
at s 1: 458% (1,029%), at s .5: 178% (336%). With the true live edge at half the backtest's: 19% / 20% / 51%; at 0.3 of it:
-11% / -155% / -0%. The odds archive's first week ran at 0.44, so units.TIMING = 0.5 shipped: it beats the Oct 21 rule at
every true share from 0.3 to 1. Caps 3, 5, 10 alike; lam 1 beats .5/.75 unless the true share is under ~0.4.
NBA: its history is an upper bound (the model saw tip-time injuries), so its edges over a fair coin are halved both in
the calibration and in the scoring, the same leak units.py applies.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import clv as C  # noqa: E402
import games_picks as GP  # noqa: E402
import units as U  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'pick_recal.json')
LEAK = {'nba': 0.5}
G0 = 1.0
MARKETS = {'cfb': ('spread', 'total'), 'cbb': ('spread',), 'nba': ('spread', 'total')}
SLATE_MAX = 0.5


def dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


def picks(sport, mk):
    """every opened game's model side: {S, slate, gap, w, p, l (close-implied, leak applied), res margin vs line}"""
    F = json.load(open(GP.FIT))['sports']
    caps = F.get(sport, {}).get('cap') or [None, None]
    cap = caps[0] if mk == 'spread' else caps[1]
    rows = [r for r in GP.load_wf(sport) if r.get('res') is not None and (r.get('Lo') if mk == 'spread' else r.get('To')) is not None]
    out = []
    m = LEAK.get(sport, 1.0)
    for e in GP.rule_bets(sport, rows, mk, G0, True, cap):
        g = e['g']
        close = g['L'] if mk == 'spread' else g['T']
        c = C.chances(sport, mk, e['side'], e['line'], close)
        if c is None or U.bad_open(sport, mk, g):
            continue
        w, p, l = c
        d = (w - l) * m
        w, l = (1 - p + d) / 2, (1 - p - d) / 2
        res = g['res'] if mk == 'spread' else g['tot']
        dd = (res - e['line']) if e['side'] in ('home', 'over') else (e['line'] - res)
        out.append({'S': g['S'], 'slate': U.slate_of(sport, g), 'gap': e['edge'], 'w': w, 'p': p, 'l': l, 'd': d,
                    'r': 0 if dd == 0 else (1 if dd > 0 else -1)})
    return out


def ols(xs, ys, cl):
    """y = a + b x: (a, b, cov) with slate-clustered errors (floored at iid)"""
    n = len(xs)
    xb = sum(xs) / n
    sxx = sum((x - xb) ** 2 for x in xs) or 1e-9
    b = sum((x - xb) * (y - sum(ys) / n) for x, y in zip(xs, ys)) / sxx
    a = sum(ys) / n - b * xb
    res = [y - a - b * x for x, y in zip(xs, ys)]
    s2 = sum(r * r for r in res) / max(1, n - 2)
    # iid covariance of (a, b)
    Vi = [[s2 * (1 / n + xb * xb / sxx), -s2 * xb / sxx], [-s2 * xb / sxx, s2 / sxx]]
    # clustered (sandwich) on the slate
    G = {}
    for x, r, c in zip(xs, res, cl):
        g = G.setdefault(c, [0.0, 0.0])
        g[0] += r
        g[1] += r * x
    Sx, Sxx = sum(xs), sum(x * x for x in xs)
    det = n * Sxx - Sx * Sx
    Inv = [[Sxx / det, -Sx / det], [-Sx / det, n / det]]
    M = [[sum(g[0] * g[0] for g in G.values()), sum(g[0] * g[1] for g in G.values())],
         [sum(g[0] * g[1] for g in G.values()), sum(g[1] * g[1] for g in G.values())]]
    A = [[sum(Inv[i][k] * M[k][j] for k in range(2)) for j in range(2)] for i in range(2)]
    Vc = [[sum(A[i][k] * Inv[k][j] for k in range(2)) for j in range(2)] for i in range(2)]
    V = [[max(Vi[i][j], Vc[i][j]) if i == j else Vc[i][j] for j in range(2)] for i in range(2)]
    return a, b, V


def calib(fit):
    a, b, V = ols([q['gap'] for q in fit], [q['d'] for q in fit], [q['slate'] for q in fit])
    push = sum(q['p'] for q in fit) / len(fit)
    return {'a': a, 'b': b, 'V': V, 'push': push}


def pred(cal, gap, o):
    """(expected return at price o, its sd, win, push, loss)"""
    d = cal['a'] + cal['b'] * gap
    V = cal['V']
    vd = max(0.0, V[0][0] + 2 * gap * V[0][1] + gap * gap * V[1][1])
    p = cal['push']
    w, l = (1 - p + d) / 2, (1 - p - d) / 2
    B = dec(o) - 1
    return w * B - l, math.sqrt(vd) * (B + 1) / 2, w, p, l


def mean_x(fit, o, grid, total=False):
    """the Oct 21 rule: the cut with the best mean close-implied return at price o (n >= 40, t >= 1); total: the cut
    with the most total close-implied return (where the marginal pick stops paying: the growth cut)"""
    best = None
    B = dec(o) - 1
    for x in grid:
        rs = [q['w'] * B - q['l'] for q in fit if q['gap'] >= x]
        if len(rs) < GP.RULE_MIN_N:
            continue
        m = sum(rs) / len(rs)
        s = math.sqrt(sum((r - m) ** 2 for r in rs) / (len(rs) - 1))
        v = m * len(rs) if total else m
        if m > 0 and s and m / (s / math.sqrt(len(rs))) >= 1 and (best is None or v > best[1]):
            best = (x, v)
    return best[0] if best else None


def stakes(test, cal, pol, o):
    """% of bankroll per test pick (0 = no bet)"""
    B = dec(o) - 1
    out = []
    for q in test:
        e, se, w, p, l = pred(cal, q['gap'], o)
        ok = e > 0
        if pol['rule'] in ('meanX', 'sumX'):
            ok = ok and pol['x'] is not None and q['gap'] >= pol['x']
        elif pol['rule'] == 'edgeSE':
            ok = ok and e > se
        elif pol['rule'] == 'edgeMin':
            ok = ok and e >= pol['m']
        if pol.get('xmin') is not None:
            ok = ok and q['gap'] >= pol['xmin']
        if not ok:
            out.append(0.0)
            continue
        u = e * e / (e * e + se * se)
        f = pol['lam'] * u * e / (B * (1 - p))
        out.append(min(pol['cap'] / 100, f))
    return out


STRESS = 1.0


def score(test, f, o):
    """(expected log growth at the close, realized log growth, bets, staked) summed over the test picks, by slate"""
    B = dec(o) - 1
    sl = {}
    for q, s in zip(test, f):
        if s > 0:
            sl.setdefault(q['slate'], []).append((q, s))
    ge = gr = 0.0
    nb = 0
    st = 0.0
    for v in sl.values():
        tot = sum(s for _, s in v)
        k = min(1.0, SLATE_MAX / tot) if tot > 0 else 1.0
        x = 0.0
        for q, s in v:
            s *= k
            d = q['d'] * STRESS
            w, l = (1 - q['p'] + d) / 2, (1 - q['p'] - d) / 2
            ge += w * math.log(1 + s * B) + l * math.log(1 - s)
            x += s * (B if q['r'] > 0 else -1 if q['r'] < 0 else 0)
            nb += 1
            st += s
        gr += math.log(max(1e-9, 1 + x))
    return ge, gr, nb, st


def run(O_BET=-103, O_FIT_OLD=-110):
    lams = (0.25, 0.5, 0.75, 1.0, 1.5)
    caps = (2.0, 3.0, 5.0, 10.0)
    pols = []
    for lam in lams:
        for cap in caps:
            pols.append({'rule': 'meanX', 'ofit': O_FIT_OLD, 'lam': lam, 'cap': cap})
            pols.append({'rule': 'meanX', 'ofit': O_BET, 'lam': lam, 'cap': cap})
            pols.append({'rule': 'edge0', 'lam': lam, 'cap': cap})
            pols.append({'rule': 'edgeSE', 'lam': lam, 'cap': cap})
            pols.append({'rule': 'sumX', 'ofit': O_BET, 'lam': lam, 'cap': cap})

    def key(p):
        return f"{p['rule']}{'@' + str(p['ofit']) if p.get('ofit') else ''} lam {p['lam']} cap {p['cap']}"
    res = {}
    for sport, mks in MARKETS.items():
        for mk in mks:
            P = picks(sport, mk)
            seasons = sorted({q['S'] for q in P})
            grid = GP.RULE_GRID[mk]
            for T in seasons[1:]:
                fit = [q for q in P if q['S'] < T]
                test = [q for q in P if q['S'] == T]
                if len(fit) < 100 or not test:
                    continue
                cal = calib(fit)
                xs = {o: mean_x(fit, o, grid) for o in (O_FIT_OLD, O_BET)}
                xsum = mean_x(fit, O_BET, grid, True)
                for pol in pols:
                    pp = dict(pol)
                    if pp['rule'] == 'meanX':
                        pp['x'] = xs[pp['ofit']]
                    elif pp['rule'] == 'sumX':
                        pp['x'] = xsum
                    f = stakes(test, cal, pp, O_BET)
                    ge, gr, nb, st = score(test, f, O_BET)
                    r = res.setdefault(key(pol), {}).setdefault(f'{sport} {mk}', [])
                    r.append({'S': T, 'ge': ge, 'gr': gr, 'n': nb, 'st': st, 'x': pp.get('x')})
    return res, pols, key


def scaled(cal, s):
    """a calibration with its edge over a fair coin scaled by s (the timing haircut, units.TIMING)"""
    return {**cal, 'a': cal['a'] * s, 'b': cal['b'] * s, 'V': [[v * s * s for v in r] for r in cal['V']]}


def main():
    """the decision table (Oct 27 2026): the Oct 21 rule (meanX at -110, 1x Kelly, cap 5) against the growth cut on a
    calibration scaled by s, scored at the bet price with the true live edge at TRUE x the backtest's"""
    global STRESS
    pols = [('meanX@-110', None, 1.0, 5.0)] + [('edge0', s, 1.0, 5.0) for s in (1.0, 0.75, 0.6, 0.5)] + \
           [('edge0', 0.5, lam, 5.0) for lam in (0.5, 0.75, 1.25)] + [('edge0', 0.5, 1.0, c) for c in (3.0, 10.0)]
    D = {}
    for sport, mks in MARKETS.items():
        for mk in mks:
            P = picks(sport, mk)
            ss = sorted({q['S'] for q in P})
            for T in ss[1:]:
                fit = [q for q in P if q['S'] < T]
                D[(sport, mk, T)] = (calib(fit), mean_x(fit, -110, GP.RULE_GRID[mk]), [q for q in P if q['S'] == T])
    out = []
    for ob in (-103, -105, -110):
        for st in (1.0, 0.75, 0.5, 0.3):
            STRESS = st
            for name, s, lam, cap in pols:
                ge = gr = 0.0
                nb = 0
                for (sport, mk, T), (cal, x, test) in D.items():
                    if s is None:
                        pp, c = {'rule': 'meanX', 'x': x, 'lam': lam, 'cap': cap}, cal
                    else:
                        pp, c = {'rule': 'edge0', 'lam': lam, 'cap': cap}, scaled(cal, s)
                    a, b, n, _ = score(test, stakes(test, c, pp, ob), ob)
                    ge, gr, nb = ge + a, gr + b, nb + n
                out.append({'price': ob, 'true': st, 'rule': name, 'timing': s, 'lam': lam, 'cap': cap,
                            'gClose': round(ge * 100, 1), 'gReal': round(gr * 100, 1), 'n': nb})
                print(f"bet {ob} true x{st}: {name} s {s} lam {lam} cap {cap}: log growth close {ge * 100:.1f}% real {gr * 100:.1f}% n {nb}")
    STRESS = 1.0
    json.dump({'note': 'walk-forward test seasons (CFB 2024-26, CBB 2025-26, NBA 2016-17 + 2024-26), total log growth in % '
                       '(close-implied with the live edge at true x the backtest, and realized)', 'rows': out}, open(OUT, 'w'), indent=0)


if __name__ == '__main__':
    main()
