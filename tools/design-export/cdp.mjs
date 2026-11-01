// Minimal CDP harness: node cdp.mjs <check|shot|print> <url> <w> <h> [out.png] [--mobile] [--clipY=N]
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const [mode, url, W, H, out] = process.argv.slice(2);
const mobile = process.argv.includes("--mobile");
const reduced = process.argv.includes("--reduced");
const dpr = +((process.argv.find(a => a.startsWith("--dpr=")) || "--dpr=1").slice(6));
const full = process.argv.includes("--full");
const asPrint = process.argv.includes("--print");
const yArg = (process.argv.find(a => a.startsWith("--y=")) || "").slice(4);
const scratch = path.dirname(new URL(import.meta.url).pathname);
const prof = mkdtempSync(path.join(scratch, "prof-"));

const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
  `--user-data-dir=${prof}`, "--remote-debugging-port=0", "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
const wsUrl = await new Promise((res, rej) => {
  let buf = ""; const t = setTimeout(() => rej(new Error("no devtools url")), 15000);
  chrome.stderr.on("data", d => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) { clearTimeout(t); res(m[1]); } });
});
const ws = new WebSocket(wsUrl);
await new Promise(r => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map(); const listeners = [];
ws.addEventListener("message", ev => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) { const { res, rej } = pending.get(msg.id); pending.delete(msg.id); msg.error ? rej(new Error(JSON.stringify(msg.error))) : res(msg.result); }
  else listeners.forEach(l => l(msg));
});
const send = (method, params = {}, sessionId) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const S = (m, p) => send(m, p, sessionId);
await S("Page.enable"); await S("Runtime.enable");
await S("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: dpr, mobile });
if (reduced) await S("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
const loaded = new Promise(r => listeners.push(m => { if (m.method === "Page.loadEventFired" && m.sessionId === sessionId) r(); }));
await S("Page.navigate", { url });
await loaded;
await S("Runtime.evaluate", { expression: "document.fonts.ready.then(()=>true)", awaitPromise: true });
await sleep(1600); // let the one-shot redaction animation finish

const evalJSON = async expr => { const r = await S("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails)); return r.result.value; };

const CHECK = `(() => {
  const r = {};
  r.vw = innerWidth; r.scrollW = document.documentElement.scrollWidth; r.hOverflow = r.scrollW > r.vw; r.docH = document.documentElement.scrollHeight;
  r.fonts = { mono: document.fonts.check('700 16px "Martian Mono"'), text: document.fonts.check('16px "Atkinson Hyperlegible Next"') };
  r.faces = [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight + ' ' + f.stretch + ' ' + f.unicodeRange.slice(0,12));
  const off = [];
  for (const el of document.querySelectorAll('body *')) {
    const b = el.getBoundingClientRect(); if (!b.width || el.closest('.tbl') || el.closest('.sr-only')) continue;
    if (b.right > innerWidth + .5 || b.left < -.5) off.push(el.tagName + '.' + el.className + ' [' + Math.round(b.left) + ',' + Math.round(b.right) + '] ' + (el.textContent||'').trim().slice(0,30));
  }
  r.offenders = off.slice(0, 12);
  r.tables = [...document.querySelectorAll('.tbl')].map(t => (t.scrollWidth > t.clientWidth + 1 ? 'SCROLL ' : 'fit ') + t.scrollWidth + '/' + t.clientWidth);
  const h1 = document.querySelector('h1'), cs = getComputedStyle(h1);
  r.h1 = { fs: cs.fontSize, lh: cs.lineHeight, w: Math.round(h1.getBoundingClientRect().width), h: Math.round(h1.getBoundingClientRect().height) };
  // contrast of every text-bearing element against its effective background
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = ({r,g,b}) => { const f = v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126*f(r) + .7152*f(g) + .0722*f(b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x,y) + .05) / (Math.min(x,y) + .05); };
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > .5) return c; } return { r: 255, g: 255, b: 255, a: 1 }; };
  const low = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.closest('[aria-hidden="true"]') || el.closest('.sr-only') || el.closest('.redact')) continue;
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) continue;
    const s = getComputedStyle(el); if (s.visibility === 'hidden' || s.display === 'none') continue;
    const fg = parse(s.color), bg = bgOf(el), cr = ratio(fg, bg);
    const fs = parseFloat(s.fontSize), large = fs >= 24 || (fs >= 18.66 && +s.fontWeight >= 700);
    if (cr < (large ? 3 : 4.5)) low.push(el.tagName + '.' + el.className + ' ' + cr.toFixed(2) + ' ' + s.color + ' on ' + JSON.stringify(bg) + ' "' + el.textContent.trim().slice(0, 30) + '"');
  }
  r.lowContrast = low.slice(0, 15); r.lowContrastCount = low.length;
  return r;
})()`;

const PRINT = `(() => {
  const r = {}; const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const dark = []; for (const el of document.querySelectorAll('html, body, body *')) { const c = parse(getComputedStyle(el).backgroundColor); if (c && c.a > .1 && (c.r + c.g + c.b) < 600) dark.push(el.tagName + '.' + el.className + ' ' + getComputedStyle(el).backgroundColor); }
  r.nonWhiteBackgrounds = dark.slice(0, 20); r.count = dark.length;
  r.body = getComputedStyle(document.body).color + ' on ' + getComputedStyle(document.body).backgroundColor;
  r.nav = getComputedStyle(document.querySelector('.topnav')).display;
  r.tableMinW = [...document.querySelectorAll('table')].map(t => getComputedStyle(t).minWidth).join(',');
  r.tblOverflow = [...document.querySelectorAll('.tbl')].map(t => getComputedStyle(t).overflowX).join(',');
  return r;
})()`;

try {
  if (mode === "check") console.log(JSON.stringify(await evalJSON(CHECK), null, 1));
  if (mode === "print") { await S("Emulation.setEmulatedMedia", { media: "print" }); console.log(JSON.stringify(await evalJSON(PRINT), null, 1)); }
  if (mode === "evalfile") { const { readFileSync } = await import("node:fs"); console.log(JSON.stringify(await evalJSON(readFileSync(out, "utf8")), null, 1)); }
  if (asPrint) await S("Emulation.setEmulatedMedia", { media: "print" });
  if (mode === "eval") console.log(JSON.stringify(await evalJSON(process.argv[6] || out), null, 1));
  if (mode === "shot") {
    if (full) { const h = await evalJSON("Math.ceil(document.documentElement.scrollHeight)"); await S("Emulation.setDeviceMetricsOverride", { width: +W, height: h, deviceScaleFactor: dpr, mobile }); await sleep(500); }
    if (yArg) { await S("Runtime.evaluate", { expression: `window.scrollTo(0, ${+yArg})` }); await sleep(400); }
    const { data } = await S("Page.captureScreenshot", { format: "png" });
    writeFileSync(out, Buffer.from(data, "base64")); console.log("saved", out);
  }
  if (mode === "pdf") {
    const { data } = await S("Page.printToPDF", { printBackground: false, preferCSSPageSize: true });
    writeFileSync(out, Buffer.from(data, "base64")); console.log("saved", out);
  }
} finally { ws.close(); chrome.kill(); }
