(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CameraDiagnostics = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function install(viewer, Cesium, options) {
    options = options || {};
    if (!viewer || !Cesium || options.enabled !== true) return null;
    const records = [];
    let previous = null;
    let previousGeneration = viewer._cameraControlGeneration || 0;
    let ignoreFrames = 0;
    const scratchPosition = new Cesium.Cartesian3();
    const scratchDelta = new Cesium.Cartesian3();
    const array = (value) => value ? [value.x, value.y, value.z] : null;
    const trackedId = () => {
      const entity = viewer.trackedEntity;
      return entity && (entity.id || entity._id) || null;
    };

    function sample() {
      const generation = viewer._cameraControlGeneration || 0;
      if (generation !== previousGeneration) {
        previousGeneration = generation;
        ignoreFrames = 3;
      }
      const entity = viewer.trackedEntity;
      const satellitePosition = entity && entity.position
        ? entity.position.getValue(viewer.clock.currentTime, scratchPosition) : null;
      const range = satellitePosition ? Cesium.Cartesian3.magnitude(Cesium.Cartesian3.subtract(
        viewer.camera.positionWC, satellitePosition, scratchDelta
      )) : null;
      const direction = Cesium.Cartesian3.clone(viewer.camera.directionWC);
      let directionStepDeg = 0;
      if (previous && previous.direction) {
        directionStepDeg = Cesium.Math.toDegrees(Math.acos(Cesium.Math.clamp(
          Cesium.Cartesian3.dot(previous.direction, direction), -1, 1
        )));
      }
      const rangeRatio = previous && range && previous.range
        ? Math.max(range / previous.range, previous.range / range) : 1;
      const discontinuity = ignoreFrames === 0 && previous
        && previous.trackedId === trackedId()
        && (directionStepDeg > 12 || rangeRatio > 1.5);
      if (discontinuity) {
        const orientation = entity && entity.orientation
          ? entity.orientation.getValue(viewer.clock.currentTime) : null;
        const record = {
          simulationTime: Cesium.JulianDate.toIso8601(viewer.clock.currentTime),
          trackedId: trackedId(),
          controlMode: viewer._cameraControlSource || (entity ? 'cesium-entity-tracking' : 'user'),
          cameraPositionWC: array(viewer.camera.positionWC),
          directionWC: array(viewer.camera.directionWC),
          upWC: array(viewer.camera.upWC),
          rightWC: array(viewer.camera.rightWC),
          cameraTransform: Array.from(viewer.camera.transform),
          satellitePositionECEF: array(satellitePosition),
          satelliteOrientation: orientation ? [orientation.x, orientation.y, orientation.z, orientation.w] : null,
          model: entity && entity.model ? {
            show: entity.model.show && entity.model.show.getValue(viewer.clock.currentTime),
            scale: entity.model.scale && entity.model.scale.getValue(viewer.clock.currentTime),
            minimumPixelSize: entity.model.minimumPixelSize && entity.model.minimumPixelSize.getValue(viewer.clock.currentTime),
            maximumScale: entity.model.maximumScale && entity.model.maximumScale.getValue(viewer.clock.currentTime)
          } : null,
          inViewport: satellitePosition
            ? Boolean(Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene, satellitePosition)) : null,
          directionStepDeg: directionStepDeg,
          rangeRatio: rangeRatio,
          source: 'scene.postRender'
        };
        records.push(record);
        if (records.length > 50) records.shift();
        console.warn('[camera-discontinuity]', record);
      }
      previous = { direction: direction, range: range, trackedId: trackedId() };
      if (ignoreFrames > 0) ignoreFrames -= 1;
    }
    viewer.scene.postRender.addEventListener(sample);
    const controller = {
      records: records,
      snapshot: () => records.slice(),
      destroy: () => viewer.scene.postRender.removeEventListener(sample)
    };
    viewer._cameraDiagnostics = controller;
    return controller;
  }

  return { install };
}));
