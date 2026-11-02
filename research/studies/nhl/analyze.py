"""NHL goalie-pull studies. usage: python3 -I analyze.py <scratch_dir> <out_dir>
Builds per-game exposure/goal tables for late-game states, pull events, and score-effects counts; pickles them."""
import json, os, pickle, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timeline import p3_timeline, goalie_in_from_shifts

S = sys.argv[1]
KEYS = []  # state keys
def key(T_g, O_g, T_sk, O_sk, d, dp, sec):
    """Return state label for trailing-team-perspective, or None."""
    if dp: return None
    tl = 1200 - sec
    if d == 0:
        if T_g and O_g and T_sk == 5 and O_sk == 5 and tl <= 600: return "tied"
        return None
    if d < 0: return None
    dd = min(d, 3)
    if T_g and O_g:
        if T_sk == 5 and O_sk == 5 and tl <= 600: return f"5v5_d{dd}"
        if T_sk == 5 and O_sk == 4: return f"5v4_d{dd}"
        return None
    if not T_g and O_g:
        if T_sk == 6 and O_sk == 5: return f"6v5_d{dd}"
        if T_sk == 6 and O_sk == 4: return f"6v4_d{dd}"
        if T_sk == 5 and O_sk == 5 : return f"6v5_d{dd}"   # rare mis-count, goalie out at even strength
    return None

games = []; expo = []; pulls = []; fen = []
shdir = os.path.join(S, "raw", "shifts")
n_shift = 0
for line in open(os.path.join(S, "games.jsonl")):
    g = json.loads(line)
    gi = len(games)
    games.append((g["gid"], g["season"]))
    # ---- score effects: unblocked attempts and goals at 5v5 by score state, periods 1-3
    hs = as_ = 0
    for e in g["ev"]:
        if e[0] > 3: break
        if e[3] in ("shot-on-goal", "missed-shot", "goal") and e[2] == "1551" and e[4] in (g["home"], g["away"]):
            dh = hs - as_
            fen.append((gi, e[0], 1 if e[4] == g["home"] else 0, dh, 1 if e[3] == "goal" else 0))
        if e[3] == "goal" and e[6] is not None: hs, as_ = e[6], e[7]
    # ---- third-period states
    sp = os.path.join(shdir, f"{g['gid']}.json.gz")
    sh = goalie_in_from_shifts(sp, g["goalies"], g["home"], g["away"]) if os.path.exists(sp) else None
    if sh: n_shift += 1
    st, goals, fin = p3_timeline(g, sh)
    if st is None: continue
    acc = {}
    def persp(x, home):
        hg, ag, hsk, ask, diff, dp = x
        return (hg, ag, hsk, ask, diff, dp) if home else (ag, hg, ask, hsk, -diff, dp)
    for s, x in enumerate(st):
        if x is None: continue
        for home in (True, False):
            Tg, Og, Tsk, Osk, dT, dp = persp(x, home)
            if dT > 0: continue
            if dT == 0 and not home: continue   # count tied exposure once
            k = key(Tg, Og, Tsk, Osk, -dT, dp, s)
            if k: acc.setdefault(k, [0, 0, 0])[0] += 1
    for (t, team, c, dbefore) in goals:
        x = st[max(t - 1, 0)]
        if x is None: continue
        for home in (True, False):
            Tg, Og, Tsk, Osk, dT, dp = persp(x, home)
            if dT > 0 or (dT == 0 and not home): continue
            k = key(Tg, Og, Tsk, Osk, -dT, dp, max(t - 1, 0))
            if not k: continue
            Tid = g["home"] if home else g["away"]
            if team == Tid: acc.setdefault(k, [0, 0, 0])[1] += 1
            else: acc.setdefault(k, [0, 0, 0])[2] += 1
    expo.append((gi, acc))
    # ---- pulls: goalie-out spells while trailing, last 10 min of P3
    ev3 = [e for e in g["ev"] if e[0] == 3]
    for home in (True, False):
        Tid = g["home"] if home else g["away"]; Oid = g["away"] if home else g["home"]
        s = 0; spells = []
        while s < 1200:
            x = st[s]
            if x is not None and (x[0] if home else x[1]) == 0:
                s0 = s
                while s < 1200 and st[s] is not None and (st[s][0] if home else st[s][1]) == 0: s += 1
                spells.append((s0, s))
            s += 1
        for (s0, s1) in spells:
            Tg, Og, Tsk, Osk, dT, dp = persp(st[s0], home)
            if dT >= 0 or 1200 - s0 > 600: continue
            dpe = any(e[3] == "delayed-penalty" and e[4] == Oid and s0 - 5 <= e[1] <= s0 + 5 for e in ev3)
            fo = [e for e in ev3 if e[3] == "faceoff" and s0 - 1 <= e[1] <= s0 + 2]
            fz = None
            if fo:
                z = fo[0][5]; fz = z if fo[0][4] == Tid else {"O": "D", "D": "O"}.get(z, z)
            gf = any(t >= s0 and t <= s1 + 1 and team == Tid for (t, team, c, db) in goals)
            ga = any(t >= s0 and t <= s1 + 1 and team == Oid for (t, team, c, db) in goals)
            fT = (fin[0] - fin[1]) if home else (fin[1] - fin[0])
            # state at 6:00 / 10:00 left
            def dat(sec):
                x = st[sec]
                return None if x is None else ((x[4] if home else -x[4]))
            pulls.append(dict(gi=gi, season=g["season"], home=home, s0=s0, s1=s1, tl=1200 - s0, d=-dT,
                              Tsk=Tsk, Osk=Osk, dpe=dpe, fz=fz, gf=gf, ga=ga, level=fT >= 0,
                              shifts=bool(sh)))
    # trailing teams at checkpoints, for "never pulled" / censoring analysis
    for home in (True, False):
        for tl in (600, 360):
            x = st[1200 - tl]
            if x is None: continue
            dT = x[4] if home else -x[4]
            if dT < 0:
                ff = (fin[0] - fin[1]) if home else (fin[1] - fin[0])
                pulls.append(dict(gi=gi, season=g["season"], home=home, checkpoint=tl, d=-dT, level=ff >= 0,
                                  Tg=(x[0] if home else x[1]), Og=(x[1] if home else x[0]),
                                  Tsk=(x[2] if home else x[3]), Osk=(x[3] if home else x[2])))
pickle.dump(dict(games=games, expo=expo, pulls=pulls, fen=fen, n_shift=n_shift), open(os.path.join(S, "tables.pkl"), "wb"))
print("games", len(games), "with shifts", n_shift, "pull rows", len(pulls), "fenwick", len(fen))
