"""NFL payroll panel (spec: PANEL.md): every team season 2013 on, each player's cap hit and NFL WAR with that team.

Pay: OverTheCap through nflverse (historical_contracts.parquet), each player's season_history (year, club, cap number),
deduped by otc_id. No dead money rows (the file carries none). Value: the site's NFL WAR board (scripts/nfl_war.py board),
one row a player; a player on two clubs has his WAR split by his offense + defense snaps with each (kickers and punters go
to the club he kicked most for). Join by gsis id (board pfr id -> gsis through the season's nflverse roster), else the
shared name key plus club. Wins = regular season wins + half the ties (nflverse games.csv).

    python3 scripts/research/payrolls_nov28/nfl_panel.py            # boards cached under scripts/.cache/payrolls/
    python3 scripts/research/payrolls_nov28/nfl_panel.py --fresh    # rebuild the boards (and the in-progress season)
"""
import csv
import gzip
import json
import os
import sys
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCRIPTS)
import names as NM        # noqa: E402
import nfl_war            # noqa: E402
from xaav import NFL_CAP  # noqa: E402

CACHE = os.path.join(SCRIPTS, '.cache', 'payrolls')
OUT = os.path.join(HERE, 'panel_nfl.json.gz')
HC_URL = 'https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.parquet'
YEARS = range(2013, 2027)
LIVE = 2026          # season in progress: its row is season to date
# CBA minimum salary for a player with no credited seasons (the rookie minimum), $M
NFL_MIN = {2013: 0.405, 2014: 0.42, 2015: 0.435, 2016: 0.45, 2017: 0.465, 2018: 0.48, 2019: 0.495, 2020: 0.61,
           2021: 0.66, 2022: 0.705, 2023: 0.75, 2024: 0.795, 2025: 0.84, 2026: 0.885}
NICK = {'Cardinals': 'ARI', 'Falcons': 'ATL', 'Ravens': 'BAL', 'Bills': 'BUF', 'Panthers': 'CAR', 'Bears': 'CHI',
        'Bengals': 'CIN', 'Browns': 'CLE', 'Cowboys': 'DAL', 'Broncos': 'DEN', 'Lions': 'DET', 'Packers': 'GB',
        'Texans': 'HOU', 'Colts': 'IND', 'Jaguars': 'JAX', 'Chiefs': 'KC', 'Dolphins': 'MIA', 'Vikings': 'MIN',
        'Patriots': 'NE', 'Saints': 'NO', 'Giants': 'NYG', 'Jets': 'NYJ', 'Eagles': 'PHI', 'Steelers': 'PIT',
        '49ers': 'SF', 'Seahawks': 'SEA', 'Buccaneers': 'TB', 'Titans': 'TEN', 'Commanders': 'WAS', 'Redskins': 'WAS',
        'Football Team': 'WAS', 'Washington': 'WAS'}
# moved franchises: code by season (nflverse games / snap counts)
MOVED = {'Raiders': lambda y: 'OAK' if y <= 2019 else 'LV', 'Chargers': lambda y: 'SD' if y <= 2016 else 'LAC',
         'Rams': lambda y: 'STL' if y <= 2015 else 'LA'}


def code(nick, y):
    return MOVED[nick](y) if nick in MOVED else NICK.get(nick)


def contracts_path():
    p = os.path.join(CACHE, 'historical_contracts.parquet')
    if not os.path.exists(p):
        os.makedirs(CACHE, exist_ok=True)
        tmp = '/tmp/claude-0/pay/hc.parquet'
        if os.path.exists(tmp):
            open(p, 'wb').write(open(tmp, 'rb').read())
        else:
            req = urllib.request.Request(HC_URL, headers={'User-Agent': 'arkndjl.net research'})
            open(p, 'wb').write(urllib.request.urlopen(req, timeout=120).read())
    return p


