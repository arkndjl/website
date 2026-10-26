#!/usr/bin/env python3
"""Hockey prospects ARKBOARD (Noah, Oct 24 2026): every 2027 draft prospect and every drafted player still short of
the NHL, graded on the 20-80 FV scale against what past picks became in the NHL.

    python3 scripts/hockey_data.py            # draft classes 2008-26 (picks, NHL ids, season lines, Central Scouting)
    python3 scripts/hockey_prospects.py --fit # outcome scale, driver selection, stage models -> data/hockey_fit.json
    python3 scripts/hockey_prospects.py       # grades -> data/hockey.json (board, pipeline, past classes)

Outcome   Peak NHL value: the mean of a player's best three seasons of descriptive WAR (static/data/nhl-war/,
          scripts/nhl_players.py; since Oct 25 2026, was the projected value, which underrated defencemen: D coefficient
          -0.55 -> +0.28) in his first seven seasons after the draft, missing seasons counted as 0. Goalies are ranked
          among goalies on peak goals saved above expected and given the skater value at the same rarity, so a goalie
          and a skater with the same FV were as rare among picks.
FV scale  By rarity among picks, classes 2008-19 (about 212 picks a class): 80 = one in four classes (McDavid), 75 =
          one in two, 70 = the best of a class, 65 = top 2, 60 = top 5 (first line, top pair, starting goalie), 55 = top
          10, 50 = top 20 (NHL regular), 45 = top 30, 40 = top 45; below that 20 (no NHL games) to 40 by games played.
          Values between cuts are interpolated. Grades in steps of 1.
Draft     FV = OLS on outcome FV, so the headline is the MEAN outcome (Noah, Oct 21). Base: log draft slot (and its
model     square), defense and goalie flags. Candidates (draft-year line: NHLe a full season from the league's
          translation factor, fit since Oct 25 2026 on the careers of every pick (scripts/hockey_nhle.py), goals share; age at the draft; height, weight; league group; Central Scouting rank; the
          season before): added forward while they cut leave-one-class-out error with t >= 2 over the 12 classes and win
          8 of 12.
Stages    Drafted players after k seasons (k = 1-4): OLS on the draft model's out-of-class grade, the latest season's
          NHLe (NHL and AHL lines translated too), age, NHL games and WAR so far, a World Juniors spot that season,
          pro games that season, NHLe growth since the draft year, AHL shots per game over the league's (HockeyTech's
          public AHL feed, 2008-09 on); inputs kept on the same rule (the last four also had to pass top-of-board and
          forward checks, scripts/hockey_fv_drivers.py).
Live      2027 class from Tankathon's NHL big board (rank, league, size, birth month, this season's line). Rank stands in
          for the slot: ln slot = m + b (ln rank - m), m the board's mean log rank, b = .81 from Central Scouting's
          January ranks against the June slot (an in-season board regresses toward the middle by the draft). This
          season's NHLe is shrunk to the slot's typical NHLe with NHLE_K games.
Prov      Draft-eligibles in the CHL, AHL and Liiga feeds who are not on Tankathon's board get a provisional grade
          (scripts/hockey_provisional.py, prov = 1) and join the board in FV order; the table shows those graded PROV_SHOW+.
Display   Pipeline players whose latest line is in Liiga or the SHL carry that season's ice time and shots on goal a game
          (etoi, esog; liiga.fi and shl.se, frozen by hockey_data.py --euro; null otherwise). Not a model input: only
          ~45 gradable Euro-pro picks have TOI seasons, too few to fit (round 2 research, Oct 24 2026).
Files     --fit freezes the pulled classes in scripts/data/hockey_rows.json.gz so the daily build (nhl.yml) needs no
          cache; after each June draft rerun hockey_data.py for the new class, then --fit.
"""
import datetime as dt
import gzip
import json
import math
import os
import re
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM
import nhl_data as D

CACHE = os.path.join(HERE, '.cache', 'hockey')
WARD = os.path.join(ROOT, 'static', 'data', 'nhl-war')
FIT = os.path.join(ROOT, 'data', 'hockey_fit.json')
ROWS = os.path.join(HERE, 'data', 'hockey_rows.json.gz')        # the pulled classes, frozen by --fit for the daily build
AHL = os.path.join(HERE, 'data', 'hockey_ahl.json.gz')          # AHL skater shots by season (scripts/hockey_data.py --ahl)
EURO = os.path.join(HERE, 'data', 'hockey_euro.json.gz')        # Liiga/SHL TOI and SOG by season (hockey_data.py --euro)
OUT = os.path.join(ROOT, 'data', 'hockey.json')
TANK = 'https://tankathon.com/nhl/big-board'
FIRST, LAST_FIT, WINDOW = 2008, 2019, 7
NHLE_K = 20
GOALIE_GP = 50          # NHL games in the window before a goalie's GSAx sets his outcome (FV audit, Oct 26 2026)
PROV_SHOW = 22          # provisional rows on the board table: graded above the floor
CUTS = [(80, 0.25), (75, 0.5), (70, 1), (65, 2), (60, 5), (55, 10), (50, 20), (45, 30), (40, 45)]   # FV, picks a class

