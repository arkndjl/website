# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NHL awards research, Nov 23 2026 (pre-registration: prereg.md beside this file).

    python3 scripts/research/awards_nov23/nhl/run.py races     # new races: test, Holm over the NHL list, merge into data/awards_fit.json
    python3 scripts/research/awards_nov23/nhl/run.py drivers   # driver add-ons to Hart / Norris / Vezina / Calder (report only)
    python3 scripts/research/awards_nov23/nhl/run.py titles    # Art Ross / Rocket Richard as-of calibration

Results -> results.json beside this file. numpy."""
import collections, gzip, json, math, os, random, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
sys.path.insert(0, SCR)
import awards_engine as E
import awards_nhl as A
import awards_nhl_more as M
import names as NM
from awards_research import t_sf, holm, summarise, OUT, L2
from awards_more import test, gate

RES = os.path.join(HERE, 'results.json')
ROOT = os.path.join(SCR, '..')
CACHE = os.path.join(SCR, '.cache', 'awards', 'nhl_landing')


def save(key, val):
    cur = json.load(open(RES)) if os.path.exists(RES) else {}
    cur[key] = val
    json.dump(cur, open(RES, 'w'), indent=1, sort_keys=True)


# ------------------------------------------------------------------ top-k by group (All-Star)

def test_groups(rs, cols, null):
    """rs: [(season, group, pool, named)]; held out by season, the season's groups summed"""
    X = lambda p, cs: [[r[c] for c in cs] for r in p]
    seasons = sorted({s for s, _, _, o in rs if o})

    def run(cs):
        out = []
        for s in seasons:
            tr = [(X(p, cs), o) for t, _, p, o in rs if t != s and o]
            b, mu, sd = E.fit(tr, l2=L2, depth=max(M.AS_K.values()))
            ll, hit, k = 0.0, 0, 0
            for t, g, p, o in rs:
                if t != s or not o: continue
                Z = X(p, cs)
                ll += E.loglik_order(Z, o, b, mu, sd, len(o))
                z = [sum(bk * ((xk - m) / v) for bk, xk, m, v in zip(b, x, mu, sd)) for x in Z]
                top = set(sorted(range(len(z)), key=lambda j: -z[j])[:len(o)])
                hit += len(top & set(o)); k += len(o)
            out.append({'season': s, 'll': ll, 'hit': hit, 'pw': hit / k, 'fav_p': 0.0})
        return out

    full, base = run(cols), run(null)
    pr = E.paired(full, base)
    b, mu, sd = E.fit([(X(p, cols), o) for _, _, p, o in rs if o], l2=L2, depth=max(M.AS_K.values()))
    return {'cols': cols, 'null': null, 'depth': max(M.AS_K.values()), 'b': [round(v, 5) for v in b],
            'mu': [round(v, 5) for v in mu], 'sd': [round(v, 5) for v in sd], 'seasons': [seasons[0], seasons[-1]],
            'k': sum(M.AS_K.values()), 'kg': M.AS_K,
            'test': {'model': summarise(full), 'null': summarise(base), 'gain': pr['gain'], 't': pr['t'],
                     'p': round(t_sf(pr['t'], pr['n'] - 1), 4), 'wins': pr['wins'],
                     'by': [{'s': x['season'], 'pw': round(x['pw'], 3), 'pw0': round(y['pw'], 3), 'hit': x['hit']}
                            for x, y in zip(full, base)]}}


def races_cmd():
    R, prev = M.races()
    cur = json.load(open(OUT))
    new = {}
    for aw, label, cols, null, depth in (('selke', 'Selke', M.SELKE_COLS, M.SELKE_NULL, 3),
                                         ('byng', 'Lady Byng', M.BYNG_COLS, M.BYNG_NULL, 3),
                                         ('lindsay', 'Ted Lindsay', M.LINDSAY_COLS, M.LINDSAY_NULL, 1),
                                         ('adams', 'Jack Adams', M.ADAMS_COLS, M.ADAMS_NULL, 1)):
        new[aw] = dict(test(R[aw], cols, null, depth), award=aw, label=label, more=True)
    new['allstar'] = dict(test_groups(R['allstar'], M.AS_COLS, M.AS_NULL), award='allstar', label='All-Star', more=True)
    gate(cur, 'nhl', new)
    for a in new:
        if a == 'allstar':
            t = new[a]['test']
            print(f"  allstar: named {t['model']['hit']} of {len(t['by']) * 12} vs null {t['null']['hit']}")
    cur['nhl'].update(new)
    pv = cur['nhl'].setdefault('_prev', {})
    for a in ('selke', 'byng', 'allstar', 'lindsay', 'adams'): pv[a] = prev.get(a, {})
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    save('races', {a: {'cols': v['cols'], 'null': v['null'], 'test': {k: x for k, x in v['test'].items() if k != 'by'}}
                   for a, v in new.items()})
    print('wrote', OUT)


