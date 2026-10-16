const assert = require('node:assert/strict');
const policy = require('../draw/replay-build-policy.js');

assert.equal(policy.action('NOT_REQUESTED'), 'AUTO_BUILD');
assert.equal(policy.action('BUILDING'), 'POLL');
assert.equal(policy.action('FAILED'), 'MANUAL_RETRY');
assert.equal(policy.action('READY'), 'LOAD');
assert.throws(() => policy.action('UNKNOWN'), /Unknown replay status/);
console.log('replay auto-build policy tests passed');
