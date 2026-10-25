#!/usr/bin/env python3
"""Pre-registered 2027 draft ledger: dated snapshots of every board's draft read, scored once the drafts happen.

    python3 scripts/draft_ledger.py snap cfb|cbb|hockey      after each board run (the board workflows call it)
    python3 scripts/draft_ledger.py score cfb|cbb|hockey     after that sport's draft (see SCORE_AFTER)
    python3 scripts/draft_ledger.py score cfb --draft f.json a dry run against a made-up draft [[name, pick], ...]

Why: some of FV's weights can't be tested on history because the inputs have none. On3's college grade
(FV_W.on3 .40, scripts/fetch_cfb.mjs, FV's largest weight) has no past seasons, and neither do the fall mock market
weight or the Draft% fall curve. A forecast written down before the draft and scored after it is the only test. So
the ledger freezes what the boards said, and this file fixes how it will be scored, before anyone knows the answer.

Store: scripts/data/ledger/<sport>/<class>/<date>.json.gz, append-only. One snapshot a week through the season, then
one a day in the draft month (DAILY_FROM), so the eve-of-draft read is kept. A rerun on a snapshot day replaces that
day's file (the day's last board). gzip mtime 0, so an unchanged board writes the same bytes and no commit.
Each snapshot keeps the class's players (every FV component, Draft% / NBA% / slot odds, the board's model weights)
and every mock (predictive, blended, conviction).

PRE-REGISTERED SCORING (fixed 2026-10-25; change only with a dated note below, before the draft):
  outcome   the 2027 draft: NFL (nflverse draft_picks.csv), NBA (Basketball-Reference), NHL (NHL draft API).
            Players join through scripts/names.py (school / club checked when the source has one). Undrafted = tied
            last (pick = number of picks + 1).
  snapshots `final` = the last one before the draft's first day; `fall` = the first one on or after Nov 1, 2026.
            The curve reports every snapshot.
  1 board   Spearman rho of FV (fvx; hockey: fvx and xslot) with draft order, class players only. Per snapshot.
  2 odds    Draft% (CFB draftP: drafted at all; CBB nbaP: drafted at all; hockey p30: drafted at all, informational):
            Brier, log loss (p clipped .01-.99) and Brier skill vs the class base rate. Ten-bin calibration at `final`.
            Fall curve: Brier by snapshot date. Pass: skill > 0 at `final`; the fall curve passes if `fall` skill > 0.
  3 mocks   per mock, per snapshot: picks where the mock's player went in round 1 (hits of 32 / 30 / 32), exact
            pick-and-team hits, mean absolute error of mock slot vs actual slot over the mock's round-1 players
            (undrafted counted at last + 1). Fall mock market weight: blended vs predictive at `fall`, paired by
            player |error|, sign test. Blended wins = keep or raise the market weight; predictive wins at p < .10 =
            cut it by half.
  4 On3     CFB only, players with an On3 grade at `final`: y = inverse-normal of draft-order rank (undrafted tied);
            OLS y ~ z(on3) + parts[1] (production term) + sum of the other parts. ratio = b_on3 / b_prod against the
            board's 1.0 (.40 / .40). 2000 bootstrap draws over players, seed 2027. If the 90% interval leaves 1.0,
            new split = .80 x r / (1 + r) with r halfway between 1.0 and the fit (one class is a small sample);
            otherwise On3 stays .40. Same test at `fall`, reported only.
  Results go to data/draft_ledger_<sport>_<class>.json. A failed test is a result: it is reported, not tuned away.
"""
import csv, datetime as dt, gzip, io, json, math, os, random, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names as NM                       # noqa: E402  the shared player-name matcher

STORE = os.path.join(HERE, 'data', 'ledger')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
# run the score after these dates (2027 drafts: NFL late April, NBA and NHL late June)
SCORE_AFTER = {'cfb': '2027-04-25', 'cbb': '2027-06-27', 'hockey': '2027-06-27'}
DAILY_FROM = {'cfb': (4, 1), 'cbb': (6, 1), 'hockey': (6, 1)}   # (month, day) daily snapshots until the draft
FALL = '2026-11-01'


def load(p):
    with open(os.path.join(ROOT, p)) as f:
        return json.load(f)


