#!/usr/bin/env python3
"""Censoring check for the conviction mock (scripts/cbb_mock.py fit_conv), audit item #18 (Oct 25 2026).

fit_conv regresses peak NBA XPM (best three seasons) on the slot, 3-season BPM and age over the 2009-23 drafts. The
2021-23 picks have had 3-5 NBA seasons, so their "peak" is a partial career, and a partial career punishes the young
(they peak later): the age penalty is fit on a target that is short for exactly the players it penalises.

Candidates, each fit leave-one-draft-out and scored on the drafts whose careers are long enough to call (2009-18,
8+ NBA seasons) against the full-career peak:
  all        2009-23 drafts, career peak to date (the live fit)
  drop       2009-20 drafts only (6+ seasons), career peak
  horizon H  2009-(2026-H) drafts, best three of NBA seasons 1..H (a common horizon: every draft observed as long)
Scores: RMSE of peak XPM centred within the draft, and the redraft slot error, mean |ln conviction slot - ln redraft
slot| within each held-out draft (redraft = order of realized peak; the conviction slot = order of the prediction).
Standard errors clustered by draft (players in one draft share its depth and its era).

    python3 scripts/cbb_conv_backtest.py          # writes scripts/data/cbb_conv_backtest.json
"""
import glob, json, math, os, sys
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_mock as M

KIT = os.environ.get('CBB_KIT', '/mnt/project-files/cbb/kit')
OUT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_conv_backtest.json')
LAST_SEASON = 2026
SCORE = range(2009, 2019)


def xpm_seasons():
    """bref id -> {NBA season: shrunk XPM}, built as cbb_careers_kit.py builds peakXpm (.5 BPM + .5 DPM, BPM alone
    with no DPM row, shrunk to -2 by 500 minutes)."""
    nba = defaultdict(list)
    for s in json.load(open(f'{KIT}/bbref_nba_seasons.json')): nba[s['bref']].append(s)
    by_ns = {(D.norm(x['name']), x['year']): b for b, ss in nba.items() for x in ss}
    dpm = defaultdict(dict)
    for p in glob.glob(f'{KIT}/dpm/*.json'):
        for x in json.load(open(p)):
            b = by_ns.get((D.norm(x['name']), x['season']))
            if b: dpm[b][x['season']] = x['dpm']
    out = {}
    for b, ss in nba.items():
        out[b] = {s['year']: (s['mp'] * (0.5 * s['bpm'] + 0.5 * dpm[b][s['year']] if s['year'] in dpm[b] else s['bpm']) - 1000.0) / (s['mp'] + 500)
                  for s in ss if s['bpm'] is not None}
    return out


def best3(vals):
    v = sorted(vals, reverse=True) + [-2.5] * 3
    return sum(v[:3]) / 3


def rows_with_targets():
    past = M.past_boards()
    rows = M.conv_rows(past, (2009, 2023))
    cs = {c['name'] + '|' + str((c['nba'] or {}).get('draft')): c for c in json.load(open(os.path.join(D.CACHE, 'careers.json')))}
    xs = xpm_seasons()
    for r in rows:
        c = cs.get(r['name'] + '|' + str(r['year']))
        b = ((c or {}).get('nba') or {}).get('bref')
        sv = xs.get(b, {})
        r['peak'] = r['y']
        r['h'] = {H: best3([v for y, v in sv.items() if r['year'] < y <= r['year'] + H]) for H in (3, 4, 5, 6, 7)}
    return rows


def clustered(X, y, g):
    """OLS with standard errors clustered by g (CR1)."""
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    B = np.linalg.pinv(X.T @ X)
    G = sorted(set(g)); n, k = X.shape
    meat = np.zeros((k, k))
    for c in G:
        i = g == c
        s = X[i].T @ e[i]; meat += np.outer(s, s)
    adj = len(G) / (len(G) - 1) * (n - 1) / (n - k)
    se = np.sqrt(np.diag(adj * B @ meat @ B))
    return b, se


def centred(rows, key):
    by = defaultdict(list)
    for r in rows: by[r['year']].append(key(r))
    m = {y: np.mean(v) for y, v in by.items()}
    return np.array([key(r) - m[r['year']] for r in rows])


def ranks(v, desc=True):
    o = np.argsort(-np.asarray(v) if desc else np.asarray(v), kind='stable')
    r = np.empty(len(v)); r[o] = np.arange(1, len(v) + 1)
    return r


FULL = 2016    # drafts with 10 NBA seasons: their peak is the career's


