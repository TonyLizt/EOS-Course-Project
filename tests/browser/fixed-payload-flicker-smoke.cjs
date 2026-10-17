// Real Chromium soak for the serial Fixed Payload renderer. The companion
// serve_integrated_fixture.py owns all temporary database/replay state.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const coord = process.env.EOS_BROWSER_QA_COORD;
  if (!coord) throw new Error('EOS_BROWSER_QA_COORD is required');
  const info = JSON.parse(fs.readFileSync(coord, 'utf8'));
  const expectedCount = Number(process.env.PAYLOAD_SATELLITE_COUNT || info.satellite_count);
  const soakSeconds = Number(process.env.PAYLOAD_SOAK_SECONDS || 30);
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.EOS_BROWSER_EXECUTABLE
      ? { executablePath: process.env.EOS_BROWSER_EXECUTABLE } : {}),
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--js-flags=--expose-gc']
  });
  const errors = [];
  const failedResponses = [];
  let page;
  try {
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    page = await context.newPage();
    page.on('pageerror', (error) => errors.push(String(error)));
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    page.on('response', (response) => {
      if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() });
    });
    await page.goto(info.url + '/visualization/cesium/' + info.run_id,
      { waitUntil: 'domcontentloaded', timeout: 60000 });
    const debugUrl = new URL(page.url());
    debugUrl.searchParams.set('debug_payload', '1');
    await page.goto(debugUrl.toString(), { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForFunction((count) => typeof viewer !== 'undefined'
      && document.querySelectorAll('.payload-tile').length === count,
    expectedCount, { timeout: 60000 });
    await page.waitForFunction((count) => Array.from(document.querySelectorAll('.payload-tile canvas'))
      .length === count && Array.from(document.querySelectorAll('.payload-tile canvas'))
      .every((canvas) => canvas.dataset.renderSequence),
    expectedCount, { timeout: 120000 });

    await page.evaluate(() => {
      viewer.clock.currentTime = Cesium.JulianDate.clone(viewer.clock.startTime);
      viewer.clock.multiplier = 1;
      viewer.clock.shouldAnimate = true;
      if (typeof gc === 'function') gc();
    });
    const heapStart = await page.evaluate(() => performance.memory
      ? performance.memory.usedJSHeapSize : null);
    const histories = new Map();
    const samples = [];

    async function sample() {
      const value = await page.evaluate(() => {
        const tiles = Array.from(document.querySelectorAll('.payload-tile')).map((tile) => {
          const canvas = tile.querySelector('canvas');
          let pixelSignature = null;
          try {
            const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            let sum = 0;
            for (let offset = 0; offset < data.length; offset += 4096) {
              sum = (sum + data[offset] * 3 + data[offset + 1] * 5
                + data[offset + 2] * 7 + data[offset + 3]) >>> 0;
            }
            pixelSignature = sum;
          } catch (_error) {}
          return {
            id: tile.dataset.satelliteId,
            owner: canvas.dataset.satelliteId || null,
            time: canvas.dataset.simulationTime || null,
            sequence: Number(canvas.dataset.renderSequence || 0),
            signature: pixelSignature,
            selected: tile.classList.contains('is-selected'),
            state: tile.querySelector('.payload-tile-state').textContent
          };
        });
        const gl = viewer._payloadViewer.scene.context._gl;
        return {
          simulationTime: Cesium.JulianDate.toIso8601(viewer.clock.currentTime),
          shouldAnimate: viewer.clock.shouldAnimate,
          tiles: tiles,
          scheduler: viewer._payloadRenderScheduler.getState(),
          webglError: gl.getError(),
          diagnostics: viewer._payloadRenderDiagnostics.slice(),
          selectedCount: document.querySelectorAll('.payload-tile.is-selected').length
        };
      });
      assert.equal(value.tiles.length, expectedCount);
      assert.equal(value.webglError, 0, JSON.stringify(value));
      for (const tile of value.tiles) {
        assert.equal(tile.owner, tile.id, 'cross-window frame ownership: ' + JSON.stringify(tile));
        assert.ok(tile.sequence > 0 && tile.time, JSON.stringify(tile));
        if (!histories.has(tile.id)) histories.set(tile.id, { times: new Set(), lastSequence: 0 });
        const history = histories.get(tile.id);
        assert.ok(tile.sequence >= history.lastSequence, 'render sequence moved backwards');
        history.lastSequence = tile.sequence;
        history.times.add(tile.time);
      }
      samples.push(value);
    }

    for (let second = 0; second < soakSeconds; second += 1) {
      if (second === 5) await page.evaluate(() => document.querySelectorAll('.payload-tile')[0].click());
      if (second === 8) await page.evaluate(() => { viewer.clock.multiplier = 60; });
      if (second === 12 && expectedCount > 1) {
        await page.evaluate(() => document.querySelectorAll('.payload-tile')[1].click());
      }
      if (second === 16) await page.evaluate(() => { viewer.clock.shouldAnimate = false; });
      if (second === 17) await page.evaluate(() => { viewer.clock.shouldAnimate = true; });
      if (second === 21) await page.keyboard.press('Escape');
      if (second === 24) await page.evaluate(() => document.querySelectorAll('.payload-tile')[0].click());
      if (second === 26) await page.evaluate(() => document.querySelectorAll('.payload-tile')[0].click());
      await page.waitForTimeout(1000);
      await sample();
    }

    await page.evaluate(() => { viewer.clock.shouldAnimate = false; if (typeof gc === 'function') gc(); });
    const heapEnd = await page.evaluate(() => performance.memory
      ? performance.memory.usedJSHeapSize : null);
    const final = samples[samples.length - 1];
    const commits = final.diagnostics.filter((entry) => entry.event === 'commit');
    assert.ok(commits.length > 0, 'no renderer commit diagnostics');
    assert.ok(commits.every((entry) => entry.tilesLoaded
      && entry.pendingTerrainOrImageryTiles === 0 && !entry.contextLost),
    JSON.stringify(commits.filter((entry) => !entry.tilesLoaded
      || entry.pendingTerrainOrImageryTiles !== 0 || entry.contextLost).slice(0, 3)));
    assert.ok(!final.diagnostics.some((entry) => entry.event === 'context-lost'));
    for (const [id, history] of histories) {
      assert.ok(history.times.size >= 2, id + ' did not receive a second complete simulation frame');
    }
    if (heapStart != null && heapEnd != null) {
      assert.ok(heapEnd - heapStart < 256 * 1024 * 1024,
        'unbounded heap growth: ' + JSON.stringify({ heapStart, heapEnd }));
    }
    assert.equal(errors.length, 0, JSON.stringify({ errors, failedResponses }));
    assert.equal(failedResponses.length, 0, JSON.stringify(failedResponses));
    console.log(JSON.stringify({
      satelliteCount: expectedCount,
      soakSeconds: soakSeconds,
      samples: samples.length,
      completeCommitsInDiagnosticWindow: commits.length,
      minimumUniqueTimes: Math.min(...Array.from(histories.values()).map((item) => item.times.size)),
      heapStart: heapStart,
      heapEnd: heapEnd,
      finalSelectedCount: final.selectedCount,
      webglErrors: 0,
      consoleErrors: 0,
      failedResponses: 0
    }));
  } finally {
    await browser.close();
    if (fs.existsSync(coord)) fs.writeFileSync(coord, JSON.stringify({ ...info, stop: true }));
  }
})().catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
