#!/usr/bin/env python3
"""Picks for the all-sports games page (content/arkboard-games.md): every bet on the board (each side of the spread,
the moneyline, the over and the under) priced by a calibrated chance, ranked by expected return, sized by Kelly.

    python3 scripts/games_picks.py --fit           # data/games_picks_fit.json (numpy), from the walk-forward files
    python3 scripts/games_picks.py nfl             # live picks for one sport (stdlib): data/games_picks_nfl.json
                                                   # (cfb, nfl, cbb, nba; run after that sport's game build)

The walk-forward files, one per sport (scripts/games_wf/; re-run after a sport's model changes, then --fit):
    node scripts/games_wf/cfb_wf.mjs md.json.gz scripts/data/games_wf/cfb.json.gz [espn_odds.json]
                                         # the "cfb game research" workflow's model-input dump; season-swap folds
    python3 scripts/games_wf/nfl_wf.py   # the live model's walk (nflverse), 2015 on
    python3 scripts/nba_games.py --fit && python3 scripts/games_wf/nba_wf.py
    python3 scripts/games_wf/cbb_wf.py   # the committed tuning (2016-20) walked forward, 2016 on

Calibration. Each sport's game model already has a walk-forward history: every past game predicted by weights fit only
on the seasons before it (scripts/data/games_wf/<sport>.json.gz; how each was made is in that sport's notes below).
For each market the chance a bet wins is a logistic on the model's disagreement with the line, with the market's own
no-vig price as the offset:

    logit P(home covers)  = logit q(spread prices) + b * (model margin - line)
    logit P(home wins)    = logit q(moneylines)    + b * (model margin - line)
    logit P(over)         = logit q(total prices)  + b * (model total - total)

b = 0 is the market itself; b is fit, in each test season, on the seasons before it, so b says how much of the model's
disagreement with the closing line has held up. No intercept: a home or favorite lean in the past is not a bet. Expected
return = P x payout - (1 - P) at the price on the board.

Thresholds. A market is bet when its expected return clears a cut. The cut is chosen on the tuning seasons only (the
cut with the best return there, 40+ bets and t >= 1); a market whose best cut doesn't reach that is off. The seasons
after the tuning ones never touched the cut or the fit and are the held-out record shown on the page. One side bet per
game (the spread or the moneyline, whichever expects more) and one total.

Units: the Kelly stake at the calibrated chance over the average Kelly stake of that market's backtest bets, clipped
0.25-3 and rounded to quarters, so the average pick is 1 unit. Live picks are logged at the line and price when first
flagged and graded from ESPN's final score.

Judged by the close first (Oct 21 2026, scripts/clv.py): each graded pick gets the points the line moved its way and the
return it was worth at the closing line (clvRet); the record leads with those, ROI second. Every build also appends
the board's lines and the model's numbers to the timed odds archive (scripts/data/odds/<sport>-<yyyy-mm>.jsonl): the
close is a game's last archived line before the start, and the archive's snapshots by hours to the start are the bet
timing table.
"""
import datetime
import gzip
import json
import math
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WF = os.path.join(HERE, 'data', 'games_wf')
FIT = os.path.join(ROOT, 'data', 'games_picks_fit.json')
OUT = os.path.join(ROOT, 'data', 'games_picks_{}.json')
SPORTS = ('cfb', 'nfl', 'cbb', 'nba')
NAMES = {'cfb': 'college football', 'nfl': 'NFL', 'cbb': 'college basketball', 'nba': 'NBA'}
# first held-out season: the same split each sport's game model reports (CFB has two seasons: 2025 tunes, 2026 tests)
HELD = {'cfb': 2026, 'nfl': 2021, 'cbb': 2021, 'nba': 2022}
MARKETS = ('spread', 'ml', 'total')
CUTS = [round(0.01 * i, 2) for i in range(0, 16)]
MIN_N, MIN_T = 40, 1.0
ML_CAP = 300                      # moneylines past +-300 are left out (the calibration is thin in the tails)
KELLY_MIN, KELLY_CAP = 0.25, 3.0
ESPN = {'cfb': 'football/college-football', 'nfl': 'football/nfl', 'cbb': 'basketball/mens-college-basketball', 'nba': 'basketball/nba'}
UA = 'Mozilla/5.0 (arkndjl.net arkboard)'
ODDS = os.path.join(HERE, 'data', 'odds')
SNAP = ('L', 'T', 'mlH', 'mlA', 'oH', 'oA', 'm', 'tm')
sys.path.insert(0, HERE)
import clv as C


