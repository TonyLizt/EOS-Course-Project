"""执行 `python -m eos_system` 启动单进程开发服务器。"""

from __future__ import annotations

import uvicorn


if __name__ == "__main__":
    # 不启用 reload/workers：否则每个 Web 进程都会尝试创建自己的 Controller。
    uvicorn.run("eos_system.api:create_app", host="127.0.0.1", port=8765, factory=True, workers=1, access_log=False)