def table(p):
    d = load(p)
    return [dict(zip(d['cols'], r)) for r in d['rows']]


def mock(p, key='picks'):
    d = load(p)
    return [[m.get('pick'), m.get('team'), m.get('name'), m.get('pos'), m.get('school') or m.get('club'), m.get('xPick')]
            for m in d[key]]


# ------------------------------------------------------------------- snapshots
def snap_cfb():
    d = load('data/cfb.json')
    top = {(p['name'], p['team']): p for p in d['players']}
    zs = ['talentZ', 'prodZ', 'ageZ', 'classZ', 'sizeZ', 'sosZ', 'statZ', 'hsZ', 'oeZ', 'castAdj', 'frameFV', 'yearsFV',
          'comp', 'fvBase', 'hsGrade', 'hsStars', 'on3Rank']
    cols = ['name', 'pos', 'team', 'div', 'cls', 'age', 'on3', 'pfn', 'cons', 'consRk', 'fv', 'fvx', 'fvg', 'fvd', 'parts',
            'draftP', 'ovr', 'posRank'] + zs
    rows = []
    for r in table('static/data/cfb-all.json'):
        # the 2027 class: draft-eligible next spring, and either a real Draft% or an On3 grade (the weight under test)
        if not r.get('draft27') or not ((r.get('draftP') or 0) >= 0.005 or r.get('on3')):
            continue
        t = top.get((r['name'], r['team']), {})
        rows.append([r.get(c) if c in r else t.get(c) for c in cols])
    mocks = {k: mock(f'data/{f}.json') for k, f in (('pred', 'cfb_mock_pred'), ('blend', 'cfb_mock'), ('conv', 'cfb_mock_conv'))}
    return {'cls': int(d['season']) + 1, 'asof': d['asof'], 'model': d.get('model'), 'cols': cols, 'rows': rows, 'mocks': mocks}


def snap_cbb():
    d = load('data/cbb.json')
    m = load('data/cbb_mock.json')
    named = {p['name'] for k in m['mocks'] for p in m['mocks'][k]}
    cols = ['name', 'team', 'conf', 'pos', 'cls', 'age', 'ageEst', 'ovr', 'fv', 'fvx', 'fvg', 'fvd', 'nbaP', 'xbpm', 'parts', 'rec']
    rows = [[r.get(c) for c in cols] for r in table('static/data/cbb-all.json')
            if (r.get('ovr') and r['ovr'] <= 400) or r['name'] in named]
    mocks = {k: [[p.get('pick'), p.get('team'), p.get('name'), p.get('pos'), p.get('school'), None] for p in v]
             for k, v in m['mocks'].items()}
    season = str(d['season'])
    cls = int(season[:4]) + 1 if '-' in season else int(season)
    return {'cls': cls, 'asof': d['asof'], 'model': d.get('models'), 'cols': cols, 'rows': rows, 'mocks': mocks}


def snap_hockey():
    d = load('data/hockey.json')
    m = load('data/hockey_mock.json')
    cols = ['rk', 'name', 'pos', 'club', 'league', 'age', 'gp', 'pts', 'nhle', 'xslot', 'fv', 'fvx', 'p30', 'p40', 'p50', 'p60', 'parts']
    rows = [[r.get(c) for c in cols] for r in d['board']]
    mocks = {k: mock('data/hockey_mock.json', k) for k in ('pred', 'blend', 'conv')}
    return {'cls': int(d['year']), 'asof': d['asof'], 'model': d.get('fit'), 'cols': cols, 'rows': rows, 'mocks': mocks}


def due(sport, folder, today):
    """a snapshot today? weekly, daily in the draft month; a rerun on a snapshot day replaces it"""
    have = sorted(f[:10] for f in os.listdir(folder) if f.endswith('.json.gz')) if os.path.isdir(folder) else []
    if not have or have[-1] == today.isoformat():
        return True
    mo, dy = DAILY_FROM[sport]
    if today.month == mo and today.day >= dy:
        return True
    return (today - dt.date.fromisoformat(have[-1])).days >= 7


