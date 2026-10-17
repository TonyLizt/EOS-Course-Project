const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const root = process.env.EOS_INTERPOLATION_FIXTURE;
  if (!root) throw new Error('set EOS_INTERPOLATION_FIXTURE');
  const read = name => JSON.parse(fs.readFileSync(root + '/' + name + '.czml', 'utf8'));
  const data = {reference:read('reference-1s'), baseline:read('baseline-300s'), candidate:read('candidate-30s')};
  const build = JSON.parse(fs.readFileSync(root + '/build-metrics.json', 'utf8'));
  const browser = await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:8099/tests/browser/camera-continuity-smoke.html',{waitUntil:'domcontentloaded'});
    await page.waitForFunction(() => typeof Cesium !== 'undefined',null,{timeout:60000});
    const result = await page.evaluate(async ({data,satellites}) => {
      const sources = {};
      for (const [key,value] of Object.entries(data)) sources[key] = await Cesium.CzmlDataSource.load(value);
      const epoch = Cesium.JulianDate.fromIso8601(data.reference[0].clock.currentTime);
      const results = {};
      for (const satellite of satellites) {
        const errors = {baseline:[],candidate:[]};
        const checkpoints = [];
        const offsets = new Set();
        for (let offset=10; offset<1800; offset+=10) offsets.add(offset);
        for (let interval=0; interval<1800; interval+=300) {
          for (const inside of [75,150,225]) offsets.add(interval+inside);
        }
        for (const offset of Array.from(offsets).sort((a,b)=>a-b)) {
          const time=Cesium.JulianDate.addSeconds(epoch,offset,new Cesium.JulianDate());
          const truth=sources.reference.entities.getById(satellite).position.getValue(time);
          const checkpoint = offset % 300 === 75 || offset % 300 === 150 || offset % 300 === 225
            ? {offset_s:offset} : null;
          for (const key of ['baseline','candidate']) {
            const actual=sources[key].entities.getById(satellite).position.getValue(time);
            const error=Cesium.Cartesian3.distance(actual,truth);
            errors[key].push(error);
            if (checkpoint) checkpoint[key+'_m']=error;
          }
          if (checkpoint) checkpoints.push(checkpoint);
        }
        const summary = values => {
          const ordered=values.slice().sort((a,b)=>a-b);
          return {max_m:Math.max(...values),rms_m:Math.sqrt(values.reduce((s,v)=>s+v*v,0)/values.length),
            p95_m:ordered[Math.floor((ordered.length-1)*.95)]};
        };
        results[satellite]={baseline:summary(errors.baseline),candidate:summary(errors.candidate),checkpoints};
      }
      return results;
    }, {data,satellites:build.satellites});
    for (const satellite of build.satellites) {
      assert.ok(result[satellite].baseline.max_m > 50000, JSON.stringify(result[satellite]));
      assert.ok(result[satellite].candidate.max_m <= 1000, JSON.stringify(result[satellite]));
    }
    console.log('CESIUM_INTERPOLATION_ACCURACY_OK '+JSON.stringify({build,result}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error.stack);process.exitCode=1;});
