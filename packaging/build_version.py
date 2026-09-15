"""Read release constants without importing the application or its GUI."""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def release_info(source: Path | None = None) -> dict[str, str]:
    source = Path(source) if source is not None else ROOT / 'build_input' / 'source'
    path = source / 'app_version.py'
    constants = {}
    for node in ast.parse(path.read_text(encoding='utf-8'), filename=str(path)).body:
        if isinstance(node, ast.Assign):
            names, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            names, value = [node.target], node.value
        else:
            continue
        for name in names:
            if isinstance(name, ast.Name) and name.id in {'APP_VERSION', 'BUILD_DATE'}:
                constants[name.id] = ast.literal_eval(value)
    version, build_date = constants.get('APP_VERSION'), constants.get('BUILD_DATE')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError(f'{path} must define APP_VERSION as a numeric major.minor.patch string.')
    if any(int(part) > 65535 for part in version.split('.')):
        raise ValueError('Windows version fields must be at most 65535.')
    if not isinstance(build_date, str) or date.fromisoformat(build_date).isoformat() != build_date:
        raise ValueError(f'{path} must define BUILD_DATE as YYYY-MM-DD.')
    return {'version': version, 'build_date': build_date}


def write_build_metadata(source: Path, destination: Path = ROOT) -> dict[str, str]:
    info = release_info(source)
    version = info['version']
    fixed = ','.join(version.split('.') + ['0'])
    resource = (
        'VSVersionInfo(\n'
        f'  ffi=FixedFileInfo(filevers=({fixed}), prodvers=({fixed}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),\n'
        "  kids=[StringFileInfo([StringTable('040904B0', [\n"
        "    StringStruct('FileDescription', 'Optical Design Studio'),\n"
        f"    StringStruct('FileVersion', '{version}'),\n"
        "    StringStruct('InternalName', 'OpticalDesignStudio'),\n"
        "    StringStruct('OriginalFilename', 'Optical Design Studio.exe'),\n"
        "    StringStruct('ProductName', 'Optical Design Studio'),\n"
        f"    StringStruct('ProductVersion', '{version}')\n"
        "  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]\n"
        ')\n'
    )
    destination = Path(destination)
    (destination / 'version_info.txt').write_text(resource, encoding='utf-8')
    (destination / 'version.iss').write_text(
        '; Generated from app_version.py by prepare_payload.py.\n'
        f'#define Version "{version}"\n', encoding='utf-8')
    return info


def update_info(source: Path) -> dict:
    """Read the compiled updater target independently of research-data delivery."""
    path = Path(source)/'update_client.py'
    repository = None
    for node in ast.parse(path.read_text(encoding='utf-8'), filename=str(path)).body:
        if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == 'REPOSITORY'
                                               for name in node.targets):
            repository = ast.literal_eval(node.value)
    targets = {'Wgeshow/optical-design-studio-updates': True,
               'Wgeshow/Optical-Design-Studio': False,
               'Wgeshow/optical-design-studio-downloads': False}
    if repository not in targets:
        raise ValueError('Review the updater authentication metadata for this repository before packaging.')
    private = targets[repository]
    return {'repository': repository, 'private': private, 'authenticated_check': private,
            'authenticated_download': private, 'automatic_check': False,
            'automatic_install': False, 'release_channel': 'stable'}
