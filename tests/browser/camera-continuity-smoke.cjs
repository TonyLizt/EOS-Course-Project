const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.EOS_CAMERA_QA_URL;
  if (!base) throw new Error('请设置 EOS_CAMERA_QA_URL');
  const browser = await chromium.launch({headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const errors=[],failedResponses=[];
  try {
    const page = await browser.newPage({viewport:{width:1280,height:800}});
    page.on('pageerror',error => errors.push(String(error)));
    page.on('console',message => { if (message.type()==='error') errors.push(message.text()); });
    page.on('response',response => {
      if (response.status()>=400) failedResponses.push({status:response.status(),url:response.url()});
    });
    await page.goto(base+'/tests/browser/camera-continuity-smoke.html',{waitUntil:'domcontentloaded',timeout:60000});
    await page.waitForFunction(() => window.cameraContinuityReady === true,null,{timeout:60000});
    const result = await page.evaluate(async () => {
      const startWall=performance.now();
      let previousDirection=null, maxDirectionStepDeg=0, minRange=Infinity, maxRange=0;
      let pauseDeltaSec=null, switched=false, samples=0, measuredSamples=0;
      let ignoreUntil=2000; // Cesium applies the initial entity viewFrom once.
      const scratchPosition=new Cesium.Cartesian3();
      const scratchDelta=new Cesium.Cartesian3();
      await new Promise((resolve) => {
        function sample() {
          const elapsed=performance.now()-startWall;
          if (elapsed>=10000 && pauseDeltaSec===null) {
            viewer.clock.shouldAnimate=false;
            const before=Cesium.JulianDate.clone(viewer.clock.currentTime);
            setTimeout(() => {
              pauseDeltaSec=Math.abs(Cesium.JulianDate.secondsDifference(viewer.clock.currentTime,before));
              viewer.clock.shouldAnimate=true;
              requestAnimationFrame(sample);
            },1000);
            return;
          }
          if (elapsed>=16000 && !switched) {
            followController.select('SAT-B');
            switched=true;
            ignoreUntil=elapsed+1500;
            previousDirection=null; // Explicit user switch is allowed to move the camera.
          }
          const tracked=viewer.trackedEntity;
          const position=tracked && tracked.position.getValue(viewer.clock.currentTime,scratchPosition);
          if (position && elapsed>=ignoreUntil) {
            const range=Cesium.Cartesian3.magnitude(Cesium.Cartesian3.subtract(
              viewer.camera.positionWC,position,scratchDelta
            ));
            minRange=Math.min(minRange,range); maxRange=Math.max(maxRange,range);
          }
          const direction=Cesium.Cartesian3.clone(viewer.camera.directionWC);
          if (previousDirection && elapsed>=ignoreUntil) {
            const cosine=Cesium.Math.clamp(Cesium.Cartesian3.dot(previousDirection,direction),-1,1);
            maxDirectionStepDeg=Math.max(maxDirectionStepDeg,Cesium.Math.toDegrees(Math.acos(cosine)));
          }
          previousDirection=elapsed>=ignoreUntil ? direction : null;
          samples+=1;
          if (elapsed>=ignoreUntil) measuredSamples+=1;
          if (elapsed>=31000) resolve(); else requestAnimationFrame(sample);
        }
        requestAnimationFrame(sample);
      });
      viewer.clock.shouldAnimate=false;
      const orientationNow=viewer.trackedEntity.orientation.getValue(viewer.clock.currentTime);
      const oneSecondEarlier=Cesium.JulianDate.addSeconds(
        viewer.clock.currentTime,-1,new Cesium.JulianDate()
      );
      const orientationEarlier=viewer.trackedEntity.orientation.getValue(oneSecondEarlier);
      return {
        samples,measuredSamples,maxDirectionStepDeg,minRange,maxRange,pauseDeltaSec,switched,
        simulatedSeconds:Cesium.JulianDate.secondsDifference(viewer.clock.currentTime,start),
        trackedId:viewer.trackedEntity && viewer.trackedEntity.id,
        trackingFrame:viewer.trackedEntity && viewer.trackedEntity.trackingReferenceFrame,
        enuFrame:Cesium.TrackingReferenceFrame.ENU,
        physicalOrientationDot:Math.abs(Cesium.Quaternion.dot(orientationNow,orientationEarlier))
      };
    });
    assert.ok(result.samples>100,JSON.stringify(result));
    assert.ok(result.measuredSamples>100,JSON.stringify(result));
    assert.ok(result.simulatedSeconds>=1700,JSON.stringify(result));
    assert.ok(result.maxDirectionStepDeg<10,JSON.stringify(result));
    assert.ok(result.maxRange/result.minRange<1.05,JSON.stringify(result));
    assert.ok(result.pauseDeltaSec<0.05,JSON.stringify(result));
    assert.equal(result.switched,true);
    assert.equal(result.trackedId,'SAT-B');
    assert.equal(result.trackingFrame,result.enuFrame);
    assert.ok(result.physicalOrientationDot<0.99,JSON.stringify(result));
    assert.deepEqual(errors,[],JSON.stringify({result,errors,failedResponses}));
    assert.deepEqual(failedResponses,[],JSON.stringify({result,errors,failedResponses}));
    console.log('CAMERA_CONTINUITY_OK '+JSON.stringify({...result,errors,failedResponses}));
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error.stack);process.exitCode=1;});
