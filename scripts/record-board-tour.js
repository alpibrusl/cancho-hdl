#!/usr/bin/env node
// Re-records docs/demo/board-tour.mp4 and .webm (and the poster) from the gallery on docs/index.html.
// A recording of the page, not a live session: the animations replay numbers recorded from the board.
// Needs node, the `playwright` package with a Chromium (PLAYWRIGHT_CHROMIUM names the binary), and ffmpeg.
//   node scripts/record-board-tour.js
'use strict';
const fs = require('fs');
const http = require('http');
const path = require('path');
const { spawnSync } = require('child_process');
const { chromium } = require('playwright');

const NAME = 'board-tour';
const DOCS = path.join(__dirname, '..', 'docs');
const OUT = path.join(DOCS, 'demo');

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
  const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'record-board-tour-'));
  const browser = await chromium.launch({ args: ['--no-proxy-server'], executablePath: process.env.PLAYWRIGHT_CHROMIUM || undefined });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await ctx.newPage();
  await page.goto(url);
  // Playwright's own video recorder needs a matching ffmpeg build, so frames are screenshots with their capture times,
  // joined afterwards by ffmpeg's concat demuxer (variable frame rate, about 8 frames a second).
  const frames = [];
  let recording = true;
  const t0 = Date.now();
  const grab = (async () => {
    for (let n = 0; recording; n++) {
      const f = path.join(tmp, `f${String(n).padStart(5, '0')}.jpg`);
      await page.screenshot({ path: f, type: 'jpeg', quality: 80 });
      frames.push([f, Date.now() - t0]);
    }
  })();
  // Each stop scrolls a row of the gallery into view and lets its animations run.
  const stops = ['#state', '#fmax', '#gallery', '.gal .ex:nth-child(4)', '.gal .ex:nth-child(7)', '.gal .ex:nth-child(10)', '#link'];
  for (const sel of stops) {
    await page.evaluate((s) => { const e = document.querySelector(s); const y = e.getBoundingClientRect().top + window.scrollY - 80; window.scrollTo({ top: y, behavior: 'smooth' }); }, sel);
    await page.waitForTimeout(sel.includes('.ex') ? 6500 : 3500);
  }
  recording = false;
  await grab;
  await browser.close();
  server.close();
  const list = frames.map(([f, t], i) => `file '${f}'\nduration ${((i + 1 < frames.length ? frames[i + 1][1] : t + 100) - t) / 1000}`).join('\n') + `\nfile '${frames[frames.length - 1][0]}'\n`;
  fs.writeFileSync(path.join(tmp, 'list.txt'), list);
  const webm = path.join(tmp, 'tour.mp4');
  ffmpeg(['-f', 'concat', '-safe', '0', '-i', path.join(tmp, 'list.txt'), '-vf', 'fps=15', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', webm]);
  const mp4 = path.join(OUT, NAME + '.mp4');
  ffmpeg(['-ss', '0.5', '-i', webm, '-vf', 'fps=15,scale=1024:-2:flags=lanczos', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '29', '-preset', 'slow', '-movflags', '+faststart', '-an', mp4]);
  ffmpeg(['-ss', '0.5', '-i', webm, '-vf', 'fps=15,scale=1024:-2:flags=lanczos', '-c:v', 'libvpx-vp9', '-b:v', '0', '-crf', '40', '-an', path.join(OUT, NAME + '.webm')]);
  const dur = parseFloat(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', mp4]).stdout.toString());
  ffmpeg(['-ss', '14', '-i', mp4, '-frames:v', '1', '-q:v', '4', path.join(OUT, NAME + '.poster.jpg')]);
  console.log(`wrote ${mp4} (${dur.toFixed(1)} s)`);
})().catch((e) => { console.error(e); process.exit(1); });
