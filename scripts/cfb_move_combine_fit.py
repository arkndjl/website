"""Combine measurements in the position-change flag: fit on where the NFL used college players, 2020-26 combines.

The board's flag (fetch_cfb.mjs, "position fit") reads listed size, projected to 22, and production. When the draft
year's combine posts (late February), measured height and weight replace the listing and the testing (40, vertical,
broad, 3-cone, shuttle) can say whether he moves like the spot he'd move to. This scores each step against the NFL
outcome, so only what holds out of sample goes live. Run by hand after
  node scripts/cfb_move_backtest.mjs --rows scripts/.cache/vers/move_rows.json
  python3 scripts/cfb_move_combine_fit.py -> data/cfb_move_combine_fit.json (needs numpy, pandas)

  rows      every college player at a 2020-26 combine with 100+ snaps in his last PFN season, for each move the
            board can flag that the NFL made at least once (DL-EDGE, EDGE-DL, EDGE-LB, WR-TE, QB-ATH, S-LB, S-CB, CB-S,
            OT-IOL; LB-EDGE can't be scored, see the move backtest). Outcome: the NFL depth-chart spot
  listed    the flag at his ESPN listing (what the board shows before the combine)
  measured  the same rules at combine height and weight
  athFit    how much closer his testing sits to the new spot's NFL invitees than to his own spot's: for each drill,
            |z at his spot| - |z at the new spot| (z against 2010-25 invitees at each spot), averaged over 2+ drills
  sizeFit   the same for measured height and weight, as a continuous version of the size gates
  hist      college history at the new spot: graded there by PFN (100+ snaps in a season) or recruited there (247)
  model     logistic, intercept per move shrunk to a common one (ridge), scored leaving one combine year out:
            log loss, Brier, AUC, and the flag at P >= .5 (right / flagged, and moves found)
Result (Oct 14, 2026; 1,108 player-moves, 57 NFL moves):
  rules at the listing          37 flags, 17 right                                 (the board until now)
  listing + size fit + history  log loss .170 -> .140, AUC .79 -> .90, 19 flags, 13 right   (live before the combine)
  rules at combine size         log loss .151, AUC .84, 35 flags, 23 right
  combine size + fit + history  log loss .130, AUC .93, 28 flags, 17 right          (live once the combine posts)
  + athletic testing            t 1.6 once size is in, log loss .1300 -> .1308: left out
Size fit t 5-7, college history at the new spot t 2.1-2.3 (versatility does predict where the NFL plays him, even
though it doesn't predict how well: scripts/cfb_versatility_backtest.py). Arm length isn't in public combine data.
"""
import json, os, re, glob, math
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SP, VC = (os.path.join(ROOT, 'scripts', '.cache', d) for d in ('statplus', 'vers'))
OUT = os.path.join(ROOT, 'data', 'cfb_move_combine_fit.json')
rows = json.load(open(os.path.join(VC, 'move_rows.json')))
MOVES = [('DL', 'EDGE'), ('EDGE', 'DL'), ('EDGE', 'LB'), ('WR', 'TE'), ('QB', 'ATH'), ('S', 'LB'), ('S', 'CB'), ('CB', 'S'), ('OT', 'IOL')]
DRILLS = ['forty', 'vert', 'broad', 'cone', 'shuttle']

nm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', re.sub(r'[^a-z ]', '', str(s or '').lower()))).strip()
school = lambda s: re.sub(r'\buniversity\b|\bof\b', '', nm(s).replace('state', 'st')).strip().split(' ')[0] if s else ''

# ---- NFL spot norms: 2010-25 combine invitees at each spot (2020-21 lumped DE/DT as DL and edges as LB: left out) ----
cb = pd.read_csv(os.path.join(SP, 'combine.csv'), low_memory=False)
cb = cb[cb.season.between(2010, 2025)].copy()
SPOT = dict(QB='QB', RB='RB', FB='RB', WR='WR', TE='TE', OT='OT', T='OT', OG='IOL', G='IOL', C='IOL', DE='EDGE', EDGE='EDGE', DT='DL', NT='DL',
            ILB='LB', MLB='LB', CB='CB', S='S', SAF='S', FS='S', SS='S')
