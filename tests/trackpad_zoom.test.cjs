const assert = require('node:assert/strict');
const trackpadZoom = require('../draw/trackpad-zoom.js');

const listeners = new Map();
const canvas = {
  addEventListener(type, listener, options) { listeners.set(type, {listener, options}); },
  removeEventListener(type, listener) {
    if (listeners.get(type)?.listener === listener) listeners.delete(type);
  }
};
const calls = [];
const controller = {zoomEventTypes: ['right-drag']};
const viewer = {
  scene: {canvas, screenSpaceCameraController: controller,
          requestRender() { calls.push(['render']); }},
  camera: {
    positionCartographic: {height: 1000},
    zoomIn(amount) { calls.push(['in', amount]); },
    zoomOut(amount) { calls.push(['out', amount]); }
  }
};
const remove = trackpadZoom.install(viewer, {
  CameraEventType: {RIGHT_DRAG: 'right-drag', WHEEL: 'wheel', PINCH: 'pinch'}
});

assert.equal(controller.enableZoom, true);
assert.deepEqual(controller.zoomEventTypes, ['right-drag', 'wheel', 'pinch']);
assert.equal(listeners.get('wheel').options.passive, false);

let prevented = false;
let stopped = false;
listeners.get('wheel').listener({
  ctrlKey: true, cancelable: true, deltaMode: 0, deltaY: -20,
  preventDefault() { prevented = true; },
  stopImmediatePropagation() { stopped = true; }
});
assert.equal(prevented, true);
assert.equal(stopped, true);
assert.equal(calls[0][0], 'in');
assert.ok(calls[0][1] > 0 && calls[0][1] <= 250);
assert.deepEqual(calls[1], ['render']);

const before = calls.length;
listeners.get('wheel').listener({ctrlKey: false, cancelable: true, deltaY: 20});
assert.equal(calls.length, before, 'ordinary wheel events must remain Cesium-owned');

remove();
assert.equal(listeners.size, 0);
console.log('trackpad zoom tests passed');
