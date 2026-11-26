#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Draft-night trades for the NBA mock (cbb_mock.py): which picks change hands, held out by draft, 2008-26.

    python3 scripts/nba_draft_trades.py     # fetch (cached) Wikipedia draft pages, parse, backtest, write data/nba_trade_fit.json

Source: each "20XX NBA draft" Wikipedia page, the selections table: a pick's holder, its original team ("from") and
the team it was traded to on draft night ("traded to", post-draft trades), with the deal notes (what each side got).
Parsing and the tests live in scripts/research/nba_trades_nov26/ (parse, deals, curve, occur).

Stage A  Trade%: P(the pick changes hands on draft night), logit on ln(pick), ln(pick)^2, round 2 and ln(picks its
         holder has in the draft); leave-one-draft-out log loss against the slot alone and a flat rate.
Stage B  who gets it: conditional logit over the other 29 teams (picks held, a later pick, gap, record, original
         owner) against a uniform draw. Fails, so the mock names no partner.
Curve    a pick value chart fit to NBA pure-pick deals (power law + future firsts, seconds and cash) against the
         Massey-Thaler chart the NFL mock uses, held out by draft. Fails to beat it, so nothing is priced on it.
The mock (cbb_mock.py) shows Trade% for every pick and tags the likeliest picks in each round, as many as the round's
expected number of trades, as projected trades."""
import json, math, os, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'research', 'nba_trades_nov26'))
import parse as PA
OUT = os.path.join(PA.ROOT, 'data', 'nba_trade_fit.json')
YEARS = range(2008, 2027)
KEYS = ['lnpick', 'ln2', 'r2', 'npk']


def fetch():
    os.makedirs(PA.C, exist_ok=True)
    for y in YEARS:
        p = os.path.join(PA.C, f'w{y}.txt')
        if os.path.exists(p) and os.path.getsize(p) > 20000: continue
        subprocess.run(['curl', '-s', '-m', '60', '-A', 'arkndjl.net research script', '-o', p,
                        f'https://en.wikipedia.org/w/index.php?title={y}_NBA_draft&action=raw'], check=False)


def feats(pick, rnd, held):
    """the stage A inputs for one pick: held = how many picks its holder has in the draft"""
    lp = math.log(pick)
    return {'lnpick': lp, 'ln2': lp * lp, 'r2': float(rnd == 2), 'npk': math.log(max(held, 1))}


def trade_p(fit, pick, rnd, held):
    f = feats(pick, rnd, held)
    z = fit['b'][0] + sum(b * f[k] for b, k in zip(fit['b'][1:], fit['keys']))
    return 1 / (1 + math.exp(-z))


def main():
    fetch()
    allp = []
    for y in YEARS: allp += PA.parse(y)
    json.dump(allp, open(os.path.join(PA.C, 'picks.json'), 'w'))
    import deals as DL
    import importlib
    importlib.reload(DL)
    json.dump(DL.deals(), open(os.path.join(PA.C, 'deals.json'), 'w'))
    import occur as O, curve as CV
    importlib.reload(O); importlib.reload(CV)
    R = O.rows_A()
    for r in R: r[1]['ln2'] = r[1]['lnpick'] ** 2
    lc = []
    for y in O.YRS:
        tr = np.mean([r[2] for r in R if r[0] != y]); te = np.array([r[2] for r in R if r[0] == y])
        lc += list(-(te * np.log(tr) + (1 - te) * np.log(1 - tr)))
    lc = np.array(lc)
    ls, pers = O.lodo_A(R, ['lnpick', 'r2'])
    lf, perf = O.lodo_A(R, KEYS)
    perc = {y: lc[np.array([r[0] for r in R]) == y].mean() for y in O.YRS}
    X = np.array([[1] + [r[1][k] for k in KEYS] for r in R]); Y = np.array([r[2] for r in R])
    b = O.logit_fit(X, Y)
    # held-out calibration: expected vs actual trades a draft, by round
    cal = {}
    for rd in (1, 2):
        e = a = 0
        for y in O.YRS:
            tr = [r for r in R if r[0] != y]
            bb = O.logit_fit(np.array([[1] + [r[1][k] for k in KEYS] for r in tr]), np.array([r[2] for r in tr]))
            for r in R:
                if r[0] == y and r[1]['r2'] == rd - 1:
                    e += 1 / (1 + math.exp(-(bb[0] + sum(c * r[1][k] for c, k in zip(bb[1:], KEYS))))); a += r[2]
        cal[f'R{rd}'] = {'expected': round(e / len(O.YRS), 2), 'actual': round(a / len(O.YRS), 2)}
    G = O.groups_B()
    KB = ['any', 'later', 'lngap', 'npk', 'qual', 'sameRd', 'orig']
    lu, t1u, t3u = O.lodo_B(G, []); lb, t1, t3 = O.lodo_B(G, KB)
    ys = np.array([g[0] for g in G]); d = lb - lu
    gg = np.array([d[ys == y].sum() for y in O.YRS if (ys == y).any()])
    tB = d.mean() / (math.sqrt(len(gg)) * gg.std(ddof=1) / len(d))
    CV.FORM = 'power'
    yrs = sorted({x['y'] for x in CV.D})
    en, em = [], []
    for y in yrs:
        th = CV.fit([x for x in CV.D if x['y'] != y])
        for x in CV.D:
            if x['y'] == y: en.append(abs(CV.resid(x, th))); em.append(abs(CV.resid(x, CV.MT_FULL)))
    en, em = np.array(en), np.array(em)
    dc = en - em; dys = np.array([x['y'] for x in CV.D])
    gc = np.array([dc[dys == y].sum() for y in yrs]); tC = dc.mean() / (math.sqrt(len(gc)) * gc.std(ddof=1) / len(dc))
    cbetter = sum(en[dys == y].mean() < em[dys == y].mean() for y in yrs)
    out = {
        'asof': __import__('time').strftime('%Y-%m-%d'), 'drafts': [O.YRS[0], O.YRS[-1]], 'picks': len(R), 'traded': int(Y.sum()),
        'rate': round(float(Y.mean()), 3), 'keys': KEYS, 'b': [round(float(x), 4) for x in b],
        'held': {'ll': round(float(lf.mean()), 4), 'llSlot': round(float(ls.mean()), 4), 'llFlat': round(float(lc.mean()), 4),
                 'tSlot': round(float(O.clustered_t(lf, ls, R)), 2), 'tFlat': round(float(O.clustered_t(lf, lc, R)), 2),
                 'wonSlot': int(sum(perf[y] < pers[y] for y in O.YRS)), 'wonFlat': int(sum(perf[y] < perc[y] for y in O.YRS)), 'of': len(O.YRS)},
        'perRound': cal,
        'partner': {'n': len(G), 'll': round(float(lb.mean()), 3), 'llUniform': round(float(lu.mean()), 3), 't': round(float(tB), 2),
                    'top1': round(float(t1), 3), 'top1Uniform': round(float(t1u), 3), 'top3': round(float(t3), 3), 'top3Uniform': round(float(t3u), 3), 'ship': bool(tB <= -2)},
        'curve': {'n': len(CV.D), 'drafts': [yrs[0], yrs[-1]], 'err': round(float(en.mean()), 3), 'errMT': round(float(em.mean()), 3),
                  't': round(float(tC), 2), 'won': int(cbetter), 'of': len(yrs), 'ship': bool(tC <= -2)},
    }
    print(json.dumps(out, indent=1))
    json.dump(out, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
