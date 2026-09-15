"""Run desktop test modules in isolated processes to avoid shared Qt globals."""
import json
import os
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    source = root.parent / 's4_ui_redesign'
    logs = root / 'release-1.1.0-module-tests'
    logs.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([str(source), str(source/'tests'), str(root/'build_input/source/ml_dependencies')])
    results = {}
    for test in sorted((source/'tests').glob('test_*.py')):
        try:
            result = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'tests.'+test.stem],
                                    cwd=source, env=env, capture_output=True, timeout=180)
            (logs/(test.stem+'.log')).write_bytes(result.stdout + result.stderr)
            results[test.stem] = result.returncode
        except subprocess.TimeoutExpired as exc:
            (logs/(test.stem+'.log')).write_bytes((exc.stdout or b'')+(exc.stderr or b'')+b'\nTIMEOUT')
            results[test.stem] = 'timeout'
        print(test.stem, results[test.stem], flush=True)
        (logs/'results.json').write_text(json.dumps(results, indent=2))
    raise SystemExit(0 if all(value == 0 for value in results.values()) else 1)
