"""Audit a frozen x64 payload and supply missing native DLL dependencies.

PyInstaller's Conda dependency hooks can miss libraries used by Pillow and its
codecs. This post-build check examines PE imports recursively, never replaces an
existing DLL, and records the provenance/checksum of each additional library.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parent
AMD64 = 0x8664
WINDOWS_DLLS = set('''advapi32 avrt bcrypt bcryptprimitives cabinet cfgmgr32 clbcatq comctl32 comdlg32
    crypt32 cryptbase cryptsp d2d1 d3d11 d3d12 d3d9 d3dcompiler_47 dbgcore dbghelp dhcpcsvc dnsapi
    dsound dwmapi dwrite dxgi dxva2 gdi32 gdi32full glu32 hid imm32 iphlpapi kernel32 kernelbase
    mf mfcore mfplat mfreadwrite mfuuid mpr msacm32 msimg32 msvcrt mswsock ncrypt netapi32 normaliz
    nsi ntdll ole32 oleacc oleaut32 opengl32 powrprof profapi propsys psapi rasapi32 rpcrt4 secur32
    setupapi shell32 shlwapi shcore sspicli ucrtbase user32 userenv usp10 uxtheme version win32u
    windowscodecs winhttp wininet winmm winnsi winspool.drv wintrust wldap32 ws2_32 wsock32 wtsapi32
    winrnr wkscli samcli logoncli sfc sfc_os winusb authz ktmw32 wevtapi dhcpcsvc6 cryptnet
    imagehlp uiautomationcore combase pdh'''.split())
WINDOWS_DLLS = {name if '.' in name else name + '.dll' for name in WINDOWS_DLLS}


def checksum(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(chunk)
    return digest.hexdigest()


def pe_imports(path):
    import pefile
    with pefile.PE(str(path), fast_load=True) as binary:
        binary.parse_data_directories(directories=[1, 13])
        imports = sorted({entry.dll.decode('ascii') for table in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT')
                          for entry in getattr(binary, table, [])}, key=str.casefold)
        return binary.FILE_HEADER.Machine, imports


def native_files(root):
    """The executable runtime only; readable source copies are not loader inputs."""
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if name.casefold() not in {'source', 'third_party_licenses', '__pycache__'}
                            and not (Path(directory) / name).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.suffix.casefold() in {'.exe', '.dll', '.pyd'} and not path.is_symlink():
                yield path


def source_directories(environment, extra=()):
    environment = Path(environment).resolve()
    roots = [environment]
    if environment.parent.name.casefold() == 'envs':
        roots.append(environment.parent.parent)
    directories = [Path(path).resolve() for path in extra]
    for root in roots:
        directories.extend([root / 'Library' / 'bin', root, root / 'DLLs'])
        packages = root / 'Lib' / 'site-packages'
        # Package-local hashed BLAS/OpenMP and Qt libraries may also be needed.
        # Do not recursively walk a user's entire Conda base installation.
        if packages.is_dir():
            directories.extend(sorted(packages.glob('*.libs'), key=lambda p: str(p).casefold()))
            directories.extend([packages / 'numpy' / '.libs', packages / 'scipy' / '.libs',
                                packages / 'sklearn' / '.libs', packages / 'PIL', packages / 'PyQt6' / 'Qt6' / 'bin'])
    return list(dict.fromkeys(path for path in directories if path.is_dir()))


def optional_import(owner, name):
    """Unused Conda MKL MPI/compiler/offload plugins are not solver requirements."""
    owner, name = owner.casefold(), name.casefold()
    return ((owner.startswith('mkl_blacs_') and name in {'impi.dll', 'msmpi.dll'}) or
            (owner == 'mkl_pgi_thread.2.dll' and name in {'pgf90.dll', 'pgmath.dll', 'pgc.dll'}) or
            (owner.startswith('omptarget') and (name.startswith('sycl') or name in {'ze_loader.dll', 'opencl.dll'})))


def augment(payload, environment, *, extra=(), audit_only=False):
    payload = Path(payload).resolve()
    internal = payload / '_internal'
    if not internal.is_dir() or not (payload / 'Optical Design Studio.exe').is_file():
        raise ValueError('Choose a completed Optical Design Studio payload folder.')
    paths = list(native_files(payload))
    present = {}
    for path in paths:
        present.setdefault(path.name.casefold(), []).append(path)
    candidates = {}
    directories = source_directories(environment, extra)
    for directory in directories:
        for path in sorted(directory.glob('*.dll'), key=lambda p: p.name.casefold()):
            candidates.setdefault(path.name.casefold(), []).append(path)
    report = dict(payload=str(payload), environment=str(Path(environment).resolve()), audit_only=bool(audit_only),
                  searched_directories=[str(p) for p in directories], copied=[], would_copy=[],
                  unresolved=[], optional_unresolved=[], invalid_architecture=[], parse_errors=[],
                  system_imports=[], inspected=0)
    inspected, system_imports = set(), set()
    queue = list(paths)
    while queue:
        owner = queue.pop(0)
        key = str(owner.resolve()).casefold()
        if key in inspected:
            continue
        inspected.add(key)
        try:
            architecture, imports = pe_imports(owner)
        except Exception as exc:
            report['parse_errors'].append(dict(path=str(owner), reason=str(exc)))
            continue
        if architecture != AMD64:
            report['invalid_architecture'].append(dict(path=str(owner), machine=hex(architecture)))
            continue
        for name in imports:
            lower = name.casefold()
            if lower in present:
                continue
            if lower.startswith(('api-ms-', 'ext-ms-')) or lower in WINDOWS_DLLS:
                system_imports.add(name)
                continue
            if optional_import(owner.name, name):
                report['optional_unresolved'].append(dict(owner=str(owner), dependency=name))
                continue
            available = candidates.get(lower, [])
            source = None
            rejected = []
            for path in available:
                try:
                    machine, _ = pe_imports(path)
                    if machine == AMD64:
                        source = path
                        break
                    rejected.append(dict(path=str(path), machine=hex(machine)))
                except Exception as exc:
                    rejected.append(dict(path=str(path), reason=str(exc)))
            if source is None:
                report['unresolved'].append(dict(owner=str(owner), dependency=name, rejected_candidates=rejected))
                continue
            destination = internal / source.name
            # Never replace a PyInstaller-selected binary or another build's DLL.
            # All copies here are missing basenames, validated as AMD64 first.
            if destination.exists():
                present.setdefault(lower, []).append(destination)
                queue.append(destination)
                continue
            entry = dict(dependency=name, required_by=str(owner), source=str(source),
                         destination=str(destination), size=source.stat().st_size, sha256=checksum(source))
            if audit_only:
                report['would_copy'].append(entry)
                present[lower] = [source]
                queue.append(source)
            else:
                # Exclusive creation keeps the no-overwrite rule if two build
                # processes unexpectedly inspect the same payload concurrently.
                try:
                    with source.open('rb') as original, destination.open('xb') as target:
                        shutil.copyfileobj(original, target, length=4 * 1024**2)
                except FileExistsError:
                    present[lower] = [destination]
                    queue.append(destination)
                    continue
                report['copied'].append(entry)
                present[lower] = [destination]
                queue.append(destination)
    report['inspected'] = len(inspected)
    report['system_imports'] = sorted(system_imports, key=str.casefold)
    report['passed'] = not (report['unresolved'] or report['invalid_architecture'] or report['parse_errors'])
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, default=ROOT / 'dist' / 'Optical Design Studio')
    parser.add_argument('--environment', type=Path, default=Path(sys.prefix))
    parser.add_argument('--extra-dll-dir', action='append', default=[], type=Path)
    parser.add_argument('--audit-only', action='store_true')
    parser.add_argument('--report', type=Path, default=ROOT / 'native-runtime-audit.json')
    args = parser.parse_args(argv)
    vtk_source = ROOT/'build_input'/'source'/'cad_runtime'/'vtk.libs'
    extra = [*args.extra_dll_dir, vtk_source]
    report = augment(args.payload, args.environment, extra=extra, audit_only=args.audit_only)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('passed', 'inspected', 'copied', 'would_copy', 'unresolved',
                                                  'optional_unresolved', 'invalid_architecture', 'parse_errors')}, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
