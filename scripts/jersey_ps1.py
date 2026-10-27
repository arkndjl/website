"""ARKNDJL jerseys as PS1/N64-style low-poly renders (animated WebPs for the ARKNDJL gallery).

The pixel kits from scripts/jersey_art.py are the textures. Each jersey is a puffed
low-poly mesh (front and back sheets meeting at the silhouette), drawn by a small
software rasteriser that copies the PlayStation's look: 320x240, vertices snapped to
whole pixels (jitter), affine texture mapping (warping), colour-keyed cut-outs,
flat-shaded facets, 15-bit colour with ordered dither, distance fog.

Writes static/img/art/arkndjl-ps1-<sport>.webp and arkndjl-ps1-lineup.webp.
Run: python3 scripts/jersey_ps1.py [sport|lineup ...] [--frames N] [--out DIR] [--stills]
"""
import math, os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jersey_art as J

RW, RH = 320, 240                      # native render size
SCALE = 2                              # output is upscaled with nearest neighbour
BG_TOP, BG_BOT = (27, 27, 31), (12, 12, 14)
FOG = np.array([20, 20, 24], float)
LIGHT = np.array([-.45, .55, .70])
LIGHT /= np.linalg.norm(LIGHT)


def rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


# ---------- textures and meshes ----------
def sprite(sport, back, kit):
    """RGBA texture (H, W, 4) of one pixel jersey; alpha 0 is the colour key."""
    tex = np.zeros((J.H, J.W, 4), np.uint8)
    for (x, y), c in J.jersey(sport, back, kit).items():
        if 0 <= x < J.W and 0 <= y < J.H:
            tex[y, x, :3] = rgb(c)
            tex[y, x, 3] = 255
    return tex


def distance(mask):
    """Chessboard distance from each inside cell to the outside, by repeated erosion."""
    d = np.zeros(mask.shape, float)
    cur = mask.copy()
    k = 0
    while cur.any():
        k += 1
        d[cur] = k
        p = np.pad(cur, 1)
        cur = cur & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return d


def mesh(front, back, step=3, depth=.42):
    """Low-poly puffed jersey: (verts (n,3), uv (n,2), tris (m,3), side (m,)) in jersey units."""
    mask = (front[..., 3] > 0) | (back[..., 3] > 0)
    d = distance(mask)
    xs = list(range(0, J.W + 1, step))
    ys = list(range(0, J.H + 1, step))
    if xs[-1] != J.W: xs.append(J.W)
    if ys[-1] != J.H: ys.append(J.H)

    def vdist(x, y):  # lattice point: min over the cells touching it (outside counts 0)
        v = []
        for cx, cy in ((x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)):
            v.append(d[cy, cx] if 0 <= cx < J.W and 0 <= cy < J.H else 0)
        return min(v)

    dmax = d.max()
    verts, uv, idx = [], [], {}
    for side, sgn in ((0, 1), (1, -1)):
        for j, y in enumerate(ys):
            for i, x in enumerate(xs):
                z = sgn * depth * (vdist(x, y) / dmax) ** .6 * J.W / 2
                idx[(side, i, j)] = len(verts)
                # world: x right, y up, z toward the viewer; one unit = one texture pixel
                verts.append((x - J.W / 2, J.H / 2 - y, z))
                uv.append((x if side == 0 else J.W - x, y))
    tris, sides = [], []
    for side in (0, 1):
        for j in range(len(ys) - 1):
            for i in range(len(xs) - 1):
                x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
                if not mask[y0:y1, x0:x1].any():
                    continue
                a, b, c, e = idx[(side, i, j)], idx[(side, i + 1, j)], idx[(side, i, j + 1)], idx[(side, i + 1, j + 1)]
                q = [(a, b, c), (b, e, c)] if side == 0 else [(a, c, b), (b, c, e)]
                tris += q
                sides += [side, side]
    return np.array(verts, float), np.array(uv, float), np.array(tris), np.array(sides)


class Model:
    def __init__(self, sport, kit):
        # the back sheet is seen from behind: its uv runs right to left (see mesh)
        self.tex = [sprite(sport, False, kit), sprite(sport, True, kit)]
        self.v, self.uv, self.t, self.side = mesh(*self.tex)


