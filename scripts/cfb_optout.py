"""CFB bowl opt-outs: who sits a bowl, what it costs, and whether the game model (and the close) price it.

Data (all free ESPN):
  boxes      scripts/.cache/cfb/espn_hist/box/<id>.json (scripts/cfb_roster_hist.py): who recorded a stat for whom. Before
             2024 only passers, rushers and receivers are listed, so absence is measured on offense.
  prospects  ESPN NFL draft prospects by draft year (overall rank, pick, college athlete id), pulled here into
             scripts/.cache/cfb/draft_espn/<year>.json. Draft year S+1 is the class a bowl of season S loses.
  transfers  a player who records a stat for another FBS team the next season.
Steps:
  1. Player level: each regular (2+ regular-season games with a stat, 5%+ of his team's yardage) on a bowl team, CFP games
     excluded; absent = not in the bowl box. P(out) by draft tier, transfer and era (logistic, pooled), against the
     same player's no-draft, no-transfer baseline (injuries happen in November too).
  2. Team level: expected loss = sum of excess P(out) x value, two parts: draft talent (all positions, tier weights)
     and production share (offense, transfers and prospects alike).
  3. Price: bowl residual (result minus the walk-forward model, scripts/data/games_wf/cfb.json.gz) on the loss gap,
     fit on bowls before each season (walk-forward), scored on 2019-25; and the same against the close.
  python3 scripts/cfb_optout.py --pull [first] [last]     # draft prospects for draft years first..last
  python3 scripts/cfb_optout.py                            # research -> data/cfb_optout.json, scripts/data/cfb_bowl_adj.json
  python3 scripts/cfb_optout.py --wf                       # walk-forward bowl terms into scripts/data/games_wf/cfb.json.gz
  python3 scripts/cfb_optout.py --hc <season>              # season-start head coaches -> scripts/data/cfb_hc_start.json
"""
import gzip
import json
import math
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_espn_hist as E  # noqa: E402

ROOT = E.ROOT
BOX = os.path.join(E.DIR, 'box')
DRAFT = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'draft_espn')
NFL = 'http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons'


# ---- pulls ---------------------------------------------------------------------------------------------------------
def pull_draft(y):
    p = os.path.join(DRAFT, f'{y}.json')
    if os.path.exists(p):
        return
    picks = {}
    for rd in (E.get(f'{NFL}/{y}/draft/rounds?limit=20') or {}).get('items', []):
        for k in rd['picks']:
            if 'athlete' in k:
                picks[re.search(r'athletes/(\d+)', k['athlete']['$ref'])[1]] = k['overall']
    refs, page = [], 1
    while True:
        d = E.get(f'{NFL}/{y}/draft/athletes?limit=100&page={page}')
        if not d:
            break
        refs += [x['$ref'] for x in d['items']]
        if page >= d['pageCount']:
            break
        page += 1

    def one(ref):
        a = E.get(ref)
        if not a:
            return None
        at = {x['name']: x.get('value') for x in a.get('attributes') or []}
        cid = re.search(r'athletes/(\d+)', (a.get('athlete') or {}).get('$ref', ''))
        tid = re.search(r'teams/(\d+)', (a.get('team') or {}).get('$ref', ''))
        return {'did': a['id'], 'cid': cid[1] if cid else None, 'tid': tid[1] if tid else None, 'n': a.get('displayName'),
                'pos': (a.get('position') or {}).get('abbreviation'), 'ovr': at.get('overall'), 'grade': at.get('grade'),
                'pick': picks.get(a['id'])}
    with ThreadPoolExecutor(8) as ex:
        rows = [x for x in ex.map(one, refs) if x]
    with open(p, 'w') as f:
        json.dump(rows, f)
    print(y, len(rows), 'prospects', sum(1 for x in rows if x['pick']), 'picked', flush=True)


# ---- data ----------------------------------------------------------------------------------------------------------
def board(S):
    out = []
    for f in sorted(os.listdir(E.DIR)):
        if f.startswith(f'sb{S}_80_'):
            out += json.load(open(os.path.join(E.DIR, f)))
    seen, games = set(), []
    for g in out:
        if g['id'] not in seen:
            seen.add(g['id']); games.append(g)
    return games


