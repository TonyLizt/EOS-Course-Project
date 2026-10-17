const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../eos_system/web/comparison.js');
const T = require('../eos_system/web/timeline.js');
const run = (id, patch = {}, metrics = {}) => ({run_id: id, status: 'SUCCEEDED', config: {
  scenario_sha256: 'a'.repeat(64), algorithm_code_sha: 'b'.repeat(64),
  scenario_provenance: {scenario_physics_version: 'epoch_fixed_v1'},
  constraints: {agility_profile: 'Standard'}, objective_weights: {w_completion: 1},
  placement_mode: 'earliest', seed: 42, time_budget_s: 60, ...patch
}, metrics: {metric_schema_version: 1, TP: 20, TM: .3, RT: .1, RV: null, ...metrics}});
test('comparison isolates changed scene, source code, constraints, seed and metric schema', () => {
  const base = run('a');
  for (const patch of [{scenario_sha256: 'c'.repeat(64)}, {algorithm_code_sha: 'd'.repeat(64)}, {constraints: {agility_profile: 'Low'}}, {seed: 43}, {time_budget_s: 30}, {objective_weights: {w_profit: 1}}, {placement_mode: 'center'}]) {
    assert.equal(C.groupRuns([base, run('b', patch)]).length, 2);
  }
  assert.equal(C.groupRuns([base, run('b', {}, {metric_schema_version: 2})]).length, 2);
});
test('algorithm parameters differ transparently within a common condition group', () => {
  const groups = C.groupRuns([run('a', {algorithm_id: 'a', algorithm_params: {beam: 1}}), run('b', {algorithm_id: 'b', algorithm_params: {beam: 4}})]);
  assert.equal(groups.length, 1); assert.equal(groups[0].runs.length, 2);
});
test('TM and RT favor smaller values; missing RV and unidentified origins have no winners', () => {
  const g = C.groupRuns([run('a'), run('b', {}, {TM: .1, RT: .2})])[0];
  assert.equal(C.best(g, 'TM', -1), .1); assert.equal(C.best(g, 'RT', -1), .1);
  assert.equal(C.best(g, 'RV', -1), null);
  assert.equal(C.groupRuns([run('a', {algorithm_code_sha: null}), run('b', {algorithm_code_sha: null})]).length, 2);
});
test('legacy naive timestamps are UTC, independent of the browser timezone', () => {
  assert.equal(T.parseTime('2025-11-19T11:23:54'), T.parseTime('2025-11-19T19:23:54+08:00'));
  assert.ok(Number.isNaN(T.parseTime('invalid')));
});
test('viewport zoom, pan clamping and adaptive ticks preserve exact exposure boundaries', () => {
  const raw = [{sat_start_time: '2025-11-19T11:23:54', sat_end_time: '2025-11-19T11:24:04', task_id: 'M009'}];
  const original = JSON.stringify(raw), data = T.normalize(raw), a = data[0];
  const domain = [a.start - 86400000, a.end + 86400000];
  let view = domain;
  for (let i = 0; i < 12; i++) view = T.zoom(view, .5, (a.start + a.end) / 2, domain);
  assert.ok(view[1] - view[0] < 60000); assert.equal(a.end - a.start, 10000);
  assert.equal(JSON.stringify(raw), original);
  assert.deepEqual(T.clampRange(domain[0] - 30000, domain[0], domain), [domain[0], domain[0] + 30000]);
  assert.ok(T.tickStep(30000, 900) < T.tickStep(86400000, 900));
});
