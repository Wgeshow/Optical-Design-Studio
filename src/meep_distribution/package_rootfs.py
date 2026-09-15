"""Create the verified managed-WSL release asset after image build and review."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import tarfile
import zipfile


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('build_directory', type=Path)
    parser.add_argument('--source-notice', type=Path, required=True,
        help='Reviewed distribution/source notice identifying corresponding-source archives published with the release')
    args = parser.parse_args()
    folder = args.build_directory.resolve()
    build = json.loads((folder/'build-provenance.json').read_text(encoding='utf-8'))
    report = json.loads((folder/'self-test.json').read_text(encoding='utf-8'))
    version = build['app_version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or report.get('passed') is not True or build['meep_version']!=report['meep_version']:
        parser.error('Build identity and real Meep tests must be valid.')
    if args.source_notice.stat().st_size<30:
        parser.error('A reviewed license/corresponding-source notice is required.')
    required = {'etc/wsl.conf', 'opt/ods-meep/bin/python', 'opt/ods-build/self-test.json'}
    unpacked, names = 0, set()
    with tarfile.open(folder/'rootfs.tar', 'r:') as tar:
        for item in tar:
            names.add(item.name.lstrip('./'))
            unpacked += item.size
            if item.name.lstrip('./')=='etc/wsl.conf':
                config = tar.extractfile(item).read().decode()
                if 'default=ods' not in config or 'enabled=false' not in config:
                    parser.error('WSL runtime must use the unprivileged ods user and disable Windows interop.')
    if not required<=names or unpacked>12*1024**3:
        parser.error('Rootfs is missing required files or exceeds its supported size.')
    archive = folder/f'OpticalDesignStudio-Addon-meep-{version}-WSL2-x64.zip'
    if archive.exists():
        parser.error('The release asset already exists; refusing to overwrite.')
    compressed = folder/'rootfs.tar.gz'
    with (folder/'rootfs.tar').open('rb') as source, compressed.open('xb') as target:
        with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as out:
            shutil.copyfileobj(source, out, 1024**2)
    manifest = dict(schema=1, id='meep-wsl2', app_version=version, platform='wsl2-linux-x64',
        python='/opt/ods-meep/bin/python', default_user='ods', rootfs_file='rootfs.tar.gz',
        rootfs_sha256=sha256(compressed), rootfs_bytes=compressed.stat().st_size,
        unpacked_bytes=unpacked, meep_version=build['meep_version'], licenses=build['licenses'],
        provenance=build, solver_tests=report, source_notice=args.source_notice.read_text(encoding='utf-8'))
    (folder/'addon.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as package:
        package.write(folder/'addon.json', 'addon.json')
        package.write(compressed, 'rootfs.tar.gz')
    (folder/(archive.name+'.sha256')).write_text(sha256(archive)+'  '+archive.name+'\n', encoding='ascii')
    print(archive)


if __name__=='__main__':
    main()
