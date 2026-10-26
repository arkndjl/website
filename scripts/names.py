"""Player names across sources, every sport: one key and one matcher so ESPN, Barttorvik, On3, 247, PFN, CFBD,
nflverse, Basketball-Reference and the draft boards land on the same player. scripts/names.mjs is the same code for
the Node scripts (keep the two in step; `python3 scripts/names.py --test` and `node scripts/names.mjs --test` run
the same cases).

    key(name)        the exact key: accents folded (Joksimović = Joksimovic), case, periods and apostrophes dropped
                     (T.J. = TJ, D'Andre = DAndre), hyphens as spaces, spaced initials joined (A. J. = AJ), suffixes
                     dropped (Jr., III), and the hand-kept aliases in data/name_aliases.json applied (Neo Avdalas =
                     Neoklis Avdalas)
    same(a, b)       could the two names be the same player: equal keys, or the same last name with first names that
                     fit (a nickname pair, Chris = Christopher, matching initials), or one letter off in a long last name
    Matcher(rows)    index one source; .find(name, team=, pos=, cls=, id=) returns the one row that fits, or None.
                     Stages, first that gives exactly one: stable id; key + team; key alone (unique in the pool);
                     same() + team; same() alone (unique, and position/class don't contradict). Two different players
                     sharing a name never merge: a key held by two rows needs the team (or id) to pick one.
"""
import html, json, os, re, sys, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALIAS_FILE = os.path.join(ROOT, 'data', 'name_aliases.json')

# letters NFKD leaves alone
_LETTERS = str.maketrans({'ø': 'o', 'Ø': 'o', 'ł': 'l', 'Ł': 'l', 'đ': 'd', 'Đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss',
                          'æ': 'ae', 'Æ': 'ae', 'œ': 'oe', 'Œ': 'oe', 'ı': 'i', 'ħ': 'h'})
SUFFIX = {'jr', 'sr', 'ii', 'iii', 'iv', 'v', 'vi', 'll', 'lll'}       # ll: II typed with lowercase Ls (Brian Blades ll)
# first-name groups (data/name_aliases.json "nicknames"): any two names in a group are the same first name
_data = None


def _load():
    global _data
    if _data is None:
        try:
            _data = json.load(open(ALIAS_FILE, encoding='utf-8'))
        except (OSError, ValueError):
            _data = {}
    return _data


NICK = _load().get('nicknames', [])
_NICKOF = {}
for _i, _g in enumerate(NICK):
    for _n in _g: _NICKOF.setdefault(_n, set()).add(_i)

_aliases = None


def aliases():
    """data/name_aliases.json: groups of spellings that are one player (beyond what the rules catch), keyed once.
    Each group's first spelling is the canonical one."""
    global _aliases
    if _aliases is None:
        _aliases = {}
        for g in _load().get('players', []):
            names = g['names'] if isinstance(g, dict) else g
            canon = _base(names[0])
            for n in names[1:]: _aliases[_base(n)] = canon
    return _aliases


def fold(s):
    """accents and case folded, html entities decoded"""
    s = html.unescape(str(s or '')).translate(_LETTERS)
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c)).lower()


def tokens(s):
    s = re.sub(r"[.'`’‘ʻ]", '', fold(s).replace('.', '. '))   # "A.J." -> "a j" -> joined below
    t = re.sub(r'[^a-z0-9]+', ' ', s).split()
    # a run of single letters is one set of initials: "a j brown" -> "aj brown"
    out, run = [], ''
    for w in t:
        if len(w) == 1: run += w; continue
        if run: out.append(run); run = ''
        out.append(w)
    if run: out.append(run)
    while len(out) > 2 and out[-1] in SUFFIX: out.pop()
    if len(out) == 2 and out[-1] in SUFFIX and out[-1] != 'v': out.pop()
    return out


def _base(s): return ' '.join(tokens(s))


def key(s):
    b = _base(s)
    return aliases().get(b, b)


