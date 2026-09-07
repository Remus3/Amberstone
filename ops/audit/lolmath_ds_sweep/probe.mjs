import { chromium } from 'playwright';
// Resolved under THIS account's home rather than baked in: a launch path naming
// another account's home silently does not exist.
const EXE=`${process.env.LOCALAPPDATA}\\ms-playwright\\chromium-1217\\chrome-win64\\chrome.exe`;
const b=await chromium.launch({headless:true,executablePath:EXE});
const ctx=await b.newContext();
for(const s of ['gwen','jayce','viego']){
  const p=await ctx.newPage();
  await p.goto(`https://lolmath.net/itemop/${s}/`,{waitUntil:'domcontentloaded',timeout:25000});
  await p.waitForTimeout(30000);
  const r=await p.evaluate(()=>{let bo=[...document.querySelectorAll('*')].find(e=>/BUILD ORDER/i.test(e.textContent||'')&&e.querySelectorAll('img').length>=5&&e.querySelectorAll('img').length<=14);return bo?[...bo.querySelectorAll('img')].filter(i=>/item|loot/i.test(i.src)).map(i=>(i.alt||'').trim()).filter(a=>a&&a!=='No Item'):[];});
  console.error(s, r.length, JSON.stringify(r));
  await p.close();
}
await b.close();
