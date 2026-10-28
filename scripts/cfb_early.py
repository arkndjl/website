#!/usr/bin/env python3
"""CFB early-season corrections to the game model (thread "Improve early-season CFB predictions", Oct 28 2026).

Weeks 0-2 are where the CFB model trails the close most (+1.2 to +1.9 points of MAE). Two shapes in the walk-forward
history (scripts/data/games_wf/cfb.json.gz) explain part of it:
  margins  FBS vs FBS in weeks 1-3 (ESPN week 1 holds week 0) run compressed: the result on the model's margin has a
           slope of 1.13 on 2017-21 and sits above 1 in every season 2017-26 (later weeks ~1.0, the close ~1.0). The
           preseason ratings are pulled too far toward the mean. Margin and sigma both x k, so win chances don't move.
  totals   weeks 2-6 run the other way (slope .75 on 2017-21): each total shrinks toward its week's mean total by s
           (the week's level is kept; games_picks recentres totals on the line anyway). Week 1 has no model total.
k and s are fit on 2017-21 (2020 left out) and judged on 2022-26 (paired t, clustered by game day). Constants live in
cfb_model.mjs EARLY; keep the two in step.

Also tested here and not shipped (results in data/cfb_early.json):
  win totals   preseason market win totals (sportsbettingdime.com past-seasons page, 2018-25, ~70-130 teams a year) as
               a week 1-2 prior input: the close already prices them; the result residual does not (held out b ~0).
  ML slope     a.logit(no-vig close ML) + c, and the spread-vs-ML gap, as the ML pick offset: the favourite-longshot
               bias sits past +-300, which games_picks.ML_CAP already leaves out; inside it held out log loss is worse.
  bowl opens   the model with the opt-out term beats the bowl close from the open 2023-25 (+5-9% CLV), but the history's
               opt-out inputs are hindsight (a transfer = played elsewhere next season; draft ranks from April), so the
               CLV is not point-in-time. Grade the live bowl picks (Transfer% / Draft% at the time) before any segment.

    python3 scripts/cfb_early.py                 # research -> data/cfb_early.json, ledger rows (data/model_ledger.json)
    python3 scripts/cfb_early.py --wf            # apply k and s to scripts/data/games_wf/cfb.json.gz (once; rows keep
                                                 # ek and tmr, the raw total, so the research reads the raw model)
    python3 scripts/cfb_early.py --wt <page.html>   # the win-total test from a saved copy of the SBD page
Then games_picks.py --fit and --rules.
"""
import gzip
import html
import json
import math
import os
import re
import sys
from statistics import NormalDist

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import harness as H  # noqa: E402

WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
OUT = os.path.join(ROOT, 'data', 'cfb_early.json')
EARLY = {'wk': 3, 'k': 1.13, 'tw': (2, 6), 's': 0.75}       # cfb_model.mjs EARLY
TUNE, HELD = (2017, 2018, 2019, 2021), (2022, 2023, 2024, 2025, 2026)


def load():
    return json.load(gzip.open(WF))


def raw(rows):
    """the model's own margin and total, before these corrections"""
    for r in rows:
        r['m_'] = r['m'] / r.get('ek', 1)
        r['tm_'] = r.get('tmr', r['tm'])
    return rows


def margin_on(r):
    return r['fcs'] == 0 and r['wk'] <= EARLY['wk']


def slates(rows, key):
    mu = {}
    for r in rows:
        if r.get(key) is not None:
            mu.setdefault((r['S'], r['wk']), []).append(r[key])
    return {k: float(np.mean(v)) for k, v in mu.items()}


def Phi(z):
    return 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z, float) / math.sqrt(2)))


def pt(new, base, day):
    p = H.paired(new, base, cluster=day)
    return {'d': round(float(np.mean(new) - np.mean(base)), 4), 't': round(p['t'], 2), 'n': int(len(new)), 'G': p['G']}


