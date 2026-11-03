#!/usr/bin/env python3
"""1NT research (Nov 3 2026): stand-in cost (C1) and round-share player Elo (C2) on ESEA league matches.

    python3 scripts/esea_standin_research.py   # reads research/esea_matches.json.gz (+ data/esea.json git history)
                                                # writes data/esea_standin_research.json

Every rating is walk-forward: a match is predicted from earlier matches only, then the ratings update.
Unit = one league match, predicted for faction1 (Bo1 regular season; Bo3 playoffs use the first map's five).

C1 stand-ins. A team's core = the 5 players with the most appearances in its previous CORE_N maps of the same
season (prior maps only, no lookahead; needs CORE_MIN prior maps that season). subs = players in the five on the first map who aren't in the
core (0, 1, 2+). Feature sd = subs(f1) - subs(f2). Tested as a residual on four baselines:
  lvcore  mean FACEIT skill level (match-time, 1-10) of each team's CORE five: what a roster-based rating sees
  lvfive  the same for the five who actually played (does the stand-in's pug level carry his value?)
  prs     round-share player Elo of the actual five (C2)
  live    the page's own preview inputs on S59 (team top-5 FACEIT elo + talent), from data/esea.json history
Logistic on [baseline logit, sd] vs [baseline logit], leave-one-match-day-out, and tune S54-S57 -> held S58-S59.

C2 player Elo ported from the pro model (scripts/cs2_model.py DEF): team = mean of the five, each map updates on
round share (.5 + (share - .5) / span / 2), K = Kmin + (K - Kmin) exp(-maps / n0), new players start at their
division level + mu_new. Grid on S54-S57, scored on S58-S59, then blended with FACEIT elo on the S59 live set.
"""
import gzip
import json
import math
import os
import subprocess
import sys
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'research', 'esea_matches.json.gz')
OUT = os.path.join(ROOT, 'data', 'esea_standin_research.json')
DIV = {'Open9-10': -2, 'Open1-8': -2, 'Open': -2, 'Intermediate': -1, 'Main': 0, 'Advanced': 1}
CORE_N, CORE_MIN = 20, 5
TUNE, HELD, BURN = (54, 57), (58, 59), 53


def clip(p):
    return min(1 - 1e-6, max(1e-6, p))


def lg(p):
    p = clip(p)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def ll(p, y):
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def load():
    d = json.load(gzip.open(DATA))
    ms = []
    for m in d['matches']:
        if m.get('winner') not in ('faction1', 'faction2') or not m.get('at') or not m.get('maps'):
            continue
        maps = [mp for mp in m['maps'] if mp.get('s1') is not None and mp.get('s2') is not None and mp.get('p1') and mp.get('p2')]
        if not maps:
            continue
        m['maps'] = maps
        m['y'] = 1 if m['winner'] == 'faction1' else 0
        m['five1'] = [p[0] for p in maps[0]['p1']][:6]
        m['five2'] = [p[0] for p in maps[0]['p2']][:6]
        m['lv'] = {p[0]: p[1] for f in ('f1', 'f2') for p in m[f]['roster'] if p[1]}
        m['div_r'] = DIV.get(m['div'], 0)
        ms.append(m)
    ms.sort(key=lambda m: m['at'])
    return d, ms