def pay_rows():
    """{(year, code): [(id, name, gsis, cap $M)]}: one season_history a player (the longest of his contract rows)"""
    import pyarrow.parquet as pq
    t = pq.read_table(contracts_path(), columns=['player', 'otc_id', 'gsis_id', 'season_history']).to_pylist()
    best = {}
    for r in t:
        k = r['otc_id'] or r['gsis_id'] or r['player']
        h = r['season_history'] or []
        if k not in best or len(h) > len(best[k]['season_history'] or []):
            best[k] = r
    out, bad = defaultdict(list), Counter()
    for k, r in best.items():
        seen = {}
        for e in r['season_history'] or []:
            try:
                y = int(e['year'])
            except (TypeError, ValueError):
                continue
            if y not in YEARS or e.get('cap_number') is None:
                continue
            c = code(e['team'], y)
            if not c:
                bad[e['team']] += 1
                continue
            seen[(y, c)] = seen.get((y, c), 0.0) + float(e['cap_number'])
        for (y, c), cap in seen.items():
            out[(y, c)].append((f"otc{r['otc_id']}" if r['otc_id'] else r['player'], r['player'], r['gsis_id'] or '', cap))
    if bad:
        print('unmapped clubs:', dict(bad))
    return out


def board_of(y, fresh=False):
    """slim board rows for season y with WAR split by club: [{pfr, gsis, n, t: {code: WAR}}], cached"""
    p = os.path.join(CACHE, f'nfl_board_{y}.json')
    if os.path.exists(p) and not fresh and y != LIVE:
        return json.load(open(p))
    out, _, _ = nfl_war.board(y, fresh=fresh and y == LIVE)
    by_pfr, by_name = nfl_war.gsis_map(y)
    snaps = defaultdict(Counter)
    sc = nfl_war.get(f'snap_counts_{y}.csv', f'{nfl_war.REL}/snap_counts/snap_counts_{y}.csv')
    for r in csv.DictReader(open(sc, newline='', encoding='utf-8')):
        if r['game_type'] == 'REG':
            snaps[r['pfr_player_id']][r['team']] += nfl_war.num(r['offense_snaps']) + nfl_war.num(r['defense_snaps'])
    rows = []
    for b in out:
        tms = b['tm'].split('/')
        s = snaps.get(b['id'], {})
        tot = sum(s.get(t, 0) for t in tms)
        split = ({t: b['war'] * s.get(t, 0) / tot for t in tms if s.get(t, 0)} if len(tms) > 1 and tot and b['_g'] != 'ST'
                 else {b['t']: b['war']})
        gs = b['id'] if b['id'].startswith('00-') else by_pfr.get(b['id']) or by_name.get((NM.key(b['n']), b['t'])) or ''
        rows.append({'pfr': b['id'], 'gsis': gs, 'n': b['n'], 't': {t: round(v, 3) for t, v in split.items()}})
    os.makedirs(CACHE, exist_ok=True)
    json.dump(rows, open(p, 'w'))
    return rows


def team_wins():
    """{(season, code): [wins + ties / 2, games]} regular season, played games only"""
    W = {}
    for g in nfl_war.rows(nfl_war.get('games.csv', nfl_war.GAMES)):
        if g['game_type'] != 'REG' or g['home_score'] in ('', 'NA') or int(g['season']) not in YEARS:
            continue
        y, hs, as_ = int(g['season']), float(g['home_score']), float(g['away_score'])
        for t, a, b in ((g['home_team'], hs, as_), (g['away_team'], as_, hs)):
            w = W.setdefault((y, t), [0.0, 0])
            w[0] += 1.0 if a > b else 0.5 if a == b else 0.0
            w[1] += 1
    return W


