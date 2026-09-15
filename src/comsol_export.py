"""Export the S4 unit cell as an editable COMSOL Java API model."""
from __future__ import annotations

import math
import re
from pathlib import Path

from model import LAYER_COLS, MAT_COLS, PAT_COLS
from structure_builder import rows, validate_structure
from structure_preview import normalize_region, periodic_centers
from export_geometry import ExportOptions, dimensions, array_centers


BUILD_HELPER = r'''# Compile the adjacent Java source with your installed COMSOL version.
param([string]$ComsolBin, [switch]$BuildMph, [string]$Source)
$ErrorActionPreference = 'Stop'
$source = if ($Source) { (Resolve-Path -LiteralPath $Source).Path } else { Join-Path $PSScriptRoot '@@NAME@@.java' }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing Java source: $source" }
$modelName = [IO.Path]::GetFileNameWithoutExtension($source)
if ([IO.Path]::GetExtension($source) -cne '.java' -or $modelName -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw 'Select the original .java source with its original Java class filename.' }
if (-not $ComsolBin) {
    $found = Get-Command comsolcompile.exe -ErrorAction SilentlyContinue
    if ($found) { $ComsolBin = Split-Path $found.Source }
}
if (-not $ComsolBin) {
    $candidates = @(
        "$env:ProgramFiles\COMSOL\COMSOL*\Multiphysics\bin\win64\comsolcompile.exe",
        "$env:ProgramFiles\COMSOL*\Multiphysics\bin\win64\comsolcompile.exe"
    )
    $found = @(Get-ChildItem -Path $candidates -ErrorAction SilentlyContinue | Sort-Object FullName -Unique)
    if ($found.Count -eq 1) { $ComsolBin = $found[0].DirectoryName }
}
if (-not $ComsolBin) { throw 'Specify -ComsolBin with your COMSOL Multiphysics bin\win64 folder. If several versions are installed, choose the version in which you will open the model.' }
$compiler = Join-Path $ComsolBin 'comsolcompile.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) { throw "COMSOL compiler not found: $compiler" }
# Keep each build separate so existing class/model files are never overwritten.
$build = Join-Path (Split-Path $source) ($modelName + '_compiled_' + [Guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $build | Out-Null
Copy-Item -LiteralPath $source -Destination $build
Push-Location -LiteralPath $build
try {
    & $compiler "$modelName.java" 2>&1 | Tee-Object -FilePath 'compile.log'
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath "$modelName.class")) {
        throw "COMSOL compilation failed. Read $build\compile.log"
    }
    Write-Host "Compiled successfully: $build\$modelName.class"
    Write-Host 'In COMSOL choose File > Open > Compiled Model File for Java (*.class), then select this class file.'
    Write-Host 'After the model builds, save it as an MPH file. Do not import the Java source as geometry or rename it to .mph.'
    if ($BuildMph) {
        $batch = Join-Path $ComsolBin 'comsolbatch.exe'
        if (-not (Test-Path -LiteralPath $batch -PathType Leaf)) { throw "COMSOL batch launcher not found: $batch" }
        & $batch '-inputfile' "$modelName.class" '-outputfile' "$modelName.mph" '-batchlog' 'model-build.log'
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath "$modelName.mph")) {
            throw "COMSOL model build failed. Read $build\model-build.log"
        }
        Write-Host "Open the completed model: $build\$modelName.mph"
    }
} finally { Pop-Location }
'''


def export_instructions(name):
    return f'''COMSOL export: {name}

The .java file is SOURCE CODE, not an MPH model or a geometry-import file.
COMSOL File > Open accepts the COMPILED .class model. Compile with the same
COMSOL version that you will use to open it. Renaming a file does not convert it.

Windows (PowerShell opened in this export folder):
  .\\{name}.build.ps1 -ComsolBin 'C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics\\bin\\win64'
Replace the example installation path with your installed COMSOL version.
If script execution is restricted, use the manual compiler command below;
there is no need to change your system execution policy.

Manual PowerShell command:
  & 'C:\\Program Files\\COMSOL\\COMSOL64\\Multiphysics\\bin\\win64\\comsolcompile.exe' '{name}.java'

Linux/macOS (from a terminal with COMSOL on PATH):
  comsol compile {name}.java

Then File > Open > Compiled Model File for Java (*.class), select {name}.class,
wait for the geometry/model to build, and Save As an .mph model.
The Windows helper optionally accepts -BuildMph to build the MPH in batch mode.
The helper stores results and error logs in a new compiled subfolder each run.

This exports geometry and material setup; physics, ports and PMLs still need setup.
Tabulated n/k materials need manual interpolation setup before simulation.
Compilation/model building requires a local COMSOL installation. Java export alone
does not prove that COMSOL compiled or built the model successfully.

Official instructions:
https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_intro.46.09.html
'''