# ------------------------------------------------------------------ drivers

def landing(pid):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{pid}.json')
    if os.path.exists(fn): return json.load(open(fn))
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(f'https://api-web.nhle.com/v1/player/{pid}/landing',
                       headers={'User-Agent': 'arkndjl.net-arkboard/1.0'}), timeout=30).read())
    except Exception as e:
        print('landing', pid, e); d = {}
    json.dump(d, open(fn, 'w')); time.sleep(.3)
    return d


def draft_grades():
    """{NHL id: (draft year, overall pick, draft-time FV)}: out-of-class grade for classes 2008-19, the fit's grade after"""
    import numpy as np
    import hockey_prospects as HP
    W = HP.war_tables()
    rows = HP.read_rows(W)
    HP.nhl_so_far(rows, W)
    sc = HP.outcome_scale(rows)
    fit = json.load(open(os.path.join(ROOT, 'data', 'hockey_fit.json')))
    kept = fit['kept']
    F = [HP.feats(r) for r in rows]
    cls = np.array([r['year'] for r in rows])
    tr = np.array([HP.FIRST <= r['year'] <= HP.LAST_FIT for r in rows])
    y = np.array([HP.fv_of(r, sc) for r in rows])
    babs = HP.ols(np.array([[F[i][c] for c in HP.ABS] for i in np.where(tr)[0]]), y[tr])
    S = HP.class_strength(F, cls, babs)
    Smean = float(np.mean([S[c] for c in S if HP.FIRST <= c <= HP.LAST_FIT]))
    HP.set_cs(F, cls, S, Smean)
    Ftr = [F[i] for i in np.where(tr)[0]]
    p_tr = np.clip(HP.loco(Ftr, y[tr], cls[tr], kept), 20, 80)
    b = HP.ols(np.array([[f[c] for c in kept] for f in Ftr]), y[tr])
    out, j = {}, 0
    for i, r in enumerate(rows):
        if tr[i]: g = float(p_tr[j]); j += 1
        else: g = float(np.clip(HP.pred(b, np.array([[F[i][c] for c in kept]]))[0], 20, 80))
        if r.get('id'): out[str(r['id'])] = (r['year'], r['pick'], g)
    return out


def goalie_wins():
    """{(season, goalie id): wins} from the game archive (the winning side's goalie with the most ice time)"""
    G = json.load(gzip.open(os.path.join(SCR, 'nhl_games_hist.json.gz')))
    w = collections.Counter()
    for g in G:
        if g['po'] or not g.get('final'): continue
        gl = g['gl'] if isinstance(g['gl'], dict) else eval(g['gl'])
        sd = 'h' if g['hs'] > g['as'] else 'a'
        if gl.get(sd): w[(g['S'], str(max(gl[sd], key=lambda x: x[3])[0]))] += 1
    return w


