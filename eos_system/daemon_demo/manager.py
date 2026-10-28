"""独立课程演示编排：只管理本对象创建的临时实例，不接触业务运行目录。"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone

from eos_system.process_state import identity, matches, pinned_signal, read_json, lock_held


class DemoSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.temp = None
        self.process = None
        self.saved = None
        self.run_ids = []
        self.last = {'state': 'IDLE', 'runs': [], 'events': []}

    def start(self):
        with self.lock:
            if self.temp is not None:
                raise ValueError('请先停止当前演示，再开始新一轮')
            self.temp = tempfile.TemporaryDirectory(prefix='eos-daemon-demo-')
            self.root = Path(self.temp.name)
            self.runtime = self.root / 'runtime'
            scenes = self.root / 'scenarios'
            scenes.mkdir()
            # 空场景只驱动受控等待作业；不执行算法、不生成科研指标或物理认证。
            scene = scenes / 'demo.json'
            scene.write_text(json.dumps({'scenario_id':'demo', 'metadata':{'duration':60},
                'satellites':[], 'missions':[], 'ground_stations':[]}), encoding='utf-8')
            from eos_system.storage import Database
            from eos_system.contracts import RunConfig
            self.db = Database(self.runtime / 'results.sqlite3')
            self.run_ids = []
            for _ in range(3):
                run_id = str(uuid.uuid4())
                self.db.enqueue(RunConfig(run_id=run_id, scenario_id='demo',
                    scenario_path=str(scene), scenario_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),
                    algorithm_id='profit_first', algorithm_version='demo-wait-only', time_budget_s=300,
                    created_at=datetime.now(timezone.utc).isoformat()), max_queued=8)
                self.run_ids.append(run_id)
            with socket.socket() as port:
                port.bind(('127.0.0.1', 0))
                self.port = port.getsockname()[1]
            project = Path(__file__).resolve().parents[2]
            bootstrap = Path(__file__).parent / 'bootstrap'
            env = {**os.environ, 'EOS_RUNTIME_DIR':str(self.runtime), 'EOS_SCENARIO_DIR':str(scenes),
                'EOS_MAX_WORKERS':'1', 'EOS_ISOLATED_DEMO':'1', 'EOS_PREINITIALIZE_OREKIT':'0',
                'PYTHONPATH':str(bootstrap)+os.pathsep+str(project), 'PYTHONUNBUFFERED':'1'}
            try:
                self.process = subprocess.Popen([sys.executable, '-m', 'eos_system.daemon_demo.runner',
                    str(os.getpid()), 'run', '--runtime-dir', str(self.runtime), '--port',str(self.port),
                    '--interval','.4','--request-timeout','.5','--startup-grace','30',
                    '--max-restarts','3','--backoff','2','--stop-grace','8'], cwd=project, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
                self.saved = identity(self.process.pid)
            except BaseException:
                self.stop()
                raise
            return self.status()

    def status(self):
        with self.lock:
            if self.temp is None:
                return self.last
            try:
                state = read_json(self.runtime / 'daemon-status.json')
            except (OSError, ValueError):
                state = {'state':'STARTING'}
            # 只公开本轮已创建的进程和简短事件；不暴露任意文件读取能力。
            own = state.get('daemon')
            live = bool(self.saved and own and own.get('pid') == self.saved['pid']
                        and own.get('starttime') == self.saved['starttime'] and matches(self.saved))
            events = []
            log = self.runtime / 'daemon.log'
            if log.exists():
                # 日志本身由Daemon滚动限额，读取尾部防止响应越来越大。
                with log.open('rb') as stream:
                    stream.seek(0, 2)
                    stream.seek(max(0, stream.tell()-65536))
                    for line in stream.read().decode('utf-8',errors='replace').splitlines():
                        try:
                            item = json.loads(line[line.index('{'):])
                            if 'event' in item:
                                events.append({key:item[key] for key in ('time','event','pid','attempt','delay_s') if key in item})
                        except (ValueError, TypeError): pass
            runs = []
            for i, run_id in enumerate(self.run_ids):
                run = self.db.get_run(run_id)
                runs.append({'name':f'演示作业 {i+1}', 'status':run['status'],
                    'error':run.get('error'), 'attempts':run['attempts']})
            worker = None
            try:
                lease = read_json(self.runtime / 'worker-lease.json')
                if lease['run_id'] in self.run_ids and matches(lease['leader']): worker = lease['leader']
            except (OSError, ValueError, KeyError): pass
            self.last = {'state':state.get('state','STARTING'), 'daemon_alive':live,
                'daemon_pid':own.get('pid') if own else None,
                'controller_pid':(state.get('controller') or {}).get('pid'),
                'worker_pid':worker.get('pid') if worker else None, 'restarts':state.get('restarts',0),
                'limit':3, 'runs':runs, 'events':events[-30:], 'active':True}
            if self.process and self.process.poll() is not None:
                self.last['state'] = 'STOPPED' if self.process.returncode == 0 else 'ERROR'
            return self.last

    def fault(self, target):
        with self.lock:
            status = self.status()
            if target not in {'worker','controller'} or self.temp is None or not status.get('daemon_alive'):
                raise ValueError('没有可注入故障的本轮演示实例')
            if status['state'] != 'HEALTHY': raise ValueError('请等待演示实例健康后再操作')
            if target == 'controller':
                saved = read_json(self.runtime / 'daemon-status.json')['controller']
                # 必须为本对象Daemon的直接子进程，拒绝外部或历史PID。
                current = identity(saved['pid'])
                if current['ppid'] != self.saved['pid']: raise ValueError('Controller归属不符')
            else:
                lease = read_json(self.runtime / 'worker-lease.json')
                if lease['run_id'] not in self.run_ids: raise ValueError('Worker不属于本轮演示')
                saved = lease['leader']
                if identity(saved['pid'])['ppid'] != status['controller_pid']:
                    raise ValueError('Worker归属不符')
            if not pinned_signal(saved, signal.SIGKILL): raise ValueError('进程已结束，请刷新后重试')
            return self.status()

    def stop(self):
        with self.lock:
            if self.temp is None: return self.last
            self.status()
            if self.process and self.process.poll() is None:
                pinned_signal(self.saved, signal.SIGTERM)
                try: self.process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    raise ValueError('演示进程尚未退出，保留目录供诊断')
            # 锁仍占用时不删除证据，也不向未知进程发送信号。
            if lock_held(self.runtime / 'controller.lock') or lock_held(self.runtime / 'daemon.lock'):
                raise ValueError('演示实例仍持锁，尚不能清理')
            self.status()  # 关闭后重新读取作业终态和最后事件。
            self.last.update(state='STOPPED', active=False, daemon_alive=False, worker_pid=None)
            self.temp.cleanup()
            self.temp = None
            self.process = None
            self.saved = None
            return self.last
