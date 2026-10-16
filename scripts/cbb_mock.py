#!/usr/bin/env python3
"""2027 NBA mock drafts for the College Basketball ARKBOARD: predictive, blended and conviction, as for college football.

    python3 scripts/cbb_mock.py [--offline]     # writes data/cbb_mock.json

Inputs
  order      Tankathon's full 2027 draft order (current standings, owed picks applied): .cache/cbb/tankathon_full_draft.html
  boards     the 2027 big boards in /mnt/project-files/cbb/boards (or $CBB_BOARDS): Tankathon, CBS, Bleacher Report,
             ESPN (Woo), FanSided, SI, No Ceilings v1. Consensus = .5 x median board rank + .5 x mean, a player missing
             from a board sits at 1.5 x that board's depth.
  our board  static/data/cbb-all.json (fetch_cbb.py) for FV, xBPM, recruiting and last season; past boards in
             static/data/cbb-past.json (cbb_fit.py); careers in .cache/cbb/careers.json (cbb_link.py).

Mocks
  predictive  where they will go: score = w ln(consensus rank) + (1 - w) ln(our board rank), w backtested on
              the first No Ceilings board of each draft year (Nov-Dec, 2022-2026, our forward boards) against the
              June slot, picked by leave-one-draft-out on mean |ln slot error| (undrafted = 75).
  conviction  what teams should do: expected peak XPM (NBA, best three seasons of .5 BPM + .5 DPM) given the
              consensus slot and what the market underprices beyond it (cbb/backtest: steals, A/TO, BPM; pedigree
              overpaid), ridge-free OLS on drafted college players 2009-2023, outcome centred within each draft,
              each term kept only if it lowers leave-one-draft-out RMSE.
  blended     each player at the geometric mean of his predictive and conviction slots.
Reach / value: predictive and conviction grade each other, both grade the blended mock; reach when the grader's slot
is 2.5x+ and 16+ later (undrafted = 75), value the mirror. Site table only.
"""
import csv, json, math, os, re, sys, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D

BOARDS_DIR = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
LIVE = ['tankathon_2027', 'cbs_2027', 'br_wasserman_2027', 'espn_woo_2027', 'fansided_2027', 'si_2027']
UND = 75          # slot of an undrafted player, for errors and grades
GRADE_RATIO, GRADE_SPOTS = 2.5, 16
OUT = os.path.join(D.ROOT, 'data', 'cbb_mock.json')
TK = 'https://www.tankathon.com/full_draft'
LOGO = '/img/nba/{}.png'   # ESPN's logos, served from the site so the GFX can draw them (all 30 teams)


