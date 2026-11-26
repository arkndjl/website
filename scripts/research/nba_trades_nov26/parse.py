"""Parse Wikipedia NBA draft pages (2008-2026): each pick's holder, original team (from ... via) and draft-night
acquirer ((traded to X), post-draft trades). Writes scripts/.cache/nba_trades/picks.json"""
import json, os, re, glob
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
C = os.path.join(ROOT, 'scripts', '.cache', 'nba_trades')
T = {'Atlanta': 'ATL', 'Boston': 'BOS', 'Brooklyn': 'BKN', 'New Jersey': 'BKN', 'Charlotte': 'CHA', 'Chicago': 'CHI',
     'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN', 'Detroit': 'DET', 'Golden State': 'GS', 'Houston': 'HOU',
     'Indiana': 'IND', 'L.A. Clippers': 'LAC', 'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC', 'L.A. Lakers': 'LAL',
     'LA Lakers': 'LAL', 'Los Angeles Lakers': 'LAL', 'Memphis': 'MEM', 'Miami': 'MIA', 'Milwaukee': 'MIL', 'Minnesota': 'MIN',
     'New Orleans': 'NO', 'New York': 'NY', 'Oklahoma City': 'OKC', 'Seattle': 'OKC', 'Orlando': 'ORL', 'Philadelphia': 'PHI',
     'Phoenix': 'PHX', 'Los Angeles': None, 'Portland': 'POR', 'Sacramento': 'SAC', 'San Antonio': 'SA', 'Toronto': 'TOR', 'Utah': 'UTAH', 'Washington': 'WSH'}
NICK = {'Hawks': 'ATL', 'Celtics': 'BOS', 'Nets': 'BKN', 'Hornets': None, 'Bobcats': 'CHA', 'Bulls': 'CHI', 'Cavaliers': 'CLE',
        'Mavericks': 'DAL', 'Nuggets': 'DEN', 'Pistons': 'DET', 'Warriors': 'GS', 'Rockets': 'HOU', 'Pacers': 'IND', 'Clippers': 'LAC',
        'Lakers': 'LAL', 'Grizzlies': 'MEM', 'Heat': 'MIA', 'Bucks': 'MIL', 'Timberwolves': 'MIN', 'Pelicans': 'NO', 'Knicks': 'NY',
        'Thunder': 'OKC', 'SuperSonics': 'OKC', 'Magic': 'ORL', '76ers': 'PHI', 'Suns': 'PHX', 'Trail Blazers': 'POR', 'Kings': 'SAC',
        'Spurs': 'SA', 'Raptors': 'TOR', 'Jazz': 'UTAH', 'Wizards': 'WSH'}


def team(s):
    """a wiki link or plain name -> code"""
    s = re.sub(r'<[^>]+>', '', s).strip()
    m = re.match(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', s)
    full = (m.group(1) if m else s).strip()
    if 'Hornets' in full:
        return 'NO' if 'New Orleans' in full else 'CHA'
    for k, v in NICK.items():
        if v and full.endswith(k): return v
    for k, v in T.items():
        if full.startswith(k) and v: return v
    return None


def links(s):
    return [team(x) for x in re.findall(r'\[\[[^\]]+\]\]|(?<![\[|])\b(?:' + '|'.join(map(re.escape, T)) + r')\b', s)]


def strip_refs(s):
    s = re.sub(r'<ref[^>]*/>', '', s)
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.S)
    out, i = [], 0
    while i < len(s):
        if s.startswith('{{refn', i) or s.startswith('{{efn', i) or s.startswith('{{Cref', i):
            d, j = 0, i
            while j < len(s):
                if s.startswith('{{', j): d += 1; j += 2; continue
                if s.startswith('}}', j):
                    d -= 1; j += 2
                    if d == 0: break
                    continue
                j += 1
            i = j; continue
        out.append(s[i]); i += 1
    return ''.join(out)


