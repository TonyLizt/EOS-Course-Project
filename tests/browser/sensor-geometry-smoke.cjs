const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.goto(
    process.env.GEOMETRY_SMOKE_URL || 'http://127.0.0.1:8099/tests/browser/sensor-geometry-smoke.html',
    { waitUntil: 'networkidle' }
  );
  await page.waitForFunction(() => window.geometrySmoke && window.geometrySmoke.ready, null, { timeout: 30000 });
  const result = await page.evaluate(() => window.geometrySmoke);
  await browser.close();
  if (result.error) throw new Error(result.error);
  if (result.status !== 'COMPLETE' || result.rayCount !== 16 || result.hitCount !== 16) {
    throw new Error('unexpected WGS84 geometry result: ' + JSON.stringify(result));
  }
  if (consoleErrors.length) throw new Error('browser console errors: ' + consoleErrors.join('\n'));
  console.log(JSON.stringify(result));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
