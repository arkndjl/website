"""Rolling school / coach development effects for the CFB FV candidate stage (Nov 1 2026 FV sweep, research only).

scripts/school_dev.py ranks schools by NFL outcome over what the recruiting rating predicted (CFB tau .42 FV a signee,
rolling t 5.3). Here the same effect is rebuilt ROLLING, so the wide FV harness (scripts/cfb_fv_refit.mjs --wide) can
add it to each player-season's inputs with no lookahead: the effect a board grading season s may read uses only HS
classes y <= s - 5, scored on drafts through spring s (a class's whole draft window, y+3 .. y+5, is then known).

  recruits  247Sports composite classes 2003-21 (scripts/.cache/fvrefit/247/c_<y>_<pg>.html, as the harness caches them)
  outcome   draft capital: AV a season the slot returns (a + b ln pick, fit on the 2006-15 drafts), undrafted 0; a
            recruit counts for the school that signed him (intent to treat), linked to nflverse draft_picks.csv through
            scripts/names.py (name + signing school, exact name across schools, position must fit), drafts y+3 .. y+5
  E[y]      OLS on a rating hinge (knots at composite quantiles), class and position-group dummies, fit on the training
            classes leaving the school's own recruits out
  effect    precision-weighted school mean of y - E[y] (residual variance by rating bin), DerSimonian-Laird tau2,
            shrunk u = m tau2 / (tau2 + V)
Units: draft-capital AV a season per signee. Keys: names.py team_key of the school (the coach file keys by coach id).

  python3 scripts/cfb_fv_schooldev.py -> scripts/.cache/fvrefit/schooldev.json
    {"school": {s: {team: u}}, "pos": {s: {team|grp: u}}, "coach": {s: {coach: u}}, "hc": {s: {team: coach}}, "tau": {...}}
  coach: recruits attributed to the head coach of the signing school in the class year (CFBD /coaches list from the
  cfb-game-research artifact, scripts/.cache/cfb/hist/coaches.json); hc maps each team-season to its head coach
"""
import glob
import html as H
import json
import math
import os
import re
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = os.path.join(ROOT, 'scripts', '.cache')
OUT = os.path.join(C, 'fvrefit', 'schooldev.json')
GRP = {'QB': 'QB', 'PRO': 'QB', 'DUAL': 'QB', 'RB': 'RB', 'APB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OT': 'OL', 'OG': 'OL', 'OC': 'OL', 'IOL': 'OL',
       'SDE': 'EDGE', 'WDE': 'EDGE', 'DE': 'EDGE', 'EDGE': 'EDGE', 'DT': 'DL', 'DL': 'DL', 'ILB': 'LB', 'OLB': 'LB', 'LB': 'LB', 'CB': 'DB', 'S': 'DB', 'DB': 'DB', 'ATH': 'ATH'}
NFLG = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'DE': 'EDGE', 'OLB': 'LB', 'DT': 'DL', 'NT': 'DL', 'DL': 'DL',
        'LB': 'LB', 'ILB': 'LB', 'CB': 'DB', 'S': 'DB', 'SAF': 'DB', 'DB': 'DB', 'K': 'K', 'P': 'K', 'LS': 'K'}
FIRST_S, LAST_S, LAG = 2012, 2022, 5


def parse247():
    out = []
    for y in range(2003, 2022):
        rk = 0
        for pg in range(1, 61):
            f = os.path.join(C, 'fvrefit', '247', f'c_{y}_{pg}.html')
            if not os.path.exists(f): break
            h = open(f, encoding='utf-8', errors='replace').read()
            items = h.split('rankings-page__list-item"')[1:]
            if not items: break
            for x in items:
                g = lambda pat: (re.search(pat, x, re.S) or [None, None])[1]
                sc, nm = g(r'class="score">([\d.]+)'), g(r'name-link"[^>]*>([^<]*)')
                if not sc or not nm: continue
                rk += 1
                pos = (g(r'class="position">\s*([^<]*?)\s*</div>') or '').strip().upper()
                sch = H.unescape(g(r'class="img-link"[^>]*>\s*<img alt="([^"]*)"') or '')
                if not sch: continue          # uncommitted / unsigned: no school to credit
                out.append({'name': H.unescape(nm).strip(), 'pos': pos, 'grp': GRP.get(pos, 'ATH'), 'rating': float(sc), 'team': sch, 'cls': y, 'rank': rk})
    return out


def capital_fn(picks):
    S = [r for r in picks if 2006 <= int(r['season']) <= 2015 and r['pick']]
    x = np.log([float(r['pick']) for r in S]); y = np.array([float(r['w_av'] or 0) / (2025 - int(r['season']) + 1) for r in S])
    b, a = np.polyfit(x, y, 1)
    return lambda pk: max(0.0, a + b * math.log(pk))


