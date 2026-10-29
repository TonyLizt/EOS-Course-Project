"""临时实例随宿主退出；核对父进程而不依赖创建请求线程的寿命。"""
import os
import signal
import sys
import threading
import time

if __name__ == '__main__':
    parent = int(sys.argv[1])
    if os.getppid() != parent: sys.exit(1)
    def monitor_parent():
        # Linux PDEATHSIG关联创建线程；Web线程池会回收空闲线程，不能用它判断宿主死亡。
        # 这里只检查当前进程的真实PPID，并把单轮演示限制在十分钟内。
        deadline=time.monotonic()+600
        while os.getppid()==parent and time.monotonic()<deadline:
            time.sleep(1)
        os.kill(os.getpid(),signal.SIGTERM)
    threading.Thread(target=monitor_parent,name='demo-host-monitor',daemon=True).start()
    from eos_system.daemon import main
    sys.exit(main(sys.argv[2:]))
