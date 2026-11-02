"""The headline FV's top end (Noah, Oct 31 2026: "80 actually attainable, albeit extremely rare", on every board).

The headline is the mean of a player's outcome odds on a 20-80 outcome scale, so it can only reach 80 when every
outcome is an 80: no board had ever shown one (soccer topped out at 72, basketball at 57). This keeps the mean below
each board's knot K and stretches the top above it, so the mean that the board reaches about once every five
seasons shows as 80:

    FV = mean                                     mean <= K
    FV = K + (mean - K) x (80 - K) / (T - K)      mean >  K (80 at T and above)

K = the mean about three players a season reach on that board; T = the mean one player reaches about once every
five seasons, from an exponential tail fit to the held-out means above K (T = K + mean excess x ln 15). Each board
has its own K and T, from its own history (no shared cross-sport scale). The order never changes (the map is
increasing), fvx stays the exact mean on every row, and the outcome odds and the range stay on the outcome scale.
Below K nothing moves.

    python3 scripts/fv_scale.py --fit       refit K and T from the boards' held-out tables -> data/fv_scale.json
    python3 scripts/fv_scale.py --restate   rewrite fv from fvx in the current board files (after a --fit)
    python3 scripts/fv_scale.py --report    who would have shown 80 (and 75+) on past boards

Writers call fv_of(board, mean, fv) for the whole-number headline; scripts/fv_scale.mjs mirrors it for Node.
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE = os.path.join(ROOT, 'data', 'fv_scale.json')
PER_K, PER_T = 3.0, 0.2          # players a season at K; seasons per 80 = 1 / PER_T
_S = None


def scale():
    global _S
    if _S is None:
        try: _S = json.load(open(FILE))['boards']
        except (OSError, ValueError, KeyError): _S = {}
    return _S


def show(board, x):
    """the headline on the stretched scale, with decimals"""
    s = scale().get(board)
    if x is None or s is None or x <= s['K']: return x
    return min(80.0, s['K'] + (x - s['K']) * (80.0 - s['K']) / (s['T'] - s['K']))


def rnd(x, d=0):
    """round half up, as JavaScript's Math.round (Python's round() goes half to even: 49.5 -> 49, Node's 50)"""
    m = 10 ** d
    return int(math.floor(x + 0.5)) if not d else math.floor(x * m + 0.5) / m


def fv_of(board, x, fv=None):
    """the whole-number headline for an exact mean x; fv (the board's own rounding) is kept below the knot"""
    if x is None: return fv
    s = scale().get(board)
    if s is None or x <= s['K']: return rnd(x) if fv is None else fv
    return rnd(show(board, x))


# ---- fit ------------------------------------------------------------------------------------------------------------

def tail_bands(bands, seasons):
    """K, mean excess and T from 5-point bands [(lo, n, mean)], the last band open-ended; counts per season"""
    bands = sorted(bands); N, tot = {}, 0
    for lo, n, _ in reversed(bands): tot += n; N[lo] = tot / seasons
    los = sorted(N); K = None
    for a, b in zip(los, los[1:]):
        if N[a] >= PER_K > N[b]: K = a + (b - a) * math.log(N[a] / PER_K) / math.log(N[a] / N[b])
    lo, n, m = bands[-1]
    if K is None: K = lo + (m - lo) * math.log(N[lo] / PER_K)   # inside the open top band (exponential)
    ex = cnt = 0.0
    for i, (lo, n, m) in enumerate(bands):
        if i == len(bands) - 1:
            if K <= lo: ex += n * (m - K); cnt += n
            else: th = m - lo; f = math.exp(-(K - lo) / th); ex += n * f * th; cnt += n * f
        elif lo >= K: ex += n * (m - K); cnt += n
        elif lo + 5 > K: f = (lo + 5 - K) / 5; ex += n * f * (lo + 5 - K) / 2; cnt += n * f
    th = ex / cnt
    return K, th, K + th * math.log(PER_K / PER_T)


def tail_values(vals, seasons):
    """K = the k-th highest mean (k = PER_K a season); the tail's mean excess from the k - 1 above it (the k-th's own
    excess is 0 by construction, so counting it biased the excess low by (k - 1) / k)"""
    v = sorted((x for x in vals if x is not None), reverse=True); k = int(round(PER_K * seasons))
    K = v[k - 1]; th = sum(x - K for x in v[:k - 1]) / (k - 1)
    return K, th, K + th * math.log(PER_K / PER_T)


