#!/usr/bin/env python3
"""Check data/terms.json (the term hovers, assets/js/terms.js): every entry has a name and a one-line explanation in the
site's copy rules, and links to a glossary term that exists in data/library.json (its own, or its abbreviation group's)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAD = re.compile(r'\b(delve|robust|leverage|comprehensive|seamless|cutting-edge|unlock|empower|game-changer|elevate)\b', re.I)


def problems():
    d = json.loads((ROOT / 'data/terms.json').read_text())
    lib = json.loads((ROOT / 'data/library.json').read_text())
    have = {e['term'] for s in lib['sections'] for e in s['entries']}
    bad = []
    for gid, g in d['groups'].items():
        if g['term'] not in have:
            bad.append(f'group {gid}: "{g["term"]}" is not in the glossary (rerun scripts/library_glossary.py and scripts/library_build.py)')
    for k, e in d['terms'].items():
        for where, v in [('', e)] + [(' by ' + p, x) for p, x in (e.get('by') or {}).items()] + [(' when ' + x['m'], x) for x in e.get('when') or []]:
            for f in ('n', 'd'):
                s = v.get(f, '')
                if not where and not s:
                    bad.append(f'{k}: no "{f}"')
                if '—' in s or '–' in s or BAD.search(s) or len(s) > 150:
                    bad.append(f'{k}{where}: "{f}" breaks the copy rules (dash, word list or over 150 characters)')
            g, a = v.get('g'), v.get('a')
            if g and g not in have:
                bad.append(f'{k}{where}: glossary term "{g}" does not exist')
            if a and a not in d['groups']:
                bad.append(f'{k}{where}: group "{a}" does not exist')
        if not e.get('g') and not e.get('a'):
            bad.append(f'{k}: needs "g" (glossary term) or "a" (abbreviation group)')
    for a, k in d['alias'].items():
        if k not in d['terms']:
            bad.append(f'alias {a}: "{k}" is not a term')
    return bad, f'terms: {len(d["terms"])} entries, {len(d["alias"])} aliases, {len(bad)} problems'


def main():
    bad, line = problems()
    for b in bad:
        print(b)
    print(line)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
