#!/usr/bin/env python3
"""Parse CS2 demos dropped in the project's demo folder into round economy for scripts/esea_econ.py.

Noah downloads demos from FACEIT match rooms and uploads them; this picks up every demo it has not seen
(by content hash) in the folders given (default: /mnt/project-files/esea/demos/ and the project upload
folder, where uploads land without a name or extension) and appends them to research/esea_econ.json.gz.
Accepts .dem, .dem.zst, .dem.gz, .dem.bz2 and .zip; files that are not demos are skipped.

Per round, per team: money at round start, kept equipment, equipment after buying (5 s after freeze
end), side, winner. Teams are named from the demo's team names; a side with three or more 1NT members
(data/esea.json) is 1NT. 1NT maps are matched to the FACEIT match by map and score (data/esea.json) for
the date and the opponent's FACEIT name.

  python3 scripts/esea_econ_parse.py [folder ...]
"""
import bz2, gzip, hashlib, io, json, os, sys, tempfile, zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'research' / 'esea_econ.json.gz'
DIRS = sys.argv[1:] or ['/mnt/project-files/esea/demos/', '/mnt/project-files/uploads/hearth/']
TEAM = '1NT'
MAGIC = {b'PBDEMS2\x00': 'dem', b'\x28\xb5\x2f\xfd': 'zst', b'\x1f\x8b': 'gz', b'BZh': 'bz2', b'PK\x03\x04': 'zip'}


def kind(path):
    with open(path, 'rb') as f:
        head = f.read(8)
    return next((k for m, k in MAGIC.items() if head.startswith(m)), None)


def digest(path):
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        h.update(f.read(1 << 22))
    h.update(str(os.path.getsize(path)).encode())
    return h.hexdigest()[:16]


def unpack(path, tmp):
    """A plain .dem path for any accepted container, or None."""
    k = kind(path)
    if k == 'dem':
        return path
    out = os.path.join(tmp, 'x.dem')
    if k == 'zst':
        import zstandard
        with open(path, 'rb') as fi, open(out, 'wb') as fo:
            zstandard.ZstdDecompressor().copy_stream(fi, fo)
    elif k in ('gz', 'bz2'):
        with (gzip.open if k == 'gz' else bz2.open)(path, 'rb') as fi, open(out, 'wb') as fo:
            while ch := fi.read(1 << 20):
                fo.write(ch)
    elif k == 'zip':
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if '.dem' in n.lower()]
            if not names:
                return None
            with z.open(names[0]) as fi, open(out + '.in', 'wb') as fo:
                while ch := fi.read(1 << 20):
                    fo.write(ch)
        return unpack(out + '.in', tmp)
    else:
        return None
    return out if kind(out) == 'dem' else unpack(out, tmp)


def parse_demo(dem):
    """{'map', 'teams': [name A, name B], 'players': {steamid: [name, 0 A / 1 B]}, 'rounds': [[round,
    A side (2 T / 3 CT), A bank, B bank, A kept, B kept, A equip, B equip, winner (1 A / 2 B), reason]]}.
    Team A = the team on CT in the first live round."""
    from demoparser2 import DemoParser
    p = DemoParser(dem)
    hdr = p.parse_header()
    starts, fe, ends = p.parse_event('round_start'), p.parse_event('round_freeze_end'), p.parse_event('round_end')
    tk = sorted(set(starts.tick) | set(fe.tick) | set(fe.tick + 320))
    props = ['team_num', 'current_equip_value', 'balance', 'total_rounds_played', 'is_warmup_period', 'team_clan_name']
    try:
        df = p.parse_ticks(props, ticks=tk)
    except Exception:
        df = p.parse_ticks(props[:-1], ticks=tk); df['team_clan_name'] = ''
    df = df[df.team_num.isin([2, 3])]
    df['steamid'] = df['steamid'].astype(str)
    by = {t: g.set_index('steamid') for t, g in df.groupby('tick')}
    st, en = sorted(starts.tick), ends.sort_values('tick')
    team, rows = None, {}
    for t in sorted(fe.tick):
        g = by.get(t)
        if g is None or bool(g['is_warmup_period'].any()):
            continue
        if team is None:
            team = {s: 0 if n == 3 else 1 for s, n in g['team_num'].items()}
        nxt = en[en.tick > t]
        if nxt.empty:
            continue
        e = nxt.iloc[0]
        w = {'T': 2, 'CT': 3}.get(str(e.get('winner')).upper(), e.get('winner'))
        try:
            w = int(w)
        except (TypeError, ValueError):
            continue
        rn = int(g['total_rounds_played'].max()) + 1
        g0 = by.get(max([x for x in st if x <= t], default=-1), g)
        g1 = by.get(t + 320, g)
        g = g.assign(k=g.index.map(team))
        a = g[g.k == 0]
        if a.empty or w not in (2, 3):
            continue
        side = int(a['team_num'].mode().iloc[0])

        def tot(gg, k, col):
            return int(gg[gg.index.map(team) == k][col].sum())

        def eq(k):
            x0 = g[g.k == k]['current_equip_value']
            x1 = g1[g1.index.map(team) == k]['current_equip_value']
            return int(x0.combine(x1, max, fill_value=0).sum())
        rows[rn] = [rn, side, tot(g0, 0, 'balance'), tot(g0, 1, 'balance'), tot(g0, 0, 'current_equip_value'), tot(g0, 1, 'current_equip_value'),
                    eq(0), eq(1), 1 if w == side else 2, str(e.get('reason', ''))]
    if team is None:
        return None
    names = {s: n for s, n in zip(df.steamid, df.name)}
    clan = []
    for k in (0, 1):
        c = Counter(n for s, n in zip(df.steamid, df.team_clan_name) if team.get(s) == k and n and str(n) != 'nan')
        clan.append(c.most_common(1)[0][0] if c else '')
    return {'map': str(hdr.get('map_name', '')).replace('de_', ''), 'teams': clan,
            'players': {s: [names.get(s, ''), k] for s, k in team.items()}, 'rounds': [rows[k] for k in sorted(rows)]}