def add_drivers(R):
    """the pre-registered driver columns on every row of the four existing races"""
    dg = draft_grades()
    gw = goalie_wins()
    war = {s: {r['id']: r for r in A.war(s)} for s in range(A.FIRST - 1, A.LAST + 1)}
    vs = {s: A.votes(s) for s in range(A.FIRST - 1, A.LAST + 1)}
    for aw in ('hart', 'norris', 'vezina', 'calder'):
        for s, pool, _ in R[aw]:
            M.attach_hr(pool, s)
            W = list(war[s].values())
            pmax, gmax = max(r.get('pts') or 0 for r in W), max(r.get('g') or 0 for r in W)
            dpmax = max((r.get('pts') or 0) for r in W if r['grp'] == 'D')
            wmax = max((v for (t, _), v in gw.items() if t == s), default=0)
            st = A.standings(s)
            rank = {t: i + 1 for i, t in enumerate(sorted(st, key=lambda t: -st[t]))}
            pv = vs[s - 1].get(aw, [])
            top = pv[0][2] if pv else 1
            share = {NM.key(n): v / top for n, _, v in pv}
            for r in pool:
                q = war[s - 1].get(r['id'], {})
                r['pwar0'] = (q.get('gsax') or 0) if (aw == 'vezina') else (q.get('war') or 0)
                r['prevvote'] = share.get(NM.key(r['n']), 0.0)
                if aw == 'hart': r['title'] = 1.0 if (r['pts'] >= pmax or r['g'] >= gmax) else 0.0
                elif aw == 'norris': r['title'] = 1.0 if r['pts'] >= dpmax else 0.0
                elif aw == 'vezina': r['title'] = 1.0 if gw.get((s, r['id']), 0) >= wmax else 0.0
                else: r['title'] = 0.0
                r['trank'] = rank.get(r['tm'].split('/')[-1], 16)
                r['age'] = (war[s].get(r['id']) or {}).get('age') or 24
                if aw == 'calder':
                    d = dg.get(str(r['id']))
                    if d is None:
                        dd = (landing(r['id']) or {}).get('draftDetails') or {}
                        ov = dd.get('overallPick')
                        d = (dd.get('year'), ov, None) if ov else (None, None, None)
                    r['lslot'] = math.log(d[1]) if d[1] else math.log(225)
                    # draft-time FV: the grade where the class is in the hockey prospects rows, else the slot-only
                    # mapping of the draft model (const + slot terms) for picks before 2008, 25 undrafted
                    r['dfv'] = d[2] if d[2] is not None else (25.0 if not d[1] else None)
                    r['_dyear'] = d[0]
    # slot-only grade for picks before the 2008 class (no draft-year line in the rows)
    fit = json.load(open(os.path.join(ROOT, 'data', 'hockey_fit.json')))['coef']
    for s, pool, _ in R['calder']:
        for r in pool:
            if r['dfv'] is None:
                ls = r['lslot']
                r['dfv'] = min(max(fit['const'] + fit['ls'] * ls + fit['ls2'] * ls * ls + fit['D'] * (r['grp'] == 'D') + fit['G'] * (r['grp'] == 'G'), 20), 80)


def bo_held_out():
    """{(NHL id, target season): BO%} from the NHL breakout model's kept signals, each target season predicted by a fit
    that left that season's outcomes out (the research's leave-one-season-out; the live model is not touched)"""
    import numpy as np
    import breakout_lib as L
    import nhl_breakout as B
    import nhl_breakout_research as BR
    fit = json.load(open(os.path.join(ROOT, 'data', 'nhl_breakout_fit.json')))
    Lq, keep = fit['breakout']['L'], fit['breakout']['keep']
    cur = B.D.current_season()
    import awards_asof as AS
    for S in range(BR.Y0 - 1, cur):           # nhl_breakout.pull asks for limit=-1, which the API now caps at 100 rows:
        path = os.path.join(B.CACHE, f'{S}.json.gz')   # fill its cache with every row (same format) before season() reads it
        if os.path.exists(path): continue
        out = {}
        for rep, fields in B.REPORTS.items():
            for r in AS.stats_pages(f'skater/{rep}', f'seasonId={S - 1}{S} and gameTypeId=2'):
                o = out.setdefault(str(r['playerId']), {})
                for k in fields: o[k] = r.get(k)
        os.makedirs(B.CACHE, exist_ok=True)
        B.D.save(path, out)
        print('bo pull', S, len(out), flush=True)
    P = {}
    for S in range(BR.Y0, cur):
        for pid, o in B.season(S).items(): P[(pid, S)] = o
    C = B.career(last=cur - 1)
    by = {}
    for (pid, y), o in P.items(): by.setdefault(y, {})[pid] = o
    rows = []
    for y in range(BR.Y_BO, cur - 1):
        for pid, a in by[y].items():
            if a['war'] is None or a['tmin'] < B.ROW_MIN * a['gmax'] / 82: continue
            if max(B.peak(C, pid, y) or -9, B.shr(a)) >= Lq: continue
            b = by[y + 1].get(pid)
            hit = 1.0 if (b and b['war'] is not None and b['tmin'] >= B.ROLE_MIN * b['gmax'] / 82 and B.shr(b) >= Lq) else 0.0
            f = B.bo_feats(a, B.history(P, pid, y), None, None)
            rows.append((pid, y + 1, hit, f['base'] + [v for k in keep for v in f[k]]))
    X = np.array([r[3] for r in rows], float); yv = np.array([r[2] for r in rows]); S = np.array([r[1] for r in rows], float)
    ho = np.zeros(len(yv))
    BR.run_logit(X, yv, S, ho)
    print('bo rows', len(rows), 'rate', round(float(yv.mean()), 4), flush=True)
    return {(pid, t): float(p) for (pid, t, _, _), p in zip(rows, ho)}


