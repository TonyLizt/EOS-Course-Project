(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FixedPayloadView = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function cameraPose(state) {
    if (!state || !Array.isArray(state.position_ecef_m)
        || !Array.isArray(state.direction_ecef) || !Array.isArray(state.up_ecef)) {
      return null;
    }
    return {
      position_ecef_m: state.position_ecef_m.slice(),
      direction_ecef: state.direction_ecef.slice(),
      up_ecef: state.up_ecef.slice(),
      phase: state.phase || 'IDLE',
      task_id: state.task_id || null,
      sensor_id: state.sensor_id || null,
      quality: state.quality || 'missing',
      target_visibility: state.target_visibility || 'UNKNOWN',
      geometry_valid: state.geometry_valid !== false
    };
  }

  function opticalFrustum(sensor) {
    if (!sensor) return null;
    const horizontal = Number(sensor.horizontal_full_fov_deg);
    const vertical = Number(sensor.vertical_full_fov_deg);
    if (!(horizontal > 0 && horizontal < 180) || !(vertical > 0 && vertical < 180)) {
      throw new Error('fixed payload FOV must be between 0 and 180 degrees');
    }
    return {
      horizontal_full_fov_deg: horizontal,
      vertical_full_fov_deg: vertical,
      aspect_ratio: Math.tan(horizontal * Math.PI / 360) / Math.tan(vertical * Math.PI / 360),
      interpretation: sensor.fov_interpretation
    };
  }

  function viewportBox(width, height, opticalAspectRatio) {
    const availableWidth = Math.max(0, Number(width));
    const availableHeight = Math.max(0, Number(height));
    const aspect = Number(opticalAspectRatio);
    if (!(aspect > 0)) throw new Error('optical aspect ratio must be positive');
    let boxWidth = availableWidth;
    let boxHeight = boxWidth / aspect;
    if (boxHeight > availableHeight) {
      boxHeight = availableHeight;
      boxWidth = boxHeight * aspect;
    }
    return {
      width: boxWidth,
      height: boxHeight,
      left: (availableWidth - boxWidth) / 2,
      top: (availableHeight - boxHeight) / 2
    };
  }

  function statusText(satelliteId, pose) {
    if (!satelliteId) return 'No satellite selected';
    if (!pose) return satelliteId + ' | geometry unavailable';
    const visibility = pose.target_visibility === 'EARTH_OCCLUDED'
      ? ' | EARTH OCCLUDED' : pose.target_visibility === 'UNKNOWN' && pose.task_id
        ? ' | visibility unknown' : '';
    return satelliteId + ' | ' + pose.phase + ' | task ' + (pose.task_id || '-')
      + visibility + ' | ' + pose.quality;
  }

  function missionDisplay(mission) {
    if (!mission || !mission.id || !mission.target_location) return null;
    const latitude = Number(mission.target_location.latitude);
    const longitude = Number(mission.target_location.longitude);
    const altitudeM = Number(mission.target_location.altitude_km || 0) * 1000;
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)
        || !Number.isFinite(altitudeM)) return null;
    return {
      id: mission.id,
      latitude: latitude,
      longitude: longitude,
      altitude_m: altitudeM,
      label: mission.id + '\n' + latitude.toFixed(4) + '°, ' + longitude.toFixed(4) + '°'
    };
  }

  return { cameraPose, missionDisplay, opticalFrustum, statusText, viewportBox };
}));
