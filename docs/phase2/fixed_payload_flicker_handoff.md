# Fixed Payload View 頻閃修補交接

日期：2026-10-17  
分支：`fix/cesium-300s-consistency`

## 根因

所有衛星小窗共用一個隱藏 Cesium Viewer。舊實作在主時鐘的同一個 tick 中，為不同衛星反覆執行 `camera.setView()`、`render()` 和 `drawImage()`。Cesium 的 imagery tile selection、LOD 載入和替換是非同步的；相機剛從衛星 A 切到衛星 B 時，程式沒有等待 B 所需瓦片完成，就把預設 framebuffer 複製到 B 的 Canvas。

因此 UI 邊框和文字穩定，但小窗會交替出現舊視角瓦片、低階瓦片、未完成的新視角或突然改變的地球邊緣。不同衛星相距越遠、窗口越多，tile working set 競爭越明顯。主 Viewer 的 ENU 跟隨相機不參與這條渲染鏈，也不是本次根因。

## 修補

- 新增 `draw/fixed-payload-renderer.js`，把所有小窗工作放入單一序列 queue。同衛星尚未開始的舊要求會合併成最新仿真時間，但正在渲染的工作不會被覆蓋。
- 一次只允許一個衛星擁有隱藏 Viewer 的 Camera 和預設 framebuffer。相機保持不變，直到 imagery/terrain pending count 為 0、`globe.tilesLoaded` 為 true，且連續兩個 render frame 都穩定。
- 完整幀才以一次 `drawImage()` 原子提交到對應 satellite tile。載入期間保留上一個完整幀，不會將半載入 framebuffer 暴露給使用者；超過有界嘗試次數則丟棄新工作，而不是提交錯誤畫面。
- 選中 tile 與普通 tile 交替取得渲染權，避免 2×2 選中畫面餓死其他衛星。queued work 使用 `Map` 合併，記憶體不會隨 tick 無限累積。
- 隱藏 Viewer 使用有界 512-tile cache，降低 10/50 星輪巡時相同 NaturalEarth 瓦片反覆卸載/載入；沒有降低地形或 imagery 品質。
- tile 的 `OBSERVING / IDLE / Earth occluded` 文本與影像在同一 commit 更新，避免狀態先走到新時間、影像仍是舊時間。
- 主 Cesium Viewer、衛星本體姿態、固定鏡頭 quaternion、1×1/2×2 佈局與自動跟隨邏輯不變。

## Debug 模式

在 Cesium URL 加上 `debug_payload=1`。每個 begin/render/commit/drop 事件以 `[fixed-payload-render]` 輸出，並保留最近 2000 筆於 `viewer._payloadRenderDiagnostics`。

記錄包含衛星 ID、渲染 frame、仿真時間、衛星位置、本體/固定鏡頭 quaternion、鏡頭 direction/up、View/Projection Matrix、Canvas、framebuffer 類型、render 起訖時間、imagery/terrain pending count、tilesLoaded、context lost 與 resize generation。預設關閉，不產生長期記錄開銷。

## 驗證

- Node：scheduler 的穩定兩幀門檻、工作合併、選中公平性、50 衛星 frame ownership 全部通過。
- 真實 Chromium 2 星、30 秒：38 次完整 commit；每星至少 16 個不同仿真時間；正常倍速、60x、選中、切星、暫停/恢復、Escape 通過；WebGL/console/HTTP error 均為 0；heap 約 47.2 MiB → 51.0 MiB。
- 真實 Chromium 10 星、30 秒：28 次完整 commit；每星至少 2 個不同仿真時間；相同互動流程通過；WebGL/console/HTTP error 均為 0；heap 約 78.6 MiB → 64.3 MiB。
- 依使用者指示沒有再執行 50 星 30 秒長測。50 星已通過 frame ownership/queue 單元測試，但真實 GPU 吞吐與首次全部瓦片完成時間仍是未實測限制。

測試入口：

```bash
node tests/fixed_payload_renderer.test.cjs
node tests/fixed_payload_view.test.cjs
python -m unittest -v tests.test_replay_delivery
```

真實瀏覽器 soak 使用 `tests/browser/serve_integrated_fixture.py` 與 `tests/browser/fixed-payload-flicker-smoke.cjs`。隔離服務使用臨時資料庫與 replay 目錄，結束後清理，不修改正式實驗。

## 剩餘限制

- 仍使用單一隱藏 WebGL Context，目的是避免 50 個 Viewer/Context 造成更大的 GPU 壓力。代價是大量衛星的更新頻率低於選中衛星，但每次可見提交都是完整且歸屬正確的幀。
- 512-tile cache 是固定上限，不會無限增長；低記憶體 GPU 可能較早回收底層資源。context lost/restored 已記錄，恢復後會重新排入所有衛星。
- Fixed Payload View 是 `illustration_only` 成像示意；此修補保留既有物理姿態與固定安裝鏡頭方向，不將它宣稱為真實光學影像模擬。