def is_cfp(S, g):
    n = (g.get('note') or '').upper()
    return bool(re.search(r'CFP|PLAYOFF|NATIONAL CHAMPIONSHIP', n)) or (S == 2017 and 'ROSE BOWL' in n)


def box(i):
    p = os.path.join(BOX, f'{i}.json')
    return json.load(open(p)) if os.path.exists(p) else None


def yds(r):
    return r.get('pas_YDS', 0) + r.get('rus_YDS', 0) + r.get('rec_YDS', 0)


def season(S, nxt=True):
    """Regulars on every bowl team of season S and whether each sat the bowl; their draft tier and transfer status."""
    games = board(S)
    reg = sorted((g for g in games if g['st'] == 2 and g['done']), key=lambda g: g['date'])
    post = [g for g in games if g['st'] == 3 and g['done']]
    agg = defaultdict(lambda: defaultdict(lambda: {'g': 0, 'yds': 0.0, 'n': None, 'last': 0}))
    tg = defaultdict(list)
    for g in reg:
        b = box(g['id'])
        if not b:
            continue
        for t, P in b.items():
            tg[t].append(g['id'])
            k = len(tg[t])
            for aid, r in P.items():
                a = agg[t][aid]; a['g'] += 1; a['yds'] += yds(r); a['n'] = r.get('n'); a['last'] = k
    pros = {}
    p = os.path.join(DRAFT, f'{S + 1}.json')
    for x in (json.load(open(p)) if os.path.exists(p) else []):
        if x['cid']:
            rk = x['ovr'] or (x['pick'] and 30 + x['pick']) or 400
            pros[x['cid']] = {'rk': rk, 'pick': x['pick'], 'pos': x['pos']}
    after = defaultdict(set)                   # player -> teams he recorded a stat for next season
    if nxt:
        for g in board(S + 1):
            b = box(g['id']) if g['done'] else None
            for t, P in (b or {}).items():
                for aid in P:
                    after[aid].add(t)
    rows = []
    for g in post:
        b = box(g['id'])
        if not b:
            continue
        for t in (g['h'], g['a']):
            if t not in agg or len(tg[t]) < 6:
                continue
            tot = sum(a['yds'] for a in agg[t].values()) or 1
            played = set((b.get(t) or {}).keys())
            for aid, a in agg[t].items():
                share = a['yds'] / tot
                pr = pros.get(aid)
                if a['g'] < 2 or (share < 0.05 and not pr):
                    continue
                rows.append({'S': S, 'gid': g['id'], 't': t, 'opp': g['a'] if t == g['h'] else g['h'], 'cfp': is_cfp(S, g),
                             'aid': aid, 'n': a['n'], 'share': round(share, 4), 'obs': share >= 0.05, 'late': a['last'] >= len(tg[t]) - 2,
                             'rk': pr['rk'] if pr else None, 'pick': pr['pick'] if pr else None,
                             'xfer': bool(after.get(aid) and t not in after[aid]) if nxt else None,
                             'back': bool(t in after.get(aid, ())), 'out': aid not in played})
    return rows


def tier(rk):
    return 0 if rk is None else 1 if rk <= 32 else 2 if rk <= 100 else 3 if rk <= 250 else 4


def era(S):
    return 0 if S <= 2019 else 1 if S <= 2022 else 2


def talent(rk):
    """Draft talent of a prospect by ESPN overall rank (pre-set: 1.0 at #1, .65 at #32, .26 at #100, .04 at #250)."""
    return math.exp(-rk / 75) if rk is not None else 0.0


CELLS = lambda x: (tier(x['rk']), bool(x['xfer']))


def rates(rows, k=20):
    """P(out) by (draft tier, transfer) from observed regulars, each cell shrunk toward its tier's pooled rate (k
    players of weight), and the no-draft, no-transfer baseline."""
    obs = [x for x in rows if x['late'] and x['obs'] and not x['cfp']]
    base = sum(x['out'] for x in obs if CELLS(x) == (0, False)) / max(1, sum(1 for x in obs if CELLS(x) == (0, False)))
    pool = sum(x['out'] for x in obs) / max(1, len(obs))
    n, o = defaultdict(int), defaultdict(int)
    for x in obs:
        n[CELLS(x)] += 1; o[CELLS(x)] += x['out']
    tiers = {}
    for t in range(5):
        nn = sum(v for c, v in n.items() if c[0] == t); oo = sum(v for c, v in o.items() if c[0] == t)
        tiers[t] = (oo + k * pool) / (nn + k)
    cell = {c: (o[c] + k * tiers[c[0]]) / (n[c] + k) for c in n}
    return {'base': base, 'cell': cell, 'tier': tiers, 'n': dict(n)}


