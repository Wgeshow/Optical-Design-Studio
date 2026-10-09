"""Reproducible benchmark of fresh independent simulations; outputs JSON.

Use --reference-build to compare repaired legacy/internal math with optimized
CPU and hybrid runs. Timings include pool startup; no speedup is assumed.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--build', type=Path, default=ROOT/'build/python')
    p.add_argument('--reference-build', type=Path)
    p.add_argument('--basis', type=int, default=101)
    p.add_argument('--points', type=int, default=32)
    p.add_argument('--repeat', type=int, default=3)
    p.add_argument('--gpu', action='store_true')
    p.add_argument('--gpu-min-n', type=int, default=1024)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    cores = min(4, os.cpu_count() or 1)
    modes = [('cpu_1process_1thread',args.build,1,1,False),
             ('cpu_1process_multithread',args.build,1,cores,False),
             ('cpu_multiprocess',args.build,cores,1,False)]
    if args.reference_build:
        modes.insert(0,('reference_internal_math',args.reference_build,1,1,False))
    if args.gpu:
        modes += [('gpu_1process',args.build,1,1,True), ('hybrid_multiprocess',args.build,cores,1,True)]
    report = {'basis_requested':args.basis,'points':args.points,'repeat':args.repeat,'modes':{}}
    reference_values = None
    for name,build,workers,threads,gpu in modes:
        runs = []
        for _ in range(args.repeat):
            env = os.environ.copy()
            env['PYTHONPATH'] = str(build.resolve())
            env['S4_GPU'] = '0'
            command = [sys.executable,str(ROOT/'examples/parallel_sweep.py'),'--workers',str(workers),
                       '--threads',str(threads),'--basis',str(args.basis),'--points',str(args.points),
                       '--gpu-min-n',str(args.gpu_min_n)]
            if gpu:
                command += ['--gpu']
            result = subprocess.run(command,env=env,capture_output=True,text=True,check=True)
            runs.append(json.loads(result.stdout))
        values = [(x['R'],x['T']) for x in runs[0]['results']]
        if reference_values is None:
            reference_values = values
        error = max((abs(a-b) for actual,expected in zip(values,reference_values)
                     for a,b in zip(actual,expected)),default=0.0)
        modes_report = {'seconds':[r['seconds'] for r in runs],
                        'median_seconds':statistics.median(r['seconds'] for r in runs),
                        'max_abs_RT_difference_from_first_mode':error,
                        'last_results':runs[-1]['results']}
        report['modes'][name] = modes_report
        print(name,modes_report['median_seconds'], 's; max R/T difference',error,flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    else:
        print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
