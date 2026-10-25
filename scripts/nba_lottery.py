"""NBA draft order odds: the lottery and the rest of the order from simulated final standings.

    import nba_lottery as L; L.order(wins, playoff, rng)      # one simulated draft order (team -> pick, rounds 1-2)
    python3 scripts/nba_lottery.py --backtest                # walk-forward P(top-4 pick) 2016-26 -> data/nba_lottery_backtest.json

The order: the 14 teams out of the playoffs (play-in losers included from 2021) are the lottery, seeded worst record
first (ties a coin flip; the league splits tied teams' combinations, a few tenths of a point). Since 2019 four picks
are drawn on 140/140/140/125/105/90/75/60/45/30/20/15/10/5 of 1,000 combinations; before it three on 250/199/156/
119/88/63/43/28/17/11/8/7/6/5. Everyone else goes in seed order. Picks 15-30 go to the playoff teams worst record
first, and round 2 to all 30 worst record first.

Backtest (--backtest): at 0, 200, ... 1,000 games into each regular season 2016-26 (2020 out), each team's rating as
the season odds build it (nba_games_build.season_views), the rest of the season simulated from it (rating shocks at the
walk-forward sd of data/nba_season_sd.json, scaled by k; game sd from the fit), then the play-in and the lottery. The
event: the team's own pick lands in the top 4. Scored by log loss against "if the season ended today" (the lottery odds
at today's record order, from 200 games in), with k picked leave one season out. Lottery results by seed:
Wikipedia's "<year> NBA draft" lottery tables (scripts/.cache/nba_lottery).
"""
import json
import math
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ODDS = {2019: [140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5], 0: [250, 199, 156, 119, 88, 63, 43, 28, 17, 11, 8, 7, 6, 5]}
EAST = frozenset({'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DET', 'IND', 'MIA', 'MIL', 'NY', 'ORL', 'PHI', 'TOR', 'WSH'})


def lottery(seeds, rng, year=2027):
    """seeds: the 14 lottery teams worst first -> those teams in pick order"""
    odds, draws = (ODDS[2019], 4) if year >= 2019 else (ODDS[0], 3)
    w = list(odds[:len(seeds)]); left = list(range(len(seeds))); won = []
    for _ in range(min(draws, len(seeds))):
        x = rng.random() * sum(w[i] for i in left)
        for i in left:
            x -= w[i]
            if x <= 0: break
        won.append(i); left.remove(i)
    return [seeds[i] for i in won] + [seeds[i] for i in left]


def order(wins, playoff, rng, year=2027):
    """one draft order: team -> [its round-1 pick, its round-2 pick] (own picks, before any trades)"""
    tb = {t: w + rng.random() * 1e-3 for t, w in wins.items()}
    lot = sorted((t for t in wins if t not in playoff), key=lambda t: tb[t])
    r1 = lottery(lot, rng, year) + sorted(playoff, key=lambda t: tb[t])
    r2 = sorted(wins, key=lambda t: tb[t])
    return {t: [r1.index(t) + 1, len(r1) + r2.index(t) + 1] for t in wins}


def playoff_teams(wins, rng, game, year=2027):
    """the 16 playoff teams from final wins: the top 8 a conference, from 2021 seeds 7-10 through the play-in.
    game(h, a) -> the winner of one game"""
    out = set()
    for conf in (EAST, frozenset(wins) - EAST):
        o = sorted(conf, key=lambda t: -(wins[t] + rng.random() * 1e-3))
        if year < 2021: out |= set(o[:8]); continue
        s7, s8, s9, s10 = o[6:10]
        w78 = game(s7, s8); l78 = s8 if w78 == s7 else s7
        out |= set(o[:6]) | {w78, game(l78, game(s9, s10))}
    return out


# ---------------------------------------------------------------- backtest
WIKI = {'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN', 'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI',
        'Cleveland Cavaliers': 'CLE', 'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET', 'Golden State Warriors': 'GS',
        'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND', 'Los Angeles Clippers': 'LAC', 'LA Clippers': 'LAC', 'Los Angeles Lakers': 'LAL',
        'Memphis Grizzlies': 'MEM', 'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN', 'New Orleans Pelicans': 'NO',
        'New York Knicks': 'NY', 'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
        'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SA', 'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTAH',
        'Washington Wizards': 'WSH'}
OWNER_ROWS = {(2017, 'BOS'): 'BKN'}   # rows listed under the pick's owner: Boston held Brooklyn's 2017 pick


