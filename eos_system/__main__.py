"""执行 `python -m eos_system` 启动单进程开发服务器。"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import uvicorn


if __name__ == "__main__":
    project = Path(__file__).resolve().parent.parent
    console = project / '.worktrees' / 'scheduling-console'
    if (not (project/'eos_system/web/console.js').is_file()
            and (console/'eos_system/web/console.js').is_file()):
        os.environ.setdefault('EOS_SCENARIO_DIR', str(project/'experiments/scenarios'))
        print(f'EOS：从独立升级目录启动统一调度控制台：{console}', flush=True)
        os.chdir(console)
        os.execv(sys.executable, [sys.executable, '-m', 'eos_system'])
    # 不启用 reload/workers：否则每个 Web 进程都会尝试创建自己的 Controller。
    uvicorn.run("eos_system.api:create_app", host="127.0.0.1", port=8765, factory=True, workers=1, access_log=False)
