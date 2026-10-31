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


def fv_of(board, x, fv=None):
    """the whole-number headline for an exact mean x; fv (the board's own rounding) is kept below the knot"""
    if x is None: return fv
    s = scale().get(board)
    if s is None or x <= s['K']: return int(round(x)) if fv is None else fv
    return int(round(show(board, x)))


# ---- fit ------------------------------------------------------------------------------------------------------------

def tail_bands(bands, seasons):
    """K, mean excess and T from 5-point bands [(lo, n, mean)], the last band open-ended; counts per season"""
    bands = sorted(bands); N, tot = {}, 0
    for lo, n, _ in reversed(bands): tot += n; N[lo] = tot / seasons
    los = sorted(N); K = None
    for a, b in zip(los, los[1:]):
        if N[a] >= PER_K > N[b]: K = a + 5 * math.log(N[a] / PER_K) / math.log(N[a] / N[b])
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
    v = sorted((x for x in vals if x is not None), reverse=True); k = int(round(PER_K * seasons))
    K = v[k - 1]; th = sum(x - K for x in v[:k]) / k
    return K, th, K + th * math.log(PER_K / PER_T)


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
    # the mean of a capped outcome tops out where a sure grade-80 player sits; T can't sit above that
    reach = {'cfb': fv_dist('cfb', 80, None)['mean'], 'cbb': fv_dist('cbb', 80, None)['mean']}
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


def restate_obj(o, board, skip=(), keep=False):
    """every player-like dict under o (one with a name): fv from its fvx (the exact mean), fv0 / fvNow from their own
    value. keep: a row without fvx gets one (the mean it had), so a rerun is a no-op and a refit reads the mean (the
    past lists); without it (files rebuilt from the board on their next run) run --restate once. Returns the count
    changed."""
    n = 0
    if isinstance(o, list):
        for v in o: n += restate_obj(v, board, skip, keep)
    elif isinstance(o, dict):
        if ('name' in o or 'n' in o) and isinstance(o.get('fv'), (int, float)) and not isinstance(o.get('fv'), bool):
            x = o['fv'] if o.get('fvx') is None else o['fvx']
            if keep and o.get('fvx') is None: o['fvx'] = x
            new = fv_of(board, x, o['fv']) if isinstance(o['fv'], int) else round(show(board, x), 1)
            n += new != o['fv']; o['fv'] = new
            for k in FV_KEYS[1:]:
                if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool):
                    x = o.get(k + 'x', o[k])
                    if keep: o[k + 'x'] = x
                    o[k] = fv_of(board, x, o[k]) if isinstance(o[k], int) else round(show(board, x), 1)
        for k, v in o.items():
            if k not in skip and isinstance(v, (list, dict)): n += restate_obj(v, board, skip, keep)
    return n


def restate_cols(A, board):
    ci = {c: i for i, c in enumerate(A['cols'])}; n = 0
    for r in A['rows']:
        x, f = r[ci['fvx']], r[ci['fv']]
        if x is None or f is None: continue
        new = fv_of(board, x, f); n += new != f; r[ci['fv']] = new
    return n


def restate():
    P = lambda *p: os.path.join(ROOT, *p)
    def rw(path, fn, compact=False):
        if not os.path.exists(path): return
        raw = open(path, encoding='utf-8').read(); A = json.loads(raw)
        # write it back the way it was written (indent, separators, ascii), so the diff is only the changed grades
        forms = [dict(indent=i, separators=sp, ensure_ascii=e) for i in (None, 1, 2) for sp in ((',', ':'), (', ', ': '), (',', ': '))
                 for e in (False, True)]
        form = next((f for f in forms if json.dumps(A, **f) == raw.rstrip('\n')), dict(indent=None if compact else 1,
                    separators=(',', ':') if compact else (',', ': '), ensure_ascii=False))
        n = fn(A)
        if not n: print(f'{os.path.relpath(path, ROOT)}: 0 changed'); return
        open(path, 'w', encoding='utf-8').write(json.dumps(A, **form) + ('\n' if raw.endswith('\n') else ''))
        print(f'{os.path.relpath(path, ROOT)}: {n} changed')
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
                new = fv_of('cfb', r[4], r[1]); n += new != r[1]; r[1] = new
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
    if '--report' in sys.argv:
        r = report()
        if '--json' in sys.argv: json.dump(r, open(os.path.join(ROOT, 'data', 'fv_scale_report.json'), 'w'), indent=1)
