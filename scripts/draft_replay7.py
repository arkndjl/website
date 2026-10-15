"""Seven-round draft replay for the mock draft (mockDraft in scripts/cfb_teams.mjs): specialists, FCS, team needs,
team tendencies, and draft-day trades in every round.

Replays the 2020-25 drafts pick by pick in the real order (after trades), all seven rounds, from DraftTek's final
boards (scripts/draft_backtest.py writes scripts/.cache/draft/rows.json) through the board-to-pick curve
(BOARD_PICK). Each team takes the board player with the best mock utility: -ln xPick + need - dup - run - set-QB
block (the live constants), plus the candidate terms. Every term is scored leave-one-draft-out: a weight is chosen
on the other five drafts and scored on the sixth, and the team tendencies themselves come only from drafts before
the one replayed.

Needs are rebuilt the way fetchNflNeeds builds them live, as of the October before each draft: the team's roster
that season (nflverse rosters), each player's quality the better of his draft capital on a rookie deal and his
pay against the top of his position (OverTheCap contracts, share of the cap), cut for age and an expiring deal;
a room's need is 1 - the quality of its starters, averaged with its rank among the 32.

Metrics (per draft, averaged):
  team7 / team3: the share of each team's real picks (by position group) that the replay also gives that team, in
                 rounds 1-7 / 1-3 (multiset overlap): how well the mock knows who takes what
  cnt7:          sum over positions (K, P and LS included) and rounds 1-7 of |replayed - real picks|
  mae100:        mean |replayed - real pick| for players really taken in the top 100 (undrafted = 290)
Writes data/cfb_draft_replay7.json. Usage: python3 scripts/draft_replay7.py (needs numpy; run draft_backtest.py first).
"""
import os, subprocess, csv, json, math, re, collections, gzip, statistics
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'scripts', '.cache', 'draft'); os.chdir(W)
NV = 'https://github.com/nflverse/nflverse-data/releases/download/'
get = lambda out, url: os.path.exists(out) or subprocess.run(['curl', '-sSLf', '-o', out, url])
YEARS = list(range(2020, 2026))
for y in range(2019, 2025): get(f'roster_{y}.csv', NV + f'rosters/roster_{y}.csv')
get('contracts.csv.gz', NV + 'contracts/historical_contracts.csv.gz')
get('games.csv', 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv')
get('trades.csv', 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/trades.csv')
get('combine.csv', NV + 'combine/combine.csv')
rows = json.load(open('rows.json'))
boards = {(b['year'], b['rank']): b for b in json.load(open('boards.json'))}
dp = list(csv.DictReader(open('draft_picks.csv')))
TF = {'OAK': 'LV', 'SD': 'LAC', 'STL': 'LA', 'LAR': 'LA', 'GNB': 'GB', 'KAN': 'KC', 'NWE': 'NE', 'NOR': 'NO', 'SFO': 'SF', 'TAM': 'TB', 'LVR': 'LV', 'SDG': 'LAC'}
tf = lambda t: TF.get(t, t)
def norm(n):
    n = re.sub(r'\(.*?\)', '', n or '').lower().replace('.', '').replace("'", '').replace('’', '')
    n = re.sub(r'\b(jr|sr|ii|iii|iv|v)\b', '', n); return re.sub(r'[^a-z]', '', n)
SPEC = ('K', 'P', 'LS')
G = ['QB', 'RB', 'WR', 'TE', 'OL', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P', 'LS']
NK = ['QB', 'RB', 'WR', 'TE', 'OT', 'G', 'C', 'EDGE', 'DL', 'LB', 'CB', 'S', 'K', 'P', 'LS']
NKG = {'OT': 'OL', 'G': 'OL', 'C': 'OL'}
NG = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OL', 'OT': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'DE': 'EDGE', 'OLB': 'EDGE',
      'DT': 'DL', 'DL': 'DL', 'NT': 'DL', 'LB': 'LB', 'ILB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'SAF': 'S', 'FS': 'S', 'K': 'K', 'P': 'P', 'LS': 'LS'}
# the live constants (cfb_teams.mjs)
NEED_W, NEED_MIN = 0.45, 0.6
QB_DUP, DUP, QB_BLOCK, RUN = 1.0, 0.15, 0.8, 0.15
STARTERS = {'QB': 1, 'RB': 1, 'WR': 3, 'TE': 1, 'OT': 2, 'G': 2, 'C': 1, 'EDGE': 2, 'DL': 2, 'LB': 2, 'CB': 3, 'S': 2, 'K': 1, 'P': 1, 'LS': 1}
TOP_PAY = {'QB': 55e6, 'RB': 14e6, 'WR': 33e6, 'TE': 18e6, 'OT': 25e6, 'G': 20e6, 'C': 18e6, 'EDGE': 32e6, 'DL': 30e6, 'LB': 20e6, 'CB': 25e6, 'S': 20e6,
           'K': 6e6, 'P': 4e6, 'LS': 1.6e6}
CAP26 = 301.2e6
UND = 290
BP = json.load(open(os.path.join(ROOT, 'data', 'cfb_draft_backtest.json')))['curve']
lnx = lambda rk: BP[0] + BP[1] * math.log(rk) + BP[2] * math.log(rk) ** 2

# ---- prospects -------------------------------------------------------------------------------------------
BOARD_NK = {'OT': 'OT', 'OG': 'G', 'OC': 'C', 'OL': 'G', 'PK': 'K', 'P': 'P', 'LS': 'LS'}
teams_conf = json.load(open(os.path.join(ROOT, 'data', 'cfb_teams.json')))['teams']
CONF = {}
for t in teams_conf:
    for k in [t['team'], t.get('full') or '', t.get('abbr') or '']:
        if k: CONF[norm(k)] = t['conf']
ALIAS = {'appalachianstate': 'appstate', 'appalachianst': 'appstate', 'centralflorida': 'ucf', 'southernmississippi': 'southernmiss', 'ullafayette': 'louisiana',
         'miamifl': 'miami', 'mississippi': 'olemiss', 'pittsburgh': 'pitt', 'northcarolinast': 'ncstate', 'northcarolinastate': 'ncstate', 'bostoncol': 'bostoncollege',
         'alabirmingham': 'uab', 'texassanantonio': 'utsa', 'texaselpaso': 'utep', 'lamonroe': 'ulmonroe', 'middletennst': 'middletennessee', 'louisianastate': 'lsu',
         'brighamyoung': 'byu', 'texaschristian': 'tcu', 'southernmethodist': 'smu', 'southerncalifornia': 'usc', 'connecticut': 'uconn', 'floridaintl': 'fiu',
         'nevadalasvegas': 'unlv', 'washingtonst': 'washingtonstate'}
def conf_of(school):
    s = norm((school or '').replace(' St.', ' State'))
    return CONF.get(ALIAS.get(s, s)) or CONF.get(ALIAS.get(norm(school), norm(school)))
P5 = {'SEC', 'Big Ten', 'ACC', 'Big 12', 'Pac-12'}
def lvl(c): return 'P5' if c in P5 else 'G5' if c else 'FCS+'
# size and speed z within the position group (combine, all years)
comb = list(csv.DictReader(open('combine.csv')))
def ht_in(h):
    m = re.match(r'(\d+)-(\d+)', h or ''); return int(m[1]) * 12 + int(m[2]) if m else None
zs = collections.defaultdict(lambda: collections.defaultdict(list))
for r in comb:
    g = NG.get(r['pos'])
    if not g: continue
    if r['wt']: zs[g]['wt'].append(float(r['wt']))
    if r['forty']: zs[g]['forty'].append(float(r['forty']))
ZS = {g: {k: (statistics.mean(v), statistics.pstdev(v) or 1) for k, v in d.items() if len(v) > 20} for g, d in zs.items()}
def z(g, k, x):
    if x is None or g not in ZS or k not in ZS[g]: return 0.0
    m, s = ZS[g][k]; return max(-3, min(3, (x - m) / s))
for r in rows:
    b = boards.get((r['year'], r['rank']), {})
    r['school'] = b.get('school')
    r['conf'] = conf_of(r['school']); r['lvl'] = lvl(r['conf'])
    r['nk'] = BOARD_NK.get(r['pos']) or ('G' if r['g'] == 'OL' else r['g'])
    r['grp'] = r['nk'] if r['nk'] in SPEC else NKG.get(r['nk'], r['nk'])
    r['szz'] = z(r['grp'], 'wt', r['wt']); r['fz'] = -z(r['grp'], 'forty', r['forty'])
    r['young'] = bool(r['under'])

# ---- real drafts ------------------------------------------------------------------------------------------
pmap = {}
for r in rows:
    if r['pick']: pmap[(r['year'], r['pick'])] = r
order, real = {}, {}
for Y in YEARS:
    L = sorted([r for r in dp if int(r['season']) == Y], key=lambda r: int(r['pick']))
    order[Y] = [(int(r['pick']), int(r['round']), tf(r['team'])) for r in L]
    real[Y] = []
    for r in L:
        b = pmap.get((Y, int(r['pick'])))
        g = b['grp'] if b else ('OL' if NG.get(r['position']) == 'OL' else NG.get(r['position'], 'X'))
        real[Y].append((int(r['pick']), int(r['round']), tf(r['team']), g))
UNDRAFTED_REAL = {Y: sum(1 for r in rows if r['year'] == Y and r['pick']) for Y in YEARS}

def per_round(excl):   # picks per position and round, 2015-25 less the test draft (the mock's perRound prior: rounds 1-3)
    c = collections.Counter(); ys = [y for y in range(2015, 2026) if y != excl]
    for r in dp:
        if int(r['season']) in ys: c[(NG.get(r['position'], 'X'), int(r['round']))] += 1
    return {(g, rd): c[(g, rd)] / len(ys) for g in G for rd in range(1, 8)}

# ---- specialists: the i-th kicker / punter / snapper off the board goes at the i-th one's historical slot ----
SPEC_HIST = collections.defaultdict(list)
for r in dp:
    if r['position'] in SPEC and 2010 <= int(r['season']) <= 2025: SPEC_HIST[(r['position'], int(r['season']))].append(int(r['pick']))
def spec_slots(excl, pos, n=6):
    ys = [y for y in range(2010, 2026) if y != excl]
    out = []
    for i in range(n):
        v = [sorted(SPEC_HIST[(pos, y)])[i] if len(SPEC_HIST[(pos, y)]) > i else 1e4 for y in ys]
        out.append(statistics.median(v))   # past the draft's end in most years: undrafted (1e4, never taken)
    return out

# ---- needs as of the October before each draft ---------------------------------------------------------------
con = list(csv.DictReader(gzip.open('contracts.csv.gz', 'rt')))
cbyname = collections.defaultdict(list)
for c in con:
    try: cbyname[norm(c['player'])].append((int(c['year_signed']), int(c['years']), float(c['apy_cap_pct'] or 0), float(c['apy'] or 0)))
    except ValueError: pass
DC = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'WR': 'WR', 'TE': 'TE', 'T': 'OT', 'OT': 'OT', 'G': 'G', 'OG': 'G', 'C': 'C', 'OL': 'G', 'DE': 'EDGE', 'DT': 'DL', 'NT': 'DL',
      'DL': 'DL', 'MLB': 'LB', 'ILB': 'LB', 'LB': 'LB', 'CB': 'CB', 'DB': 'CB', 'S': 'S', 'FS': 'S', 'SS': 'S', 'SAF': 'S', 'K': 'K', 'P': 'P', 'LS': 'LS'}
def rooms(Y):
    S = Y - 1; out = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in csv.DictReader(open(f'roster_{S}.csv')):
        if r['status'] not in ('ACT', 'RES', 'INA'): continue
        dcp = r['depth_chart_position'] or r['position']
        g = DC.get(dcp)
        if dcp == 'OLB' or (not g and r['position'] == 'LB'): g = 'EDGE' if float(r['weight'] or 0) >= 243 else 'LB'
        if not g: continue
        bd = r['birth_date'] or ''; age = S - int(bd[:4]) + 0.5 if bd[:4].isdigit() else 27
        exp = int(r['years_exp'] or 0); dn = int(r['draft_number']) if (r['draft_number'] or '').isdigit() else None
        ry = int(r['rookie_year']) if (r['rookie_year'] or '').isdigit() else None
        rookie = exp <= 3 and ry is not None and S - ry <= 3
        dq = (max(0.15, 1 - 0.13 * math.log(dn)) if dn else 0.05) if rookie else 0
        deals = [d for d in cbyname.get(norm(r['full_name']), []) if d[0] <= S < d[0] + d[1]]
        left = None; pay = 0
        if deals:
            d = max(deals); left = d[0] + d[1] - 1 - S; pay = d[2] * CAP26
        q = max(dq, min(1, pay / TOP_PAY[g]))
        if g not in SPEC:
            if age >= (35 if g == 'QB' else 30): q *= 0.7
            if age >= (38 if g == 'QB' else 32): q *= 0.6
        elif age >= 38: q *= 0.7
        if left is not None and left <= 0 and exp >= 5: q *= 0.6
        if g == 'QB' and pay >= 0.7 * TOP_PAY['QB'] and (left or 0) >= 2 and age < 35: q = max(q, 0.9)
        if g == 'QB' and rookie and dn and dn <= 32 and S - ry <= 1: q = max(q, 0.85)
        out[tf(r['team'])][g].append(q)
    return out
ROOMS = {Y: rooms(Y) for Y in YEARS}
def need_table(Y, p=1.0, cut=None):
    """need by team and room. p: the power mean of the starters' gaps (1 - q): 1 = the live average, larger leans on
    the weakest starter (an elite CB1 doesn't hide a weak CB2). Returns raw gaps, scores (raw averaged with rank) and the
    sorted starter qualities for refilling."""
    R = ROOMS[Y]; raw = {}; qs = {}
    for t, rm in R.items():
        for g in NK:
            n = STARTERS[g]; top = sorted(rm.get(g, []), reverse=True)[:n]; top += [0.0] * (n - len(top))
            qs[(t, g)] = top
            raw[(t, g)] = gap(top, p)
    rk = {}
    for g in NK:
        L = sorted([t for t in R], key=lambda t: raw[(t, g)])
        for i, t in enumerate(L): rk[(t, g)] = i / (len(L) - 1)
    return raw, rk, qs
def gap(top, p):
    gs = [1 - q for q in top]
    if p == 'max': return max(gs)
    return (sum(x ** p for x in gs) / len(gs)) ** (1 / p)

# ---- team tendencies (drafts before the one replayed) ------------------------------------------------------------
coach = {}
for r in csv.DictReader(open('games.csv')):
    if r['game_type'] == 'REG':
        s = int(r['season'])
        for side in ('home', 'away'):
            k = (s, tf(r[side + '_team']))
            if k not in coach or int(r['week']) < coach[k][0]: coach[k] = (int(r['week']), r[side + '_coach'])
COACH = {k: v[1] for k, v in coach.items()}
cmb_by = {r['pfr_id']: r for r in comb if r['pfr_id']}
HIST = []
for r in dp:
    y = int(r['season'])
    if y < 2005: continue
    g = NG.get(r['position'])
    if not g: continue
    c = cmb_by.get(r['pfr_player_id'])
    cf = conf_of(r['college'])
    HIST.append(dict(y=y, t=tf(r['team']), g=g, rd=int(r['round']), coach=COACH.get((y, tf(r['team']))), lvl=lvl(cf),
                     young=(r['age'] or '99') <= '21', szz=z(g, 'wt', float(c['wt'])) if c and c['wt'] else None,
                     fz=-z(g, 'forty', float(c['forty'])) if c and c['forty'] else None))
def tendencies(Y, how='team', win=5):
    """per team: categorical log ratios (position group, school level, underclassman) and continuous preferences
    (size, speed), from drafts before Y: the franchise's last `win` drafts (team) or the current head coach's
    drafts anywhere (coach)."""
    lg = [h for h in HIST if Y - win <= h['y'] < Y]
    out = {}
    for t in set(x[2] for x in order[Y]):
        if how == 'team': mine = [h for h in lg if h['t'] == t]
        else:
            hc = COACH.get((Y, t)); mine = [h for h in HIST if h['y'] < Y and h['coach'] == hc and h['y'] >= Y - 12] if hc else []
        out[t] = mine
    return lg, out
def cat_ratio(lg, mine, key, k):
    L = collections.Counter(h[key] for h in lg); n = len(lg); M = collections.Counter(h[key] for h in mine); m = len(mine)
    return {c: math.log(((M[c] + k * L[c] / n) / (m + k)) / (L[c] / n)) for c in L}
def cont_pref(lg, mine, key, k):
    lv = [h[key] for h in lg if h[key] is not None]; mv = [h[key] for h in mine if h[key] is not None]
    mu = statistics.mean(lv) if lv else 0
    return sum(x - mu for x in mv) / (len(mv) + k)

# ---- the replay ---------------------------------------------------------------------------------------------
def sim(Y, prm):
    pr = per_round(Y)
    pool = [r for r in rows if r['year'] == Y and r['g'] != 'X']
    if prm.get('spec') == 'excl': pool = [r for r in pool if r['grp'] not in SPEC]
    lx = np.array([lnx(r['rank']) for r in pool])
    if prm.get('spec') == 'order':
        for pos in SPEC:
            sl = spec_slots(Y, pos); idx = [i for i, r in enumerate(pool) if r['grp'] == pos]
            for j, i in enumerate(sorted(idx, key=lambda i: pool[i]['rank'])): lx[i] = math.log(sl[j] if j < len(sl) else 1e4)
    gi = np.array([G.index(r['grp']) for r in pool]); ni = np.array([NK.index(r['nk']) for r in pool])
    teams = sorted(set(x[2] for x in order[Y]))
    # needs
    p = prm.get('needp', 1.0)
    raw, rk, qs = need_table(Y, p)
    wpos = prm.get('wpos', {})
    def score(t, g): return min(1.0, (raw[(t, g)] + rk[(t, g)]) / 2) if (t, g) in raw else 0.5
    need = {t: np.array([score(t, g) for g in NK]) for t in teams}
    qbneed_only = prm.get('needs') == 'qb'
    wv = np.array([wpos.get(g, 1.0) for g in NK])
    # tendencies
    tend = {t: np.zeros(len(pool)) for t in teams}
    if prm.get('tend'):
        lg, mine = tendencies(Y, prm.get('how', 'team'), prm.get('win', 5))
        for t in teams:
            v = np.zeros(len(pool)); M = mine.get(t, [])
            for f, w in prm['tend'].items():
                if f in ('g', 'lvl', 'young'):
                    cr = cat_ratio(lg, M, f, prm.get('k', 30))
                    key = 'grp' if f == 'g' else f
                    v += w * np.array([cr.get(('OL' if r[key] in ('OT', 'G', 'C') else r[key]) if f == 'g' else r[key], 0.0) for r in pool])
                else:
                    pf = cont_pref(lg, M, f, prm.get('kc', 10))
                    v += w * pf * np.array([r[f] for r in pool])
            tend[t] = v
    taken = np.zeros(len(pool), bool); tpos = collections.defaultdict(lambda: np.zeros(len(G))); rc = collections.Counter(); out = {}
    dupw = np.array([QB_DUP if g in ('QB',) + SPEC else DUP for g in G])
    for pk, rd, t in order[Y]:
        ri = rd if prm.get('runrounds') == 7 else min(rd, 3)
        nv = need[t]
        if qbneed_only:
            nb = np.full(len(NK), 0.5); nb[0] = nv[0]; nv_use = nb
        else: nv_use = nv
        u = -lx + prm.get('needw', NEED_W) * (wv * nv_use)[ni] - tpos[t][gi] * dupw[gi] + tend[t]
        cap = {g: max(1, round(pr.get((g, ri), 3) * 1.25)) if g not in SPEC else 4 for g in G}
        runp = np.array([prm.get('runw', RUN) * (rc[(g, rd)] - cap[g] + 1) if rc[(g, rd)] >= cap[g] else 0 for g in G])
        u -= runp[gi]
        if nv[0] < NEED_MIN and rd <= 3: u -= QB_BLOCK * (gi == 0)
        u[taken] = -1e9
        i = int(np.argmax(u)); r = pool[i]; taken[i] = True
        tpos[t][gi[i]] += 1; rc[(r['grp'], rd)] += 1
        out[(r['name'], r['rank'])] = (pk, rd, t, r['grp'])
        k = NK.index(r['nk']); cap_ = max(0.15, 1 - 0.13 * math.log(pk))
        if prm.get('fill') == 'slot':
            top = sorted(qs[(t, r['nk'])] + [cap_], reverse=True)[:STARTERS[r['nk']]]; qs[(t, r['nk'])] = top
            raw[(t, r['nk'])] = gap(top, p); need[t][k] = score(t, r['nk'])
        else: need[t][k] *= 1 - cap_ / STARTERS[r['nk']]
    return out
def metrics(Y, res):
    simt = collections.Counter((t, g) for pk, rd, t, g in res.values())
    simt3 = collections.Counter((t, g) for pk, rd, t, g in res.values() if rd <= 3)
    rl = collections.Counter((t, g) for pk, rd, t, g in real[Y]); rl3 = collections.Counter((t, g) for pk, rd, t, g in real[Y] if rd <= 3)
    sc = collections.Counter((g, rd) for pk, rd, t, g in res.values()); ac = collections.Counter((g, rd) for pk, rd, t, g in real[Y])
    e = [abs(r['pick'] - res.get((r['name'], r['rank']), (UND,))[0]) for r in rows if r['year'] == Y and r['pick'] and r['pick'] <= 100]
    # exact: the share of board players really drafted whom the replay sends to the same team; attr: per attribute
    # (size, speed, small school, underclassman), the mean squared gap across teams between the replayed and real
    # class means (a team that likes big, fast, small-school or young players)
    held = {pk: t for pk, rd, t in order[Y]}
    br = [r for r in rows if r['year'] == Y and r['pick']]
    ex = sum(1 for r in br if res.get((r['name'], r['rank']), (0, 0, None))[2] == held.get(r['pick'])) / len(br)
    byname = {(r['name'], r['rank']): r for r in rows if r['year'] == Y}
    attr = {}
    for a, f in (('size', lambda r: r['szz']), ('speed', lambda r: r['fz']), ('small', lambda r: float(r['lvl'] != 'P5')), ('young', lambda r: float(r['young']))):
        sm = collections.defaultdict(list); rm = collections.defaultdict(list)
        for k, (pk, rd, t, g) in res.items(): sm[t].append(f(byname[k]))
        for r in br: rm[held[r['pick']]].append(f(r))
        attr[a] = float(np.mean([(np.mean(sm[t]) - np.mean(rm[t])) ** 2 for t in rm if sm[t]]))
    return dict(exact=ex, **{'a_' + k: v for k, v in attr.items()},team7=sum((rl & simt).values()) / sum(rl.values()), team3=sum((rl3 & simt3).values()) / sum(rl3.values()),
                cnt7=sum(abs(sc[(g, rd)] - ac[(g, rd)]) for g in G for rd in range(1, 8)), mae100=float(np.mean(e)),
                spec=[sum(sc[(g, rd)] for rd in range(1, 8)) for g in SPEC], specReal=[sum(ac[(g, rd)] for rd in range(1, 8)) for g in SPEC])
CACHE = {}
def evaluate(prm):
    key = json.dumps(prm, sort_keys=True)
    if key not in CACHE: CACHE[key] = {Y: metrics(Y, sim(Y, prm)) for Y in YEARS}
    return CACHE[key]
def summary(byY, keys=('team7', 'team3', 'exact', 'cnt7', 'mae100', 'a_size', 'a_speed', 'a_small', 'a_young')):
    return {k: round(float(np.mean([byY[Y][k] for Y in byY])), 4) for k in keys}
def lodo(base, grid, obj='team7', years=YEARS):
    """grid: list of param dicts layered on base. For each draft, the setting that scores best on the other five
    (obj; higher better for team, lower for errors) is scored on it."""
    sign = 1 if obj.startswith('team') or obj == 'exact' else -1
    res = [evaluate({**base, **g}) for g in grid]
    out = {}; chosen = []
    for Y in years:
        tr = [y for y in years if y != Y]
        b = max(range(len(grid)), key=lambda i: sign * np.mean([res[i][y][obj] for y in tr]))
        out[Y] = res[b][Y]; chosen.append(grid[b])
    return out, chosen


# ---- history that isn't a replay: trades by round, the future-pick discount, FCS draftees, the kicker need --------------
mtv = lambda p: math.exp(-0.148 * max(0, p - 1) ** 0.698)
def trade_history():
    """draft-day trade-ups 2015-25 by the round of the pick moved up to (nflverse trades; the draft's three days are
    the dates with the most current-year pick deals; pick-only deals between two teams): per year, the median jump,
    the share sending a later draft's pick, and the chart value of a next-year pick as a share of the same round's
    middle pick now (deals where the team moving up sends this year's picks plus later ones)."""
    R = list(csv.DictReader(open('trades.csv')))
    n = collections.Counter((r['season'], r['trade_date']) for r in R if r['pick_season'] == r['season'] and r['pick_number'] and r['trade_date'][5:7] in ('04', '05'))
    days = {s: set(sorted([d for (y, d) in n if y == str(s)], key=lambda d: -n[(str(s), d)])[:3]) for s in range(2010, 2026)}
    deals = collections.defaultdict(list)
    for r in R:
        s = int(r['season'])
        if s in days and r['trade_date'] in days[s]: deals[r['trade_id']].append(r)
    by = collections.defaultdict(list); disc = []
    for rs in deals.values():
        s = int(rs[0]['season'])
        if len({r['gave'] for r in rs} | {r['received'] for r in rs}) != 2 or any(not r['pick_season'] for r in rs): continue
        cur = [(int(r['pick_number']), r['received'], r['gave'], int(r['pick_round'])) for r in rs if r['pick_season'] == str(s) and r['pick_number']]
        if not cur: continue
        b, U, Dn, rd = min(cur)
        sentU = [p for p, rec, g, _ in cur if g == U]
        futU = [int(r['pick_round'] or 0) for r in rs if r['gave'] == U and int(r['pick_season']) > s]
        futD = [1 for r in rs if r['gave'] == Dn and int(r['pick_season']) > s]
        if s >= 2015: by[rd].append(dict(gap=min(sentU) - b if sentU else None, fut=bool(futU)))
        if futU and not futD and all(futU) and sentU:
            recv = sum(mtv(p) for p, rec, g, _ in cur if rec == U); given = sum(mtv(p) for p, rec, g, _ in cur if g == U)
            disc.append((recv - given) / sum(mtv(16 + 32 * (r - 1)) for r in futU))
    out = {}
    for rd in range(1, 8):
        L = by[rd]; gaps = sorted(x['gap'] for x in L if x['gap'] is not None)
        out[rd] = dict(perYear=round(len(L) / 11, 2), gapMedian=statistics.median(gaps) if gaps else None, gapP75=gaps[3 * len(gaps) // 4] if gaps else None,
                       futureShare=round(sum(x['fut'] for x in L) / max(1, len(L)), 2))
    return dict(byRound=out, perYear=round(sum(len(L) for L in by.values()) / 11, 1), futureDiscount=dict(n=len(disc), median=round(statistics.median(disc), 3)),
                oneRoundLater=[round(mtv(16 + 32 * r) / mtv(16 + 32 * (r - 1)), 3) for r in range(1, 7)])
def fcs_history():
    d = json.load(open(os.path.join(ROOT, 'static', 'data', 'cfb-all.json'))); c = d['cols']
    fcs = {norm(r[c.index('team')]) for r in d['rows'] if r[c.index('div')] == 'FCS'}
    fbs = {norm(r[c.index('team')]) for r in d['rows'] if r[c.index('div')] == 'FBS'}
    k = lambda col: norm(re.sub(r'\(.*?\)', '', col.replace(' St.', ' State').replace('SE ', 'Southeast ').replace('S.F. Austin', 'Stephen F. Austin')))
    cnt = collections.Counter(); rd = collections.Counter(); tot = collections.Counter()
    for r in dp:
        y = int(r['season'])
        if y < 2015: continue
        tot[y] += 1
        if not (conf_of(r['college']) or k(r['college']) in fbs) and k(r['college']) in fcs: cnt[y] += 1; rd[int(r['round'])] += 1
    return dict(perDraft={y: cnt[y] for y in sorted(cnt)}, mean2015_25=round(sum(cnt.values()) / 11, 1), mean2021_25=round(sum(cnt[y] for y in range(2021, 2026)) / 5, 1),
                share2021_25=round(sum(cnt[y] for y in range(2021, 2026)) / sum(tot[y] for y in range(2021, 2026)), 3), byRound=dict(sorted(rd.items())))
def kicker_need():
    """2010-25: did a team draft a kicker (punter) when its kicker was 35+ or made under 80% of 15+ field goals the
    season before (its punter 34+)? nflverse rosters and player stats."""
    drafted = collections.defaultdict(set)
    for r in dp:
        if r['position'] in ('K', 'P'): drafted[(int(r['season']), tf(r['team']))].add(r['position'])
    res = collections.defaultdict(lambda: [0, 0])
    for Y in range(2010, 2026):
        S = Y - 1; get(f'roster_{S}.csv', NV + f'rosters/roster_{S}.csv'); get(f'ps_{S}.csv', NV + f'stats_player/stats_player_reg_{S}.csv')
        age = {}; pun = collections.defaultdict(list)
        for r in csv.DictReader(open(f'roster_{S}.csv')):
            bd = r['birth_date'] or ''; a = S - int(bd[:4]) if bd[:4].isdigit() else None; age[r['gsis_id']] = a
            if r['position'] == 'P' and r['status'] in ('ACT', 'RES', 'INA') and a: pun[tf(r['team'])].append(a)
        ks = {}
        for r in csv.DictReader(open(f'ps_{S}.csv')):
            if r['position'] == 'K' and float(r['fg_att'] or 0) >= 1:
                t = tf(r['recent_team']); att = int(float(r['fg_att']))
                if t not in ks or att > ks[t][0]: ks[t] = (att, float(r['fg_made'] or 0) / att, age.get(r['player_id']))
        for t in {tf(r['team']) for r in dp if int(r['season']) == Y}:
            att, pct, a = ks.get(t, (0, 0, None))
            flag = (a is not None and a >= 35) or (att >= 15 and pct < 0.8)
            k = 'K flagged' if flag else 'K fine'; res[k][0] += 1; res[k][1] += 'K' in drafted[(Y, t)]
            k = 'P 34+' if pun.get(t) and max(pun[t]) >= 34 else 'P younger'; res[k][0] += 1; res[k][1] += 'P' in drafted[(Y, t)]
    out = {k: dict(n=n, drafted=d, rate=round(d / n, 3)) for k, (n, d) in sorted(res.items())}
    a, b = res['K flagged'], res['K fine']; p1, p2 = a[1] / a[0], b[1] / b[0]
    out['K z'] = round((p1 - p2) / math.sqrt(p1 * (1 - p1) / a[0] + p2 * (1 - p2) / b[0]), 2); out['K ln ratio'] = round(math.log(p1 / p2), 2)
    return out
def persistence():
    """raw persistence of a team's draft style: correlation across team-drafts (2012-25) between a class's mean and the
    franchise's last five drafts' (or the head coach's drafts anywhere, 12 years back) mean, and for position shares"""
    H = HIST; out = {}
    for a, f in (('size', lambda h: h['szz']), ('speed', lambda h: h['fz']), ('small school', lambda h: float(h['lvl'] != 'P5')), ('underclassman', lambda h: float(h['young']))):
        for how in ('team', 'coach'):
            xs, ys = [], []
            for Y in range(2012, 2026):
                for t in {h['t'] for h in H if h['y'] == Y}:
                    cur = [f(h) for h in H if h['y'] == Y and h['t'] == t and f(h) is not None]
                    if how == 'team': past = [f(h) for h in H if Y - 5 <= h['y'] < Y and h['t'] == t and f(h) is not None]
                    else:
                        hc = COACH.get((Y, t)); past = [f(h) for h in H if Y - 12 <= h['y'] < Y and h['coach'] == hc and f(h) is not None] if hc else []
                    if len(cur) >= 3 and len(past) >= 8: xs.append(np.mean(past)); ys.append(np.mean(cur))
            out[f'{a} ({how})'] = round(float(np.corrcoef(xs, ys)[0, 1]), 3)
    xs, ys = [], []
    for Y in range(2012, 2026):
        lg = collections.Counter(h['g'] for h in H if Y - 5 <= h['y'] < Y); n = sum(lg.values())
        for t in {h['t'] for h in H if h['y'] == Y}:
            cur = collections.Counter(h['g'] for h in H if h['y'] == Y and h['t'] == t); nc = sum(cur.values())
            past = collections.Counter(h['g'] for h in H if Y - 5 <= h['y'] < Y and h['t'] == t); npst = sum(past.values())
            for g in lg: xs.append(past[g] / npst - lg[g] / n); ys.append(cur[g] / nc - lg[g] / n)
    out['position share (team)'] = round(float(np.corrcoef(xs, ys)[0, 1]), 3)
    return out

if __name__ == '__main__':
    R = {}
    def show(name, byY, ref=None, key='team7'):
        s = summary(byY); R[name] = dict(s, perDraft={Y: {k: round(byY[Y][k], 4) for k in ('team7', 'team3', 'exact', 'cnt7', 'mae100')} for Y in byY})
        if ref: R[name]['wins'] = {k: sum((byY[Y][k] > ref[Y][k]) == k.startswith(('team', 'exact')) and byY[Y][k] != ref[Y][k] for Y in byY) for k in ('team7', 'team3', 'exact', 'cnt7', 'mae100')}
        print(f"{name:58s} " + ' '.join(f"{k} {v:.4g}" for k, v in s.items() if not k.startswith('a_')) + (f"  wins {R[name]['wins']}" if ref else ''), flush=True)
        return byY
    live = show('mock before (no K/P, run caps rounds 1-3, QB need only)', evaluate(dict(spec='excl', needs='qb')))
    sp = show('+ kickers and punters at historical slots', evaluate(dict(spec='order', needs='qb')), live)
    R['specialists per draft [K, P, LS] replay vs real'] = {Y: [sp[Y]['spec'], sp[Y]['specReal']] for Y in YEARS}
    B = dict(spec='order', needs='qb')
    run7 = show('+ run caps from each round\'s own counts (rounds 4-7 too)', evaluate(dict(B, runrounds=7)), sp)
    for w in (0.25, 0.4): show(f'  run weight {w} (live .15)', evaluate(dict(B, runrounds=7, runw=w)), run7)
    B = dict(B, runrounds=7)
    NY = [2020, 2021, 2022]   # contracts (OverTheCap via nflverse) stop in mid-2022: needs can be rebuilt for these drafts only
    sub = lambda b: {Y: b[Y] for Y in NY}
    q = show('needs 2020-22: QB only', sub(evaluate(B)))
    a = show('needs 2020-22: every room, live model (mean of starters)', sub(evaluate(dict(B, needs='all'))), q)
    for p in (2, 4, 'max'):
        show(f'needs 2020-22: weakest starter weighs more (power mean {p})', sub(evaluate(dict(B, needs='all', needp=p))), a)
        show(f'needs 2020-22: power mean {p}, a pick fills the weakest slot', sub(evaluate(dict(B, needs='all', needp=p, fill='slot'))), a)
    for w in (0.2, 0.7):
        show(f'needs 2020-22: every room, weight {w} (live .45)', sub(evaluate(dict(B, needs='all', needw=w))), a)
    pv = {g: (TOP_PAY[g] / np.mean([TOP_PAY[x] for x in NK if x not in SPEC])) ** 0.5 for g in NK}
    show('needs 2020-22: weighted by position value (sqrt of top pay)', sub(evaluate(dict(B, needs='all', wpos=pv))), a)
    b0 = evaluate(B)
    for f, ws in (('g', (-0.25, 0.25)), ('lvl', (0.05, 0.25, 0.5)), ('young', (0.05, 0.25, 0.5)), ('szz', (0.05, 0.25, 0.5)), ('fz', (0.05, 0.25, 0.5))):
        for how in ('team', 'coach'):
            out, ch = lodo(B, [dict(tend={f: w}, how=how) for w in ws], 'team7' if f == 'g' else 'exact')
            show(f'tendency {f} ({how}), weight picked on the other drafts', out, b0)
    R['persistence'] = persistence(); print(R['persistence'])
    R['trades'] = trade_history(); print(json.dumps(R['trades']))
    R['fcs'] = fcs_history(); print(R['fcs'])
    R['kickerNeed'] = kicker_need(); print(R['kickerNeed'])
    R['specialistSlots'] = {pos: spec_slots(None, pos)[:2] for pos in SPEC}
    # the mock's per-round position counts (cfb_draft_priors.json perRound, rounds 1-7), 2015-25
    pr = per_round(None)
    pri_path = os.path.join(ROOT, 'data', 'cfb_draft_priors.json'); pri = json.load(open(pri_path))
    pri['perRound'] = {g: [round(pr[(g, rd)], 2) for rd in range(1, 8)] for g in G if g != 'LS'}
    pri['_readme'] = ('Mock-draft priors: perRound = mean picks per position in each round of the 2015-25 drafts (nflverse draft_picks, '
                      'scripts/draft_replay7.py; the run penalty caps each round at 1.25x); value = FV bonus by round (teams pay up for QB, EDGE, OT, WR, CB early).')
    json.dump(pri, open(pri_path, 'w'), indent=1)
    json.dump({'_readme': __doc__.strip(), **R}, open(os.path.join(ROOT, 'data', 'cfb_draft_replay7.json'), 'w'), indent=1)
