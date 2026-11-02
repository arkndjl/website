"""ARKBOARD research: tennis studies from the Match Charting Project (and tennis_atp / tennis_wta ranks).
Run: python3 -I studies.py <scratch_dir>   (expects <scratch_dir>/points.pkl from parse_mcp.py)"""
import json, math, os, sys
import numpy as np
import pandas as pd

S = sys.argv[1]
OUT = os.path.dirname(os.path.abspath(__file__))
RNG = np.random.default_rng(7)
ONLY = sys.argv[2:]  # optional study ids


def wilson(k, n, z=1.96):
    if n == 0:
        return (float('nan'),) * 3
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def r4(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def save(obj):
    with open(os.path.join(OUT, obj['id'] + '.json'), 'w') as f:
        json.dump(obj, f, indent=2)
    print('wrote', obj['id'])


def load():
    d = pd.read_pickle(os.path.join(S, 'points.pkl'))
    d['in1'] = ~d.fault1
    d['w1'] = d.in1 & d.won
    d['n2'] = d.fault1
    d['in2'] = d.fault1 & ~d.df
    d['w2'] = d.in2 & d.won
    yr = pd.to_numeric(d.mid.astype(str).str[:4], errors='coerce')
    d['year'] = yr.fillna(2000).astype(int)
    return d


# ---------------------------------------------------------------- 1. second serve: go big?
def second_serve(d, MIN2=500, B=2000):
    pm = d.groupby(['g', 'server', 'mid'], observed=True).agg(
        n1=('pt', 'size'), in1=('in1', 'sum'), w1=('w1', 'sum'), n2=('n2', 'sum'), in2=('in2', 'sum'),
        w2=('w2', 'sum'), year=('year', 'first')).reset_index()
    res = []
    for (g, pl), q in pm.groupby(['g', 'server'], observed=True):
        if q.n2.sum() < MIN2:
            continue
        a = q[['n1', 'w1', 'n2', 'w2', 'in1', 'in2']].to_numpy(float)
        gain = a[:, 1].sum() / a[:, 0].sum() - a[:, 3].sum() / a[:, 2].sum()
        idx = RNG.integers(0, len(a), (B, len(a)))
        s = a[idx].sum(1)
        bg = s[:, 1] / s[:, 0] - s[:, 3] / s[:, 2]
        lo, hi = np.percentile(bg, [2.5, 97.5])
        T = a.sum(0)
        res.append(dict(g=g, player=pl, matches=len(a), n1=int(T[0]), n2=int(T[2]), p1in=T[4] / T[0],
                        w1=T[1] / T[4], p2in=T[5] / T[2], w2=T[3] / T[5], gain=gain, lo=lo, hi=hi,
                        early=None))
    r = pd.DataFrame(res)
    # split check: gain by era (matches before / from 2015)
    pm['era'] = np.where(pm.year < 2015, 'early', 'late')
    era = pm.groupby(['g', 'server', 'era'], observed=True)[['n1', 'w1', 'n2', 'w2']].sum().reset_index()
    era = era[era.n2 >= 250]
    era['gain'] = era.w1 / era.n1 - era.w2 / era.n2
    r.to_csv(os.path.join(S, 'second_serve_players.csv'), index=False)
    out = {}
    for g in 'MW':
        q = r[r.g == g]
        e = era[era.g == g]
        out[g] = dict(n=len(q), pos=int((q.gain > 0).sum()), sigpos=int((q.lo > 0).sum()),
                      signeg=int((q.hi < 0).sum()), med=q.gain.median(), q90=q.gain.quantile(.9),
                      top=q.sort_values('gain', ascending=False).head(5)[['player', 'gain', 'lo', 'hi', 'n2', 'p1in', 'w1', 'p2in', 'w2']].round(3).to_dict('records'),
                      era_pos={k: (int((v.gain > 0).sum()), len(v)) for k, v in e.groupby('era')})
        print(g, {k: v for k, v in out[g].items()})
    bins = np.arange(-0.16, 0.0401, 0.02)
    series = []
    for g, name in (('M', 'men'), ('W', 'women')):
        q = r[r.g == g]
        h, _ = np.histogram(q.gain.clip(bins[0] + 1e-9, bins[-1] - 1e-9), bins)
        pts = []
        for i, c in enumerate(h):
            lo_, hi_ = bins[i] * 100, bins[i + 1] * 100
            fmt = lambda v: '0' if abs(v) < 1e-9 else f'{v:+.0f}'
            pts.append({'x': f'{fmt(lo_)} to {fmt(hi_)}', 'y': r4(c / len(q)), 'n': int(c)})
        series.append({'name': f'{name} ({len(q)})', 'points': pts})
    M, W = out['M'], out['W']
    save({
        'id': 'tennis-second-serve-first-serve',
        'sport': 'tennis',
        'question': 'Should players hit a first serve on second serve?',
        'answer': f"No. {M['pos']} of {M['n']} men and {W['pos']} of {W['n']} women would gain. "
                  f"Median player loses {abs(M['med'])*100:.1f} pts (men), {abs(W['med'])*100:.1f} (women) per 100.",
        'findings': [
            f"Men: {M['signeg']} of {M['n']} lose with 95% CI below zero; {M['sigpos']} gain with CI above zero.",
            f"Women: {W['signeg']} of {W['n']} lose with 95% CI below zero; {W['sigpos']} gain with CI above zero.",
            f"Pooled men: 1st serve wins {d[d.g=='M'].w1.sum()/len(d[d.g=='M'])*100:.1f}% per attempt vs 2nd {d[d.g=='M'].w2.sum()/d[d.g=='M'].n2.sum()*100:.1f}%.",
            f"Pooled women: 1st serve wins {d[d.g=='W'].w1.sum()/len(d[d.g=='W'])*100:.1f}% per attempt vs 2nd {d[d.g=='W'].w2.sum()/d[d.g=='W'].n2.sum()*100:.1f}%.",
        ],
        'method': 'Per server: P(1st in) x P(win | 1st in) minus P(2nd in) x P(win | 2nd in). '
                  'Bootstrap 95% CI resampling matches. Assumes first-serve in-rate and win rate hold on second-serve points.',
        'data': f"Match Charting Project points, 1960-2026 (71% of matches 2015+), {d.mid.nunique():,} matches; servers with {MIN2}+ second serves.",
        'n': int(M['n'] + W['n']),
        'robust': True,
        'interest': 3,
        'split_check': "Gainers by era (250+ 2nd serves), pre-2015 / 2015+: men {0[0]} of {0[1]} / {1[0]} of {1[1]}, women {2[0]} of {2[1]} / {3[0]} of {3[1]}.".format(
                       M['era_pos']['early'], M['era_pos']['late'], W['era_pos']['early'], W['era_pos']['late']),
        'chart': {'type': 'bar', 'title': 'Gain from a first serve on second serve, per player',
                  'x_label': 'points won per 100 second-serve points', 'y_label': 'share of players',
                  'y_fmt': 'pct', 'x_reverse': False, 'ref': None, 'mark': {'x': '0 to +2', 'label': 'gain starts'},
                  'series': series},
        '_extra': {'top_men': M['top'], 'top_women': W['top'], 'min_second_serves': MIN2},
    })


# ---------------------------------------------------------------- 2. serve direction mix
def direction(d, MINP=150):
    f = d[d.dir1.isin(['4', '5', '6']) & (d.ptsum >= 0)].copy()
    f['side'] = np.where(f.ptsum % 2 == 0, 'Deuce', 'Ad')
    f['dname'] = f.dir1.astype(str).map({'4': 'wide', '5': 'body', '6': 'T'})
    pooled = f.groupby(['g', 'side', 'dname'], observed=True).agg(n=('won', 'size'), k=('won', 'sum'),
                                                                   kin=('in1', 'sum'), w1=('w1', 'sum')).reset_index()
    print(pooled)
    # within player-side: chi-square equal win rates across wide and T (and all 3)
    ps = f.groupby(['g', 'server', 'side', 'dname'], observed=True).agg(n=('won', 'size'), k=('won', 'sum')).reset_index()
    stats = {}
    for g in 'MW':
        tests2, tests3, diffs, bdiffs = [], [], [], []
        for (pl, side), q in ps[ps.g == g].groupby(['server', 'side'], observed=True):
            q = q.set_index('dname')
            if not {'wide', 'T'} <= set(q.index) or q.loc['wide', 'n'] < MINP or q.loc['T', 'n'] < MINP:
                continue
            sub = q.loc[['wide', 'T']]
            p = sub.k.sum() / sub.n.sum()
            x2 = (((sub.k - sub.n * p) ** 2) / (sub.n * p * (1 - p))).sum()
            tests2.append(math.erfc(math.sqrt(x2 / 2)))  # chi2 df=1 sf
            rw, rt = q.loc['wide', 'k'] / q.loc['wide', 'n'], q.loc['T', 'k'] / q.loc['T', 'n']
            var = rw * (1 - rw) / q.loc['wide', 'n'] + rt * (1 - rt) / q.loc['T', 'n']
            diffs.append((rt - rw, var, side))
            if 'body' in q.index and q.loc['body', 'n'] >= 50:
                p3 = q.k.sum() / q.n.sum()
                x3 = (((q.k - q.n * p3) ** 2) / (q.n * p3 * (1 - p3))).sum()
                tests3.append(math.exp(-x3 / 2))  # chi2 df=2 sf
                rb = q.loc['body', 'k'] / q.loc['body', 'n']
                ro = sub.k.sum() / sub.n.sum()
                bdiffs.append((rb - ro, rb * (1 - rb) / q.loc['body', 'n'] + ro * (1 - ro) / sub.n.sum()))
        dd = np.array([x[0] for x in diffs]); vv = np.array([x[1] for x in diffs])
        wts = 1 / vv
        fe = (dd * wts).sum() / wts.sum(); fese = math.sqrt(1 / wts.sum())
        # excess variation: share of the variance in diffs beyond sampling noise
        chi = (((dd - fe) ** 2) * wts).sum(); k_ = len(dd)
        sides = {s: (np.array([x[0] for x in diffs if x[2] == s]), np.array([x[1] for x in diffs if x[2] == s])) for s in ('Deuce', 'Ad')}
        side_fe = {s: ((a / b).sum() / (1 / b).sum(), math.sqrt(1 / (1 / b).sum()), len(a)) for s, (a, b) in sides.items()}
        bw = np.array([1 / x[1] for x in bdiffs])
        bfe = (np.array([x[0] for x in bdiffs]) * bw).sum() / bw.sum()
        stats[g] = dict(bfe=bfe, bfese=math.sqrt(1 / bw.sum()), k=k_, sig2=float(np.mean(np.array(tests2) < .05)), k3=len(tests3),
                        sig3=float(np.mean(np.array(tests3) < .05)), fe=fe, fese=fese, Q=chi, side_fe=side_fe,
                        sd_obs=float(dd.std()), sd_noise=float(np.sqrt(vv.mean())))
        print(g, stats[g])
    # split check by era
    f['era'] = np.where(f.year < 2015, 'early', 'late')
    era = f[f.dname != 'body'].groupby(['g', 'era', 'dname'], observed=True).won.mean().unstack()
    print(era)
    series = []
    for g, name in (('M', 'men'), ('W', 'women')):
        pts = []
        for side in ('Deuce', 'Ad'):
            for dn in ('wide', 'body', 'T'):
                row = pooled[(pooled.g == g) & (pooled.side == side) & (pooled.dname == dn)].iloc[0]
                p, lo, hi = wilson(row.k, row.n)
                pts.append({'x': f'{side} {dn}', 'y': r4(p), 'lo': r4(lo), 'hi': r4(hi), 'n': int(row.n)})
        series.append({'name': name, 'points': pts})
    M, W = stats['M'], stats['W']
    use = pooled.groupby(['g', 'dname']).n.sum() / pooled.groupby('g').n.sum()
    def pr(g, side, dn):
        row = pooled[(pooled.g == g) & (pooled.side == side) & (pooled.dname == dn)].iloc[0]
        return row.k / row.n * 100
    save({
        'id': 'tennis-serve-direction-mix',
        'sport': 'tennis',
        'question': 'Do first serves wide, body and T win at equal rates, as mixed-strategy theory predicts?',
        'answer': f"Wide and T: yes, within 1 pt for the same server. Body: no, {abs(M['bfe'])*100:.1f} pts lower (men), {abs(W['bfe'])*100:.1f} (women).",
        'findings': [
            f"Within-player T minus wide: men {M['fe']*100:+.1f} pts (SE {M['fese']*100:.1f}, {M['k']} player-sides), women {W['fe']*100:+.1f} (SE {W['fese']*100:.1f}, {W['k']}).",
            f"Wide vs T differ at p<.05 for {M['sig2']*100:.0f}% of men's and {W['sig2']*100:.0f}% of women's player-sides; 5% expected by chance.",
            f"Body minus wide/T, same server: men {M['bfe']*100:+.1f} pts (SE {M['bfese']*100:.1f}), women {W['bfe']*100:+.1f} (SE {W['bfese']*100:.1f}).",
            f"Body is {use['M']['body']*100:.0f}% of men's and {use['W']['body']*100:.0f}% of women's first serves; charters may log missed targets as body.",
        ],
        'method': 'Outcome: server wins the point, given the first serve was aimed at that target (faults count). '
                  'Within-player test compares wide and T for each server and court side (150+ serves each).',
        'data': f"Match Charting Project points, {f.mid.nunique():,} charted matches, {len(f):,} first serves with a direction.",
        'n': int(len(f)),
        'robust': True,
        'interest': 3,
        'split_check': 'pre-2015 / 2015+: ' + '; '.join(f"{g} {e}: wide {era.loc[(g, e), 'wide']*100:.1f}%, T {era.loc[(g, e), 'T']*100:.1f}%" for g, e in era.index),
        'chart': {'type': 'bar', 'title': 'Points won by first-serve target',
                  'x_label': 'court side and target', 'y_label': 'server points won',
                  'y_fmt': 'pct', 'x_reverse': False, 'ref': None, 'mark': None, 'series': series},
        '_extra': {k: {kk: (vv if not isinstance(vv, float) else round(vv, 4)) for kk, vv in v.items()} for k, v in stats.items()},
    })


# ---------------------------------------------------------------- games / sets tables
PTOK = {'0', '15', '30', '40', 'AD'}


def games(d):
    """One row per game: match, set index, game score before, server (1/2), winner (1/2), tiebreak flag.
    Matches whose game sequence is inconsistent are dropped."""
    d = d.sort_values(['mid', 'pt'])
    d['pw'] = np.where(d.won, d.svr, 3 - d.svr)
    key = d.mid.astype(str) + '|' + d.set1.astype(str) + '|' + d.set2.astype(str) + '|' + d.gm1.astype(str) + '|' + d.gm2.astype(str)
    newg = key.ne(key.shift())
    d['gid'] = newg.cumsum()
    toks = d.pts.astype(str).str.split('-', expand=True)
    d['tbpt'] = ~(toks[0].isin(PTOK) & toks[1].isin(PTOK))
    G = d.groupby('gid', sort=True).agg(mid=('mid', 'first'), g=('g', 'first'), set1=('set1', 'first'),
                                        set2=('set2', 'first'), gm1=('gm1', 'first'), gm2=('gm2', 'first'),
                                        svr=('svr', 'first'), win=('pw', 'last'), tbp=('tbpt', 'any'),
                                        npts=('pt', 'size'), server=('server', 'first'), returner=('returner', 'first'),
                                        year=('year', 'first'))
    G['tb'] = G.tbp | ((G.gm1 == G.gm2) & (G.gm1 >= 6))
    G['setno'] = G.set1 + G.set2 + 1
    # consistency: next game in the same set must have the winner's count +1
    nx = G.shift(-1)
    same = (nx.mid == G.mid) & (nx.setno == G.setno)
    ok = ~same | ((nx.gm1 == G.gm1 + (G.win == 1)) & (nx.gm2 == G.gm2 + (G.win == 2)))
    # a new set must follow a set-ending game
    newset = (nx.mid == G.mid) & (nx.setno == G.setno + 1)
    ok &= ~newset | (((nx.set1 == G.set1 + (G.win == 1)) & (nx.set2 == G.set2 + (G.win == 2))))
    bad = set(G.mid[~ok])
    print('games', len(G), 'matches', G.mid.nunique(), 'inconsistent matches', len(bad))
    G = G[~G.mid.isin(bad)].copy()
    # set winner: winner of the last game of the set when another set follows, else last point of a complete-looking set
    last = G.groupby(['mid', 'setno']).tail(1).copy()
    nxt = last.groupby('mid').setno.transform('max')
    lw = last.win
    g1 = last.gm1 + (lw == 1); g2 = last.gm2 + (lw == 2)
    done = last.tb | ((np.maximum(g1, g2) >= 6) & ((g1 - g2).abs() >= 2))
    last['complete'] = (last.setno < nxt) | done
    last['setwin'] = lw
    return G, last[['mid', 'setno', 'complete', 'setwin']]


def logit(X, y, iters=30):
    # drop constant (non-intercept) and redundant columns, keep column 0 (intercept) and 1
    keep = [0, 1]
    for j in range(2, X.shape[1]):
        if X[:, j].std() > 0 and np.linalg.matrix_rank(X[:, keep + [j]]) == len(keep) + 1:
            keep.append(j)
    X = X[:, keep]
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None])
        b_new = b + np.linalg.solve(H, X.T @ (y - p))
        if np.max(np.abs(b_new - b)) < 1e-9:
            b = b_new
            break
        b = b_new
    p = 1 / (1 + np.exp(-X @ b))
    H = X.T @ (X * (p * (1 - p))[:, None])
    return b, np.sqrt(np.diag(np.linalg.inv(H)))


