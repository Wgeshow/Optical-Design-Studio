"""Portable, append-only user data. Paths in saved records are relative to the library."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone

from model import MAT_COLS, LAYER_COLS, PAT_COLS, number, numeric_rows


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows scanners/readers can briefly hold the previous checkpoint.
                # Keep atomic replacement, retry briefly, and preserve real errors.
                if attempt == 5: raise
                time.sleep(min(.05*2**attempt,.2))
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class DataLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.runs = self.root / 'runs'
        self.data = self.root / 'data_library'
        self.assets = self.data / 'optical_constants'
        self.presets_dir = self.data / 'presets'
        self.exports = self.data / 'exports'
        self.lock = threading.RLock()
        for path in (self.runs, self.assets, self.presets_dir, self.exports):
            path.mkdir(parents=True, exist_ok=True)

    def asset(self, payload):
        name = 'nk_' + hashlib.sha256(payload).hexdigest() + '.csv'
        path = self.assets / name
        with self.lock:
            if path.exists():
                if path.read_bytes() != payload:
                    raise ValueError('Stored optical-constant checksum mismatch: ' + name)
            else:
                temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
                temporary.write_bytes(payload)
                os.replace(temporary, path)
        return path

    def materialize(self, project):
        project = copy.deepcopy(project)
        mapping = {}
        for name, record in project.get('optical_constants', {}).items():
            payload = base64.b64decode(record['base64'], validate=True)
            if hashlib.sha256(payload).hexdigest() != record['sha256']:
                raise ValueError('Embedded optical-constant checksum mismatch')
            mapping[name] = self.asset(payload).name
        for row in project.get('materials', []):
            if row.get('Model') == 'table_nk' and row.get('DataFile') in mapping:
                row['DataFile'] = mapping[row['DataFile']]
        return project

    def snapshot(self, project, uploads=None):
        project = self.materialize(project)
        supplied = {}
        for filename in uploads or []:
            path = Path(filename)
            if path.name in supplied:
                raise ValueError('Duplicate uploaded filename: ' + path.name)
            supplied[path.name] = path
        embedded = {}
        for row in project.get('materials', []):
            if row.get('Model') != 'table_nk':
                continue
            name = Path(str(row.get('DataFile') or '')).name
            path = supplied.get(name)
            if path is None:
                path = self.assets / name
                if not name.startswith('nk_') or not path.is_file():
                    raise ValueError(f"{row.get('Name')}: upload the n,k file '{name}' before saving or running")
            numeric_rows(path, row.get('WavelengthUnit') or 'nm')
            payload = path.read_bytes()
            saved = self.asset(payload)
            row['DataFile'] = saved.name
            embedded[saved.name] = dict(sha256=hashlib.sha256(payload).hexdigest(),
                                       base64=base64.b64encode(payload).decode('ascii'),
                                       original_name=project.get('optical_constants', {}).get(name, {}).get('original_name', name))
        project.update(format_version=3, optical_constants=embedded)
        return project

    def files_for(self, project):
        names = {row['DataFile'] for row in project.get('materials', []) if row.get('Model') == 'table_nk'}
        return [str(self.assets / name) for name in sorted(names)]

    def presets(self):
        result = {}
        for path in sorted(self.presets_dir.glob('*.json')):
            record = read_json(path)
            key = f"{record['label']} [saved {record['created']}; {record['id'][:8]}]"
            result[key] = record
        return result

    def save_preset(self, row, label, notes='', uploads=None):
        row = dict(row)
        row['Name'] = str(row.get('Name') or '').strip()
        if not row['Name']:
            raise ValueError('Enter a material name')
        if row.get('Model') not in ('constant_nk', 'constant_eps', 'table_nk'):
            raise ValueError('Model must be constant_nk, constant_eps, or table_nk')
        if row['Model'] != 'table_nk':
            row['A'] = number(row.get('A'), 'A')
            row['B'] = number(row.get('B'), 'B', default=0)
            row['DataFile'] = ''
        project = self.snapshot(dict(materials=[row]), uploads)
        identifier = uuid.uuid4().hex
        record = dict(id=identifier, label=str(label or row['Name']).strip(), notes=notes or '',
                      created=timestamp(), project=project)
        with self.lock:
            write_json(self.presets_dir / (identifier + '.json'), record)
        return next(key for key, value in self.presets().items() if value['id'] == identifier)

    def directory(self, identifier):
        if not identifier or Path(identifier).name != identifier or ':' in identifier or identifier in ('.', '..'):
            raise ValueError('Choose a saved entry')
        path = (self.runs / identifier).resolve()
        if path.parent != self.runs.resolve() or not path.is_dir():
            raise ValueError('Saved entry not found')
        return path

    def record(self, directory, **updates):
        directory = self.directory(Path(directory).name)
        path = directory / 'library_record.json'
        with self.lock:
            record = read_json(path) if path.exists() else dict(
                id=directory.name, title=directory.name, created=datetime.fromtimestamp(
                    directory.stat().st_mtime, timezone.utc).isoformat(timespec='seconds'),
                kind='saved data', status='saved', notes='')
            record.update(updates, id=directory.name)
            write_json(path, record)
        return record

    def entries(self, query=''):
        records = []
        for path in self.runs.iterdir():
            if not path.is_dir() or path.is_symlink():
                continue
            try:
                meta = path / 'library_record.json'
                if meta.exists():
                    record = read_json(meta)
                else:
                    kind = 'optimization' if (path / 'design_results.csv').exists() else 'simulation'
                    status = 'complete' if (path / 'results.csv').exists() else 'saved'
                    if (path / 'search_summary.json').exists():
                        kind = 'optimization'
                        status = read_json(path / 'search_summary.json').get('status', status)
                    elif (path / 'error.txt').exists():
                        status = 'error'
                    elif (path / 'cancel.flag').exists():
                        status = 'cancelled'
                    elif (path / 's4_project.json').exists():
                        kind = 'project'
                    elif (path / 'search_bounds.json').exists():
                        kind = 'search settings'
                    record = self.record(path, kind=kind, status=status, title=kind.title() + ' ' + path.name[:12])
                if query.lower() in json.dumps(record, ensure_ascii=False).lower():
                    records.append(record)
            except (OSError, ValueError, KeyError):
                # One damaged legacy directory must not hide the rest of the collection.
                records.append(dict(id=path.name, title=path.name, kind='unreadable metadata',
                                    status='inspect files', created='', notes=''))
        return sorted(records, key=lambda item: item['created'], reverse=True)

    def from_model(self, model, base=None):
        project = copy.deepcopy(base or {})
        materials = []
        for mat in model['materials']:
            name = ''
            if mat['model'] == 'table_nk':
                payload = ('wavelength,n,k\n' + '\n'.join(','.join(map(repr, row)) for row in mat['table']) + '\n').encode()
                name = self.asset(payload).name
            materials.append(dict(zip(MAT_COLS, [mat['name'], mat['model'], mat['a'], mat['b'], name, 'nm'])))
        project['materials'] = materials
        project['layers'] = [dict(zip(LAYER_COLS, [r['name'], r['thickness'], r['material']])) for r in model['layers']]
        project['patterns'] = [dict(zip(PAT_COLS, [r['shape'], r['layer'], r['material'], r['cx'], r['cy'], r['sx'], r['sy'], r['angle']])) for r in model['patterns']]
        settings = project.setdefault('settings', {})
        settings.update(ax_um=model['ax'], ay_um=model['ay'], NumG=model['basis'], mode=model['mode'],
                        phi_deg=model['phi'], polarization=model['polarization'])
        points = model.get('points', [])
        if points:
            settings.update(fixed_wl_nm=points[0][1], theta_deg=points[0][2],
                            wl_start_nm=min(p[1] for p in points), wl_stop_nm=max(p[1] for p in points),
                            angle_start=min(p[2] for p in points), angle_stop=max(p[2] for p in points))
            wavelengths = sorted({p[1] for p in points})
            angles = sorted({p[2] for p in points})
            if len(wavelengths) > 1:
                settings['wl_step_nm'] = min(b-a for a, b in zip(wavelengths, wavelengths[1:]))
            if len(angles) > 1:
                settings['angle_step'] = min(b-a for a, b in zip(angles, angles[1:]))
        return self.snapshot(project)

    def project_for(self, identifier, design_id=0):
        directory = self.directory(identifier)
        job = read_json(directory / 'job.json') if (directory / 'job.json').exists() else {}
        search = job.get('search') or {}
        project = search.get('project')
        for name in ('project.json', 's4_project.json'):
            if (directory / name).exists():
                project = read_json(directory / name)
                break
        if design_id:
            with (directory / 'design_models.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    entry = json.loads(line)
                    if entry['design_id'] == design_id:
                        return self.from_model(entry['model'], project), search
            raise ValueError('Design ID not found')
        if project is None and 'model' in job:
            project = self.from_model(job['model'], dict(performance=job.get('performance', {})))
        if project is None:
            raise ValueError('This entry contains no structure. Download its files or select a simulation/optimization.')
        # Legacy jobs contain the actual n,k table even when the original upload is gone.
        try:
            return self.snapshot(project), search
        except ValueError:
            if 'model' not in job:
                raise
            return self.from_model(job['model'], project), search

    def export(self, identifier=None, source_root=None):
        """Export complete run trees, presets and assets; optionally include runnable source."""
        with self.lock:
            self.entries()
            path = self.exports / ('s4_bundle_' + uuid.uuid4().hex + '.zip')
            manifest = dict(format='s4-library', version=1, created=timestamp(), files={})
            candidates = []
            roots = [self.directory(identifier)] if identifier else [self.runs, self.assets, self.presets_dir]
            for root in roots:
                candidates.extend((p, p.relative_to(self.root).as_posix()) for p in root.rglob('*') if p.is_file())
            if source_root:
                source_root = Path(source_root).resolve()
                candidates.extend((p, p.name) for p in source_root.iterdir() if p.is_file() and p.suffix.lower() in
                                  ('.py', '.cmd', '.sh', '.txt', '.md', '.json', '.ps1', '.yml', '.yaml', '.ico'))
                for folder in ('pcs_s4_runtime', 'ml_dependencies', 'S4-source', 'third-party-licenses', 'tests'):
                    candidates.extend((p, p.relative_to(source_root).as_posix()) for p in (source_root / folder).rglob('*') if p.is_file())
                # Keep installer recipes and artwork so an exported application
                # can be rebuilt. Prune build/download trees before walking them;
                # these can contain entire recursive copies of the application.
                packaging = source_root / 'packaging'
                omitted = {'tools', 'work', 'dist', 'build', 'build_input', 'downloads', 'release', 'payload',
                           '__pycache__', '.git', '.venv', 'venv', 'node_modules'}
                source_suffixes = {'.py', '.cmd', '.sh', '.ps1', '.spec', '.iss', '.txt', '.md', '.json',
                                   '.yml', '.yaml', '.toml', '.manifest', '.ico', '.png', '.bmp', '.svg'}
                if packaging.is_dir() and not packaging.is_symlink():
                    for directory, folders, files in os.walk(packaging, followlinks=False):
                        directory = Path(directory)
                        folders[:] = [name for name in folders if name.casefold() not in omitted
                                      and not name.casefold().startswith('work_')
                                      and not (directory / name).is_symlink()]
                        for name in files:
                            candidate = directory / name
                            if candidate.suffix.lower() in source_suffixes or name.upper() in {'LICENSE', 'COPYING', 'NOTICE'}:
                                candidates.append((candidate, candidate.relative_to(source_root).as_posix()))
            try:
                with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                    for file, name in candidates:
                        if file.is_symlink() or any(part in ('__pycache__', '.git') for part in file.parts) or file.suffix == '.tmp':
                            continue
                        digest = hashlib.sha256()
                        size = 0
                        with file.open('rb') as src, archive.open(name, 'w', force_zip64=True) as dst:
                            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                                digest.update(chunk)
                                size += len(chunk)
                                dst.write(chunk)
                        manifest['files'][name] = dict(size=size, sha256=digest.hexdigest())
                    archive.writestr('s4-library-manifest.json', json.dumps(manifest, indent=2))
                return str(path)
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    def import_bundle(self, filename):
        """Verify before merging; uploaded source is never executed or installed."""
        with self.lock, tempfile.TemporaryDirectory(prefix='s4_import_') as temp:
            stage = Path(temp)
            with zipfile.ZipFile(filename) as archive:
                infos = archive.infolist()
                if len(infos) > 100000 or sum(i.file_size for i in infos) > 20 * 1024**3:
                    raise ValueError('Bundle exceeds 100,000 files or 20 GB expanded size')
                seen = set()
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in info.filename
                            or ':' in info.filename or info.filename.casefold() in seen
                            or any(p.rstrip(' .') != p or PureWindowsPath(p).is_reserved() for p in path.parts)
                            or any(ord(c) < 32 or c in '<>\"|?*' for c in info.filename)
                            or (info.external_attr >> 16) & 0o170000 == 0o120000):
                        raise ValueError('Unsafe or duplicate archive path')
                    seen.add(info.filename.casefold())
                if archive.getinfo('s4-library-manifest.json').file_size > 32 * 1024**2:
                    raise ValueError('Bundle manifest exceeds 32 MB')
                manifest = json.loads(archive.read('s4-library-manifest.json'))
                if manifest.get('format') != 's4-library' or manifest.get('version') != 1:
                    raise ValueError('Unsupported S4 library bundle')
                actual = {i.filename for i in infos if not i.is_dir() and i.filename != 's4-library-manifest.json'}
                if actual != set(manifest['files']):
                    raise ValueError('Bundle file inventory does not match its manifest')
                for name, record in manifest['files'].items():
                    parts = PurePosixPath(name).parts
                    keep = (len(parts) >= 3 and parts[0] == 'runs') or (
                        len(parts) == 3 and parts[:2] in (('data_library', 'presets'), ('data_library', 'optical_constants')))
                    target = stage.joinpath(*parts)
                    if keep:
                        target.parent.mkdir(parents=True, exist_ok=True)
                    digest, size = hashlib.sha256(), 0
                    with archive.open(name) as src:
                        dst = target.open('wb') if keep else None
                        try:
                            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                                size += len(chunk)
                                digest.update(chunk)
                                if dst:
                                    dst.write(chunk)
                        finally:
                            if dst:
                                dst.close()
                    if size != record['size'] or digest.hexdigest() != record['sha256']:
                        raise ValueError('Bundle checksum mismatch: ' + name)
            # Validate records and immutable assets before making any live changes.
            incoming_assets = list((stage / 'data_library' / 'optical_constants').glob('*'))
            incoming_presets = list((stage / 'data_library' / 'presets').glob('*.json'))
            for path in incoming_assets:
                if path.name != 'nk_' + hashlib.sha256(path.read_bytes()).hexdigest() + '.csv':
                    raise ValueError('Invalid optical-constant asset name')
            probe = DataLibrary(stage / '_validate')
            for path in incoming_assets:
                probe.asset(path.read_bytes())
            for path in incoming_presets:
                record = read_json(path)
                if (path.name != record['id'] + '.json' or len(record['id']) != 32
                        or any(c not in '0123456789abcdef' for c in record['id'])
                        or not all(isinstance(record.get(k), str) for k in ('label', 'notes', 'created'))
                        or len(record['project']['materials']) != 1):
                    raise ValueError('Invalid preset record')
                project = probe.materialize(record['project'])
                probe.save_preset(project['materials'][0], record['label'], record['notes'])
            for path in (stage / 'runs').glob('*/library_record.json'):
                if not isinstance(read_json(path), dict):
                    raise ValueError('Invalid saved-run metadata')
            for path in incoming_assets:
                self.asset(path.read_bytes())
            imported_presets = 0
            for path in incoming_presets:
                record = read_json(path)
                destination = self.presets_dir / path.name
                if destination.exists():
                    if read_json(destination) == record:
                        continue
                    record['id'] = uuid.uuid4().hex
                    destination = self.presets_dir / (record['id'] + '.json')
                self.materialize(record['project'])
                write_json(destination, record)
                imported_presets += 1
            imported_runs = 0
            for folder in (stage / 'runs').glob('*'):
                if not folder.is_dir():
                    continue
                destination = self.runs / folder.name
                if destination.exists():
                    # Preserve both copies; never replace existing simulation data.
                    destination = self.runs / (folder.name + '_import_' + uuid.uuid4().hex[:12])
                shutil.copytree(folder, destination)
                self.record(destination, imported=timestamp())
                imported_runs += 1
            return dict(runs=imported_runs, presets=imported_presets, assets=len(incoming_assets))