def read_csv(name):
    p = os.path.join(BOARDS_DIR, name if name.endswith('.csv') else name + '.csv')
    with open(p, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def key(n): return D.norm(n)


def surname(n):
    t = key(n).split()
    return t[-1] if t else ''


# ---------------------------------------------------------------- draft order
def draft_order(offline):
    p = os.path.join(D.CACHE, 'tankathon_full_draft.html')
    if not offline or not os.path.exists(p):
        import subprocess
        subprocess.run(['curl', '-sL', '-m', '60', '-A', 'Mozilla/5.0', TK, '-o', p + '.tmp'], check=False)
        if os.path.exists(p + '.tmp') and os.path.getsize(p + '.tmp') > 20000: os.replace(p + '.tmp', p)
    s = open(p, encoding='utf-8').read()
    picks = []
    for r in re.findall(r'<td class="pick-number">.*?</tr>', s, re.S):
        n = int(re.search(r'pick-num">(\d+)', r).group(1))
        ab, short, full = re.search(r'team-link.*?nba/([a-z]+)\.svg.*?class="mobile">([^<]+)<.*?class="desktop">([^<]+)<', r, re.S).groups()
        via = re.search(r'class="trade">.*?<span class="desktop">([^<]+)<', r, re.S)
        picks.append({'pick': n, 'round': 1 if n <= 30 else 2, 'abbr': ab.upper(), 'team': ab.upper() if len(short) > 4 else short,
                      'teamName': full, 'teamLogo': LOGO.format(ab), 'via': via.group(1) if via else None})
    picks.sort(key=lambda x: x['pick'])
    asof = time.strftime('%Y-%m-%d', time.gmtime(os.path.getmtime(p)))
    return picks, asof


# ---------------------------------------------------------------- consensus
def consensus(boards):
    """boards: list of lists of (name, school, pos, rank). Returns {key: dict(name, school, pos, cons score, ranks)}."""
    ppl = {}
    for b, rows in enumerate(boards):
        for name, school, pos, rk in rows:
            k = key(name)
            # same player under another spelling (Cam / Cameron): same surname and school already in
            if k not in ppl:
                alt = [q for q, v in ppl.items() if surname(q) == surname(k) and key(v['school'])[:5] == key(school)[:5] and q.split()[0][:3] == k.split()[0][:3]]
                if alt: k = alt[0]
            p = ppl.setdefault(k, {'name': name, 'school': school, 'pos': pos, 'ranks': {}})
            p['ranks'].setdefault(b, rk)
            if not p['pos'] and pos: p['pos'] = pos
    depth = [max(r[3] for r in rows) for rows in boards]
    for p in ppl.values():
        rr = [p['ranks'].get(b, 1.5 * depth[b]) for b in range(len(boards))]
        p['score'] = 0.5 * float(np.median(rr)) + 0.5 * float(np.mean(rr))
        p['nboards'] = len(p['ranks'])
    order = sorted(ppl, key=lambda k: (ppl[k]['score'], -ppl[k]['nboards']))
    for i, k in enumerate(order, 1): ppl[k]['cons'] = i
    return ppl


# ---------------------------------------------------------------- matching to our boards
def match(name, school, index):
    """index: {norm name: [rows]}, rows carry 'school'. Exact name, then surname + school + first initial."""
    k = key(name)
    c = index.get(k, [])
    if len(c) > 1 and school:
        c2 = [r for r in c if key(r['school'])[:4] == key(school)[:4]]
        c = c2 or c
    if c: return c[0]
    sn, ini = surname(name), k[:1]
    for kk, rows in index.get(('_sn', sn), {}).items():
        for r in rows:
            if school and key(r['school'])[:4] == key(school)[:4] and kk[:1] == ini: return r
    return None


def build_index(rows):
    idx = defaultdict(list)
    sn = defaultdict(lambda: defaultdict(list))
    for r in rows:
        idx[key(r['name'])].append(r)
        sn[surname(r['name'])][key(r['name'])].append(r)
    for s, v in sn.items(): idx[('_sn', s)] = v
    return idx


def past_boards():
    d = json.load(open(os.path.join(D.ROOT, 'static', 'data', 'cbb-past.json')))
    c = d['cols']
    by = defaultdict(list)
    for r in d['rows']:
        x = dict(zip(c, r)); x['school'] = x['team']
        by[x['season']].append(x)
    return by


def espn_slots():
    """(draft year, norm name) -> slot, every drafted player ESPN lists (college and international)."""
    out = {}
    for r in read_csv('espn_picks'):
        if r['slot_pick']: out[(int(r['draft_year']), key(r['name']))] = int(r['slot_pick'])
    return out


# ---------------------------------------------------------------- predictive: backtest the model weight
def pred_order(pool, w):
    """pool: list of dicts with cons (rank) and mrank (our board rank among pool college players, or None)."""
    s = [(w * math.log(p['cons']) + (1 - w) * math.log(p['mrank'] or p['cons']), p['cons']) for p in pool]
    order = sorted(range(len(pool)), key=lambda i: s[i])
    slot = [0] * len(pool)
    for j, i in enumerate(order, 1): slot[i] = j
    return slot


def slot_err(pool, slot):
    e = [abs(math.log(min(s, UND)) - math.log(p['actual'])) for p, s in zip(pool, slot)]
    return float(np.mean(e))


def backtest_pred(past, slots):
    nc = defaultdict(lambda: defaultdict(list))
    for r in read_csv('noceilings'): nc[int(r['draft_year'])][r['board_date']].append(r)
    years, pools = [], {}
    for y in range(2022, 2027):
        first = min(nc[y])
        rows = [(r['name'], r['school'], r['pos'], int(r['rank'])) for r in nc[y][first]]
        pools[y] = make_pool([rows], past.get(y, []), slots, y)
        years.append((y, first, len(rows)))
    grid = [round(x, 2) for x in np.arange(0, 1.0001, 0.05)]
    err = {y: {w: slot_err(pools[y], pred_order(pools[y], w)) for w in grid} for y in pools}
    lodo, chosen = [], {}
    for y in pools:
        wbest = min(grid, key=lambda w: (sum(err[z][w] for z in pools if z != y), -w))
        chosen[y] = wbest
        lodo.append((err[y][wbest], err[y][1.0], err[y][0.0]))
    full = min(grid, key=lambda w: (sum(err[z][w] for z in pools), -w))
    lo = np.array(lodo)
    res = {'boards': [{'year': y, 'date': d, 'depth': n, 'pool': len(pools[y]), 'w': chosen[y],
                       'err': round(err[y][chosen[y]], 3), 'errCons': round(err[y][1.0], 3), 'errModel': round(err[y][0.0], 3)}
                      for y, d, n in years],
           'w': full, 'lodoErr': round(float(lo[:, 0].mean()), 3), 'consErr': round(float(lo[:, 1].mean()), 3),
           'modelErr': round(float(lo[:, 2].mean()), 3),
           'yearsBetter': int(sum(a < b - 1e-9 for a, b, _ in lodo)), 'years': len(lodo),
           'yearsConsBest': int(sum(err[y][1.0] <= min(err[y][w] for w in grid) + 1e-9 for y in pools)),
           'curve': {str(w): round(float(np.mean([err[y][w] for y in pools])), 4) for w in grid}}
    # sanity: final pre-draft ESPN boards (the market's last word): the model should add little there
    es = defaultdict(list)
    for r in read_csv('espn'): es[int(r['draft_year'])].append(r)
    ee = {}
    for y in range(2017, 2027):
        rows = [(r['name'], r['school'], r['pos'], int(r['rank'])) for r in es.get(y, []) if r['rank']]
        if not rows: continue
        pl = make_pool([rows], past.get(y, []), slots, y)
        ee[y] = {w: slot_err(pl, pred_order(pl, w)) for w in grid}
    if ee:
        wf = min(grid, key=lambda w: sum(ee[y][w] for y in ee))
        res['espnFinal'] = {'w': wf, 'err': round(float(np.mean([ee[y][wf] for y in ee])), 3),
                            'errCons': round(float(np.mean([ee[y][1.0] for y in ee])), 3), 'years': f'{min(ee)}-{max(ee)}'}
    return res


def make_pool(boards, ours, slots, year, extra=40):
    """consensus over boards, our board matched in, plus our top `extra` players no board has."""
    ppl = consensus(boards)
    idx = build_index(ours)
    pool = []
    seen = set()
    for k, p in ppl.items():
        m = match(p['name'], p['school'], idx)
        if m is not None: seen.add(id(m))
        pool.append({'name': p['name'], 'school': p['school'], 'pos': p['pos'], 'consScore': p['score'], 'ranks': p['ranks'],
                     'nboards': p['nboards'], 'ours': m})
    depth = [max(r[3] for r in b) for b in boards]
    fill = 0.5 * float(np.median([1.5 * d for d in depth])) + 0.5 * float(np.mean([1.5 * d for d in depth]))
    for r in sorted(ours, key=lambda r: -r['fvx'])[:extra]:
        if id(r) in seen: continue
        pool.append({'name': r['name'], 'school': r['school'], 'pos': r.get('pos'), 'consScore': fill + 1, 'ranks': {}, 'nboards': 0, 'ours': r})
    pool.sort(key=lambda p: (p['consScore'], -p['nboards'], -(p['ours']['fvx'] if p['ours'] else 0)))
    for i, p in enumerate(pool, 1): p['cons'] = i
    col = sorted([p for p in pool if p['ours']], key=lambda p: -p['ours']['fvx'])
    for i, p in enumerate(col, 1): p['mrank'] = i
    for p in pool:
        p.setdefault('mrank', None)
        p['actual'] = slots.get((year, key(p['name'])), UND) if slots is not None else None
    return pool


# ---------------------------------------------------------------- conviction: value beyond the slot
FEATS = ['lnpick', 'bpm', 'bpm3', 'stl', 'ato', 'dbpm', 'lrank', 'age', 'fv']
LABEL = {'lnpick': 'ln(slot)', 'bpm': 'BPM, draft season', 'bpm3': '3-season BPM', 'stl': 'steal %', 'ato': 'A/TO',
         'dbpm': 'D-BPM', 'lrank': 'recruiting rank (-ln)', 'age': 'age at the draft', 'fv': 'our preseason FV'}


def bpm3_of(seasons):
    num = den = 0.0
    for w, r in zip((3, 2, 1), reversed(seasons[-3:])):
        if r.get('bpm') is None: continue
        m = (r.get('min_per') or 0) * (r.get('gp') or 0)
        num += w * m * r['bpm']; den += w * m
    return num / den if den else None


def lrank_of(rec):
    rk = [x for x in ((rec or {}).get('on3rk'), (rec or {}).get('rk247')) if x]
    return -math.log(min(np.mean(rk), 300)) if rk else -math.log(300)


def conv_rows(past):
    cs = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    out = []
    for c in cs:
        o = c['nba'] or {}
        if not o.get('draft') or not o.get('pick') or not (2009 <= o['draft'] <= 2023): continue
        ss = [s for s in c['seasons'] if s['year'] <= o['draft']]
        if not ss or ss[-1]['year'] < o['draft'] - 1: continue
        L = ss[-1]
        age = D.age_on(c['dob'], o['draft'], 6, 25)
        fvr = match(c['name'], L['team'], past_idx(past, o['draft']))
        out.append({'year': o['draft'], 'name': c['name'], 'y': o['peakXpm'] if o.get('peakXpm') is not None else -2.5,
                    'f': {'lnpick': math.log(o['pick']), 'bpm': L['bpm'], 'bpm3': bpm3_of(ss), 'stl': min(L['stl'] or 0, 6),
                          'ato': min(L['ast_tov'] or 0, 5), 'dbpm': L['dbpm'], 'lrank': lrank_of(c.get('rec')), 'age': age,
                          'fv': fvr['fvx'] if fvr else past_floor(past, o['draft'])}})
    return out


_PI = {}
def past_idx(past, y):
    if y not in _PI: _PI[y] = build_index(past.get(y, []))
    return _PI[y]


def past_floor(past, y):
    v = [r['fvx'] for r in past.get(y, [])]
    return min(v) if v else 20.0


def design(rows, feats, mu=None, sd=None):
    X = np.array([[r['f'].get(k) if r['f'].get(k) is not None else np.nan for k in feats] for r in rows], float)
    if mu is None:
        mu = np.nanmean(X, 0); sd = np.nanstd(X, 0); sd[sd == 0] = 1
    Z = np.nan_to_num((X - mu) / sd)
    Z = np.clip(Z, -4, 4)
    return np.column_stack([np.ones(len(rows)), Z]), mu, sd


def centred(rows):
    by = defaultdict(list)
    for r in rows: by[r['year']].append(r['y'])
    m = {y: np.mean(v) for y, v in by.items()}
    return np.array([r['y'] - m[r['year']] for r in rows])


def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    s2 = e @ e / max(1, len(y) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.pinv(X.T @ X)))
    return b, se