# NHLe hand constants: NHL points a point in each league (public translation factors; Tankathon's for the CHL and NCAA).
# Since Oct 25 2026 the factors come from data/hockey_nhle.json (scripts/hockey_nhle.py: fit on the careers of every pick
# since 2008, league pairs in the same or the next season, age-adjusted); these stay as the fit's prior, its fallback for a
# league it has no movers for, and the pro / junior cut (PRO_CUT), which is a league tier, not a scoring rate.
HAND = {'NHL': 1.0, 'KHL': .772, 'Rus-KHL': .772, 'Russia': .772, 'SHL': .566, 'Sweden': .566, 'Liiga': .441, 'Finland': .441,
        'SM-liiga': .441, 'NL': .459, 'Swiss': .459, 'Czechia': .469, 'CzRep': .469, 'Czech': .469, 'DEL': .384,
        'Germany': .384, 'AHL': .389, 'VHL': .40, 'Russia2': .40, 'HockeyAllsvenskan': .29, 'Sweden-2': .29,
        'Allsvenskan': .29, 'Slovakia': .27, 'Czechia2': .23, 'CzRep-2': .23, 'Mestis': .21, 'Finland-2': .21,
        'Austria': .3, 'ICEHL': .3, 'EBEL': .3, 'Norway': .17, 'Denmark': .17, 'ECHL': .15,
        'OHL': .323, 'WHL': .302, 'QMJHL': .284, 'NCAA': .333, 'WCHA': .333, 'CCHA': .333, 'H-East': .333, 'ECAC': .333,
        'NCHC': .333, 'Big Ten': .333, 'BIG10': .333, 'Atlantic': .333, 'AHA': .333, 'Hockey East': .333,
        'USHL': .143, 'NTDP': .17, 'USDP': .17, 'USNTDP': .17, 'U.S. National U18 Team': .17, 'MHL': .145,
        'Russia-Jr.': .145, 'J20 Nationell': .19, 'J20 SuperElit': .19, 'Swe-Jr.': .19, 'U20 Nationell': .19,
        'U20 SM-sarja': .15, 'U20 SM-liiga': .15, 'Fin-Jr.': .15, 'Czechia U20': .12, 'CzRep-Jr.': .12,
        'Swiss-Jr.': .12, 'Slovakia-Jr.': .1, 'BCHL': .10, 'NAHL': .10, 'AJHL': .09, 'OJHL': .08, 'CCHL': .08,
        'ON-Jr.A': .08, 'MJHL': .07, 'SJHL': .07, 'CJHL': .08, 'QJHL': .07, 'EJHL': .07, 'USPHL': .06,
        'HockeyEttan': .1, 'Swe-U18': .08, '18U AAA': .04}
TOURN = re.compile(r'^(U-?1[78]|U-?20|WJC|WJ18|WC|OG|Hlinka|IIHF|WHC|U17|U18|5 Nations|4 Nations|World|Int|Olympics)', re.I)
CHL, EPRO = {'OHL', 'WHL', 'QMJHL'}, {'KHL', 'Rus-KHL', 'Russia', 'SHL', 'Sweden', 'Liiga', 'Finland', 'SM-liiga', 'NL', 'Swiss',
                                         'Czechia', 'CzRep', 'Czech', 'DEL', 'Germany', 'VHL', 'Russia2', 'HockeyAllsvenskan',
                                         'Sweden-2', 'Allsvenskan', 'Slovakia', 'Czechia2', 'Mestis', 'Austria', 'ICEHL',
                                         'Norway', 'Denmark', 'AHL', 'NHL'}
NCAA = {'NCAA', 'WCHA', 'CCHA', 'H-East', 'ECAC', 'NCHC', 'Big Ten', 'BIG10', 'Atlantic', 'AHA', 'Hockey East'}
USJR = {'USHL', 'NTDP', 'USDP', 'USNTDP', 'NAHL', 'BCHL', 'AJHL', 'OJHL', 'CCHL', 'ON-Jr.A', 'MJHL', 'SJHL', 'CJHL', 'QJHL',
        'EJHL', 'USPHL', '18U AAA'}


def hand_of(lg):
    if lg in HAND:
        return HAND[lg]
    if lg and (lg.startswith('High') or lg.startswith('USHS')):
        return .05
    return .10


PRO_CUT = .38
NHLE_FILE = os.path.join(ROOT, 'data', 'hockey_nhle.json')
FITTED = json.load(open(NHLE_FILE))['factors'] if os.path.exists(NHLE_FILE) else {}


def nhle_of(lg):
    """the fitted translation factor; a league the fit has no movers for keeps its hand constant on the fitted scale"""
    if lg in FITTED:
        return FITTED[lg]
    return hand_of(lg) * FITTED.get('_unk', 1.0)


def is_pro(lg):
    return hand_of(lg) >= PRO_CUT


def group_of(lg):
    if lg in CHL: return 'chl'
    if lg in NCAA: return 'ncaa'
    if lg in EPRO: return 'epro'
    if lg in USJR or (lg or '').startswith(('High', 'USHS')): return 'usjr'
    return 'ejr'


def main_line(seasons, sid, goalie=False):
    """the season line that best describes a player's season: most games among regular-season club lines"""
    ls = [s for s in seasons if s['season'] == sid and s.get('gameTypeId') == 2 and (s.get('gamesPlayed') or 0) > 0
          and not TOURN.match(s.get('leagueAbbrev') or '')]
    if not ls:
        return None
    # a pro line with real games beats a junior line (a top prospect who split time)
    ls.sort(key=lambda s: -((s['gamesPlayed'] or 0) * (1.5 if is_pro(s['leagueAbbrev']) else 1)))
    return ls[0]


def line_feats(s):
    if not s:
        return None
    gp = s.get('gamesPlayed') or 0
    if gp < 5:
        return None
    f = nhle_of(s['leagueAbbrev'])
    pts = s.get('points') or 0
    return {'lg': s['leagueAbbrev'], 'gp': gp, 'ppg': pts / gp, 'nhle': 82 * f * pts / gp, 'gsh': (s.get('goals') or 0) / max(pts, 1),
            'grp': group_of(s['leagueAbbrev'])}


def post_extra(seasons, sid):
    """a post-draft season beyond the main line: pro games across every club line, and a World Juniors (U20) roster spot"""
    reg = [s for s in seasons if s['season'] == sid and s.get('gameTypeId') == 2 and not TOURN.match(s.get('leagueAbbrev') or '')]
    return {'progp': sum(s.get('gamesPlayed') or 0 for s in reg if is_pro(s['leagueAbbrev'])),
            'wjc': int(any((s.get('leagueAbbrev') or '').startswith('WJC') and s['season'] == sid for s in seasons))}


def ahl_shots(rows):
    """px[k]['ahls']: AHL shots on goal per game that season over the league's (forwards or defence, 20+ GP), None when he
    played fewer than 20 AHL games or the season has no shots in the feed. Joined by birth date + the shared name matcher."""
    A = json.load(gzip.open(AHL, 'rt')) if os.path.exists(AHL) else {}
    by = {}
    for y, t in A.items():
        for p in t['p']:
            if p[1]:
                by.setdefault((int(y), p[1]), []).append(p)
    for r in rows:
        for k, x in (r.get('px') or {}).items():
            t = A.get(str(r['year'] + int(k)))
            c = [p for p in by.get((r['year'] + int(k), r.get('birth')), []) if NM.same(p[0], r['name'])] if t and not r['G'] else []
            x['ahls'] = round(c[0][3] / c[0][2] - t['norm']['D' if r['D'] else 'F'], 4) if len(c) == 1 else None
    return rows


