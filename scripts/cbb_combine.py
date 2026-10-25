#!/usr/bin/env python3
"""NBA combine as a stage on the College Basketball ARKBOARD, audit item #15 (Oct 25 2026).

    python3 scripts/cbb_combine.py --fit    # the backtest below -> data/cbb_combine.json (needs /mnt/project-files/cbb/frame)
    live: combine_terms(rows) (fetch_cbb.py, cbb_live.py) reads the committed testing in scripts/data/cbb_combine/*.csv

The Oct 16 research (/mnt/project-files/cbb/measurables-roles-boards.md) passed two combine drivers with the draft pick as
the control: the guard athletic composite (mean z of max vert, standing vert, -lane agility, -3/4 sprint) and big max
vertical reach (standing reach + max vert). The board doesn't control for the pick: its last stage is the draft-board
consensus (cbb_fit.board_stage: the model's E[FV] and the June consensus rank). This re-tests both against that.

Sample: combine invitees whose last Barttorvik season is the combine year (they stayed in the draft), drafts 2009-19
(7+ NBA seasons). Outcome: realized FV on the board's own scale (peak XPM, cbb_fit.xpm_fv). Controls:
  A      production: final-season BPM, OBPM-DBPM, usage, minutes %, recruit score, age at the draft, height, group
  board  A + the June consensus (-ln rank, ESPN + NBADraft.net finals, cbb_fit.june_ranks) and an on-a-board flag:
         the board stage's two inputs, with A standing in for the model's E[FV]
  pick   board + ln pick (the Oct 16 control, now on top of the boards)
Each driver is z-scored within its group (testers only; untested = 0) and enters only for its group. Scored leave one
draft out (RMSE gain) and on 5 blocks of consecutive drafts (the board's 4-of-5 rule), plus a forward split
(fit 2009-14, score 2015-19). Writes data/cbb_combine.json: the kept per-SD effects, the group norms for
z-scores, and the backtest.

Live stage (dormant until a tester is on the board): each kept driver at its per-SD size, z from the committed norms,
capped at 2 SD, added to E[FV] after the board stage. The files are one per combine (combine_YYYY.csv: name, team as
Barttorvik spells them, grp, the raw tests). combine_2026.csv carries this spring's testers forward: the ones who went
back to school are on the 2027 board with their numbers. The 2027 combine (mid-May) goes in combine_2027.csv the same
way, from NBA.com's combine pages or the Kaggle copy (marcusfern/nba-draft-combine), and the next run picks it up.
"""
import json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D
import cbb_fit as F

FRAME = os.environ.get('CBB_FRAME', '/mnt/project-files/cbb/frame')
OUT = os.path.join(D.ROOT, 'data', 'cbb_combine.json')
LIVE_DIR = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_combine')
RAW = ['LPVERT', 'STNDVERT', 'LANE', 'SPRINT', 'STNDRCH']
Y0, Y1 = 2009, 2019
CAP = 2.0          # z cap, as football's FV_ATH


def zcols(d, ref=None):
    import pandas as pd
    """the two drivers, z within group on the testers (ref = the norms to use; None = fit them on d)."""
    d = d.copy()
    d['LANEn'] = -d.LANE; d['SPRINTn'] = -d.SPRINT; d['MAXREACH'] = d.STNDRCH + d.LPVERT
    norms = ref or {}
    for c in ('LPVERT', 'STNDVERT', 'LANEn', 'SPRINTn', 'MAXREACH'):
        for g in ('G', 'W', 'B'):
            if ref is None:
                v = d.loc[d.grp == g, c].dropna()
                norms[f'{c}|{g}'] = [round(float(v.mean()), 4), round(float(v.std()), 4)]
            m, s = norms[f'{c}|{g}']
            d.loc[d.grp == g, 'z_' + c] = ((d.loc[d.grp == g, c] - m) / s)
    ath = d[['z_LPVERT', 'z_STNDVERT', 'z_LANEn', 'z_SPRINTn']]
    d['ath'] = ath.mean(axis=1, skipna=True).where(ath.notna().any(axis=1))
    d['G_ath'] = (d.ath.fillna(0) * (d.grp == 'G')).clip(-CAP, CAP)
    d['B_reach'] = (d.z_MAXREACH.fillna(0) * (d.grp == 'B')).clip(-CAP, CAP)
    return d, norms


