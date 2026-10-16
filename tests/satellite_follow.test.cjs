const assert = require('node:assert/strict');
const follow = require('../draw/satellite-follow.js');

const satelliteA = { id: 'SAT-A', position: {}, orientation: { physical: 'A' }, path: {} };
const satelliteB = { id: 'SAT-B', position: {}, orientation: { physical: 'B' }, path: {} };
const target = { id: 'M001', position: {} };
const byId = new Map([[satelliteA.id, satelliteA], [satelliteB.id, satelliteB], [target.id, target]]);
const viewer = { selectedEntity: undefined, trackedEntity: undefined };
const dataSource = { entities: { getById: (id) => byId.get(id) } };
const enu = 101;

const controller = follow.install(viewer, dataSource, ['SAT-A', 'SAT-B', 'missing'], enu);
assert.equal(controller.entities.size, 2);
assert.equal(satelliteA.trackingReferenceFrame, enu);
assert.equal(satelliteB.trackingReferenceFrame, enu);
assert.deepEqual(satelliteA.orientation, { physical: 'A' }, 'physical attitude must remain untouched');
assert.equal(target.trackingReferenceFrame, undefined);

assert.equal(controller.select('SAT-A'), true);
assert.equal(viewer.selectedEntity, satelliteA);
assert.equal(viewer.trackedEntity, undefined, 'selection must not start camera tracking implicitly');

viewer.trackedEntity = satelliteA;
assert.equal(controller.select('SAT-B'), true);
assert.equal(viewer.selectedEntity, satelliteB);
assert.equal(viewer.trackedEntity, satelliteB, 'an active follow must move to the selected task satellite');

viewer.trackedEntity = target;
assert.equal(controller.select('SAT-A'), true);
assert.equal(viewer.trackedEntity, target, 'non-satellite camera ownership must not be overwritten');
assert.equal(controller.select('unknown'), false);
console.log('satellite follow tests passed');
