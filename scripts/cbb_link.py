#!/usr/bin/env python3
"""Link every Barttorvik college career (2008 on) to its NBA career and to its recruiting grades.

    python3 scripts/cbb_link.py     # writes scripts/.cache/cbb/careers.json

NBA side (Basketball-Reference): drafted players by draft page (name, draft year = last college season or the
one after, college name as the tie-break); undrafted NBA players by name and age (NBA age within 1.5 years of
the Barttorvik date of birth, first NBA season within three years of the last college one).
Recruiting side: On3 industry (consensus) rating and rank, 247Sports composite, matched by name with the
class year = first D-I season - 1 (or - 2 for a prep year).

Each career gets its NBA role tier (the realized FV, see TIERS) and a peak BPM.
"""
import json, os, re, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cbb_data as D

FIRST, LAST = 2008, 2026
NBA_LAST = 2026
SEASON_G = {2012: 66, 2020: 70, 2021: 72}   # lockout and pandemic seasons; 82 otherwise

# realized FV: the NBA role a career reached (checked in order, the first that holds)
TIERS = [
    (80, '3+ All-NBA', lambda c: c['allnba'] >= 3),
    (75, '2 All-NBA', lambda c: c['allnba'] == 2),
    (70, 'All-NBA', lambda c: c['allnba'] == 1),
    (65, '2+ All-Star', lambda c: c['allstar'] >= 2),
    (60, 'All-Star', lambda c: c['allstar'] == 1),
    (55, '6+ seasons as a starter', lambda c: c['starts'] >= 6),
    (50, '4+ seasons as a starter', lambda c: c['starts'] >= 4),
    (45, '2+ seasons as a starter', lambda c: c['starts'] >= 2),
    (40, 'rotation, 3+ seasons', lambda c: c['rot'] >= 3),
    (35, 'bench, 100+ games', lambda c: c['games'] >= 100),
    (30, 'reached the NBA', lambda c: c['games'] >= 1),
    (20, 'non-NBA', lambda c: True),
]


def tier(c):
    for fv, label, ok in TIERS:
        if ok(c): return fv, label


def team_key(s):
    s = D.norm(s).replace('state', 'st').replace('saint', 'st').replace('university', '').replace('of ', '')
    return re.sub(r'\s+', '', s)


