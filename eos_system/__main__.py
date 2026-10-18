"""执行 `python -m eos_system` 启动单进程开发服务器。"""

from __future__ import annotations

import os
import fcntl
from pathlib import Path
import sys
import uvicorn

from .config import Settings
from .process_state import atomic_json, identity


class SupervisedServer(uvicorn.Server):
    """Record user shutdown before Uvicorn drains requests/closes HTTP."""

    def handle_exit(self, sig, frame):
        settings = Settings.from_env()
        try:
            atomic_json(settings.runtime_dir / 'controller-stopping.json',
                        {'token': os.environ['EOS_SUPERVISION_TOKEN'],
                         'process': identity(os.getpid())})
        finally:
            super().handle_exit(sig, frame)


def controller_is_running(lock_path: Path) -> bool:
    """只探测现有锁，不删除锁文件；最终互斥仍由 Controller.start 保证。"""
    try:
        stream = lock_path.open("r")
    except FileNotFoundError:
        return False
    with stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
    return False


def main() -> int:
    project = Path(__file__).resolve().parent.parent
    console = project / '.worktrees' / 'scheduling-console'
    if (not (project/'eos_system/web/console.js').is_file()
            and (console/'eos_system/web/console.js').is_file()):
        os.environ.setdefault('EOS_SCENARIO_DIR', str(project/'experiments/scenarios'))
        print(f'EOS：从独立升级目录启动统一调度控制台：{console}', flush=True)
        os.chdir(console)
        os.execv(sys.executable, [sys.executable, '-m', 'eos_system'])
    settings = Settings.from_env()
    try:
        running = controller_is_running(settings.lock_path)
    except OSError as exc:
        print(f"EOS：无法检查运行目录 {settings.runtime_dir}：{exc}", file=sys.stderr)
        return 1
    if running:
        print(
            f"EOS：已有 Controller 正在使用运行目录 {settings.runtime_dir}，无需重复启动。\n"
            "若使用默认端口，请打开 http://127.0.0.1:8765/ 。\n"
            "如需重启，请在原服务终端按 Ctrl+C，等待退出后再执行本命令。\n"
            "请勿删除 controller.lock 或强行启动第二个 Controller。",
            file=sys.stderr,
        )
        return 1
    # 不启用 reload/workers：否则每个 Web 进程都会尝试创建自己的 Controller。
    options = dict(host="127.0.0.1", port=int(os.environ.get('EOS_PORT', '8765')),
                   factory=True, workers=1, access_log=False)
    if os.environ.get('EOS_SUPERVISION_TOKEN'):
        SupervisedServer(uvicorn.Config("eos_system.api:create_app", **options)).run()
    else:
        uvicorn.run("eos_system.api:create_app", **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
