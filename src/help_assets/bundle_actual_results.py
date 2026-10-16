"""Bundle completed production S4 results and native captures for portable Help."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent))
from field_storage import field_data_path, export_field_csv
source=root.parent.parent/'ui_redesign_20261008'/'silicon-help-simulation'
destination=root/'silicon-reference-run'
provenance=json.loads((source/'provenance.json').read_text(encoding='utf-8'))
validation=json.loads((source/'scientific-validation.json').read_text(encoding='utf-8'))
if provenance['status']!='complete' or validation['status']!='passed':
    raise RuntimeError('Only completed, scientifically checked production results can be bundled.')
run=Path(provenance['actual_run_directory']).resolve()
field=Path(provenance['fields']['displayed_directory']).resolve()
if not run.is_relative_to(source.resolve()) or not field.is_relative_to(run):
    raise RuntimeError('Actual-run source paths must remain inside this workspace capture.')
destination.mkdir(exist_ok=True)
files=[]

def copy(original,name):
    target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(original,target)
    files.append(dict(file=name,source=str(original.resolve()),bytes=target.stat().st_size,
                      sha256=hashlib.sha256(target.read_bytes()).hexdigest()))


def copy_fields(directory,name):
    original=field_data_path(directory)
    target=export_field_csv(directory,destination/name)
    files.append(dict(file=name,source=str(original.resolve()),bytes=target.stat().st_size,
                      sha256=hashlib.sha256(target.read_bytes()).hexdigest()))

for name in ('provenance.json','scientific-validation.json','backend-events.json','run_and_capture.py'):
    copy(source/name,name)
for name in provenance['images']+['actual-electric-field-maps.png','actual-spectrum-export.png']:
    if not name.endswith('.png') or Path(name).name!=name:raise RuntimeError('Unexpected native image name')
    copy(source/name,name)
for name in ('results.csv','project.json','job.json','diagnostics.json','desktop_request.json','backend_stderr.txt'):
    copy(run/name,name)
copy_fields(field,'electric_fields.csv')
for name in ('field_model.json','field_features.json','field_diagnostics.json','airhole_field_metrics.json'):
    if (field/name).is_file():copy(field/name,name)
samples=json.loads((run/'fields'/'samples.json').read_text(encoding='utf-8'))
copy(run/'fields'/'samples.json','field-samples-source.json')
portable_samples=[]
for index,sample in enumerate(samples['samples'],1):
    directory=Path(sample['directory']).resolve()
    if not directory.is_relative_to(run):raise RuntimeError('Unexpected wavelength field source')
    name=f'all-wavelength-fields/sample-{index:06d}.csv'
    copy_fields(directory,name)
    portable_samples.append(dict(point_index=sample['point_index'],wavelength_nm=sample['wavelength_nm'],
        angle_deg=sample['angle_deg'],file=name))
(destination/'field-samples.json').write_text(json.dumps(dict(status=samples['status'],settings=samples['settings'],samples=portable_samples),indent=2),encoding='utf-8')
sample_index=destination/'field-samples.json'
files.append(dict(file='field-samples.json',source='Portable index generated from field-samples-source.json',
                  bytes=sample_index.stat().st_size,sha256=hashlib.sha256(sample_index.read_bytes()).hexdigest()))
for item in validation['basis_comparisons']:
    directory=Path(item['directory']).resolve()
    if not directory.is_relative_to(source.resolve()):raise RuntimeError('Unexpected basis comparison source')
    for name in ('results.csv','project.json','job.json','diagnostics.json','backend_stdout.jsonl','backend_stderr.txt'):
        if (directory/name).is_file():copy(directory/name,f"basis-{item['requested_NumG']}/"+name)
bundle=dict(status='complete',description='Actual production S4 results; constant-index demonstration model, not measured-material validation.',
    original_provenance='provenance.json',scientific_validation='scientific-validation.json',
    displayed_spectrum='results.csv',displayed_fields='electric_fields.csv',field_sample_index=35,
    displayed_wavelength_nm=1550,all_wavelength_fields='field-samples.json',files=files)
(destination/'bundle.json').write_text(json.dumps(bundle,indent=2),encoding='utf-8')
# Loading the tutorial now restores precisely the settings used in the actual
# displayed run, rather than a different default sweep or Fourier basis.
project=json.loads((destination/'project.json').read_text(encoding='utf-8'))
project['example_notes']='220 nm Silicon on semi-infinite SiO2, 100 nm radius Air holes and 540 nm square period. Constant Silicon n=3.48 and SiO2 n=1.45 with k=0 are explicit approximations. The separate Help result bundle records the completed production S4 run and its data; this project file restores the calculation inputs.'
(root/'air-hole-example.json').write_text(json.dumps(project,indent=2),encoding='utf-8')
print(f'Bundled {len(files)} original files and {len(portable_samples)} wavelength field datasets')
