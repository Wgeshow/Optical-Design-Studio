"""Pinned official-download Meep setup inside an exclusively owned WSL distro."""
from __future__ import annotations
import hashlib
import gzip
import json
import lzma
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.error import HTTPError

from app_version import APP_VERSION
from data_library import write_json
from update_client import UpdateCancelled, _cancelled
import meep_runtime

LOCK = 'linux-64.explicit.txt'
MAX_DOWNLOAD = 2*1024**3
MAX_TAR = 12*1024**3
ASSET_HOSTS = {'release-assets.githubusercontent.com', 'objects.githubusercontent.com',
               'github-releases.githubusercontent.com'}


def validate_manifest(manifest, lock):
    if (manifest.get('schema')!=2 or manifest.get('id')!='meep-wsl2'
            or manifest.get('app_version')!=APP_VERSION or manifest.get('platform')!='wsl2-linux-x64'
            or manifest.get('python')!='/opt/ods-meep/bin/python' or manifest.get('default_user')!='ods'
            or manifest.get('lock_file')!=LOCK or manifest.get('meep_version')!='1.30.0'
            or hashlib.sha256(lock).hexdigest()!=manifest.get('lock_sha256')):
        raise ValueError('Incompatible FDTD setup manifest or lock checksum.')
    for key in ('ubuntu', 'miniforge'):
        item = manifest.get(key, {})
        url = urlsplit(item.get('url', ''))
        valid_path = (url.hostname in {'cloud-images.ubuntu.com', 'cdimage.ubuntu.com'}
                      and (re.search(r'/release-\d{8}/.*amd64.*\.tar\.xz$', url.path)
                           or re.fullmatch(r'/wsl/releases/24\.04/current/ubuntu-noble-wsl-amd64-wsl\.rootfs\.tar\.gz',url.path))) if key=='ubuntu' else (
                      url.hostname=='github.com' and re.fullmatch(
                          r'/conda-forge/miniforge/releases/download/[0-9][A-Za-z0-9.\-]*/Miniforge3-[A-Za-z0-9.\-]+-Linux-x86_64\.sh', url.path))
        if (url.scheme!='https' or url.username or url.password or url.port not in (None,443)
                or url.query or url.fragment or not valid_path
                or not re.fullmatch('[0-9a-f]{64}', item.get('sha256', ''))
                or type(item.get('bytes')) is not int or not 0<item['bytes']<=MAX_DOWNLOAD):
            raise ValueError('FDTD setup requires pinned official '+key+' downloads.')
    lines = [line.strip() for line in lock.decode('utf-8').splitlines()
             if line.strip() and not line.lstrip().startswith('#')]
    if not lines or lines[0]!='@EXPLICIT' or len(lines)<2:
        raise ValueError('FDTD setup requires an explicit package lock.')
    pattern = r'https://conda\.anaconda\.org/conda-forge/(linux-64|noarch)/[A-Za-z0-9_.+\-]+\.(conda|tar\.bz2)#[0-9a-f]{32}([0-9a-f]{32})?'
    if any(not re.fullmatch(pattern,line) for line in lines[1:]):
        raise ValueError('FDTD lock contains an unpinned or unofficial package URL.')
    if not any('/pymeep-1.30.0-' in line for line in lines):
        raise ValueError('The explicit lock does not contain the required Meep version.')
    return manifest


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def download(item, target, cancel=None, progress=None):
    """Cache only exact verified bytes; validate redirect host before each request."""
    target = Path(target)
    if target.is_symlink() or getattr(target,'is_junction',lambda:False)():
        raise ValueError('Linked FDTD download cache is not allowed.')
    def digest(path):
        value = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024**2),b''):
                _cancelled(cancel)
                value.update(chunk)
        return value.hexdigest()
    if target.is_file() and target.stat().st_size==item['bytes'] and digest(target)==item['sha256']:
        return target
    temporary = target.with_name(target.name+'.part')
    if temporary.exists() or temporary.is_symlink():
        raise ValueError('An unfinished download cache exists; it was preserved: '+str(temporary))
    opener = build_opener(_NoRedirect())
    url = item['url']
    original_host = urlsplit(url).hostname
    response = None
    try:
        for _ in range(6):
            _cancelled(cancel)
            parts = urlsplit(url)
            if (parts.scheme!='https' or parts.username or parts.password or parts.port not in (None,443)
                    or parts.hostname not in ({original_host}|ASSET_HOSTS)):
                raise ValueError('Official FDTD download redirected to an unexpected host.')
            try:
                response = opener.open(Request(url,headers={'User-Agent':'OpticalDesignStudio/'+APP_VERSION}), timeout=30)
                break
            except HTTPError as exc:
                if exc.code not in (301,302,303,307,308):
                    raise RuntimeError('Official FDTD download failed (HTTP '+str(exc.code)+').') from None
                location = exc.headers.get('Location')
                if not location:
                    raise ValueError('Official download returned an invalid redirect.')
                url = urljoin(url,location)
        if response is None:
            raise ValueError('Too many official-download redirects.')
        total, sha = 0, hashlib.sha256()
        with response, temporary.open('xb') as out:
            while True:
                _cancelled(cancel)
                chunk = response.read(1024**2)
                if not chunk:
                    break
                total += len(chunk)
                if total>item['bytes']:
                    raise ValueError('Official download exceeded the pinned size.')
                out.write(chunk)
                sha.update(chunk)
        if total!=item['bytes'] or sha.hexdigest()!=item['sha256']:
            raise ValueError('Official download failed its SHA256/size verification.')
        temporary.replace(target)
        return target
    finally:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()


