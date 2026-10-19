#!/usr/bin/env python3
"""Shared loaders for the College Basketball ARKBOARD (scripts/cbb_fit.py, scripts/fetch_cbb.py).

Raw pulls live in scripts/.cache/cbb/ (not in git):
  bt/adv<year>.csv      Barttorvik player seasons (getadvstats.php?year=<year>&csv=1), 2008 on. <year> is the
                        season's end (2026 = 2025-26). 2027 is Barttorvik's 2026-27 rosters with last season's lines.
  bbref/draft<year>     Basketball-Reference draft pages (pick, college, career BPM)
  bbref/adv<year>       Basketball-Reference NBA advanced tables (G, GS, MP, BPM per player season)
  bbref/allnba, asbyplayer   All-NBA teams by season, All-Star selections by player
  r247/<class>-p<n>     247Sports composite rankings, pages of 50
  on3/<class>.json      On3 industry (consensus) rankings, from scripts/cbb_on3.mjs
  espn/r<id>.json       ESPN 2026-27 rosters
"""
import csv, html, json, os, re, sys, time, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import names as N                     # the shared player-name key (scripts/names.py), every sport

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, '.cache', 'cbb')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'

# Barttorvik's CSV has no header; these are its columns in order
BT_COLS = ['name', 'team', 'conf', 'gp', 'min_per', 'ortg', 'usg', 'efg', 'ts', 'orb', 'drb', 'ast', 'to', 'ftm', 'fta',
           'ft', 'twopm', 'twopa', 'twop', 'tpm', 'tpa', 'tp', 'blk', 'stl', 'ftr', 'yr', 'ht', 'num', 'porpag', 'adjoe',
           'pfr', 'year', 'pid', 'home', 'rec', 'ast_tov', 'rimm', 'rima', 'midm', 'mida', 'rim', 'mid', 'dunkm', 'dunka',
           'dunk', 'pick', 'drtg', 'adrtg', 'dporpag', 'stops', 'bpm', 'obpm', 'dbpm', 'gbpm', 'mp', 'ogbpm', 'dgbpm',
           'oreb_g', 'dreb_g', 'treb_g', 'ast_g', 'stl_g', 'blk_g', 'pts_g', 'role', 'tpa100', 'dob']
BT_TEXT = {'name', 'team', 'conf', 'yr', 'ht', 'home', 'role', 'dob', 'pid'}


def fetch(url, path, sleep=0, binary=False):
    """curl into the cache (python's TLS fingerprint gets 403s from some of these sites; curl doesn't)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(['curl', '-s', '-m', '60', '-A', UA, url, '-o', path], check=False)
    if sleep: time.sleep(sleep)
    return path


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def inches(h):
    m = re.match(r"\s*(\d)\D+(\d+(?:\.\d+)?)", h or '')
    return int(m.group(1)) * 12 + float(m.group(2)) if m else None


def norm(n):
    """a player's name key: accents, case, punctuation, suffixes and the aliases in data/name_aliases.json folded"""
    return N.key(n)


def load_bt(year):
    p = os.path.join(CACHE, 'bt', f'adv{year}.csv')
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        fetch(f'https://barttorvik.com/getadvstats.php?year={year}&csv=1', p, 1)
    out = []
    with open(p, newline='', encoding='utf-8', errors='replace') as f:
        for row in csv.reader(f):
            if len(row) < 66: continue
            r = {k: (row[i] if k in BT_TEXT else num(row[i])) if i < len(row) else None for i, k in enumerate(BT_COLS)}
            r['year'] = int(r['year']) if r['year'] else year
            r['hti'] = inches(r['ht'])
            r['key'] = norm(r['name'])
            out.append(r)
    return out


def bbref_rows(path):
    h = open(path, encoding='utf-8', errors='replace').read()
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S):
        cells = dict(re.findall(r'data-stat="([a-z0-9_]+)"[^>]*>(.*?)</t[dh]>', tr, re.S))
        if not cells: continue
        link = re.search(r"/players/[a-z]/([a-z0-9]+)\.html", tr)
        yield cells, (link.group(1) if link else None)


def strip(s): return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def load_draft(year):
    p = os.path.join(CACHE, 'bbref', f'draft{year}.html')
    if not os.path.exists(p): fetch(f'https://www.basketball-reference.com/draft/NBA_{year}.html', p, 4)
    out = []
    for c, pid in bbref_rows(p):
        pick = num(strip(c.get('pick_overall')))
        if not pick or not pid: continue
        out.append({'year': year, 'pick': int(pick), 'bref': pid, 'name': strip(c.get('player')), 'key': norm(strip(c.get('player'))),
                    'college': strip(c.get('college_name')), 'bpm': num(strip(c.get('bpm'))), 'mp': num(strip(c.get('mp')))})
    return out


