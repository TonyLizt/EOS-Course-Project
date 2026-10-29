"""演示专用路由；业务API仅调用注册入口，不接收用户指定PID或路径。"""
import os
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

def install_routes(app, web_dir, session):
    @app.get('/daemon-demo')
    def page():
        return FileResponse(web_dir / 'daemon-demo.html', headers={'Cache-Control':'no-store'})

    @app.get('/api/daemon-demo')
    def status():
        return session.status()

    @app.post('/api/daemon-demo/{action}')
    def action(action: str, request: Request):
        # 自定义头拒绝表单跨站触发，Origin检查拒绝浏览器跨源控制。
        from urllib.parse import urlsplit
        origin = request.headers.get('origin')
        if (request.url.hostname not in {'127.0.0.1','localhost','::1'}
                or request.headers.get('x-eos-demo') != '1'
                or request.headers.get('sec-fetch-site') == 'cross-site'
                or (origin and urlsplit(origin).netloc != request.url.netloc)
                or os.environ.get('EOS_ISOLATED_DEMO') == '1'):
            raise HTTPException(403, '只允许本机同源演示页面控制隔离实例')
        try:
            if action == 'start': return session.start()
            if action == 'stop': return session.stop()
            if action in {'worker','controller'}: return session.fault(action)
            raise ValueError('未知演示操作')
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
