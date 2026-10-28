"""受控等待作业：使用真实spawn、session和双Pipe，不执行卫星求解。"""
import os
import time
from datetime import datetime, timezone
from eos_system.worker_reference import send_message, receive_message

def waiting_worker(run_id, attempt, events, controls):
    os.setsid()
    def report(seq, kind, payload):
        send_message(events, {'protocol_version':1,'run_id':run_id,'attempt':attempt,'seq':seq,
            'kind':kind,'sent_at':datetime.now(timezone.utc).isoformat(),'payload':payload})
    report(1, 'started', {'worker_pid':os.getpid()})
    receive_message(controls)
    report(2, 'heartbeat', {'phase':'SEARCHING'})
    while True:
        if controls.poll(.05):
            try: message = receive_message(controls)
            except EOFError:
                time.sleep(.05)
                continue  # 由真实Controller恢复机制回收孤儿，不模拟成功。
            if message['kind'] == 'cancel':
                report(3,'cancel_ack',{'accepted':True})
                return
