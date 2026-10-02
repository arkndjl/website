"""Build a pixel web font from MS Gothic's embedded 16px bitmap strike.

MS Gothic's pixel look comes from bitmap strikes that browsers ignore for web
fonts and that disappear at large sizes. This script turns the 16px strike into
an outline font in which every lit pixel is a 64-unit square (1024 units per
em), so the exact bitmap renders at 16px, 32px, 128px ... in any browser.

Input : brand/fonts/msgothic.ttc  (copy from C:\\Windows\\Fonts; not committed)
Output: static/fonts/mspgothic-pixel.woff2 (MS PGothic face, proportional Latin: the site font)
        FACE=0 python3 brand/make-pixel-font.py -> static/fonts/msgothic-pixel.woff2 (monospaced MS Gothic)
Run   : python3 brand/make-pixel-font.py   (needs: pip install fonttools brotli)
"""
import os, pathlib
from fontTools.ttLib import TTCollection
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'brand/fonts/msgothic.ttc'
# FACE 0 = MS Gothic (monospaced Latin), 2 = MS PGothic (proportional Latin); same bitmap drawings
FACE = int(os.environ.get('FACE', '2'))
OUT = ROOT / ('static/fonts/msgothic-pixel.woff2' if FACE == 0 else 'static/fonts/mspgothic-pixel.woff2')
PPEM, UPEM = 16, 1024
PX = UPEM // PPEM  # 64 units per pixel
FAMILY = 'MS Gothic Pixel' if FACE == 0 else 'MS PGothic Pixel'

RANGES = [(0x20, 0x7E), (0xA0, 0xFF), (0x100, 0x17F), (0x2010, 0x2027), (0x2030, 0x203A), (0x2044, 0x2044),
          (0x20AC, 0x20AC), (0x2122, 0x2122), (0x2190, 0x2199), (0x2212, 0x2212), (0x221E, 0x221E),
          (0x2260, 0x2265), (0x25A0, 0x25A1), (0x25B2, 0x25B3), (0x25CB, 0x25CF), (0x2605, 0x2606), (0x266A, 0x266B)]

src = TTCollection(str(SRC)).fonts[FACE]
cmap = src.getBestCmap()
eblc, ebdt = src['EBLC'], src['EBDT']
si = next(i for i, s in enumerate(eblc.strikes) if s.bitmapSizeTable.ppemX == PPEM)
strike = eblc.strikes[si]
bitmaps = ebdt.strikeData[si]
asc, desc = strike.bitmapSizeTable.hori.ascender, strike.bitmapSizeTable.hori.descender

# metrics for format-5 glyphs live in the index subtable
sub_metrics = {}
for st in strike.indexSubTables:
    m = getattr(st, 'metrics', None)
    if m is not None:
        for n in st.names:
            sub_metrics[n] = m

class M:  # normalised horizontal metrics (small and big glyph metrics differ in field names)
    def __init__(self, m):
        self.width, self.height = m.width, m.height
        self.BearingX = getattr(m, 'BearingX', getattr(m, 'horiBearingX', 0))
        self.BearingY = getattr(m, 'BearingY', getattr(m, 'horiBearingY', 0))
        self.Advance = getattr(m, 'Advance', getattr(m, 'horiAdvance', 0))

def pixels(name):
    g = bitmaps[name]
    if hasattr(g, 'ensureDecompiled'):
        g.ensureDecompiled()
    raw = getattr(g, 'metrics', None) or sub_metrics.get(name)
    m = M(raw)
    rows = []
    for r in range(m.height):
        row = g.getRow(r, bitDepth=1, metrics=raw, reverseBytes=False)
        bits = ''.join(f'{b:08b}' for b in row)[:m.width]
        rows.append(bits)
    return m, rows

def rect(pen, x0, y0, x1, y1):
    pen.moveTo((x0, y0)); pen.lineTo((x0, y1)); pen.lineTo((x1, y1)); pen.lineTo((x1, y0)); pen.closePath()

glyphs, widths, charmap, order = {}, {}, {}, ['.notdef']
pen = TTGlyphPen(None); glyphs['.notdef'] = pen.glyph(); widths['.notdef'] = 8 * PX
for lo, hi in RANGES:
    for cp in range(lo, hi + 1):
        name = cmap.get(cp)
        if not name or name not in bitmaps or name in glyphs:
            if name in glyphs:
                charmap[cp] = name
            continue
        m, rows = pixels(name)
        pen = TTGlyphPen(None)
        for r, bits in enumerate(rows):
            c = 0
            while c < len(bits):
                if bits[c] == '1':
                    c0 = c
                    while c < len(bits) and bits[c] == '1':
                        c += 1
                    x0 = (m.BearingX + c0) * PX; x1 = (m.BearingX + c) * PX
                    y1 = (m.BearingY - r) * PX; y0 = y1 - PX
                    rect(pen, x0, y0, x1, y1)
                else:
                    c += 1
        glyphs[name] = pen.glyph(); widths[name] = m.Advance * PX
        charmap[cp] = name; order.append(name)

fb = FontBuilder(UPEM, isTTF=True)
fb.setupGlyphOrder(order)
fb.setupCharacterMap(charmap)
fb.setupGlyf(glyphs)
fb.setupHorizontalMetrics({n: (widths[n], 0) for n in order})
fb.setupHorizontalHeader(ascent=asc * PX, descent=desc * PX, lineGap=0)
fb.setupNameTable({'familyName': FAMILY, 'styleName': 'Regular', 'fullName': FAMILY,
                   'psName': FAMILY.replace(' ', '') + '-Regular', 'uniqueFontIdentifier': FAMILY.replace(' ', '') + ';16px-strike',
                   'description': 'MS Gothic 16px bitmap strike converted to outlines for web use.'})
fb.setupOS2(sTypoAscender=asc * PX, sTypoDescender=desc * PX, sTypoLineGap=0,
            usWinAscent=asc * PX, usWinDescent=-desc * PX, fsSelection=0x80 | 0x40,  # USE_TYPO_METRICS | REGULAR
            xAvgCharWidth=8 * PX, achVendID='ARKN')
fb.setupPost()
fb.font['head'].flags |= 0x0008  # integer scaling
fb.font.flavor = 'woff2'
OUT.parent.mkdir(parents=True, exist_ok=True)
fb.save(str(OUT))
print(f'{OUT.relative_to(ROOT)}: {len(order) - 1} glyphs from the {PPEM}px strike, ascent {asc}px descent {desc}px, {OUT.stat().st_size} bytes')
