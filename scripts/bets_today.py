#!/usr/bin/env python3
"""The exact bets to place now, from the Picks tab's logs (data/games_picks_<sport>.json, the same rows the
Predictions picks tab and the paper book read). Used by the place-your-picks reminders (Noah, Oct 28 2026).

Every open pick that hasn't started: not a pass, not withdrawn. Each line gives the game, start (ET), market, the
side at the current line and price (Novig, else DraftKings; the flagged one when no current quote), the bet-to line
and the stake: Kelly % and dollars on the paper book's bankroll (data/paper_book.json, or --bankroll). Picks flagged
in the last --new hours are marked new.

  python3 scripts/bets_today.py                     # working tree
  python3 scripts/bets_today.py --ref origin/main   # what the live site shows (git fetch first)
  python3 scripts/bets_today.py --ref origin/main --sent FILE   # only picks not already sent; records them in FILE

With --sent, one bet a game per family (the side: spread or moneyline; the total; each prop): a pick on a game whose
family already has an unstarted sent bet is held back, so a flip (Murray State at Tennessee State under 160.5, then
over 161.5 after the CBB totals recentring, Nov 1 2026) never asks for both sides. And a sent pick that turns pass or
is withdrawn before its start is listed once under "Skip if not placed yet" (and once more if it comes back).
"""
import argparse
import json
import math
import os
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SPORTS = [("nba", "NBA"), ("cbb", "CBB"), ("tennis", "Tennis"), ("nfl", "NFL"), ("nflprops", "NFL prop"), ("cfb", "CFB")]
ET = ZoneInfo("America/New_York")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import night_cap as NC  # noqa: E402


def night_of(k):
    """ET date of a start (datetime or ledger stamp)"""
    k = ts(k.replace("Z", ":00Z") if len(k) == 17 else k) if isinstance(k, str) else k
    return k.astimezone(ET).date().isoformat()


def load(sport, ref, path=None):
    path = path or f"data/games_picks_{sport}.json"
    try:
        if ref:
            return json.loads(subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, check=True,
                                             text=True).stdout)
        with open(path) as f:
            return json.load(f)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def num(v):
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:g}"


def price(v):
    return f"+{num(v)}" if float(v) > 0 else num(v)


def bet(p, line):
    team = p.get("homeN" if p["side"] == "home" else "awayN") or (p["home"] if p["side"] == "home" else p["away"])
    if p["mk"] == "prop":
        return f"{p['player']} {p['side']} {num(line)} {p['statN']}"
    if p["mk"] == "total":
        return f"{p['side']} {num(line)}"
    if p["mk"] == "ml":
        return f"{team} ML"
    l = -float(line) if p["side"] == "home" else float(line)
    return f"{team} {'pk' if l == 0 else ('+' if l > 0 else '') + num(l)}"


def fam(key):
    """sport:game:family of a ledger key sport:id:mk:side"""
    sp, gid, mk, _ = key.split(":", 3)
    return f"{sp}:{gid}:{'total' if mk == 'total' else 'prop' if mk == 'prop' else 'side'}"


def states(ref):
    """every listed pick's key -> 'live' (clears now with a stake) or 'pass' (keys not here are withdrawn or gone), and
    each game's name by sport:id"""
    out, names = {}, {}
    for s, _ in SPORTS:
        d = load(s, ref) or {}
        for p in d.get("log", []) + d.get("withdrawn", []) + d.get("picks", []):
            names[f"{s}:{p['id']}"] = f"{p.get('awayN') or p.get('away')} @ {p.get('homeN') or p.get('home')}"
        for p in d.get("picks", []):
            units = (p.get("now") or {}).get("units", p.get("units"))
            out[f"{s}:{p['id']}:{p['mk']}:{p['side']}"] = "pass" if p.get("pass") or not units else "live"
    return out, names


