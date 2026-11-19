#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Keep the coordinators in data/cfb_staff.json current from Wikipedia's season infoboxes.

    python3 scripts/cfb_coord_sync.py            # every team's season page, apply the differences
    python3 scripts/cfb_coord_sync.py --dry      # print the differences only
    python3 scripts/cfb_coord_sync.py --test     # parser self-test (no network)

Each FBS team's season article ("2026 Auburn Tigers football team") carries an infobox with off_coach, def_coach,
off_scheme and def_scheme. The page is read as wikitext through /wiki/<title>?action=raw (the article path; one
request a team, 1.2 s apart). Where the infobox names a coordinator the file does not have (compared through scripts/names.py), the
role takes the infobox names: the old entry is kept under "prev" with the date, as the head coach sync does. A role
the infobox leaves blank is never cleared, and a run where fewer than 80% of the pages answer changes nothing.
Scheme labels and the page's fetch date are stored beside the role (scheme, wikiAsof). Every difference is appended
to scripts/data/cfb_coord_log.jsonl.
"""
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import names  # noqa: E402

P = os.path.join(ROOT, 'data', 'cfb_staff.json')
TEAMS = os.path.join(ROOT, 'data', 'cfb_teams.json')
LOG = os.path.join(ROOT, 'scripts', 'data', 'cfb_coord_log.jsonl')
UA = 'arkndjl.net-arkboard/1.0 (https://arkndjl.net)'
RAW = 'https://en.wikipedia.org/wiki/{}?action=raw'
PACE = 1.2


def raw(title, hops=2):
    url = RAW.format(urllib.parse.quote(title.replace(' ', '_'), safe="()',_-.&"))
    try:
        t = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=25).read().decode('utf8', 'replace')
    except Exception:
        return None
    m = re.match(r'\s*#REDIRECT\s*\[\[([^\]|#]+)', t, re.I)
    if m and hops:
        time.sleep(PACE)
        return raw(m.group(1).strip(), hops - 1)
    return t


def field(text, name):
    """One infobox field's raw value (to the next top-level '|' line), or ''."""
    m = re.search(r'^\s*\|\s*' + re.escape(name) + r'\s*=(.*?)(?=^\s*\|\s*[A-Za-z_0-9]+\s*=|^\s*\}\})', text, re.S | re.M)
    return m.group(1).strip() if m else ''


def clean(v):
    v = re.sub(r'<ref[^>]*/>', '', v)
    v = re.sub(r'<ref.*?</ref>', '', v, flags=re.S)
    v = re.sub(r'<!--.*?-->', '', v, flags=re.S)
    v = re.sub(r'\{\{(?:efn|sfn|refn|cn|citation needed)[^{}]*\}\}', '', v, flags=re.I)
    return v


GONE = re.compile(r'first \d+ games?|games? \d+\s*[–-]\s*\d+|fired|resigned|dismissed|until |through |left ', re.I)
STAYS = re.compile(r'interim|remainder|rest of|final \d+ games?', re.I)