def main():
    import csv
    picks = list(csv.DictReader(open(os.path.join(C, 'statplus', 'draft_picks.csv'))))
    cap = capital_fn(picks)
    R = parse247()
    print('247 recruits', len(R), 'classes', sorted({r['cls'] for r in R})[:1], '..', max(r['cls'] for r in R), flush=True)
    # link: drafts y+3 .. y+5, by name + signing school, exact name across schools
    byD = defaultdict(list)
    for p in picks: byD[int(p['season'])].append({'name': p['pfr_player_name'], 'team': p['college'], 'pos': p['position'], 'pick': int(p['pick'])})
    M = {D: N.Matcher(v) for D, v in byD.items()}
    used = set()
    for r in R:
        r['pick'] = None; r['D'] = None
        for D in (r['cls'] + 3, r['cls'] + 4, r['cls'] + 5):
            if D not in M: continue
            hit, how = M[D].find(r['name'], team=r['team'], pos=r['pos'] if r['grp'] != 'ATH' else None, cross_team='exact')
            if hit and id(hit) not in used:
                used.add(id(hit)); r['pick'] = hit['pick']; r['D'] = D; break
    print('linked', sum(1 for r in R if r['pick']), 'of', len(R), flush=True)
    # head coach by team-season (CFBD list)
    hc = {}
    try:
        for c in json.load(open(os.path.join(C, 'cfb', 'hist', 'coaches.json'))):
            cid = f"{c['firstName']} {c['lastName']}|{c['id']}"
            for s in c['seasons']:
                k = (N.team_key(s['school']), s['year'])
                # mid-season changes: the coach with more games that season
                if k not in hc or (s.get('games') or 0) > hc[k][1]: hc[k] = (cid, s.get('games') or 0)
    except OSError:
        print('no coaches.json: coach effects skipped')
    hc = {k: v[0] for k, v in hc.items()}
    for r in R:
        r['tk'] = N.team_key(r['team']); r['coach'] = hc.get((r['tk'], r['cls']))
    qs = np.quantile([r['rating'] for r in R], [.5, .75, .9, .96, .99])
    G = sorted({r['grp'] for r in R})
    def design(rows, classes):
        X = np.array([[1.0, r['rating']] + [max(0.0, r['rating'] - q) for q in qs] + [float(r['cls'] == c) for c in classes[1:]] + [float(r['grp'] == g) for g in G[1:]] for r in rows])
        return X
    res = {'school': {}, 'pos': {}, 'coach': {}, 'tau': {}, 'n': {}}
    for s in range(FIRST_S, LAST_S + 1):
        tr = [r for r in R if r['cls'] <= s - LAG]
        y = np.array([cap(r['pick']) if r['pick'] and r['D'] <= s else 0.0 for r in tr])
        classes = sorted({r['cls'] for r in tr})
        X = design(tr, classes)
        XtX, Xty = X.T @ X, X.T @ y
        lam = 1e-6 * np.eye(X.shape[1])
        by = defaultdict(list)
        for i, r in enumerate(tr): by[r['tk']].append(i)
        e = np.zeros(len(tr))
        for t, ix in by.items():          # leave the school out of its own baseline
            Xi = X[ix]; b = np.linalg.solve(XtX - Xi.T @ Xi + lam, Xty - Xi.T @ y[ix]); e[ix] = y[ix] - Xi @ b
        # residual variance by rating bin -> precision weights
        bins = np.digitize([r['rating'] for r in tr], qs)
        v = np.array([np.var(e[bins == k]) if (bins == k).sum() > 20 else np.var(e) for k in range(len(qs) + 1)])
        w = 1 / v[bins]
        def eb(groups, label):
            m, V = {}, {}
            for gk, ix in groups.items():
                if len(ix) < 5: continue
                W = w[ix].sum(); m[gk] = float((w[ix] * e[ix]).sum() / W); V[gk] = 1 / W
            if len(m) < 5: return {}, 0.0
            ks = list(m); wj = np.array([1 / V[k] for k in ks]); mj = np.array([m[k] for k in ks])
            mu = (wj * mj).sum() / wj.sum(); Q = (wj * (mj - mu) ** 2).sum()
            t2 = max(0.0, (Q - (len(ks) - 1)) / (wj.sum() - (wj ** 2).sum() / wj.sum()))
            res['tau'].setdefault(label, {})[s] = round(math.sqrt(t2), 4)
            return {k: round((m[k] - mu) * t2 / (t2 + V[k]), 5) for k in ks}, t2
        res['school'][s], _ = eb(by, 'school')
        bp = defaultdict(list)
        for i, r in enumerate(tr): bp[r['tk'] + '|' + r['grp']].append(i)
        # position-group effects: shrunk within each group
        res['pos'][s] = {}
        for g in G:
            sub = {k: ix for k, ix in bp.items() if k.endswith('|' + g)}
            u, _ = eb(sub, 'pos_' + g); res['pos'][s].update(u)
        bc = defaultdict(list)
        for i, r in enumerate(tr):
            if r['coach']: bc[r['coach']].append(i)
        res['coach'][s], _ = eb(bc, 'coach')
        res['n'][s] = len(tr)
        top = sorted(res['school'][s].items(), key=lambda kv: -kv[1])[:4]
        print(s, 'classes <=', s - LAG, 'n', len(tr), 'tau school', res['tau']['school'].get(s), 'coach', res['tau'].get('coach', {}).get(s), 'top', top, flush=True)
    res['hc'] = {s: {k[0]: v for k, v in hc.items() if k[1] == s} for s in range(FIRST_S, LAST_S + 1)}
    json.dump(res, open(OUT, 'w'))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
