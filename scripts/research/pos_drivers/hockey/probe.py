# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""probe HockeyTech feeds for goalie season stats and team standings"""
import json
import urllib.request
UA = 'Mozilla/5.0'


def get(u):
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': UA}), timeout=60).read())
    except Exception as e:
        return str(e)


MK = 'https://lscluster.hockeytech.com/feed/?feed=modulekit&fmt=json&lang=en&key=f1aa699db3d81487&client_code=ohl'
ss = get(MK + '&view=seasons')['SiteKit']['Seasons']
sid = [s['season_id'] for s in ss if s['season_name'].startswith('2012-13 Regular')][0]
for q in ['&view=statviewtype&type=topgoalies&season_id=%s&first=0&limit=5&qualified=all&order_direction=',
          '&view=statviewtype&type=standings&stat=conference&season_id=%s',
          '&view=teamsbyseason&season_id=%s']:
    d = get(MK + q % sid)
    print(q, json.dumps(d)[:1500])
    print()
