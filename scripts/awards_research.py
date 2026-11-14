# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Award voter models: fit and test every sport's races, write data/awards_fit.json (read by scripts/awards.py).

    python3 scripts/awards_research.py            # all sports
    python3 scripts/awards_research.py nba nhl    # some

Each award has one pre-registered voter model (its COLS in the sport module: the board's value metric plus box
stats, team success and narrative terms) and a null: the board's value metric alone where the board has one in every
past season (NBA VORX / D-XPM, NHL WAR / GSAx, CBB BPM), else box production alone (football yards + touchdowns).
Test: leave one season out, score log P(actual winner); the voter model passes when it beats the null on held-out
seasons (one-sided paired t, Holm across the sport's awards at .05) and wins most seasons. Only passing awards are
published. numpy."""
import json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import awards_engine as E

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'data', 'awards_fit.json')
L2 = 1.0
PREV = {}


def t_sf(t, df):
    """one-sided P(T > t), Student t (Simpson on the density)"""
    if df <= 0: return .5
    c = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
    dens = lambda x: c * (1 + x * x / df) ** (-(df + 1) / 2)
    a, b, n = 0.0, abs(t), 2000
    h = (b - a) / n
    s = dens(a) + dens(b) + sum((4 if i % 2 else 2) * dens(a + i * h) for i in range(1, n))
    half = s * h / 3
    return .5 - half if t >= 0 else .5 + half


def holm(ps, alpha=.05):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    ok = [False] * len(ps)
    for r, i in enumerate(order):
        if ps[i] <= alpha / (len(ps) - r): ok[i] = True
        else: break
    return ok


def specs():
    """{sport: [(award, label, races, cols, null, depth)]}"""
    out = {}
    import awards_nba as NB
    import awards_nhl as NH
    import awards_cbb as CB
    out['nba'] = lambda: (lambda R: [('mvp', 'MVP', R['mvp'], NB.MVP_COLS, ['vorx'], 3),
                                     ('dpoy', 'DPOY', R['dpoy'], NB.DPOY_COLS, ['dxpm'], 3),
                                     ('roy', 'ROY', R['roy'], NB.ROY_COLS, ['vorx'], 3)])(NB.seasons_data())
    out['nhl'] = lambda: (lambda R: [('hart', 'Hart', R['hart'], NH.HART_COLS, ['war'], 3),
                                     ('norris', 'Norris', R['norris'], NH.NORRIS_COLS, ['war'], 3),
                                     ('vezina', 'Vezina', R['vezina'], NH.VEZINA_COLS, ['gsax'], 3),
                                     ('calder', 'Calder', R['calder'], NH.CALDER_COLS, ['war'], 3)])(NH.seasons_data())
    out['cbb'] = lambda: (lambda R: [('wooden', 'Wooden', R['wooden'], CB.WOODEN_COLS, ['bpm'], 1)])(CB.seasons_data())
    try:
        import awards_football as FB
        if os.path.exists(FB.POOL % 'cfb'):
            out['cfb'] = lambda: (lambda R: [('heisman', 'Heisman', R['heisman'], FB.HEIS_COLS, FB.NULL_COLS, 3)])(FB.cfb_races())
        if os.path.exists(FB.POOL % 'nfl'):
            out['nfl'] = lambda: (lambda R: [(a, FB.NFL_LABEL[a], R[a], FB.NFL_COLS[a], FB.NFL_NULL[a], 1) for a in FB.NFL_COLS])(FB.nfl_races())
    except (ImportError, AttributeError):
        pass
    return out


def summarise(o):
    n = len(o)
    return {'n': n, 'll': round(sum(x['ll'] for x in o) / n, 3), 'hit': sum(x['hit'] for x in o),
            'pw': round(sum(x['pw'] for x in o) / n, 3), 'fav': round(sum(x['fav_p'] for x in o) / n, 3)}


def run_sport(sport, build):
    items = build()
    PREV[sport] = prev_counts(sport, items)
    res, ps = [], []
    for aw, label, races, cols, null, depth in items:
        S = [s for s, _, _ in races]
        rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
        full = E.loso(rr(cols), S, l2=L2, depth=depth)
        base = E.loso(rr(null), S, l2=L2, depth=depth)
        pr = E.paired(full, base)
        p = t_sf(pr['t'], pr['n'] - 1)
        b, mu, sd = E.fit([x for x in rr(cols) if x[1]], l2=L2, depth=depth)
        res.append({'award': aw, 'label': label, 'cols': cols, 'null': null, 'depth': depth,
                    'b': [round(v, 5) for v in b], 'mu': [round(v, 5) for v in mu], 'sd': [round(v, 5) for v in sd],
                    'seasons': [min(S), max(S)], 'test': {'model': summarise(full), 'null': summarise(base),
                    'gain': pr['gain'], 't': pr['t'], 'p': round(p, 4), 'wins': pr['wins'],
                    'by': [{'s': x['season'], 'pw': round(x['pw'], 3), 'pw0': round(y['pw'], 3), 'hit': x['hit']}
                           for x, y in zip(full, base)]}})
        ps.append(p)
    ok = holm(ps)
    for r, k in zip(res, ok):
        r['test']['pass'] = bool(k and r['test']['gain'] > 0 and r['test']['wins'] * 2 > r['test']['model']['n'])
        t = r['test']
        print(f"{sport} {r['label']:8s} held-out log P(winner) {t['model']['ll']:.3f} vs null {t['null']['ll']:.3f} "
              f"gain {t['gain']:+.3f} t {t['t']} p {t['p']} wins {t['wins']}/{t['model']['n']} "
              f"hit {t['model']['hit']} vs {t['null']['hit']}  {'PASS' if t['pass'] else 'fail'}", flush=True)
    return res


def prev_counts(sport, items):
    """award wins by player through the last finished season (the voter models' prior-award terms), PRE included"""
    import names as NM
    out = {}
    pre = {}
    if sport == 'nba':
        import awards_nba as NB
        pre = {'mvp': NB.PRE_MVP, 'dpoy': NB.PRE_DPOY}
    elif sport == 'nhl':
        import awards_nhl as NH
        pre = {a: {} for a in NH.PRE}
        for a, ns in NH.PRE.items():
            for n in ns: pre[a][NM.key(n)] = pre[a].get(NM.key(n), 0) + 1
    elif sport == 'nfl':
        import awards_football as FB
        pre = {'mvp': dict(FB.PRE_MVP)}
    for aw, _, races, _, _, _ in items:
        c = dict(pre.get(aw, {}))
        for _, pool, o in races:
            if not o: continue
            r = pool[o[0]]
            k = r['id'] if sport == 'nba' else NM.key(r['n'])
            c[k] = c.get(k, 0) + 1
        out[aw] = c
    return out


def main(argv):
    sp = specs()
    want = [a for a in argv if a in sp] or list(sp)
    cur = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for s in want:
        cur[s] = {r['award']: r for r in run_sport(s, sp[s])}
        cur[s]['_prev'] = PREV[s]
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


if __name__ == '__main__':
    main(sys.argv[1:])
