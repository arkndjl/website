# tour-level tournament name -> ISO2 host country; INDOOR = names (tour-aware where needed) played indoors
C = {}
def add(cc, *ns):
    for n in ns: C[n.strip().lower()] = cc
add('nl', "'s Hertogenbosch", 'Hertogenbosch', 'S-Hertogenbosch', 's Hertogenbosch', 's-Hertogenbosch', 'Rotterdam')
add('br', 'ATP Rio de Janeiro', 'Rio De Janeiro', 'Rio de Janeiro', 'Rio Olympics', 'Florianopolis', 'Sao Paulo')
add('ae', 'Abu Dhabi', 'Dubai'); add('mx', 'Acapulco', 'Cancun Finals', 'Guadalajara', 'Guadalajara 2', 'Guadalajara Finals', 'Los Cabos', 'Merida', 'Monterrey')
add('au', 'Adelaide', 'Adelaide 1', 'Adelaide 2', 'Australian Open', 'Brisbane', 'Gippsland Trophy', 'Grampians Trophy', 'Great Ocean Road Open', 'Hobart', 'Melbourne', 'Melbourne 1', 'Melbourne 2', 'Murray River Open', 'Phillip Island Trophy', 'Sydney', 'Yarra Valley Classic', 'Atp Cup', 'United Cup')
add('kz', 'Almaty', 'Astana', 'Nur-Sultan'); add('tr', 'Antalya', 'Istanbul'); add('be', 'Antwerp', 'Brussels')
add('gr', 'Athens'); add('us', 'Atlanta', 'Austin', 'Carlsbad', 'Charleston', 'Charleston 1', 'Charleston 2', 'Chicago 1', 'Chicago 2', 'Cincinnati', 'Cincinnati Masters', 'Cleveland', 'Dallas', 'Delray Beach', 'Fort Worth Finals', 'Houston', 'Indian Wells', 'Indian Wells Masters', 'Lexington', 'Los Angeles', 'Memphis', 'Miami', 'Miami Masters', 'New Haven', 'New York', 'Newport', 'San Diego', 'San Jose', 'Stanford', 'US Open', 'Us Open', 'Washington', 'Winston-Salem')
add('nz', 'Auckland'); add('at', 'Bad Gastein', 'Kitzbuhel', 'Linz', 'Vienna'); add('de', 'Bad Homburg', 'Berlin', 'Cologne 1', 'Cologne 2', 'Dusseldorf', 'Halle', 'Hamburg', 'Munich', 'Nuremberg', 'Nurnberg', 'Stuttgart')
add('az', 'Baku'); add('th', 'Bangkok', 'Hua Hin', 'Hua Hin 2', 'Pattaya'); add('ba', 'Banja Luka'); add('es', 'Barcelona', 'Calvia', 'Gijon', 'Madrid', 'Madrid Masters', 'Mallorca', 'Marbella', 'Tenerife', 'Valencia')
add('ch', 'Basel', 'Biel', 'Geneva', 'Gstaad', 'Lausanne', 'Lugano'); add('se', 'Bastad', 'Stockholm'); add('cn', 'Beijing', 'Chengdu', 'Guangzhou', 'Guangzhou Open', 'Hangzhou', 'Jiujiang', 'Nanchang', 'Ningbo', 'Shanghai', 'Shanghai Masters', 'Shenzhen', 'Shenzhen Finals', 'Tianjin', 'Wuhan', 'Zhengzhou', 'Zhuhai')
add('rs', 'Belgrade', 'Belgrade 2'); add('gb', 'Birmingham', 'Eastbourne', 'London', 'London Olympics', 'Nottingham', "Queen's Club", 'Wimbledon', 'Tour Finals')
add('co', 'Bogota'); add('hr', 'Bol', 'Umag', 'Zagreb'); add('ro', 'Bucharest', 'Cluj Napoca', 'Cluj-Napoca', 'Cluj-Napoca 1', 'Cluj-Napoca 2', 'Iasi'); add('hu', 'Budapest')
add('ar', 'Buenos Aires', 'Buenos Aires 125', 'Cordoba'); add('it', 'Cagliari', 'Courmayeur', 'Florence', 'Naples', 'Palermo', 'Parma', 'Rome', 'Rome Masters', 'Sardinia')
add('ca', 'Canada Masters', 'Granby', 'Montreal', 'Quebec City', 'Toronto'); add('ma', 'Casablanca', 'Fes', 'Marrakech', 'Rabat'); add('in', 'Chennai', 'Pune')
add('dk', 'Copenhagen'); add('qa', 'Doha'); add('pt', 'Estoril', 'Oeiras'); add('pl', 'Gdynia', 'Katowice', 'Warsaw'); add('jp', 'Hiroshima', 'Japan Open Tokyo', 'Osaka', 'Tokyo', 'Tokyo Olympics', 'Toray Pan Pacific Open Tennis')
add('hk', 'Hong Kong'); add('tw', 'Kaohsiung', 'Taipei'); add('lv', 'Jurmala'); add('my', 'Kuala Lumpur'); add('fr', 'Limoges', 'Lyon', 'Marseille', 'Metz', 'Montpellier', 'Nice', 'Paris', 'Paris Masters', 'Paris Olympics', 'Roland Garros', 'Rouen', 'Strasbourg')
add('cz', 'Livesport Prague Open', 'Ostrava', 'Prague'); add('lu', 'Luxembourg'); add('mc', 'Monte Carlo Masters'); add('ru', 'Moscow', 'St Petersburg', 'St. Petersburg'); add('tn', 'Monastir')
add('sa', 'Riyadh Finals', 'Next Gen Finals', 'NextGen Finals'); add('si', 'Portoroz'); add('ec', 'Quito'); add('cl', 'Santiago', 'Vina del Mar'); add('kr', 'Seoul'); add('sg', 'Singapore', 'WTA Championships')
add('bg', 'Sofia'); add('ee', 'Tallinn'); add('uz', 'Tashkent'); add('il', 'Tel Aviv')
# Olympics 'Olympics' (2012-24 ambiguous) left out; Laver Cup, Tournament of Champions, WTA Finals vary by year: left out
INDOOR_ANY = {'antwerp', 'basel', 'brussels', 'cologne 1', 'cologne 2', 'dallas', 'fort worth finals', 'limoges', 'linz', 'luxembourg', 'lyon', 'marseille', 'memphis', 'metz', 'montpellier', 'moscow', 'ostrava', 'paris masters', 'rotterdam', 'sofia', 'st petersburg', 'st. petersburg', 'stockholm', 'tallinn', 'tour finals', 'vienna', 'next gen finals', 'nextgen finals', 'quebec city', 'cluj-napoca', 'cluj-napoca 1', 'cluj napoca', 'astana', 'nur-sultan', 'almaty', 'san jose', 'riyadh finals', 'zhuhai', 'shenzhen finals', 'belgrade 2', 'naples', 'gijon', 'florence', 'singapore', 'wta championships', 'chicago 2'}
INDOOR_TOUR = {('wta', 'stuttgart'), ('wta', 'paris'), ('atp', 'zagreb'), ('atp', 'new york'), ('wta', 'st petersburg')}
def country(name): return C.get((name or '').strip().lower())
def indoor(tour, name):
    n = (name or '').strip().lower()
    return n in INDOOR_ANY or (tour, n) in INDOOR_TOUR