def lodo_rmse(rows, feats):
    y = centred(rows)
    yrs = sorted({r['year'] for r in rows})
    err = np.zeros(len(rows)); per = {}
    for t in yrs:
        tr = [i for i, r in enumerate(rows) if r['year'] != t]; te = [i for i, r in enumerate(rows) if r['year'] == t]
        X, mu, sd = design([rows[i] for i in tr], feats)
        b, _ = ols(X, y[tr])
        Xt, _, _ = design([rows[i] for i in te], feats, mu, sd)
        err[te] = y[te] - Xt @ b
        per[t] = float(np.sqrt(np.mean(err[te] ** 2)))
    return float(np.sqrt(np.mean(err ** 2))), per, err


def fit_conv(past):
    rows = conv_rows(past)
    base = ['lnpick']
    rm0, per0, e0 = lodo_rmse(rows, base)
    singles = []
    for k in FEATS[1:]:
        rm, per, e = lodo_rmse(rows, base + [k])
        d = e0 ** 2 - e ** 2   # per-row gain in squared error
        t = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d))))
        singles.append({'driver': LABEL[k], 'key': k, 'rmse': round(rm, 4), 'gain': round(rm0 - rm, 4), 't': round(t, 2),
                        'years': int(sum(per[y] < per0[y] for y in per0)), 'of': len(per0)})
    # forward selection on LODO RMSE, a term stays if it wins 9+ of the 15 drafts
    kept = list(base); cur, curper, cure = rm0, per0, e0
    while True:
        best = None
        for k in FEATS[1:]:
            if k in kept: continue
            rm, per, e = lodo_rmse(rows, kept + [k])
            wins = sum(per[y] < curper[y] for y in per)
            if rm < cur - 1e-4 and wins >= 9 and (best is None or rm < best[1]): best = (k, rm, per, e)
        if not best: break
        kept.append(best[0]); cur, curper, cure = best[1], best[2], best[3]
    X, mu, sd = design(rows, kept)
    b, se = ols(X, centred(rows))
    d = e0 ** 2 - cure ** 2
    return {'n': len(rows), 'drafts': '2009-2023', 'kept': kept, 'mu': mu.tolist(), 'sd': sd.tolist(), 'b': b.tolist(),
            'coef': [{'driver': LABEL[k], 'key': k, 'perSd': round(float(b[i + 1]), 3), 't': round(float(b[i + 1] / se[i + 1]), 2)} for i, k in enumerate(kept)],
            'rmseSlot': round(rm0, 4), 'rmse': round(cur, 4), 'gainPct': round(100 * (rm0 - cur) / rm0, 2),
            't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
            'years': int(sum(curper[y] < per0[y] for y in per0)), 'of': len(per0), 'singles': singles}