def snap(sport):
    s = {'cfb': snap_cfb, 'cbb': snap_cbb, 'hockey': snap_hockey}[sport]()
    if dt.date.today().isoformat() >= SCORE_AFTER[sport] and s['cls'] <= int(SCORE_AFTER[sport][:4]):
        print(f'ledger {sport}: {s["cls"]} draft is past, not snapped'); return
    folder = os.path.join(STORE, sport, str(s['cls']))
    today = dt.datetime.now(dt.timezone.utc).date()
    if not due(sport, folder, today):
        print(f'ledger {sport}: not due (weekly)'); return
    os.makedirs(folder, exist_ok=True)
    s['snapped'] = today.isoformat()
    raw = json.dumps(s, separators=(',', ':'), allow_nan=False).encode()
    p = os.path.join(folder, f'{today.isoformat()}.json.gz')
    with gzip.GzipFile(p, 'wb', mtime=0) as f:
        f.write(raw)
    print(f'ledger {sport}: {len(s["rows"])} players, {sum(len(v) for v in s["mocks"].values())} mock picks -> '
          f'{os.path.relpath(p, ROOT)} ({os.path.getsize(p) // 1024} KB)')


# ------------------------------------------------------------------- the draft
def curl(url):
    return subprocess.run(['curl', '-sL', '-m', '90', '-A', UA, url], capture_output=True, text=True).stdout


def draft(sport, year):
    """[{name, pick, team, school}] for the year's draft"""
    if sport == 'cfb':
        rows = csv.DictReader(io.StringIO(curl('https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv')))
        return [{'name': r['pfr_player_name'], 'pick': int(r['pick']), 'team': r['team'], 'school': r.get('college')}
                for r in rows if r.get('season') == str(year)]
    if sport == 'cbb':
        import cbb_data
        return [{'name': r['name'], 'pick': r['pick'], 'team': None, 'school': r['college']} for r in cbb_data.load_draft(year)]
    j = json.loads(curl(f'https://api-web.nhle.com/v1/draft/picks/{year}/all') or '{}')
    return [{'name': f"{p['firstName']['default']} {p['lastName']['default']}", 'pick': p['overallPick'],
             'team': p.get('teamAbbrev'), 'school': p.get('amateurClubName')} for p in j.get('picks', [])]


def attach(rows, picks, sport):
    """each board row's draft slot, through the shared matcher (school checked when the source names one)"""
    sp = {'cfb': 'football', 'cbb': 'basketball', 'hockey': 'hockey'}[sport]
    m = NM.Matcher(picks, name='name', team='school', pos=None, sport=sp)
    last = len(picks) + 1
    for r in rows:
        hit, _ = m.find(r['name'], team=r.get('team') or r.get('club'), cross_team='variant')
        r['_pick'], r['_drafted'] = (hit['pick'], 1) if hit else (last, 0)
        r['_team'] = hit['team'] if hit else None
    return last


# ------------------------------------------------------------------- statistics
def ranks(x):
    o = sorted(range(len(x)), key=lambda i: x[i])
    r = [0.0] * len(x)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and x[o[j + 1]] == x[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def corr(a, b):
    n = len(a)
    if n < 3: return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a)); sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return None if not sa or not sb else round(sum((x - ma) * (y - mb) for x, y in zip(a, b)) / sa / sb, 4)


def spearman(a, b): return corr(ranks(a), ranks(b))


def odds(p, y):
    n = len(p)
    if not n: return None
    base = sum(y) / n
    br = sum((q - t) ** 2 for q, t in zip(p, y)) / n
    b0 = sum((base - t) ** 2 for t in y) / n
    ll = -sum(t * math.log(min(max(q, .01), .99)) + (1 - t) * math.log(1 - min(max(q, .01), .99)) for q, t in zip(p, y)) / n
    return {'n': n, 'base': round(base, 4), 'brier': round(br, 5), 'logloss': round(ll, 4), 'skill': round(1 - br / b0, 4) if b0 else None}


def calib(p, y, bins=10):
    out = []
    for b in range(bins):
        s = [(q, t) for q, t in zip(p, y) if b / bins <= q < (b + 1) / bins or (b == bins - 1 and q == 1)]
        if s: out.append({'bin': f'{b / bins:.1f}-{(b + 1) / bins:.1f}', 'n': len(s), 'pred': round(sum(q for q, _ in s) / len(s), 3),
                          'actual': round(sum(t for _, t in s) / len(s), 3)})
    return out


