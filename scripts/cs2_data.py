#!/usr/bin/env python3
"""Counter-Strike data layer (the COUNTER-STRIKE ARKBOARD): every pro CS2 series between ranked rosters since early
2024, from free sources.

    python3 scripts/cs2_data.py          # sync Valve's standings repo + Liquipedia's match ticker, rebuild the history

Sources (free, no key):
  - Valve's Regional Standings (github.com/ValveSoftware/counter-strike_regional_standings, the VRS that seeds Major
    invites): every published snapshot (weekly Aug-Dec 2024, monthly since) lists every ranked roster's series over
    the six months before it: date, opponent, win/loss, the five players, and the roster's VRS points. The union of
    all snapshots is the series history (Feb 2024 on); each snapshot's points are VRS as it stood that day, the
    baseline our ratings are scored against. Shallow clone in scripts/.cache/cs/vrs (~300 MB, not committed).
  - Liquipedia (liquipedia.net/counterstrike, CC BY-SA 3.0), one API call per run (Liquipedia:Matches, under the
    API terms: gzip, our user agent, one parse a run): series about to start and just finished, with the format (Bo1,
    Bo3, Bo5), the score and the event. Finished series accumulate in scripts/data/cs2_lp_results.json.gz, so the
    ratings keep moving between Valve's monthly snapshots.

Writes scripts/data/cs2_history.json.gz (committed): {"series": [[date, teamA, teamB, winner 0/1, rosterA, rosterB, src,
fmt (+ ts, scoreA, scoreB, event from Liquipedia)]], "vrs": {snapshot date: [[rank, name, points, roster, region]]}, "upcoming": [...], "logos": {...}}.
"""
import gzip
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / ".cache" / "cs"
VRS = CACHE / "vrs"
VRS_GIT = "https://github.com/ValveSoftware/counter-strike_regional_standings"
OUT = ROOT / "scripts" / "data" / "cs2_history.json.gz"
LP_RES = ROOT / "scripts" / "data" / "cs2_lp_results.json.gz"
UA = "arkndjl.net-arkboard/1.0 (https://arkndjl.net; arkndjl@gmail.com)"
LP_API = "https://liquipedia.net/counterstrike/api.php?action=parse&page=Liquipedia:Matches&format=json&prop=text"

# Liquipedia's short names that differ from Valve's (after key()); extend when a ticker team fails to join
ALIAS = {"navi": "natusvincere", "mongolz": "themongolz", "nip": "ninjasinpyjamas", "fazeclan": "faze"}


def key(name):
    """Team join key: lower case, letters and digits, a leading/trailing 'team' and 'esports'/'gaming' dropped."""
    # Liquipedia's link titles for teams without a page carry " (page does not exist)"
    k = re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(page does not exist\)", "", html.unescape(name or ""), flags=re.I).lower())
    for w in ("esports", "esport", "gaming", "club"):
        if k.endswith(w) and len(k) > len(w) + 1:
            k = k[: -len(w)]
    if k.startswith("team") and len(k) > 5:
        k = k[4:]
    if k.endswith("team") and len(k) > 5:
        k = k[:-4]
    return ALIAS.get(k, k)


def sync_vrs():
    if (VRS / ".git").exists():
        subprocess.run(["git", "-C", str(VRS), "fetch", "-q", "--depth", "1", "origin", "main"], check=True)
        subprocess.run(["git", "-C", str(VRS), "reset", "-q", "--hard", "origin/main"], check=True)
    else:
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", VRS_GIT, str(VRS)], check=True)


ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d{4}-\d\d-\d\d)\s*\|\s*(.+?)\s*\|\s*([WL])\s*\|(.*)\|\s*(.+?)\s*\|\s*$")