def strength(d):
    """Leave-one-match-out share of points won (serve + return) for each (match, player), shrunk to 0.5 with 200 pts."""
    a = d.groupby(['mid', 'server'], observed=True).agg(sw=('won', 'sum'), sn=('won', 'size')).reset_index().rename(columns={'server': 'pl'})
    b = d.groupby(['mid', 'returner'], observed=True).agg(rl=('won', 'sum'), rn=('won', 'size')).reset_index().rename(columns={'returner': 'pl'})
    m = a.merge(b, on=['mid', 'pl'], how='outer').fillna(0)
    m['w'] = m.sw + m.rn - m.rl
    m['n'] = m.sn + m.rn
    tot = m.groupby('pl', observed=True)[['w', 'n']].transform('sum')
    m['str'] = (tot.w - m.w + 100) / (tot.n - m.n + 200)
    m['pl'] = m.pl.astype(str)
    m['mid'] = m.mid.astype(str)
    return m.set_index(['mid', 'pl'])['str']


# ---------------------------------------------------------------- 3. serving first in a set
def serve_first(d, G, sets):
    st = strength(d)
    first = G.groupby(['mid', 'setno']).head(1)
    first = first[(first.gm1 == 0) & (first.gm2 == 0)]
    x = first.merge(sets, on=['mid', 'setno'])
    x = x[x.complete].copy()
    x['fs_won'] = (x.setwin == x.svr).astype(float)
    mids = x.mid.astype(str); sv = x.server.astype(str); rt = x.returner.astype(str)
    x['sdiff'] = st.reindex(list(zip(mids, sv))).to_numpy() - st.reindex(list(zip(mids, rt))).to_numpy()
    # previous set won by the first server of this set
    prev = sets.set_index(['mid', 'setno']).setwin
    pw = prev.reindex(list(zip(x.mid, x.setno - 1))).to_numpy()
    x['prevwon'] = np.where(x.setno > 1, (pw == x.svr.to_numpy()).astype(float) - 0.5, 0.0)
    x['sets_ahead'] = np.where(x.svr == 1, x.set1 - x.set2, x.set2 - x.set1).astype(float)
    x = x.dropna(subset=['sdiff'])
    res = {}
    for g in 'MW':
        q = x[x.g == g]
        for sn in (1, 2, 3, 4, 5):
            r = q[q.setno == sn]
            if len(r) < 200:
                continue
            p, lo, hi = wilson(r.fs_won.sum(), len(r))
            # logit with strength diff and, for later sets, set-score controls; intercept = first-server effect at even strength
            cols = [np.ones(len(r)), r.sdiff.to_numpy() * 10]
            if sn == 2:
                cols += [r.sets_ahead.to_numpy()]
            elif sn > 2:
                cols += [r.prevwon.to_numpy(), r.sets_ahead.to_numpy()]
            b, se = logit(np.column_stack(cols), r.fs_won.to_numpy())
            inv = lambda z: 1 / (1 + math.exp(-z))
            res[(g, sn)] = dict(n=len(r), p=p, lo=lo, hi=hi, adj=inv(b[0]), alo=inv(b[0] - 1.96 * se[0]), ahi=inv(b[0] + 1.96 * se[0]),
                                bal=float(r.sdiff.mean()), slope=b[1])
            print(g, sn, {k: round(v, 4) for k, v in res[(g, sn)].items()})
        # split check set 1 by era
        r = q[q.setno == 1]
        for e, rr in r.groupby(r.year < 2015):
            print(g, 'set1 pre2015' if e else 'set1 2015+', len(rr), round(rr.fs_won.mean(), 4))
    # all sets pooled: first server effect
    allr = {}
    for g in 'MW':
        r = x[x.g == g]
        cols = [np.ones(len(r)), r.sdiff.to_numpy() * 10, r.prevwon.to_numpy(), r.sets_ahead.to_numpy()]
        b, se = logit(np.column_stack(cols), r.fs_won.to_numpy())
        inv = lambda z: 1 / (1 + math.exp(-z))
        allr[g] = dict(n=len(r), adj=inv(b[0]), alo=inv(b[0] - 1.96 * se[0]), ahi=inv(b[0] + 1.96 * se[0]), raw=r.fs_won.mean())
        print(g, 'all sets', allr[g])
    eras = {}
    for g in 'MW':
        r = x[(x.g == g) & (x.setno == 1)]
        eras[g] = [(int(len(rr)), float(rr.fs_won.mean())) for _, rr in r.groupby(r.year >= 2015)]
    return res, allr, eras


