const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  await page.goto(
    process.env.PAYLOAD_VIEW_SMOKE_URL
      || 'http://127.0.0.1:8099/tests/browser/fixed-payload-view-smoke.html',
    { waitUntil: 'networkidle' }
  );
  await page.waitForFunction(
    () => window.payloadViewSmoke && window.payloadViewSmoke.ready,
    null,
    { timeout: 30000 }
  );
  const result = await page.evaluate(() => window.payloadViewSmoke);
  await browser.close();
  if (result.error) throw new Error(result.error);
  if (result.width !== 180 || result.height !== 180 || result.aspectRatio !== 1) {
    throw new Error('optical viewport was stretched: ' + JSON.stringify(result));
  }
  if (result.shouldAnimate || result.inputsEnabled || Math.abs(result.fovDegrees - 45) > 1e-9) {
    throw new Error('secondary viewer authority/FOV mismatch: ' + JSON.stringify(result));
  }
  if (!result.time.startsWith('2026-01-01T00:00:05')) {
    throw new Error('secondary viewer time mismatch: ' + JSON.stringify(result));
  }
  if (consoleErrors.length) throw new Error('browser console errors: ' + consoleErrors.join('\n'));
  console.log(JSON.stringify(result));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
