const assert = require('node:assert/strict');
const { createScheduler } = require('../draw/fixed-payload-renderer.js');

const callbacks = [];
const prepared = [];
const rendered = [];
const committed = [];
const events = [];
const readiness = new Map();
const scheduler = createScheduler({
  requestFrame(callback) { callbacks.push(callback); return callbacks.length; },
  prepare(job) { prepared.push([job.id, job.payload.time]); readiness.set(job.sequence, 0); },
  render(job) { rendered.push([job.id, job.payload.time]); },
  isReady(job) {
    const attempt = readiness.get(job.sequence) + 1;
    readiness.set(job.sequence, attempt);
    return { ready: attempt >= 2, tilesLoaded: attempt >= 2 };
  },
  commit(job) { committed.push([job.id, job.payload.time]); },
  onEvent(event) { events.push([event.type, event.job && event.job.id]); },
  stableFrames: 2,
  maxFrames: 10
});

function frame() {
  const callback = callbacks.shift();
  assert.ok(callback, 'expected a scheduled animation frame');
  callback(rendered.length * 16);
}

scheduler.setPriority('selected');
scheduler.request('selected', { time: 1 });
scheduler.request('other', { time: 1 });
frame(); // selected starts, incomplete
scheduler.request('selected', { time: 2 }); // must not replace the active time=1 frame
frame(); // first ready frame
frame(); // second ready frame and atomic commit
assert.deepEqual(committed, [['selected', 1]]);
assert.deepEqual(prepared[0], ['selected', 1]);

frame(); // fairness: the normal tile starts before selected time=2
frame();
frame();
assert.deepEqual(committed[1], ['other', 1]);
frame();
frame();
frame();
assert.deepEqual(committed[2], ['selected', 2]);

scheduler.request('other', { time: 3 });
scheduler.request('other', { time: 4 });
frame();
frame();
frame();
assert.deepEqual(committed[3], ['other', 4], 'queued frames must coalesce to the latest time');
assert.ok(events.some(([type]) => type === 'render'));
assert.equal(scheduler.getState().activeId, null);
scheduler.destroy();
assert.equal(scheduler.getState().destroyed, true);

// A 50-satellite queue must never commit one job's payload under another ID.
const manyCallbacks = [];
const manyCommits = [];
const many = createScheduler({
  requestFrame(callback) { manyCallbacks.push(callback); return manyCallbacks.length; },
  prepare() {},
  render() {},
  isReady() { return true; },
  commit(job) { manyCommits.push([job.id, job.payload.owner]); },
  stableFrames: 1
});
for (let index = 0; index < 50; index += 1) {
  const id = 'SAT-' + index;
  many.request(id, { owner: id });
}
while (manyCallbacks.length) manyCallbacks.shift()(manyCommits.length * 16);
assert.equal(manyCommits.length, 50);
assert.ok(manyCommits.every(([id, owner]) => id === owner));
many.destroy();
console.log('fixed payload renderer scheduler tests passed');
