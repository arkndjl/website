// Copyright (c) 2025-2026 Noah Dengler. All rights reserved. See LICENSE.
// Private feed of ARK model output for TLS Fantasy: a Cloudflare Worker in front of an R2 bucket. Not part of the
// public site, and nothing it serves is committed to git (sim draws) or it is a copy of a build file.
//
//   GET  /v1/                  list of files: [{key, size, uploaded}]                 Authorization: Bearer <read token>
//   GET  /v1/<sport>/<file>    one file (latest)                                       Authorization: Bearer <read token>
//   GET  /v1/<sport>/weekly/<YYYY-Www>/<file>   that ISO week's first copy of a draws file
//   PUT  /v1/<sport>/<file>    write (scripts/tls_upload.py from the sport's workflow)   Authorization: Bearer <upload token>
//
// Sports: nfl, nba, cbb, cfb. Secrets TLS_READ_TOKEN and TLS_UPLOAD_TOKEN may each hold several tokens separated by
// commas, so one can be rotated without downtime. A draws file (<sport>/draws.json.gz) also keeps the first upload of
// each ISO week under <sport>/weekly/<week>/, so past snapshots stay while the latest is overwritten.

const KEY = /^(nfl|nba|cbb|cfb)\/(weekly\/\d{4}-W\d{2}\/)?[a-z0-9_.-]{1,64}$/;
const MAX = 50 * 1024 * 1024;

function same(a, b) {                       // constant-time compare
  const x = new TextEncoder().encode(a), y = new TextEncoder().encode(b);
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x[i] || 0) ^ (y[i] || 0);
  return d === 0;
}

function allowed(req, list) {
  const m = /^Bearer\s+(.+)$/.exec(req.headers.get('authorization') || '');
  if (!m || !list) return false;
  let ok = false;
  for (const t of String(list).split(',').map(s => s.trim()).filter(s => s.length >= 32)) ok = same(m[1].trim(), t) || ok;
  return ok;
}

function isoWeek(d) {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  const y = t.getUTCFullYear(), w = Math.ceil(((t - Date.UTC(y, 0, 1)) / 864e5 + 1) / 7);
  return `${y}-W${String(w).padStart(2, '0')}`;
}

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
const type = k => k.endsWith('.gz') ? 'application/gzip' : k.endsWith('.json') ? 'application/json' : 'application/octet-stream';

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (!url.pathname.startsWith('/v1/')) return json({ error: 'not found' }, 404);
    const key = decodeURIComponent(url.pathname.slice(4));

    if (req.method === 'PUT') {
      if (!allowed(req, env.TLS_UPLOAD_TOKEN)) return json({ error: 'unauthorized' }, 401);
      if (!KEY.test(key) || key.includes('/weekly/')) return json({ error: 'bad key' }, 400);
      const len = +(req.headers.get('content-length') || 0);
      if (!len || len > MAX) return json({ error: 'empty or too large' }, 413);
      const body = await req.arrayBuffer();
      const meta = { httpMetadata: { contentType: type(key) }, customMetadata: { asof: req.headers.get('x-asof') || '' } };
      await env.FEED.put(key, body, meta);
      let weekly = null;
      if (key.endsWith('/draws.json.gz')) {
        const [sport] = key.split('/'), wk = `${sport}/weekly/${isoWeek(new Date())}/draws.json.gz`;
        if (!(await env.FEED.head(wk))) { await env.FEED.put(wk, body, meta); weekly = wk; }
      }
      return json({ ok: true, key, size: body.byteLength, weekly });
    }

    if (req.method !== 'GET' && req.method !== 'HEAD') return json({ error: 'method' }, 405);
    if (!allowed(req, env.TLS_READ_TOKEN)) return json({ error: 'unauthorized' }, 401);
    if (key === '') {
      const files = [];
      let cursor;
      do {
        const r = await env.FEED.list({ cursor, include: ['customMetadata'] });
        for (const o of r.objects) files.push({ key: o.key, size: o.size, uploaded: o.uploaded, asof: o.customMetadata?.asof || null });
        cursor = r.truncated ? r.cursor : undefined;
      } while (cursor);
      return json({ files });
    }
    if (!KEY.test(key)) return json({ error: 'bad key' }, 400);
    const obj = await env.FEED.get(key);
    if (!obj) return json({ error: 'not found' }, 404);
    const h = new Headers({ 'cache-control': 'no-store', etag: obj.httpEtag });
    obj.writeHttpMetadata(h);
    if (obj.customMetadata?.asof) h.set('x-asof', obj.customMetadata.asof);
    return new Response(req.method === 'HEAD' ? null : obj.body, { headers: h });
  },
};