def ppf(q):
    """inverse normal (Acklam's rational approximation)"""
    a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857]
    c = [-.00778489400243029, -.322396458041136, -2.40075827716184, -2.54973253934263, 4.37466414146497, 2.93816398269878]
    d = [.00778469570904146, .32246712907004, 2.445134137143, 3.75440866190742]
    if q < .02425:
        t = math.sqrt(-2 * math.log(q)); return (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1)
    if q > 1 - .02425:
        return -ppf(1 - q)
    t = q - .5; r = t * t
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * t / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def ols(X, y):
    """least squares by the normal equations (small k)"""
    k = len(X[0])
    A = [[sum(x[i] * x[j] for x in X) for j in range(k)] + [sum(x[i] * t for x, t in zip(X, y))] for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(A[r][i]))
        A[i], A[p] = A[p], A[i]
        if abs(A[i][i]) < 1e-12: return None
        for r in range(k):
            if r != i:
                f = A[r][i] / A[i][i]
                A[r] = [u - f * v for u, v in zip(A[r], A[i])]
    return [A[i][k] / A[i][i] for i in range(k)]


def on3_test(rows):
    s = [r for r in rows if r.get('on3') is not None and r.get('parts')]
    if len(s) < 30: return {'n': len(s), 'result': 'too few graded players'}
    m = sum(r['on3'] for r in s) / len(s); sd = math.sqrt(sum((r['on3'] - m) ** 2 for r in s) / len(s)) or 1
    rk = ranks([-r['_pick'] for r in s])
    y = [ppf((q - .5) / len(s)) for q in rk]
    X = [[1, (r['on3'] - m) / sd, r['parts'][1], sum(r['parts']) - r['parts'][0] - r['parts'][1]] for r in s]

    def ratio(ix):
        b = ols([X[i] for i in ix], [y[i] for i in ix])
        return b[1] / b[2] if b and b[2] > 0 else None
    full = ratio(range(len(s)))
    rnd = random.Random(2027)
    boots = sorted(v for v in (ratio([rnd.randrange(len(s)) for _ in s]) for _ in range(2000)) if v is not None)
    lo, hi = boots[int(.05 * len(boots))], boots[int(.95 * len(boots)) - 1]
    move = not (lo <= 1.0 <= hi)
    r = (1 + full) / 2 if move and full is not None else 1.0
    return {'n': len(s), 'ratio': round(full, 3) if full is not None else None, 'ci90': [round(lo, 3), round(hi, 3)],
            'verdict': 'change' if move else 'keep .40',
            'newOn3': round(.8 * r / (1 + r), 3), 'newProd': round(.8 / (1 + r), 3)}


def mock_score(picks, by_name, last, n1):
    rows = [p for p in picks if p[2] in by_name]
    r1 = [p for p in rows if p[0] <= n1]
    act = {n: by_name[n] for n in by_name}
    hits = sum(1 for p in r1 if act[p[2]]['_drafted'] and act[p[2]]['_pick'] <= n1)
    exact = sum(1 for p in r1 if act[p[2]]['_pick'] == p[0] and act[p[2]]['_team'] == p[1])
    mae = sum(abs(min(act[p[2]]['_pick'], last) - p[0]) for p in r1) / len(r1) if r1 else None
    xp = [p for p in rows if p[5]]
    return {'r1Hits': hits, 'exact': exact, 'r1MAE': round(mae, 2) if mae is not None else None,
            'xPickMAE': round(sum(abs(act[p[2]]['_pick'] - p[5]) for p in xp) / len(xp), 2) if xp else None,
            '_err': {p[2]: abs(min(act[p[2]]['_pick'], last) - p[0]) for p in r1}}


def sign_test(a, b):
    """blended vs predictive |error| on the players both mocked in round 1: two-sided sign test p"""
    w = sum(1 for k in a if k in b and a[k] < b[k]); l = sum(1 for k in a if k in b and a[k] > b[k])
    n = w + l
    if not n: return {'blendBetter': 0, 'predBetter': 0, 'p': None}
    tail = sum(math.comb(n, i) for i in range(0, min(w, l) + 1)) / 2 ** n
    return {'blendBetter': w, 'predBetter': l, 'p': round(min(1, 2 * tail), 4)}