def cfb_groups():
    """every spread group scripts/fv_dist.mjs cfbZ gives a recruited player (years on campus 1-6, his last season or
    not, on a consensus draft board or not; the fit's kept terms). Walk-ons (no 247 record) are left out: their reach
    (73.5 for an underclassman on a draft board) would set the whole board's top for a type that never grades there."""
    out = {}
    for y in range(1, 7):
        for last_cls in (False, True):
            for cons in (0, 1):
                last = y >= 4 or last_cls
                z = {'under': float(y <= 2.5), 'early': 0.0 if last else 0.5 if cons and y >= 3 else 1.0,
                     'walkon': 0.0, 'cons': float(cons)}
                out[tuple(sorted(z.items()))] = z
    return list(out.values())


def fit():
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from fv_dist import fv_dist
    J = lambda *p: json.load(open(os.path.join(ROOT, *p)))
    D = J('data', 'fv_dist.json'); H = J('data', 'hockey.json'); S = J('data', 'soccer_prospects.json')
    T = J('data', 'tennis_prospects_fit.json')
    band = lambda bs, lo, n, m: [(b[lo], b[n], b[m]) for b in bs]
    src = {
        'cfb': (tail_bands(band(D['cfb']['scorecard']['bands'], 'lo', 'n', 'pred'), 4), 4,
                'held-out FBS player-seasons 2019-22 (data/fv_dist.json cfb scorecard)'),
        'cbb': (tail_bands(band(D['cbb']['scorecard']['bands'], 'lo', 'n', 'pred'), 7), 7,
                'held-out top 300 of the 2009-10 to 2015-16 preseason boards (data/fv_dist.json cbb scorecard)'),
        'hockey': (tail_values([r.get('fvx', r['fv']) for r in H['past']], 12), 12,
                   'the 2008-19 draft classes as graded on the board (data/hockey.json past)'),
        'soccer': (tail_bands(band(S['fit']['calib'], 'band', 'n', 'pred'), 8), 8,
                   'held-out prospect seasons 2013-20 (data/soccer_prospects.json fit calib)'),
        'atp': (tail_bands(band(T['atp']['scorecard']['bands'], 'lo', 'n', 'pred'), 19), 19,
                'held-out October grades, players born 1979-97: 19 seasons of pools (data/tennis_prospects_fit.json)'),
        'wta': (tail_bands(band(T['wta']['scorecard']['bands'], 'lo', 'n', 'pred'), 19), 19,
                'held-out October grades, players born 1979-97: 19 seasons of pools (data/tennis_prospects_fit.json)'),
    }
    # the mean of a capped outcome tops out where a sure grade-80 player sits; T can't sit above that. CFB (Noah, Nov 2
    # 2026): at the widest-spread group's reach, so every player type can show 80 (a spread-neutral cap, 76.8, left
    # early underclassmen topping out at 77-78)
    reach = {'cfb': min(fv_dist('cfb', 80, z)['mean'] for z in cfb_groups()), 'cbb': fv_dist('cbb', 80, None)['mean']}
    out = {}
    for b, ((K, th, Tb), n, note) in src.items():
        cap = reach.get(b, 80.0) - 0.0
        out[b] = {'K': round(K, 2), 'T': round(min(Tb, cap), 2), 'tail': round(th, 2), 'tailT': round(Tb, 2),
                  'reach': round(cap, 2), 'seasons': n, 'src': note}
    json.dump({'asof': __import__('time').strftime('%Y-%m-%d'), 'method': 'scripts/fv_scale.py --fit',
               'rule': f'FV = mean up to K ({PER_K:g} a season); linear above to 80 at T (one a season x {PER_T:g}), capped at the board\'s reach',
               'boards': out}, open(FILE, 'w'), indent=1)
    for b, s in out.items(): print(b, s)


# ---- restate the current files --------------------------------------------------------------------------------------

FV_KEYS = ('fv', 'fv0', 'fvNow')