# ---------------------------------------------------------------- 4. hold after breaking
def break_back(G, B=1000):
    G = G.copy()
    prev = G.shift(1)
    c = (prev.mid == G.mid) & (prev.setno == G.setno) & ~G.tb & ~prev.tb.fillna(True).astype(bool) & (prev.svr != G.svr)
    G = G[c].copy()
    pv = prev[c]
    G['hold'] = (G.win == G.svr).astype(int)
    G['after_break'] = (pv.win == G.svr).astype(int)     # server of this game won the previous (opponent's) game
    G['key'] = G.mid.astype(str) + '|' + G.svr.astype(str)
    out = {}
    for g in 'MW':
        q = G[G.g == g]
        # within player-match: keep player-matches with both kinds of game
        t = q.groupby(['key', 'after_break']).hold.agg(['sum', 'size']).unstack()
        t = t.dropna()
        t.columns = ['h0', 'h1', 'n0', 'n1']
        mid = t.index.str.split('|').str[0]
        # Mantel-Haenszel style risk difference, weights n0*n1/(n0+n1)
        w = t.n0 * t.n1 / (t.n0 + t.n1)
        rd = ((t.h1 / t.n1 - t.h0 / t.n0) * w).sum() / w.sum()
        # cluster bootstrap by match
        grp = pd.Series(np.arange(len(t)), index=t.index).groupby(mid).apply(list).tolist()
        arr = np.column_stack([t.h0, t.h1, t.n0, t.n1, w])
        bs = []
        for _ in range(B):
            pick = RNG.integers(0, len(grp), len(grp))
            ix = np.concatenate([grp[i] for i in pick])
            a = arr[ix]
            bs.append(((a[:, 1] / a[:, 3] - a[:, 0] / a[:, 2]) * a[:, 4]).sum() / a[:, 4].sum())
        lo, hi = np.percentile(bs, [2.5, 97.5])
        raw = q.groupby('after_break').hold.agg(['sum', 'size'])
        eras = {}
        for e, qq in q.groupby(q.year >= 2015):
            tt = qq.groupby(['key', 'after_break']).hold.agg(['sum', 'size']).unstack().dropna()
            tt.columns = ['h0', 'h1', 'n0', 'n1']
            ww = tt.n0 * tt.n1 / (tt.n0 + tt.n1)
            eras['late' if e else 'early'] = ((tt.h1 / tt.n1 - tt.h0 / tt.n0) * ww).sum() / ww.sum()
        out[g] = dict(rd=rd, lo=lo, hi=hi, pm=len(t), matches=mid.nunique(), raw=raw, eras=eras,
                      games=int(len(q)))
        print(g, {k: v for k, v in out[g].items() if k != 'raw'}, raw.to_dict())
    return out


