// Site worker: static assets (public/) plus /api/plays, the ST. CLAIRE song play counter.
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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.replace(/\/+$/, "") === "/api/kofi") return kofi(request, env);
    if (url.pathname.replace(/\/+$/, "") === "/api/supporters") {
      const list = await env.SUPPORTERS.get(env.SUPPORTERS.idFromName("kofi")).top(25);
      return json(list, 200, { "cache-control": "public, max-age=60" });
    }
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
    if (origin && new URL(origin).host !== url.host) return json({ error: "origin" }, 403);

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

// Ko-fi webhook (Ko-fi Settings > API > Webhook URL = https://arkndjl.net/api/kofi). Ko-fi posts form data
// with one field, data = JSON {verification_token, message_id, from_name, amount, currency, is_public, type}.
// Checked against the KOFI_TOKEN worker secret. Every payment is stored; /api/supporters lists only names from
// public payments (is_public true), ranked by total, names only, no amounts.
async function kofi(request, env) {
  if (request.method !== "POST") return json({ error: "method" }, 405, { allow: "POST" });
  if (!env.KOFI_TOKEN) return json({ error: "not set up" }, 503);
  let d;
  try { d = JSON.parse((await request.formData()).get("data") || ""); } catch { return json({ error: "bad data" }, 400); }
  if (!d || d.verification_token !== env.KOFI_TOKEN) return json({ error: "token" }, 403);
  const amount = Number(d.amount);
  if (!d.message_id || !Number.isFinite(amount)) return json({ error: "bad data" }, 400);
  await env.SUPPORTERS.get(env.SUPPORTERS.idFromName("kofi")).add({
    id: String(d.message_id).slice(0, 80),
    name: String(d.from_name || "").trim().slice(0, 40),
    amount, currency: String(d.currency || "USD").slice(0, 8),
    pub: d.is_public === true || d.is_public === "true" ? 1 : 0,
    t: Date.parse(d.timestamp) || Date.now(),
  });
  return json({ ok: true });
}

export class Supporters extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS tips (id TEXT PRIMARY KEY, name TEXT, amount REAL, currency TEXT, pub INTEGER, t INTEGER)`);
  }
  add(r) {
    this.sql.exec(`INSERT OR IGNORE INTO tips (id, name, amount, currency, pub, t) VALUES (?, ?, ?, ?, ?, ?)`, r.id, r.name, r.amount, r.currency, r.pub, r.t);
  }
  top(n) {
    const out = [];
    for (const r of this.sql.exec(`SELECT name, SUM(amount) a, MAX(t) t FROM tips WHERE pub = 1 AND name != '' GROUP BY lower(name) ORDER BY a DESC, t ASC LIMIT ?`, n)) out.push(r.name);
    return out;
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