_EURO = {}


def euro_line(r, season, lg):
    """(TOI minutes a game, shots on goal a game) in Liiga or the SHL that season, or (None, None). Liiga joins on birth date +
    the shared name matcher; the SHL feed has no birth dates, so a unique name match at his position."""
    if not _EURO and os.path.exists(EURO):
        _EURO.update(json.load(gzip.open(EURO, 'rt')))
    key = {'Liiga': 'liiga', 'SHL': 'shl'}.get(lg)
    t = (_EURO.get(str(season)) or {}).get(key) if key else None
    if not t or r['G']:
        return None, None
    pos = 'D' if r['D'] else 'F'
    c = [p for p in t if (p[1] == r.get('birth') if key == 'liiga' else p[2] == pos) and NM.same(p[0], r['name'])]
    if len(c) != 1 or not c[0][4]:
        return None, None
    nm, b, ps, gp, gpt, toi, sog = c[0]
    return round(toi / gpt / 60, 1), round(sog / gp, 2)


def war_tables():
    W = {}
    for fn in os.listdir(WARD):
        if fn[:4].isdigit():
            W[int(fn[:4])] = {p['id']: p for p in json.load(open(os.path.join(WARD, fn)))['players']}
    return W


def landing(pid):
    fn = os.path.join(CACHE, 'landing', f'{pid}.json')
    return json.load(open(fn)) if pid and os.path.exists(fn) else None


def age_at(birth, year):
    try:
        b = dt.date.fromisoformat(birth)
    except (TypeError, ValueError):
        return None
    return (dt.date(year, 9, 15) - b).days / 365.25


def load_rows(W):
    """one row per pick, 2008-26: draft-time features, post-draft lines, NHL outcome"""
    rows = []
    cur = D.current_season()
    for y in range(FIRST, 2027):
        fn = os.path.join(CACHE, f'class_{y}.json')
        if not os.path.exists(fn):
            continue
        d = json.load(open(fn))
        for p in d['picks']:
            L = landing(p.get('id'))
            seasons = (L or {}).get('seasons') or []
            g = p['pos'] == 'G'
            r = {'year': y, 'name': p['name'], 'id': p.get('id'), 'pick': p['pick'], 'team': p['team'], 'pos': p['pos'],
                 'G': int(g), 'D': int(p['pos'] == 'D'), 'ht': p.get('ht'), 'wt': p.get('wt'), 'birth': p.get('birth'),
                 'age': age_at(p.get('birth'), y), 'league': p.get('league'), 'club': p.get('club'), 'country': p.get('country'),
                 'css': p.get('css')}
            r['d0'] = line_feats(main_line(seasons, (y - 1) * 10000 + y))
            r['dm1'] = line_feats(main_line(seasons, (y - 2) * 10000 + y - 1))
            r['post'], r['px'] = {}, {}
            for k in range(1, 5):
                S = y + k
                if S >= cur:
                    break
                r['post'][k] = line_feats(main_line(seasons, (S - 1) * 10000 + S))
                r['px'][k] = post_extra(seasons, (S - 1) * 10000 + S)
            outcome(r, W, cur)
            rows.append(r)
    return ahl_shots(rows)


def outcome(r, W, cur):
    """NHL outcome: WAR seasons in the window (and what is in so far)"""
    wins, gps, gsx = [], 0, []
    for S in range(r['year'] + 1, r['year'] + 1 + WINDOW):
        q = W.get(S, {}).get(r.get('id'))
        if q:
            wins.append(q.get('war') or 0.0); gps += q.get('gp') or 0
            gsx.append(q.get('gsax') or 0.0)
    r['nhl_war'] = wins; r['nhl_gp'] = gps
    r['peak'] = sum((sorted(wins, reverse=True) + [0, 0, 0])[:3]) / 3
    r['gpeak'] = sum((sorted(gsx, reverse=True) + [0, 0, 0])[:3]) / 3
    r['mature'] = r['year'] + WINDOW < cur


def outcome_scale(rows):
    """FV cuts on peak WAR by rarity among 2008-19 picks; goalies mapped by rarity among goalies"""
    fit = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    ncls = LAST_FIT - FIRST + 1
    sk = sorted((r['peak'] for r in fit if not r['G']), reverse=True)
    share = len(sk) / len(fit)
    cuts = []
    for fv, per in CUTS:
        k = max(1, int(round(per * ncls * share)))
        cuts.append((fv, sk[k - 1]))
    gk = sorted((r['gpeak'] for r in fit if r['G']), reverse=True)
    return {'cuts': cuts, 'goalie': gk, 'skater': sk, 'classes': ncls}


def fv_of(r, sc):
    """outcome FV of a finished (or in-progress) career"""
    peak = r['peak']
    if r['G']:
        gk, sk = sc['goalie'], sc['skater']
        # a goalie's GSAx ranks him only once he has a real sample (GOALIE_GP): before the gate, any positive best
        # season out-ranked the ~55% of drafted goalies with no games, so 2-5 NHL games graded 45-48 (Wedgewood,
        # Dansk); under it he takes the games path like a skater
        if r['nhl_gp'] < GOALIE_GP:
            peak = 0.0
        else:
            q = sum(1 for v in gk if v > r['gpeak']) / max(len(gk), 1)        # share of goalies above him
            peak = sk[min(int(q * len(sk)), len(sk) - 1)]
    cuts = sc['cuts']
    if peak >= cuts[0][1]:
        return 80.0
    for (f1, v1), (f0, v0) in zip(cuts, cuts[1:]):
        if peak >= v0:
            return f0 + (f1 - f0) * (peak - v0) / max(v1 - v0, 1e-9)
    if r['nhl_gp'] == 0:
        return 20.0
    lo = cuts[-1][1]
    return min(40.0, 30.0 + 10.0 * min(r['nhl_gp'], 200) / 200 * (1 if peak > 0 else 0.6))


