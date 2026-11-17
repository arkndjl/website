// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// LAURSEN_111 social section: YouTube uploads (channel RSS, no key; YOUTUBE_API_KEY adds the full upload list with
// likes, comments and length), Twitch streams (decapi.me live viewer samples, no key; TWITCH_CLIENT_ID +
// TWITCH_CLIENT_SECRET add Helix stream start times and the VOD archive), and the schedule / growth read built
// from them. Called by scripts/laursen_socials.mjs, which writes everything to data/laursen_socials.json.
const YT_CH = 'UC6FmXC9DL1Rc4ATAVPeBYtQ', TW_LOGIN = 'laursen_111';
const PRIOR = 30, DAY = 864e5, HR = 36e5, MIN_AGE = 3;           // uploads younger than 3 days are left out of timing splits
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const BLOCKS = ['12a', '4a', '8a', '12p', '4p', '8p']; // 4-hour ET blocks
const etf = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', hourCycle: 'h23' });
export function et(t) { const p = Object.fromEntries(etf.formatToParts(new Date(t)).map(x => [x.type, x.value])); const h = +p.hour % 24; return { d: DAYS.indexOf(p.weekday), h, b: Math.floor(h / 4) }; }
const median = a => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const r1 = v => v == null || !isFinite(v) ? null : Math.round(v * 10) / 10, r2 = v => v == null || !isFinite(v) ? null : Math.round(v * 100) / 100;
const isoDur = s => { const m = /PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/.exec(s || ''); return m ? (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0) : null; };
const twDur = s => { const m = /(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?/.exec(s || ''); return m ? (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0) : null; };
async function json(u, opt = {}) { try { const r = await fetch(u, opt); return r.ok ? await r.json() : null; } catch { return null; } }

async function youtube(prev, now, get) {
  const yt = { ...(prev.yt || {}) }; let src = null;
  const seen = {};
  const key = process.env.YOUTUBE_API_KEY;
  if (key) {
    const ids = []; let tok = '';
    for (let i = 0; i < 10; i++) {
      const j = await json(`https://www.googleapis.com/youtube/v3/playlistItems?part=contentDetails&maxResults=50&playlistId=UU${YT_CH.slice(2)}&key=${key}${tok ? '&pageToken=' + tok : ''}`);
      if (!j) break; for (const it of j.items || []) ids.push(it.contentDetails.videoId); if (!(tok = j.nextPageToken)) break;
    }
    for (let i = 0; i < ids.length; i += 50) {
      const j = await json(`https://www.googleapis.com/youtube/v3/videos?part=snippet,statistics,contentDetails&id=${ids.slice(i, i + 50).join(',')}&key=${key}`);
      for (const v of j?.items || []) { const dur = isoDur(v.contentDetails.duration);
        seen[v.id] = { title: v.snippet.title, pub: Date.parse(v.snippet.publishedAt), short: dur != null && dur <= 180, dur, views: +v.statistics.viewCount || 0, likes: +v.statistics.likeCount || 0, comments: +v.statistics.commentCount || 0 }; }
    }
    if (Object.keys(seen).length) src = 'api';
  }
  if (!src) {
    const x = await get(`https://www.youtube.com/feeds/videos.xml?channel_id=${YT_CH}`);
    for (const e of (x || '').split('<entry>').slice(1)) {
      const id = (/<yt:videoId>([^<]+)/.exec(e) || [])[1]; if (!id) continue;
      const dec = s => s.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
      seen[id] = { title: dec((/<title>([^<]*)/.exec(e) || [])[1] || ''), pub: Date.parse((/<published>([^<]+)/.exec(e) || [])[1]), short: /\/shorts\//.test(e),
        views: +((/<media:statistics views="(\d+)"/.exec(e) || [])[1] || 0), likes: +((/<media:starRating count="(\d+)"/.exec(e) || [])[1] || 0) };
    }
    if (Object.keys(seen).length) src = 'rss';
  }
  for (const [id, v] of Object.entries(seen)) {
    const o = yt[id] || { v: [] }, lastV = o.v.length ? o.v[o.v.length - 1][1] : null;
    const snaps = lastV === v.views ? o.v : [...o.v, [now, v.views]];
    yt[id] = { ...o, ...v, views: undefined, v: snaps.length > 40 ? [snaps[0], ...snaps.slice(-39)] : snaps };
  }
  for (const o of Object.values(yt)) delete o.views;
  return { yt, src };
}

async function twitch(prev, now, get, follows) {
  const tw = { live: null, sessions: [], vods: [], ...(prev.tw || {}) };
  let live = null, src = 'decapi';
  const id = process.env.TWITCH_CLIENT_ID, sec = process.env.TWITCH_CLIENT_SECRET;
  if (id && sec) {
    const tok = await json(`https://id.twitch.tv/oauth2/token?client_id=${id}&client_secret=${sec}&grant_type=client_credentials`, { method: 'POST' });
    if (tok?.access_token) {
      const H = { headers: { 'Client-Id': id, Authorization: `Bearer ${tok.access_token}` } };
      const u = (await json(`https://api.twitch.tv/helix/users?login=${TW_LOGIN}`, H))?.data?.[0];
      if (u) {
        src = 'helix';
        const st = (await json(`https://api.twitch.tv/helix/streams?user_id=${u.id}`, H))?.data?.[0];
        if (st) live = { s: Date.parse(st.started_at), v: st.viewer_count, g: st.game_name, title: st.title };
        const vd = (await json(`https://api.twitch.tv/helix/videos?user_id=${u.id}&type=archive&first=100`, H))?.data;
        if (vd?.length) { const byId = Object.fromEntries((tw.vods || []).map(v => [v.id, v]));
          for (const v of vd) byId[v.id] = { id: v.id, s: Date.parse(v.created_at), dur: twDur(v.duration), views: v.view_count, title: v.title };
          tw.vods = Object.values(byId).sort((a, b) => a.s - b.s).slice(-400); }
      }
    }
  }
  if (src === 'decapi') {
    const vc = (await get(`https://decapi.me/twitch/viewercount/${TW_LOGIN}`) || '').trim();
    if (/^\d+$/.test(vc)) live = { s: null, v: +vc, g: (await get(`https://decapi.me/twitch/game/${TW_LOGIN}`) || '').trim() || null };
  }
  if (live) {
    if (!tw.live) tw.live = { s: live.s || now, g: live.g, n: [], f0: follows };
    if (live.s && live.s < tw.live.s) tw.live.s = live.s;
    tw.live.n = [...tw.live.n, [now, live.v]].slice(-200); tw.live.g = live.g || tw.live.g;
  } else if (tw.live) {
    const L = tw.live, vs = L.n.map(x => x[1]), e = L.n.length ? L.n[L.n.length - 1][0] : L.s;
    tw.sessions = [...tw.sessions, { s: L.s, e, peak: Math.max(...vs), avg: r1(vs.reduce((a, b) => a + b, 0) / vs.length), n: vs.length, g: L.g, f: follows != null && L.f0 != null ? follows - L.f0 : null }].slice(-500);
    tw.live = null;
  }
  return { tw, src };
}

// TikTok creator embed (public, no key): latest ~10 videos with play counts. Post time from the id (top 32 bits = unix s).
async function tiktok(prev, now, get) {
  const tt = { ...(prev.tt || {}) };
  const h = await get('https://www.tiktok.com/embed/@laursen_111'); if (!h) return { tt, ok: false };
  const i = h.indexOf('"videoList":['); if (i < 0) return { tt, ok: false };
  let list = []; try { let d = 0, j = i + 12; for (; j < h.length; j++) { if (h[j] === '[') d++; else if (h[j] === ']' && --d === 0) break; } list = JSON.parse(h.slice(i + 12, j + 1)); } catch { return { tt, ok: false }; }
  for (const v of list) { if (!v.id || v.playCount == null) continue;
    const o = tt[v.id] || { v: [] }, lastV = o.v.length ? o.v[o.v.length - 1][1] : null, snaps = lastV === v.playCount ? o.v : [...o.v, [now, v.playCount]];
    tt[v.id] = { desc: (v.desc || '').slice(0, 140), pub: Number(BigInt(v.id) >> 32n) * 1e3, photo: !v.height, v: snaps.length > 40 ? [snaps[0], ...snaps.slice(-39)] : snaps }; }
  return { tt, ok: list.length > 0 };
}

// Hours of each stream: tracked sessions, plus archived VODs (Helix) that no tracked session overlaps.
function streams(tw) {
  const out = tw.sessions.map(s => ({ s: s.s, e: Math.max(s.e, s.s + 15 * 6e4), avg: s.avg, peak: s.peak, f: s.f, src: 'live' }));
  for (const v of tw.vods || []) if (v.dur && !out.some(o => Math.abs(o.s - v.s) < 2 * HR)) out.push({ s: v.s, e: v.s + v.dur * 1e3, views: v.views, src: 'vod' });
  return out.sort((a, b) => a.s - b.s);
}

export async function build({ prev, now, series, goals, cur, get, hist = {} }) {
  const { yt, src: ytSrc } = await youtube(prev, now, get);
  const { tw, src: twSrc } = await twitch(prev, now, get, cur.twitch);
  const { tt, ok: ttOk } = await tiktok(prev, now, get);
  const plan = { src: { yt: ytSrc, tw: twSrc, tt: ttOk ? 'embed' : null }, ideas: [] };

  // ---- YouTube: each upload's latest views; timing splits use uploads at least MIN_AGE days old
  const ups = Object.entries(yt).map(([id, o]) => ({ id, ...o, views: o.v.length ? o.v[o.v.length - 1][1] : 0, age: (now - o.pub) / DAY })).sort((a, b) => a.pub - b.pub);
  const old = ups.filter(u => u.age >= MIN_AGE);
  const grid = (rows, val) => { const g = DAYS.map(() => BLOCKS.map(() => [])); for (const r of rows) { const w = et(r.pub); g[w.d][w.b].push(val(r)); } return g; };
  const ytGrid = grid(old, u => u.views).map(r => r.map(c => ({ n: c.length, med: median(c) })));
  const split = (rows, key) => { const m = {}; for (const r of rows) (m[key(r)] = m[key(r)] || []).push(r.views); return m; };
  const byDay = split(old, u => et(u.pub).d), byBlock = split(old, u => et(u.pub).b);
  // slot strength: mean log views shrunk toward the channel's (k = 3 uploads of prior weight), shown as views
  const lg = v => Math.log(1 + v), allLog = old.length ? old.reduce((a, u) => a + lg(u.views), 0) / old.length : 0, K = 3;
  const shrunk = a => Math.exp((a.reduce((x, v) => x + lg(v), 0) + K * allLog) / (a.length + K)) - 1;
  const best = (m, labels) => { let b = null; for (const [k, a] of Object.entries(m)) { if (a.length < 2) continue; const md = shrunk(a); if (!b || md > b.med) b = { k: labels[k], med: md, n: a.length }; } return b; };
  const shorts = old.filter(u => u.short).map(u => u.views), longs = old.filter(u => !u.short).map(u => u.views);
  // batch = posted within an hour of another upload; solo = no other upload within 24 hours
  const near = (u, w) => ups.some(o => o.id !== u.id && Math.abs(o.pub - u.pub) < w);
  const batch = old.filter(u => near(u, HR)).map(u => u.views), solo = old.filter(u => !near(u, DAY)).map(u => u.views);
  const allMed = median(old.map(u => u.views));
  // view velocity: views added per day across all uploads between the first and latest snapshot that overlap
  let dv = 0, dt = 0; for (const u of ups) if (u.v.length > 1) { const a = u.v[0], b = u.v[u.v.length - 1]; dv += b[1] - a[1]; dt = Math.max(dt, (b[0] - a[0]) / DAY); }
  const vpd = dt >= 0.5 ? dv / dt : null;
  // subs per 1,000 views: subscriber gain over the same span as the view gain
  const ysr = series.filter(s => s.youtube != null), sp = ysr.length > 1 ? (ysr[ysr.length - 1].t - ysr[0].t) / DAY : 0;
  const subsPerK = vpd && sp >= 3 && dv > 0 ? (ysr[ysr.length - 1].youtube - ysr[0].youtube) / (vpd * sp) * 1e3 : null;
  const last30 = ups.filter(u => now - u.pub < 30 * DAY).length;
  const gaps = ups.slice(1).map((u, i) => (u.pub - ups[i].pub) / DAY).filter(g => g > 1 / 24);
  plan.yt = {
    n: ups.length, nOld: old.length, median: allMed, shorts: { n: shorts.length, med: median(shorts) }, long: { n: longs.length, med: median(longs) },
    batch: { n: batch.length, med: median(batch) }, solo: { n: solo.length, med: median(solo) }, last30, gap: r1(median(gaps)), vpd: r1(vpd), subsPerK: r2(subsPerK),
    likeRate: r2(old.reduce((a, u) => a + (u.likes || 0), 0) / Math.max(1, old.reduce((a, u) => a + u.views, 0)) * 100),
    grid: ytGrid, base: Math.round(Math.exp(allLog) - 1),
    days: DAYS.map((d, i) => ({ d, n: (byDay[i] || []).length, med: median(byDay[i] || []), x: byDay[i] ? Math.round(shrunk(byDay[i])) : null })), blocks: BLOCKS.map((b, i) => ({ b, n: (byBlock[i] || []).length, med: median(byBlock[i] || []), x: byBlock[i] ? Math.round(shrunk(byBlock[i])) : null })),
    ups: ups.slice(-40).map(u => ({ id: u.id, title: u.title, pub: u.pub, short: u.short, views: u.views, likes: u.likes ?? null, comments: u.comments ?? null, age: r1(u.age), et: et(u.pub) })),
  };

  // ---- Twitch: streams by ET start slot, follows per live hour vs per offline hour
  const st = streams(tw);
  const liveIn = t => st.some(s => t >= s.s && t <= s.e) || (tw.live && t >= tw.live.s);
  const tsr = series.filter(s => s.twitch != null); let fLive = 0, fOff = 0, hLive = 0, hOff = 0;
  for (let i = 1; i < tsr.length; i++) { const a = tsr[i - 1], b = tsr[i], d = b.twitch - a.twitch, h = (b.t - a.t) / HR; if (liveIn((a.t + b.t) / 2)) { fLive += d; hLive += h; } else { fOff += d; hOff += h; } }
  const tGrid = DAYS.map(() => BLOCKS.map(() => ({ hrs: 0, n: 0, v: [] })));
  for (const s of st) { for (let t = s.s; t < s.e; t += HR) { const w = et(t), c = tGrid[w.d][w.b]; c.hrs += Math.min(1, (s.e - t) / HR); } const w = et(s.s), c = tGrid[w.d][w.b]; c.n++; if (s.avg != null) c.v.push(s.avg); }
  const tracked = st.filter(s => s.src === 'live'), hrs = st.reduce((a, s) => a + (s.e - s.s) / HR, 0);
  const spanD = st.length ? Math.max(7, (now - st[0].s) / DAY) : null;
  const slotV = {}; for (const s of tracked) { const w = et(s.s); (slotV[`${DAYS[w.d]} ${BLOCKS[w.b]}`] = slotV[`${DAYS[w.d]} ${BLOCKS[w.b]}`] || []).push(s.avg); }
  const lpH = hLive >= 1 ? fLive / hLive : null, opH = hOff >= 1 ? fOff / hOff : null;
  plan.tw = {
    n: st.length, tracked: tracked.length, hrs: r1(hrs), perWeek: spanD ? r1(hrs / spanD * 7) : null, avg: r1(median(tracked.map(s => s.avg))), peak: tracked.length ? Math.max(...tracked.map(s => s.peak)) : null,
    lpH: r2(lpH), opH: r2(opH), hLive: r1(hLive), hOff: r1(hOff), live: tw.live ? { s: tw.live.s, v: tw.live.n.at(-1)?.[1] ?? null, g: tw.live.g } : null,
    grid: tGrid.map(r => r.map(c => ({ hrs: r1(c.hrs), n: c.n, avg: r1(median(c.v)) }))),
    streams: st.slice(-30).map(s => ({ s: s.s, hrs: r1((s.e - s.s) / HR), avg: s.avg ?? null, peak: s.peak ?? null, f: s.f ?? null, views: s.views ?? null, src: s.src })),
  };

  // ---- TikTok: hearts per video, and hearts on videos posted since tracking began
  const tts = series.filter(s => s.ttv != null && s.tth != null);
  const tv = Object.entries(tt).map(([id, o]) => ({ id, ...o, views: o.v.length ? o.v[o.v.length - 1][1] : 0, age: (now - o.pub) / DAY })).sort((a, b) => a.pub - b.pub);
  const tOld = tv.filter(u => u.age >= MIN_AGE), tLog = tOld.length ? tOld.reduce((a, u) => a + lg(u.views), 0) / tOld.length : 0;
  const tShr = a => Math.exp((a.reduce((x, v) => x + lg(v), 0) + K * tLog) / (a.length + K)) - 1;
  const tDay = split(tOld, u => et(u.pub).d), tBlk = split(tOld, u => et(u.pub).b);
  let tdv = 0, tdt = 0; for (const u of tv) if (u.v.length > 1) { const a = u.v[0], b = u.v[u.v.length - 1]; tdv += b[1] - a[1]; tdt = Math.max(tdt, (b[0] - a[0]) / DAY); }
  if (tts.length || tv.length) { const a = tts[0] || {}, b = tts[tts.length - 1] || {};
    plan.tt = { videos: b.ttv ?? null, hearts: b.tth ?? null, hpv: b.ttv ? r1(b.tth / b.ttv) : null, newVideos: b.ttv != null ? b.ttv - a.ttv : null, newHearts: b.tth != null ? b.tth - a.tth : null, fpv: r2(b.ttv ? (cur.tiktok || 0) / b.ttv : null),
      n: tv.length, views: tv.reduce((x, u) => x + u.views, 0), median: median(tOld.map(u => u.views)), vpd: tdt >= 0.5 ? r1(tdv / tdt) : null,
      hearts_t: tts.map(x => [x.t, x.tth]).slice(-400),
      grid: grid(tOld, u => u.views).map(r => r.map(c => ({ n: c.length, med: median(c) }))),
      days: DAYS.map((d, i) => ({ d, n: (tDay[i] || []).length, med: median(tDay[i] || []), x: tDay[i] ? Math.round(tShr(tDay[i])) : null })),
      vids: tv.slice(-40).map(u => ({ id: u.id, desc: u.desc, pub: u.pub, photo: u.photo, views: u.views })) };
    const tb = best(tDay, DAYS);
    if (tb && tOld.length >= 4) plan.ttBest = { k: 'TikTok post day', v: tb.k, x: tb.med, base: Math.exp(tLog) - 1, n: tb.n }; }

  // ---- read: data-backed calls, each with its sample size
  const I = plan.ideas, fmt = v => v == null ? '—' : Math.round(v).toLocaleString('en-US');
  if (plan.ttBest) { const b = plan.ttBest; I.push({ k: b.k, v: b.v, d: `${fmt(b.x)} expected views vs ${fmt(b.base)}`, n: b.n }); delete plan.ttBest; }
  const bd = best(byDay, DAYS), bb = best(byBlock, BLOCKS);
  if (bd || bb) I.push({ k: 'YouTube post slot', v: [bd && bd.k, bb && `${bb.k} ET`].filter(Boolean).join(' · '), d: `${fmt((bd || bb).med)} expected views vs ${fmt(Math.exp(allLog) - 1)}`, n: (bd || bb).n });
  if (shorts.length && longs.length) { const s = median(shorts), l = median(longs); I.push({ k: 'Shorts vs long', v: s >= l ? 'Shorts' : 'long', d: `${fmt(s)} vs ${fmt(l)} median views`, n: shorts.length + longs.length }); }
  if (batch.length >= 2 && solo.length >= 2) { const b = median(batch), s = median(solo); I.push({ k: 'Batch uploads', v: b >= s ? 'batch' : 'space out', d: `${fmt(b)} batched vs ${fmt(s)} solo`, n: batch.length + solo.length }); }
  if (gaps.length >= 3) I.push({ k: 'Upload gap', v: `${r1(median(gaps))} days`, d: `${last30} in 30 days`, n: gaps.length });
  if (subsPerK != null && goals.youtube?.next) { const need = goals.youtube.next.goal - (cur.youtube || 0); I.push({ k: `YouTube ${goals.youtube.next.goal}`, v: `${fmt(need / subsPerK * 1e3)} views`, d: `${r2(subsPerK)} subs / 1k views`, n: ups.length }); }
  const sv = Object.entries(slotV).filter(([, a]) => a.length >= 2).map(([k, a]) => ({ k, med: median(a), n: a.length })).sort((a, b) => b.med - a.med)[0];
  if (sv) I.push({ k: 'Stream slot', v: `${sv.k} ET`, d: `${r1(sv.med)} avg viewers`, n: sv.n });
  else { let top = null; tGrid.forEach((r, d) => r.forEach((c, b) => { if (c.hrs > 0 && (!top || c.hrs > top.hrs)) top = { k: `${DAYS[d]} ${BLOCKS[b]}`, hrs: c.hrs }; })); if (top) I.push({ k: 'Most streamed', v: `${top.k} ET`, d: `${r1(top.hrs)} hrs`, n: st.length }); }
  if (lpH != null && opH != null) I.push({ k: 'Follows / hour', v: `${r2(lpH)} live`, d: `${r2(opH)} offline${opH > 0 ? ` · ${r1(lpH / opH)}x` : ''}`, n: Math.round(hLive) });
  if (lpH > 0 && goals.twitch?.next) { const need = goals.twitch.next.goal - (cur.twitch || 0); I.push({ k: `Twitch ${goals.twitch.next.goal}`, v: `${fmt(need / lpH)} live hrs`, d: `${fmt(need)} follows at ${r2(lpH)}/hr`, n: Math.round(hLive) }); }
  if (plan.tt) I.push({ k: 'TikTok hearts', v: `${plan.tt.hpv} / video`, d: `${plan.tt.videos} videos · ${r2(plan.tt.fpv)} followers / video`, n: plan.tt.videos });
  const ytShorts = ups.filter(u => u.short).length;
  if (plan.tt && ytShorts) I.push({ k: 'Cross-post', v: `${plan.tt.videos} TikTok · ${ytShorts} Shorts`, d: plan.tt.videos > ytShorts ? `${plan.tt.videos - ytShorts} TikToks not on Shorts${ytSrc === 'rss' ? ' (feed shows latest 15)' : ''}` : 'even', n: plan.tt.videos });
  // ---- rolling views: the last X Shorts / TikToks (sum, mean, median) and a trailing-5 mean per post; history kept per change
  const X = 10, sum = a => a.reduce((x, y) => x + y, 0);
  const rollOf = a => { const l = a.slice(-X).map(u => u.views); return l.length ? { n: l.length, sum: sum(l), avg: Math.round(sum(l) / l.length), med: median(l) } : null; };
  const trail = (a, id) => { const i = a.findIndex(u => u.id === id); if (i < 0) return null; const w = a.slice(Math.max(0, i - 4), i + 1).map(u => u.views); return w.length >= 3 ? Math.round(sum(w) / w.length) : null; };
  const ytS = ups.filter(u => u.short);
  plan.roll = { x: X, yt: rollOf(ytS), tt: rollOf(tv) };
  for (const u of plan.yt.ups) u.r5 = u.short ? trail(ytS, u.id) : null;
  if (plan.tt?.vids) for (const u of plan.tt.vids) u.r5 = trail(tv, u.id);
  // ---- insights that unlock as samples grow (pending ones list what they wait on)
  const NETS = { twitch: 'Twitch', youtube: 'YouTube', tiktok: 'TikTok', x: 'X' }, pend = (k, d) => I.push({ k, v: null, d, n: null, wait: true });
  const vs = (a, lbl) => { const cur10 = a.slice(-X).map(u => u.views), prev10 = a.slice(-2 * X, -X).map(u => u.views);
    if (prev10.length >= 5) { const c = sum(cur10) / cur10.length, q = sum(prev10) / prev10.length, ch = (c / Math.max(1, q) - 1) * 100;
      I.push({ k: `${lbl} L10 trend`, v: `${ch >= 0 ? '+' : ''}${Math.round(ch)}%`, d: `${fmt(c)} vs ${fmt(q)} avg, prior ${prev10.length}`, n: cur10.length + prev10.length }); }
    else pend(`${lbl} L10 trend`, `at ${X + 5} ${lbl === 'Shorts' ? 'Shorts' : 'TikToks'} tracked (${a.length})`); };
  vs(ytS, 'Shorts'); vs(tv, 'TikTok');
  for (const [k, nm] of Object.entries(NETS)) { const g = goals[k]; if (!g) continue;
    if (g.tracked >= 14) { const t = (g.rate * (PRIOR + g.tracked) - g.prior * PRIOR) / Math.max(1, g.tracked);
      I.push({ k: `${nm} pace`, v: `${t >= g.prior ? '+' : ''}${r1(t - g.prior)}/mo vs lifetime`, d: `${r1(t)}/mo tracked · ${g.prior}/mo lifetime`, n: Math.round(g.tracked) }); }
    else pend(`${nm} pace`, `at 14 days tracked (${r1(g.tracked)})`); }
  const res = Object.values(hist).flatMap(h => (h.dated || []).filter(d => d.done)), msHit = Object.values(hist).flatMap(h => (h.ms || []).filter(m => m.hit && !m.est && m.ahead != null));
  if (res.length >= 3) { const hit = res.filter(d => d.hit).length, exp = sum(res.map(d => d.p)) / res.length;
    I.push({ k: 'Goal calibration', v: `${hit} of ${res.length} hit`, d: `${Math.round(hit / res.length * 100)}% hit vs ${Math.round(exp)}% forecast`, n: res.length }); }
  else pend('Goal calibration', `at 3 dated goals resolved (${res.length})`);
  if (msHit.length) { const a = sum(msHit.map(m => m.ahead)) / msHit.length; I.push({ k: 'Milestones vs pace', v: `${a >= 0 ? '+' : ''}${Math.round(a)} days`, d: `mean over ${msHit.length} tracked milestone${msHit.length > 1 ? 's' : ''}`, n: msHit.length }); }
  else pend('Milestones vs pace', 'at the first tracked milestone');
  const ttTr = series.filter(x => x.tiktok != null), ttDays = ttTr.length > 1 ? (ttTr.at(-1).t - ttTr[0].t) / DAY : 0;
  if (ttDays >= 7 && tdv > 0) { const f = ttTr.at(-1).tiktok - ttTr[0].tiktok; I.push({ k: 'TikTok follows / 1k views', v: `${r2(f / tdv * 1e3)}`, d: `${f} follows on ${fmt(tdv)} new views`, n: Math.round(ttDays) }); }
  else pend('TikTok follows / 1k views', `at 7 days tracked (${r1(ttDays)})`);
  if (!lpH) pend('Follows / hour', `at 1 live hour sampled (${r1(hLive)})`);
  if (subsPerK == null) pend('Subs / 1k views', 'at 3 days of YouTube view history');
  const rh = prev.plan?.roll_t || [], lr = rh[rh.length - 1], pt = [now, plan.roll.yt?.sum ?? null, plan.roll.tt?.sum ?? null];
  plan.roll_t = !lr || lr[1] !== pt[1] || lr[2] !== pt[2] || now - lr[0] > DAY ? [...rh, pt].slice(-1500) : rh;
  return { yt, tw, plan };
}
