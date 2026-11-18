#!/usr/bin/env node
// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// LAURSEN_111 follower counts over time: Twitch (decapi.me, no key), YouTube (channel page subscriber line),
// TikTok (profile page followerCount), X (api.fxtwitter.com, no key). One reading per run, kept when any count moved, plus one a day so a
// flat stretch still draws. Writes data/laursen_socials.json. A source that fails keeps its last value (null when never read).
import fs from 'fs';
import path from 'path';
import { buildGoals } from './social_goals.mjs';
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'data', 'laursen_socials.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36';
const prev = (() => { try { return JSON.parse(fs.readFileSync(OUT, 'utf8')); } catch { return { series: [] }; } })();
async function get(u, ua = UA) { try { const r = await fetch(u, { headers: { 'User-Agent': ua, 'Accept-Language': 'en-US,en;q=0.9' } }); return r.ok ? await r.text() : null; } catch { return null; } }
const num = s => { if (s == null) return null; const m = /^([\d.,]+)\s*([KkMm])?$/.exec(String(s).trim()); if (!m) return null; const v = parseFloat(m[1].replace(/,/g, '')); return Math.round(v * (m[2] ? (/k/i.test(m[2]) ? 1e3 : 1e6) : 1)); };
const twitch = num(await get('https://decapi.me/twitch/followcount/laursen_111'));
const ytHtml = await get('https://www.youtube.com/@LAURSEN_111');
const youtube = ytHtml ? num((/([\d.,]+[KkMm]?) subscribers/.exec(ytHtml) || [])[1]) : null;
const ttHtml = await get('https://www.tiktok.com/@laursen_111');
const tiktok = ttHtml ? num((/"followerCount":(\d+)/.exec(ttHtml) || [])[1]) : null;
const ttVideos = ttHtml ? num((/"videoCount":(\d+)/.exec(ttHtml) || [])[1]) : null, ttHearts = ttHtml ? num((/"heartCount":(\d+)/.exec(ttHtml) || [])[1]) : null;
const xj = await get('https://api.fxtwitter.com/LAURSEN_111', 'arkndjl.net') ?? await get('https://api.fxtwitter.com/laursen_111', 'arkndjl.net');   // retry once: fxtwitter drops the odd CI run
const x = (() => { try { return JSON.parse(xj).user.followers ?? null; } catch { return null; } })();
const last = prev.series[prev.series.length - 1] || {};
const now = Date.now(), cur = { t: now, twitch: twitch ?? last.twitch ?? null, youtube: youtube ?? last.youtube ?? null, tiktok: tiktok ?? last.tiktok ?? null, x: x ?? last.x ?? null, ttv: ttVideos ?? last.ttv ?? null, tth: ttHearts ?? last.tth ?? null };
const moved = ['twitch', 'youtube', 'tiktok', 'x', 'ttv', 'tth'].some(k => cur[k] !== (last[k] ?? null)), stale = !last.t || now - last.t > 864e5;
const status = { twitch: twitch != null, youtube: youtube != null, tiktok: tiktok != null, x: x != null };
console.log('socials:', JSON.stringify({ twitch, youtube, tiktok, x }));
const series = moved || stale ? [...prev.series, cur].slice(-3000) : prev.series;

const OPENED = { twitch: '2023-10-31', youtube: '2023-11-10', tiktok: '2023-11-11', x: '2024-08-11' };   // decapi /twitch/creation, YouTube about, TikTok createTime, fxtwitter joined
const { goals, hist } = buildGoals(series, prev.hist, OPENED);
console.log('goals:', JSON.stringify(goals));
const { yt, tw, plan } = await import('./laursen_social_plan.mjs').then(m => m.build({ prev, now, series, goals, cur, get, hist }));
const body = { status, goals, hist, series, yt, tw, plan };
const strip = o => JSON.stringify({ ...o, asof: undefined });
if (strip(body) === strip(prev) && !stale) process.exit(0);
fs.writeFileSync(OUT, JSON.stringify({ asof: new Date(now).toISOString(), ...body }, null, 1) + '\n');