def label(d, esea):
    """Name the sides (1NT by members) and match a 1NT map to its FACEIT match by map and score."""
    nicks = {m['nick'].lower() for m in esea.get('members', [])}
    ours = [sum(1 for n, k in d['players'].values() if k == side and n.lower() in nicks) for side in (0, 1)]
    us = 0 if ours[0] >= 3 else 1 if ours[1] >= 3 else None
    names = [d['teams'][0] or 'Team A', d['teams'][1] or 'Team B']
    rec = {'map': d['map'], 'n1': names[0], 'n2': names[1], 'f1': names[0], 'f2': names[1], 'at': None, 'id': None, 'n': 0}
    if us is not None:
        names[us] = TEAM
        rec['n1' if us == 0 else 'n2'] = rec['f1' if us == 0 else 'f2'] = TEAM
        r = d['rounds']
        sc = [sum(x[8] == 1 for x in r), sum(x[8] == 2 for x in r)]
        mine, theirs = sc[us], sc[1 - us]
        for m in esea.get('matches', []):
            for i, mp in enumerate(m.get('maps') or []):
                if str(mp.get('map', '')).replace('de_', '') == d['map'] and [mp.get('rf'), mp.get('ra')] == [mine, theirs]:
                    o = (m.get('opp') or {}).get('name')
                    if o:
                        rec['n2' if us == 0 else 'n1'] = rec['f2' if us == 0 else 'f1'] = o
                    rec.update(id=m['id'], n=i, at=(m.get('at') or 0) // 1000)
    return rec


def main():
    data = {'maps': []}
    if OUT.exists():
        data = json.load(gzip.open(OUT))
    seen = {m.get('hash') for m in data['maps']}
    try:
        esea = json.load(open(ROOT / 'data' / 'esea.json'))
    except Exception:
        esea = {}
    new = 0
    for folder in DIRS:
        if not os.path.isdir(folder):
            continue
        for f in sorted(Path(folder).iterdir()):
            if not f.is_file() or f.stat().st_size < 1 << 20 or not kind(f):
                continue
            h = digest(f)
            if h in seen:
                continue
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    dem = unpack(str(f), tmp)
                    d = parse_demo(dem) if dem else None
                except Exception as e:
                    print(f'{f.name}: parse failed: {e!r}'[:300]); continue
            if not d or len(d['rounds']) < 13:
                print(f'{f.name}: no usable rounds'); continue
            rec = label(d, esea)
            rec.update(hash=h, src=f.name, rounds=d['rounds'])
            data['maps'].append(rec); seen.add(h); new += 1
            print(f"{f.name}: {rec['n1']} v {rec['n2']} {rec['map']} {len(d['rounds'])} rounds{'' if rec['id'] else ' (no FACEIT match found)'}")
    if new:
        OUT.parent.mkdir(exist_ok=True)
        with gzip.open(OUT, 'wt') as fo:
            json.dump(data, fo)
    print(f"{new} new maps, {len(data['maps'])} total in {OUT.relative_to(ROOT)}")


if __name__ == '__main__':
    main()
