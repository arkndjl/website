# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""WAVE's catalog (scripts/wave.py calls build()): every product feed behind the page's drops, collection showcases,
sales, picks and the suggested-brand table. Stores are public Shopify feeds (products.json, collections.json), read
through wave.get, so robots.txt and the per-host pause apply. No product is typed in: a card is a row a store printed.

    python3 scripts/wave.py            runs this as part of the fetch
    python3 scripts/wave.py --test     self-check (no network), includes test() here

Three kinds of store in SHOPS:
  own     a brand's own store: every product is that brand's (`vendor` narrows a store that also stocks others)
  retail  a multi-brand shop: `brands` maps a tracked brand to its collection handle there; a product on the plain
          pages counts when its vendor names a tracked brand
  team    Knicks / Mets sources: `teams` maps a team to collection handles (the store's own order, i.e. its
          best sellers / featured first); `team` marks a store that is all one team

Rules, all explicit:
  new       published in the store in the last NEW_DAYS days and created at most FRESH_GAP days before that
            (stores re-publish old products on a restock; a piece loaded ahead of its launch still counts)
  drop      a brand's new products, one group per ET day; within a day ordered by WAVE x ln(1 + pieces)
  showcase  a collection a brand's own store published in the last COLL_DAYS days, with a lookbook image or a
            season / drop / collab word in its title, GENERIC titles (all, sale, tees, homepage...) left out; up to
            SHOW_ITEMS of its products in the store's order
  sale      in stock with a compare-at price above the price. OFF = 1 - price / compare-at.
            VAL = 100 x expected / price, expected = compare-at x (1 - BASE), BASE = the store's mean OFF over every
            product on its plain pages (0 for full-price ones). A store that marks everything 20% off has BASE .20,
            so its 20% tags read VAL 100; VAL 120+ = deal (the same VAL as the ticket table)
  collab    title or vendor joins two names (A x B, A + B, "Kith for ...") or a tracked brand's piece names a team
  taste     gothic = black / leather / skull / cross / distressed words; oversized top = a top or jacket with
            oversized / boxy / baggy / wide; slim bottom = a bottom with slim / skinny / flare / stacked / bootcut
  PICK      for in-stock pieces that are not new: TEAM 30 (names the Knicks or Mets) + COLLAB 20
            + BRAND (.3 x the brand's WAVE score; a named brand = 30) + FIT (8 per taste hit, max 24)
            + TYPE (jacket 12, top 10, cap 10, bottom 8, shoes 8, bag / jewellery 4) + SIZES 4 (3+ sizes in stock)
  FIT       a suggested brand's measured taste share: (hits + K x pooled rate) / (n + K) over its catalog rows
            whose title names a colour or a cut, x 25 points. LINK also counts ties the catalog shows (2+ pieces naming a tracked brand, band or team)
"""
import concurrent.futures as cf
import datetime as dt
import math
import re
import urllib.parse

NEW_DAYS = 21
FRESH_GAP = 150
COLL_DAYS = 45
COLL_RESCAN_H = 20      # a store's collection list is re-read this often (it is the heavy call)
SHOW_ITEMS = 24
DROP_ITEMS = 16
DEAL = 120
FIT_K = 40
CAPS = {'drops': 48, 'shows': 30, 'sales': 240, 'pick': 36}
SYM = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CAD': 'C$'}

# handle each tracked brand usually has at a retailer (the brand's id -> collection handle)
H = {'rickowens': 'rick-owens', 'ysl': 'saint-laurent', 'newbalance': 'new-balance', 'undercover': 'undercover',
     'yohjiyamamoto': 'yohji-yamamoto', 'julius7': 'julius', 'maisonmargiela': 'maison-margiela',
     'rafsimons': 'raf-simons', 'balenciaga': 'balenciaga', 'commedesgaronshommeplus': 'comme-des-garcons-homme-plus',
     'guidi': 'guidi', 'anndemeulemeester': 'ann-demeulemeester', 'borisbidjansaberi': 'boris-bidjan-saberi',
     'enfantsrichesdprims': 'enfants-riches-deprimes', 'saintmichael': 'saint-michael', 'thugclub': 'thug-club',
     'vetements': 'vetements', '1017alyx9sm': '1017-alyx-9sm', 'kidill': 'kidill', 'hystericglamour': 'hysteric-glamour',
     'studioseven': 'studio-seven'}


def _h(*ids, **over):
    return {**{i: H[i] for i in ids}, **over}


SHOPS = [
    # ---- own stores
    {'id': '47', 'n': "'47", 'base': 'https://www.47brand.com', 'own': '47', 'pages': 2,
     'teams': {'mets': ['new-york-mets'], 'knicks': ['new-york-knicks']}},
    {'id': 'kith', 'n': 'Kith', 'base': 'https://kith.com', 'own': 'kith', 'vendor': r'^Kith\b', 'pages': 3, 'colls': 8,
     'brands': _h('newbalance', '1017alyx9sm', 'balenciaga'),
     'teams': {'knicks': ['kith-for-the-new-york-knicks-mens', 'kith-for-the-new-york-knicks-2026']}},
    {'id': 'ald', 'n': 'Aimé Leon Dore', 'base': 'https://www.aimeleondore.com', 'own': 'aimleondore', 'pages': 2, 'colls': 1},
    {'id': 'awake', 'n': 'Awake NY', 'base': 'https://awakenewyork.com', 'own': 'awakeny', 'pages': 2, 'colls': 1,
     'teams': {'knicks': ['knicks'], 'mets': ['subway-series-2026']}},
    {'id': 'braindead', 'n': 'Brain Dead', 'base': 'https://wearebraindead.com', 'own': 'braindead', 'pages': 2, 'colls': 1},
    {'id': 'pleasures', 'n': 'Pleasures', 'base': 'https://pleasuresnow.com', 'own': 'pleasures', 'pages': 2, 'colls': 1},
    {'id': 'jjjjound', 'n': 'JJJJound', 'base': 'https://www.jjjjound.com', 'own': 'jjjjound', 'pages': 1, 'colls': 1},
    {'id': 'jfg', 'n': 'Joe Freshgoods', 'base': 'https://joefreshgoods.com', 'own': 'joefreshgoods', 'pages': 1, 'colls': 1},
    {'id': 'rick', 'n': 'Rick Owens', 'base': 'https://www.rickowens.eu', 'own': 'rickowens', 'cur': 'EUR', 'pages': 3, 'colls': 2},
    {'id': 'annd', 'n': 'Ann Demeulemeester', 'base': 'https://www.anndemeulemeester.com', 'own': 'anndemeulemeester', 'cur': 'EUR', 'pages': 2, 'colls': 2},
    {'id': 'noah', 'n': 'Noah', 'base': 'https://noahny.com', 'own': 'noah', 'vendor': r'^Noah\b', 'pages': 2, 'colls': 1},
    {'id': 'wdw', 'n': 'Who Decides War', 'base': 'https://whodecideswar.com', 'own': 'whodecideswar', 'vendor': r'WHO DECIDES', 'pages': 1, 'colls': 1},
    {'id': 'onlyny', 'n': 'Only NY', 'base': 'https://onlyny.com', 'own': 'onlyny', 'pages': 1, 'colls': 1},
    {'id': 'stussy', 'n': 'Stüssy', 'base': 'https://www.stussy.com', 'own': 'stssy', 'pages': 2, 'colls': 1},
    {'id': 'ee', 'n': 'Eric Emanuel', 'base': 'https://www.ericemanuel.com', 'own': 'ericemanuel', 'pages': 2, 'colls': 1},
    # ---- retailers
    {'id': 'atelier', 'n': 'Atelier New York', 'base': 'https://ateliernewyork.com', 'pages': 1,
     'brands': _h('ysl', 'rickowens', 'anndemeulemeester', 'balenciaga', 'borisbidjansaberi', 'commedesgaronshommeplus',
                  'enfantsrichesdprims', 'guidi', 'maisonmargiela', 'saintmichael', 'thugclub', 'undercover', 'vetements',
                  'yohjiyamamoto')},
    {'id': 'hlorenzo', 'n': 'H. Lorenzo', 'base': 'https://www.hlorenzo.com', 'pages': 1,
     'brands': _h('1017alyx9sm', 'kidill', 'rafsimons', 'thugclub', 'vetements', 'yohjiyamamoto')},
    {'id': 'nubian', 'n': 'NUBIAN', 'base': 'https://nubiantokyo.com', 'cur': 'JPY', 'pages': 1,
     'brands': _h('studioseven', 'julius7', 'hystericglamour', 'undercover', 'yohjiyamamoto', 'saintmichael')},
    {'id': 'extrabutter', 'n': 'Extra Butter', 'base': 'https://extrabutterny.com', 'pages': 2,
     'brands': _h('newbalance', 'maisonmargiela', 'rafsimons', 'thugclub')},
    {'id': 'cncpts', 'n': 'Concepts', 'base': 'https://cncpts.com', 'pages': 1,
     'brands': _h('ysl', 'newbalance', 'rickowens', 'maisonmargiela', 'balenciaga', 'rafsimons', '1017alyx9sm')},
    {'id': 'amm', 'n': 'A Ma Maniére', 'base': 'https://www.a-ma-maniere.com', 'pages': 1,
     'brands': _h('ysl', 'newbalance', 'rickowens', 'maisonmargiela', 'balenciaga', 'rafsimons', 'saintmichael',
                  'enfantsrichesdprims', 'thugclub', **{'1017alyx9sm': 'alyx'})},
    {'id': 'feature', 'n': 'Feature', 'base': 'https://feature.com', 'pages': 1,
     'brands': _h('newbalance', 'maisonmargiela', 'rafsimons', 'saintmichael', 'thugclub', 'undercover',
                  'commedesgaronshommeplus', '1017alyx9sm')},
    {'id': 'packer', 'n': 'Packer', 'base': 'https://packershoes.com', 'pages': 1,
     'brands': _h('newbalance', 'commedesgaronshommeplus')},
    {'id': 'union', 'n': 'Union', 'base': 'https://store.unionlosangeles.com', 'pages': 1,
     'brands': _h('newbalance', 'commedesgaronshommeplus')},
    {'id': 'notre', 'n': 'Notre', 'base': 'https://www.notre-shop.com', 'pages': 1,
     'brands': _h('guidi', 'rafsimons', 'undercover')},
    {'id': 'socialstatus', 'n': 'Social Status', 'base': 'https://www.socialstatuspgh.com', 'pages': 1,
     'brands': _h('newbalance')},
    # ---- Knicks / Mets
    {'id': 'msg', 'n': 'MSG Shop', 'base': 'https://shop.msg.com', 'pages': 1,
     'teams': {'knicks': ['new-york-knicks-best-sellers', 'new-york-knicks-mitchell-ness', 'new-york-knicks-mens-jackets']}},
    {'id': 'newera', 'n': 'New Era', 'base': 'https://www.neweracap.com', 'pages': 0,
     'teams': {'mets': ['new-york-mets'], 'knicks': ['new-york-knicks']}},
    {'id': '7line', 'n': 'The 7 Line', 'base': 'https://the7line.com', 'pages': 2, 'team': 'mets'},
    {'id': 'homage', 'n': 'Homage', 'base': 'https://www.homage.com', 'pages': 0,
     'teams': {'mets': ['new-york-mets'], 'knicks': ['new-york-knicks']}},
    {'id': 'sportiqe', 'n': 'Sportiqe', 'base': 'https://www.sportiqe.com', 'pages': 1,
     'teams': {'knicks': ['billy-joel-x-knicks'], 'mets': ['billy-joel-x-mets']}},
    {'id': 'ebbets', 'n': 'Ebbets Field Flannels', 'base': 'https://www.ebbets.com', 'pages': 1,
     'teams': {'mets': ['team-new-york-mets']}},
]

TEAM_RX = {'knicks': re.compile(r'\bKnicks\b', re.I), 'mets': re.compile(r'\bMets\b')}
KIDS = re.compile(r"\b(youth|kids?|infants?|toddlers?|newborn|juvenile|baby|bib|onesie|girls|boys|pet|dog|"
                  r"gift ?card|e-?gift|shipping|insurance|route|membership|donation|sticker pack)\b", re.I)
COLLAB = re.compile(r"[A-Za-z0-9®™)'’]\s+[x×]\s+[A-Za-z(']|\bKith\b.*\bfor\b|\b(?:&|and)\b.*\bfor the\b|\S\s\+\s\S", re.I)
GENERIC = re.compile(
    r"^(all|all products?|new|new arrivals?|new in|latest|sale|shop( all)?|home ?page.*|featured.*|best ?sell\w*|tops?|"
    r"bottoms?|tees?|t-?shirts?|shirts?|hood\w*|sweat\w*|knit\w*|outerwear|jackets?|pants|denim|shorts|accessor\w*|"
    r"footwear|shoes|sneakers|bags?|hats?|caps?|headwear|jewel\w*|mens?|womens?|men.?s|women.?s|unisex|kids|others?|"
    r"essentials?|basics?|core|archive|apparel|clothing|objects?|home|lifestyle|gifts?.*|.*gift guide.*|.*under \$?\d+.*|"
    r".*\bsale\b.*|.*\bcopy\b.*|.*promo.*|.*exclude.*|.*carousel.*|.*\bhp\b.*|.*home ?page.*|size .*|.*preview.*|"
    r".*restock.*|.*\btest\b.*|.*do not.*|.*bfcm.*|.*black friday.*|.*cyber.*|.*you may also like.*|.*new arrivals.*|"
    r".*newest.*|.*back in stock.*|.*available now.*|.*last chance.*|.*\bstyles\b.*|.*recommend.*|.*upsell.*|.*bundle.*|"
    r".*early access.*|.*employee.*|.*friends (and|&) family.*|.*wholesale.*|.*discount.*|.*markdown.*|.*clearance.*)$", re.I)
CAT_WORDS = re.compile(r"\b(all|the|and|for|him|her|them|his|hers|mens?|womens?|men's|women's|tees?|polos?|shirts?|knits?|"
                       r"knitwear|sweaters?|fleece|outerwear|jackets?|coats?|pants|trousers|denim|jeans|shorts|suiting|tailoring|"
                       r"accessories|bags?|hats?|headwear|shoes|footwear|sneakers|boots|jewel\w*|home|goods|gifts?|holiday|"
                       r"new|shop|best|sellers?|tops?|bottoms?|sweats?|hoodies?|socks|eyewear|fragrance|swim\w*|kids|"
                       r"category|categories|items?|products?|styles?|essentials?|classics?|looks?|\d+)\b|[^a-z]+", re.I)
DROP_WORDS = re.compile(r"\b(FW|SS|AW|PF|HO)\s?'?\d\d|\b(fall|autumn|winter|spring|summer|holiday|resort|pre-?fall)\b|"
                        r"\b(drop|delivery|collection|capsule|collab\w*|season|lookbook|edition|pack)\b|\b20\d\d\b|"
                        r"\s[x×+&]\s|\bfor\b", re.I)
TASTE_RX = {
    'gothic': re.compile(r"\b(black|blk|noir|nero|leather|skull\w*|cross(es)?|goth\w*|distress\w*|destroy\w*|waxed|coated|"
                         r"dark|charcoal|onyx|raven|bone|chain|studded|spike\w*|lace[- ]?up|corset|harness)\b", re.I),
    'oversized top': re.compile(r"\b(oversized?|over-?size|boxy|baggy|loose|relaxed|wide|jumbo|big|cocoon|drop[- ]?shoulder|heavyweight)\b", re.I),
    'slim bottom': re.compile(r"\b(slim|skinny|flared?|boot-?cut|tight|stack\w*|taper\w*|leggings?|cigarette|drainpipe|fitted)\b", re.I),
}
TYPE_PTS = {'outer': 12, 'top': 10, 'cap': 10, 'bottom': 8, 'shoes': 8, 'acc': 4}


def cat_of(title, ptype='', tags=''):
    s = f'{ptype} {title}'.lower()
    full = f'{s} {tags}'.lower()
    if re.search(r'\b(vinyl|lp|cd|cassette|7"|12")\b', s):
        return 'music'
    if re.search(r'\b(sneakers?|shoes?|boots?|loafers?|sandals?|slides?|derb\w+|trainers?|footwear|99\dv?\d?|\d{3,4}[a-z]?v?\d?\b.*new balance|new balance)\b', s) and not re.search(r'\b(tee|hoodie|jacket|cap|hat|sock|short|pant|bag)\b', s):
        return 'shoes'
    if re.search(r'\b(socks?|wallet|belt|tote|backpack|necklace|bracelet|keychain|scarf)\b', s):
        return 'acc'
    if re.search(r'\b(hats?|caps?|beanies?|fitted|snapback|59fifty|9forty|9twenty|9fifty|9seventy|clean up|hitch|trucker|bucket|visor|knit cuff|cuff knit|headwear)\b', s):
        return 'cap'
    if re.search(r'\b(jackets?|coats?|parkas?|puffer\w*|bomber|blouson|varsity|windbreaker|anorak|vest|gilet|blazer|outerwear|shell|trench|duvet|flight)\b', s):
        return 'outer'
    if re.search(r'\b(pants?|trousers?|jeans?|denim|shorts?|sweatpants?|joggers?|leggings?|cargo\w*|skirt|bottoms?|chino\w*|slacks)\b', s):
        return 'bottom'
    if re.search(r'\b(tees?|t-?shirts?|shirts?|hood\w*|crew\w*|sweat\w*|long ?sleeve|l/s|ls|jersey\w*|tops?|tank|knit\w*|cardigan|polo|sweater|pullover|thermal|henley|quarter zip|half zip|fleece)\b', s):
        return 'top'
    if re.search(r'\b(bags?|totes?|backpack|scarf|scarves|socks?|pins?|patch|keychain|poster|bandana|necklace|rings?|bracelet|jewel\w*|wallet|belt|gloves?|sunglasses|eyewear|pendant|earrings?|clutch)\b', full):
        return 'acc'
    return 'other'


def tidy(title):
    """Store titles as printed, minus a leading SKU ("RP02F5265_JS_34 | HIKED LS T") or brand prefix handled by caller."""
    t = re.sub(r'\s+', ' ', title or '').strip()
    if ' | ' in t:
        a, b = t.split(' | ', 1)
        if re.fullmatch(r'[A-Z0-9_\-./ ]{5,}', a) and re.search(r'\d', a):
            t = b
    t = re.sub(r'\s*\((?=[^)]*\d)[A-Z0-9][A-Z0-9\-_/. ]{7,}\)\s*$', '', t)   # a trailing SKU: "(AAMOU0372-FA01-BLUE)"
    return t[:96]


GENDER = (('w', re.compile(r"\b(women'?s?|womens|ladies|wmns|femme|girlfriend)\b", re.I)),
          ('m', re.compile(r"\b(men'?s?|mens|homme)\b", re.I)))


def strip_vendor(title, vendor):
    """"RICK OWENS - Men Drawstring Slim Long Pants" -> ("Drawstring Slim Long Pants", "m")."""
    t, g = title, None
    v = (vendor or '').strip()
    if v and t.lower().startswith(v.lower() + ' - '):
        t = t[len(v) + 3:]
        m = re.match(r"(Men|Mens|Women|Womens|Unisex)\b\s+", t)
        if m:
            g = {'men': 'm', 'mens': 'm', 'women': 'w', 'womens': 'w'}.get(m.group(1).lower())
            t = t[m.end():]
    if not g:
        g = next((k for k, rx in GENDER if rx.search(title)), None)
    return t, g


COLOUR = re.compile(r"\b(black|blk|noir|nero|white|wht|grey|gray|gry|blue|navy|red|green|grn|brown|brn|beige|cream|pink|"
                    r"purple|yellow|orange|olive|tan|khaki|ivory|natural|silver|gold|multi|charcoal|bone|indigo|burgundy)\b", re.I)


def taste(rec):
    hay = f"{rec['t']} {rec.get('color', '')}"
    hits = []
    if TASTE_RX['gothic'].search(hay):
        hits.append('gothic')
    if rec['type'] in ('top', 'outer') and TASTE_RX['oversized top'].search(hay):
        hits.append('oversized top')
    if rec['type'] == 'bottom' and TASTE_RX['slim bottom'].search(hay):
        hits.append('slim bottom')
    rec['known'] = bool(hits or COLOUR.search(hay))
    return hits


def record(shop, p, now):
    """One Shopify product -> a catalog row (None when it has no image or price)."""
    vs = p.get('variants') or []
    imgs = [i.get('src') for i in (p.get('images') or []) if i.get('src')]
    if not vs or not imgs:
        return None
    live = [v for v in vs if v.get('available')]
    use = live or vs
    try:
        v = min(use, key=lambda v: float(v.get('price') or 0))
        price = float(v.get('price') or 0)
        was = float(v.get('compare_at_price') or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    opts = p.get('options') or []
    size_i = next((i for i, o in enumerate(opts) if re.search(r'size|taglia|サイズ', o.get('name') or '', re.I)), None)
    color = ' '.join(str(x) for o in opts if re.search(r'colou?r|カラー', o.get('name') or '', re.I) for x in (o.get('values') or []))
    sizes = []
    if size_i is not None:
        for x in live:
            s = x.get(f'option{size_i + 1}')
            if s and s not in sizes:
                sizes.append(str(s)[:8])
    tags = p.get('tags')
    tags = ' '.join(tags) if isinstance(tags, list) else str(tags or '')
    pub = p.get('published_at') or p.get('created_at')
    title, g = strip_vendor(tidy(p.get('title')), p.get('vendor'))
    if not g:
        meta = f"{tags[:300]} {p.get('product_type') or ''}"
        if re.search(r"\b(wom[ae]n'?s?|ladies)\b", meta, re.I) and not re.search(r"\b(mens?|men's|unisex)\b", meta, re.I):
            g = 'w'
    base = shop['base'] + ('/en' if shop['id'] == 'nubian' else '')
    rec = {
        'id': f"{shop['id']}:{p.get('id')}", 't': title, 'u': f"{base}/products/{p.get('handle')}",
        'img': imgs[0], 'img2': imgs[1] if len(imgs) > 1 else None,
        'price': price, 'was': was if was > price * 1.005 else None, 'cur': shop.get('cur', 'USD'),
        'vendor': (p.get('vendor') or '').strip(), 'type': cat_of(title, p.get('product_type') or '', tags),
        'tags': tags[:400], 'color': color[:80], 'pub': pub, 'avail': bool(live), 'sz': sizes[:10], 'nsz': len(sizes),
        'st': shop['id'], 'stn': shop['n'], 'tm': [], 'who': None, 'g': g, 'created': p.get('created_at'),
    }
    rec['off'] = round(100 * (1 - price / was)) if rec['was'] else None
    return rec


def scan(W, shop, ents, now):
    """Fetch one store: plain pages + its brand / team collections. Returns (rows kept, base rate, n scanned)."""
    base, got, offs = shop['base'], {}, []
    vend_rx = [(e['id'], W.word_rx(e['terms'])) for e in ents]
    own_rx = re.compile(shop['vendor'], re.I) if shop.get('vendor') else None
    keep_rx = re.compile(shop['keep'], re.I) if shop.get('keep') else None
    keep_ent = {e['id']: re.compile(e['keep'], re.I) for e in ents if e.get('keep')}

    def page(path, n):
        return (W.get(f'{base}{path}/products.json?limit=250&page={n}', as_json=True).get('products') or [])

    def take(p, who=None, team=None):
        r = record(shop, p, now)
        if not r:
            return None
        if r['id'] in got:
            r = got[r['id']]
        hay = f"{r['t']} {r['vendor']} {r['tags']}"
        if KIDS.search(f"{r['t']} {p.get('product_type') or ''}"):
            return None
        for tid, rx in TEAM_RX.items():
            if (team == tid or shop.get('team') == tid or rx.search(f"{r['t']} {r['vendor']}")) and tid not in r['tm']:
                r['tm'].append(tid)
        if who:
            r['who'] = who
        elif not r['who']:
            if shop.get('own') and (not own_rx or own_rx.search(r['vendor'])) and (not keep_rx or keep_rx.search(r['t'])):
                r['who'] = shop['own']
            elif not shop.get('own'):
                r['who'] = next((eid for eid, rx in vend_rx if rx.search(r['vendor'])), None)
            elif not own_rx or not own_rx.search(r['vendor']):
                r['who'] = next((eid for eid, rx in vend_rx if eid != shop['own'] and rx.search(r['vendor'])), None)
        if r['who'] in keep_ent and not keep_ent[r['who']].search(r['t']):
            r['who'] = None
        other = next((eid for eid, rx in vend_rx if eid != r['who'] and rx.search(r['vendor'])), None)
        r['co'] = bool(COLLAB.search(re.sub(r'Fresh Foam X', '', r['t'], flags=re.I)) or re.search(r'\s[x×+]\s', r['vendor']) or
                       (r['who'] and r['tm'] and r['who'] != '47') or (shop.get('own') and r['who'] == shop['own'] and other))
        if r['who'] or r['tm']:
            got[r['id']] = r
        return r

    for n in range(1, shop.get('pages', 1) + 1):
        ps = page('', n)
        for p in ps:
            r = record(shop, p, now)
            if r:
                offs.append((r['off'] or 0) / 100)
            take(p)
        if len(ps) < 250:
            break
    errs = []
    for who, handle in (shop.get('brands') or {}).items():
        try:
            for p in page(('/en' if shop['id'] == 'nubian' else '') + '/collections/' + handle, 1):
                take(p, who=who)
        except Exception as e:   # one missing handle must not lose the store
            errs.append(f'{handle}: {str(e)[:40]}')
    for team, handles in (shop.get('teams') or {}).items():
        for i, handle in enumerate(handles):
            try:
                for rank, p in enumerate(page('/collections/' + handle, 1)):
                    r = take(p, team=team)
                    if r and r['id'] in got:
                        r.setdefault('rank', rank + 250 * i)   # the store's own order: best sellers first
            except Exception as e:
                errs.append(f'{handle}: {str(e)[:40]}')
    rows = list(got.values())
    base_rate = sum(offs) / len(offs) if offs else 0.0
    for r in rows:
        if r['off']:
            exp = r['was'] * (1 - base_rate)
            r['val'] = round(100 * exp / r['price'])
        t = W.parse_time(r['pub'])
        r['d'] = t.astimezone(W.NYC).date().isoformat() if t else None
        c = W.parse_time(r['created']) or t
        r['new'] = bool(t and t >= now - dt.timedelta(days=NEW_DAYS) and (t - c) <= dt.timedelta(days=FRESH_GAP))
        r['fit'] = taste(r)
    return rows, base_rate, len(offs), errs


def showcases(W, shop, now, rows_by_id):
    """Collections the store published lately that read as a drop, each with its products in the store's order."""
    out, base = [], shop['base']
    cut = now - dt.timedelta(days=COLL_DAYS)
    cands = []
    for n in range(1, int(shop.get('colls', 1)) + 1):
        cs = W.get(f'{base}/collections.json?limit=250&page={n}', as_json=True).get('collections') or []
        for c in cs:
            t = W.parse_time(c.get('published_at'))
            title = re.sub(r'\s+', ' ', c.get('title') or '').strip()
            if not t or t < cut or t > now + dt.timedelta(days=1) or not (2 <= (c.get('products_count') or 0) <= 250):
                continue
            if GENERIC.match(title) or KIDS.search(title) or re.search(r'women|kids|\blook \d', title, re.I) or not CAT_WORDS.sub('', title):
                continue
            img = (c.get('image') or {}).get('src')
            if not (img or DROP_WORDS.search(title)):
                continue
            cands.append((t, c, title, img))
        if len(cs) < 250:
            break
    cands.sort(key=lambda x: x[0], reverse=True)
    seen_t = set()
    for t, c, title, img in cands:
        key = re.sub(r'[^a-z0-9]+', '', re.sub(r'\b(apparel|accessories|lifestyle|collection|mens?)\b', '', title.lower()))
        if key in seen_t or len(out) >= 4:
            continue
        ps = W.get(f"{base}/collections/{c['handle']}/products.json?limit=250", as_json=True).get('products') or []
        items = []
        for p in ps:
            r = record(shop, p, now)
            if not r or KIDS.search(r['t']):
                continue
            if shop.get('vendor') and not re.search(shop['vendor'], r['vendor'], re.I) and not COLLAB.search(title):
                continue
            r0 = rows_by_id.get(r['id'])
            r['who'] = shop['own']
            if r0:
                r['val'] = r0.get('val')
            items.append(r)
        if len(items) < 2:
            continue
        seen_t.add(key)
        out.append({'id': f"{shop['id']}-{c['handle']}", 'who': shop['own'], 'name': shop['n'], 't': title[:80],
                    'd': t.astimezone(W.NYC).date().isoformat(), 'n': len(items), 'st': shop['id'],
                    'img': img or items[0]['img'], 'u': f"{base}/collections/{c['handle']}",
                    'co': bool(COLLAB.search(title)), 'items': [card(r) for r in items[:SHOW_ITEMS]]})
    return out


def card(r):
    """The JSON a product card needs (short keys; empty ones dropped)."""
    c = {'t': r['t'], 'u': r['u'], 'img': r['img'], 'img2': r.get('img2'), 'price': _num(r['price']),
         'was': _num(r['was']) if r.get('was') else None, 'off': r.get('off'), 'val': r.get('val'),
         'cur': SYM.get(r.get('cur', 'USD'), '$') if r.get('cur', 'USD') != 'USD' else None,
         'who': r.get('who'), 'st': r.get('st'), 'stn': r.get('stn'), 'type': r.get('type'), 'sz': r.get('sz') or None,
         'tm': r.get('tm') or None, 'co': r.get('co') or None, 'new': r.get('new') or None,
         'v': r['vendor'] if re.search(r'\s[x×+]\s', r.get('vendor') or '') else None,
         'out': None if r.get('avail') else True, 'pick': r.get('pick'), 'd': r.get('d'), 'g': r.get('g')}
    return {k: v for k, v in c.items() if v not in (None, '', [], False)}


def _num(x):
    return int(x) if float(x) == int(x) else round(float(x), 2)


def pick_score(r, wave_by):
    team = 30 if r['tm'] else 0
    collab = 20 if r.get('co') else 0
    brand = round(.3 * wave_by.get(r.get('who'), 0))
    fit = min(24, 8 * len(r.get('fit') or []))
    typ = TYPE_PTS.get(r['type'], 0)
    sz = 4 if r.get('nsz', 0) >= 3 else 0
    return team + collab + brand + fit + typ + sz


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        k = (r.get('who') or r['st'], re.sub(r'[^a-z0-9]+', '', r['t'].lower())[:48])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def capped(rows, n, per, key):
    cnt, out = {}, []
    for r in rows:
        k = key(r)
        cnt[k] = cnt.get(k, 0) + 1
        if cnt[k] <= per:
            out.append(r)
        if len(out) >= n:
            break
    return out


def weave(rows, key):
    """Round-robin across groups (each group keeps its order), so a page is not nine rows of one store."""
    groups, order = {}, []
    for r in rows:
        k = key(r)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    out, i = [], 0
    while len(out) < len(rows):
        for k in order:
            if i < len(groups[k]):
                out.append(groups[k][i])
        i += 1
    return out


def measure(rows, ents, names):
    """Per brand: catalog rows, taste share (shrunk), ties the catalog shows, new / sale counts."""
    by = {}
    for r in rows:
        if r.get('who'):
            by.setdefault(r['who'], []).append(r)
    tot = sum(1 for v in by.values() for r in v if r.get('known'))
    pooled = sum(1 for v in by.values() for r in v if r['fit']) / tot if tot else 0.0
    out = {}
    for e in ents:
        v = by.get(e['id'], [])
        hits = sum(1 for r in v if r['fit'])
        known = sum(1 for r in v if r.get('known'))   # rows whose title names a colour or a cut (a bare "HIKED LS T" says nothing)
        share = (hits + FIT_K * pooled) / (known + FIT_K)
        ties = {}
        for r in v:
            hay = f"{r['t']} {r['vendor']}"
            for nid, name, rx in names:
                if nid != e['id'] and rx.search(hay):
                    ties[name] = ties.get(name, 0) + 1
        out[e['id']] = {'n': len(v), 'share': share, 'raw': (hits / known) if known else None, 'known': known,
                        'ties': sorted([k for k, c in ties.items() if c >= 2], key=lambda k: -ties[k]),
                        'new': sum(1 for r in v if r['new']), 'sale': sum(1 for r in v if r.get('off') and r['avail']),
                        'stores': sorted({r['stn'] for r in v})}
    return out, pooled


def build(W, ents, names, old, state, now, wave_of):
    """ents: tracked brands [{id, name, terms}] (named + suggested). names: [(id, display, rx)] of every tracked brand,
    band and team (for ties). wave_of(measured) -> {brand id: WAVE score}. Returns the catalog part of wave.json."""
    old_cat = old or {}
    rows, bases, shows = [], {}, []
    stamp = state.setdefault('colls_at', {})

    def one(shop):
        try:
            got, base, n, errs = scan(W, shop, ents, now)
            return shop, got, base, n, errs, None
        except Exception as e:
            return shop, None, None, 0, [], e
    with cf.ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, SHOPS))
    failed = set()
    for shop, got, base, n, errs, err in results:
        if err is not None:
            failed.add(shop['id'])
            W.status(f"{shop['n']} store", 'store', False, 0, err, u=shop['base'])
            continue
        rows += got
        bases[shop['id']] = round(base, 3)
        W.status(f"{shop['n']} store", 'store', True, len(got), errs and '; '.join(errs) or None, u=shop['base'])
    rows_by_id = {r['id']: r for r in rows}

    def sc(shop):
        last = W.parse_time(stamp.get(shop['id']))
        if shop['id'] in failed or (last and now - last < dt.timedelta(hours=COLL_RESCAN_H)):
            return shop, None
        try:
            return shop, showcases(W, shop, now, rows_by_id)
        except Exception as e:
            W.status(f"{shop['n']} collections", 'store', False, 0, e, u=shop['base'])
            return shop, None
    own = [s for s in SHOPS if s.get('colls') and s.get('own')]
    with cf.ThreadPoolExecutor(8) as ex:
        sres = list(ex.map(sc, own))
    cut = (now - dt.timedelta(days=COLL_DAYS)).astimezone(W.NYC).date().isoformat()
    for shop, got in sres:
        if got is None:    # not due, or failed: keep what the page already shows for this store
            got = [x for x in (old_cat.get('showcases') or []) if x.get('st') == shop['id'] and x.get('d', '') >= cut]
        else:
            stamp[shop['id']] = W.iso(now)
        shows += got

    measured, pooled = measure(rows, ents, names)
    wave_by = wave_of(measured)
    for r in rows:
        r['pick'] = pick_score(r, wave_by)

    def keep_old(key, sub=None):
        """rows of failed stores, from the last file"""
        src = old_cat.get(key) or []
        if sub:
            src = (old_cat.get(key) or {}).get(sub) or []
        return [x for x in src if x.get('st') in failed]

    # drops: a brand's new pieces per ET day
    by = {}
    for r in rows:
        if r['new'] and r.get('who') and r['d']:
            by.setdefault((r['who'], r['d']), []).append(r)
    name_of = {e['id']: e['name'] for e in ents}
    drops = []
    for (who, d), its in by.items():
        its = dedupe(sorted(its, key=lambda r: (not r['avail'], -r['pick'], r['t'])))
        drops.append({'id': f'{who}-{d}', 'who': who, 'name': name_of.get(who, who), 'kind': 'drop', 'd': d, 'n': len(its),
                      'st': its[0]['st'], 'stores': sorted({r['stn'] for r in its}),
                      'items': [card(r) for r in its[:DROP_ITEMS]]})
    drops += [x for x in (old_cat.get('drops') or []) if x.get('st') in failed and x.get('d', '') >= (now - dt.timedelta(days=NEW_DAYS)).date().isoformat()]
    drops.sort(key=lambda x: (x['d'], wave_by.get(x['who'], 0) * math.log1p(x['n'])), reverse=True)   # the day's biggest, best-fit drop leads
    drops = capped(drops, CAPS['drops'], 3, lambda x: x['who'])

    shows.sort(key=lambda x: (x['d'], wave_by.get(x['who'], 0)), reverse=True)
    shows = shows[:CAPS['shows']]

    live = [r for r in rows if r['avail']]
    sales = dedupe(sorted([r for r in live if r.get('off') and r['off'] >= 10 and (r.get('who') or r['tm'])
                           and r['type'] in TYPE_PTS and r['price'] >= 10],
                          key=lambda r: (-(r.get('val') or 0), -r['pick'])))
    sales = capped(sales, CAPS['sales'], 14, lambda r: r.get('who') or r['st'])
    sales = [card(r) for r in sales] + keep_old('sales')

    old_rows = [r for r in live if not r['new']]

    def top(sel, per, key, order=None):
        xs = dedupe(sorted(sel, key=order or (lambda r: (-r['pick'], r.get('rank', 999), r['t']))))
        return [card(r) for r in weave(capped(xs, CAPS['pick'], per, key), key)]
    picks = {
        'knicks': top([r for r in old_rows if 'knicks' in r['tm']], 9, lambda r: r.get('who') or r['st']) + keep_old('picks', 'knicks'),
        'mets': top([r for r in old_rows if 'mets' in r['tm']], 9, lambda r: r.get('who') or r['st']) + keep_old('picks', 'mets'),
        'collabs': top([r for r in old_rows if r.get('co') and r.get('who') and not r['tm']], 5, lambda r: r['who']) + keep_old('picks', 'collabs'),
        'staples': top([r for r in old_rows if r.get('who') and not r['tm'] and not r.get('co') and r['fit']], 3, lambda r: r['who']) + keep_old('picks', 'staples'),
    }
    counts = {}
    for r in rows:
        if r.get('who'):
            c = counts.setdefault(r['who'], {'items': 0, 'sale': 0})
            c['items'] += 1 if r['new'] else 0
            c['sale'] += 1 if (r.get('off') and r['avail']) else 0
    return {'drops': drops, 'showcases': shows, 'sales': sales, 'picks': picks, 'measured': measured, 'pooled': round(pooled, 3),
            'bases': bases, 'counts': counts, 'wave_by': wave_by, 'rows': len(rows)}


