# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Parse the pulled NCAA (College Hockey News) and Swedish federation skater pages into one table.

usage: shots_tables.py <chn_dir> <swe_dir> <out.json>
out: {"NCAA": {"<endYear>": [[name, pos F/D, gp, shots, team], ...]}, "SHL": {...}, "HockeyAllsvenskan": {...}}
"""
import html, json, os, re, sys


def cells(tr):
    return [html.unescape(re.sub(r'<[^>]+>', '', c)).replace('\xa0', ' ').strip() for c in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', tr, re.S)]


def num(s):
    try:
        return int(s)
    except ValueError:
        return None


def chn(path):
    t = open(path, encoding='utf8', errors='replace').read()
    out, hdr = [], None
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
        c = cells(tr)
        if 'Name' in c and 'Shots' in c:
            hdr = {k: i for i, k in enumerate(c)}
            continue
        if not hdr or len(c) < len(hdr) - 2:
            continue
        gp, sh = num(c[hdr['GP']]), num(c[hdr['Shots']])
        pos = c[hdr['Pos']]
        if gp is None or sh is None or not pos or pos == 'G':
            continue
        out.append([re.sub(r'\s+', ' ', c[hdr['Name']]), 'D' if pos == 'D' else 'F', gp, sh, c[hdr['Team']]])
    return out


def swe(path):
    t = open(path, encoding='utf8', errors='replace').read()
    out, hdr = [], None
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
        c = cells(tr)
        if 'Name' in c and 'SOG' in c and 'GP' in c:
            hdr = {k: i for i, k in enumerate(c)}
            continue
        if 'Name' in c and 'SOG' not in c:
            hdr = None
            continue
        if not hdr or len(c) != len(hdr):
            continue
        gp, sh = num(c[hdr['GP']]), num(c[hdr['SOG']])
        pos = c[hdr['Pos']]
        if gp is None or sh is None or pos in ('GK', ''):
            continue
        n = c[hdr['Name']].split(', ', 1)
        out.append([(n[1] + ' ' + n[0]) if len(n) == 2 else c[hdr['Name']], 'D' if pos.endswith('D') else 'F', gp, sh, ''])
    return out


def main(chn_dir, swe_dir, outp):
    res = {'NCAA': {}, 'SHL': {}, 'HockeyAllsvenskan': {}}
    for f in sorted(os.listdir(chn_dir)):
        m = re.match(r'ov_(\d{4})(\d{4})\.html', f)
        if m:
            res['NCAA'][m.group(2)] = chn(os.path.join(chn_dir, f))
    for f in sorted(os.listdir(swe_dir)):
        m = re.match(r'(SHL|HockeyAllsvenskan)_(\d{4})\.html', f)
        if m:
            res[m.group(1)][m.group(2)] = swe(os.path.join(swe_dir, f))
    for lg, d in res.items():
        print(lg, {y: (len(v), sum(1 for p in v if p[3] > 0)) for y, v in d.items()})
    json.dump(res, open(outp, 'w'))


if __name__ == '__main__':
    main(*sys.argv[1:4])
