"""Build and verify an isolated local candidate; never publish or install it."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from build_version import write_build_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--build-staged', action='store_true')
    parser.add_argument('--gpu', action='store_true', help='Also require an actual GPU calculation in frozen checks.')
    args = parser.parse_args()
    packaging = Path(__file__).resolve().parent
    source, output = args.source.resolve(), args.output.resolve()
    if output.parent != packaging.parent or not output.name.startswith('local-windows-review-'):
        raise ValueError('Use a new local-windows-review-* directory immediately beside desktop_installer.')
    if not args.build_staged:
        output.mkdir(exist_ok=False)
        inputs = output/'build_input'
        staged = inputs/'source'
        staged.mkdir(parents=True)
        baseline = packaging/'build_input'
        for name in ('cad_runtime', 'ml_dependencies', 'pcs_s4_runtime'):
            print('Staging runtime:', name, flush=True)
            shutil.copytree(baseline/'source'/name, staged/name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for item in source.iterdir():
            if item.is_file() and item.suffix in ('.py', '.ico'):
                shutil.copy2(item, staged/item.name)
        for item in (source/'pcs_s4_runtime').glob('*.py'):
            shutil.copy2(item, staged/'pcs_s4_runtime'/item.name)
        shutil.copytree(baseline/'gpu', inputs/'gpu')
        shutil.copy2(source/'S4_Studio.ico', inputs/'S4_Studio.ico')
        (output/'assets').mkdir()
        shutil.copy2(packaging/'assets'/'vtk-runtime-directory.txt', output/'assets'/'vtk-runtime-directory.txt')
        for name in ('desktop_entry.py', 'backend_entry.py', 'OpticalDesignStudio.spec'):
            shutil.copy2(packaging/name, output/name)
        with zipfile.ZipFile(inputs/'seed_library.zip', 'w') as archive:
            archive.writestr('s4-library-manifest.json', json.dumps(dict(format='s4-library', version=1, files={})))
        version = write_build_metadata(staged, output)
        inventory = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staged.glob('*.py')}
        (output/'candidate-input.json').write_text(json.dumps(dict(version=version,
            created=datetime.now().isoformat(), source=str(source), files=inventory,
            purpose='Local user review only; not published'), indent=2), encoding='utf-8')
    else:
        if not (output/'candidate-input.json').is_file() or (output/'dist').exists():
            raise ValueError('Use a staged candidate that has not already been built.')
        staged = output/'build_input'/'source'
        for item in source.iterdir():
            if item.is_file() and item.suffix in ('.py', '.ico'):
                shutil.copy2(item, staged/item.name)
        shutil.copy2(source/'S4_Studio.ico', output/'build_input'/'S4_Studio.ico')
        version = write_build_metadata(staged, output)
        inventory = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staged.glob('*.py')}
        (output/'candidate-input.json').write_text(json.dumps(dict(version=version,
            created=datetime.now().isoformat(), source=str(source), files=inventory,
            purpose='Local user review only; not published'), indent=2), encoding='utf-8')
    if args.stage_only:
        print('Staged:', output, flush=True)
        return 0
    env = dict(os.environ, PYTHONNOUSERSITE='1')
    env.pop('PYTHONPATH', None)
    def run(name, command):
        print(name + ' started', flush=True)
        with (output/(name+'.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run(command, cwd=output, env=env, stdout=log,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'{name} failed: see {output/(name+".log")}')
        print(name + ' passed', flush=True)
    run('compile', [sys.executable, '-m', 'PyInstaller', '--noconfirm',
        '--distpath', str(output/'dist'), '--workpath', str(output/'work'),
        str(output/'OpticalDesignStudio.spec')])
    payload = output/'dist'/'Optical Design Studio'
    run('native-audit', [sys.executable, str(packaging/'augment_native_runtime.py'),
        '--payload', str(payload), '--report', str(output/'native-audit.json')])
    notices = packaging/'build_input'/'gpu_licenses'
    if notices.is_dir():
        shutil.copytree(notices, payload/'THIRD_PARTY_LICENSES'/'NVIDIA')
    notices = packaging/'build_input'/'source'/'third-party-licenses'
    if notices.is_dir():
        shutil.copytree(notices, payload/'THIRD_PARTY_LICENSES'/'dependencies')
    (payload/'LOCAL-REVIEW.txt').write_text(
        'LOCAL REVIEW CANDIDATE - not a published release.\n'
        'Version metadata is unchanged from the source baseline.\n'
        'Run the supplied test launcher to use a separate test library.\n', encoding='utf-8')
    run('frozen-tests', [sys.executable, str(packaging/'verify_frozen.py'),
        str(payload/'Optical Design Studio.exe'), str(output/'verification'),
        '--minimum-saved', '0', '--expect-empty-library', *(['--gpu'] if args.gpu else [])])
    print('Verified local candidate:', payload, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
