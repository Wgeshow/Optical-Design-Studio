"""Keep the finite device and existing optical project tables in agreement."""
import copy
import math
from collections import defaultdict, deque
from device_model import from_optical_project, validate_device,geometry_vertices


def _ring_rectangles(obj):
    """Four nonoverlapping bars preserve a ring in the legacy optical table."""
    sx,sy=obj['size_x_um'],obj['size_y_um']
    ix,iy=obj['inner_size_x_um'],obj['inner_size_y_um']
    angle=math.radians(obj['angle_deg']);c,s=math.cos(angle),math.sin(angle)
    specifications=[(0.,(sy+iy)/4,sx,(sy-iy)/2),
                    (0.,-(sy+iy)/4,sx,(sy-iy)/2),
                    (-(sx+ix)/4,0.,(sx-ix)/2,iy),
                    ((sx+ix)/4,0.,(sx-ix)/2,iy)]
    return [dict(obj,shape='rectangle',cx_um=obj['cx_um']+c*x-s*y,
                 cy_um=obj['cy_um']+s*x+c*y,size_x_um=width,size_y_um=depth)
            for x,y,width,depth in specifications]


def optical_structure(device, electrical_materials, project):
    device=validate_device(device,electrical_materials)
    materials=copy.deepcopy(project['materials'])
    library={row['id']:row for row in electrical_materials}
    by_name={row['Name']:row for row in materials}
    def name_for(obj):
        if obj.get('operation')=='void':
            if 'Air' not in by_name:
                row=dict(Name='Air',Model='constant_nk',A=1.,B=0.,DataFile='',WavelengthUnit='nm')
                materials.append(row);by_name['Air']=row
            return 'Air'
        material=library.get(obj.get('material_id'),{})
        candidates=[obj.get('optical_material_name'),material.get('optical_material_name'),material.get('name')]
        for candidate in candidates:
            if candidate in by_name:return candidate
        props=material.get('properties',{})
        name=(material.get('optical_material_name') or material.get('name') or 'Unassigned optical material')
        if props.get('optical_n') is None:
            name='__optical_unassigned_'+(material.get('id') or obj['id'])
        if name not in by_name:
            row=dict(Name=name,Model='constant_nk',A=props.get('optical_n') or 1.,B=props.get('optical_k') or 0.,DataFile='',WavelengthUnit='nm')
            materials.append(row);by_name[name]=row
        return name
    original=project.get('layers',[])
    exterior=[copy.deepcopy(original[i]) for i in (0,-1)] if len(original)>=2 else [
        dict(Name='Incident_air',Thickness_um=0.,Material='Air'),dict(Name='Exit_air',Thickness_um=0.,Material='Air')]
    name_for({'id':'void','operation':'void'})
    finite=[];mapping={}
    used={row['Name'] for row in exterior}
    for layer in device['layers']:
        if not layer['enabled']:continue
        name=layer['name'];suffix=2
        while name in used:name=layer['name']+'_'+str(suffix);suffix+=1
        used.add(name);mapping[layer['id']]=name
        finite.append(dict(Name=name,Thickness_um=layer['thickness_um'],Material=name_for(layer)))
    patterns=[];polygons=[]
    for obj in device['shapes']:
        if not obj['enabled'] or obj['layer_id'] not in mapping:continue
        material=name_for(obj)
        if obj['shape']=='polygon':
            polygons.append(dict(shape='polygon',layer=mapping[obj['layer_id']],material=material,
                cx=0.,cy=0.,sx=obj['size_x_um'],sy=obj['size_y_um'],angle=0.,vertices=geometry_vertices(obj)))
        else:
            objects=_ring_rectangles(obj) if obj['shape']=='square_ring' else [obj]
            for physical in objects:
                scale=.5 if physical['shape'] in ('circle','ellipse') else 1.
                patterns.append(dict(Shape=physical['shape'],Layer=mapping[obj['layer_id']],Material=material,
                    CenterX_um=physical['cx_um'],CenterY_um=physical['cy_um'],SizeX_um=physical['size_x_um']*scale,
                    SizeY_um=0. if physical['shape']=='circle' else physical['size_y_um']*scale,Angle_deg=physical['angle_deg']))
    return materials,[exterior[0],*finite,exterior[1]],patterns,polygons