cb['spot'] = cb.pos.map(SPOT)
cb.loc[cb.season.between(2020, 2021) & cb.pos.isin(['LB', 'DL']), 'spot'] = None
cb.loc[(cb.season < 2020) & (cb.pos == 'LB'), 'spot'] = 'LB'
cb['ht_in'] = cb.ht.astype(str).str.extract(r'^(\d+)-(\d+)').astype(float).pipe(lambda x: 12 * x[0] + x[1])
cb = cb.rename(columns={'vertical': 'vert', 'broad_jump': 'broad'})
NORM = {}
for sp, g in cb[cb.spot.notna()].groupby('spot'):
    NORM[sp] = {m: [round(float(g[c].mean()), 3), round(float(g[c].std()), 3)] for m, c in [('ht', 'ht_in'), ('wt', 'wt')] + [(d, d) for d in DRILLS] if g[c].notna().sum() >= 30}
FROM = dict(DL='DL', EDGE='EDGE', WR='WR', QB='QB', S='S', CB='CB', OT='OT')

def fit_gap(vals, a, b, keys, need):
    """mean over keys of |z at a| - |z at b|: positive = closer to b's invitees"""
    zs = [abs((vals[k] - NORM[a][k][0]) / NORM[a][k][1]) - abs((vals[k] - NORM[b][k][0]) / NORM[b][k][1])
          for k in keys if vals.get(k) is not None and k in NORM.get(a, {}) and k in NORM.get(b, {})]
    return float(np.mean(zs)) if len(zs) >= need else None

# ---- college history at the new spot: PFN grade there (100+ snaps), or recruited there (247 composite) ----------------
SPG = dict(QB=65, RB=30, WR=40, TE=40, OL=65, EDGE=50, DL=45, LB=55, CB=55, S=55)
vol = lambda g, r: next((r[k] for k in ('snapsQ', 'snaps') if isinstance(r.get(k), (int, float))), None) or (r.get('gp') or r.get('gamesQ') or 0) * SPG[g]
pfn_hist = {}
for g in SPG:
    for r in json.load(open(os.path.join(SP, f'pfn_{g}.json'))):
        if r['division'] == 'FBS' and vol(g, r) >= 100: pfn_hist.setdefault((nm(r['name']), school(r['team'])), set()).add((g, r['season']))
