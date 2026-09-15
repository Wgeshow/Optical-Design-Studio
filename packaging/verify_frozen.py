"""Launch the built/installed executable without the developer's Python paths."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess

from public_profile import assert_empty_seed

def pe_machine(path):
    with path.open('rb') as stream:
        if stream.read(2) != b'MZ':
            return None
        stream.seek(0x3c)
        offset = struct.unpack('<I', stream.read(4))[0]
        stream.seek(offset)
        if stream.read(4) != b'PE\0\0':
            return None
        return struct.unpack('<H', stream.read(2))[0]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('application', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--minimum-saved', type=int, help='Defaults to the payload seed count.')
    parser.add_argument('--expect-empty-library', action='store_true',
                        help='Assert that this fresh test starts without runs, presets or material tables.')
    args = parser.parse_args()
    application = args.application.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = application.parent/'PAYLOAD-MANIFEST.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else {}
    if args.minimum_saved is None:
        args.minimum_saved = manifest.get('build_input', {}).get('seed_runs', 97)
    if manifest.get('delivery_profile') == 'public':
        assert_empty_seed(application.parent/'_internal'/'seed_library.zip')
    artifacts = {}
    for relative in ['Optical Design Studio.exe', 'OpticalDesignBackend.exe',
                     '_internal/python312.dll', '_internal/pcs_s4_runtime/S4.cp312-win_amd64.pyd',
                     '_internal/PyQt6/Qt6/bin/Qt6Core.dll', '_internal/cublas64_11.dll']:
        path = application.parent/relative
        machine = pe_machine(path)
        artifacts[relative] = hex(machine) if machine else 'not PE'
        if machine != 0x8664:
            raise RuntimeError(f'Expected x64 PE executable/library: {path}: {machine}')
    (output/'architecture.json').write_text(json.dumps(artifacts, indent=2), encoding='utf-8')
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(('PYTHON', 'CONDA', 'S4_', 'QT_', 'MPL', 'MKL', 'OMP', 'OPENBLAS'))}
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = os.pathsep.join([str(windows/'System32'), str(windows), str(windows/'System32'/'Wbem')])
    env['PYTHONNOUSERSITE'] = '1'
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    env['S4_LIBRARY_ROOT'] = str(output/'User Data')
    env['S4_SELF_TEST_MIN_SAVED_ENTRIES'] = str(args.minimum_saved)
    env['S4_SELF_TEST_EXPECT_EMPTY_LIBRARY'] = '1' if args.expect_empty_library else '0'
    env['S4_SELF_TEST_GPU'] = '1' if args.gpu else '0'
    env['QT_QPA_PLATFORM'] = 'offscreen'
    report = output/'report.json'
    with (output/'stdout.log').open('w', encoding='utf-8') as stdout, (output/'stderr.log').open('w', encoding='utf-8') as stderr:
        result = subprocess.run([str(application), '--self-test', str(report)], cwd=output, env=env,
                                stdout=stdout, stderr=stderr, timeout=300,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    diagnostic_text = (output/'stderr.log').read_text(encoding='utf-8', errors='replace')
    failures = [marker for marker in ('Traceback (most recent call last)', 'Exception ignored', 'ImportError:',
                                      'FileNotFoundError:', 'ModuleNotFoundError:') if marker in diagnostic_text]
    if failures:
        print('Unexpected runtime errors in stderr: ' + ', '.join(failures))
        print(diagnostic_text[-6000:])
        raise SystemExit(1)
    print(json.dumps({'exit_code': result.returncode, 'report': str(report), 'architectures': artifacts}, indent=2))
    if report.exists():
        print(report.read_text(encoding='utf-8'))
    raise SystemExit(result.returncode)

if __name__ == '__main__':
    main()
