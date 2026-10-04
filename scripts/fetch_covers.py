#!/usr/bin/env python3
"""Download ARKLIBRARY cover thumbnails into static/img/covers/.

    python3 scripts/fetch_covers.py            # fetch anything missing
    python3 scripts/fetch_covers.py --force    # re-fetch everything

Books come from Open Library (search by title + author, then the cover id).
Open Library has no film posters or building photos, so those come from the
lead image of the English Wikipedia article. Each image's source page and credit
(author and licence, where the file has them) go into data/covers.json, which the
winlist shortcode uses for the thumbnail's link and hover text.

To add an item: add a row to COVERS below, run this script, and give the list row
a fourth column with the same path, e.g.  - Dune | Frank Herbert | 1965 | /img/covers/dune-book.jpg
Standard library only. If ImageMagick's `convert` is on PATH, images are resized
to 240 px wide; otherwise they are kept at the size the source serves.
"""
import json, os, re, shutil, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "static", "img", "covers")
DATA = os.path.join(ROOT, "data", "covers.json")
UA = "arkndjl.net cover fetcher (https://arkndjl.net; arkndjl site maintenance)"
WIDTH = 240

# slug -> (source, query). source "book" = Open Library title|author; "olid" = a pinned Open Library
# cover id|work key, for when search picks a bad scan; "wiki" = Wikipedia article title;
# "file" = a pinned Wikipedia/Commons file name, for when the lead image is a logo.
COVERS = {
    "the-bell-jar":     ("book", "The Bell Jar|Sylvia Plath"),
    "dune-book":        ("book", "Dune|Frank Herbert"),
    "the-present-age":  ("olid", "15043093|/works/OL35424793W"),  # Fontana edition; search hits a blank binding
    "marty-supreme":    ("wiki", "Marty Supreme"),
    "dune-2021":        ("wiki", "Dune (2021 film)"),
    "dune-part-two":    ("wiki", "Dune: Part Two"),
    "the-batman":       ("wiki", "The Batman (film)"),
    "anora":            ("wiki", "Anora"),
    "pearl":            ("wiki", "Pearl (2022 film)"),
    "skam":             ("file", "Skam - NMD 2016 (26893986332).jpg"),  # cast photos: the leads are logos
    "seinfeld":         ("file", "Seinfeld actors montage.jpg"),
    "sagrada-familia":  ("wiki", "Sagrada Família"),
    "fallingwater":     ("wiki", "Fallingwater"),
}


def get(url, binary=False, tries=5):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for i in range(tries):
        time.sleep(1)  # Wikimedia rate-limits bursts
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(int(e.headers.get("Retry-After") or 2 ** (i + 2)))
    return body if binary else json.loads(body)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def open_library(query):
    title, author = query.split("|")
    q = urllib.parse.urlencode({"title": title, "author": author, "limit": 10,
                                "fields": "key,title,cover_i,edition_count"})
    docs = [d for d in get(f"https://openlibrary.org/search.json?{q}").get("docs", []) if d.get("cover_i")]
    if not docs:
        raise LookupError(f"no Open Library cover for {query!r}")
    doc = max(docs, key=lambda d: d.get("edition_count", 0))  # the main work, not a stray edition
    return {
        "url": f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg",
        "source": f"https://openlibrary.org{doc['key']}",
        "credit": "cover via Open Library",
    }


def open_library_pinned(query):
    cover, work = query.split("|")
    return {"url": f"https://covers.openlibrary.org/b/id/{cover}-L.jpg",
            "source": f"https://openlibrary.org{work}", "credit": "cover via Open Library"}


def wikipedia(article):
    api = "https://en.wikipedia.org/w/api.php?"
    q = urllib.parse.urlencode({"action": "query", "format": "json", "redirects": 1,
                                "titles": article, "prop": "pageimages", "piprop": "name",
                                "pilicense": "any"})  # posters are non-free; the default skips them
    page = next(iter(get(api + q)["query"]["pages"].values()))
    name = page.get("pageimage")
    if not name:
        raise LookupError(f"no lead image on Wikipedia for {article!r}")
    return wiki_file(name)


def wiki_file(name):
    api = "https://en.wikipedia.org/w/api.php?"
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": f"File:{name}",
                                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": WIDTH * 2})
    info = next(iter(get(api + q)["query"]["pages"].values()))["imageinfo"][0]
    meta = info.get("extmetadata", {})
    artist = strip_html(meta.get("Artist", {}).get("value"))
    if len(artist) > 60:  # composites list every source photo's author
        artist = "various, see source"
    licence = strip_html(meta.get("LicenseShortName", {}).get("value"))
    if licence.lower() == "fair use":  # film posters
        credit = "poster via Wikipedia, fair use"
    else:
        credit = ", ".join(x for x in (f"photo: {artist}" if artist else "", licence) if x) or "image via Wikipedia"
    return {"url": info.get("thumburl") or info["url"], "source": info["descriptionurl"], "credit": credit}


def save(url, path):
    raw = path + ".download"
    with open(raw, "wb") as f:
        f.write(get(url, binary=True))
    if shutil.which("convert"):
        subprocess.run(["convert", raw, "-resize", f"{WIDTH}x>", "-strip", "-quality", "85", path], check=True)
        os.remove(raw)
    else:
        os.replace(raw, path)


def main():
    force = "--force" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    data = json.load(open(DATA)) if os.path.exists(DATA) else {}
    failed = []
    for slug, (kind, query) in COVERS.items():
        name = f"{slug}.jpg"
        path = os.path.join(OUT, name)
        if os.path.exists(path) and name in data and not force:
            print(f"  have  {name}")
            continue
        try:
            hit = {"book": open_library, "olid": open_library_pinned, "wiki": wikipedia, "file": wiki_file}[kind](query)
            save(hit["url"], path)
            data[name] = {"source": hit["source"], "credit": hit["credit"]}
            print(f"  got   {name}  ({hit['credit']})")
        except Exception as e:  # keep going; report at the end
            failed.append(name)
            print(f"  FAIL  {name}: {e}", file=sys.stderr)
    with open(DATA, "w") as f:
        json.dump(dict(sorted(data.items())), f, indent=2, ensure_ascii=False)
        f.write("\n")
    if failed:
        sys.exit(f"{len(failed)} failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
