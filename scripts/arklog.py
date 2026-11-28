# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""ARKLOG (Process > ARKLOG, /process/#log): the dated record of every change and test on the site, read from the merged pull requests.

  python3 scripts/arklog.py            rebuild from the cache
  python3 scripts/arklog.py --fetch    first pull the newest merged pull requests (GitHub API; GITHUB_TOKEN if set)
  python3 scripts/arklog.py --all      refetch every page (rebuilds the cache)
  python3 scripts/arklog.py --test     parser self-test
  python3 scripts/arklog.py --month 2026-11   that month's rows as notes, by section and sport (for the monthly Process update)

Nothing here is typed in. Every row is one merged pull request: its merge time, its title, and what its description
says was tested (the held-out number before and after, the t, shipped or failed). The descriptions are cached in
scripts/data/arklog_prs.json.gz (number, title, merged_at, body), so a parser change reruns on all of them.
The reading is by pattern, so it is not trusted on its own. A description's own line
  ARKLOG: shipped · R² .643 to .732 · t = 2.1        (shipped, part shipped or failed; the number and t are optional)
is taken as written. research/arklog_fix.json holds the reviewed reading of a row ({"<pr>": {"v", "e", "tt"}, null drops
a field, {"hide": true} drops the row): every test through #1283 was read against its write-up on Nov 27 2026.

Writes
  static/data/arklog.json   every row, read by layouts/shortcodes/arklog.html in the browser (assets/js/arklog.js)
  data/arklog.json          counts by week / section / sport / area, the newest rows, and the pixel charts (scoreboard, Process overview)

Row: n (pull request), d (merge time, UTC), t (title), sec (site section), sp (sports), ar (area = the Process tab an
ARKBOARD row belongs to),
v (s shipped, f failed, m some of each, '' no test), e [metric, before, after, better] (the held-out number), tt (t),
l [[tag, line]] (the lines of the description that carry numbers), rec (the research record's folder).
Research studies (research/studies) are rows too (k = 'study'), dated by the pull request that added them.
"""
import gzip
import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / 'scripts/data/arklog_prs.json.gz'
FIX = ROOT / 'research/arklog_fix.json'
REPO = 'arkndjl/website'

SPORTS = [  # (tag, pattern on the title; the description is used only when the title names no sport)
    ('CFB', r'\bCFB\b|college football|\bCFP\b|\bFBS\b|\bFCS\b|Heisman|\bportal\b'),
    ('NFL', r'\bNFL\b|quarterback value|fantasy VOR'),
    ('CBB', r'\bCBB\b|college basketball|NCAA tournament|Bracket Matrix|Barttorvik|March Madness'),
    ('NBA', r'\bNBA\b|G League|\bLEBRON\b|\bRAPM\b'),
    ('NHL', r'\bNHL\b|hockey|goalie|\bCHL\b|\bpWAR\b'),
    ('Soccer', r'\bsoccer\b|Understat|FotMob|Transfermarkt|\bxMV\b|\bGAR\b|\bSVAR\b|Ballon|Premier League|national[- ]team'),
    ('Tennis', r'\btennis\b|\bATP\b|\bWTA\b'),
    ('CS2', r'\bCS2\b|\bESEA\b|\bRWA\b|\b1NT\b|Counter-Strike|Pick.?Em|\bHLTV\b|bo3\.gg|FACEIT'),
    ('MLB', r'\bMLB\b|baseball'),
]
# what stays out: pages that are not public (CLAUDE.md: never surface hidden pages)
OUT = re.compile(r'Franchise Fantasy|\bTLS\b|style guide', re.I)
# never logged (Noah, Nov 28): copy cleanups (taglines, blurbs, intros, rewrites into his own words) and anything that
# mentions AI; a description line that mentions it is dropped too. Earlier rows are hidden or retitled in the fix file.
NOAI = re.compile(r'tagline|\bblurbs?\b|bold lead-ins|\bLLMs?\b|\bA\.?I\b(?! bot)|\bClaude\b|Anthropic|ChatGPT|\bGPT\b|'
                  r'(?:Noah\'s|my) (?:own )?(?:voice|words)|descriptive copy|intro (?:text|box)|"::" subtitles|method-spec style', re.I)
AI_LINE = re.compile(r'\bA\.?I\b|\bLLMs?\b|\bClaude\b|Anthropic|ChatGPT|\bGPT\b|language model', re.I)
# the site section a row belongs to, by its title; first match wins, ARKBOARD when the title names a sport or a board
SECTIONS = [
    ('LAURSEN_111', r'LAURSEN|\b111\b|laurlog|chat-box|mfplug|Valorant|Twitch'),
    ('1NT', r'\b1NT\b|sticker|jersey|\bkits?\b|Road to Pro|Path to Pro|\bESEA\b(?!.*(ARK|RWA|prospect|board))'),
    ('ST. CLAIRE', r'ST\. ?CLAIRE|\b(?-i:WAVE|Wave)\b|\bmusic\b|play count|SoundCloud'),
    ('ARKLIBRARY', r'ARKLIBRARY|\balbums?\b|Altarpiece'),
    ('site', r'tip/donate|Ko-fi|about/contact|\babout\b|main menu|\bmenu\b|social icons|\bhome ?page\b|\bhome\b|site search|'
             r'search (bar|index)|site data|site stats|\bARKLOG\b|favicon|\blogo\b|\bPost:|\barticles?\b|eephus|Instagram|'
             r'deploy|build gate|Cloudflare|\bnav\b|header|footer|ticker|\bnews\b|redirect|uniform|gothic|pixel art|'
             r'ARKNDJL|Brand exports|site-?wide|every page|\bfonts?\b|analytics|Knicks'),
]
SEC_ORDER = ['ARKBOARD', '1NT', 'LAURSEN_111', 'ST. CLAIRE', 'ARKLIBRARY', 'ARKNDJL', 'YTST', 'site']
LOGGED = lambda r: r.get('k') not in ('study', 'content')   # a change to the site (studies and content rows are not)


def section_of(title, sports):
    board = bool(sports) or bool(re.search(r'ARKBOARD|ARKLIST|ARKRANKING|ARK Ranking|Predictions|Process|\bFV\b|\bpicks?\b|standings|'
                                             r'prospects?|recruit|mock|\bGFX\b', title, re.I))
    for k, p in SECTIONS:
        if re.search(p, title, re.I) and not (k == 'site' and board) and not (k == '1NT' and re.search(r'\bCS2\b.*(ARK|RWA|prospect)', title)):
            return k
    return 'ARKBOARD'


AREAS = [  # (id = Process tab group, pattern); first match wins, title first
    ('players', r'Draft%|Ret%|Return%|Transfer%|Xfer|\bDec%|D-1%|FBS%|\bawards?\b|next up|breakout|backup watch'),
    ('fv', r'\bFV\b|future value|prospect|recruit|ARK stars|5-star|class (score|rank)|\bxFV\b'),
    ('drafts', r'\bmock|\bdraft\b|\bxPick\b|\bxSlot\b|\bUDFA\b|lottery'),
    ('games', r'game model|game projection|\btotals?\b|spread|win prob|\bpicks?\b|Kelly|\bCLV\b|\bprops?\b|paper book|'
              r'\bodds\b(?! snap)|Predictions|moneyline|market|close predictor|pick rule|\bedge\b|Novig|Polymarket|live WP|bet'),
    ('teams', r'rating|\bElo\b|ARK Ranking|ARK Top|power rank|season odds|\bCFP\b|bracket|\bsims?\b|standings|tournament odds|'
              r'playoff|futures|game control|coach pay|staff score|manager|all-time'),
    ('players', r'Draft%|Ret%|Return%|Transfer%|Xfer|breakout|next up|award|standouts?|backup|\bxGap\b|comps?\b|projection|'
                r'\bDec%|D-1%|FBS%|G League|depth chart|lineups?|injur|landing|\blean'),
    ('value', r'\bXPM\b|\bWAR\b|\bGAR\b|\bRWA\b|Stat\+|\bXV\b|\bNIL\b|\bSV\b|\bSVAR\b|VORX|\bxMV\b|\bxAAV\b|\bAV\b|value|'
              r'\bBPM\b|\bEPA\b|replacement|\bWAA\b|NHLe|GSAx|p/90|metric'),
    ('data', r'fetch|source|workflow|cron|pipeline|refresh|quota|backup feed|name match|alias|freshness|stale|snapshot|'
             r'schedule|auto-update|deploy|build gate|search index|data sources'),
    ('site', r'.'),
]
AREA_NAME = {'fv': 'FV', 'value': 'player value', 'players': 'player odds', 'teams': 'team ratings', 'games': 'game models',
             'drafts': 'drafts and mocks', 'data': 'data', 'site': 'site'}
UI = re.compile(r'\bGFX\b|\btabs?\b|mobile|\bphones?\b|\brename|layout|\bnav\b|\bmenu\b|\bcards?\b|photo|icon|hover|\bfont\b|'
                r'\bcopy\b|\bpage\b|window|column|\bsort|filter|search|\bbuild\b|\bbug|\bfix|logos?\b|flags?\b|tooltip|'
                r'\bshow\b|display|spacing|scroll|chips?\b|table\b|label|blurb|text\b', re.I)
TEST = re.compile(r'held[- ]out|walk[- ]forward|out[- ]of[- ]sample|\bOOS\b|backtest|leave[- ]one|\bLOSO\b|\bLOCO\b|'
                  r'pre-?reg|\bt\s*=?\s*[-+]?\.?\d|cross-?fit|point in time|placebo', re.I)
FAIL_T = re.compile(r'not shipped|nothing ships|research only|not kept|none pass|all fail|no pass|\bfails?\b|\bfailed\b|no model change|tested, not|'
                    r'nothing passes|does not (pass|help|ship)|ruled out', re.I)
FAIL_H = re.compile(r'^(failed|tested,? (and )?not (shipped|kept)|not shipped|research only|did not (pass|ship)|rejected|'
                    r'not kept|what failed|tested and dropped|no change)', re.I)
SHIP_H = re.compile(r'^(shipped|ships|what ships|what shipped|passed|kept|change|changes|what changed|what changes|model)\b', re.I)
FAIL_L = re.compile(r'\bfails?\b|\bfailed\b|not shipped|not kept|does(n\'t| not) (pass|help|beat|add)|no gain|'
                    r'adds nothing|worse than|\bworse\b.*\bt\b|left (blank|out|as is)|did not ship|stays out|isn\'t used', re.I)
SHIP_L = re.compile(r'\bpass(es|ed)?\b|\bships?\b|\bshipped\b|\bkept\b|\badded\b|\bjoins\b|now (uses|reads|feeds)|'
                    r'\bimproves?\b|\bbeats\b|\bgoes from\b|\bcuts\b', re.I)
NUM = r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)?\.?\d+%?'
# the held-out number: "<metric> ... a to b"; lower is better for the first group
LOW = r'log[- ]?loss|\bLL\b|Brier|RMSE|\brmse\b|\bMAE\b|\bmae\b|deviance|\bMSE\b|CRPS|abs(?:olute)? (?:margin )?error|error|miss'
HIGH = r'R²|R2\b|\bAUC\b|\bcorr(?:elation)?\b|\br\b|hit rate|accuracy|\bROI\b|\bCLV\b|Brier skill|coverage|slope'
EFF = re.compile(r'(?P<m>' + LOW + '|' + HIGH + r')(?P<mid>[^.;\n|]{0,48}?)\s(?:from\s)?(?P<a>' + NUM + r')\s*(?:to|->|→)\s*(?P<b>' + NUM + ')', re.I)
TVAL = re.compile(r'\bt\s*(?:=|of|stat(?:istic)?)?\s*(?P<t>[-+]?\d*\.?\d+)(?![\d%])')
CODE = re.compile(r'`([^`]*)`')
FILEY = re.compile(r'[/\\]|\.(py|json|mjs|js|yml|html|md|gz|css|toml)\b|^--|_')


def clean(s):
    """One line of a description as plain text: code names and file paths out, arrows to words."""
    def code(m):
        return '' if FILEY.search(m.group(1)) else m.group(1)
    s = CODE.sub(code, s)
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)             # links: the text
    s = re.sub(r'\*\*|__|^#+\s*', '', s)
    s = s.replace('→', ' to ').replace('->', ' to ').replace('—', ', ').replace('–', '-')
    s = re.sub(r'\(\s*(?:in|see|from|at|via|,)?\s*[,;]?\s*\)', '', s)   # brackets a removed path left empty
    s = re.sub(r'\b(?:PR )?#\d+\b', '', s)
    s = re.sub(r'\((?:team(?: model)? idea|audit|idea)\s*\d*[^)]*\)', '', s, flags=re.I)
    s = re.sub(r'\bOOS\b', 'out of sample', s)
    s = re.sub(r'\bpts\b|\bpp\b', 'points', s)
    s = re.sub(r'\bw/\s', 'with ', s)
    s = re.sub(r'\s+([,;:)]|\.(?!\d))', r'\1', s)
    s = re.sub(r'\(\s+', '(', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(' -*•\t')
    s = re.sub(r'^[,;:]\s*', '', s)
    return s


def body_lines(b):
    """The description as (heading, line) pairs: boilerplate out, list items and sentences kept apart."""
    b = re.sub(r'<!--.*?-->', '', b, flags=re.S)
    b = re.sub(r'(?m)^_Requested by .*$|^_?Generated (by|with) .*$|^🤖.*$|^https://claude\.ai\S*$|^Co-Authored-By.*$|^---+\s*$', '', b)
    out, head = [], ''
    for raw in b.split('\n'):
        ln = raw.strip()
        if not ln or AI_LINE.search(ln):
            continue
        m = re.match(r'^(?:#{1,6}\s*(.+?)\s*#*|\*\*([^*]+?)\*\*:?)$', ln)
        if m:
            head = (m.group(1) or m.group(2)).strip(' :.')
            continue
        m = re.match(r'^\*\*([^*]{2,60}?)[.:]?\*\*[.:]?\s+(.*)$', ln)      # "**Shipped.** text" run-in heading
        if m and (FAIL_H.match(m.group(1)) or SHIP_H.match(m.group(1))):
            head, ln = m.group(1).strip(), m.group(2)
        if ln.startswith('|'):
            if re.match(r'^\|[\s:|-]+\|$', ln):
                continue
            ln = ' · '.join(c.strip() for c in ln.strip('|').split('|') if c.strip())
        out.append((head, ln))
    return out


def sports_of(title, lines):
    sp = [k for k, p in SPORTS if re.search(p, title, re.I)]
    if not sp:   # the title names no sport: a sport the description leans on (3+ mentions, most first)
        text = ' '.join(l for _, l in lines)
        hits = sorted(((len(re.findall(p, text, re.I)), k) for k, p in SPORTS), reverse=True)
        sp = [k for c, k in hits if c >= 3][:3]
        sp = [k for k, _ in SPORTS if k in sp]
    return sp


def area_of(title, text):
    for src in (title, text[:600]):
        for k, p in AREAS[:-1]:
            if re.search(p, src, re.I):
                return k
    return 'site'


def fnum(s):
    try:
        return float(s.replace(',', '').rstrip('%'))
    except ValueError:
        return None


def metric_name(m):
    m = m.strip()
    low = m.lower().replace('-', ' ')
    return {'ll': 'log loss', 'logloss': 'log loss', 'log loss': 'log loss', 'r2': 'R²', 'r²': 'R²', 'auc': 'AUC', 'rmse': 'RMSE',
            'mae': 'MAE', 'mse': 'MSE', 'brier': 'Brier', 'crps': 'CRPS', 'roi': 'ROI', 'clv': 'CLV', 'corr': 'r',
            'correlation': 'r', 'r': 'r'}.get(low, low)


def effect(line, with_end=False):
    """[metric, before, after, better (1 better, 0 worse, None unknown)] from one line, or None."""
    for m in EFF.finditer(line):
        a, b = fnum(m.group('a')), fnum(m.group('b'))
        if a is None or b is None or a == b:
            continue
        if re.search(r'\d{4}\s*$', m.group('mid')) or (a > 1900 and b > 1900 and a == int(a)):   # "2012 to 2018": seasons
            continue
        name = metric_name(m.group('m'))
        if name == 'r' and (abs(a) > 1 or abs(b) > 1):
            continue
        low = bool(re.fullmatch(LOW, m.group('m'), re.I))
        if (name in ('log loss', 'Brier', 'R²', 'AUC', 'r') and max(abs(a), abs(b)) > 2) or min(abs(a), abs(b)) == 0:
            continue
        if low and abs(b - a) / max(abs(a), abs(b)) > .5:   # a halved loss is two different things on one line, not a gain
            continue
        better = (b < a) if low else (b > a)
        e = [name, m.group('a'), m.group('b'), 1 if better else 0]
        return (e, m.end()) if with_end else e
    return (None, 0) if with_end else None


def tnear(line, end):
    """The t that belongs to the number ending at `end`: the first one in the same clause, right after it."""
    m = TVAL.search(re.split(r';|\.\s|\s·\s', line[end:end + 60])[0])
    t = fnum(m.group('t')) if m else None
    return t if t is not None and abs(t) < 60 else None


LOGLINE = re.compile(r'^ARKLOG:\s*(?P<v>shipped|part shipped|failed)\b(?P<rest>.*)$', re.I)


def tval(line):
    ts = [fnum(m.group('t')) for m in TVAL.finditer(line)]
    ts = [t for t in ts if t is not None and abs(t) < 60]
    return ts[0] if ts else None


def show_title(title):
    """The title as the row prints it: "vs" spelled out, and a closing "(tested, not shipped)" dropped (the verdict chip says it)."""
    t = re.sub(r'\s+vs\.?\s+', ' against ', clean(title))
    return re.sub(r'\s*\((?:[^()]*\b(?:not shipped|failed|shipped|research only)\b[^()]*)\)\s*$', '', t) or t


def parse(pr):
    title = re.sub(r'\s*\(#\d+\)$', '', pr['t']).strip()
    if OUT.search(title) or NOAI.search(title):
        return None
    lines = body_lines(pr.get('b') or '')
    text = ' '.join(l for _, l in lines)
    row = {'n': pr['n'], 'd': pr['at'], 't': show_title(title), 'sp': sports_of(title, lines), 'ar': area_of(title, text), 'v': ''}
    row['sec'] = section_of(title, [k for k, p in SPORTS if re.search(p, title, re.I)])
    if row['sec'] != 'ARKBOARD':
        row['ar'] = 'site'
        row['sp'] = [x for x in row['sp'] if x == 'CS2'] if row['sec'] in ('1NT', 'LAURSEN_111') else []
    m = re.search(r'scripts/research/([A-Za-z0-9_]+)', pr.get('b') or '')
    if m:
        row['rec'] = m.group(1)
    if not (TEST.search(text) or TEST.search(title)):
        if UI.search(title):
            row['ar'] = 'site'
        return row
    # each numbered line with the side of the gate it reports
    tagged, ship_n, fail_n = [], 0, 0
    for head, ln in lines:
        for part in ([ln] if len(ln) < 260 else re.split(r'(?<=[a-z0-9)%])\.\s+(?=[A-Z])', ln)):
            c = clean(re.sub(r'^[-*•]\s+|^\d+[.)]\s+', '', part))
            if len(c) < 12 or not re.search(r'\d', c) or re.search(r'/mnt/|workflow|after merge|rerun|re-run|\bCI\b', c, re.I):
                continue
            hf, hs = bool(FAIL_H.match(head)), bool(SHIP_H.match(head))
            lf, ls = bool(FAIL_L.search(c)), bool(SHIP_L.search(c))
            tag = 'f' if (hf or (lf and not hs)) else 's' if (hs or ls) else ''
            if re.match(r'(shipped|ships|pass(es|ed)?|kept)\b', c, re.I) or re.search(r'\bso (it|this) passes\b', c, re.I):   # the line says so itself
                tag = 's'
            elif re.match(r'(failed|fails?|not shipped|not kept)\b', c, re.I):
                tag = 'f'
            if tag == 'f' and not hf and ls and re.search(r'\bpass(es|ed)?\b', c, re.I) and not re.search(r'\bfails?\b|\bfailed\b|not shipped', c, re.I):
                tag = 's'
            if not (TEST.search(c) or effect(c) or tag or re.search(r'\bn\s*=?\s*\d', c)):
                continue
            c = re.sub(r'\bt\s*=?\s*(-?\+?\.?\d)', r't = \1', re.sub(r'\s+vs\.?\s+', ' against ', c))
            # a line with code names in it still counts as evidence, but is not shown
            show = not re.search(r'\b[a-z]+[A-Z][A-Za-z]+\b|\b[a-z]+_[a-z_]+\b|--[a-z]|\b[a-z]{2,}\d\b', c)
            tagged.append([tag, c[:300].rstrip(), show, head])
            ship_n += tag == 's'
            fail_n += tag == 'f'
    # the headline number: one held-out number, with the t stated right after it in the same clause. From a shipped
    # line when one is tagged, else the first line that carries one. A t with no number beside it is never a headline.
    order = [c for tg, c, _, _h in tagged if tg == 's'] + [c for tg, c, _, _h in tagged if tg == ''] + [c for tg, c, _, _h in tagged if tg == 'f']
    tf = bool(FAIL_T.search(title))
    for c in (order if not tf else [c for _, c, _, _h in tagged]):
        e, end = effect(c, True)
        if e and (tf or e[3] == 1):
            row['e'] = e
            t = tnear(c, end)
            if t is not None:
                row['tt'] = t
            break
    has_t = any(tval(c) is not None for _, c, _, _h in tagged)
    # a test is a row with a held-out number, or a title that says it was one
    named = bool(re.search(r'\btests?\b|\btested\b|backtest|research|held[- ]out|\baudit\b|\bsweep\b|\brefit\b|retest|'
                           r'walk-forward|pre-?reg|\bdrivers?\b|calibrat', title, re.I))
    if not (tf or 'e' in row or has_t or (named and (ship_n or fail_n))):
        row['ar'] = area_of(title, text) if not UI.search(title) else 'site'
        return row
    bare = re.sub(r"not shipped|nothing ship\w*|not kept|none pass\w*|nothing passes|no(ne)? [^;,]{0,20}pass\w*|does not \w+", '', title, flags=re.I)
    ts = bool(re.search(r'\bships?\b|\bshipped\b|\bpass(es|ed)?\b|\benters\b|\bjoins\b|\bstays\b', bare, re.I))
    # a title with a second clause that is not about the test ("X fills the misses; Y test (failed)") shipped that clause
    clauses = [c for c in re.split(r';|\s\+\s', title) if c.strip()]
    other = any(not FAIL_T.search(c) and not re.search(r'\btests?\b|research|record', c, re.I) for c in clauses) and len(clauses) > 1
    if tf and not ts:
        v = 'm' if other else 'f'
    elif tf or (fail_n and ship_n):
        v = 'm'
    elif fail_n and not ship_n:
        v = 'f' if re.search(r'\btests?\b|\btested\b|research|backtest', title, re.I) and not (row.get('e') or [0, 0, 0, 0])[3] else 'm'
    else:
        v = 's'
    row['v'] = v
    if v == 'f' and row.get('e') and row['e'][3] == 1:   # a gain that still failed its gate reads as a failed line, not a win
        row['e'][3] = None
    row['l'] = [['', c] for tg, c, show, head in tagged if show][:14]   # shown unmarked: the row's verdict is the reviewed one
    return row


def logline(pr, row):
    """A description's own "ARKLOG: shipped · R² .643 to .732 · t = 2.1" line is taken as written, over the reading above."""
    for raw in (pr.get('b') or '').split('\n'):
        m = LOGLINE.match(raw.strip().strip('*_ '))
        if not m:
            continue
        row['v'] = {'shipped': 's', 'part shipped': 'm', 'failed': 'f'}[m.group('v').lower()]
        row.pop('e', None), row.pop('tt', None)
        e, end = effect(clean(m.group('rest')), True)
        if e:
            if row['v'] == 'f':
                e[3] = None
            row['e'] = e
        t = tval(clean(m.group('rest')))
        if t is not None and e:
            row['tt'] = t
        row.setdefault('l', [])
    return row


def tnum(t):
    s = f'{t:g}'
    return s.replace('0.', '.', 1) if s.startswith(('0.', '-0.')) else s


def headline(r):
    """the row's number as one string: 'log loss .8862 to .8831 · t 2.89'"""
    p = []
    if r.get('e'):
        p.append(f"{r['e'][0]} {r['e'][1]} to {r['e'][2]}")
    if r.get('tt') is not None:
        p.append('t = ' + tnum(r['tt']))
    return ' · '.join(p)


def fetch(pages):
    have = {p['n']: p for p in load_cache()}
    tok = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    for page in range(1, pages + 1):
        req = urllib.request.Request(
            f'https://api.github.com/repos/{REPO}/pulls?state=closed&sort=updated&direction=desc&per_page=100&page={page}',
            headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'arklog'})
        if tok:
            req.add_header('Authorization', f'Bearer {tok}')
        with urllib.request.urlopen(req, timeout=40) as r:
            rows = json.loads(r.read().decode())
        if not rows:
            break
        for p in rows:
            if p.get('merged_at') and (p.get('base') or {}).get('ref', 'main') == 'main':
                have[p['number']] = {'n': p['number'], 't': p['title'], 'at': p['merged_at'], 'b': p.get('body') or ''}
    out = sorted(have.values(), key=lambda p: p['n'])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(CACHE, 'wb', mtime=0) as f:
        f.write(json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode())
    return out


def load_cache():
    if not CACHE.exists():
        return []
    return json.loads(gzip.open(CACHE).read().decode())


# ---- pixel charts (same grid rules as scripts/library_build.py: integer coordinates, colour by CSS class) ----
def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def stack_svg(cols, keys, label, w=336, h=176):
    """Stacked pixel columns. cols [[x label, {key: n}]], keys [(key, css class)] bottom first."""
    L, R, T, B = 30, 6, 8, 30
    pw, ph = w - L - R, h - T - B
    top = max((sum(c[1].get(k, 0) for k, _ in keys) for c in cols), default=1) or 1
    step = next(s for s in (5, 10, 20, 25, 50, 100, 200, 500) if top / s <= 4)
    ymax = -(-top // step) * step
    out = [f'<svg class="libchart" viewBox="0 0 {w} {h}" shape-rendering="crispEdges" role="img" aria-label="{esc(label)}">']
    for v in range(0, ymax + 1, step):
        y = T + round(ph * (1 - v / ymax))
        out.append(f'<rect class="lc-grid" x="{L}" y="{y}" width="{pw}" height="1"/>')
        out.append(f'<text class="lc-tick" x="{L - 4}" y="{y + 4}" text-anchor="end">{v}</text>')
    slot = pw / max(1, len(cols))
    bw = max(4, int(slot * 0.72))
    for i, (xl, d) in enumerate(cols):
        x = L + int(slot * i + (slot - bw) / 2)
        y = T + ph
        for k, cls in keys:
            n = d.get(k, 0)
            if not n:
                continue
            hh = max(1, round(ph * n / ymax))
            y -= hh
            out.append(f'<rect class="lc-bar {cls}" x="{x}" y="{y}" width="{bw}" height="{hh - 1 if hh > 2 else hh}"><title>{esc(xl)}: {n}</title></rect>')
        if xl and (len(cols) <= 10 or i % 2 == 0):
            out.append(f'<text class="lc-tick" x="{x + bw // 2}" y="{T + ph + 13}" text-anchor="middle">{esc(xl)}</text>')
    out.append(f'<rect class="lc-axis" x="{L}" y="{T + ph}" width="{pw}" height="2"/>')
    out.append(f'<text class="lc-label" x="{L + pw // 2}" y="{h - 3}" text-anchor="middle">{esc(label)}</text>')
    out.append('</svg>')
    return ''.join(out)


def hstack_svg(rows, keys, label, w=336):
    """Stacked pixel rows. rows [[label, {key: n}]]: one bar per row, the count at its end."""
    L, R, T, rh = 84, 34, 4, 18
    h = T + rh * len(rows) + 20
    pw = w - L - R
    top = max((sum(r[1].get(k, 0) for k, _ in keys) for r in rows), default=1) or 1
    out = [f'<svg class="libchart" viewBox="0 0 {w} {h}" shape-rendering="crispEdges" role="img" aria-label="{esc(label)}">']
    for i, (lab, d) in enumerate(rows):
        y = T + i * rh
        out.append(f'<text class="lc-tick" x="{L - 6}" y="{y + 12}" text-anchor="end">{esc(lab)}</text>')
        x = L
        for k, cls in keys:
            n = d.get(k, 0)
            if not n:
                continue
            ww = max(2, round(pw * n / top))
            out.append(f'<rect class="lc-bar {cls}" x="{x}" y="{y + 3}" width="{ww - 1}" height="11"><title>{esc(lab)} {k}: {n}</title></rect>')
            x += ww
        out.append(f'<text class="lc-tick" x="{x + 4}" y="{y + 12}">{sum(d.get(k, 0) for k, _ in keys)}</text>')
    out.append(f'<rect class="lc-axis" x="{L - 2}" y="{T}" width="2" height="{rh * len(rows)}"/>')
    out.append(f'<text class="lc-label" x="{L + pw // 2}" y="{h - 4}" text-anchor="middle">{esc(label)}</text>')
    out.append('</svg>')
    return ''.join(out)


def week_of(d):
    import datetime
    dt = datetime.date.fromisoformat(d[:10])
    mon = dt - datetime.timedelta(days=dt.weekday())
    return mon.isoformat()


def study_rows(prs):
    """Research studies as rows, dated by the pull request whose description names the study."""
    rows = []
    for f in sorted((ROOT / 'research/studies').glob('*/*.json')):
        s = json.loads(f.read_text())
        if s.get('publish') is False or not s.get('question'):
            continue
        sid = s['id']
        when = [p['at'] for p in prs if sid in (p.get('b') or '') or sid in p['t']]
        d = min(when) if when else (s.get('date') or '2026-11-02') + 'T12:00:00Z'
        sp = {'soccer': 'Soccer', 'tennis': 'Tennis'}.get(s['sport'], s['sport'])
        rows.append({'k': 'study', 'id': sid, 'd': d, 't': s['question'], 'a': s['answer'], 'sp': [sp], 'ar': 'research', 'sec': 'ARKBOARD',
                     'v': 's' if s.get('robust') else 'w', 'nn': s.get('n')})
    return rows


def content_rows():
    """What went out, next to what changed (Noah, Nov 28): YouTube uploads on the ARKNDJL, LAURSEN_111 and YTST channels,
    LAURSEN_111 Twitch streams, 1NT ESEA matches, articles and ST. CLAIRE releases. Read from files already in the repo
    (the social pulls, data/esea.json, content/posts, content/arkndjl-music.md); nothing typed in. k = 'content', c = kind."""
    import datetime as dt
    import tomllib
    rows = []
    iso = lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    for key, sec in (('arkndjl', 'ARKNDJL'), ('laursen', 'LAURSEN_111'), ('ytst', 'YTST')):
        f = ROOT / f'data/{key}_socials.json'
        d = json.loads(f.read_text()) if f.exists() else {}
        for vid, y in (d.get('yt') or {}).items():
            if not y.get('pub') or not y.get('title'):
                continue
            t = re.sub(r'(?:\s+#\w+)+\s*$', '', y['title']).strip() or y['title']
            kind = 'short' if y.get('short') else 'episode' if sec == 'YTST' else 'video'
            rows.append({'k': 'content', 'id': f'yt-{vid}', 'd': iso(y['pub']), 't': t, 'c': kind, 'sec': sec, 'sp': [], 'ar': 'site',
                         'v': '', 'u': f'https://youtu.be/{vid}'})
        for s in ((d.get('tw') or {}).get('sessions') or []):
            if not s.get('peak') and s['e'] == s['s']:   # one empty sample, not a stream
                continue
            mins = round((s['e'] - s['s']) / 60000)
            ln = f' for {mins // 60}h {mins % 60:02d}m' if mins >= 10 else ''
            g = s.get('g') or 'Twitch'
            rows.append({'k': 'content', 'id': f'tw-{s["s"]}', 'd': iso(s['s']), 'c': 'stream', 'sec': sec, 'sp': [], 'ar': 'site', 'v': '',
                         't': f'Streamed {g}{ln}, peak {s.get("peak", 0)} viewers', 'u': 'https://www.twitch.tv/laursen_111'})
    f = ROOT / 'data/esea.json'
    e = json.loads(f.read_text()) if f.exists() else {}
    for m in e.get('matches') or []:
        if m.get('status') != 'FINISHED' or not m.get('score'):
            continue
        a, b = m['score']
        opp = (m.get('opp') or {}).get('name') or 'TBD'
        stage = f'ESEA S{e.get("season")} {"playoffs" if m.get("stage") == "Playoffs" else "regular season"}'
        if a + b == 1:
            t = f'1NT {"won by forfeit against" if a > b else "lost by forfeit to"} {opp} ({stage})'
        else:
            t = f'1NT {"beat" if a > b else "lost to"} {opp} {a}-{b} ({stage})'
        rows.append({'k': 'content', 'id': f'm-{m["id"]}', 'd': iso(m['at']), 't': t, 'c': 'match', 'sec': '1NT', 'sp': ['CS2'],
                     'ar': 'site', 'v': '', 'u': m.get('url')})
    for f in sorted((ROOT / 'content/posts').glob('*.md')):
        txt = f.read_text()
        m = re.match(r'\+\+\+\n(.*?)\n\+\+\+', txt, re.S)
        if not m:
            continue
        fm = tomllib.loads(m.group(1))
        if fm.get('draft') or fm.get('searchExclude') or OUT.search(fm.get('title', '')) or not fm.get('date'):
            continue
        d = dt.datetime.fromisoformat(str(fm['date'])).astimezone(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        if d > dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ'):
            continue
        url = fm.get('url') or f'/posts/{(fm.get("slug") or f.stem).lower()}/'
        rows.append({'k': 'content', 'id': f'post-{f.stem.lower()}', 'd': d, 't': fm['title'], 'c': 'article', 'sec': 'site', 'sp': [],
                     'ar': 'site', 'v': '', 'u': url})
    f = ROOT / 'content/arkndjl-music.md'
    if f.exists():   # a track counts as a release once its front matter has a date (date = "YYYY-MM-DD")
        m = re.match(r'\+\+\+\n(.*?)\n\+\+\+', f.read_text(), re.S)
        for tr in (tomllib.loads(m.group(1)).get('tracks') or []) if m else []:
            if tr.get('date'):
                d = str(tr['date'])[:10] + 'T12:00:00Z'
                rows.append({'k': 'content', 'id': f'rel-{tr["title"].lower()}', 'd': d, 't': f'{tr["title"]} by {tr.get("artist", "arkndjl")}',
                             'c': 'release', 'sec': 'ST. CLAIRE', 'sp': [], 'ar': 'site', 'v': '', 'u': tr.get('soundcloud') or tr.get('youtube')})
    for r in rows:
        if not r.get('u'):
            r.pop('u', None)
    return [r for r in rows if not NOAI.search(r['t'])]


def build():
    prs = load_cache()
    fix = json.loads(FIX.read_text()) if FIX.exists() else {}
    rows = []
    for p in prs:
        r = parse(p)
        r = logline(p, r) if r else r
        if not r:
            continue
        f = fix.get(str(r['n'])) or {}
        if f.get('hide'):
            continue
        r.update({k: v for k, v in f.items() if k != 'hide'})
        for k in [k for k, v in r.items() if v is None]:   # a fix of null drops the field
            del r[k]
        x = headline(r)
        if x:
            r['x'] = x
        rows.append(r)
    rows += study_rows(prs)
    rows += content_rows()
    rows.sort(key=lambda r: r['d'], reverse=True)
    asof = rows[0]['d'] if rows else ''
    (ROOT / 'static/data').mkdir(parents=True, exist_ok=True)
    (ROOT / 'static/data/arklog.json').write_text(
        json.dumps({'asof': asof, 'rows': rows}, ensure_ascii=False, separators=(',', ':'), allow_nan=False))

    tests = [r for r in rows if r['v'] in ('s', 'f', 'm') and r.get('k') != 'study']
    cnt = lambda rs: {'s': sum(r['v'] == 's' for r in rs), 'm': sum(r['v'] == 'm' for r in rs), 'f': sum(r['v'] == 'f' for r in rs)}
    weeks = {}
    for r in rows:
        if not LOGGED(r):
            continue
        w = weeks.setdefault(week_of(r['d']), {'shipped': 0, 'mixed': 0, 'failed': 0, 'other': 0})
        w[{'s': 'shipped', 'm': 'mixed', 'f': 'failed'}.get(r['v'], 'other')] += 1
    wk = sorted(weeks.items())
    mlab = lambda d: f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][int(d[5:7]) - 1]} {int(d[8:10])}"
    KEYS = [('shipped', 'lc-s0'), ('mixed', 'lc-s2'), ('failed', 'lc-s4')]
    sp_order = [k for k, _ in SPORTS]
    by_sport = [[s, {'shipped': c['s'], 'mixed': c['m'], 'failed': c['f']}] for s in sp_order
                for c in [cnt([r for r in tests if s in r['sp']])] if sum(c.values())]
    by_area = [[AREA_NAME[a], {'shipped': c['s'], 'mixed': c['m'], 'failed': c['f']}] for a in AREA_NAME
               for c in [cnt([r for r in tests if r['ar'] == a])] if sum(c.values())]
    by_sec = [[k, {'tests': sum(1 for r in tests if r['sec'] == k), 'other': sum(1 for r in rows if r['sec'] == k and r not in tests and LOGGED(r))}]
              for k in SEC_ORDER if any(r['sec'] == k for r in rows)]
    tw = [[mlab(w), {k: d[k] for k in ('shipped', 'mixed', 'failed')}] for w, d in wk if d['shipped'] + d['mixed'] + d['failed']]
    aw = [[mlab(w), {'tests': d['shipped'] + d['mixed'] + d['failed'], 'other': d['other']}] for w, d in wk]
    slim = lambda r: {k: r[k] for k in ('n', 'd', 't', 'sec', 'sp', 'ar', 'v', 'e', 'tt', 'x', 'k', 'id', 'a') if k in r}
    out = {
        'asof': asof, 'rows': len(rows), 'changes': sum(1 for r in rows if LOGGED(r)), 'content': sum(1 for r in rows if r.get('k') == 'content'),
        'tests': len(tests), **{k: v for k, v in zip(('shipped', 'mixed', 'failed'), cnt(tests).values())},
        'studies': sum(1 for r in rows if r.get('k') == 'study'),
        'first': rows[-1]['d'][:10] if rows else '',
        'sports': {s: {**cnt([r for r in tests if s in r['sp']]), 'all': sum(1 for r in rows if s in r['sp'])} for s in sp_order},
        'sections': {k: sum(1 for r in rows if r['sec'] == k) for k in SEC_ORDER},
        'months': [{'mo': m, 'changes': sum(1 for r in rs if LOGGED(r)), 'content': sum(1 for r in rs if r.get('k') == 'content'), **cnt([r for r in rs if r in tests]),
                    'studies': sum(1 for r in rs if r.get('k') == 'study'),
                    'sections': {k: sum(1 for r in rs if r['sec'] == k) for k in SEC_ORDER if any(r['sec'] == k for r in rs)}}
                   for m in sorted({r['d'][:7] for r in rows}, reverse=True) for rs in [[r for r in rows if r['d'][:7] == m]]],
        'weeks': [[w, d] for w, d in wk], 'by_sport': by_sport, 'by_area': by_area, 'by_sec': by_sec,
        'latest': [slim(r) for r in rows if r['v'] in ('s', 'f', 'm') and r.get('k') != 'study'][:8],
        'svg': {'weeks': stack_svg(tw, KEYS, 'week merged'),
                'all': stack_svg(aw, [('tests', 'lc-s0'), ('other', 'lc-s3')], 'week merged'),
                'sport': hstack_svg(by_sport, KEYS, 'tests'),
                'area': hstack_svg(by_area, KEYS, 'tests'),
                'sec': hstack_svg(by_sec, [('tests', 'lc-s0'), ('other', 'lc-s3')], 'changes')},
    }
    (ROOT / 'data/arklog.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
    print(f"arklog: {out['changes']} changes, {out['tests']} tests ({out['shipped']} shipped, {out['mixed']} mixed, "
          f"{out['failed']} failed), {out['studies']} studies, newest {asof}")
    return rows


def digest(month):
    """One month of ARKLOG as plain text, grouped by section then sport: the working notes for that month's Process
    update (content/posts, front matter series = "process", month = "YYYY-MM"; listed on /arklog/#updates)."""
    rows = [r for r in json.loads((ROOT / 'static/data/arklog.json').read_text())['rows'] if r['d'][:7] == month]
    lab = {'s': 'shipped', 'm': 'part shipped', 'f': 'failed', 'w': 'weak', '': ''}
    print(f'# ARKLOG {month}: {len(rows)} rows')
    for sec in SEC_ORDER:
        rs = [r for r in rows if r['sec'] == sec]
        if not rs:
            continue
        print(f'\n## {sec} ({len(rs)})')
        keys = ([k for k, _ in SPORTS] + ['']) if sec == 'ARKBOARD' else ['']
        seen = set()
        for sp in keys:
            grp = [r for r in rs if id(r) not in seen and ((sp in r['sp']) if sp else True)]
            if not grp:
                continue
            seen.update(id(r) for r in grp)
            if sec == 'ARKBOARD':
                print(f'\n### {sp or "all sports"}')
            for r in sorted(grp, key=lambda r: r['d']):
                print(f"- {r['d'][5:10]} [{lab.get(r['v'], '')}] {r['t']}" + (f" | {r['x']}" if r.get('x') else '') + (f" | {r['a']}" if r.get('a') else ''))


def selftest():
    b = ("<!-- x -->\n_Requested by **N** · [project thread](https://x)_\n\n**Shipped**\n- CBB Transfer%: head coach's seasons "
         "(`hc_ten`). 2025-26 held out t 2.89; log loss .8862 to .8831, AUC .725 to .727.\n\n**Failed (not shipped)**\n"
         "- Came with his coach: t -.91 / .98.\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_")
    r = parse({'n': 1, 't': 'Coach loyalty: CBB Transfer% coach tenure', 'at': '2026-11-27T21:46:03Z', 'b': b})
    assert r['v'] == 'm' and r['e'] == ['log loss', '.8862', '.8831', 1] and 'tt' not in r and r['sp'] == ['CBB'], r
    assert r['ar'] == 'players' and len(r['l']) == 2, r
    r = parse({'n': 2, 't': 'NBA: RAPM / LEBRON / RAPTOR test (research only, all failed)', 'at': '2026-10-29T00:00:00Z',
               'b': 'Held out 2015-23, none beats XPM: RMSE 2.93 to 2.97 (t 1.4).'})
    assert r['v'] == 'f' and r['e'][0] == 'RMSE' and r['e'][3] == 0 and r['sp'] == ['NBA'], r
    r = parse({'n': 3, 't': 'Add Awake NY to Wave brands', 'at': '2026-11-27T00:00:00Z', 'b': ''})
    assert r['sec'] == 'ST. CLAIRE' and r['v'] == '' and r['sp'] == [], r
    assert parse({'n': 5, 't': 'Franchise Fantasy: draft room', 'at': '2026-11-27T00:00:00Z', 'b': ''}) is None
    r = parse({'n': 4, 't': 'CFB depth chart tab on phones', 'at': '2026-11-27T00:00:00Z', 'b': 'Rows wrap at 390px.'})
    assert r['v'] == '' and r['ar'] == 'site', r
    assert clean('split `XNIL.k` 1.1 -> 1.375 (`scripts/x.py`)') == 'split XNIL.k 1.1 to 1.375'
    assert effect('seasons 2012 to 2018, r .41') is None
    print('arklog: tests pass')


if __name__ == '__main__':
    if '--test' in sys.argv:
        selftest()
        sys.exit(0)
    if '--month' in sys.argv:
        digest(sys.argv[sys.argv.index('--month') + 1])
        sys.exit(0)
    if '--all' in sys.argv:
        fetch(40)
    elif '--fetch' in sys.argv:
        try:
            fetch(2)
        except Exception as e:   # the API is down or rate-limited: the log rebuilds from the cache
            print(f'arklog: fetch failed ({e}); using the cache', flush=True)
    build()
