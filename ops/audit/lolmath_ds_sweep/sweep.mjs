// lolmath all-champion build sweep (headless). Writes lolmath_sweep.json.
// Usage: node sweep.mjs [limitN]   (limitN optional, for smoke test)
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';

const LIMIT = process.argv[2] ? parseInt(process.argv[2], 10) : 0;
const CONC = 5;
const OUT = new URL('./lolmath_sweep.json', import.meta.url).pathname.replace(/^\//, '');

const EXTRACT = () => {
  const r = { build_order: [], enemies: [], runes: [], nyi: '' };
  const items = el => [...el.querySelectorAll('img')]
    .filter(i => /item|loot/i.test(i.src || ''))
    .map(i => (i.alt || i.title || '').trim())
    .filter(a => a && a !== 'No Item');
  let bo = [...document.querySelectorAll('*')].find(e =>
    /BUILD ORDER/i.test(e.textContent || '') &&
    e.querySelectorAll('img').length >= 5 && e.querySelectorAll('img').length <= 14);
  if (bo) r.build_order = items(bo);
  r.enemies = [...document.querySelectorAll('img')]
    .filter(i => /champion|tiles|centered/i.test(i.src || ''))
    .map(i => (i.alt || '').trim()).filter(Boolean).slice(0, 6);
  r.runes = [...document.querySelectorAll('img')]
    .filter(i => /perk|rune/i.test(i.src || ''))
    .map(i => (i.alt || '').trim()).filter(Boolean).slice(0, 9);
  const bt = document.body.innerText || '';
  const m = bt.match(/Not Yet Implemented[\s\S]{0,400}/i);
  if (m) r.nyi = m[0].replace(/\s+/g, ' ').trim().slice(0, 400);
  return r;
};

async function scrape(ctx, slug) {
  const page = await ctx.newPage();
  try {
    await page.goto(`https://lolmath.net/itemop/${slug}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    await page.waitForFunction(() => {
      const bo = [...document.querySelectorAll('*')].find(e =>
        /BUILD ORDER/i.test(e.textContent || '') &&
        e.querySelectorAll('img').length >= 5);
      if (!bo) return false;
      return [...bo.querySelectorAll('img')]
        .filter(i => /item|loot/i.test(i.src || '') && (i.alt || '').trim() && (i.alt || '').trim() !== 'No Item')
        .length >= 5;
    }, { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(800);
    const d = await page.evaluate(EXTRACT);
    const status = d.build_order.length >= 5 ? 'ok' : (d.build_order.length ? 'partial' : 'empty');
    process.stderr.write(`${slug}:${status}:${d.build_order.length} `);
    return { slug, status, ...d };
  } catch (e) {
    process.stderr.write(`${slug}:ERR `);
    return { slug, status: 'error', err: String(e).slice(0, 120), build_order: [], enemies: [], runes: [], nyi: '' };
  } finally {
    await page.close();
  }
}

(async () => {
  const EXE = 'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe';
  const browser = await chromium.launch({ headless: true, executablePath: EXE });
  const ctx = await browser.newContext();
  // harvest roster slugs
  const idx = await ctx.newPage();
  await idx.goto('https://lolmath.net/itemop/', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await idx.waitForTimeout(2500);
  let slugs = await idx.evaluate(() => [...document.querySelectorAll('a[href*="/itemop/"]')]
    .map(a => (a.getAttribute('href') || '').match(/\/itemop\/([^\/]+)\/?$/))
    .filter(Boolean).map(m => m[1].toLowerCase()));
  slugs = [...new Set(slugs)].filter(s => s && s !== '');
  await idx.close();
  if (LIMIT) slugs = slugs.slice(0, LIMIT);
  process.stderr.write(`\nROSTER ${slugs.length} slugs\n`);

  const results = [];
  let i = 0;
  async function worker() {
    while (i < slugs.length) {
      const s = slugs[i++];
      results.push(await scrape(ctx, s));
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker));
  // retry pass: re-scrape any non-ok once
  const bad = results.filter(r => r.status !== 'ok').map(r => r.slug);
  if (bad.length) {
    process.stderr.write(`\nRETRY ${bad.length}: ${bad.join(',')}\n`);
    for (const s of bad) {
      const fresh = await scrape(ctx, s);
      const idx2 = results.findIndex(r => r.slug === s);
      if (fresh.build_order.length >= results[idx2].build_order.length) results[idx2] = fresh;
    }
  }
  results.sort((a, b) => a.slug.localeCompare(b.slug));
  writeFileSync(OUT, JSON.stringify({ patch_label: '26.12', count: results.length, results }, null, 1));
  process.stderr.write(`\nWROTE ${OUT} (${results.length})\n`);
  await browser.close();
})();