def parts(s):
    """(first, last) of the key"""
    t = key(s).split()
    if not t: return '', ''
    return (' '.join(t[:-1]), t[-1])


def _one_off(a, b, least=6):
    """one edit apart (a typo: Mestemaker / Mestamaker), only for longer names"""
    if a == b: return True
    if min(len(a), len(b)) < least or abs(len(a) - len(b)) > 1: return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    if len(a) > len(b): a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]: i += 1
    return a[i:] == b[i + 1:]


def first_fits(f, g):
    """2: the same first name (equal, a nickname pair, an alias, matching initials), 1: one letter off (Jalen / Jaylen,
    a typo or a second spelling, only trusted with the team), 0: no"""
    if f == g: return 2
    f0, g0 = f.split(), g.split()
    if not f0 or not g0: return 0
    a, b = f0[0], g0[0]            # middle names drop out of some sources
    if a == b: return 2
    if _NICKOF.get(a, set()) & _NICKOF.get(b, set()): return 2
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) >= 5 and l.startswith(s): return 2      # Christian / Christiaan
    ia, ib = ''.join(w[0] for w in f0), ''.join(w[0] for w in g0)
    if len(a) <= 3 and len(b) <= 3 and (a == ib or b == ia): return 2
    if a[0] == b[0] and _one_off(a, b, 4): return 1      # Jalen / Jaylen; Devin / Kevin are two names
    if len(s) >= 3 and l.startswith(s): return 1      # Tre / Trevon, but also Dan / Dante: only with the team
    if len(s) == 1 and l.startswith(s): return 1      # a lone initial (tennis feeds' "Sinner J."): only with the team
    if len(f0) == 1 and 2 <= len(a) <= 3 and a == ib: return 1    # initials of two first names (J. M. = Juan Manuel)
    if len(g0) == 1 and 2 <= len(b) <= 3 and b == ia: return 1
    return 0


def strength(a, b):
    """how well two names agree: 3 the same key, 2 the same player by the rules (nickname, initials, a shortened
    two-part surname), 1 a one-letter difference (trust it only with the team), 0 different players"""
    ka, kb = key(a), key(b)
    if not ka or not kb: return 0
    if ka == kb or ka.replace(' ', '') == kb.replace(' ', ''): return 3      # De Vante / DeVante
    ta, tb = ka.split(), kb.split()
    if len(ta) < 2 or len(tb) < 2: return 0
    f, l, g, m = ' '.join(ta[:-1]), ta[-1], ' '.join(tb[:-1]), tb[-1]
    if l == m: return first_fits(f, g)
    # one source keeps a two-part surname whole or joined (Smith-Njigba / Smith Njigba / SmithNjigba), or one of its
    # parts (Smith-Reed / Smith, Hayes-Davis / Hayes): a part alone is only trusted with the team
    if len(ta) == 3 and ' '.join(ta[1:]) == ' '.join(tb[1:]) and len(tb) == 3: return first_fits(ta[0], tb[0])
    if len(ta) == 3 and ta[1] + ta[2] == m and ta[0] == g: return 3
    if len(tb) == 3 and tb[1] + tb[2] == l and tb[0] == f: return 3
    if min(len(l), len(m)) >= 6 and _one_off(l, m): return min(1, first_fits(f, g))   # Underwood / Underwod
    if (len(ta) == 3 and ta[1] == m and ta[0] == g) or (len(tb) == 3 and tb[1] == l and tb[0] == f): return 1   # Hayes-Davis / Hayes
    return 0


def same(a, b): return strength(a, b) >= 2


