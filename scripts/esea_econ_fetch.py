#!/usr/bin/env python3
"""Round economy for the 1NT economy gameplan (scripts/esea_econ.py): FACEIT match demos of ESEA NA
league maps, parsed with demoparser2 into per-round team money, equipment value and winner. Written to
research/esea_econ.json.gz (resumes: maps already there are skipped). Needs FACEIT_API_KEY;
.github/workflows/esea-econ.yml runs it.

  FACEIT_API_KEY=... ECON_MINUTES=300 python3 scripts/esea_econ_fetch.py

Order: 1NT's matches, then its S59 opponents' matches, then the rest of the league, newest first.
Demo URLs come from the Data API match details (demo_url). FACEIT's CDN may want a signed link; the
Downloads API (POST /download/v2/demos/download) is tried when the plain link is refused.
"""
import bz2, gzip, json, os, sys, tempfile, time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'research' / 'esea_matches.json.gz'
OUT = ROOT / 'research' / 'esea_econ.json.gz'
KEY = os.environ.get('FACEIT_API_KEY')
API = 'https://open.faceit.com/data/v4'
DL = 'https://open.faceit.com/download/v2/demos/download'
BUDGET = float(os.environ.get('ECON_MINUTES', 300)) * 60
MAXM = int(os.environ.get('ECON_MAX', 100000))
TEAM = os.environ.get('ECON_TEAM', '1NT')
T0 = time.time()
if not KEY:
    print('FACEIT_API_KEY not set'); sys.exit(0)
S = requests.Session()
S.headers.update({'Authorization': f'Bearer {KEY}', 'Accept': 'application/json'})
calls = 0


def api(p):
    global calls
    for a in range(5):
        calls += 1
        try:
            r = S.get(API + p, timeout=30)
        except requests.RequestException:
            time.sleep(2 * (a + 1)); continue
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 * (a + 1)); continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    return None


log = {'matches': 0, 'with_demo_url': 0, 'direct': {}, 'signed': {}, 'parsed': 0, 'parse_fail': 0, 'unmapped': 0, 'samples': []}


def note(kind, code, extra=''):
    log[kind][str(code)] = log[kind].get(str(code), 0) + 1
    if len(log['samples']) < 12:
        log['samples'].append(f'{kind} {code} {extra}'[:300])
        print(log['samples'][-1], flush=True)


def fetch(url, path):
    """Download url to path; True on success. Tries the plain link, then a Downloads API signed link."""
    for kind in ('direct', 'signed'):
        u = url
        if kind == 'signed':
            try:
                r = S.post(DL, json={'resource_url': url}, timeout=30)
            except requests.RequestException as e:
                note(kind, 'err', str(e)); return False
            if not r.ok:
                note(kind, r.status_code, r.text[:200]); return False
            j = r.json()
            u = (j.get('payload') or {}).get('download_url') or j.get('download_url')
            if not u:
                note(kind, 'nourl', json.dumps(j)[:200]); return False
        try:
            with requests.get(u, stream=True, timeout=120, headers={'User-Agent': 'Mozilla/5.0'}) as r:
                if not r.ok:
                    note(kind, r.status_code, u.split('?')[0][-80:]); continue
                with open(path, 'wb') as f:
                    for ch in r.iter_content(1 << 20):
                        f.write(ch)
            note(kind, 200)
            return True
        except requests.RequestException as e:
            note(kind, 'err', str(e)[:150])
    return False


def unpack(path):
    with open(path, 'rb') as f:
        head = f.read(4)
    out = path + '.dem'
    if head[:2] == b'\x1f\x8b':
        op = gzip.open
    elif head == b'\x28\xb5\x2f\xfd':
        import zstandard
        with open(path, 'rb') as fi, open(out, 'wb') as fo:
            zstandard.ZstdDecompressor().copy_stream(fi, fo)
        return out
    elif head[:3] == b'BZh':
        op = bz2.open
    else:
        return path
    with op(path, 'rb') as fi, open(out, 'wb') as fo:
        while ch := fi.read(1 << 20):
            fo.write(ch)
    return out


steam_cache = {}


