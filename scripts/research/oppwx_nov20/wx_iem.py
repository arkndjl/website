# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Hourly airport weather (METAR) from the Iowa Environmental Mesonet's ASOS archive, research only (Nov 20 2026).

IEM (mesonet.agron.iastate.edu, Iowa State University) mirrors the world's airport observations; its robots.txt leaves
the request scripts open and it documents scripted downloads. One call per station per season (Jul 1 - Jun 30), one at
a time with a pause. Open-Meteo's archive (the CFB / NFL weather source) now disallows robots, so it is not used here.

    import wx_iem as WX
    st = WX.stations(['GB__ASOS', ...])            # [(id, lat, lon, begin)]
    WX.nearest(st, lat, lon)                        # station id
    WX.hours(station, season, cache_dir)            # {'YYYY-MM-DD HH': (temp F, wind mph, gust mph, wet, snow)}
"""
import csv, io, json, math, os, time, urllib.request
UA = {'User-Agent': 'arkndjl.net research (github.com/arkndjl/website)'}
BASE = 'https://mesonet.agron.iastate.edu'


def get(url, tries=4):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read().decode('utf-8', 'replace')
        except Exception as e:
            time.sleep(5 * (i + 1))
    return None


def stations(networks, cache):
    out = []
    for n in networks:
        fn = os.path.join(cache, f'net_{n}.json')
        if not os.path.exists(fn):
            t = get(f'{BASE}/geojson/network/{n}.geojson')
            if not t: continue
            open(fn, 'w').write(t); time.sleep(1)
        for f in json.load(open(fn))['features']:
            p = f['properties']
            if p.get('archive_begin') and not p.get('archive_end'):
                out.append((f['id'], f['geometry']['coordinates'][1], f['geometry']['coordinates'][0], p['archive_begin']))
    return out


def km(a, b, c, d):
    p = math.pi / 180
    x = math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))


def nearest(st, lat, lon, before='2012-07-01', n=3):
    c = sorted((km(lat, lon, s[1], s[2]), s[0]) for s in st if s[3] <= before)
    return c[:n]


WET = ('RA', 'DZ', 'SN', 'SG', 'PL', 'GR', 'GS', 'TS', 'SH', 'UP')


def hours(station, season, cache):
    """season = end year (Jul 1 of the year before to Jun 30). None when the pull fails."""
    fn = os.path.join(cache, f'{station}_{season}.csv')
    if not os.path.exists(fn):
        url = (f'{BASE}/cgi-bin/request/asos.py?station={station}&data=tmpf&data=sknt&data=gust&data=p01i&data=wxcodes'
               f'&year1={season - 1}&month1=7&day1=1&year2={season}&month2=7&day2=1&tz=Etc/UTC&format=onlycomma&latlon=no'
               f'&missing=M&trace=T&report_type=3&report_type=4')
        t = get(url)
        if t is None or not t.startswith('station'):
            return None
        open(fn, 'w').write(t); time.sleep(1.0)
    out = {}
    for r in csv.DictReader(open(fn)):
        k = r['valid'][:13]
        def f(x):
            try: return float(x)
            except ValueError: return None
        w = r.get('wxcodes') or ''
        p = f(r['p01i'])
        wet = any(c in w for c in WET) or (p is not None and p > 0.005)
        snow = 'SN' in w or 'SG' in w
        o = out.get(k)
        tm, wd, gu = f(r['tmpf']), f(r['sknt']), f(r['gust'])
        if o is None:
            out[k] = [tm, wd * 1.1508 if wd is not None else None, gu * 1.1508 if gu is not None else None, wet, snow]
        else:                                               # several reports in the hour: max wind / gust, any wet
            if tm is not None and o[0] is None: o[0] = tm
            if wd is not None: o[1] = max(o[1] or 0, wd * 1.1508)
            if gu is not None: o[2] = max(o[2] or 0, gu * 1.1508)
            o[3] = o[3] or wet; o[4] = o[4] or snow
    return out


def window(station, d0, d1, cache):
    """hourly rows between two dates (datetime.date, d1 exclusive), cached per call. {} when the station has none."""
    fn = os.path.join(cache, f'{station}_{d0:%Y%m%d}_{d1:%Y%m%d}.csv')
    if not os.path.exists(fn):
        url = (f'{BASE}/cgi-bin/request/asos.py?station={station}&data=tmpf&data=sknt&data=gust&data=p01i&data=wxcodes'
               f'&year1={d0.year}&month1={d0.month}&day1={d0.day}&year2={d1.year}&month2={d1.month}&day2={d1.day}&tz=Etc/UTC'
               f'&format=onlycomma&latlon=no&missing=M&trace=T&report_type=3&report_type=4')
        t = get(url)
        if t is None or not t.startswith('station'):
            return None
        open(fn, 'w').write(t); time.sleep(0.7)
    out = {}
    for r in csv.DictReader(open(fn)):
        def f(x):
            try: return float(x)
            except ValueError: return None
        w = r.get('wxcodes') or ''
        p = f(r['p01i'])
        out.setdefault(r['valid'][:13], []).append((f(r['tmpf']), f(r['sknt']), f(r['gust']),
                                                    any(c in w for c in WET) or (p is not None and p > 0.005)))
    return out
