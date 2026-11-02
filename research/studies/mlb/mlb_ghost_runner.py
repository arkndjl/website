"""Study mlb-ghost-runner: extra-inning runner on 2nd; home edge and leadoff bunt vs swing away."""
import importlib.util, json, numpy as np, pandas as pd
spec = importlib.util.spec_from_file_location("c", "/home/user/website/research/studies/mlb/mlb_common.py"); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
d = c.load()
d = d[~d.dh7].copy()
q, lg = c.batter_quality(d)
# ---- home win % in extra-inning games
ex = d[d.inning >= 10].groupby('gid').agg(season=('season', 'first'), hw=('home_win', 'first'))
ex9 = d[d.inning <= 9].groupby('gid').agg(season=('season', 'first'), hw=('home_win', 'first'))
for nm, m in [('2015-19', ex.season < 2020), ('2020-25', ex.season >= 2020)]:
    z = ex[m]; print('extras', nm, len(z), round(z.hw.mean(), 4), c.wilson(z.hw.sum(), len(z)))
print('all games home win', ex9.groupby(ex9.season >= 2020).hw.mean())
print(ex.groupby('season').hw.agg(['mean', 'size']))
# ---- leadoff PA of each extra half-inning, ghost era
d['pa_id'] = d.groupby('gid').pa.cumsum() - d.pa
g = d[d.ghost].copy()
g['first_pa'] = g.groupby('half').pa_id.transform('min')
lead = g[g.pa_id == g.first_pa]
st = lead.groupby('half').first()  # state at start of half
pa = lead.groupby('half').agg(bunt=('bunt', 'max'), pitches=('pitches', lambda s: ''.join(s.fillna('').astype(str))),
                               batter=('batter', 'last'), bat_f=('bat_f', 'last'), sh=('sh', 'max'))
st = st.join(pa, rsuffix='_pa')
st = st[(st.bases == 2) & (st.outs_pre == 0)]
st['bunt_att'] = ((st.bunt_pa == 1) | st.pitches_pa.str.contains('[LMO]', regex=True)).astype(int)
st['q'] = q.reindex(pd.MultiIndex.from_arrays([st.season, st.batter_pa])).values - lg
st['scored'] = (st.runs_half > 0).astype(int)
st['bat_win'] = np.where(st.home_bat == 1, st.home_win, 1 - st.home_win)
st['tied'] = st.diff_home == 0
st = st[st.bat_f_pa != 1]  # no pitchers batting
print(st.groupby(['home_bat', 'tied', 'bunt_att']).agg(n=('scored', 'size'), scored=('scored', 'mean'), runs=('runs_half', 'mean'), win=('bat_win', 'mean'), q=('q', 'mean')))
print(st.groupby('season').bunt_att.mean())
st.to_pickle(c.SCRATCH + '/ghost.pkl')

# ---- batter-quality adjusted bunt effect (linear probability / OLS with season FE), bootstrap by game
def adj_diff(z, yc, B=1000, seed=1):
    def fit(zz):
        X = np.column_stack([np.ones(len(zz)), zz.bunt_att, zz.q] + [(zz.season == y).astype(float) for y in range(2021, 2026)])
        return np.linalg.lstsq(X, zz[yc].values.astype(float), rcond=None)[0][1]
    est = fit(z)
    rng = np.random.default_rng(seed)
    games = z.gid.unique(); gi = {g: z.index[z.gid == g] for g in games}
    bs = []
    zz = z.reset_index()
    idx_by_g = zz.groupby('gid').indices
    keys = list(idx_by_g)
    for _ in range(B):
        pick = rng.integers(0, len(keys), len(keys))
        rows = np.concatenate([idx_by_g[keys[i]] for i in pick])
        bs.append(fit(zz.iloc[rows]))
    return est, np.percentile(bs, 2.5), np.percentile(bs, 97.5)
R = {}
for half, lab in [(0, 'top'), (1, 'bottom')]:
    z = st[(st.home_bat == half) & st.tied]
    for yc in ['scored', 'runs_half', 'bat_win']:
        R[(lab, yc)] = adj_diff(z, yc)
        print(lab, yc, np.round(R[(lab, yc)], 4))