def run_owned(distro, arguments, cancel=None, progress=None, timeout=1800):
    """Run fixed application commands as root, with precise Linux group cancellation."""
    argv = ['wsl.exe','--distribution',distro,'--user','root','--exec',
            '/usr/bin/setsid','--wait','/bin/sh','-c',
            'printf "ODS_SETUP_PID=%s\\n" "$$"; exec "$@"','ods-setup',*arguments]
    process = subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding='utf-8',errors='replace',**meep_runtime.process_options())
    lines = queue.Queue()
    def reader():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=reader,daemon=True).start()
    pid, tail, started = None, [], time.monotonic()
    try:
        while True:
            timed_out = time.monotonic()-started>timeout
            cancelling = cancel is not None and cancel.is_set()
            if timed_out or (cancelling and (pid is not None or time.monotonic()-started>3)):
                if pid:
                    subprocess.run(['wsl.exe','--distribution',distro,'--user','root','--exec',
                        '/bin/kill','-KILL','--','-'+str(pid)],capture_output=True,timeout=10,
                        **meep_runtime.process_options())
                process.kill()
                process.wait(timeout=10)
                if cancelling:
                    raise UpdateCancelled()
                raise TimeoutError('FDTD setup step exceeded its time limit.')
            try:
                line = lines.get(timeout=.2)
            except queue.Empty:
                continue
            if line is None:
                break
            if line.startswith('ODS_SETUP_PID='):
                value = line.strip().split('=',1)[1]
                if value.isdecimal() and int(value)>1:
                    pid = int(value)
            else:
                tail = (tail+[line.rstrip()])[-20:]
        code = process.wait(timeout=10)
        _cancelled(cancel)
        if code:
            raise RuntimeError('FDTD setup command failed: '+'\n'.join(tail))
    finally:
        process.stdout.close()


SETUP = r'''set -eu
id ods >/dev/null 2>&1 || useradd --user-group --create-home --shell /bin/bash ods
mkdir -p /home/ods /usr/local/bin
chown ods:ods /home/ods
printf '[user]\ndefault=ods\n[automount]\nenabled=true\nroot=/mnt/\n[interop]\nenabled=false\nappendWindowsPath=false\n' > /etc/wsl.conf
printf '#!/bin/sh\nexec /usr/bin/setsid --wait "$@"\n' > /usr/local/bin/setsid
chmod 755 /usr/local/bin/setsid
if ! /opt/conda/bin/conda --version >/dev/null 2>&1; then
  /bin/bash "$1" -b -u -p /opt/conda
fi
if [ -f /opt/ods-meep/conda-meta/history ]; then
  /opt/conda/bin/conda install --yes --prefix /opt/ods-meep --file "$2"
else
  /opt/conda/bin/conda create --yes --prefix /opt/ods-meep --file "$2"
fi
/opt/ods-meep/bin/python -c 'import meep; assert meep.__version__ == "1.30.0"'
'''