def people(v):
    """[(name, wiki title or None)] from a coach field: one person per <br>, list item or slash. Where the field
    lists a coordinator who left during the season beside his replacement ("first 8 games" / "interim; remainder of
    season"), only those still in the job are returned."""
    v = clean(v)
    v = re.sub(r'\{\{\s*(?:ubl|unbulleted list|plainlist|plain list|flatlist)\s*\|', '\x01', v, flags=re.I)
    v = re.sub(r'\{\{[^{}]*\}\}', '', v)
    held = []

    def hold(m):
        held.append(m)
        return f'\x00{len(held) - 1}\x00'
    v = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', hold, v)
    notes = []

    def note(m):
        notes.append(m.group(1))
        return f'\x02{len(notes) - 1}\x02'
    v = re.sub(r'\(([^()]*)\)', note, v)
    out = []
    for part in re.split(r'<br\s*/?>|\n\s*\*|\n|\||\s/\s|;', v):
        part = part.strip(' *{}\x01')
        if not part:
            continue
        link = re.search(r'\x00(\d+)\x00', part)
        title = held[int(link.group(1))].group(1).strip() if link else None
        why = ' '.join(notes[int(i)] for i in re.findall(r'\x02(\d+)\x02', part))
        txt = re.sub(r'\x02\d+\x02', '', part)
        txt = re.sub(r'\x00(\d+)\x00', lambda m: (held[int(m.group(1))].group(2) or held[int(m.group(1))].group(1)).strip(), txt)
        txt = re.sub(r'\([^)]*\)?', '', txt)
        txt = re.sub(r"'{2,}", '', txt)
        txt = re.sub(r'\b(?:co-?(?:offensive|defensive)?\s*coordinators?|interim|and)\b[:\s]*', ' ', txt, flags=re.I)
        txt = re.sub(r'\s+', ' ', txt).strip(' ,-–:&')
        if len(txt) < 4 or len(txt.split()) < 2 or not re.search(r'[A-Za-z]{2,}', txt) or re.search(r'\d{4}|season|games?\b', txt, re.I):
            continue
        gone = bool(GONE.search(why)) and not STAYS.search(why)
        out.append((txt, title, gone))
    if any(g for _, _, g in out) and any(not g for _, _, g in out):
        out = [x for x in out if not x[2]]
    seen, uniq = set(), []
    for n, t, _ in out:
        k = names.key(n)
        if k and k not in seen:
            seen.add(k)
            uniq.append((n, t))
    return uniq


def scheme(v):
    v = clean(v)
    v = re.sub(r'\[\[(?:[^\]|]+\|)?([^\]]+)\]\]', r'\1', v)
    v = re.sub(r'<br\s*/?>', ' / ', v)
    v = re.sub(r'\{\{[^{}]*\}\}|<[^>]+>', '', v)
    return re.sub(r'\s+', ' ', v).strip(' /') or None


def parse(text):
    return {'hc': people(field(text, 'head_coach')), 'oc': people(field(text, 'off_coach')), 'dc': people(field(text, 'def_coach')),
            'off_scheme': scheme(field(text, 'off_scheme')), 'def_scheme': scheme(field(text, 'def_scheme'))}


def title_for(tid, t, full, season):
    for role in ('oc', 'dc', 'hc'):
        m = re.match(r'wikipedia:(\d{4} .+? football team)', (t.get(role) or {}).get('src') or '')
        if m:
            return re.sub(r'^\d{4}', str(season), m.group(1))
    return f'{season} {full} football team' if full else None


def role_names(e):
    if not e:
        return []
    return e.get('names') or ([x.strip() for x in (e.get('name') or '').split(' / ') if x.strip()])


def self_test():
    box = """{{Infobox college sports team season
| year = 2026
| head_coach = [[Alex Golesh]]
| hc_year = 1st
| off_coach = [[Joel Gordon (American football)|Joel Gordon]] (1st season)<br />[[Kodi Burns]] (co-OC)
| def_coach = {{ubl|[[D. J. Durkin]]|Tim Banks}}<ref name="x">cite</ref>
| off_scheme = [[Spread offense|Up-tempo spread]]
| def_scheme = Multiple 4–2–5
| stadium = [[Jordan–Hare Stadium]]
}}"""
    p = parse(box)
    assert [n for n, _ in p['oc']] == ['Joel Gordon', 'Kodi Burns'], p['oc']
    assert p['oc'][0][1] == 'Joel Gordon (American football)'
    assert [n for n, _ in p['dc']] == ['D. J. Durkin', 'Tim Banks'], p['dc']
    assert p['off_scheme'] == 'Up-tempo spread' and p['def_scheme'] == 'Multiple 4–2–5', p
    assert [n for n, _ in p['hc']] == ['Alex Golesh']
    assert people('') == [] and people('TBD') == []
    assert [n for n, _ in people('[[Tony White (gridiron football)|Tony White]] (2nd season; first 8 games)<br>[[Ernie Sims]] (interim; remainder of season)')] == ['Ernie Sims']
    assert [n for n, _ in people('[[Stephen Belichick]]{{ref|a}} (2nd season; first 2 games)<br>[[Brian Belichick]]{{ref|a}} (interim; remainder of season)')] == ['Brian Belichick']
    assert [n for n, _ in people('[[Rod Smith (American football coach)|Rod Smith]] (2nd season; fired November 15) <br> [[Gunter Brewer]] (interim)')] == ['Gunter Brewer']
    print('cfb_coord_sync: self-test ok')


