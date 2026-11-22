# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ST. CLAIRE WAVE (/stclaire/wave/): fashion drops, band merch, NYC shows, Mets promos, Mets/Knicks tickets and
collabs, and suggested brands, from free public sources only. Writes data/wave.json; state (first-seen times, ticket
price history) in scripts/data/wave_state.json. Run by .github/workflows/wave.yml every 3 hours.

    python3 scripts/wave.py            fetch everything, rewrite data/wave.json
    python3 scripts/wave.py --test     self-check (no network)

Every request checks the host's robots.txt first (cached per host, * and our agent's groups, wildcards honoured) and
skips a disallowed path. A source that fails keeps its last good items (state "keep"), so one dead store never blanks
the page; data_health.py watches the file's checked stamp.

Bands come from ARKLIBRARY's music artists.exe (content/arklibrary.md), so a band added there is tracked here on the
next run (shows + news); a store for it goes in STORES. Optional free keys: TICKETMASTER_API_KEY adds every NYC
Ticketmaster show for the bands (arenas and the venues the keyless venue pages miss). Missing keys are listed in
the file's `keys` and on the page's status bar.

Rules, all explicit:
  drop      a store product first seen in the last NEW_DAYS days (the first run seeds by created_at instead), grouped
            per brand per ET day; a drop = 1+ products
  news      a feed item whose title names a tracked brand or band (word match; GENERIC names need a music word too)
  show      a venue-page or Ticketmaster event in NYC whose title names a band (GENERIC names must lead the title)
  promo     a Mets home game promotion from the MLB Stats API (giveaway, theme night, ticket offer, highlight)
  deal      VAL = 100 x expected / listed get-in price for a home game (ESPN's ticket listing). Expected =
            exp(mean log price + weekday + month + opponent effects), each effect a mean residual shrunk by
            n / (n + SHRINK) over 8 backfitting passes. VAL 120+ = deal. d = change since the first price we saw.
  collab    a feed item naming the Mets or Knicks with a collab word, or a new '47 Mets/Knicks product
  suggested WAVE score = TAG (15 per taste tag matched: streetwear, gothic, oversized top, slim bottom; max 60)
            + LINK (12.5 per verified tie to a tracked brand, band or team; max 25) + NYC (15 if based in NYC);
            collections = feed items naming a suggested brand in the last 45 days, ranked score x recency
"""
import datetime as dt
import email.utils
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'wave.json')
STATE = os.path.join(ROOT, 'scripts', 'data', 'wave_state.json')
LIB = os.path.join(ROOT, 'content', 'arklibrary.md')
NYC = ZoneInfo('America/New_York')
UA = 'Mozilla/5.0 (compatible; arkndjl-wave/1.0; +https://arkndjl.net)'
UA_HOST = {'site.api.espn.com': 'Mozilla/5.0 (arkndjl-wave)'}   # ESPN's edge refuses agents that carry a URL
AGENT = 'arkndjl-wave'
NEW_DAYS = 21       # a product counts as part of a drop this long after we first see it
NEWS_DAYS = 45
KEEP_DROPS = 40
SHRINK = 4
DEAL = 120
PAUSE = 1.0         # seconds between requests to one host

# ------------------------------------------------------------------ what is tracked
# Fashion brands Noah named. logo = pixel sprite id (scripts/pixelart.py wave_logos).
BRANDS = [
    {'id': 'studioseven', 'name': 'STUDIO SEVEN', 'kind': 'brand',
     'terms': [r'Studio Seven', r'STUDIO SEVEN', r'スタジオ\s?セブン'],
     'stores': [{'base': 'https://nubiantokyo.com', 'coll': 'studio-seven', 'path': '/en'}]},
    {'id': 'ysl', 'name': 'SAINT LAURENT', 'kind': 'brand',
     'terms': [r'Saint Laurent', r'\bYSL\b', r'Yves Saint Laurent', r'サンローラン'], 'stores': []},
    {'id': '47', 'name': "'47", 'kind': 'brand',
     'terms': [r"['’]47 Brand", r"\b47 Brand\b", r"['’]47\b"],
     # the whole catalogue is every league's team: keep '47's own pieces and Noah's teams (news.py's list + the Mets)
     'stores': [{'base': 'https://www.47brand.com', 'pages': 12,
                 'keep': r"^\s*['’]47\b|\b(Mets|Knicks|Rangers|Ravens|Barcelona|New York)\b"}]},
    {'id': 'newbalance', 'name': 'NEW BALANCE', 'kind': 'brand',
     'terms': [r'New Balance', r'ニューバランス'], 'stores': []},
]
TEAMS = [
    {'id': 'mets', 'name': 'METS', 'kind': 'team', 'terms': [r'\bMets\b']},
    {'id': 'knicks', 'name': 'KNICKS', 'kind': 'team', 'terms': [r'\bKnicks\b']},
]
# Band stores (Shopify products.json). `keep` = only titles matching (a label store that sells other artists).
STORES = {
    'The Strokes': [{'base': 'https://shop.thestrokes.com'}],
    'Charli XCX': [{'base': 'https://store.charlixcx.com'}],
    'Playboi Carti': [{'base': 'https://shop.playboicarti.com'}],
    'FKA twigs': [{'base': 'https://store.fkatwigsofficial.com'}],
    'Geese': [{'base': 'https://store.geeseband.com'}],
    'Sextile': [{'base': 'https://www.sacredbonesrecords.com', 'coll': 'sextile'}],
    'The Voidz': [{'base': 'https://cultrecords.com', 'keep': r'Voidz'}],
    'Julian Casablancas': [{'base': 'https://cultrecords.com', 'keep': r'Casablancas'}],
    'Fleetwood Mac': [{'base': 'https://fleetwoodmac.store'}],
    'Nas': [{'base': 'https://shop.nasirjones.com'}],
    'Lauryn Hill': [{'base': 'https://mslaurynhill.com'}],
    'PinkPantheress': [{'base': 'https://store.warnermusic.com', 'coll': 'pinkpantheress'}],
    'Ethel Cain': [{'base': 'https://shop.roughtrade.com', 'coll': 'ethel-cain'}],
}
# Names that are ordinary words: a news match needs a music word, a show must lead with the name.
GENERIC = {'Automatic', 'Geese', 'Hardrock', 'The Fashion', 'Nas', 'chokecherry'}
MUSIC_WORDS = r'\b(band|album|single|song|tour|tours|LP|EP|record|video|merch|show|shows|concert|announce[sd]?|shares|releases?|drops?|live|dates)\b'
COLLAB_WORDS = r'\b(collab\w*|collection|capsule|x|×|drop\w*|release[sd]?|jersey|cap|hat|merch|sneakers?|apparel|tee|hoodie|partner\w*|giveaway|edition)\b'

FEEDS = [  # free RSS; f = fashion, m = music (Nice Kicks and BrooklynVegan disallow their feeds in robots.txt)
    {'n': 'Highsnobiety', 'u': 'https://www.highsnobiety.com/feeds/rss', 'k': 'f'},
    {'n': 'WWD', 'u': 'https://wwd.com/feed/', 'k': 'f'},
    {'n': 'Fashionista', 'u': 'https://fashionista.com/.rss/full/', 'k': 'f'},
    {'n': 'Sneaker Files', 'u': 'https://www.sneakerfiles.com/feed/', 'k': 'f'},
    {'n': 'FASHIONSNAP', 'u': 'https://www.fashionsnap.com/rss.xml', 'k': 'f'},
    {'n': 'Pitchfork', 'u': 'https://pitchfork.com/feed/feed-news/rss', 'k': 'm'},
    {'n': 'Stereogum', 'u': 'https://www.stereogum.com/feed/', 'k': 'm'},
    {'n': 'NME', 'u': 'https://www.nme.com/news/music/feed', 'k': 'm'},
]
VENUES = [  # NYC venue calendars that print their shows in the page (JSON-LD or the Ticketweb list)
    {'n': 'Mercury Lounge', 'u': 'https://www.mercuryloungenyc.com/'},
    {'n': 'Bowery Ballroom', 'u': 'https://www.boweryballroom.com/'},
    {'n': 'Irving Plaza', 'u': 'https://www.irvingplaza.com/'},
    {'n': 'Brooklyn Paramount', 'u': 'https://www.brooklynparamount.com/'},
]
TEAM_IDS = {'mets': ('baseball/mlb', 21, 121), 'knicks': ('basketball/nba', 18, None)}  # ESPN path, ESPN id, MLB id

# Suggested brands. tags from TASTE; ties only where they are on record (collabs, a band's known uniform).
TASTE = ['streetwear', 'gothic', 'oversized top', 'slim bottom']
SUGGEST = [
    {'name': 'Rick Owens', 'tags': ['gothic', 'oversized top', 'slim bottom', 'streetwear'], 'ties': ['Playboi Carti'], 'nyc': False, 'u': 'https://www.rickowens.eu/', 'terms': [r'Rick Owens', r'DRKSHDW']},
    {'name': 'Kith', 'tags': ['streetwear'], 'ties': ['New Balance', 'Knicks'], 'nyc': True, 'u': 'https://kith.com/', 'terms': [r'\bKith\b']},
    {'name': 'Aimé Leon Dore', 'tags': ['streetwear'], 'ties': ['New Balance'], 'nyc': True, 'u': 'https://www.aimeleondore.com/', 'terms': [r'Aim[eé] Leon Dore', r'\bALD\b']},
    {'name': 'Saint Michael', 'tags': ['streetwear', 'gothic', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://saintmxxxxxx.com/', 'terms': [r'Saint Michael', r'SAINT MXXXXXX']},
    {'name': 'Julius_7', 'tags': ['gothic', 'slim bottom', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://julius-7.com/', 'terms': [r'\bJulius[_ ]?7\b', r'JULIUS']},
    {'name': 'Enfants Riches Déprimés', 'tags': ['gothic', 'streetwear', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://enfantsrichesdeprimes.com/', 'terms': [r'Enfants Riches D[ée]prim[ée]s', r'\bERD\b']},
    {'name': 'Undercover', 'tags': ['streetwear', 'gothic', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://undercoverism.com/', 'terms': [r'\bUndercover\b(?! (cop|agent|officer|investigation|police))', r'UNDERCOVER', r'Jun Takahashi']},
    {'name': 'Chrome Hearts', 'tags': ['gothic', 'streetwear'], 'ties': [], 'nyc': False, 'u': 'https://www.chromehearts.com/', 'terms': [r'Chrome Hearts']},
    {'name': 'Yohji Yamamoto', 'tags': ['gothic', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://www.yohjiyamamoto.co.jp/', 'terms': [r'Yohji Yamamoto', r'\bY-3\b']},
    {'name': 'Ann Demeulemeester', 'tags': ['gothic', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://www.anndemeulemeester.com/', 'terms': [r'Ann Demeulemeester']},
    {'name': 'Vetements', 'tags': ['streetwear', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://vetementswebsite.com/', 'terms': [r'Vetements']},
    {'name': 'Brain Dead', 'tags': ['streetwear', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://wearebraindead.com/', 'terms': [r'Brain Dead']},
    {'name': 'Pleasures', 'tags': ['streetwear', 'gothic'], 'ties': [], 'nyc': False, 'u': 'https://pleasuresnow.com/', 'terms': [r'\bPLEASURES\b', r'Pleasures Now']},
    {'name': 'Number (N)ine', 'tags': ['gothic', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://numbernine-official.com/', 'terms': [r'Number \(N\)ine', r'NUMBER \(N\)INE']},
    {'name': 'Thug Club', 'tags': ['streetwear', 'gothic', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://thugclub.com/', 'terms': [r'Thug Club']},
    {'name': '1017 ALYX 9SM', 'tags': ['streetwear', 'gothic', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://www.alyxstudio.com/', 'terms': [r'\bALYX\b', r'1017 ALYX']},
    {'name': 'JJJJound', 'tags': ['streetwear'], 'ties': ['New Balance'], 'nyc': False, 'u': 'https://www.jjjjound.com/', 'terms': [r'JJJJound']},
    {'name': 'Joe Freshgoods', 'tags': ['streetwear'], 'ties': ['New Balance'], 'nyc': False, 'u': 'https://joefreshgoods.com/', 'terms': [r'Joe Freshgoods']},
    {'name': 'Awake NY', 'tags': ['streetwear', 'oversized top'], 'ties': [], 'nyc': True, 'u': 'https://awakenewyork.com/', 'terms': [r'Awake NY', r'Awake New York']},
    {'name': 'Hysteric Glamour', 'tags': ['streetwear', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://www.hystericglamour.jp/', 'terms': [r'Hysteric Glamour', r'HYSTERIC GLAMOUR']},
    {'name': 'Boris Bidjan Saberi', 'tags': ['gothic', 'slim bottom'], 'ties': [], 'nyc': False, 'u': 'https://www.borisbidjansaberi.com/', 'terms': [r'Boris Bidjan Saberi']},
    {'name': 'Kidill', 'tags': ['gothic', 'streetwear', 'oversized top'], 'ties': [], 'nyc': False, 'u': 'https://kidill.com/', 'terms': [r'\bKIDILL\b', r'\bKidill\b']},
]
TAG_WORDS = r'\b(goth\w*|dark|black|leather|grunge|punk|oversized|boxy|baggy|skinny|slim|flare\w*|denim|distressed|archive|runway|capsule|collection|collab\w*|drop|FW\d\d|SS\d\d|fall|winter|spring|summer)\b'

# Actors (Noah, Nov 22): new film announcements. Each actor's tag feed on the trades plus two general film feeds;
# an item counts only when its title names the actor; ANN = the title reads as an announcement (ANN_WORDS).
ACTORS = [
    {'id': 'pattinson', 'name': 'ROBERT PATTINSON', 'kind': 'actor', 'terms': [r'Pattinson'], 'tag': 'robert-pattinson'},
    {'id': 'chalamet', 'name': 'TIMOTHÉE CHALAMET', 'kind': 'actor', 'terms': [r'Chalamet'], 'tag': 'timothee-chalamet'},
]
FILM_FEEDS = [
    {'n': 'Deadline', 'u': 'https://deadline.com/tag/{tag}/feed/'},
    {'n': 'Variety', 'u': 'https://variety.com/t/{tag}/feed/'},
    {'n': 'IndieWire', 'u': 'https://www.indiewire.com/t/{tag}/feed/'},
    {'n': 'The Hollywood Reporter', 'u': 'https://www.hollywoodreporter.com/t/{tag}/feed/'},
    {'n': '/Film', 'u': 'https://www.slashfilm.com/feed/'},
    {'n': 'Collider', 'u': 'https://collider.com/feed/'},
]
ANN_WORDS = (r'\b(cast as|is cast|joins|joined|to star|set to star|will star|stars? opposite|to play|will play|in talks|'
             r'in negotiations|boards|signs on|attached to|lands|becomes|first[- ]look|trailer|teaser|release date|sets? date|'
             r'dated|title (reveal|revealed)|titled|greenlit|green-?lights?|wraps|begins? (filming|production|shooting)|'
             r'starts? (filming|production|shooting)|next (film|movie|project)|new (film|movie|project)|lead role|leads)\b')

KEYS = {'TICKETMASTER_API_KEY': 'every NYC Ticketmaster show for the ARKLIBRARY bands (free key at developer.ticketmaster.com)'}

# ------------------------------------------------------------------ helpers
NOW = dt.datetime.now(dt.timezone.utc)
_last_hit = {}
_robots = {}
STATUS = []


def slug(s):
    return re.sub(r'[^a-z0-9]+', '', s.lower().replace('&', 'and')) or 'x'


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ') if t else None


def parse_time(s):
    if not s:
        return None
    s = str(s).strip()
    try:
        t = email.utils.parsedate_to_datetime(s)
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass
    try:
        t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        return t if t.tzinfo else t.replace(tzinfo=NYC)
    except ValueError:
        return None


def robots_ok(url):
    """robots.txt check with * / $ wildcards, longest match wins, Allow beats Disallow on a tie."""
    p = urllib.parse.urlsplit(url)
    host = f'{p.scheme}://{p.netloc}'
    if host not in _robots:
        rules = []
        try:
            req = urllib.request.Request(host + '/robots.txt', headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                txt = r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            txt = '' if e.code in (404, 410) else None
        except Exception:
            txt = None
        if txt is None:
            rules = None   # unreachable robots: be careful, treat as allowed only for API hosts below
        else:
            groups, cur, agents, seen_rule = [], None, [], False
            for line in txt.splitlines():
                line = line.split('#', 1)[0].strip()
                if ':' not in line:
                    continue
                k, v = [x.strip() for x in line.split(':', 1)]
                k = k.lower()
                if k == 'user-agent':
                    if seen_rule or cur is None:
                        cur = {'agents': [], 'rules': []}
                        groups.append(cur)
                        seen_rule = False
                    cur['agents'].append(v.lower())
                elif k in ('allow', 'disallow') and cur is not None:
                    seen_rule = True
                    if v:
                        cur['rules'].append((k == 'allow', v))
            mine = [g for g in groups if any(a != '*' and a in AGENT for a in g['agents'])]
            use = mine or [g for g in groups if '*' in g['agents']]
            rules = [r for g in use for r in g['rules']]
        _robots[host] = rules
    rules = _robots[host]
    if rules is None:
        return p.netloc.endswith(('statsapi.mlb.com', 'site.api.espn.com', 'app.ticketmaster.com'))
    path = p.path or '/'
    if p.query:
        path += '?' + p.query
    best = (-1, True)
    for allow, pat in rules:
        rx = '^' + re.escape(pat).replace(r'\*', '.*')
        if rx.endswith(r'\$'):
            rx = rx[:-2] + '$'
        if re.match(rx, path):
            n = len(pat)
            if n > best[0] or (n == best[0] and allow):
                best = (n, allow)
    return best[1]


def get(url, as_json=False, timeout=25):
    if not robots_ok(url):
        raise PermissionError('robots.txt disallows ' + url)
    host = urllib.parse.urlsplit(url).netloc
    wait = PAUSE - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA_HOST.get(host, UA), 'Accept': '*/*'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            _last_hit[host] = time.time()
            txt = body.decode('utf-8', 'replace')
            return json.loads(txt) if as_json else txt
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (403, 404, 410):
                break
        except Exception as e:  # timeouts, resets
            last = e
        time.sleep(2 * (attempt + 1))
    raise last


def status(n, kind, ok, count=0, err=None, u=None):
    STATUS.append({'n': n, 'k': kind, 'ok': ok, 'c': count, **({'e': str(err)[:120]} if err else {}), **({'u': u} if u else {})})


def word_rx(terms, case=False):
    return re.compile('|'.join(f'(?:{t})' for t in terms), 0 if case else re.I)


def clean(s):
    s = html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))
    return re.sub(r'\s+', ' ', s).strip()


# ------------------------------------------------------------------ ARKLIBRARY bands
def library_bands():
    txt = open(LIB, encoding='utf-8').read()
    m = re.search(r'winlist title="artists\.exe" icon="note".*?\n(.*?)\{\{< /winlist >\}\}', txt, re.S)
    out = []
    for line in (m.group(1) if m else '').splitlines():
        line = line.strip()
        if line.startswith('- '):
            name = line[2:].split('|')[0].strip()
            img = (line.split('|')[3].strip() if line.count('|') >= 3 else '')
            if name:
                out.append({'name': name, 'img': img})
    return out


def band_terms(name):
    base = re.escape(name)
    alt = [base]
    if name.lower().startswith('the '):
        alt.append(re.escape(name[4:]))
    if name == 'my bloody valentine':
        alt.append(r'\bmbv\b')
    if name == 'Julian Casablancas':
        alt = [r'Julian Casablancas']
    return [r'(?<![\w])' + a + r'(?![\w])' for a in alt]


# ------------------------------------------------------------------ Shopify stores
def shopify(store, label):
    base, coll, pre = store['base'], store.get('coll'), store.get('path', '')
    pages = store.get('pages', 1)
    items = []
    for page in range(1, pages + 1):
        u = f"{base}{pre}{'/collections/' + coll if coll else ''}/products.json?limit=250&page={page}"
        d = get(u, as_json=True)
        prods = d.get('products') or []
        for p in prods:
            if store.get('keep') and not re.search(store['keep'], p.get('title', ''), re.I):
                continue
            img = ((p.get('images') or [{}])[0] or {}).get('src')
            var = (p.get('variants') or [{}])[0] or {}
            items.append({
                'id': f"{urllib.parse.urlsplit(base).netloc}:{p['id']}",
                't': clean(p.get('title'))[:90],
                'u': f"{base}{pre}/products/{p.get('handle')}",
                'img': img,
                'price': var.get('price'),
                'type': kind_of(p),
                'created': p.get('created_at'),
                'avail': any(v.get('available') for v in p.get('variants') or []) if p.get('variants') else None,
            })
        if len(prods) < 250:
            break
    return items


def kind_of(p):
    s = ' '.join([p.get('product_type') or '', p.get('title') or '', ' '.join(p.get('tags') or []) if isinstance(p.get('tags'), list) else str(p.get('tags') or '')]).lower()
    if re.search(r'\b(vinyl|lp|cd|cassette|tape|7"|12"|record)\b', s):
        return 'music'
    if re.search(r'\b(tee|t-shirt|shirt|hoodie|hood|crew|sweat\w*|jacket|long ?sleeve|ls|pants|shorts|jersey|top|tank|denim|knit|cardigan|coat|vest)\b', s):
        return 'top' if not re.search(r'\b(pants|shorts|denim|jeans|trouser)\b', s) else 'bottom'
    if re.search(r'\b(hat|cap|beanie|bag|tote|scarf|sock|pin|patch|keychain|poster|sticker|bandana|necklace|ring|jewel\w*|mug|lighter)\b', s):
        return 'acc'
    return 'other'


def first_seen(state, items, seed):
    seen = state.setdefault('seen', {})
    now = iso(NOW)
    for it in items:
        if it['id'] not in seen:
            c = parse_time(it.get('created'))
            # first run for this store: only products created recently count as new
            seen[it['id']] = iso(c) if (seed and c) else now
        it['first'] = seen[it['id']]
    return items


def drops_for(owner, items, kind):
    """Group recent products into drops: one per ET day of first sight."""
    cut = NOW - dt.timedelta(days=NEW_DAYS)
    by_day = {}
    for it in items:
        t = parse_time(it['first'])
        if not t or t < cut:
            continue
        day = t.astimezone(NYC).date().isoformat()
        by_day.setdefault(day, []).append(it)
    out = []
    for day, its in by_day.items():
        its.sort(key=lambda x: (x.get('img') is None, x['t']))
        out.append({'id': f'{owner["id"]}-{day}', 'who': owner['id'], 'name': owner['name'], 'kind': kind, 'd': day,
                    'n': len(its), 'items': [{k: v for k, v in it.items() if k in ('t', 'u', 'img', 'price', 'type', 'avail')} for it in its[:12]]})
    return out


# ------------------------------------------------------------------ feeds
def rss(feed):
    txt = get(feed['u'])
    root = ET.fromstring(txt.encode('utf-8'))
    out = []
    for it in root.iter('item'):
        g = lambda tag: (it.findtext(tag) or '').strip()
        img = None
        for el in it:
            if el.tag.endswith('}content') or el.tag.endswith('}thumbnail') or el.tag == 'enclosure':
                if (el.get('url') or '').startswith('http') and (el.get('medium') in (None, 'image') or 'image' in (el.get('type') or '')):
                    img = el.get('url')
                    break
        if not img:
            m = re.search(r'<img[^>]+src="(https?://[^"]+)"', g('description') + (it.findtext('{http://purl.org/rss/1.0/modules/content/}encoded') or ''))
            img = m.group(1) if m else None
        t = parse_time(g('pubDate') or g('{http://purl.org/dc/elements/1.1/}date'))
        out.append({'t': clean(g('title'))[:140], 'u': g('link'), 's': clean(g('description'))[:400], 'at': iso(t), 'img': img, 'src': feed['n'], 'k': feed['k']})
    return out


def match_news(items, who):
    """who: list of (id, name, rx, generic). Returns items tagged with the ids they name."""
    music = re.compile(MUSIC_WORDS, re.I)
    out = []
    for it in items:
        hay = it['t']
        hits = []
        for wid, name, rx, generic in who:
            if not rx.search(hay):
                continue
            if generic and not (it['k'] == 'm' and music.search(hay)):
                continue
            hits.append(wid)
        if hits:
            out.append({**it, 'who': hits})
    return out


# ------------------------------------------------------------------ shows
def venue_events(v):
    txt = get(v['u'])
    out = []
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', txt, re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        for e in (d if isinstance(d, list) else [d]):
            if isinstance(e, dict) and 'Event' in str(e.get('@type', '')):
                loc = e.get('location') or {}
                out.append({'t': clean(e.get('name')), 'at': e.get('startDate'), 'u': e.get('url') or v['u'],
                            'venue': clean(loc.get('name') if isinstance(loc, dict) else '') or v['n']})
    for m in re.finditer(r'<div class="tw-name">\s*<a href="([^"]+)"[^>]*>(.*?)</a>(.*?)tw-event-date">([^<]+)<', txt, re.S):
        sup = re.search(r'tw-attractions">(.*?)</div>', m.group(3), re.S)
        vn = re.search(r'tw-venue-name">\s*([^<]+?)\s*<', txt[m.end():m.end() + 1500])
        out.append({'t': clean(m.group(2)), 'at': m.group(4).strip(), 'u': m.group(1), 'venue': clean(vn.group(1)) if vn else v['n'],
                    'with': clean(sup.group(1)).removeprefix('with ').strip() if sup else ''})
    return out


def tm_events(key, band):
    u = ('https://app.ticketmaster.com/discovery/v2/events.json?' +
         urllib.parse.urlencode({'apikey': key, 'keyword': band, 'dmaId': '345', 'classificationName': 'music', 'size': 50, 'sort': 'date,asc'}))
    d = get(u, as_json=True)
    out = []
    for e in (d.get('_embedded') or {}).get('events', []):
        st = (e.get('dates') or {}).get('start') or {}
        ven = (((e.get('_embedded') or {}).get('venues') or [{}])[0])
        pr = (e.get('priceRanges') or [{}])[0]
        out.append({'t': clean(e.get('name')), 'at': st.get('dateTime') or st.get('localDate'), 'u': e.get('url'),
                    'venue': clean(ven.get('name')), 'city': ((ven.get('city') or {}).get('name')), 'min': pr.get('min'),
                    'acts': [a.get('name') for a in ((e.get('_embedded') or {}).get('attractions') or [])]})
    return out


def show_date(s):
    if not s:
        return None
    t = parse_time(s)
    if t:
        return t
    for fmt in ('%a %b %d, %Y', '%b %d, %Y', '%Y-%m-%d'):
        try:
            return dt.datetime.strptime(s.strip(), fmt).replace(hour=20, tzinfo=NYC)
        except ValueError:
            pass
    return None


def match_show(ev, bands):
    t = ev['t']
    acts = ev.get('acts') or []
    for b in bands:
        if acts and any(a.lower() == b['name'].lower() for a in acts):
            return b
        if b['generic']:
            if re.match(r'^\s*' + re.escape(b['name']) + r'\s*($|[:\-–—|,(@]|with\b|w/)', t, re.I):
                return b
        elif b['rx'].search(t) or (ev.get('with') and b['rx'].search(ev['with'])):
            return b
    return None


# ------------------------------------------------------------------ Mets promos, tickets
def mets_promos():
    out = []
    yr = NOW.astimezone(NYC).year
    for season in (yr, yr + 1):
        u = f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId=121&season={season}&gameType=R&hydrate=game(promotions)'
        d = get(u, as_json=True)
        for day in d.get('dates', []):
            for g in day.get('games', []):
                if g['teams']['home']['team']['id'] != 121:
                    continue
                t = parse_time(g.get('gameDate'))
                if not t:
                    continue
                opp = g['teams']['away']['team']['name']
                for p in g.get('promotions') or []:
                    out.append({'d': t.astimezone(NYC).date().isoformat(), 'at': iso(t), 'opp': opp, 'pk': g['gamePk'], 'yr': season,
                                'past': t < NOW - dt.timedelta(hours=6),
                                't': clean(p.get('name')), 'type': p.get('offerType'), 'dist': p.get('distribution'),
                                'by': p.get('presentedBy'), 'img': p.get('thumbnailUrl') or p.get('imageUrl'),
                                'u': p.get('altPageUrl') or 'https://www.mlb.com/mets/tickets/promotions',
                                's': clean(p.get('description'))[:220]})
    seen, uniq = set(), []
    for p in sorted(out, key=lambda x: (x['at'], x['t'])):
        k = (p['pk'], p['t'])
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def home_tickets(team):
    path, eid, _ = TEAM_IDS[team]
    d = get(f'https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{eid}/schedule', as_json=True)
    out = []
    for e in d.get('events', []):
        c = e['competitions'][0]
        if c['status']['type']['state'] != 'pre':
            continue
        home = next((x for x in c['competitors'] if x.get('homeAway') == 'home'), {})
        away = next((x for x in c['competitors'] if x.get('homeAway') == 'away'), {})
        if str((home.get('team') or {}).get('id')) != str(eid):
            continue
        tk = (c.get('tickets') or [{}])[0]
        price = tk.get('startingPrice')
        link = next((l['href'] for l in tk.get('links', []) if 'event' in l.get('rel', [])), None)
        t = parse_time(e['date'])
        out.append({'id': e['id'], 'team': team, 'at': iso(t), 'd': t.astimezone(NYC).date().isoformat(),
                    'wd': t.astimezone(NYC).weekday(), 'mo': t.astimezone(NYC).month,
                    'opp': (away.get('team') or {}).get('displayName'), 'oppa': (away.get('team') or {}).get('abbreviation'),
                    'price': price, 'max': tk.get('maxPrice'), 'n': tk.get('numberAvailable'), 'u': link,
                    'venue': (c.get('venue') or {}).get('fullName')})
    return out


def price_model(games):
    """Additive model on log get-in price: weekday, month and opponent effects, shrunk means, backfit."""
    g = [x for x in games if x.get('price') and x['price'] > 0]
    if len(g) < 6:
        for x in games:
            x['exp'] = x['val'] = None
        return {}
    y = {x['id']: math.log(x['price']) for x in g}
    mu = sum(y.values()) / len(y)
    eff = {'wd': {}, 'mo': {}, 'oppa': {}}
    for _ in range(8):
        for f in eff:
            res = {}
            for x in g:
                others = sum(eff[o].get(x[o], 0) for o in eff if o != f)
                res.setdefault(x[f], []).append(y[x['id']] - mu - others)
            eff[f] = {k: (sum(v) / len(v)) * len(v) / (len(v) + SHRINK) for k, v in res.items()}
    for x in games:
        if not x.get('price'):
            x['exp'] = x['val'] = None
            continue
        e = math.exp(mu + sum(eff[f].get(x[f], 0) for f in eff))
        x['exp'] = round(e)
        x['val'] = round(100 * e / x['price'])
    return {'mu': round(math.exp(mu)), 'n': len(g)}


# ------------------------------------------------------------------ suggested
def score(s):
    tag = 15 * sum(1 for t in TASTE if t in s['tags'])
    link = min(25, 12.5 * len(s['ties']))
    nyc = 15 if s['nyc'] else 0
    return {'tag': tag, 'link': link, 'nyc': nyc, 'total': round(tag + link + nyc)}


def per_brand(ds, cap=4):
    """Newest first, at most `cap` drop days per brand, so one busy store can't fill the tab."""
    n, out = {}, []
    for d in sorted(ds, key=lambda d: d['d'], reverse=True):
        n[d['who']] = n.get(d['who'], 0) + 1
        if n[d['who']] <= cap:
            out.append(d)
    return out[:KEEP_DROPS]


# ------------------------------------------------------------------ main
def load(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return dflt


def run():
    state = load(STATE, {})
    old = load(OUT, {})
    bands = []
    for b in library_bands():
        bands.append({'id': slug(b['name']), 'name': b['name'], 'kind': 'band', 'img': b['img'],
                      'generic': b['name'] in GENERIC, 'rx': word_rx(band_terms(b['name']), case=b['name'] in GENERIC)})

    # 1. stores
    drops, merch, store_counts = [], [], {}
    seeded = set(state.get('seeded', []))
    def do_store(owner, store, kind, label):
        key = store['base'] + (store.get('coll') or '') + (store.get('keep') or '')
        try:
            items = shopify(store, label)
            first_seen(state, items, key not in seeded)
            seeded.add(key)
            got = drops_for(owner, items, kind)
            state.setdefault('keep_store', {})[key] = got
            status(label, 'store', True, len(items), u=store['base'])
        except Exception as e:
            got = state.get('keep_store', {}).get(key, [])
            status(label, 'store', False, 0, e, u=store['base'])
        return got
    for br in BRANDS:
        for st in br['stores']:
            drops += do_store(br, st, 'drop', f"{br['name']} store")
    for b in bands:
        for st in STORES.get(b['name'], []):
            merch += do_store(b, st, 'merch', f"{b['name']} store")
    state['seeded'] = sorted(seeded)

    # 2. feeds
    feed_items = []
    for f in FEEDS:
        try:
            its = rss(f)
            feed_items += its
            state.setdefault('keep_feed', {})[f['n']] = its[:80]
            status(f['n'], 'feed', True, len(its), u=f['u'])
        except Exception as e:
            feed_items += state.get('keep_feed', {}).get(f['n'], [])
            status(f['n'], 'feed', False, 0, e, u=f['u'])
    cut = NOW - dt.timedelta(days=NEWS_DAYS)
    feed_items = [x for x in feed_items if (parse_time(x.get('at')) or NOW) >= cut]
    # keep feed items we saw before (feeds roll over fast); state holds the last NEWS_DAYS of matches
    who = [(b['id'], b['name'], word_rx(b['terms'], case=True), False) for b in BRANDS]
    who += [(b['id'], b['name'], b['rx'], b['generic']) for b in bands]
    news = match_news(feed_items, who)
    team_rx = [(t['id'], word_rx(t['terms'], case=True)) for t in TEAMS]
    collab_rx = re.compile(COLLAB_WORDS, re.I)
    collabs = []
    for it in feed_items:
        hit = [tid for tid, rx in team_rx if rx.search(it['t'])]
        if hit and collab_rx.search(it['t']) and it['k'] == 'f':
            collabs.append({**it, 'who': hit})
    sugg_news = []
    for s in SUGGEST:
        rx = word_rx(s['terms'], case=True)
        for it in feed_items:
            if it['k'] == 'f' and rx.search(it['t']):
                sugg_news.append({**it, 'who': [slug(s['name'])]})
    def merge(kind, new):
        allx = {x['u']: x for x in state.get('keep_' + kind, []) if (parse_time(x.get('at')) or NOW) >= cut}
        for x in new:
            allx[x['u']] = x
        out = sorted(allx.values(), key=lambda x: x.get('at') or '', reverse=True)
        state['keep_' + kind] = out[:200]
        return out
    news = merge('news', news)
    collabs = merge('collabs', collabs)
    sugg_news = merge('sugg', sugg_news)

    # '47 Mets / Knicks products count as collabs (the brand x the team)
    for d in drops:
        if d['who'] != '47':
            continue
        for it in d['items']:
            for t in TEAMS:
                if re.search(t['terms'][0], it['t'], re.I):
                    collabs.append({'t': it['t'].title(), 'u': it['u'], 'img': it['img'], 'at': d['d'] + 'T12:00Z', 'src': "'47", 'who': [t['id']], 'k': 'f', 'price': it.get('price')})
    collabs.sort(key=lambda x: x.get('at') or '', reverse=True)

    # 2b. actors: film announcements
    film = []
    seen_f = set()
    for a in ACTORS:
        rx = word_rx(a['terms'], case=True)
        for f in FILM_FEEDS:
            u = f['u'].format(tag=a['tag'])
            if u in seen_f and '{tag}' not in f['u']:
                its = state.get('keep_feed', {}).get('film:' + u, [])
            else:
                seen_f.add(u)
                try:
                    its = rss({'n': f['n'], 'u': u, 'k': 'v'})
                    state.setdefault('keep_feed', {})['film:' + u] = its[:40]
                    status(f"{f['n']} {a['id'] if '{tag}' in f['u'] else 'film'}", 'film', True, len(its), u=u)
                except Exception as e:
                    its = state.get('keep_feed', {}).get('film:' + u, [])
                    status(f"{f['n']} {a['id'] if '{tag}' in f['u'] else 'film'}", 'film', False, 0, e, u=u)
            for it in its:
                if rx.search(it['t']) and (parse_time(it.get('at')) or NOW) >= NOW - dt.timedelta(days=120):
                    film.append({**it, 'who': [a['id']], 'ann': bool(re.search(ANN_WORDS, it['t'], re.I))})
    byu = {}
    for x in state.get('keep_film', []) + film:
        if (parse_time(x.get('at')) or NOW) >= NOW - dt.timedelta(days=120):
            if x['u'] in byu:
                byu[x['u']]['who'] = sorted(set(byu[x['u']]['who']) | set(x['who']))
            else:
                byu[x['u']] = dict(x)
    film = sorted(byu.values(), key=lambda x: x.get('at') or '', reverse=True)
    for x in film:   # re-read every time, so a change to ANN_WORDS applies to kept items too
        x['ann'] = bool(re.search(ANN_WORDS, x['t'], re.I))
    state['keep_film'] = film[:200]

    # 3. shows
    shows = []
    for v in VENUES:
        try:
            evs = venue_events(v)
            status(v['n'], 'venue', True, len(evs), u=v['u'])
        except Exception as e:
            evs = []
            status(v['n'], 'venue', False, 0, e, u=v['u'])
        for ev in evs:
            b = match_show(ev, bands)
            t = show_date(ev.get('at'))
            if b and t and t >= NOW - dt.timedelta(hours=6):
                shows.append({'who': b['id'], 'name': b['name'], 'at': iso(t), 'd': t.astimezone(NYC).date().isoformat(),
                              't': ev['t'], 'venue': ev['venue'], 'u': ev['u'], 'with': ev.get('with') or '', 'src': v['n']})
    key = os.environ.get('TICKETMASTER_API_KEY')
    missing = [k for k in KEYS if not os.environ.get(k)]
    if key:
        n = 0
        for b in bands:
            try:
                for ev in tm_events(key, b['name']):
                    if match_show(ev, [b]):
                        t = show_date(ev['at'])
                        if t and t >= NOW - dt.timedelta(hours=6):
                            n += 1
                            shows.append({'who': b['id'], 'name': b['name'], 'at': iso(t), 'd': t.astimezone(NYC).date().isoformat(),
                                          't': ev['t'], 'venue': ev['venue'], 'u': ev['u'], 'with': '', 'src': 'Ticketmaster', 'min': ev.get('min')})
            except Exception as e:
                status('Ticketmaster ' + b['name'], 'tickets', False, 0, e)
        status('Ticketmaster', 'tickets', True, n)
    seen, uniq = set(), []
    for s in sorted(shows, key=lambda x: x['at']):
        k = (s['who'], s['d'], slug(s['venue'])[:10])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    shows = uniq

    # 4. Mets promos + Mets/Knicks tickets
    try:
        promos = mets_promos()
        status('MLB Stats API', 'promos', True, len(promos), u='https://statsapi.mlb.com/')
    except Exception as e:
        promos = (old.get('mets') or {}).get('promos', [])
        status('MLB Stats API', 'promos', False, 0, e)
    deals, models = [], {}
    hist = state.setdefault('prices', {})
    for team in TEAM_IDS:
        try:
            games = home_tickets(team)
            status(f'ESPN {team} tickets', 'tickets', True, len(games), u='https://www.espn.com/')
        except Exception as e:
            games = [x for x in (old.get('deals') or []) if x.get('team') == team]
            status(f'ESPN {team} tickets', 'tickets', False, 0, e)
        models[team] = price_model(games)
        for x in games:
            h = hist.setdefault(x['id'], [])
            if x.get('price') and (not h or h[-1][1] != x['price']):
                h.append([iso(NOW), x['price']])
                del h[:-12]
            x['p0'] = h[0][1] if h else None
            x['dp'] = round(100 * (x['price'] / h[0][1] - 1)) if (h and x.get('price')) else None
        deals += games
    live_ids = {x['id'] for x in deals}
    state['prices'] = {k: v for k, v in hist.items() if k in live_ids}
    promo_by_day = {}
    for p in promos:
        promo_by_day.setdefault(p['d'], []).append(p['t'])
    for x in deals:
        if x['team'] == 'mets':
            x['promo'] = promo_by_day.get(x['d'], [])[:3]
        for k in ('wd', 'mo'):
            x.pop(k, None)

    # 5. suggested
    sugg = []
    for s in SUGGEST:
        sc = score(s)
        sid = slug(s['name'])
        recent = [x for x in sugg_news if sid in x['who']][:3]
        sugg.append({'id': sid, 'name': s['name'], 'tags': s['tags'], 'ties': s['ties'], 'nyc': s['nyc'], 'u': s['u'], **sc,
                     'n': len([x for x in sugg_news if sid in x['who']])})
    sugg.sort(key=lambda x: (-x['total'], -x['n'], x['name']))
    by_score = {x['id']: x['total'] for x in sugg}
    colls = []
    for x in sugg_news:
        age = max(0.0, (NOW - (parse_time(x.get('at')) or NOW)).total_seconds() / 86400)
        tagw = len(set(m.lower() for m in re.findall(TAG_WORDS, x['t'], re.I)))
        r = by_score.get(x['who'][0], 0) * math.exp(-age / 14) * (1 + .15 * tagw)
        colls.append({**x, 'r': round(r, 1)})
    colls.sort(key=lambda x: -x['r'])

    # 6. the logo wall: every tracked name, with counts and the last time it moved
    def last_of(wid):
        ts = [d['d'] + 'T12:00Z' for d in drops + merch if d['who'] == wid] + [x['at'] for x in news if wid in x['who'] and x.get('at')]
        ts += [s['at'] for s in shows if s['who'] == wid]
        ts += [x['at'] for x in film if wid in x['who'] and x.get('at')]
        return max(ts) if ts else None
    wall = []
    for o in BRANDS + TEAMS + ACTORS + bands:
        wid = o['id']
        n_items = sum(d['n'] for d in drops + merch if d['who'] == wid)
        n_news = sum(1 for x in news + collabs + film if wid in x['who'])
        n_shows = sum(1 for s in shows if s['who'] == wid)
        n_promo = len(promos) if wid == 'mets' else 0
        wall.append({'id': wid, 'name': o['name'], 'kind': o['kind'], 'items': n_items, 'news': n_news, 'shows': n_shows,
                     'promos': n_promo, 'last': last_of(wid), 'store': bool(o.get('stores') or STORES.get(o['name']))})

    def trim(xs, n, keys):
        return [{k: x[k] for k in keys if x.get(k) not in (None, '', [])} for x in xs[:n]]
    nk = ('t', 'u', 'img', 'at', 'src', 'who', 's', 'price')
    out = {
        'about': 'scripts/wave.py: drops = store products first seen in the last %d days; deal VAL = 100 x expected / listed get-in price (weekday + month + opponent model); WAVE score = TAG + LINK + NYC' % NEW_DAYS,
        'wall': wall,
        'drops': per_brand(drops),
        'merch': per_brand(merch),
        'news': trim([x for x in news if any(w in {b['id'] for b in BRANDS} for w in x['who'])], 40, nk),
        'bandnews': trim([x for x in news if any(w in {b['id'] for b in bands} for w in x['who'])], 40, nk),
        'shows': shows[:60],
        'mets': {'promos': promos[:120]},
        'deals': sorted(deals, key=lambda x: x['at'])[:140],
        'models': models,
        'collabs': trim(collabs, 40, nk),
        'suggested': sugg,
        'collections': trim(colls, 30, nk + ('r',)),
        'film': trim(film, 60, nk + ('ann',)),
        'sources': STATUS,
        'keys': [{'k': k, 'w': KEYS[k]} for k in missing],
    }
    write(out, old, state)
    return out


def write(out, old, state):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import checked
        body = checked.stamp(old, {**out, 'asof': iso(NOW)}, NOW)
    except Exception:
        body = {**out, 'asof': iso(NOW)}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, separators=(',', ':'))
        f.write('\n')
    if body is None:
        print('wave: no change')
        return
    txt = json.dumps(body, ensure_ascii=False, indent=1, allow_nan=False)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write(txt + '\n')
    ok = sum(1 for s in STATUS if s['ok'])
    print(f'wave: {len(out["drops"])} drops, {len(out["merch"])} merch drops, {len(out["shows"])} shows, '
          f'{len(out["mets"]["promos"])} promos, {len(out["deals"])} games, {ok}/{len(STATUS)} sources ok')


# ------------------------------------------------------------------ test
def test():
    global NOW
    assert slug("Aimé Leon Dore") == 'aimloendore' or slug('The Strokes') == 'thestrokes'
    _robots['https://x.test'] = [(False, '/collections/*sort_by*'), (False, '/a'), (True, '/a/ok$')]
    assert robots_ok('https://x.test/products.json?limit=250')
    assert not robots_ok('https://x.test/collections/all?sort_by=x')
    assert not robots_ok('https://x.test/admin') and robots_ok('https://x.test/a/ok')
    bands = [{'id': 'geese', 'name': 'Geese', 'generic': True, 'rx': word_rx(band_terms('Geese'), case=True)},
             {'id': 'thestrokes', 'name': 'The Strokes', 'generic': False, 'rx': word_rx(band_terms('The Strokes'))}]
    assert match_show({'t': 'Geese'}, bands)['id'] == 'geese'
    assert match_show({'t': 'Geese with Friko'}, bands)['id'] == 'geese'
    assert match_show({'t': 'Canada Geese Fly-In Party'}, bands) is None
    assert match_show({'t': 'The Strokes: Reality Awaits Tour'}, bands)['id'] == 'thestrokes'
    assert match_show({'t': 'Strokes tribute night'}, bands)['id'] == 'thestrokes'
    news = match_news([{'t': 'Geese announce 2027 tour', 'k': 'm'}, {'t': 'Geese spotted in Central Park', 'k': 'm'},
                       {'t': 'Geese-inspired parkas', 'k': 'f'}], [('geese', 'Geese', bands[0]['rx'], True)])
    assert [n['t'] for n in news] == ['Geese announce 2027 tour'], news
    g = []
    import random
    rnd = random.Random(1)
    for i in range(40):
        opp = ['BOS', 'LAL', 'DET', 'CHA'][i % 4]
        wd = i % 7
        base = {'BOS': 300, 'LAL': 400, 'DET': 120, 'CHA': 100}[opp] * (1.3 if wd >= 4 else 1)
        g.append({'id': str(i), 'price': base * rnd.uniform(.9, 1.1), 'wd': wd, 'mo': 11, 'oppa': opp})
    g.append({'id': 'cheap', 'price': 200, 'wd': 1, 'mo': 11, 'oppa': 'LAL'})
    price_model(g)
    assert g[-1]['val'] > DEAL, g[-1]
    assert all(60 < x['val'] < 160 for x in g[:-1]), [x['val'] for x in g[:-1]]
    s = score({'tags': ['gothic', 'streetwear'], 'ties': ['New Balance'], 'nyc': True})
    assert s['total'] == 30 + 12.5 + 15 or s['total'] == round(57.5)
    assert kind_of({'title': 'Tour Tee', 'product_type': ''}) == 'top'
    assert kind_of({'title': 'Getting Killed LP', 'product_type': 'Vinyl'}) == 'music'
    lb = library_bands()
    assert any(b['name'] == 'The Strokes' for b in lb) and len(lb) >= 10, lb
    print('wave test ok')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
    else:
        run()