def add_bo(R):
    bo = bo_held_out()
    n = 0
    for s, pool, _ in R['calder']:
        for r in pool:
            v = bo.get((str(r['id']), s))
            r['bo'] = v if v is not None else 0.0
            r['bo_na'] = 0.0 if v is not None else 1.0
            n += v is not None
    print('calder rows with a BO%', n, flush=True)


DRIVERS = {'calder': ['lslot', 'dfv', 'age', 'pwar0', 'pm', 'trank', 'bo'],
           'hart': ['pwar0', 'pm', 'prevvote', 'title', 'trank'],
           'norris': ['pwar0', 'pm', 'prevvote', 'title', 'trank', 'gfrac'],
           'vezina': ['pwar0', 'pm', 'prevvote', 'title', 'trank', 'gfrac']}


def drivers_cmd(extra=None):
    R = A.seasons_data()
    add_drivers(R)
    if extra: extra(R)
    fit = json.load(open(OUT))['nhl']
    res, ps, keys = {}, [], []
    for aw, ds in DRIVERS.items():
        races = R[aw]
        S = [s for s, _, _ in races]
        rr = lambda cs: [([[r[c] for c in cs] for r in p], o) for _, p, o in races]
        cols = fit[aw]['cols']
        base = E.loso(rr(cols), S, l2=L2, depth=3)
        for d in ds:
            if d in cols: continue
            dc = [d, 'bo_na'] if d == 'bo' else [d]
            if any(c not in races[0][1][0] for c in dc): print('skip', aw, d); continue
            full = E.loso(rr(cols + dc), S, l2=L2, depth=3)
            pr = E.paired(full, base)
            p = t_sf(pr['t'], pr['n'] - 1)
            b, mu, sd = E.fit([x for x in rr(cols + dc) if x[1]], l2=L2, depth=3)
            res[f'{aw}:{d}'] = {'gain': pr['gain'], 't': pr['t'], 'p': round(p, 4), 'wins': pr['wins'], 'n': pr['n'],
                                'hit': sum(x['hit'] for x in full), 'hit0': sum(x['hit'] for x in base),
                                'll': round(sum(x['ll'] for x in full) / len(full), 3), 'll0': round(sum(x['ll'] for x in base) / len(base), 3),
                                'coef': round(b[len(cols)], 3)}
            ps.append(p); keys.append(f'{aw}:{d}')
    ok = holm(ps)
    for k, o in zip(keys, ok):
        r = res[k]
        r['pass'] = bool(o and r['gain'] > 0 and r['wins'] * 2 > r['n'])
        print(f"{k:16s} gain {r['gain']:+.3f} t {r['t']:5.2f} p {r['p']:.4f} wins {r['wins']}/{r['n']} hit {r['hit']} vs {r['hit0']} "
              f"coef {r['coef']:+.3f} (Holm over {len(keys)})  {'PASS' if r['pass'] else 'fail'}", flush=True)
    save('drivers', res)
    return res


# ------------------------------------------------------------------ stat titles (as-of)

TITLES = (('artross', 'Art Ross', 'pts', 'g'), ('richard', 'Rocket Richard', 'g', None))