def main(fresh=False):
    if fresh:   # the in-progress season's games
        nfl_war.get('games.csv', nfl_war.GAMES, fresh=True)
    P = pay_rows()
    W = team_wins()
    seasons, panel, rep = {}, [], []
    for y in YEARS:
        B = board_of(y, fresh)
        bg = {b['gsis']: b for b in B if b['gsis']}
        bn = defaultdict(list)
        for b in B:
            for t in b['t']:
                bn[(NM.key(b['n']), t)].append(b)
        teams = sorted(t for (s, t) in W if s == y)
        gp = max(W[(y, t)][1] for t in teams)
        seasons[str(y)] = {'cap': NFL_CAP[y], 'min': NFL_MIN[y], 'gp': 17 if y >= 2021 else 16, **({'partial': 1, 'gp_played': gp} if y == LIVE else {})}
        used = set()
        R = {t: [] for t in teams}
        pay_j = pay_all = war_j = war_all = 0.0
        for t in teams:
            for pid, n, gs, cap in P.get((y, t), ()):
                b = bg.get(gs) if gs else None
                if b is None or t not in b['t']:
                    c = [x for x in bn.get((NM.key(n), t), ()) if (id(x), t) not in used]
                    b = c[0] if len(c) == 1 else (b if b is not None and t in b['t'] else None)
                v = None
                if b is not None and (id(b), t) not in used:
                    used.add((id(b), t))
                    v = round(b['t'][t], 2)
                    pay_j += cap
                pay_all += cap
                R[t].append({'id': gs or pid, 'n': n, 'pay': round(cap, 3), 'v': v})
        for b in B:
            for t, w in b['t'].items():
                war_all += w
                if (id(b), t) in used:
                    war_j += w
                elif t in R:
                    R[t].append({'id': b['gsis'] or b['pfr'], 'n': b['n'], 'pay': None, 'v': round(w, 2)})
        for t in teams:
            panel.append({'s': y, 'tm': t, 'w': W[(y, t)][0], 'gp': W[(y, t)][1], 'pts': None,
                          'pl': sorted(R[t], key=lambda p: -(p['pay'] or 0))})
        sw = [(sum(p['v'] or 0 for p in r['pl']), r['w']) for r in panel if r['s'] == y]
        mx, my = sum(a for a, _ in sw) / len(sw), sum(b for _, b in sw) / len(sw)
        cov = sum((a - mx) * (b - my) for a, b in sw)
        cor = cov / (sum((a - mx) ** 2 for a, _ in sw) * sum((b - my) ** 2 for _, b in sw)) ** 0.5
        pay_t = sum(sum(p['pay'] or 0 for p in r['pl']) for r in panel if r['s'] == y) / len(teams)
        rep.append((y, len(teams), pay_j / pay_all, war_j / war_all, mx, my, cor, pay_t))
    print('season teams  pay$->WAR  WAR->pay  teamWAR  wins   r(WAR,w)  payroll/team')
    for y, n, a, b, mx, my, cor, pt in rep:
        print(f'{y}  {n:4d}   {a:7.1%}   {b:7.1%}   {mx:6.1f}  {my:5.2f}   {cor:.3f}   {pt:6.1f} (cap {NFL_CAP[y]})')
    doc = {'lg': 'nfl', 'unit': 'wins',
           'src': ('Pay: OverTheCap cap numbers via nflverse historical_contracts (season_history, deduped by otc_id); no dead '
                   'money in the source, so no dead rows. Value: site NFL WAR board (scripts/nfl_war.py board), a two-club '
                   "player's WAR split by his offense + defense snaps with each, kickers/punters to their main club. Join: gsis "
                   'id, else names.py key + club. w = regular-season wins + ties/2 (nflverse games.csv). min = CBA rookie '
                   f'minimum. {LIVE} is season to date.'),
           'seasons': seasons, 'rows': panel}
    with gzip.open(OUT, 'wt', encoding='utf-8') as f:
        json.dump(doc, f, separators=(',', ':'))
    print('wrote', OUT, len(panel), 'team seasons')


if __name__ == '__main__':
    main('--fresh' in sys.argv)