def load_nba_seasons(year):
    """one row per player season (the combined row for players on several teams: the most minutes)."""
    p = os.path.join(CACHE, 'bbref', f'adv{year}.html')
    if not os.path.exists(p): fetch(f'https://www.basketball-reference.com/leagues/NBA_{year}_advanced.html', p, 4)
    best = {}
    for c, pid in bbref_rows(p):
        mp = num(strip(c.get('mp')))
        if not pid or mp is None: continue
        r = {'bref': pid, 'year': year, 'name': strip(c.get('name_display') or c.get('player')), 'age': num(strip(c.get('age'))),
             'g': num(strip(c.get('games') or c.get('g'))) or 0, 'gs': num(strip(c.get('games_started') or c.get('gs'))) or 0,
             'mp': mp, 'bpm': num(strip(c.get('bpm'))), 'vorp': num(strip(c.get('vorp')))}
        if pid not in best or mp > best[pid]['mp']: best[pid] = r
    return list(best.values())


def load_awards():
    allnba, allstar = {}, {}
    p = os.path.join(CACHE, 'bbref', 'allnba.html')
    if not os.path.exists(p): fetch('https://www.basketball-reference.com/awards/all_league.html', p, 4)
    h = open(p, encoding='utf-8', errors='replace').read()
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S):
        if '>NBA<' not in tr: continue
        for pid in re.findall(r"/players/[a-z]/([a-z0-9]+)\.html", tr):
            allnba[pid] = allnba.get(pid, 0) + 1
    p = os.path.join(CACHE, 'bbref', 'asbyplayer.html')
    if not os.path.exists(p): fetch('https://www.basketball-reference.com/awards/all_star_by_player.html', p, 4)
    h = open(p, encoding='utf-8', errors='replace').read()
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', h, re.S):
        m = re.search(r"/players/[a-z]/([a-z0-9]+)\.html", tr)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if m and len(tds) >= 4:
            n = num(strip(tds[3]))      # NBA selections (the column after the all-leagues total)
            if n: allstar[m.group(1)] = int(n)
    return allnba, allstar


def load_247(cls):
    out = []
    for pg in range(1, 13):
        p = os.path.join(CACHE, 'r247', f'{cls}-p{pg}.html')
        if not os.path.exists(p):
            fetch(f'https://247sports.com/season/{cls}-basketball/compositerecruitrankings/?Page={pg}', p, 1.5)
        h = open(p, encoding='utf-8', errors='replace').read()
        items = h.split('rankings-page__list-item"')[1:]
        n0 = len(out)
        for it in items:
            nm = re.search(r'rankings-page__name-link"[^>]*>([^<]+)<', it)
            sc = re.search(r'class="score">([\d.]+)<', it)
            rk = re.search(r'class="primary">\s*(\d+)', it)
            if not nm or not sc: continue
            meta = re.search(r'class="meta">\s*([^<]*)<', it)
            pos = re.search(r'class="position">\s*([^<]*?)\s*<', it)
            hw = re.search(r'class="metrics">\s*([^<]*?)\s*<', it)
            team = re.search(r'class="img-link"[^>]*>\s*<img alt="([^"]+)"', it)
            out.append({'cls': cls, 'name': html.unescape(nm.group(1).strip()), 'key': norm(nm.group(1)), 'r247': float(sc.group(1)),
                        'rank247': int(rk.group(1)) if rk else None, 'meta': html.unescape(meta.group(1).strip()) if meta else '',
                        'pos': pos.group(1) if pos else '', 'hw': hw.group(1) if hw else '', 'team': html.unescape(team.group(1)) if team else None})
        if len(out) - n0 < 10: break
    return out


def load_on3(cls):
    p = os.path.join(CACHE, 'on3', f'{cls}.json')
    if not os.path.exists(p): return []
    rows = json.load(open(p))
    for r in rows: r['key'] = norm(r['name'])
    return rows


def age_on(dob, y, m, d):
    try:
        b = time.strptime(dob, '%Y-%m-%d')
    except (TypeError, ValueError):
        return None
    return (y - b.tm_year) + ((m - b.tm_mon) * 30.44 + (d - b.tm_mday)) / 365.25
