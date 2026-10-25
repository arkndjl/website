"""Pick noise for the probabilistic CFB mock (mockSims in scripts/cfb_teams.mjs).

The mock takes, at each pick, the player with the best team utility (log-pick units: -ln xPick plus need, less the
dup, run and set-QB penalties). The probabilistic mock adds Gumbel noise of scale beta to every utility, so a team
takes player j with probability softmax(u / beta). beta is fit on the 2020-25 drafts replayed pick by pick in the
real order (scripts/draft_sim_backtest.py: DraftTek final boards, the mock's utilities): at each real pick, the
players really taken before it are gone and each team's real earlier picks set its dup and run terms, and the score
is the log probability of the player the team really took (teacher forcing; picks of players off the top-400 board
are skipped). Leave one draft out. Specs: one beta; beta by round group (1, 2-3, 4-7); beta a + b ln pick; the same
logit on board order alone (no mock terms), to show what the utilities add. Then forward sims of each held-out
draft from its final board at the held-out beta, with a board shock (each player's ln xPick moved once a draft, sd sp)
and the pick noise scaled by k, (sp, k) picked leave one draft out on round-1 log loss: P(round 1) against who went in round 1, by Brier and
log loss, against the log-normal Draft% curve at its final-month sd (.56 around xPick, cut at 32.5), and the 80%
pick-range coverage. Writes data/cfb_mock_noise.json. Usage: python3 scripts/mock_noise_backtest.py (after
scripts/draft_backtest.py; numpy).
"""
import os, sys, json, math, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import draft_sim_backtest as B

SIMS = 400
OUT = os.path.join(B.ROOT, 'data', 'cfb_mock_noise.json')


def util_fn(Y, prm, pr):
    """the mock's utility for a player given team t's state (draft_sim_backtest.sim, without the noise)"""
    def u(p, t, rd, tpos, rc):
        g = p['g']; v = -p['lx']; ri = min(rd, 3)
        if not prm: return v
        needy = B.qneed.get((Y, t), 1)
        if g == 'QB':
            v -= tpos[t].count('QB') * prm['qbdup']
            v += prm['needw'] * (needy - prm['needbase'])
            if not needy and rd <= 3: v -= prm['block']
        else: v -= tpos[t].count(g) * prm['dup']
        cap = max(1, round(pr[(g, ri)] * 1.25))
        if rc[(g, rd)] >= cap: v -= prm['run'] * (rc[(g, rd)] - cap + 1)
        return v
    return u


def replay(Y, prm):
    """teacher-forced: per real pick with the real player on the board, (pick, round, utilities, index of the real one)"""
    pool = [dict(r, lx=B.lnx(r['rank'])) for r in B.rows if r['year'] == Y and r['g'] in B.G and r['rank'] <= 400]
    by_pick = {p['pick']: p for p in pool if p.get('pick')}
    u = util_fn(Y, prm, B.per_round(Y))
    taken = set(); tpos = collections.defaultdict(list); rc = collections.Counter(); out = []
    for pk, rd, t, g, n in B.order[Y]:
        real = by_pick.get(pk)
        if real is not None:
            av = [p for p in pool if id(p) not in taken]
            out.append((pk, rd, np.array([u(p, t, rd, tpos, rc) for p in av]), next(i for i, p in enumerate(av) if p is real)))
            taken.add(id(real)); tpos[t].append(real['g']); rc[(real['g'], rd)] += 1
        else:   # off-board pick: the slot still counts toward the team's room and the round's run
            tpos[t].append(g); rc[(g, rd)] += 1
    return out


def beta_of(spec, th, pk, rd):
    if spec == 'one': return th[0]
    if spec == 'round': return th[0] if rd == 1 else th[1] if rd <= 3 else th[2]
    return max(0.02, th[0] + th[1] * math.log(pk))


def ll(rep, spec, th):
    tot = []
    for pk, rd, u, j in rep:
        b = beta_of(spec, th, pk, rd); z = u / b; m = z.max()
        tot.append(z[j] - m - math.log(np.exp(z - m).sum()))
    return tot


GRID = {'one': [(b,) for b in np.arange(0.05, 1.21, 0.025)],
        'lnpick': [(a, b) for a in np.arange(-0.2, 0.61, 0.05) for b in np.arange(0.0, 0.31, 0.02)]}


def fit(reps, spec):
    if spec == 'round':   # the log likelihood splits by round group: one beta each
        grp = lambda rd: 0 if rd == 1 else 1 if rd <= 3 else 2
        return tuple(fit([[x for x in r if grp(x[1]) == k] for r in reps], 'one')[0] for k in range(3))
    best = None
    for th in GRID[spec]:
        s = sum(sum(ll(r, spec, th)) for r in reps)
        if best is None or s > best[0]: best = (s, th)
    return best[1]


