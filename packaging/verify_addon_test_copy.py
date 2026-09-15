"""Check the add-on-free shell; missing CAD is expected until installed."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    payload, output = args.payload.resolve(), args.output.resolve()
    output.mkdir(exist_ok=False)
    if (payload/'_internal'/'cad_runtime').exists() or list((payload/'_internal').glob('cublas*.dll')):
        raise ValueError('The test copy still includes native add-on payloads.')
    env = {key:value for key,value in os.environ.items()
        if not key.upper().startswith(('PYTHON','CONDA','S4_','QT_','MPL','MKL','OMP','OPENBLAS'))}
    windows = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env.update(PATH=os.pathsep.join([str(windows/'System32'),str(windows)]),
        PYTHONNOUSERSITE='1', PYINSTALLER_RESET_ENVIRONMENT='1', QT_QPA_PLATFORM='offscreen',
        S4_LIBRARY_ROOT=str(output/'User Data'), S4_SELF_TEST_MIN_SAVED_ENTRIES='0',
        S4_SELF_TEST_EXPECT_EMPTY_LIBRARY='1', S4_SELF_TEST_GPU='0')
    report = output/'report.json'
    with (output/'stdout.log').open('w') as stdout, (output/'stderr.log').open('w') as stderr:
        process = subprocess.run([str(payload/'Optical Design Studio.exe'),'--self-test',str(report)],
            cwd=output, env=env, stdout=stdout, stderr=stderr, timeout=300,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    data = json.loads(report.read_text(encoding='utf-8'))
    failures = {key:value for key,value in data['checks'].items() if not value['passed']}
    expected = (set(failures)=={'cad_and_comsol_export'} and
        'STEP export requires the OpenCascade runtime' in failures['cad_and_comsol_export'].get('traceback',''))
    required = {'bundled_library','desktop_pages_and_themes','machine_learning_fit_predict',
        'native_cpu_spectrum','native_electric_field_maps_and_features','dependency_origins'}
    passed = process.returncode==1 and expected and required.issubset(data['checks'])
    summary = dict(passed=passed, expected_unavailable='CAD runtime intentionally absent',
        verified_checks=[key for key,value in data['checks'].items() if value['passed']], report=str(report))
    (output/'addon-shell-check.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    return 0 if passed else 1


if __name__=='__main__':
    raise SystemExit(main())
