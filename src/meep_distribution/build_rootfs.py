"""Build/export on a Linux Docker host using an explicit locked environment.

No OS features or WSL distributions are changed. Does not publish artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid


def run(args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-image', required=True, help='Reviewed condaforge/miniforge3@sha256:<digest> Linux amd64 image')
    parser.add_argument('--lock', type=Path, required=True, help='Conda @EXPLICIT linux-64 package lock with checksum fragments')
    parser.add_argument('--app-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'condaforge/miniforge3@sha256:[0-9a-f]{64}', args.base_image):
        parser.error('Pin a reviewed Miniforge image by SHA256 digest.')
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.app_version):
        parser.error('Invalid application version.')
    lock = args.lock.read_text(encoding='utf-8')
    packages = [line for line in lock.splitlines() if line and not line.startswith(('#', '@'))]
    if '@EXPLICIT' not in lock or not packages or not any('pymeep-' in line for line in packages):
        parser.error('The explicit lock must include the actual pymeep package.')
    if any(not re.fullmatch(r'https://conda.anaconda.org/conda-forge/(linux-64|noarch)/[^\s#]+#[0-9a-f]{32}', line) for line in packages):
        parser.error('Use conda-forge linux-64/noarch explicit package URLs with MD5 checksum fragments.')
    if args.output.exists():
        parser.error('Output directory already exists; choose a new empty artifact location.')
    args.output.mkdir(parents=True)
    name = 'ods-meep-build-'+uuid.uuid4().hex
    image = name+':'+args.app_version
    here = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='ods-meep-context-') as tmp:
        context = Path(tmp)
        for file in ('Dockerfile', 'rootfs_self_test.py'):
            shutil.copy2(here/file, context/file)
        shutil.copy2(args.lock, context/'linux-64.explicit.txt')
        run(['docker', 'build', '--platform', 'linux/amd64', '--build-arg', 'BASE_IMAGE='+args.base_image, '-t', image, str(context)])
        created = False
        try:
            run(['docker', 'create', '--name', name, image])
            created = True
            run(['docker', 'cp', name+':/opt/ods-build/self-test.json', str(args.output/'self-test.json')])
            run(['docker', 'cp', name+':/usr/share/ods-fdtd/package-metadata', str(args.output/'package-metadata')])
            run(['docker', 'cp', name+':/usr/share/ods-fdtd/licenses', str(args.output/'licenses')])
            run(['docker', 'export', '--output', str(args.output/'rootfs.tar'), name])
        finally:
            if created:
                # Delete only the unique container created by this invocation;
                # keep the built image as build provenance for maintainers.
                run(['docker', 'rm', name])
    report = json.loads((args.output/'self-test.json').read_text())
    if report.get('passed') is not True:
        raise RuntimeError('Actual Meep self-test did not pass; refusing to package.')
    metadata = [json.loads(p.read_text()) for p in (args.output/'package-metadata').glob('*.json')]
    licenses = sorted({m.get('license', 'UNKNOWN') for m in metadata})
    if not metadata or 'UNKNOWN' in licenses:
        raise RuntimeError('Review and resolve missing runtime license metadata before publishing.')
    build = dict(schema=1, app_version=args.app_version, base_image=args.base_image,
        lock_sha256=hashlib.sha256(args.lock.read_bytes()).hexdigest(), meep_version=report['meep_version'],
        licenses=licenses, packages=[dict(name=m['name'], version=m['version'], build=m['build'],
            license=m['license'], url=m.get('url', ''), sha256=m.get('sha256', '')) for m in metadata])
    (args.output/'build-provenance.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    shutil.copy2(args.lock, args.output/'linux-64.explicit.txt')
    print('Rootfs exported and real air/Fresnel tests passed. Review licenses/source obligations, then run package_rootfs.py.')


if __name__=='__main__':
    main()
