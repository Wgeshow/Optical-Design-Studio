"""Fail-closed privacy checks for the public installer delivery profile."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

PRIVATE_FOLDERS = {'runs', 'data_library', 'user data', 'backups', 'exports',
                   '.git', '.codex', '__pycache__', 'test_ui_library', 'ui_preview_library'}
PRIVATE_FILES = {'desktop_session.json', 'benchmark_results.json', 'ui_preview_server.json',
                 'test_report.md', 'desktop_test_report.md', 'ui_test_report.md',
                 '.env', 'startup-error.txt'}
PRIVATE_SUFFIXES = ('.log', '.pickle', '.pkl', '.joblib', '.zip', '.7z', '.rar', '.tar',
                    '.gz', '.bz2', '.xz', '.whl', '.exe', '.dll', '.pyd', '.so',
                    '.sqlite', '.sqlite3', '.db', '.npy', '.npz', '.h5', '.hdf5')
PERSONAL_PATH = re.compile(r'(?i)(?:[a-z]:[\\/]+Users[\\/]+[^\s\"\'<>/\\]+|/(?:Users|home)/[^\s\"\'<>/]+)')
SOURCE_REQUIRED = ('app.py', 'qt_app.py', 'qt_about.py', 'desktop_runtime.py',
                   'S4-source/COPYING', 'S4-source/COPYRIGHT', 'S4-source/Makefile',
                   'S4-source/S4/accelerator.cpp', 'third-party-licenses/COPYING')


def assert_empty_seed(path):
    """The public profile never distributes research runs, materials or tables."""
    with zipfile.ZipFile(path) as archive:
        if archive.namelist() != ['s4-library-manifest.json']:
            raise ValueError('Public delivery requires a manifest-only seed archive.')
        manifest = json.loads(archive.read('s4-library-manifest.json'))
        if manifest != {'format': 's4-library', 'version': 1, 'files': {}}:
            raise ValueError('Public delivery requires an empty valid library manifest.')


def write_empty_seed(path):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('s4-library-manifest.json', json.dumps(
            {'format': 's4-library', 'version': 1, 'files': {}}, indent=2))
    assert_empty_seed(path)


def validate_public_source(root):
    """Inspect the separately reviewed readable source, never the private library."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise ValueError('Public readable source must be a real, reviewed directory.')
    root = root.resolve()
    inventory = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        directory = Path(directory)
        for name in folders + files:
            path = directory / name
            relative = path.relative_to(root)
            if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
                raise ValueError('Public source cannot contain filesystem links: ' + relative.as_posix())
            if any(part.casefold() in PRIVATE_FOLDERS for part in relative.parts):
                raise ValueError('Private data directory in public source: ' + relative.as_posix())
            if name.casefold() in PRIVATE_FILES or name.casefold().endswith(PRIVATE_SUFFIXES):
                raise ValueError('Private result/configuration file in public source: ' + relative.as_posix())
        for name in files:
            path = directory / name
            relative = path.relative_to(root).as_posix()
            data = path.read_bytes()
            # Real user-profile paths are not needed in distributable instructions
            # or source. This does not inspect compiled dependency binaries.
            text = None
            if data.startswith((b'\xff\xfe', b'\xfe\xff')):
                text = data.decode('utf-16', errors='replace')
            elif b'\0' not in data[:4096]:
                text = data.decode('utf-8', errors='replace')
            if text is not None:
                if PERSONAL_PATH.search(text):
                    raise ValueError('Personal absolute path in public readable source: ' + relative)
            inventory[relative] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    for name in SOURCE_REQUIRED:
        if name not in inventory:
            raise ValueError('Public readable source is missing required application/native source: ' + name)
    encoded = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return {'files': inventory, 'tree_sha256': hashlib.sha256(encoded).hexdigest()}


def public_build_info(build):
    """The shipped inventory must not expose builder paths or private bundle IDs."""
    if build.get('profile') != 'public' or any(build.get(key) != 0 for key in ('seed_files', 'seed_runs', 'seed_presets')):
        raise ValueError('Invalid public build: private library entries must be zero.')
    return {key: build[key] for key in ('version', 'build_date', 'profile', 'seed_files',
            'seed_runs', 'seed_presets', 'public_source_tree_sha256')}