HS_AT = dict(EDGE={'WDE', 'EDGE'}, DL={'DT'}, LB={'ILB', 'OLB', 'LB'}, TE={'TE'}, CB={'CB'}, S={'S'}, IOL={'OG', 'OC', 'IOL'}, ATH={'ATH', 'RB', 'APB', 'WR'})
hs = {}
for f in sorted(glob.glob(os.path.join(VC, 'c247_*.html'))):
    for x in open(f, encoding='utf8', errors='ignore').read().split('rankings-page__list-item"')[1:]:
        n = re.search(r'name-link"[^>]*>([^<]*)', x); pos = re.search(r'class="position">\s*([^<]*?)\s*</div>', x)
        sc = re.search(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"', x)
        if n and pos: hs.setdefault(nm(n.group(1)), []).append((pos.group(1).strip(), school(sc.group(1)) if sc else ''))
def history(r, to):
    k = (nm(r['name']), school(r['team']))
    pf = any(g == to and s < r['season'] + 1 for g, s in pfn_hist.get(k, ()))
    c = hs.get(k[0], []); m = [p for p, s in c if s == k[1]] or ([c[0][0]] if len(c) == 1 else [])
    return int(pf or (bool(m) and m[0] in HS_AT.get(to, ())))

# ---- the design -------------------------------------------------------------------------------------------------------
moved = lambda r, to: (r['at'] != 'QB') if to == 'ATH' else r['at'] == to
D = []
for r in rows:
    if r['at'] == 'DL?': continue
    for a, to in MOVES:
        if r['g'] != a: continue
        cm = dict(r['cm'], ht=r['ht'], wt=r['wt'])
        dest = to if to != 'ATH' else None
        D.append(dict(move=f'{a}-{to}', year=r['combine'], name=r['name'], y=int(moved(r, to)),
                      listed=None if r.get('flagListed', None) is None and 'flagListed' not in r else int(r.get('flagListed') == to),
                      measured=int(r['flag'] == to),
                      ath=fit_gap(cm, FROM[a], dest, DRILLS, 2) if dest else None,
                      size=fit_gap(cm, FROM[a], dest, ['ht', 'wt'], 2) if dest else None,
                      lsize=fit_gap(dict(ht=r['lht'], wt=r['lwt']), FROM[a], dest, ['ht', 'wt'], 2) if dest and r.get('lht') else None,
                      hist=history(r, to)))
d = pd.DataFrame(D)
cov = dict(rows=len(d), moves=int(d.y.sum()), listed=int(d.listed.notna().sum()), ath=int(d.ath.notna().sum()))
d['ath0'] = d.ath.fillna(0.0); d['size0'] = d['size'].fillna(0.0); d['lsize0'] = d.lsize.fillna(0.0)

def logit_fit(X, M, y, lam=1.0):
    """logistic: global intercept + per-move intercepts (ridge lam) + features (ridge lam / 10)"""
    Z = np.column_stack([np.ones(len(X)), M, X]); w = np.zeros(Z.shape[1])
    pen = np.r_[0, np.full(M.shape[1], lam), np.full(X.shape[1], lam / 10)]
    for _ in range(50):
        p = 1 / (1 + np.exp(-Z @ w)); g = Z.T @ (p - y) + pen * w
        H = Z.T @ (Z * (p * (1 - p))[:, None]) + np.diag(pen + 1e-9); step = np.linalg.solve(H, g); w -= step
        if np.abs(step).max() < 1e-8: break
    return w
def auc(p, y):
    o = np.argsort(p); r = np.empty(len(p)); r[o] = np.arange(1, len(p) + 1)
    n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None
MV = sorted(d.move.unique())
mdum = lambda S: np.column_stack([(S.move == m).astype(float) for m in MV])
def score(S, feats):
    P = np.zeros(len(S))
    for yr in sorted(S.year.unique()):
        tr, te = S.year != yr, S.year == yr
        w = logit_fit(S.loc[tr, feats].values.astype(float), mdum(S[tr]), S.y[tr].values.astype(float))
        Z = np.column_stack([np.ones(te.sum()), mdum(S[te]), S.loc[te, feats].values.astype(float)])
        P[te.values] = 1 / (1 + np.exp(-Z @ w))
    y = S.y.values; P = np.clip(P, 1e-4, 1 - 1e-4)
    fl = P >= 0.5
    w = logit_fit(S[feats].values.astype(float), mdum(S), y.astype(float))
    # t from the observed information at the full fit
    Z = np.column_stack([np.ones(len(S)), mdum(S), S[feats].values.astype(float)]); p = 1 / (1 + np.exp(-Z @ w))
    cov_ = np.linalg.inv(Z.T @ (Z * (p * (1 - p))[:, None]) + np.diag(np.r_[0, np.full(len(MV), 1.0), np.full(len(feats), 0.1)]))
    k0 = 1 + len(MV)
    return dict(n=int(len(S)), moves=int(y.sum()), logloss=round(float(-np.mean(y * np.log(P) + (1 - y) * np.log(1 - P))), 4),
                brier=round(float(np.mean((P - y) ** 2)), 5), auc=round(auc(P, y), 3), flagged=int(fl.sum()), right=int((fl & (y == 1)).sum()),
                cuts={str(c): [int((P >= c).sum()), int(((P >= c) & (y == 1)).sum())] for c in (0.3, 0.35, 0.4, 0.45, 0.5, 0.6)},
                byMove={m: [int((fl & (S.move == m).values).sum()), int((fl & (y == 1) & (S.move == m).values).sum()), int(((y == 1) & (S.move == m).values).sum())] for m in MV},
                coef={f: dict(b=round(float(w[k0 + i]), 3), t=round(float(w[k0 + i] / math.sqrt(cov_[k0 + i, k0 + i])), 2)) for i, f in enumerate(feats)},
                intercepts={m: round(float(w[0] + w[1 + i]), 3) for i, m in enumerate(MV)})
S = d[d.listed.notna()].copy()
S['listed'] = S.listed.astype(int)
models = dict(listed=['listed'], listed_size=['listed', 'lsize0'], listed_hist=['listed', 'hist'], listed_size_hist=['listed', 'lsize0', 'hist'],
              measured=['measured'], measured_size_hist=['measured', 'size0', 'hist'], measured_size_hist_ath=['measured', 'size0', 'hist', 'ath0'], measured_ath=['measured', 'ath0'], measured_size=['measured', 'size0'],
              measured_ath_size=['measured', 'ath0', 'size0'], measured_hist=['measured', 'hist'], measured_ath_hist=['measured', 'ath0', 'hist'])
res = {k: score(S, f) for k, f in models.items()}
# testers only (the athletic term can't help a player who skipped the drills)
T = S[S.ath.notna()].copy()
res_t = {k: score(T, f) for k, f in dict(measured=['measured'], measured_ath=['measured', 'ath0']).items()}
out = dict(asof=pd.Timestamp.today().strftime('%Y-%m-%d'), method='see scripts/cfb_move_combine_fit.py', coverage=cov, models=res, testers=res_t,
           norms=NORM, moves=[f'{a}-{b}' for a, b in MOVES])
# what the board runs (fetch_cfb.mjs, position fit): before the combine the listed-size model, after it the measured
# one; the athletic term is left out (it adds nothing once size is in: t 1.6, out-of-sample log loss worse)
live = lambda m: dict(a=m['intercepts'], b=dict(flag=m['coef'][next(k for k in m['coef'] if k in ('listed', 'measured'))]['b'],
                                                size=m['coef'][next(k for k in m['coef'] if 'size' in k)]['b'], hist=m['coef']['hist']['b']))
out['live'] = dict(pre=live(res['listed_size_hist']), post=live(res['measured_size_hist']), cut=0.5, also=0.25, hsAt={k: sorted(v) for k, v in HS_AT.items()},
                   targets={a: [b for x, b in MOVES if x == a] for a in dict.fromkeys(a for a, _ in MOVES)}, from_=FROM)
# per move: listed vs measured flags
out['byMove'] = {m: dict(moves=int(g.y.sum()), listedFlags=int(g.listed.sum()), listedRight=int((g.listed & g.y).sum()),
                         measuredFlags=int(g.measured.sum()), measuredRight=int((g.measured & g.y).sum()),
                         athMoved=round(float(g[g.y == 1].ath.mean()), 2) if g[g.y == 1].ath.notna().any() else None,
                         athStayed=round(float(g[g.y == 0].ath.mean()), 2) if g[g.y == 0].ath.notna().any() else None) for m, g in S.groupby('move')}
json.dump(out, open(OUT, 'w'), indent=1)
print(json.dumps(cov))
for k, v in res.items(): print(k.ljust(18), {x: v[x] for x in ('logloss', 'brier', 'auc', 'flagged', 'right')}, v['coef'])
for k, v in res_t.items(): print('testers', k.ljust(10), {x: v[x] for x in ('n', 'moves', 'logloss', 'brier', 'auc', 'flagged', 'right')}, v['coef'])
print(json.dumps(out['byMove'], indent=0))