# ---------- rasteriser ----------
class Frame:
    def __init__(self):
        g = np.linspace(0, 1, RH)[:, None, None]
        self.img = (np.array(BG_TOP) * (1 - g) + np.array(BG_BOT) * g) * np.ones((RH, RW, 3))
        self.z = np.full((RH, RW), np.inf)

    def tri(self, p, uv, tex, shade, fog, cull=True):
        """p: 3 screen points (x, y, depth) already snapped; uv affine in screen space."""
        (x0, y0, _), (x1, y1, _), (x2, y2, _) = p
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if area == 0 or (cull and area < 0):
            return  # back-facing or degenerate
        xa, xb = int(max(0, min(x0, x1, x2))), int(min(RW - 1, max(x0, x1, x2)))
        ya, yb = int(max(0, min(y0, y1, y2))), int(min(RH - 1, max(y0, y1, y2)))
        if xa > xb or ya > yb:
            return
        X, Y = np.meshgrid(np.arange(xa, xb + 1) + .5, np.arange(ya, yb + 1) + .5)
        w0 = ((x1 - X) * (y2 - Y) - (x2 - X) * (y1 - Y)) / area
        w1 = ((x2 - X) * (y0 - Y) - (x0 - X) * (y2 - Y)) / area
        w2 = 1 - w0 - w1
        ins = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not ins.any():
            return
        z = w0 * p[0][2] + w1 * p[1][2] + w2 * p[2][2]
        u = w0 * uv[0][0] + w1 * uv[1][0] + w2 * uv[2][0]   # affine: no perspective divide
        v = w0 * uv[0][1] + w1 * uv[1][1] + w2 * uv[2][1]
        tu = np.clip(u.astype(int), 0, tex.shape[1] - 1)
        tv = np.clip(v.astype(int), 0, tex.shape[0] - 1)
        texel = tex[tv, tu]
        zb = self.z[ya:yb + 1, xa:xb + 1]
        ok = ins & (texel[..., 3] > 0) & (z < zb)
        if not ok.any():
            return
        col = texel[..., :3].astype(float) * shade
        col = col * (1 - fog) + FOG * fog
        self.img[ya:yb + 1, xa:xb + 1][ok] = col[ok]
        zb[ok] = z[ok]

    def model(self, m, pos, yaw, cam):
        c, s = math.cos(yaw), math.sin(yaw)
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        w = m.v @ R.T * cam["unit"] + pos
        e = w - cam["eye"]
        zc = -e[:, 2]  # camera looks down -z
        f = cam["f"]
        sx = np.floor(RW / 2 + f * e[:, 0] / zc)  # whole-pixel snap: PS1 vertex jitter
        sy = np.floor(RH / 2 - f * (e[:, 1]) / zc)
        nrm_src = w
        for t, side in zip(m.t, m.side):
            a, b, cc = t
            n = np.cross(nrm_src[cc] - nrm_src[a], nrm_src[b] - nrm_src[a])
            ln = np.linalg.norm(n)
            if ln == 0:
                continue
            lam = max(0., float(n @ LIGHT) / ln)
            shade = round((.5 + .58 * lam) * 8) / 8   # stepped flat shading
            depth = (zc[a] + zc[b] + zc[cc]) / 3
            fog = min(.55, max(0., (depth - cam["fog0"]) / cam["fog1"]))
            self.tri([(sx[a], sy[a], zc[a]), (sx[b], sy[b], zc[b]), (sx[cc], sy[cc], zc[cc])],
                     [m.uv[a], m.uv[b], m.uv[cc]], m.tex[side], shade, fog)

    def floor(self, cam, y, half=12, z0=-16, z1=8, n=14):
        """Checker floor, coarse quads so the affine warp shows."""
        tex = np.zeros((16, 16, 4), np.uint8)
        a, b, line = rgb("#26262c"), rgb("#1c1c21"), rgb("#3f3e52")
        for yy in range(16):
            for xx in range(16):
                tex[yy, xx, :3] = a if (xx < 8) ^ (yy < 8) else b
                if xx in (0, 8) or yy in (0, 8):
                    tex[yy, xx, :3] = line
                tex[yy, xx, 3] = 255
        xs = np.linspace(-half, half, n + 1)
        zs = np.linspace(z0, z1, n + 1)
        f = cam["f"]
        for i in range(n):
            for j in range(n):
                q = [(xs[i], zs[j]), (xs[i + 1], zs[j]), (xs[i + 1], zs[j + 1]), (xs[i], zs[j + 1])]
                pts, uvs = [], []
                for (x, z), (u, v) in zip(q, ((0, 0), (16, 0), (16, 16), (0, 16))):
                    e = np.array([x, y, z]) - cam["eye"]
                    zc = -e[2]
                    if zc <= .3:
                        break
                    pts.append((math.floor(RW / 2 + f * e[0] / zc), math.floor(RH / 2 - f * e[1] / zc), zc + 50))
                    uvs.append((min(u, 15.99), min(v, 15.99)))
                else:
                    depth = sum(p[2] - 50 for p in pts) / 4
                    fog = min(.85, max(0., (depth - cam["fog0"]) / cam["fog1"]))
                    for t in ((0, 2, 1), (0, 3, 2)):
                        self.tri([pts[k] for k in t], [uvs[k] for k in t], tex, 1.0, fog, cull=False)

    def shadow(self, cam, pos, y, r):
        """Soft dark blob on the floor under a model (stepped, like a baked shadow decal)."""
        e = np.array([pos[0], y, pos[2]]) - cam["eye"]
        zc = -e[2]
        sx, sy = RW / 2 + cam["f"] * e[0] / zc, RH / 2 - cam["f"] * e[1] / zc
        rx, ry = cam["f"] * r / zc, cam["f"] * r * .28 / zc
        Y, X = np.mgrid[0:RH, 0:RW]
        d = ((X - sx) / rx) ** 2 + ((Y - sy) / ry) ** 2
        for lim, k in ((1, .8), (.55, .68)):
            self.img[d < lim] *= k

    def text(self, s, cx, y, col, k=1):
        cells = {}
        J.ctext(cells, s, cx, y, col, k)
        for (x, yy), c in cells.items():
            if 0 <= x < RW and 0 <= yy < RH:
                self.img[yy, x] = rgb(c)

    def finish(self):
        """15-bit colour with a 4x4 ordered dither, then nearest-neighbour upscale."""
        bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16 - .5
        dith = np.tile(bayer, (RH // 4, RW // 4))[..., None] * 8
        q = np.clip(np.floor((self.img + dith) / 8) * 8 + 4, 0, 255).astype(np.uint8)
        return Image.fromarray(q).resize((RW * SCALE, RH * SCALE), Image.NEAREST)


# ---------- scenes ----------
def sport_scene(sport, frames):
    models = [Model(sport, kit) for kit in J.KITS]
    cam = dict(eye=np.array([0, 1.0, 9.5]), f=300, unit=.064, fog0=8, fog1=10)
    out = []
    for i in range(frames):
        fr = Frame()
        fr.floor(cam, -1.5)
        t = 2 * math.pi * i / frames
        for k, m in enumerate(models):
            bob = .08 * math.sin(t * 2 + k)
            pos = np.array([(k - 1) * 3.3, .15 + bob, 0])
            fr.shadow(cam, pos, -1.5, 1.35 - bob)
            fr.model(m, pos, t + k * .35, cam)
        fr.text("ARKNDJL", RW // 2, 10, J.LILAC, 2)
        fr.text(sport.upper(), RW // 2, 24, J.TEAL)
        for k, kit in enumerate(J.KITS):
            fr.text(kit.upper(), RW // 2 + (k - 1) * 104, RH - 16, J.LILAC)
        out.append(fr.finish())
    return out


def lineup_scene(frames, kit="home"):
    models = [Model(s, kit) for s in J.SPORTS]
    cam = dict(eye=np.array([0, .9, 10.5]), f=300, unit=.046, fog0=9, fog1=12)
    out = []
    for i in range(frames):
        fr = Frame()
        fr.floor(cam, -1.25)
        t = 2 * math.pi * i / frames
        for k, m in enumerate(models):
            pos = np.array([(k - 2) * 1.95, .1 + .07 * math.sin(t * 2 + k), -abs(k - 2) * .7])
            fr.shadow(cam, pos, -1.25, 1.05)
            fr.model(m, pos, t + k * .5, cam)
        fr.text("ARKNDJL", RW // 2, 10, J.LILAC, 2)
        fr.text(kit.upper() + " KITS", RW // 2, 24, J.TEAL)
        out.append(fr.finish())
    return out


def save_anim(frames, path, ms=70):
    # lossless animated WebP: keeps every pixel crisp at about a third of a GIF's size
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0, lossless=True, method=6)


if __name__ == "__main__":
    args = sys.argv[1:]
    n = int(args[args.index("--frames") + 1]) if "--frames" in args else 48
    out = args[args.index("--out") + 1] if "--out" in args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "img", "art")
    only = [a for a in args if a in J.SPORTS + ["lineup"]]
    for s in only or J.SPORTS + ["lineup"]:
        fr = lineup_scene(n) if s == "lineup" else sport_scene(s, n)
        save_anim(fr, os.path.join(out, f"arkndjl-ps1-{s}.webp"))
        if "--stills" in args:
            fr[0].save(os.path.join(out, f"arkndjl-ps1-{s}.png"))
        print(s, "ok")
