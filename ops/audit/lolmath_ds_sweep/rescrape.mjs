// Re-scrape only partial/short champs at low concurrency (optimizer is CPU-bound).
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';
const EXE = 'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe';
const F = new URL('./lolmath_sweep.json', import.meta.url).pathname.replace(/^\//, '');
const data = JSON.parse(readFileSync(F, 'utf-8'));
const CONC = 2, WAIT = 28000, NEED = 6;

const EXTRACT = () => {
  const items = el => [...el.querySelectorAll('img')].filter(i => /item|loot/i.test(i.src || ''))
    .map(i => (i.alt || i.title || '').trim()).filter(a => a && a !== 'No Item');
  let bo = [...document.querySelectorAll('*')].find(e => /BUILD ORDER/i.test(e.textContent || '') &&
    e.querySelectorAll('img').length >= 5 && e.querySelectorAll('img').length <= 14);
  const r = { build_order: bo ? items(bo) : [] };
  r.enemies = [...document.querySelectorAll('img')].filter(i => /champion|tiles|centered/i.test(i.src || ''))
    .map(i => (i.alt || '').trim()).filter(Boolean).slice(0, 6);
  r.runes = [...document.querySelectorAll('img')].filter(i => /perk|rune/i.test(i.src || ''))
    .map(i => (i.alt || '').trim()).filter(Boolean).slice(0, 9);
  return r;
};

const todo = data.results.filter(r => r.status !== 'ok' || r.build_order.length < NEED).map(r => r.slug);
process.stderr.write(`RESCRAPE ${todo.length} at CONC=${CONC}\n`);

const browser = await chromium.launch({ headless: true, executablePath: EXE });
const ctx = await browser.newContext();
let i = 0;
async function scrape(slug) {
  const p = await ctx.newPage();
  try {
    await p.goto(`https://lolmath.net/itemop/${slug}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    await p.waitForFunction(() => {
      const bo = [...document.querySelectorAll('*')].find(e => /BUILD ORDER/i.test(e.textContent || '') && e.querySelectorAll('img').length >= 5);
      if (!bo) return false;
      return [...bo.querySelectorAll('img')].filter(i => /item|loot/i.test(i.src || '') && (i.alt || '').trim() && (i.alt || '').trim() !== 'No Item').length >= 6;
    }, { timeout: WAIT }).catch(() => {});
    await p.waitForTimeout(800);
    const d = await p.evaluate(EXTRACT);
    process.stderr.write(`${slug}:${d.build_order.length} `);
    return d;
  } catch (e) { process.stderr.write(`${slug}:ERR `); return { build_order: [], enemies: [], runes: [] }; }
  finally { await p.close(); }
}
async function worker() {
  while (i < todo.length) {
    const s = todo[i++];
    const d = await scrape(s);
    const idx = data.results.findIndex(r => r.slug === s);
    if (d.build_order.length > data.results[idx].build_order.length) {
      data.results[idx] = { ...data.results[idx], ...d, status: d.build_order.length >= 5 ? 'ok' : 'partial' };
    }
  }
}
await Promise.all(Array.from({ length: CONC }, worker));
data.results.sort((a, b) => a.slug.localeCompare(b.slug));
writeFileSync(F, JSON.stringify(data, null, 1));
const dist = data.results.reduce((m, r) => (m[r.build_order.length] = (m[r.build_order.length] || 0) + 1, m), {});
process.stderr.write(`\nDONE len-dist ${JSON.stringify(dist)}\n`);
await browser.close();
