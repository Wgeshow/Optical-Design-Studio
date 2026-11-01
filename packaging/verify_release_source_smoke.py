"""Run the exact staged end-to-end source harness with a short isolated library."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from stage_release import digest, inventory, tree_digest, write_json

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT/'source'
DEPENDENCIES = Path(os.environ.get('ODS_RELEASE_DEPENDENCIES', ROOT.parent/'s4_ui_redesign'))


def main():
    stage = json.loads((ROOT/'stage-manifest.json').read_text(encoding='utf-8'))
    before = inventory(SOURCE)
    if before != stage['files'] or tree_digest(before) != stage['source_tree_sha256']:
        raise ValueError('Source smoke checks require the exact staged snapshot.')
    output = ROOT/'source-smoke-final'
    output.mkdir(exist_ok=False)
    session = Path(tempfile.mkdtemp(prefix='ods-src-140a1-'))
    report_path = output/'report.json'
    env = dict(os.environ)
    env.update(
        PYTHONPATH=os.pathsep.join([str(SOURCE),str(SOURCE/'tests'),
            str(DEPENDENCIES/'ml_dependencies'),str(DEPENDENCIES/'geometry_dependencies'),
            str(DEPENDENCIES/'plot_dependencies')]),
        QT_QPA_PLATFORM='offscreen',MPLBACKEND='Agg',PYTHONIOENCODING='utf-8',
        S4_SELF_TEST_EXPECT_EMPTY_LIBRARY='1',S4_SELF_TEST_MIN_SAVED_ENTRIES='0',
    )
    started = time.monotonic()
    # Append CAD after the interpreter's existing package paths, preserving
    # the environment's NumPy/SciPy ABI used by the pinned S4 extension.
    launcher = ('import runpy,sys; sys.path.append(sys.argv.pop(1)); '
                'sys.argv[0]=sys.argv.pop(1); runpy.run_path(sys.argv[0],run_name="__main__")')
    with (output/'console.log').open('w',encoding='utf-8') as log:
        child = subprocess.Popen([sys.executable,'-c',launcher,str(DEPENDENCIES/'cad_runtime'),
            str(SOURCE/'installer_smoke.py'),str(report_path),
            '--library',str(session/'User Data')],cwd=SOURCE,env=env,stdout=log,
            stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        write_json(output/'process.json',dict(pid=child.pid,session=str(session),
            source_tree_sha256=stage['source_tree_sha256']))
        try:
            exit_code = child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],check=False,
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child.wait(timeout=20)
            exit_code = 124
    if inventory(SOURCE) != before:
        raise ValueError('Staged source changed during the real source smoke check.')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    fields = report.get('checks',{}).get('native_electric_field_maps_and_features',{})
    speed = report.get('checks',{}).get('simulation_speed_and_scan_storage',{})
    maximize = report.get('checks',{}).get('maximize_restore_painting',{})
    passed = bool(exit_code == 0 and report.get('passed') is True and report.get('frozen') is False
                  and report.get('version') == '1.4.0-alpha.11'
                  and len(report.get('checks',{})) >= 9 and fields.get('passed') is True
                  and fields['detail'].get('selected_csv_verified') is True
                  and fields['detail'].get('volume_depths') == 5
                  and speed.get('passed') is True
                  and all(speed.get('detail',{}).get(name) is True for name in (
                      'spectrum_rta_only','separate_field_job', 'validated_fourier_sampling',
                      'exact_disk_backed_spectrum', 'compact_scan_roundtrip', 'contour_label_parity'))
                  and speed['detail'].get('field_sample_count') == 3
                  and maximize.get('passed') is True
                  and maximize.get('detail',{}).get('maximized_transparency_policy_verified') is True
                  and maximize.get('detail',{}).get('restored_glass_policy') is True
                  and maximize.get('detail',{}).get('looks') == ['glass_dark', 'glass_light'])
    verification = dict(status='passed' if passed else 'failed',passed=passed,exit_code=exit_code,
        source_tree_sha256=stage['source_tree_sha256'],installer_smoke_sha256=digest(SOURCE/'installer_smoke.py'),
        checks_run=len(report.get('checks',{})),checks={name:value['passed'] for name,value in report.get('checks',{}).items()},
        exact_new_field_snapshot_verified=bool(fields.get('detail',{}).get('selected_csv_verified')),
        short_isolated_library=str(session/'User Data'),report=str(report_path),
        elapsed_seconds=time.monotonic()-started)
    write_json(output/'verification.json',verification)
    print(json.dumps(verification,indent=2),flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