def titles_cmd(sims=1000):
    import awards as AW
    import awards_asof as B
    G, CP = B.nhl_checkpoints()
    seasons = [S for S in sorted(CP) if S >= 2011]
    war = {S: {r['id']: r for r in A.war(S)} for S in range(2010, 2027)}
    rows = []
    for S in seasons:
        full, _ = B.nhl_lines(G, S, 3, CP[S][3])
        sk = [r for r in full.values() if r['grp'] != 'G']
        mx = max(r['pts'] for r in sk)
        ar = [r for r in sk if r['pts'] == mx]
        mg = max(r['g'] for r in ar)
        win = {'artross': {r['id'] for r in ar if r['g'] == mg}, 'richard': {r['id'] for r in sk if r['g'] == max(x['g'] for x in sk)}}
        Gs = min(max(collections.Counter([g['h'] for g in G if g['S'] == S] + [g['a'] for g in G if g['S'] == S]).values()), 82)
        if S == 2020: Gs = 70
        last = war[S - 1]
        for ci in range(3):
            L, T = B.nhl_lines(G, S, ci, CP[S][ci])
            teams = {}
            for t, (pts, gp) in T.items():
                left = max(Gs - gp, 0)
                teams[t] = (pts, gp * 2, 2 * B.shrunk_left(pts / 2, gp, Gs, 'nhl'), math.sqrt(left * 1.0 + (left * .25 * .2) ** 2), 2 * Gs)
            cands = []
            for i, r in L.items():
                if r['grp'] == 'G' or r['tm'] not in teams: continue
                q = last.get(i, {})
                cands.append({'id': i, 'n': r['n'], 'tm': r['tm'], 'grp': r['grp'], 'gp': r['gp'], 'tg': teams[r['tm']][1] / 2,
                              'toi': r['toi'], 'war': 0.0, 'pwar': 0.0, 'gd': 0.0, 'pts': r['pts'], 'g': r['g'], 'gsax': 0.0,
                              'ppg0': (q.get('pts') or 0) / q['gp'] if q.get('gp') else None,
                              'gpg0': (q.get('g') or 0) / q['gp'] if q.get('gp') else None, 'gsx0': None, 'key': NM.key(r['n'])})
            draw = AW.nhl_draw({}, teams, G=Gs)
            for aw, _, metric, tie in TITLES:
                pool = AW.title_pool(cands, metric, tie)
                out = {'s': S, 'cp': ci, 'aw': aw}
                for mode in ('pred', 'conv'):
                    AW.SEASON_ONLY = mode == 'conv'
                    try: p = AW.title_p(pool, draw, metric, tie, random.Random(S * 10 + ci), sims)
                    finally: AW.SEASON_ONLY = False
                    pw = sum(pi for c, pi in zip(pool, p) if c['id'] in win[aw])
                    j = max(range(len(p)), key=p.__getitem__)
                    out[mode] = {'pw': round(pw, 4), 'll': math.log(max(pw, 1e-3)), 'favp': round(p[j], 4), 'hit': int(pool[j]['id'] in win[aw])}
                rows.append(out)
                print(S, ci, aw, 'pred', out['pred'], 'conv', out['conv'], flush=True)
    summ = {}
    for aw, label, _, _ in TITLES:
        R = [r for r in rows if r['aw'] == aw]
        o = {'n': len(R)}
        for mode in ('pred', 'conv'):
            o[mode] = {'ll': round(sum(r[mode]['ll'] for r in R) / len(R), 3), 'hit': sum(r[mode]['hit'] for r in R),
                       'favp': round(sum(r[mode]['favp'] for r in R) / len(R), 3), 'pw': round(sum(r[mode]['pw'] for r in R) / len(R), 3),
                       'by_cp': [{'cp': c, 'hit': sum(r[mode]['hit'] for r in R if r['cp'] == c), 'n': sum(1 for r in R if r['cp'] == c),
                                  'favp': round(sum(r[mode]['favp'] for r in R if r['cp'] == c) / max(1, sum(1 for r in R if r['cp'] == c)), 3)}
                                 for c in range(3)]}
            h = o[mode]['hit'] / len(R)
            o[mode]['cal_z'] = round((o[mode]['favp'] - h) / math.sqrt(max(h * (1 - h), .01) / len(R)), 2)
        # predictive vs conviction, by season (checkpoints averaged): one-sided t that predictive is better
        byS = collections.defaultdict(list)
        for r in R: byS[r['s']].append(r['pred']['ll'] - r['conv']['ll'])
        d = [sum(v) / len(v) for v in byS.values()]
        m = sum(d) / len(d); v = sum((x - m) ** 2 for x in d) / (len(d) - 1)
        o['gain'] = round(m, 4); o['t'] = round(m / math.sqrt(v / len(d)), 2) if v > 0 else 0.0
        o['wins'] = sum(x > 0 for x in d); o['seasons'] = len(d)
        # shown as predictive when it is not worse than this-season-only (t > -2) and its favourite is calibrated (|z| < 2)
        o['pass'] = bool(o['t'] > -2 and abs(o['pred']['cal_z']) < 2)
        summ[aw] = o
        print(label, json.dumps({k: v for k, v in o.items()}), flush=True)
    save('titles', {'summary': summ, 'rows': rows})
    cur = json.load(open(OUT))
    for aw, label, metric, _ in TITLES:
        o = summ[aw]
        P = o['pred']
        about = (f"P(lead): the share of {AW.SIMS:,} simulated rests of the season in which he leads the league in "
                 f"{'points (goals break a tie)' if aw == 'artross' else 'goals'}, rates blended toward last season. "
                 f"As-of test {seasons[0]}-{seasons[-1]} at a quarter, half and three quarters of the season: the favourite "
                 f"had {P['favp']:.0%} on average and led {P['hit']} of {o['n']} times.")
        cur['nhl'][aw] = {'award': aw, 'label': label, 'stat': True, 'more': True, 'null': [metric], 'about': about,
                          'seasons': [seasons[0], seasons[-1]], 'test': {k: v for k, v in o.items() if k != 'pass'} | {'pass': o['pass']}}
    json.dump(cur, open(OUT, 'w'), indent=1, sort_keys=True)
    print('wrote', OUT)


