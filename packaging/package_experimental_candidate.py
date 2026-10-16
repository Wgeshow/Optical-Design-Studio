"""Package an explicitly requested experimental release without claiming unfinished checks passed."""
from __future__ import annotations
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

candidate=Path(sys.argv[1]).resolve()
pack=candidate/'packaging'
sys.path.insert(0,str(pack))
pkg=importlib.import_module('package_release')
stage,tests=pkg.verify_stage()
app=pkg.APP
out=pkg.OUT
version=pkg.VERSION
assert version=='1.4.0-alpha.1'
assert not out.exists() or not any(out.iterdir()),'Preserve existing release assets'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
partial_path=pack/'verification/report.json'
partial=read(partial_path)
assert partial.get('frozen') is True and partial['version']==version
completed={name:row['passed'] for name,row in partial['checks'].items()}
assert completed.get('simulation_launcher_and_model_screens') is True
assert partial['checks']['simulation_launcher_and_model_screens']['detail']['choices_checked']==27
gates=read(candidate/'packaging-gates-report.json')
models=read(candidate/'frozen-research-verified/validation.json')
bands=read(candidate/'frozen-band-followup/validation.json')
assert gates['passed'] and gates['tests']==20
assert models['passed'] and models['completed']==models['requested']==12
assert bands['passed'] and bands['completed']==bands['requested']==2
assert tests['passed'] and not tests['errors'] and not tests['failures']
exe_hash=pkg.digest(app/'Optical Design Studio.exe')
backend_hash=pkg.digest(app/'OpticalDesignBackend.exe')
assert models['executable_sha256']==bands['executable_sha256']==backend_hash
previous=read(app/'PAYLOAD-MANIFEST.json')
files_before=pkg.public_files()
assert files_before==previous['files'],'Prepared payload changed before experimental packaging'
shutil.copy2(pack/'RELEASE_NOTES.md',app/'RELEASE_NOTES.md')

validation=read(app/'BUILD_VERIFICATION.json')
validation.update(
    release_channel='highly_experimental',
    validation_scope='Partial compiled verification; remaining compiled and native startup checks stopped at the explicit user request to package and ship.',
    frozen_verification='partial',native_startup_verification='not_run',
    packaged_checks=completed,packaged_self_tests_passed=False,
    package_gate_tests=20,compiled_startup_choices_verified=27,
    compiled_model_jobs_completed=12,edited_band_jobs_completed=2,
    compiled_model_jobs=[{key:row.get(key) for key in ('name','engine','passed','status')} for row in models['jobs']],
    edited_band_jobs=[{key:row.get(key) for key in ('name','solver','dimension','passed','status','frequency_values','convergence_claim')} for row in bands['jobs']],
    unfinished_checks='Remaining compiled self-tests and the real Windows native startup matrix were not completed.',
    limitations=['Highly Experimental prerelease.','The finite PCSEL paper case executed but remains unconverged.','Execution success does not establish physical convergence or agreement with every paper.'],
    executable_sha256=exe_hash,backend_executable_sha256=backend_hash,
    archive_integrity='pending',published=False)
pkg.write_json(app/'BUILD_VERIFICATION.json',validation)
files=pkg.public_files()
assert set(files)==set(files_before)
assert all(files[name]==files_before[name] for name in files if name not in ('BUILD_VERIFICATION.json','RELEASE_NOTES.md'))
pkg.write_json(app/'PAYLOAD-MANIFEST.json',dict(version=version,delivery_profile='public',
    release_channel='highly_experimental',source_tree_sha256=stage['source_tree_sha256'],
    packaged_self_tests_passed=False,compiled_verification='partial',native_startup_verification='not_run',files=files))
out.mkdir(exist_ok=True)
portable=out/f'OpticalDesignStudio-Portable-{version}-Windows-x64.zip'
entries=[(app/name,name) for name in files]+[(app/'PAYLOAD-MANIFEST.json','PAYLOAD-MANIFEST.json')]
print('Creating public highly experimental portable ZIP; compiled verification is explicitly partial.',flush=True)
pkg.create_zip(portable,entries,'Optical Design Studio/',1)
print(json.dumps(dict(portable=str(portable),bytes=portable.stat().st_size,below_github_2gib=portable.stat().st_size<2*1024**3)),flush=True)
source=out/f'OpticalDesignStudio-Source-{version}.zip'
readable=app/'_internal/source'
source_entries=[(readable/name,('native/'+name if name.startswith('S4-source/') else 'src/'+name)) for name in pkg.inventory(readable)]
source_entries += [(app/'THIRD_PARTY_LICENSES'/name,'THIRD_PARTY_LICENSES/'+name) for name in pkg.inventory(app/'THIRD_PARTY_LICENSES')]
recipe_names=('OpticalDesignStudio.spec','desktop_entry.py','backend_entry.py','version_info.txt',
    'stage_release.py','build_release.py','test_release_source.py','verify_release.py',
    'package_release.py','test_release_package_gates.py','test_packaging.py','test_native_setup_packaging.py',
    'verify_release_source_smoke.py','audit_source_recipe.py','audit_release_archives.py','seed_library.zip',
    'stage-manifest.json','source-stage-manifest.json','START_HERE.md','RELEASE_NOTES.md',
    'THIRD_PARTY_NOTICES.md','SOURCE_README.md','BUILDING.md','package_experimental_candidate.py')