# ---------------------------------------------------------------- live
def live_pool():
    boards = []
    for f in LIVE:
        boards.append([(r['name'], r['school'], r['pos'], int(r['rank'])) for r in read_csv(f)])
    boards.append([(r['name'], r['school'], r['pos'], int(r['rank'])) for r in read_csv('noceilings') if r['draft_year'] == '2027'])
    a = json.load(open(os.path.join(D.ROOT, 'static', 'data', 'cbb-all.json')))
    ours = [dict(zip(a['cols'], r)) for r in a['rows']]
    for r in ours: r['school'] = r['team']
    # board entrants from our side: FV 50+ (one-and-done or upperclass) the boards have not listed
    top = [r for r in ours if r['fv'] >= 50]
    pool = make_pool(boards, top, None, 2027, extra=len(top))
    # players a board lists who are on our board below FV 50: match against everyone
    idx = build_index(ours)
    for p in pool:
        if p['ours'] is None: p['ours'] = match(p['name'], p['school'], idx)
    col = sorted([p for p in pool if p['ours']], key=lambda p: -p['ours']['fvx'])
    for i, p in enumerate(col, 1): p['mrank'] = i
    return pool, len(boards)


def career_index():
    cs = json.load(open(os.path.join(D.CACHE, 'careers.json')))
    idx = defaultdict(list)
    for c in cs:
        if c['last'] >= 2026:
            L = c['seasons'][-1]
            idx[key(c['name'])].append({'name': c['name'], 'school': L['team'], 'c': c})
    return idx