def parse_snapshots():
    """-> (series rows per snapshot, standings per snapshot). Live snapshots only (Valve's 'invitation' copies
    repeat them)."""
    snaps, stand = {}, {}
    for ydir in sorted((VRS / "live").iterdir()):
        det = ydir / "details"
        if not det.is_dir():
            continue
        for sdir in sorted(det.iterdir()):
            d = sdir.name.replace("_", "-")
            byid, region = defaultdict(list), {}
            for f in sdir.iterdir():
                txt = f.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"Team Name:\s*(.+?)<br", txt)
                if not m:
                    continue
                team = html.unescape(m.group(1).strip())
                rg = re.search(r"Region:\s*\[([^\]]+)\]", txt)
                region[team] = rg.group(1).strip() if rg else None
                for line in txt.splitlines():
                    r = ROW.match(line)
                    if r:
                        _, mid, date, opp, wl, _, roster = r.groups()
                        byid[mid].append((team, html.unescape(opp), wl, date,
                                          [p.strip() for p in roster.split(",")]))
            snaps[d] = byid
            g = ydir / f"standings_global_{sdir.name}.md"
            rows = []
            if g.exists():
                for line in g.read_text(encoding="utf-8").splitlines():
                    c = [x.strip() for x in line.strip().strip("|").split("|")]
                    if len(c) >= 4 and c[0].isdigit():
                        n = html.unescape(c[2])
                        rows.append([int(c[0]), n, float(c[1]), [p.strip() for p in c[3].split(",")], region.get(n)])
            stand[d] = rows
    return snaps, stand


def vrs_series(snaps):
    """Union of every snapshot's series. Inside a snapshot the match id joins the two rosters' rows; across snapshots
    a series is (date, the two names, winner) and appears as many times as the snapshot that lists it most."""
    best = {}
    for d, byid in snaps.items():
        cnt = defaultdict(list)
        for mid, rows in byid.items():
            a = rows[0]
            team, opp, wl, date, roster = a
            oroster = None
            for b in rows[1:]:
                if b[0] == opp:
                    oroster = b[4]
            win = team if wl == "W" else opp
            k = (date,) + tuple(sorted((team, opp))) + (win,)
            ra = {team: roster, opp: oroster}
            cnt[k].append((int(mid), ra))
        for k, lst in cnt.items():
            prev = best.get(k)
            # more copies wins; same count -> keep the later snapshot (rosters filled more often)
            if prev is None or len(lst) >= len(prev):
                lst.sort(key=lambda x: -x[0])
                if prev is not None and len(lst) == len(prev):
                    for i, (_, ra) in enumerate(lst):  # fill a missing roster from the earlier copy
                        for t in ra:
                            if ra[t] is None and prev[i][1].get(t):
                                ra[t] = prev[i][1][t]
                best[k] = lst
    out = []
    for (date, a, b, win), lst in best.items():
        for mid, ra in lst:
            out.append([date, a, b, 0 if win == a else 1, ra.get(a), ra.get(b), "vrs", None, -mid])
    out.sort(key=lambda r: (r[0], r[8]))  # inside a day: Valve's ids (higher = earlier, only ordered within a
    return [r[:8] for r in out]            # snapshot, so approximate across copies)


def lp_fetch():
    req = urllib.request.Request(LP_API, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)["parse"]["text"]["*"]


