#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""The 2027 NBA draft boards the College Basketball ARKBOARD reads (scripts/data/cbb_boards/), and the map from a
board rank on a given day to the June rank it predicts (audit item #23, Oct 25 2026).

    python3 scripts/cbb_boards.py --pull    # weekly (cbb-boards.yml): re-pull the live boards into scripts/data/cbb_boards/
    python3 scripts/cbb_boards.py --articles  # the one-off articles in ARTICLES (rerun after swapping in a newer URL)
    python3 scripts/cbb_boards.py --fit     # the dated rank -> June map and its backtest -> scripts/data/cbb_board_att.json
                                            # (needs the board history in /mnt/project-files/cbb/boards or $CBB_BOARDS)

Pull. Boards that change through the season, each kept only if the pull parses at least MIN_ROWS players (a failed or
empty pull keeps last week's file): Tankathon's big board and CBS (live pages), No Ceilings' newest 2027 composite
(Substack API), ESPN's core API (Givony/Woo; empty until ESPN fills its 2027 database near the draft) and NBADraft.net
(empty for 2027 so far). The one-off articles (Bleacher Report, SI, FanSided, ESPN's June mock) stay as pulled.

Fit. The board stage (cbb_fit.board_stage) is trained on June ranks: the mean -ln rank on ESPN's and NBADraft.net's final
boards. The live board only has today's boards, so a player's rank today is mapped to the June rank it predicts,
-ln June = a + b (-ln rank today) + e, e ~ N(0, sd). That map was fit once, on No Ceilings' first board each year
(Nov-Dec), and used all season. Tested on every dated No Ceilings version 2022-26 (36 boards before the draft), leave
one draft out, Gaussian log score of the held-out June ranks:
  - a, b and ln sd linear (and quadratic) in ln days to the draft, fit on all dates: better overall (t 5) but worse than
    the first-board map on the Nov-Feb boards, so before CUT days the live map stays;
  - from CUT days (late February) on, a late map (a, b fixed, ln sd linear in ln days, fit on the boards under CUT
    days): the spread narrows from about .73 at CUT to .40 in draft week. This is what ships (keep in cbb_board_att.json).
"""
import csv, datetime, html, json, math, os, re, subprocess, sys, time
from collections import defaultdict
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D

BOARDS = os.environ.get('CBB_BOARDS', '/mnt/project-files/cbb/boards')
LIVE_DIR = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_boards')
ATT = os.path.join(D.ROOT, 'scripts', 'data', 'cbb_board_att.json')
DRAFT = {2022: '2022-06-23', 2023: '2023-06-22', 2024: '2024-06-26', 2025: '2025-06-25', 2026: '2026-06-24',
         2027: '2027-06-24'}   # 2027: the NBA's usual last-Thursday-in-June slot, until the league sets it
YEAR = 2027
MIN_ROWS = 25
COLS = ['source', 'draft_year', 'board_date', 'rank', 'name', 'school', 'pos']
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


# who each board in scripts/data/cbb_boards is: file stem -> (analyst, outlet, kind). One board per analyst: the
# newest of his big board and his mock.
SOURCES = {
    'espn_woo': ('Jeremy Woo', 'ESPN', 'board'),
    'br_wasserman': ('Jonathan Wasserman', 'Bleacher Report', 'mock'),
    'floorandceiling': ('Wilko Martinez', 'Floor and Ceiling', 'board'),
    'noceilings': ('No Ceilings staff', 'No Ceilings', 'board'),
    'fansided': ('Christopher Kline', 'FanSided', 'board'),
    'clutchpoints': ('Bailey Bassett', 'ClutchPoints', 'mock'),
    'nbadraftnet': ('Aran Smith', 'NBADraft.net', 'mock'),
    'cbs': ('Kyle Boone', 'CBS Sports', 'board'),
    'tankathon': ('Tankathon', 'Tankathon', 'board'),
    'si': ('Kevin Sweeney', 'Sports Illustrated', 'board'),
    'espn': ('Givony / Woo', 'ESPN', 'board'),
}
# recency weight on each board: 0.5 ** (days older than the newest board / HALF_LIFE). Tested Nov 17 2026
# (scripts/research/cbb_consensus_nov17/recency.py): ESPN + NBADraft.net finals plus one older No Ceilings board,
# drafts 2022-26, real slot: mean |ln slot err| .3144 equal -> .3011 held out (t 8.0, 5/5 drafts); 7-30 days flat
# (.3007-.3008), 30 kept to leave stale independent boards some say. No Ceilings versions alone: .500 -> .423 (t 10, 4/5).
HALF_LIFE = 30.0


def live_boards():
    """the current boards in scripts/data/cbb_boards: [{src, date, rows [(name, school, pos, rank)], age, w}], age in
    days behind the newest board, w the recency weight."""
    out = []
    for f in sorted(x for x in os.listdir(LIVE_DIR) if x.endswith('.csv')) if os.path.isdir(LIVE_DIR) else []:
        with open(os.path.join(LIVE_DIR, f), newline='', encoding='utf-8') as fh:
            R = list(csv.DictReader(fh))
        if not R: continue
        d = R[0]['board_date'] if re.match(r'\d{4}-\d\d-\d\d$', R[0]['board_date'] or '') else None
        out.append({'src': f[:-4].replace(f'_{YEAR}', ''), 'date': d,
                    'rows': [(r['name'], r['school'], r['pos'], int(r['rank'])) for r in R]})
    dates = [b['date'] for b in out if b['date']]
    top = max(dates) if dates else None
    for b in out:
        b['age'] = (datetime.date.fromisoformat(top) - datetime.date.fromisoformat(b['date'])).days if b['date'] and top else 0
        b['w'] = 0.5 ** (b['age'] / HALF_LIFE)
    return out


def source_list(boards=None):
    """the boards as the site lists them, newest first"""
    out = []
    for b in boards if boards is not None else live_boards():
        a, o, k = SOURCES.get(b['src'], (b['src'], '', 'board'))
        out.append({'src': b['src'], 'analyst': a, 'outlet': o, 'kind': k, 'date': b['date'], 'n': len(b['rows']),
                    'w': round(b['w'], 3)})
    return sorted(out, key=lambda x: (x['date'] or '', x['n']), reverse=True)


def days_to_draft(date, year=YEAR):
    d = (datetime.date.fromisoformat(DRAFT[year]) - datetime.date.fromisoformat(date)).days
    return max(1, d)


# ---------------------------------------------------------------- the dated map
CUT = 120     # days to the draft (late February) where the late map takes over


def att_at(A, days):
    """a, b, sd of the map on a board `days` before the draft. A = cbb_board_att.json 'fit': a and b fixed, ln sd
    linear in ln days."""
    L = math.log(max(1, min(days, A['maxDays'])))
    return {'a': A['a'], 'b': A['b'], 'sd': math.exp(A['s'][0] + A['s'][1] * L)}


def live_att(C):
    """the map for today's boards: from CUT days out, the late map at the boards' median date (when
    cbb_board_att.json ships it); before that, and whenever the file or a date is missing, the board stage's own map
    (C = cbb_fit.json 'boards', fit on No Ceilings' first board)."""
    try:
        A = json.load(open(ATT))
        dates = []
        for f in os.listdir(LIVE_DIR):
            if f.endswith('.csv'):
                with open(os.path.join(LIVE_DIR, f), newline='', encoding='utf-8') as fh:
                    r = next(csv.DictReader(fh), None)
                if r and re.match(r'\d{4}-\d\d-\d\d$', r['board_date'] or ''): dates.append(r['board_date'])
        if not A.get('keep') or not dates: return C['att']
        days = days_to_draft(sorted(dates)[len(dates) // 2])
        return dict(att_at(A['fit'], days), days=days) if days < A['cut'] else C['att']
    except (OSError, ValueError, KeyError):
        return C['att']


def june_ranks():
    """the board stage's target (cbb_fit.june_ranks): -ln June consensus rank by (draft year, name key)."""
    import cbb_fit as F
    F.BOARDS = BOARDS
    return F.june_ranks()


def nc_versions():
    by = defaultdict(lambda: defaultdict(dict))
    with open(os.path.join(BOARDS, 'noceilings.csv'), newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            y = int(r['draft_year'])
            if y in DRAFT and y < YEAR: by[y][r['board_date']][D.norm(r['name'])] = int(r['rank'])
    return by


def rows():
    """one row per player on a dated No Ceilings board 2022-26: draft year, ln days to draft, -ln rank, -ln June rank."""
    jr = june_ranks()
    fill = -math.log(150)      # on neither June board (cbb_fit.CONS_FILL)
    out = []
    for y, vs in nc_versions().items():
        for date, b in vs.items():
            if date >= DRAFT[y]: continue          # the post-draft repost of the final board
            first = date == min(vs)
            for k, rk in b.items():
                out.append({'y': y, 'date': date, 'L': math.log(days_to_draft(date, y)), 'x': -math.log(rk),
                            'yj': jr.get((y, k), fill), 'first': first})
    return out


def fit_late(R, iters=8):
    """-ln June = a + b x by weighted least squares, ln sd = s0 + s1 ln days refit on the squared residuals."""
    L = np.array([r['L'] for r in R]); x = np.array([r['x'] for r in R]); y = np.array([r['yj'] for r in R])
    X = np.column_stack([np.ones(len(R)), x]); S = np.column_stack([np.ones(len(R)), L]); w = np.ones(len(R))
    for _ in range(iters):
        beta = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)[0]
        e2 = (y - X @ beta) ** 2
        s = np.linalg.lstsq(S, np.log(e2 + 1e-6) + 1.27, rcond=None)[0] / 2     # E ln chi2_1 = -1.27
        c = math.sqrt(float(np.mean(e2 / np.exp(S @ s) ** 2))); s[0] += math.log(c)
        w = 1 / np.exp(S @ s) ** 2
    return {'a': float(beta[0]), 'b': float(beta[1]), 's': [float(s[0]), float(s[1])], 'maxDays': float(math.exp(L.max()))}


def fit_const(R):
    """the board stage's map (cbb_fit.preseason_att) on these rows: one a, b, sd."""
    x = np.array([r['x'] for r in R]); y = np.array([r['yj'] for r in R])
    b, a = np.polyfit(x, y, 1)
    return {'a': float(a), 'b': float(b), 's': [math.log(float(np.std(y - a - b * x, ddof=2))), 0.0], 'maxDays': 400.0}


def score(A, R):
    ll, se = [], []
    for r in R:
        m = att_at(A, math.exp(r['L']))
        mu = m['a'] + m['b'] * r['x']
        ll.append(-0.5 * math.log(2 * math.pi * m['sd'] ** 2) - 0.5 * ((r['yj'] - mu) / m['sd']) ** 2)
        se.append((r['yj'] - mu) ** 2)
    return np.array(ll), np.array(se)


def backtest(R):
    """leave one draft out on the boards under CUT days: the late map vs the live map (first board, constant) and vs a
    constant fit on the same late rows."""
    late = [r for r in R if math.exp(r['L']) < CUT]
    years = sorted({r['y'] for r in R})
    res = defaultdict(list)
    for t in years:
        te = [r for r in late if r['y'] == t]
        for name, A in (('live', fit_const([r for r in R if r['y'] != t and r['first']])),
                        ('lateConst', fit_const([r for r in late if r['y'] != t])),
                        ('late', fit_late([r for r in late if r['y'] != t]))):
            res[name].append((t,) + score(A, te) + (te,))
    out = {'rows': len(late), 'cut': CUT}
    for name in res:
        ll = np.concatenate([x[1] for x in res[name]]); se = np.concatenate([x[2] for x in res[name]])
        out[name] = {'logScore': round(float(ll.mean()), 4), 'rmse': round(float(np.sqrt(se.mean())), 4),
                     'byDraft': {x[0]: round(float(x[1].mean()), 4) for x in res[name]}}
    for name in ('live', 'lateConst'):
        d = np.concatenate([b[1] - a[1] for a, b in zip(res[name], res['late'])])
        per = [float((b[1] - a[1]).mean()) for a, b in zip(res[name], res['late'])]
        out[f'late vs {name}'] = {'logGain': round(float(d.mean()), 4), 'tRow': round(float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))), 2),
                                  'draftsBetter': int(sum(p > 0 for p in per)), 'of': len(per)}
    out['byWindow'] = []
    for lab, lo, hi in (('Mar-Apr', 60, CUT), ('May-Jun', 0, 60)):
        row = {'window': lab}
        for name in res:
            ll = np.concatenate([x[1][[lo <= math.exp(r['L']) < hi for r in x[3]]] for x in res[name]])
            row[name] = {'n': int(len(ll)), 'logScore': round(float(ll.mean()), 4) if len(ll) else None}
        out['byWindow'].append(row)
    # before CUT the live map stays: the dated alternatives tested there lost Nov-Feb (see the module notes)
    return out


def main_fit():
    R = rows()
    print(len(R), 'board rows,', len({(r['y'], r['date']) for r in R}), 'dated No Ceilings boards')
    bt = backtest(R)
    for k, v in bt.items():
        if k != 'byWindow': print(k, v)
    for w in bt['byWindow']: print('  ', w)
    A = fit_late([r for r in R if math.exp(r['L']) < CUT])
    g = bt['late vs live']
    keep = g['logGain'] > 0 and g['tRow'] >= 2 and g['draftsBetter'] >= 3
    curve = [{'days': d, **{k: round(v, 4) for k, v in att_at(A, d).items()}} for d in (119, 90, 60, 30, 14, 3)]
    print('kept' if keep else 'not kept', curve)
    json.dump({'asof': time.strftime('%Y-%m-%d'), 'keep': bool(keep), 'cut': CUT,
               'target': 'mean -ln rank on ESPN + NBADraft.net final boards (cbb_fit.june_ranks)',
               'boards': 'No Ceilings composites 2022-26, every dated version before the draft', 'rows': len(R),
               'fit': {k: ([round(x, 6) for x in v] if isinstance(v, list) else round(v, 6)) for k, v in A.items()},
               'curve': curve, 'backtest': bt, 'draft': DRAFT}, open(ATT, 'w'), indent=1)
    print('wrote', ATT)


# ---------------------------------------------------------------- pulls
def curl(url, tries=3):
    for i in range(tries):
        r = subprocess.run(['curl', '-sL', '-m', '60', '-A', UA, url], capture_output=True)
        if r.returncode == 0 and r.stdout: return r.stdout.decode('utf-8', 'replace')
        time.sleep(2 * (i + 1))
    return ''


def consecutive(rows):
    """the first run of ranks 1, 2, 3, ... (drops side lists)"""
    out = []
    for r in rows:
        if r[0] == len(out) + 1: out.append(r)
    return out


def pull_tankathon():
    h = curl('https://www.tankathon.com/big-board')
    seg = h[h.find('id="big-board"'):]
    rows = []
    for rk, nm, sp in re.findall(r'<div class="mock-row-pick-number">(\d+)</div>.*?<div class="mock-row-name">(.*?)</div>'
                                 r'<div class="mock-row-school-position">(.*?)</div>', seg, flags=re.S):
        pos, _, school = html.unescape(re.sub(r'<[^>]+>', '', sp)).partition('|')
        rows.append((int(rk), html.unescape(nm).strip(), school.strip(), pos.strip()))
    return 'tankathon', time.strftime('%Y-%m-%d'), consecutive(rows)


def pull_cbs():
    h = curl('https://www.cbssports.com/nba/draft/prospect-rankings/')
    t = h[h.find('table-base-nba-prospect-rankings'):]
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, flags=re.S):
        c = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', x))).strip() for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S)]
        if len(c) >= 5 and c[0].isdigit() and re.search(r'[A-Za-z]{2}', c[1]): rows.append((int(c[0]), c[1], c[2], c[4]))   # skip stat lines
    return 'cbs', time.strftime('%Y-%m-%d'), consecutive(rows)


def substack_posts(api, q):
    """a Substack archive search. Since Nov 2026 the API refuses limit/offset and wraps the list in {'posts': [...]}"""
    try: j = json.loads(curl(f'{api}/archive?sort=new&search={q}') or '[]')
    except ValueError: return []
    return j.get('posts', []) if isinstance(j, dict) else j


def pull_floorandceiling():
    """Wilko Martinez's newest 2027 big board (Floor and Ceiling, Substack; the free part runs '1. Name' then
    'POS | SCHOOL | BIRTHDAY | COUNTRY')."""
    api = 'https://floorandceiling.substack.com/api/v1'
    posts = sorted((p for p in substack_posts(api, f'{YEAR}%20big%20board') if re.match(rf'^{YEAR}-nba-draft-big-board', p.get('slug', ''))),
                   key=lambda p: p['post_date'])
    if not posts: return 'floorandceiling', None, []
    p = posts[-1]
    try: body = json.loads(curl(f"{api}/posts/{p['slug']}") or '{}').get('body_html') or ''
    except ValueError: body = ''
    L = _nc_lines(body)
    out = []
    for i, l in enumerate(L[:-1]):
        m = re.match(r"^(\d{1,3})\.\s+([A-Za-zÀ-ɏ'’][^|]{1,40})$", l)
        parts = [x.strip() for x in L[i + 1].split('|')]
        if m and len(parts) >= 3:
            sch = parts[1] if len(parts[1]) <= 4 else re.sub(r"(?<=['’])S\b", 's', parts[1].title())   # BYU, UCONN stay caps
            out.append((int(m.group(1)), m.group(2).strip(), sch, parts[0].title()))
    return 'floorandceiling', p['post_date'][:10], consecutive(sorted(out))


def _nc_lines(body):
    t = re.sub(r'<(?!/?(?:a|span|strong|em|b|i)\b)[^>]+>', '\n', body)
    t = html.unescape(re.sub(r'<[^>]+>', '', t)).replace('\xa0', ' ')
    return [re.sub(r'\s+', ' ', l).strip() for l in t.split('\n') if l.strip()]


def pull_noceilings():
    """the newest 2027 No Ceilings composite ('#N. Name | POS | School', their 2025+ layout)."""
    api = 'https://www.noceilingsnba.com/api/v1'
    arr = substack_posts(api, 'big%20board')
    posts = sorted((p for p in arr if re.match(rf'^{YEAR}-nba-draft-big-board(-v\d+)?$', p.get('slug', ''))), key=lambda p: p['post_date'])
    if not posts: return 'noceilings', None, []
    p = posts[-1]
    try: body = json.loads(curl(f"{api}/posts/{p['slug']}") or '{}').get('body_html') or ''
    except ValueError: body = ''
    out, seen = [], set()
    for l in _nc_lines(body):
        m = re.match(r"^#?\s*(\d{1,3})\s*\.\s+([A-Za-zÀ-ɏ'][^|]*?)\s*\|\s*(.*)$", l)
        if not m or re.search(r'PTS|REB|AST|FG%|PPG', l): continue
        rk, name = int(m.group(1)), m.group(2).strip()
        parts = [x.strip() for x in m.group(3).split('|')]
        if rk in seen or len(name) > 40: continue
        seen.add(rk)
        out.append((rk, name, parts[-1], parts[0] if len(parts) >= 2 else ''))
    return 'noceilings', p['post_date'][:10], consecutive(sorted(out))


def pull_espn():
    """ESPN's core API: each athlete's 'overall' attribute is the Givony/Woo big-board rank."""
    base = f'https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/seasons/{YEAR}/draft/athletes?limit=500'
    try: items = json.loads(curl(base) or '{}').get('items') or []
    except ValueError: items = []
    rows, colleges = [], {}
    for it in items[:300]:
        try: a = json.loads(curl(it['$ref'].replace('http://', 'https://')) or '{}')
        except ValueError: continue
        rk = next((int(x['value']) for x in a.get('attributes', []) if x.get('name') == 'overall'), None)
        if not rk: continue
        school = ''
        cref = (a.get('college') or {}).get('$ref')
        if cref:
            if cref not in colleges:
                try: c = json.loads(curl(cref.replace('http://', 'https://')) or '{}')
                except ValueError: c = {}
                colleges[cref] = c.get('name') or c.get('shortName') or ''
            school = colleges[cref]
        rows.append((rk, ' '.join((a.get('displayName') or '').split()), school, (a.get('position') or {}).get('abbreviation', '')))
    return 'espn', time.strftime('%Y-%m-%d'), consecutive(sorted(rows))


def pull_nbadraftnet():
    h = curl(f'https://www.nbadraft.net/ranking/bigboard/?year-ranking={YEAR}')
    strip = lambda s: html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'</span><span>', ' ', re.sub(r'<noscript>.*?</noscript>', '', s, flags=re.S)))).strip()
    rows = []
    for tr in re.findall(r'<tr class="(?:odd|even)">(.*?)</tr>', h, flags=re.S):
        c = dict(re.findall(r'<td class="([a-z]+)">(.*?)</td>', tr, flags=re.S))
        if 'rank' in c and strip(c['rank']).isdigit():
            rows.append((int(strip(c['rank'])), strip(c.get('name', '')), strip(c.get('team', '')), strip(c.get('teamposition', ''))))
    rows = consecutive(sorted(rows))
    if len(rows) >= MIN_ROWS: return 'nbadraftnet', time.strftime('%Y-%m-%d'), rows
    # 2027 big board still empty: their live mock ('Updated: YYYY-MM-DD'), # | Team | Player | H | W | P | School | Yr
    h = curl(f'https://www.nbadraft.net/nba-mock-drafts/?year-mock={YEAR}')
    d = re.search(r'Updated:\s*(\d{4}-\d\d-\d\d)', h)
    # long names are cut ('Hugo Yimga Mouko...'): the player link's slug has the whole name
    h = re.sub(r'<a href="[^"]*/players/([a-z0-9-]+)/?">([^<]*?)\.\.\.</a>',
               lambda m: m.group(2) + m.group(1).replace('-', ' ')[len(m.group(2)):], h)
    t = html.unescape(re.sub(r'<[^>]+>', '\n', re.sub(r'(?s)<(script|style)[^>]*>.*?</\1>', '', h)))
    L = [x.strip() for x in t.split('\n') if x.strip()]
    out = []
    for i in range(len(L) - 7):
        if L[i].isdigit() and re.match(r'^\d-\d{1,2}$', L[i + 3]) and L[i + 4].isdigit():
            out.append((int(L[i]), L[i + 2], L[i + 6], L[i + 5]))
    return 'nbadraftnet', d.group(1) if d else None, consecutive(sorted(set(out)))


