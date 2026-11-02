"""Possession tracking over a game's event list (normalized events from bball_common)."""

TERMINAL_NEXT = {"ft", "shot", "tov", "oreb", "dreb", "steal", "endp"}


def last_ft_flags(kinds, teams, subs):
    """True for a free throw that ends its trip (next relevant event is not an FT by the same team)."""
    n = len(kinds)
    out = [False] * n
    nxt_kind, nxt_team = None, None
    for i in range(n - 1, -1, -1):
        if kinds[i] == "ft":
            out[i] = not (nxt_kind == "ft" and nxt_team == teams[i])
        if kinds[i] in TERMINAL_NEXT:
            nxt_kind, nxt_team = kinds[i], teams[i]
    return out


def possession_after(kinds, teams, made, subs, home, away):
    """Team with the ball after each event (None = loose ball / unknown)."""
    lastft = last_ft_flags(kinds, teams, subs)
    opp = {home: away, away: home}
    pos = None
    out = []
    for i, k in enumerate(kinds):
        t = teams[i]
        if t in opp:
            if k == "shot":
                pos = opp[t] if made[i] else None
            elif k in ("oreb", "dreb", "dbreb", "steal"):
                pos = t
            elif k == "tov":
                pos = opp[t]
            elif k == "ft" and subs[i] != "special":
                if lastft[i]:
                    pos = opp[t] if made[i] else None
                else:
                    pos = t
        out.append(pos)
    return out, lastft