def restated(board, x, cur):
    """the headline for a stored mean x, given the headline cur the row shows now. x is stored rounded (2 decimals,
    some 1), while the writers stretch the unrounded mean, so where x's rounding interval straddles a whole number on
    the stretched scale (the steep CBB top: 0.005 of mean is 0.02 shown) cur, already one of the two, is kept: a
    restate never re-rounds a writer's exact headline, and a second restate changes nothing."""
    if isinstance(cur, bool) or not isinstance(cur, (int, float)): return cur
    h = 0.05 if abs(x * 10 - round(x * 10)) < 1e-9 else 0.005
    if isinstance(cur, int):
        new = fv_of(board, x, cur)
        return cur if fv_of(board, x - h, cur) <= cur <= fv_of(board, x + h, cur) else new
    new = rnd(show(board, x), 1)
    return cur if rnd(show(board, x - h), 1) <= cur <= rnd(show(board, x + h), 1) else new


def restate_obj(o, board, skip=(), keep=False):
    """every player-like dict under o (one with a name): fv from its fvx (the exact mean), fv0 / fvNow from fv0x /
    fvNowx. A row without its exact mean is left alone: its fv is already on the stretched scale (fv_scale.mjs
    fvReplacer and the Python writers put the mean beside it since Nov 2 2026; older files get it on their next build),
    and stretching a shown value again would push it up a second time. keep (the past lists, written on the mean before
    the stretch): a row without the exact mean takes its value as the mean, once, and keeps it beside. Returns the count
    changed."""
    n = 0
    if isinstance(o, list):
        for v in o: n += restate_obj(v, board, skip, keep)
    elif isinstance(o, dict):
        if ('name' in o or 'n' in o) and isinstance(o.get('fv'), (int, float)) and not isinstance(o.get('fv'), bool):
            for k in FV_KEYS:
                v = o.get(k)
                if isinstance(v, bool) or not isinstance(v, (int, float)): continue
                x = o.get(k + 'x')
                if not isinstance(x, (int, float)) or isinstance(x, bool):
                    if not keep: continue
                    x = o[k + 'x'] = v
                    new = fv_of(board, x, v) if isinstance(v, int) else rnd(show(board, x), 1)
                else:
                    new = restated(board, x, v)
                n += new != v; o[k] = new
        for k, v in o.items():
            if k not in skip and isinstance(v, (list, dict)): n += restate_obj(v, board, skip, keep)
    return n


def restate_cols(A, board):
    ci = {c: i for i, c in enumerate(A['cols'])}; n = 0
    for r in A['rows']:
        x, f = r[ci['fvx']], r[ci['fv']]
        if x is None or f is None: continue
        new = restated(board, x, f); n += new != f; r[ci['fv']] = new
    return n


