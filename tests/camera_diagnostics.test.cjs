const assert = require('node:assert/strict');
const diagnostics = require('../draw/camera-diagnostics.js');

assert.equal(diagnostics.install({}, {}, { enabled: false }), null);
console.log('camera diagnostics disabled-by-default test passed');
