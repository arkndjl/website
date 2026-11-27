"""The DECT history rows (scripts/dect.py's own, read without touching it): run its main() with the output sent to a
scratch file and keep the locals of main() (CFB fall boards H) and nba() (CBB ranked boards)."""
import importlib.util, os, sys, pickle
HERE = os.path.dirname(os.path.abspath(__file__)); SCR = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, '.hist.pkl')


def load():
    if os.path.exists(CACHE): return pickle.load(open(CACHE, 'rb'))
    sys.path.insert(0, SCR)
    spec = importlib.util.spec_from_file_location('dect', os.path.join(SCR, 'dect.py')); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.OUT = os.path.join(HERE, '.dect_fit_scratch.json')
    # dect.py prints json.dumps(...) near the end of nba() and json.dump(...) at the end of main(): a stand-in json
    # module there copies the caller's locals at those points (no change to dect.py, no tracing)
    import json as _json
    got = {}
    class J:
        def __getattr__(self, k): return getattr(_json, k)
        def dumps(self, *a, **k):
            f = sys._getframe(1)
            if f.f_code.co_name == 'nba': got['nba'] = dict(f.f_locals)
            return _json.dumps(*a, **k)
        def dump(self, *a, **k):
            f = sys._getframe(1)
            if f.f_code.co_name == 'main':
                L = f.f_locals; got['main'] = dict(L)
                # every non-grad fall board row of every draft (the history check stops at 2025; the 2026 boards are the
                # 2025 season, the second Transfer% fold), priced the way the check prices them
                import math as _m, numpy as _np
                S, b, PAY = L['S'], L['b'], L['PAY']
                ext = []
                for r in L['fall']:
                    if r['grad'] or r['draft'] < 2022 or r in L['H']: continue
                    r['ageD'] = (r['age'] + r['days'] / 365.25 if r['age'] is not None else 21.8) - 0.5
                    yr = min(r['draft'], 2026)
                    r['nil'] = 1e-6 * _m.exp(S['a'] + S['b'] * r['lx'] + S['qb'] * (r['pos'] == 'QB') + (S['fcs'] if r['fcs'] else 0 if r['p4'] else S['g5'])) * PAY.NILM[yr] / PAY.NILM[2026]
                    B = _np.column_stack(L['nodes'](r['lx'], r['grp'])); c = m.sides(B, r['ageD'] - 22, b[3], r['nil']); r['ce'], r['med'] = c[0], c[4]; r['vd'] = c[1]
                    r['even'] = m.verdict(B, r['ageD'] - 22, b[3], L['ASE'], r['nil'], m.SIG['cfb'])[3]
                    ext.append(r)
                got['cfb_extra'] = ext
            return _json.dump(*a, **k)
    m.json = J()
    m.main()
    keep = lambda r: {k: v for k, v in r.items() if isinstance(v, (int, float, str, bool, type(None)))}
    M, N = got['main'], got['nba']
    out = {'cfb': [keep(r) for r in M['H']], 'cfb_extra': [keep(r) for r in got['cfb_extra']], 'cbb': [keep(r) for r in N['ranked']], 'cbb_rows': [keep(r) for r in N['rows']],
           'cfb_ageB': M['b'][3], 'cfb_ageSE': M['ASE'], 'gap': M['GAP']}
    pickle.dump(out, open(CACHE, 'wb'))
    return out


if __name__ == '__main__':
    h = load()
    print(len(h['cfb']), len(h['cbb']), len(h['cbb_rows'])); print(h['cfb'][0]); print(h['cbb'][0]); print(h['cbb_rows'][0])
