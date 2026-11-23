"""Raw wikitext of the public award pages the mock driver tests read (cached in scripts/.cache/mocks_nov23/wiki).

    python3 scripts/research/mocks_nov23/fetch_wiki.py

Pages: FBS season pages 2009-2025 (Heisman voting table, position award winners), the All-America college football
team pages (consensus section), the NCAA men's basketball All-Americans pages 2009-2026 and the D-I men's basketball
season pages (major player of the year awards, conference players of the year). 3 s between requests."""
import os, subprocess, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
C = os.path.join(ROOT, 'scripts', '.cache', 'mocks_nov23', 'wiki'); os.makedirs(C, exist_ok=True)


def raw(title, name):
    f = os.path.join(C, name)
    for _ in range(4):
        if os.path.exists(f):
            s = open(f, encoding='utf-8', errors='replace').read()
            if s.lstrip().upper().startswith('#REDIRECT'):
                title = s.split('[[', 1)[1].split(']]', 1)[0].split('#')[0].replace(' ', '_'); os.remove(f)
            elif len(s) > 500: return f
            else: os.remove(f); time.sleep(10)
        subprocess.run(['curl', '-sSL', '-m', '60', '-A', 'Mozilla/5.0 (arkndjl research)', '-o', f,
                        f'https://en.wikipedia.org/w/index.php?title={title}&action=raw'])
        time.sleep(3)
    return f if os.path.exists(f) and os.path.getsize(f) > 500 else None


if __name__ == '__main__':
    for y in range(2009, 2026):
        raw(f'{y}_NCAA_Division_I_FBS_football_season', f'fbs_{y}.txt')
        raw(f'{y}_College_Football_All-America_Team', f'aa_fb_{y}.txt')
    for y in range(2009, 2027):
        raw(f'{y}_NCAA_Men%27s_Basketball_All-Americans', f'aa_bb_{y}.txt')
        raw(f'{y-1}%E2%80%93{str(y)[2:]}_NCAA_Division_I_men%27s_basketball_season', f'mbb_{y}.txt')
    print(sorted(os.listdir(C)))
