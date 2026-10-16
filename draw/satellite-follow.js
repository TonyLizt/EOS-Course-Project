(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SatelliteFollow = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function entityId(entity) {
    return entity && (entity.id || entity._id);
  }

  function install(viewer, dataSource, satelliteIds, trackingReferenceFrame) {
    if (!viewer || !dataSource || !dataSource.entities) {
      throw new Error('viewer and satellite data source are required');
    }
    const ids = new Set(satelliteIds || []);
    const entities = new Map();
    ids.forEach((id) => {
      const entity = dataSource.entities.getById(id);
      if (!entity || !entity.position) return;
      // The user camera follows only the orbital position frame.  The physical
      // body quaternion remains on the rendered entity for the model/sensor.
      entity.trackingReferenceFrame = trackingReferenceFrame;
      entities.set(id, entity);
    });

    function select(satelliteId) {
      const entity = entities.get(satelliteId);
      if (!entity) return false;
      const followedId = entityId(viewer.trackedEntity);
      const keepFollowing = entities.has(followedId);
      viewer.selectedEntity = entity;
      if (keepFollowing && viewer.trackedEntity !== entity) {
        viewer.trackedEntity = entity;
      }
      return true;
    }

    function follow(satelliteId, viewFrom) {
      const entity = entities.get(satelliteId);
      if (!entity) return false;
      if (viewFrom) entity.viewFrom = viewFrom;
      viewer._cameraControlGeneration = (viewer._cameraControlGeneration || 0) + 1;
      viewer._cameraControlSource = 'fixed-payload-grid';
      viewer.selectedEntity = entity;
      viewer.trackedEntity = entity;
      return true;
    }

    function stopAutoFollow(satelliteId) {
      if (entityId(viewer.trackedEntity) !== satelliteId) return false;
      viewer._cameraControlGeneration = (viewer._cameraControlGeneration || 0) + 1;
      viewer._cameraControlSource = 'fixed-payload-grid-release';
      viewer.trackedEntity = undefined;
      return true;
    }

    viewer._selectMainSatellite = select;
    viewer._followMainSatellite = follow;
    viewer._stopMainSatelliteAutoFollow = stopAutoFollow;
    return { entities, select, follow, stopAutoFollow };
  }

  return { install };
}));
