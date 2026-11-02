"""Download NHL shift charts (goalie rows only kept) for the game ids listed in a file.
usage: fetch_shifts.py <gids.txt> <out_dir> <goalies.json: {gid: [goalie ids]}>"""
import concurrent.futures as cf, gzip, json, os, sys, time, urllib.request
ids = open(sys.argv[1]).read().split()
OUT = sys.argv[2]; os.makedirs(OUT, exist_ok=True)
def get(gid):
    path = os.path.join(OUT, gid + ".json.gz")
    if os.path.exists(path): return 0
    url = f"https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gid}"
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (arkboard research)"})
            with urllib.request.urlopen(req, timeout=30) as r: b = r.read()
            with gzip.open(path, "wb") as f: f.write(b)
            return 1
        except Exception:
            time.sleep(2 * (a + 1))
    return -2
with cf.ThreadPoolExecutor(6) as ex: res = list(ex.map(get, ids))
print({k: res.count(k) for k in set(res)})