def price(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return v if abs(v) >= 100 else default


def dec(o):
    return 1 + o / 100 if o > 0 else 1 + 100 / -o


def lg(p):
    return math.log(p / (1 - p))


def sig(z):
    return 1 / (1 + math.exp(-z))


def novig(a, b):
    pa, pb = 1 / dec(a), 1 / dec(b)
    return pa / (pa + pb)


CAP = {}                          # per sport: (spread, total) disagreement past which a game is skipped (set by fit)


def markets(g, cap=(None, None)):
    """the bets on one game: {market: (x, offset, (home/over price, away/under price))}; g has m, L, tm, T and prices.
    A game is skipped when the model and the line disagree by more than three standard deviations of that sport's
    disagreement (in the history these are mostly bad lines: a sign flipped, a stale number), or when the spread and
    the moneyline name different favorites."""
    out = {}
    m, L = g.get('m'), g.get('L')
    mh, ma = price(g.get('mlH')), price(g.get('mlA'))
    if L is not None and mh is not None and ma is not None and abs(L) >= 3 and (mh < ma) != (L > 0):
        return out
    if m is not None and L is not None and (cap[0] is None or abs(m - L) <= cap[0]):
        a, b = price(g.get('oH'), -110), price(g.get('oA'), -110)
        out['spread'] = (m - L, lg(novig(a, b)), (a, b))
        if mh is not None and ma is not None and max(abs(mh), abs(ma)) <= ML_CAP:
            out['ml'] = (m - L, lg(novig(mh, ma)), (mh, ma))
    if g.get('tm') is not None and g.get('T') is not None and (cap[1] is None or abs(g['tm'] - g['T']) <= cap[1]):
        a, b = price(g.get('oO'), -110), price(g.get('oU'), -110)
        out['total'] = (g['tm'] - g['T'], lg(novig(a, b)), (a, b))
    return out


def outcome(g, mk):
    """1 home/over wins, 0 loses, None push"""
    if mk == 'spread':
        d = g['res'] - g['L']
    elif mk == 'ml':
        d = g['res']
    else:
        d = g['tot'] - g['T']
    return None if d == 0 else (1 if d > 0 else 0)


def bets_for(g, coef, cap=(None, None)):
    """every bet on a game with its calibrated chance and expected return: list of dicts"""
    out = []
    for mk, (x, off, (pa, pb)) in markets(g, cap).items():
        b = coef.get(mk)
        if b is None:
            continue
        ph = sig(off + b * x)
        for side, p, o in (('home' if mk != 'total' else 'over', ph, pa), ('away' if mk != 'total' else 'under', 1 - ph, pb)):
            pay = dec(o) - 1
            ev = p * pay - (1 - p)
            out.append({'mk': mk, 'side': side, 'p': p, 'price': o, 'ev': ev, 'kelly': max(ev, 0) / pay})
    return out


def choose(bets, cuts):
    """the bets that clear their market's cut: the best side bet (spread or moneyline) and the best total"""
    pick = []
    for fam in (('spread', 'ml'), ('total',)):
        c = [b for b in bets if b['mk'] in fam and cuts.get(b['mk']) is not None and b['ev'] > cuts[b['mk']]]
        if c:
            pick.append(max(c, key=lambda b: b['ev']))
    return pick


def summ(bs):
    n = len(bs)
    pr = [b['profit'] for b in bs]
    u = sum(pr)
    mu = u / n if n else 0.0
    sd = math.sqrt(sum((x - mu) ** 2 for x in pr) / (n - 1)) if n > 1 else 0.0
    risked = sum(b.get('units', 1.0) for b in bs)
    su = sum(b.get('units', 1.0) * b['profit'] for b in bs)
    return {'n': n, 'w': sum(1 for x in pr if x > 0), 'l': sum(1 for x in pr if x < 0), 'units': round(u, 1),
            'roi': round(mu, 3) if n else None, 't': round(mu / (sd / math.sqrt(n)), 2) if n > 1 and sd else None,
            'ev': round(sum(b['ev'] for b in bs) / n, 3) if n else None,
            'sized': {'units': round(su, 1), 'risked': round(risked, 1), 'roi': round(su / risked, 3) if risked else None}}


def load_wf(sport):
    fn = os.path.join(WF, sport + '.json.gz')
    return [r for r in json.load(gzip.open(fn)) if r.get('L') is not None] if os.path.exists(fn) else []


def fit_b(rows, mk, cap=(None, None)):
    """MLE of the one slope (no intercept) by Newton, tiny ridge"""
    D = []
    for r in rows:
        x = markets(r, cap).get(mk)
        y = outcome(r, mk) if x else None
        if x and y is not None:
            D.append((x[0], x[1], y))
    if len(D) < 200:
        return None, len(D)
    b = 0.0
    for _ in range(30):
        g = h = 0.0
        for x, off, y in D:
            p = sig(off + b * x)
            g += (y - p) * x
            h += p * (1 - p) * x * x
        g -= 1e-3 * b
        h += 1e-3
        b += g / h
    return b, len(D)


def fit():
    res = {'asof': datetime.date.today().isoformat(), 'minN': MIN_N, 'minT': MIN_T, 'cuts': CUTS, 'mlCap': ML_CAP,
           'kelly': [KELLY_MIN, KELLY_CAP], 'sports': {}}
    for sport in SPORTS:
        rows = load_wf(sport)
        if not rows:
            continue
        seasons = sorted({r['S'] for r in rows})
        held = HELD[sport]
        sd = lambda v: math.sqrt(sum(x * x for x in v) / len(v) - (sum(v) / len(v)) ** 2)
        tv = [r['tm'] - r['T'] for r in rows if r.get('tm') is not None and r.get('T') is not None]
        cap = (round(3 * sd([r['m'] - r['L'] for r in rows]), 1), round(3 * sd(tv), 1) if tv else None)
        # walk-forward: every season's bets priced by b fit on the seasons before it (CFB: on the other season)
        allb = {mk: [] for mk in MARKETS}
        bs_by = {}
        for S in seasons:
            tr = [r for r in rows if (r['S'] != S if sport == 'cfb' else r['S'] < S)]
            coef = {}
            for mk in MARKETS:
                coef[mk] = fit_b(tr, mk, cap)[0]
            bs_by[S] = coef
            for r in rows:
                if r['S'] != S:
                    continue
                for b in bets_for(r, coef, cap):
                    y = outcome(r, b['mk'])
                    if y is None:
                        continue
                    won = (y == 1) == (b['side'] in ('home', 'over'))
                    allb[b['mk']].append({**b, 'S': S, 'id': r['id'], 'profit': dec(b['price']) - 1 if won else -1.0})
        # cuts on the tuning seasons
        mkt = {}
        cuts = {}
        for mk in MARKETS:
            tune = [b for b in allb[mk] if b['S'] < held]
            best = None
            grid = []
            for c in CUTS:
                s = summ([b for b in tune if b['ev'] > c])
                grid.append({'cut': c, 'n': s['n'], 'roi': s['roi'], 't': s['t']})
                if s['n'] >= MIN_N and s['roi'] is not None and s['roi'] > 0 and (s['t'] or 0) >= MIN_T and (best is None or s['roi'] > best[1]):
                    best = (c, s['roi'])
            cuts[mk] = best[0] if best else None
            mkt[mk] = {'cut': cuts[mk], 'grid': grid, 'n': len(allb[mk]) // 2}
        # the shipped rule on every season: the chosen bets per game (one side bet, one total). A market whose own
        # tuning record under that rule misses the gate (the side bet went to the other market) is turned off and
        # the rest re-chosen.
        by_game = {}
        for mk in MARKETS:
            for b in allb[mk]:
                by_game.setdefault((b['S'], b['id']), []).append(b)
        for _ in range(3):
            chosen = [b for bs in by_game.values() for b in choose(bs, cuts)]
            bad = []
            for mk in MARKETS:
                if cuts[mk] is None:
                    continue
                s_ = summ([b for b in chosen if b['mk'] == mk and b['S'] < held])
                if s_['n'] < MIN_N or (s_['roi'] or 0) <= 0 or (s_['t'] or 0) < MIN_T:
                    bad.append(mk)
            if not bad:
                break
            for mk in bad:
                cuts[mk] = None
                mkt[mk]['cut'] = None
                mkt[mk]['dropped'] = True
        # Kelly units, each season's scale from the other seasons
        for b in chosen:
            other = [x['kelly'] for x in chosen if x['mk'] == b['mk'] and x['S'] != b['S']]
            sc = sum(other) / len(other) if other else None
            b['units'] = min(KELLY_CAP, max(KELLY_MIN, b['kelly'] / sc)) if sc else 1.0
        for mk in MARKETS:
            cb = [b for b in chosen if b['mk'] == mk]
            mkt[mk].update({'tune': summ([b for b in cb if b['S'] < held]), 'held': summ([b for b in cb if b['S'] >= held]),
                            'bySeason': [{'season': S, **{k: v for k, v in summ([b for b in cb if b['S'] == S]).items() if k in ('n', 'w', 'l', 'roi')}} for S in seasons],
                            'scale': round(sum(b['kelly'] for b in cb) / len(cb), 4) if cb else None})
            # how far the expected return ran ahead of the result, held out (every bet with positive expected return)
            pos = [b for b in allb[mk] if b['S'] >= held and b['ev'] > 0]
            mkt[mk]['heldAll'] = summ(pos)
        # the live slope: fit on every season
        live = {mk: fit_b(rows, mk, cap) for mk in MARKETS}
        res['sports'][sport] = {'name': NAMES[sport], 'cap': list(cap), 'seasons': [seasons[0], seasons[-1]], 'held': held, 'games': len(rows),
                                'b': {mk: round(v[0], 4) if v[0] is not None else None for mk, v in live.items()},
                                'bN': {mk: v[1] for mk, v in live.items()},
                                'bBySeason': {str(S): {mk: round(v, 4) if v is not None else None for mk, v in c.items()} for S, c in bs_by.items()},
                                'markets': mkt,
                                'all': {'tune': summ([b for b in chosen if b['S'] < held]), 'held': summ([b for b in chosen if b['S'] >= held])}}
        on = [mk for mk in MARKETS if cuts[mk] is not None]
        print(sport, 'b', res['sports'][sport]['b'], 'on', {mk: cuts[mk] for mk in on})
        for mk in MARKETS:
            m = mkt[mk]
            print(f"  {mk:6s} cut {m['cut']}  tune {m['tune']['n']} {m['tune']['roi']} t {m['tune']['t']}  held {m['held']['n']} {m['held']['roi']} t {m['held']['t']}"
                  f"  (held, every +EV bet: {m['heldAll']['n']} roi {m['heldAll']['roi']} vs ev {m['heldAll']['ev']})")
    with open(FIT, 'w') as f:
        json.dump(res, f, indent=1)


# ---------------------------------------------------------------- live

def board(sport):
    """this slate from the sport's own build: list of {id, espn, kick, home, away, m, L, tm, T, mlH, mlA, oH, oA}"""
    out = []
    if sport == 'cfb':
        d = json.load(open(os.path.join(ROOT, 'data', 'cfb_games.json')))
        for g in d.get('games', []):
            p = g.get('proj') or {}
            if g.get('market') is None or p.get('margin') is None:
                continue
            ml, so = g.get('ml') or {}, g.get('spreadOdds') or {}
            out.append({'id': str(g['id']), 'espn': str(g['id']), 'kick': g['date'], 'home': g['home']['name'], 'away': g['away']['name'],
                        'm': p['margin'], 'L': -float(g['market']), 'tm': p.get('total'), 'T': g.get('total'),
                        'mlH': ml.get('home'), 'mlA': ml.get('away'), 'oH': so.get('home'), 'oA': so.get('away')})
        return out
    d = json.load(open(os.path.join(ROOT, 'data', f'{sport}_games.json')))
    for g in d.get('games', []):
        if g.get('line') is None or g.get('final'):
            continue
        ml = g.get('ml') or {}
        h, a = g['home'], g['away']
        out.append({'id': str(g['id']), 'espn': str(g.get('espn') or g['id']), 'kick': g.get('kick') or g.get('tip'),
                    'home': h['n'] if isinstance(h, dict) else h, 'away': a['n'] if isinstance(a, dict) else a,
                    'm': g['margin'], 'L': float(g['line']), 'tm': g.get('total'), 'T': g.get('tline'),
                    'mlH': ml.get('home'), 'mlA': ml.get('away')})
    return out


def espn_final(sport, eid):
    try:
        req = urllib.request.Request(f'https://site.api.espn.com/apis/site/v2/sports/{ESPN[sport]}/summary?event={eid}', headers={'User-Agent': UA})
        j = json.load(urllib.request.urlopen(req, timeout=20))
        c = j['header']['competitions'][0]
        if not c['status']['type'].get('completed'):
            return None
        sc = {x['homeAway']: float(x['score']) for x in c['competitors']}
        return sc['home'], sc['away']
    except Exception:
        return None


def iso(t):
    return datetime.datetime.fromisoformat(t.replace('Z', '+00:00'))


def archive_rows(sport):
    """every snapshot in the odds archive for a sport, oldest first"""
    rows = []
    if os.path.isdir(ODDS):
        for fn in sorted(os.listdir(ODDS)):
            if fn.startswith(sport + '-') and fn.endswith('.jsonl'):
                with open(os.path.join(ODDS, fn)) as f:
                    rows += [json.loads(x) for x in f if x.strip()]
    return rows


def archive(sport, games, now, rows):
    """The timed odds archive (scripts/data/odds/<sport>-<yyyy-mm>.jsonl): each game not yet started, at every build that
    sees its line or price or the model's number change, with the time it was seen and the model's margin and total
    as they stood then (so a bet-timing test never uses news the line didn't have). Returns the new rows."""
    last = {}
    for r in rows:
        last[r['id']] = r
    new = []
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    for g in games:
        if not g.get('kick') or iso(g['kick']) <= now or g.get('L') is None:
            continue
        snap = {k: (round(float(g[k]), 2) if k in ('m', 'tm') else g[k]) if g.get(k) is not None else None for k in SNAP}
        kick = iso(g['kick']).strftime('%Y-%m-%dT%H:%M:%SZ')
        prev = last.get(str(g['id']))
        if prev and all(prev.get(k) == snap[k] for k in SNAP) and prev.get('k') == kick:
            continue
        new.append({'t': stamp, 'id': str(g['id']), 'k': kick, **snap})
    if new:
        os.makedirs(ODDS, exist_ok=True)
        with open(os.path.join(ODDS, f'{sport}-{now:%Y-%m}.jsonl'), 'a') as f:
            for r in new:
                f.write(json.dumps(r, separators=(',', ':')) + '\n')
    return new


def live(sport):
    F = json.load(open(FIT))['sports'].get(sport)
    fn = OUT.format(sport)
    try:
        old = json.load(open(fn))
    except (OSError, ValueError):
        old = {}
    log = old.get('log', [])
    if not F:
        return print(f'{sport} picks: no fit')
    coef = F['b']
    cap = tuple(F.get('cap') or (None, None))
    cuts = {mk: F['markets'][mk]['cut'] for mk in MARKETS}
    scale = {mk: F['markets'][mk].get('scale') for mk in MARKETS}
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    games = board(sport)
    arch = archive_rows(sport)
    arch += archive(sport, games, now, arch)
    # the close: each game's last archived snapshot before its kick
    closes = {}
    for r in arch:
        if r['t'] < r['k']:
            closes[r['id']] = r
    seen = {(e['id'], e['mk'], e['side']) for e in log}
    G = {g['id']: g for g in games}
    cur = {}
    top = []
    # suggested units on the game table: each game's best bet by expected return, Kelly-sized on its market's
    # pick scale (or the mean scale of the markets that are on, for a market that is off); 0 when nothing is +EV
    on = [v for v in scale.values() if v]
    gsc = sum(on) / len(on) if on else None
    if not gsc:
        sc_all = [m.get('scale') for x in json.load(open(FIT))['sports'].values() for m in x['markets'].values() if m.get('scale')]
        gsc = sum(sc_all) / len(sc_all) if sc_all else None
    def sized(b, pick):
        sc = scale.get(b['mk']) or gsc
        u = min(KELLY_CAP, b['kelly'] / sc) if sc else 0.0
        if pick:
            u = max(KELLY_MIN, u)
        return round(u * 4) / 4 if b['ev'] > 0 else 0.0
    gtab = {}
    for g in games:
        if not g['kick'] or iso(g['kick']) <= now:
            continue
        bs = bets_for(g, coef, cap)
        if bs:
            b = max(bs, key=lambda b: b['ev'])
            pick = cuts.get(b['mk']) is not None and b['ev'] > cuts[b['mk']]
            u = sized(b, pick)
            gtab[str(g['id'])] = {'mk': b['mk'], 'side': b['side'], 'home': g['home'], 'away': g['away'],
                                  'line': g['T'] if b['mk'] == 'total' else (g['L'] if b['mk'] != 'ml' else None), 'price': b['price'],
                                  'ev': round(b['ev'], 3), 'units': u,
                                  'state': 'pick' if pick else ('off' if cuts.get(b['mk']) is None else 'under')}
        # the board: every game's best side bet and best total by expected return, cut or not
        for b in choose(bets_for(g, coef, cap), {mk: -1.0 for mk in MARKETS}):
            top.append({'id': g['id'], 'sport': sport, 'kick': g['kick'], 'home': g['home'], 'away': g['away'], 'mk': b['mk'], 'side': b['side'],
                        'line': g['T'] if b['mk'] == 'total' else (g['L'] if b['mk'] != 'ml' else None), 'price': b['price'],
                        'p': round(b['p'], 3), 'ev': round(b['ev'], 3), 'm': round(g['m'], 1), 'tm': round(g['tm'], 1) if g.get('tm') is not None else None,
                        'cut': cuts.get(b['mk']), 'units': sized(b, False)})
        for b in choose(bets_for(g, coef, cap), cuts):
            sc = scale.get(b['mk'])
            units = round((min(KELLY_CAP, max(KELLY_MIN, b['kelly'] / sc)) if sc else 1.0) * 4) / 4
            line = g['T'] if b['mk'] == 'total' else (g['L'] if b['mk'] != 'ml' else None)
            cur[(g['id'], b['mk'], b['side'])] = {'price': b['price'], 'ev': round(b['ev'], 3)}
            if (g['id'], b['mk'], b['side']) in seen:
                continue
            seen.add((g['id'], b['mk'], b['side']))
            log.append({'id': g['id'], 'espn': g['espn'], 'sport': sport, 'kick': g['kick'], 'home': g['home'], 'away': g['away'],
                        'mk': b['mk'], 'side': b['side'], 'line': line, 'price': b['price'], 'p': round(b['p'], 3), 'ev': round(b['ev'], 3),
                        'units': units, 'm': round(g['m'], 1), 'tm': round(g['tm'], 1) if g.get('tm') is not None else None, 'flagged': stamp})
    # the line at kickoff (the last one this build saw before the game) for closing line value; then the final
    for e in log:
        g = G.get(e['id'])
        if g and e.get('res') is None and iso(g['kick']) > now:
            e['close'] = g['T'] if e['mk'] == 'total' else g['L']
        if e.get('res') is not None or iso(e['kick']) > now - datetime.timedelta(hours=3):
            continue
        fin = espn_final(sport, e['espn'])
        if not fin:
            continue
        hs, as_ = fin
        e['score'] = [as_, hs]
        if e['mk'] == 'total':
            d = hs + as_ - e['line']
            win = None if d == 0 else (d > 0) == (e['side'] == 'over')
        elif e['mk'] == 'spread':
            d = hs - as_ - e['line']
            win = None if d == 0 else (d > 0) == (e['side'] == 'home')
        else:
            d = hs - as_
            win = None if d == 0 else (d > 0) == (e['side'] == 'home')
        e['res'] = 'p' if win is None else ('w' if win else 'l')
        e['profit'] = 0.0 if win is None else round(dec(e['price']) - 1 if win else -1.0, 3)
    # closing line value: the pick's line and price against the close (the last line archived before the start, else
    # the last this build saw), as points and as the return the bet was worth if the close is the true price
    for e in log:
        if e.get('res') is None:
            continue
        c = closes.get(str(e['id']))
        if c:
            e['close'] = c['T'] if e['mk'] == 'total' else c['L']
            if e['mk'] == 'ml':
                e['closeML'] = [c.get('mlH'), c.get('mlA')]
        if e.get('close') is None:
            continue
        cml = tuple(e['closeML']) if e.get('closeML') and None not in e['closeML'] else None
        C.judge(e, sport, e['mk'], e['side'], e['line'], e['price'], e['close'], cml)
    done = [e for e in log if e.get('res') is not None]
    rec = summ([{'profit': e['profit'], 'units': e['units'], 'ev': e['ev']} for e in done]) if done else {'n': 0}
    rec.update(C.summary(done))
    rec['byMarket'] = {mk: {**C.summary([e for e in done if e['mk'] == mk]), 'n': sum(1 for e in done if e['mk'] == mk)} for mk in MARKETS}
    picks = []
    for e in log:
        if e.get('res') is None and iso(e['kick']) > now - datetime.timedelta(hours=4):
            p = dict(e)
            p['now'] = cur.get((e['id'], e['mk'], e['side']))
            picks.append(p)
    picks.sort(key=lambda p: -p['ev'])
    top.sort(key=lambda b: -b['ev'])
    # bet timing: the model's side at each archived line, by hours before the start, judged by the close
    mins = {'cfb': 3, 'nfl': 2, 'cbb': 3, 'nba': 2}
    timing = C.timing(sport, arch, mins[sport])
    out = {'sport': sport, 'name': NAMES[sport], 'asof': stamp, 'picks': picks, 'board': top[:25], 'games': gtab, 'record': rec,
           'timing': {'minEdge': mins[sport], 'snapshots': len(arch), 'buckets': timing},
           'recent': sorted(done, key=lambda e: e['kick'], reverse=True)[:40], 'log': log}
    if {k: v for k, v in old.items() if k != 'asof'} == json.loads(json.dumps({k: v for k, v in out.items() if k != 'asof'})):
        return print(f'{sport} picks: no change')
    with open(fn, 'w') as f:
        json.dump(out, f, indent=1)
    print(f'{sport} picks: {len(picks)} open, {len(done)} graded')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--fit':
        fit()
    elif a and a[0] in SPORTS:
        live(a[0])
    else:
        print(__doc__)