def p_out(R, t, xf):
    return R['cell'].get((t, xf), R['tier'][t] if not xf else R['cell'].get((0, True), R['tier'][t]))


def team_loss(rows, R):
    """Expected loss per (bowl, team): draft talent (every prospect) and production share (offense regulars), each the
    excess P(out) over the baseline; and the realized version (who actually sat, offense only)."""
    out = defaultdict(lambda: {'draft': 0.0, 'prod': 0.0, 'real': 0.0, 'realD': 0.0, 'n': 0})
    for x in rows:
        if x['obs'] and not x['late']:
            continue
        v = out[(x['gid'], x['t'])]
        ex = max(0.0, p_out(R, tier(x['rk']), bool(x['xfer'])) - R['base'])
        v['draft'] += ex * talent(x['rk'])
        if x['obs']:
            v['prod'] += ex * x['share']
            v['real'] += (x['out'] - R['base']) * x['share']
            if x['rk'] is not None:
                v['realD'] += x['out'] * talent(x['rk'])
        v['n'] += 1
    return out


# ---- coaching changes ---------------------------------------------------------------------------------------------
def coaches(keys):
    """{(season, team id): [head coaches that season, head coaches next season]} from the seasons' Wikipedia infoboxes
    (scripts/cfb_transfer_fit.wiki_hc, cached in scripts/.cache/transfer); keys: (season, team id, ESPN display name)"""
    titles = sorted({f'{S + k} {n} football team' for S, _, n in keys for k in (0, 1)})
    hc = wiki_titles(titles)
    return {(S, t): [hc.get(f'{S} {n} football team'), hc.get(f'{S + 1} {n} football team')] for S, t, n in keys}


HC_CACHE = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'hc_titles.json')


def wiki_titles(titles, fresh=False):
    """{infobox title: [head coaches]}, cached by title (Wikimedia answers bursts with 429: what's missing is retried
    after a pause); fresh: refetch these titles"""
    import time
    import cfb_transfer_fit as T
    hc = {} if fresh or not os.path.exists(HC_CACHE) else json.load(open(HC_CACHE))
    for k in range(4):                     # titles with no page never come back: give up on them after a few passes
        todo = [x for x in titles if x not in hc]
        if not todo:
            break
        hc.update(T.wiki_hc(todo))
        with open(HC_CACHE, 'w') as f:
            json.dump(hc, f)
        if k < 3 and any(x not in hc for x in titles):
            time.sleep(60)
    return {x: hc.get(x) or None for x in titles}


def changed(v):
    """the head coach who starts next season isn't one who coached this one (a firing, a departure, an interim)"""
    return None if not v or not v[0] or not v[1] else 0 if v[1][0] in v[0] else 1


# ---- pricing -------------------------------------------------------------------------------------------------------
def wf_rows():
    p = os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'cfb.json.gz')
    return {r['id']: r for r in json.load(gzip.open(p)) if r['wk'] >= 20}


def nll(e, s):
    return 0.5 * math.log(2 * math.pi * s * s) + e * e / (2 * s * s)


def ttest(d):
    n = len(d); m = sum(d) / n; v = sum((x - m) ** 2 for x in d) / (n - 1)
    return m / math.sqrt(v / n) if v else 0.0


def lstsq(X, y):
    """least squares through the origin (home is arbitrary at a bowl, so no intercept); coefficients and their t"""
    import numpy as np
    X, y = np.array(X, float), np.array(y, float)
    b = np.linalg.solve(X.T @ X, X.T @ y)
    s2 = ((y - X @ b) ** 2).sum() / max(1, len(y) - len(b))
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return b.tolist(), (b / se).tolist()


KEYS = ['opt', 'hc']        # expected production lost to opt-outs (away minus home), coaching change (away minus home)