def research():
    rows = raw([r for r in load() if r['S'] != 2020 and r['res'] is not None])
    out = {'asof': None, 'tune': TUNE, 'held': HELD}
    # margins: slope by week and season, the fit, the paired tests (weeks 1-4, so week 4 shows no harm)
    slope = lambda R, k='m_': float(sum(r[k] * r['res'] for r in R) / sum(r[k] ** 2 for r in R))
    out['slopeBySeason'] = {S: {'wk1_3': round(slope([r for r in rows if r['S'] == S and margin_on(r)]), 3),
                                'later': round(slope([r for r in rows if r['S'] == S and r['fcs'] == 0 and 4 <= r['wk'] <= 13]), 3)}
                            for S in sorted({r['S'] for r in rows})}
    k = slope([r for r in rows if r['S'] in TUNE and margin_on(r)])
    out['margin'] = {'kFit': round(k, 3), 'kShip': EARLY['k'], 'wfPath': {S: round(slope([r for r in rows if r['S'] < S and margin_on(r)]), 3) for S in range(2018, 2027)}}
    for nm, ss in (('tune', TUNE), ('held', HELD)):
        R = [r for r in rows if r['S'] in ss and r['wk'] <= EARLY['wk'] + 1]
        m, y, s = (np.array([r[c] for r in R]) for c in ('m_', 'res', 'sigma'))
        s = s / np.array([r.get('ek', 1) for r in R])
        kk = np.array([EARLY['k'] if margin_on(r) else 1 for r in R])
        day = np.array([r['date'][:10] for r in R])
        dec = y != 0
        out['margin'][nm] = {'mae': pt(H.ae(m * kk, y), H.ae(m, y), day), 'crps': pt(H.crps_normal(m * kk, s * kk, y), H.crps_normal(m, s, y), day),
                             'llSigmaFixed': pt(H.logloss(Phi(m * kk / s)[dec], (y[dec] > 0)), H.logloss(Phi(m / s)[dec], (y[dec] > 0)), day[dec]),
                             'maeBase': round(float(H.ae(m, y).mean()), 3)}
        L = np.array([r['L'] for r in R])
        out['margin'][nm]['distToClose'] = [round(float(np.abs(m - L).mean()), 3), round(float(np.abs(m * kk - L).mean()), 3)]
    # totals: shrink toward the week's mean
    T = [r for r in rows if r['tm_'] is not None]
    mu = slates(T, 'tm_')
    lo, hi = EARLY['tw']
    on = lambda r: lo <= r['wk'] <= hi
    tr = [r for r in T if r['S'] in TUNE and on(r)]
    d = np.array([r['tm_'] - mu[(r['S'], r['wk'])] for r in tr])
    e = np.array([r['tot'] - mu[(r['S'], r['wk'])] for r in tr])
    out['total'] = {'sFit': round(float(d @ e / (d @ d)), 3), 'sShip': EARLY['s']}
    for nm, ss in (('tune', TUNE), ('held', HELD)):
        R = [r for r in T if r['S'] in ss and on(r)]
        a = np.array([r['tm_'] for r in R])
        b = np.array([mu[(r['S'], r['wk'])] + EARLY['s'] * (r['tm_'] - mu[(r['S'], r['wk'])]) for r in R])
        y = np.array([r['tot'] for r in R])
        out['total'][nm] = {'mae': pt(H.ae(b, y), H.ae(a, y), np.array([r['date'][:10] for r in R])), 'maeBase': round(float(H.ae(a, y).mean()), 3)}
    return out


# ---- not shipped: preseason win totals (sportsbettingdime.com past seasons) -----------------------------------------
ALIAS = {'Appalachian State': 'App State', 'FIU': 'Florida International', 'Hawaii': "Hawai'i", 'Miami FL': 'Miami', 'Miami OH': 'Miami (OH)',
         'San Jose State': 'San José State', 'ULM': 'UL Monroe', 'UMass': 'Massachusetts', 'Connecticut': 'UConn'}


def parse_sbd(t):
    heads = [(m.start(), int(m.group(1))) for m in re.finditer(r'(20\d\d) College Football Win Totals</h2>', t)]
    out = {}
    for i, (pos, yr) in enumerate(heads):
        seg = t[pos:heads[i + 1][0] if i + 1 < len(heads) else len(t)]
        for tr in re.findall(r'<tr.*?</tr>', seg, flags=re.S):
            c = [html.unescape(re.sub(r'<[^>]+>', '', x)).strip() for x in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, flags=re.S)]
            if len(c) < 2 or c[0] == 'Team':
                continue
            rest = ' '.join(c[1:]).replace('Even', 'EVEN')
            m = re.match(r'\s*(\d+(?:\.\d)?)', rest)
            if m:
                od = [100 if o == 'EVEN' else int(o) for o in re.findall(r'([+-]\d{3}|EVEN)', rest)][:2]
                out.setdefault(yr, {})[ALIAS.get(c[0], c[0])] = [float(m.group(1))] + od
    return out


