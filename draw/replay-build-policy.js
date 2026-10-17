(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ReplayBuildPolicy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function action(status) {
    if (status === 'NOT_REQUESTED') return 'AUTO_BUILD';
    if (status === 'BUILDING') return 'POLL';
    if (status === 'FAILED') return 'MANUAL_RETRY';
    if (status === 'READY') return 'LOAD';
    throw new Error('Unknown replay status: ' + status);
  }

  return {action};
});