# split: 2020-22 vs 2023-25 win effect
SP = {}
for nm, yrs in [('2020-22', [2020, 2021, 2022]), ('2023-25', [2023, 2024, 2025])]:
    for half, lab in [(0, 'top'), (1, 'bottom')]:
        z = st[(st.home_bat == half) & st.tied & st.season.isin(yrs)]
        zz = z.groupby('bunt_att').bat_win.mean()
        SP[(nm, lab)] = zz[1] - zz[0]
print(SP)

# ---- JSON
pre = ex[ex.season < 2020]; post = ex[ex.season >= 2020]
plo, phi = c.wilson(post.hw.sum(), len(post)); qlo, qhi = c.wilson(pre.hw.sum(), len(pre))
pts = {0: [], 1: []}
for half, lab in [(0, 'top'), (1, 'bottom')]:
    for yc, yl in [('scored', 'scored'), ('bat_win', 'won')]:
        for b in [0, 1]:
            z = st[(st.home_bat == half) & st.tied & (st.bunt_att == b)]
            lo, hi = c.wilson(z[yc].sum(), len(z))
            pts[b].append({'x': f'{lab}: {yl}', 'y': round(z[yc].mean(), 3), 'lo': round(lo, 3), 'hi': round(hi, 3), 'n': int(len(z))})
tw, bw, ts, bs_ = R[('top', 'bat_win')], R[('bottom', 'bat_win')], R[('top', 'scored')], R[('bottom', 'scored')]
tr = R[('top', 'runs_half')]
pp = lambda t: f"{t[0]*100:+.1f} pts (CI {t[1]*100:+.1f} to {t[2]*100:+.1f})"
n_main = int(st.tied.sum())
out = {
    "id": "mlb-ghost-runner", "sport": "MLB",
    "question": "With the extra-inning runner on 2nd, does bunting him to 3rd pay, and has the home edge changed?",
    "answer": f"No measurable edge either way; visitors' bunts {tr[0]:+.2f} runs (CI {tr[1]:+.2f} to {tr[2]:+.2f}). Home teams win {post.hw.mean():.1%} of extra games.",
    "findings": [
        f"Visitors, tied, leadoff bunt try vs swing: runs {tr[0]:+.2f} (CI {tr[1]:+.2f} to {tr[2]:+.2f}), win {pp(tw)}.",
        f"Home, tied, bunt try vs swing: scored {pp(bs_)}, win {pp(bw)}.",
        f"Home win % in extra-inning games: {pre.hw.mean():.1%} 2015-19 (n={len(pre):,}), {post.hw.mean():.1%} 2020-25 (n={len(post):,}).",
        f"Leadoff bunt attempt rate in extras: {st.bunt_att.mean():.1%} of {len(st):,} halves; bunters hit {st[st.bunt_att==1].q.mean()*1000:+.0f} pts of wOBA vs swingers {st[st.bunt_att==0].q.mean()*1000:+.0f}.",
    ],
    "method": "Leadoff PA of each extra half-inning (runner on 2nd, 0 out), non-pitchers. Bunt try = bunt in play or a foul/missed bunt. "
              "Linear model with batter-season wOBA and season; game bootstrap CIs. Intent beyond the batter is not observed.",
    "data": f"Retrosheet play-by-play, 2020-2025 regular season (7-inning games removed), {n_main:,} tied extra half-innings; 2015-19 extras for home win %.",
    "n": n_main, "robust": False, "interest": 2,
    "split_check": f"Win diff, bunt minus swing: visitors {SP[('2020-22','top')]*100:+.1f} pts 2020-22, {SP[('2023-25','top')]*100:+.1f} 2023-25; "
                   f"home {SP[('2020-22','bottom')]*100:+.1f}, {SP[('2023-25','bottom')]*100:+.1f} (raw).",
    "chart": {"type": "bar", "title": "Leadoff with runner on 2nd, tied extra innings",
              "x_label": "half-inning: outcome", "y_label": "batting team %", "y_fmt": "pct", "x_reverse": False,
              "ref": None, "mark": None,
              "series": [{"name": "swing away", "points": pts[0]}, {"name": "bunt try", "points": pts[1]}]},
}
json.dump(out, open(c.OUT + '/mlb-ghost-runner.json', 'w'), indent=2)
print(json.dumps({k: out[k] for k in ['answer', 'findings', 'split_check']}, indent=1))