def research(first=2016, last=2025):
    rows = []
    for S in range(first, last + 1):
        rows += season(S)
    wf = wf_rows()
    boards = {S: {g['id']: g for g in board(S)} for S in range(first, last + 1)}
    hc = coaches(sorted({(S, t, g['hn'] if t == g['h'] else g['an']) for S in boards for g in boards[S].values()
                         if g['st'] == 3 for t in (g['h'], g['a'])}))
    games = []
    for S in range(first + 1, last + 1):
        R = rates([x for x in rows if S - 3 <= x['S'] < S])        # walk-forward: the three seasons before
        L = team_loss([x for x in rows if x['S'] == S], R)
        for gid in sorted({x['gid'] for x in rows if x['S'] == S}):
            w, g = wf.get(gid), boards[S][gid]
            if not w or w['L'] is None or is_cfp(S, g):
                continue
            h, a = g['h'], g['a']
            ch, ca = changed(hc.get((S, h))), changed(hc.get((S, a)))
            games.append({'S': S, 'id': gid, 'res': w['res'], 'm': w['m'] - w.get('opt', 0), 'L': w['L'], 'sigma': w['sigma'],
                          'opt': L.get((gid, a), {}).get('prod', 0) - L.get((gid, h), {}).get('prod', 0),
                          'hc': (ca or 0) - (ch or 0), 'hcKnown': ch is not None and ca is not None,
                          'real': L.get((gid, a), {}).get('real', 0) - L.get((gid, h), {}).get('real', 0)})
    return rows, games


def evaluate(rows, games, split=2021):
    """slopes on the model's miss and on the close's, tuning (2017-21) and held out (2022-25); walk-forward scoring of
    the model with the bowl terms priced on the bowls before each season"""
    G = [g for g in games if g['hcKnown']]
    out = {'n': len(G), 'nBowls': len(games), 'slopes': {}}
    for k in KEYS + ['real']:
        for tgt in ('m', 'L'):
            for nm, part in (('tune', [g for g in G if g['S'] <= split]), ('held', [g for g in G if g['S'] > split]), ('all', G)):
                b, t = lstsq([[g[k]] for g in part], [g['res'] - g[tgt] for g in part])
                out['slopes'][f'{k}|{"model" if tgt == "m" else "close"}|{nm}'] = {'n': len(part), 'b': round(b[0], 2), 't': round(t[0], 2)}
    b, t = lstsq([[g[k] for k in KEYS] for g in G], [g['res'] - g['m'] for g in G])
    out['joint'] = {'b': dict(zip(KEYS, [round(x, 2) for x in b])), 't': dict(zip(KEYS, [round(x, 2) for x in t]))}
    bc, tc = lstsq([[g[k] for k in KEYS] for g in G], [g['res'] - g['L'] for g in G])
    out['jointClose'] = {'b': dict(zip(KEYS, [round(x, 2) for x in bc])), 't': dict(zip(KEYS, [round(x, 2) for x in tc]))}
    # walk-forward: terms priced on the bowls before each season; scored 2019-25
    adj, d_ae, d_ll, ae0, ae1 = {}, [], [], [], []
    for S in sorted({g['S'] for g in games}):
        tr = [g for g in G if g['S'] < S]
        bb = lstsq([[g[k] for k in KEYS] for g in tr], [g['res'] - g['m'] for g in tr])[0] if len(tr) >= 60 else [0.0, 0.0]
        for g in (x for x in games if x['S'] == S):
            a = sum(c * g[k] for c, k in zip(bb, KEYS))
            adj[g['id']] = round(a, 2)
            if S >= 2019 and g['hcKnown']:
                e0, e1 = g['res'] - g['m'], g['res'] - g['m'] - a
                ae0.append(abs(e0)); ae1.append(abs(e1)); d_ae.append(abs(e1) - abs(e0)); d_ll.append(nll(e1, g['sigma']) - nll(e0, g['sigma']))
    out['walkForward'] = {'seasons': [2019, max(g['S'] for g in games)], 'n': len(d_ae), 'mae': [round(sum(ae0) / len(ae0), 3), round(sum(ae1) / len(ae1), 3)],
                          'tMae': round(ttest(d_ae), 2), 'dLogLoss': round(sum(d_ll) / len(d_ll), 4), 'tLogLoss': round(ttest(d_ll), 2)}
    # sitting rates, by season, for the record
    bySeason = {}
    for S in sorted({x['S'] for x in rows}):
        obs = [x for x in rows if x['S'] == S and x['late'] and x['obs'] and not x['cfp']]
        c = defaultdict(lambda: [0, 0])
        for x in obs:
            c['draft' if x['rk'] is not None and x['rk'] <= 250 else 'transfer' if x['xfer'] else 'other'][0] += 1
            c['draft' if x['rk'] is not None and x['rk'] <= 250 else 'transfer' if x['xfer'] else 'other'][1] += x['out']
        bySeason[S] = {k: [v[0], round(v[1] / v[0], 3)] for k, v in c.items()}
    out['satBowl'] = bySeason
    return out, adj


