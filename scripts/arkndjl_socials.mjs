#!/usr/bin/env node
// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// @ARKNDJL social data for the about/contact page (social_data.exe, x.exe, youtube.exe, insights.exe), the same
// pattern as LAURSEN_111's (scripts/laursen_socials.mjs). X: followers + the latest ~20 posts with views and
// engagement from api.fxtwitter.com (no key). YouTube: subscribers from the channel page, uploads from the channel
// feed (no key; YOUTUBE_API_KEY adds the full upload list with likes, comments and length). One reading per run,
// kept when a count moved plus one a day. Writes data/arkndjl_socials.json; a source that fails keeps its last value.
import fs from 'fs';
import path from 'path';
import { buildGoals } from './social_goals.mjs';
import { youtube, et, median, r1, r2, DAYS, BLOCKS } from './laursen_social_plan.mjs';
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'data', 'arkndjl_socials.json');
const X_USER = 'ARKNDJL', YT_HANDLE = 'ARKNDJL', YT_CH = 'UCQycF-Vk740tEVkBthOgLdg';
const OPENED = { x: '2024-08-20', youtube: '2025-02-21' };   // fxtwitter joined, YouTube about "Joined"
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36';
const DAY = 864e5, MIN_AGE = 3, X_AGE = 1, K = 3, X10 = 10;   // X posts get most of their views in a day; YouTube uploads 3
const prev = (() => { try { return JSON.parse(fs.readFileSync(OUT, 'utf8')); } catch { return { series: [] }; } })();
async function get(u, ua = UA) { try { const r = await fetch(u, { headers: { 'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9' } }); return r.ok ? await r.text() : null; } catch { return null; } }
const num = s => { if (s == null) return null; const m = /^([\d.,]+)\s*([KkMm])?$/.exec(String(s).trim()); if (!m) return null; const v = parseFloat(m[1].replace(/,/g, '')); return Math.round(v * (m[2] ? (/k/i.test(m[2]) ? 1e3 : 1e6) : 1)); };
const pj = s => { try { return JSON.parse(s); } catch { return null; } };
const sum = a => a.reduce((x, y) => x + y, 0), fmt = v => v == null ? '—' : Math.round(v).toLocaleString('en-US');

// ---- counts
const now = Date.now();
const xu = pj(await get(`https://api.fxtwitter.com/${X_USER}`, 'arkndjl.net'))?.user || null;
const x = xu?.followers ?? null, xn = xu?.tweets ?? null;
const ytHtml = await get(`https://www.youtube.com/@${YT_HANDLE}`);
const yts = ytHtml ? num((/([\d.,]+[KkMm]?) subscribers/.exec(ytHtml) || [])[1]) : null;
const last = prev.series[prev.series.length - 1] || {};
const cur = { t: now, x: x ?? last.x ?? null, youtube: yts ?? last.youtube ?? null, xn: xn ?? last.xn ?? null };
const moved = ['x', 'youtube', 'xn'].some(k => cur[k] !== (last[k] ?? null)), stale = !last.t || now - last.t > DAY;
const status = { x: x != null, youtube: yts != null };
console.log('socials:', JSON.stringify({ x, youtube: yts, xn }));
const series = moved || stale ? [...prev.series, cur].slice(-3000) : prev.series;
const { goals, hist } = buildGoals(series, prev.hist, OPENED);

// ---- X posts: his own posts (no reposts), views snapshotted per run; replies to his own posts are thread parts
const xp = { ...(prev.xp || {}) };
const st = pj(await get(`https://api.fxtwitter.com/2/profile/${X_USER}/statuses`, 'arkndjl.net'));
let xOk = false;
for (const p of st?.results || []) {
  if (p.reposted_by || (p.author?.screen_name || '').toLowerCase() !== X_USER.toLowerCase() || p.views == null) continue;
  xOk = true;
  const media = ((p.media || {}).all || []).map(m => m.type), kind = p.replying_to ? 'reply' : p.quote ? 'quote' : media.length ? (media.includes('video') || media.includes('gif') ? 'video' : 'photo') : 'text';
  const o = xp[p.id] || { v: [] }, lastV = o.v.length ? o.v[o.v.length - 1][1] : null, snaps = lastV === p.views ? o.v : [...o.v, [now, p.views]];
  xp[p.id] = { text: (p.text || '').replace(/\s+/g, ' ').slice(0, 140), pub: p.created_timestamp * 1e3, kind, likes: p.likes || 0, reposts: p.reposts || 0, replies: p.replies || 0, quotes: p.quotes || 0, bookmarks: p.bookmarks || 0,
    v: snaps.length > 40 ? [snaps[0], ...snaps.slice(-39)] : snaps };
}
// keep the newest 600
const xKeep = Object.entries(xp).sort((a, b) => b[1].pub - a[1].pub).slice(0, 600); for (const k of Object.keys(xp)) delete xp[k]; for (const [k, v] of xKeep) xp[k] = v;

