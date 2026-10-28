"""真实隔离恢复验收；不向业务服务或历史PID发送信号。"""
import unittest
import time
from pathlib import Path
from eos_system.daemon_demo.manager import DemoSession
from eos_system.process_state import matches

class DemoTests(unittest.TestCase):
    def wait(self, demo, predicate):
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            state=demo.status()
            if predicate(state): return state
            time.sleep(.1)
        self.fail(str(demo.status()))

    def test_real_worker_isolation_and_controller_recovery(self):
        demo=DemoSession()
        self.addCleanup(demo.stop)
        with self.assertRaises(ValueError): demo.fault('controller')
        # Web请求在线程池启动；创建线程退出不能让独立Daemon误停。
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(demo.start).result()
        root=demo.root
        with self.assertRaises(ValueError): demo.start()
        first=self.wait(demo,lambda s:s['state']=='HEALTHY' and s['worker_pid'])
        dog=first['daemon_pid'];controller=first['controller_pid'];worker=first['worker_pid']
        saved=demo.saved.copy()
        self.assertEqual(len({dog,controller,worker}),3)
        with self.assertRaises(ValueError): demo.fault('12345')
        demo.fault('worker')
        second=self.wait(demo,lambda s:s['runs'][0]['status']=='FAILED' and s['worker_pid'] and s['worker_pid']!=worker)
        self.assertEqual(second['restarts'],0)
        self.assertEqual(second['controller_pid'],controller)
        self.assertIn(second['runs'][0]['error']['code'],{'WORKER_EXIT','IPC_DISCONNECTED'})
        demo.fault('controller')
        recovered=self.wait(demo,lambda s:s['state']=='HEALTHY' and s['restarts']==1 and s['worker_pid'])
        self.assertEqual(recovered['daemon_pid'],dog)
        self.assertNotEqual(recovered['controller_pid'],controller)
        self.assertEqual(recovered['runs'][1]['error']['code'],'CONTROLLER_RESTART')
        self.assertEqual(recovered['runs'][2]['status'],'RUNNING')
        self.assertTrue(any(e['event']=='RECOVERY_ATTEMPT' for e in recovered['events']))
        print('DEMO EVIDENCE',first,'RECOVERED',recovered,flush=True)
        stopped=demo.stop()
        self.assertFalse(matches(saved))
        self.assertFalse(root.exists())
        self.assertEqual(stopped['state'],'STOPPED')
        self.assertFalse(stopped['active'])
        demo.stop()  # 幂等停止。



class RouteTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from test_replay_backend import _DirectClient
        from eos_system.daemon_demo.routes import install_routes
        class FakeSession:
            calls=[]
            def status(self): return {'state':'IDLE'}
            def start(self): self.calls.append('start');return self.status()
            def stop(self): self.calls.append('stop');return self.status()
            def fault(self,target): self.calls.append(target);return self.status()
        self.session=FakeSession()
        self.session.calls=[]
        app=FastAPI()
        install_routes(app,Path('.'),self.session)
        self.client=_DirectClient(app)

    def test_cross_origin_and_plain_form_cannot_send_signals(self):
        self.assertEqual(self.client._request('POST','/api/daemon-demo/start').status_code,403)
        self.assertEqual(self.client._request('POST','/api/daemon-demo/controller',headers={
            'X-EOS-Demo':'1','Origin':'https://example.org'}).status_code,403)
        self.assertEqual(self.client._request('POST','/api/daemon-demo/controller',headers={
            'X-EOS-Demo':'1','Sec-Fetch-Site':'cross-site'}).status_code,403)
        self.assertEqual(self.session.calls,[])

    def test_only_fixed_actions_and_demo_children_cannot_nest(self):
        from unittest.mock import patch
        headers={'X-EOS-Demo':'1','Origin':'http://127.0.0.1'}
        self.assertEqual(self.client._request('POST','/api/daemon-demo/start',headers=headers).status_code,200)
        self.assertEqual(self.client._request('POST','/api/daemon-demo/12345',headers=headers).status_code,409)
        with patch.dict('os.environ',{'EOS_ISOLATED_DEMO':'1'}):
            self.assertEqual(self.client._request('POST','/api/daemon-demo/start',headers=headers).status_code,403)
        self.assertEqual(self.session.calls,['start'])

if __name__=='__main__': unittest.main()