def lottery_results():
    """year -> {team: its real pick} for the lottery teams (Wikipedia's lottery tables, the highlighted cell)"""
    import html
    W = os.path.join(HERE, '.cache', 'nba_lottery'); os.makedirs(W, exist_ok=True)
    out = {}
    for y in range(2016, 2027):
        p = os.path.join(W, f'w{y}.html')
        if not os.path.exists(p):
            import subprocess, time
            subprocess.run(['curl', '-sSLf', '-m', '30', '-A', 'Mozilla/5.0 (arkboard research; arkndjl.net)', '-o', p, f'https://en.wikipedia.org/wiki/{y}_NBA_draft'], check=False)
            time.sleep(3)
        s = open(p, encoding='utf-8').read()
        i = s.find('id="Draft_lottery"'); j = s.rfind('<table', 0, s.find('plainrowheaders', i)); k = s.find('</table>', j)
        res = {}
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', s[j:k], re.S):
            cells = re.findall(r'<t([dh])([^>]*)>(.*?)</t[dh]>', tr, re.S)
            txt = [re.sub(r'\[.*?\]', '', html.unescape(re.sub(r'<[^>]+>', '', c[2]))).strip() for c in cells]
            if len(txt) < 10 or not re.match(r'\d+[–-]\d+$', txt[1]): continue
            hi = [n for n, c in enumerate(cells) if 'background' in c[1] and n >= 3]
            t = WIKI[re.sub(r'\s*\(.*?\)', '', txt[0]).strip()]; t = OWNER_ROWS.get((y, t), t)
            res[t] = hi[0] - 2
        out[y] = res
    return out


def snapshots():
    """per season and checkpoint: ratings (season_views' composite), wins so far, games left (h, a, neutral)"""
    import nba_games as N
    import nba_games_fit as F
    games, names = N.load_hist()
    games.sort(key=lambda g: g['tip'])
    fit = json.load(open(F.N.FIT)); b = fit['coef']
    m = N.Model(names, fit['P'], inj=F.load_inj(), **fit['params'])
    CK = (0, 200, 400, 600, 800, 1000)
    teams = sorted(N.ARENA)
    # the Cup final (2024+): on the schedule as a regular-season game, out of the standings
    reg = {}
    for g in games:
        if g['t'] == 2: reg.setdefault(g['S'], []).append(g)
    cupf = set()
    for S, L in reg.items():
        dec = [g for g in L if g['n'] and g['tip'][5:7] == '12']
        if S >= 2024 and dec: cupf.add(max(dec, key=lambda g: g['tip'])['id'])
    snaps, S0, nreg = [], None, 0
    for g in games:
        if g['S'] != S0: S0 = g['S']; nreg = 0
        m.feats(g)
        if g['t'] == 2 and g['id'] not in cupf:
            if nreg in CK and g['S'] >= 2016 and g['S'] != 2020:
                L_ = m.lgp[0] / m.lgp[1]
                net = lambda t: m.rate(m.off, t) - m.rate(m.dfn, t)
                mk = sum(m.mkt[t] for t in teams) / len(teams)
                R = {}
                for t in teams:
                    V = m.lineup(t)
                    c = {'elo': (m.elo[t] - 1505) / 28, 'eff': net(t) * (L_ + m.rate(m.pace, t)) / 100, 'mkt': m.mkt[t] - mk, 'lin': V - m.rate(m.base, t, 1.0)}
                    R[t] = sum(b.get(f, 0.0) * v for f, v in c.items())
                av = sum(R.values()) / len(R)
                done = [x for x in reg[g['S']] if x['tip'] < g['tip'] and x['id'] not in cupf]
                w = dict.fromkeys(teams, 0)
                for x in done: w[x['h'] if x['hs'] > x['as'] else x['a']] += 1
                left = [(x['h'], x['a'], x['n']) for x in reg[g['S']] if x['tip'] >= g['tip'] and x['id'] not in cupf]
                snaps.append({'S': g['S'], 'ck': nreg, 'R': {t: R[t] - av for t in teams}, 'w': w, 'left': left, 'n': len(done) + len(left)})
            nreg += 1
        m.update(g)
    final = {}
    for S, L in reg.items():
        w = dict.fromkeys(teams, 0)
        for x in L:
            if x['id'] not in cupf: w[x['h'] if x['hs'] > x['as'] else x['a']] += 1
        final[S] = w
    return snaps, final, fit


def sim_top4(sn, fit, ab, k, sims, rng, nrng):
    """P(own pick in the top 4) per team from one snapshot"""
    import numpy as np
    teams = sorted(sn['R']); ix = {t: i for i, t in enumerate(teams)}
    a, bb = ab
    share = len(sn['left']) / sn['n']
    rsd = k * math.sqrt(max(0.05, a + bb * share))
    H = np.array([ix[h] for h, _, _ in sn['left']], int); A = np.array([ix[x] for _, x, _ in sn['left']], int)
    hfa = fit['coef']['home']; R = np.array([sn['R'][t] for t in teams])
    mu = R[H] - R[A] + np.array([0 if n else hfa for _, _, n in sn['left']])
    sd = fit['sd']; w0 = np.array([sn['w'][t] for t in teams])
    hit = np.zeros(len(teams)); slots = np.zeros((len(teams), 30))
    for s in range(sims):
        sh = nrng.normal(0, rsd, len(teams))
        d = mu + sh[H] - sh[A] + nrng.normal(0, sd, len(mu))
        w = w0 + np.bincount(np.where(d > 0, H, A), minlength=len(teams))
        W = {t: int(w[i]) for i, t in enumerate(teams)}
        game = lambda h, x: h if rng.gauss(sn['R'][h] - sn['R'][x] + sh[ix[h]] - sh[ix[x]] + hfa, sd) > 0 else x
        po = playoff_teams(W, rng, game, sn['S'])
        o = order(W, po, rng, sn['S'])
        for t in teams:
            if o[t][0] <= 4: hit[ix[t]] += 1
            slots[ix[t], o[t][0] - 1] += 1
    return {t: hit[ix[t]] / sims for t in teams}