# ---- C1 features ---------------------------------------------------------------------------------
def standin_features(ms):
    """walk forward: per match and side, core five from prior maps, subs in the first map's five, levels"""
    tmaps = defaultdict(list)   # team -> [five per prior map]
    level = {}                  # player -> last known match-time level
    for m in ms:
        for p, v in m['lv'].items():
            level.setdefault(p, v)   # first sight seeds; updated after the match below
        m['c'] = {}
        for t, five in (('f1', m['five1']), ('f2', m['five2'])):
            hist = tmaps[(m['season'], m[t]['id'])][-CORE_N:]
            if len(hist) < CORE_MIN:
                m['c'][t] = None
                continue
            cnt, last = Counter(), {}
            for j, f in enumerate(hist):
                for p in f:
                    cnt[p] += 1
                    last[p] = j
            core = sorted(cnt, key=lambda p: (-cnt[p], -last[p]))[:5]
            subs = [p for p in five if p not in core]
            lvl = lambda ps: [m['lv'].get(p) or level.get(p) for p in ps]
            lf, lc = [x for x in lvl(five) if x], [x for x in lvl(core) if x]
            # levels of the core players a stand-in replaced vs the stand-ins themselves
            out = [p for p in core if p not in five]
            ls, lo = [x for x in lvl(subs) if x], [x for x in lvl(out) if x]
            m['c'][t] = {'subs': len(subs), 'lvfive': sum(lf) / len(lf) if lf else None, 'lvcore': sum(lc) / len(lc) if lc else None,
                         'lvsub': sum(ls) / len(ls) if ls else None, 'lvout': sum(lo) / len(lo) if lo else None,
                         'nsub_lv': len(ls), 'nout_lv': len(lo), 'core': core}
        for mp in m['maps']:
            tmaps[(m['season'], m['f1']['id'])].append([p[0] for p in mp['p1']])
            tmaps[(m['season'], m['f2']['id'])].append([p[0] for p in mp['p2']])
        for p, v in m['lv'].items():
            level[p] = v


# ---- C2 player Elo ---------------------------------------------------------------------------------
def round_share(won, lost, span):
    rs = won / ((won + lost) or 24)
    return min(1.0, max(0.0, (rs - 0.5) / span * 0.5 + 0.5))


class PElo:
    def __init__(self, K=480, Kmin=144, n0=100, mu_new=-100, span=0.4, kmap=0.6, gap=100, carry=1.0, wins=False):
        self.p = dict(K=K, Kmin=Kmin, n0=n0, mu_new=mu_new, span=span, kmap=kmap, gap=gap, carry=carry, wins=wins)
        self.r, self.n, self.season = {}, defaultdict(int), {}

    def kf(self, q):
        p = self.p
        return p['Kmin'] + (p['K'] - p['Kmin']) * math.exp(-self.n[q] / p['n0'])

    def get(self, q, m):
        base = self.p['gap'] * m['div_r']
        if q not in self.r:
            self.r[q] = base + self.p['mu_new']
            self.season[q] = m['season']
        elif self.season[q] != m['season'] and self.p['carry'] < 1:
            self.r[q] = base + self.p['carry'] * (self.r[q] - base)
            self.season[q] = m['season']
        return self.r[q]

    def team(self, five, m):
        return sum(self.get(q, m) for q in five) / len(five)

    def gap_of(self, m):
        return (self.team(m['five1'], m) - self.team(m['five2'], m)) / 400

    def update(self, m):
        p = self.p
        for mp in m['maps']:
            a = [x[0] for x in mp['p1']]
            b = [x[0] for x in mp['p2']]
            e = 1 / (1 + 10 ** (-(self.team(a, m) - self.team(b, m)) / 400))
            s = (1.0 if mp['s1'] > mp['s2'] else 0.0) if p['wins'] else round_share(mp['s1'], mp['s2'], p['span'])
            for ros, sg in ((a, 1), (b, -1)):
                for q in ros:
                    self.r[q] = self.get(q, m) + sg * p['kmap'] * self.kf(q) * (s - e)
            for q in a + b:
                self.n[q] += 1


def run_pelo(ms, **kw):
    mdl = PElo(**kw)
    out = {}
    for m in ms:
        out[m['id']] = mdl.gap_of(m)
        mdl.update(m)
    return out, mdl