# ------------------------------------------------------------------ awards -> hockey prospects FV

def calder_held_out():
    """{(NHL id, season): Calder P(win)} at season end, each season from a voter model fit leaving that season out"""
    R = A.seasons_data()
    cols = json.load(open(OUT))['nhl']['calder']['cols']
    races = R['calder']
    out = {}
    for s, pool, o in races:
        tr = [([[r[c] for c in cols] for r in p], q) for t, p, q in races if t != s and q]
        b, mu, sd = E.fit(tr, l2=L2, depth=3)
        for r, p in zip(pool, E.prob([[r[c] for c in cols] for r in pool], b, mu, sd)): out[(str(r['id']), s)] = p
    return out


def fv_cmd():
    """the Calder model's held-out P(win) in a pick's stage season as an input to the stage-k FV (k = 1-3), on the
    hockey prospects class-out rule (t >= 2, 8 of 12 classes) plus the first-64-picks check"""
    import numpy as np
    import hockey_prospects as HP
    cp = calder_held_out()
    W = HP.war_tables()
    rows = HP.read_rows(W)
    HP.nhl_so_far(rows, W)
    sc = HP.outcome_scale(rows)
    tr = [r for r in rows if HP.FIRST <= r['year'] <= HP.LAST_FIT]
    y = np.array([HP.fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    F = [HP.feats(r) for r in tr]
    fit = json.load(open(os.path.join(ROOT, 'data', 'hockey_fit.json')))
    kept = fit['kept']
    babs = HP.ols(np.array([[f[c] for c in HP.ABS] for f in F]), y)
    S = HP.class_strength(F, cls, babs); HP.set_cs(F, cls, S, float(np.mean(list(S.values()))))
    _, p0 = HP.score(F, y, cls, kept)
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    res, ps, keys = {}, [], []
    for k in (1, 2, 3):
        sub = [r for r in tr if r['year'] + k < 2027 and HP.onboard(r, k)]
        Fk = [HP.stage_feats(r, k, oof[id(r)]) for r in sub]
        for f, r in zip(Fk, sub): f['calp'] = cp.get((str(r['id']), r['year'] + k), 0.0)
        yk = np.array([HP.fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub])
        base = [c for c in fit['stages'][str(k)]['kept'] if c != 'comp']
        s0, q0 = HP.score(Fk, yk, ck, base)
        s1, q1 = HP.score(Fk, yk, ck, base + ['calp'])
        d = s0 - s1
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() > 0 else 0.0
        top = np.array([r['pick'] <= 64 for r in sub])
        res[k] = {'gain': round(float(d.mean()), 3), 't': round(t, 2), 'wins': int((d > 0).sum()), 'of': len(d),
                  'p': round(t_sf(t, len(d) - 1), 4), 'n_calp': int(sum(f['calp'] > 0 for f in Fk)),
                  'top64_mse': [round(float(np.mean((q0[top] - yk[top]) ** 2)), 2), round(float(np.mean((q1[top] - yk[top]) ** 2)), 2)]}
        ps.append(res[k]['p']); keys.append(k)
    ok = holm(ps)
    for k, o in zip(keys, ok):
        r = res[k]
        r['pass'] = bool(o and r['t'] >= 2 and r['wins'] >= 8 and r['top64_mse'][1] < r['top64_mse'][0])
        print(f"stage {k}: class-out MSE gain {r['gain']:+.3f} t {r['t']} wins {r['wins']}/{r['of']} p {r['p']} "
              f"picks with a Calder P {r['n_calp']} top-64 MSE {r['top64_mse']}  {'PASS' if r['pass'] else 'fail'}", flush=True)
    save('fv', res)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'races'
    if cmd == 'drivers': drivers_cmd(add_bo if '--no-bo' not in sys.argv else None)
    else: {'races': races_cmd, 'titles': titles_cmd, 'fv': fv_cmd}.get(cmd, lambda: print('unknown', cmd))()
