"""Download NHL API play-by-play for regular seasons 2021-22..2024-25 (gzip) into the scratchpad."""
import concurrent.futures as cf, gzip, os, sys, time, urllib.request
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
ids = [f"{y}02{n:04d}" for y in (2021, 2022, 2023, 2024) for n in range(1, 1313)]
def get(gid):
    path = os.path.join(OUT, gid + ".json.gz")
    if os.path.exists(path): return 0
    for a in range(4):
        try:
            req = urllib.request.Request(f"https://api-web.nhle.com/v1/gamecenter/{gid}/play-by-play", headers={"User-Agent": "Mozilla/5.0 (arkboard research)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                b = r.read()
            with gzip.open(path, "wb") as f: f.write(b)
            return 1
        except Exception as e:
            if getattr(e, "code", None) == 404: return -1
            time.sleep(2 * (a + 1))
    return -2
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(get, ids))
print({k: res.count(k) for k in set(res)})
