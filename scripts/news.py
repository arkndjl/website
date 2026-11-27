# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Site news: one feed built from the site's own data files, nothing posted by hand.

  python3 scripts/news.py            rebuild data/news.json (state in scripts/data/news_state.json)
  python3 scripts/news.py --test     self-check

Feeds the header ticker (layouts/partials/newsticker.html), the /news/ page (layouts/shortcodes/news.html) and the
daily roundup GFX (assets/js/gfx.js buildNews). Each item: id, d (ET day), at (ms), sec (stclaire | arkboard | 1nt |
laursen), cat, tag (the label on its pixel tag), t (headline), s (detail), w (weight 0-100), href, logo / logo2.

Weight `w` ranks an item; MAJOR (w >= 60) is what the ticker and the daily GFX draw from. The rules, all explicit:

  song / art        new ST. CLAIRE track or piece 90 / 85; play-count milestone (PLAYS steps) 60-80
  1NT               ESEA match result 80 (playoff 88)
  LAURSEN_111       social milestone hit 75, dated goal hit 65, new upload 62, log entry 55,
                    PUG day report 50 (60 when the day's RWA is +/-4 or the day is 3+ games unbeaten)
  trade             a player at or above the sport's 90th value percentile 88; 75th 72; other players 52; picks only 45
  move              sign / release / claim / call-up only for a 75th+ percentile player: 56 (90th: 68)
  soccer transfer   market value EUR 40M+ 80; 15M+ 62; smaller ones stay on the transactions tab
  portal            college player entering: FV 50+ 78; 45+ 62; else 42
  injury            RotoWire item that takes a player out (OUT pattern; rest days skipped): 90th percentile 72; 75th 54;
                    college FV 50+ 70; 45+ 54; +16 for a long absence (SEVERE: season, ACL, Achilles, tear,
                    fracture, surgery, IR); everyone else stays on the injury tabs
  recruit           commit / sign / flip / decommit / reclass: a recruit on the site's board 70 (flip 76, decommit 66); cb (247 Crystal Ball alert) 45, never MAJOR;
                    off the board 40
  FV                |change| >= 2 since the day's first build on an FV board: 44 + 6 per point (cap 92), so >= 3 is major;
                    a player under FV 40 before and after needs >= 3 and tops out at 55 (college boards track FV 40+ only)
  game              final where the model's pregame winner chance was <= 30%: 60 + (30 - p) (cap 88);
                    both teams ranked 70 (both top 10: 82); a top-10 team losing to an unranked one 80;
                    one of Noah's teams (Knicks, Rangers, Ravens, Barcelona) 66; other finals are not news

Value percentile: NFL WAR, NBA VORX, NHL WAR among the players on the site's boards; college = FV. Names join through
scripts/names.py. Items are kept KEEP_DAYS days; a past day is frozen (only today's FV moves are recomputed).
"""
import datetime as dt
import glob
import json
import os
import re
import sys
import urllib.request
from collections import Counter
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'news.json')
STATE = os.path.join(ROOT, 'scripts', 'data', 'news_state.json')
ET = ZoneInfo('America/New_York')
KEEP_DAYS = 30
MAJOR = 60
TICKER_N = 24     # cells on the strip
TICKER_DAYS = 7
NEWS_FLOOR = 40   # impact = w - NEWS_FLOOR (40 = the "not news" line in the rules above)
HALF_LIFE_H = 24  # impact halves every 24 h
FV_FLOOR = 40     # an FV move is major only for a player at 40+ (before or after)
PLAYS = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000]
OUT_RE = re.compile(r"ruled out|won't play|will not play|not playing|out for (the )?season|season[- ]ending|lands on (ir|injured reserve)|"
                    r"placed on (ir|injured reserve)|moved to (ir|injured reserve)|to injured reserve|undergoes \w+ surgery|has surgery|surgery (scheduled|set)|needs surgery|out indefinitely|"
                    r"downgraded to out|unavailable|out (multiple|several|at least)|sidelined|won't return|out for week|out (sun|mon|tues|wednes|thurs|fri|satur)day|"
                    r"tears|torn|fracture|out \d", re.I)
SEVERE_RE = re.compile(r'season|acl|achilles|torn|tear|fracture|surgery|injured reserve|\bir\b|indefinite|broken', re.I)
BACK_RE = re.compile(r'activated|returns to|cleared|back at practice|expected to play|good to go|will play|^available|tbd|avoids|no surgery|whether', re.I)
MINE = {'nba': {'NY', 'NYK'}, 'nhl': {'NYR'}, 'nfl': {'BAL'}}
NHL_ESPN = {'LAK': 'LA', 'SJS': 'SJ', 'TBL': 'TB', 'NJD': 'NJ'}
RW_SPORT = {'football': 'nfl', 'basketball': 'nba', 'hockey': 'nhl', 'cfootball': 'cfb', 'cbasketball': 'cbb'}
PAGE = {'nfl': '/arkboard/nfl/', 'nba': '/arkboard/nba/', 'nhl': '/arkboard/nhl/', 'cfb': '/arkboard/college-football/',
        'cbb': '/arkboard/college-basketball/', 'soccer': '/arkboard/soccer/', 'hockey': '/arkboard/hockey-prospects/',
        'u22': '/arkboard/soccer-prospects/', 'tennis': '/arkboard/tennis-prospects/', 'cs2': '/arkboard/counter-strike/'}
TAG = {'nfl': 'NFL', 'nba': 'NBA', 'nhl': 'NHL', 'cfb': 'CFB', 'cbb': 'CBB', 'soccer': 'SOCCER', 'hockey': 'HOCKEY', 'u22': 'U22',
       'tennis': 'TENNIS', 'cs2': 'CS2'}


def load(rel, default=None):
    try:
        with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def newest(pattern):
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)))
    return os.path.relpath(fs[-1], ROOT) if fs else None


def et_day(ms=None):
    t = dt.datetime.fromtimestamp(ms / 1000, ET) if ms is not None else dt.datetime.now(ET)
    return t.strftime('%Y-%m-%d')


def day_ms(d, hour=12):
    y, m, x = (int(v) for v in d.split('-'))
    return int(dt.datetime(y, m, x, hour, tzinfo=ET).timestamp() * 1000)


def iso_ms(s):
    try:
        return int(dt.datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp() * 1000)
    except ValueError:
        return None


def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', str(s).lower()).strip('-')


def clip(s, n):
    s = ' '.join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + '…'


def num(v):
    v = round(float(v), 1)
    return str(int(v)) if v == int(v) else str(v)


def item(id, d, sec, cat, tag, t, w, s=None, href=None, at=None, logo=None, logo2=None, sp=None):
    it = {'id': id, 'd': d, 'at': at, 'sec': sec, 'cat': cat, 'tag': tag, 't': t, 's': s, 'w': int(round(w)), 'href': href,
          'logo': logo, 'logo2': logo2, 'sp': sp}
    return {k: v for k, v in it.items() if v is not None}


# ---- player value: percentile on the pro boards, FV on the college boards ------------------------------------------
class Values:
    def __init__(self):
        self.m = {}
        self._pro('nfl', 'static/data/nfl-war.json', 'n', 'tm', 'war')
        self._pro('nba', newest('static/data/nba-xpm/20*.json'), 'n', 'tm', 'vorx')
        self._pro('nhl', newest('static/data/nhl-war/20*.json'), 'n', 'tm', 'war')
        self._college('cfb', 'static/data/cfb-all.json')
        self._college('cbb', 'static/data/cbb-all.json')

    def _pro(self, sp, rel, n, t, v):
        d = load(rel) if rel else None
        rows = [r for r in (d or {}).get('players', []) if isinstance(r.get(v), (int, float))]
        if not rows: return
        vals = sorted(r[v] for r in rows)
        for r in rows:
            r['_pct'] = 100.0 * sum(1 for x in vals if x < r[v]) / max(1, len(vals) - 1)
        self.m[sp] = (names.Matcher(rows, name=n, team=t, pos=None, sport='football'), '_pct')

    def _college(self, sp, rel):
        d = load(rel)
        if not d or 'cols' not in d: return
        c = d['cols']
        try: i_n, i_t, i_f = c.index('name'), c.index('team'), c.index('fv')
        except ValueError: return
        rows = [{'name': r[i_n], 'team': r[i_t], 'fv': r[i_f]} for r in d['rows'] if isinstance(r[i_f], (int, float))]
        self.m[sp] = (names.Matcher(rows, name='name', team='team', pos=None), 'fv')

    def get(self, sp, name, team=None):
        """pro: value percentile 0-100; college: FV; None when the player is not on the board"""
        if sp not in self.m or not name: return None
        m, f = self.m[sp]
        try: r, _ = m.find(name, team=team, cross_team='exact')
        except Exception: r = None
        return r.get(f) if r else None


def tier(sp, v):
    """2 = major, 1 = notable, 0 = neither"""
    if v is None: return 0
    if sp in ('cfb', 'cbb'): return 2 if v >= 50 else 1 if v >= 45 else 0
    return 2 if v >= 90 else 1 if v >= 75 else 0


def pro_logo(sp, ab):
    if not ab or sp not in ('nfl', 'nba', 'nhl'): return None
    p = '/img/%s/%s.png' % (sp, str(ab).lower())
    return p if os.path.exists(os.path.join(ROOT, 'static', p.lstrip('/'))) else None


# ---- sources ------------------------------------------------------------------------------------------------------
def transactions(V, since):
    out = []
    for sp in ('nfl', 'nba', 'nhl', 'cfb', 'cbb'):
        d = load('data/transactions/%s.json' % sp) or {}
        href = PAGE[sp] + '#transactions'
        traded = set()
        for deal in d.get('deals', []):
            if deal['d'] < since: continue
            ps = [p for p in deal.get('players', []) if p and p[0]]
            if sp in ('cfb', 'cbb'): continue
            best = max([tier(sp, V.get(sp, p[0])) for p in ps] or [0])
            w = 45 if not ps else (88 if best == 2 else 72 if best == 1 else 52)
            for p in ps: traded.add((deal['d'], p[0]))
            if ps:
                lead = ps[0]
                t = '%s %s → %s' % (lead[0], lead[1] or '', lead[2] or '') if lead[2] else lead[0]
                more = len(ps) - 1
                picks = len(deal.get('picks') or [])
                s = 'trade' + (' · +%d player%s' % (more, '' if more == 1 else 's') if more else '') + (' · %d pick%s' % (picks, '' if picks == 1 else 's') if picks else '')
                lg, lg2 = pro_logo(sp, lead[1]), pro_logo(sp, lead[2])
            else:
                pk = deal['picks'][0]
                t = '%s → %s' % (pk[2], pk[3]); s = 'trade · %d pick%s' % (len(deal['picks']), '' if len(deal['picks']) == 1 else 's')
                lg, lg2 = pro_logo(sp, pk[2]), pro_logo(sp, pk[3])
            out.append(item('tx|%s|%s|%s' % (sp, deal['d'], slug(t)), deal['d'], 'arkboard', 'trade', TAG[sp], ' '.join(t.split()), w, s, href,
                            logo=lg, logo2=lg2, sp=sp))
        for r in d.get('rows', []):
            if r['d'] < since or r['k'] in ('trade', 'practice', 'down') or (r['d'], r['n']) in traded: continue
            college = sp in ('cfb', 'cbb')
            v = V.get(sp, r['n'], r.get('fr') if college else (r.get('to') or r.get('fr')))
            tr = tier(sp, v)
            if college and r['k'] == 'exit':
                w = 78 if tr == 2 else 62 if tr == 1 else 42
                t = '%s%s enters the portal' % (r['n'], ' (%s)' % r['fr'] if r.get('fr') and r['fr'] != 'No Current School' else '')
                s = 'portal · %s' % r['pos'] if r.get('pos') else 'portal'
                if v is not None: s += ' · FV %s' % num(v)
            elif college or not tr:
                continue
            else:
                w = 68 if tr == 2 else 56
                verb = {'sign': 'signs', 'release': 'released', 'claim': 'claimed', 'up': 'called up', 'exit': 'out', 'move': 'moves'}.get(r['k'], r['k'])
                t = '%s %s' % (r['n'], verb) + (' · %s' % r['to'] if r.get('to') else '')
                s = clip(r.get('h') or r['k'], 60)
            out.append(item('mv|%s|%s|%s|%s' % (sp, r['d'], slug(r['n']), r['k']), r['d'], 'arkboard', 'portal' if college else 'move', TAG[sp], t, w, s, href,
                            logo=None if college else pro_logo(sp, r.get('to') or r.get('fr')), sp=sp))
    d = load('data/transactions/soccer.json') or {}
    for r in d.get('rows', []):
        mv = r.get('mv') or r.get('fee') or 0
        if r['d'] < since or mv < 15e6: continue
        s = 'transfer · €%sM' % num(mv / 1e6) + (' · fee €%sM' % num(r['fee'] / 1e6) if r.get('fee') else '')
        out.append(item('tx|soccer|%s|%s' % (r['d'], slug(r['n'])), r['d'], 'arkboard', 'trade', 'SOCCER', '%s %s → %s' % (r['n'], r.get('fr') or '', r.get('to') or ''),
                        80 if mv >= 40e6 else 62, s, PAGE['soccer'] + '#transactions', sp='soccer'))
    return out


def folded(r, rows):
    """a decommitment that a commitment elsewhere within a day turns into a flip: the flip row carries the move (DJ Jacobs,
    Ohio State -> Miami, Nov 26 2026), so the decommitment is not a second item"""
    import names
    d0 = dt.date.fromisoformat(r['d'])
    for x in rows:
        if x is r or x['k'] not in ('flip', 'commit') or not x.get('to') or not names.same(x['n'], r['n']): continue
        if r.get('fr') and names.same_team(x['to'], r['fr']): continue
        if 0 <= (dt.date.fromisoformat(x['d']) - d0).days <= 1: return True
    return False


def recruits(since):
    out = []
    d = load('data/recruit_news.json') or {}
    for sp in ('cfb', 'cbb'):
        seen, rows = set(), d.get(sp, [])
        for r in rows:
            if r['d'] < since or (r['n'], r['k']) in seen: continue
            if r['k'] == 'decommit' and folded(r, rows): continue
            seen.add((r['n'], r['k']))
            k, on = r['k'], bool(r.get('b'))
            who = r['n'] + (' %s' % r['pos'] if r.get('pos') else '') + (" '%s" % str(r['cls'])[2:] if r.get('cls') else '')
            if k == 'flip': t = '%s flips %s → %s' % (who, r.get('fr') or '', r.get('to') or '')
            elif k == 'decommit': t = '%s decommits%s' % (who, ' from %s' % r['fr'] if r.get('fr') else '')
            elif k == 'reclass': t = '%s reclassifies%s' % (who, ' to %s' % r['cls'] if r.get('cls') else '')
            elif k == 'sign': t = '%s signs%s' % (who, ' with %s' % r['to'] if r.get('to') else '')
            elif k in ('portal',): t = '%s enters the portal' % who
            elif k == 'cb': t = '%s: 247 Crystal Ball%s' % (who, ' → %s' % r['to'] if r.get('to') else '')
            else: t = '%s commits%s' % (who, ' to %s' % r['to'] if r.get('to') else '')
            if k == 'commit' and not r.get('fr'):   # a commitment right after a decommitment is a flip
                dec = next((x for x in rows if x['k'] == 'decommit' and x.get('fr') and folded(x, [r])), None)
                if dec: k, r = 'flip', dict(r, fr=dec['fr'], fl=dec.get('fl')); t = '%s flips %s → %s' % (who, r['fr'], r['to'])
            w = 45 if k == 'cb' else ({'flip': 76, 'decommit': 66}.get(k, 70)) if on else 40   # a Crystal Ball is a lean, not a move: never MAJOR
            out.append(item('rc|%s|%s|%s|%s' % (sp, r['d'], slug(r['n']), k), r['d'], 'arkboard', 'recruit', TAG[sp], ' '.join(t.split()), w,
                            'recruit · %s' % k + (' · on board' if on else ''), PAGE[sp] + '#recruit-transactions',
                            logo=r.get('fl') if k == 'flip' else (r.get('tl') or r.get('fl')), logo2=r.get('tl') if k == 'flip' else None, sp=sp))
            out[-1]['n'] = r['n']
    return out


def injuries(V, since):
    d = load('scripts/data/rotowire_news.json') or {}
    best = {}
    for v in (d.get('items') or {}).values():
        sp = RW_SPORT.get(v.get('sport'))
        if not sp or not v.get('ts'): continue
        day = et_day(v['ts'] * 1000)
        head = v.get('head') or ''
        if day < since or not OUT_RE.search(head) or BACK_RE.search(head) or str(v.get('inj') or '').lower() in ('rest', 'personal', 'not injury related', 'coach\'s decision'): continue
        college = sp in ('cfb', 'cbb')
        val = V.get(sp, v.get('player'), v.get('team') if college else v.get('abbr'))
        tr = tier(sp, val)
        if not tr: continue
        w = (70 if tr == 2 else 54) if college else (72 if tr == 2 else 54)
        if SEVERE_RE.search(head + ' ' + str(v.get('inj') or '')): w += 16   # long absences lead the day
        team = v.get('team') if college else v.get('abbr')
        t = '%s%s: %s' % (v['player'], ' (%s)' % team if team else '', head[0].lower() + head[1:] if head[1:2].islower() else head)
        s = 'injury' + (' · %s' % v['inj'].lower() if v.get('inj') else '') + (' · FV %s' % num(val) if college else '')
        it = item('inj|%s|%s|%s' % (sp, day, slug(v['player'])), day, 'arkboard', 'injury', TAG[sp], t, w, s, PAGE[sp] + '#transactions',
                  at=v['ts'] * 1000, logo=pro_logo(sp, v.get('abbr')), sp=sp)
        if it['id'] not in best or best[it['id']]['at'] < it['at']: best[it['id']] = it
    return list(best.values())


FV_BOARDS = [   # tag key, file, path to rows, id fields, name field, team field, page hash
    ('cbb', 'static/data/cbb-all.json', None, ('name', 'team'), 'name', 'team', '#board'),
    ('hockey', 'data/hockey.json', ('board',), ('name',), 'name', 'club', '#draft-board'),
    ('u22', 'data/soccer_prospects.json', ('board',), ('id',), 'name', 'club', '#big-board'),
    ('tennis', 'data/tennis_prospects.json', ('atp', 'board'), ('id',), 'name', None, '#atp-big-board'),
    ('tennis', 'data/tennis_prospects.json', ('wta', 'board'), ('id',), 'name', None, '#wta-big-board'),
    ('cs2', 'data/cs2_players.json', ('prospects',), ('id',), 'n', 'tm', '#prospects'),
    ('cfb', 'static/data/cfb-all.json', None, ('name', 'team'), 'name', 'team', '#board'),
]

OLD_HREF = {'/arkboard/hockey-prospects/#board': '/arkboard/hockey-prospects/#draft-board',
            '/arkboard/soccer-prospects/#board': '/arkboard/soccer-prospects/#big-board',
            '/arkboard/tennis-prospects/#board': ('/arkboard/tennis-prospects/#atp-big-board', '/arkboard/tennis-prospects/#wta-big-board')}   # (ATP, WTA): WTA ids start with w


def fv_rows(rel, path):
    d = load(rel)
    if d is None: return []
    if path is None:
        c = d.get('cols') or []
        return [dict(zip(c, r)) for r in d.get('rows', [])]
    for k in path:
        d = (d or {}).get(k) if isinstance(d, dict) else None
    return d or []


def fv_moves(state, today, now):
    """FV now against the day's first build (the first run ever: against the board's weekly baseline w0)"""
    snap = state.get('fv')
    base = None if not snap else snap.get('last', {}) if snap.get('d') != today else snap.get('b', {})
    cur_all, base_all, out = {}, {}, []
    for key, rel, path, idf, nf, tf, hash_ in FV_BOARDS:
        bk = key + ':' + '/'.join(path or ('',))
        cur, b_ = cur_all.setdefault(bk, {}), base_all.setdefault(bk, {})
        rows = fv_rows(rel, path)
        # a player the board lists at two positions (a kicker who punts: K 48, P 34) is two ids, not one id whose two
        # grades read as a move every day
        twice = {p for p, n in Counter('|'.join(str(r.get(f)) for f in idf) for r in rows).items() if n > 1}
        for r in rows:
            fv = r.get('fv')
            if not isinstance(fv, (int, float)) or isinstance(fv, bool): continue
            pid = '|'.join(str(r.get(f)) for f in idf)
            if pid in twice: pid += '|%s' % r.get('pos')
            if pid in cur: continue   # the same player twice at one position (a duplicated board row): the first row only
            if key in ('cfb', 'cbb') and fv < FV_FLOOR and not (base and pid in base.get(bk, {})): continue   # deep college rows: not tracked
            cur[pid] = fv
            b0 = r.get('w0') if base is None else base.get(bk, {}).get(pid)
            if not isinstance(b0, (int, float)) or isinstance(b0, bool): continue
            b_[pid] = b0
            dv = fv - b0
            if abs(dv) < (2 if max(fv, b0) >= FV_FLOOR else 3): continue
            team = r.get(tf) if tf else None
            out.append(item('fv|%s|%s|%s' % (key, today, slug(pid)), today, 'arkboard', 'fv', TAG[key],
                            '%s FV %s → %s' % (r.get(nf), num(b0), num(fv)), (min(92, 44 + 6 * abs(dv)) if max(fv, b0) >= FV_FLOOR else min(55, 40 + 3 * abs(dv))),
                            'FV %s%s' % ('+' if dv > 0 else '−', num(abs(dv))) + (' · %s' % team if team else ''),
                            PAGE[key] + hash_, at=now, logo=r.get('logo') if isinstance(r.get('logo'), str) else None, sp=key))
    if not snap or snap.get('d') != today:
        state['fv'] = {'d': today, 'b': base_all if base is None else snap.get('last', {}), 'last': cur_all}
    else:
        state['fv']['last'] = cur_all
    return out


def logo_id(u):
    m = re.search(r'/(\d+)\.png', u or '')
    return m.group(1) if m else None


def games(state, since):
    out = []
    pre = state.setdefault('pre', {})
    # pregame model chances, kept until the final shows up
    nba = load('data/nba_games.json') or {}
    for g in list(nba.get('games', [])) + [x.get('row') for x in (nba.get('log') or {}).values() if isinstance(x, dict) and x.get('row')]:
        if g.get('pHome') is not None: pre['nba|%s|%s|%s' % (g['day'], g['home'], g['away'])] = g['pHome']
    for g in (load('data/nhl_games.json') or {}).get('games', []):
        if g.get('pHome') is not None: pre['nhl|%s|%s|%s' % (g['day'], NHL_ESPN.get(g['home'], g['home']), NHL_ESPN.get(g['away'], g['away']))] = g['pHome']
    for g in (load('data/cbb_games.json') or {}).get('games', []):
        if g.get('pHome') is not None: pre['cbb|%s|%s|%s' % (g['date'], g['home'].get('id'), g['away'].get('id'))] = g['pHome']
    for g in (load('data/cfb_games.json') or {}).get('games', []):
        if g.get('pHome') is not None and g.get('date'):
            pre['cfb|%s|%s|%s' % (et_day(iso_ms(g['date'])), g['home'].get('id'), g['away'].get('id'))] = g['pHome']
    cut = (dt.datetime.now(ET) - dt.timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
    for k in [k for k in pre if k.split('|')[1] < cut]: del pre[k]

    def add(sp, day, at, home, away, hs, as_, p_home, hrk=None, ark=None, hlogo=None, alogo=None, mine=False):
        if hs == as_ or day < since: return
        hw = hs > as_
        win, los, ws, ls = (home, away, hs, as_) if hw else (away, home, as_, hs)
        wrk, lrk = (hrk, ark) if hw else (ark, hrk)
        pw = None if p_home is None else (p_home if hw else 1 - p_home)
        w, why = 0, []
        if pw is not None and pw <= 0.30: w = max(w, min(88, 60 + (30 - 100 * pw))); why.append('upset · model %d%%' % round(100 * pw))
        if wrk and lrk: w = max(w, 82 if wrk <= 10 and lrk <= 10 else 70); why.append('ranked matchup')
        if lrk and lrk <= 10 and not wrk: w = max(w, 80); why.append('top-10 loss')
        if mine: w = max(w, 66)
        if not w: return
        if pw is not None and not any('model' in x for x in why): why.append('model %d%%' % round(100 * pw))
        rk = lambda r: '#%d ' % r if r else ''
        out.append(item('gm|%s|%s|%s|%s' % (sp, day, slug(home), slug(away)), day, 'arkboard', 'game', TAG[sp],
                        '%s%s %s, %s%s %s' % (rk(wrk), win, ws, rk(lrk), los, ls), w, ' · '.join(['final'] + why), PAGE[sp] + '#games', at=at,
                        logo=hlogo if hw else alogo, logo2=alogo if hw else hlogo, sp=sp))

    nfl = load('data/nfl_games.json') or {}
    for g in nfl.get('past', []):
        f = g.get('final')
        if not f or f.get('home') is None: continue
        add('nfl', g['date'], iso_ms(g.get('kick')), g['home'], g['away'], f['home'], f['away'], g.get('pHome'),
            hlogo=pro_logo('nfl', g['home']), alogo=pro_logo('nfl', g['away']), mine=bool({g['home'], g['away']} & MINE['nfl']))
    sc = (load('data/standings.json') or {}).get('scores', {})
    for sp in ('nba', 'nhl', 'cbb', 'cfb'):
        for dayrow in sc.get(sp, []):
            for g in dayrow.get('games', []):
                if g.get('st') != 'post' or not re.match(r'^20\d{10}$', str(g.get('key', ''))): continue
                k = g['key']; day = '%s-%s-%s' % (k[:4], k[4:6], k[6:8])
                a, h = g['a'], g['h']
                try: hs, as_ = int(h['s']), int(a['s'])
                except (TypeError, ValueError): continue
                if sp in ('cbb', 'cfb'): hk, ak = logo_id(h.get('logo')), logo_id(a.get('logo'))
                else: hk, ak = h['ab'], a['ab']
                p = pre.get('%s|%s|%s|%s' % (sp, day, hk, ak))
                at = int(dt.datetime(int(k[:4]), int(k[4:6]), int(k[6:8]), int(k[8:10]), int(k[10:12]), tzinfo=ET).timestamp() * 1000) + 9000000
                add(sp, day, at, h['ab'] if sp in ('nba', 'nhl') else h['n'], a['ab'] if sp in ('nba', 'nhl') else a['n'], hs, as_, p,
                    h.get('rk'), a.get('rk'), pro_logo(sp, h['ab']) or h.get('logo'), pro_logo(sp, a['ab']) or a.get('logo'),
                    mine=bool({h['ab'], a['ab']} & MINE.get(sp, set())))
    return out


def nt_and_laursen(state, since, now):
    out = []
    e = load('data/esea.json') or {}
    for m in e.get('matches', []):
        if m.get('status') != 'FINISHED' or not m.get('result') or not m.get('at'): continue
        day = et_day(m['at'])
        if day < since: continue
        maps = m.get('maps') or []
        opp = (m.get('opp') or {}).get('name') or 'opponent'
        if len(maps) == 1: sc = '%s-%s' % (maps[0]['rf'], maps[0]['ra']); det = maps[0]['map']
        else:
            won = sum(1 for x in maps if x.get('win')); sc = '%d-%d' % (won, len(maps) - won); det = ' '.join(x['map'] for x in maps)
        po = 'playoff' in str(m.get('stage', '')).lower()
        out.append(item('nt|%s' % m['id'], day, '1nt', 'match', '1NT', '1NT %s %s' % (sc, opp), 88 if po else 80,
                        ' · '.join(x for x in [m['result'], det, 'bo%s' % m.get('best_of') if (m.get('best_of') or 1) > 1 else None, 'playoffs' if po else None] if x),
                        '/1nt/#matchday', at=m['at'], logo2=(m.get('opp') or {}).get('avatar')))
    pg = ((e.get('profile') or {}).get('pugs') or {})
    for d in pg.get('days', []):
        if d['day'] < since or not d.get('n'): continue
        a = d.get('avg') or {}
        rwa = a.get('rwa')
        w = 60 if (isinstance(rwa, (int, float)) and abs(rwa) >= 4) or (d['n'] >= 3 and not d.get('l')) else 50
        s = ' · '.join(x for x in ['RWA %s%s' % ('+' if (rwa or 0) > 0 else '', num(rwa)) if isinstance(rwa, (int, float)) else None,
                                   'rating %.2f' % a['rating'] if isinstance(a.get('rating'), (int, float)) else None,
                                   '%d MVP' % d['mvps'] if d.get('mvps') else None] if x)
        at = max([g.get('at') or 0 for g in d.get('games', [])] or [0]) or day_ms(d['day'], 23)
        out.append(item('pug|%s' % d['day'], d['day'], 'laursen', 'pug', 'LAURSEN_111', 'PUGs %d-%d' % (d.get('w') or 0, d.get('l') or 0), w, s,
                        '/laursen_111/#stats', at=at))
    for en in (load('data/laurlog.json') or {}).get('entries', []):
        at = iso_ms(en.get('at'))
        if not at or et_day(at) < since: continue
        out.append(item('log|%s' % en['n'], et_day(at), 'laursen', 'log', 'LAURSEN_111', 'log #%s' % en['n'], 55, clip(en.get('text', ''), 90),
                        '/laursen_111/', at=at))
    s = load('data/laursen_socials.json') or {}
    unit = {'twitch': 'followers', 'youtube': 'subscribers', 'tiktok': 'followers', 'x': 'followers'}
    for net, h in (s.get('hist') or {}).items():
        for m in h.get('ms', []):
            if m.get('hit') and not m.get('est') and et_day(m['hit']) >= since:
                out.append(item('soc|%s|%s' % (net, m['goal']), et_day(m['hit']), 'laursen', 'social', 'LAURSEN_111',
                                '%s %s %s' % (net, '{:,}'.format(m['goal']), unit.get(net, 'followers')), 75, 'milestone', '/laursen_111/#social', at=m['hit']))
        for m in h.get('dated', []):
            if m.get('hit') and et_day(m['hit']) >= since:
                out.append(item('socd|%s|%s|%s' % (net, m['goal'], m.get('set')), et_day(m['hit']), 'laursen', 'social', 'LAURSEN_111',
                                '%s %s %s' % (net, '{:,}'.format(m['goal']), unit.get(net, 'followers')), 65, '%s-day goal hit' % m.get('T'), '/laursen_111/#social', at=m['hit']))
    for u in (load('data/cs.json') or {}).get('uploads', []):
        if u.get('date') and u['date'] >= since:
            out.append(item('up|%s' % u['id'], u['date'], 'laursen', 'upload', '1NT' if u.get('nt') else 'LAURSEN_111', clip(u.get('t', 'upload'), 70), 62, 'video',
                            '/laursen_111/#clips', at=day_ms(u['date'])))
    return out


def front(rel):
    try:
        import tomllib
        txt = open(os.path.join(ROOT, rel), encoding='utf-8').read()
        m = re.match(r'\+\+\+\n(.*?)\n\+\+\+', txt, re.S)
        return tomllib.loads(m.group(1)) if m else {}
    except Exception:
        return {}


def fetch_plays():
    try:
        req = urllib.request.Request('https://arkndjl.net/api/plays', headers={'User-Agent': 'site-news/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            return d if isinstance(d, dict) else {}
    except Exception:
        return None


def stclaire(state, today, now, plays='fetch'):
    """New tracks and pieces are the ones not seen on an earlier run (the first run only records what is there);
    a `date` in the front matter wins. Play milestones: the first run that sees a count at or past a PLAYS step."""
    out = []
    seen = state.get('seen')
    first = seen is None
    seen = state.setdefault('seen', {})
    for kind, rel, key, href, w in (('song', 'content/arkndjl-music.md', 'tracks', '/stclaire/music/', 90), ('art', 'content/arkndjl-art.md', 'gallery', '/stclaire/art/', 85)):
        for t in front(rel).get(key, []):
            if kind == 'art' and t.get('group', 'mine') != 'mine': continue
            title = t.get('title') or os.path.basename(t.get('src', ''))
            sid = '%s|%s' % (kind, slug(t.get('src') or title))
            if t.get('date'): d = str(t['date'])[:10]
            elif sid in seen: d = seen[sid]                    # '' = there before the feed began: not news
            else: d = '' if first else today
            seen[sid] = d
            if d:
                seen[sid] = d
                out.append(item('sc|' + sid, d, 'stclaire', kind, 'ST. CLAIRE', title, w, 'new song' if kind == 'song' else 'new piece', href,
                                at=now if d == today and sid not in state.get('at', {}) else state.get('at', {}).get(sid, day_ms(d))))
                state.setdefault('at', {}).setdefault(sid, out[-1]['at'])
    counts = fetch_plays() if plays == 'fetch' else plays
    titles = {os.path.splitext(os.path.basename(t.get('src', '')))[0]: t.get('title') for t in front('content/arkndjl-music.md').get('tracks', [])}
    hit = state.setdefault('plays', {})
    for sl, n in (counts or {}).items():
        if not isinstance(n, int) or sl not in titles: continue
        step = max([p for p in PLAYS if p <= n] or [0])
        if step > hit.get(sl, {}).get('step', 0):
            hit[sl] = {'step': step, 'd': today, 'at': now}
    for sl, h in hit.items():
        if h.get('step') and sl in titles:
            out.append(item('pl|%s|%s' % (sl, h['step']), h['d'], 'stclaire', 'plays', 'ST. CLAIRE', '%s %s plays' % (titles[sl] or sl, '{:,}'.format(h['step'])),
                            min(80, 60 + 4 * PLAYS.index(h['step'])), 'milestone', '/stclaire/music/', at=h['at']))
    return out


def roundup(day_items, n=10, floor=50, per_cat=3, per_tag=4):
    """the day's roundup (front page, daily GFX): heaviest first, at most per_cat of a category and per_tag of a tag,
    so one busy feed (a signing day, an injury report) cannot fill the card; ids in order"""
    out, cats, tags = [], {}, {}
    for i in sorted(day_items, key=lambda i: (-i['w'], -i['at'])):
        if i['w'] < floor or cats.get(i['cat'], 0) >= per_cat or tags.get(i['tag'], 0) >= per_tag: continue
        out.append(i['id']); cats[i['cat']] = cats.get(i['cat'], 0) + 1; tags[i['tag']] = tags.get(i['tag'], 0) + 1
        if len(out) == n: break
    if len(out) < n:   # room left: the caps give way, weight order kept
        rest = [i for i in sorted(day_items, key=lambda i: (-i['w'], -i['at'])) if i['w'] >= floor and i['id'] not in out]
        out += [i['id'] for i in rest[:n - len(out)]]
        order = {i['id']: (-i['w'], -i['at']) for i in day_items}
        out.sort(key=lambda x: order[x])
    return out


# ---- build --------------------------------------------------------------------------------------------------------
def build(state, plays='fetch'):
    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    today = et_day()
    since = (dt.datetime.now(ET) - dt.timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d')
    V = Values()
    new = []
    for fn in (lambda: transactions(V, since), lambda: recruits(since), lambda: injuries(V, since), lambda: fv_moves(state, today, now),
               lambda: games(state, since), lambda: nt_and_laursen(state, since, now), lambda: stclaire(state, today, now, plays)):
        try: new += fn()
        except Exception as ex:   # one broken source never empties the feed
            print('news: source failed:', repr(ex), file=sys.stderr)
    old = {i['id']: i for i in (load('data/news.json') or {}).get('items', [])}
    for o in old.values():   # frozen FV items written before the boards' tabs were renamed: "#board" opens nothing there
        if o.get('cat') == 'fv' and o.get('href') in OLD_HREF:
            h = OLD_HREF[o['href']]
            o['href'] = h[o['id'].split('|')[-1][:1] == 'w'] if isinstance(h, tuple) else h
    ids = {i['id'] for i in new}
    for i in new:
        o = old.get(i['id'])
        if 'at' not in i: i['at'] = (o or {}).get('at') or (now if i['d'] == today else day_ms(i['d']))
        elif o and i['cat'] == 'fv' and o.get('t') == i['t']: i['at'] = o['at']   # an unchanged FV move keeps its first time
    # a past day is frozen: what was reported stays; only today's FV moves are recomputed
    # an earlier recruit item about a player this build has recruit items for (same name rules) is superseded: a misdated
    # copy, a decommitment folded into a flip. One the recruit news no longer has at all stays, like any past day.
    import names
    now_rc = [i['n'] for i in new if i['cat'] == 'recruit' and i.get('n')]
    def superseded(o):
        if o['cat'] != 'recruit': return False
        w = o['t'].split()
        return any(names.same(n, ' '.join(w[:j])) for n in now_rc for j in (2, 3, 4) if len(w) >= j)
    keep = [o for k, o in old.items() if k not in ids and o['d'] >= since and not (o['cat'] == 'fv' and o['d'] == today) and not superseded(o)]
    items = [i for i in new + keep if i['d'] >= since and i['d'] <= today]
    items.sort(key=lambda i: (i['d'], i['w'] >= MAJOR, i['at']), reverse=True)
    days = []
    for i in items:
        if not days or days[-1]['d'] != i['d']: days.append({'d': i['d'], 'n': 0, 'major': 0})
        days[-1]['n'] += 1; days[-1]['major'] += i['w'] >= MAJOR
    for dy in days:
        dy['top'] = roundup([i for i in items if i['d'] == dy['d']])
    strip = ticker_pool(items, dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    return {'asof': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'major': MAJOR, 'ticker': strip, 'days': days, 'items': items}


def blend(i, now_ms):
    """Strip order: impact over the news floor times a 24 h half-life, (w - 40) * 2^(-age / 24 h). A 92 (52 over the
    floor) outranks a fresh 60 (20) until it is about 33 h old. One half-life for every item, so the ratio of two items'
    scores never changes with the clock: the order is fixed when the feed is built (no reshuffle between builds)."""
    age_h = max(0.0, (now_ms - i['at']) / 3.6e6)
    return (i['w'] - NEWS_FLOOR) * 2 ** (-age_h / HALF_LIFE_H)


def ticker_pool(items, now_ms):
    """The header strip: majors from the last TICKER_DAYS days, best blend first. A headline reported on several days (an FV
    move that repeats against each day's first build) is one cell, the newest id, aged from its first report."""
    since = (dt.datetime.fromtimestamp(now_ms / 1000, ET).date() - dt.timedelta(days=TICKER_DAYS - 1)).isoformat()
    first, show = {}, {}
    for i in items:
        if i['w'] < MAJOR: continue
        k = (i.get('cat'), i['t'])
        first[k] = min(first.get(k, i['at']), i['at'])
        if i['d'] >= since and (k not in show or i['at'] > show[k]['at']): show[k] = i
    rank = sorted(show.items(), key=lambda kv: -blend(dict(kv[1], at=first[kv[0]]), now_ms))
    return [i['id'] for _, i in rank][:TICKER_N]


def _test():
    assert OUT_RE.search('Ruled out for Sunday') and OUT_RE.search('Lands on IR') and not OUT_RE.search('Questionable for Monday')
    assert BACK_RE.search('Activated from IR')
    assert tier('nfl', 95) == 2 and tier('nba', 80) == 1 and tier('cfb', 50) == 2 and tier('cbb', 44) == 0 and tier('nhl', None) == 0
    assert clip('a' * 100, 10).endswith('…') and len(clip('a' * 100, 10)) == 10
    assert num(3.0) == '3' and num(2.5) == '2.5'
    H = 3.6e6
    assert abs(blend({'w': 92, 'at': 0}, 24 * H) - 26) < 1e-9 and blend({'w': 70, 'at': 5 * H}, 0) == 30
    tp = ticker_pool([{'id': 'a', 'w': 92, 'at': 0, 'd': '1970-01-01', 't': 'x'}, {'id': 'b', 'w': 92, 'at': H, 'd': '1970-01-01', 't': 'x'},
                      {'id': 'c', 'w': 62, 'at': 31 * H, 'd': '1970-01-02', 't': 'y'}, {'id': 'd', 'w': 59, 'at': 30 * H, 'd': '1970-01-02', 't': 'z'}], 31 * H)
    assert tp == ['c', 'b'], tp   # b is shown, aged from a (its first report)
    st = {}
    a = fv_moves(st, '2026-01-01', 0)
    assert st['fv']['d'] == '2026-01-01' and all(abs(float(i['s'].split()[1].replace('−', '-').replace('+', ''))) >= 2 for i in a)
    b = fv_moves(st, '2026-01-01', 0)
    assert len(b) == len(a)
    d = build({}, plays={})
    assert all(i['id'] and i['t'] and i['href'].startswith('/') and 0 <= i['w'] <= 100 for i in d['items'])
    assert len({i['id'] for i in d['items']}) == len(d['items'])
    assert not any('franchise' in json.dumps(i).lower() for i in d['items'])
    assert all(len(x['top']) <= 10 and len(set(x['top'])) == len(x['top']) for x in d['days'])
    assert roundup([{'id': str(k), 'w': 70, 'at': k, 'cat': 'c', 'tag': 't'} for k in range(9)]) == [str(k) for k in range(8, -1, -1)]
    assert roundup([{'id': str(k), 'w': 70 if k < 5 else 60, 'at': k, 'cat': 'a' if k < 5 else 'b', 'tag': str(k)} for k in range(14)])[:4] == ['4', '3', '2', '1']
    print('news ok: %d items, %d major' % (len(d['items']), sum(i['w'] >= MAJOR for i in d['items'])))


if __name__ == '__main__':
    if '--test' in sys.argv:
        _test(); sys.exit(0)
    state = load(os.path.relpath(STATE, ROOT), {}) or {}
    data = build(state)
    old = load('data/news.json') or {}
    if all(old.get(k) == data[k] for k in ('major', 'ticker', 'days', 'items')):
        print('news: no change')   # the file (and its asof) stays, so the run adds no site build
    else:
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
            f.write('\n')
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    print('news: %d items (%d major), %d days' % (len(data['items']), sum(i['w'] >= MAJOR for i in data['items']), len(data['days'])))
