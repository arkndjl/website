#!/usr/bin/env python3
"""Turn photos and logos into small pixel-art images (needs ImageMagick).

    python3 scripts/pixel_portraits.py           # make anything missing
    python3 scripts/pixel_portraits.py --force   # remake everything

Each source is cropped square, shrunk to a small grid (32 or 48 px) and cut down to a
limited palette without dithering, so it reads as pixel art. Pages show the result scaled
up by a whole number with image-rendering: pixelated (see .pxphoto in static/style.css).
"""
import os, subprocess, sys, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "arkndjl.net pixel portraits (https://arkndjl.net)"

# out (under static/) -> (source url, square crop "WxH+X+Y" of the source or None if it is square, grid, colours)
PORTRAITS = {
    "img/px/brunson.png": ("https://a.espncdn.com/i/headshots/nba/players/full/3934672.png", "400x400+100+0", 32, 20),
    "img/px/wright.png": ("https://img.mlbstatic.com/mlb-photos/image/upload/w_426,q_auto:best/v1/people/431151/headshot/67/current", "400x400+13+40", 32, 20),
    "img/px/laursen.png": ("https://distribution.faceit-cdn.net/images/c3a31e6a-3dc2-415b-b4ab-7fa87d0dea42.jpg", None, 40, 16),
    "img/px/1nt.png": ("https://distribution.faceit-cdn.net/images/af61f233-8c12-43a1-9e7e-7d9221c8e5e7.jpg", None, 48, 12),
}


def make(out, url, crop, grid, colours):
    path = os.path.join(ROOT, "static", out)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r, tempfile.NamedTemporaryFile(suffix=".img") as src:
        src.write(r.read())
        src.flush()
        args = ["convert", src.name + "[0]", "-background", "#2b2140", "-flatten"]
        if crop:  # without one the source is taken as already square
            args += ["-crop", crop, "+repage"]
        args += ["-filter", "box", "-resize", f"{grid}x{grid}!", "+dither", "-colors", str(colours), "-strip", path]
        subprocess.run(args, check=True)
    print(f"  made  {out}")


def main():
    force = "--force" in sys.argv
    for out, (url, crop, grid, colours) in PORTRAITS.items():
        if force or not os.path.exists(os.path.join(ROOT, "static", out)):
            make(out, url, crop, grid, colours)


if __name__ == "__main__":
    main()
