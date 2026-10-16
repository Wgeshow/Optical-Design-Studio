"""Compare two isolated S4 builds, including every modal field/amplitude value.

Example: python compare_structural_fastpaths.py --reference OLD_BUILD
    --candidate NEW_BUILD --dll-dir MKL_DLL_DIRECTORY --output EVIDENCE_DIRECTORY
Each build is imported in a separate worker process; no production installation
is changed. This is a numerical regression suite, not a timing benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


def cases():
    result = []
    for layers in (3, 4, 6):
        for kind in ("uniform", "pattern", "tensor"):
            result.append(dict(name=f"{kind}_{layers}_oblique_skew", layers=layers,
                               kind=kind, basis=32, wavelength=1013.7, skew=True,
                               angles=(17., 23.), bottom=False))
    result.append(dict(name="bottom_exterior", layers=4, kind="pattern", basis=32,
                       wavelength=1031.7, skew=True, angles=(0., 0.), bottom=True))
    for wavelength in (900., 945.1, 1000., 1100., 1154.99, 1155., 1155.01, 1200.):
        result.append(dict(name=f"target_{wavelength:g}", layers=3, kind="pattern",
                           basis=128, wavelength=wavelength, skew=False,
                           angles=(0., 0.), bottom=False))
    return result


def sample(build, dll_dir, output):
    os.environ.update(MKL_NUM_THREADS="1", OMP_NUM_THREADS="1", S4_GPU="0")
    dll_handle = os.add_dll_directory(str(dll_dir)) if os.name == "nt" else None
    if not list(build.glob("S4*.pyd")) and (build/"pcs_s4_runtime").is_dir():
        build = build/"pcs_s4_runtime"
    sys.path.insert(0, str(build))
    import S4
    arrays = {}
    metadata = []
    for case in cases():
        sim = S4.New(Lattice=((.77, 0.), (.13, .73)) if case["skew"] else ((.77, 0.), (0., .77)),
                     NumBasis=case["basis"])
        sim.SetMaterial(Name="air", Epsilon=1.)
        eps = (3.4+.015j)**2
        if case["kind"] == "tensor":
            eps = ((eps, .03j, 0), (-.02j, eps+.2, 0), (0, 0, eps-.1))
        sim.SetMaterial(Name="film", Epsilon=eps)
        sim.SetMaterial(Name="glass", Epsilon=2.25)
        names, thicknesses = ["top"], [0.]
        sim.AddLayer(Name="top", Thickness=0., S4_Material="air")
        for index in range(case["layers"]-2):
            name = f"film{index}"
            thickness = .25 if index == 0 else .11+.03*index
            if index == 1:
                sim.AddLayerCopy(Name=name, Thickness=thickness, S4_Layer="film0")
            else:
                sim.AddLayer(Name=name, Thickness=thickness, S4_Material="film" if index%2==0 else "glass")
                if case["kind"] != "uniform" and index%2==0:
                    sim.SetRegionCircle(S4_Layer=name, S4_Material="air", Center=(0., 0.), Radius=.1)
            names.append(name)
            thicknesses.append(thickness)
        sim.AddLayer(Name="bottom", Thickness=0., S4_Material="glass")
        names.append("bottom")
        thicknesses.append(0.)
        sim.SetExcitationPlanewave(IncidenceAngles=case["angles"],
                                  sAmplitude=.4+.1j if case["skew"] else 0., pAmplitude=1.)
        if case["bottom"]:
            # Negative 1-based order means bottom incidence. This API uses
            # SolveInterior rather than SolveAll and serves as an unchanged-path control.
            sim.SetExcitationExterior(Excitations=((-1, "x", 1.+0j), (-1, "y", .2+.1j)))
        sim.SetFrequency(1000./case["wavelength"])
        boundaries = np.cumsum(thicknesses)
        depths = [-.07, 0.] + [float(boundaries[i-1]+thicknesses[i]*.37)
                               for i in range(1,len(names)-1)] + [float(boundaries[-1]+.07)]
        prefix = case["name"]+"/"
        arrays[prefix+"amplitudes"] = np.asarray([sim.GetAmplitudes(name, .013) for name in names])
        arrays[prefix+"coefficients"] = np.frombuffer(sim.GetFieldCoefficientsMany(depths), dtype=np.complex128)
        arrays[prefix+"fields"] = np.asarray([sim.GetFields(x,y,z) for z in depths
                                              for x,y in ((0.,0.), (.19,-.21),(-.33,.27))])
        flux = np.asarray([sim.GetPowerFlux(name) for name in names])
        arrays[prefix+"flux"] = flux
        if not case["bottom"]:
            with np.errstate(invalid="ignore", divide="ignore"):
                r=-flux[0,1].real/flux[0,0].real
                t=flux[-1,0].real/flux[0,0].real
            arrays[prefix+"rta"] = np.asarray([r,t,1-r-t])
        metadata.append(dict(**case, retained_basis=len(sim.GetBasisSet()),
                             finite=bool(np.isfinite(arrays[prefix+"coefficients"]).all())))
    np.savez(output, **arrays)
    output.with_suffix(".json").write_text(json.dumps(metadata,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference",type=Path)
    parser.add_argument("--candidate",type=Path)
    parser.add_argument("--dll-dir",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--worker",type=Path)
    args=parser.parse_args()
    if args.worker:
        sample(args.worker,args.dll_dir,args.output)
        return
    args.output.mkdir(parents=True,exist_ok=True)
    for name, build in (("reference",args.reference),("candidate",args.candidate)):
        subprocess.run([sys.executable,__file__,"--worker",str(build),"--dll-dir",str(args.dll_dir),
                        "--output",str(args.output/(name+".npz"))],check=True)
    reference=np.load(args.output/"reference.npz")
    candidate=np.load(args.output/"candidate.npz")
    assert set(reference.files)==set(candidate.files)
    report={}
    for name in reference.files:
        a,b=reference[name],candidate[name]
        assert a.shape==b.shape,name
        # Availability and the exact positions of failed coefficients must agree.
        np.testing.assert_array_equal(np.isfinite(a),np.isfinite(b),err_msg=name)
        mask=np.isfinite(a)
        np.testing.assert_allclose(b[mask],a[mask],atol=2e-11,rtol=2e-9,err_msg=name)
        diff=np.abs(a[mask]-b[mask])
        scale=np.maximum(1.,np.abs(a[mask]))
        report[name]=dict(count=int(a.size),finite=int(mask.sum()),
                          max_abs=float(diff.max(initial=0.)),max_scaled=float((diff/scale).max(initial=0.)))
    for side in ("reference","candidate"):
        status=json.loads((args.output/(side+".json")).read_text())
        for case in status:
            assert case["finite"] == (case["wavelength"] != 1155.), (side,case)
    (args.output/"comparison.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(cases=len(cases()), arrays=len(report),
                          values=sum(item["count"] for item in report.values()),
                          max_scaled=max(item["max_scaled"] for item in report.values()),
                          report=str(args.output/"comparison.json")),indent=2))


if __name__=="__main__":
    main()