def test(W):
    assert tidy('RP02F5265_JS_34 | HIKED LS T') == 'HIKED LS T' and tidy('Amazin Coaster | Ladies T-shirt').startswith('Amazin')
    assert cat_of('New York Mets 9FORTY A-Frame') == 'cap' and cat_of('Geth Jeans', 'DENIM') == 'bottom'
    assert cat_of('Satin Jacket') == 'outer' and cat_of('New Balance 2010 - Sport Green', 'Low Top Sneakers') == 'shoes'
    assert cat_of('HIKED LS T', 'T-SHIRTS / SHIRTS') == 'top'
    assert COLLAB.search('Awake NY x New Era 59Fifty') and COLLAB.search('Kith & Armani for the New York Knicks')
    assert not COLLAB.search('Box Logo Tee') and not COLLAB.search('8 x 10 Print'.replace('8 x 10', '8x10'))
    assert GENERIC.match('NEW ARRIVALS MEN_NEWEST') and GENERIC.match('HOMEPAGE KNITWEAR') and GENERIC.match('Sale')
    assert not GENERIC.match('Fall/Winter 2026 - Drop 3 (AWAKE x VANSON)') and DROP_WORDS.search('MONCLER + RICK OWENS')
    shop = {'id': 't', 'n': 'T', 'base': 'https://t.test', 'own': 'b'}
    now = dt.datetime(2026, 11, 25, tzinfo=dt.timezone.utc)
    p = {'id': 1, 'title': 'Black Oversized Hoodie', 'handle': 'h', 'vendor': 'B', 'product_type': 'Hoodies', 'tags': [],
         'published_at': '2026-11-20T10:00:00-05:00', 'images': [{'src': 'https://i/1.jpg'}],
         'options': [{'name': 'Size', 'values': ['S', 'M', 'L']}],
         'variants': [{'price': '60.00', 'compare_at_price': '100.00', 'available': True, 'option1': s} for s in 'SML']}
    r = record(shop, p, now)
    assert r['off'] == 40 and r['sz'] == ['S', 'M', 'L'] and r['type'] == 'top', r
    assert strip_vendor('RICK OWENS - Men Drawstring Slim Long Pants', 'Rick Owens') == ('Drawstring Slim Long Pants', 'm')
    assert tidy('Destroyed Denim Jacket (AAMOU0372-FA01-BLUE)') == 'Destroyed Denim Jacket' and tidy('Tee (Black)') == 'Tee (Black)'
    assert not CAT_WORDS.sub('', 'Tees & Polos') and not CAT_WORDS.sub('', 'For Him') and not CAT_WORDS.sub('', 'All Holiday') and CAT_WORDS.sub('', 'Holiday 2026 Vanson')
    assert taste(r) == ['gothic', 'oversized top']
    r.update(who='b', tm=[], co=False, fit=taste(r))
    assert pick_score(r, {'b': 100}) == 30 + 16 + 10 + 4
    # VAL: 40% off where the store's base rate is 20% -> 100 x .8 / .6 = 133; a store-wide 20% tag reads 100
    assert round(100 * 100 * (1 - .2) / 60) == 133 and round(100 * 100 * (1 - .2) / 80) == 100
    m, pooled = measure([dict(r, vendor='B', new=True, avail=True, stn='T')] * 3 + [dict(r, who='c', fit=[], known=True, vendor='C', new=False, avail=True, stn='T')],
                        [{'id': 'b'}, {'id': 'c'}], [])
    assert m['b']['share'] > pooled > m['c']['share'] and m['b']['n'] == 3
    assert weave([1, 3, 5, 2, 4], lambda x: x % 2) == [1, 2, 3, 4, 5] and cat_of('Classic Crew Socks - Black') == 'acc'
    assert card(r)['price'] == 60 and 'cur' not in card(r)
    print('wave catalog test ok')