def impute(rows, cols, skip=None):
    """career peak for the drafts still running: E[peak | best three of the seasons seen so far (+ cols)], one OLS per
    horizon on the drafts through FULL (minus the held-out draft); a draft with 8+ seasons keeps its own peak."""
    out = {}
    fit = [r for r in rows if r['year'] <= FULL and r['year'] != skip]
    mean = {c: float(np.mean([r['f'][c] for r in fit if r['f'][c] is not None])) for c in cols}
    x = lambda r, H: [1, r['h'][H]] + [r['f'][c] if r['f'][c] is not None else mean[c] for c in cols]
    for H in (3, 4, 5, 6, 7):
        out[H] = np.linalg.lstsq(np.array([x(r, H) for r in fit]), np.array([r['peak'] for r in fit]), rcond=None)[0]
    def tg(r):
        H = LAST_SEASON - r['year']
        if H >= 8: return r['peak']
        return max(r['peak'], float(np.array(x(r, H)) @ out[H]))
    return tg


def evaluate(rows, feats, train_years, target):
    """fit on train_years minus the held-out draft, predict each scored draft; returns per-draft (sq err, slot err).
    target is a function of a row, or ('impute', cols): refit per held-out draft."""
    truth = centred(rows, lambda r: r['peak'])
    per = {}
    for t in SCORE:
        yc = centred(rows, impute(rows, target[1], t) if isinstance(target, tuple) else target)
        tr = [i for i, r in enumerate(rows) if r['year'] in train_years and r['year'] != t]
        te = [i for i, r in enumerate(rows) if r['year'] == t]
        X, mu, sd = M.design([rows[i] for i in tr], feats)
        b, *_ = np.linalg.lstsq(X, yc[tr], rcond=None)
        Xt, _, _ = M.design([rows[i] for i in te], feats, mu, sd)
        p = Xt @ b
        se = (truth[te] - (p - p.mean())) ** 2
        slot = float(np.mean(np.abs(np.log(ranks(p)) - np.log(ranks(truth[te])))))
        per[t] = (se, slot)
    return per


def summary(per, base=None):
    se = np.concatenate([per[t][0] for t in SCORE])
    out = {'rmse': round(float(np.sqrt(se.mean())), 4), 'slotErr': round(float(np.mean([per[t][1] for t in SCORE])), 4)}
    if base:
        d = np.concatenate([base[t][0] - per[t][0] for t in SCORE])          # per-row squared-error gain
        dd = np.array([base[t][1] - per[t][1] for t in SCORE])                # per-draft slot gain
        # draft-clustered t on the squared-error gain: one mean per draft
        md = np.array([float((base[t][0] - per[t][0]).mean()) for t in SCORE])
        out.update({'rmseGain': round(float(np.sqrt(np.concatenate([base[t][0] for t in SCORE]).mean())) - out['rmse'], 4),
                    'tRow': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                    'tDraft': round(float(md.mean() / (md.std(ddof=1) / math.sqrt(len(md)))), 2),
                    'draftsBetter': int(sum(base[t][0].mean() > per[t][0].mean() + 1e-12 for t in SCORE)),
                    'slotGain': round(float(dd.mean()), 4), 'tSlot': round(float(dd.mean() / (dd.std(ddof=1) / math.sqrt(len(dd)))), 2),
                    'draftsSlotBetter': int(sum(x > 1e-12 for x in dd)), 'of': len(SCORE)})
    return out


def main():
    rows = rows_with_targets()
    print(len(rows), 'drafted college players 2009-23')
    cands = {'all': (range(2009, 2024), lambda r: r['peak']), 'drop': (range(2009, 2021), lambda r: r['peak'])}
    for H in (3, 4, 5, 6):
        cands[f'horizon{H}'] = (range(2009, LAST_SEASON - H + 1), lambda r, H=H: r['h'][H])
    cands['impute'] = (range(2009, 2024), ('impute', []))
    cands['impute+age'] = (range(2009, 2024), ('impute', ['age']))
    res = {'n': len(rows), 'scored': f'{SCORE[0]}-{SCORE[-1]}', 'sets': {}}
    for name, feats in (('live', ['lnpick', 'bpm3', 'age']), ('slot', ['lnpick'])):
        base = evaluate(rows, feats, *cands['all'])
        res['sets'][name] = {'feats': feats, 'cands': {}}
        for c, (yrs, tg) in cands.items():
            per = evaluate(rows, feats, yrs, tg)
            s = summary(per, base if c != 'all' else None)
            yrs = list(yrs)
            ix = [i for i, r in enumerate(rows) if r['year'] in yrs]
            if isinstance(tg, tuple): tg = impute(rows, tg[1])
            X, _, _ = M.design([rows[i] for i in ix], feats)
            b, se = clustered(X, centred([rows[i] for i in ix], tg), np.array([rows[i]['year'] for i in ix]))
            _, se0 = M.ols(X, centred([rows[i] for i in ix], tg))
            s['drafts'] = f'{yrs[0]}-{yrs[-1]}'
            s['coef'] = [{'key': k, 'perSd': round(float(b[i + 1]), 3), 'tCluster': round(float(b[i + 1] / se[i + 1]), 2),
                          'tIid': round(float(b[i + 1] / se0[i + 1]), 2)} for i, k in enumerate(feats)]
            res['sets'][name]['cands'][c] = s
            print(name, c, s)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()