def rows(ref, now, new_h, days):
    out = []
    for s, name in SPORTS:
        d = load(s, ref)
        if not d:
            continue
        for p in d.get("picks", []):
            k = ts(p.get("kick"))
            if p.get("pass") or not k or k <= now or k > now + timedelta(days=days):
                continue
            cur = p.get("now") or {}
            line = cur.get("line", p.get("line")) if cur.get("mk", p["mk"]) == p["mk"] else p.get("line")
            pr = cur.get("price", p["price"])
            units = cur.get("units", p["units"])
            if not units:
                continue
            to = ""
            if p.get("betTo") is not None and p["mk"] != "ml":
                to = (f"{p['side']} {'<=' if p['side'] == 'over' else '>='} {num(p['betTo'])}" if p["mk"] == "total"
                      else f"{bet(p, p['betTo'])} or better")
            game = f"{p.get('awayN') or p['away']} @ {p.get('homeN') or p['home']}"
            if s == "tennis" and p.get("ev_"):
                game += f" ({p['ev_']})"
            fl = ts(p.get("flagged"))
            out.append({"key": f"{s}:{p['id']}:{p['mk']}:{p['side']}", "k": k, "sport": name, "game": game, "mk": {"ml": "moneyline", "prop": "player prop"}.get(p["mk"], p["mk"]),
                        "bet": bet(p, line), "price": price(pr), "to": to, "kelly": float(units),
                        "new": bool(fl and fl >= now - timedelta(hours=new_h))})
    return sorted(out, key=lambda r: (r["k"], r["sport"], r["game"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", help="git ref to read the logs from, e.g. origin/main")
    ap.add_argument("--new", type=float, default=12, help="mark picks flagged in the last N hours (default 12)")
    ap.add_argument("--days", type=float, default=7, help="only picks starting within N days (default 7)")
    ap.add_argument("--bankroll", type=float, help="bankroll in dollars (default: the paper book's, data/paper_book.json)")
    ap.add_argument("--sent", help="JSON ledger of picks already sent: list only the rest, then add them to it")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    rs = rows(a.ref, now, a.new, a.days)
    bank = a.bankroll or ((load(None, a.ref, "data/paper_book.json") or {}).get("bankroll") or {}).get("now")
    sent = {}
    held, skip, back, full, capped = [], [], [], [], {}
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    if a.sent:
        try:
            with open(a.sent) as f:
                sent = json.load(f)
        except (OSError, json.JSONDecodeError):
            sent = {}
        rs = [r for r in rs if r["key"] not in sent]
        # sent bets not yet started, by game family: a new pick there is the other side (or the other market) of a
        # bet Noah may already hold, so it is held back, not sent
        opn = {}
        for k, v in sent.items():
            if v.get("kick", "") > stamp and not v.get("held"):
                opn.setdefault(fam(k), []).append(v)
        held = [(r, opn[fam(r["key"])]) for r in rs if fam(r["key"]) in opn]
        # listed once: recorded as held (not a bet) so the next alert doesn't repeat it
        sent.update({r["key"]: {"held": stamp, "kick": r["k"].strftime("%Y-%m-%dT%H:%MZ"), "bet": f"{r['bet']} {r['price']}",
                                "kelly": 0.0, "game": r["game"]} for r, _ in held})
        rs = [r for r in rs if fam(r["key"]) not in opn]
        # the nightly cap (scripts/night_cap.py, Noah Nov 1 2026: 40% a night): bets already sent for an ET night count
        # first; new picks share what is left, scaled down together, and none go out once the night is full
        out_n = {}
        for k, v in sent.items():
            if v.get("kick", "") > stamp and not v.get("held"):
                out_n[night_of(v["kick"])] = out_n.get(night_of(v["kick"]), 0.0) + float(v.get("kelly") or 0)
        new_n = {}
        for r in rs:
            new_n[night_of(r["k"])] = new_n.get(night_of(r["k"]), 0.0) + r["kelly"]
        full = []
        for r in rs:
            n = night_of(r["k"])
            room = NC.CAP - out_n.get(n, 0.0)
            if room < 0.25:
                full.append(r)
            elif new_n[n] > room:
                r["kelly"] = max(0.25, math.floor(r["kelly"] * room / new_n[n] * 4 + 1e-9) / 4)
        sent.update({r["key"]: {"held": stamp, "kick": r["k"].strftime("%Y-%m-%dT%H:%MZ"), "bet": f"{r['bet']} {r['price']}",
                                "kelly": 0.0, "game": r["game"], "why": "night cap"} for r in full})
        rs = [r for r in rs if r not in full]
        capped = {n: round(out_n.get(n, 0.0), 2) for n in {night_of(r["k"]) for r in full}}
        st, names = states(a.ref)
        for k, v in sent.items():
            v.setdefault("game", names.get(":".join(k.split(":")[:2])) or "")
        label = dict(SPORTS)
        for k, v in sorted(sent.items(), key=lambda kv: kv[1].get("kick", "")):
            if v.get("kick", "") <= stamp or v.get("held"):
                continue
            now_st = st.get(k, "withdrawn")
            if now_st != "live" and not v.get("skip"):
                v["skip"] = stamp
                skip.append((k, v, now_st))
            elif now_st == "live" and v.get("skip"):
                v.pop("skip")
                back.append((k, v))
    if a.sent and (skip or back or held or full):
        if full:
            print("**Not sent, night full** (" + "; ".join(f"{n}: {num(v)}% already sent" for n, v in sorted(capped.items()))
                  + f", cap {num(NC.CAP)}%): " + ", ".join(f"{r['game']} {r['bet']}" for r in full))
        if skip:
            print("**Skip if not placed yet** (no longer clears its cut; keep it if already placed):")
            for k, v, why in skip:
                print(f"- {label.get(k.split(':')[0], k.split(':')[0])} {kick_et(v['kick'])}, {v['game'] or k.split(':')[1]}: {v['bet']} ({why})")
        if back:
            print("**Back on** (clears again; place if skipped):")
            for k, v in back:
                print(f"- {label.get(k.split(':')[0], k.split(':')[0])} {kick_et(v['kick'])}, {v['game']}: {v['bet']}, {num(v['kelly'])}% Kelly")
        if held:
            print("**Not sent** (a bet on this game's " + "side/total is already out):")
            for r, vs in held:
                print(f"- {r['sport']} {r['game']}: {r['bet']} {r['price']}; already sent {', '.join(v['bet'] for v in vs)}")
    if not rs:
        print("No new picks." if a.sent else "No open picks right now.")
        if a.sent and (skip or back or held or full):
            save(a.sent, sent, now)
        return
    day = None
    for r in rs:
        k = r["k"].astimezone(ET)
        if k.date() != day:
            day = k.date()
            print(f"\n**{k.strftime('%a %b')} {k.day}**")
        to = f", bet to {r['to']}" if r["to"] else ""
        print(f"- {r['sport']} {k.strftime('%I:%M %p').lstrip('0')} ET, {r['game']}: **{r['bet']} {r['price']}** "
              f"({r['mk']}{to}), **{num(r['kelly'])}% Kelly**{dollars(r['kelly'], bank)}"
              f"{' (new)' if r['new'] and not a.sent else ''}")
    tot = sum(r["kelly"] for r in rs)
    print(f"\n{len(rs)} bet{'s' if len(rs) != 1 else ''}, {num(round(tot, 2))}% of bankroll{dollars(tot, bank)} in all"
          f"{f' (bankroll ${bank:,.2f})' if bank else ''}. Skip any whose line has moved past its bet-to.")
    if a.sent:
        sent.update({r["key"]: {"sent": stamp, "kick": r["k"].strftime("%Y-%m-%dT%H:%MZ"), "bet": f"{r['bet']} {r['price']}",
                                "kelly": r["kelly"], "game": r["game"]} for r in rs})
        save(a.sent, sent, now)


def save(fn, sent, now):
    cut = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%MZ")
    sent = {k: v for k, v in sent.items() if v.get("kick", "") >= cut}
    with open(fn, "w") as f:
        json.dump(sent, f, indent=1, sort_keys=True)


def kick_et(s):
    k = ts(s.replace("Z", ":00Z") if len(s) == 17 else s).astimezone(ET)
    return f"{k.strftime('%a')} {k.strftime('%I:%M %p').lstrip('0')} ET"


def dollars(pct, bank):
    return f" (${bank * pct / 100:,.2f})" if bank else ""


if __name__ == "__main__":
    main()
