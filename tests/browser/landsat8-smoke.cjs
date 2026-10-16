const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({viewport: {width: 1000, height: 700}});
  const errors = [];
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.goto(process.env.MODEL_SMOKE_URL || 'http://127.0.0.1:8099/tests/browser/landsat8-smoke.html', {waitUntil: 'networkidle'});
  await page.waitForFunction(() => window.__modelResult, null, {timeout: 120000});
  const result = await page.evaluate(() => window.__modelResult);
  if (!result.ready) throw new Error(result.error || `model not ready: ${JSON.stringify(result)}; console=${JSON.stringify(errors)}`);
  if (result.modelCount < 1) throw new Error('entity model primitive was not added');
  if (process.env.MODEL_SMOKE_SCREENSHOT) await page.screenshot({path: process.env.MODEL_SMOKE_SCREENSHOT});
  console.log(JSON.stringify({result, consoleErrors: errors}));
  await browser.close();
})().catch((error) => { console.error(error); process.exitCode = 1; });
