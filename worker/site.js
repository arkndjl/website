// Site worker: static assets (public/) plus /api/plays, the ST. CLAIRE song play counter, /api/posts (article views and
// favorites, PostStats below) and /api/photo (On3 recruit photos).
// Only /api/* runs this code (run_worker_first in wrangler.toml); every other path is served straight from assets.
//   GET  /api/plays          -> {"ambro_sia": 12, "PHOENiX": 9}
//   POST /api/plays/<slug>   -> {"slug": "...", "plays": 13, "counted": true}
// <slug> is a track's mp3 name in /audio/ (ambro_sia for /audio/ambro_sia.mp3); unknown slugs are refused.
// Counts live in one SQLite Durable Object (no KV namespace or secret to set up). Dedupe: one count per
// visitor (hashed IP + user agent, salted per day, never stored raw) per song per 10 minutes, and at most
// 30 counts per visitor per hour across all songs.

import { DurableObject } from "cloudflare:workers";

const SLUG = /^[A-Za-z0-9_.-]{1,64}$/;
const SAME_SONG_MS = 10 * 60 * 1000;
const HOURLY_CAP = 30;

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

async function visitorKey(request) {
  const ip = request.headers.get("cf-connecting-ip") || "0";
  const ua = request.headers.get("user-agent") || "";
  const day = new Date().toISOString().slice(0, 10);
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${day}|${ip}|${ua}`));
  return [...new Uint8Array(buf).slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function looksLikeBot(ua) {
  return !ua || /bot|crawl|spider|slurp|headless|curl|wget|python|httpclient|preview/i.test(ua);
}

// Cloudflare's own clock (wrangler.toml [triggers]) starts the feed workflows that GitHub's cron skips. Each one is
// a workflow_dispatch of an existing workflow, so its concurrency group still queues or merges overlapping runs.
// Needs the GITHUB_TOKEN secret: a fine-grained token on arkndjl/website with Actions: read and write.
const DISPATCH = ["odds-snap.yml", "esea.yml", "picks-refresh.yml"];

async function dispatchFeeds(env) {
  if (!env.GITHUB_TOKEN) return console.log("feed dispatch: GITHUB_TOKEN not set");
  for (const wf of DISPATCH) {
    const r = await fetch(`https://api.github.com/repos/arkndjl/website/actions/workflows/${wf}/dispatches`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "arkndjl-site-cron",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({ ref: "main" }),
    });
    console.log(`feed dispatch ${wf}: ${r.status}`);
  }
}

// /api/photo/<path>: an On3 recruit photo (on3static.com/<path>) served from this site, so the GFX cards can draw it on a
// canvas and still save it (On3's CDN sends CORS headers only on some cached copies). Only On3's resized upload paths.
const ON3_PHOTO = /^cdn-cgi\/image\/[a-z0-9=,.]{1,120}\/uploads\/assets\/\d{1,6}\/\d{1,6}\/\d{1,9}\.(png|jpe?g|webp)$/i;

async function photo(url, request) {
  const path = url.pathname.slice("/api/photo/".length);
  if (request.method !== "GET" || !ON3_PHOTO.test(path)) return new Response("not found", { status: 404 });
  const r = await fetch(`https://on3static.com/${path}`, {
    headers: { Accept: request.headers.get("accept") || "image/*" },
    cf: { cacheEverything: true, cacheTtl: 7 * 86400 },
  });
  const type = r.headers.get("content-type") || "";
  if (!r.ok || !type.startsWith("image/")) return new Response("not found", { status: 404 });
  return new Response(r.body, {
    headers: { "content-type": type, "cache-control": "public, max-age=604800", "access-control-allow-origin": "*", vary: "Accept" },
  });
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchFeeds(env));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.replace(/\/+$/, "") === "/api/kofi") return kofi(request, env);
    if (url.pathname.replace(/\/+$/, "") === "/api/supporters") {
      return json(await supporters(request, env), 200, { "cache-control": "public, max-age=60" });
    }
    if (url.pathname.startsWith("/api/photo/")) return photo(url, request);
    if (url.pathname.replace(/\/+$/, "") === "/api/posts" || url.pathname.startsWith("/api/posts/")) return posts(url, request, env);
    if (!url.pathname.startsWith("/api/plays")) return env.ASSETS.fetch(request);
    const stub = env.PLAYS.get(env.PLAYS.idFromName("stclaire"));
    const rest = url.pathname.slice("/api/plays".length).replace(/^\/+|\/+$/g, "");

    if (request.method === "GET" && !rest) {
      const counts = await stub.all();
      return json(counts, 200, { "cache-control": "public, max-age=15" });
    }
    if (request.method !== "POST") return json({ error: "method" }, 405, { allow: "GET, POST" });
    if (!SLUG.test(rest)) return json({ error: "slug" }, 400);

    // same-site only: the browser sends Origin on POST
    const origin = request.headers.get("origin");
    // "Origin: null" (sandboxed frames, some privacy modes) is not a URL: refuse it, do not throw a 500
    let originHost = "";
    try { originHost = origin ? new URL(origin).host : ""; } catch { originHost = ""; }
    if (origin && originHost !== url.host) return json({ error: "origin" }, 403);

    // the song must be a real file on the site
    const asset = await env.ASSETS.fetch(new Request(new URL(`/audio/${rest}.mp3`, url), { method: "HEAD" }));
    if (!asset.ok) return json({ error: "unknown song" }, 404);

    if (looksLikeBot(request.headers.get("user-agent"))) {
      return json({ slug: rest, plays: await stub.get(rest), counted: false });
    }
    const out = await stub.hit(rest, await visitorKey(request), Date.now());
    return json({ slug: rest, ...out });
  },
};