def _tag(value, prefix="v"):
    text = re.sub(r"[^A-Za-z0-9_]", "_", str(value)).strip("_").lower()
    if not text or text[0].isdigit():
        text = prefix + "_" + text
    return text[:48]


def _class_name(value):
    text = re.sub(r"[^A-Za-z0-9_$]", "_", str(value))
    if not text or not (text[0].isalpha() or text[0] in "_$"):
        text = "S4_" + text
    return text


def _q(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("COMSOL dimensions and material constants must be finite.")
    return format(result, ".15g")


def _expr(value, unit="um"):
    return _q(f"{_num(value)}[{unit}]")


def _unique_tags(values, prefix):
    used = set()
    result = {}
    for value in values:
        base = _tag(value, prefix)
        candidate, suffix = base, 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        result[value] = candidate
    return result


def comsol_java(materials, layers, patterns, settings, class_name="S4UnitCell", options=None):
    """Return a COMSOL 6.x Java model containing geometry and material selections."""
    mats, stack, regions = validate_structure(materials, layers, patterns)
    if not isinstance(settings, dict):
        raise ValueError("COMSOL export settings must be a mapping.")
    ax, ay = float(settings.get("ax_um", 0)), float(settings.get("ay_um", 0))
    if not math.isfinite(ax) or not math.isfinite(ay) or ax <= 0 or ay <= 0:
        raise ValueError("Lattice periods must be finite and greater than zero.")

    material_tags = _unique_tags([row["Name"] for row in mats], "mat")
    layer_tags = _unique_tags([row["Name"] for row in stack], "layer")
    finite_layers = stack[1:-1]
    total = sum(float(row["Thickness_um"]) for row in finite_layers)
    default_padding = max(ax, ay)
    options = options or ExportOptions(incident_um=default_padding, exit_um=default_padding)
    ax, ay, width, depth = dimensions(settings, options)
    if sum(len(array_centers(r, ax, ay, options)) for r in regions) > 100000:
        raise ValueError('Export exceeds 100,000 patterned copies. Reduce the repeat counts.')
    lines = [
        '// Java SOURCE: compile with COMSOL before opening the resulting .class.',
        '// See the adjacent .README.txt and .build.ps1 files.',
        "import com.comsol.model.*;",
        "import com.comsol.model.util.*;",
        "",
        f"public class {_class_name(class_name)} {{",
        "  public static Model run() {",
        '    Model model = ModelUtil.create("Model");',
        '    model.modelPath(".");',
        '    model.label("S4 unit cell.mph");',
        '    model.param().set("ax", ' + _expr(ax) + ', "Unit-cell period X");',
        '    model.param().set("ay", ' + _expr(ay) + ', "Unit-cell period Y");',
        f'    model.param().set("cells_x", "{options.cells_x}");',
        f'    model.param().set("cells_y", "{options.cells_y}");',
        '    model.param().set("width", "cells_x*ax");',
        '    model.param().set("depth", "cells_y*ay");',
        '    model.param().set("incident_padding", ' + _expr(options.incident_um) + ', "Finite incident-medium thickness");',
        '    model.param().set("exit_padding", ' + _expr(options.exit_um) + ', "Finite exit-medium thickness");',
        '    model.param().set("pml_thickness", ' + _expr(default_padding / 2) + ', "Suggested PML thickness; create PMLs after choosing physics");',
        '    model.param().set("lambda0", ' + _q(f'{_num(settings.get("fixed_wl_nm", settings.get("wl_start_nm", 1550)))}[nm]') + ', "Reference wavelength");',
        '    model.component().create("comp1", true);',
        '    model.component("comp1").geom().create("geom1", 3);',
        f'    model.component("comp1").geom("geom1").lengthUnit("{options.unit}");',
        '    GeomSequence g = model.component("comp1").geom("geom1");',
        "",
    ]
    for name, tag in material_tags.items():
        lines += [
            f'    g.selection().create("sel_{tag}", "CumulativeSelection");',
            f'    g.selection("sel_{tag}").label({_q(name + " domains")});',
            f'    g.selection("sel_{tag}").show(true);',
        ]

    # Add finite stand-ins for the two S4 half-spaces, then the physical stack.
    export_layers = [dict(stack[0], Thickness_um="incident_padding", _z="-incident_padding")]
    z = 0.0
    for row in finite_layers:
        if float(row['Thickness_um']) > 0:
            export_layers.append(dict(row, _z=_num(z)+'[um]'))
        z += float(row["Thickness_um"])
    export_layers.append(dict(stack[-1], Thickness_um="exit_padding", _z=_num(total)+'[um]'))
    if not options.include_exterior:
        export_layers = export_layers[1:-1]

    by_layer = {}
    for index, region in enumerate(regions):
        by_layer.setdefault(region["Layer"], []).append((index, region))

    for layer_index, layer in enumerate(export_layers):
        ltag = layer_tags[layer["Name"]]
        block = f"blk_{ltag}"
        height = layer["Thickness_um"]
        height_expr = _q(height) if isinstance(height, str) else _expr(height)
        z_expr = _q(layer["_z"]) if isinstance(layer["_z"], str) else _expr(layer["_z"])
        lines += [
            "",
            f'    g.create("{block}", "Block");',
            f'    g.feature("{block}").label({_q(layer["Name"])});',
            f'    g.feature("{block}").set("base", "corner");',
            f'    g.feature("{block}").set("size", new String[]{{"width", "depth", {height_expr}}});',
            f'    g.feature("{block}").set("pos", new String[]{{"-width/2", "-depth/2", {z_expr}}});',
        ]
        subtract = []
        for region_index, region in by_layer.get(layer["Name"], []):
            normalized = normalize_region(region)
            centers = array_centers(region, ax, ay, options)
            for copy_index, center in enumerate(centers, 1):
                suffix = f"{region_index+1}_{copy_index}"
                wp, shape, ext = f"wp_{suffix}", f"sh_{suffix}", f"ext_{suffix}"
                clip, clipped = f"clip_{suffix}", f"int_{suffix}"
                subtract.append(clipped)
                lines += [
                    f'    g.create("{wp}", "WorkPlane");',
                    f'    g.feature("{wp}").set("quickplane", "xy");',
                    f'    g.feature("{wp}").set("quickz", {z_expr});',
                ]
                if region["Shape"] == "rectangle":
                    lines += [
                        f'    g.feature("{wp}").geom().create("{shape}", "Rectangle");',
                        f'    g.feature("{wp}").geom().feature("{shape}").set("base", "center");',
                        f'    g.feature("{wp}").geom().feature("{shape}").set("size", new String[]{{{_expr(region["SizeX_um"])}, {_expr(region["SizeY_um"])}}});',
                    ]
                else:
                    sy = region["SizeX_um"] if region["Shape"] == "circle" else region["SizeY_um"]
                    lines += [
                        f'    g.feature("{wp}").geom().create("{shape}", "Ellipse");',
                        f'    g.feature("{wp}").geom().feature("{shape}").set("semiaxes", new String[]{{{_expr(region["SizeX_um"])}, {_expr(sy)}}});',
                    ]
                lines += [
                    f'    g.feature("{wp}").geom().feature("{shape}").set("pos", new String[]{{{_expr(center[0])}, {_expr(center[1])}}});',
                    f'    g.feature("{wp}").geom().feature("{shape}").set("rot", {_q(_num(region["Angle_deg"]))});',
                    f'    g.create("{ext}", "Extrude");',
                    f'    g.feature("{ext}").set("workplane", "{wp}");',
                    f'    g.feature("{ext}").set("distance", {height_expr});',
                    f'    g.create("{clip}", "Block");',
                    f'    g.feature("{clip}").set("base", "corner");',
                    f'    g.feature("{clip}").set("size", new String[]{{"width", "depth", {height_expr}}});',
                    f'    g.feature("{clip}").set("pos", new String[]{{"-width/2", "-depth/2", {z_expr}}});',
                    f'    g.create("{clipped}", "Intersection");',
                    f'    g.feature("{clipped}").selection("input").set(new String[]{{"{ext}", "{clip}"}});',
                    f'    g.feature("{clipped}").set("selresult", "on");',
                    f'    g.feature("{clipped}").set("contributeto", "sel_{material_tags[region["Material"]]}");',
                ]
        host_feature = block
        if subtract:
            host_feature = f"dif_{ltag}"
            quoted = ", ".join(_q(item) for item in subtract)
            lines += [
                f'    g.create("{host_feature}", "Difference");',
                f'    g.feature("{host_feature}").selection("input").set(new String[]{{"{block}"}});',
                f'    g.feature("{host_feature}").selection("input2").set(new String[]{{{quoted}}});',
                f'    g.feature("{host_feature}").set("keepsubtract", true);',
            ]
        lines += [
            f'    g.feature("{host_feature}").set("selresult", "on");',
            f'    g.feature("{host_feature}").set("contributeto", "sel_{material_tags[layer["Material"]]}");',
        ]

    lines += ["", '    g.run();', ""]
    for index, mat in enumerate(mats, 1):
        name, tag, mode = mat["Name"], material_tags[mat["Name"]], mat["Model"]
        if mode == "constant_eps":
            eps = complex(float(mat["A"]), -float(mat["B"]))
        elif mode == "constant_nk":
            eps = complex(float(mat["A"]), -float(mat["B"])) ** 2
        else:
            eps = 1 + 0j
        eps_text = _num(eps.real) + (("+" if eps.imag >= 0 else "") + _num(eps.imag) + "*i" if eps.imag else "")
        lines += [
            f'    model.component("comp1").material().create("mat{index}", "Common");',
            f'    model.component("comp1").material("mat{index}").label({_q(name)});',
            f'    model.component("comp1").material("mat{index}").selection().named("geom1_sel_{tag}_dom");',
            f'    model.component("comp1").material("mat{index}").propertyGroup("def").set("relpermittivity", new String[]{{{_q(eps_text)}, "0", "0", "0", {_q(eps_text)}, "0", "0", "0", {_q(eps_text)}}});',
            f'    model.component("comp1").material("mat{index}").propertyGroup("def").set("relpermeability", new String[]{{"1", "0", "0", "0", "1", "0", "0", "0", "1"}});',
        ]
        if mode == "table_nk":
            lines.append(f'    // TODO: {name}: attach the exported n,k table {_q(mat.get("DataFile") or "(missing filename)")} as interpolation functions of wavelength.')

    lines += [
        "",
        '    // The x/y side pairs are periodic. Add Floquet periodic conditions in your chosen wave physics.',
        '    // Use incident_padding, exit_padding and pml_thickness when adding ports and PML domains.',
        "    return model;",
        "  }",
        "",
        "  public static void main(String[] args) throws java.io.IOException {",
        "    run();",
        "  }",
        "}",
        "",
    ]
    return "\n".join(lines)


def export_comsol_java(path, materials, layers, patterns, settings, options=None):
    destination = Path(path)
    if destination.suffix.lower() != ".java":
        destination = destination.with_suffix(".java")
    if _class_name(destination.stem) != destination.stem or destination.stem in {'class', 'public', 'void', 'int', 'package', 'import'}:
        raise ValueError('Choose a Java filename starting with a letter and containing only letters, digits, and underscores.')
    text = comsol_java(materials, layers, patterns, settings, destination.stem, options)
    destination.with_suffix('.build.ps1').write_text(BUILD_HELPER.replace('@@NAME@@', destination.stem), encoding='utf-8')
    destination.with_suffix('.README.txt').write_text(export_instructions(destination.stem), encoding='utf-8')
    destination.write_text(text, encoding="utf-8", newline="\n")
    return destination
