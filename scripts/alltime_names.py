# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""NFL team-season display names for the all-time rankings (scripts/alltime.py): FiveThirtyEight / nflverse codes by era."""
# code: [(first season, name), ...] latest last
NFL = {
    'ARI': [(1920, 'Chicago Cardinals'), (1960, 'St. Louis Cardinals'), (1988, 'Phoenix Cardinals'), (1994, 'Arizona Cardinals')],
    'ATL': [(1966, 'Atlanta Falcons')], 'BAL': [(1996, 'Baltimore Ravens')], 'BUF': [(1960, 'Buffalo Bills')],
    'CAR': [(1995, 'Carolina Panthers')], 'CHI': [(1920, 'Decatur Staleys'), (1921, 'Chicago Staleys'), (1922, 'Chicago Bears')],
    'CIN': [(1968, 'Cincinnati Bengals')], 'CLE': [(1946, 'Cleveland Browns')], 'DAL': [(1960, 'Dallas Cowboys')],
    'DEN': [(1960, 'Denver Broncos')], 'DET': [(1930, 'Portsmouth Spartans'), (1934, 'Detroit Lions')], 'GB': [(1921, 'Green Bay Packers')],
    'HOU': [(2002, 'Houston Texans')], 'IND': [(1953, 'Baltimore Colts'), (1984, 'Indianapolis Colts')], 'JAX': [(1995, 'Jacksonville Jaguars')],
    'KC': [(1960, 'Dallas Texans'), (1963, 'Kansas City Chiefs')], 'LAC': [(1960, 'Los Angeles Chargers'), (1961, 'San Diego Chargers'), (2017, 'Los Angeles Chargers')],
    'SD': [(1961, 'San Diego Chargers')],
    'LAR': [(1937, 'Cleveland Rams'), (1946, 'Los Angeles Rams'), (1995, 'St. Louis Rams'), (2016, 'Los Angeles Rams')],
    'LA': [(2016, 'Los Angeles Rams')], 'STL': [(1995, 'St. Louis Rams')],
    'MIA': [(1966, 'Miami Dolphins')], 'MIN': [(1961, 'Minnesota Vikings')],
    'NE': [(1960, 'Boston Patriots'), (1971, 'New England Patriots')], 'NO': [(1967, 'New Orleans Saints')], 'NYG': [(1925, 'New York Giants')],
    'NYJ': [(1960, 'New York Titans'), (1963, 'New York Jets')],
    'OAK': [(1960, 'Oakland Raiders'), (1982, 'Los Angeles Raiders'), (1995, 'Oakland Raiders'), (2020, 'Las Vegas Raiders')], 'LV': [(2020, 'Las Vegas Raiders')],
    'PHI': [(1933, 'Philadelphia Eagles'), (1943, 'Phil-Pitt Steagles'), (1944, 'Philadelphia Eagles')],
    'PIT': [(1933, 'Pittsburgh Pirates'), (1940, 'Pittsburgh Steelers'), (1943, 'Phil-Pitt Steagles'), (1944, 'Card-Pitt'), (1945, 'Pittsburgh Steelers')],
    'SEA': [(1976, 'Seattle Seahawks')], 'SF': [(1946, 'San Francisco 49ers')], 'TB': [(1976, 'Tampa Bay Buccaneers')],
    'TEN': [(1960, 'Houston Oilers'), (1997, 'Tennessee Oilers'), (1999, 'Tennessee Titans')],
    'WSH': [(1932, 'Boston Braves'), (1933, 'Boston Redskins'), (1937, 'Washington Redskins'), (2020, 'Washington Football Team'), (2022, 'Washington Commanders')],
    'WAS': [(1999, 'Washington Redskins'), (2020, 'Washington Football Team'), (2022, 'Washington Commanders')],
    # AAFC 1946-49
    'BBA': [(1946, 'Buffalo Bisons'), (1947, 'Buffalo Bills')], 'BCL': [(1947, 'Baltimore Colts')], 'BDA': [(1946, 'Brooklyn Dodgers')],
    'BYK': [(1944, 'Boston Yanks'), (1949, 'New York Bulldogs')], 'CRA': [(1946, 'Chicago Rockets'), (1949, 'Chicago Hornets')],
    'LDA': [(1946, 'Los Angeles Dons')], 'MSA': [(1946, 'Miami Seahawks')], 'NAA': [(1946, 'New York Yankees')], 'NYY': [(1949, 'New York Yanks')],
    # early NFL
    'AKR': [(1920, 'Akron Pros'), (1926, 'Akron Indians')], 'BFF': [(1920, 'Buffalo All-Americans'), (1924, 'Buffalo Bisons'), (1925, 'Buffalo Rangers'), (1927, 'Buffalo Bisons')],
    'BKN': [(1930, 'Brooklyn Dodgers'), (1945, 'Brooklyn Tigers')], 'CBD': [(1920, 'Columbus Panhandles'), (1923, 'Columbus Tigers')],
    'CIB': [(1923, 'Cleveland Indians'), (1924, 'Cleveland Bulldogs')], 'DAY': [(1920, 'Dayton Triangles')], 'DUL': [(1923, 'Duluth Kelleys'), (1926, 'Duluth Eskimos')],
    'FYJ': [(1924, 'Frankford Yellow Jackets')], 'PRV': [(1925, 'Providence Steam Roller')], 'PTB': [(1925, 'Pottsville Maroons')],
    'RII': [(1920, 'Rock Island Independents')], 'CTI': [(1920, 'Chicago Tigers')], 'NYA': [(1927, 'New York Yankees')],
    'RAC': [(1922, 'Racine Legion'), (1926, 'Racine Tornadoes')], 'MIL': [(1922, 'Milwaukee Badgers')], 'TOL': [(1922, 'Toledo Maroons')],
    'DPN': [(1925, 'Detroit Panthers')], 'DWL': [(1928, 'Detroit Wolverines')], 'SIS': [(1929, 'Staten Island Stapletons')],
    'CLI': [(1931, 'Cleveland Indians')], 'GUN': [(1934, 'Cincinnati Reds')], 'RED': [(1933, 'Cincinnati Reds')], 'STG': [(1934, 'St. Louis Gunners')],
    'KCB': [(1924, 'Kansas City Blues'), (1925, 'Kansas City Cowboys')], 'HAM': [(1920, 'Hammond Pros')], 'RCH': [(1920, 'Rochester Jeffersons')],
    'LOU': [(1921, 'Louisville Brecks'), (1923, 'Louisville Colonels')], 'MNN': [(1921, 'Minneapolis Marines'), (1929, 'Minneapolis Red Jackets')],
    'COL': [(1920, 'Columbus Panhandles')], 'CCL': [(1921, 'Cincinnati Celts')], 'TOR': [(1929, 'Orange Tornadoes'), (1930, 'Newark Tornadoes')],
    'DTX': [(1952, 'Dallas Texans')], 'CRP': [(1944, 'Card-Pitt')], 'OOR': [(1922, 'Oorang Indians')], 'ECG': [(1921, 'Evansville Crimson Giants')],
    'BRL': [(1926, 'Brooklyn Lions')], 'HRT': [(1926, 'Hartford Blues')], 'LAB': [(1926, 'Los Angeles Buccaneers')], 'KEN': [(1924, 'Kenosha Maroons')],
    'SLA': [(1923, 'St. Louis All-Stars')], 'NG1': [(1921, 'New York Giants')], 'TON': [(1921, 'Tonawanda Kardex')], 'SEN': [(1921, 'Washington Senators')],
    'DTI': [(1921, 'Detroit Tigers')], 'MUN': [(1920, 'Muncie Flyers')], 'CHT': [(1920, 'Chicago Tigers')],
}


def nfl_name(code, y):
    L = NFL.get(code)
    if not L: return code
    n = L[0][1]
    for y0, nm in L:
        if y >= y0: n = nm
    return n
