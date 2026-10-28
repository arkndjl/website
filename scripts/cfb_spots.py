#!/usr/bin/env python3
"""CFB schedule spots: letdown, look-ahead and bounce-back (thread "Test a CFB letdown-game driver", Oct 28 2026).

Does a team play worse than the close (and the model) the week after a big win, the week before a big game, or better
after an upset loss? Pre-registered before any outcome was looked at (definitions below, one BH family over all of them).
Rows: scripts/data/games_wf/cfb.json.gz (lined FBS games 2017-26, the walk-forward model m, close L, result res, home view).
Each spot is a team flag; the term is home flag minus away flag; residuals res - L and res - m. Tune 2017-22, held 2023-26,
standard errors clustered by game day. Ship bar: tune t <= -1.5 with the expected sign AND held-out squared error of
L + b x below L (b fit on tune) at paired t <= -1.5, so it beats the close out of sample.
Ranks: ESPN scoreboard curatedRank at kickoff (AP top 25, the CFP ranking once it is out), scripts/data/cfb_ranks.json.

Team T, G2 = this game (regular season), G1 = T's previous game, played (and finished) within 9 days before G2:
  LD   letdown: T won G1 AND (G1 opponent ranked OR T was a >= 3 pt closing underdog in G1)        primary, SHIPPED
       secondaries: LDr won vs ranked, LDu won as a 3+ dog, LDt won vs top 10, LDweak LD and G2 opponent unranked,
       LDany LD after a bye too, G1oc G1 margin over the close / 14 (clipped +-2)
  LA   look-ahead: T's next game after G2 is vs a ranked opponent AND G2's opponent is unranked      primary, null
       (the next opponent's rank is the poll in force at G2 kickoff: its own game that week)
       secondaries: LA1 next opponent ranked (any G2), LA2 either of the next two ranked, LAt next opponent top 10,
       LAfav LA and T favoured in G2
  BB   bounce-back ("blowout spot"): T lost G1 as a >= 3 pt closing favourite (expected sign +)     primary, null
       secondaries: BB7 lost as a 7+ favourite, BBr T ranked and lost to an unranked team, BBfav BB and T favoured in G2
Result Oct 28 2026: LD passes (close b -1.0 tune t -1.7, -2.1 held t -3.0; held squared error vs the close t -2.2; every
season 2017-26 negative). LA and BB fail: LA is ~0 everywhere; BB fits +1.4 on tune (t 2.4) and reverses held out.
Shipped as cfb_model.mjs LETDOWN (b = the tune fit on the model's residual), applied to every margin (live, sim, walk-forward).

    python3 scripts/cfb_spots.py                 # research -> data/cfb_spots.json + ledger rows
    python3 scripts/cfb_spots.py --ranks [S..]   # pull ESPN scoreboards (cached) and refresh cfb_ranks.json (default: this season)
    python3 scripts/cfb_spots.py --wf            # apply LETDOWN to scripts/data/games_wf/cfb.json.gz (once; rows keep ld)
Then games_picks.py --fit and --rules.
"""
import collections
import datetime
import gzip
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
try:
    import numpy as np
    import harness as H
except ImportError:             # --ranks runs on the stdlib (the board workflow's system Python)
    np = H = None

WF = os.path.join(HERE, 'data', 'games_wf', 'cfb.json.gz')
HIST = os.path.join(HERE, 'data', 'cfb_hist_md.json.gz')
RANKS = os.path.join(HERE, 'data', 'cfb_ranks.json')
CACHE = os.path.join(HERE, '.cache', 'cfb', 'scoreboard')
OUT = os.path.join(ROOT, 'data', 'cfb_spots.json')
LETDOWN = {'b': -1.3, 'dog': 3, 'gap': 9}       # cfb_model.mjs LETDOWN
TUNE, HELD = range(2017, 2023), range(2023, 2027)
SB = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={S}&seasontype={st}&week={w}&groups=80&limit=500'
SIGN = {'LD': -1, 'LDr': -1, 'LDu': -1, 'LDt': -1, 'LDweak': -1, 'LDany': -1, 'G1oc': -1,
        'LA': -1, 'LA1': -1, 'LA2': -1, 'LAt': -1, 'LAfav': -1, 'BB': 1, 'BB7': 1, 'BBr': 1, 'BBfav': 1}
PRIMARY = ('LD', 'LA', 'BB')


