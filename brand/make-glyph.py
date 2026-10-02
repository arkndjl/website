"""Extract the 🜎 outline from Noto Sans Symbols (weight 500) and write:
   static/favicon.svg        vector favicon, transparent, colour follows the OS theme
   brand/favicon.html        two-tone glyph page that render.js screenshots for PNG/ICO
   data/favicon.json         path + metrics for the animated favicon script in extended_head
   brand/exports/logo-glyph-{lilac,purple,teal}.svg   vector logo files (also used by the templates)
Run: python3 brand/make-favicon.py   (needs: pip install fonttools)"""
import json, pathlib
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.boundsPen import BoundsPen

root = pathlib.Path(__file__).resolve().parent.parent
font = instantiateVariableFont(TTFont(root / 'brand/fonts/NotoSansSymbols[wght].ttf'), {'wght': 500})
gs = font.getGlyphSet(); glyph = gs[font.getBestCmap()[0x1F70E]]
bp = BoundsPen(gs); glyph.draw(bp); xmin, ymin, xmax, ymax = bp.bounds
sp = SVGPathPen(gs, ntos=lambda v: ('%.1f' % v).rstrip('0').rstrip('.')); glyph.draw(sp); d = sp.getCommands()
cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
side = max(xmax - xmin, ymax - ymin) * 1.12          # square box with 6% padding each side
vb = '%.1f %.1f %.1f %.1f' % (cx - side / 2, -(cy + side / 2), side, side)
LILAC, PURPLE, STROKE = '#c8c7ff', '#4a3b6b', side * 0.045

(root / 'static/favicon.svg').write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">'
    f'<style>path{{fill:{PURPLE}}}@media (prefers-color-scheme:dark){{path{{fill:{LILAC}}}}}</style>'
    f'<path transform="scale(1,-1)" d="{d}"/></svg>\n')
# raster page: lilac fill with a purple outline so it reads on light and dark tab bars
(root / 'brand/favicon.html').write_text(
    '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;background:transparent;overflow:hidden}'
    'svg{display:block;width:100vw;height:100vh}body.solid{background:' + PURPLE + '}body.solid path{stroke:none}</style></head>'
    f'<body><svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><path transform="scale(1,-1)" fill="{LILAC}" '
    f'stroke="{PURPLE}" stroke-width="{STROKE:.1f}" paint-order="stroke" stroke-linejoin="round" d="{d}"/></svg>'
    '<script>if(location.hash==="#solid")document.body.classList.add("solid")</script></body></html>\n')
exports = root / 'brand/exports'; exports.mkdir(exist_ok=True)
for name, colour in (('lilac', LILAC), ('purple', PURPLE), ('teal', '#7fffd4')):
    (exports / f'logo-glyph-{name}.svg').write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}"><path transform="scale(1,-1)" fill="{colour}" d="{d}"/></svg>\n')
(root / 'data/favicon.json').write_text(json.dumps({'d': d, 'cx': round(cx, 1), 'cy': round(cy, 1), 'side': round(side, 1), 'stroke': round(STROKE, 1)}) + '\n')
print('favicon.svg, favicon.html, favicon.json and logo-glyph-*.svg written; glyph box', round(xmax - xmin), 'x', round(ymax - ymin))
