"""Compile the frozen Windows applications from a verified staged source tree."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent


def main():
    stage = json.loads((ROOT / 'stage-manifest.json').read_text(encoding='utf-8'))
    count = 0
    for relative, expected in stage['files'].items():
        path = ROOT / 'source' / relative
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']:
            raise RuntimeError('The verified staged source changed: ' + relative)
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), relative, 'exec')
            count += 1
    (ROOT / 'syntax-check.json').write_text(json.dumps(dict(
        version=stage['version'], passed=True, python_files=count,
        source_tree_sha256=stage['source_tree_sha256']), indent=2), encoding='utf-8')
    destination = ROOT / 'dist'
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('Keep existing candidates intact; the interrupted build output must be empty.')
    started = time.monotonic()
    print(f'Compiled {count} Python files; building both Windows executables.', flush=True)
    with (ROOT / 'build.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([
            sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
            '--distpath', str(destination), '--workpath', str(ROOT / 'work'),
            str(ROOT / 'OpticalDesignStudio.spec')], cwd=ROOT,
            stdout=log, stderr=subprocess.STDOUT)
    report = dict(version=stage['version'], passed=result.returncode == 0,
                  exit_code=result.returncode, elapsed_seconds=time.monotonic() - started,
                  source_tree_sha256=stage['source_tree_sha256'], python_files_compiled=count)
    (ROOT / 'build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    if result.returncode:
        print((ROOT / 'build.log').read_text(encoding='utf-8')[-7000:], flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