def main():
    rows, games = research()
    ev, adj = evaluate(rows, games)
    last = max(x['S'] for x in rows)
    R = rates([x for x in rows if last - 2 <= x['S'] <= last])     # the live rates: the last three bowl seasons
    G = [g for g in games if g['hcKnown']]
    b = lstsq([[g[k] for k in KEYS] for g in G], [g['res'] - g['m'] for g in G])[0]
    fit = {'asof': __import__('datetime').date.today().isoformat(),
           'note': 'Bowl (not CFP) margin terms: opt = expected share of the offense lost to opt-outs, excess P(sits) over '
                   'the baseline x share of team yards; hc = head coach change. pts = b x (away - home).',
           'b': dict(zip(KEYS, [round(x, 2) for x in b])),
           'rates': {'seasons': [last - 2, last], 'base': round(R['base'], 4), 'tiers': [0, 32, 100, 250],
                     'cell': {f'{t}|{int(x)}': round(v, 4) for (t, x), v in sorted(R['cell'].items())},
                     'tier': {str(t): round(v, 4) for t, v in R['tier'].items()}, 'n': {f'{t}|{int(x)}': v for (t, x), v in sorted(R['n'].items())}},
           'minShare': 0.05, **ev}
    with open(os.path.join(ROOT, 'data', 'cfb_optout.json'), 'w') as f:
        json.dump(fit, f, indent=1)
    with open(os.path.join(ROOT, 'scripts', 'data', 'cfb_bowl_adj.json'), 'w') as f:
        json.dump(adj, f, separators=(',', ':'))
    print(json.dumps({k: fit[k] for k in ('b', 'joint', 'jointClose', 'walkForward')}, indent=1))
    for k, v in ev['slopes'].items():
        print(k, v)


def hc_start(S):
    """each FBS team's head coach(es) on its season-S Wikipedia infobox, the first listed being the one who started the
    season: scripts/data/cfb_hc_start.json, which the live bowl term compares with ESPN's current coach. Once a season,
    after the schedule is out."""
    names = {}
    for g in board(S):
        names[g['h']] = g['hn']; names[g['a']] = g['an']
    titles = {t: f'{S} {n} football team' for t, n in names.items()}
    hc = wiki_titles(sorted(titles.values()), fresh=True)
    out = {t: hc[x] for t, x in sorted(titles.items()) if hc.get(x)}
    with open(os.path.join(ROOT, 'scripts', 'data', 'cfb_hc_start.json'), 'w') as f:
        json.dump({'season': S, 'coaches': out}, f, indent=0)
    print('head coaches', len(out), 'of', len(titles))


def apply_wf():
    """bowl terms into the walk-forward picks file (scripts/data/games_wf/cfb.json.gz): m carries opt, the walk-forward
    adjustment (replacing any earlier one), so games_picks sees what the live model would have said"""
    p = os.path.join(ROOT, 'scripts', 'data', 'games_wf', 'cfb.json.gz')
    adj = json.load(open(os.path.join(ROOT, 'scripts', 'data', 'cfb_bowl_adj.json')))
    rows = json.load(gzip.open(p))
    n = 0
    for r in rows:
        a = adj.get(r['id'], 0.0)
        r['m'] = round(r['m'] - r.get('opt', 0.0) + a, 2)
        if a:
            r['opt'] = a; n += 1
        else:
            r.pop('opt', None)
    with gzip.open(p, 'wt') as f:
        json.dump(rows, f, separators=(',', ':'))
    print('bowl terms in', n, 'walk-forward rows')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--pull':
        os.makedirs(DRAFT, exist_ok=True)
        for y in range(int(a[1]), int(a[2]) + 1):
            pull_draft(y)
    elif a and a[0] == '--hc':
        hc_start(int(a[1]))
    elif a and a[0] == '--wf':
        apply_wf()
    else:
        main()