def lp_parse(t):
    """Liquipedia:Matches -> [{ts, a, b, sa, sb, fmt, event, done, logoA, logoB}]"""
    out = []
    for blk in t.split('<div class="match-info">')[1:]:
        ts = re.search(r'data-timestamp="(\d+)"', blk)
        if not ts:
            continue
        done = 'data-finished="finished"' in blk[:600]
        names = re.findall(r'<span class="name"[^>]*>(?:<a [^>]*title="([^"]*)"[^>]*>)?([^<]*)', blk)
        if len(names) < 2:
            continue
        logos = []
        for side in re.split(r'match-info-header-scoreholder"', blk, maxsplit=1):
            m = re.search(r'team-template-image-icon(?: team-template-darkmode)?"><a [^>]*><img alt="[^"]*" src="([^"]+)"',
                          side.replace("team-template-lightmode", "x"))
            logos.append(m.group(1) if m else None)
        sc = re.findall(r'match-info-header-scoreholder-score(?: match-info-header-winner)?">([^<]*)<', blk)
        fmt = re.search(r'scoreholder-lower">\((Bo\d)\)', blk)
        ev = re.search(r'match-info-tournament-name"><a [^>]*title="([^"]*)"[^>]*>(?:<span>)?([^<]*)', blk)
        # the link title is the team's page ("BetBoom Team"); the text is a ticker abbreviation ("BB")
        a, b = (html.unescape(n[0].strip() or n[1].strip()) for n in names[:2])
        if not a or not b or a.upper() == "TBD" or b.upper() == "TBD":
            continue
        sa = sb = None
        if len(sc) >= 2 and sc[0].strip().isdigit() and sc[1].strip().isdigit():
            sa, sb = int(sc[0]), int(sc[1])
        out.append({"ts": int(ts.group(1)), "a": a, "b": b, "sa": sa, "sb": sb, "fmt": fmt.group(1) if fmt else None,
                    "event": html.unescape(ev.group(2).strip() or ev.group(1)) if ev else "", "done": done,
                    "logoA": logos[0] if logos else None, "logoB": logos[1] if len(logos) > 1 else None})
    return out


def load_gz(p, default):
    try:
        with gzip.open(p, "rt") as f:
            return json.load(f)
    except (FileNotFoundError, OSError, ValueError):
        return default


def main():
    sync_vrs()
    snaps, stand = parse_snapshots()
    series = vrs_series(snaps)
    last_vrs = max(r[0] for r in series)
    lp = load_gz(LP_RES, {"results": {}, "logos": {}})
    upcoming = []
    try:
        ticker = lp_parse(lp_fetch())
    except Exception as e:  # the ticker is a bonus; the ratings still build from Valve's snapshots
        print("liquipedia ticker failed:", e, file=sys.stderr)
        ticker = None
    now = time.time()
    if ticker is None:  # keep the last run's schedule for the matches still ahead
        upcoming = [m for m in load_gz(OUT, {}).get("upcoming", []) if m["ts"] > now - 3 * 3600]
        ticker = []
    for m in ticker:
        for side, logo in (("a", m["logoA"]), ("b", m["logoB"])):
            if logo:
                lp["logos"][key(m[side])] = "https://liquipedia.net" + logo if logo.startswith("/") else logo
        if m["done"] and m["sa"] is not None and m["sa"] != m["sb"]:
            k = f'{m["ts"]}|{key(m["a"])}|{key(m["b"])}'
            lp["results"][k] = [m["ts"], m["a"], m["b"], m["sa"], m["sb"], m["fmt"], m["event"]]
        elif not m["done"] and m["ts"] > now - 6 * 3600:
            upcoming.append({k: m[k] for k in ("ts", "a", "b", "sa", "sb", "fmt", "event")})
    # Liquipedia results after Valve's last listed day join the series (names mapped onto Valve's by key)
    for ts, a, b, sa, sb, fmt, ev in sorted(lp["results"].values()):
        d = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if d > last_vrs:
            series.append([d, a, b, 0 if sa > sb else 1, None, None, "lp", fmt, ts, sa, sb, ev])
    series.sort(key=lambda r: r[0])
    LP_RES.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(LP_RES, "wt") as f:
        json.dump(lp, f, separators=(",", ":"), sort_keys=True)
    with gzip.open(OUT, "wt") as f:
        json.dump({"series": series, "vrs": stand, "upcoming": upcoming, "logos": lp["logos"], "lastVrs": last_vrs},
                  f, separators=(",", ":"))
    print(f"{len(series)} series ({sum(r[6] == 'lp' for r in series)} from Liquipedia), {len(stand)} VRS snapshots, "
          f"last VRS series {last_vrs}, {len(upcoming)} upcoming")


if __name__ == "__main__":
    main()
