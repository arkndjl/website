# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""Daytime weather for outdoor tour-level tennis events 2012-26 (research, Nov 20 2026): the nearest airport's hourly
reports (wx_iem.py) over each event's days, 11:00-19:00 local.
    python3 scripts/research/oppwx_nov20/tennis_wx_pull.py MATCHES_CSV_GZ CACHE_DIR OUT_JSON
OUT: {tid: {day offset: [temp F, wind mph, gust mph, wet share, hours]}}
"""
import csv, datetime as dt, gzip, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wx_iem as WX
# event name -> (airport, hours from UTC in the event's month); outdoor events only. (name, tour) keys win over names.
EV = {'Australian Open': ('YMML', 11), 'Roland Garros': ('LFPO', 2), 'Wimbledon': ('EGLL', 1), 'US Open': ('KLGA', -4), 'Us Open': ('KLGA', -4),
      'Indian Wells Masters': ('KPSP', -7), 'Indian Wells': ('KPSP', -7), 'Miami Masters': ('KMIA', -4), 'Miami': ('KMIA', -4),
      'Rome Masters': ('LIRA', 2), 'Rome': ('LIRA', 2), 'Dubai': ('OMDB', 4), 'Beijing': ('ZBAA', 8), 'Madrid Masters': ('LEMD', 2),
      'Madrid': ('LEMD', 2), 'Doha': ('OTBD', 3), 'Washington': ('KDCA', -4), 'Cincinnati': ('KCVG', -4), 'Cincinnati Masters': ('KCVG', -4),
      'Monte Carlo Masters': ('LFMN', 2), 'Shanghai Masters': ('ZSSS', 8), 'Eastbourne': ('EGKK', 1), 'Winston-Salem': ('KINT', -4),
      ('Stuttgart', 'atp'): ('EDDS', 2), 'Barcelona': ('LEBL', 2), 'Hamburg': ('EDDH', 2), 'Acapulco': ('MMAA', -6), 'Auckland': ('NZAA', 13),
      'Brisbane': ('YBBN', 10), ('Tokyo', 'atp'): ('RJTT', 9), 'Charleston': ('KCHS', -4), "Queen's Club": ('EGLL', 1), 'Gstaad': ('LSGS', 2),
      'Nottingham': ('EGNX', 1), 'Bastad': ('ESTA', 2), 's Hertogenbosch': ('EHEH', 2), "'s Hertogenbosch": ('EHEH', 2), 'Hertogenbosch': ('EHEH', 2),
      's-Hertogenbosch': ('EHEH', 2), 'S-Hertogenbosch': ('EHEH', 2), 'Montreal': ('CYUL', -4), 'Toronto': ('CYYZ', -4), 'Toronto ': ('CYYZ', -4),
      'Delray Beach': ('KPBI', -5), 'Halle': ('EDLP', 2), 'Bogota': ('SKBO', -5), 'Wuhan': ('ZHHH', 8), 'Buenos Aires': ('SABE', -3),
      'Kitzbuhel': ('LOWI', 2), 'Munich': ('EDDM', 2), 'Umag': ('LDPL', 2), 'Sydney': ('YSSY', 11), 'Bucharest': ('LROP', 3),
      'Monterrey': ('MMMY', -6), 'Strasbourg': ('LFST', 2), 'Estoril': ('LPPT', 1), 'Houston': ('KHOU', -5), 'Prague': ('LKPR', 2),
      ('Lyon', 'atp'): ('LFLL', 2), 'Newport': ('KPVD', -4), 'Rio de Janeiro': ('SBRJ', -3), 'Rio De Janeiro': ('SBRJ', -3), 'Atlanta': ('KATL', -4),
      'Birmingham': ('EGBB', 1), 'Seoul': ('RKSS', 9), 'Geneva': ('LSGG', 2), 'Shenzhen': ('ZGSZ', 8), 'Marrakech': ('GMMX', 1), 'Rabat': ('GMME', 1),
      'Hobart': ('YMHB', 11), 'Los Cabos': ('MMSD', -6), 'Hong Kong': ('VHHH', 8), 'Mallorca': ('LEPA', 2), 'Adelaide': ('YPAD', 10.5),
      'Adelaide 1': ('YPAD', 10.5), 'Adelaide 2': ('YPAD', 10.5), 'Santiago': ('SCEL', -3), 'Chennai': ('VOMM', 5.5), 'Guangzhou': ('ZGGG', 8),
      'Chengdu': ('ZUUU', 8), 'Guadalajara': ('MMGL', -6), 'Palermo': ('LICJ', 2), 'Bad Homburg': ('EDDF', 2), 'Abu Dhabi': ('OMAA', 4),
      'Berlin': ('EDDB', 2), 'Cordoba': ('SACO', -3), 'Nanchang': ('ZSCN', 8), 'Osaka': ('RJOO', 9), 'Zhuhai': ('ZGSD', 8), 'Nice': ('LFMN', 2),
      'San Diego': ('KSAN', -7), 'Pune': ('VAPO', 5.5), 'Nurnberg': ('EDDN', 2), 'Nuremberg': ('EDDN', 2), 'Tashkent': ('UTTT', 5), 'Hua Hin': ('VTPH', 7),
      'Austin': ('KAUS', -6), 'Tianjin': ('ZBTJ', 8), 'Lausanne': ('LSGG', 2), 'New Haven': ('KHVN', -4), 'Merida': ('MMMD', -6), 'Ningbo': ('ZSNB', 8),
      'Antalya': ('LTAI', 3), 'Casablanca': ('GMMN', 1), 'Quito': ('SEQM', -5), 'Stanford': ('KSJC', -7), 'San Jose': ('KSJC', -7), 'Cleveland': ('KCLE', -4),
      'Paris Olympics': ('LFPO', 2), 'Belgrade': ('LYBE', 2), 'Melbourne': ('YMML', 11), 'Melbourne 1': ('YMML', 11), 'Melbourne 2': ('YMML', 11)}
CANADA_TORONTO = {2012, 2014, 2016, 2018, 2021, 2023, 2025}
LV = {'G', 'M', 'A', 'F', 'O'}


def place(name, tour, year):
    if name == 'Canada Masters':
        return ('CYYZ', -4) if year in CANADA_TORONTO else ('CYUL', -4)
    return EV.get((name, tour)) or EV.get(name)


if __name__ == '__main__':
    cache = sys.argv[2]; os.makedirs(cache, exist_ok=True)
    ev = {}
    for r in csv.DictReader(gzip.open(sys.argv[1], 'rt')):
        if r['d'] < '20120101' or r['lv'] not in LV or not r['w_svpt']: continue
        p = place(r['tname'], r['tour'], int(r['d'][:4]))
        if p: ev[r['tid']] = (r['d'], p)
    print(len(ev), 'events', flush=True)
    out = {}
    for i, (tid, (d, (st, off))) in enumerate(sorted(ev.items(), key=lambda kv: kv[1])):
        d0 = dt.datetime.strptime(d, '%Y%m%d').date()
        H = WX.window(st, d0 - dt.timedelta(days=2), d0 + dt.timedelta(days=17), cache)
        if not H: continue
        days = {}
        for j in range(-1, 16):
            day = d0 + dt.timedelta(days=j)
            obs = []
            for hl in range(11, 19):
                u = dt.datetime(day.year, day.month, day.day) + dt.timedelta(hours=hl - off)
                obs += H.get(u.strftime('%Y-%m-%d %H'), [])
            tv = [o[0] for o in obs if o[0] is not None]; wv = [o[1] for o in obs if o[1] is not None]
            if len(tv) < 4 or len(wv) < 4: continue
            gv = [o[2] for o in obs if o[2] is not None]
            days[j] = [round(sum(tv) / len(tv), 1), round(sum(wv) / len(wv) * 1.1508, 1), round(max(gv) * 1.1508, 1) if gv else None,
                       round(sum(1 for o in obs if o[3]) / len(obs), 2), len(obs)]
        if days: out[tid] = days
        if i % 100 == 0:
            print(i, len(out), flush=True); json.dump(out, open(sys.argv[3], 'w'))
    json.dump(out, open(sys.argv[3], 'w'))
    print('done', len(out), 'of', len(ev))
