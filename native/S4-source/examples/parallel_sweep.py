"""python examples/parallel_sweep.py --workers 4 [--gpu]

Put the build/python directory on PYTHONPATH first. No S4 import at module scope.
Replace solve_one() with your model; return plain Python values.
"""
import argparse
import json
import time
from s4_parallel import parallel_map

def solve_one(parameters):
    import S4
    frequency, basis = parameters
    simulation = S4.New(Lattice=((1.0, 0.0), (0.0, 1.0)), NumBasis=basis)
    simulation.SetMaterial('Vacuum', 1.0)
    simulation.SetMaterial('Dielectric', 12.0)
    simulation.AddLayer('Top', 0.0, 'Vacuum')
    simulation.AddLayer('Slab', 0.5, 'Dielectric')
    simulation.SetRegionCircle('Slab', 'Vacuum', (0.0, 0.0), 0.2)
    simulation.AddLayer('Bottom', 0.0, 'Vacuum')
    simulation.SetExcitationPlanewave((0.0, 0.0), 1.0, 0.0)
    simulation.SetFrequency(frequency)
    forward, backward = simulation.GetPowerFlux('Top')
    transmitted, _ = simulation.GetPowerFlux('Bottom')
    return {'frequency': frequency, 'R': -backward.real / forward.real,
            'T': transmitted.real / forward.real, 'backend': S4.AccelerationInfo()}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--basis', type=int, default=101)
    parser.add_argument('--points', type=int, default=16)
    parser.add_argument('--gpu', action='store_true')
    parser.add_argument('--gpu-min-n', type=int, default=1024)
    args = parser.parse_args()
    parameters = [(0.25 + i * 0.01, args.basis) for i in range(args.points)]
    started = time.perf_counter()
    results = parallel_map(solve_one, parameters, workers=args.workers,
        threads_per_worker=args.threads, gpu=args.gpu, gpu_min_n=args.gpu_min_n)
    print(json.dumps({'seconds': time.perf_counter() - started, 'results': results}, indent=2))

if __name__ == '__main__':
    main()
