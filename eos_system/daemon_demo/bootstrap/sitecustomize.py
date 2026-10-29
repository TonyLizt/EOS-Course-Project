"""仅隔离演示子进程通过专用PYTHONPATH载入；正常服务不会导入本文件。"""
import os
if os.environ.get('EOS_ISOLATED_DEMO') == '1':
    from eos_system import controller
    from eos_system.daemon_demo.worker import waiting_worker
    controller.worker_main = waiting_worker
