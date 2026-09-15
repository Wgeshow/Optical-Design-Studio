"""Prepare a requested patch with packaging integrity only; never publish."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent


def main():
    from build_version import release_info, write_build_metadata
    source = WORKSPACE/'s4_ui_redesign'
    version = release_info(source)['version']
    export = WORKSPACE/f'github_source_release_{version}_portable'
    write_build_metadata(source)
    steps = [
        [str(export/'export_source.py'), '--source', str(source), '--packaging', str(ROOT)],
        [str(export/'create_public_readable_source.py')],
        ['prepare_payload.py', '--source', str(source), '--bundle', str(WORKSPACE/'S4_Optical_Studio_PyQt6.zip'), '--profile', 'public', '--public-source', str(export/'public-readable-source')],
        ['clean_payload.py'],
        ['-m', 'PyInstaller', '--noconfirm', '--distpath', 'dist', '--workpath', 'work', 'OpticalDesignStudio.spec'],
        ['augment_native_runtime.py'],
        ['finalize_payload.py'],
        ['package_portable.py', '--integrity-only'],
        [str(export/'create_source_archive.py')],
    ]
    logdir = ROOT/f'patch-{version}-packaging'
    logdir.mkdir(exist_ok=True)
    for index, step in enumerate(steps):
        log = logdir/f'{index+1:02d}.log'
        print(f'STEP {index+1}/{len(steps)}: {step[0]} -> {log}', flush=True)
        with log.open('w', encoding='utf8') as stream:
            result = subprocess.run([sys.executable, *step], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            print(log.read_text(encoding='utf8', errors='replace')[-12000:], flush=True)
            raise SystemExit(result.returncode)
    print('Artifacts built; packaging integrity verified. No application or COMSOL tests run. Nothing published.', flush=True)


if __name__ == '__main__':
    main()
