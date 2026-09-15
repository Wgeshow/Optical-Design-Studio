"""Stage a reproducible desktop build and a verified, data-only seed archive."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import zipfile

from build_version import release_info, write_build_metadata
from public_profile import assert_empty_seed, validate_public_source

ROOT = Path(__file__).resolve().parent
SOURCE_FOLDERS = {'pcs_s4_runtime', 'ml_dependencies', 'cad_runtime', 'S4-source', 'third-party-licenses', 'tests'}
SOURCE_SUFFIXES = {'.py', '.cmd', '.sh', '.txt', '.md', '.json', '.ps1', '.yml', '.yaml', '.ico', '.png'}

def copy_current_file(source, target):
    for attempt in range(6):
        try:
            shutil.copy2(source, target)
            return
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) != 32 or attempt == 5:
                raise RuntimeError(f'Cannot stage {source.name}: {exc}') from exc
            time.sleep(.5 * (attempt + 1))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, help='Optional source/runtime snapshot; required for private library delivery.')
    parser.add_argument('--profile', choices=('private', 'public'), default='private')
    parser.add_argument('--public-source', type=Path, help='Separately reviewed readable application/native source tree for public delivery.')
    args = parser.parse_args()
    if args.profile == 'private' and args.bundle is None:
        parser.error('--bundle is required for the private library profile.')
    if args.profile == 'public' and args.public_source is None:
        parser.error('--public-source is required for the public profile.')
    # Check the authoritative release constants before changing build staging.
    release = release_info(args.source)
    build = ROOT / 'build_input'
    if args.source.resolve().is_relative_to(build.resolve()):
        raise ValueError('Build source cannot be inside the generated staging folder.')
    reviewed = None
    if args.profile == 'public':
        if args.public_source.resolve().is_relative_to(build.resolve()):
            raise ValueError('Reviewed public source cannot be inside generated staging.')
        reviewed = validate_public_source(args.public_source)
        if release_info(args.public_source) != release:
            raise ValueError('Reviewed readable source does not match the application release version/date.')
    # Never retain obsolete application files between releases. This target is
    # fixed to this builder's own workspace, never derived from user input.
    if build.exists():
        if build.is_symlink() or build.resolve().parent != ROOT.resolve():
            raise ValueError('Build staging must stay inside the packaging directory.')
        def remove_readonly(function, path, error):
            target = Path(path).resolve()
            if not isinstance(error, PermissionError) or not target.is_relative_to(build.resolve()):
                raise error
            # OneDrive can mark generated directories read-only. Clear only
            # this attribute on the verified build target; never alter ACLs.
            if not (Path(path).stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY):
                raise error
            Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
            function(path)
        shutil.rmtree(build, onexc=remove_readonly)
    source = build / 'source'
    source.mkdir(parents=True, exist_ok=True)
    seed_manifest = {'format': 's4-library', 'version': 1, 'files': {}}
    with zipfile.ZipFile(build/'seed_library.zip', 'w', zipfile.ZIP_DEFLATED) as seed:
        if args.bundle is not None:
            with zipfile.ZipFile(args.bundle) as bundle:
                manifest = json.loads(bundle.read('s4-library-manifest.json'))
                if manifest.get('format') != 's4-library' or manifest.get('version') != 1:
                    raise ValueError('Export a valid library bundle from Saved work first.')
                for name, record in manifest['files'].items():
                    path = PurePosixPath(name)
                    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                        raise ValueError(f'Unsafe archive path: {name}')
                    data = bundle.read(name)
                    if len(data) != record['size'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                        raise ValueError(f'Bundle integrity failure: {name}')
                    if path.parts[0] in {'runs', 'data_library'}:
                        if args.profile == 'private':
                            seed.writestr(name, data)
                            seed_manifest['files'][name] = record
                    elif path.parts[0] in SOURCE_FOLDERS or (len(path.parts) == 1 and path.suffix.lower() in SOURCE_SUFFIXES):
                        target = source.joinpath(*path.parts)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
        seed.writestr('s4-library-manifest.json', json.dumps(seed_manifest, indent=2))
    if args.profile == 'public':
        assert_empty_seed(build/'seed_library.zip')
        shutil.copytree(args.public_source, build/'public_source')
        if validate_public_source(build/'public_source') != reviewed:
            raise ValueError('Reviewed source changed while staging the public build.')
    # Current source takes precedence over the snapshot used for the shared data.
    for item in args.source.iterdir():
        if item.is_file() and item.suffix.lower() in SOURCE_SUFFIXES:
            copy_current_file(item, source/item.name)
        elif item.is_dir() and item.name in SOURCE_FOLDERS:
            patterns = ['__pycache__', '*.pyc', '.git']
            if item.name == 'cad_runtime':
                # STEP export calls OCP directly; VTK is only CadQuery's
                # optional visualization layer and is not shipped.
                # Keep native vtk.libs only as an audit source: the OCP binary
                # links its small IVtk bridge even when visualization is unused.
                # The post-build audit copies only that bridge's transitive DLLs.
                patterns += ['vtk.py', 'vtkmodules', 'vtk-*.dist-info', 'IVtk*']
            shutil.copytree(item, source/item.name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*patterns))
    icon = ROOT/'assets'/'S4_Studio.ico'
    if not icon.is_file():
        icon = ROOT.parent/'S4_Studio.ico'
    shutil.copy2(icon, build/'S4_Studio.ico')
    shutil.copy2(icon, source/'S4_Studio.ico')
    gpu = build/'gpu'
    gpu.mkdir(exist_ok=True)
    for wheel in sorted((ROOT/'tools').glob('nvidia_*cu11-*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            for info in archive.infolist():
                if Path(info.filename).name in {'cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll'}:
                    (gpu/Path(info.filename).name).write_bytes(archive.read(info))
                elif 'license' in info.filename.lower() and not info.is_dir():
                    dest = build/'gpu_licenses'/wheel.stem/Path(info.filename).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(archive.read(info))
    required = ['qt_app.py', 'qt_chrome.py', 'qt_about.py', 'app_version.py',
                'update_client.py', 'update_credentials.py',
                'backend.py', 'desktop_runtime.py', 'installer_smoke.py',
                'pcs_s4_runtime/S4.cp312-win_amd64.pyd', 'ml_dependencies/sklearn/__init__.py']
    for name in required:
        if not (source/name).is_file():
            raise FileNotFoundError(source/name)
    for name in ('cublas64_11.dll', 'cublasLt64_11.dll', 'cudart64_110.dll'):
        if not (gpu/name).is_file():
            raise FileNotFoundError(f'Download the pinned NVIDIA wheels first: {gpu/name}')
    if write_build_metadata(source) != release:
        raise ValueError('Release constants changed during payload preparation.')
    summary = {**release, 'profile': args.profile, 'source': str(args.source.resolve()),
               'data_bundle': str(args.bundle.resolve()) if args.bundle else None,
               'data_bundle_sha256': hashlib.sha256(args.bundle.read_bytes()).hexdigest() if args.bundle else None,
               'seed_files': len(seed_manifest['files']),
               'seed_runs': len({PurePosixPath(n).parts[1] for n in seed_manifest['files'] if n.startswith('runs/')}),
               'seed_presets': sum(n.startswith('data_library/presets/') for n in seed_manifest['files'])}
    if reviewed is not None:
        summary['public_source_tree_sha256'] = reviewed['tree_sha256']
    (build/'build_input.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
