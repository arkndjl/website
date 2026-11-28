#!/usr/bin/env python3
# Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
"""articleGFX check: every post's [gfx] front matter must come from the article. keys = [one comma list a section, in
section order] (Noah, Nov 28: the card lists each section's key words, not lines): each key word must be in its own
section (any case). quote = [excerpts] (older form) and each line of post = "lines" must be in the article word for word
(a post line may also be the title), and the post must fit X's 280 characters with the link counted as 23. The card itself is buildArticle in
assets/js/gfx.js (button in layouts/_default/single.html); a post with no [gfx] block uses its first sentence.

    python3 scripts/article_gfx.py          # list problems, exit 1 on any
    python3 scripts/article_gfx.py --test   # the checker's own cases
"""
import os, re, sys, tomllib

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
POSTS = os.path.join(ROOT, 'content', 'posts')


def plain(md):
    """the article's text as a reader sees it: no shortcodes, link targets, emphasis or heading marks"""
    md = re.sub(r'\{\{[<%].*?[>%]\}\}', ' ', md, flags=re.S)
    md = re.sub(r'!\[[^\]]*\]\([^)]*\)', ' ', md)
    md = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', md)
    md = re.sub(r'(\*\*|__|\*|`)', '', md)
    md = re.sub(r'^\s{0,3}(#+|>|[-*+]|\d+\.)\s+', '', md, flags=re.M)
    md = md.replace('’', "'").replace('“', '"').replace('”', '"')
    return re.sub(r'\s+', ' ', md)


def norm(t):
    return re.sub(r'\s+', ' ', t.replace('’', "'").replace('“', '"').replace('”', '"')).strip()


def x_len(text):
    return len(re.sub(r'https?://\S+', 'x' * 23, text))


def problems_of(front, body, name='post'):
    g = front.get('gfx') or {}
    out, txt, title = [], plain(body), norm(front.get('title', ''))
    for q in g.get('quote') or []:
        if norm(q) not in txt:
            out.append(f'{name}: gfx.quote is not in the article word for word: {q[:70]!r}')
    secs = re.split(r'^##\s+.*$', body, flags=re.M)[1:]
    keys = g.get('keys') or []
    if len(keys) > len(secs):
        out.append(f'{name}: gfx.keys has {len(keys)} lists for {len(secs)} sections')
    for i, ks in enumerate(keys[:len(secs)]):
        st = plain(secs[i]).lower()
        for k in [k.strip() for k in ks.split(',') if k.strip()]:
            if k.lower() not in st:
                out.append(f'{name}: gfx.keys word {k!r} is not in section {i + 1}')
    post = g.get('post') or ''
    for line in [l for l in re.split(r'\n\s*\n', post) if l.strip()]:
        if norm(line) != title and norm(line) not in txt:
            out.append(f'{name}: gfx.post line is not the title or in the article word for word: {line[:70]!r}')
    if post and x_len(post.strip() + '\n\n' + 'https://arkndjl.net/') > 280:
        out.append(f'{name}: gfx.post is over 280 characters with the link')
    return out


def problems():
    out = []
    for f in sorted(os.listdir(POSTS)):
        if not f.endswith('.md'):
            continue
        s = open(os.path.join(POSTS, f), encoding='utf-8').read()
        m = re.match(r'\+\+\+\n(.*?)\n\+\+\+\n(.*)', s, re.S)
        if not m:
            continue
        try:
            front = tomllib.loads(m.group(1))
        except tomllib.TOMLDecodeError as e:
            out.append(f'{f}: front matter does not parse ({e})')
            continue
        out += problems_of(front, m.group(2), f)
    return out


def test():
    body = 'Friction is a big part of life, and my designs have **friction**. See [Process](/process/).\n\n{{< postchart "x" >}}'
    ok = {'title': 'T: A', 'gfx': {'quote': ['Friction is a big part of life, and my designs have friction.'], 'post': 'T: A\n\nSee Process.'}}
    assert problems_of(ok, body) == [], problems_of(ok, body)
    bad = {'title': 'T', 'gfx': {'quote': ['Friction is good.'], 'post': 'Something I never wrote.'}}
    assert len(problems_of(bad, body)) == 2
    secs = '## A\n\nFriction and trust.\n\n## B\n\nDense tables.'
    assert problems_of({'title': 'T', 'gfx': {'keys': ['friction, Trust', 'dense tables']}}, secs) == []
    assert len(problems_of({'title': 'T', 'gfx': {'keys': ['dense tables', 'x', 'y']}}, secs)) == 3
    long = {'title': 'T', 'gfx': {'post': 'Friction ' * 40}}
    assert any('280' in p for p in problems_of(long, body))
    assert x_len('a https://arkndjl.net/posts/very-long-slug-here/') == 25
    print('article_gfx: tests ok')


if __name__ == '__main__':
    if '--test' in sys.argv[1:]:
        test()
        sys.exit(0)
    P = problems()
    for p in P:
        print('FAIL:', p)
    print(f'article_gfx: {"FAILED" if P else "ok"}')
    sys.exit(1 if P else 0)