def load():
    import pandas as pd
    d = pd.read_csv(os.path.join(FRAME, 'combine_linked.csv'), low_memory=False)
    d = d[d.linked & (d.career_last == d.YEAR) & d.YEAR.between(Y0, Y1) & d.grp.notna()].copy()
    cs = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    thr = F.xpm_scale(cs)
    fv = {c['pid']: F.xpm_fv(c, thr) for c in cs}
    d['fv'] = [fv.get(str(int(p))) if p == p else None for p in d.pid]
    d = d[d.fv.notna()].copy()
    jr = F.june_ranks()
    d['lr'] = [jr.get((int(y), D.norm(n))) for y, n in zip(d.YEAR, d.name)]
    d['on'] = d.lr.notna() * 1.0
    d['lr'] = d.lr.fillna(F.CONS_FILL)
    d['age'] = [(pd.Timestamp(f'{y}-06-25') - pd.Timestamp(b)).days / 365.25 if isinstance(b, str) else np.nan for b, y in zip(d.dob, d.YEAR)]
    d['age'] = d.age.fillna(d.age.mean())
    d['rec'] = d.rec.fillna(0)
    d['lpick'] = np.log(d.nba_pick.where(d.nba_draft == d.YEAR).fillna(75))
    d['obpm_dbpm'] = d.obpm - d.dbpm; d['gW'] = (d.grp == 'W') * 1.0; d['gB'] = (d.grp == 'B') * 1.0
    return d


A = ['bpm', 'obpm_dbpm', 'usg', 'min_per', 'rec', 'age', 'hti', 'gW', 'gB']
CTL = {'A': A, 'board': A + ['lr', 'on'], 'pick': A + ['lr', 'on', 'lpick']}


def X(d, cols): return np.column_stack([np.ones(len(d))] + [d[c].astype(float).fillna(0).to_numpy() for c in cols])


def pred(d, tr, te, cols):
    b, *_ = np.linalg.lstsq(X(d[tr], cols), d.fv[tr].to_numpy(float), rcond=None)
    return X(d[te], cols) @ b


def oos(d, cols):
    y = d.fv.to_numpy(float); yrs = sorted(d.YEAR.unique()); e = np.zeros(len(d))
    for t in yrs:
        te = (d.YEAR == t).to_numpy(); e[te] = y[te] - pred(d, ~te, te, cols)
    fe = []
    for f in np.array_split(yrs, 5):
        te = d.YEAR.isin(f).to_numpy(); fe.append(float(np.mean((y[te] - pred(d, ~te, te, cols)) ** 2)))
    tr = (d.YEAR <= 2014).to_numpy(); fw = float(np.sqrt(np.mean((y[~tr] - pred(d, tr, ~tr, cols)) ** 2)))
    return e, np.array(fe), fw


def coef(d, cols, k):
    Xm = X(d, cols); y = d.fv.to_numpy(float)
    b, *_ = np.linalg.lstsq(Xm, y, rcond=None); r = y - Xm @ b
    # clustered by draft
    B = np.linalg.pinv(Xm.T @ Xm); meat = np.zeros((Xm.shape[1],) * 2)
    for t in d.YEAR.unique():
        i = (d.YEAR == t).to_numpy(); s = Xm[i].T @ r[i]; meat += np.outer(s, s)
    G = d.YEAR.nunique(); se = np.sqrt(np.diag(G / (G - 1) * B @ meat @ B))
    j = 1 + cols.index(k)
    return float(b[j]), float(b[j] / se[j])


