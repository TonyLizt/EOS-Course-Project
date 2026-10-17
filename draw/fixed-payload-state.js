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
  const WGS84_A = 6378137.0;
  const WGS84_B = 6356752.314245179;
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
  // Keep integer UTC microseconds internally. Date alone drops the final
  // three fractional digits; floating epoch milliseconds cannot represent them.
  function microseconds(value) {
    let text = value;
    if (typeof text === 'string') {
      text = text.trim();
      // The existing legacy scheduler contract defines naive timestamps as UTC.
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text)) text += 'Z';
    }
    const ms = new Date(text).getTime();
    if (!Number.isFinite(ms)) throw new Error('invalid UTC replay time: ' + String(value));
    const fraction = typeof text === 'string' && text.match(/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/);
    const us = fraction ? BigInt(fraction[1].slice(0, 6).padEnd(6, '0')) : 0n;
    return BigInt(ms) * 1000n + us % 1000n;
  }
  function phaseAt(segments, satelliteId, time) {
    const instant = microseconds(time);
    return segments.find((segment) => segment.satellite_id === satelliteId && microseconds(segment.start_time) <= instant && instant < microseconds(segment.end_time)) || null;
  }
  function targetVisibility(position, target) {
    if (!Array.isArray(position) || !Array.isArray(target)
        || position.length < 3 || target.length < 3) return 'UNKNOWN';
    // A target can see the satellite only when it is above the tangent plane
    // of the WGS84 ellipsoid at that target.  This catches schedule/replay
    // mismatches before an occluded target is presented as observable.
    const normal = [
      target[0] / (WGS84_A * WGS84_A),
      target[1] / (WGS84_A * WGS84_A),
      target[2] / (WGS84_B * WGS84_B)
    ];
    const aboveHorizon = dot(sub(position, target), normal);
    return Number.isFinite(aboveHorizon) && aboveHorizon > 0
      ? 'VISIBLE' : 'EARTH_OCCLUDED';
  }
  // 服务端 READY 样本是正式页面的姿态来源；缓存索引避免每帧全表筛选。
  const sampleIndexes = new WeakMap();
  // The same bounded degree-five position interpolation as replay/runtime.py.
  // UTC microsecond indexing and quaternion SLERP retain their P0 semantics.
  function interpolatePosition(rows, time, lower) {
    const count = Math.min(6, rows.length);
    const first = Math.max(0, Math.min(lower - Math.floor((count - 2) / 2), rows.length - count));
    const nodes = rows.slice(first, first + count);
    const offsets = nodes.map(row => Number(row.instant - time) / 1000000);
    const exact = offsets.indexOf(0);
    if (exact >= 0) return nodes[exact].position_ecef_m.slice();
    const position = [0, 0, 0];
    for (let j = 0; j < count; j++) {
      let coefficient = 1;
      for (let k = 0; k < count; k++) {
        if (j !== k) coefficient *= -offsets[k] / (offsets[j] - offsets[k]);
      }
      for (let axis = 0; axis < 3; axis++) position[axis] += coefficient * nodes[j].position_ecef_m[axis];
    }
    return position;
  }
  function sampleState(replay, satelliteId, time, targetPosition) {
    let index = sampleIndexes.get(replay);
    if (!index) {
      index = {samples:new Map(), satellites:new Map(), segments:new Map()};
      for (const satellite of replay.satellites) index.satellites.set(satellite.id,satellite);
      for (const row of replay.samples) {
        if (!index.samples.has(row.satellite_id)) index.samples.set(row.satellite_id, []);
        index.samples.get(row.satellite_id).push({...row, instant: microseconds(row.time)});
      }
      for (const row of replay.segments) {
        if (!index.segments.has(row.satellite_id)) index.segments.set(row.satellite_id,[]);
        index.segments.get(row.satellite_id).push({...row,start:microseconds(row.start_time),end:microseconds(row.end_time)});
      }
      for (const rows of index.samples.values()) rows.sort((a,b) => Number(a.instant-b.instant));
      for (const rows of index.segments.values()) rows.sort((a,b) => Number(a.start-b.start));
      sampleIndexes.set(replay,index);
    }
    const rows = index.samples.get(satelliteId) || [];
    const t = microseconds(time);
    if (!rows.length || t < rows[0].instant || t > rows[rows.length-1].instant) {
      return {satellite_id:satelliteId, phase:'IDLE', quality:'missing', warnings:['ORBIT_DATA_MISSING']};
    }
    let lo=0, hi=rows.length-1;
    while (hi-lo>1) {
      const mid=(lo+hi)>>1;
      if (rows[mid].instant<=t) lo=mid; else hi=mid;
    }
    const a=rows[lo], b=rows[hi];
    const u=b.instant===a.instant ? 0 : Number(t-a.instant)/Number(b.instant-a.instant);
    const body=slerp(a.body_to_ecef_quaternion_xyzw,b.body_to_ecef_quaternion_xyzw,u);
    const position=interpolatePosition(rows,t,lo);
    const satellite=index.satellites.get(satelliteId);
    // 各星阶段预解析，按绝对时间二分定位；不在每个图元 callback 中扫描全体任务。
    const segments=index.segments.get(satelliteId) || [];
    let left=0,right=segments.length;
    while(left<right) {
      const mid=(left+right)>>1;
      if(segments[mid].start<=t) left=mid+1; else right=mid;
    }
    const candidate=segments[left-1];
    const active=candidate && t<candidate.end ? candidate : null;
    const sensor=satellite.sensors.find(item => active && item.sensor_id===active.sensor_id) || satellite.sensors[0];
    const camera=multiply(body,sensor ? sensor.sensor_mount_quaternion_xyzw : [0,0,0,1]);
    const target = active && active.task_id && typeof targetPosition === 'function'
      ? targetPosition(active.task_id) : null;
    const visibility = active ? targetVisibility(position, target) : 'NOT_APPLICABLE';
    const geometryValid = !active || visibility === 'VISIBLE';
    const warnings = (replay.warnings || []).slice();
    if (visibility === 'EARTH_OCCLUDED') warnings.push('TARGET_EARTH_OCCLUDED');
    return {
      satellite_id:satelliteId, position_ecef_m:position,
      body_to_ecef_quaternion_xyzw:body, camera_to_ecef_quaternion_xyzw:camera,
      direction_ecef:rotate(camera,[0,0,-1]), up_ecef:rotate(camera,[0,1,0]),
      phase:active ? active.phase : 'IDLE', task_id:active && active.task_id,
      sensor_id:active && active.sensor_id, activation_time:active && active.activation_time,
      cone_visible:Boolean(active) && geometryValid, target_visibility:visibility,
      geometry_valid:geometryValid, quality:a.quality, warnings:warnings
    };
  }
  function evaluateSatelliteState(replay, satelliteId, time, positionAt, targetPosition) {
    if (Array.isArray(replay.samples)) return sampleState(replay, satelliteId, time, targetPosition);
    const position = positionAt(satelliteId, time);
    if (!position) return { satellite_id: satelliteId, phase: 'IDLE', quality: 'missing', warnings: ['ORBIT_DATA_MISSING'] };
    const satellite = replay.satellites.find((item) => item.id === satelliteId);
    if (!satellite) throw new Error('unknown satellite: ' + satelliteId);
    const timeline = replay.segments.filter((item) => item.satellite_id === satelliteId).sort((a, b) => Number(microseconds(a.start_time) - microseconds(b.start_time)));
    const active = phaseAt(timeline, satelliteId, time);
    const observations = timeline.filter((item) => item.phase === 'OBSERVING');
    let cameraQuaternion, taskId = active && active.task_id, sensorId = active && active.sensor_id;
    if (satellite.maneuverability_type !== 'agile') {
      cameraQuaternion = pointingQuaternion(position, [0,0,0]);
    } else if (active && active.phase === 'OBSERVING') {
      cameraQuaternion = pointingQuaternion(position, targetPosition(active.task_id));
    } else if (active && active.phase === 'SLEWING') {
      const previous = observations.find((item) => item.assignment_ordinal === active.from_assignment_ordinal);
      const next = observations.find((item) => item.assignment_ordinal === active.assignment_ordinal);
      const qa = pointingQuaternion(positionAt(satelliteId, previous.end_time), targetPosition(previous.task_id));
      const qb = pointingQuaternion(positionAt(satelliteId, next.start_time), targetPosition(next.task_id));
      const u = Number(microseconds(time) - microseconds(active.start_time)) / Number(microseconds(active.end_time) - microseconds(active.start_time));
      cameraQuaternion = slerp(qa, qb, u);
    } else {
      const earlier = observations.filter((item) => microseconds(item.end_time) <= microseconds(time)).pop();
      const anchor = earlier || observations[0];
      cameraQuaternion = anchor
        ? pointingQuaternion(positionAt(satelliteId, earlier ? anchor.end_time : anchor.start_time), targetPosition(anchor.task_id))
        : pointingQuaternion(position, [0, 0, 0]);
      taskId = null; sensorId = null;
    }
    const sensor = satellite.sensors.find((item) => item.sensor_id === sensorId) || satellite.sensors[0];
    const mount = sensor ? sensor.sensor_mount_quaternion_xyzw : [0, 0, 0, 1];
    const bodyQuaternion = multiply(cameraQuaternion, conjugate(mount));
    const target = taskId && typeof targetPosition === 'function' ? targetPosition(taskId) : null;
    const visibility = active ? targetVisibility(position, target) : 'NOT_APPLICABLE';
    const geometryValid = !active || visibility === 'VISIBLE';
    const warnings = (replay.warnings || []).slice();
    if (visibility === 'EARTH_OCCLUDED') warnings.push('TARGET_EARTH_OCCLUDED');
    return {
      satellite_id: satelliteId, position_ecef_m: position,
      body_to_ecef_quaternion_xyzw: bodyQuaternion, camera_to_ecef_quaternion_xyzw: cameraQuaternion,
      direction_ecef: rotate(cameraQuaternion, [0, 0, -1]), up_ecef: rotate(cameraQuaternion, [0, 1, 0]),
      phase: active ? active.phase : 'IDLE', task_id: taskId, sensor_id: sensorId,
      activation_time: active && active.activation_time,
      cone_visible: Boolean(active) && geometryValid, target_visibility: visibility,
      geometry_valid: geometryValid, quality: replay.manifest.attitude_source, warnings: warnings
    };
  }
  return { normalizeQuaternion, multiply, rotate, pointingQuaternion, slerp, phaseAt,
    targetVisibility, evaluateSatelliteState };
}));