# school short forms the boards and feeds use
TEAM_ALIAS = {'uconn': 'connecticut', 'olemiss': 'mississippi', 'lsu': 'louisianastate', 'usc': 'southerncalifornia',
              'byu': 'brighamyoung', 'smu': 'southernmethodist', 'tcu': 'texaschristian', 'ucf': 'centralflorida',
              'unlv': 'nevadalasvegas', 'vcu': 'virginiacommonwealth', 'unc': 'northcarolina', 'uva': 'virginia',
              'pitt': 'pittsburgh', 'umass': 'massachusetts', 'utep': 'texaselpaso', 'utsa': 'texassanantonio',
              'fiu': 'floridainternational', 'fau': 'floridaatlantic', 'miamifl': 'miami', 'miamiflorida': 'miami',
              'stjohns': 'saintjohns', 'stmarys': 'saintmarys', 'ncstate': 'northcarolinastate', 'gatech': 'georgiatech',
              'washst': 'washingtonstate', 'mizzou': 'missouri', 'cal': 'california', 'ucberkeley': 'california',
              'texasam': 'texasam', 'tamu': 'texasam', 'unm': 'newmexico', 'uh': 'houston', 'etsu': 'easttennesseestate',
              'fgcu': 'floridagulfcoast', 'liu': 'longisland', 'uab': 'alabamabirmingham', 'ucsb': 'ucsantabarbara'}


def team_key(s):
    t = fold(s).replace('&', '').replace("'", '')
    t = re.sub(r'^st\.?\s', 'saint ', t)                       # St. John's, St. Mary's
    t = re.sub(r'\bst\b\.?', 'state', re.sub(r'^n\.?\s', 'north ', re.sub(r'^s\.?\s', 'south ', t)))
    t = re.sub(r'\buniv(ersity)?\b|\bof\b|\bthe\b|\bu\b', ' ', t)
    t = re.sub(r'[^a-z0-9]', '', t)
    return TEAM_ALIAS.get(t, t)


def same_team(a, b):
    """the same school or club, by its key (abbreviations through TEAM_ALIAS); Michigan and Michigan State differ"""
    return bool(a) and bool(b) and team_key(a) == team_key(b)


_POSGRP = {'QB': 'QB', 'RB': 'RB', 'FB': 'RB', 'HB': 'RB', 'WR': 'WR', 'TE': 'TE', 'OL': 'OL', 'OT': 'OL', 'T': 'OL', 'G': 'OL', 'OG': 'OL',
           'C': 'OL', 'IOL': 'OL', 'DL': 'DL', 'DT': 'DL', 'NT': 'DL', 'DE': 'DL', 'EDGE': 'DL', 'LB': 'LB', 'ILB': 'LB', 'OLB': 'LB',
           'SWR': 'WR', 'CB': 'DB', 'S': 'DB', 'SAF': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB', 'NCB': 'DB', 'K': 'K', 'P': 'K', 'LS': 'K', 'ATH': None,
           'ED': 'DL', 'IDL': 'DL', 'DI': 'DL', 'LT': 'OL', 'RT': 'OL', 'LG': 'OL', 'RG': 'OL', 'MLB': 'LB', 'WLB': 'LB', 'SLB': 'LB', 'HB': 'RB', 'PK': 'K'}


def pos_fits(a, b, sport='football'):
    """positions that don't contradict: football groups with the usual moves (edge to LB, safety to LB, athlete
    anywhere); basketball always fits (G/F/C labels move too much between sources)"""
    if not a or not b or sport != 'football': return True
    x, y = _POSGRP.get(str(a).upper().split('/')[0]), _POSGRP.get(str(b).upper().split('/')[0])
    if x is None or y is None or x == y: return True
    near = {frozenset(p) for p in (('DL', 'LB'), ('LB', 'DB'), ('RB', 'WR'), ('WR', 'DB'), ('TE', 'WR'), ('TE', 'OL'), ('DL', 'OL'), ('RB', 'DB'), ('QB', 'WR'))}
    return frozenset((x, y)) in near


