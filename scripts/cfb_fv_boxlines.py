"""Box-score season lines for the wide FV backtest (scripts/cfb_fv_refit.mjs --wide). PFN's impact scores start in 2019,
so seasons 2012-18 get a stand-in built from free ESPN data, in PFN's row format, at QB, RB, WR, TE, EDGE, DL and LB:
  offense  ESPN box scores (scripts/cfb_roster_hist.py), summed by season: games, passing, rushing, receiving, team shares
  defense  ESPN's season leaderboard (cfb_roster_hist.py --def): tackles, sacks, TFL, passes defended, forced fumbles, INT
           a team game (ESPN has no games played for defenders before 2017, so every season uses team games)
The stand-in score is PFN's score (z within position and season) as a ridge fit on those lines, trained on 2019-22 where
both exist and measured one season held out. Defenders' snaps (PFN has them, ESPN doesn't) and the EDGE / DL / LB split
(ESPN lists many fronts as "DL" or "LB") are fit the same way, the split as a softmax on ESPN's position, weight and the
sack and TFL mix, voted over a player's seasons. Offense takes ESPN's roster position. Each season's pool is the group's
top N by volume (attempts, touches, catches, fitted snaps), N = PFN's median FBS pool 2019-22.
Lines are written for 2019-22 too, so the harness can grade those classes on box lines alone (--boxonly) and measure what
the stand-in loses against PFN.
  python3 scripts/cfb_fv_boxlines.py -> scripts/.cache/fvrefit/box_lines.json, data/cfb_fv_boxlines.json (fit quality)
"""
import collections
import csv
import glob
import json
import os
import re
import unicodedata

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EH = os.path.join(ROOT, 'scripts', '.cache', 'cfb', 'espn_hist')
RO = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'ros')
SP = os.path.join(ROOT, 'scripts', '.cache', 'statplus')
OUT = os.path.join(ROOT, 'scripts', '.cache', 'fvrefit', 'box_lines.json')
REPORT = os.path.join(ROOT, 'data', 'cfb_fv_boxlines.json')
SEASONS, FIT = range(2012, 2023), (2019, 2020, 2021, 2022)
G7 = ('QB', 'RB', 'WR', 'TE', 'EDGE', 'DL', 'LB')
DEF = ('EDGE', 'DL', 'LB')
FRONT = ('DE', 'DT', 'NT', 'DL', 'LB', 'OLB', 'ILB', 'MLB', 'EDGE')     # ESPN positions that can land on PFN's front boards


def nm(s):
    s = re.sub(r'[^a-z ]', '', unicodedata.normalize('NFKD', (s or '').lower()))
    return re.sub(r'\s+', ' ', re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', s)).strip()


def school(s):
    # as cfb_fv_refit.mjs: the first word, "state" shortened
    s = re.sub(r'\s+', ' ', re.sub(r'\buniversity\b|\bof\b', '', re.sub(r'\bstate\b', 'st', nm(s), count=1))).strip()
    return s.split(' ')[0] if s else ''


def slug(s):
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', s.lower()))).strip('-')


def schedule(S):
    # team id -> school and division; team games; each game's opponent pregame Elo (the QB schedule read)
    team, tg, opp = {}, collections.Counter(), collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(RO, f's{S}.csv'))):
        for a, b in (('home', 'away'), ('away', 'home')):
            team[r[a + '_id']] = (r[a + '_team'], r[a + '_division'])
            if r['completed'] == 'TRUE':
                tg[r[a + '_id']] += 1
                e = r[b + '_pregame_elo']
                if e not in ('', 'NA'):
                    opp[r[a + '_id']].append(float(e))
    return team, tg, {t: np.mean(v) for t, v in opp.items()}


def boxes(S):
    ids = set()
    for f in glob.glob(os.path.join(EH, f'sb{S}_80_*.json')):
        ids |= {g['id'] for g in json.load(open(f)) or [] if g['done']}
    L, tot = {}, collections.defaultdict(collections.Counter)
    keys = (('cmp', 'cmp'), ('att', 'att'), ('pyds', 'pas_YDS'), ('ptd', 'pas_TD'), ('int', 'pas_INT'), ('car', 'rus_CAR'),
            ('ryds', 'rus_YDS'), ('rtd', 'rus_TD'), ('rec', 'rec_REC'), ('recyds', 'rec_YDS'), ('rectd', 'rec_TD'))
    for i in ids:
        p = os.path.join(EH, 'box', f'{i}.json')
        if not os.path.exists(p):
            continue
        for tid, P in json.load(open(p)).items():
            for aid, r in P.items():
                x = L.setdefault(aid, {'n': r['n'], 'tm': collections.Counter(), 'gp': 0, **{k: 0.0 for k, _ in keys}})
                x['tm'][tid] += 1
                x['gp'] += 1
                for k, src in keys:
                    v = r.get(src) or 0
                    x[k] += v
                    tot[tid][k] += v
    for x in L.values():
        x['team'] = x['tm'].most_common(1)[0][0]
    return L, tot