def score(sport, draft_file=None):
    cls = int(SCORE_AFTER[sport][:4])
    folder = os.path.join(STORE, sport, str(cls))
    files = sorted(f for f in os.listdir(folder) if f.endswith('.json.gz'))
    if draft_file:
        picks = [{'name': n, 'pick': p, 'team': None, 'school': None} for n, p in json.load(open(draft_file))]
        day1 = '9999-12-31'
    else:
        if dt.date.today().isoformat() < SCORE_AFTER[sport]:
            sys.exit(f'{sport}: the {cls} draft has not happened; score after {SCORE_AFTER[sport]}')
        picks = draft(sport, cls)
        day1 = {'cfb': '2027-04-22', 'cbb': '2027-06-23', 'hockey': '2027-06-25'}[sport]
    if not picks: sys.exit('no draft picks found')
    snaps = [f for f in files if f[:10] < day1]
    final = snaps[-1]
    fall = next((f for f in snaps if f[:10] >= FALL), snaps[0])
    n1 = {'cfb': 32, 'cbb': 30, 'hockey': 32}[sport]
    curve, at = [], {}
    for f in snaps:
        s = json.load(gzip.open(os.path.join(folder, f)))
        rows = [dict(zip(s['cols'], r)) for r in s['rows']]
        last = attach(rows, picks, sport)
        by = {r['name']: r for r in rows}
        pk = [-r['_pick'] for r in rows]
        pcol = {'cfb': 'draftP', 'cbb': 'nbaP', 'hockey': 'p30'}[sport]
        pr = [(r[pcol], r['_drafted']) for r in rows if r.get(pcol) is not None]
        e = {'date': f[:10], 'n': len(rows), 'drafted': sum(r['_drafted'] for r in rows),
             'rhoFV': spearman([r['fvx'] or 0 for r in rows], pk), 'odds': odds([p for p, _ in pr], [t for _, t in pr])}
        if sport == 'hockey':
            e['rhoXslot'] = spearman([-(r['xslot'] or 999) for r in rows], pk)
        ms = {k: mock_score(v, by, last, n1) for k, v in s['mocks'].items()}
        if 'blend' in ms and 'pred' in ms:
            e['blendVsPred'] = sign_test(ms['blend']['_err'], ms['pred']['_err'])
        e['mocks'] = {k: {a: b for a, b in v.items() if a != '_err'} for k, v in ms.items()}
        if f in (final, fall):
            at[f] = (rows, pr)
        curve.append(e)
    out = {'sport': sport, 'class': cls, 'prereg': 'scripts/draft_ledger.py docstring (2026-10-25)', 'picks': len(picks),
           'final': final[:10], 'fall': fall[:10], 'curve': curve,
           'calibFinal': calib([p for p, _ in at[final][1]], [t for _, t in at[final][1]])}
    # pass / fail as registered
    fin = next(c for c in curve if c['date'] == final[:10]); fl = next(c for c in curve if c['date'] == fall[:10])
    out['oddsPass'] = bool(fin['odds'] and fin['odds']['skill'] and fin['odds']['skill'] > 0)
    out['fallCurvePass'] = bool(fl['odds'] and fl['odds']['skill'] and fl['odds']['skill'] > 0)
    bv = fl.get('blendVsPred')
    if bv:
        out['marketWeight'] = ('cut by half' if bv['predBetter'] > bv['blendBetter'] and bv['p'] is not None and bv['p'] < .10
                               else 'keep or raise')
    if sport == 'cfb':
        out['on3'] = {'final': on3_test(at[final][0]), 'fall': on3_test(at[fall][0])}
    p = os.path.join(ROOT, 'data', f'draft_ledger_{sport}_{cls}' + ('_dryrun' if draft_file else '') + '.json')
    with open(p, 'w') as f:
        json.dump(out, f, indent=1, allow_nan=False)
    print(json.dumps({k: v for k, v in out.items() if k not in ('curve', 'calibFinal')}, indent=1))
    print('->', os.path.relpath(p, ROOT))


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] not in ('snap', 'score') or sys.argv[2] not in SCORE_AFTER:
        sys.exit(__doc__)
    if sys.argv[1] == 'snap':
        snap(sys.argv[2])
    else:
        score(sys.argv[2], sys.argv[sys.argv.index('--draft') + 1] if '--draft' in sys.argv else None)
