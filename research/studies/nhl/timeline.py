"""Shared helpers: per-game third-period second-by-second state from play-by-play (+ optional goalie shifts)."""
import gzip, json, os

def mmss(x):
    m, s = x.split(":"); return int(m) * 60 + int(s)

def code(c):
    """situationCode -> (away goalie in, away skaters, home skaters, home goalie in)"""
    if not c or len(c) != 4 or not c.isdigit(): return None
    return int(c[0]), int(c[1]), int(c[2]), int(c[3])

def goalie_in_from_shifts(path, gl, home, away, period=3):
    """Return dict team -> list[1200] of 1/0 goalie on ice in given period, or None."""
    try:
        rows = json.load(gzip.open(path)).get("data", [])
    except Exception:
        return None
    gs = set(gl)
    out = {home: [0] * 1200, away: [0] * 1200}
    seen = False
    for r in rows:
        if r.get("period") != period or r.get("playerId") not in gs or r.get("typeCode") != 517: continue
        if not r.get("startTime") or not r.get("endTime"): continue
        t = r.get("teamId")
        if t not in out: continue
        a, b = mmss(r["startTime"]), mmss(r["endTime"])
        for s in range(a, min(b, 1200)): out[t][s] = 1
        seen = True
    return out if seen else None

def p3_timeline(g, shifts=None):
    """Seconds 0..1199 of period 3. Each second s covers (s, s+1].
    Returns list of dicts per second: hg, ag (goalie in), hsk, ask, diff (home-away before), dp (delayed penalty flag)
    and list of goals (sec, team, home goalie in, away goalie in, hsk, ask, diff_before)."""
    ev = [e for e in g["ev"] if e[0] == 3]
    if not ev: return None, None
    # score at start of P3
    hs = as_ = 0
    for e in g["ev"]:
        if e[0] < 3 and e[3] == "goal" and e[6] is not None: hs, as_ = e[6], e[7]
    st = [None] * 1200
    goals = []
    prev_t = 0; dp = False
    for e in ev:
        t = min(e[1], 1200); c = code(e[2])
        if c:
            for s in range(prev_t, t):
                st[s] = [c[3], c[0], c[2], c[1], hs - as_, dp]
        if e[3] == "goal" and e[6] is not None:
            goals.append((t, e[4], c, hs - as_))
            hs, as_ = e[6], e[7]
        if e[3] == "delayed-penalty": dp = True
        elif e[3] in ("penalty", "stoppage", "goal", "faceoff", "period-end"): dp = False
        prev_t = max(prev_t, t)
    # fill any gaps (e.g. events without codes) from the next known state
    nxt = None
    for s in range(1199, -1, -1):
        if st[s] is None: st[s] = nxt
        else: nxt = st[s]
    if shifts:
        for s in range(1200):
            if st[s] is None: continue
            h, a = shifts[g["home"]][s], shifts[g["away"]][s]
            st[s][2] = max(3, min(6, st[s][2] + st[s][0] - h)); st[s][3] = max(3, min(6, st[s][3] + st[s][1] - a))
            st[s][0], st[s][1] = h, a
    return st, goals, (hs, as_)