def main():
    if '--test' in sys.argv:
        return self_test()
    dry = '--dry' in sys.argv
    dump = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--dump=')), None)
    S = json.load(open(P))
    teams = S['teams']
    T = json.load(open(TEAMS))
    full = {str(t['tid']): t.get('full') for t in T.get('teams', [])}
    season = int(S.get('season') or T.get('season') or (dt.date.today().year if dt.date.today().month >= 3 else dt.date.today().year - 1))
    today = dt.date.today().isoformat()
    got, pages = 0, {}
    for tid, t in teams.items():
        title = title_for(tid, t, full.get(tid), season)
        if not title:
            continue
        text = raw(title)
        time.sleep(PACE)
        if not text or 'football' not in text[:4000].lower():
            continue
        got += 1
        pages[tid] = {'title': title, **parse(text)}
    if dump:
        json.dump(pages, open(dump, 'w'), indent=1, ensure_ascii=False)
    if got < 0.8 * len(teams):
        print(f'cfb coordinators: only {got} of {len(teams)} Wikipedia pages answered, nothing changed')
        return 0
    changes = []
    for tid, pg in pages.items():
        t = teams[tid]
        for role in ('oc', 'dc'):
            new = pg[role]
            if not new:
                continue
            old = t.get(role) or {}
            have = {names.key(n) for n in role_names(old)}
            want = {names.key(n) for n, _ in new}
            sch = pg['off_scheme' if role == 'oc' else 'def_scheme']
            # the infobox often lists one of two co-coordinators: the file changes only when the infobox names
            # someone it does not have
            if want <= have:
                if sch and old.get('scheme') != sch:
                    old['scheme'] = sch
                old['wikiAsof'] = today
                t[role] = old
                continue
            changes.append({'date': today, 'tid': tid, 'role': role, 'was': role_names(old), 'now': [n for n, _ in new], 'title': pg['title']})
            ns = [n for n, _ in new]
            wikis = {n: 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(w.replace(' ', '_'), safe="()',_-.") for n, w in new if w}
            e = {'name': ' / '.join(ns), 'src': f"wikipedia:{pg['title']}#infobox", 'wiki': wikis.get(ns[0]), 'wikiAsof': today}
            if len(ns) > 1:
                e['names'] = ns
                e['wikis'] = wikis
            if sch:
                e['scheme'] = sch
            if old.get('name'):
                e['prev'] = [{'name': old['name'], 'until': today}] + (old.get('prev') or [])[:3]
            t[role] = e
    for c in changes:
        print(f"cfb coordinators: team {c['tid']} {c['role']} {' / '.join(c['was']) or '-'} -> {' / '.join(c['now'])}")
    if not dry:
        S['coordSynced'] = today
        with open(P, 'w') as f:
            json.dump(S, f, indent=1, ensure_ascii=False)
            f.write('\n')
        if changes:
            os.makedirs(os.path.dirname(LOG), exist_ok=True)
            with open(LOG, 'a') as f:
                for c in changes:
                    f.write(json.dumps(c, ensure_ascii=False) + '\n')
    print(f'cfb coordinators: {len(changes)} change(s), {got}/{len(teams)} pages read')
    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
