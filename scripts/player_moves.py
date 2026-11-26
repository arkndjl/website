# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Each player's moves, for the MOVES strip on the recruit and player GFX cards (assets/js/gfx.js pcMoves):
commitments, decommitments, flips, signings, reclassifications, visits (the last six), portal entries, transfers and, in the
pro sports, signings, trades, claims and releases. No new outside source: every row comes from a file already in the repo.

  CFB  data/recruit_news.json (247/On3 headlines), scripts/data/cfb_on3_live.json (commit dates, classes being
       recruited), scripts/data/recruit_on3_hist.json.gz + cfb_recruits_cfbd.json.gz (commit dates and schools, signed
       classes), scripts/data/recruit_on3_live.json.gz (visits), data/cfb_portal.json, data/transactions/cfb.json
  CBB  data/recruit_news.json, scripts/data/cbb_recruit_hist.json.gz, recruit_on3_live.json.gz (visits),
       static/data/cbb/portal.json (no dates: the season's year), data/transactions/cbb.json
  NFL, NBA, NHL, soccer  data/transactions/<sport>.json (roster shuttles and practice-squad rows left out)

Headlines and transaction feeds roll off their sources, so rows from them are kept in scripts/data/player_moves_hist.json.gz
and never dropped. Out: static/data/moves/<sport>.json = {asof, t: [team], l: [logo path or 0],
p: {name key (scripts/names.py): [[date, kind, from team index or -1, to team index or -1, class year or 0], ...]}}, oldest
first. The card keeps the rows that belong to the player on it (class year for a recruit, the chain of schools ending at
his team for anyone else), so two players who share a name stay apart.

  python3 scripts/player_moves.py"""
import datetime as dt
import gzip, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names  # noqa: E402

HIST = os.path.join(ROOT, 'scripts', 'data', 'player_moves_hist.json.gz')
OUT = os.path.join(ROOT, 'static', 'data', 'moves')
RECRUIT = ('commit', 'decommit', 'flip', 'sign', 'reclass', 'visit')
PRO_KEEP = {'sign', 'release', 'trade', 'claim', 'transfer', 'exit'}
NO_TEAM = {'no current school', 'free agent', 'none', ''}


def j(p, default=None):
    f = os.path.join(ROOT, p)
    try:
        return json.load(gzip.open(f, 'rt') if f.endswith('.gz') else open(f, encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def slug(s): return re.sub(r'[^a-z0-9]+', '-', names.fold(s)).strip('-')


def team(t):
    t = (t or '').strip()
    return None if t.lower() in NO_TEAM else t


class Book:
    def __init__(self):
        self.ev = {}     # name key -> {(date, kind, from key, to key): [date, kind, from, to, cls]}

    def add(self, name, d, k, fr=None, to=None, cls=None):
        key = names.key(name or '')
        fr, to = team(fr), team(to)
        if not key or not (fr or to or k == 'reclass'): return
        sig = (d or '', k, names.team_key(fr or ''), names.team_key(to or ''))
        self.ev.setdefault(key, {}).setdefault(sig, [d or None, k, fr, to, int(cls) if cls else 0])

    def rows(self, key):
        """oldest first; a commitment a headline and On3 both carry (same school, within 10 days) counts once, as the
        flip when one of them is a flip, at the earlier date"""
        ev = sorted(self.ev[key].values(), key=lambda e: (e[0] or '0000', RECRUIT.index(e[1]) if e[1] in RECRUIT else 9))
        out = []
        for e in ev:
            dup = None
            if e[1] in ('commit', 'flip', 'transfer', 'sign'):
                for o in out:
                    same_kind = o[1] == e[1] or {o[1], e[1]} == {'commit', 'flip'}
                    if same_kind and names.team_key(o[3] or '') == names.team_key(e[3] or '') and near(o[0], e[0], 10 if e[1] != 'sign' else 3): dup = o
            if dup:
                if e[1] == 'flip': dup[1] = 'flip'
                dup[2] = dup[2] or e[2]; dup[4] = dup[4] or e[4]
            elif e[1] == 'decommit' and any(o[1] == 'decommit' and tk(o[2]) == tk(e[2]) and not any(
                    q[1] in ('commit', 'flip') and tk(q[3]) == tk(e[2]) and (q[0] or '') > (o[0] or '') for q in out) for o in out):
                continue            # a later headline on the same decommitment
            else:
                out.append(list(e))
        # On3 dates a commitment at the first pledge: a recruit who later flipped S -> T committed to S that day, not T
        for e in out:
            if e[1] != 'flip' or not e[2]: continue
            for o in out:
                if o[1] == 'commit' and tk(o[3]) == tk(e[3]) and o[0] and e[0] and o[0] < e[0] and not near(o[0], e[0], 10) \
                        and not any(q[1] == 'commit' and tk(q[3]) == tk(e[2]) for q in out): o[3] = e[2]
        vis = [e for e in out if e[1] in ('visit', 'unofficial')]
        return [e for e in out if e not in vis or e in vis[-6:]]


def tk(t): return names.team_key(t or '')


def near(a, b, days):
    if not a or not b: return a == b
    try:
        return abs((dt.date.fromisoformat(a[:10]) - dt.date.fromisoformat(b[:10])).days) <= days
    except ValueError:
        return False


def logos():
    lg = {}
    def put(t, u):
        if t and u: lg.setdefault(names.team_key(t), u)
    for t in j('data/cfb_teams.json').get('teams') or []: put(t.get('team'), t.get('logo'))
    cf, cb = j('data/cfb_recruits.json'), j('data/cbb_recruits.json')
    for t in (cf.get('teams') or []) + (cb.get('teams') or []): put(t.get('team'), t.get('logo'))
    for c in [{'list': cf.get('class') or []}] + (cf.get('future') or []) + (cb.get('classes') or []):
        for r in c.get('list') or []: put(r.get('team'), r.get('logo'))
    for r in j('data/cfb_portal.json').get('moves') or []: put(r.get('from'), r.get('fromLogo')); put(r.get('to'), r.get('toLogo'))
    for x in j('static/data/cbb/portal.json').get('seasons') or []:
        for r in x.get('rows') or []: put(r.get('tm'), r.get('lo'))
    for sp in ('cfb', 'cbb'):
        for n in j('data/recruit_news.json').get(sp) or []: put(n.get('to'), n.get('tl')); put(n.get('fr'), n.get('fl'))
    return lg


def school_slugs():
    """On3 school slug ('georgia-bulldogs') -> the site's team name, from the full names in data/cfb_teams.json"""
    return {slug(t['full']): t['team'] for t in j('data/cfb_teams.json').get('teams') or [] if t.get('full') and t.get('team')}


def site_recruits(sp):
    """{class year: [row]} of the class tabs"""
    d = j(f'data/{sp}_recruits.json'); out = {}
    if sp == 'cfb':
        if d.get('class'): out[int(d['next'])] = d['class']
        for c in d.get('future') or []: out[int(c['year'])] = c.get('list') or []
    else:
        for c in d.get('classes') or []: out[int(c['year'])] = c.get('list') or []
    return out


def volatile(sp):
    """rows from sources that roll off: [name, date, kind, from, to, cls]"""
    out = []
    for n in j('data/recruit_news.json').get(sp) or []:
        k = n.get('k')
        if k in ('commit', 'decommit', 'flip', 'sign', 'reclass', 'portal', 'transfer'):
            out.append([n.get('n'), n.get('d'), k, n.get('fr'), n.get('to'), n.get('cls')])
    college = sp in ('cfb', 'cbb')
    for r in j(f'data/transactions/{sp}.json').get('rows') or []:
        k = r.get('k')
        if k not in PRO_KEEP: continue
        if k == 'exit':
            if not college or not re.search(r'portal', r.get('h') or '', re.I): continue
            k = 'portal'
        if k == 'sign' and re.search(r'extension|extend', r.get('h') or '', re.I): k = 'extend'
        elif k == 'sign' and re.search(r're-?sign|return' if college else r're-?sign', r.get('h') or '', re.I): k = 'resign'
        out.append([r.get('n'), r.get('d'), k, r.get('fr'), r.get('to'), None])
    return out


def build(sp, hist, slugs):
    B = Book()
    old = hist.get(sp) or []
    seen = {json.dumps(r) for r in old}
    for r in volatile(sp):
        if json.dumps(r) not in seen: old.append(r); seen.add(json.dumps(r))
    hist[sp] = old
    for n, d, k, fr, to, cls in old: B.add(n, d, k, fr, to, cls)
    if sp in ('cfb', 'cbb'):
        rec = site_recruits(sp)
        live = j('scripts/data/recruit_on3_live.json.gz').get(sp) or {}
        if sp == 'cfb':
            # commit dates of the classes being recruited: On3's industry table, joined to the class rows by name
            for y, rows in (j('scripts/data/cfb_on3_live.json').get('classes') or {}).items():
                m = names.Matcher(rec.get(int(y)) or [], team=None)
                for o in rows:
                    r, _ = m.find(o[0])
                    if r and r.get('team') and o[7] and (not o[1] or (r.get('home') or '').endswith(o[1])): B.add(r['name'], o[7], 'commit', None, r['team'], y)
            # signed classes: On3's commit date, the school from the CFBD class list
            h3 = j('scripts/data/recruit_on3_hist.json.gz').get('cfb') or {}
            cf = j('scripts/data/cfb_recruits_cfbd.json.gz')
            for y, rows in h3.items():
                m = names.Matcher([{'name': c[0], 'team': c[4]} for c in cf.get(y) or []], team=None)
                for o in rows:
                    r, _ = m.find(o.get('name')) if o.get('cdate') else (None, None)
                    if r and r.get('team'): B.add(r['name'], o['cdate'], 'commit', None, r['team'], y)
            for r in j('data/cfb_portal.json').get('moves') or []:
                if r.get('to'): B.add(r.get('name'), r.get('date'), 'transfer', r.get('from'), r.get('to'))
                elif r.get('from'): B.add(r.get('name'), r.get('date'), 'portal', r.get('from'), None)
        else:
            for r in j('scripts/data/cbb_recruit_hist.json.gz').get('recruits') or []:
                d, t = (r.get('x') or {}).get('commit'), (r.get('college') or {}).get('team')
                if d and t: B.add(r.get('name'), d, 'commit', None, t, r.get('cls'))
            for x in j('static/data/cbb/portal.json').get('seasons') or []:
                for r in x.get('rows') or []:
                    m = re.match(r'from (.+?)(?: \([^)]*\))?$', r.get('sub') or '')
                    if m and r.get('tm'): B.add(r.get('n'), str(int(x['s']) - 1), 'transfer', m.group(1), r['tm'])
        # visits of the uncommitted recruits (official: 'visit'; the rest 'unofficial')
        for y, rows in live.items():
            m = names.Matcher(rec.get(int(y)) or [], team=None)
            for o in rows:
                r, _ = m.find(o.get('name'))
                if not r or (o.get('state') and r.get('home') and not r['home'].endswith(o['state'])): continue
                for v in o.get('visits') or []:
                    if v[0] in slugs and v[2]: B.add(r['name'], v[2], 'visit' if v[1] == 'Official' else 'unofficial', None, slugs[v[0]], y)
    return B


def main():
    hist = j('scripts/data/player_moves_hist.json.gz')
    lg, slugs = logos(), school_slugs()
    os.makedirs(OUT, exist_ok=True)
    asof = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')
    for sp in ('cfb', 'cbb', 'nfl', 'nba', 'nhl', 'soccer'):
        B = build(sp, hist, slugs)
        teams, ti, P = [], {}, {}
        def ix(t):
            if not t: return -1
            k = names.team_key(t)
            if k not in ti: ti[k] = len(teams); teams.append(t)
            return ti[k]
        for key in sorted(B.ev):
            P[key] = [[e[0], e[1], ix(e[2]), ix(e[3]), e[4]] for e in B.rows(key)]
        out = {'asof': asof, 't': teams, 'l': [lg.get(names.team_key(t), 0) for t in teams], 'p': P}
        f = os.path.join(OUT, sp + '.json')
        prev = j(os.path.relpath(f, ROOT))
        if prev and {k: prev.get(k) for k in 'tlp'} == {k: out[k] for k in 'tlp'}: print(sp, 'unchanged'); continue
        json.dump(out, open(f, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(sp, len(P), 'players', sum(len(v) for v in P.values()), 'moves', os.path.getsize(f) // 1024, 'KB')
    with open(HIST, 'wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as fh:      # mtime 0: same rows, same bytes
        fh.write(json.dumps(hist, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8'))


if __name__ == '__main__':
    main()