# ---- ESPN scoreboards -----------------------------------------------------------------------------------------------
def pull(S, fresh=False):
    os.makedirs(CACHE, exist_ok=True)
    out = []
    for st, wks in ((2, range(1, 17)), (3, range(1, 2))):
        for w in wks:
            fn = os.path.join(CACHE, f'{S}_{st}_{w}.json')
            if fresh or not os.path.exists(fn):
                for k in range(4):
                    try:
                        raw = urllib.request.urlopen(SB.format(S=S, st=st, w=w), timeout=30).read()
                        break
                    except Exception:
                        time.sleep(2 ** k)
                else:
                    print(f'cfb_spots: no scoreboard {S} {st} {w}')
                    continue
                open(fn, 'wb').write(raw)
            out.extend(json.load(open(fn)).get('events', []))
    return out


def games(S, fresh=False):
    rows = {}
    for e in pull(S, fresh):
        c = e['competitions'][0]
        t = {x['homeAway']: x for x in c['competitors']}
        if 'home' not in t or 'away' not in t:
            continue
        rk = lambda x: (lambda r: r if r and r <= 25 else 99)((x.get('curatedRank') or {}).get('current', 99))
        sc = lambda x: float(x['score']) if x.get('score') not in (None, '') else None
        rows[e['id']] = dict(id=e['id'], S=S, st=e['season']['type'], date=e['date'], done=bool(c['status']['type'].get('completed')),
                             h=t['home']['team']['id'], a=t['away']['team']['id'], hr=rk(t['home']), ar=rk(t['away']), hp=sc(t['home']), ap=sc(t['away']))
    return list(rows.values())


def ranks(seasons, this):
    cur = json.load(open(RANKS)) if os.path.exists(RANKS) else {}
    for S in seasons:
        G = games(S, fresh=S >= this)
        cur[str(S)] = {g['id']: [g['hr'], g['ar']] for g in G if g['hr'] < 99 or g['ar'] < 99}
    json.dump(dict(sorted(cur.items())), open(RANKS, 'w'), separators=(',', ':'))
    print(f"cfb_spots: ranks for {', '.join(map(str, seasons))} -> {RANKS}")


# ---- flags --------------------------------------------------------------------------------------------------------
def closes():
    """closing home margin by game id: the walk-forward file, then the history's consensus line"""
    out = {}
    hist = json.load(gzip.open(HIST))
    for ls in hist['lines'].values():
        for x in ls:
            ln = x['lines']
            pick = next((l for l in ln if l.get('provider') == 'consensus'), None) or next((l for l in ln if l.get('spread') is not None), None)
            if pick and pick.get('spread') is not None:
                out[str(x['id'])] = -pick['spread']
    for r in json.load(gzip.open(WF)):
        if r.get('L') is not None:
            out[str(r['id'])] = r['L']
    return out