const { yt, src: ytSrc } = await youtube(prev, now, get, YT_CH);

// ---- read helpers: slot strength = mean log views shrunk toward the account's (K posts of prior weight), shown as views
const lg = v => Math.log(1 + v);
function slots(rows) {
  const base = rows.length ? sum(rows.map(u => lg(u.views))) / rows.length : 0, shr = a => Math.exp((sum(a.map(lg)) + K * base) / (a.length + K)) - 1;
  const by = f => { const m = {}; for (const r of rows) (m[f(r)] = m[f(r)] || []).push(r.views); return m; };
  const byDay = by(u => et(u.pub).d), byBlock = by(u => et(u.pub).b);
  const best = (m, labels) => { let b = null; for (const [k, a] of Object.entries(m)) { if (a.length < 2) continue; const v = shr(a); if (!b || v > b.med) b = { k: labels[k], med: v, n: a.length }; } return b; };
  const grid = DAYS.map(() => BLOCKS.map(() => [])); for (const r of rows) { const w = et(r.pub); grid[w.d][w.b].push(r.views); }
  return { base: Math.exp(base) - 1, grid: grid.map(r => r.map(c => ({ n: c.length, med: median(c) }))),
    days: DAYS.map((d, i) => ({ d, n: (byDay[i] || []).length, med: median(byDay[i] || []), x: byDay[i] ? Math.round(shr(byDay[i])) : null })),
    bd: best(byDay, DAYS), bb: best(byBlock, BLOCKS) };
}
// views gained per day across tracked posts, and followers gained over the same span per 1,000 of them
function velocity(rows, net) {
  let dv = 0, dt = 0; for (const u of rows) if (u.v.length > 1) { const a = u.v[0], b = u.v[u.v.length - 1]; dv += b[1] - a[1]; dt = Math.max(dt, (b[0] - a[0]) / DAY); }
  const vpd = dt >= 0.5 ? dv / dt : null, sr = series.filter(s => s[net] != null), sp = sr.length > 1 ? (sr.at(-1).t - sr[0].t) / DAY : 0;
  const perK = vpd && sp >= 3 && dv > 0 ? (sr.at(-1)[net] - sr[0][net]) / (vpd * sp) * 1e3 : null;
  return { vpd, perK };
}
const rollOf = a => { const l = a.slice(-X10).map(u => u.views); return l.length ? { n: l.length, sum: sum(l), avg: Math.round(sum(l) / l.length), med: median(l) } : null; };
const trail = (a, id) => { const i = a.findIndex(u => u.id === id); if (i < 0) return null; const w = a.slice(Math.max(0, i - 4), i + 1).map(u => u.views); return w.length >= 3 ? Math.round(sum(w) / w.length) : null; };
const plan = { src: { x: xOk ? 'fxtwitter' : null, yt: ytSrc }, ideas: [] }, I = plan.ideas, pend = (k, d) => I.push({ k, v: null, d, n: null, wait: true });