# ---- fitting / scoring ----------------------------------------------------------------------------
def logit_fit(X, y, lam=1e-3, iters=30):
    k = len(X[0])
    b = [0.0] * k
    for _ in range(iters):
        g = [lam * bj for bj in b]
        H = [[lam * (i == j) for j in range(k)] for i in range(k)]
        for x, t in zip(X, y):
            z = sum(bj * xj for bj, xj in zip(b, x))
            p = sig(max(-30, min(30, z)))
            w = p * (1 - p)
            for i in range(k):
                g[i] -= (t - p) * x[i]
                for j in range(k):
                    H[i][j] += w * x[i] * x[j]
        A = [H[i][:] + [g[i]] for i in range(k)]
        for c in range(k):
            piv = max(range(c, k), key=lambda r: abs(A[r][c]))
            A[c], A[piv] = A[piv], A[c]
            for r in range(k):
                if r != c and A[c][c]:
                    f = A[r][c] / A[c][c]
                    A[r] = [a - f * bb for a, bb in zip(A[r], A[c])]
        d = [A[i][k] / A[i][i] if A[i][i] else 0 for i in range(k)]
        b = [bj - dj for bj, dj in zip(b, d)]
        if max(abs(x) for x in d) < 1e-7:
            break
    return b


def pred(b, x):
    return sig(sum(bj * xj for bj, xj in zip(b, x)))


def lodo(rows, cols):
    """rows: dicts with 'day', 'y' and feature keys. -> {id: loss} leave-one-match-day-out"""
    days = sorted({r['day'] for r in rows})
    out = {}
    byday = defaultdict(list)
    for r in rows:
        byday[r['day']].append(r)
    # sufficient: refit per day (n days small enough for the live set; for big sets fold days into 20 blocks)
    if len(days) > 60:
        blocks = {d: i % 20 for i, d in enumerate(days)}
    else:
        blocks = {d: i for i, d in enumerate(days)}
    for blk in sorted(set(blocks.values())):
        tr = [r for r in rows if blocks[r['day']] != blk]
        te = [r for r in rows if blocks[r['day']] == blk]
        b = logit_fit([[r[c] for c in cols] for r in tr], [r['y'] for r in tr])
        for r in te:
            out[r['id']] = ll(pred(b, [r[c] for c in cols]), r['y'])
    return out


def split_fit(rows, cols, tune, held):
    tr = [r for r in rows if tune[0] <= r['season'] <= tune[1]]
    te = [r for r in rows if held[0] <= r['season'] <= held[1]]
    b = logit_fit([[r[c] for c in cols] for r in tr], [r['y'] for r in tr])
    return b, {r['id']: ll(pred(b, [r[c] for c in cols]), r['y']) for r in te}


def paired(a, b):
    ids = [i for i in a if i in b]
    d = [a[i] - b[i] for i in ids]
    n = len(d)
    if n < 3:
        return None
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / (n - 1)) or 1e-9
    return {'n': n, 'll_base': round(sum(b[i] for i in ids) / n, 4), 'll_new': round(sum(a[i] for i in ids) / n, 4),
            'diff': round(mu, 5), 't': round(mu / (sd / math.sqrt(n)), 2)}


def season_folds(a, b, rows):
    """per season: does the new model win?"""
    won, tot = 0, 0
    for s in sorted({r['season'] for r in rows}):
        ids = [r['id'] for r in rows if r['season'] == s and r['id'] in a and r['id'] in b]
        if len(ids) < 30:
            continue
        tot += 1
        won += sum(a[i] - b[i] for i in ids) < 0
    return f'{won}/{tot}'