def rosters():
    # ESPN athlete id -> {season: (position, weight)}
    P = collections.defaultdict(dict)
    for f in glob.glob(os.path.join(RO, 'r*.csv')):
        for r in csv.DictReader(open(f)):
            if not r['athlete_id'].startswith('-'):
                w = float(r['weight']) if r['weight'] not in ('', 'NA') else None
                P[r['athlete_id']][int(r['season'])] = (r['position'], w)
    return P


def near(d, S):
    # the season's value, else the nearest season's
    if not d:
        return None
    return d[min(d, key=lambda y: (abs(y - S), -y))]


def div(a, b):
    return a / b if b else 0.0


OFF_POS = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE'}


def features(g, x, tot, tgames):
    if g == 'QB':
        a = max(x['att'], 1)
        return [x['att'] / x['gp'], x['pyds'] / x['gp'], x['pyds'] / a, x['cmp'] / a, x['ptd'] / a, x['int'] / a,
                x['ryds'] / x['gp'], x['rtd'] / x['gp'], div(x['att'], tot['att']), x['gp'] / tgames, np.log1p(x['att'])]
    if g == 'RB':
        return [x['car'] / x['gp'], x['ryds'] / x['gp'], x['ryds'] / max(x['car'], 1), x['rtd'] / x['gp'], x['rec'] / x['gp'],
                x['recyds'] / x['gp'], div(x['car'], tot['car']), x['gp'] / tgames, np.log1p(x['car'] + x['rec'])]
    if g in ('WR', 'TE'):
        return [x['rec'] / x['gp'], x['recyds'] / x['gp'], x['recyds'] / max(x['rec'], 1), x['rectd'] / x['gp'],
                div(x['rec'], tot['rec']), div(x['recyds'], tot['recyds']), x['gp'] / tgames, np.log1p(x['rec']), x['ryds'] / x['gp']]
    t = max(x.get('totalTackles') or 0, 1)
    v = [x.get(k) or 0 for k in ('totalTackles', 'soloTackles', 'assistTackles', 'sacks', 'tacklesForLoss', 'passesDefended', 'fumblesForced', 'interceptions')]
    return [u / tgames for u in v] + [div(v[3], t), div(v[4], t), np.log1p(v[0])]


def ridge(X, y, lam=1.0):
    m, s = X.mean(0), X.std(0) + 1e-9
    Z = np.c_[np.ones(len(X)), (X - m) / s]
    A = Z.T @ Z + lam * np.diag([0] + [1] * (Z.shape[1] - 1))
    b = np.linalg.solve(A, Z.T @ y)
    return lambda Xn: np.c_[np.ones(len(Xn)), (Xn - m) / s] @ b


def clip(X, lo=None, hi=None):
    lo = np.percentile(X, 1, axis=0) if lo is None else lo
    hi = np.percentile(X, 99, axis=0) if hi is None else hi
    return np.clip(X, lo, hi), lo, hi