def restate(root=ROOT, quiet=False):
    P = lambda *p: os.path.join(root, *p); out = {}
    def rw(path, fn, compact=False):
        if not os.path.exists(path): return
        raw = open(path, encoding='utf-8').read(); A = json.loads(raw)
        # write it back the way it was written (indent, separators, ascii), so the diff is only the changed grades
        forms = [dict(indent=i, separators=sp, ensure_ascii=e) for i in (None, 1, 2) for sp in ((',', ':'), (', ', ': '), (',', ': '))
                 for e in (False, True)]
        form = next((f for f in forms if json.dumps(A, **f) == raw.rstrip('\n')), dict(indent=None if compact else 1,
                    separators=(',', ':') if compact else (',', ': '), ensure_ascii=False))
        n = fn(A)
        out[os.path.relpath(path, root)] = n
        if not quiet: print(f'{os.path.relpath(path, root)}: {n} changed')
        if not n: return
        open(path, 'w', encoding='utf-8').write(json.dumps(A, **form) + ('\n' if raw.endswith('\n') else ''))
    # football: the board, its files, and the files built from it (rebuilt from the raw board on the next run)
    for f in ('cfb.json', 'cfb_games.json', 'cfb_mock.json', 'cfb_mock_conv.json', 'cfb_mock_pred.json', 'cfb_portal.json',
              'cfb_proj.json', 'cfb_teams.json', 'cfb_breakout.json', 'cfb_top.json', 'backup_cfb.json'):
        rw(P('data', f), lambda A: restate_obj(A, 'cfb'))
    rw(P('static', 'data', 'cfb-builder.json'), lambda A: restate_obj(A, 'cfb'), compact=True)
    rw(P('static', 'data', 'cfb-all.json'), lambda A: restate_cols(A, 'cfb'), compact=True)
    def cfb_past(A):   # {key: [[season, fv, pos, team], ...]}: fv only, the mean rounded
        n = 0
        for rows in A['players'].values():
            for r in rows:
                if len(r) < 5: r.append(r[1])          # the mean, kept so a rerun is a no-op
                new = restated('cfb', r[4], r[1]); n += new != r[1]; r[1] = new
        if 'fvx' not in A['cols']: A['cols'].append('fvx')
        return n
    rw(P('static', 'data', 'cfb-past.json'), cfb_past, compact=True)
    # basketball
    for f in ('cbb-all.json', 'cbb-past.json', 'cbb-intl.json'):
        rw(P('static', 'data', f), lambda A: restate_cols(A, 'cbb'), compact=True)
    rw(P('data', 'cbb.json'), lambda A: restate_obj(A, 'cbb', skip=('fvTable',)))
    rw(P('data', 'cbb_recruits.json'), lambda A: restate_obj(A['classes'], 'cbb'))
    for f in ('cbb_mock.json', 'backup_cbb.json'): rw(P('data', f), lambda A: restate_obj(A, 'cbb'))
    # hockey, soccer, tennis
    rw(P('data', 'hockey.json'), lambda A: sum(restate_obj(A[k], 'hockey', keep=k == 'past') for k in ('board', 'pipe', 'past', 'prov') if k in A))
    rw(P('data', 'hockey_mock.json'), lambda A: restate_obj(A, 'hockey'))
    rw(P('data', 'soccer_prospects.json'), lambda A: restate_obj(A['board'], 'soccer') + restate_obj(A['past'], 'soccer', keep=True))
    rw(P('data', 'tennis_prospects.json'), lambda A: sum(restate_obj(A[t]['board'], t) for t in ('atp', 'wta')))
    rw(P('data', 'tennis_prospects_fit.json'), lambda A: sum(restate_obj(A[t]['past'], t, keep=True) for t in ('atp', 'wta')))
    return out


def test():
    """python3 scripts/fv_scale.py --test: restating twice is restating once (on copies of the current files, and on
    rows that carry no exact mean), and the rounding is JavaScript's half up"""
    import shutil, tempfile
    assert rnd(49.5) == 50 and rnd(48.5) == 49 and rnd(-0.5) == 0 and rnd(72.25, 1) == 72.3
    K = scale()['cfb']['K']
    row = {'name': 'a', 'fv': fv_of('cfb', K + 6), 'fv0': fv_of('cfb', K + 5)}          # shown values, no exact mean
    before = dict(row); restate_obj(row, 'cfb'); assert row == before, row
    row = {'name': 'b', 'fv': 0, 'fvx': K + 6.123, 'fv0': 0, 'fv0x': K + 4.2}
    restate_obj(row, 'cfb'); once = dict(row); restate_obj(row, 'cfb'); assert row == once and row['fv'] == fv_of('cfb', K + 6.123)
    files = [('data', f) for f in ('cfb.json', 'cfb_games.json', 'cfb_mock.json', 'cfb_mock_conv.json', 'cfb_mock_pred.json',
             'cfb_portal.json', 'cfb_proj.json', 'cfb_teams.json', 'cfb_breakout.json', 'cfb_top.json', 'backup_cfb.json',
             'cbb.json', 'cbb_recruits.json', 'cbb_mock.json', 'backup_cbb.json', 'hockey.json', 'hockey_mock.json',
             'soccer_prospects.json', 'tennis_prospects.json', 'tennis_prospects_fit.json', 'fv_scale.json')] + \
            [('static', 'data', f) for f in ('cfb-builder.json', 'cfb-all.json', 'cfb-past.json', 'cbb-all.json', 'cbb-past.json', 'cbb-intl.json')]
    tmp = tempfile.mkdtemp()
    try:
        for f in files:
            if os.path.exists(os.path.join(ROOT, *f)):
                os.makedirs(os.path.join(tmp, *f[:-1]), exist_ok=True); shutil.copy(os.path.join(ROOT, *f), os.path.join(tmp, *f))
        first = restate(tmp, quiet=True)
        snap = {f: open(os.path.join(tmp, *f), 'rb').read() for f in files if os.path.exists(os.path.join(tmp, *f))}
        second = restate(tmp, quiet=True)
        moved = {k: v for k, v in second.items() if v}
        assert not moved and all(open(os.path.join(tmp, *f), 'rb').read() == b for f, b in snap.items()), moved
        print('restate twice == restate once; first pass changed', {k: v for k, v in first.items() if v} or 'nothing')
    finally:
        shutil.rmtree(tmp)


