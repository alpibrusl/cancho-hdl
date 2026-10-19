#!/usr/bin/env node
// Re-records docs/demo/hdl-demo.mp4 and .webm (and the poster) from the project page's replay.
// A recording of the page, not a live session: the replay on docs/index.html is driven
// by captured output of the chw commands and the Python impact report. Needs node, the `playwright` package with a
// Chromium (PLAYWRIGHT_CHROMIUM or the default), and ffmpeg. Re-run it when the replay
// in docs/index.html changes.
//   node scripts/record-demo.js
'use strict';
const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawnSync } = require('child_process');
const { chromium } = require('playwright');

const NAME = 'hdl-demo';
const DOCS = path.join(__dirname, '..', 'docs');
const OUT = path.join(DOCS, 'demo');
const SCROLL = 372;          // keeps the demo clear of the sticky header
const SETTLE_MS = 4000;      // the log must stop changing for this long

function serve() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.mp4': 'video/mp4', '.png': 'image/png', '.jpg': 'image/jpeg' };
  const server = http.createServer((req, res) => {
    const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
    const file = path.join(DOCS, path.normalize(rel));
    if (!file.startsWith(DOCS) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((ok) => server.listen(0, '127.0.0.1', () => ok(server)));
}

function ffmpeg(args) {
  const r = spawnSync('ffmpeg', ['-loglevel', 'error', '-y', ...args], { stdio: 'inherit' });
  if (r.status !== 0) { throw new Error('ffmpeg failed: ' + args.join(' ')); }
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const server = await serve();
  const url = `http://127.0.0.1:${server.address().port}/index.html`;
  const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'record-demo-'));
  const browser = await chromium.launch({ args: ['--no-proxy-server'] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: tmp, size: { width: 1280, height: 720 } } });
  const page = await ctx.newPage();
  await page.goto(url);
  await page.evaluate((y) => window.scrollTo(0, y), SCROLL);
  let last = '', same = 0;
  for (let i = 0; i < 240 && same * 500 < SETTLE_MS; i++) {
    await page.waitForTimeout(500);
    const t = await page.textContent('#screen');
    same = t === last ? same + 1 : 0;
    last = t;
  }
  await page.waitForTimeout(1500);
  await ctx.close();
  await browser.close();
  server.close();
  const webm = path.join(tmp, fs.readdirSync(tmp).find((f) => f.endsWith('.webm')));
  const mp4 = path.join(OUT, NAME + '.mp4');
  // Drop the first second (page load), 15 fps, 1024 px wide: about 200 KB.
  ffmpeg(['-ss', '1.0', '-i', webm, '-vf', 'fps=15,scale=1024:-2:flags=lanczos', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '29', '-preset', 'slow', '-movflags', '+faststart', '-an', mp4]);
  // A WebM (VP9) beside the MP4: browsers without an H.264 decoder (some Linux builds) take it.
  ffmpeg(['-ss', '1.0', '-i', webm, '-vf', 'fps=15,scale=1024:-2:flags=lanczos', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '40', '-an', path.join(OUT, NAME + '.webm')]);
  const dur = parseFloat(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', mp4]).stdout.toString());
  ffmpeg(['-ss', String(Math.max(0, dur - 1.8)), '-i', mp4, '-frames:v', '1', '-q:v', '4', path.join(OUT, NAME + '.poster.jpg')]);
  console.log(`wrote ${mp4} (${dur.toFixed(1)} s)`);
})().catch((e) => { console.error(e); process.exit(1); });