# -- features ---------------------------------------------------------------------------------------------------
def feats(r, sl=None):
    """draft-time features (sl overrides ln slot for the live board)"""
    d0, dm = r.get('d0'), r.get('dm1')
    ls = math.log(r['pick']) if sl is None else sl
    g = r['G']
    nh = (d0 or {}).get('nhle')
    ht = r.get('ht') or (73.5 if g else 72.5)
    wt = r.get('wt') or 190
    age = r.get('age') if r.get('age') is not None else 18.5
    css = r.get('css') or {}
    lc = math.log(css['final']) if css.get('final') else math.log(250)
    f = {'ls': ls, 'ls2': ls * ls, 'D': r['D'], 'G': g,
         'nhle': 0.0 if g or nh is None else nh / 10, 'nhle_na': int(not g and nh is None),
         'nhleD': 0.0 if g or nh is None else r['D'] * nh / 10,
         'gsh': 0.0 if g or not d0 else d0['gsh'] - 0.4,
         'age': age - 18.5, 'agenh': (age - 18.5) * (0.0 if g or nh is None else nh / 10),
         'ht': ht - 72.5, 'wt': (wt - 190) / 10,
         'chl': int((d0 or {}).get('grp') == 'chl'), 'ncaa': int((d0 or {}).get('grp') == 'ncaa'),
         'epro': int((d0 or {}).get('grp') == 'epro'), 'usjr': int((d0 or {}).get('grp') == 'usjr'),
         'css': lc - ls, 'cssint': int(css.get('reg') == 'INT'),
         'grow': 0.0 if g or nh is None or not dm or dm.get('nhle') is None else (nh - dm['nhle']) / 10, 'cs': 0.0}
    return f


# Class strength (Noah, Oct 26 2026: FV grades absolute talent, so it can't depend on the class a player is drafted in).
# The slot is a rank within one class, so on slot alone every class's 5th pick grades the same. cs puts the level back:
# the class's top CS_K picks graded on the draft-time inputs that mean the same in any class (NHLe, age, size, league,
# position; the ABS fit, no slot), their mean against the 2008-19 average, applied to top picks and fading out by
# pick 2 x CS_K. Leave-one-class-out MSE 90.37 -> 90.19 (8/12 classes, t 1.6; the S fit redone inside each fold gives
# the same), top 32 MSE 103.8 -> 102.9, forward (fit 2008-15, grade 2016-19) 83.68 -> 83.44. The current grade's
# top-32 class means spread 42.9-44.8 against realized 42.1-49.2 (r with cs .53); kept as a forced term, not by the
# driver gate, because it is the rule the scale is built on and it is no worse out of sample.
CS_K = 32
ABS = ['nhle', 'nhle_na', 'D', 'G', 'age', 'agenh', 'ht', 'wt', 'chl', 'ncaa', 'epro']


def cs_weight(ls):
    return max(0.0, 1 - ls / math.log(2 * CS_K))


def abs_pred(b, f):
    return b[0] + sum(w * f[c] for w, c in zip(b[1:], ABS))


def class_strength(F, cls, b):
    """{class: mean ABS grade of its top CS_K picks} (F carries ls = ln slot, or the board's expected ln slot)"""
    out = {}
    for c in sorted(set(cls)):
        v = [abs_pred(b, f) for f, k in zip(F, cls) if k == c and f['ls'] <= math.log(CS_K) + 1e-9]
        if v: out[c] = float(np.mean(v))
    return out


def set_cs(F, cls, S, mean):
    for f, c in zip(F, cls):
        f['cs'] = (S[c] - mean) * cs_weight(f['ls']) if c in S else 0.0


BASE = ['ls', 'ls2', 'D', 'G']
CANDS = ['nhle', 'nhle_na', 'nhleD', 'gsh', 'age', 'agenh', 'ht', 'wt', 'chl', 'ncaa', 'epro', 'usjr', 'css', 'cssint', 'grow']


def ols(X, y, lam=1.0):
    X1 = np.column_stack([np.ones(len(X)), X])
    P = lam * np.eye(X1.shape[1]); P[0, 0] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)


def pred(b, X):
    return b[0] + np.asarray(X) @ b[1:]


def loco(F, y, cls, cols):
    """leave-one-class-out predictions"""
    X = np.array([[f[c] for c in cols] for f in F])
    out = np.zeros(len(y))
    for c in sorted(set(cls)):
        m = cls == c
        b = ols(X[~m], y[~m])
        out[m] = pred(b, X[m])
    return out


def score(F, y, cls, cols):
    p = np.clip(loco(F, y, cls, cols), 20, 80)
    return np.array([np.mean((p[cls == c] - y[cls == c]) ** 2) for c in sorted(set(cls))]), p