def main():
    pfn = {g: [r for r in json.load(open(os.path.join(SP, f'pfn_{g}.json'))) if r['division'] == 'FBS'] for g in G7}
    pool_n = {g: int(np.median([sum(1 for r in pfn[g] if r['season'] == s) for s in FIT])) for g in G7}
    ros = rosters()
    seasons = {}
    for S in SEASONS:
        team, tg, oppElo = schedule(S)
        L, tot = boxes(S)
        D = {r['id']: r for r in json.load(open(os.path.join(EH, f'def{S}.json')))}
        seasons[S] = (team, tg, oppElo, L, tot, D)
        print(S, len(L), 'box lines,', len(D), 'defensive lines', flush=True)
    # candidate lines: (season, ESPN id, group or None for defense, line)
    cand = []
    for S, (team, tg, oppElo, L, tot, D) in seasons.items():
        for aid, x in L.items():
            if team.get(x['team'], ('', ''))[1] != 'fbs' or not tg.get(x['team']):
                continue
            rp = near({y: p for y, (p, w) in ros.get(aid, {}).items()}, S)
            g = OFF_POS.get(rp) if rp else None
            if g is None and rp not in ('OL', 'DB', 'CB', 'S', 'LB', 'DL', 'DE', 'DT', 'PK', 'P', 'LS'):
                g = 'QB' if x['att'] >= 30 else 'RB' if x['car'] >= 2 * x['rec'] else 'WR'
            if g:
                cand.append((S, aid, g, x))
        for aid, x in D.items():
            if team.get(x['team'], ('', ''))[1] == 'fbs' and tg.get(x['team']) and (x.get('totalTackles') or 0) > 0 and x.get('pos') in FRONT:
                x = {**x, 'gp': tg[x['team']]}
                cand.append((S, aid, None, x))
    # PFN rows by (name, school, season), to train on
    pidx = {g: {(nm(r['name']), school(r['team']), r['season']): r for r in pfn[g]} for g in G7}
    teamname = lambda S, t: seasons[S][0].get(t, ('', ''))[0]
    rep = {'pool': pool_n, 'fit': {}}

    # ---- the EDGE / DL / LB split: softmax on ESPN position, weight and the stat mix -----------------------------
    POSV = FRONT
    def dfeat(S, aid, x):
        w = near({y: w for y, (p, w) in ros.get(aid, {}).items() if w}, S)
        t = max(x.get('totalTackles') or 0, 1)
        return [float(x.get('pos') == p) for p in POSV] + [((w or 260) - 260) / 30, float(w is None),
                div(x.get('sacks') or 0, t), div(x.get('tacklesForLoss') or 0, t), np.log1p(t), (x.get('passesDefended') or 0) / x['gp']]
    dc = [c for c in cand if c[2] is None]
    DX = np.array([dfeat(S, aid, x) for S, aid, _, x in dc])
    dy = []
    for S, aid, _, x in dc:
        k = (nm(x['n']), school(teamname(S, x['team'])), S)
        hit = [g for g in DEF if k in pidx[g]]
        dy.append(max(hit, key=lambda g: pidx[g][k].get('snaps') or 0) if hit else None)
    tr = np.array([y is not None for y in dy])
    Y = np.array([DEF.index(y) if y else -1 for y in dy])
    m, s = DX[tr].mean(0), DX[tr].std(0) + 1e-9
    Z = np.c_[np.ones(len(DX)), (DX - m) / s]
    Wt = np.zeros((Z.shape[1], 3))
    for _ in range(3000):        # softmax regression, light L2
        P = np.exp(Z[tr] @ Wt); P /= P.sum(1, keepdims=True)
        Wt -= 0.5 * (Z[tr].T @ (P - np.eye(3)[Y[tr]]) / tr.sum() + 1e-3 * Wt)
    P = np.exp(Z @ Wt); P /= P.sum(1, keepdims=True)
    # one group per player: probabilities summed over his seasons (fronts flip between "DL" and "DE" year to year)
    vote = collections.defaultdict(lambda: np.zeros(3))
    for (S, aid, _, x), p in zip(dc, P):
        vote[aid] += p
    seasonAcc = float(np.mean(P[tr].argmax(1) == Y[tr]))
    playerAcc = float(np.mean([vote[dc[i][1]].argmax() == Y[i] for i in np.where(tr)[0]]))
    rep['split'] = {'trainRows': int(tr.sum()), 'seasonAcc': round(seasonAcc, 3), 'playerAcc': round(playerAcc, 3)}
    print('defensive split: season acc', round(seasonAcc, 3), 'player vote acc', round(playerAcc, 3), flush=True)
    cand = [(S, aid, g if g else DEF[vote[aid].argmax()], x) for S, aid, g, x in cand]

    # ---- stand-in score (and defenders' snaps), fit on 2019-22, one season held out to measure it --------------------
    lines = {g: [] for g in G7}
    for g in G7:
        C = [c for c in cand if c[2] == g]
        X = np.array([features(g, x, seasons[S][4][x['team']] if g not in DEF else None, seasons[S][1][x['team']]) for S, aid, _, x in C], dtype=float)
        X, lo, hi = clip(X)
        key = [(nm(x['n']), school(teamname(S, x['team'])), S) for S, aid, _, x in C]
        hit = np.array([k in pidx[g] for k in key])
        sc = {}
        for S in FIT:
            v = [r['score'] for r in pfn[g] if r['season'] == S]
            sc[S] = (np.mean(v), np.std(v))
        y = np.array([(pidx[g][k]['score'] - sc[k[2]][0]) / sc[k[2]][1] if h else 0 for k, h in zip(key, hit)])
        sv = np.array([np.log(max(pidx[g][k].get('snaps') or 0, 30)) if h else 0 for k, h in zip(key, hit)])
        seas = np.array([c[0] for c in C])
        held, heldSn = np.zeros(len(C)), np.zeros(len(C))
        for S in FIT:
            trn, tst = hit & (seas != S), hit & (seas == S)
            held[tst] = ridge(X[trn], y[trn])(X[tst])
            if g in DEF:
                heldSn[tst] = ridge(X[trn], sv[trn])(X[tst])
        pred = ridge(X[hit], y[hit])(X)
        snp = np.exp(ridge(X[hit], sv[hit])(X)) if g in DEF else None
        f = {'trainRows': int(hit.sum()), 'rHeldOut': round(float(np.corrcoef(held[hit], y[hit])[0, 1]), 3)}
        if g in DEF:
            f['snapsRHeldOut'] = round(float(np.corrcoef(heldSn[hit], sv[hit])[0, 1]), 3)
        # each season's pool: top N by volume
        vol = np.array([x['att'] if g == 'QB' else x['car'] + x['rec'] if g == 'RB' else x['rec'] if g in ('WR', 'TE') else 0 for S, aid, _, x in C], dtype=float)
        if g in DEF:
            vol = snp
        keep = np.zeros(len(C), bool)
        for S in SEASONS:
            ix = np.where(seas == S)[0]
            keep[ix[np.argsort(-vol[ix])[:pool_n[g]]]] = True
        f['poolOverlap'] = round(float(np.mean([hit[i] for i in np.where(keep & np.isin(seas, FIT))[0]])), 3)
        f['pfnCovered'] = round(float(np.mean([k in {key[i] for i in np.where(keep)[0]} for k in pidx[g] if k[2] in FIT])), 3)
        # held-out r inside the pool PFN and the box pool share
        both = keep & hit
        f['rHeldOutPool'] = round(float(np.corrcoef(held[both], y[both])[0, 1]), 3)
        rep['fit'][g] = f
        print(g, f, flush=True)
        mu, sd = np.mean([v[0] for v in sc.values()]), np.mean([v[1] for v in sc.values()])
        for i in np.where(keep)[0]:
            S, aid, _, x = C[i]
            team, tg, oppElo = seasons[S][0], seasons[S][1], seasons[S][2]
            row = {'eid': 'espn-' + aid, 'espn': aid, 'name': x['n'], 'team': team[x['team']][0], 'division': 'FBS', 'season': S,
                   'score': round(float(mu + sd * pred[i]), 2), 'src': 'box', 'gp': x['gp'], 'sos': round(float(oppElo.get(x['team'], 1500) - 1500) / 100, 2)}
            if g in DEF:
                row.update(snaps=round(float(snp[i])), tkl=x.get('totalTackles'), tfl=x.get('tacklesForLoss'), sk=x.get('sacks'))
            elif g == 'QB':
                row.update(att=x['att'], cmp=x['cmp'], cmpPct=round(100 * div(x['cmp'], x['att']), 1), nypa=round(div(x['pyds'], x['att']), 2), ryds=x['ryds'])
            elif g == 'RB':
                row.update(share=round(100 * div(x['car'], seasons[S][4][x['team']]['car']), 1), rec=x['rec'], recYds=x['recyds'], ryds=x['ryds'])
            else:
                row.update(rec=x['rec'], recYds=x['recyds'])
            lines[g].append(row)
    # the PFN slug for a player PFN also lists in 2019-22 (any group), so the wide harness links his earlier box seasons
    link = {}
    for g in G7:
        for r in lines[g]:
            k = (nm(r['name']), school(r['team']), r['season'])
            for g2 in G7:
                if r['season'] in FIT and k in pidx[g2]:
                    link[r['espn']] = pidx[g2][k]['id']
    for g in G7:
        for r in lines[g]:
            r['id'] = link.get(r['espn'], r['eid'])
    rep['linked'] = len(link)
    rep['lines'] = {g: collections.Counter(r['season'] for r in lines[g]) for g in G7}
    json.dump(lines, open(OUT, 'w'))
    json.dump({'method': 'python3 scripts/cfb_fv_boxlines.py', **rep}, open(REPORT, 'w'), indent=1)
    open(REPORT, 'a').write('\n')
    print('linked to PFN ids', len(link))


if __name__ == '__main__':
    main()