# ---------------------------------------------------------------- one-off articles (--articles)
# The newest free article per analyst. When one posts a newer board or mock, swap the URL and rerun --articles.
ARTICLES = {
    'espn_woo': 'https://abc7.com/post/2027-nba-draft-big-board-rankings-top-100-prospects/20017483/',   # ESPN, syndicated
    'br_wasserman': 'https://bleacherreport.com/articles/25520687-new-2027-nba-mock-draft-college-basketball-season-tips',
    'fansided': 'https://fansided.com/nba/2027-nba-draft-big-board-top-60-prospects-as-college-basketball-gets-underway',
    'clutchpoints': 'https://clutchpoints.com/nba/nba-stories/2027-nba-mock-draft-1st-round-predictions-after-one-week-college-hoops',
}


def _lines(h):
    t = html.unescape(re.sub(r'<[^>]+>', '\n', re.sub(r'(?s)<(script|style)[^>]*>.*?</\1>', '', h)))
    return [re.sub(r'\s+', ' ', x).strip() for x in t.split('\n') if x.strip()]


def _published(h):
    m = re.search(r'"datePublished"\s*:\s*"(\d{4}-\d\d-\d\d)', h)
    return m.group(1) if m else None


def parse_article(src, h):
    L = _lines(h); rows = []
    if src == 'espn_woo':            # '7.' | 'Name' | ', POS, School' (or '2. Name, POS, Club')
        for i, l in enumerate(L):
            m = re.match(r'^(\d{1,3})\.\s*(.*)$', l)
            if not m: continue
            txt = m.group(2) or ''
            j = i + 1
            while (not txt or txt.count(',') < 2 or txt.rstrip().endswith(',')) and j < min(i + 5, len(L)):
                txt += (' ' if txt and not L[j].startswith(('.', ',')) else '') + L[j]; j += 1
            parts = [x.strip() for x in txt.split('|')[0].split(',')]
            if len(parts) >= 3 and 1 < len(parts[0]) <= 40:
                rows.append((int(m.group(1)), parts[0], re.sub(r'\s*Age:.*$', '', parts[2]).strip(), parts[1]))
    elif src == 'br_wasserman':      # '1. Sacramento Kings: Tyran Stokes (Kansas)'
        for l in L:
            m = re.match(r'^(\d{1,2})\.\s+[^:]+:\s+(.+?)\s+\(([^)]+)\)$', l)
            if m: rows.append((int(m.group(1)), m.group(2), m.group(3), ''))
    elif src == 'fansided':          # '1. Tyran Stokes' | 'G-F' | 'Kansas'
        for i, l in enumerate(L[:-2]):
            m = re.match(r'^(\d{1,2})\.\s+(.{2,40})$', l)
            if not m: continue
            nm, *rest = [x.strip() for x in m.group(2).split('|')]
            if len(rest) >= 2: rows.append((int(m.group(1)), nm, rest[1], rest[0]))
            elif len(L[i + 1]) <= 6: rows.append((int(m.group(1)), nm, L[i + 2], L[i + 1]))
    elif src == 'clutchpoints':      # '1. New Orleans Pelicans (via Bucks): Tyran Stokes, Kansas'
        for l in L:
            m = re.match(r'^(\d{1,2})\.\s+[^:]+:\s+([^,]+),\s*(.+)$', l)
            if m: rows.append((int(m.group(1)), m.group(2).strip(), m.group(3).strip(), ''))
        # a pick run into the paragraph before it ('... 13. Charlotte Hornets (via Mavericks): Dame Sarr, Duke Dame Sarr would')
        have, txt = {r[0] for r in rows}, ' '.join(L)
        for n in range(1, 31):
            if n in have: continue
            m = re.search(rf'(?<![\d$]){n}\.\s+[A-Z][^:]{{2,45}}:\s+([A-Z][^,]{{2,40}}),\s+', txt)
            if not m: continue
            first = m.group(1).split()[0]
            sch = re.match(rf'(.+?)\s+{re.escape(first)}\b', txt[m.end():m.end() + 80])
            if sch: rows.append((n, m.group(1).strip(), sch.group(1).strip(), ''))
    seen, out = set(), []
    for r in sorted(rows):
        if r[0] not in seen: seen.add(r[0]); out.append(r)
    return consecutive(out)


