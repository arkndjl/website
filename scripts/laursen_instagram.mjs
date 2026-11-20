// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// @laursen_111 Instagram through the official Instagram API with Instagram Login (graph.instagram.com, free).
// Needs secret IG_TOKEN: a long-lived Instagram user token for the professional (Creator/Business) account,
// scopes instagram_business_basic + instagram_business_manage_insights. Long-lived tokens last 60 days; this
// refreshes it once a day and, when Meta hands back a new string and IG_SECRETS_PAT (fine-grained PAT,
// repo Secrets: read and write) is set, stores it back as IG_TOKEN, so it never lapses. No token: returns null.
// Per run: followers, post count, every post's likes/comments, views on the newest 25 (all posts once a day).
import { execFileSync } from 'child_process';
const G = 'https://graph.instagram.com', V = `${G}/v23.0`, DAY = 864e5;
async function j(u) { try { const r = await fetch(u); const b = await r.json(); return r.ok ? b : { error: b?.error?.message || r.status }; } catch (e) { return { error: String(e) }; } }

export async function instagram(prev, now) {
  let tok = process.env.IG_TOKEN; if (!tok) return null;
  const meta = { ...(prev.igmeta || {}) };
  // daily refresh (Meta refuses tokens under 24h old; harmless)
  if (!meta.refreshed || now - meta.refreshed > DAY) {
    const r = await j(`${G}/refresh_access_token?grant_type=ig_refresh_token&access_token=${encodeURIComponent(tok)}`);
    if (r.access_token) { meta.refreshed = now; meta.exp = now + (r.expires_in || 0) * 1e3;
      if (r.access_token !== tok) { if (process.env.IG_SECRETS_PAT && process.env.GITHUB_REPOSITORY) {
          try { execFileSync('gh', ['secret', 'set', 'IG_TOKEN', '-R', process.env.GITHUB_REPOSITORY], { input: r.access_token, env: { ...process.env, GH_TOKEN: process.env.IG_SECRETS_PAT }, stdio: ['pipe', 'ignore', 'pipe'] }); meta.saved = now; }
          catch (e) { console.log('ig: could not store refreshed token:', String(e.stderr || e).slice(0, 200)); } }
        tok = r.access_token; } }
    else console.log('ig refresh:', r.error);
  }
  const q = s => `${s}${s.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(tok)}`;
  const me = await j(q(`${V}/me?fields=user_id,username,followers_count,follows_count,media_count`));
  if (me.error || me.followers_count == null) { console.log('ig:', me.error); return { meta, ok: false }; }
  // every post (paged), likes + comments come with the list
  const list = []; let u = q(`${V}/me/media?fields=id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count&limit=50`);
  for (let i = 0; u && i < 20; i++) { const r = await j(u); if (r.error || !r.data) break; list.push(...r.data); u = r.paging?.next || null; }
  const posts = { ...(prev.igm || {}) }, full = !meta.fullv || now - meta.fullv > DAY;
  list.sort((a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp));
  for (const [i, m] of list.entries()) {
    const o = posts[m.id] || { v: [] };
    let views = null;
    if (i < 25 || full) { const r = await j(q(`${V}/${m.id}/insights?metric=views`)); views = r?.data?.[0]?.values?.[0]?.value ?? r?.data?.[0]?.total_value?.value ?? null; }
    const lastV = o.v.length ? o.v[o.v.length - 1][1] : null;
    const snaps = views == null || views === lastV ? o.v : [...o.v, [now, views]];
    posts[m.id] = { cap: (m.caption || '').split('\n')[0].slice(0, 140), pub: Date.parse(m.timestamp), type: m.media_product_type === 'REELS' ? 'reel' : m.media_type === 'CAROUSEL_ALBUM' ? 'carousel' : m.media_type === 'VIDEO' ? 'video' : 'photo',
      url: m.permalink, l: m.like_count ?? o.l ?? null, c: m.comments_count ?? o.c ?? null, v: snaps.length > 40 ? [snaps[0], ...snaps.slice(-39)] : snaps };
  }
  if (full && list.length) meta.fullv = now;
  if (list.length) meta.opened = new Date(Math.min(...list.map(m => Date.parse(m.timestamp)))).toISOString().slice(0, 10);   // oldest post stands in for the join date
  const vals = Object.values(posts), sum = f => vals.reduce((s, p) => s + (f(p) || 0), 0);
  return { ok: true, meta, posts, followers: me.followers_count, following: me.follows_count ?? null, media: me.media_count ?? null,
    likes: sum(p => p.l), comments: sum(p => p.c), views: sum(p => p.v.length ? p.v[p.v.length - 1][1] : 0) };
}

// plan.ig for instagram.exe: tiles + posts oldest to newest with a trailing-5 view line
export function igPlan(posts, cur) {
  const ps = Object.entries(posts || {}).map(([id, p]) => ({ id, ...p, views: p.v.length ? p.v[p.v.length - 1][1] : 0 })).sort((a, b) => a.pub - b.pub);
  if (!ps.length) return null;
  const last = ps.slice(-10), r = x => Math.round(x), med = a => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
  const vids = ps.slice(-40).map((p, i, a) => { const w = a.slice(Math.max(0, i - 4), i + 1); return { id: p.id, cap: p.cap, pub: p.pub, type: p.type, url: p.url, views: p.views, l: p.l, c: p.c, r5: w.length === 5 ? r(w.reduce((s, x) => s + x.views, 0) / 5) : null }; });
  const er = cur.ig ? Math.round(1000 * last.reduce((s, p) => s + (p.l || 0) + (p.c || 0), 0) / last.length / cur.ig) / 10 : null;
  return { posts: cur.igp ?? ps.length, likes: cur.igl, views: cur.igv, lpp: Math.round(10 * cur.igl / Math.max(1, ps.length)) / 10,
    l10: { n: last.length, sum: last.reduce((s, p) => s + p.views, 0), avg: r(last.reduce((s, p) => s + p.views, 0) / last.length), med: r(med(last.map(p => p.views))), likes: r(last.reduce((s, p) => s + (p.l || 0), 0) / last.length) }, er, vids };
}
