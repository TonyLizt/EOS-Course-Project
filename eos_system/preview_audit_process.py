"""Controller 专用的预览物理核验子进程；不读写数据库，不签发正式凭据。"""
from __future__ import annotations

import json
import sys

from .contracts import RunConfig
from .planning_preview import _audit_preview_local
from utils.continuous_exposure import ContinuousCertificationError, ExposureStatus


def main():
    """stdin/stdout 仅交换 JSON；Java 日志保留在 stderr 供故障诊断。"""
    try:
        request = json.load(sys.stdin)
        config = RunConfig.model_validate(request['config'])
        receipt = _audit_preview_local(config, request['plan'],
            deadline=float(request['deadline']), data_path=request['data_path'])
        response = {'evidence': receipt.evidence()}
    except ContinuousCertificationError as exc:
        response = {'error': str(exc).removeprefix(str(exc.status) + ': '),
                    'status': exc.status.value}
    except Exception as exc:
        response = {'error': type(exc).__name__ + ': ' + str(exc), 'status': ExposureStatus.ERROR.value}
    print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