def se_coef(rows, cols, b):
    """coefficient standard errors from the observed information"""
    k = len(cols)
    H = [[0.0] * k for _ in range(k)]
    for r in rows:
        x = [r[c] for c in cols]
        p = pred(b, x)
        for i in range(k):
            for j in range(k):
                H[i][j] += p * (1 - p) * x[i] * x[j]
    # invert
    A = [H[i][:] + [1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]
    for c in range(k):
        piv = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        pv = A[c][c]
        A[c] = [a / pv for a in A[c]]
        for r in range(k):
            if r != c:
                f = A[r][c]
                A[r] = [a - f * bb for a, bb in zip(A[r], A[c])]
    return [math.sqrt(max(0, A[i][k + i])) for i in range(k)]


# ---- live preview set (S59, data/esea.json history) ------------------------------------------------
def snapshots():
    try:
        revs = subprocess.check_output(['git', '-C', ROOT, 'log', '--format=%H %ct', 'origin/main', '--', 'data/esea.json']).decode().split()
    except Exception:
        return []
    snaps = []
    for h, t in zip(revs[::2], revs[1::2]):
        try:
            d = json.loads(subprocess.check_output(['git', '-C', ROOT, 'show', f'{h}:data/esea.json'], stderr=subprocess.DEVNULL))
        except Exception:
            continue
        r = d.get('rankings')
        rk = r.get('teams') if isinstance(r, dict) else None
        if rk:
            snaps.append((int(t), {x['id']: x for x in rk}))
    return sorted(snaps, key=lambda s: s[0])


def main():
    d, ms = load()
    standin_features(ms)
    res = {'asof': d.get('asof'), 'matches': len(ms), 'core': {'window_maps': CORE_N, 'min_prior_maps': CORE_MIN}}

    # descriptive: raw win % by own subs (prior-only core), both sides defined
    desc = defaultdict(lambda: [0, 0])
    for m in ms:
        for t, y in (('f1', m['y']), ('f2', 1 - m['y'])):
            c = m['c'].get(t)
            if c:
                k = min(c['subs'], 2)
                desc[k][0] += y
                desc[k][1] += 1
    res['raw_by_subs'] = {str(k): {'n': v[1], 'win': round(v[0] / v[1], 4)} for k, v in sorted(desc.items())}

    # ---- C2 grid on tune seasons --------------------------------------------------------------------
    grid = []
    for K in (48, 64, 96, 128, 192):
        for kr in (0.2, 0.4):
            for n0 in (50, 150):
                for span in (0.3, 0.4, 0.5):
                    for gap in (0, 100):
                        grid.append(dict(K=K, Kmin=round(K * kr), n0=n0, span=span, kmap=1.0, mu_new=-100, gap=gap))
    if '--quick' in sys.argv:
        grid = [dict(K=96, Kmin=19, n0=50, span=0.4, kmap=1.0, mu_new=-100, gap=0)]
    best, bestll, tab = None, 9, []
    for g in grid:
        gp, _ = run_pelo(ms, **g)
        rows = [{'id': m['id'], 'y': m['y'], 'season': m['season'], 'x': gp[m['id']]} for m in ms if m['season'] > BURN]
        b, lls = split_fit(rows, ['x'], TUNE, TUNE)   # in-sample fit on tune: slope absorbs the scale
        v = sum(lls.values()) / len(lls)
        tab.append({**g, 'tune_ll': round(v, 4), 'slope': round(b[0], 3)})
        if v < bestll:
            best, bestll = g, v
    res['c2_grid_top'] = sorted(tab, key=lambda r: r['tune_ll'])[:8]
    res['c2_best'] = best
    gp, PE = run_pelo(ms, **best)
    gw, _ = run_pelo(ms, **{**best, 'wins': True})          # same model, wins only (round share check)
    from esea_research import Elo  # team round-share Elo, the Oct 26 best (relo)
    te = Elo(K=96, carry=0.0, div_gap=0, margin=True)
    trelo = {}
    for m in ms:
        m['share'] = sum(mp['s1'] for mp in m['maps']) / max(1, sum(mp['s1'] + mp['s2'] for mp in m['maps']))
        m['div_r'] = DIV.get(m['div'], 0)
        trelo[m['id']] = lg(te.predict(m))
        te.update(m)

    def lvdiff(m, k):
        a, b = m['c'].get('f1'), m['c'].get('f2')
        if a and b and a[k] is not None and b[k] is not None:
            return a[k] - b[k]
        if k == 'lvfive':
            la = [m['lv'].get(p) for p in m['five1'] if m['lv'].get(p)]
            lb = [m['lv'].get(p) for p in m['five2'] if m['lv'].get(p)]
            if len(la) >= 3 and len(lb) >= 3:
                return sum(la) / len(la) - sum(lb) / len(lb)
        return None

    # C2 held: player round-share Elo vs wins-only vs team relo vs FACEIT level of the actual five
    base_rows = []
    for m in ms:
        if m['season'] <= BURN:
            continue
        base_rows.append({'id': m['id'], 'y': m['y'], 'season': m['season'], 'day': m['at'] // 86400,
                          'prs': gp[m['id']], 'pw': gw[m['id']], 'relo': trelo[m['id']], 'lv': lvdiff(m, 'lvfive')})
    c2 = {}
    fits = {}
    for name, cols in (('prs', ['prs']), ('pwins', ['pw']), ('relo', ['relo']), ('prs+relo', ['prs', 'relo'])):
        b, lls = split_fit(base_rows, cols, TUNE, HELD)
        fits[name] = lls
        c2[name] = {'coef': [round(x, 3) for x in b], 'held_ll': round(sum(lls.values()) / len(lls), 4), 'n': len(lls)}
    c2['prs_vs_relo'] = paired(fits['prs'], fits['relo'])
    c2['prs_vs_wins'] = paired(fits['prs'], fits['pwins'])
    c2['prs_vs_relo']['seasons'] = season_folds(fits['prs'], fits['relo'], base_rows)
    # with FACEIT level of the actual five (the only match-time FACEIT number in the archive)
    lvrows = [r for r in base_rows if r['lv'] is not None]
    fl = {}
    for name, cols in (('lv', ['lv']), ('prs', ['prs']), ('lv+prs', ['lv', 'prs']), ('lv+relo', ['lv', 'relo'])):
        b, lls = split_fit(lvrows, cols, TUNE, HELD)
        fl[name] = lls
        c2['lvset_' + name] = {'coef': [round(x, 3) for x in b], 'held_ll': round(sum(lls.values()) / len(lls), 4), 'n': len(lls)}
    c2['lvset_lv+prs_vs_lv'] = paired(fl['lv+prs'], fl['lv'])
    c2['lvset_lv+prs_vs_lv']['seasons'] = season_folds(fl['lv+prs'], fl['lv'], lvrows)
    c2['lvset_prs_vs_lv'] = paired(fl['prs'], fl['lv'])
    # S59 holdout (fit S54-S58)
    a = split_fit(lvrows, ['lv'], (54, 58), (59, 59))[1]
    b = split_fit(lvrows, ['lv', 'prs'], (54, 58), (59, 59))[1]
    c2['s59_holdout_lv+prs_vs_lv'] = paired(b, a)
    res['c2_held'] = c2

    # ---- C1: stand-in residual on each baseline -----------------------------------------------------
    c1 = {}
    rows = []
    byid = {m['id']: m for m in ms}
    for r in base_rows:
        m = byid[r['id']]
        a, b = m['c'].get('f1'), m['c'].get('f2')
        if not a or not b:
            continue
        sa, sb = min(a['subs'], 2), min(b['subs'], 2)
        x = dict(r)
        x.update({'sd': sa - sb, 'sd1': (sa >= 1) - (sb >= 1), 'sd2': (sa >= 2) - (sb >= 2),
                  'lvcore': lvdiff(m, 'lvcore'), 'lvfive': lvdiff(m, 'lvfive'), 'one': 1.0})
        rows.append(x)
    c1['n'] = len(rows)
    c1['share_with_sub'] = round(sum((byid[r['id']]['c']['f1']['subs'] > 0) + (byid[r['id']]['c']['f2']['subs'] > 0) for r in rows) / (2 * len(rows)), 4)
    for base in ('lvcore', 'lvfive', 'prs', 'relo', 'prs+lvfive', 'prs+lvcore'):
        bc = base.split('+')
        rr = [r for r in rows if all(r[c] is not None for c in bc)]
        A = lodo(rr, bc)
        B = lodo(rr, bc + ['sd'])
        B1 = lodo(rr, bc + ['sd1'])
        h1 = split_fit(rr, bc + ['sd1'], TUNE, HELD)
        b0, ha = split_fit(rr, bc, TUNE, HELD)
        b1, hb = split_fit(rr, bc + ['sd'], TUNE, HELD)
        full = logit_fit([[r[c] for c in bc + ['sd']] for r in rr], [r['y'] for r in rr])
        se = se_coef(rr, bc + ['sd'], full)
        # indicator coding: first stand-in vs second
        full2 = logit_fit([[r[c] for c in bc + ['sd1', 'sd2']] for r in rr], [r['y'] for r in rr])
        se2 = se_coef(rr, bc + ['sd1', 'sd2'], full2)
        c1[base] = {'n': len(rr), 'sub_coef': round(full[-1], 3), 'sub_se': round(se[-1], 3), 'sub_z': round(full[-1] / se[-1], 2),
                    'first_sub': [round(full2[-2], 3), round(se2[-2], 3)], 'second_sub': [round(full2[-1], 3), round(se2[-1], 3)],
                    'base_coef': [round(x, 3) for x in full[:-1]],
                    'lodo': paired(B, A), 'held': paired(hb, ha), 'held_coef': round(b1[-1], 3),
                    'seasons': season_folds(B, A, rr),
                    'any_sub': {'lodo': paired(B1, A), 'held': paired(h1[1], ha), 'held_coef': round(h1[0][-1], 3), 'seasons': season_folds(B1, A, rr)}}
    # pug level of the stand-in vs the core player he replaced (one-sub sides, both levels known)
    gaps = [byid[r['id']]['c'][t]['lvsub'] - byid[r['id']]['c'][t]['lvout'] for r in rows for t in ('f1', 'f2')
            if byid[r['id']]['c'][t]['subs'] == 1 and byid[r['id']]['c'][t]['nsub_lv'] == 1 and byid[r['id']]['c'][t]['nout_lv'] == 1]
    if gaps:
        mu = sum(gaps) / len(gaps)
        c1['sub_minus_replaced_level'] = {'n': len(gaps), 'mean': round(mu, 3),
                                           'se': round(math.sqrt(sum((g - mu) ** 2 for g in gaps) / (len(gaps) - 1) / len(gaps)), 3),
                                           'sub_lower': round(sum(g < 0 for g in gaps) / len(gaps), 3), 'sub_higher': round(sum(g > 0 for g in gaps) / len(gaps), 3)}
    # is the stand-in's pug level over/understated? split the five's level into core part and stand-in part
    rr = []
    for r in rows:
        m = byid[r['id']]
        def parts(t):
            c = m['c'][t]
            five = m['five1'] if t == 'f1' else m['five2']
            core = set(c['core'])
            lvl = lambda p: m['lv'].get(p)
            cl = [lvl(p) for p in five if p in core and lvl(p)]
            sl = [lvl(p) for p in five if p not in core and lvl(p)]
            n = len(cl) + len(sl)
            return (sum(cl) / 5 if n == len(five) else None, sum(sl) / 5 if n == len(five) else None)
        (ca, sa), (cb, sb) = parts('f1'), parts('f2')
        if None in (ca, sa, cb, sb):
            continue
        rr.append({**r, 'lvc': ca - cb, 'lvs': sa - sb})
    if rr:
        cols = ['prs', 'lvc', 'lvs', 'sd']
        full = logit_fit([[r[c] for c in cols] for r in rr], [r['y'] for r in rr])
        se = se_coef(rr, cols, full)
        c1['level_split'] = {'n': len(rr), 'cols': cols, 'coef': [round(x, 3) for x in full], 'se': [round(x, 3) for x in se],
                             'note': 'lvc = core players level sum/5, lvs = stand-ins level sum/5; lvs < lvc per level = pug level overstates the stand-in'}
    res['c1'] = c1

    # study card: win % by own stand-ins (prior-only core) vs what the five's player Elo expected
    bb = logit_fit([[r['prs']] for r in base_rows], [r['y'] for r in base_rows])
    agg = defaultdict(lambda: [0, 0, 0.0])
    for m in ms:
        if m['season'] <= BURN:
            continue
        p1 = sig(bb[0] * gp[m['id']])
        for t, y, p in (('f1', m['y'], p1), ('f2', 1 - m['y'], 1 - p1)):
            c = m['c'].get(t)
            if c:
                k = min(c['subs'], 2)
                agg[k][0] += y
                agg[k][1] += 1
                agg[k][2] += p
    def wilson(w, n, z=1.96):
        ph = w / n
        den = 1 + z * z / n
        c = (ph + z * z / (2 * n)) / den
        h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
        return round(c - h, 4), round(c + h, 4)
    lab = {0: 'core five', 1: '1 stand-in', 2: '2+ stand-ins'}
    pts_raw, pts_exp = [], []
    for k in (0, 1, 2):
        w, n, e = agg[k]
        lo, hi = wilson(w, n)
        pts_raw.append({'x': lab[k], 'y': round(w / n, 4), 'lo': lo, 'hi': hi, 'n': n})
        pts_exp.append({'x': lab[k], 'y': round(e / n, 4), 'lo': None, 'hi': None, 'n': n})
    res['card'] = {'raw': pts_raw, 'expected': pts_exp, 'prs_slope': round(bb[0], 3)}

    # ---- live preview set: S59 matches with a data/esea.json rankings snapshot ----------------------
    snaps = snapshots()
    live = []
    for m in ms:
        if m['season'] != 59 or not snaps:
            continue
        prior = [s for s in snaps if s[0] < m['at'] - 60]
        if not prior:
            continue
        S = prior[-1][1]
        a, b = S.get(m['f1']['id']), S.get(m['f2']['id'])
        if not a or not b or not a.get('elo') or not b.get('elo'):
            continue
        ta, tb = (a.get('talent') or {}).get('exact'), (b.get('talent') or {}).get('exact')
        ca, cb = m['c'].get('f1'), m['c'].get('f2')
        pe = 1 / (1 + 10 ** (-(a['elo'] - b['elo']) / 600))
        pt = sig(0.48 * ((ta or 0) - (tb or 0)))
        pv = sig(0.8 * lg(pe) + 0.2 * lg(pt)) if ta is not None and tb is not None else pe
        live.append({'id': m['id'], 'y': m['y'], 'season': 59, 'day': m['at'] // 86400, 'pv': lg(pv), 'elo': (a['elo'] - b['elo']) / 100,
                     'prs': gp[m['id']], 'sd': (min(ca['subs'], 2) - min(cb['subs'], 2)) if ca and cb else 0, 'one': 1.0})
    L = {'n': len(live), 'snapshots': len(snaps)}
    if len(live) >= 30:
        fixed = {r['id']: ll(sig(r['pv']), r['y']) for r in live}   # the page's preview as it is (no refit)
        L['preview_as_is_ll'] = round(sum(fixed.values()) / len(fixed), 4)
        A = lodo(live, ['pv'])
        for name, cols in (('pv+sd', ['pv', 'sd']), ('pv+prs', ['pv', 'prs']), ('prs', ['prs']), ('pv+prs+sd', ['pv', 'prs', 'sd'])):
            B = lodo(live, cols)
            full = logit_fit([[r[c] for c in cols] for r in live], [r['y'] for r in live])
            L[name] = {'lodo_vs_pv': paired(B, A), 'coef': [round(x, 3) for x in full]}
        L['pv_lodo_ll'] = round(sum(A.values()) / len(A), 4)
        # time split: fit the first half of the S59 match days, score the second half
        days = sorted({r['day'] for r in live})
        cut = days[len(days) // 2]
        tr, te = [r for r in live if r['day'] < cut], [r for r in live if r['day'] >= cut]
        ts = {}
        for name, cols in (('pv', ['pv']), ('pv+prs', ['pv', 'prs'])):
            b = logit_fit([[r[c] for c in cols] for r in tr], [r['y'] for r in tr])
            ts[name] = {r['id']: ll(pred(b, [r[c] for c in cols]), r['y']) for r in te}
        L['time_split'] = {'train': len(tr), 'test': len(te), 'pv+prs_vs_pv': paired(ts['pv+prs'], ts['pv']),
                           'vs_as_is': paired(ts['pv+prs'], {r['id']: ll(sig(r['pv']), r['y']) for r in te})}
        L['lodo_vs_as_is'] = paired(lodo(live, ['pv', 'prs']), fixed)
        L['with_sub'] = sum(1 for r in live if r['sd'] != 0)
    res['live_s59'] = L

    json.dump(res, open(OUT, 'w'), indent=1)
    print(json.dumps(res, indent=1)[:6000])


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
