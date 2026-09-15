"""Analytic STEP solids using OpenCascade directly; construction is in um."""
import hashlib
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from export_geometry import ExportOptions, dimensions, array_centers
from structure_builder import validate_structure


def cad_library():
    local = Path(__file__).parent / 'cad_runtime'
    if local.is_dir() and str(local) not in sys.path:
        sys.path.append(str(local))
    try:
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_Transform
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Common
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.gp import gp_Pnt, gp_Dir, gp_Vec, gp_Ax1, gp_Ax2, gp_Elips, gp_Trsf
        from OCP.TopAbs import TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
    except ImportError as exc:
        raise ValueError('STEP export requires the OpenCascade runtime in requirements-cad.txt.') from exc
    return SimpleNamespace(**locals())


def cad_parts(materials, layers, patterns, settings, options=None, include_air=False):
    options = options or ExportOptions(include_exterior=False)
    ax, ay, width, depth = dimensions(settings, options)
    mats, stack, regions = validate_structure(materials, layers, patterns)
    c = cad_library()
    air = {m['Name'] for m in mats if m['Name'].strip().lower() in ('air', 'vacuum', 'air / vacuum')}
    result, export_layers = [], []
    z = 0.
    if options.include_exterior:
        export_layers.append((stack[0], -options.incident_um, options.incident_um))
    for layer in stack[1:-1]:
        height = float(layer['Thickness_um'])
        if height > 0:
            export_layers.append((layer, z, height))
        z += height
    if options.include_exterior:
        export_layers.append((stack[-1], z, options.exit_um))
    if sum(len(array_centers(r, ax, ay, options)) for r in regions) > 100000:
        raise ValueError('Export exceeds 100,000 patterned copies. Reduce the repeat counts.')
    def solid(shape):
        return not shape.IsNull() and c.TopExp_Explorer(shape, c.TopAbs_SOLID).More()
    for layer, z, height in export_layers:
        host = c.BRepPrimAPI_MakeBox(c.gp_Pnt(-width/2, -depth/2, z), width, depth, height).Shape()
        pieces = [(layer['Material'], host)]
        for region in (r for r in regions if r['Layer'] == layer['Name']):
            sx = float(region['SizeX_um'])
            sy = sx if region['Shape'] == 'circle' else float(region['SizeY_um'])
            angle = math.radians(float(region['Angle_deg']))
            if region['Shape'] == 'rectangle':
                polygon = c.BRepBuilderAPI_MakePolygon()
                for px, py in [(-sx/2,-sy/2), (sx/2,-sy/2), (sx/2,sy/2), (-sx/2,sy/2)]:
                    polygon.Add(c.gp_Pnt(px, py, 0))
                polygon.Close()
                wire = polygon.Wire()
            else:
                axis = c.gp_Ax2(c.gp_Pnt(0,0,0), c.gp_Dir(0,0,1), c.gp_Dir(1,0,0) if sx >= sy else c.gp_Dir(0,1,0))
                edge = c.BRepBuilderAPI_MakeEdge(c.gp_Elips(axis, max(sx,sy), min(sx,sy))).Edge()
                wire = c.BRepBuilderAPI_MakeWire(edge).Wire()
            face = c.BRepBuilderAPI_MakeFace(wire).Face()
            prototype = c.BRepPrimAPI_MakePrism(face, c.gp_Vec(0,0,height)).Shape()
            rotation = c.gp_Trsf()
            rotation.SetRotation(c.gp_Ax1(c.gp_Pnt(0,0,0), c.gp_Dir(0,0,1)), angle)
            prototype = c.BRepBuilderAPI_Transform(prototype, rotation, True).Shape()
            for x, y in array_centers(region, ax, ay, options):
                move = c.gp_Trsf()
                move.SetTranslation(c.gp_Vec(x,y,z))
                tool = c.BRepBuilderAPI_Transform(prototype, move, True).Shape()
                clipped = c.BRepAlgoAPI_Common(tool, host).Shape()
                if not solid(clipped):
                    continue
                pieces = [(name, c.BRepAlgoAPI_Cut(shape, clipped).Shape()) for name, shape in pieces if solid(shape)]
                pieces.append((region['Material'], clipped))
        for index, (material, shape) in enumerate(pieces):
            if solid(shape) and (include_air or material not in air):
                if not c.BRepCheck_Analyzer(shape).IsValid():
                    raise ValueError('CAD geometry could not be built for layer ' + layer['Name'])
                result.append((f'{layer["Name"]} / {material} / {index}', material, shape))
    if not result:
        raise ValueError('No solid domains to export. Enable air domains or include exterior media.')
    return result


def shape_metrics(shapes):
    """Bounds in um and volume in um^3 for kernel shapes."""
    cad_library()
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    bounds = Bnd_Box()
    volume = 0.
    for shape in shapes:
        BRepBndLib.AddOptimal_s(shape, bounds, False, False)
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        volume += props.Mass()
    xmin,ymin,zmin,xmax,ymax,zmax = bounds.Get()
    return dict(x_um=xmax-xmin, y_um=ymax-ymin, z_um=zmax-zmin, volume_um3=volume)


def read_step_metrics(path):
    """Read any supported STEP length unit and report physical um dimensions."""
    cad_library()
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise ValueError('Cannot read STEP file.')
    reader.SetSystemLengthUnit(.001)  # millimeters per model unit: 1 um
    reader.TransferRoots()
    return shape_metrics([reader.OneShape()])


def export_cad_step(path, materials, layers, patterns, settings, options=None, include_air=False):
    options = options or ExportOptions(include_exterior=False)
    parts = cad_parts(materials, layers, patterns, settings, options, include_air)
    from OCP.TDocStd import TDocStd_Document
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
    from OCP.TDataStd import TDataStd_Name
    from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.Interface import Interface_Static
    from OCP.IFSelect import IFSelect_RetDone
    doc = TDocStd_Document(TCollection_ExtendedString('Optical structure'))
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    colors = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
    for name, material, shape in parts:
        label = shapes.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
        rgb = hashlib.sha256(material.encode('utf8')).digest()[:3]
        colors.SetColor(label, Quantity_Color(*(0.3+c/255*.6 for c in rgb), Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    Interface_Static.SetCVal_s('xstep.cascade.unit', 'UM')
    Interface_Static.SetCVal_s('write.step.unit', options.unit.upper())
    if not writer.Transfer(doc, STEPControl_AsIs):
        raise ValueError('STEP transfer failed.')
    destination = Path(path)
    if destination.suffix.lower() not in ('.step', '.stp'):
        destination = destination.with_suffix('.step')
    fd, temp = tempfile.mkstemp(suffix='.step', dir=destination.parent)
    os.close(fd)
    try:
        if writer.Write(temp) != IFSelect_RetDone:
            raise ValueError('STEP file could not be written.')
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return destination
