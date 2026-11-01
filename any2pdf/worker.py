import json
from pathlib import Path
import sys
import time
import traceback

from .core import convert
from .errors import ConversionError


def run_worker(request_path):
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    start = time.monotonic()
    result_path = Path(request['result'])
    cancel_path = Path(request['cancel'])
    def emit(stage):
        if sys.stdout:
            print(json.dumps({'stage': stage}), flush=True)
    try:
        output = convert(request['source'], request['outdir'], cancel_path.exists, emit,
                         workspace_prefix=request.get('workspace_prefix', '.any2pdf-'))
        result = {'status': 'success', 'output': str(output), 'error_code': '', 'detail': ''}
    except ConversionError as exc:
        result = {'status': 'cancelled' if exc.code == 'cancelled' else 'failed',
                  'output': '', 'error_code': exc.code, 'detail': exc.detail}
    except BaseException:
        result = {'status': 'failed', 'output': '', 'error_code': 'unknown',
                  'detail': traceback.format_exc()[-16000:]}
    result['elapsed'] = time.monotonic() - start
    temp = result_path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temp.replace(result_path)
    return 0 if result['status'] == 'success' else 1
