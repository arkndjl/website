"""The 16:9 ARKPHILOSOPHY card (static/img/process/arkphilosophy.png): one panel a Philosophy tab, its pull line and a
small figure, numbers read from data/philosophy.json (scripts/philosophy_build.py). Rendered with Playwright.

    python3 scripts/philosophy_gfx.py
"""
import html
import json
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'static/img/process/arkphilosophy.png'


def n3(v):
    return f'{v:.3f}'.lstrip('0')


def bar(label, v, cls=''):
    return (f'<div class="b"><span class="bl">{label}</span><span class="bt"><i class="{cls}" style="width:{v * 100:.0f}%"></i>'
            f'</span><span class="bn">{n3(v)}</span></div>')


def figs(V):
    f = {}
    f['predict and describe'] = ('<div class="cap">NHL, held-out R²</div>' + bar('WAR describe', V['nhl_war_d']) +
                                 bar('WAR predict', V['nhl_war_p'], 'p') + bar('pWAR describe', V['nhl_pwar_d']) +
                                 bar('pWAR predict', V['nhl_pwar_p'], 'p'))
    f['count and rate'] = (f'<div class="two"><div><b>XPM</b><span>rate</span><span>impact</span></div>'
                           f'<div><b>VORX</b><span>count</span><span>value</span></div></div>'
                           f'<div class="cap">{html.escape(V["cr_small_name"])}: {V["cr_small_xpm"]} XPM in {V["cr_small_mp"]} min</div>')
    ticks = ''.join(f'<span style="left:{(g - 20) / 60 * 100:.1f}%"><i></i>{g}</span>' for g in range(20, 81, 10))
    f['projection'] = f'<div class="fv"><div class="fvb"></div><div class="fvt">{ticks}</div></div><div class="cap">50 regular · 60 plus · 70 star · 80 generational</div>'
    f['one framework'] = '<div class="tri"><span>player value</span><span>team fit</span><span>context</span></div><div class="cap">CFB CBB NFL NBA NHL soccer tennis CS2</div>'
    t = V['tests']
    seg = ''.join(f'<i class="{c}" style="width:{V[k] / t * 100:.1f}%"></i>' for k, c in (('shipped', 's'), ('mixed', 'm'), ('failed', 'f')))
    f['shipping'] = (f'<div class="big">{t}<small>tests</small></div><div class="stack">{seg}</div>'
                     f'<div class="cap"><em class="s">{V["shipped"]} shipped</em> <em class="m">{V["mixed"]} part</em> <em class="f">{V["failed"]} failed</em></div>')
    sw = ''.join(f'<i style="background:{c}"></i>' for c in ('#4a3b6b', '#57068c', '#7fffd4', '#c8c7ff', '#b46cff', '#ff9ec7', '#b9f2ff'))
    f['friction'] = f'<div class="sw">{sw}</div><div class="cap">border-radius 0 · one font · no emoji</div>'
    f['human'] = '<div class="type">&gt; written by a person<span>_</span></div><div class="cap">no blurbs · no AI copy</div>'
    f['skin in the game'] = '<div class="big">$0<small>free</small></div><div class="cap">no betting lines in the news</div>'
    return f


