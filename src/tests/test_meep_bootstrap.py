import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
import meep_bootstrap as bootstrap
import meep_managed as managed
from app_version import APP_VERSION
from update_client import ReleaseInfo, UpdateCancelled

LOCK = b'@EXPLICIT\nhttps://conda.anaconda.org/conda-forge/linux-64/pymeep-1.30.0-test.conda#'+b'a'*32+b'\n'
def manifest():
    return dict(schema=2,id='meep-wsl2',app_version=APP_VERSION,platform='wsl2-linux-x64',
        python=managed.LINUX_PYTHON,default_user='ods',meep_version='1.30.0',
        lock_file=bootstrap.LOCK,lock_sha256=hashlib.sha256(LOCK).hexdigest(),
        ubuntu=dict(url='https://cloud-images.ubuntu.com/wsl/releases/24.04/current/ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz',sha256='a'*64,bytes=123),
        miniforge=dict(url='https://github.com/conda-forge/miniforge/releases/download/26.7.2-0/Miniforge3-26.7.2-0-Linux-x86_64.sh',sha256='b'*64,bytes=123))

class BootstrapTests(unittest.TestCase):
    def test_valid_explicit_official_manifest(self):
        bootstrap.validate_manifest(manifest(),LOCK)

    def test_arbitrary_script_host_and_mutable_installer_rejected(self):
        for url in ('https://example.com/a.sh','https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh'):
            item=manifest(); item['miniforge']['url']=url
            with self.assertRaises(ValueError): bootstrap.validate_manifest(item,LOCK)

    def test_lock_hash_and_unofficial_packages_rejected(self):
        with self.assertRaises(ValueError): bootstrap.validate_manifest(manifest(),LOCK+b'x')
        lock=LOCK.replace(b'conda.anaconda.org',b'evil.example')
        item=manifest();item['lock_sha256']=hashlib.sha256(lock).hexdigest()
        with self.assertRaises(ValueError): bootstrap.validate_manifest(item,lock)

    def test_actual_small_pack_dispatch_and_no_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'setup.zip'
            with zipfile.ZipFile(path,'w') as pack:
                pack.writestr('addon.json',json.dumps(manifest()))
                pack.writestr(bootstrap.LOCK,LOCK)
            release=ReleaseInfo(APP_VERSION,'v'+APP_VERSION,'','','',1,managed.asset_name(),path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())
            staged,item=managed.unpack_pack(path,release,Path(tmp)/'stage')
            self.assertEqual(staged.name,'addon.json')
            self.assertEqual({p.name for p in staged.parent.iterdir()},{'addon.json',bootstrap.LOCK})
            with patch.object(bootstrap,'install',return_value={'available':True}) as install:
                self.assertTrue(managed.import_pack(staged,item,release)['available'])
                install.assert_called_once()

    def test_verified_cached_download_no_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'cached';target.write_bytes(b'valid')
            with patch.object(bootstrap,'build_opener') as opener:
                self.assertEqual(bootstrap.download(dict(bytes=5,sha256=hashlib.sha256(b'valid').hexdigest()),target),target)
                opener.assert_not_called()

    def test_cancel_before_cached_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'cached';target.write_bytes(b'valid')
            stop=threading.Event();stop.set()
            with self.assertRaises(UpdateCancelled):
                bootstrap.download(dict(bytes=5,sha256='a'*64),target,stop)

    def test_new_asset_name_does_not_collide_with_old_client(self):
        self.assertNotEqual(managed.asset_name(),managed.legacy_asset_name())
        self.assertIn('meep-setup-',managed.asset_name())

    def test_setup_keeps_fixed_owned_targets_and_retry(self):
        self.assertIn('conda install --yes --prefix /opt/ods-meep',bootstrap.SETUP)
        self.assertIn('enabled=false',bootstrap.SETUP)
        self.assertNotIn('rm -',bootstrap.SETUP)
        self.assertNotIn('--unregister',bootstrap.SETUP)

if __name__=='__main__': unittest.main()