def main():
    seasons = {y: D.load_bt(y) for y in range(FIRST, LAST + 1)}
    careers = {}
    for y, rows in seasons.items():
        for r in rows:
            c = careers.setdefault(r['pid'], {'pid': r['pid'], 'name': r['name'], 'key': r['key'], 'seasons': []})
            c['seasons'].append(r)
            c['name'], c['key'] = r['name'], r['key']
    for c in careers.values():
        c['seasons'].sort(key=lambda r: r['year'])
        c['first'], c['last'] = c['seasons'][0]['year'], c['seasons'][-1]['year']
        c['dob'] = next((r['dob'] for r in reversed(c['seasons']) if r['dob']), None)
        c['keys'] = {r['key'] for r in c['seasons']}
    by_key = defaultdict(list)
    for c in careers.values():
        for k in c['keys']: by_key[k].append(c)
    by_last = defaultdict(list)
    for c in careers.values():
        if c['key']: by_last[tuple(c['key'].split()[-1:])].append(c)
    print(f'{len(careers)} college careers {FIRST}-{LAST}')

    # ---- NBA careers
    nba = defaultdict(list)
    for y in range(2009, NBA_LAST + 1):
        for s in D.load_nba_seasons(y): nba[s['bref']].append(s)
    allnba, allstar = D.load_awards()
    drafts = [p for y in range(2008, NBA_LAST + 1) for p in D.load_draft(y)]
    linked = {}
    miss = []
    for p in drafts:
        cands = [c for c in by_key.get(p['key'], []) if p['year'] - 1 <= c['last'] <= p['year']]
        if len(cands) > 1:
            tk = team_key(p['college'])
            cands = sorted(cands, key=lambda c: (team_key(c['seasons'][-1]['team'])[:5] != tk[:5], c['last'] != p['year']))
        if not cands and p['college']:
            # nicknames (Bam / Edrice, Moe / Maurice): same surname, same college, right year, only one such player
            last, tk = p['key'].split()[-1:], team_key(p['college'])[:5]
            cands = [c for c in by_last.get(tuple(last), []) if p['year'] - 1 <= c['last'] <= p['year']
                     and team_key(c['seasons'][-1]['team'])[:5] == tk and (c['seasons'][-1]['min_per'] or 0) >= 15]
            if len(cands) != 1: cands = []
        if cands:
            c = cands[0]
            if c['pid'] not in linked: linked[c['pid']] = (p['bref'], p['year'], p['pick'])
        elif p['college'] and p['year'] >= FIRST + 1:
            miss.append(p)
    drafted_bref = {v[0] for v in linked.values()}
    # undrafted NBA players: name + age
    nba_first = {}
    for b, ss in nba.items():
        f = min(s['year'] for s in ss)
        age = next((s['age'] for s in ss if s['year'] == f), None)
        nba_first[b] = (f, age, ss[0]['name'])
    all_drafted = {p['bref'] for p in drafts}
    und = 0
    for b, (f, age, name) in nba_first.items():
        if b in all_drafted: continue
        for c in by_key.get(D.norm(name), []):
            if c['pid'] in linked or not (f - 3 <= c['last'] <= f - 1 + 1) or c['last'] >= f + 1: continue
            a = D.age_on(c['dob'], f - 1, 2, 1) if c['dob'] else None   # bbref age = age on Feb 1 of the season
            if a is not None and age is not None and abs((a + 1) - age) > 1.5: continue
            linked[c['pid']] = (b, None, None); und += 1
            break
    print(f'NBA: {len(drafted_bref)} drafted players linked, {und} undrafted NBA players linked; '
          f'{len(miss)} drafted college players not found (e.g. {", ".join(p["name"] + " " + str(p["year"]) for p in miss[:8])})')

    # databallr DPM by season (scripts/cbb_dpm.mjs), matched to Basketball-Reference ids by name and season
    dpm = defaultdict(list)
    by_ns = {}
    for b, ss in nba.items():
        for x in ss: by_ns[(D.norm(x['name']), x['year'])] = b
    for y in range(2010, NBA_LAST + 1):
        pth = os.path.join(D.CACHE, 'dpm', f'{y}.json')
        if not os.path.exists(pth): continue
        for x in json.load(open(pth)):
            b = by_ns.get((D.norm(x['name']), x['season']))
            if b: dpm[b].append(x)
    print(f'DPM: {sum(len(v) for v in dpm.values())} player seasons matched to Basketball-Reference')

    # ---- outcome per career
    for c in careers.values():
        b, dy, pick = linked.get(c['pid'], (None, None, None))
        ss = nba.get(b, []) if b else []
        o = {'bref': b, 'draft': dy, 'pick': pick, 'allnba': allnba.get(b, 0) if b else 0, 'allstar': allstar.get(b, 0) if b else 0,
             'games': sum(s['g'] for s in ss), 'starts': 0, 'rot': 0, 'nba_seasons': len(ss)}
        vals = []
        for s in ss:
            G = SEASON_G.get(s['year'], 82)
            if s['gs'] >= 0.5 * G: o['starts'] += 1
            if s['mp'] >= 1000 * G / 82: o['rot'] += 1
            if s['bpm'] is not None:
                vals.append((s['mp'] * s['bpm'] + 500 * -2.0) / (s['mp'] + 500))  # low-minute seasons shrink to replacement
        vals.sort(reverse=True)
        vals += [-2.5] * 3
        o['peak'] = round(sum(vals[:3]) / 3, 2) if ss else None
        dv = sorted(((x['min'] * x['dpm'] + 500 * -2.0) / (x['min'] + 500) for x in dpm.get(b, [])), reverse=True) + [-2.5] * 3
        o['peakDpm'] = round(sum(dv[:3]) / 3, 2) if b and dpm.get(b) else None
        o['fv'], o['role'] = tier(o)
        c['nba'] = o

    # ---- recruiting grades
    rec = defaultdict(dict)
    for cls in range(2006, LAST + 1):
        for r in D.load_on3(cls): rec[cls].setdefault(r['key'], {}).update({'on3': r['cons'], 'on3rk': r['consRank'], 'on3own': r['on3'], 'on3slug': r['slug'], 'on3img': r.get('img')})
        for r in ([] if os.environ.get("NO247") else D.load_247(cls)): rec[cls].setdefault(r['key'], {}).update({'r247': r['r247'], 'rk247': r['rank247']})
    hit = 0
    for c in careers.values():
        g = None
        for k in c['keys']:
            for cls in (c['first'] - 1, c['first'] - 2, c['first']):
                if k in rec.get(cls, {}): g = dict(rec[cls][k], cls=cls); break
            if g: break
        c['rec'] = g
        hit += bool(g)
    print(f'recruiting grades matched for {hit} careers')

    out = []
    for c in careers.values():
        out.append({k: c[k] for k in ('pid', 'name', 'first', 'last', 'dob', 'nba', 'rec')} | {'seasons': [
            {k: r[k] for k in D.BT_COLS + ['hti'] if k not in ('home', 'num')} for r in c['seasons']]})
    json.dump(out, open(os.path.join(D.CACHE, 'careers.json'), 'w'))
    # quick look: role tiers per college class that has finished
    cnt = defaultdict(lambda: defaultdict(int))
    for c in careers.values():
        if c['last'] <= 2019: cnt[c['nba']['fv']][c['last']] += 1
    for fv, label, _ in TIERS:
        print(fv, label, dict(sorted(cnt[fv].items())))


if __name__ == '__main__':
    main()