def steam(pid):
    if pid not in steam_cache:
        j = api(f'/players/{pid}') or {}
        steam_cache[pid] = str(((j.get('games') or {}).get('cs2') or {}).get('game_player_id') or j.get('steam_id_64') or '')
    return steam_cache[pid]


def parse(dem, m, shown=[False]):
    """Per round: [round, f1 side (2 T / 3 CT), f1 bank, f2 bank, f1 kept equip, f2 kept equip,
    f1 equip, f2 equip, winner (1/2), reason]. Bank and kept equip at round start (before buying),
    equip 5 s after freeze end (after buying)."""
    from demoparser2 import DemoParser
    p = DemoParser(dem)
    hdr = p.parse_header()
    starts = p.parse_event('round_start')
    fe = p.parse_event('round_freeze_end')
    ends = p.parse_event('round_end')
    tk = sorted(set(starts.tick) | set(fe.tick) | set(fe.tick + 320))
    df = p.parse_ticks(['team_num', 'current_equip_value', 'balance', 'total_rounds_played', 'is_warmup_period', 'team_clan_name'], ticks=tk)
    if not shown[0]:
        shown[0] = True
        print('demo columns:', list(df.columns), '| round_end:', list(ends.columns), ends.head(3).to_dict('records'), flush=True)
    # which faction is each steam id
    side_of = {}
    for f, k in (('f1', 1), ('f2', 2)):
        for pid, _ in m[f]['roster']:
            s = steam(pid)
            if s:
                side_of[s] = k
    df['steamid'] = df['steamid'].astype(str)
    df['fac'] = df['steamid'].map(side_of)
    if df['fac'].notna().mean() < 0.6:
        # fall back to clan names (FACEIT sets them to the team names)
        nm = {m['f1']['name'].lower(): 1, m['f2']['name'].lower(): 2}
        df['fac'] = df['fac'].fillna(df['team_clan_name'].astype(str).str.lower().map(nm))
    if df['fac'].notna().mean() < 0.6:
        log['unmapped'] += 1
        return None, hdr.get('map_name')
    by_tick = {t: g for t, g in df.groupby('tick')}
    st = sorted(starts.tick)
    en = ends.sort_values('tick')
    rows = {}
    for t in sorted(fe.tick):
        g = by_tick.get(t)
        if g is None or bool(g['is_warmup_period'].any()):
            continue
        rn = int(g['total_rounds_played'].max()) + 1
        s0 = max([x for x in st if x <= t], default=None)
        g0 = by_tick.get(s0, g)
        g1 = by_tick.get(t + 320, g)
        nxt = en[en.tick > t]
        if nxt.empty:
            continue
        e = nxt.iloc[0]
        w = e.get('winner')
        w = {'T': 2, 'CT': 3, 't': 2, 'ct': 3}.get(w, w)
        try:
            w = int(w)
        except (TypeError, ValueError):
            continue
        f1 = g[g.fac == 1]
        if f1.empty or w not in (2, 3):
            continue
        side1 = int(f1['team_num'].mode().iloc[0])
        fac_of_side = {side1: 1, 5 - side1: 2}

        def team(gg, k, col):
            x = gg[gg.fac == k]
            return int(x[col].sum())
        eq = {}
        for k in (1, 2):
            a = g[g.fac == k].set_index('steamid')['current_equip_value']
            b = g1[g1.fac == k].set_index('steamid')['current_equip_value']
            eq[k] = int(a.combine(b, max, fill_value=0).sum())
        rows[rn] = [rn, side1, team(g0, 1, 'balance'), team(g0, 2, 'balance'), team(g0, 1, 'current_equip_value'), team(g0, 2, 'current_equip_value'),
                    eq[1], eq[2], fac_of_side[w], str(e.get('reason', ''))]
    return [rows[k] for k in sorted(rows)], hdr.get('map_name')