// ---- X
const posts = Object.entries(xp).map(([id, o]) => ({ id, ...o, views: o.v.length ? o.v[o.v.length - 1][1] : 0, age: (now - o.pub) / DAY })).sort((a, b) => a.pub - b.pub);
const top = posts.filter(u => u.kind !== 'reply'), xOld = top.filter(u => u.age >= X_AGE), xs = slots(xOld);
const eng = u => u.likes + u.reposts + u.replies + u.quotes + u.bookmarks;
const er = rows => { const v = sum(rows.map(u => u.views)); return v ? sum(rows.map(eng)) / v * 100 : null; };
const kinds = {}; for (const u of xOld) (kinds[u.kind] = kinds[u.kind] || []).push(u.views);
const xGaps = top.slice(1).map((u, i) => (u.pub - top[i].pub) / DAY).filter(g => g > 1 / 24), xv = velocity(posts, 'x');
const xSpan = top.length > 1 ? Math.max(1, (now - top[0].pub) / DAY) : null;
plan.x = {
  n: posts.length, top: top.length, nOld: xOld.length, median: median(xOld.map(u => u.views)), er: r2(er(xOld)), perDay: xSpan ? r1(top.length / xSpan) : null,
  last30: top.filter(u => now - u.pub < 30 * DAY).length, gap: r1(median(xGaps)), vpd: r1(xv.vpd), fpk: r2(xv.perK), base: Math.round(xs.base),
  kinds: Object.fromEntries(['text', 'photo', 'video', 'quote'].map(k => [k, { n: (kinds[k] || []).length, med: median(kinds[k] || []) }])),
  grid: xs.grid, days: xs.days,
  posts: posts.slice(-40).map(u => ({ id: u.id, text: u.text, pub: u.pub, kind: u.kind, views: u.views, likes: u.likes, reposts: u.reposts, replies: u.replies, er: u.views ? r1(eng(u) / u.views * 100) : null })),
};
for (const u of plan.x.posts) u.r5 = u.kind === 'reply' ? null : trail(top, u.id);

// ---- YouTube
const ups = Object.entries(yt).map(([id, o]) => ({ id, ...o, views: o.v.length ? o.v[o.v.length - 1][1] : 0, age: (now - o.pub) / DAY })).sort((a, b) => a.pub - b.pub);
const yOld = ups.filter(u => u.age >= MIN_AGE), ys = slots(yOld), yv = velocity(ups, 'youtube');
const shorts = yOld.filter(u => u.short).map(u => u.views), longs = yOld.filter(u => !u.short).map(u => u.views);
const yGaps = ups.slice(1).map((u, i) => (u.pub - ups[i].pub) / DAY).filter(g => g > 1 / 24);
plan.yt = {
  n: ups.length, nOld: yOld.length, median: median(yOld.map(u => u.views)), shorts: { n: shorts.length, med: median(shorts) }, long: { n: longs.length, med: median(longs) },
  last30: ups.filter(u => now - u.pub < 30 * DAY).length, gap: r1(median(yGaps)), vpd: r1(yv.vpd), subsPerK: r2(yv.perK),
  likeRate: r2(sum(yOld.map(u => u.likes || 0)) / Math.max(1, sum(yOld.map(u => u.views))) * 100), grid: ys.grid, base: Math.round(ys.base), days: ys.days,
  ups: ups.slice(-40).map(u => ({ id: u.id, title: u.title, pub: u.pub, short: u.short, views: u.views, likes: u.likes ?? null, comments: u.comments ?? null, age: r1(u.age), et: et(u.pub) })),
};
for (const u of plan.yt.ups) u.r5 = trail(ups, u.id);
plan.roll = { x: X10, xp: rollOf(top), yt: rollOf(ups), ytl: 'uploads' };

// ---- insights: data-backed calls with their sample size; pending ones say what they wait on
if (xs.bd || xs.bb) I.push({ k: 'X post slot', v: [xs.bd && xs.bd.k, xs.bb && `${xs.bb.k} ET`].filter(Boolean).join(' · '), d: `${fmt((xs.bd || xs.bb).med)} expected views vs ${fmt(xs.base)}`, n: (xs.bd || xs.bb).n });
else pend('X post slot', `at 2 posts in a slot, 1+ day old (${xOld.length} posts)`);
const km = Object.entries(plan.x.kinds).filter(([, v]) => v.n >= 2).sort((a, b) => b[1].med - a[1].med);
if (km.length >= 2) I.push({ k: 'X post type', v: km[0][0], d: km.map(([k, v]) => `${k} ${fmt(v.med)}`).join(' · '), n: sum(km.map(([, v]) => v.n)) });
else pend('X post type', `at 2 posts of two types, 1+ day old (${xOld.length})`);
if (plan.x.er != null) I.push({ k: 'X engagement', v: `${plan.x.er}%`, d: 'likes, reposts, replies, quotes, bookmarks per view', n: xOld.length });
if (xGaps.length >= 3) I.push({ k: 'X posting', v: `${plan.x.perDay} / day`, d: `${plan.x.last30} in 30 days`, n: top.length });
if (xv.perK != null) { I.push({ k: 'X follows / 1k views', v: `${r2(xv.perK)}`, d: `${fmt(xv.vpd)} views / day on tracked posts`, n: posts.length });
  if (goals.x?.next && xv.perK > 0) I.push({ k: `X ${fmt(goals.x.next.goal)}`, v: `${fmt((goals.x.next.goal - cur.x) / xv.perK * 1e3)} views`, d: `${r2(xv.perK)} follows / 1k views`, n: posts.length }); }