// /api/posts: article views and favorites (layouts/partials/poststats.html, assets/js/poststats.js).
//   GET  /api/posts                    -> {"introducing-xpm": {"v": 412, "f": 9}, ...}
//   POST /api/posts/<slug>/view        -> {"v", "f", "counted"}: one view per visitor (hashed IP + user agent, salted per
//                                         day) per article per day, at most 60 a visitor a day, bots and other origins skipped
//   POST /api/posts/<slug>/fav {id, on} -> {"v", "f", "on"}: id is the browser's own random id (local storage), so one
//                                         favorite per browser and taking it back works on any later day; per IP a day at
//                                         most 5 favorites of one article and 40 favorite clicks in all
// <slug> must be a page at /posts/<slug>/. scripts/post_stats.py reads the GET into data/post_stats.json for milestones.
const POST_ID = /^[a-f0-9]{16,32}$/;

async function ipDay(request) {
  const ip = request.headers.get("cf-connecting-ip") || "0";
  const day = new Date().toISOString().slice(0, 10);
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`fav|${day}|${ip}`));
  return [...new Uint8Array(buf).slice(0, 12)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function posts(url, request, env) {
  const stub = env.POSTS.get(env.POSTS.idFromName("posts"));
  const parts = url.pathname.slice("/api/posts".length).replace(/^\/+|\/+$/g, "").split("/");
  if (request.method === "GET" && !parts[0]) return json(await stub.all(), 200, { "cache-control": "public, max-age=30" });
  if (request.method !== "POST") return json({ error: "method" }, 405, { allow: "GET, POST" });
  const [slug, act] = parts;
  if (parts.length !== 2 || !SLUG.test(slug) || (act !== "view" && act !== "fav")) return json({ error: "path" }, 400);
  const origin = request.headers.get("origin");
  let originHost = "";
  try { originHost = origin ? new URL(origin).host : ""; } catch { originHost = ""; }
  if (!origin || originHost !== url.host) return json({ error: "origin" }, 403);
  const page = await env.ASSETS.fetch(new Request(new URL(`/posts/${slug}/`, url), { method: "HEAD" }));
  if (!page.ok) return json({ error: "unknown post" }, 404);
  const bot = looksLikeBot(request.headers.get("user-agent"));
  const now = Date.now();
  if (act === "view") {
    if (bot) return json({ ...(await stub.one(slug)), counted: false });
    return json(await stub.view(slug, await visitorKey(request), now));
  }
  let body = {};
  try { body = await request.json(); } catch { body = {}; }
  const id = String(body.id || "");
  if (!POST_ID.test(id) || bot) return json({ error: "id" }, 400);
  return json(await stub.fav(slug, id, body.on !== false, await ipDay(request), now));
}

export class PostStats extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS views (slug TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS seen (who TEXT NOT NULL, slug TEXT NOT NULL, t INTEGER NOT NULL, PRIMARY KEY (who, slug))`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS favs (id TEXT NOT NULL, slug TEXT NOT NULL, t INTEGER NOT NULL, PRIMARY KEY (id, slug))`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS clicks (ip TEXT NOT NULL, slug TEXT NOT NULL, add_ INTEGER NOT NULL, t INTEGER NOT NULL)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS clicks_ip ON clicks (ip)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS favs_slug ON favs (slug)`);
  }

  all() {
    const out = {};
    for (const r of this.sql.exec(`SELECT slug, n FROM views`)) out[r.slug] = { v: r.n, f: 0 };
    for (const r of this.sql.exec(`SELECT slug, COUNT(*) AS c FROM favs GROUP BY slug`)) (out[r.slug] ||= { v: 0, f: 0 }).f = r.c;
    return out;
  }

  one(slug) {
    const v = this.sql.exec(`SELECT n FROM views WHERE slug = ?`, slug).toArray()[0];
    const f = this.sql.exec(`SELECT COUNT(*) AS c FROM favs WHERE slug = ?`, slug).toArray()[0];
    return { v: v ? v.n : 0, f: f ? f.c : 0 };
  }

  view(slug, who, now) {
    // the visitor key changes at midnight UTC, so a day's rows are all that is kept
    this.sql.exec(`DELETE FROM seen WHERE t < ?`, now - 26 * 3600 * 1000);
    const mine = this.sql.exec(`SELECT slug FROM seen WHERE who = ?`, who).toArray();
    if (mine.some((r) => r.slug === slug) || mine.length >= 60) return { ...this.one(slug), counted: false };
    this.sql.exec(`INSERT INTO seen (who, slug, t) VALUES (?, ?, ?)`, who, slug, now);
    this.sql.exec(`INSERT INTO views (slug, n) VALUES (?, 1) ON CONFLICT(slug) DO UPDATE SET n = n + 1`, slug);
    return { ...this.one(slug), counted: true };
  }

  fav(slug, id, on, ip, now) {
    this.sql.exec(`DELETE FROM clicks WHERE t < ?`, now - 26 * 3600 * 1000);
    const has = this.sql.exec(`SELECT 1 FROM favs WHERE id = ? AND slug = ?`, id, slug).toArray().length > 0;
    if (has === on) return { ...this.one(slug), on };
    const c = this.sql.exec(`SELECT slug, add_ FROM clicks WHERE ip = ?`, ip).toArray();
    if (on && (c.length >= 40 || c.filter((r) => r.slug === slug && r.add_).length >= 5)) return { ...this.one(slug), on: false, limited: true };
    if (!on && c.length >= 40) return { ...this.one(slug), on: true, limited: true };
    this.sql.exec(`INSERT INTO clicks (ip, slug, add_, t) VALUES (?, ?, ?, ?)`, ip, slug, on ? 1 : 0, now);
    if (on) this.sql.exec(`INSERT INTO favs (id, slug, t) VALUES (?, ?, ?)`, id, slug, now);
    else this.sql.exec(`DELETE FROM favs WHERE id = ? AND slug = ?`, id, slug);
    return { ...this.one(slug), on };
  }
}

// Ko-fi webhook (Ko-fi Settings > API > Webhook URL = https://arkndjl.net/api/kofi). Ko-fi posts form data
// with one field, data = JSON {verification_token, message_id, kofi_transaction_id, from_name, amount, currency,
// is_public, type, timestamp}. Checked against the KOFI_TOKEN worker secret. Every payment is stored.
// /api/supporters = {donors, gifts}: donations and memberships only (no shop orders or commissions), top 10 donors by
// total and top 10 single donations. A payment marked private (is_public false) is listed with no name (n = "").
// Ko-fi's "Send Single Donation Test" posts from "Jo Example"; it is stored but never listed.
// Past payments from Ko-fi's CSV export: static/data/kofi-past.json (scripts/kofi_past.py), merged by transaction id.
const KOFI_SKIP = new Set(["shop order", "commission"]);

async function supporters(request, env) {
  let rows = await env.SUPPORTERS.get(env.SUPPORTERS.idFromName("kofi")).rows();
  try {
    const r = await env.ASSETS.fetch(new Request(new URL("/data/kofi-past.json", request.url)));
    if (r.ok) {
      const seen = new Set(rows.map((x) => x.id));
      rows = rows.concat(((await r.json()).rows || []).filter((x) => x && !seen.has(String(x.id))));
    }
  } catch {}
  rows = rows.filter((x) => Number(x.amount) > 0 && !KOFI_SKIP.has(String(x.type || "").toLowerCase())
    && String(x.name || "").trim().toLowerCase() !== "jo example");
  const nm = (x) => (x.pub ? String(x.name || "").trim() : "");
  const by = new Map();
  for (const x of rows) {
    const n = nm(x), cur = x.currency || "USD";
    // private donors are not merged with each other: each name stays its own row, shown with no name
    const k = (n ? "p:" + n.toLowerCase() : "x:" + String(x.name || x.id).toLowerCase()) + "|" + cur;
    const o = by.get(k) || { n, a: 0, c: cur, k: 0, t: 0 };
    o.a += Number(x.amount); o.k += 1; o.t = Math.max(o.t, x.t || 0);
    by.set(k, o);
  }
  const r2 = (v) => Math.round(v * 100) / 100;
  const donors = [...by.values()].sort((a, b) => b.a - a.a || a.t - b.t).slice(0, 10).map((o) => ({ ...o, a: r2(o.a) }));
  const gifts = rows.slice().sort((a, b) => b.amount - a.amount || a.t - b.t).slice(0, 10)
    .map((x) => ({ n: nm(x), a: r2(Number(x.amount)), c: x.currency || "USD", t: x.t || 0 }));
  return { donors, gifts };
}

async function kofi(request, env) {
  if (request.method !== "POST") return json({ error: "method" }, 405, { allow: "POST" });
  if (!env.KOFI_TOKEN) return json({ error: "not set up" }, 503);
  let d;
  try { d = JSON.parse((await request.formData()).get("data") || ""); } catch { return json({ error: "bad data" }, 400); }
  if (!d || d.verification_token !== env.KOFI_TOKEN) return json({ error: "token" }, 403);
  const amount = Number(d.amount);
  if (!d.message_id || !Number.isFinite(amount)) return json({ error: "bad data" }, 400);
  await env.SUPPORTERS.get(env.SUPPORTERS.idFromName("kofi")).add({
    id: String(d.kofi_transaction_id || d.message_id).slice(0, 80),
    name: String(d.from_name || "").trim().slice(0, 40),
    amount, currency: String(d.currency || "USD").slice(0, 8),
    pub: d.is_public === true || d.is_public === "true" ? 1 : 0,
    t: Date.parse(d.timestamp) || Date.now(),
    type: String(d.type || "").slice(0, 20),
  });
  return json({ ok: true });
}

export class Supporters extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS tips (id TEXT PRIMARY KEY, name TEXT, amount REAL, currency TEXT, pub INTEGER, t INTEGER)`);
    const cols = this.sql.exec(`PRAGMA table_info(tips)`).toArray().map((c) => c.name);
    if (!cols.includes("type")) this.sql.exec(`ALTER TABLE tips ADD COLUMN type TEXT`);
  }
  add(r) {
    this.sql.exec(`INSERT OR IGNORE INTO tips (id, name, amount, currency, pub, t, type) VALUES (?, ?, ?, ?, ?, ?, ?)`, r.id, r.name, r.amount, r.currency, r.pub, r.t, r.type);
  }
  rows() {
    return this.sql.exec(`SELECT id, name, amount, currency, pub, t, type FROM tips`).toArray();
  }
}

