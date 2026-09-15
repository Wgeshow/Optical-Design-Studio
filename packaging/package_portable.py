"""Package only verified public inventory into a portable ZIP and test extraction."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
PAYLOAD = ROOT/'dist'/'Optical Design Studio'

def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    manifest = json.loads((PAYLOAD/'PAYLOAD-MANIFEST.json').read_text(encoding='utf-8'))
    version = manifest['version']
    if manifest['delivery_profile'] != 'public' or manifest['build_input']['seed_files'] != 0:
        raise ValueError('Portable public ZIP must have an empty research seed.')
    report = json.loads((ROOT/f'portable-{version}-verification'/'report.json').read_text(encoding='utf-8'))
    if not report['passed'] or report['version'] != version:
        raise ValueError('Frozen verification must pass first.')
    target = ROOT.parent/f'OpticalDesignStudio-Portable-{version}-Windows-x64.zip'
    if target.exists():
        raise FileExistsError(target)
    temporary = target.with_suffix('.zip.part')
    if temporary.exists():
        raise FileExistsError(temporary)
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        names = dict(manifest['files'])
        names['PAYLOAD-MANIFEST.json'] = None
        for index, (name, record) in enumerate(names.items()):
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                raise ValueError('Invalid inventory path: ' + name)
            source = PAYLOAD/name
            if not source.resolve().is_relative_to(PAYLOAD.resolve()) or source.is_symlink():
                raise ValueError('Invalid source path: ' + name)
            if record and (source.stat().st_size != record['size'] or sha256(source) != record['sha256']):
                raise ValueError('Payload changed after verification: ' + name)
            if name.startswith(('User Data/', 'runs/', 'data_library/')) or path.name == 'portable_settings.json':
                raise ValueError('Personal data/configuration cannot be packaged: ' + name)
            archive.write(source, 'Optical Design Studio/' + name)
            if index % 1000 == 0:
                print(f'Packaged {index}/{len(names)} files', flush=True)
    extraction = ROOT/f'portable-extracted-{version}'
    extraction.mkdir(exist_ok=False)
    with zipfile.ZipFile(temporary) as archive:
        archive.extractall(extraction)  # Entries above are verified relative inventory names.
    extracted = extraction/'Optical Design Studio'
    for name, record in manifest['files'].items():
        if sha256(extracted/name) != record['sha256']:
            raise ValueError('Extracted file differs: ' + name)
    subprocess.run([sys.executable, str(ROOT/'verify_frozen.py'),
                    str(extracted/'Optical Design Studio.exe'),
                    str(ROOT/f'portable-extracted-{version}-verification'), '--gpu', '--expect-empty-library'], check=True)
    temporary.replace(target)
    digest = sha256(target)
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    result = dict(version=version, artifact=str(target), size=target.stat().st_size, sha256=digest,
                  format='portable-zip', source_included=True, personal_data_included=False,
                  extracted_runtime_verified=True, files=len(names),
                  data_default='User Data beside the program', data_setting='Settings → Data output folder',
                  requires_restart_after_data_change=True)
    (ROOT.parent/f'OPTICAL_DESIGN_STUDIO_PORTABLE_{version}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)

if __name__ == '__main__':
    main()