def live_feats(p, cidx):
    o = p['ours'] or {}
    f = {'lnpick': math.log(p['cons'])}
    if o:
        f['fv'] = o['fvx']
        f['lrank'] = lrank_of(o.get('rec'))
        a = o.get('age') or o.get('ageEst')
        f['age'] = a + 0.7 if a else None        # season start -> draft night
        cm = match(o['name'], o['team'], cidx)
        ss = [s for s in cm['c']['seasons'] if s['year'] <= 2026] if cm else []
        f['bpm'] = o.get('xbpm')                 # the draft season is this one: our projected BPM
        if ss:
            L = ss[-1]
            proj = {'bpm': o.get('xbpm'), 'min_per': L.get('min_per') or 60, 'gp': 30}
            f['bpm3'] = bpm3_of(ss + [proj]) if o.get('xbpm') is not None else bpm3_of(ss)
            f['stl'] = min(L['stl'] or 0, 6) if (L.get('min_per') or 0) >= 15 else None
            f['ato'] = min(L['ast_tov'] or 0, 5) if (L.get('min_per') or 0) >= 15 else None
            f['dbpm'] = L.get('dbpm')
            p['line'] = L
            p['nseasons'] = len(ss)
        else:
            f['bpm3'] = o.get('xbpm')
    return f