export class PlayCounter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS plays (slug TEXT PRIMARY KEY, n INTEGER NOT NULL DEFAULT 0)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS hits (who TEXT NOT NULL, slug TEXT NOT NULL, t INTEGER NOT NULL)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS hits_who_t ON hits (who, t)`);
  }

  all() {
    const out = {};
    for (const r of this.sql.exec(`SELECT slug, n FROM plays ORDER BY slug`)) out[r.slug] = r.n;
    return out;
  }

  get(slug) {
    const r = this.sql.exec(`SELECT n FROM plays WHERE slug = ?`, slug).toArray()[0];
    return r ? r.n : 0;
  }

  hit(slug, who, now) {
    this.sql.exec(`DELETE FROM hits WHERE t < ?`, now - 60 * 60 * 1000);
    const recent = this.sql.exec(`SELECT slug, t FROM hits WHERE who = ?`, who).toArray();
    const dup = recent.some((r) => r.slug === slug && r.t > now - SAME_SONG_MS);
    if (dup || recent.length >= HOURLY_CAP) return { plays: this.get(slug), counted: false };
    this.sql.exec(`INSERT INTO hits (who, slug, t) VALUES (?, ?, ?)`, who, slug, now);
    this.sql.exec(`INSERT INTO plays (slug, n) VALUES (?, 1) ON CONFLICT(slug) DO UPDATE SET n = n + 1`, slug);
    return { plays: this.get(slug), counted: true };
  }
}
