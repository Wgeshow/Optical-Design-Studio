"""Run the same guarded installer checks outside OneDrive's synchronized tree."""
import json
from pathlib import Path
import shutil
import tempfile

import verify_installer as verification

local_root = Path(tempfile.gettempdir()).resolve() / 'OpticalStudioVerification'
marker = local_root / 'verification-owner.json'
identity = {'builder': str(verification.ROOT), 'purpose': 'Optical Design Studio isolated installer verification'}
if local_root.is_symlink() or local_root.is_junction():
    raise ValueError('The local verification folder cannot be a link.')
if local_root.exists():
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != identity:
        raise ValueError('The local verification folder is not owned by this test.')
else:
    local_root.mkdir()
    marker.write_text(json.dumps(identity), encoding='utf-8')


def contained(path):
    resolved = Path(path).resolve()
    if resolved == local_root or not resolved.is_relative_to(local_root):
        raise ValueError('Installer test target must remain inside the owned temporary directory: ' + str(path))
    return resolved


original_run = verification.run_hidden


def run_hidden(command, directory, env, log_prefix, timeout=300):
    if Path(command[0]).name.startswith('OpticalDesignStudio-Setup-'):
        timeout = 900
    return original_run(command, directory, env, log_prefix, timeout)


verification.VERIFICATION_ROOT = local_root
verification.contained = contained
verification.run_hidden = run_hidden
try:
    code = verification.main()
finally:
    latest = local_root / 'latest-verification.json'
    if latest.is_file():
        shutil.copyfile(latest, verification.ROOT / 'install_verification' / 'latest-verification.json')
raise SystemExit(code)