def flags(G, L):
    when = lambda s: datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
    sch = collections.defaultdict(list)
    for g in G:
        for me, op in (('h', 'a'), ('a', 'h')):
            sch[(g['S'], g[me])].append(dict(g=g, me=me, opp=g[op], oppr=g[op + 'r'], myr=g[me + 'r'], t=when(g['date'])))
    for v in sch.values():
        v.sort(key=lambda e: e['t'])

    def rank_at(S, team, t):          # the poll in force at t: the team's own game that week, else its last game before t
        es = sch[(S, team)]
        near = [(abs((e['t'] - t).total_seconds()) / 864e2, e['myr']) for e in es]
        near = [x for x in near if x[0] <= 4]
        if near:
            return min(near)[1]
        prev = [e for e in es if e['t'] < t]
        return prev[-1]['myr'] if prev else 99

    def tv(e, v):
        return None if v is None else (v if e['me'] == 'h' else -v)

    F = {}
    for (S, team), es in sch.items():
        for i, e in enumerate(es):
            g = e['g']
            if g['st'] != 2:
                continue
            f = dict.fromkeys(SIGN, 0)
            p = es[i - 1] if i else None
            if p and p['g']['done'] and p['g']['hp'] is not None:
                gap = (e['t'] - p['t']).total_seconds() / 864e2
                mar = tv(p, p['g']['hp'] - p['g']['ap'])
                won, lost = mar > 0, mar < 0
                Lp = tv(p, L.get(p['g']['id']))
                near = gap <= LETDOWN['gap']
                big = won and (p['oppr'] <= 25 or (Lp is not None and Lp <= -LETDOWN['dog']))
                f['LDany'] = int(big)
                f['LD'] = int(big and near)
                f['LDr'] = int(won and p['oppr'] <= 25 and near)
                f['LDu'] = int(won and Lp is not None and Lp <= -LETDOWN['dog'] and near)
                f['LDt'] = int(won and p['oppr'] <= 10 and near)
                f['LDweak'] = int(f['LD'] and e['oppr'] > 25)
                f['G1oc'] = max(-2, min(2, (mar - Lp) / 14)) if near and Lp is not None else 0
                f['BB'] = int(lost and Lp is not None and Lp >= LETDOWN['dog'] and near)
                f['BB7'] = int(lost and Lp is not None and Lp >= 7 and near)
                f['BBr'] = int(lost and p['myr'] <= 25 and p['oppr'] > 25 and near)
            nx = [es[j] for j in (i + 1, i + 2) if j < len(es)]
            r = [rank_at(S, n['opp'], e['t']) if n['g']['st'] == 2 else 99 for n in nx] + [99, 99]
            unr = e['oppr'] > 25
            f['LA'] = int(r[0] <= 25 and unr)
            f['LA1'] = int(r[0] <= 25)
            f['LA2'] = int((r[0] <= 25 or r[1] <= 25) and unr)
            f['LAt'] = int(r[0] <= 10 and unr)
            Lt = tv(e, L.get(g['id']))
            fav = Lt is not None and Lt > 0
            f['LAfav'] = int(f['LA'] and fav)
            f['BBfav'] = int(f['BB'] and fav)
            F[(g['id'], e['me'])] = f
    return F


# ---- tests ----------------------------------------------------------------------------------------------------------
def ols_cl(X, y, c):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    XtXi = np.linalg.inv(X.T @ X)
    meat = sum(np.outer(s, s) for s in (X[c == g].T @ e[c == g] for g in np.unique(c)))
    n, k = X.shape
    G = len(np.unique(c))
    V = XtXi @ meat @ XtXi * G / (G - 1) * (n - 1) / (n - k)
    return b, np.sqrt(np.diag(V))


def research():
    G = [g for S in range(2016, 2027) for g in games(S)]
    F = flags(G, closes())
    rows = [r for r in json.load(gzip.open(WF)) if r['res'] is not None and r['L'] is not None and (str(r['id']), 'h') in F]
    for r in rows:
        r['m_'] = r['m'] - r.get('ld', 0)        # the model before this term
    S = np.array([r['S'] for r in rows])
    day = np.array([r['date'][:10] for r in rows])
    y, L, m = (np.array([r[k] for r in rows], float) for k in ('res', 'L', 'm_'))
    tune, held = np.isin(S, TUNE), np.isin(S, HELD)
    Phi = lambda z: 0.5 * (1 + np.vectorize(math.erf)(np.asarray(z) / math.sqrt(2)))
    out = {'asof': datetime.date.today().isoformat(), 'rows': len(rows), 'tune': [TUNE[0], TUNE[-1]], 'held': [HELD[0], HELD[-1]], 'terms': {}}
    for k, sg in SIGN.items():
        x = np.array([F[(str(r['id']), 'h')][k] - F[(str(r['id']), 'a')][k] for r in rows], float)
        o = {'flagged': {'tune': int((x[tune] != 0).sum()), 'held': int((x[held] != 0).sum())}}
        X = np.c_[np.ones(len(x)), x]
        for base, nm in ((L, 'close'), (m, 'model')):
            res = y - base
            fit = {}
            for part, mk in (('tune', tune), ('held', held), ('all', tune | held)):
                b, s = ols_cl(X[mk], res[mk], day[mk])
                fit[part] = (b, s)
            bt = fit['tune'][0]
            new, old = base + bt[0] + bt[1] * x, base + res[tune].mean()
            o[nm] = {p: {'b': round(float(b[1]), 2), 't': round(float(b[1] / s[1]), 2)} for p, (b, s) in fit.items()}
            for part, mk in (('tune', tune), ('held', held)):
                pr = H.paired(H.se(new[mk], y[mk]), H.se(old[mk], y[mk]), cluster=day[mk])
                o[nm]['se_' + part] = {'d': round(float(pr['d']), 3), 't': round(pr['t'], 2)}
        win = (y > 0) + 0.5 * (y == 0) - Phi(L / 13.7)
        b, s = ols_cl(X, win, day)
        o['winVsClose'] = {'b': round(float(b[1]), 3), 't': round(float(b[1] / s[1]), 2)}
        bw = (y >= 21) - (1 - Phi((21 - L) / 13.7)) - ((y <= -21) - Phi((-21 - L) / 13.7))
        b, s = ols_cl(X, bw, day)
        o['by21VsClose'] = {'b': round(float(b[1]), 3), 't': round(float(b[1] / s[1]), 2)}
        if k == 'LD':
            rc = y - L
            o['bySeason'] = {int(s_): round(float((rc * x)[(S == s_) & (x != 0)].mean()), 2) for s_ in sorted(set(S))}
            on = (x != 0) & (rc != 0)
            o['atsAgainst'] = {p: [int(((rc * x) < 0)[on & mk].sum()), int(((rc * x) > 0)[on & mk].sum())] for p, mk in (('tune', tune), ('held', held))}
        # one family: sign-matched Stouffer of the tune and held coefficient t's vs the close
        z = H.stouffer([sg * o['close']['tune']['t'], sg * o['close']['held']['t']])
        o['z'] = round(-z, 2)
        o['p'] = 2 * (1 - float(Phi(abs(z))))
        o['pass'] = bool(sg * o['close']['tune']['t'] >= 1.5 and o['close']['se_held']['t'] <= -1.5)
        out['terms'][k] = o
    q = H.bh([o['p'] for o in out['terms'].values()])
    for (k, o), qq in zip(out['terms'].items(), q):
        o['q'] = round(float(qq), 4)
        o['p'] = round(o['p'], 5)
    return out