source_entries += [(pack/name,'packaging/'+name) for name in recipe_names]
source_entries += [(pack/name,name) for name in ('START_HERE.md','RELEASE_NOTES.md','THIRD_PARTY_NOTICES.md')]
source_entries += [(pack/'SOURCE_README.md','README.md'),(app/'BUILD_VERIFICATION.json','EXPERIMENTAL_VALIDATION.json')]
print('Creating corresponding source ZIP.',flush=True)
pkg.create_zip(source,source_entries,f'OpticalDesignStudio-Source-{version}/',6)
sums=[]
for path in (portable,source):
    line=pkg.digest(path)+'  '+path.name
    sums.append(line)
    path.with_name(path.name+'.sha256').write_text(line+'\n',encoding='ascii')
(out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='ascii')
shutil.copy2(pack/'RELEASE_NOTES.md',out/'RELEASE_NOTES.md')

sys.path.insert(0,str(pack/'source'))
from desktop_runtime import _safe_parts
checked=0
with zipfile.ZipFile(portable) as archive,zipfile.ZipFile(source) as code:
    prefix='Optical Design Studio/'
    code_prefix=f'OpticalDesignStudio-Source-{version}/'
    seen=set();expanded=0
    for row in archive.infolist():
        parts=_safe_parts(row,seen)
        assert parts[0]=='Optical Design Studio' and len(parts)>1
        assert not pkg.FORBIDDEN_FILES.intersection(part.casefold() for part in parts)
        expanded+=row.file_size
    assert len(archive.infolist())<=30000 and expanded<=8*1024**3
    actual={r.filename[len(prefix):] for r in archive.infolist() if not r.is_dir()}
    assert actual==set(files)|{'PAYLOAD-MANIFEST.json'}
    manifest=json.loads(archive.read(prefix+'PAYLOAD-MANIFEST.json'))
    assert manifest['packaged_self_tests_passed'] is False and manifest['compiled_verification']=='partial'
    for name,row in files.items():
        assert archive.getinfo(prefix+name).file_size==row['size']
    for name in ('Optical Design Studio.exe','OpticalDesignBackend.exe'):
        assert hashlib.sha256(archive.read(prefix+name)).hexdigest()==files[name]['sha256']
    seen=set()
    for row in code.infolist():
        parts=_safe_parts(row,seen)
        assert parts[0]==code_prefix.rstrip('/') and len(parts)>1
        assert not pkg.FORBIDDEN_FILES.intersection(part.casefold() for part in parts)
    for name,row in stage['files'].items():
        if Path(name).suffix in ('.pyd','.dll','.exe'):continue
        for source_archive,target in ((archive,prefix+'_internal/source/'+name),(code,code_prefix+'src/'+name)):
            payload=source_archive.read(target)
            assert len(payload)==row['size'] and hashlib.sha256(payload).hexdigest()==row['sha256'],target
        checked+=1
    for name in recipe_names:
        assert hashlib.sha256(code.read(code_prefix+'packaging/'+name)).hexdigest()==pkg.digest(pack/name)
    for name in pkg.inventory(app/'THIRD_PARTY_LICENSES'):
        assert hashlib.sha256(code.read(code_prefix+'THIRD_PARTY_LICENSES/'+name)).hexdigest()==pkg.digest(app/'THIRD_PARTY_LICENSES'/name)
    for name in pkg.inventory(readable/'S4-source'):
        assert hashlib.sha256(code.read(code_prefix+'native/S4-source/'+name)).hexdigest()==pkg.digest(readable/'S4-source'/name)

validation['archive_integrity']='passed'
validation['assets']=[dict(name=p.name,bytes=p.stat().st_size,sha256=pkg.digest(p)) for p in (portable,source)]
pkg.write_json(out/'VALIDATION.json',validation)
audit=dict(passed=True,version=version,release_channel='highly_experimental',
    frozen_verification='partial',native_startup_verification='not_run',packaged_self_tests_passed=False,
    source_tree_sha256=stage['source_tree_sha256'],portable_files=len(actual),portable_expanded_bytes=expanded,
    source_files_checked_in_both_archives=checked,archive_crc_verified=True,archive_sha256_verified=True,
    personal_data_excluded=True,native_source_and_license_correspondence=True,recipe_correspondence=True,
    assets=validation['assets'],published=False)
pkg.write_json(pack/'experimental-archive-audit.json',audit)
print(json.dumps(audit,indent=2),flush=True)