def main_articles():
    for src, url in ARTICLES.items():
        h = curl(url)
        rows, date = parse_article(src, h), _published(h)
        if len(rows) < MIN_ROWS or not date:
            print(f'{src}: {len(rows)} rows, kept the last copy'); continue
        write_board(src, date, rows)


def write_board(src, date, rows):
    p = os.path.join(LIVE_DIR, f'{src}_{YEAR}.csv')
    with open(p, 'w', newline='', encoding='utf-8') as o:
        w = csv.writer(o); w.writerow(COLS)
        w.writerows([[src, YEAR, date, rk, nm, sc, ps] for rk, nm, sc, ps in rows])
    print(f'{src}: {len(rows)} rows ({date}), top 3:', ', '.join(r[1] for r in rows[:3]))


def main_pull():
    os.makedirs(LIVE_DIR, exist_ok=True)
    changed = 0
    for fn in (pull_tankathon, pull_cbs, pull_noceilings, pull_floorandceiling, pull_espn, pull_nbadraftnet):
        try: src, date, rows = fn()
        except Exception as e:      # one source down never stops the others
            print(fn.__name__, 'failed:', e); continue
        if len(rows) < MIN_ROWS or not date:
            print(f'{src}: {len(rows)} rows, kept the last pull'); continue
        write_board(src, date, rows)
        changed += 1
    print(changed, 'boards refreshed')


if __name__ == '__main__':
    if '--fit' in sys.argv: main_fit()
    elif '--pull' in sys.argv: main_pull()
    elif '--articles' in sys.argv: main_articles()
    else: sys.exit(__doc__)