class Matcher:
    """rows: dicts; name/team/pos/cls/id fields named by the arguments. .find() returns (row, how) or (None, None)."""

    def __init__(self, rows, name='name', team='team', pos='pos', cls=None, id=None, sport='football', team_eq=None):
        self.rows, self.f, self.sport = list(rows), dict(name=name, team=team, pos=pos, cls=cls, id=id), sport
        self.team_eq = team_eq or same_team        # (wanted team, row's team) -> bool
        self.by_key, self.by_last, self.by_id = {}, {}, {}
        for r in self.rows:
            n = self._get(r, 'name')
            if not n: continue
            self.by_key.setdefault(key(n), []).append(r)
            t = key(n).split()
            if t: self.by_last.setdefault(t[-1], []).append(r)
            if len(t) == 3: self.by_last.setdefault(t[1], []).append(r)      # a two-part surname under its first part too
            i = self._get(r, 'id')
            if i not in (None, ''): self.by_id.setdefault(str(i), []).append(r)
        self.lasts = list(self.by_last)

    def _get(self, r, f):
        k = self.f[f]
        if k is None: return None
        return k(r) if callable(k) else r.get(k)

    def _fit(self, r, pos, cls):
        if pos and not pos_fits(pos, self._get(r, 'pos'), self.sport): return False
        c = self._get(r, 'cls')
        if cls is not None and c is not None and callable(cls): return cls(c)
        return True

    def candidates(self, name, least=1):
        """rows whose name agrees with this one at strength >= least (below an exact key)"""
        t = key(name).split()
        if not t: return []
        last = t[-1]
        pool = list(self.by_last.get(last, []))
        if len(t) == 3: pool += self.by_last.get(t[1], [])
        if len(last) >= 6:
            for l2 in self.lasts:
                if l2 != last and abs(len(l2) - len(last)) <= 1 and l2[:1] == last[:1] and _one_off(l2, last): pool += self.by_last[l2]
        seen, out = set(), []
        for r in pool:
            if id(r) in seen: continue
            seen.add(id(r))
            s = strength(name, self._get(r, 'name'))
            if least <= s < 3: out.append(r)
        return out

    def find(self, name, team=None, pos=None, cls=None, id=None, cross_team='exact'):
        """the one row that is this player, as (row, how), or (None, None).
        cross_team: when the row's team differs from `team` (a transfer, or a source with stale teams), accept
        'exact' names only (the default), 'variant' spellings too (nickname-level, never a typo), or 'none'."""
        if id not in (None, '') and str(id) in self.by_id:
            c = self.by_id[str(id)]
            if len(c) == 1: return c[0], 'id'
        # a row that carries a different id is another player, whatever the name says
        ok = (lambda r: self._get(r, 'id') in (None, '') or str(self._get(r, 'id')) == str(id)) if id not in (None, '') else (lambda r: True)
        exact = [r for r in self.by_key.get(key(name), []) if ok(r)]
        has_team = team and self.f['team'] is not None
        if has_team:
            c = [r for r in exact if self.team_eq(team, self._get(r, 'team'))]
            if len(c) == 1: return c[0], 'name+team'
            if len(c) > 1:
                c = [r for r in c if self._fit(r, pos, cls)]
                return (c[0], 'name+team') if len(c) == 1 else (None, None)
            var = [r for r in self.candidates(name) if self.team_eq(team, self._get(r, 'team')) and ok(r)]
            if len(var) == 1 and self._fit(var[0], pos, cls): return var[0], 'variant+team'
        if has_team and cross_team == 'none':
            return None, None
        if len(exact) > 1:
            # two players with this name: only the team, an id or a position/class that fits just one can pick
            c = [r for r in exact if self._fit(r, pos, cls)] if (pos or cls) else []
            return (c[0], 'name+pos') if len(c) == 1 else (None, None)
        if len(exact) == 1:
            return (exact[0], 'name') if self._fit(exact[0], pos, cls) else (None, None)
        if not has_team or cross_team == 'variant':
            var = [r for r in self.candidates(name, least=2) if ok(r)]
            if len(var) == 1 and self._fit(var[0], pos, cls): return var[0], 'variant'
        return None, None


