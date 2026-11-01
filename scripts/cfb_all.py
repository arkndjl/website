"""The College Football board's player file, read and written as one merged {asof, cols, rows}.

On disk it is two files (scripts/cfb_all.mjs has the layout): static/data/cfb-all.json, the columns the table reads,
and static/data/cfb-detail.json, the scouting-report columns (DETAIL_COLS) in the same row order, tied by dk.
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DETAIL_COLS = ['report', 'parts', 'fvd', 'mk']


def all_path(root=ROOT): return os.path.join(root, 'static', 'data', 'cfb-all.json')
def detail_path(root=ROOT): return os.path.join(root, 'static', 'data', 'cfb-detail.json')


def read_cfb_all(path=None, root=ROOT):
    """The merged board (path: the cfb-all.json to read; its cfb-detail.json sits beside it)."""
    f = path or all_path(root)
    A = json.load(open(f, encoding='utf-8'))
    g = os.path.join(os.path.dirname(f), 'cfb-detail.json')
    D = json.load(open(g, encoding='utf-8')) if os.path.exists(g) else None
    A.pop('dk', None)
    if D and D.get('dk') is not None and len(D['rows']) == len(A['rows']):
        keep = [(c, j) for j, c in enumerate(D['cols']) if c not in A['cols']]
        A['cols'] = A['cols'] + [c for c, _ in keep]
        A['rows'] = [r + [D['rows'][i][j] for _, j in keep] for i, r in enumerate(A['rows'])]
    return A


def write_cfb_all(A, root=ROOT):
    """Write a merged board as the two files (same bytes as scripts/cfb_all.mjs would)."""
    ci = {c: i for i, c in enumerate(A['cols'])}
    dcols = [c for c in DETAIL_COLS if c in ci]; core = [c for c in A['cols'] if c not in dcols]
    dump = lambda o: json.dumps(o, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    drows = [[r[ci[c]] for c in dcols] for r in A['rows']]
    dk = hashlib.sha1(dump(drows).encode('utf-8')).hexdigest()[:12]
    extra = {k: v for k, v in A.items() if k not in ('asof', 'dk', 'cols', 'rows')}
    with open(detail_path(root), 'w', encoding='utf-8') as fh:
        fh.write(dump({'asof': A.get('asof'), 'dk': dk, 'cols': dcols, 'rows': drows}))
    with open(all_path(root), 'w', encoding='utf-8') as fh:
        fh.write(dump({'asof': A.get('asof'), 'dk': dk, **extra, 'cols': core, 'rows': [[r[ci[c]] for c in core] for r in A['rows']]}))