def forward(Y, prm, spec, th, rng, sp=0.0, k=1.0, sims=SIMS):
    """sims full drafts of Y from its final board: each player's pick per sim (undrafted 300). Every pick adds Gumbel
    noise at k x beta; sp > 0 also moves each player's ln xPick by a normal shock of sd sp, held for the whole draft
    (a board miss: a player the board has too high falls past many teams, not one)"""
    pool = [dict(r, lx=B.lnx(r['rank'])) for r in B.rows if r['year'] == Y and r['g'] in B.G and r['rank'] <= 400]
    pr = B.per_round(Y); od = B.order[Y]; n = len(pool)
    gi = np.array([B.G.index(p['g']) for p in pool]); lx0 = np.array([p['lx'] for p in pool]); isqb = gi == B.G.index('QB')
    slot = np.full((sims, n), 300)
    for s in range(sims):
        lx = lx0 + (sp * rng.standard_normal(n) if sp else 0)
        taken = np.zeros(n, bool); tcnt = collections.defaultdict(lambda: np.zeros(len(B.G))); rc = collections.Counter()
        for pk, rd, t, *_ in od:
            if taken.all(): break
            ri = min(rd, 3); needy = B.qneed.get((Y, t), 1); tc = tcnt[t]
            pen = np.array([tc[j] * (prm['qbdup'] if g == 'QB' else prm['dup']) for j, g in enumerate(B.G)])
            for j, g in enumerate(B.G):
                cap = max(1, round(pr[(g, ri)] * 1.25))
                if rc[(g, rd)] >= cap: pen[j] += prm['run'] * (rc[(g, rd)] - cap + 1)
            qb = prm['needw'] * (needy - prm['needbase']) - (prm['block'] if not needy and rd <= 3 else 0)
            v = -lx - pen[gi] + np.where(isqb, qb, 0.0) + k * beta_of(spec, th, pk, rd) * rng.gumbel(size=n)
            v[taken] = -np.inf
            i = int(v.argmax()); taken[i] = True; slot[s, i] = pk; tc[gi[i]] += 1; rc[(pool[i]['g'], rd)] += 1
    return pool, slot