def win_totals(path):
    W, N = parse_sbd(open(path).read()), NormalDist()
    dv = lambda a, b: (lambda pa, pb: pa / (pa + pb))(*(100 / (o + 100) if o > 0 else -o / (-o + 100) for o in (a, b)))
    E = {(S, t): v[0] + 1.7 * N.inv_cdf(min(max(dv(v[1], v[2]) if len(v) >= 3 else .5, .05), .95)) for S, tb in W.items() for t, v in tb.items()}
    rows = [r for r in load() if r['S'] in (2018, 2019, 2021, 2022, 2023, 2024, 2025) and r['wk'] <= 2 and r['L'] is not None
            and (r['S'], r['home']) in E and (r['S'], r['away']) in E]
    raw(rows)
    out = {'teams': {S: len(v) for S, v in W.items()}}
    ols = lambda X, y: np.linalg.lstsq(X, y, rcond=None)[0]
    for nm, ss in (('tune', (2018, 2019, 2021)), ('held', (2022, 2023, 2024, 2025))):
        R = [r for r in rows if r['S'] in ss]
        x = np.array([E[(r['S'], r['home'])] - E[(r['S'], r['away'])] for r in R])
        m, y, L = (np.array([r[c] for r in R]) for c in ('m_', 'res', 'L'))
        out[nm] = {'n': len(R), 'res~m+wins': [round(float(v), 3) for v in ols(np.c_[m, x], y)], 'close~m+wins': [round(float(v), 3) for v in ols(np.c_[m, x], L)],
                   'res~close+wins': [round(float(v), 3) for v in ols(np.c_[L, x], y)]}
    return out


def ledger(res):
    led = json.load(open(H.LEDGER))
    models = led['models']
    rows = [r for r in models['cfb_games']['rows'] if not r['term'].startswith('early:')]
    mg, tt = res['margin'], res['total']
    rows.append(H.from_t('early:margin stretch', mg['tune']['mae']['t'], mg['held']['mae']['t'], mg['tune']['mae']['n'], mg['held']['mae']['n'],
                         d_held=-mg['held']['mae']['d'], note='FBS v FBS weeks 1-3 margin and sigma x 1.13 (MAE, weeks 1-4); scripts/cfb_early.py', shipped=True))
    rows.append(H.from_t('early:total shrink', tt['tune']['mae']['t'], tt['held']['mae']['t'], tt['tune']['mae']['n'], tt['held']['mae']['n'],
                         d_held=-tt['held']['mae']['d'], note='weeks 2-6 totals x .75 toward the week mean (MAE); scripts/cfb_early.py', shipped=True))
    models['cfb_games']['rows'] = [{k: v for k, v in r.items() if k not in ('z', 'p', 'q', 'verdict')} for r in rows]
    H.write_ledger(models, pending=led.get('pending'))


def apply_wf():
    rows = load()
    if any('ek' in r or 'tmr' in r for r in rows):
        return print('cfb_early: already applied')
    for r in rows:
        if margin_on(r):
            r['m'] = round(r['m'] * EARLY['k'], 2)
            r['sigma'] = round(r['sigma'] * EARLY['k'], 2)
            r['ek'] = EARLY['k']
    mu = slates(rows, 'tm')
    lo, hi = EARLY['tw']
    n = 0
    for r in rows:
        if r.get('tm') is not None and lo <= r['wk'] <= hi:
            r['tmr'] = r['tm']
            r['tm'] = round(mu[(r['S'], r['wk'])] + EARLY['s'] * (r['tm'] - mu[(r['S'], r['wk'])]), 2)
            n += 1
    with gzip.open(WF, 'wt', encoding='utf-8') as f:
        json.dump(rows, f, separators=(',', ':'), ensure_ascii=False)
    print(f"cfb_early: {sum('ek' in r for r in rows)} margins stretched, {n} totals shrunk")


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--wf':
        apply_wf()
    elif a and a[0] == '--wt':
        print(json.dumps(win_totals(a[1]), indent=1))
    else:
        res = research()
        import datetime
        res['asof'] = datetime.date.today().isoformat()
        old = json.load(open(OUT)) if os.path.exists(OUT) else {}
        res['notShipped'] = old.get('notShipped', {})
        json.dump(res, open(OUT, 'w'), indent=1)
        ledger(res)
        print(json.dumps({k: res[k] for k in ('margin', 'total')}, indent=1))
