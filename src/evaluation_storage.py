"""Persist every completed native worker batch, including interrupted evaluations."""
import csv
import os
from pathlib import Path
from data_library import write_json, timestamp


class EvaluationRecorder:
    def __init__(self, directory, executor):
        self.directory = Path(directory)
        self.executor = executor
        self.index = 0

    def __call__(self, model, perf, emit=lambda event: None, cancelled=lambda: False):
        self.index += 1
        directory = self.directory / 'evaluations' / f'{self.index:06d}'
        directory.mkdir(parents=True, exist_ok=False)
        write_json(directory / 'model.json', dict(model=model, performance=perf))
        write_json(directory / 'status.json', dict(status='running', started=timestamp()))
        completed = 0
        with (directory / 'batch_results.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['point_index', 'wavelength_nm', 'angle_deg', 'R', 'T', 'A'])
            stream.flush()

            def checkpoint(rows):
                nonlocal completed
                writer.writerows(rows)
                completed += len(rows)
                stream.flush()
                os.fsync(stream.fileno())

            try:
                result = self.executor(model, perf, emit, cancelled, checkpoint=checkpoint)
                write_json(directory / 'diagnostics.json', result[1])
                write_json(directory / 'status.json', dict(status='complete', completed_points=completed, finished=timestamp()))
                return result
            except BaseException as exc:
                write_json(directory / 'status.json', dict(status='interrupted', completed_points=completed,
                                                          error=str(exc), finished=timestamp()))
                raise