def _test():
    eq = [('Neo Avdalas', 'Neoklis Avdalas'), ('T.J. Watt', 'TJ Watt'), ('A. J. Brown', 'AJ Brown'), ('Nikola Jokić', 'Nikola Jokic'),
          ('Nikola Joksimović', 'Nikola Joksimovic'), ("D'Andre Swift", 'DAndre Swift'), ('Marvin Harrison Jr.', 'Marvin Harrison'),
          ('Kenneth Walker III', 'Kenneth Walker'), ('Jaxon Smith-Njigba', 'Jaxon Smith Njigba'), ('Luka Dončić', 'Luka Doncic')]
    for a, b in eq: assert key(a) == key(b), (a, b, key(a), key(b))
    same_ok = [('Sammy Brown', 'Samuel Brown'), ('Chris Bell', 'Christopher Bell'), ('Mike Washington', 'Michael Washington'),
               ('Cam Coleman', 'Cameron Coleman'), ('Nick Singleton', 'Nicholas Singleton'),
               ('Jaxon Smith-Njigba', 'Jaxon Njigba')]
    for a, b in same_ok: assert same(a, b), (a, b)
    assert key('Brian Blades ll') == key('Brian Blades II') and strength('Sylvester Smith-Reed', 'Sylvester Smith') == 1
    assert strength('Will Holmes', 'William Holmes') == 2 and strength('Devin Jackson', 'Devon Jackson') == 1 and strength('Devin Henderson', 'Kevin Henderson') == 0
    assert strength('Bryce Underwood', 'Bryce Underwod') == 1 and strength('Jalen Smith', 'Jaylen Smith') == 1
    diff = [('Josh Allen', 'Jordan Allen'), ('Chris Bell', 'Charles Bell'), ('Malik Brown', 'Malachi Brown'), ('AJ Green', 'AJ Greene'),
            ('Will Anderson', 'Wyatt Anderson'), ('Dan Jackson', 'Dante Jackson'), ('Dave Smith', 'Davion Smith'),
            ('Jalen Smith', 'Jaylen Smith')]
    for a, b in diff: assert not same(a, b), (a, b)
    m = Matcher([{'name': 'Josh Allen', 'team': 'Buffalo'}, {'name': 'Josh Allen', 'team': 'Jacksonville'},
                 {'name': 'Neoklis Avdalas', 'team': 'Virginia Tech'}])
    assert m.find('Josh Allen')[0] is None and m.find('Josh Allen', 'Jacksonville')[0]['team'] == 'Jacksonville'
    assert m.find('Neo Avdalas', 'North Carolina')[0]['team'] == 'Virginia Tech'   # an alias: the same key
    m2 = Matcher([{'name': 'Samuel Brown', 'team': 'Miami'}, {'name': 'Jaylen Smith', 'team': 'Ohio State'}])
    assert m2.find('Sammy Brown', 'Miami')[1] == 'variant+team'
    assert m2.find('Sammy Brown', 'Houston')[0] is None and m2.find('Sammy Brown', 'Houston', cross_team='variant')[1] == 'variant'
    assert m2.find('Jalen Smith', 'Ohio State')[1] == 'variant+team' and m2.find('Jalen Smith', 'Iowa', cross_team='variant')[0] is None
    assert strength('J. M. Cerundolo', 'Juan Manuel Cerundolo') == 1 and strength('J. Sinner', 'Jannik Sinner') == 1 and strength('J. Sinner', 'Matteo Sinner') == 0
    m3 = Matcher([{'name': 'Jannik Sinner', 'team': 'it'}, {'name': 'Alexander Zverev', 'team': 'de'}, {'name': 'Mischa Zverev', 'team': 'de'}])
    assert m3.find('J. Sinner', 'it')[1] == 'variant+team' and m3.find('J. Sinner', 'fr')[0] is None and m3.find('A. Zverev', 'de')[0]['name'] == 'Alexander Zverev'
    assert same_team('N. Carolina', 'North Carolina') and same_team('UConn', 'Connecticut') and same_team("St. John's", 'Saint Johns')
    assert same_team('Michigan St.', 'Michigan State') and not same_team('Michigan', 'Michigan State') and not same_team('Virginia', 'Virginia Tech')
    print('names.py: ok')


if __name__ == '__main__' and '--test' in sys.argv:
    _test()