def main():
    d = load()
    for name, fn in (('second', second_serve), ('direction', direction)):
        if not ONLY or name in ONLY:
            fn(d)
    if not ONLY or 'sets' in ONLY or 'brk' in ONLY or 'tb' in ONLY:
        G, sets = games(d)
        if not ONLY or 'sets' in ONLY:
            write_serve_first(d, *serve_first(d, G, sets))
        if not ONLY or 'brk' in ONLY:
            write_break_back(break_back(G))
        if not ONLY or 'tb' in ONLY:
            write_tiebreaks(tiebreaks(d, G))


# ---------------------------------------------------------------- 5. tiebreaks vs serve strength
def p_tb(pa, pb, target=7):
    """P(A wins a first-to-`target`, win-by-2 tiebreak), A serves first, iid points; pa/pb = serve-point win rates."""
    def srv_a(k):
        return k == 0 or ((k - 1) // 2) % 2 == 1
    from functools import lru_cache

    @lru_cache(None)
    def f(a, b):
        if a >= target and a - b >= 2:
            return 1.0
        if b >= target and b - a >= 2:
            return 0.0
        if a == b and a >= target - 1:
            # from level at 6-6 (or later): each pair of points has one A serve and one B serve
            w2 = pa * (1 - pb)
            l2 = (1 - pa) * pb
            return w2 / (w2 + l2)
        k = a + b
        q = pa if srv_a(k) else 1 - pb
        return q * f(a + 1, b) + (1 - q) * f(a, b + 1)
    return f(0, 0)


def tiebreaks(d, G):
    nt = d.copy()
    nt['key'] = nt.mid.astype(str) + '|' + nt.set1.astype(str) + '|' + nt.set2.astype(str) + '|' + nt.gm1.astype(str) + '|' + nt.gm2.astype(str)
    tbg = G[G.tb & (G.gm1 == 6) & (G.gm2 == 6)]
    tbkeys = set(tbg.mid.astype(str) + '|' + tbg.set1.astype(str) + '|' + tbg.set2.astype(str) + '|6|6')
    istb = nt.key.isin(tbkeys)
    sp = nt[~istb].groupby(['mid', 'svr'], observed=True).won.agg(['sum', 'size'])
    tp = nt[istb].assign(pw=np.where(nt[istb].won, nt[istb].svr, 3 - nt[istb].svr))
    rows = []
    for k, q in tp.groupby('key', sort=False):
        mid = q.mid.iloc[0]
        a1 = (q.pw == 1).sum(); a2 = (q.pw == 2).sum()
        hi_, lo_ = max(a1, a2), min(a1, a2)
        if hi_ >= 10 and lo_ <= 8:
            continue  # 10-point tiebreak
        if not ((hi_ >= 7) and (hi_ - lo_ >= 2)):
            continue  # incomplete
        try:
            s1, s2 = sp.loc[(mid, 1)], sp.loc[(mid, 2)]
        except KeyError:
            continue
        if s1['size'] < 30 or s2['size'] < 30:
            continue
        p1, p2 = s1['sum'] / s1['size'], s2['sum'] / s2['size']
        first = int(q.svr.iloc[0])
        pa, pb = (p1, p2) if first == 1 else (p2, p1)
        pf = p_tb(round(pa, 3), round(pb, 3))
        p1win = pf if first == 1 else 1 - pf
        rows.append(dict(mid=mid, g=q.g.iloc[0], p1=p1, p2=p2, pred1=p1win, win1=int(a1 > a2), year=int(q.year.iloc[0]),
                         first=first))
    t = pd.DataFrame(rows)
    # perspective: the bigger server (higher serve-point win rate in the match)
    big1 = t.p1 >= t.p2
    t['adv'] = (t.p1 - t.p2).abs()
    t['pred'] = np.where(big1, t.pred1, 1 - t.pred1)
    t['win'] = np.where(big1, t.win1, 1 - t.win1)
    t['bigsv'] = np.where(big1, t.p1, t.p2)
    t['fs_pred'] = np.where(t['first'] == 1, t.pred1, 1 - t.pred1)
    t['fs_win'] = np.where(t['first'] == 1, t.win1, 1 - t.win1)
    print(len(t), t.groupby('g')[['win', 'pred', 'fs_win', 'fs_pred']].mean())
    return t


def write_tiebreaks(t):
    bins = [0, .02, .04, .06, .08, .10, .14, 1]
    labels = ['0-2', '2-4', '4-6', '6-8', '8-10', '10-14', '14+']
    t['bin'] = pd.cut(t.adv, bins, labels=labels, right=False)
    act, mod = [], []
    for lab, q in t.groupby('bin', observed=True):
        p, lo, hi = wilson(q.win.sum(), len(q))
        act.append({'x': lab, 'y': r4(p), 'lo': r4(lo), 'hi': r4(hi), 'n': int(len(q))})
        mod.append({'x': lab, 'y': r4(q.pred.mean()), 'n': int(len(q))})
    res = {}
    for g in ('M', 'W', 'all'):
        q = t if g == 'all' else t[t.g == g]
        r = (q.win - q.pred)
        # cluster SE by match
        cm = r.groupby(q.mid).sum()
        se = math.sqrt(len(cm) / (len(cm) - 1) * (cm ** 2).sum()) / len(q)
        res[g] = dict(n=len(q), win=q.win.mean(), pred=q.pred.mean(), diff=r.mean(), se=se)
    # big-serve players: does the residual grow with the bigger server's serve level?
    hs = t[t.bigsv >= .72]
    rh = (hs.win - hs.pred)
    seh = rh.std() / math.sqrt(len(hs))
    fs = (t.fs_win - t.fs_pred)
    split = {e: (q.win - q.pred).mean() for e, q in t.groupby(t.year >= 2015)}
    print(res, len(hs), rh.mean(), seh, fs.mean(), fs.std() / math.sqrt(len(t)), split)
    A, M_, W_ = res['all'], res['M'], res['W']
    save({
        'id': 'tennis-tiebreak-serve-strength',
        'sport': 'tennis',
        'question': 'Do bigger servers win tiebreaks more often than their point-level edge predicts?',
        'answer': f"No. Bigger server wins {A['win']*100:.1f}% of tiebreaks; an iid point model predicts {A['pred']*100:.1f}%.",
        'findings': [
            f"Actual minus model: {A['diff']*100:+.1f} pts (95% CI {(A['diff']-1.96*A['se'])*100:+.1f} to {(A['diff']+1.96*A['se'])*100:+.1f}), n={A['n']:,} tiebreaks.",
            f"Men {M_['diff']*100:+.1f} pts (n={M_['n']:,}); women {W_['diff']*100:+.1f} pts (n={W_['n']:,}).",
            f"Bigger server at 72%+ serve pts won: {rh.mean()*100:+.1f} pts vs model (SE {seh*100:.1f}, n={len(hs):,}); partly regression to mean.",
            f"First server in the tiebreak: {fs.mean()*100:+.1f} pts vs model (SE {fs.std()/math.sqrt(len(t))*100:.1f}).",
        ],
        'method': "Model: each player's serve-point win rate in the same match outside tiebreaks, points iid, "
                  "7-point serve order. Edges measured in-match regress to the mean, so the model overstates large edges. SE by match.",
        'data': f"Match Charting Project points, {t.mid.nunique():,} matches, {len(t):,} tiebreaks at 6-6 (10-point tiebreaks excluded).",
        'n': int(len(t)),
        'robust': bool(abs(A['diff']) < 1.96 * A['se']),
        'interest': 2,
        'split_check': f"Actual minus model, pre-2015 {split.get(False, float('nan'))*100:+.1f} pts, 2015+ {split.get(True, float('nan'))*100:+.1f} pts.",
        'chart': {'type': 'bar', 'title': 'Tiebreak win rate of the bigger server',
                  'x_label': 'serve-point win rate edge, pts', 'y_label': 'tiebreaks won',
                  'y_fmt': 'pct', 'x_reverse': False, 'ref': {'y': 0.5, 'label': 'even'}, 'mark': None,
                  'series': [{'name': 'actual', 'points': act}, {'name': 'iid model', 'points': mod}]},
    })


def write_serve_first(d, res, allr, eras):
    series = []
    for g, name in (('M', 'men'), ('W', 'women')):
        pts = []
        for sn in (1, 2, 3, 4, 5):
            r = res.get((g, sn))
            if r:
                pts.append({'x': f'set {sn}', 'y': r4(r['adj']), 'lo': r4(r['alo']), 'hi': r4(r['ahi']), 'n': r['n']})
        series.append({'name': name, 'points': pts})
    m1, w1 = res[('M', 1)], res[('W', 1)]
    am, aw = allr['M'], allr['W']
    save({
        'id': 'tennis-serve-first-in-set',
        'sport': 'tennis',
        'question': 'Does the player who serves first in a set win it more often?',
        'answer': f"Set 1 raw: {m1['p']*100:.1f}% men, {w1['p']*100:.1f}% women. At equal strength: {m1['adj']*100:.1f}% and {w1['adj']*100:.1f}%, CIs include 50%.",
        'findings': [
            f"Men set 1: {m1['adj']*100:.1f}% at equal strength (95% CI {m1['alo']*100:.1f}-{m1['ahi']*100:.1f}, n={m1['n']:,}).",
            f"Women set 1: {w1['adj']*100:.1f}% at equal strength (95% CI {w1['alo']*100:.1f}-{w1['ahi']*100:.1f}, n={w1['n']:,}).",
            "Raw edge is mostly strength: stronger players are more often the first server in set 1.",
            f"All sets, adjusted: men {am['adj']*100:.1f}% ({am['alo']*100:.1f}-{am['ahi']*100:.1f}), women {aw['adj']*100:.1f}% ({aw['alo']*100:.1f}-{aw['ahi']*100:.1f}).",
        ],
        'method': "Logistic model of set win on first-server flag plus strength (each player's point-win share in other "
                  "charted matches); later sets add set score. Intercept = first-server win % at equal strength.",
        'data': f"Match Charting Project points, {m1['n'] + w1['n']:,} charted matches with a complete first set.",
        'n': int(m1['n'] + w1['n']),
        'robust': True,
        'interest': 2,
        'split_check': "Raw set 1, pre-2015 / 2015+: men {0:.1f}% / {1:.1f}%, women {2:.1f}% / {3:.1f}%.".format(
            eras['M'][0][1] * 100, eras['M'][1][1] * 100, eras['W'][0][1] * 100, eras['W'][1][1] * 100),
        'chart': {'type': 'bar', 'title': 'First server set win %, equal strength',
                  'x_label': 'set', 'y_label': 'sets won by first server', 'y_fmt': 'pct', 'x_reverse': False,
                  'ref': {'y': 0.5, 'label': 'no edge'}, 'mark': None, 'series': series},
    })


def write_break_back(out):
    series = []
    for g, name in (('M', 'men'), ('W', 'women')):
        raw = out[g]['raw']
        pts = []
        for ab, lab in ((0, 'after opponent held'), (1, 'after breaking')):
            k, n = int(raw.loc[ab, 'sum']), int(raw.loc[ab, 'size'])
            p, lo, hi = wilson(k, n)
            pts.append({'x': lab, 'y': r4(p), 'lo': r4(lo), 'hi': r4(hi), 'n': n})
        series.append({'name': name, 'points': pts})
    M, W = out['M'], out['W']
    save({
        'id': 'tennis-hold-after-break',
        'sport': 'tennis',
        'question': 'Do players drop serve more often right after breaking?',
        'answer': f"No. Same player and match: hold rate after breaking is {M['rd']*100:+.1f} pts (men), {W['rd']*100:+.1f} (women) vs after opponent holds.",
        'findings': [
            f"Men: {M['rd']*100:+.1f} pts (95% CI {M['lo']*100:+.1f} to {M['hi']*100:+.1f}), {M['pm']:,} player-matches.",
            f"Women: {W['rd']*100:+.1f} pts (95% CI {W['lo']*100:+.1f} to {W['hi']*100:+.1f}), {W['pm']:,} player-matches.",
            f"Raw hold after breaking: men {series[0]['points'][1]['y']*100:.1f}%, women {series[1]['points'][1]['y']*100:.1f}%; mostly stronger servers breaking.",
        ],
        'method': "Hold (non-tiebreak games) by whether the server broke in the previous game. Within player-match "
                  "difference, weighted; bootstrap CI resampling matches. Form swings within a match bias this upward.",
        'data': f"Match Charting Project points, {M['matches'] + W['matches']:,} matches, {M['games'] + W['games']:,} service games.",
        'n': int(M['games'] + W['games']),
        'robust': True,
        'interest': 3,
        'split_check': f"Pre-2015 / 2015+: men {M['eras']['early']*100:+.1f} / {M['eras']['late']*100:+.1f} pts, "
                       f"women {W['eras']['early']*100:+.1f} / {W['eras']['late']*100:+.1f} pts.",
        'chart': {'type': 'bar', 'title': 'Hold rate by previous game',
                  'x_label': 'previous game', 'y_label': 'hold %', 'y_fmt': 'pct', 'x_reverse': False,
                  'ref': None, 'mark': None, 'series': series},
    })


if __name__ == '__main__':
    main()
