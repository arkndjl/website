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
# "file" = a pinned Wikipedia/Commons file name, for when the lead image is a logo;
# "anilist" = ANIME:<id or title> or MANGA:<id or title>, cover art from AniList (anime and manga);
# "tvmaze" = a TVmaze show id (poster); "tvperson" = a TVmaze person id (actor photo);
# "deezer" = an artist name, exact match, photo from Deezer (musicians);
# "album" = artist|album title, cover art from Deezer;
# "url" = image url|source page|credit, for a pinned file (WikiArt portraits, Open Library author photos).
COVERS = {
    "the-bell-jar":     ("olid", "14882229|/books/OL44777916M"),  # first edition: Heinemann 1963, as Victoria Lucas
    "dune-book":        ("olid", "15244952|/books/OL43283259M"),  # first edition: Chilton 1965
    "baseball-abstract": ("olid", "9496213|/books/OL3005932M"),  # 1984 Ballantine edition: no earlier cover is scanned
    "the-present-age":  ("olid", "15043093|/works/OL35424793W"),  # Fontana edition; search hits a blank binding
    "marty-supreme":    ("wiki", "Marty Supreme"),
    "dune-2021":        ("wiki", "Dune (2021 film)"),
    "dune-part-two":    ("wiki", "Dune: Part Two"),
    "the-batman":       ("wiki", "The Batman (film)"),
    "anora":            ("wiki", "Anora"),
    "pearl":            ("wiki", "Pearl (2022 film)"),
    "skam":             ("tvmaze", "14866"),
    "seinfeld":         ("tvmaze", "530"),
    "atlanta":          ("tvmaze", "6508"),
    "fullmetal-alchemist-2003": ("anilist", "ANIME:121"),  # the 2003 series, not Brotherhood
    "hunter-x-hunter-2011": ("anilist", "ANIME:11061"),  # the Madhouse series, not 1999
    "sagrada-familia":  ("wiki", "Sagrada Família"),
    "fallingwater":     ("wiki", "Fallingwater"),
    # albums
    "a-is-it-now": ("album", "Automatic|Is It Now?"),
    "a-ripe-fruit": ("album", "chokecherry|Ripe Fruit Rots And Falls"),
    "a-getting-killed": ("album", "Geese|Getting Killed"),
    "a-willoughby-tucker": ("album", "Ethel Cain|Willoughby Tucker, I'll Always Love You"),
    "a-i-love-my-computer": ("album", "Ninajirachi|I Love My Computer"),
    "a-slimyfella": ("album", "Hardrock|SLIMYFELLA"),
    "a-fancy-that": ("album", "PinkPantheress|Fancy That"),
    "a-eusexua": ("album", "FKA twigs|EUSEXUA"),
    "a-yes-please": ("album", "Sextile|yes, please."),
    "a-is-this-it": ("album", "The Strokes|Is This It"),
    "a-room-on-fire": ("album", "The Strokes|Room on Fire"),
    "a-first-impressions": ("url", "https://cdn-images.dzcdn.net/images/cover/67b74ca40694bcc143715fd2811042ab/1000x1000-000000-80-0-0.jpg|https://www.deezer.com/album/1435597|cover via Deezer"),  # Deezer's search misses it
    "a-angles": ("album", "The Strokes|Angles"),
    "a-comedown-machine": ("album", "The Strokes|Comedown Machine"),
    "a-the-new-abnormal": ("album", "The Strokes|The New Abnormal"),
    "a-reality-awaits": ("album", "The Strokes|Reality Awaits"),
    "a-tyranny": ("album", "Julian Casablancas+The Voidz|Tyranny"),
    "a-brat":           ("album", "Charli XCX|brat"),
    "a-whole-lotta-red": ("album", "Playboi Carti|Whole Lotta Red"),
    "a-die-lit":        ("album", "Playboi Carti|Die Lit"),
    "a-preachers-daughter": ("album", "Ethel Cain|Preacher's Daughter"),
    "a-mbv":            ("album", "my bloody valentine|m b v"),
    "a-miseducation":   ("album", "Lauryn Hill|The Miseducation of Lauryn Hill"),
    "a-loveless":       ("wiki", "Loveless (album)"),  # not on Deezer
    "a-you-made-me-realise": ("album", "my bloody valentine|you made me realise"),
    "a-rumours":        ("album", "Fleetwood Mac|Rumours"),
    "st-patricks":      ("url", "https://live.staticflickr.com/3/4309341_195a078e36_b.jpg|https://www.flickr.com/photos/35034359460@N01/4309341|photo: Peter Kaminski, CC BY 2.0"),
    "a-virtue": ("album", "The Voidz|Virtue"),
    # people (rows in the artists / authors / actors / architects tabs)
    "p-basquiat":       ("url", "https://uploads3.wikiart.org/images/jean-michel-basquiat.jpg!Portrait.jpg|https://www.wikiart.org/en/jean-michel-basquiat|photo via WikiArt"),
    "p-warhol":         ("url", "https://uploads3.wikiart.org/images/andy-warhol.jpg!Portrait.jpg|https://www.wikiart.org/en/andy-warhol|self-portrait, via WikiArt"),
    "p-af-klint":       ("url", "https://uploads4.wikiart.org/00452/images/hilma-af-klint/1901portrait-photograph-c-1901-or-earlier.jpg!Portrait.jpg|https://www.wikiart.org/en/hilma-af-klint|photo c. 1901, via WikiArt"),
    "p-renwick":        ("wiki", "James Renwick Jr."),
    "p-bill-james":     ("wiki", "Bill James"),
    "p-gaudi":          ("url", "https://uploads6.wikiart.org/00337/images//441px-antoni-gaudi-1878.jpg!Portrait.jpg|https://www.wikiart.org/en/antoni-gaudi|photo 1878, via WikiArt"),
    "p-wright":         ("url", "https://covers.openlibrary.org/a/id/5541052-L.jpg|https://openlibrary.org/authors/OL86573A|photo via Open Library"),
    "p-kierkegaard":    ("url", "https://covers.openlibrary.org/a/id/12727588-L.jpg|https://openlibrary.org/authors/OL20509A|sketch by N. C. Kierkegaard, via Open Library"),
    "p-plath":          ("url", "https://covers.openlibrary.org/a/id/15226387-L.jpg|https://openlibrary.org/authors/OL4327652A|photo via Open Library"),
    "p-herbert":        ("url", "https://covers.openlibrary.org/a/id/14852808-L.jpg|https://openlibrary.org/authors/OL79034A|photo via Open Library"),
    "p-chalamet":       ("tvperson", "1047"),
    "p-stanfield":      ("tvperson", "142534"),
    "g-deltarune": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/1671210/library_600x900_2x.jpg|https://store.steampowered.com/app/1671210/|box art via Steam"),
    "g-cs2": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/730/library_600x900_2x.jpg|https://store.steampowered.com/app/730/|box art via Steam"),
    "g-portal": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/400/library_600x900_2x.jpg|https://store.steampowered.com/app/400/|box art via Steam"),
    "g-portal-2": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/620/library_600x900_2x.jpg|https://store.steampowered.com/app/620/|box art via Steam"),
    "g-half-life": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/70/library_600x900_2x.jpg|https://store.steampowered.com/app/70/|box art via Steam"),
    "g-half-life-2": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/220/library_600x900_2x.jpg|https://store.steampowered.com/app/220/|box art via Steam"),
    "g-hl2-episode-one": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/380/library_600x900_2x.jpg|https://store.steampowered.com/app/380/|box art via Steam"),
    "g-hl2-episode-two": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/420/library_600x900_2x.jpg|https://store.steampowered.com/app/420/|box art via Steam"),
    "g-half-life-alyx": ("url", "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/546560/library_600x900_2x.jpg|https://store.steampowered.com/app/546560/|box art via Steam"),
    "g-pokemon-soulsilver": ("url", "https://archives.bulbagarden.net/media/upload/5/5c/SoulSilver_EN_boxart.jpg|https://archives.bulbagarden.net/wiki/File:SoulSilver_EN_boxart.jpg|box art via Bulbapedia"),  # Wikipedia pairs it with HeartGold
    "g-pokemon-platinum": ("wiki", "Pokémon Platinum"),
    "g-pokemon-emerald": ("wiki", "Pokémon Emerald"),
    "p-mbv":            ("deezer", "my bloody valentine"),
    "p-strokes":        ("deezer", "The Strokes"),
    "p-casablancas":    ("deezer", "Julian Casablancas"),
    "p-voidz":          ("deezer", "The Voidz"),
    "p-nas":            ("deezer", "Nas"),
    "p-ethel-cain":     ("deezer", "Ethel Cain"),
    "p-charli-xcx":     ("deezer", "Charli xcx"),
    "p-carti":          ("deezer", "Playboi Carti"),
    "p-automatic": ("deezer", "Automatic"),
    "p-chokecherry": ("deezer", "271260652"),  # pinned: another chokecherry has more fans
    "p-geese": ("deezer", "Geese"),
    "p-ninajirachi": ("deezer", "Ninajirachi"),
    "p-hardrock": ("deezer", "Hardrock"),
    "p-pinkpantheress": ("deezer", "PinkPantheress"),
    "p-fka-twigs": ("deezer", "FKA twigs"),
    "p-sextile": ("deezer", "Sextile"),
    "p-lauryn-hill": ("deezer", "1117"),  # pinned: the search's top hit is a different page
    "p-fleetwood-mac": ("deezer", "Fleetwood Mac"),
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


def anilist(query):
    kind, key = query.split(":", 1)
    arg = f"id: {int(key)}" if key.isdigit() else f"search: {json.dumps(key)}"
    gql = f"{{ Media({arg}, type: {kind}) {{ siteUrl coverImage {{ extraLarge }} }} }}"
    req = urllib.request.Request("https://graphql.anilist.co", data=json.dumps({"query": gql}).encode(),
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        media = json.loads(r.read())["data"]["Media"]
    return {"url": media["coverImage"]["extraLarge"], "source": media["siteUrl"], "credit": "cover art via AniList"}


def tvmaze(show_id):
    show = get(f"https://api.tvmaze.com/shows/{int(show_id)}")
    return {"url": show["image"]["original"], "source": show["url"], "credit": "poster via TVmaze"}


def tvperson(person_id):
    p = get(f"https://api.tvmaze.com/people/{int(person_id)}")
    return {"url": p["image"]["original"], "source": p["url"], "credit": "photo via TVmaze"}


def deezer(name):
    if name.isdigit():  # a pinned Deezer artist id, for names several artists share
        a = get(f"https://api.deezer.com/artist/{name}")
        return {"url": a["picture_xl"], "source": a["link"], "credit": "photo via Deezer"}
    hits = get("https://api.deezer.com/search/artist?" + urllib.parse.urlencode({"q": name}))["data"]
    hits = [h for h in hits if h["name"].lower() == name.lower()]
    if not hits:
        raise LookupError(f"no Deezer artist named {name!r}")
    a = max(hits, key=lambda h: h["nb_fan"])
    return {"url": a["picture_xl"], "source": a["link"], "credit": "photo via Deezer"}


def album(query):
    artist, title = query.split("|")
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    lead = artist.split("+")[0].strip()  # "Julian Casablancas+The Voidz" is filed under either name
    for q in (f'artist:"{artist}" album:"{title}"', f"{lead} {title}", title):  # strict first, then looser
        hits = get("https://api.deezer.com/search/album?" + urllib.parse.urlencode({"q": q}))["data"]
        ok = [h for h in hits if norm(lead) in norm(h["artist"]["name"]) or norm(h["artist"]["name"]) in norm(artist)]
        exact = [h for h in ok if norm(h["title"]) == norm(title)] or [h for h in ok if norm(h["title"]).startswith(norm(title))]
        if exact:
            a = exact[0]
            return {"url": a["cover_xl"], "source": a["link"], "credit": "cover via Deezer"}
    raise LookupError(f"no Deezer album {title!r} by {artist!r}")


def pinned_url(query):
    url, source, credit = query.split("|")
    return {"url": url, "source": source, "credit": credit}


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
        credit = ", ".join(x for x in (f"photo: {artist}" if artist else "", "public domain" if licence == "PD" else licence) if x) or "image via Wikipedia"
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
            hit = {"book": open_library, "olid": open_library_pinned, "wiki": wikipedia, "file": wiki_file,
                   "anilist": anilist, "tvmaze": tvmaze,
                   "tvperson": tvperson, "deezer": deezer, "album": album, "url": pinned_url}[kind](query)
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
