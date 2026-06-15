// Sweep lolmath ULTIMATE BUILD (cost-ignoring) + CURRENT, via ?tab=results.
// Item row is a SIBLING of the label heading (CURRENT=next, ULTIMATE=prev), so probe both.
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';
const EXE = 'C:\\Users\\Administrator\\AppData\\Local\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe';
const base = JSON.parse(readFileSync(new URL('./lolmath_sweep.json', import.meta.url).pathname.replace(/^\//, ''), 'utf-8'));
const slugs = base.results.map(r => r.slug);
const OUT = new URL('./ultimate_sweep.json', import.meta.url).pathname.replace(/^\//, '');
const CONC = 2, WAIT = 26000;

const EXTRACT = () => {
  const itemsOf = el => el ? [...el.querySelectorAll('img')].filter(i => /item|loot/i.test(i.src))
    .map(i => (i.alt || '').trim()).filter(a => a && a !== 'No Item') : [];
  function pick(label) {
    const h = [...document.querySelectorAll('span,div,h3,h4,p')]
      .find(e => (e.textContent || '').trim().toUpperCase() === label && e.querySelectorAll('img').length === 0);
    if (!h) return [];
    for (const c of [h.previousElementSibling, h.nextElementSibling]) {
      const it = itemsOf(c); if (it.length >= 5) return it.slice(0, 6);
    }
    return [];
  }
  return { current: pick('CURRENT BUILD'), ultimate: pick('ULTIMATE BUILD') };
};

const browser = await chromium.launch({ headless: true, executablePath: EXE });
const ctx = await browser.newContext();
const out = [];
let i = 0;
async function scrape(slug) {
  const p = await ctx.newPage();
  try {
    await p.goto(`https://lolmath.net/itemop/${slug}/?tab=results`, { waitUntil: 'domcontentloaded', timeout: 25000 });
    await p.waitForFunction(() => {
      const itemsOf = el => el ? [...el.querySelectorAll('img')].filter(i => /item|loot/i.test(i.src) && (i.alt || '').trim() && (i.alt || '').trim() !== 'No Item') : [];
      const h = [...document.querySelectorAll('span,div,h3,h4,p')].find(e => (e.textContent || '').trim().toUpperCase() === 'ULTIMATE BUILD' && e.querySelectorAll('img').length === 0);
      if (!h) return false;
      return itemsOf(h.previousElementSibling).length >= 5 || itemsOf(h.nextElementSibling).length >= 5;
    }, { timeout: WAIT }).catch(() => {});
    await p.waitForTimeout(700);
    const d = await p.evaluate(EXTRACT);
    process.stderr.write(`${slug}:u${d.ultimate.length}/c${d.current.length} `);
    return { slug, ...d };
  } catch (e) { process.stderr.write(`${slug}:ERR `); return { slug, current: [], ultimate: [], err: String(e).slice(0, 80) }; }
  finally { await p.close(); }
}
async function worker() { while (i < slugs.length) { out.push(await scrape(slugs[i++])); } }
await Promise.all(Array.from({ length: CONC }, worker));
const bad = out.filter(r => r.ultimate.length < 5).map(r => r.slug);
if (bad.length) { process.stderr.write(`\nRETRY ${bad.length}\n`); for (const s of bad) { const f = await scrape(s); const j = out.findIndex(r => r.slug === s); if (f.ultimate.length > out[j].ultimate.length) out[j] = f; } }
out.sort((a, b) => a.slug.localeCompare(b.slug));
writeFileSync(OUT, JSON.stringify({ count: out.length, results: out }, null, 1));
const ud = out.reduce((m, r) => (m[r.ultimate.length] = (m[r.ultimate.length] || 0) + 1, m), {});
const cd = out.reduce((m, r) => (m[r.current.length] = (m[r.current.length] || 0) + 1, m), {});
process.stderr.write(`\nWROTE ult-dist ${JSON.stringify(ud)} cur-dist ${JSON.stringify(cd)}\n`);
await browser.close();