def diag(url):
    """One-off look at why a demo link fails: DNS, the plain GET, and the Downloads API variants."""
    import socket
    from urllib.parse import urlparse
    h = urlparse(url).hostname
    print('demo url:', url.split('?')[0], flush=True)
    try:
        print('dns', h, socket.gethostbyname_ex(h), flush=True)
    except Exception as e:
        print('dns', h, repr(e), flush=True)
    try:
        r = requests.get(url, stream=True, timeout=30)
        print('plain', r.status_code, dict(r.headers), flush=True)
    except Exception as e:
        print('plain', repr(e)[:600], flush=True)
    for v in ('v2', 'v1'):
        for body in ({'resource_url': url}, {'resource_url': url.split('?')[0]}):
            try:
                r = S.post(f'https://open.faceit.com/download/{v}/demos/download', json=body, timeout=30)
                print('downloads api', v, r.status_code, {k: r.headers[k] for k in r.headers if k.lower().startswith(('x-', 'content-type', 'www'))}, r.text[:300], flush=True)
            except Exception as e:
                print('downloads api', v, repr(e)[:300], flush=True)


def main():
    src = json.load(gzip.open(SRC))
    done = {}
    if OUT.exists():
        try:
            done = {(x['id'], x['n']): x for x in json.load(gzip.open(OUT))['maps']}
        except Exception:
            done = {}
    ms = [m for m in src['matches'] if m.get('maps')]
    ms.sort(key=lambda m: -(m.get('at') or 0))
    ours = [m for m in ms if TEAM in (m['f1']['name'], m['f2']['name'])]
    opp = {m[f]['id'] for m in ours if m.get('season') == max(x.get('season') or 0 for x in ms) for f in ('f1', 'f2')}
    ordered, seen = [], set()
    for grp in (ours, [m for m in ms if m['f1']['id'] in opp or m['f2']['id'] in opp], ms):
        for m in grp:
            if m['id'] not in seen:
                seen.add(m['id']); ordered.append(m)
    maps = list(done.values())
    tmp = tempfile.mkdtemp()
    for m in ordered[:MAXM]:
        if time.time() - T0 > BUDGET:
            print('time budget reached'); break
        if all((m['id'], i) in done for i in range(len(m['maps']))):
            continue
        log['matches'] += 1
        det = api(f"/matches/{m['id']}") or {}
        urls = det.get('demo_url') or []
        if urls:
            log['with_demo_url'] += 1
            if log['with_demo_url'] <= 2 and os.environ.get('ECON_DIAG'):
                diag(urls[0])
        elif log['matches'] <= 3:
            print('no demo_url:', m['id'], sorted(det.keys()), flush=True)
        for i, u in enumerate(urls[:len(m['maps'])]):
            if (m['id'], i) in done:
                continue
            raw = os.path.join(tmp, 'd')
            if not fetch(u, raw):
                continue
            dem = None
            try:
                dem = unpack(raw)
                rounds, mapname = parse(dem, m)
                if rounds:
                    maps.append({'id': m['id'], 'n': i, 'season': m.get('season'), 'div': m.get('div'), 'at': m.get('at'),
                                 'map': str(mapname or m['maps'][i]['map']).replace('de_', ''), 'f1': m['f1']['id'], 'f2': m['f2']['id'],
                                 'n1': m['f1']['name'], 'n2': m['f2']['name'], 'rounds': rounds})
                    log['parsed'] += 1
                    if log['parsed'] % 10 == 1:
                        print(f"parsed {log['parsed']}: {m['f1']['name']} v {m['f2']['name']} {mapname} {len(rounds)} rounds ({(time.time() - T0) / 60:.0f} min)", flush=True)
            except Exception as e:
                log['parse_fail'] += 1
                print('parse failed', m['id'], repr(e)[:200], flush=True)
            for f in (raw, dem):
                if f and os.path.exists(f):
                    os.remove(f)
        if log['matches'] >= 25 and not log['parsed'] and not maps:
            print('no demos parsed after 25 matches; stopping'); break
    OUT.parent.mkdir(exist_ok=True)
    with gzip.open(OUT, 'wt') as f:
        json.dump({'asof': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'probe': log, 'maps': maps}, f)
    print(json.dumps(log, indent=1))
    print(f'wrote {OUT.relative_to(ROOT)}: {len(maps)} maps, {calls} API calls')


main()
