(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FixedPayloadState = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const add = (a, b) => a.map((v, i) => v + b[i]);
  const sub = (a, b) => a.map((v, i) => v - b[i]);
  const scale = (a, s) => a.map((v) => v * s);
  const dot = (a, b) => a.reduce((sum, v, i) => sum + v * b[i], 0);
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  function normalize(a) {
    const length = Math.sqrt(dot(a, a));
    if (!Number.isFinite(length) || length < 1e-12) throw new Error('cannot normalize zero/non-finite vector');
    return scale(a, 1 / length);
  }
  function normalizeQuaternion(q) {
    const value = normalize(q);
    return value[3] < 0 ? scale(value, -1) : value;
  }
  function conjugate(q) { return [-q[0], -q[1], -q[2], q[3]]; }
  function multiply(a, b) {
    return normalizeQuaternion([
      a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
      a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
      a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
      a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]
    ]);
  }
  function rotate(q, v) {
    const p = [v[0], v[1], v[2], 0];
    const rawMultiply = (a, b) => [
      a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
      a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
      a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
      a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]
    ];
    return rawMultiply(rawMultiply(q, p), conjugate(q)).slice(0, 3);
  }
  function matrixQuaternion(columns) {
    const m00 = columns[0][0], m01 = columns[1][0], m02 = columns[2][0];
    const m10 = columns[0][1], m11 = columns[1][1], m12 = columns[2][1];
    const m20 = columns[0][2], m21 = columns[1][2], m22 = columns[2][2];
    const trace = m00 + m11 + m22;
    let x, y, z, w, s;
    if (trace > 0) {
      s = Math.sqrt(trace + 1) * 2; w = 0.25 * s; x = (m21 - m12) / s; y = (m02 - m20) / s; z = (m10 - m01) / s;
    } else if (m00 > m11 && m00 > m22) {
      s = Math.sqrt(1 + m00 - m11 - m22) * 2; w = (m21 - m12) / s; x = 0.25 * s; y = (m01 + m10) / s; z = (m02 + m20) / s;
    } else if (m11 > m22) {
      s = Math.sqrt(1 + m11 - m00 - m22) * 2; w = (m02 - m20) / s; x = (m01 + m10) / s; y = 0.25 * s; z = (m12 + m21) / s;
    } else {
      s = Math.sqrt(1 + m22 - m00 - m11) * 2; w = (m10 - m01) / s; x = (m02 + m20) / s; y = (m12 + m21) / s; z = 0.25 * s;
    }
    return normalizeQuaternion([x, y, z, w]);
  }
  function pointingQuaternion(position, target) {
    const forward = normalize(sub(target, position));
    let reference = [0, 0, 1];
    if (Math.abs(dot(forward, reference)) > 0.98) reference = [0, 1, 0];
    const right = normalize(cross(forward, reference));
    const up = normalize(cross(right, forward));
    return matrixQuaternion([right, up, scale(forward, -1)]);
  }
  function slerp(a, b, u) {
    let qa = normalizeQuaternion(a), qb = normalizeQuaternion(b);
    let cosine = dot(qa, qb);
    if (cosine < 0) { qb = scale(qb, -1); cosine = -cosine; }
    const t = Math.max(0, Math.min(1, u));
    if (cosine > 0.9995) return normalizeQuaternion(add(scale(qa, 1 - t), scale(qb, t)));
    const angle = Math.acos(Math.max(-1, Math.min(1, cosine)));
    return normalizeQuaternion(add(scale(qa, Math.sin((1 - t) * angle) / Math.sin(angle)), scale(qb, Math.sin(t * angle) / Math.sin(angle))));
  }
  const milliseconds = (value) => new Date(value).getTime();
  function phaseAt(segments, satelliteId, time) {
    const instant = milliseconds(time);
    return segments.find((segment) => segment.satellite_id === satelliteId && milliseconds(segment.start_time) <= instant && instant < milliseconds(segment.end_time)) || null;
  }
  function evaluateSatelliteState(replay, satelliteId, time, positionAt, targetPosition) {
    const position = positionAt(satelliteId, time);
    if (!position) return { satellite_id: satelliteId, phase: 'IDLE', quality: 'missing', warnings: ['ORBIT_DATA_MISSING'] };
    const satellite = replay.satellites.find((item) => item.id === satelliteId);
    if (!satellite) throw new Error('unknown satellite: ' + satelliteId);
    const timeline = replay.segments.filter((item) => item.satellite_id === satelliteId).sort((a, b) => milliseconds(a.start_time) - milliseconds(b.start_time));
    const active = phaseAt(timeline, satelliteId, time);
    const observations = timeline.filter((item) => item.phase === 'OBSERVING');
    let cameraQuaternion, taskId = active && active.task_id, sensorId = active && active.sensor_id;
    if (active && active.phase === 'OBSERVING') {
      cameraQuaternion = pointingQuaternion(position, targetPosition(active.task_id));
    } else if (active && active.phase === 'SLEWING') {
      const previous = observations.find((item) => item.assignment_ordinal === active.from_assignment_ordinal);
      const next = observations.find((item) => item.assignment_ordinal === active.assignment_ordinal);
      const qa = pointingQuaternion(positionAt(satelliteId, previous.end_time), targetPosition(previous.task_id));
      const qb = pointingQuaternion(positionAt(satelliteId, next.start_time), targetPosition(next.task_id));
      const u = (milliseconds(time) - milliseconds(active.start_time)) / (milliseconds(active.end_time) - milliseconds(active.start_time));
      cameraQuaternion = slerp(qa, qb, u);
    } else {
      const earlier = observations.filter((item) => milliseconds(item.end_time) <= milliseconds(time)).pop();
      const anchor = earlier || observations[0];
      cameraQuaternion = anchor
        ? pointingQuaternion(positionAt(satelliteId, earlier ? anchor.end_time : anchor.start_time), targetPosition(anchor.task_id))
        : pointingQuaternion(position, [0, 0, 0]);
      taskId = null; sensorId = null;
    }
    const sensor = satellite.sensors.find((item) => item.sensor_id === sensorId) || satellite.sensors[0];
    const mount = sensor ? sensor.sensor_mount_quaternion_xyzw : [0, 0, 0, 1];
    const bodyQuaternion = multiply(cameraQuaternion, conjugate(mount));
    return {
      satellite_id: satelliteId, position_ecef_m: position,
      body_to_ecef_quaternion_xyzw: bodyQuaternion, camera_to_ecef_quaternion_xyzw: cameraQuaternion,
      direction_ecef: rotate(cameraQuaternion, [0, 0, -1]), up_ecef: rotate(cameraQuaternion, [0, 1, 0]),
      phase: active ? active.phase : 'IDLE', task_id: taskId, sensor_id: sensorId,
      activation_time: active && active.activation_time, cone_visible: Boolean(active),
      quality: replay.manifest.attitude_source, warnings: replay.warnings || []
    };
  }
  return { normalizeQuaternion, multiply, rotate, pointingQuaternion, slerp, phaseAt, evaluateSatelliteState };
}));