# ---- report: who would have shown 80 --------------------------------------------------------------------------------

def report():
    J = lambda *p: json.load(open(os.path.join(ROOT, *p)))
    out = {}
    def top(board, rows, seasons, label):
        rows = [(n, s, x) for n, s, x in rows if x is not None]
        hi = sorted(rows, key=lambda r: -r[2])
        e80 = [f'{n} {s} ({x:.1f})' for n, s, x in hi if show(board, x) >= 79.5]
        e75 = sum(show(board, x) >= 74.5 for _, _, x in hi); e70 = sum(show(board, x) >= 69.5 for _, _, x in hi)
        best = [f'{n} {s}: {x:.1f} -> {fv_of(board, x)}' for n, s, x in hi[:6]]
        out[f'{board} {label}'] = {'seasons': seasons, '80': e80, 'n75': e75, 'n70': e70, 'top': best}
        print(f'\n{board} {label} ({seasons} seasons): 80s {len(e80)} {e80[:6]}  75+ {e75}  70+ {e70}\n   ' + '\n   '.join(best))
    p = J('static', 'data', 'cbb-past.json'); ci = {c: i for i, c in enumerate(p['cols'])}
    top('cbb', [(r[ci['name']], r[0], r[ci['fvx']]) for r in p['rows']], len({r[0] for r in p['rows']}), 'past boards 2010-26')
    a = J('static', 'data', 'cbb-all.json'); ci = {c: i for i, c in enumerate(a['cols'])}
    top('cbb', [(r[ci['name']], 'now', r[ci['fvx']]) for r in a['rows']], 1, 'live board')
    a = J('static', 'data', 'cfb-all.json'); ci = {c: i for i, c in enumerate(a['cols'])}
    top('cfb', [(r[ci['name']], 'now', r[ci['fvx']]) for r in a['rows']], 1, 'live board')
    p = J('static', 'data', 'cfb-past.json')
    top('cfb', [(k.split('|')[0], r[0], r[4] if len(r) > 4 else r[1]) for k, v in p['players'].items() for r in v], 7,
        'past boards 2019-25 (players still in college only)')
    h = J('data', 'hockey.json')
    top('hockey', [(r['name'], r['year'], r.get('fvx', r['fv'])) for r in h['past']], 12, 'draft classes 2008-19')
    top('hockey', [(r['name'], 'board', r['fvx']) for r in h['board']] + [(r['name'], 'pipe', r['fvx']) for r in h['pipe']], 1, 'live board + pipeline')
    s = J('data', 'soccer_prospects.json')
    top('soccer', [(r['name'], r['season'], r.get('fvx', r['fv'])) for r in s['past']], 8, 'past seasons 2013-20 (listed players)')
    top('soccer', [(r['name'], 'now', r['fvx']) for r in s['board']], 1, 'live board')
    t = J('data', 'tennis_prospects.json'); tf = J('data', 'tennis_prospects_fit.json')
    for tour in ('atp', 'wta'):
        top(tour, [(r['name'], r['season'], r.get('fvx', r['fv'])) for r in tf[tour]['past']], 21, 'past (listed players)')
        top(tour, [(r['name'], 'now', r['fvx']) for r in t[tour]['board']], 1, 'live board')
    return out


if __name__ == '__main__':
    if '--fit' in sys.argv: fit()
    if '--restate' in sys.argv: restate()
    if '--test' in sys.argv: test()
    if '--report' in sys.argv:
        r = report()
        if '--json' in sys.argv: json.dump(r, open(os.path.join(ROOT, 'data', 'fv_scale_report.json'), 'w'), indent=1)
