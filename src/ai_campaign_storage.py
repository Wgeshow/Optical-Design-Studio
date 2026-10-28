"""Relocatable AI checkpoint reads and archives without rewriting saved evidence."""
import copy
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

PATHS_FILE='campaign_paths.json'


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _inside(root,relative):
    relative=PurePosixPath(str(relative).replace('\\','/'))
    if relative.is_absolute() or '..' in relative.parts or any(':' in part for part in relative.parts):
        raise ValueError('Campaign field path must stay inside the extracted archive.')
    candidate=(root/Path(*relative.parts)).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError('Campaign field path leaves the extracted archive.')
    return candidate


def resolve_campaign_paths(saved,checkpoint):
    """Return a copy with usable field paths; the checkpoint is never changed.

    Legacy collection archives used absolute paths but kept their designs tree.
    New archives carry an explicit manifest, also covering fit-only records whose
    original fields live in another run. Local archived evidence takes priority
    even when the old machine's absolute path still happens to exist.
    """
    path=Path(checkpoint).resolve();root=path.parent;saved=copy.deepcopy(saved)
    manifest=_read(root/PATHS_FILE) if (root/PATHS_FILE).is_file() else None
    if manifest is not None and manifest.get('schema_version')!=1:
        raise ValueError('Unsupported campaign path manifest.')
    entries={}
    for entry in (manifest or {}).get('records',[]):
        index=entry.get('record_index')
        if not isinstance(index,int) or isinstance(index,bool) or index in entries:
            raise ValueError('Invalid campaign path manifest record.')
        entries[index]=entry
    records=saved.get('records',[])
    if any(index<0 or index>=len(records) for index in entries):
        raise ValueError('Campaign path manifest refers to an unknown record.')
    for index,record in enumerate(records):
        original=str(record.get('field_directory',''));candidate=None
        if index in entries:
            entry=entries[index]
            if entry.get('original_field_directory')!=original or entry.get('measurement_key')!=record.get('measurement_key'):
                raise ValueError('Campaign path manifest does not match its saved observation.')
            candidate=_inside(root,entry['relative_field_directory'])
            if not (candidate/'field_features.json').is_file():
                raise ValueError(f'Archived fields are missing for observation {index+1}.')
        elif original:
            parts=str(original).replace('\\','/').split('/')
            # Only recover the known legacy designs/<identifier>/fields layout;
            # do not guess arbitrary directories or silently use another record.
            if len(parts)>=3 and parts[-3]=='designs' and parts[-1]=='fields' and parts[-2].isdigit():
                local=_inside(root,'/'.join(parts[-3:]))
                if (local/'field_features.json').is_file():candidate=local
            if candidate is None and not Path(original).is_absolute() and ':' not in original:
                local=_inside(root,original)
                if (local/'field_features.json').is_file():candidate=local
        if candidate is not None and str(candidate)!=original:
            record.setdefault('source_field_directory',original)
            record['field_directory']=str(candidate)
    references=(manifest or {}).get('references',[])
    if references:
        settings=saved.setdefault('settings',{})
        original=str(settings.get('reference_directory',''))
        sources=[part.strip() for part in original.split(';') if part.strip()]
        if len(references)!=len(sources):
            raise ValueError('Campaign reference manifest does not match its settings.')
        relocated=[]
        for entry,source in zip(references,sources):
            if entry.get('original_reference_directory')!=source:
                raise ValueError('Campaign reference manifest does not match its settings.')
            candidate=_inside(root,entry['relative_reference_directory'])
            if not (candidate/'field_features.json').is_file():
                raise ValueError('Archived reference field features are missing.')
            relocated.append(str(candidate))
        settings.setdefault('source_reference_directory',original)
        settings['reference_directory']=';'.join(relocated)
    return saved


def load_campaign_checkpoint(path):
    return resolve_campaign_paths(_read(path),path)


def export_campaign_archive(directory,target):
    """Archive current evidence and all referenced fields, preserving file bytes."""
    root=Path(directory).resolve();target=Path(target).resolve()
    if target.suffix.lower()!='.zip':target=target.with_suffix('.zip')
    if target.is_relative_to(root):
        raise ValueError('Choose an export location outside the saved run directory.')
    raw=_read(root/'campaign.json');resolved=resolve_campaign_paths(raw,root/'campaign.json')
    entries={}
    for file in root.rglob('*'):
        if not file.is_file() or file==root/PATHS_FILE:continue
        if not file.resolve().is_relative_to(root):
            raise ValueError('Saved campaign contains a file link outside its directory.')
        entries[file.relative_to(root).as_posix()]=file
    manifest=dict(schema_version=1,source_campaign=str(root/'campaign.json'),records=[])
    copied={}
    for index,(original,record) in enumerate(zip(raw.get('records',[]),resolved.get('records',[]))):
        source=Path(record.get('field_directory','')).resolve()
        if not (source/'field_features.json').is_file() or not any((source/name).is_file() for name in ('electric_fields.npz','electric_fields.csv')):
            raise ValueError(f'Cannot export observation {index+1}: its saved field data is missing.')
        if source.is_relative_to(root):relative=source.relative_to(root).as_posix()
        else:
            relative=copied.get(source)
            if relative is None:
                relative=f'portable_fields/{index+1:06d}'
                if any(name==relative or name.startswith(relative+'/') for name in entries):
                    raise ValueError('Portable field archive path conflicts with existing data.')
                copied[source]=relative
                for file in source.rglob('*'):
                    if not file.is_file():continue
                    if not file.resolve().is_relative_to(source):
                        raise ValueError('Saved fields contain a file link outside their directory.')
                    entries[relative+'/'+file.relative_to(source).as_posix()]=file
        manifest['records'].append(dict(record_index=index,measurement_key=original.get('measurement_key'),
            original_field_directory=original.get('field_directory',''),relative_field_directory=relative))
    manifest['references']=[]
    if raw.get('settings',{}).get('approach')=='reference':
        original_references=[v.strip() for v in raw['settings'].get('reference_directory','').split(';') if v.strip()]
        resolved_references=[v.strip() for v in resolved['settings'].get('reference_directory','').split(';') if v.strip()]
        for index,(original,location) in enumerate(zip(original_references,resolved_references)):
            source=Path(location).resolve()
            if not (source/'field_features.json').is_file():
                raise ValueError(f'Cannot export reference {index+1}: saved field features are missing.')
            if source.is_relative_to(root):relative=source.relative_to(root).as_posix()
            else:
                relative=copied.get(source)
                if relative is None:
                    relative=f'portable_references/{index+1:06d}'
                    if any(name==relative or name.startswith(relative+'/') for name in entries):
                        raise ValueError('Portable reference archive path conflicts with existing data.')
                    copied[source]=relative
                    for file in source.rglob('*'):
                        if not file.is_file():continue
                        if not file.resolve().is_relative_to(source):
                            raise ValueError('Reference fields contain a file link outside their directory.')
                        entries[relative+'/'+file.relative_to(source).as_posix()]=file
            manifest['references'].append(dict(original_reference_directory=original,relative_reference_directory=relative))
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='ods-campaign-',suffix='.zip',dir=target.parent,delete=False) as handle:
            temporary=Path(handle.name)
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,file in sorted(entries.items()):archive.write(file,name)
            archive.writestr(PATHS_FILE,json.dumps(manifest,indent=2)+'\n')
        os.replace(temporary,target);temporary=None
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return target
