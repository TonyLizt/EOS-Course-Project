(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TrackpadZoom = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function install(viewer, Cesium, options) {
    if (!viewer || !viewer.scene || !viewer.scene.canvas || !viewer.camera) {
      throw new TypeError('A Cesium viewer with a scene canvas and camera is required');
    }
    const canvas = viewer.scene.canvas;
    const controller = viewer.scene.screenSpaceCameraController;
    const settings = Object.assign({speed: 0.0025, maxFraction: 0.25}, options || {});

    if (controller) {
      controller.enableZoom = true;
      if (Cesium && Cesium.CameraEventType) {
        const eventTypes = Array.isArray(controller.zoomEventTypes)
          ? controller.zoomEventTypes.slice()
          : [Cesium.CameraEventType.RIGHT_DRAG].filter((item) => item !== undefined);
        [Cesium.CameraEventType.WHEEL, Cesium.CameraEventType.PINCH].forEach((item) => {
          if (item !== undefined && !eventTypes.includes(item)) eventTypes.push(item);
        });
        controller.zoomEventTypes = eventTypes;
      }
    }

    function cameraHeight() {
      const cartographic = viewer.camera.positionCartographic;
      if (cartographic && Number.isFinite(cartographic.height)) {
        return Math.max(1, cartographic.height);
      }
      const position = viewer.camera.position;
      if (position && Number.isFinite(position.x)
          && Number.isFinite(position.y) && Number.isFinite(position.z)) {
        return Math.max(1, Math.hypot(position.x, position.y, position.z));
      }
      return 1;
    }

    function zoom(delta) {
      if (!Number.isFinite(delta) || delta === 0) return;
      const fraction = Math.min(
        settings.maxFraction,
        1 - Math.exp(-Math.abs(delta) * settings.speed)
      );
      const amount = cameraHeight() * fraction;
      if (delta < 0) viewer.camera.zoomIn(amount);
      else viewer.camera.zoomOut(amount);
      if (viewer.scene.requestRender) viewer.scene.requestRender();
    }

    function wheelDelta(event) {
      if (event.deltaMode === 1) return event.deltaY * 16;
      if (event.deltaMode === 2) return event.deltaY * 800;
      return event.deltaY;
    }

    function onWheel(event) {
      // Chromium 将触控板捏合暴露为可取消的 Ctrl+wheel。
      // 普通滚轮/两指滚动继续交由 Cesium 原生控制。
      if (!event.ctrlKey || !event.cancelable) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      zoom(wheelDelta(event));
    }

    let gestureScale = 1;
    function onGestureStart(event) {
      gestureScale = Number.isFinite(event.scale) && event.scale > 0 ? event.scale : 1;
      if (event.cancelable) event.preventDefault();
    }
    function onGestureChange(event) {
      const current = Number.isFinite(event.scale) && event.scale > 0 ? event.scale : gestureScale;
      if (event.cancelable) event.preventDefault();
      zoom(-Math.log(current / gestureScale) * 120);
      gestureScale = current;
    }

    const listenerOptions = {capture: true, passive: false};
    canvas.addEventListener('wheel', onWheel, listenerOptions);
    canvas.addEventListener('gesturestart', onGestureStart, listenerOptions);
    canvas.addEventListener('gesturechange', onGestureChange, listenerOptions);
    return function remove() {
      canvas.removeEventListener('wheel', onWheel, listenerOptions);
      canvas.removeEventListener('gesturestart', onGestureStart, listenerOptions);
      canvas.removeEventListener('gesturechange', onGestureChange, listenerOptions);
    };
  }

  return {install};
});
