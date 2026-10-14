(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FixedPayloadGeometry = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const add = (a, b) => a.map((value, index) => value + b[index]);

  function phaseStyle(phase) {
    if (phase === 'SLEWING') {
      return { visible: true, name: 'slewing', rgba: [1.0, 0.55, 0.0, 0.24] };
    }
    if (phase === 'OBSERVING') {
      return { visible: true, name: 'observing', rgba: [0.15, 1.0, 0.35, 0.28] };
    }
    return { visible: false, name: 'idle', rgba: [0.5, 0.5, 0.5, 0.0] };
  }

  function boundaryRays(horizontalFullFovDeg, verticalFullFovDeg, samplesPerEdge) {
    const horizontal = Number(horizontalFullFovDeg);
    const vertical = Number(verticalFullFovDeg);
    const samples = Number(samplesPerEdge == null ? 4 : samplesPerEdge);
    if (!(horizontal > 0 && horizontal < 180) || !(vertical > 0 && vertical < 180)) {
      throw new Error('full FOV angles must be between 0 and 180 degrees');
    }
    if (!Number.isInteger(samples) || samples < 1 || samples > 64) {
      throw new Error('samplesPerEdge must be an integer in [1, 64]');
    }
    const x = Math.tan(horizontal * Math.PI / 360);
    const y = Math.tan(vertical * Math.PI / 360);
    const corners = [[-x, y], [x, y], [x, -y], [-x, -y]];
    const rays = [];
    for (let edge = 0; edge < corners.length; edge += 1) {
      const start = corners[edge];
      const end = corners[(edge + 1) % corners.length];
      for (let index = 0; index < samples; index += 1) {
        const amount = index / samples;
        const raw = [
          start[0] + (end[0] - start[0]) * amount,
          start[1] + (end[1] - start[1]) * amount,
          -1
        ];
        const length = Math.hypot(raw[0], raw[1], raw[2]);
        rays.push(raw.map((value) => value / length));
      }
    }
    return rays;
  }

  function sensorFrame(state, sensor, rotateVector, samplesPerEdge) {
    if (!state || !state.position_ecef_m || !state.camera_to_ecef_quaternion_xyzw) {
      return null;
    }
    if (!sensor) throw new Error('active sensor display configuration is missing');
    const bodyOffset = sensor.sensor_offset_body_m || [0, 0, 0];
    const ecefOffset = rotateVector(state.body_to_ecef_quaternion_xyzw, bodyOffset);
    const origin = add(state.position_ecef_m, ecefOffset);
    const cameraQuaternion = state.camera_to_ecef_quaternion_xyzw;
    return {
      origin_ecef_m: origin,
      center_direction_ecef: rotateVector(cameraQuaternion, [0, 0, -1]),
      boundary_directions_ecef: boundaryRays(
        sensor.horizontal_full_fov_deg,
        sensor.vertical_full_fov_deg,
        samplesPerEdge
      ).map((ray) => rotateVector(cameraQuaternion, ray)),
      fov_interpretation: sensor.fov_interpretation,
      target_altitude_is_separate_from_ellipsoid_hit: true
    };
  }

  function intersectFrame(frame, intersectDirection) {
    if (!frame) return null;
    const centerHit = intersectDirection(frame.origin_ecef_m, frame.center_direction_ecef);
    const boundaryHits = frame.boundary_directions_ecef.map(
      (direction) => intersectDirection(frame.origin_ecef_m, direction)
    );
    const hitCount = boundaryHits.filter(Boolean).length;
    let status = 'COMPLETE';
    if (hitCount === 0) status = 'NO_BOUNDARY_INTERSECTION';
    else if (hitCount !== boundaryHits.length) status = 'PARTIAL_HORIZON';
    if (!centerHit && status === 'COMPLETE') status = 'CENTER_MISS';
    return {
      origin_ecef_m: frame.origin_ecef_m,
      center_hit_ecef_m: centerHit,
      boundary_hits_ecef_m: boundaryHits,
      coverage_ecef_m: status === 'COMPLETE' ? boundaryHits : null,
      hit_count: hitCount,
      ray_count: boundaryHits.length,
      status: status,
      fov_interpretation: frame.fov_interpretation,
      target_altitude_is_separate_from_ellipsoid_hit: true
    };
  }

  return { boundaryRays, intersectFrame, phaseStyle, sensorFrame };
}));