def select(F, y, cls, base, cands, log=None):
    kept = list(base)
    cur, _ = score(F, y, cls, kept)
    ev = {}
    while True:
        best = None
        for c in cands:
            if c in kept:
                continue
            s, _ = score(F, y, cls, kept + [c])
            d = cur - s                                   # per-class MSE gain
            t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if d.std() > 0 else 0
            ev[c] = {'gain': round(float(d.mean()), 3), 't': round(float(t), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
            if t >= 2 and (d > 0).sum() >= math.ceil(len(d) * 2 / 3) and (best is None or d.mean() > best[1]):
                best = (c, d.mean(), s)
        if best is None:
            break
        kept.append(best[0]); cur = best[2]
        if log: log(f'  + {best[0]}  mse {cur.mean():.2f}  {ev[best[0]]}')
    return kept, ev, cur


def stage_feats(r, k, fv0):
    q = r['post'].get(k)
    nh = (q or {}).get('nhle')
    war = sum(r.get('war_k', {}).get(k, [])) if r.get('war_k') else 0.0
    x = (r.get('px') or {}).get(k) or {}
    nh0 = (r.get('d0') or {}).get('nhle')
    pro = int(bool(q) and is_pro(q['lg']))
    return {'wjc': x.get('wjc', 0) * (1 - r['G']), 'progp': min(x.get('progp', 0), 70) / 70,
            'ahls': 0.0 if r['G'] or x.get('ahls') is None else x['ahls'],
            'nhgrow': 0.0 if r['G'] or nh is None or nh0 is None or pro else (nh - nh0) / 10,
            'fv0': fv0, 'nh': 0.0 if r['G'] or nh is None else nh / 10, 'nh_na': int(not r['G'] and nh is None),
            'nhD': 0.0 if r['G'] or nh is None else r['D'] * nh / 10,
            'pro': int(bool(q) and is_pro(q['lg'])), 'age': (r['age'] or 18.5) - 18.5,
            'gp': min(r['gp_k'].get(k, 0), 164) / 82, 'war': war, 'G': r['G'], 'D': r['D']}


SBASE = ['fv0']
SCANDS = ['nh', 'nh_na', 'nhD', 'pro', 'age', 'gp', 'war', 'G', 'D']
# Oct 24 2026 (scripts/hockey_fv_drivers.py): a World Juniors spot after the draft, pro games played, and NHLe growth
# since the draft year pass the class-out rule at every stage they are offered to below, and also cut error on the first
# 64 picks and on classes 2016-19 graded from a 2008-15 fit. Where a stage is not offered one, it failed those checks.
SNEW = {1: ['wjc'], 2: ['wjc', 'progp', 'nhgrow'], 3: ['progp'], 4: []}
# Oct 24 2026 (AHL shots, HockeyTech feed): AHL shots per game over the league's, offered after the stage's other inputs
# are chosen (as it was tested: on top of them). Passes at k2 only; at k3-4 it cuts class-out error (t 3.9, 8.1) but
# lowers forward top-64 Spearman (-.004, -.009), so it is not offered there.
SLATE = {1: [], 2: ['ahls'], 3: [], 4: []}


def nhl_so_far(rows, W):
    for r in rows:
        r['gp_k'], r['war_k'] = {}, {}
        gp, wl = 0, []
        for k in range(1, 6):
            q = W.get(r['year'] + k, {}).get(r['id']) if r['id'] else None
            if q:
                gp += q.get('gp') or 0; wl.append(q.get('war') or 0.0)
            r['gp_k'][k] = gp; r['war_k'][k] = list(wl)


def save_rows(rows):
    keep = [{k: v for k, v in r.items() if k not in ('gp_k', 'war_k')} for r in rows]
    with gzip.open(ROWS, 'wt') as f:
        json.dump(keep, f, separators=(',', ':'))


def renhle(q):
    """a frozen line's NHLe on the current factors"""
    if q and q.get('ppg') is not None:
        q['nhle'] = 82 * nhle_of(q['lg']) * q['ppg']
    return q


def read_rows(W):
    """the frozen classes with this season's NHL record laid over them"""
    rows = json.load(gzip.open(ROWS, 'rt'))
    for r in rows:
        r['post'] = {int(k): renhle(v) for k, v in r['post'].items()}
        renhle(r.get('d0')); renhle(r.get('dm1'))
        r['px'] = {int(k): v for k, v in (r.get('px') or {}).items()}
        outcome(r, W, D.current_season())
    return ahl_shots(rows)


def fit(frozen=False, scorecard=False):
    """frozen: refit on scripts/data/hockey_rows.json.gz instead of the pulled cache; scorecard: write only the
    held-out FV scorecard (scripts/fv_scorecard.py) into data/hockey_fit.json and leave the fit as it is"""
    W = war_tables()
    rows = read_rows(W) if frozen else load_rows(W)
    if not frozen and not scorecard:
        save_rows(rows)
    nhl_so_far(rows, W)
    sc = outcome_scale(rows)
    tr = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    y = np.array([fv_of(r, sc) for r in tr])
    cls = np.array([r['year'] for r in tr])
    F = [feats(r) for r in tr]
    print('picks', len(tr), 'outcome FV mean', round(y.mean(), 2), 'cuts', [(f, round(v, 2)) for f, v in sc['cuts']])
    base_s, base_p = score(F, y, cls, BASE)
    print('slot-only LOCO mse', round(base_s.mean(), 2))
    kept, ev, cur = select(F, y, cls, BASE, CANDS, log=print)
    # class strength (CS_K): the ABS fit on every pick, then each class's level against the 2008-19 average
    babs = ols(np.array([[f[c] for c in ABS] for f in F]), y)
    S = class_strength(F, cls, babs); Smean = float(np.mean(list(S.values())))
    set_cs(F, cls, S, Smean)
    s_cs, _ = score(F, y, cls, kept + ['cs'])
    d = cur - s_cs
    ev['cs'] = {'gain': round(float(d.mean()), 3), 't': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2), 'wins': int((d > 0).sum()), 'of': len(d)}
    print('  + cs (forced: class strength)', ev['cs'])
    kept = kept + ['cs']
    s_all, p0 = score(F, y, cls, kept)
    X = np.array([[f[c] for c in kept] for f in F]); b = ols(X, y)
    coef = dict(zip(['const'] + kept, [round(float(v), 4) for v in b]))
    print('kept', kept, 'mse', round(s_all.mean(), 2), 'vs slot', round(base_s.mean(), 2)); print(coef)
    # calibration of the out-of-class grades: bands of 5
    calib = []
    for lo in range(20, 80, 5):
        m = (p0 >= lo) & (p0 < lo + 5)
        if m.sum() >= 5:
            calib.append({'band': lo, 'n': int(m.sum()), 'pred': round(float(p0[m].mean()), 1), 'real': round(float(y[m].mean()), 1),
                          'nhl': round(float(np.mean([tr[i]['nhl_gp'] > 0 for i in np.where(m)[0]])), 3)})
    print(calib)
    if scorecard:
        from fv_scorecard import card
        sc_ = card(p0, y, cls=cls, note=f'{len(tr):,} draft picks {FIRST}-{LAST_FIT}, each graded by a fit that left his draft class out; '
                   'outcome: the FV his first NHL seasons earned on WAR; tier odds from a logistic on that grade, also class-out')
        print('scorecard', sc_['summary'])
        cur_fit = json.load(open(FIT)); cur_fit['scorecard'] = sc_
        json.dump(cur_fit, open(FIT, 'w'), indent=1)
        return
    # stage models: k seasons after the draft
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    stages = {}
    for k in range(1, 5):
        sub = [r for r in tr if r['year'] + k < D.current_season()]
        Fk = [stage_feats(r, k, oof[id(r)]) for r in sub]
        yk = np.array([fv_of(r, sc) for r in sub]); ck = np.array([r['year'] for r in sub])
        s0, _ = score(Fk, yk, ck, SBASE)
        kk, evk, curk = select(Fk, yk, ck, SBASE, SCANDS + SNEW[k])
        if SLATE[k]:
            kk, ev2, curk = select(Fk, yk, ck, kk, SLATE[k]); evk.update(ev2)
        Xk = np.array([[f[c] for c in kk] for f in Fk]); bk = ols(Xk, yk)
        stages[k] = {'kept': kk, 'coef': dict(zip(['const'] + kk, [round(float(v), 4) for v in bk])),
                     'mse': round(float(curk.mean()), 2), 'mseDraft': round(float(s0.mean()), 2), 'ev': evk}
        print('stage', k, kk, 'mse', stages[k]['mse'], 'vs draft grade', stages[k]['mseDraft'])
    # slot <- in-season rank: Central Scouting midterm (January) vs the June slot, NA skaters ranked both times
    xs, ys = [], []
    for y0 in range(FIRST, 2027):
        for r in rows:
            c = r.get('css') or {}
            if r['year'] == y0 and c.get('cat') == 1 and c.get('mid') and c.get('final'):
                xs.append(math.log(c['mid'])); ys.append(math.log(r['pick']))
    A = np.column_stack([np.ones(len(xs)), xs]); ab = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
    rs = np.array(ys) - A @ ab
    # the slot's typical draft-year NHLe (the shrink target for a short season)
    nn = [(math.log(r['pick']), r['d0']['nhle']) for r in tr if not r['G'] and r.get('d0') and r['d0'].get('nhle') is not None]
    nb = np.polyfit([a for a, _ in nn], [v for _, v in nn], 1)
    out = {'asof': dt.date.today().isoformat(), 'classes': [FIRST, LAST_FIT], 'window': WINDOW, 'picks': len(tr),
           'cuts': [[f, round(v, 3)] for f, v in sc['cuts']], 'goalie': [round(v, 2) for v in sc['goalie']],
           'skater': [round(v, 3) for v in sc['skater']],
           'kept': kept, 'coef': coef, 'ev': ev, 'mse': round(float(s_all.mean()), 2), 'mseSlot': round(float(base_s.mean()), 2),
           'calib': calib, 'stages': stages, 'rank2slot': {'a': round(float(ab[0]), 3), 'b': round(float(ab[1]), 3),
                                                         'sd': round(float(rs.std()), 3), 'n': len(xs)},
           'nhleSlot': [round(float(v), 3) for v in nb], 'nhleK': NHLE_K, 'odds': odds_fit(p0, y),
           'abs': {'cols': ABS, 'coef': [round(float(v), 5) for v in babs], 'k': CS_K, 'mean': round(Smean, 3),
                   'byClass': {str(c): round(v, 2) for c, v in S.items()}}}
    json.dump(out, open(FIT, 'w'), indent=1)
    print('rank2slot', out['rank2slot'], 'nhleSlot', out['nhleSlot'])


def tankathon():
    """the 2027 board: [{rk, name, pos, club, league, ht, wt, birth (year-month-15), gp, g, a, p}]"""
    req = urllib.request.Request(TANK, headers={'User-Agent': D.UA})
    try:
        html = urllib.request.urlopen(req, timeout=60).read().decode('utf8', 'replace')
    except Exception as e:
        print('tankathon:', e, file=sys.stderr)
        return None, None
    m = re.search(r'<h1 class="page-title">(\d{4}) NHL Draft', html)
    year = int(m.group(1)) if m else None
    mon = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
    out = []
    for chunk in html.split('<div class="mock-row nhl"')[1:]:
        def g(rx, d=None):
            x = re.search(rx, chunk)
            return x.group(1).strip() if x else d
        rk, nm = g(r'mock-row-pick-number">(\d+)'), g(r'mock-row-name">([^<]*)')
        if not rk or not nm:
            continue
        sp = g(r'mock-row-school-position">([^<]*)', '')
        pos, _, club = sp.partition('|')
        ht = g(r'class="height">([^<]*)')
        hti = None
        if ht:
            hm = re.match(r"(\d+)&#39;(\d+)", ht) or re.match(r"(\d+)'(\d+)", ht)
            hti = int(hm.group(1)) * 12 + int(hm.group(2)) if hm else None
        yr = re.findall(r'class="year">(\d{4})', chunk); mo = g(r'class="month">([A-Z]{3})')
        vals = dict(re.findall(r'<div class="label">([A-Za-z%]+)</div><div class="value total"[^>]*>([^<]*)', chunk))
        num = lambda k: float(vals[k]) if vals.get(k) not in (None, '', '-') else None
        out.append({'rk': int(rk), 'name': nm.replace('&#39;', "'"), 'pos': pos.strip().split('/')[0], 'posFull': pos.strip(),
                    'club': club.strip().replace('&amp;', '&'), 'league': (g(r'league-name">([^<]*)') or '').replace('\u2011', '-'),
                    'ht': hti, 'wt': int(g(r'class="weight">(\d+)')) if g(r'class="weight">(\d+)') else None,
                    'birth': f"{yr[0]}-{mon.get(mo, 6):02d}-15" if yr else None,
                    'gp': num('GAMES'), 'g': num('GOALS'), 'a': num('ASSISTS'), 'p': num('POINTS')})
    return year, out


TK_LEAGUE = {'Slovak': 'Slovakia', 'HA': 'HockeyAllsvenskan', 'Allsvenskan': 'HockeyAllsvenskan', 'Mestis': 'Mestis', 'NL': 'NL', 'DEL': 'DEL', 'U20 SM-sarja': 'U20 SM-sarja', 'Czechia': 'Czechia', 'Sweden J20': 'J20 Nationell', 'J20 Nationell': 'J20 Nationell',
             'USNTDP': 'NTDP', 'NTDP': 'NTDP', 'USHL': 'USHL', 'Liiga': 'Liiga', 'SHL': 'SHL', 'KHL': 'KHL', 'MHL': 'MHL', 'VHL': 'VHL'}


def grade(fitd, f):
    b = fitd['coef']
    v = b['const'] + sum(b[k] * f.get(k, 0.0) for k in fitd['kept'])
    return min(80.0, max(20.0, v))


def sgrade(st, f):
    b = st['coef']
    return min(80.0, max(20.0, b['const'] + sum(b[k] * f[k] for k in st['kept'])))


def odds(fitd, x):
    """P(40+ outcome: an NHL career) and P(50+: a regular) from the grade, logistic on the out-of-class grades"""
    o = fitd['odds']
    return [1 / (1 + math.exp(-(a + b * (x - 30)))) for a, b in (o['p40'], o['p50'])]


def odds_fit(p0, y, cuts=(('p40', 40), ('p50', 50))):
    out = {}
    for k, cut in cuts:
        t = (y >= cut).astype(float); x = p0 - 30
        a, b = 0.0, 0.1
        for _ in range(50):                                    # Newton steps, two parameters
            z = a + b * x; q = 1 / (1 + np.exp(-z)); w = q * (1 - q)
            g = np.array([np.sum(t - q), np.sum((t - q) * x)])
            H = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]]) + 1e-6 * np.eye(2)
            a, b = np.array([a, b]) + np.linalg.solve(H, g)
        out[k] = [round(float(a), 4), round(float(b), 4)]
    return out


