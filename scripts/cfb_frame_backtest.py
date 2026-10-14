"""QB frame backtest for frameFV (scripts/fetch_cfb.mjs).

frameFV prices size against drafted QBs at the combine (data/cfb_calibration.json size.QB): -5.7 FV per SD of height
under the 10th percentile (6-1), -5 per SD of weight under 212 lb, a small slope between p10 and p90, all halved.
This tests it the way the badge backtest tests badges: on the board's own universe and inputs, holding production
fixed. Run by hand after scripts/cfb_statplus_backtest.mjs (it reuses that script's cached PFN QB lines and nflverse
picks): python3 scripts/cfb_frame_backtest.py -> data/cfb_frame_backtest.json (needs numpy, pandas).
  universe   each FBS QB's last PFN season 2019-22, outcome weighted NFL AV a season through 2025, undrafted = 0
  size       the college roster listing that season (cfbfastR rosters), as the board reads ESPN's listing
  production FV's blend: 5/4/3 by snaps, regressed with K 3000 weighted snaps, z within the universe
  test       AV ~ production + frame; the frame's AV per FV point against production's (FV gives production about
             4 FV per SD at QB: weight .41 x ~9.8 FV per composite point), so scale = 1 means frameFV is sized right.
             Scored leave one final season out against production alone; 2000 bootstrap draws give the interval.
  step       a flag for a listing under the drafted-QB 10th percentile (212 lb, fixed by the calibration, not
             fitted here), the same way, as FV at production's rate
Result (Oct 14, 2026): the frame passes in direction (t 1.8, a small out-of-sample gain) at about a third of its
size, but nearly all of its evidence is weight, and a step under 212 lb beats the hinge (t -3.2, ~3 FV, out-of-sample
+1.6 points against +0.7). Light QBs are drafted a third as often at the same production. So frameFV is not too harsh
on light QBs; it is kept as it is (42 drafted QBs is too few to refit the shape with confidence).
"""
import json, os, re, subprocess, tempfile
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache', 'statplus')
W = tempfile.mkdtemp()
YEARS = range(2019, 2023)
for y in YEARS:
    subprocess.run(['curl', '-sSLf', '-o', os.path.join(W, f'r{y}.csv'), f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/csv/cfb_rosters_{y}.csv'], check=True)
CAL = json.load(open(os.path.join(ROOT, 'data', 'cfb_calibration.json')))['size']['QB']
H, Wt, HG = CAL['ht'], CAL['wt'], CAL['hinge']
FV_PER_PROD_SD = 4.0

nm = lambda s: re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv)\b', '', re.sub(r'[^a-z ]', '', str(s or '').lower()))).strip()
col = lambda s: nm(s).replace('state', 'st').split(' ')[0]
rows = [r for r in json.load(open(os.path.join(CACHE, 'pfn_QB.json'))) if r['division'] == 'FBS']
cz = {}
for r in rows: cz.setdefault(r['season'], []).append(r['score'])
cz = {s: (np.mean(x), np.std(x)) for s, x in cz.items()}
by = {}
for r in rows:
    r['z'] = (r['score'] - cz[r['season']][0]) / cz[r['season']][1]
    r['v'] = r['snapsQ'] if isinstance(r.get('snapsQ'), (int, float)) else (r.get('gp') or r.get('gamesQ') or 0) * 65
    by.setdefault(r['id'], {})[r['season']] = r
dp = pd.read_csv(os.path.join(CACHE, 'draft_picks.csv'), low_memory=False)
dp = dp[dp.season.between(2020, 2025) & (dp.position == 'QB')]
ros = pd.concat([pd.read_csv(os.path.join(W, f'r{y}.csv'), usecols=['first_name', 'last_name', 'team', 'weight', 'height', 'position', 'season'], low_memory=False) for y in YEARS])
ros = ros[ros.weight.notna() & ros.height.notna() & (ros.position == 'QB')]
ros['k'] = (ros.first_name.astype(str) + ' ' + ros.last_name.astype(str)).map(nm)
rk = {(k, s): g for (k, s), g in ros.groupby(['k', 'season'])}
out = []
for b in by.values():
    last = max(b)
    if last > 2022: continue
    r, D = b[last], last + 1
    cand = dp[dp.pfr_player_name.map(nm) == nm(r['name'])]
    pk = cand[cand.season == D]
    if pk.empty and (cand.season > D).any(): continue   # drafted in a later class: his last PFN line isn't his last season
    num = den = 0
    for k, w in enumerate((5, 4, 3)):
        x = b.get(last - k)
        if x: num += w * x['v'] * x['z']; den += w * x['v']
    g = rk.get((nm(r['name']), last))
    if g is None: continue
    if len(g) > 1:
        g = g[g.team.map(col) == col(r['team'])]
        if len(g) != 1: continue
    ht, wt = float(g.height.iloc[0]), float(g.weight.iloc[0])
    if ht < 66 or wt < 160: continue
    out.append(dict(name=r['name'], last=last, ht=ht, wt=wt, prod=num / (den + 3000), drafted=len(pk) > 0,
                    av=float(pk.w_av.fillna(0).iloc[0]) / (2025 - D + 1) if len(pk) else 0.0))
d = pd.DataFrame(out)
d['pz'] = (d['prod'] - d['prod'].mean()) / d['prod'].std(ddof=0)
# frameFV's pieces, as fetch_cfb.mjs computes them (before its x0.5 and clamp)
d['ht_lo'] = -abs(HG['ht_lo']) * np.maximum(0, H['p10'] - d.ht) / H['sd']
d['ht_mid'] = np.where(d.ht.between(H['p10'], H['p90']), max(0, HG['ht_mid']) * (d.ht - H['p50']) / H['sd'] * 0.5, 0)
d['wt_lo'] = -abs(HG['wt_lo']) * np.maximum(0, Wt['p10'] - d.wt) / Wt['sd']
d['wt_mid'] = np.where(d.wt.between(Wt['p10'], Wt['p90']), max(0, HG['wt_mid']) * (d.wt - Wt['p50']) / Wt['sd'] * 0.5, 0)
d['frame'] = np.clip((d.ht_lo + d.ht_mid + d.wt_lo + d.wt_mid) * 0.5, -8, 3)


def fit(df, cols):
    X = np.c_[np.ones(len(df)), df[cols].values]
    b = np.linalg.lstsq(X, df.av.values, rcond=None)[0]
    res = df.av.values - X @ b
    return b, b / np.sqrt(np.diag(res @ res / (len(df) - X.shape[1]) * np.linalg.inv(X.T @ X)))


def oos(cols):
    e = []
    for s in sorted(d['last'].unique()):
        tr, te = d[d['last'] != s], d[d['last'] == s]
        e += list(te.av.values - np.c_[np.ones(len(te)), te[cols].values] @ fit(tr, cols)[0])
    return 1 - np.mean(np.square(e)) / d.av.var(ddof=0)


scale = lambda b: b[2] / (b[1] / FV_PER_PROD_SD)
base = oos(['pz'])
b, t = fit(d, ['pz', 'frame'])
rng = np.random.default_rng(1)
boot = [scale(fit(d.iloc[rng.integers(0, len(d), len(d))], ['pz', 'frame'])[0]) for _ in range(2000)]
pieces = {}
for c in ('ht_lo', 'ht_mid', 'wt_lo', 'wt_mid'):
    _, tc = fit(d, ['pz', c])
    pieces[c] = {'t': round(float(tc[2]), 2), 'oosGain': round(float(oos(['pz', c]) - base), 4)}
light = d.wt < Wt['p10']
d['light'] = light.astype(float)
bs, ts = fit(d, ['pz', 'light'])
res = {'_readme': __doc__.strip().split('\n\n')[0] + ' See the script header for the method.',
       'n': int(len(d)), 'drafted': int(d.drafted.sum()),
       'frame': {'t': round(float(t[2]), 2), 'oosR2': round(float(oos(['pz', 'frame'])), 4), 'prodOnlyOosR2': round(float(base), 4),
                 'scale': round(float(scale(b)), 2), 'scaleP10P90': [round(float(x), 2) for x in np.percentile(boot, [10, 90])]},
       'pieces': pieces,
       'light': {'n': int(light.sum()), 'avs': round(float(d.av[light].mean()), 2), 'drafted': round(float(d.drafted[light].mean()), 3), 'prodZ': round(float(d.pz[light].mean()), 2),
                 'restAvs': round(float(d.av[~light].mean()), 2), 'restDrafted': round(float(d.drafted[~light].mean()), 3), 'restProdZ': round(float(d.pz[~light].mean()), 2)},
       'step': {'t': round(float(ts[2]), 2), 'fv': round(float(bs[2] / (bs[1] / FV_PER_PROD_SD)), 1), 'oosGain': round(float(oos(['pz', 'light']) - base), 4)},
       'byWeight': [{'lb': str(k), 'n': int(len(g)), 'avs': round(float(g.av.mean()), 2), 'drafted': round(float(g.drafted.mean()), 2), 'prodZ': round(float(g.pz.mean()), 2)}
                    for k, g in d.groupby(pd.cut(d.wt, [0, 200, 206, 212, 218, 225, 400]), observed=True)]}
json.dump(res, open(os.path.join(ROOT, 'data', 'cfb_frame_backtest.json'), 'w'), indent=1)
print(json.dumps(res, indent=1))