def main():
    import pandas as pd
    d0 = load()
    d, norms = zcols(d0)
    print(f'sample {len(d)} ({d.grp.value_counts().to_dict()}), on a June board {int(d.on.sum())}, guards tested {int(((d.grp == "G") & d.ath.notna()).sum())}, bigs with reach {int(((d.grp == "B") & d.z_MAXREACH.notna()).sum())}')
    res = {'sample': int(len(d)), 'drafts': f'{Y0}-{Y1}', 'outcome': 'realized FV (peak XPM scale)', 'tests': []}
    for ctl, base in CTL.items():
        e0, f0, w0 = oos(d, base)
        for drv in (['G_ath'], ['B_reach'], ['G_ath', 'B_reach']):
            e1, f1, w1 = oos(d, base + drv)
            r0, r1 = math.sqrt(np.mean(e0 ** 2)), math.sqrt(np.mean(e1 ** 2))
            g = e0 ** 2 - e1 ** 2
            t = {k: [round(v, 3) for v in coef(d, base + drv, k)] for k in drv}
            row = {'control': ctl, 'drivers': drv, 'perSd_t': t, 'oosGainPct': round(100 * (r0 - r1) / r0, 2),
                   'tRow': round(float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))), 2), 'folds': int((f1 < f0).sum()),
                   'forwardGainPct': round(100 * (w0 - w1) / w0, 2)}
            res['tests'].append(row); print(row)
    pick = next(r for r in res['tests'] if r['control'] == 'board' and r['drivers'] == ['G_ath', 'B_reach'])
    alone = {k: next(r for r in res['tests'] if r['control'] == 'board' and r['drivers'] == [k]) for k in ('G_ath', 'B_reach')}
    kept = [k for k, r in alone.items() if r['folds'] >= 4 and r['oosGainPct'] > 0 and r['forwardGainPct'] > 0 and r['perSd_t'][k][0] > 0]
    keep = {k: round(coef(d, CTL['board'] + kept, k)[0], 3) for k in kept}
    res.update({'keep': keep, 'cap': CAP, 'norms': norms,
                'rule': 'each driver alone on control board: OOS gain > 0, 4+ of 5 folds, forward gain > 0; size from the fit of the kept'})
    # the testers to carry forward: this spring's combine, linked to Barttorvik
    raw = pd.read_csv(os.path.join(FRAME, 'combine_linked.csv'), low_memory=False)
    cur = raw[raw.linked & (raw.YEAR == raw.YEAR.max()) & raw.grp.notna()]
    os.makedirs(LIVE_DIR, exist_ok=True)
    cur[['YEAR', 'name', 'team', 'grp'] + RAW].rename(columns={'YEAR': 'year'}).to_csv(
        os.path.join(LIVE_DIR, f'combine_{int(raw.YEAR.max())}.csv'), index=False)
    print('kept (FV per SD):', keep)
    json.dump(res, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


# ---------------------------------------------------------------- live
def combine_terms(names_teams, pos=None):
    """E[FV] added for each (name, team) by the kept combine drivers: (term, z) or None for a player with no testing.
    pos: the board's G/F/C, for a combine file without the tester's group (a guard = G)."""
    import csv, glob
    import names as N
    try: fit = json.load(open(OUT))
    except OSError: return [None] * len(names_teams)
    if not fit.get('keep'): return [None] * len(names_teams)
    rows = []
    for p in sorted(glob.glob(os.path.join(LIVE_DIR, 'combine_*.csv'))):
        with open(p, newline='', encoding='utf-8') as fh: rows += list(csv.DictReader(fh))
    rows.sort(key=lambda r: -int(r['year']))          # a player's latest combine first
    idx = N.Matcher(rows, name='name', team='team', pos=None, sport='basketball')
    nm = fit['norms']; out = []
    for j, (n, t) in enumerate(names_teams):
        r = idx.find(n, t)[0]
        if r is None: out.append(None); continue
        g = r.get('grp') or {'G': 'G', 'C': 'B'}.get((pos or [None] * len(names_teams))[j], 'W')
        val = lambda c: float(r[c]) if r.get(c) not in (None, '') else None
        x = {'LPVERT': val('LPVERT'), 'STNDVERT': val('STNDVERT'), 'LANEn': -val('LANE') if val('LANE') is not None else None,
             'SPRINTn': -val('SPRINT') if val('SPRINT') is not None else None,
             'MAXREACH': val('STNDRCH') + val('LPVERT') if val('STNDRCH') is not None and val('LPVERT') is not None else None}
        z = {c: (v - nm[f'{c}|{g}'][0]) / nm[f'{c}|{g}'][1] for c, v in x.items() if v is not None}
        ath = [z[c] for c in ('LPVERT', 'STNDVERT', 'LANEn', 'SPRINTn') if c in z]
        zz = {'G_ath': float(np.mean(ath)) if g == 'G' and ath else None, 'B_reach': z.get('MAXREACH') if g == 'B' else None}
        terms = [(k, max(-CAP, min(CAP, zz[k]))) for k in fit['keep'] if zz.get(k) is not None]
        out.append((sum(fit['keep'][k] * v for k, v in terms), terms[0][1]) if terms else None)
    return out


if __name__ == '__main__':
    if '--fit' in sys.argv: main()
    else: sys.exit(__doc__)