def phi(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def main():
    rng = np.random.default_rng(7)
    years = list(B.YEARS)
    R = {m: {Y: replay(Y, prm) for Y in years} for m, prm in (('mock', B.MOCK), ('board', {}))}
    res = {}
    for m, spec in (('mock', 'one'), ('mock', 'round'), ('mock', 'lnpick'), ('board', 'one')):
        held, ths = [], {}
        for Y in years:
            th = fit([R[m][y] for y in years if y != Y], spec); ths[Y] = [round(float(x), 3) for x in th]
            held.append(ll(R[m][Y], spec, th))
        per = [float(np.mean(h)) for h in held]
        res[f'{m} {spec}'] = {'heldLogScore': round(float(np.mean(np.concatenate(held))), 4), 'byDraft': dict(zip(years, [round(x, 4) for x in per])),
                              'theta': ths, 'all': [round(float(x), 3) for x in fit([R[m][y] for y in years], spec)], '_ll': held}
        print(f'{m:5s} {spec:6s} held-out log score/pick {res[f"{m} {spec}"]["heldLogScore"]:.4f}  theta (all) {res[f"{m} {spec}"]["all"]}')
    # paired: each spec against one beta, pick by pick, and the mock against the board order
    def paired(a, b):
        d = np.concatenate([np.array(x) - np.array(y) for x, y in zip(res[a]['_ll'], res[b]['_ll'])])
        won = sum(np.mean(x) > np.mean(y) for x, y in zip(res[a]['_ll'], res[b]['_ll']))
        return {'diff': round(float(d.mean()), 4), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'drafts': f'{won}/{len(years)}'}
    tests = {'round vs one': paired('mock round', 'mock one'), 'lnpick vs one': paired('mock lnpick', 'mock one'), 'mock vs board order': paired('mock one', 'board one')}
    for k, v in tests.items(): print(k, v)
    # the spec the live mock uses: the best held-out one that beats one beta at t >= 2 in 4+ of 6 drafts, else one beta
    pick = 'one'
    for s in ('round', 'lnpick'):
        v = tests[f'{s} vs one']
        if v['t'] >= 2 and int(v['drafts'].split('/')[0]) >= 4 and res[f'mock {s}']['heldLogScore'] > res[f'mock {pick}']['heldLogScore']: pick = s
    # forward sims at the held-out theta, with and without a player-level board shock (sp) and the pick noise
    # scaled by k: P(round 1) and pick ranges. The (sp, k) pair is picked leave one draft out on round-1 log loss
    clip = lambda q: np.clip(q, 1e-3, 1 - 1e-3)
    LL = lambda q, y: float(-np.mean(y * np.log(clip(q)) + (1 - y) * np.log(1 - clip(q))))
    CFG = [(sp, k) for sp in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7) for k in (1.0, 0.75, 0.5, 0.25)]
    sim = {}
    for Y in years:
        th = res[f'mock {pick}']['theta'][Y]; nr1 = sum(1 for pk, rd, *_ in B.order[Y] if rd == 1)
        for c in CFG:
            pool, slot = forward(Y, B.MOCK, pick, th, rng, *c, sims=300)
            real = np.array([p.get('pick') or 300 for p in pool]); y = (real <= nr1).astype(float)
            ln = np.array([phi((math.log(nr1 + 0.5) - p['lx']) / 0.56) for p in pool])
            lo, hi = np.quantile(slot, [0.1, 0.9], axis=0); cv = [(lo[i] <= real[i] <= hi[i]) for i in range(len(pool)) if pool[i].get('pick') and pool[i]['rank'] <= 150]
            sim[(Y, c)] = dict(q=(slot <= nr1).mean(0), y=y, ln=ln, cov=cv)
        print(Y, 'forward sims done', flush=True)
    grid = {f'sp {c[0]} k {c[1]}': {'r1LogLoss': round(float(np.mean([LL(sim[(Y, c)]['q'], sim[(Y, c)]['y']) for Y in years])), 4),
                                     'range80': round(float(np.mean(np.concatenate([sim[(Y, c)]['cov'] for Y in years]))), 3)} for c in CFG}
    chosen, rows, cov = {}, [], []
    for Y in years:
        c = min(CFG, key=lambda c: np.mean([LL(sim[(y, c)]['q'], sim[(y, c)]['y']) for y in years if y != Y])); chosen[Y] = list(c)
        S = sim[(Y, c)]; rows += [(Y, float(a), float(b), float(t)) for a, b, t in zip(S['q'], S['ln'], S['y'])]; cov += S['cov']
    best = min(CFG, key=lambda c: np.mean([LL(sim[(y, c)]['q'], sim[(y, c)]['y']) for y in years]))
    A = np.array([(r[1], r[2], r[3]) for r in rows])
    brier = lambda q: float(np.mean((q - A[:, 2]) ** 2))
    logl = lambda q: LL(q, A[:, 2])
    bins = [(lo, hi) for lo, hi in ((0, .05), (.05, .25), (.25, .5), (.5, .75), (.75, .95), (.95, 1.01))]
    calib = [{'bin': f'{lo:.2f}-{min(hi, 1):.2f}', 'n': int(((A[:, 0] >= lo) & (A[:, 0] < hi)).sum()),
              'sims': round(float(A[(A[:, 0] >= lo) & (A[:, 0] < hi), 0].mean()), 3), 'real': round(float(A[(A[:, 0] >= lo) & (A[:, 0] < hi), 2].mean()), 3)}
             for lo, hi in bins if ((A[:, 0] >= lo) & (A[:, 0] < hi)).any()]
    byY = {}
    for Y in years:
        kk = np.array([r[0] == Y for r in rows]); y_ = A[kk, 2]
        byY[Y] = (LL(A[kk, 0], y_), LL(A[kk, 1], y_))
    d = -(A[:, 2] * np.log(clip(A[:, 0])) + (1 - A[:, 2]) * np.log(1 - clip(A[:, 0]))) + (A[:, 2] * np.log(clip(A[:, 1])) + (1 - A[:, 2]) * np.log(1 - clip(A[:, 1])))
    r1 = {'n': len(rows), 'heldOutCfg': chosen, 'cfg': {'sp': best[0], 'k': best[1]}, 'grid': grid,
          'brier': {'sims': round(brier(A[:, 0]), 4), 'lognormal .56': round(brier(A[:, 1]), 4)},
          'logLoss': {'sims': round(logl(A[:, 0]), 4), 'lognormal .56': round(logl(A[:, 1]), 4)},
          't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'draftsWon': f'{sum(a < b for a, b in byY.values())}/{len(years)}',
          'byDraft': {Y: [round(a, 4), round(b, 4)] for Y, (a, b) in byY.items()}, 'calibration': calib,
          'range80Coverage': round(float(np.mean(cov)), 3), 'range80N': len(cov)}
    print(json.dumps({k: v for k, v in r1.items() if k != 'byDraft'}, indent=1))
    for v in res.values(): v.pop('_ll')
    json.dump({'_readme': __doc__.strip().split('\n\n')[0], 'spec': pick, 'theta': res[f'mock {pick}']['all'], 'sp': best[0], 'k': best[1], 'sims': SIMS,
               'specs': res, 'tests': tests, 'round1': r1}, open(OUT, 'w'), indent=1)


if __name__ == '__main__':
    main()