def today_top4(sn, rng, sims=4000):
    """if the season ended today: the lottery on today's records (wins, then win% ties a coin flip)"""
    teams = sorted(sn['R']); played = {}
    for t in teams: played[t] = 0
    gp = (sn['n'] - len(sn['left'])) * 2 / len(teams)
    W = {t: sn['w'][t] for t in teams}
    hit = dict.fromkeys(teams, 0)
    for _ in range(sims):
        po = playoff_teams(W, rng, lambda h, a: h if rng.random() < 0.5 else a, sn['S'])
        o = order(W, po, rng, sn['S'])
        for t in teams: hit[t] += o[t][0] <= 4
    return {t: hit[t] / sims for t in teams}


def backtest():
    import numpy as np
    rng, nrng = random.Random(11), np.random.default_rng(11)
    res = lottery_results()
    import pickle
    pk = os.path.join(HERE, '.cache', 'nba_lottery', 'snaps.pkl')
    if os.path.exists(pk): snaps, final, fit = pickle.load(open(pk, 'rb'))
    else: snaps, final, fit = snapshots(); pickle.dump((snaps, final, fit), open(pk, 'wb'))
    ssd = json.load(open(os.path.join(os.path.dirname(HERE), 'data', 'nba_season_sd.json')))
    walk = {int(y): v for y, v in ssd['walk2018_26']['ab'].items()}
    KS = (0.5, 0.75, 1.0, 1.25, 1.5)
    rows = []   # (season, ck, team, outcome, today, {k: p})
    for sn in snaps:
        S = sn['S']; ab = walk.get(S, (ssd['a'], ssd['b']))   # 2016-17: the live fit (no walk-forward value)
        y = {t: 1 if res[S].get(t, 99) <= 4 else 0 for t in sn['R']}
        P = {k: sim_top4(sn, fit, ab, k, 1000, rng, nrng) for k in KS}
        td = today_top4(sn, rng) if sn['ck'] else None
        for t in sn['R']: rows.append((S, sn['ck'], t, y[t], td[t] if td else None, {k: P[k][t] for k in KS}))
        print(S, sn['ck'], 'done', flush=True)
    clip = lambda p: min(1 - 1e-3, max(1e-3, p))
    L = lambda p, y: -(y * math.log(clip(p)) + (1 - y) * math.log(1 - clip(p)))
    seasons = sorted({r[0] for r in rows})
    held, chosen = [], {}
    for S in seasons:
        k = min(KS, key=lambda k: sum(L(r[5][k], r[3]) for r in rows if r[0] != S)); chosen[S] = k
        held += [(r, r[5][k]) for r in rows if r[0] == S]
    kall = min(KS, key=lambda k: sum(L(r[5][k], r[3]) for r in rows))
    by_ck = {}
    for ck in sorted({r[1] for r in rows}):
        H = [(r, p) for r, p in held if r[1] == ck]
        e = {'n': len(H), 'sims': round(sum(L(p, r[3]) for r, p in H) / len(H), 4), 'brier': round(sum((p - r[3]) ** 2 for r, p in H) / len(H), 4)}
        if ck:
            e['today'] = round(sum(L(r[4], r[3]) for r, p in H) / len(H), 4)
            d = np.array([L(p, r[3]) - L(r[4], r[3]) for r, p in H])
            e['t'] = round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2)
            e['seasonsWon'] = f"{sum(1 for S in seasons if sum(L(p, r[3]) for r, p in H if r[0] == S) < sum(L(r[4], r[3]) for r, p in H if r[0] == S))}/{len(seasons)}"
        by_ck[ck] = e
    bins = ((0, .02), (.02, .1), (.1, .25), (.25, .45), (.45, 1.01))
    calib = []
    for lo, hi in bins:
        H = [(r, p) for r, p in held if lo <= p < hi]
        if H: calib.append({'bin': f'{lo:.2f}-{min(hi, 1):.2f}', 'n': len(H), 'sims': round(sum(p for _, p in H) / len(H), 3), 'real': round(sum(r[3] for r, _ in H) / len(H), 3)})
    out = {'_readme': __doc__.strip().split('\n\n')[2], 'kByHeldOutSeason': chosen, 'k': kall,
           'byCheckpoint': by_ck, 'calibration': calib,
           'kGrid': {k: round(sum(L(r[5][k], r[3]) for r in rows) / len(rows), 4) for k in KS}}
    json.dump(out, open(os.path.join(os.path.dirname(HERE), 'data', 'nba_lottery_backtest.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == '__main__' and '--backtest' in sys.argv:
    sys.path.insert(0, HERE)
    backtest()