def sync_from_optical(project, library, previous=None):
    """Legacy edits preserve contact/doping references by stable layer identity."""
    fresh=from_optical_project(project,library)
    if not previous:return fresh
    library_ids={row['id'] for row in library}
    for group in ('layers','shapes'):
        for obj in fresh[group]:
            marker=obj.get('optical_material_name','')
            if not obj.get('material_id') and marker.startswith('__optical_unassigned_'):
                material_id=marker[len('__optical_unassigned_'):]
                if material_id in library_ids:
                    obj['material_id']=material_id
    old={row['name']:row for row in previous['layers']}
    active_old=[row for row in previous['layers'] if row['enabled']]
    id_map={}
    for index,layer in enumerate(fresh['layers']):
        prior=old.get(layer['name'])
        if prior is None and len(fresh['layers'])==len(active_old):prior=active_old[index]
        if prior:
            id_map[layer['id']]=prior['id'];layer['id']=prior['id']
            for key in ('donor_cm3','acceptor_cm3'):layer[key]=prior.get(key,0.)
    for shape in fresh['shapes']:shape['layer_id']=id_map.get(shape['layer_id'],shape['layer_id'])
    # Adding/assigning an optical material imports the same legacy patterns.
    # Keep the editor's names and IDs for unchanged geometry while retaining
    # the newly imported material assignment. Match each prior shape once so
    # identical footprints still retain distinct editable object identities.
    primitives=[row for row in previous['shapes']
                if row['enabled'] and row['shape'] in ('rectangle','circle','ellipse')]
    claimed=set()
    # Exact exported geometry is the common path for generated PC arrays.
    # Index it once; scanning every prior hole for every imported hole makes
    # a 50,000-hole material edit quadratic. A small precision bucket retains
    # the earlier tolerant matching for rounded external table edits.
    def geometry_keys(row):
        return ('cx_um','cy_um','size_x_um') if row['shape']=='circle' else (
            'cx_um','cy_um','size_x_um','size_y_um','angle_deg')
    def signature(row, rounded=False):
        values=tuple(float(row[key]) for key in geometry_keys(row))
        if rounded:values=tuple(float(format(value,'.8g')) for value in values)
        return (row['layer_id'],row['shape'],*values)
    exact,precision=defaultdict(deque),defaultdict(list)
    for row in primitives:
        exact[signature(row)].append(row)
        precision[signature(row,True)].append(row)
    retained_array_members=set()
    for shape in fresh['shapes']:
        # Circle diameter is size_x; the editor's disabled Y field and a
        # rotation do not change its geometry. Legacy optical import rightly
        # normalizes Y to the diameter, so neither can identify a new object.
        candidates=exact.get(signature(shape))
        while candidates and candidates[0]['id'] in claimed:candidates.popleft()
        prior=candidates.popleft() if candidates else None
        if prior is None:
            candidates=precision.get(signature(shape,True),())
            # Coincident repeated primitives use the exact queue above. Limit
            # fallback work so changed large arrays cannot restore O(N²) scans.
            if len(candidates)<=64:
                prior=next((row for row in candidates if row['id'] not in claimed
                            and all(math.isclose(row[key],shape[key],rel_tol=1e-9,abs_tol=1e-12)
                                    for key in geometry_keys(shape))),None)
        if prior:
            shape['id']=prior['id'];shape['name']=prior['name']
            claimed.add(prior['id'])
            if prior.get('pc_array_id') and shape['operation']==prior['operation']:
                for key in ('pc_array_id','pc_cell'):
                    if key in prior:shape[key]=copy.deepcopy(prior[key])
                retained_array_members.add(prior['id'])
    ids={row['id'] for row in fresh['layers']}
    for key in ('contacts','doping_regions'):
        fresh[key]=[copy.deepcopy(row) for row in previous[key] if row['layer_id'] in ids]
    fresh['shapes'] += [copy.deepcopy(row) for row in previous['shapes'] if row['shape']=='polygon' and row['layer_id'] in ids]
    # Restore one editable ring when its four exported bars remain intact. A
    # legacy edit to an individual bar instead imports the edited rectangles,
    # so no old ring is silently drawn over changed geometry.
    for ring in previous['shapes']:
        if ring['shape']!='square_ring' or not ring['enabled'] or ring['layer_id'] not in ids:
            continue
        matched=[]
        for bar in _ring_rectangles(ring):
            match=next((i for i,row in enumerate(fresh['shapes']) if i not in matched
                        and row['shape']=='rectangle' and row['layer_id']==ring['layer_id']
                        and row['operation']==ring['operation']
                        and (ring['operation']=='void' or row['material_id']==ring['material_id'])
                        and all(math.isclose(row[key],bar[key],rel_tol=1e-9,abs_tol=1e-12)
                                for key in ('cx_um','cy_um','size_x_um','size_y_um','angle_deg'))),None)
            if match is None:
                break
            matched.append(match)
        if len(matched)==4:
            restored=[]
            for i,row in enumerate(fresh['shapes']):
                if i==min(matched):restored.append(copy.deepcopy(ring))
                if i not in matched:restored.append(row)
            fresh['shapes']=restored
    for key in ('name','temperature_K','mesh'):fresh[key]=copy.deepcopy(previous[key])
    if 'pc_arrays' in previous:
        array_members=defaultdict(set)
        for obj in previous['shapes']:
            if obj.get('pc_array_id'):array_members[obj['pc_array_id']].add(obj['id'])
        fresh['pc_arrays']=[copy.deepcopy(row) for row in previous['pc_arrays']
            if array_members[row['id']].issubset(retained_array_members)]
    return validate_device(fresh,library)


def apply_polygons(model, project):
    if project.get('device'):
        _,layers,_,polygons=optical_structure(project['device'],project['electrical_materials'],project)
        by_name={layer['name']:layer for layer in model['layers']}
        active=[layer for layer in project['device']['layers'] if layer['enabled']]
        for physical,optical in zip(active,layers[1:-1]):
            if optical['Name'] in by_name:
                by_name[optical['Name']]['device_layer_id']=physical['id']
        names={layer['name'] for layer in model['layers']}
        model['patterns'].extend(row for row in polygons if row['layer'] in names)
        from contact_optics import apply_contact_optics
        apply_contact_optics(model,project['device'])
    from optical_unit_cell import apply_optical_unit_cell
    apply_optical_unit_cell(model, project.get('settings', {}).get('optical_unit_cell'), project.get('device'))
    return model


def validate_optical_assignment(model):
    used={row['material'] for row in model['layers']}|{row['material'] for row in model['patterns']}
    missing=[row['name'] for row in model['materials'] if row['name'] in used and row['name'].startswith('__optical_unassigned_') and row.get('a')==1. and row.get('b')==0.]
    if missing:
        raise ValueError('Assign optical n/k data in Materials or the electrical material editor before running optics: '+', '.join(missing))
