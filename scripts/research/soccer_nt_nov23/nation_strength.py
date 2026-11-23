"""Point-in-time national team strength (expected goal margin vs an average side, neutral ground) from
scripts/soccer_intl.py's goal ratings walked forward over every full international (martj42). For each nation the
strength *before* each match day; lookups take the last value before a date (no same-day info)."""
import bisect, gzip, json, math, os, pickle, sys
HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, SCR)
import soccer_intl as SI   # noqa: E402

CACHE = os.path.join(SCR, '.cache', 'soccer_prospects', 'nt')


def series():
    fn = os.path.join(CACHE, 'strength.pkl')
    if os.path.exists(fn):
        return pickle.load(open(fn, 'rb'))
    os.makedirs(CACHE, exist_ok=True)
    rows = SI.mj_rows()
    rows.sort(key=lambda r: (r['day'], r['h']))
    P = SI.params()
    R = SI.Ratings(P)
    S = {}
    for r in rows:
        h, a = r['h'], r['a']
        for t in (h, a):
            if R.n[t] >= 5:
                S.setdefault(t, ([], []))
                S[t][0].append(r['day']); S[t][1].append(R.strength(t))
        R._decay(h, r['day']); R._decay(a, r['day'])
        lh, la = R.rates(h, a, r['neu'])
        R.update(r, lh, la)
    pickle.dump(S, open(fn, 'wb'))
    return S


def at(S, team, day):
    s = S.get(team)
    if not s:
        return None
    i = bisect.bisect_left(s[0], day)       # strictly before day
    return s[1][i - 1] if i else None


if __name__ == '__main__':
    S = series()
    for t in ['Denmark', 'Spain', 'San Marino', 'Brazil', 'Norway']:
        print(t, at(S, t, '2026-11-20'), at(S, t, '2016-06-01'))