def why_conv(p, conv):
    """one line from the terms that move him most off his consensus slot, scouting style."""
    f, L, o = p['f'], p.get('line'), p['ours'] or {}
    out = []
    for k, v in sorted(p['contrib'].items(), key=lambda t: -abs(t[1])):
        if abs(v) < 0.12 or k == 'lnpick': continue
        x = f.get(k)
        if x is None: continue
        if k in ('bpm', 'bpm3'):
            span = 'projected ' if not L else ('3-yr ' if k == 'bpm3' and (p.get('nseasons') or 1) >= 2 else '')
            out.append(f'underrated production: {x:+.1f} {span}BPM' if v > 0 else f'light production: {x:+.1f} {span}BPM')
        elif k == 'age':
            if not o.get('age'): continue                       # class-estimated age: not worth a line
            out.append(f'young: {x:.1f} on draft night' if v > 0 else f'old: {x:.1f} on draft night')
        elif k == 'stl': out.append(f'underrated hands: {x:.1f} stl%' if v > 0 else f'{x:.1f} stl%, few events on defense')
        elif k == 'ato': out.append(f'underrated feel: {x:.1f} A/TO' if v > 0 else f'{x:.1f} A/TO, loose with the ball')
        elif k == 'dbpm': out.append(f'{x:+.1f} D-BPM' if v > 0 else f'{x:+.1f} D-BPM, a defensive question')
        elif k == 'lrank':
            rk = round(math.exp(-x))
            out.append((f'No. {rk} recruit' if rk < 300 else 'unranked out of high school') + (', pedigree already priced in' if v < 0 else ''))
        elif k == 'fv' and o: out.append(f'FV {o["fv"]}{"+" if o["plus"] else ""} on our board')
        if len(out) == 2: break
    return '; '.join(out) if out else 'priced about right at his slot'


def why_pred(p, slot, w):
    c, o, nb = p['cons'], p['ours'], p['nboards']
    fv = f'our FV {o["fv"]}{"+" if o["plus"] else ""}' if o else 'no D-I line'
    if not nb: return f'on no board yet; {fv}'
    head = f'consensus No. {c}, on {nb} of 7 boards' if nb < 7 else f'consensus No. {c}'
    if w < 1 and o and slot < c - 2: return f'{head}; goes earlier on {fv}'
    if w < 1 and o and slot > c + 2: return f'{head}; slides on {fv}'
    return f'{head}; {fv}'


def assign(pool, scores, picks):
    order = sorted(range(len(pool)), key=lambda i: scores[i])
    slot = {}
    for j, i in enumerate(order, 1): slot[i] = j
    return order, slot


