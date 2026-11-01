"""Read-only check of final release archives and the updater's package contract."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / 'GitHub-Release-1.4.0-alpha.6'
sys.path.insert(0, str(ROOT / 'source'))
from desktop_runtime import _safe_parts


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    stage = json.loads((ROOT / 'stage-manifest.json').read_text(encoding='utf-8'))
    validation = json.loads((OUT / 'VALIDATION.json').read_text(encoding='utf-8'))
    assert validation['version'] == '1.4.0-alpha.6' and validation['archive_integrity'] == 'passed'
    assert validation['native_startup_verification'] == 'passed'
    assert validation['source_tree_sha256'] == stage['source_tree_sha256']
    assert validation['published'] is False
    assets = validation['assets']
    assert len(assets) == 2 and {entry['name'] for entry in assets} == {
        'OpticalDesignStudio-Portable-1.4.0-alpha.6-Windows-x64.zip',
        'OpticalDesignStudio-Source-1.4.0-alpha.6.zip'}
    expected_sums = []
    for entry in assets:
        path = OUT / entry['name']
        assert path.stat().st_size == entry['bytes'] and digest(path) == entry['sha256']
        line = entry['sha256'] + '  ' + entry['name']
        expected_sums.append(line)
        assert path.with_name(path.name + '.sha256').read_text(encoding='ascii').splitlines() == [line]
    assert (OUT / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines() == expected_sums
    portable = OUT / 'OpticalDesignStudio-Portable-1.4.0-alpha.6-Windows-x64.zip'
    source = OUT / 'OpticalDesignStudio-Source-1.4.0-alpha.6.zip'
    with zipfile.ZipFile(portable) as app, zipfile.ZipFile(source) as code:
        seen = set()
        expanded = 0
        for entry in app.infolist():
            parts = _safe_parts(entry, seen)
            assert parts[0] == 'Optical Design Studio' and len(parts) >= 2
            assert parts[1].casefold() not in {
                'user data', 'portable_settings.json', 'runs', 'data_library', 'addons', 'add-ons'}
            assert not parts[1].casefold().startswith('.ods-update-')
            expanded += entry.file_size
        assert len(app.infolist()) <= 30000 and expanded <= 8 * 1024**3
        prefix = 'Optical Design Studio/'
        manifest = json.loads(app.read(prefix + 'PAYLOAD-MANIFEST.json'))
        actual = {entry.filename[len(prefix):] for entry in app.infolist() if not entry.is_dir()}
        assert actual == set(manifest['files']) | {'PAYLOAD-MANIFEST.json'}
        assert manifest['source_tree_sha256'] == stage['source_tree_sha256']
        assert manifest['version'] == '1.4.0-alpha.6' and manifest['packaged_self_tests_passed'] is True
        for name in ('Optical Design Studio.exe', 'OpticalDesignBackend.exe'):
            payload = app.read(prefix + name)
            assert len(payload) == manifest['files'][name]['size']
            assert hashlib.sha256(payload).hexdigest() == manifest['files'][name]['sha256']
        seed = json.loads(app.read(prefix + 'BUILD_VERIFICATION.json'))
        assert seed['frozen_verification'] == 'passed'
        assert seed['native_startup_verification'] == 'passed'
        code_prefix = 'OpticalDesignStudio-Source-1.4.0-alpha.6/'
        code_seen = set()
        for entry in code.infolist():
            parts = _safe_parts(entry, code_seen)
            assert parts[0] == code_prefix.rstrip('/') and len(parts) >= 2
        checked = 0
        csv_files = 0
        for name, expected in stage['files'].items():
            if Path(name).suffix in ('.pyd', '.dll', '.exe'):
                continue
            for archive, target in (
                (app, prefix + '_internal/source/' + name),
                (code, code_prefix + 'src/' + name),
            ):
                payload = archive.read(target)
                assert len(payload) == expected['size'], target
                assert hashlib.sha256(payload).hexdigest() == expected['sha256'], target
            checked += 1
            csv_files += name.startswith('help_assets/') and name.endswith('.csv')
        assert 'native/S4-source/COPYING' in {
            name[len(code_prefix):] for name in code.namelist()}
    report = dict(passed=True, version='1.4.0-alpha.6', published=False,
                  source_tree_sha256=stage['source_tree_sha256'],
                  updater_archive_contract='passed', portable_files=len(actual),
                  portable_expanded_bytes=expanded, source_files_checked_in_both_archives=checked,
                  scientific_csv_files_checked_in_both_archives=csv_files,
                  archive_sha256_verified=True)
    (ROOT / 'final-archive-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
