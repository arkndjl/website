# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""MoneyPuck pregame win probability: second-stage stack on the NHL win model, the public benchmark table, and the
morning-line timing study (pre-registered H1, H9).

usage: mp_stack.py <dir from mp_pull.py> <out.json>
"""
import csv, datetime as dt, email.utils, gzip, json, math, os, sys
from zoneinfo import ZoneInfo
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
import harness as H  # noqa: E402

ET = ZoneInfo('America/New_York')
TUNE, HELD = (2021, 2022, 2023), (2024, 2025, 2026)


def lg(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def logit_fit(X, y):
    b = np.zeros(X.shape[1])
    for _ in range(50):
        p = 1 / (1 + np.exp(-(X @ b)))
        st = np.linalg.solve((X * (p * (1 - p))[:, None]).T @ X + 1e-8 * np.eye(X.shape[1]), X.T @ (y - p))
        b += st
        if np.abs(st).max() < 1e-9:
            break
    return b


def load(d):
    wf = {g['id']: g for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'nhl.json.gz')))
          if 2020 <= g['S'] <= 2026 and g.get('c')}
    start = {g['id']: g.get('t') for g in json.load(gzip.open(os.path.join(ROOT, 'scripts', 'nhl_games_hist.json.gz'))) if g['id'] in wf}
    rows, n = [], {'index': 0, 'not200': 0, 'late': 0, 'nostart': 0, 'bad': 0, 'teams': 0}
    for ln in open(os.path.join(d, 'index.jsonl')):
        r = json.loads(ln)
        n['index'] += 1
        g = wf.get(r['id'])
        if r.get('code') != 200 or not g:
            n['not200'] += 1; continue
        t0 = start.get(r['id'])
        if not t0 or not r.get('lm'):
            n['nostart'] += 1; continue
        st = dt.datetime.fromisoformat(t0).replace(tzinfo=ET).astimezone(dt.timezone.utc)
        if email.utils.parsedate_to_datetime(r['lm']) >= st:
            n['late'] += 1; continue
        try:
            c = next(csv.DictReader(open(os.path.join(d, '%d.csv' % r['id']), encoding='utf8')))
            ov = float(c['preGameHomeTeamWinOverallScore'])
        except Exception:
            n['bad'] += 1; continue
        from nhl_data import team as T
        if T(c['homeTeamCode']) != g['h']:
            n['teams'] += 1; continue

        def f(k):
            try:
                v = float(c.get(k) or 'nan')
                return v if 0 < v < 1 else float('nan')
            except ValueError:
                return float('nan')
        rows.append({'id': r['id'], 'S': g['S'], 'day': g['day'], 'y': float(g['hs'] > g['as']), 'p': g['p'], 'c': g['c']['p'],
                     'o': (g.get('o') or {}).get('p'), 'ov': ov, 'mp2': f('preGameMoneyPuckHomeWinPrediction'),
                     'odds': f('preGameBettingOddsHomeWinPrediction')})
    return rows, n


def main(d, outp):
    rows, n = load(d)
    res = {'files': n, 'kept': len(rows), 'bySeason': {}}
    if len(rows) < 5000:
        res['verdict'] = 'BLOCKED: under 5,000 usable files'
        json.dump(res, open(outp, 'w'), indent=1); print(res); return
    A = lambda k: np.array([r[k] if r[k] is not None else np.nan for r in rows], float)
    S, y, p, c, ov, mp2, odds = A('S'), A('y'), A('p'), A('c'), A('ov'), A('mp2'), A('odds')
    day = np.array([r['day'] for r in rows])
    # which model column is the model-only number (farther from the odds column)
    m = ~np.isnan(mp2) & ~np.isnan(odds)
    dist = {'overall': float(np.abs(ov[m] - odds[m]).mean()), 'mpPred': float(np.abs(mp2[m] - odds[m]).mean())}
    use2 = dist['mpPred'] > dist['overall'] + 1e-9
    mp = np.where(use2 & ~np.isnan(mp2), mp2, ov)
    res['column'] = {'meanAbsGapToOdds': {k: round(v, 4) for k, v in dist.items()}, 'n': int(m.sum()),
                     'used': 'preGameMoneyPuckHomeWinPrediction where present' if use2 else 'preGameHomeTeamWinOverallScore',
                     'corrOverallMpPred': round(float(np.corrcoef(ov[m], mp2[m])[0, 1]), 4)}
    zp, zm = lg(p), lg(mp)
    ps, pr_, coef = np.full(len(y), np.nan), np.full(len(y), np.nan), {}
    for s in range(2021, 2027):
        tr, te = S < s, S == s
        b = logit_fit(np.column_stack([np.ones(tr.sum()), zp[tr], zm[tr]]), y[tr])
        ps[te] = 1 / (1 + np.exp(-(b[0] + b[1] * zp[te] + b[2] * zm[te])))
        b0 = logit_fit(np.column_stack([np.ones(tr.sum()), zp[tr]]), y[tr])
        pr_[te] = 1 / (1 + np.exp(-(b0[0] + b0[1] * zp[te])))
        coef[s] = [round(float(v), 3) for v in b]
    res['coef'] = coef
    ll = lambda q, mk: H.logloss(np.clip(q[mk], 1e-4, 1 - 1e-4), y[mk])
    for lab, ss in (('tune', TUNE), ('held', HELD)):
        mk = np.isin(S, ss)
        l1, l0 = ll(ps, mk), ll(p, mk)
        t = H.paired(l1, l0, day[mk])
        better = sum(1 for s in ss if (l1 - l0)[S[mk] == s].mean() < 0)
        tr_ = H.paired(ll(pr_, mk), l0, day[mk]); tm = H.paired(ll(mp, mk), l0, day[mk]); tc = H.paired(l1, ll(c, mk), day[mk])
        res[lab] = {'n': int(mk.sum()), 'llModel': round(float(l0.mean()), 5), 'llStack': round(float(l1.mean()), 5),
                    'd': round(float((l1 - l0).mean()), 5), 't': round(t['t'], 2), 'p': t['p'], 'seasonsBetter': f'{better}/{len(ss)}',
                    'llRecalOnly': round(float(ll(pr_, mk).mean()), 5), 'tRecalOnly': round(tr_['t'], 2),
                    'llMP': round(float(ll(mp, mk).mean()), 5), 'tMPvsModel': round(tm['t'], 2),
                    'llClose': round(float(ll(c, mk).mean()), 5), 'tStackVsClose': round(tc['t'], 2)}
    for s in range(2020, 2027):
        mk = S == s
        if mk.sum():
            res['bySeason'][str(s)] = {'n': int(mk.sum()), 'model': round(float(ll(p, mk).mean()), 4), 'moneypuck': round(float(ll(mp, mk).mean()), 4),
                                       'close': round(float(ll(c, mk).mean()), 4),
                                       'stack': round(float(ll(ps, mk).mean()), 4) if s >= 2021 else None,
                                       'sdModel': round(float(zp[mk].std() / lg(c[mk]).std()), 3), 'sdMP': round(float(zm[mk].std() / lg(c[mk]).std()), 3)}
    # H9: morning line
    mo = ~np.isnan(odds)
    h9 = {'n': int(mo.sum()), 'rClose': round(float(np.corrcoef(odds[mo], c[mo])[0, 1]), 4),
          'meanAbsToClose': round(float(np.abs(odds[mo] - c[mo]).mean()), 4)}
    o_ = A('o'); mo2 = mo & ~np.isnan(o_)
    if mo2.sum() > 50:
        h9['rOpen'] = round(float(np.corrcoef(odds[mo2], o_[mo2])[0, 1]), 4); h9['meanAbsToOpen'] = round(float(np.abs(odds[mo2] - o_[mo2]).mean()), 4)
    for lab, ss in (('tune', (2022, 2023)), ('held', HELD)):
        mk = mo & np.isin(S, ss) & (np.abs(p - odds) >= 0.03)
        side = np.sign(p[mk] - odds[mk])
        clv = side * (c[mk] - odds[mk])
        ms = np.where(side > 0, odds[mk], 1 - odds[mk]); win = np.where(side > 0, y[mk], 1 - y[mk])
        ret = win / ms - 1
        tc_ = H.paired(-clv, np.zeros(len(clv)), day[mk]); tr2 = H.paired(-ret, np.zeros(len(ret)), day[mk])
        h9[lab] = {'n': int(mk.sum()), 'clv': round(float(clv.mean()), 5), 'tClv': round(-tc_['t'], 2), 'ret': round(float(ret.mean()), 4), 'tRet': round(-tr2['t'], 2),
                   'seasonsClvPos': f"{sum(1 for s in ss if clv[S[mk] == s].mean() > 0)}/{len(ss)}"}
    res['morning'] = h9
    json.dump(res, open(outp, 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