def main():
    offline = '--offline' in sys.argv
    picks, order_asof = draft_order(offline)
    past = past_boards()
    slots = espn_slots()
    bt = backtest_pred(past, slots)
    print(f"predictive: w(consensus) = {bt['w']}  LODO |ln slot err| {bt['lodoErr']} vs consensus only {bt['consErr']}, model only {bt['modelErr']}; better in {bt['yearsBetter']}/{bt['years']} drafts")
    for b in bt['boards']: print('   ', b)
    print('    ESPN final boards:', bt.get('espnFinal'))
    conv = fit_conv(past)
    print(f"conviction: n {conv['n']}, kept {conv['kept']}, LODO RMSE {conv['rmse']} vs slot only {conv['rmseSlot']} ({conv['gainPct']}%, t {conv['t']}, {conv['years']}/{conv['of']} drafts)")
    for c in conv['coef']: print('   ', c)
    for s in conv['singles']: print('    single', s)

    pool, nb = live_pool()
    w = bt['w']
    cidx = career_index()
    mu, sd, b = np.array(conv['mu']), np.array(conv['sd']), np.array(conv['b'])
    for p in pool:
        p['f'] = live_feats(p, cidx)
        x = np.array([p['f'].get(k) if p['f'].get(k) is not None else np.nan for k in conv['kept']], float)
        z = np.clip(np.nan_to_num((x - mu) / sd), -4, 4)
        p['xxpm'] = float(b[0] + b[1:] @ z)
        p['contrib'] = {k: float(b[i + 1] * z[i]) for i, k in enumerate(conv['kept'])}
    n = len(picks)
    ps = pred_order(pool, w)
    sc_pred = [s for s in ps]
    sc_conv = [-p['xxpm'] for p in pool]
    _, s_pred = assign(pool, sc_pred, picks)
    _, s_conv = assign(pool, sc_conv, picks)
    sc_blend = [math.sqrt(s_pred[i] * s_conv[i]) + 1e-6 * s_pred[i] for i in range(len(pool))]
    _, s_blend = assign(pool, sc_blend, picks)
    S = {'pred': s_pred, 'conv': s_conv, 'blend': s_blend}
    eff = {m: {i: (s if s <= n else None) for i, s in S[m].items()} for m in S}
    graders = {'pred': ['conv'], 'conv': ['pred'], 'blend': ['pred', 'conv']}

    def row(i, mode, pk):
        p, o = pool[i], pool[i]['ours'] or {}
        mine = S[mode][i]
        grades = []
        for g in graders[mode]:
            other = eff[g][i] or UND
            if other >= GRADE_RATIO * mine and other - mine >= GRADE_SPOTS: grades.append({'g': 'reach', 'by': g, 'o': eff[g][i]})
            elif mine >= GRADE_RATIO * other and mine - other >= GRADE_SPOTS: grades.append({'g': 'value', 'by': g, 'o': other})
        why = why_conv(p, conv) if mode == 'conv' else why_pred(p, mine, w) if mode == 'pred' else (
            why_conv(p, conv) if abs(S['conv'][i] - S['pred'][i]) >= 4 else why_pred(p, S['pred'][i], w))
        pos = o.get('pos') or pos_of(p['pos'])
        return dict(pk, name=o.get('name') or p['name'], pos=pos, role=o.get('role'), school=o.get('team') or p['school'],
                    logo=o.get('logo'), conf=o.get('conf'), fv=o.get('fv'), plus=o.get('plus'), fvx=o.get('fvx'),
                    cls=o.get('cls') or ('Intl' if not o else None), age=round(o['age'] + 0.7, 1) if o.get('age') else (round(o['ageEst'] + 0.7, 1) if o.get('ageEst') else None),
                    ageEst=bool(o and not o.get('age')), ht=o.get('ht'), cons=p['cons'] if p['nboards'] else None, boards=p['nboards'],
                    xxpm=round(p['xxpm'], 2), slots={m: eff[m][i] for m in S if m != mode}, grades=grades, why=why)

    mocks = {}
    for mode in S:
        order = sorted(range(len(pool)), key=lambda i: S[mode][i])[:n]
        mocks[mode] = [row(i, mode, pk) for i, pk in zip(order, picks)]
    out = {'asof': time.strftime('%Y-%m-%d'), 'orderAsof': order_asof, 'boards': nb, 'pool': len(pool),
           'method': {'pred': bt, 'conv': {k: v for k, v in conv.items() if k not in ('mu', 'sd', 'b')}},
           'gradeRatio': GRADE_RATIO, 'gradeSpots': GRADE_SPOTS, 'mocks': mocks}
    json.dump(out, open(OUT, 'w'), indent=1)
    for mode in ('pred', 'blend', 'conv'):
        print(mode, '|', ', '.join(f"{r['pick']} {r['team']} {r['name']}" for r in mocks[mode][:10]))


def pos_of(s):
    s = (s or '').upper()
    if not s: return None
    t = re.split(r'[/\- ]', s)[0]
    return {'PG': 'G', 'SG': 'G', 'G': 'G', 'GUARD': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'FORWARD': 'F', 'C': 'C', 'CENTER': 'C', 'WING': 'F', 'BIG': 'C'}.get(t, t[:1])


if __name__ == '__main__':
    main()