# scouting-report dropdowns: inputs that move together show as one push on the grade
PART = {'ls': 'slot', 'ls2': 'slot', 'D': 'pos', 'G': 'pos', 'nhle': 'nhle', 'nhle_na': 'nhle', 'nhleD': 'nhle',
        'nh': 'nh', 'nh_na': 'nh', 'nhD': 'nh'}


def parts(coef, kept, f, mean):
    """each input's push on the grade against the average 2008-19 pick (stage models: the average pick that far out)"""
    out = {}
    for k in kept:
        g = PART.get(k, k)
        out[g] = out.get(g, 0.0) + coef[k] * (f[k] - mean[k])
    return [[g, round(v, 2)] for g, v in sorted(out.items(), key=lambda kv: -abs(kv[1])) if abs(v) >= .05]


def build():
    fitd = json.load(open(FIT))
    W = war_tables()
    rows = read_rows(W)
    nhl_so_far(rows, W)
    cur = D.current_season()
    sc = {'cuts': fitd['cuts'], 'goalie': fitd['goalie'], 'skater': fitd['skater']}
    # out-of-class grades of the 2008-19 picks: the 30 and 60 rungs of the outcome odds (40 and 50 are in the fit),
    # and the average pick each input's push is measured against
    tr = [r for r in rows if FIRST <= r['year'] <= LAST_FIT]
    Fp = [feats(r) for r in tr]
    y = np.array([fv_of(r, sc) for r in tr]); cls = np.array([r['year'] for r in tr])
    # class strength for every drafted class (2008 on), from the frozen picks' draft-time lines
    A = fitd.get('abs')
    Sall = class_strength([feats(r) for r in rows], [r['year'] for r in rows], A['coef']) if A else {}
    csOf = lambda f, c: (Sall[c] - A['mean']) * cs_weight(f['ls']) if A and c in Sall else 0.0
    for f, c in zip(Fp, cls): f['cs'] = csOf(f, c)
    _, p0 = score(Fp, y, cls, fitd['kept'])
    rung = {**fitd['odds'], **odds_fit(p0, y, (('p30', 30), ('p60', 60)))}
    sig = lambda k, x: 1 / (1 + math.exp(-(rung[k][0] + rung[k][1] * (x - 30))))
    mean0 = {k: float(np.mean([f[k] for f in Fp])) for k in fitd['kept']}
    oof = {id(r): float(p) for r, p in zip(tr, p0)}
    meank = {}
    for k, st in fitd['stages'].items():
        sub = [stage_feats(r, int(k), oof[id(r)]) for r in tr if r['year'] + int(k) < cur]
        meank[k] = {c: float(np.mean([f[c] for f in sub])) for c in st['kept']}
    r2s, ns = fitd['rank2slot'], fitd['nhleSlot']
    # 1. the coming draft class
    year, tk = tankathon()
    board = []
    seen = set(); tk = [t for t in tk or [] if not ((t['rk'], t['name']) in seen or seen.add((t['rk'], t['name'])))]
    # an overall board: the June slot regresses toward the board's middle at the in-season rate (b), centred on it
    mlr = sum(math.log(t['rk']) for t in tk) / max(len(tk), 1)
    live = []
    for t in tk:
        g = t['pos'] == 'G'
        ls = mlr + r2s['b'] * (math.log(t['rk']) - mlr)
        lg = TK_LEAGUE.get(t['league'], t['league'])
        f0 = nhle_of(lg)
        prior = ns[0] * ls + ns[1]
        gp = t['gp'] or 0
        nh = (82 * f0 * (t['p'] or 0) + NHLE_K * prior) / (gp + NHLE_K) if gp else prior
        nh_raw = 82 * f0 * t['p'] / gp if gp and t['p'] is not None else None
        r = {'pick': 1, 'G': int(g), 'D': int(t['pos'] in ('D', 'LD', 'RD')), 'ht': t['ht'], 'wt': t['wt'], 'age': age_at(t['birth'], year or cur),
             'd0': None if g else {'nhle': nh, 'gsh': (t['g'] or 0) / max(t['p'] or 0, 1) if gp else 0.4, 'grp': group_of(lg)}, 'css': None}
        f = feats(r, sl=ls)
        f['css'] = 0.0
        live.append((t, g, lg, gp, nh_raw, r, f, ls))
    # the class's strength from its top CS_K on the board (in-season NHLe already shrunk toward the slot's typical line)
    S_live = class_strength([f for *_, f, _ in live], [0] * len(live), A['coef']).get(0) if A else None
    for t, g, lg, gp, nh_raw, r, f, ls in live:
        if S_live is not None: f['cs'] = (S_live - A['mean']) * cs_weight(f['ls'])
        x = grade(fitd, f)
        p40, p50 = odds(fitd, x)
        board.append({'rk': t['rk'], 'name': t['name'], 'pos': 'D' if r['D'] else t['pos'], 'posFull': t['posFull'], 'club': t['club'],
                      'league': t['league'], 'grp': group_of(lg), 'ht': t['ht'], 'wt': t['wt'], 'age': round(r['age'], 1) if r['age'] else None,
                      'gp': int(gp), 'pts': int(t['p']) if t['p'] is not None else None, 'nhle': round(nh_raw, 1) if nh_raw is not None else None,
                      'xslot': round(math.exp(ls)), 'fvx': round(x, 2), 'fv': int(round(x)), 'p40': round(p40, 3), 'p50': round(p50, 3),
                      'p30': round(sig('p30', x), 3), 'p60': round(sig('p60', x), 3), 'parts': parts(fitd['coef'], fitd['kept'], f, mean0)})
    # provisional grades (Oct 25 2026): draft-eligibles in the CHL, AHL and Liiga feeds who are not on Tankathon's board,
    # graded up from the 20 floor (scripts/hockey_provisional.py) and ranked with the board; the table shows those above
    # the floor (22+), the rest are counted
    import hockey_provisional as HP
    prov = HP.live(year or cur, board, rows) if tk else []
    nprov = len(prov)
    board += [p for p in prov if p['fv'] >= PROV_SHOW]
    board.sort(key=lambda r: (-r['fvx'], r['rk'] or 999))
    # 2. drafted, not yet NHL regulars: the newest five classes
    pipe = []
    for r in rows:
        k = (cur - 1) - r['year']                      # completed seasons since the draft
        if k < 0 or k > 4 or r['year'] < cur - 6:
            continue
        gp_all = sum((W.get(S, {}).get(r['id']) or {}).get('gp') or 0 for S in range(r['year'] + 1, cur + 1)) if r['id'] else 0
        if gp_all >= (50 if r['G'] else 100):
            continue                                    # graduated: an NHL player now (NHL WAR board)
        f0 = feats(r)
        f0['cs'] = csOf(f0, r['year'])
        x0 = grade(fitd, f0)
        if k == 0:
            x, pp = x0, parts(fitd['coef'], fitd['kept'], f0, mean0)
        else:
            st, fk = fitd['stages'][str(k)], stage_feats(r, k, x0)
            x, pp = sgrade(st, fk), parts(st['coef'], st['kept'], fk, meank[str(k)])
        px = (r.get('px') or {}).get(k) or {}
        p40, p50 = odds(fitd, x)
        q = r['post'].get(k) if k else r['d0']
        tm = W.get(cur, {}).get(r['id'], {}).get('tm') if r['id'] else None
        etoi, esog = euro_line(r, r['year'] + k, (q or {}).get('lg'))
        pipe.append({'name': r['name'], 'id': r['id'], 'year': r['year'], 'pick': r['pick'], 'team': r['team'], 'pos': r['pos'],
                     'age': round(age_at(r['birth'], cur - 1), 1) if r['birth'] else None, 'k': k,
                     'league': (q or {}).get('lg'), 'gp': (q or {}).get('gp'),
                     'ahls': (r['px'].get(k) or {}).get('ahls') if k else None, 'etoi': etoi, 'esog': esog, 'nhle': round(q['nhle'], 1) if q and not r['G'] else None,
                     'nhlgp': gp_all, 'fv0': int(round(x0)), 'fvx': round(x, 2), 'fv': int(round(x)), 'p40': round(p40, 3), 'p50': round(p50, 3),
                     'p30': round(sig('p30', x), 3), 'p60': round(sig('p60', x), 3), 'parts': pp,
                     'nh0': round(r['d0']['nhle'], 1) if not r['G'] and (r.get('d0') or {}).get('nhle') is not None else None,
                     'wjc': int(bool(px.get('wjc'))) if k else 0, 'progp': px.get('progp') if k else None,
                     'war': round(sum(r.get('war_k', {}).get(k, [])), 2) if k and r.get('war_k') else None})
    pipe.sort(key=lambda r: -r['fvx'])
    pipe = [p for i, p in enumerate(pipe) if i < 300 or p['fv'] >= 35]
    # 3. past classes: the out-of-class draft grade and what each pick became
    past = []
    for r, pg, yo in zip(tr, p0, y):
        past.append({'name': r['name'], 'year': r['year'], 'pick': r['pick'], 'team': r['team'], 'pos': r['pos'],
                     'fv': int(round(pg)), 'out': int(round(yo)), 'gp': r['nhl_gp'], 'peak': round(r['peak'], 2) if not r['G'] else None,
                     'gpeak': round(r['gpeak'], 1) if r['G'] else None})
    past = [p for p in past if p['pick'] <= 64 or p['fv'] >= 35 or p['out'] >= 45]
    asof = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    pf = json.load(open(HP.FIT)) if os.path.exists(HP.FIT) else None
    out = {'asof': asof, 'year': year, 'season': cur, 'board': board, 'pipe': pipe, 'past': past,
           'prov': {'n': nprov, 'shown': sum(1 for b in board if b.get('prov')), 'min': PROV_SHOW,
                    'fit': {k: pf[k] for k in ('classes', 'boardN', 'n', 'drafted', 'nhl', 'meanFv', 'kept', 'coef', 'ev', 'mse', 'mseFlat',
                                               'mseLate', 'vsFlat', 'vsLate', 'picks', 'top5', 'calib')} if pf else None},
           'nhle': {k: v for k, v in json.load(open(NHLE_FILE)).items() if k in ('asof', 'lines', 'players', 'test')} if os.path.exists(NHLE_FILE) else None,
           'teams': sorted({p['team'] for p in pipe if p['team']}),
           'leagues': sorted({b['league'] for b in board if b['league']}),
           'fit': {k: fitd[k] for k in ('classes', 'window', 'picks', 'cuts', 'kept', 'coef', 'ev', 'mse', 'mseSlot', 'calib', 'rank2slot', 'odds')},
           'classStrength': {'k': CS_K, 'live': round(S_live - A['mean'], 2) if A and S_live is not None else None,
                             'byClass': {str(c): round(v - A['mean'], 2) for c, v in Sall.items()} if A else {}},
           'rungs': rung,
           'stages': {k: {kk: v[kk] for kk in ('kept', 'coef', 'mse', 'mseDraft')} for k, v in fitd['stages'].items()}}
    try:   # headshots from the CHL/USHL HockeyTech rosters (scripts/faces.py); the board builds without them
        import faces
        print('hockey faces:', faces.hockey_attach(board), 'of', len(board))
    except Exception as e:
        print('hockey faces skipped:', e)
    json.dump(out, open(OUT, 'w'), separators=(',', ':'))
    print('wrote', OUT, len(board), 'board', nprov, 'provisional', len(pipe), 'pipeline', len(past), 'past')


if __name__ == '__main__':
    if '--fit' in sys.argv:
        fit(frozen='--frozen' in sys.argv)
    elif '--scorecard' in sys.argv:
        fit(frozen=True, scorecard=True)
    else:
        build()
