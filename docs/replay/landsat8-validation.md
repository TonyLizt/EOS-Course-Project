# Landsat 8 display asset validation

- Source: NASA Science, `https://science.nasa.gov/3d-resources/landsat-8/`
- Credit shown by the source page: NASA/Christopher R. Meaney
- Download checked on 2026-10-14: original GLB, 780,280 bytes
- SHA-256: `8b599e867be20589cd35e55ed1d46da104299b430b1827b548a25d3fad0a314d`
- Container: glTF 2.0 GLB with valid JSON/BIN chunks
- Contents: one mesh, 33 materials, no textures, no animations; required extension `KHR_draco_mesh_compression`
- Cesium check: CesiumJS 1.136 in headless Chromium 141 created one Entity model primitive from the local HTTP URL. Geometry and materials were visible in the captured frame and the browser reported no console errors.

The model is a generic illustrative appearance for dataset satellites; it never renames ALOS-2, AQUA, CARTOSAT, or another source entity. The identity model-to-body quaternion is provisional visual calibration because the NASA asset does not define this project's body or sensor axes. The fixed payload uses its own constant camera-to-body transform, so changing or scaling the appearance cannot change observation direction.

The NASA page provides the recorded credit but does not state an asset-specific MIT/Apache-style license. The repository therefore records the source and uncertainty instead of assigning a software license to the GLB.

Run the optional browser smoke check from a repository HTTP server:

```bash
PLAYWRIGHT_MODULE=/path/to/playwright \
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers \
node tests/browser/landsat8-smoke.cjs
```