def install(manifest_path, manifest, release, *, root=None, cancel=None, progress=None):
    import meep_managed as managed
    managed.ManagedMeepClient._validate_release(release)
    manifest_path = Path(manifest_path)
    lock = manifest_path.with_name(LOCK).read_bytes()
    validate_manifest(manifest,lock)
    if json.loads(manifest_path.read_text(encoding='utf-8'))!=manifest:
        raise ValueError('FDTD setup manifest changed after verification.')
    root = Path(root) if root is not None else managed.runtime_root()
    if any(managed._linked(p) for p in (root,*root.parents)):
        raise ValueError('FDTD setup directory must not contain links or junctions.')
    status = managed.prerequisites(cancel)
    if not status['ready']:
        raise RuntimeError(status['message'])
    saved, registered = managed.receipt(root), managed.registration()
    exists = registered or managed.distro_name() in status.get('distributions',[])
    if exists:
        if (not saved or not registered or saved['sha256']!=release.sha256
                or os.path.normcase(registered['location'])!=os.path.normcase(saved['location'])
                or registered['version']!=2):
            raise RuntimeError('The FDTD distribution is not this owned setup transaction; it was left unchanged.')
        if saved.get('state')=='ready':
            return managed.verify_installed(root,cancel)
    root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<8*1024**3:
        raise RuntimeError('FDTD direct setup needs at least 8 GiB free disk space.')
    cache = root/'downloads'
    if managed._linked(cache):
        raise ValueError('Linked FDTD download cache is not allowed.')
    cache.mkdir(exist_ok=True)
    if progress:
        progress('Downloading pinned Ubuntu and Miniforge files directly from their official publishers…')
    suffix = '.xz' if manifest['ubuntu']['url'].endswith('.xz') else '.gz'
    ubuntu = download(manifest['ubuntu'],cache/('ubuntu-rootfs.tar'+suffix),cancel,progress)
    installer = download(manifest['miniforge'],cache/'miniforge.sh',cancel,progress)
    destination = root/'distro'
    if not exists:
        reusable = destination.is_dir() and not any(destination.iterdir()) and saved and saved['sha256']==release.sha256
        if destination.exists() and not reusable:
            raise RuntimeError('Existing FDTD runtime files were preserved; setup cannot overwrite them.')
        tar = cache/'ubuntu-rootfs.tar'
        # Recreate only this derived cache blob from verified compressed bytes.
        if managed._linked(tar):
            raise ValueError('Linked FDTD import cache is not allowed.')
        decompress = lzma.open if suffix=='.xz' else gzip.open
        with decompress(ubuntu,'rb') as src, tar.open('wb') as out:
            total = 0
            for chunk in iter(lambda:src.read(1024**2),b''):
                _cancelled(cancel)
                total += len(chunk)
                if total>MAX_TAR:
                    raise ValueError('Ubuntu import archive exceeds the safety limit.')
                out.write(chunk)
        destination.mkdir(exist_ok=bool(reusable))
        saved = dict(schema=1,app_version=APP_VERSION,distro=managed.distro_name(),
            location=str(destination.resolve()),sha256=release.sha256,
            meep_version=manifest['meep_version'],state='importing',setup_schema=2)
        write_json(root/'installation.json',saved)
        write_json(root/'addon.json',manifest)
        if progress:
            progress('Importing the dedicated Ubuntu runtime; cancellation is honored after import completes safely.')
        code, output, error = managed._wsl(['--import',managed.distro_name(),str(destination.resolve()),str(tar.resolve()),'--version','2'],timeout=900)
        if code:
            raise RuntimeError('WSL import failed; its files were preserved. '+(error or output))
    try:
        _cancelled(cancel)
        write_json(root/'installation.json',dict(saved,state='bootstrapping'))
        if progress:
            progress('Installing the pinned Meep environment from conda-forge in the dedicated runtime…')
        config = managed.managed_config()
        run_owned(managed.distro_name(),['/bin/bash','-c',SETUP,'ods-setup',
            meep_runtime.linux_path(installer,config),meep_runtime.linux_path(manifest_path.with_name(LOCK),config)],cancel,progress)
        _cancelled(cancel)
        # Apply default-user configuration only to this verified owned distro.
        code, output, error = managed._wsl(['--terminate',managed.distro_name()],timeout=30)
        if code:
            raise RuntimeError('Could not restart the owned FDTD runtime: '+(error or output))
        result = managed.verify_installed(root,cancel)
        if not result['available']:
            raise RuntimeError('Meep setup finished but its runtime probe failed: '+result['message'])
        return result
    except Exception:
        write_json(root/'installation.json',dict(saved,state='needs-check',setup_schema=2))
        raise
