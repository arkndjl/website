# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Swedish federation skater tables (SHL, HockeyAllsvenskan), one page a league-season.

usage: swe_pull.py <out_dir>   seasons 2008-09 to 2023-24 (the prospect stage seasons of classes 2008-19)
"""
import html, json, os, re, sys, time, urllib.request

UA = "arkndjl.net-arkboard/1.0 (https://arkndjl.net)"
BASE = "https://stats.swehockey.se"
CUR = {"SHL": 18263, "HockeyAllsvenskan": 20962}


def get(url):
    time.sleep(1.5)
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=90)
    return r.read().decode("utf8", "replace")


def main(out):
    os.makedirs(out, exist_ok=True)
    ids = {}
    for lg, cid in CUR.items():
        t = get("%s/ScheduleAndResults/Overview/%d" % (BASE, cid))
        for u, lab in re.findall(r'<option[^>]*value="(/ScheduleAndResults/[A-Za-z]+/(?:\d+))"[^>]*>\s*(\d{4}-\d{2})\s*<', t):
            y = int(lab[:4]) + 1
            if 2009 <= y <= 2024:
                ids.setdefault(lg, {})[y] = int(u.rsplit("/", 1)[1])
    # the season menu points at the last stage played (playoffs, play-out); take the regular season from the stage menu
    REG = {"SHL": ("SHL", "Elitserien"), "HockeyAllsvenskan": ("HockeyAllsvenskan", "Allsvenskan")}
    reg = {}
    for lg, m in ids.items():
        for y, cid in sorted(m.items()):
            t = get("%s/ScheduleAndResults/Overview/%d" % (BASE, cid))
            opts = [(int(u), html.unescape(lab).strip()) for u, lab in
                    re.findall(r'<option[^>]*value="/ScheduleAndResults/[A-Za-z]+/(\d+)"[^>]*>([^<]*)<', t)]
            pick = [u for u, lab in opts if lab in REG[lg]]
            reg.setdefault(lg, {})[y] = pick[0] if pick else cid
    json.dump({"menu": ids, "regular": reg}, open(os.path.join(out, "ids.json"), "w"), indent=1)
    for lg, m in reg.items():
        for y, cid in sorted(m.items()):
            fn = os.path.join(out, "%s_%d.html" % (lg, y))
            if ids[lg][y] == cid and os.path.exists(fn) and os.path.getsize(fn) > 20000:
                continue
            try:
                open(fn, "w", encoding="utf8").write(get("%s/Players/Statistics/PlayersByTeam/%d" % (BASE, cid)))
            except Exception as e:
                print(lg, y, cid, "ERR", e, flush=True)
    print("done", reg, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