CSS = """
@font-face { font-family: P; src: url('file://%s'); }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1600px; height: 900px; font-family: P, monospace; color: #c8c7ff; -webkit-font-smoothing: none;
  background: #4a3b6b; background-image: radial-gradient(#57068c 1px, transparent 1px); background-size: 4px 4px; padding: 22px; }
.w { background: #4a3b6b; border: 3px solid; border-color: #c8c7ff #241a3a #241a3a #c8c7ff; height: 100%%; display: flex; flex-direction: column; }
.t { background: #57068c; color: #fff; font-size: 22px; padding: 6px 10px; display: flex; justify-content: space-between; }
.t b { font-weight: 400; } .t i { font-style: normal; letter-spacing: 6px; }
.hd { display: flex; align-items: baseline; justify-content: space-between; padding: 14px 22px 4px; }
.hd h1 { font-weight: 400; font-size: 64px; color: #7fffd4; letter-spacing: 4px; text-shadow: 4px 4px 0 #241a3a; }
.hd span { font-size: 22px; color: #c8c7ff; }
.g { flex: 1; display: grid; grid-template-columns: repeat(4, 1fr); grid-template-rows: 1fr 1fr; gap: 14px; padding: 10px 22px 22px; }
.p { background: #3a2d56; border: 3px solid; border-color: #241a3a #c8c7ff #c8c7ff #241a3a; display: flex; flex-direction: column; }
.pt { background: #241a3a; color: #7fffd4; font-size: 17px; padding: 4px 8px; display: flex; justify-content: space-between; }
.pt em { font-style: normal; color: #b46cff; }
.q { color: #fff; font-size: 24px; line-height: 1.35; padding: 12px 14px 6px; }
.f { margin-top: auto; padding: 4px 12px 12px; font-size: 15px; }
.cap { color: #c8c7ff; font-size: 14px; margin-top: 6px; }
.b { display: grid; grid-template-columns: 104px 1fr 40px; gap: 6px; align-items: center; margin-top: 4px; font-size: 13px; }
.bt { height: 11px; background: #241a3a; } .bt i { display: block; height: 100%%; background: #7fffd4; } .bt i.p { background: #b46cff; }
.bn { color: #fff; text-align: right; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.two div { background: #241a3a; padding: 6px 8px; display: grid; } .two b { font-weight: 400; font-size: 30px; color: #7fffd4; }
.two div + div b { color: #b46cff; }
.fv { position: relative; height: 44px; } .fvb { height: 14px; background: linear-gradient(90deg, #241a3a, #57068c 40%%, #b46cff 70%%, #b9f2ff); }
.fvt span { position: absolute; top: 16px; transform: translateX(-50%%); color: #fff; font-size: 14px; }
.fvt span i { display: block; width: 2px; height: 6px; background: #c8c7ff; margin: 0 auto 2px; }
.fvt span:first-child { transform: none; } .fvt span:last-child { transform: translateX(-100%%); }
.tri { display: grid; gap: 4px; } .tri span { background: #241a3a; color: #7fffd4; padding: 4px 8px; font-size: 16px; border-left: 4px solid #b46cff; }
.big { font-size: 52px; color: #fff; line-height: 1; } .big small { font-size: 16px; color: #c8c7ff; margin-left: 8px; }
.stack { display: flex; height: 16px; margin-top: 8px; } .stack i { display: block; height: 100%%; }
.s { background: #7fffd4; } .m { background: #b46cff; } .f2, .stack .f { background: #ff9ec7; }
.cap em { font-style: normal; background: none !important; } .cap em.s { color: #7fffd4; } .cap em.m { color: #cf9bff; } .cap em.f { color: #ff9ec7; }
.sw { display: flex; gap: 4px; } .sw i { flex: 1; height: 34px; border: 2px solid #241a3a; }
.type { background: #241a3a; color: #7fffd4; font-size: 18px; padding: 10px 8px; } .type span { color: #fff; }
.ft { display: flex; justify-content: space-between; font-size: 15px; padding: 0 22px 10px; color: #c8c7ff; }
"""


def main():
    d = json.loads((ROOT / 'data/philosophy.json').read_text())
    V, F = d['values'], figs(d['values'])
    panels = []
    for i, t in enumerate(d['tabs'], 1):
        q = next(b['q'] for b in t['blocks'] if 'q' in b)
        panels.append(f'<div class="p"><div class="pt"><span>{html.escape(t["title"])}</span><em>{i:02d}</em></div>'
                      f'<div class="q">{html.escape(q)}</div><div class="f">{F[t["tab"]]}</div></div>')
    page = (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS % (ROOT / "static/fonts/mspgothic-pixel.woff2")}</style></head>'
            f'<body><div class="w"><div class="t"><b>ARKPHILOSOPHY.exe</b><i>_□×</i></div>'
            f'<div class="hd"><h1>ARKPHILOSOPHY</h1><span>Noah Dengler · ARKNDJL</span></div>'
            f'<div class="g">{"".join(panels)}</div>'
            f'<div class="ft"><span>arkndjl.net/process</span><span>{V["tests"]} tests · {V["changes"]} changes logged</span></div>'
            f'</div></body></html>')
    with tempfile.TemporaryDirectory() as tmp:
        src = pathlib.Path(tmp) / 'card.html'
        src.write_text(page)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        js = ("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
              "const p=await b.newPage({viewport:{width:1600,height:900},deviceScaleFactor:1});"
              f"await p.goto('file://{src}');await p.waitForTimeout(800);await p.screenshot({{path:'{OUT}'}});await b.close();}})();")
        subprocess.run(['node', '-e', js], check=True, cwd=tmp)
    print('arkphilosophy:', OUT.relative_to(ROOT))


if __name__ == '__main__':
    main()