else pend('X follows / 1k views', 'at 3 days of X view history');
if (shorts.length && longs.length) I.push({ k: 'Shorts vs long', v: median(shorts) >= median(longs) ? 'Shorts' : 'long', d: `${fmt(median(shorts))} vs ${fmt(median(longs))} median views`, n: shorts.length + longs.length });
if (ys.bd) I.push({ k: 'YouTube post day', v: ys.bd.k, d: `${fmt(ys.bd.med)} expected views vs ${fmt(ys.base)}`, n: ys.bd.n });
if (yv.perK != null && goals.youtube?.next && yv.perK > 0) I.push({ k: `YouTube ${goals.youtube.next.goal}`, v: `${fmt((goals.youtube.next.goal - cur.youtube) / yv.perK * 1e3)} views`, d: `${r2(yv.perK)} subs / 1k views`, n: ups.length });
else if (yv.perK == null) pend('Subs / 1k views', 'at 3 days of YouTube view history');
const vs = (a, lbl, unit) => { const c10 = a.slice(-X10).map(u => u.views), p10 = a.slice(-2 * X10, -X10).map(u => u.views);
  if (p10.length >= 5) { const c = sum(c10) / c10.length, q = sum(p10) / p10.length, ch = (c / Math.max(1, q) - 1) * 100;
    I.push({ k: `${lbl} L10 trend`, v: `${ch >= 0 ? '+' : ''}${Math.round(ch)}%`, d: `${fmt(c)} vs ${fmt(q)} avg, prior ${p10.length}`, n: c10.length + p10.length }); }
  else pend(`${lbl} L10 trend`, `at ${X10 + 5} ${unit} tracked (${a.length})`); };
vs(top, 'X', 'posts'); vs(ups, 'YouTube', 'uploads');
for (const [k, nm] of Object.entries({ x: 'X', youtube: 'YouTube' })) { const g = goals[k]; if (!g) continue;
  if (g.tracked >= 14) { const t = (g.rate * (30 + g.tracked) - g.prior * 30) / Math.max(1, g.tracked);
    I.push({ k: `${nm} pace`, v: `${t >= g.prior ? '+' : ''}${r1(t - g.prior)}/mo vs lifetime`, d: `${r1(t)}/mo tracked · ${g.prior}/mo lifetime`, n: Math.round(g.tracked) }); }
  else pend(`${nm} pace`, `at 14 days tracked (${r1(g.tracked)})`); }
const res = Object.values(hist).flatMap(h => (h.dated || []).filter(d => d.done)), msHit = Object.values(hist).flatMap(h => (h.ms || []).filter(m => m.hit && !m.est && m.ahead != null));
if (res.length >= 3) { const hit = res.filter(d => d.hit).length, exp = sum(res.map(d => d.p)) / res.length;
  I.push({ k: 'Goal calibration', v: `${hit} of ${res.length} hit`, d: `${Math.round(hit / res.length * 100)}% hit vs ${Math.round(exp)}% forecast`, n: res.length }); }
else pend('Goal calibration', `at 3 dated goals resolved (${res.length})`);
if (msHit.length) { const a = sum(msHit.map(m => m.ahead)) / msHit.length; I.push({ k: 'Milestones vs pace', v: `${a >= 0 ? '+' : ''}${Math.round(a)} days`, d: `mean over ${msHit.length} tracked milestone${msHit.length > 1 ? 's' : ''}`, n: msHit.length }); }
else pend('Milestones vs pace', 'at the first tracked milestone');
const rh = prev.plan?.roll_t || [], lr = rh[rh.length - 1], pt = [now, plan.roll.yt?.sum ?? null, plan.roll.xp?.sum ?? null];   // [t, YouTube L10, X L10]
plan.roll_t = !lr || lr[1] !== pt[1] || lr[2] !== pt[2] || now - lr[0] > DAY ? [...rh, pt].slice(-1500) : rh;

const body = { status, goals, hist, series, xp, yt, plan };
const strip = o => JSON.stringify({ ...o, asof: undefined });
if (strip(body) === strip(prev) && !stale) process.exit(0);
fs.writeFileSync(OUT, JSON.stringify({ asof: new Date(now).toISOString(), ...body }, null, 1) + '\n');
