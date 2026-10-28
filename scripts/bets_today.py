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
"""
import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

SPORTS = [("nba", "NBA"), ("cbb", "CBB"), ("tennis", "Tennis"), ("nfl", "NFL"), ("cfb", "CFB")]
ET = ZoneInfo("America/New_York")


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
    if p["mk"] == "total":
        return f"{p['side']} {num(line)}"
    if p["mk"] == "ml":
        return f"{team} ML"
    l = -float(line) if p["side"] == "home" else float(line)
    return f"{team} {'pk' if l == 0 else ('+' if l > 0 else '') + num(l)}"


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
            out.append({"key": f"{s}:{p['id']}:{p['mk']}:{p['side']}", "k": k, "sport": name, "game": game, "mk": {"ml": "moneyline"}.get(p["mk"], p["mk"]),
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
    if a.sent:
        try:
            with open(a.sent) as f:
                sent = json.load(f)
        except (OSError, json.JSONDecodeError):
            sent = {}
        rs = [r for r in rs if r["key"] not in sent]
    if not rs:
        print("No new picks." if a.sent else "No open picks right now.")
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
        stamp = now.strftime("%Y-%m-%dT%H:%MZ")
        sent.update({r["key"]: {"sent": stamp, "kick": r["k"].strftime("%Y-%m-%dT%H:%MZ"), "bet": f"{r['bet']} {r['price']}",
                                "kelly": r["kelly"]} for r in rs})
        cut = (now - timedelta(days=14)).strftime("%Y-%m-%dT%H:%MZ")
        sent = {k: v for k, v in sent.items() if v.get("kick", "") >= cut}
        with open(a.sent, "w") as f:
            json.dump(sent, f, indent=1, sort_keys=True)


def dollars(pct, bank):
    return f" (${bank * pct / 100:,.2f})" if bank else ""


if __name__ == "__main__":
    main()