def ledger(res):
    led = json.load(open(H.LEDGER))
    models = led['models']
    rows = [r for r in models['cfb_games']['rows'] if not r['term'].startswith('spot:')]
    for k, ship in (('LD', True), ('LA', False), ('BB', False)):
        o = res['terms'][k]['model']
        n = res['terms'][k]['flagged']
        rows.append(H.from_t(f'spot:{k}', o['se_tune']['t'], o['se_held']['t'], n['tune'], n['held'], d_held=-o['se_held']['d'],
                             note={'LD': 'letdown after a win vs a ranked team or as a 3+ dog, -1.3 pts', 'LA': 'look-ahead (next opponent ranked, this one not)',
                                   'BB': 'bounce-back after a loss as a 3+ favourite'}[k] + '; scripts/cfb_spots.py', shipped=ship))
    models['cfb_games']['rows'] = [{k: v for k, v in r.items() if k not in ('z', 'p', 'q', 'verdict')} for r in rows]
    H.write_ledger(models, pending=led.get('pending'))


def apply_wf():
    rows = json.load(gzip.open(WF))
    if any('ld' in r for r in rows):
        return print('cfb_spots: already applied')
    G = [g for S in sorted({r['S'] for r in rows}) for g in games(S)]
    F = flags(G, closes())
    n = 0
    for r in rows:
        k = (str(r['id']), 'h')
        if k in F:
            x = F[k]['LD'] - F[(str(r['id']), 'a')]['LD']
            if x:
                r['ld'] = LETDOWN['b'] * x
                r['m'] = round(r['m'] + r['ld'], 2)
                n += 1
    with gzip.open(WF, 'wt', encoding='utf-8') as f:
        json.dump(rows, f, separators=(',', ':'), ensure_ascii=False)
    print(f'cfb_spots: {n} walk-forward margins moved by the letdown term')


if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--ranks':
        this = datetime.date.today().year if datetime.date.today().month >= 7 else datetime.date.today().year - 1
        ranks([int(s) for s in a[1:]] or [this], this)
    elif a and a[0] == '--wf':
        apply_wf()
    else:
        res = research()
        json.dump(res, open(OUT, 'w'), indent=1)
        ledger(res)
        for k, o in res['terms'].items():
            c = o['close']
            print(f"{k:7} n {o['flagged']['tune']:4}/{o['flagged']['held']:4}  close b {c['tune']['b']:6} (t {c['tune']['t']:5}) held {c['held']['b']:6} (t {c['held']['t']:5})"
                  f"  held SE t {c['se_held']['t']:5}  model held {o['model']['held']['b']:6}  q {o['q']}  {'PASS' if o['pass'] else ''}")