def refns(s):
    """every {{refn|group=lower-alpha|name=X|text}} -> {X: text}; unnamed get a running key"""
    out, k = {}, 0
    for m in re.finditer(r'\{\{refn\|group=lower-alpha(?:\|name=([^|}]+))?\|', s):
        i, d, j = m.start(), 0, m.start()
        while j < len(s):
            if s.startswith('{{', j): d += 1; j += 2; continue
            if s.startswith('}}', j):
                d -= 1; j += 2
                if d == 0: break
                continue
            j += 1
        body = s[m.end():j - 2]
        nm = (m.group(1) or f'_{k}').strip(); k += 1
        if body.strip() and nm not in out: out[nm] = body
    return out


def parse(y):
    s = open(os.path.join(C, f'w{y}.txt'), encoding='utf-8').read()
    sec = re.split(r'^==\s*Draft selections\s*==', s, flags=re.M)
    sec = sec[1] if len(sec) > 1 else s
    sec = re.split(r'^==[^=]', sec, flags=re.M)[0]
    R = refns(s)
    rows = re.split(r'\n\|-', sec)
    out = []
    for r in rows:
        cells = [c for c in re.split(r'\n[|!]', '\n' + r.strip()) if c.strip()]
        nums = []
        for c in cells[:3]:
            m = re.search(r'(?:\[\[[^\]|]*\|)?(\d{1,2})\]?\]?\s*$', re.sub(r'.*\|', '', c.strip()) if '[[' not in c else c.strip())
            mm = re.findall(r'\b(\d{1,2})\b', re.sub(r'style="[^"]*"', '', c))
            if mm: nums.append(int(mm[-1]))
        tcell = next((c for c in cells if re.match(r'\s*(?:style="[^"]*"\s*\|)?\s*(?:\[\[)?(?:' + '|'.join(map(re.escape, T)) + r')[^|\]]*(?:' + '|'.join(k for k in NICK) + r')', c)), None)
        if tcell is None or len(nums) < 2: continue
        rd, pk = nums[0], nums[1]
        if not (1 <= rd <= 2 and 1 <= pk <= 60): continue
        body = strip_refs(tcell)
        holder = team(re.sub(r'^\s*(?:style="[^"]*"\s*\|)?\s*', '', body).split('<')[0].split('{{')[0].split('(')[0])
        if not holder: continue  # (r'\[\[[^\]]+\]\]', body).group(0))
        frm = re.search(r'\(from (.*?)\)', body)
        orig = links(frm.group(1))[0] if frm and links(frm.group(1)) else holder
        to = None if re.search(r'traded [a-z ]*later', body) else re.search(r'traded (?:back )?to (.*?)\)', body)
        acq = None
        if to:
            L = [x for x in links(to.group(1)) if x]
            acq = L[0] if L else None
        names = [n.strip() for n in re.findall(r'(?:\{\{refn\|group=lower-alpha\|name=|<ref group=lower-alpha name=)"?([^|}/>"]+)', tcell)]
        unn = [b for b in refns(tcell).items() if b[0].startswith('_')]
        notes = [R[n] for n in dict.fromkeys(names) if n in R] + [b for _, b in unn]
        out.append(dict(y=y, pick=pk, rd=rd, holder=holder, orig=orig, acq=acq, raw=body.strip()[:300], notes=notes if acq else []))
    seen = {}
    for o in out: seen.setdefault(o['pick'], o)
    return [seen[k] for k in sorted(seen)]


if __name__ == '__main__':
    allp = []
    for y in range(2008, 2027):
        P = parse(y)
        n = sum(1 for p in P if p['acq'])
        print(y, len(P), 'picks,', n, 'traded on draft night', '| missing', sorted(set(range(1, 61)) - {p['pick'] for p in P})[:10])
        allp += P
    json.dump(allp, open(os.path.join(C, 'picks.json'), 'w'), indent=0)
